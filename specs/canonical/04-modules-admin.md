# 04 — Modules d'administration

Le panneau d'administration est structuré en **huit modules** numérotés M0 à M7. Chaque module couvre une préoccupation distincte et expose un ensemble cohérent de pages frontend + routes `/api/admin/*`.

L'ordre des modules suit la dépendance logique : on configure les secrets (M0), puis les briques de base (M1-M3), puis on les compose en agents (M4), on s'occupe de la couche infra (M5), on déploie des projets (M6) et on supervise (M7).

---

## M0 — Secrets, coffres et configuration

**Rôle** : centraliser l'accès aux secrets et à la configuration sensible. C'est le point d'entrée de l'administrateur après l'installation, parce que tout le reste dépend de la disponibilité du coffre Harpocrate et des clés API des providers IA.

### Coffres Harpocrate

Pages : `HarpocrateVaultsPage`.

L'administrateur peut déclarer un ou plusieurs coffres Harpocrate (`harpocrate_vaults`). Pour chaque coffre :
- `name` : identifiant logique (ex: `prod`, `dev`).
- `base_url` : URL du service Harpocrate.
- `api_key` : clé d'accès (saisie à la création, stockée chiffrée localement via `harpocrate_dek`, **jamais retournée en clair** ensuite).
- `is_default` : un seul coffre porte ce flag à la fois. Les nouveaux secrets sont créés dans le coffre default sauf indication contraire.

Actions disponibles : créer, mettre à jour (rotation de clé), supprimer, marquer comme default, tester la connexion.

**Indicateurs visuels** : connexion OK / KO via badge coloré.

### Secrets plateforme

Pages : `PlatformSecretsPage`.

Deux types de secrets gérés via une seule UI :

- **Type `vault`** (`POST /api/admin/secrets/vault`) : le secret est stocké dans Harpocrate. La table `platform_secrets` ne contient que la clé canonique `${vault://api:NAME}` et un flag `default_value = 'set'`. L'administrateur révèle ponctuellement la valeur via `GET /api/admin/secrets/{id}/reveal`.
- **Type `env`** (`POST /api/admin/secrets/env`) : le secret est stocké en clair dans la colonne `default_value`. Utilisé pour les valeurs non sensibles (configuration, URLs, etc.).

**Statut visuel** : chaque variable d'environnement référencée ailleurs dans la plateforme est rendue avec un indicateur trois-couleurs :

| Couleur | Signification |
|---|---|
| 🔴 Rouge | Variable non déclarée |
| 🟠 Orange | Déclarée, valeur vide |
| 🟢 Vert | Déclarée, valeur renseignée |

Le composant frontend `StatusIndicator` rend ces badges, et l'endpoint `GET /api/admin/secrets/resolve-status?var_names=…` calcule le statut pour une liste de noms.

### Coffre utilisateur

Pages : `MySecretsPage` (visible par chaque utilisateur, pas seulement les admins).

Chaque utilisateur dispose d'un espace privé dans Harpocrate (sous le préfixe `user/{id}/`) qu'il peut peupler de secrets personnels. Ces secrets sont consommables par les sessions ouvertes par cet utilisateur (via le scope `user`).

### Configuration de l'authentification

Pages : `AuthConfigPage`.

Configure le mode d'authentification de l'UI (`local` ou `keycloak`), l'URL du Keycloak, le realm, le client_id, et le client_secret (poussé dans Harpocrate, jamais en base). Permet de tester la connexion via `POST /api/admin/auth-config/test`.

### Providers IA

Pages : `AiProvidersPage`.

Configure les providers IA (Anthropic, OpenAI, Mistral, Google, etc.) par **type de service** :
- `image_generation` : générateurs d'avatars (DALL-E 3, etc.).
- `embedding` : moteurs d'embeddings.
- `llm` : modèles de langage utilisés par les agents et par les fonctions IA internes (génération de Dockerfile, synthèse de rôle).

Chaque provider porte un `secret_ref` (référence Harpocrate vers la clé API), un flag `enabled`, et un flag `is_default` (un seul default par `service_type`).

---

## M1 — Dockerfiles et images d'agents

**Rôle** : gérer les Dockerfiles versionnés à partir desquels les images des conteneurs d'agents sont construites.

Pages : `DockerfilesPage`.

### Édition

Pour chaque dockerfile :
- Méta : `id` (slug unique), `display_name`, `description`, `parameters` (JSONB de config runtime).
- Arborescence de fichiers éditable en ligne (`Dockerfile`, `entrypoint.sh`, `Dockerfile.json`, et tout fichier auxiliaire). Encodage UTF-8 ou base64 selon le contenu.
- Import / export ZIP : un ZIP exporté contient tous les fichiers du répertoire, et l'import remplace transactionnellement le contenu après validation (présence des fichiers requis, JSON parseable, etc.).

### Génération assistée par IA

Endpoint : `POST /api/admin/dockerfiles/chat-generate`.

Permet de générer un `Dockerfile` + `entrypoint.sh` depuis une description en langage naturel. Appelle le provider LLM configuré dans M0. Le résultat est présenté à l'opérateur qui peut l'approuver puis créer un dockerfile officiel via le `POST` standard.

### Build

Endpoint : `POST /api/admin/dockerfiles/{id}/build`. Retourne immédiatement un `BuildSummary` en statut `pending` ; le `dockerfile_build_worker` consomme la file, fait tourner `aiodocker build`, persiste les logs et le tag final.

Le tag d'image est déterministe : `<dockerfile_id>:<content_hash>`. Le hash est calculé à partir du contenu de l'arborescence ; les rebuilds sont idempotents.

États affichés : `never_built`, `up_to_date`, `outdated`, `failed`, `building`, `image_missing`.

### Container runtime

Endpoints : `POST /api/admin/dockerfiles/{id}/run`, `GET /api/admin/containers`, `GET /api/admin/containers/{id}/logs`, `DELETE /api/admin/containers/{id}`.

Permet de lancer manuellement un container depuis un dockerfile pour test ou debug. Le runtime résout les secrets (`{KEY}` patterns dans `Dockerfile.json`), génère un `.env` et un `run.sh` dans `.tmp/`, et lance via `aiodocker`.

### One-shot task

Endpoints : `POST /api/admin/dockerfiles/{id}/task` et `POST /api/admin/agents/{slug}/task`. Lance un container, envoie une instruction JSON sur stdin, stream les événements newline-delimited JSON, supprime le container à la sortie.

---

## M2 — Rôles, sections, documents

**Rôle** : composer les personnalités des agents — leur identité, leurs missions, leurs compétences.

Pages : `RolesPage`, `RoleEditorPage`.

### Composition d'un rôle

Chaque rôle (`roles`) a :
- `id` (slug unique), `display_name`, `description`.
- `service_types` (array) : à quelles catégories de service ce rôle s'applique (Documentation, Code, etc.).
- `identity_md` : markdown racine décrivant l'identité du rôle.
- `sections` : sections natives (`roles`, `missions`, `competences`) ou personnalisées, ordonnées.
- `documents` : un ou plusieurs fichiers markdown attachés à chaque section.

Édition en ligne en markdown avec drag-and-drop pour réordonner sections et documents. Un document peut être marqué `protected` pour empêcher sa suppression.

### Import / export ZIP

Endpoint : `POST /api/admin/roles/{id}/import`, `GET /api/admin/roles/{id}/export`.

Le ZIP contient un `role.json` (méta + sections) et un fichier markdown par document. Permet de versionner les rôles en dehors de la plateforme.

### Génération du prompt orchestrateur

Endpoint : `POST /api/admin/roles/{id}/generate-prompts`.

Appelle Claude (provider configuré en M0) pour synthétiser tous les documents en un `prompt_orchestrator_md` injecté ensuite dans le system prompt des conteneurs d'agent. Le rôle persiste ce champ.

---

## M3 — Découverte, catalogue MCP, skills

**Rôle** : connecter la plateforme à des registres externes pour installer des MCP servers et des skills.

Pages : `DiscoveryServicesPage`, `McpCatalogPage`, `SkillsCatalogPage`.

### Services de découverte

Configure un ou plusieurs registres (`discovery_services`) :
- `id` (slug), `name`, `base_url`, `api_key_var` (référence à un secret M0 contenant la clé API).
- `enabled` : permet de désactiver temporairement un service.

Actions : tester la connectivité (`POST /api/admin/discovery-services/{id}/test`), rechercher des MCP (`GET .../search/mcp?q=…`), rechercher des skills (`GET .../search/skills?q=…`), obtenir une description multilingue (`GET .../summary/{package_id}?culture=fr`).

### MCP catalog

Installation depuis un registre : `POST /api/admin/mcp-catalog` avec `discovery_service_id`, `package_id`, `recipes`, `parameters`, `category`. La plateforme télécharge la définition, instancie un `mcp_servers` local avec ses paramètres et son schema de validation.

Pour chaque MCP installé : `name`, `repo`, `repo_url`, `transport` (`stdio` / `sse` / `docker` / `streamable-http`), `short_description`, `long_description`, `documentation_url`, `parameters_schema`, `recipes`.

Mise à jour des paramètres : `PUT /api/admin/mcp-catalog/{id}` avec nouveaux `parameters`. Le schema valide les types.

### Skills catalog

Installation : `POST /api/admin/skills-catalog` avec `discovery_service_id` + `skill_id`. La skill est téléchargée et stockée localement avec son `content_md`.

---

## M4 — Composition d'agents

**Rôle** : assembler dockerfile + rôle + bindings MCP / skills + templates pour produire des agents prêts à instancier.

Pages : `AgentsPage`, `AgentEditorPage`.

### Composition

Pour chaque agent (`agents`) :
- Identité : `slug` (unique), `display_name`, `description`.
- Briques : `dockerfile_id` (FK), `role_id` (FK).
- Environnement : `env_vars` (JSONB), `timeout_seconds`, `workspace_path`, `network_mode`, `graceful_shutdown_secs`, `force_kill_delay_secs`.
- Templates de génération (chacun avec un slug + une culture) :
  - `mcp_template_*` : rend la config MCP injectée dans le conteneur.
  - `skills_template_*` : rend le fichier `skills.md` injecté.
  - `prompt_template_*` : rend le system prompt principal.
- `generations` (JSONB) : blocs de génération additionnels, chacun lié à un rôle additionnel et produisant un prompt par mission profile.
- Bindings : `mcp_bindings` (liste avec position + parameters_override), `skill_bindings` (liste avec position).
- Mission profiles : sous-ensembles de documents du rôle, un par profil.
- Agent assistant : un seul agent peut porter le flag `is_assistant`, qui le désigne comme assistant général de la plateforme.

### Aperçu de configuration

Endpoint : `GET /api/admin/agents/{id}/config-preview?profile_id=…`.

Renvoie un `ConfigPreview` qui montre exactement ce qui serait injecté dans le conteneur à l'exécution : `prompt_md` final, `mcp_json` rendu, `tools_json` extrait des MCP, `env_file` complet, `skills` (liste avec contenu), `validation_errors` (variables non résolubles, MCP avec paramètres manquants, etc.), `image_status` (`missing` / `stale` / `fresh`).

### Génération des fichiers de runtime

Endpoint : `POST /api/admin/agents/{id}/generate?profile_id=…`. Génère réellement les fichiers dans le workspace de l'agent (sur disque, accessibles ensuite par le conteneur via mount). Le `GET /generated` liste les fichiers présents, le `DELETE /generated` les efface.

### Contrats API d'agent

Sous-pages dédiées (`AgentContractsPage`) : chaque agent peut porter une liste ordonnée de **contrats OpenAPI** (`agent_api_contracts`). Un contrat décrit une API externe que l'agent peut appeler — il est documenté pour l'agent dans son contexte (output_dir typiquement `workspace/docs/ctr/`).

Sources : upload, URL distante (rafraîchissable), ou contenu manuel. Le service parse les tags OpenAPI et propose des `tag_overrides` pour customiser leur description vue par l'agent.

### Import / export / duplication

- Export : `GET /api/admin/agents/{id}/export` → ZIP avec `agent.json` + `profiles/*.json`.
- Import : `POST /api/admin/agents/import` (multipart).
- Duplication : `POST /api/admin/agents/{id}/duplicate` avec nouveau `slug` + `display_name`.

---

## M5 — Infrastructure

**Rôle** : déclarer et préparer les machines cibles, les certificats, les clusters Swarm, les types nommés.

Pages : `InfraMachinesPage`, `InfraCertificatesPage`, `InfraCategoriesPage`, `InfraNamedTypesPage`, `InfraSwarmClustersPage`.

### Catégories et named types

L'administrateur déclare les **catégories** d'infrastructure (`docker`, `docker-swarm-node`, `k3s`, …) et les **named types** qui les spécialisent. Pour chaque named type :
- Variables d'environnement requises ou exposées (`infra_named_type_env_vars`, avec `is_secret`).
- Actions concrètes (`infra_named_type_actions`) : URL d'un manifest de script qui sera téléchargé, paramétré et exécuté.
- Règles (`infra_named_type_rules`) : filtres sur les options disponibles selon le contexte.

Les **actions de catégorie** (`infra_category_actions`) sont les actions requises ou optionnelles d'une catégorie, qui peuvent à leur tour créer une nouvelle catégorie (par ex. `install_docker` sur une catégorie `proxmox-host` crée la catégorie `docker`).

### Certificats SSH

Endpoints sous `/api/infra/certificates`. Permet de **générer** une paire RSA 4096 ou Ed25519 directement dans la plateforme (la clé privée part dans Harpocrate, la clé publique reste exposable pour configurer `authorized_keys` ailleurs), ou d'**importer** un certificat existant.

### Machines

Pour chaque machine (`infra_machines`) :
- Identité : `name`, `type_id` (named type), `host`, `port`, `username`.
- Auth : mot de passe (stocké dans Harpocrate) OU certificat (`certificate_id`).
- Hiérarchie : `parent_id` (nullable) pour modéliser les containers LXC dans un host Proxmox.
- Attribution : `user_id` (nullable) pour les machines dédiées à un utilisateur en mode SaaS.
- `environment` : texte libre (label pour grouper les machines, ex: `dev`, `prod`).
- `metadata` (JSONB) : kv pairs libres.
- `status` : `not_initialized`, `initialized`, `failed`.
- `required_actions` : liste calculée des actions de la catégorie à effectuer encore.

Actions :
- `POST /test-connection-dryrun` : tester une connexion SSH **avant** que la machine soit créée (l'opérateur saisit les creds dans le body).
- `POST /{id}/test-connection` : tester la connexion d'une machine existante.
- `GET /{id}/containers` : lister les containers Docker tournant sur la machine.
- `GET /{id}/health` : auto-détection du mode (K3s via port 6443, sinon Docker via SSH).
- `POST /{id}/run-script` : télécharger un manifest de script depuis une URL et l'exécuter avec les args fournis.
- `POST /{id}/option-script` : exécuter un script court (timeout 30 s, cache) pour récupérer des options dynamiques (ex: liste des templates LXC disponibles, liste des datastores Proxmox).
- `GET /{id}/runs` : historique des exécutions.
- Variables d'env : `GET / PUT /{id}/env-vars` (upsert atomique avec mix de valeurs claires et de secrets à pousser en Harpocrate).

### Clusters Swarm

Endpoints sous `/api/infra/swarm-clusters` + actions sur les machines :
- `POST /machines/{id}/actions/swarm_init` : initialise un cluster en faisant de cette machine le premier manager. Crée un `infra_swarm_clusters` et stocke les tokens manager + worker dans Harpocrate.
- `POST /machines/{id}/actions/swarm_join` : la machine rejoint un cluster existant en rôle `manager` ou `worker` (le token approprié est lu depuis Harpocrate).
- `POST /machines/{id}/actions/swarm_leave` : la machine quitte. Si elle est le dernier manager, le cluster est dissous.

---

## M6 — Projets, déploiement, runtimes

**Rôle** : composer des ressources projet à partir des produits du catalogue, et les déployer.

Pages : `ProductsPage`, `ProjectsPage`, `ProjectDetailPage`, `DeployWizardDialog`, `ProjectRuntimesPage`.

### Produits

Le catalogue de produits (`products`) est la bibliothèque des services tiers conteneurisés disponibles. Chaque produit a une **recette YAML** versionnée qui décrit :
- Les services Docker à lancer (image, ports, mounts, env).
- Les variables exposées à l'utilisateur (avec valeur par défaut, contrainte de format).
- Les secrets requis (références Harpocrate ou variables d'environnement à fournir).
- Les capacités (`config_only` pour les produits sans runtime, `has_openapi` pour les produits avec API, `mcp_package_id` pour le lien vers un MCP catalog).

### Ressources projets

Composition d'une ressource projet :
1. Créer le projet (`projects`) avec nom, description, tags, réseau Docker.
2. Ajouter des groupes (`groups`) — un groupe = un sous-ensemble qui se déploiera sur une même machine cible.
3. Pour chaque groupe : ajouter des instances de produits (`product_instances`), des variables (`group_variables`), des scripts de groupe (`group_scripts` en timing `before` ou `after`).
4. Configurer les templates Jinja de génération (`compose_template_slug` et/ou `swarm_template_slug`).

### Check de pré-déploiement

`GET /api/admin/projects/{id}/env-vars-check` : pour chaque script de groupe avec des variables d'entrée `via_env`, vérifie que toutes les variables sont résolubles (via les `infra_env_vars` de la machine cible, les `group_variables`, les `platform_secrets`, ou les valeurs littérales fournies dans `input_values` des group_scripts).

Le résolveur unifié (`input_resolver`) est appelé en mode **dry-run** (variant `resolve_input_values_collect`) ; les erreurs sont accumulées et renvoyées avec leur `kind` typé (`value_empty`, `var_not_in_env`, `platform_secret_missing`, `machine_not_found`, `env_machine_var_not_found`, `unknown_ref`). La bannière de la page affiche chaque raison avec un message i18n.

### Wizard de déploiement

`DeployWizardDialog` — wizard 3 onglets piloté par une machine à états backend (`project_deployments`) :

1. **Configuration** : sélection des machines cibles pour chaque groupe, choix de l'utilisateur (`user_id`) qui possède le runtime, secrets à fournir (`generated_secrets`).
2. **Exécution step-by-step** : pour chaque script `before`, exécution dans une tâche `asyncio` isolée, logs streamés via SSE (Server-Sent Events) depuis un bus in-process (`asyncio.Queue`). Chaque step peut être réessayé. Les variables d'environnement résultantes sont accumulées dans `accumulated_env` après chaque step.
3. **Déploiement** : rendu Jinja de la stack (`docker-compose.yml` ou `stack.yml`), upload SSH sur la machine cible, `docker compose up -d` ou `docker stack deploy`, exécution des scripts `after`, mise à jour des `project_runtimes` et `project_group_runtimes`.

États : `draft` → `generated` → `executing_step` → `step_complete` | `step_failed` → `before_complete` → `deploying` → `deployed` | `failed`.

### Runtimes projets

Une fois déployé, le projet existe comme `project_runtimes` avec ses `project_group_runtimes`. Actions disponibles : `GET /status`, `POST /start`, `POST /stop`, `DELETE` (idempotent : stoppe les conteneurs, supprime le dossier remote, soft-delete la ligne).

---

## M7 — Supervision, sessions, audit

**Rôle** : observer l'état temps réel de la plateforme et auditer son activité.

Pages : `SupervisionPage`, `SessionsPage`, `SessionDetailPage`, `UsersPage`, `ApiKeysPage`.

### Vue d'ensemble

`GET /api/admin/supervision/overview` retourne :
- Compteurs de sessions par statut (`active`, `closed`, `expired`).
- Compteurs d'agents par statut (`idle`, `busy`, `error`, `destroyed_total`).
- Nombre de containers en cours d'exécution.
- Statistiques MOM (Message-Oriented Middleware) : `pending`, `claimed`, `failed`.

### Liste des instances d'agents

`GET /api/admin/supervision/instances?status=…` retourne les instances supervisées avec leurs métadonnées.

### Détail d'une instance

`GET /api/admin/supervision/instances/{id}` retourne :
- État de l'instance.
- Statut du container Docker associé.
- Compteurs de delivery MOM.
- Derniers messages échangés.

### Stream temps réel

Endpoint WebSocket `/api/admin/supervision/stream` (auth JWT en query param). Le backend écoute le canal PostgreSQL `pg_notify('supervision_events', …)` et pousse les events au frontend. Le hook React `useSupervisionStream` gère la reconnexion (backoff exponentiel 1 s → 30 s) et le composant `SupervisionStreamIndicator` affiche l'état (déconnecté / connecté / actif).

L'UI invalide chirurgicalement les queries TanStack Query concernées par chaque event (par exemple : event `instance.status_changed` → invalidation de la query `['supervision-instance', instance_id]`).

### Sessions et tâches

L'admin peut lister, inspecter et fermer (force) les sessions de tous les utilisateurs : `GET / DELETE /api/admin/sessions/{id}`. Les agents instances d'une session sont accessibles via `GET .../agents` ; les messages d'une instance via `GET .../agents/{instance_id}/messages?kind=&direction=&limit=`.

### Utilisateurs et clés API

- `UsersPage` : CRUD utilisateurs, approbation des comptes `pending`, désactivation, ré-activation, gestion des rôles (`admin` / `user` / `operator` / `viewer`) et des scopes.
- `ApiKeysPage` : CRUD clés API natives. La valeur en clair de la clé n'est exposée **qu'à la création** (`ApiKeyCreated.full_key`). Ensuite, seule la metadata (`prefix`, `name`, `scopes`, `expires_at`, `last_used_at`) est consultable.

### Système

Pages bas-niveau (`SystemPage`) :
- Export du volume de données.
- Export DB (`pg_dump` gzippé).
- Import DB (`--clean --if-exists` : **destructif**, l'admin doit confirmer).
- Configuration de la plateforme (`platform_config` kv pairs).
- Cross-app launcher : `apps.json` liste les autres apps de la suite, affichées dans le menu top-bar.
