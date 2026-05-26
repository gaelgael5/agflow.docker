# 01 — Glossaire

Les termes ci-dessous sont **précisément** ceux utilisés dans le code, la base de données et les API. La spec entière les emploie sans synonyme.

## Concepts métier

### Ressource projet (`projects` en DB)

**Définition** : un template versionné qui décrit un projet, c'est-à-dire un **ensemble de services conteneurisés** destinés à fonctionner ensemble. Une ressource projet n'est pas exécutable telle quelle ; elle est instanciée.

**Synonymes à éviter** : « modèle de projet », « blueprint projet ». Quand on parle au workflow externe ag.flow, ce concept s'appelle simplement `project` dans le contrat — c'est la même chose.

**Composition** : une ressource projet contient un ou plusieurs **groupes** (`groups`), et chaque groupe contient une ou plusieurs **instances de produit** (`product_instances`) et zéro ou plusieurs **scripts de groupe** (`group_scripts`).

### Instance projet (`project_runtimes` en DB)

**Définition** : une matérialisation déployée d'une ressource projet, sur une cible Docker / Swarm / K3s, pour un utilisateur donné. Les conteneurs tournent réellement ; ils consomment des ressources CPU, RAM, disque sur les machines cibles.

**Cycle de vie** : `provisioning` → `deployed` | `failed` → suppression (idempotente : supprime les conteneurs, le dossier distant, puis soft-delete la ligne en base).

**Préfixes** : pour permettre plusieurs instances du même projet sur la même machine (déploiement multi-utilisateur), les hostnames Docker sont préfixés (typiquement `agflow-user-{X}` pour le réseau partagé entre conteneurs d'un même utilisateur).

### Groupe (`groups`)

**Définition** : un sous-ensemble d'une ressource projet. Un groupe rassemble des instances de produit qui partagent un même **réseau Docker** et qui sont **co-déployées sur la même machine cible**.

**Propriétés clés** :
- `max_agents` : nombre d'agents simultanés autorisés en session sur ce groupe (0 = illimité).
- `max_replicas` : nombre de copies du groupe que l'instance projet peut déployer en parallèle (≥ 1).
- `compose_template_slug` : template Jinja2 utilisé pour rendre le `docker-compose.yml` du groupe en mode Docker simple.
- `swarm_template_slug` : template Jinja2 utilisé pour rendre la `stack.yml` Swarm correspondante.

### Instance de produit (`product_instances`)

**Définition** : une instance d'un **produit** (élément du catalogue) configurée pour un groupe donné. Exemple : une instance de « Outline » nommée `wiki-equipe` dans le groupe `primary`.

**Statuts** : `draft` (créée mais pas activée), `active` (URL de service connue, opérationnelle), `stopped` (arrêtée mais préservée).

**Variables** : chaque instance porte un dictionnaire `variables` (clé/valeur) et un dictionnaire `variable_statuses` (`keep` / `clean` / `replace`) qui pilote leur comportement au redéploiement.

### Produit (`products`)

**Définition** : un élément du catalogue qui décrit comment instancier un service tiers (Outline, Gitea, Postgres, etc.) sous forme conteneurisée. Un produit contient une **recette YAML** (services, variables exposées, secrets requis) et une catégorie (`wiki`, `tasks`, `code`, `design`, `infra`, `other`).

### Session (`sessions`)

**Définition** : une exécution active de la plateforme regroupant un ou plusieurs agents pendant une durée limitée. Une session peut être liée à une **instance projet** (les agents accèdent alors aux ressources de l'instance) ou être autonome (sandbox / one-shot).

**Cycle de vie** : créée avec `duration_seconds` (60 s à 30 j), statut `active` jusqu'à expiration, puis `closed` (explicite) ou `expired` (automatique). Extensible à tout moment via `PATCH /extend`.

**Sécurité** : créée avec un `api_key_id`, optionnellement un `callback_url` + `callback_hmac_key_id` pour recevoir des notifications signées HMAC.

### Agent

Le mot « agent » porte deux sens distincts. Le glossaire les sépare strictement :

- **Agent (catalogue)** — `agents` en DB : la **définition** d'un agent (dockerfile + rôle + configuration). C'est une composition versionnée.
- **Agent instance** — `agents_instances` en DB : une **exécution** d'un agent (catalogue) au sein d'une session. C'est un conteneur Docker qui tourne.

Quand le contexte est ambigu, on précise « définition d'agent » vs « instance d'agent ».

### Dockerfile

**Définition** : un répertoire versionné en base qui contient le `Dockerfile`, l'`entrypoint.sh`, le `Dockerfile.json` (config de runtime : mounts, env vars, network, etc.) et tout fichier auxiliaire nécessaire à la construction de l'image d'un agent.

**Build** : asynchrone via `aiodocker`. Chaque build calcule un `content_hash` déterministe à partir du contenu du répertoire ; l'image est tagguée avec ce hash, ce qui rend les rebuilds idempotents.

**État affiché** : `never_built`, `up_to_date`, `outdated`, `failed`, `building`, `image_missing`.

### Rôle (`roles`)

**Définition** : la **personnalité** d'un agent — son identité, ses compétences, ses missions, exprimées en markdown structuré. Un rôle est composé d'une `identity_md` racine et de **sections** (`sections` natives : `roles`, `missions`, `competences`, ou personnalisées) contenant des **documents** (`documents`, chaque document étant un fichier markdown).

**Prompt orchestrateur** : un rôle peut générer son `prompt_orchestrator_md` en appelant Claude pour synthétiser ses documents — texte qui sera injecté dans le system prompt des conteneurs d'agent.

### Mission / Profile (`agent_profiles`)

**Définition** : un sous-ensemble de documents du rôle d'un agent, identifié par un nom, qu'on peut appliquer à une exécution. Permet de spécialiser ponctuellement un agent (« assistant déploiement », « assistant audit ») sans dupliquer sa définition.

### MCP server (`mcp_servers`)

**Définition** : un **Model Context Protocol server** installé localement dans le catalogue, avec ses paramètres (clés API, options) et une ou plusieurs recettes d'utilisation. Les MCP exposent à un agent des outils (`tools`) qu'il peut appeler — recherche web, lecture de fichiers, requêtes SQL, etc.

**Source** : installé depuis un **service de découverte** (registre externe, par défaut `mcp.yoops.org/api/v1`).

### Skill (`skills`)

**Définition** : un pack de capacité (un fichier markdown structuré) installé depuis un service de découverte. Une skill décrit une façon de faire — un workflow réutilisable — qu'un agent peut adopter.

### Service de découverte (`discovery_services`)

**Définition** : un registre externe qui expose un catalogue de MCP servers et de skills. Configuré dans l'admin (URL de base + référence à une clé API).

### Work / Task

Un **work** est une instruction envoyée à une instance d'agent via `POST /sessions/{id}/agents/{instance_id}/work`. Côté serveur, il devient une **task** (`tasks` en DB) avec un `task_id` (UUID v4) et un cycle de vie `pending` → `running` → `completed` | `failed` | `cancelled`.

Quand l'orchestrateur externe ag.flow envoie un work, il fournit un `_agflow_correlation_id` et un `_agflow_action_execution_id` qui sont préservés dans la `task` ; ils servent à reconnecter les hooks de fin avec son propre état.

### Hook

**Définition** : un appel HTTP sortant signé HMAC envoyé par agflow.docker pour notifier un événement (typiquement `task_completed`). Le destinataire vérifie la signature avec la clé publique de la `hmac_keys` référencée par `callback_hmac_key_id`.

## Concepts d'infrastructure

### Machine (`infra_machines`)

**Définition** : un hôte physique ou virtuel, accessible par SSH, sur lequel agflow.docker peut déployer des conteneurs. Une machine est de type **named type** (voir ci-dessous) et appartient éventuellement à un **parent_id** (hiérarchie : un host LXC parent → des LXC enfants).

**Authentification** : par mot de passe (chiffré dans Harpocrate) ou par certificat SSH (RSA / Ed25519 chiffré dans Harpocrate). Le mot de passe en clair n'est jamais en base.

**Status** : `not_initialized`, `initialized`, `failed`, et un dictionnaire `required_actions` qui liste les actions de catégorie à effectuer (ex: `install_docker`, `install_swarm`).

### Cluster Swarm (`infra_swarm_clusters`)

**Définition** : un cluster Docker Swarm composé d'un nœud manager initial et de zéro ou plusieurs nœuds workers ou managers additionnels qui l'ont rejoint. Les tokens de jointure (manager + worker) sont stockés dans Harpocrate, jamais exposés en clair via l'API.

### Catégorie d'infrastructure (`infra_categories`)

**Définition** : une grande famille d'infrastructure — `docker`, `docker-swarm-node`, `k3s`, `proxmox-host`, etc. Chaque catégorie peut avoir des **actions** (`category_actions`) requises ou optionnelles à effectuer sur les machines de cette catégorie.

### Named type (`infra_named_types`)

**Définition** : un type nommé qui spécialise une catégorie d'infrastructure. Exemple : la catégorie `docker` peut contenir les named types « Docker daemon Debian », « Docker daemon Alpine », etc. Chaque named type définit ses variables d'environnement (`infra_named_type_env_vars`), ses actions concrètes (`infra_named_type_actions` qui pointent vers des scripts à exécuter) et ses règles (`infra_named_type_rules` qui sont des filtres sur les options affichées).

### Certificat (`infra_certificates`)

**Définition** : une paire clé privée / clé publique (RSA 4096 par défaut, ou Ed25519) avec passphrase optionnelle. Stockée chiffrée dans Harpocrate. Utilisée pour les connexions SSH aux machines.

## Concepts de sécurité

### Harpocrate

**Définition** : le coffre-fort externe end-to-end encrypted utilisé par agflow.docker pour stocker tous les secrets. Le coffre est accédé via un SDK local qui s'authentifie avec une clé API et résout les références de la forme `${vault://api:NAME}`.

**Multi-coffres** : la plateforme peut être configurée avec plusieurs coffres ; un coffre est marqué comme **default** et reçoit les nouveaux secrets sauf indication contraire.

**Chicken-and-egg** : la clé API qui ouvre le coffre Harpocrate est elle-même chiffrée localement (par `harpocrate_dek` en base), c'est la seule exception à la règle « tout secret dans Harpocrate ».

### Référence de secret

Une **référence de secret** est une chaîne qui ne contient pas la valeur mais indique où la chercher. Quatre formes existent :

| Forme | Sémantique |
|---|---|
| `${vault://api:NAME}` | Résolu via Harpocrate (chemin canonique du secret) |
| `${env://NAME}` | Résolu via la table `platform_secrets` (variables globales) |
| `${env-machine://<machine>:<VAR>}` | Résolu via les `infra_env_vars` de la machine `<machine>` |
| `${VAR}` ou `$VAR` (MAJUSCULES) | Résolu via le `.env` du déploiement courant |

Le **résolveur unifié** (`input_resolver`) traite ces quatre syntaxes dans cet ordre, **fail-fast** : la première référence non résoluble fait échouer le rendu avec un message explicite. Le service appliqué tant au check pré-déploiement qu'à l'exécution garantit que « check vert » implique « exécution OK ».

### Clé API native (`api_keys`)

**Définition** : un secret prefixé `agfd_` généré par la plateforme et utilisé pour authentifier les appels sur l'API publique. Chaque clé porte des **scopes** (autorisations), une **rate limit** et une **date d'expiration** optionnelle. Le hash bcrypt + HMAC est stocké en base ; la valeur en clair n'est exposée qu'au moment de la création.

### Clé HMAC (`hmac_keys`)

**Définition** : un secret partagé entre agflow.docker et un destinataire de hooks. Sert à signer les payloads sortants. Identifiée par un `key_id` court. Rotation par soft-delete (le statut passe à `rotated`, la clé reste en base pour vérifier les signatures historiques).

### Coffre utilisateur (`user_secrets`)

**Définition** : un espace privé par utilisateur dans Harpocrate où il peut stocker des secrets personnels (clés API qu'il préfère ne pas partager, tokens éphémères). Distinct des `platform_secrets` (qui sont visibles par tous les admins) et des `infra_env_vars` (liés aux machines).

## Concepts de templating

### Template (`templates`)

**Définition** : un répertoire versionné de fichiers **Jinja2 sandboxed**, identifié par un slug et organisé par **culture** (langue : `fr`, `en`, etc.) et par **type de fichier** (`config`, `prompt`, `mcp`, `skills`, `compose`, `swarm`, etc.). Chaque fichier suit la nomenclature `<slug>/<culture>.<kind>.j2`.

**Sandbox** : le moteur Jinja2 est restreint pour empêcher l'exécution de code Python arbitraire depuis les templates.

### Script (`scripts`)

**Définition** : un script shell versionné en base, avec des **variables d'entrée** (`input_variables`) typées (chacune avec un flag `via_env` qui indique si elle doit être passée en variable d'environnement) et des **variables de sortie** (`output_variables`) extraites de la dernière ligne JSON du stdout (chacune avec un `path` en dot-notation).

**Cible** : un script peut être contraint à un named type (`execute_on_types_named`) — il ne pourra être exécuté que sur une machine de ce type.

### Script de groupe (`group_scripts`)

**Définition** : un lien entre un groupe et un script, avec un **timing** (`before` ou `after`), une **position** (ordre d'exécution), une **cible** (`target_kind` = `fixed_machine` avec `machine_id`, ou `deployment_host` qui résout vers la machine du groupe au déploiement) et un dictionnaire `input_values` qui pré-remplit les variables d'entrée du script.

**Règles de déclenchement** : `trigger_rules` permet d'exécuter conditionnellement un script selon les valeurs d'autres variables (opérateurs `equals`, `not_equals`, `is_null`).

## Concepts d'API et de contrats

### API admin

Toutes les routes sous `/api/admin/*` et `/api/infra/*`. Authentifiées par **JWT Keycloak** ou **JWT issu du login local**. Réservées à l'administration de la plateforme.

### API publique

Toutes les routes sous `/api/v1/*`. Authentifiées par **clé API native** (header `Authorization: Bearer agfd_…`). Consommées par les clients externes (ag.flow, scripts intégrateurs).

### Contrat workflow v5

L'ensemble des conventions partagées entre agflow.docker et ag.flow : forme exacte des payloads de `POST /sessions`, `POST /agents`, `POST /work`, `GET /tasks/{id}`, `GET /project-runtimes/{id}/resources`, format des hooks `task_completed` signés HMAC. Le contrat utilise systématiquement le mot **project** côté externe ; en interne ce concept est appelé **ressource projet**.

### Correlation ID

Un UUID v4 généré par ag.flow au lancement d'un workflow. Présent sur tous les payloads échangés entre les deux systèmes. Préservé par agflow.docker dans les colonnes `agflow_correlation_id` et `agflow_action_execution_id` des `tasks`, ce qui permet à ag.flow de reconnecter un hook tardif avec son état interne même après crash.
