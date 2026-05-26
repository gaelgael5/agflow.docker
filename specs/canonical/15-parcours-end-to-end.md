# 15 — Parcours end-to-end

Ce fichier illustre concrètement, par scénarios, **comment les briques décrites dans les autres modules s'assemblent**. Lecture utile pour comprendre l'usage opérationnel ; chaque scénario renvoie aux fichiers détaillés.

## Scénario 1 — Installation et configuration initiale

**Acteur** : admin de la plateforme. **Objectif** : amener une instance fraîche d'agflow.docker à un état où elle peut accepter des projets.

### 1.1. Provisioning de la machine hôte

L'opérateur infra crée un LXC Proxmox (script `scripts/infra/00-create-lxc.sh`) ou prépare une VM. Il installe Docker (`scripts/infra/01-install-docker.sh`). Il configure un domaine Cloudflare Tunnel pointant vers le backend.

### 1.2. Déploiement de la plateforme

```bash
# Cloner et builder
git clone <repo> /opt/agflow.docker
cd /opt/agflow.docker
# Configurer .env (AGFLOW_LOCAL_KEY, DATABASE_URL, …)
docker compose -f docker-compose.prod.yml up -d
```

Au démarrage :
- Le backend applique les migrations SQL (état initial via `001_init.sql`).
- `container.detection.load_or_detect` détecte le mode (Docker standalone / Swarm / K3s) et le persiste dans `infra_runtime_config` (cf. 02).
- Les workers asyncio démarrent (cf. 02 — section workers internes).

### 1.3. Premier login

L'admin local créé à l'installation se connecte via `POST /api/admin/auth/login` avec l'email/mot de passe fournis dans `.env`. Il reçoit un JWT.

### 1.4. Déclaration du coffre Harpocrate

L'admin crée le premier vault (`POST /api/admin/harpocrate-vaults`) :
- `name` : `default`.
- `base_url` : URL du service Harpocrate.
- `api_key` : clé d'accès (poussée immédiatement dans `harpocrate_dek`-encrypted DB column).
- `is_default` : `true`.

Test de connexion : `POST /api/admin/harpocrate-vaults/{id}/test-connection` doit retourner `{ "ok": true }`. (Cf. 07.)

### 1.5. Configuration de Keycloak (optionnel mais recommandé)

`PUT /api/admin/auth-config` avec `mode=keycloak`, `keycloak_url`, `keycloak_realm`, `keycloak_client_id`, `keycloak_client_secret`. Le secret est poussé dans Harpocrate par le backend. Test via `POST /api/admin/auth-config/test`.

À partir de là, les nouveaux utilisateurs se connectent via Keycloak (cf. 07).

### 1.6. Configuration des providers IA

`POST /api/admin/ai-providers` pour chaque service_type :
- `(llm, anthropic)` avec `secret_ref=${vault://api:ANTHROPIC_API_KEY}` (la clé doit avoir été poussée préalablement dans Harpocrate).
- `(image_generation, openai-dalle)` pour les avatars.
- Etc.

Marquer un default par `service_type` (cf. 13).

### 1.7. Déclaration des registres MCP / skills

`POST /api/admin/discovery-services` pointe vers `https://mcp.yoops.org/api/v1` (default fourni) ou tout autre registre interne. Test : `POST /…/test`. Cf. 04 M3.

### 1.8. Première machine cible

Si on va déployer des projets, déclarer au moins une machine :
1. `POST /api/infra/categories` : créer une catégorie `docker` si pas déjà là (souvent native).
2. `POST /api/infra/named-types` : créer un type `docker-debian` lié à la catégorie.
3. `POST /api/infra/machines` : déclarer la machine avec son host SSH, son named type, ses credentials (mot de passe → poussé dans Harpocrate, ou certificat généré via `POST /api/infra/certificates/generate`).
4. `POST /api/infra/machines/{id}/test-connection` : valider l'accès.
5. `GET /api/infra/machines/{id}/health` : auto-détection du mode (Docker / K3s).

À l'issue : la plateforme est prête à composer des agents et déployer des projets. Cf. 04 M5.

## Scénario 2 — Création d'un agent custom

**Acteur** : admin. **Objectif** : créer un agent `claude-code-devops` basé sur Claude Code, spécialisé dans les tâches DevOps.

### 2.1. Préparer le dockerfile

1. `POST /api/admin/dockerfiles` : créer un dockerfile id `claude-code-base` avec un `display_name` et des `parameters` (volumes, env, network).
2. Éditer les fichiers : `Dockerfile`, `entrypoint.sh`, `Dockerfile.json` via l'UI (`PUT /api/admin/dockerfiles/{id}/files/{file_id}`).
3. Optionnel : utiliser `POST /api/admin/dockerfiles/chat-generate` pour générer un brouillon via l'IA puis l'éditer.
4. `POST /api/admin/dockerfiles/{id}/build` : lance un build async. Suivre via `GET /api/admin/dockerfiles/{id}/builds/{build_id}` jusqu'à `status=success`. Cf. 04 M1.

### 2.2. Composer un rôle

1. `POST /api/admin/roles` : créer un rôle `devops-engineer` avec une `identity_md` racine ("Tu es un ingénieur DevOps senior…").
2. Ajouter des sections natives + custom (`Roles`, `Missions`, `Compétences`).
3. Ajouter des documents markdown dans chaque section.
4. `POST /api/admin/roles/{id}/generate-prompts` : faire générer un `prompt_orchestrator_md` synthétisé par Claude. Cf. 04 M2.

### 2.3. Installer les MCP nécessaires

`POST /api/admin/mcp-catalog` avec `discovery_service_id` + `package_id` pour chaque MCP utile : `github-mcp`, `slack-mcp`, `aws-cli-mcp`, etc. Configurer les `parameters` (clés API référencées en Harpocrate). Cf. 04 M3.

### 2.4. Installer les skills

`POST /api/admin/skills-catalog` pour les skills pertinentes : `infrastructure-troubleshooting`, `kubernetes-debugging`, etc. Cf. 04 M3.

### 2.5. Composer l'agent

`POST /api/admin/agents` :

```json
{
  "slug": "claude-code-devops",
  "display_name": "Claude Code — DevOps",
  "description": "Assistant DevOps complet",
  "dockerfile_id": "claude-code-base",
  "role_id": "devops-engineer",
  "env_vars": {
    "ANTHROPIC_MODEL": "claude-opus-4-7"
  },
  "timeout_seconds": 7200,
  "mcp_template_slug": "claude-code-mcp",
  "mcp_template_culture": "fr",
  "skills_template_slug": "claude-code-skills",
  "skills_template_culture": "fr",
  "prompt_template_slug": "claude-code-prompt",
  "prompt_template_culture": "fr",
  "mcp_bindings": [
    { "mcp_server_id": "<github-mcp-uuid>",  "position": 1 },
    { "mcp_server_id": "<aws-cli-mcp-uuid>", "position": 2 }
  ],
  "skill_bindings": [
    { "skill_id": "<infra-troubleshooting-uuid>", "position": 1 }
  ]
}
```

Cf. 04 M4.

### 2.6. Définir des profils de mission

`POST /api/admin/agents/{agent_id}/profiles` :
- Profil `audit-infra` : documents `["doc-uuid-1", "doc-uuid-3"]`, focus audit.
- Profil `troubleshoot-prod` : documents `["doc-uuid-2", "doc-uuid-5"]`, focus debug.

Cf. 14 section 2.

### 2.7. Attacher des contrats API

`POST /api/admin/agents/{agent_id}/contracts` pour chaque API externe :
- GitHub API : `source_type=url`, `source_url=https://api.github.com/openapi.json` (ou la vraie spec si publiée).
- Slack API : idem.
- API interne de monitoring.

Cf. 14 section 1.

### 2.8. Aperçu

`GET /api/admin/agents/{agent_id}/config-preview?profile_id=<audit-infra-uuid>` retourne le prompt final, la MCP config, les skills, le `.env`, et les `validation_errors` éventuelles. Vérifier que rien n'est rouge. Cf. 14 section 3.

### 2.9. Test ponctuel

Avant d'utiliser l'agent dans des sessions productives, tester en one-shot : `POST /api/admin/agents/{slug}/task` avec une instruction simple. Le container est créé, exécute, stream les events, se détruit. Cf. 05 section 6.

## Scénario 3 — Composition et déploiement d'un projet

**Acteur** : admin + opérateur. **Objectif** : déployer une instance « espace de travail intégré » (wiki Outline + Gitea + agent assistant) pour un utilisateur.

### 3.1. Vérifier les produits du catalogue

L'admin a préalablement enregistré les recettes des produits (`outline`, `gitea`, etc.). `GET /api/admin/products` doit lister ceux nécessaires. Cf. 04 M6.

### 3.2. Créer la ressource projet

`POST /api/admin/projects` :

```json
{
  "display_name": "Espace de travail intégré",
  "description": "Wiki Outline + Gitea + assistant Claude Code",
  "tags": ["saas", "v1"],
  "network": "agflow"
}
```

### 3.3. Ajouter le groupe principal

`POST /api/admin/groups` :

```json
{
  "project_id": "<uuid>",
  "name": "primary",
  "max_agents": 5,
  "max_replicas": 1,
  "compose_template_slug": "saas-workspace-compose",
  "swarm_template_slug": "saas-workspace-swarm"
}
```

### 3.4. Ajouter les instances de produits

`POST /api/admin/product-instances` pour chaque service :

```json
{ "group_id": "<uuid>", "instance_name": "wiki", "catalog_id": "outline", "variables": { "OUTLINE_VERSION": "0.79" } }
{ "group_id": "<uuid>", "instance_name": "repo", "catalog_id": "gitea",   "variables": { "GITEA_VERSION":   "1.22" } }
{ "group_id": "<uuid>", "instance_name": "assistant", "catalog_id": "claude-code-devops" }  # cf. scénario 2
```

### 3.5. Ajouter les variables de groupe

`POST /api/admin/groups/{group_id}/variables` :

```json
{ "name": "REALM",            "value": "yoops" }
{ "name": "PUBLIC_DOMAIN",    "value": "user42.example.com" }
{ "name": "ADMIN_EMAIL",      "value": "admin@example.com" }
```

### 3.6. Ajouter les scripts de groupe `before`

Pour bootstrapper le wiki Outline qui nécessite un client OIDC Keycloak avant de pouvoir démarrer :

`POST /api/admin/groups/{group_id}/scripts` :

```json
{
  "script_id": "<uuid create-oidc-client>",
  "target_kind": "deployment_host",
  "timing": "before",
  "position": 0,
  "input_values": {
    "KC_ADMIN_PASSWORD": "${env-machine://keycloak1:KC_ADMIN_PASSWORD}",
    "REALM": "${REALM}",
    "CLIENT_ID": "outline-${PUBLIC_DOMAIN}"
  }
}
```

Le script `create-oidc-client` est un script du catalogue qui appelle l'API admin Keycloak et émet en dernière ligne :

```json
{"result": {"client_id": "outline-user42.example.com", "client_secret": "abc123..."}}
```

`output_variables` du script extrait `client_secret` et le merge dans `accumulated_env` pour les steps suivants. Cf. 13 section 2.

### 3.7. Vérifier le pré-déploiement

`GET /api/admin/projects/{id}/env-vars-check` :

Si tout est résoluble → `total_missing: 0`. Sinon, le rapport liste chaque référence non résoluble avec son `kind` (`machine_not_found`, `platform_secret_missing`, …). L'admin corrige en ajustant la machine `keycloak1`, ses variables d'env, ou les variables de groupe. Cf. 06.

### 3.8. Lancer le wizard de déploiement

L'opérateur ouvre `DeployWizardDialog` depuis `ProjectDetailPage` :

**Onglet 1 — Configuration** : choisir la machine cible (`group_servers={ <group_id>: <machine_id> }`), l'utilisateur cible (`user_id=<uuid>`).

**Onglet 2 — Exécution step-by-step** :
- Script `create-oidc-client` s'exécute sur la machine, crée le client OIDC, émet le JSON final.
- Logs streamés via SSE dans l'UI.
- `accumulated_env` reçoit `OUTLINE_OIDC_CLIENT_SECRET`.

**Onglet 3 — Déploiement** :
- Le `docker-compose.yml` est rendu avec toutes les variables (y compris celles du `accumulated_env`).
- Upload SSH.
- `docker compose up -d` exécuté.
- Scripts `after` exécutés (par exemple : créer un admin Outline initial).

Résultat : `project_runtimes.status = 'deployed'`, `project_group_runtimes` rempli. Cf. 06.

### 3.9. Vérification finale

`GET /api/admin/group-runtimes/{id}/status` : tous les conteneurs `up`. L'utilisateur peut ouvrir `https://wiki-user42.example.com` et se connecter via OIDC Keycloak.

## Scénario 4 — Session de travail piloté par ag.flow

**Acteur** : ag.flow (workflow service externe). **Objectif** : exécuter une étape de workflow qui demande à un agent d'auditer une PR GitHub.

### 4.1. Discovery

ag.flow appelle `GET /api/admin/projects/v5/list` pour proposer à l'utilisateur les projets disponibles. L'utilisateur choisit « Espace de travail intégré » au lancement du workflow. Cf. 09.

### 4.2. Provisioning de l'instance projet

Si l'utilisateur n'a pas encore d'instance, ag.flow appelle :

```http
POST /api/admin/projects/{project_id}/runtimes
```

Retour : `runtime_id`, `status=provisioning`. ag.flow poll `GET /api/admin/project-runtimes/{runtime_id}/resources` jusqu'à `status=ready`. Les `resources` incluent les URL du wiki, du repo, de l'assistant.

### 4.3. Création de session

```http
POST /api/admin/sessions
{
  "api_key_id": "<uuid de la clé d'ag.flow>",
  "duration_seconds": 7200,
  "project_runtime_id": "<runtime_id>",
  "callback_url": "https://workflow.example.com/api/hooks/agflow",
  "callback_hmac_key_id": "wf-2026-05"
}
```

Cf. 09.

### 4.4. Instanciation de l'agent

```http
POST /api/admin/sessions/{session_id}/agents
{
  "agent_id": "claude-code-devops",
  "count": 1,
  "labels": { "workflow_id": "wf-uuid", "step_id": "step-uuid" },
  "mission": "audit-infra"   # nom de profil → applique le sous-ensemble docs adéquat
}
```

Le backend :
1. Génère le workspace de l'agent avec le profil `audit-infra` appliqué.
2. Crée le container Docker avec `workspace/` monté en `/workspace`.
3. Le container démarre, l'agent lit son prompt, sa MCP config, ses contrats.
4. L'agent passe en `status=idle`, attend des instructions.

### 4.5. Envoi du work

```http
POST /api/admin/sessions/{session_id}/agents/{instance_id}/work
{
  "_agflow_correlation_id": "corr-uuid",
  "_agflow_action_execution_id": "exec-uuid",
  "instruction": {
    "task": "audit_pr",
    "repo": "acme/api",
    "pr_number": 1234
  }
}
```

Retour `202` : `{ "task_id": "uuid", … }`.

### 4.6. Exécution interne de l'agent

- L'agent reçoit le JSON sur stdin.
- Il consulte ses contrats GitHub (sous `workspace/docs/ctr/github/`).
- Il appelle le MCP `github-mcp` pour récupérer la PR via les tools.
- Il analyse le diff, génère un rapport markdown.
- Il émet sur stdout un event JSON : `{"kind": "result", "payload": {…}}`.

Cf. 05.

### 4.7. Réception du hook

agflow.docker met la `task` en `status=completed`, crée un `outbound_hook`. Le dispatcher signe et envoie :

```http
POST https://workflow.example.com/api/hooks/agflow
X-Agflow-Signature: …
X-Agflow-Hmac-Key-Id: wf-2026-05
X-Agflow-Event: task.completed

{
  "event": "task.completed",
  "task_id": "uuid",
  "agflow_correlation_id": "corr-uuid",
  "agflow_action_execution_id": "exec-uuid",
  "status": "completed",
  "result": { "issues": [...], "summary": "..." },
  ...
}
```

ag.flow vérifie la signature, traite le résultat, passe à l'étape suivante du workflow. Cf. 09.

### 4.8. Fermeture

À la fin du workflow, ag.flow ferme :

```http
DELETE /api/admin/sessions/{session_id}
```

Le runtime peut rester actif (l'utilisateur l'utilise encore via UI) ou être supprimé selon les règles de cycle de vie configurées dans ag.flow.

## Scénario 5 — Restauration après incident

**Acteur** : opérateur. **Objectif** : restaurer la base à 14h32 hier, après détection d'une corruption.

### 5.1. Vérifier la fenêtre PITR

`GET /api/admin/pitr/restore-window` :

```json
{
  "earliest": "2026-05-20T00:00:00Z",
  "latest":   "2026-05-26T11:45:23Z"
}
```

L'instant cible est dans la fenêtre. OK.

### 5.2. Créer un clone

`POST /api/admin/pitr/clones` :

```json
{ "target_time": "2026-05-25T14:32:00Z" }
```

Retour : `{ "clone_id": "uuid" }`. Le worker provisionne en background.

### 5.3. Suivre le clone

`GET /api/admin/pitr/clones/active` toutes les 5 s jusqu'à `status=ready`. Reçoit `pgweb_url` pour explorer la base restaurée.

### 5.4. Investigation

L'opérateur ouvre `pgweb_url`, identifie les enregistrements à récupérer, exporte les données voulues (CSV via pgweb ou requêtes SQL ciblées).

### 5.5. Application sur la prod

L'opérateur applique manuellement les corrections sur la prod (UPDATE SQL ciblés via psql ou via l'API si applicable). **Pas de bascule complète sur le clone** — le clone est en lecture seule, destiné à l'investigation, pas à devenir la nouvelle prod.

### 5.6. Extension si nécessaire

Si l'investigation prend plus de 24 h : `POST /api/admin/pitr/clones/active/extend` pour ajouter 24 h.

### 5.7. Terminaison

À la fin : `DELETE /api/admin/pitr/clones/active` libère les ressources. Cf. 10.

## Scénario 6 — Migration de la configuration via git-sync

**Acteur** : admin. **Objectif** : reproduire la configuration de la prod sur un environnement de staging.

### 6.1. Configurer git-sync en prod

`PUT /api/admin/git-sync/config` (prod) :

```json
{
  "repo_url": "git@github.com:acme/agflow-config.git",
  "auth_mode": "ssh_key",
  "auth_secret_ref": "${vault://api:GIT_SYNC_DEPLOY_KEY}",
  "branch": "main",
  "selected_tables": ["agents", "roles", "documents", "templates", "products", "mcp_servers", "skills", "discovery_services"],
  "excluded_columns": { "agents": ["updated_at"], "roles": ["updated_at"] },
  "cron_enabled": true,
  "cron_expr": "0 2 * * *"
}
```

### 6.2. Export initial

`POST /api/admin/git-sync/export` : exporte les tables sélectionnées vers `git@github.com:acme/agflow-config.git` sur branche `main`. Retour `{ "sha": "abc…", "tables_count": 8 }`.

### 6.3. Configurer git-sync sur le staging (autre instance d'agflow.docker)

Même endpoint, mêmes paramètres, mais sur l'instance staging. La staging clone le repo.

### 6.4. Preview import sur staging

`POST /api/admin/git-sync/preview-import` :

```json
{
  "tables": [
    { "table": "agents",    "to_insert": 12, "to_update": 0, "to_delete": 0 },
    { "table": "roles",     "to_insert": 8,  "to_update": 0, "to_delete": 0 },
    { "table": "documents", "to_insert": 45, "to_update": 0, "to_delete": 0 }
  ]
}
```

### 6.5. Import

`POST /api/admin/git-sync/import` applique. Retour : `{ "rows_inserted": 65, "rows_updated": 0, "rows_deleted": 0 }`.

L'instance staging a maintenant la même configuration que la prod, sans avoir touché à la DB autrement. Les **secrets** ne sont pas synchronisés (seul les refs, pas leurs valeurs) — il faut que Harpocrate côté staging ait des valeurs pour les mêmes refs. Cf. 10.

## Scénario 7 — Audit et debug d'une session échouée

**Acteur** : opérateur. **Objectif** : comprendre pourquoi un work a échoué.

### 7.1. Localiser la task

Via l'UI M7 supervision, ou via `GET /api/admin/supervision/instances?status=error` puis drill-down. Récupérer le `task_id`.

### 7.2. Détail de la task

`GET /api/admin/tasks/{task_id}` :

```json
{
  "task_id": "uuid",
  "status": "failed",
  "error": {
    "code": "agent_error",
    "message": "Tool call failed: github.get_pr returned 404",
    "details": { "tool": "github.get_pr", "response_status": 404 }
  },
  "started_at": "…",
  "completed_at": "…"
}
```

Cf. 05.

### 7.3. Logs de l'agent

`GET /api/admin/sessions/{session_id}/agents/{instance_id}/logs?limit=500` : récupère les 500 dernières lignes du container.

### 7.4. Messages échangés

`GET /api/admin/sessions/{session_id}/agents/{instance_id}/messages` : lit l'historique des messages in/out.

### 7.5. Files du workspace

`GET /api/admin/sessions/{session_id}/agents/{instance_id}/files?path=docs/ctr/github/` : vérifier que les contrats GitHub étaient bien rendus.

### 7.6. Logs Loki

Via Grafana (`https://log.yoops.org`) avec le filtre :

```
{agflow_instance_id="<uuid>"} | json
```

retrouve les logs structlog du container + ceux du backend pendant cette task.

### 7.7. Hypothèses et correction

- Si `404 GitHub` → vérifier que le token GitHub est valide (test du provider).
- Si la PR existe → vérifier l'URL utilisée (peut-être un `base_url` désynchronisé dans le contrat).
- Si l'agent n'a pas lu son contrat → vérifier que la régénération du workspace est récente (`GET /api/admin/agents/{id}/generated`).

L'opérateur corrige le problème root cause et relance le workflow côté ag.flow ou re-trigger le step manuellement.

## Tableau de référence rapide — quelle action, quel module

| Besoin | Fichier de référence |
|---|---|
| Comprendre ce qu'est la plateforme | 00, 01 |
| Saisir l'architecture technique | 02 |
| Lire le schéma DB | 03 |
| Comprendre un module admin | 04 + 13 + 14 |
| Comprendre comment un agent exécute du travail | 05 |
| Déployer une instance projet | 06 |
| Sécuriser ou auditer | 07 |
| Intégrer un client externe | 08 |
| Intégrer ag.flow ou un orchestrateur similaire | 09 |
| Sauvegarder ou restaurer | 10 |
| Observer ou debugger | 11 |
| Contribuer au code | 12 |
| Voir un cas concret de bout en bout | 15 (ce fichier) |
