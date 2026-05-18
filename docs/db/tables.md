# Schéma de base — agflow.docker

Inventaire des **39 tables** déclarées dans `backend/migrations/001_init.sql`
(consolidation des 86 migrations historiques, mai 2026).

Organisation par module fonctionnel. Pour chaque table : rôle, colonnes clés,
relations principales, **lecteurs** (FROM/JOIN) et **écrivains** (INSERT/UPDATE/DELETE).

> **Note de lecture** : "template" = entité de configuration créée par
> l'administrateur et réutilisable. "Instance" / "matérialisation" = état
> d'exécution dérivé d'un template, à durée de vie liée à un déploiement.
>
> Les chemins sont relatifs à `backend/src/agflow/`. Les `tests/` sont
> volontairement omis de la cartographie : seuls les consommateurs runtime
> sont listés.

---

## Glossaire conceptuel

Le mot "projet" est utilisé pour deux choses différentes dans l'écosystème
agflow.docker ↔ ag.flow. Ce glossaire fige le vocabulaire interne.

| Côté DB / interne | Côté UI utilisateur | Côté contrat v5 (figé) | Sens |
|---|---|---|---|
| `projects` | **ressource projet** / "recette" | `project` | Blueprint / template d'une stack de produits, créé par l'admin Docker. Lecture seule pour ag.flow. |
| `groups` | (sous-élément de la recette) | — | Regroupement de produits paramétrés au sein d'une ressource projet. |
| `instances` | (paramétrage produit dans la recette) | — | Une instance d'un produit (du catalogue YAML) déclarée dans un group d'une ressource projet. |
| `project_runtimes` | **instance projet** | `project_runtime` | Lancement effectif d'une ressource projet, créé quand un utilisateur instancie sa recette dans son projet. |
| `project_group_runtimes` | (matérialisation par-group du runtime) | — | Une row par (instance projet × group) avec le compose rendu et le push SSH. |
| `sessions` | "session" (dans un projet utilisateur) | `session` | Wrapper d'exécution rattaché à une instance projet, héberge des agents. |
| `agents_instances` | "agent" (travaille dans la session) | `agent` | Container d'agent instancié dans une session. |

**Flux utilisateur** :
1. Admin Docker crée une **ressource projet** (recette) dans agflow.docker.
2. Côté ag.flow, un utilisateur crée son projet utilisateur.
3. L'utilisateur **choisit des ressources projet** dans le catalogue Docker
   et les **lance** → ag.flow appelle `POST /api/admin/projects/{id}/runtimes`
   et obtient des **instances projet** (`project_runtimes`).
4. Pour exécuter du travail, ag.flow ouvre une **session** liée à une instance
   projet, instancie des **agents** dans cette session, et leur soumet du
   `work`.
5. Les agents accèdent aux resources rendues de l'instance projet (MCP +
   connection_params).

**Pourquoi ce vocabulaire interne diverge du contrat externe** : le contrat
v5 a été figé avec ag.flow en parlant de `project` (= ce qu'on appelle
ressource projet en interne). On garde ce mot dans le contrat (pas de v6)
mais on utilise "ressource projet" dans l'UI et la documentation interne
pour éviter la collision avec le concept "projet utilisateur" côté ag.flow.

---

## 1. Auth & utilisateurs

### `users`
**Rôle** : utilisateurs de la plateforme (humains) — Keycloak SSO + fallback local.

| Colonne clé | Sens |
|---|---|
| `email` (UNIQUE) | Identité primaire |
| `role` | `admin` / `user` / `operator` / `viewer` |
| `scopes` (text[]) | Scopes additionnels au rôle |
| `status` | `pending` / `active` / `disabled` (workflow d'approbation manuel) |
| `approved_at`, `approved_by` | Audit approbation |

**Écriture** :
- `services/users_service.py` — INSERT, UPDATE generic, UPDATE status (disable/activate), DELETE
- `api/admin/auth.py` — UPDATE `avatar_url` et `last_login` au login OIDC (Google + Keycloak)

**Lecture** :
- `services/users_service.py` — SELECT (list, by_id) avec sous-requête `COUNT(api_keys)`
- `services/project_runtimes_service.py` — LEFT JOIN `users` pour exposer le propriétaire d'un runtime SaaS

---

### `user_identities`
**Rôle** : mapping IdP externe → user local. Une row par couple `(provider, subject)`.

| Colonne clé | Sens |
|---|---|
| `user_id` (FK users) | User local |
| `provider` | `keycloak`, `google`, etc. |
| `subject` | ID stable côté IdP |
| `raw_claims` (jsonb) | Claims OIDC archivés |

**Écriture** :
- `api/admin/auth.py` — INSERT lors du link OIDC (Google + Keycloak)

**Lecture** :
- `api/admin/auth.py` — SELECT `user_id` par `(provider, subject)` au login

---

### `api_keys`
**Rôle** : clés API longue durée pour accès M2M (workflow ag.flow) et accès UI scoped.

| Colonne clé | Sens |
|---|---|
| `owner_id` (FK users, nullable) | NULL = clé système |
| `prefix` (UNIQUE), `key_hash` | bcrypt + prefix pour lookup rapide |
| `scopes` (text[]) | Ex: `m2m:orchestrate` pour workflow ag.flow |
| `rate_limit`, `expires_at`, `revoked` | Contrôle d'accès |

**Écriture** :
- `services/api_keys_service.py` — INSERT, UPDATE generic, UPDATE `revoked=TRUE`, UPDATE `last_used_at`

**Lecture** :
- `services/api_keys_service.py` — SELECT par owner, by_id, by_prefix (lookup auth)
- `services/users_service.py` — sous-requête `COUNT(api_keys)` agrégée à la liste users

---

### `platform_config`
**Rôle** : key-value pour configuration globale (toggles, URLs, paramètres ops).

**Écriture** :
- `services/platform_config_service.py` — INSERT (UPSERT via `ON CONFLICT`)

**Lecture** :
- `services/platform_config_service.py` — SELECT `value` par clé, SELECT all

---

### `rate_limit_counters`
**Rôle** : compteurs sliding-window pour rate limiting des `api_keys`.
PRIMARY KEY composite `(key, window_start)` — agrégation par minute.

**Écriture** :
- `auth/api_key.py` — INSERT compteur (avec UPSERT incrémental)

**Lecture** : pas de SELECT direct (UPSERT seul, lecture intégrée à l'incrément).

---

## 2. M1 — Dockerfiles & containers

### `dockerfiles`
**Rôle** : template Dockerfile + métadonnées. ID = slug stable (`text PK`).

| Colonne clé | Sens |
|---|---|
| `id` (text PK) | Slug stable (ex: `claude-code`, `aider`) |
| `parameters` (jsonb) | Variables d'env attendues à l'instanciation |

**Écriture** :
- `services/dockerfiles_service.py` — INSERT, UPDATE, DELETE

**Lecture** :
- `services/dockerfiles_service.py` — SELECT (list, by_id)

---

### `dockerfile_builds`
**Rôle** : historique des builds (streaming aiodocker). Une row par tentative.

| Colonne clé | Sens |
|---|---|
| `dockerfile_id` (FK) | Dockerfile concerné |
| `content_hash` | Hash du Dockerfile au moment du build (cache) |
| `image_tag` | Tag Docker résultant |
| `status` | `pending` / `running` / `success` / `failed` |
| `logs` | Logs build complets (text) |

**Écriture** :
- `services/build_service.py` — INSERT, UPDATE `logs` (append), UPDATE `status`/`finished_at`, DELETE des builds périmés (rotation)

**Lecture** :
- `services/build_service.py` — SELECT latest par dockerfile_id, by_id, lookup par `content_hash` (cache hit)

---

### `launched_tasks`
**Rôle** : containers lancés à la demande depuis un Dockerfile (M1, mode "test container").
Distinct des `agents_instances` qui sont créés en session.

| Colonne clé | Sens |
|---|---|
| `dockerfile_id` (FK) | Source |
| `container_id`, `container_name` | Docker runtime |
| `instruction` | Prompt initial passé au container |
| `status` | `pending` / `running` / `success` / `failure` / `stopped` / `error` |
| `exit_code` | Code de sortie |

**Écriture** :
- `services/launched_service.py` — INSERT, UPDATE × 3 (status, exit_code, container_id)

**Lecture** :
- `services/launched_service.py` — SELECT (list, by_id)

---

## 3. M2 — Rôles

### `roles`
**Rôle** : entité Rôle (référence par id slug). Squelette minimal — le contenu
est porté par `role_sections` et par le filesystem (`role_files_service`).

**Écriture** :
- `services/roles_service.py` — INSERT, UPDATE `updated_at`, DELETE

**Lecture** :
- `services/roles_service.py` — SELECT × 5 (list, by_id, plusieurs variantes)
- `services/service_types_service.py` — SELECT `COUNT(*) WHERE $1 = ANY(service_types)` pour valider qu'un type n'est pas utilisé avant suppression
- `services/role_files_service.py` — SELECT `identity_md, prompt_orchestrator_md` (colonnes spécifiques)

---

### `role_sections`
**Rôle** : sections d'un rôle (ROLES / MISSIONS / COMPETENCES / etc.).
PK composite `(role_id, name)`.

| Colonne clé | Sens |
|---|---|
| `role_id` (FK roles) | Parent |
| `name` | Slug section |
| `display_name` | Label UI |
| `is_native` | Sections built-in (non-supprimables) |
| `position` | Ordre d'affichage |

**Écriture** :
- `services/role_sections_service.py` — INSERT × 2 (upsert + bulk), DELETE

**Lecture** :
- `services/role_sections_service.py` — SELECT (list par role_id, by name)

---

## 4. M3 — Catalogues MCP, Skills, Discovery

### `discovery_services`
**Rôle** : registres externes (ex: `https://mcp.yoops.org/api/v1`) d'où on
installe MCP et Skills.

| Colonne clé | Sens |
|---|---|
| `id` (text PK) | Slug du registre |
| `base_url` | URL API |
| `api_key_var` | Nom de la variable d'env contenant la clé d'accès |
| `enabled` | Toggle |

**Écriture** :
- `services/discovery_services_service.py` — INSERT, UPDATE, DELETE

**Lecture** :
- `services/discovery_services_service.py` — SELECT (list, by_id)

---

### `mcp_servers`
**Rôle** : catalogue des MCP installés depuis les `discovery_services`.

| Colonne clé | Sens |
|---|---|
| `discovery_service_id` (FK) | Registre source |
| `package_id` | ID du paquet côté registre |
| `transport` | `stdio` / `sse` / `docker` |
| `parameters` (jsonb) | Valeurs par défaut |
| `parameters_schema` (jsonb) | Schéma JSON des params |
| `recipes` (jsonb) | Préréglages pour installation rapide |
| `category` | Catégorie pour filtrage UI |

UNIQUE `(discovery_service_id, package_id)`.

**Écriture** :
- `services/mcp_catalog_service.py` — INSERT, UPDATE `parameters`, DELETE

**Lecture** :
- `services/mcp_catalog_service.py` — SELECT (list, by_id)

---

### `skills`
**Rôle** : catalogue des skills installés (markdown content + metadata).

| Colonne clé | Sens |
|---|---|
| `discovery_service_id` (FK) | Registre source |
| `skill_id` | ID côté registre |
| `content_md` | Contenu markdown du skill |

UNIQUE `(discovery_service_id, skill_id)`.

**Écriture** :
- `services/skills_catalog_service.py` — INSERT, DELETE

**Lecture** :
- `services/skills_catalog_service.py` — SELECT (list, by_id)

---

## 5. M4 — Agents (composition)

### `agents_catalog`
**Rôle** : catalogue des agents disponibles. Table légère (slug + last_seen)
qui sert principalement de référentiel ENUM par FK.

| Colonne clé | Sens |
|---|---|
| `slug` (text PK) | Identifiant agent |
| `last_seen` | Dernière fois où l'agent a été référencé |

**Écriture** :
- `services/agents_catalog_service.py` — INSERT (upsert `ON CONFLICT DO NOTHING`), DELETE

**Lecture** : pas de SELECT direct repéré côté Python — la table sert principalement de référentiel FK.

> **Note** : le détail métier (rôle, MCP bindings, skills, profiles) est stocké
> dans le filesystem `/app/data/agents/<slug>/` géré par `agents_service.py`,
> pas dans la DB.

---

### `agent_api_contracts`
**Rôle** : contrats OpenAPI custom attachés à un agent (en plus des MCP).
Permet à un agent de "consommer" une API REST.

| Colonne clé | Sens |
|---|---|
| `agent_id` (FK agents_catalog.slug) | Agent destinataire |
| `slug` | Slug du contrat (unique par agent) |
| `source_type` | `upload` / `url` / `manual` |
| `spec_content` | OpenAPI YAML/JSON brut |
| `base_url`, `auth_header`, `auth_prefix`, `auth_secret_ref` | Config runtime |
| `parsed_tags`, `tag_overrides` | Filtrage / customisation tags OpenAPI |
| `managed_by_instance` (uuid) | Si lié à une instance product, FK indirecte |
| `runtime_base_url` | URL effective injectée au runtime |
| `output_dir` | Où l'agent écrit les contrats générés |

UNIQUE `(agent_id, slug)`.

**Écriture** :
- `services/api_contracts_service.py` — INSERT, UPDATE generic, UPDATE `spec_content`, UPDATE `position`, DELETE

**Lecture** :
- `services/api_contracts_service.py` — SELECT (summary list, detail, by_id)

---

## 6. M5 — API publique (Sessions, Agents en session, MOM)

### `sessions`
**Rôle** : wrapper d'exécution qui héberge ≥1 agent. Pivot M5.

| Colonne clé | Sens |
|---|---|
| `api_key_id` (FK api_keys) | Clé qui a créé la session |
| `status` | `active` / `closed` / `expired` |
| `expires_at`, `closed_at` | Cycle de vie |
| `project_id` (text, **pas FK**) | Lien optionnel vers un projet (historique) |
| `project_runtime_id` (FK project_runtimes) | Lien optionnel vers un runtime (workflow v5) |
| `callback_url`, `callback_hmac_key_id` | Callback HMAC pour hooks workflow (v5) |

**Écriture** :
- `services/sessions_service.py` — INSERT + UPDATE × 5 (close, refresh, expire, etc.)
- `api/admin/workflow_sessions.py` — UPDATE callback_url + callback_hmac_key_id + project_runtime_id à la création workflow
- `workers/session_idle_reaper.py` — UPDATE status='expired' quand inactivité dépasse seuil

**Lecture** :
- `services/sessions_service.py` — SELECT × 4 (by_id, by_api_key, list, list_by_api_key, JOIN agents_instances)
- `api/admin/workflow_sessions.py` — SELECT `status` (DELETE check), SELECT `project_runtime_id` (fusion MCP)
- `api/public/sessions.py` — SELECT pour endpoints UI publics
- `api/admin/supervision.py` — SELECT `status COUNT(*) GROUP BY status` (KPI)

---

### `agents_instances`
**Rôle** : instance d'un agent dans une session — c'est le container Docker
qui tourne (ou a tourné).

| Colonne clé | Sens |
|---|---|
| `session_id` (FK sessions) | Session parente |
| `agent_id` (FK agents_catalog.slug) | Quel agent du catalogue |
| `mission` (text) | Contexte long-terme |
| `labels` (jsonb) | Metadata libre |
| `last_container_name` | Nom du container Docker actuel |
| `status` | `idle` / `busy` / `error` / `destroyed` |
| `mcp_bindings_injected` (jsonb) | MCP injectés à l'instanciation (incluant ceux du runtime workflow v5) |
| `destroyed_at`, `last_activity_at` | Timestamps |

**Écriture** :
- `services/agents_instances_service.py` — INSERT, UPDATE × 4 (status, mission, container_name, generic)
- `mom/publisher.py` — UPDATE `last_activity_at` + status='busy' sur publish d'instruction
- `mom/consumer.py` — UPDATE status (ack/error)
- `workers/docker_reconciler.py` — UPDATE `last_container_name` après réconciliation Docker
- `workers/agent_reaper.py` — UPDATE `destroyed_at` sur expiration
- `api/admin/workflow_sessions.py` — UPDATE `mcp_bindings_injected` (fusion runtime workflow)

**Lecture** :
- `services/agents_instances_service.py` — SELECT × 4 (list, by_id, by_session, container_name)
- `api/public/messages.py` — SELECT `id FROM agents_instances` (lookup avant publish)
- `api/admin/supervision.py` — SELECT `status COUNT(*) GROUP BY status`, SELECT destroyed count
- `workers/session_idle_reaper.py` — SELECT EXISTS pour détecter sessions sans agent actif
- `workers/docker_reconciler.py` — SELECT toutes les instances non-destroyed pour réconciliation

---

### `agent_messages`
**Rôle** : bus MOM (Postgres-backed). Tous les messages échangés entre
ag.flow / API ↔ agents.

| Colonne clé | Sens |
|---|---|
| `msg_id` (PK) | UUID v4 |
| `parent_msg_id` | Chaînage conversationnel |
| `session_id`, `instance_id` | Routage (text — pas FK strict pour souplesse) |
| `direction` | `in` (vers l'agent) / `out` (depuis l'agent) |
| `kind` | `instruction` / `cancel` / `event` / `result` / `error` |
| `payload` (jsonb) | Contenu métier |
| `route` (jsonb) | Métadonnées de routage |
| `source` | Origine logique du message |
| `v` | Version d'envelope |

**Écriture** :
- `mom/publisher.py` — INSERT (un message à chaque publication, IN ou OUT)

**Lecture** :
- `mom/consumer.py` — SELECT × 2 (fetch new, fetch claimable avec JOIN delivery)
- `services/agent_messages_service.py` — SELECT historique (filtres divers)
- `api/public/messages.py` — SELECT timeline pour UI session
- `api/public/sessions.py` — SELECT × 3 (différents filtres direction/kind)
- `api/admin/supervision.py` — JOIN avec `agent_message_delivery` pour debug

---

### `agent_message_delivery`
**Rôle** : tracking de la livraison MOM par consumer group (pattern Redis-streams
porté sur Postgres). Chaque consumer group "claim" un message, l'acquitte ou échoue.

| Colonne clé | Sens |
|---|---|
| `group_name`, `msg_id` (PK composite) | Couple consumer + message |
| `status` | `pending` / `claimed` / `acked` / `failed` |
| `claimed_by`, `claimed_at`, `acked_at` | Audit |
| `retry_count`, `last_error` | Robustesse |

**Écriture** :
- `mom/publisher.py` — INSERT row 'pending' pour chaque consumer group au moment du publish
- `mom/consumer.py` — UPDATE × 3 (claim, ack, fail/retry)

**Lecture** :
- `mom/consumer.py` — SELECT FOR UPDATE SKIP LOCKED via JOIN agent_messages (claim atomique)
- `api/admin/supervision.py` — SELECT `status COUNT(*) GROUP BY status`, JOIN avec agent_messages

---

## 7. M7 — Product Registry, Projets, Runtimes

### `projects`
**Rôle** : **template** d'un projet (blueprint). Lecture seule depuis ag.flow.

| Colonne clé | Sens |
|---|---|
| `display_name` | Nom utilisateur |
| `tags` (jsonb) | Tags libres |
| `network` | Nom du réseau Docker partagé (`agflow` par défaut) |

**Écriture** :
- `services/projects_service.py` — INSERT, UPDATE, DELETE

**Lecture** :
- `services/projects_service.py` — SELECT × 2 (list, by_id) avec LEFT JOIN count(groups)
- `services/workflow_provisioning_service.py` — SELECT `id` (validation existence avant provisioning)

---

### `groups`
**Rôle** : **template** d'un groupe à l'intérieur d'un projet. Contient un
sous-ensemble d'instances. Pivot du compose : un compose Docker est rendu par
group.

| Colonne clé | Sens |
|---|---|
| `project_id` (FK projects) | Parent |
| `name` | Nom unique dans le projet |
| `max_agents` | Limite d'agents simultanés |
| `machine_id` (FK infra_machines, nullable) | Cible de déploiement par défaut |
| `compose_template_slug` | Template Jinja pour le rendu du compose |
| `max_replicas` | Nombre max de replicas dans un runtime |

UNIQUE `(project_id, name)`.

**Écriture** :
- `services/groups_service.py` — INSERT, UPDATE, DELETE

**Lecture** :
- `services/groups_service.py` — SELECT avec LEFT JOIN count(instances)
- `services/project_runtimes_service.py` — SELECT `id, max_replicas` + JOIN dans plusieurs queries de rendering
- `services/workflow_provisioning_service.py` — JOIN dans `get_resources`
- `api/admin/workflow_sessions.py` — JOIN pour fusion MCP runtime workflow
- `services/compose_renderer_service.py` — JOIN dans rendu compose
- `services/product_instances_service.py` — JOIN pour `list_by_project`
- `services/group_scripts_service.py` — JOIN pour résoudre le contexte
- `services/projects_service.py` — sous-requête count agrégée à la liste projets

---

### `instances`
**Rôle** : **template** d'une instance (déclaration d'un composant du
catalogue produit dans un groupe d'un projet). C'est la *recette* — pas la
matérialisation runtime.

| Colonne clé | Sens |
|---|---|
| `group_id` (FK groups) | Group parent (qui appartient à un projet) |
| `instance_name` | Nom unique dans le group |
| `catalog_id` | Référence au catalogue produit YAML (filesystem) |
| `variables` (jsonb), `variable_statuses` (jsonb) | Variables Jinja + statut 🔴🟠🟢 |
| `connection_params` (jsonb) | Paramètres d'accès (peuvent contenir des variables Jinja non rendues) |
| `mcp_bindings` (jsonb) | MCP exposés par cette instance |
| `setup_steps` (jsonb) | Étapes manuelles de configuration |
| `provisioning_status` | `provisioning` / `ready` / `pending_setup` / `failed` |
| `status` | `draft` / `active` / `stopped` (statut éditorial du template) |
| `service_url` | URL d'accès si applicable |

UNIQUE `(group_id, instance_name)`.

**Service principal** : `product_instances_service.py` (attention : nom du service ≠ nom de table — cf. memory `feedback_table_name_vs_service_name`).

**Écriture** :
- `services/product_instances_service.py` — INSERT, UPDATE × 3 (variables generic, status+service_url, status only), DELETE

**Lecture** :
- `services/product_instances_service.py` — SELECT × 4 (all, by_id, by_group, by_project avec JOIN groups)
- `services/workflow_provisioning_service.py` — JOIN dans `get_resources` (template lu pour exposer au contrat v5)
- `api/admin/workflow_sessions.py` — JOIN avec `groups` + `project_runtimes` pour collecte `mcp_bindings` (fusion MCP runtime workflow)
- `services/groups_service.py` — sous-requête `COUNT(*)` agrégée

> **Question ouverte tranche 2** : ces colonnes (`connection_params`,
> `mcp_bindings`, `setup_steps`, `provisioning_status`) sont aujourd'hui
> portées par le **template**, partagées entre tous les runtimes du projet.
> Le contrat v5 demande une vue par-runtime. À résoudre.

---

### `project_runtimes`
**Rôle** : **instance déployée** d'un projet. Une row par déploiement effectif.
Créée par M7 Phase 1 SaaS (mode user) et par workflow ag.flow (mode m2m, `user_id NULL`).

| Colonne clé | Sens |
|---|---|
| `project_id` (FK projects) | Template parent |
| `deployment_id` (FK project_deployments, nullable) | Lien vers ancien système (legacy) |
| `user_id` (FK users, nullable) | NULL = workflow m2m / NOT NULL = SaaS user |
| `status` | `pending` / `deployed` / `failed` |
| `pushed_at`, `error_message` | Audit déploiement |
| `seq` | Sequence pour ordering |
| `deleted_at` | Soft-delete |

**Écriture** :
- `services/project_runtimes_service.py` — INSERT × 2 (V1 et SaaS Phase 1), UPDATE status, UPDATE `deleted_at` (soft-delete)
- `services/workflow_provisioning_service.py` — INSERT + UPDATE `status='deployed'` (sync simulé tranche 1)

**Lecture** :
- `services/project_runtimes_service.py` — SELECT × 3 (list, by_id, list_by_user) avec LEFT JOIN users
- `services/workflow_provisioning_service.py` — SELECT `project_id` (résolution avant `get_resources`)
- `api/admin/workflow_runtimes.py` — SELECT `status` (endpoint GET /resources)
- `api/admin/workflow_sessions.py` — SELECT `id` (validation existence avant POST /sessions)
- `api/public/runtimes.py` — SELECT × 3 (UI publique SaaS)
- `services/compose_renderer_service.py` — SELECT `project_id`

---

### `project_group_runtimes`
**Rôle** : matérialisation **par-(runtime × group)**. Une row par couple
runtime × group, qui contient le compose_yaml rendu et l'état du push SSH vers
la machine cible.

| Colonne clé | Sens |
|---|---|
| `project_runtime_id` (FK project_runtimes) | Runtime parent |
| `group_id` (FK groups) | Group concerné |
| `machine_id` (FK infra_machines, nullable) | Machine effective de déploiement |
| `env_text`, `compose_yaml`, `remote_path` | Artefacts rendus |
| `status` | `pending` / `deployed` / `failed` |
| `replica_count` | Nombre de replicas pour ce group dans ce runtime |
| `seq` | Sequence pour ordering |
| `deleted_at` | Soft-delete |

UNIQUE `(project_runtime_id, group_id)`.

**Écriture** :
- `services/project_runtimes_service.py` — INSERT × 2 (par groupe lors du provisioning), UPDATE × 2 (compose/env render + push status), UPDATE `deleted_at`

**Lecture** :
- `services/project_runtimes_service.py` — SELECT × 3 avec JOIN groups + LEFT JOIN infra_machines
- `services/compose_renderer_service.py` — JOIN dans le rendu compose
- `api/public/runtimes.py` — SELECT × 2 (UI publique)

> **Pivot conceptuel important** : on a aujourd'hui une matérialisation runtime
> **par group**, pas **par instance**. Les `instances` individuelles ne sont
> matérialisées qu'à travers leur appartenance à un group rendu dans
> `compose_yaml`.

---

### `project_deployments` (legacy)
**Rôle** : ancien système de déploiement (pré-M7 Phase 1 SaaS Runtimes). Toujours
en place pour compat. Contient le compose + env générés par projet et par
utilisateur.

| Colonne clé | Sens |
|---|---|
| `project_id` (FK projects) | Projet déployé |
| `user_id` (FK users) | Propriétaire |
| `group_servers` (jsonb) | Mapping group → machine |
| `status` | `draft` / `generated` / `deployed` |
| `generated_compose`, `generated_env`, `generated_secrets`, `generated_data` | Artefacts |
| `nullable_secrets` (jsonb) | Secrets optionnels |

**Écriture** :
- `services/project_deployments_service.py` — INSERT, UPDATE generic, UPDATE `group_servers`, DELETE
- `api/admin/project_deployments.py` — UPDATE `status='deployed'` après push

**Lecture** :
- `services/project_deployments_service.py` — SELECT × 3 (by_project, by_user, by_id)
- `api/admin/product_instances.py` — JOIN avec `deployment_instances` pour lister les déploiements d'une instance

---

### `deployment_instances` (legacy)
**Rôle** : jointure historique (deployment × instance × machine). Lié à
l'ancien `project_deployments`.

| Colonne clé | Sens |
|---|---|
| `deployment_id`, `instance_id` | FK |
| `machine_id` (nullable) | Machine effective |
| `success`, `error_message` | Résultat |

**Écriture** :
- `api/admin/project_deployments.py` — INSERT au moment du push

**Lecture** :
- `api/admin/product_instances.py` — SELECT et JOIN avec `project_deployments` pour l'historique d'une instance

---

## 8. M8 — Infrastructure (machines, certificats, scripts)

### `infra_categories`
**Rôle** : catégories de machines (VPS, LXC, BARE_METAL, etc.).

| Colonne clé | Sens |
|---|---|
| `name` (PK) | Slug |
| `is_vps` | Flag (impacte la gestion réseau / SSH) |

**Écriture** :
- `api/infra/categories.py` — INSERT, UPDATE `visible_in_machines`, DELETE

**Lecture** :
- `api/infra/categories.py` — SELECT (list, by_name)

> **Note feedback memory** : ne **jamais** créer/modifier les `infra_*_types` /
> `infra_categories` programmatiquement (cf. `feedback_no_touch_infra_types`).

---

### `infra_category_actions`
**Rôle** : actions définissables pour une catégorie (ex: `install_docker`,
`reboot`, `update_packages`).

| Colonne clé | Sens |
|---|---|
| `category` (FK infra_categories) | Catégorie |
| `name` | Slug action |
| `is_required` | Flag obligatoire ou optionnel |

UNIQUE `(category, name)`.

**Écriture** :
- `api/infra/categories.py` — INSERT, UPDATE generic, DELETE

**Lecture** :
- `api/infra/categories.py` — SELECT (list par catégorie)
- `services/infra_machines_service.py` — JOIN dans la query principale de listing
- `services/infra_machines_runs_service.py` — JOIN pour résoudre le nom de l'action
- `services/infra_named_type_actions_service.py` — JOIN pour résoudre l'action

---

### `infra_named_types`
**Rôle** : type nommé d'une machine (ex: "Ubuntu 22.04 LXC Proxmox").
Combine `connection_type` + `type_id` (string) + parent éventuel (`sub_type_id`).

| Colonne clé | Sens |
|---|---|
| `connection_type` | Mode connexion (`ssh`, `docker`, `k3s`, …) |
| `type_id` | Slug du type |
| `name` | Nom affichable |
| `sub_type_id` (uuid nullable) | Type parent éventuel |

**Écriture** :
- `services/infra_named_types_service.py` — INSERT, UPDATE, DELETE

**Lecture** :
- `services/infra_named_types_service.py` — SELECT avec LEFT JOIN self pour exposer le parent
- `services/infra_machines_service.py` — JOIN dans la query principale (résoudre le type d'une machine)
- `services/scripts_service.py` — LEFT JOIN dans `_FROM_JOIN` pour exposer le type cible d'un script

---

### `infra_named_type_actions`
**Rôle** : URL/script associé à une couple (named_type × category_action).
Permet d'exécuter une action standard sur une machine d'un type donné.

UNIQUE `(named_type_id, category_action_id)`.

**Écriture** :
- `services/infra_named_type_actions_service.py` — INSERT, UPDATE generic, DELETE

**Lecture** :
- `services/infra_named_type_actions_service.py` — SELECT avec JOIN infra_category_actions
- `services/infra_machines_service.py` — JOIN avec `infra_machines_runs` pour exposer "dernière exécution" par action

---

### `infra_certificates`
**Rôle** : certificats SSH (clés privées + publiques) chiffrés au repos avec
Fernet (clé `AGFLOW_INFRA_KEY`, en cours de migration Harpocrate).

| Colonne clé | Sens |
|---|---|
| `name` | Label |
| `private_key`, `public_key`, `passphrase` | Chiffré |
| `key_type` | `rsa` / `ed25519` / etc. |

**Écriture** :
- `services/infra_certificates_service.py` — INSERT, UPDATE × 3 (private_key, passphrase, generic), DELETE

**Lecture** :
- `services/infra_certificates_service.py` — SELECT × 5 (variantes de colonnes : list, by_id, raw_keys, private+passphrase pour SSH)

---

### `infra_machines`
**Rôle** : serveurs cibles de déploiement.

| Colonne clé | Sens |
|---|---|
| `host`, `port` | Connexion |
| `username`, `password` | Auth (password en clair — cf. mémoire `project_vault_migration`) |
| `certificate_id` (FK infra_certificates, nullable) | Auth clé SSH |
| `type_id` (FK infra_named_types) | Type de la machine |
| `parent_id` (uuid nullable) | Hôte parent (LXC dans Proxmox) |
| `user_id` (FK users, nullable) | Propriétaire SaaS |
| `environment` (varchar(50)) | Tag d'environnement (dev/prod/...) |
| `status` | `not_initialized` / `online` / `offline` / etc. |
| `metadata` (jsonb) | Libre |

**Écriture** :
- `services/infra_machines_service.py` — INSERT, UPDATE × 5 (password, status, metadata, generic, password 2e variante), DELETE
- `services/swarm_actions_service.py` — UPDATE × 3 (jointure swarm_cluster_id et flags swarm)

**Lecture** :
- `services/infra_machines_service.py` — SELECT × 5 (list, by_id complet, by_id ssh-only, password-only)
- `services/swarm_actions_service.py` — SELECT FROM par id (avant push swarm)
- `services/infra_swarm_clusters_service.py` — LEFT JOIN + COUNT(*) pour validation cluster
- `services/group_scripts_service.py` — JOIN pour résoudre la machine d'un script
- `services/project_runtimes_service.py` — LEFT JOIN (via `project_group_runtimes`)

---

### `infra_machines_runs`
**Rôle** : historique des actions exécutées sur les machines (un peu comme
`dockerfile_builds` mais pour les scripts infra).

| Colonne clé | Sens |
|---|---|
| `machine_id` (FK), `action_id` (FK infra_category_actions) | Quoi sur quoi |
| `success`, `exit_code`, `error_message` | Résultat |
| `started_at`, `finished_at` | Timestamps |

**Écriture** :
- `services/infra_machines_runs_service.py` — INSERT, UPDATE (finish)

**Lecture** :
- `services/infra_machines_runs_service.py` — SELECT avec JOIN infra_named_type_actions + infra_category_actions
- `services/infra_machines_service.py` — JOIN dans aggregate query "dernière exécution par action"

---

### `service_types`
**Rôle** : types de services métier (BACKEND, DATABASE, FRONTEND, etc.).
Utilisés notamment par les `roles` (colonne `service_types text[]` côté roles).

| Colonne clé | Sens |
|---|---|
| `name` (PK) | Slug |
| `display_name` | Label UI |
| `is_native` | Built-in non-supprimable |
| `position` | Ordre d'affichage |

**Écriture** :
- `services/service_types_service.py` — INSERT, DELETE

**Lecture** :
- `services/service_types_service.py` — SELECT × 4 (list, by_name, exists set, validation pré-delete via JOIN logique sur roles)

---

### `scripts`
**Rôle** : scripts shell réutilisables (M8 — exécution streamée WebSocket).

| Colonne clé | Sens |
|---|---|
| `name` (UNIQUE) | Slug |
| `content` | Code shell |
| `execute_on_types_named` (uuid nullable, FK infra_named_types) | Type machine cible par défaut |
| `input_variables` (jsonb) | Schéma des variables d'entrée |

**Écriture** :
- `services/scripts_service.py` — INSERT, UPDATE, DELETE

**Lecture** :
- `services/scripts_service.py` — SELECT avec LEFT JOIN infra_named_types (constante `_FROM_JOIN`)
- `services/group_scripts_service.py` — JOIN pour résoudre le script attaché à un group

---

### `group_scripts`
**Rôle** : binding d'un script à un group (avec timing `before` / `after`
le déploiement). Permet d'attacher hooks de pré/post-déploiement.

| Colonne clé | Sens |
|---|---|
| `group_id` (FK), `script_id` (FK), `machine_id` (FK) | Liaison N×N×1 |
| `timing` | `before` / `after` |
| `position` | Ordre d'exécution |
| `env_mapping`, `input_values`, `input_statuses` | Variables d'env / inputs / statut 🔴🟠🟢 |
| `trigger_rules` (jsonb) | Conditions de déclenchement |

**Écriture** :
- `services/group_scripts_service.py` — INSERT, UPDATE generic, DELETE

**Lecture** :
- `services/group_scripts_service.py` — SELECT avec JOIN × 3 (scripts, infra_machines, groups)

---

## 9. Workflow Contracts v5 (tranche 1 livrée)

### `hmac_keys`
**Rôle** : clés HMAC partagées pour signer/vérifier les hooks sortants vers ag.flow.
Le secret est chiffré au repos (Fernet via `harpocrate_dek`).

| Colonne clé | Sens |
|---|---|
| `key_id` (UNIQUE varchar(64)) | Identifiant logique de la clé (porté par `sessions.callback_hmac_key_id`) |
| `key_value_encrypted` (bytea) | Secret hex chiffré |
| `description` | Libellé |
| `rotated_at` | Marque la clé comme rotated (non-active si NOT NULL) |

**Écriture** :
- `services/hmac_keys_service.py` — INSERT

**Lecture** :
- `services/hmac_keys_service.py` — SELECT (by_key_id retournant secret déchiffré, exists pour validation)

---

### `tasks`
**Rôle** : pivot d'asynchronisme. Toute opération workflow async crée une row
ici, dont le `id` devient le `task_id` retourné à ag.flow.

| Colonne clé | Sens |
|---|---|
| `kind` | `runtime_provision` / `session_create` / `agent_create` / `session_work` |
| `project_runtime_id` (FK, nullable) | Runtime associé si applicable |
| `session_id` (FK sessions, nullable) | Session associée |
| `agent_instance_id` (FK agents_instances, nullable) | Agent destinataire (pour `session_work`) |
| `status` | `pending` / `running` / `completed` / `failed` / `cancelled` |
| `result` (jsonb), `error` (jsonb) | Sortie finale (exclusifs selon status) |
| `agflow_action_execution_id` (uuid) | `_agflow_action_execution_id` envoyé par ag.flow |
| `agflow_correlation_id` (uuid) | `_agflow_correlation_id` pour traçabilité cross-service |
| `started_at`, `completed_at` | Cycle de vie |

**Écriture** :
- `services/tasks_service.py` — INSERT (`create_session_work`)

**Lecture** :
- `services/tasks_service.py` — SELECT × 2 (idempotence check sur (session_id, correlation_id), by_id)

> **Idempotence** : appliquée applicativement sur le couple `(session_id,
> agflow_correlation_id)` pour `kind=session_work`. Pas de UNIQUE constraint
> en DB.

> **À venir tranche 3** : UPDATE `status='completed'/'failed'` + `result`/`error`
> par le consumer MOM ou l'endpoint de complétion.

---

### `outbound_hooks`
**Rôle** : queue de hooks à émettre vers ag.flow. Le worker dispatcher de
tranche 3 lira `WHERE status='pending' AND next_retry_at <= NOW()`.

| Colonne clé | Sens |
|---|---|
| `hook_id` (UNIQUE) | UUID v4 propagé en header `X-Agflow-Hook-Id` (idempotence côté ag.flow) |
| `task_id` (FK tasks, nullable) | Task source du hook |
| `callback_url` | URL cible (snapshot de `sessions.callback_url` à l'émission) |
| `hmac_key_id` | Référence vers `hmac_keys.key_id` pour signature |
| `payload` (jsonb) | Body JSON à POSTer |
| `status` | `pending` / `delivered` / `dead` |
| `attempt_number`, `last_attempt_at`, `next_retry_at` | Retry exponentiel (1h max) |
| `last_response_code`, `error_message` | Diagnostic |

**Écriture** : aucun écrivain pour l'instant (tranche 3 — `hook_dispatcher_worker` à créer).

**Lecture** : aucun lecteur pour l'instant (tranche 3).

---

## 10. Récapitulatif par cycle de vie

### Tables "template" (configuration admin, longue durée)
- `projects`, `groups`, `instances` (déclaration produit dans projet)
- `dockerfiles`, `agents_catalog`, `agent_api_contracts`
- `roles`, `role_sections`
- `discovery_services`, `mcp_servers`, `skills`
- `service_types`, `infra_categories`, `infra_named_types`, `infra_category_actions`, `infra_named_type_actions`
- `infra_certificates`, `infra_machines`
- `scripts`, `group_scripts`
- `users`, `user_identities`, `api_keys`, `hmac_keys`
- `platform_config`

### Tables "instance/runtime" (état d'exécution, lié à un déploiement)
- `project_runtimes`, `project_group_runtimes` — déploiements projet
- `project_deployments`, `deployment_instances` — legacy déploiements
- `sessions`, `agents_instances` — runtime M5
- `dockerfile_builds`, `launched_tasks`, `infra_machines_runs` — historique d'exécution
- `tasks`, `outbound_hooks` — orchestration workflow async

### Tables "log/queue/journal"
- `agent_messages`, `agent_message_delivery` — bus MOM
- `rate_limit_counters` — métriques rate limiting

---

## 11. Le trou identifié pour la tranche 2 workflow

Aujourd'hui :
- `instances` porte les `connection_params`, `mcp_bindings`, `setup_steps`,
  `provisioning_status` **au niveau template** (partagés entre tous les
  runtimes du projet).
- `project_group_runtimes` matérialise par-(runtime × group) mais ne descend
  pas à la granularité instance individuelle.

Le contrat workflow v5 §3.4 exige une vue **par-(runtime × instance)** avec :
- `resource_id` UUID v4 stable par runtime
- `connection_params` rendus Jinja avec les vars du runtime
- `mcp_bindings` rendus
- `setup_steps` avec statut individuel par runtime
- `provisioning_status` propre au runtime

→ **Décision tranche 2 à prendre** : où loger cet état par-(runtime ×
instance) ? Trois options :

1. **Nouvelle table** `project_runtime_instances` (ou
   `project_runtime_resources`) dédiée à la matérialisation par-instance.
2. **Étendre `project_group_runtimes`** avec un JSONB `instance_states` qui
   contiendrait `[{instance_id, connection_params, mcp_bindings, setup_steps,
   status}]`. Évite une nouvelle table mais perd l'indexation native par
   resource_id.
3. **Cloner les rows `instances` par runtime** (option A discutée plus tôt) :
   ajouter `runtime_id` sur `instances`. Mélange template et matérialisation
   dans la même table.

À trancher avant de rédiger le plan tranche 2.
