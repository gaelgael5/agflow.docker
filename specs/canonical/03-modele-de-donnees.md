# 03 — Modèle de données

Cette section décrit le schéma PostgreSQL synthétiquement, regroupé par domaine. Le fichier `backend/migrations/001_init.sql` reste la source de vérité exacte (colonnes, types, contraintes, index). Cette spec donne les rôles métier des tables et les relations clés.

**Extensions** : `pgcrypto` (chiffrement éphémère, fonctions de hash), `uuid-ossp` (UUID v4).

**Conventions** :
- Toutes les clés primaires sont des UUID v4 (`uuid_generate_v4()` ou générées côté backend).
- Les colonnes `created_at` et `updated_at` sont des `TIMESTAMPTZ` mises à jour automatiquement par un trigger `set_updated_at()`.
- Les valeurs vides sont représentées par chaîne vide `''`, pas `NULL`, sauf pour les colonnes explicitement « nullable » (FK optionnelles, dates de fin, etc.).
- Les colonnes JSON utilisent `JSONB`.

---

## Domaine : utilisateurs et auth

### `users`
Utilisateurs de la plateforme.

Colonnes clés : `id`, `email` (unique), `name`, `avatar_url`, `role` (`admin` / `user` / `operator` / `viewer`), `scopes` (array), `status` (`pending` / `active` / `disabled`), `approved_at`, `approved_by` (FK users), `last_login`.

### `user_identities`
Identités externes liées à un utilisateur. Permet à un même `users.id` d'avoir plusieurs comptes Keycloak / Google / etc.

Colonnes : `user_id` (FK), `provider` (`keycloak` / `google` / `local`), `external_id`, `email`.

### `api_keys`
Clés API natives pour l'API publique.

Colonnes : `id`, `owner_id` (FK users), `name`, `prefix` (`agfd_xxxx` visible), `key_hash` (bcrypt+HMAC), `scopes`, `rate_limit`, `expires_at`, `revoked`, `last_used_at`.

### `hmac_keys`
Clés HMAC partagées pour signer les hooks sortants.

Colonnes : `key_id` (court, identifiant logique), `secret_hash`, `description`, `status` (`active` / `rotated`), `created_at`, `rotated_at`.

### `auth_config`
Configuration de l'authentification UI (singleton).

Colonnes : `mode` (`local` / `keycloak`), `keycloak_url`, `keycloak_realm`, `keycloak_client_id`, `keycloak_client_secret_ref` (référence Harpocrate), `updated_at`, `updated_by_user_id`.

### `user_secrets`
Coffre privé par utilisateur (références à des secrets Harpocrate scopés à l'utilisateur).

Colonnes : `user_id` (FK), `name`, `vault_ref` (`${vault://api:user/{id}/{name}}`), `description`.

---

## Domaine : secrets et coffre

### `platform_secrets`
Variables globales référencées par l'ensemble de la plateforme. Deux types :
- **Type `vault`** : la `key` est de la forme `${vault://api:NAME}`, la valeur est dans Harpocrate.
- **Type `env`** : la `key` est de la forme `${env://NAME}`, la valeur est dans la colonne `default_value` (utilisé pour les variables non sensibles).

Colonnes : `id`, `key` (clé canonique, unique), `default_value` (texte vide pour les vault, contenu pour les env), `created_at`, `updated_at`.

### `harpocrate_vaults`
Coffres Harpocrate déclarés.

Colonnes : `id`, `name`, `base_url`, `api_key_ref` (chiffrée localement via `harpocrate_dek`), `is_default` (booléen, un seul à la fois).

### `harpocrate_dek`
Clé de chiffrement locale qui chiffre les `api_key_ref` des `harpocrate_vaults`. Singleton (1 ligne). Existe parce que la clé qui ouvre Harpocrate ne peut pas elle-même être dans Harpocrate (chicken-and-egg).

---

## Domaine : agents et exécution

### `agents` (catalogue de définitions)
Une définition d'agent versionnée.

Colonnes : `id`, `slug` (unique), `display_name`, `description`, `dockerfile_id` (FK dockerfiles), `role_id` (FK roles), `env_vars` (JSONB), `timeout_seconds`, `workspace_path`, `network_mode` (`bridge` / `host` / `none`), `graceful_shutdown_secs`, `force_kill_delay_secs`, `is_assistant` (un seul agent peut porter ce flag), `mcp_template_slug` / `mcp_template_culture` / `mcp_config_filename`, `skills_template_slug` / `skills_template_culture` / `skills_config_filename`, `prompt_template_slug` / `prompt_template_culture` / `prompt_filename`, `generations` (JSONB : blocks de génération par rôle).

### `agent_mcp_bindings`
Liens entre un agent et les MCP servers du catalogue qu'il utilise.

Colonnes : `agent_id` (FK), `mcp_server_id` (FK), `parameters_override` (JSONB), `position`.

### `agent_skill_bindings`
Liens entre un agent et les skills qu'il adopte.

Colonnes : `agent_id` (FK), `skill_id` (FK), `position`.

### `agent_profiles`
Missions / profils d'un agent : un sous-ensemble de documents du rôle.

Colonnes : `id`, `agent_id` (FK), `name`, `description`, `document_ids` (array UUID), `template_slug`, `template_culture`, `output_dir`.

### `agent_api_contracts`
Contrats OpenAPI attachés à un agent — décrivent les API que l'agent peut consommer.

Colonnes : `id`, `agent_id` (FK), `slug`, `display_name`, `source_type` (`upload` / `url` / `manual`), `source_url`, `spec_content`, `base_url`, `runtime_base_url`, `auth_header`, `auth_prefix`, `auth_secret_ref`, `parsed_tags` (JSONB), `tag_overrides` (JSONB), `managed_by_instance` (FK product_instances, nullable), `output_dir`, `position`.

### `sessions`
Sessions d'exécution.

Colonnes : `id`, `name`, `status` (`active` / `closed` / `expired`), `project_id` (legacy, voir `project_runtime_id`), `project_runtime_id` (FK, nullable), `api_key_id` (FK), `callback_url`, `callback_hmac_key_id`, `created_at`, `expires_at`, `closed_at`.

### `agents_instances`
Instances d'agents en session.

Colonnes : `id`, `session_id` (FK), `agent_id` (référence à `agents.slug`), `labels` (JSONB), `mission` (texte libre), `status` (`idle` / `busy` / `error` / `destroyed`), `last_activity_at`, `created_at`, `destroyed_at`, `error_message`, `last_container_name`.

### `agent_messages`
Messages échangés avec ou par une instance d'agent.

Colonnes : `id`, `instance_id` (FK), `msg_id` (logique), `parent_msg_id`, `direction` (`in` / `out`), `kind` (`instruction` / `cancel` / `event` / `result` / `error`), `payload` (JSONB), `source`, `route` (JSONB), `created_at`.

### `agent_message_delivery`
Suivi de livraison des messages (compteurs pending / claimed / failed).

Colonnes : `id`, `message_id` (FK), `status` (`pending` / `claimed` / `acked` / `failed`), `attempts`, `last_attempt_at`, `error`.

### `tasks`
Tâches asynchrones de tous types (work d'agent, runtime provisioning, etc.).

Colonnes : `id`, `kind` (`agent_work` / `runtime_provision` / `dockerfile_build` / `deployment_push` / …), `status` (`pending` / `running` / `completed` / `failed` / `cancelled`), `session_id` (nullable), `agent_instance_id` (nullable), `agflow_correlation_id` (nullable), `agflow_action_execution_id` (nullable), `result` (JSONB nullable), `error` (JSONB nullable), `started_at`, `completed_at`, `created_at`.

### `launched_tasks`
Tâches one-shot lancées via l'API publique sur un dockerfile (hors session).

Colonnes : `id`, `dockerfile_id`, `container_name`, `instruction` (texte), `status`, `started_at`, `finished_at`, `exit_code`.

### `outbound_hooks`
Hooks HTTP sortants à envoyer (signés HMAC).

Colonnes : `id`, `target_url`, `payload` (JSONB), `hmac_key_id` (FK), `status` (`pending` / `delivered` / `failed`), `attempts`, `response_code`, `last_attempt_at`, `next_attempt_at`.

---

## Domaine : rôles, compétences, templates

### `roles`
Définitions de rôles.

Colonnes : `id` (slug unique), `display_name`, `description`, `service_types` (array de slugs), `identity_md`, `prompt_orchestrator_md`.

### `role_sections`
Sections natives ou personnalisées d'un rôle (Roles, Missions, Compétences, etc.).

Colonnes : `role_id` (FK), `name`, `display_name`, `is_native`, `position`.

### `documents`
Documents markdown attachés aux sections d'un rôle.

Colonnes : `id`, `role_id` (FK), `section` (FK indirecte via name), `parent_path`, `name`, `content_md`, `protected`.

### `service_types`
Catégories de service auxquelles un rôle peut être destiné (`Documentation`, `Code`, `Design`, …).

Colonnes : `name` (PK slug), `display_name`, `is_native`, `position`, `created_at`.

### `templates`
Templates Jinja2 versionnés organisés par slug.

Colonnes : `slug` (PK), `display_name`, `description`.

### `template_files`
Fichiers d'un template, par culture et type.

Colonnes : `template_slug` (FK), `culture` (`fr`, `en`, …), `kind` (`prompt`, `mcp`, `skills`, `compose`, `swarm`, …), `filename`, `content`, `size`.

### `template_cultures` et `template_file_types`
Tables de référence pour les cultures et les types de fichier disponibles.

---

## Domaine : dockerfiles et builds

### `dockerfiles`
Dockerfiles versionnés.

Colonnes : `id` (slug), `display_name`, `description`, `parameters` (JSONB : config runtime).

### `dockerfile_files`
Fichiers du répertoire d'un dockerfile.

Colonnes : `id`, `dockerfile_id` (FK), `path`, `content` (bytea ou texte), `encoding` (`utf-8` / `base64`), `type` (`file` / `dir`), `size`.

### `dockerfile_builds`
Historique des builds.

Colonnes : `id`, `dockerfile_id` (FK), `content_hash`, `image_tag`, `status` (`pending` / `running` / `success` / `failed`), `logs`, `started_at`, `finished_at`.

### `image_registries`
Registres d'images Docker externes (Docker Hub, ECR, registries privés).

Colonnes : `id` (slug), `display_name`, `url`, `auth_type` (`none` / `basic` / `token`), `credential_ref` (référence Harpocrate), `is_default`.

---

## Domaine : MCP catalog, skills, discovery

### `discovery_services`
Registres MCP / skills externes.

Colonnes : `id` (slug), `name`, `base_url`, `api_key_var` (référence au `${vault://api:NAME}` qui contient la clé), `description`, `enabled`.

### `mcp_servers`
MCP servers installés dans le catalogue local.

Colonnes : `id`, `discovery_service_id` (FK), `package_id`, `name`, `repo`, `repo_url`, `transport` (`stdio` / `sse` / `docker` / `streamable-http`), `short_description`, `long_description`, `documentation_url`, `parameters` (JSONB instance des paramètres), `parameters_schema` (JSONB schema de validation), `recipes` (JSONB), `category`.

### `skills`
Skills installés dans le catalogue local.

Colonnes : `id`, `discovery_service_id` (FK), `skill_id` (id distant), `name`, `description`, `content_md`.

### `ai_providers`
Providers IA configurés (clés API).

Colonnes : `service_type` (`image_generation` / `embedding` / `llm`), `provider_name` (`anthropic` / `openai` / `mistral` / …), `display_name`, `secret_ref` (référence Harpocrate vers la clé API), `enabled`, `is_default`. PK composite (`service_type`, `provider_name`).

---

## Domaine : produits et projets

### `products`
Catalogue de produits (templates de services tiers conteneurisés).

Colonnes : `id` (slug), `display_name`, `description`, `category` (`wiki` / `tasks` / `code` / `design` / `infra` / `other`), `tags` (array), `min_ram_mb`, `config_only`, `has_openapi`, `mcp_package_id` (lien vers un MCP server du catalogue, nullable), `recipe_version`, `recipe_yaml`, `recipe` (JSONB parsé).

### `projects` (ressources projets)
Ressources projets — templates qui regroupent des groupes.

Colonnes : `id`, `display_name`, `description`, `tags` (array), `network` (nom du réseau Docker, défaut `agflow`).

### `groups`
Groupes au sein d'une ressource projet.

Colonnes : `id`, `project_id` (FK), `name`, `max_agents`, `max_replicas`, `machine_id` (FK infra_machines, nullable — résolution `deployment_host`), `compose_template_slug` (FK templates.slug), `swarm_template_slug` (FK templates.slug).

### `group_variables`
Variables globales au niveau d'un groupe (résolues au rendu Jinja).

Colonnes : `id`, `group_id` (FK), `name` (validé `[A-Za-z_][A-Za-z0-9_]*`), `value` (peut être un littéral ou une référence `${vault://…}` / `${env://…}` / `${env-machine://…}`), `description`.

### `group_scripts`
Scripts à exécuter avant ou après le déploiement d'un groupe.

Colonnes : `id`, `group_id` (FK), `script_id` (FK), `target_kind` (`fixed_machine` / `deployment_host`), `machine_id` (FK, nullable), `timing` (`before` / `after`), `position`, `env_mapping` (JSONB), `input_values` (JSONB), `input_statuses` (JSONB : keep/clean/replace), `trigger_rules` (JSONB array).

### `product_instances`
Instances de produits déployées dans un groupe.

Colonnes : `id`, `group_id` (FK), `instance_name`, `catalog_id` (FK products.id), `variables` (JSONB), `variable_statuses` (JSONB), `status` (`draft` / `active` / `stopped`), `service_url`.

### `project_runtimes` (instances projets)
Matérialisation d'une ressource projet sur l'infra.

Colonnes : `id`, `seq` (compteur), `project_id` (FK projects), `deployment_id` (FK, nullable), `user_id` (FK users, nullable), `status` (`pending` / `provisioning` / `deployed` / `failed`), `pushed_at`, `error_message`.

### `project_group_runtimes`
Sous-runtime par groupe (un par groupe de la ressource projet, déployé sur sa machine cible).

Colonnes : `id`, `seq`, `project_runtime_id` (FK), `group_id` (FK), `machine_id` (FK), `remote_path`, `status`, `pushed_at`, `error_message`, `env_text`, `compose_yaml`.

### `project_deployments`
Brouillons de déploiement préparés avant push.

Colonnes : `id`, `project_id` (FK), `user_id` (FK), `group_servers` (JSONB : mapping group_id → machine_id), `status` (`draft` / `generated` / `deployed`), `generated_compose`, `generated_env`, `generated_secrets` (JSONB), `nullable_secrets` (array), `generated_data` (JSONB).

### `instances` et `instances_metadata`
Tables génériques pour les instances d'objets divers et leurs metadata kv. Utilisées notamment pour la liaison entre `agents_instances`, `product_instances` et les containers Docker effectivement créés.

---

## Domaine : infrastructure

### `infra_categories`
Catégories d'infrastructure (`docker`, `docker-swarm-node`, `k3s`, `proxmox-host`, …).

Colonnes : `name` (PK slug), `visible_in_machines`.

### `infra_category_actions`
Actions associées à une catégorie (préparation, installation, …).

Colonnes : `id`, `category` (FK), `name`, `is_required`, `creates_category` (nullable).

### `infra_named_types`
Types nommés (instances de catégories avec spécialisation).

Colonnes : `id`, `name`, `type_id` (FK categories.name), `sub_type_id` (nullable), `connection_type` (`SSH` / `K8s` / `local`).

### `infra_named_type_env_vars`
Variables d'environnement requises ou exposées par un named type.

Colonnes : `id`, `named_type_id` (FK), `name`, `description`, `position`, `is_secret`.

### `infra_named_type_actions`
Actions concrètes (scripts à exécuter) pour un named type.

Colonnes : `id`, `named_type_id` (FK), `category_action_id` (FK), `url` (URL du script manifest), `creates_named_type_id` (nullable).

### `infra_named_type_rules`
Règles de filtrage / options conditionnelles sur un named type.

Colonnes : `id`, `named_type_id` (FK), `key`, `value`.

### `infra_machines`
Machines hôtes.

Colonnes : `id`, `name`, `type_id` (FK named_types.id), `host`, `port` (défaut 22), `username`, `password_ref` (référence Harpocrate, nullable), `certificate_id` (FK certificates, nullable), `parent_id` (FK self, nullable), `user_id` (FK users, nullable), `environment` (texte libre), `metadata` (JSONB), `status`.

### `infra_machines_runs`
Historique des exécutions d'actions sur une machine.

Colonnes : `id`, `machine_id` (FK), `action_id` (FK named_type_actions), `success`, `output`, `started_at`, `finished_at`.

### `infra_machine_env_vars`
Valeurs concrètes des variables d'environnement d'une machine.

Colonnes : `machine_id` (FK), `named_type_env_var_id` (FK), `value` (clair ou référence `${vault://…}`), PK composite.

### `infra_swarm_clusters`
Clusters Swarm déclarés.

Colonnes : `id`, `cluster_name`, `manager_node_id` (FK machines), `manager_token_ref` (Harpocrate), `worker_token_ref` (Harpocrate), `created_at`.

### `infra_swarm_cluster_members`
Appartenance des machines à un cluster Swarm.

Colonnes : `cluster_id` (FK), `machine_id` (FK), `role` (`manager` / `worker`), `joined_at`.

### `infra_certificates`
Certificats SSH.

Colonnes : `id`, `name`, `key_type` (`rsa` / `ed25519`), `private_key_ref` (Harpocrate), `public_key`, `passphrase_ref` (Harpocrate, nullable).

### `infra_runtime_config`
Configuration runtime de la plateforme (kv pairs avec filtres optionnels).

Colonnes : `key`, `value`, `filter` (nullable).

---

## Domaine : scripts

### `scripts`
Scripts shell versionnés.

Colonnes : `id`, `name`, `description`, `content`, `execute_on_types_named` (FK named_types, nullable), `input_variables` (JSONB array), `output_variables` (JSONB array), `commands` (JSONB array).

---

## Domaine : backups et PITR

### `local_backups`
Backups DB locaux (pg_dump.gz).

Colonnes : `id`, `filename`, `size_bytes`, `status` (`ok` / `failed` / `manual`), `created_at`, `source_remote_connection_id` (nullable), `source_kind` (`manual` / `full`), `local_file_present`.

### `local_backup_pushes`
Pushes d'un local_backup vers une remote.

Colonnes : `id`, `local_backup_id` (FK), `remote_connection_id` (FK), `status` (`pending` / `pushing` / `ok` / `failed`), `pushed_at`, `error`, `remote_path`, `size_bytes`.

### `remote_backup_connections`
Connexions de backup distantes (SFTP, S3, FTPS, GDrive).

Colonnes : `id`, `name`, `kind` (`sftp` / `s3` / `ftps` / `gdrive`), `config` (JSONB), `credentials_ref` (Harpocrate, nullable), `usage` (`full` / `pitr` / `…`).

### `backup_schedules_full`
Plannings de backups complets.

Colonnes : `id`, `name`, `cron_expr`, `remote_connection_ids` (array), `keep_local`, `retention_count`, `enabled`, `last_run_at`, `last_run_status`, `last_run_error`.

### `pitr_config`
Configuration PITR (singleton).

Colonnes : `enabled`, `basebackup_cron`, `basebackup_type` (`full` / `diff` / `incr`), `full_rebase_cron`, `retention_count`, `remote_connection_ids` (array).

### `pitr_basebackups`
Basebackups pgbackrest.

Colonnes : `id`, `pgbackrest_label`, `started_at`, `completed_at`, `size_bytes`, `status` (`running` / `ok` / `failed`), `error`, `recovery_window_start`, `recovery_window_end`.

### `pitr_basebackup_pushes`
Pushes d'un basebackup vers une remote.

Colonnes : `basebackup_id` (FK), `remote_connection_id` (FK), `status`, `pushed_at`, `error`, `size_bytes`.

### `pitr_clones`
Clones PITR actifs (instances PostgreSQL temporaires restaurées à un point dans le temps).

Colonnes : `id`, `basebackup_id` (FK), `target_time`, `status` (`restoring` / `ready` / `terminating` / `terminated` / `failed`), `error`, `pgweb_url`, `started_at`, `ready_at`, `expires_at` (TTL extensible).

### `git_sync_config`
Configuration git-sync de la configuration (singleton).

Colonnes : `repo_url`, `auth_mode` (`ssh_key` / `pat_https` / `basic_https`), `auth_secret_ref` (Harpocrate), `branch`, `commit_author_name`, `commit_author_email`, `excluded_columns` (JSONB par table), `selected_tables` (array), `cron_expr`, `cron_enabled`, `last_export_at`, `last_export_status`, `last_export_sha`, `last_export_error`, `last_export_tables_count`, `last_import_at`, `last_import_status`, `last_import_error`, `last_import_rows_inserted` / `updated` / `deleted`.

---

## Domaine : avatars

### `avatar_themes`
Thèmes graphiques pour les avatars.

Colonnes : `slug` (PK), `display_name`, `description`, `prompt` (instruction de génération), `provider` (`dall-e-3` / …), `size`, `quality`, `style`.

### `avatar_characters`
Personnages d'un thème.

Colonnes : `slug`, `theme_slug` (FK), `display_name`, `description`, `prompt`, `selected` (numéro de l'image sélectionnée).

### `avatar_images`
Images générées pour un personnage. Stockées sur disque (référencées par numéro et `filename`), pas en base.

---

## Domaine : autres

### `platform_config`
Paires clé-valeur globales (toggles, paramètres divers).

### `rate_limit_counters`
Compteurs de rate limiting backés par Redis (peuvent aussi être persistés en base pour audit).

### `apps`
Cross-app launcher entries (raccourcis vers d'autres applications de la même suite).

### `supervision_events`
Événements émis via `pg_notify` consommés par le module M6 (supervision temps réel). Pas nécessairement persistés, le canal pg_notify est le bus principal.

---

## Relations transverses notables

```
users 1───* api_keys 1───* sessions
                              │
                              ├──> agents_instances ──┐
                              │                       │
                              └──> agent_messages <───┘
                              │
                              └──> tasks (kind=agent_work)

projects (ressource) 1───* groups 1───* product_instances
                          │            └──> products (catalog_id)
                          ├─── group_scripts ──> scripts
                          └─── group_variables

projects 1───* project_runtimes 1───* project_group_runtimes
                                         └──> groups + infra_machines

infra_categories 1──* infra_named_types 1──* infra_machines
                                                  │
                                                  ├──> infra_machine_env_vars
                                                  ├──> infra_machines_runs
                                                  └──> infra_certificates (via certificate_id)

harpocrate_vaults (références dans .*_ref colonnes partout)
```
