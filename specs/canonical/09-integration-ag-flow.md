# 09 — Intégration avec le workflow externe ag.flow

agflow.docker n'est pas conçu comme un système isolé : il est destiné à être piloté par un **workflow service externe** appelé **ag.flow** qui orchestre des workflows métier impliquant plusieurs agents IA et plusieurs ressources conteneurisées.

Cette section décrit le **contrat d'intégration** entre les deux systèmes : terminologie partagée, séquence d'appels, conventions de corrélation, format des hooks signés.

## Modèle conceptuel partagé

```
   ag.flow (workflow service)             agflow.docker
   ─────────────────────────              ───────────────
   Workflow                               -
     └── Step                             -
           ├──> action "spawn"        →   Crée un project_runtime
           ├──> action "session"      →   Crée une session
           ├──> action "agent"        →   Instancie un agent
           ├──> action "work"         →   Envoie un work
           └─ ← hook task_completed   ←   Notifie la fin du work
```

ag.flow décide **quand** et **dans quel ordre** les actions ont lieu. agflow.docker exécute, expose les ressources, garde l'état persistant et notifie les fins de tâche.

## Vocabulaire partagé

Le contrat utilise systématiquement les termes ci-dessous. Pour éviter la confusion entre vocabulaire interne et vocabulaire contractuel, **cette spec utilise le vocabulaire interne** ; ag.flow utilise le vocabulaire contractuel. Le glossaire (01) trace les correspondances.

| Contrat (ag.flow) | Interne (agflow.docker) | Description |
|---|---|---|
| `project` | ressource projet (`projects`) | Template de projet versionné |
| `project_runtime` | instance projet (`project_runtimes`) | Instance déployée |
| `resource` | ressource d'un runtime | Un service conteneurisé concret avec sa connexion |
| `session` | session (`sessions`) | Contexte d'exécution temporel |
| `agent` | définition d'agent (`agents`) | Composition versionnée |
| `agent_instance` | instance d'agent (`agents_instances`) | Conteneur d'agent en cours |
| `work` | work (`tasks` kind=`agent_work`) | Unité de travail asynchrone |
| `correlation_id` | `agflow_correlation_id` | UUID v4 traçable bout-en-bout |
| `action_execution_id` | `agflow_action_execution_id` | UUID v4 du step ag.flow associé |
| `hook` | outbound_hook signé HMAC | Notification de fin de work |

## Toutes les ressources sont des UUID v4

Le contrat **n'utilise jamais** de préfixes typés (pas de `pi_`, `wf_`, `sess_`, etc.) : tous les identifiants sont des UUID v4 nus. Cela permet à ag.flow d'utiliser ses propres conventions pour les UUID qu'il génère sans contrainte côté agflow.docker.

## Séquence type

### Phase 1 — Discovery (avant tout workflow)

ag.flow connaît la plateforme via sa configuration. Il liste les projets disponibles :

```
GET /api/admin/projects/v5/list
Authorization: Bearer agfd_…
```

Retour : array de `ProjectSummaryV5` :

```json
[
  {
    "project_id": "uuid",
    "name": "Espace de travail intégré",
    "description": "Wiki + repo + tasks + assistant IA",
    "resources_summary": [
      { "type": "wiki",     "label": "Outline" },
      { "type": "code",     "label": "Gitea" },
      { "type": "tasks",    "label": "Vikunja" },
      { "type": "assistant","label": "Claude Code" }
    ]
  },
  …
]
```

ag.flow présente cette liste à l'utilisateur dans son builder de workflow, qui choisit un projet. Le détail d'un projet :

```
GET /api/admin/projects/v5/{project_id}
```

renvoie le même format avec plus d'informations.

### Phase 2 — Provisioning d'une instance projet

Quand un workflow démarre et a besoin de ses ressources, ag.flow appelle :

```
POST /api/admin/projects/{project_id}/runtimes
Authorization: Bearer agfd_…
```

Retour `202 Accepted` :

```json
{
  "runtime_id": "uuid",
  "status": "provisioning"
}
```

Le provisioning se fait en background côté agflow.docker. ag.flow peut soit poller, soit attendre un événement (cf. ci-dessous).

### Phase 3 — Suivi du provisioning

Polling :

```
GET /api/admin/project-runtimes/{runtime_id}/resources
```

Retour `RuntimeResourcesResponse` :

```json
{
  "runtime_id": "uuid",
  "status": "provisioning | ready | partially_ready | failed",
  "resources": [
    {
      "resource_id": "uuid-stable-par-runtime",
      "type": "wiki",
      "name": "Outline interne",
      "status": "provisioning | ready | failed | pending_setup",
      "connection_params": {
        "url": "https://outline-user42.example.com",
        "admin_email": "admin@example.com",
        "admin_password_ref": "${vault://api:runtimes/<runtime_id>/outline_admin}"
      },
      "mcp_bindings": [
        {
          "mcp_server_id": "uuid",
          "name": "outline-search",
          "transport": "stdio"
        }
      ],
      "setup_steps": [
        { "name": "wait_for_db", "status": "completed" },
        { "name": "create_admin", "status": "completed" },
        { "name": "configure_oidc", "status": "completed" }
      ],
      "error_message": null
    },
    …
  ]
}
```

Statuts attendus :
- `provisioning` : le worker est en train de déployer le runtime.
- `ready` : tous les conteneurs sont up, tous les setup_steps sont passés.
- `partially_ready` : au moins une ressource est `ready` mais au moins une est `failed` ou `pending_setup`.
- `failed` : provisioning définitivement échoué ; ag.flow lit `error_message` de chaque resource pour reporter à l'utilisateur.

### Phase 4 — Création de session

Une fois le runtime ready (ou avant si l'agent ne nécessite pas les ressources), ag.flow ouvre une session :

```
POST /api/admin/sessions
Authorization: Bearer agfd_…
{
  "api_key_id": "uuid de la clé d'ag.flow",
  "duration_seconds": 7200,
  "project_runtime_id": "<runtime_id obtenu plus haut>",
  "callback_url": "https://ag.flow.example.com/api/hooks/agflow",
  "callback_hmac_key_id": "wf-2026-05"
}
```

Retour : `{ "session_id": "uuid", "expires_at": "ISO 8601" }`.

### Phase 5 — Instanciation d'agents

```
POST /api/admin/sessions/{session_id}/agents
{
  "agent_id": "claude-code",
  "count": 1,
  "labels": {
    "workflow_id": "<ag.flow workflow uuid>",
    "step_id": "<ag.flow step uuid>"
  },
  "mission": "audit-pr"
}
```

Retour : `{ "agent_instance_ids": ["uuid", …] }`.

Les `labels` sont libres et permettent à ag.flow de retrouver ses instances en cas de crash.

### Phase 6 — Envoi de work

```
POST /api/admin/sessions/{session_id}/agents/{instance_id}/work
{
  "_agflow_correlation_id": "uuid généré par ag.flow pour ce work",
  "_agflow_action_execution_id": "uuid du step en cours dans ag.flow",
  "instruction": {
    "tool": "github.audit_pr",
    "owner": "acme",
    "repo": "api",
    "pr_number": 1234
  }
}
```

Retour `202 Accepted` :

```json
{
  "task_id": "uuid",
  "_agflow_correlation_id": "uuid (echo)",
  "_agflow_action_execution_id": "uuid (echo)"
}
```

ag.flow stocke `task_id` ↔ ses propres identifiants pour le mapping retour.

### Phase 7 — Réception du hook de fin

Quand la task atteint un état terminal (`completed`, `failed`, `cancelled`), agflow.docker envoie :

```http
POST https://ag.flow.example.com/api/hooks/agflow HTTP/1.1
Content-Type: application/json
X-Agflow-Hmac-Key-Id: wf-2026-05
X-Agflow-Signature: <hex(HMAC-SHA256(secret, body))>
X-Agflow-Event: task.completed
X-Agflow-Correlation-Id: <agflow_correlation_id>

{
  "event": "task.completed",
  "task_id": "uuid",
  "session_id": "uuid",
  "agent_instance_id": "uuid",
  "agflow_correlation_id": "uuid",
  "agflow_action_execution_id": "uuid",
  "status": "completed",
  "result": {
    "pr_summary": "…",
    "issues_found": 3,
    "files_changed": 12
  },
  "started_at": "2026-05-25T14:00:00Z",
  "completed_at": "2026-05-25T14:03:42Z"
}
```

Pour les échecs :

```json
{
  "event": "task.completed",
  "status": "failed",
  "error": {
    "code": "timeout" | "agent_error" | "internal" | …,
    "message": "string lisible",
    "details": { … }
  },
  …
}
```

### Phase 8 — Fermeture

À la fin du workflow (ou expiration de TTL), ag.flow ferme :

```
DELETE /api/admin/sessions/{session_id}
DELETE /api/admin/group-runtimes/{group_runtime_id}   # un par groupe du runtime
```

Le décommissionnement est idempotent. Les instances projet peuvent aussi être conservées entre workflows : c'est ag.flow qui décide.

## Cas de récupération après crash d'ag.flow

C'est le cas d'usage critique du contrat : ag.flow crashe entre l'envoi d'un work (étape 6) et la réception du hook (étape 7). Au redémarrage, il a perdu son état runtime mais conserve son journal persisté avec les `agflow_correlation_id` et `agflow_action_execution_id` des works qu'il avait lancés.

### Reconnexion

Pour chaque work « en attente » :

```
GET /api/admin/tasks/{task_id}
```

retourne `TaskStatusResponse` :

```json
{
  "task_id": "uuid",
  "kind": "agent_work",
  "status": "pending | running | completed | failed | cancelled",
  "session_id": "uuid",
  "agent_instance_id": "uuid",
  "agflow_correlation_id": "uuid",
  "agflow_action_execution_id": "uuid",
  "result": { … } | null,
  "error": { … } | null,
  "started_at": "ISO 8601" | null,
  "completed_at": "ISO 8601" | null,
  "created_at": "ISO 8601"
}
```

ag.flow peut donc rattraper son état :
- `status=completed` → consommer `result`.
- `status=failed` → consommer `error`.
- `status=running` ou `pending` → continuer d'attendre (le hook de fin sera renvoyé).

### Idempotence des hooks

Le dispatcher de agflow.docker retry les hooks en cas d'échec réseau ou de réponse 5xx. Le destinataire **doit** être idempotent sur `(task_id, event)` :
- Première réception → traiter, ack 200.
- Réceptions suivantes du même hook → ack 200 sans traiter à nouveau.

## Erreurs et codes du contrat

### Codes HTTP standards

| Code | Sens dans le contrat |
|---|---|
| 200 / 201 | OK |
| 202 | Provisioning ou work démarré (async) |
| 400 / 422 | Payload mal formé ou validation Pydantic |
| 401 | Clé API agflow.docker invalide / expirée / révoquée |
| 403 | Scope insuffisant |
| 404 | Ressource introuvable (session, runtime, task, etc.) |
| 409 | État incompatible (ex: création de session sur runtime non ready) |
| 500 | Erreur interne agflow.docker |

### Codes d'erreur métier dans les hooks `task.completed`

| `error.code` | Sens |
|---|---|
| `timeout` | Le work a dépassé le `timeout_seconds` de l'agent |
| `agent_error` | L'agent a émis un kind=`error` (erreur applicative remontée) |
| `unresolved_placeholder` | Une variable nécessaire au lancement de l'agent n'a pas pu être résolue |
| `container_failed` | Le container Docker s'est arrêté avec exit code ≠ 0 avant l'envoi d'un result |
| `session_expired` | La session a expiré pendant que la task tournait |
| `cancelled` | Cancel reçu (depuis l'API ou interne) |
| `internal` | Erreur interne agflow.docker |

`error.details` contient les informations spécifiques (variable concernée, stderr du container, etc.).

## Versionnement du contrat

Le contrat est versionné en **v5**. Toute évolution incompatible passera par v6 sans casser v5 : les routes admin actuelles resteront en `/api/admin/*` tandis que la v6 introduira `/api/admin/v6/*`.

Les évolutions rétro-compatibles (ajout de champ optionnel, ajout d'event) se font dans v5 sans changement de path.

### Détection

Le header `X-Agflow-Version: 0.1.0` (version du backend) est renvoyé sur toutes les réponses. La version du contrat est implicite (v5 actuellement).

## Sécurité du contrat

### Vue d'ensemble

| Composant | Mécanisme |
|---|---|
| ag.flow → agflow.docker | Clé API native `agfd_…` dans `Authorization: Bearer` |
| agflow.docker → ag.flow (hooks) | Signature HMAC-SHA256 dans `X-Agflow-Signature` |
| Transport | TLS valide via Cloudflare Tunnel des deux côtés |
| Idempotence | Clé `(task_id, event)` du côté destinataire des hooks |

### Rotation des clés

- **API key d'ag.flow** : créée et révoquée par l'admin d'agflow.docker (M7). ag.flow doit mettre à jour sa configuration en cas de rotation.
- **Clé HMAC** : créée par l'admin d'agflow.docker (M7), partagée out-of-band avec ag.flow (typiquement via Harpocrate côté ag.flow aussi). Rotation par soft-delete : créer une nouvelle clé, mettre à jour ag.flow, soft-delete l'ancienne après confirmation.

### Audit

Tous les appels admin sont loggés en JSON structlog avec `event=admin.api.request`, `user_id` (extrait du JWT) ou `api_key_id` (extrait du Bearer), `path`, `method`, `status_code`, `duration_ms`. ag.flow peut être tracé par son `api_key_id` constant.

## Différences entre l'API admin et l'API publique

ag.flow utilise l'API **admin** (`/api/admin/sessions`, `/api/admin/sessions/{id}/agents`, `/api/admin/sessions/{id}/agents/{iid}/work`, `/api/admin/tasks/{id}`, `/api/admin/projects/v5/list`, `/api/admin/project-runtimes/{id}/resources`).

L'API **publique** V1 (`/api/v1/*`) propose un sous-ensemble simplifié (sans `_agflow_correlation_id` / `_agflow_action_execution_id`, sans `callback_url` explicite, etc.) destiné aux clients qui ne sont **pas** un orchestrateur de workflow mais des consommateurs ad-hoc (scripts, agents batch, CI).

Le choix entre les deux dépend du besoin de corrélation :
- ag.flow ou tout autre orchestrateur qui doit reconnecter ses propres états → API admin v5.
- Script ad-hoc ou intégration légère → API publique V1.
