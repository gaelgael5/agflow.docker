# 08 — API publique V1

L'API publique sous `/api/v1/*` est l'**interface contractuelle** d'agflow.docker pour les clients externes : workflows ag.flow, scripts intégrateurs, agents batch, déploiements de tests.

Elle est rétro-compatible dans sa famille V1 ; toute évolution incompatible passera par une V2 distincte. Les endpoints administratifs sous `/api/admin/*` ne sont **pas** publics et peuvent évoluer sans préavis.

## Conventions

### Authentification

Toutes les routes V1 nécessitent un header `Authorization: Bearer agfd_<prefix>_<secret>` valide (clé API native, cf. module 07).

Exception : `GET /api/v1/scopes` retourne la liste des scopes disponibles sans authentification (utilitaire d'introspection).

### Format des réponses

- Toutes les réponses succès sont en JSON UTF-8.
- Les codes d'erreur HTTP standards sont utilisés :

| Code | Signification |
|---|---|
| 200 | OK |
| 201 | Created |
| 202 | Accepted (asynchrone — la ressource sera créée plus tard) |
| 204 | No Content (succès sans corps) |
| 400 | Bad request (payload mal formé) |
| 401 | Unauthorized (clé API manquante / invalide / révoquée / expirée) |
| 403 | Forbidden (scope insuffisant) |
| 404 | Not Found |
| 409 | Conflict (état incompatible, ex: ressource déjà existante) |
| 422 | Unprocessable Entity (validation Pydantic) |
| 429 | Too Many Requests (rate limit dépassé) |
| 500 | Internal Server Error |

- Les erreurs 422 retournent un `HTTPValidationError` Pydantic standard.
- Les erreurs métier 400 / 404 / 409 retournent `{ "detail": "message lisible" }`.

### Identifiants

- Tous les identifiants exposés sont des **UUID v4** générés serveur, sauf certains slugs métier (`dockerfile_id`, `role_id`, `slug` de produits) qui sont des chaînes alphanumériques choisies par l'administrateur.
- Les `task_id`, `session_id`, `runtime_id` sont systématiquement UUID v4.

### Pagination

Les endpoints qui peuvent renvoyer de nombreux éléments utilisent un pattern `limit` + `offset` :

```
GET /api/v1/dockerfiles?limit=50&offset=0
```

`limit` typique 50 (max 500), `offset` ≥ 0. Le client utilise `offset += limit` pour paginer.

### Pas de webhooks de discovery

Cette API ne propose pas de mécanisme de webhook universel pour s'abonner à des événements. Pour recevoir des notifications de fin de tâche, le client fournit un `callback_url` à la création de session (cf. module 05).

## Périmètre de l'API V1

Les routes V1 couvrent **trois familles** d'objets :

1. **Sessions, agents, work** : la voie principale pour exécuter du travail.
2. **Projets et runtimes** : lecture de catalogue + provisioning d'instances.
3. **Dockerfiles, containers, launched tasks** : voie alternative pour les tâches one-shot sans session persistante (debug, CI).

Les routes de configuration (M0-M5) ne sont **pas** publiques.

## Référence rapide

### Sessions

```
POST   /api/v1/sessions                          Créer une session
GET    /api/v1/sessions/{id}                     Détail
PATCH  /api/v1/sessions/{id}/extend              Prolonger
DELETE /api/v1/sessions/{id}                     Fermer
GET    /api/v1/sessions/{id}/messages            Messages de toute la session
```

### Agents dans une session

```
POST   /api/v1/sessions/{id}/agents              Instancier
GET    /api/v1/sessions/{id}/agents              Lister
DELETE /api/v1/sessions/{id}/agents/{iid}        Détruire une instance
```

### Messages et streaming

```
POST /api/v1/sessions/{id}/agents/{iid}/message  Envoyer un message
GET  /api/v1/sessions/{id}/agents/{iid}/messages Lister les messages
GET  /api/v1/sessions/{id}/agents/{iid}/logs     Logs raw du container
GET  /api/v1/sessions/{id}/agents/{iid}/files    Browser de fichiers
```

### Agents catalogue (lecture)

```
GET  /api/v1/agents                              Lister les agents disponibles
GET  /api/v1/agents/{id}                         Détail (composition complète)
POST /api/v1/agents/{id}/generate                Régénérer les fichiers de runtime
GET  /api/v1/agents/{id}/generated               Lister les fichiers générés
```

### Rôles (lecture)

```
GET /api/v1/roles                                Lister
GET /api/v1/roles/{id}                           Détail avec sections + documents
```

### Projets et runtimes

```
GET    /api/v1/projects                          Lister les ressources projets disponibles
GET    /api/v1/projects/{id}                     Détail
POST   /api/v1/projects/{id}/runtimes            Créer une instance projet (provisioning async)
GET    /api/v1/runtimes                          Lister les runtimes accessibles
GET    /api/v1/runtimes/{id}                     Détail
DELETE /api/v1/runtimes/{id}                     Décommissionner
GET    /api/v1/runtimes/{id}/endpoints           Liste des endpoints (host, ports) exposés
```

### Dockerfiles et containers

```
GET    /api/v1/dockerfiles                       Lister
POST   /api/v1/dockerfiles                       Créer
GET    /api/v1/dockerfiles/{id}                  Détail
PUT    /api/v1/dockerfiles/{id}                  Mettre à jour
DELETE /api/v1/dockerfiles/{id}                  Supprimer
POST   /api/v1/dockerfiles/{id}/build            Lancer un build async
GET    /api/v1/dockerfiles/{id}/builds           Historique des builds
GET    /api/v1/dockerfiles/{id}/export           Export ZIP
POST   /api/v1/dockerfiles/{id}/import           Import ZIP

GET    /api/v1/dockerfiles/{id}/files            Lister les fichiers (content base64)
POST   /api/v1/dockerfiles/{id}/files            Créer un fichier (content base64)
PUT    /api/v1/dockerfiles/{id}/files/{file_id}  Mettre à jour (content base64)
DELETE /api/v1/dockerfiles/{id}/files/{file_id}  Supprimer

GET    /api/v1/dockerfiles/{id}/params           Lire les parameters
PUT    /api/v1/dockerfiles/{id}/params           Remplacer les parameters
PATCH  /api/v1/dockerfiles/{id}/params/{section} Modifier une section des parameters

POST   /api/v1/dockerfiles/{id}/run              Lancer un container
POST   /api/v1/dockerfiles/{id}/task             Lancer une tâche one-shot (stream NDJSON)
GET    /api/v1/containers                        Lister tous les containers managés
POST   /api/v1/containers/{cid}/stop             Arrêter un container
```

### Launched tasks (one-shot)

```
GET    /api/v1/launched?dockerfile_id=…          Lister les tasks one-shot
DELETE /api/v1/launched/{task_id}                Arrêter une task
```

### Introspection

```
GET /api/v1/scopes                               Lister les scopes disponibles (pas d'auth requise)
```

## Cas d'usage détaillés

### Cas 1 : ag.flow pilote une étape de workflow

```python
# 1. Créer un runtime pour le projet (resources nécessaires)
runtime = post("/api/v1/projects/<proj_id>/runtimes", json={
  "environment": "prod",
  "groups": { "<group_id>": { "replica_count": 1 } },
  "user_secrets": { "GITHUB_TOKEN": "ghp_…" },
})
# runtime.status = "provisioning"

# 2. Poller jusqu'à ready
while True:
    rt = get(f"/api/v1/runtimes/{runtime.id}")
    if rt.status in ("ready", "failed"):
        break
    sleep(2)

# 3. Ouvrir une session attachée au runtime
session = post("/api/v1/sessions", json={
  "duration_seconds": 3600,
  "project_id": runtime.id,  # ou via l'endpoint admin avec project_runtime_id explicite
})

# 4. Instancier un agent
ag = post(f"/api/v1/sessions/{session.id}/agents", json={
  "agent_id": "claude-code",
  "count": 1,
  "mission": "audit-pr",
})
instance_id = ag.instance_ids[0]

# 5. Envoyer du work
work = post(f"/api/v1/sessions/{session.id}/agents/{instance_id}/message", json={
  "kind": "instruction",
  "payload": {"instruction": "Audite la PR #1234 du dépôt acme/api"},
})

# 6. Attendre le résultat
while True:
    msgs = get(f"/api/v1/sessions/{session.id}/agents/{instance_id}/messages?direction=out&kind=result")
    if msgs:
        return msgs[-1].payload
    sleep(5)

# 7. Fermer
delete(f"/api/v1/sessions/{session.id}")
```

### Cas 2 : analyse batch one-shot sans session

```python
# Lancer une task one-shot et stream les events NDJSON
response = post(
  "/api/v1/dockerfiles/code-analyzer/task",
  json={
    "instruction": "Analyse les fichiers Python du commit acme/api@abc123",
    "timeout_seconds": 600,
    "secrets": { "GITHUB_TOKEN": "ghp_…" },
  },
  stream=True,
)
for line in response.iter_lines():
    event = json.loads(line)
    if event["kind"] == "result":
        return event["payload"]
    elif event["kind"] == "error":
        raise RuntimeError(event["payload"])
```

### Cas 3 : provisioner un projet avec hook signé

```python
# 1. Créer la clé HMAC (côté admin, hors API V1)
# POST /api/admin/hmac-keys → {"key_id": "wf-2026-05", "secret_hex": "…"}

# 2. Côté ag.flow : créer la session avec callback
session = post("/api/admin/sessions", json={
  "api_key_id": "<uuid>",
  "duration_seconds": 7200,
  "project_runtime_id": "<uuid>",
  "callback_url": "https://workflow.example.com/hooks/agflow",
  "callback_hmac_key_id": "wf-2026-05",
})

# 3. Envoyer un work avec correlation_id
work = post(f"/api/admin/sessions/{session.session_id}/agents/<iid>/work", json={
  "_agflow_correlation_id": "uuid-corr-1",
  "_agflow_action_execution_id": "uuid-exec-1",
  "instruction": { "tool": "github.search_repos", "query": "fastapi" },
})
# Le serveur retourne 202 avec task_id

# 4. À la fin de la task, ag.flow reçoit :
#    POST https://workflow.example.com/hooks/agflow
#    X-Agflow-Signature: <hex>
#    X-Agflow-Hmac-Key-Id: wf-2026-05
#    X-Agflow-Event: task.completed
#    {"task_id": "…", "agflow_correlation_id": "uuid-corr-1", "status": "completed", "result": {…}}
```

## Endpoints publics importants — détails

### POST `/api/v1/sessions`

**Auth** : scope `sessions:write`.

Crée une session « légère » (sans `api_key_id` ni `callback_url` explicites — l'API key utilisée pour l'appel devient l'owner, pas de callback).

Body : `SessionCreate` (`name?`, `duration_seconds`, `project_id?`).

Retour `201` : `SessionOut`.

### POST `/api/v1/sessions/{id}/agents`

**Auth** : scope `agents:write`.

Body : `AgentInstanceCreate` (`agent_id`, `count`, `labels?`, `mission?`).

Retour `201` : `AgentInstanceCreated.instance_ids`.

### POST `/api/v1/sessions/{id}/agents/{instance_id}/message`

**Auth** : scope `messages:write`.

Body : `MessageIn` (`kind` enum, `payload`, `route_to?`).

Retour `201` : `{ "message_id": "…", "task_id": "…" }` (task_id présent quand kind=`instruction`).

### POST `/api/v1/projects/{project_id}/runtimes`

**Auth** : scope `runtimes:write`.

Body : `RuntimeCreate` :

```json
{
  "environment": "prod" | "dev" | …,
  "groups": {
    "<group_id>": { "replica_count": 1 },
    …
  },
  "user_secrets": {
    "GITHUB_TOKEN": "ghp_…",
    "SLACK_BOT_TOKEN": "xoxb-…"
  }
}
```

Retour `201` : `RuntimeOut` avec `status=provisioning`.

Le provisioning est asynchrone — un worker crée le `project_runtime` et ses `project_group_runtimes`, exécute les `before` scripts, déploie les conteneurs et exécute les `after` scripts. Le client poll `GET /api/v1/runtimes/{id}` pour suivre.

### GET `/api/v1/runtimes/{id}/endpoints`

**Auth** : scope `runtimes:read`.

Retourne pour chaque container du runtime :

```json
[
  {
    "container_name": "user1-wiki",
    "image": "outlinewiki/outline:0.79",
    "host": "192.168.10.158",
    "ports": [
      { "container": 3000, "host": 30080, "protocol": "tcp" }
    ],
    "status": "running",
    "raw_status": "Up 3 hours"
  },
  …
]
```

Très utile pour qu'un agent dans la session sache à quelle URL adresser ses requêtes au wiki / au repo / à la DB / etc.

### POST `/api/v1/dockerfiles/{id}/task`

**Auth** : scope `agents:write` (ou `tasks:write` selon la config).

Body : `TaskRequest` (`instruction`, `timeout_seconds`, `model?`, `secrets`).

Retour : flux **NDJSON** (chunked transfer encoding). Chaque ligne est un événement JSON :

```
{"event": "task.started", "task_id": "uuid"}
{"event": "container.started", "container_name": "…"}
{"event": "agent.output", "stream": "stdout", "line": "…"}
{"event": "agent.output", "stream": "stderr", "line": "…"}
{"event": "task.completed", "exit_code": 0, "result": {…}}
```

Le client lit ligne par ligne et termine quand il reçoit `task.completed` ou `task.failed`.

## Versioning et compatibilité

### Politique

- Toute évolution **rétro-compatible** est intégrée sans bumper de version (ajout de champ optionnel, ajout d'endpoint, ajout de valeur d'enum).
- Toute évolution **incompatible** passe par une **V2** distincte sous `/api/v2/*`. La V1 reste maintenue en parallèle pendant au moins 6 mois après la sortie de V2.
- Les changements de comportement non visibles dans la signature (par ex. : changement de l'algorithme de retry, du timing par défaut) peuvent passer en V1 mais sont documentés dans le changelog.

### Détection de version

Le header `X-Agflow-Version: 0.1.0` est renvoyé sur chaque réponse. Le client peut s'y fier pour adapter ses appels aux fixes de bug ponctuels.

### OpenAPI

L'OpenAPI complet à jour est servi à `GET /openapi.json`. La documentation interactive est à `GET /docs` (Swagger UI) et `GET /redoc` (Redoc). Ces deux dernières routes sont publiques (lecture seule).
