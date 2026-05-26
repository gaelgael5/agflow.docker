# 05 — Cycle d'exécution

Cette section décrit comment une **session** s'ouvre, comment des **agents** y sont instanciés, comment ils reçoivent et exécutent du **work**, et comment les **hooks** notifient la fin du travail. C'est le cœur opérationnel de la plateforme.

## Vue globale

```
   ┌──────────────────┐
   │  Client          │  (UI admin, ag.flow, script externe…)
   └────────┬─────────┘
            │ 1. POST /sessions
            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Session                                                   │
   │  - api_key_id  - project_runtime_id?  - callback_url?      │
   │  - status: active → closed | expired                       │
   └────────┬─────────────────────────────────────────────────┘
            │ 2. POST /sessions/{id}/agents
            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Agent instance (conteneur Docker en cours d'exécution)    │
   │  - status: idle → busy → idle | error → destroyed          │
   └────────┬─────────────────────────────────────────────────┘
            │ 3. POST /work
            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Task (asynchrone)                                         │
   │  - status: pending → running → completed | failed | …      │
   │  - agflow_correlation_id, agflow_action_execution_id       │
   └────────┬─────────────────────────────────────────────────┘
            │ 4. fin → outbound_hook signé HMAC
            ▼
   ┌──────────────────────────────────────────────────────────┐
   │  Client (POST sur callback_url + signature)                │
   └──────────────────────────────────────────────────────────┘
```

## 1. Ouverture de session

Endpoint admin : `POST /api/admin/sessions` (depuis l'UI ou un appel admin direct).
Endpoint public : `POST /api/v1/sessions` (depuis un client externe avec clé API native).

### Payload

```json
{
  "name": "string optionnel — libellé humain",
  "duration_seconds": 3600,                // entre 60 et 86400 (UI) ou 2 592 000 (admin)
  "project_id": "uuid optionnel — instance projet à attacher"
}
```

Pour la variante admin/v5 (`POST /api/admin/sessions` du workflow), le payload est plus complet :

```json
{
  "api_key_id": "uuid",
  "name": "string optionnel",
  "duration_seconds": 3600,
  "project_runtime_id": "uuid optionnel",
  "callback_url": "https://workflow.example.com/hooks/agflow",
  "callback_hmac_key_id": "wf-hook-key-1"
}
```

### Validation

- `api_key_id` doit pointer sur une clé non révoquée et non expirée.
- Si `project_runtime_id` est fourni, il doit appartenir à l'utilisateur propriétaire de l'`api_key`.
- Si `callback_url` est fourni, `callback_hmac_key_id` doit pointer sur une `hmac_keys` en statut `active`.

### Effet

Une ligne `sessions` est insérée avec `status='active'`, `created_at=now()`, `expires_at=now()+duration_seconds`. Le client reçoit `session_id` et `expires_at`.

### Extension

`PATCH /api/v1/sessions/{id}/extend` avec `duration_seconds` (60 s à 24 h) prolonge la session. Le serveur recalcule `expires_at` à partir de l'instant actuel.

### Fermeture

- **Explicite** : `DELETE /api/v1/sessions/{id}` (ou variante admin avec `?force=true` pour fermer les sessions tierces). Statut → `closed`. Les agents instances de la session sont marqués `destroyed`, leurs containers Docker stoppés.
- **Implicite** : le worker `session_reaper` fait une passe régulière sur les sessions dont `expires_at < now()` et les passe en `expired` ; effet identique.

## 2. Instanciation d'agents

Endpoint admin : `POST /api/admin/sessions/{id}/agents`.
Endpoint public : `POST /api/v1/sessions/{id}/agents`.

### Payload

```json
{
  "agent_id": "slug ou uuid d'un agent du catalogue",
  "count": 1,                       // ≥ 1, ≤ 50 (public) ou 10 (admin)
  "labels": { "team": "ops", … },   // metadata libres
  "mission": "string optionnel — instruction libre attachée à toutes les instances créées"
}
```

### Effet

Pour chaque copie demandée :
1. Une ligne `agents_instances` est insérée avec `status='idle'`, `agent_id` (catalogue), `labels`, `mission`.
2. Un **container Docker** est créé via `aiodocker` en utilisant l'image construite par M1, en injectant :
   - Les fichiers de runtime générés par `agent_generator` : prompt, MCP config, skills, contracts (via mounts).
   - Le `.env` résolu (secrets Harpocrate, variables globales, variables de session).
   - Le réseau Docker : `bridge` par défaut, ou le réseau de l'instance projet si la session est liée à un `project_runtime`.
3. Le container démarre, exécute `entrypoint.sh`, attend des instructions sur stdin (mode `task` JSON par ligne).

Le client reçoit la liste des `instance_ids`.

### Destruction explicite

`DELETE /api/v1/sessions/{id}/agents/{instance_id}` : statut → `destroyed`, container arrêté gracefully puis retiré.

## 3. Envoi de work

L'agent instance est en attente. Le client envoie du **work** :

Endpoint admin : `POST /api/admin/sessions/{id}/agents/{instance_id}/work`.
Endpoint public : `POST /api/v1/sessions/{id}/agents/{instance_id}/message`.

### Payload public (forme libre)

```json
{
  "kind": "instruction",            // ou "cancel" / "event"
  "payload": { … },                 // contenu libre
  "route_to": "string optionnel"    // adresser le message à un autre agent de la session
}
```

### Payload admin / workflow v5

```json
{
  "_agflow_correlation_id": "uuid",
  "_agflow_action_execution_id": "uuid",
  "instruction": { … }              // objet JSON libre
}
```

Les deux champs `_agflow_*` sont préservés dans la `task` créée. Ils permettent à un orchestrateur externe de reconnecter une réponse tardive avec son propre état (typiquement en cas de crash de l'orchestrateur entre l'envoi et le hook de retour).

### Effet

1. Une ligne `agent_messages` est insérée (direction=`in`, kind=`instruction`).
2. Une ligne `tasks` est insérée (kind=`agent_work`, status=`pending`, `agent_instance_id`, `session_id`, `agflow_*_id`).
3. Un message JSON est écrit sur le stdin du container de l'agent.
4. L'agent passe en `status='busy'`.

Le serveur retourne immédiatement (202 Accepted) avec `task_id`. Le travail est asynchrone.

### Exécution

L'agent exécute son cycle interne (lecture du prompt, appels LLM, utilisation des MCP tools, écriture de fichiers, etc.) et émet des **events** sur stdout (un JSON par ligne).

Pendant l'exécution, le client peut :
- Lister les messages échangés : `GET /sessions/{id}/agents/{instance_id}/messages?kind=&direction=&limit=`.
- Lire les logs raw du container : `GET /sessions/{id}/agents/{instance_id}/logs?limit=500`.
- Parcourir les fichiers du workspace : `GET /sessions/{id}/agents/{instance_id}/files?path=`.
- Suivre la task : `GET /api/admin/tasks/{task_id}` (variante admin du contrat v5).

## 4. Fin de tâche et hooks

Quand l'agent émet un event terminal (`kind=result` ou `kind=error`) :

1. La `task` est mise à jour : `status='completed'` ou `'failed'`, `result` (ou `error`) populé, `completed_at=now()`.
2. L'instance d'agent repasse en `status='idle'` (sauf erreur fatale → `error`).
3. Si la session a un `callback_url`, un **outbound_hook** est créé.

### Forme du hook

```http
POST <callback_url> HTTP/1.1
Content-Type: application/json
X-Agflow-Signature: hex(HMAC-SHA256(secret, body))
X-Agflow-Hmac-Key-Id: <key_id de la session>
X-Agflow-Event: task.completed
X-Agflow-Correlation-Id: <uuid>

{
  "event": "task.completed",
  "task_id": "uuid",
  "session_id": "uuid",
  "agent_instance_id": "uuid",
  "agflow_correlation_id": "uuid",
  "agflow_action_execution_id": "uuid",
  "status": "completed" | "failed",
  "result": { … },                  // si completed
  "error": { … },                   // si failed
  "started_at": "ISO 8601",
  "completed_at": "ISO 8601"
}
```

### Émission

Le `hook_dispatcher_worker` consomme les `outbound_hooks` en statut `pending`, calcule la signature, fait l'appel HTTPS, persiste `response_code` et `status` (`delivered` / `failed`). Retry avec backoff exponentiel (1s, 5s, 30s, 5min, 1h) jusqu'à un max d'attempts configurable.

### Vérification côté destinataire

Le destinataire reconstitue la signature en utilisant son exemplaire du secret HMAC référencé par `X-Agflow-Hmac-Key-Id` :

```python
import hmac, hashlib
expected = hmac.new(secret.encode(), body_raw_bytes, hashlib.sha256).hexdigest()
if not hmac.compare_digest(expected, request.headers["X-Agflow-Signature"]):
    abort(401)
```

### Idempotence

Le destinataire doit pouvoir recevoir le même hook plusieurs fois (le dispatcher retry en cas d'échec réseau). La clé d'idempotence est `(task_id, event)`.

## 5. Cycle de vie des agents instances

| Statut | Signification | Transition typique |
|---|---|---|
| `idle` | Container démarré, aucun work en cours | → `busy` quand un work est envoyé |
| `busy` | Work en cours | → `idle` à la fin (success ou error non fatale) ou → `error` (erreur fatale) |
| `error` | Container a planté ou agent a émis une erreur fatale | Marquée pour `destroyed` à la prochaine passe ou destruction explicite |
| `destroyed` | Container stoppé et retiré ; ligne `agents_instances` conservée pour l'audit | Terminal |

### Timeouts

- **Idle agent timeout** : configurable par déploiement. Une instance `idle` qui dépasse ce timeout est `destroyed` par `agent_lifecycle_watcher`.
- **Work timeout** : chaque agent porte un `timeout_seconds` (défaut 3600). Si un work dépasse ce timeout, la task est passée en `failed` avec `error.code='timeout'` et un signal de cancel est envoyé au container.

## 6. Tâches one-shot hors session

Pour les cas où on veut juste exécuter une instruction et lire le résultat sans gérer une session :

Endpoint admin : `POST /api/admin/dockerfiles/{id}/task` ou `POST /api/admin/agents/{slug}/task`.
Endpoint public : `POST /api/v1/dockerfiles/{id}/task`.

Payload :

```json
{
  "instruction": "string non vide",
  "timeout_seconds": 600,
  "model": "string optionnel",
  "secrets": { "KEY": "valeur", … },
  "session_id": "string optionnel — pour groupage logique",
  "mode": "swarm"                     // ou "classic"
}
```

Effet :
1. Un container temporaire est créé depuis l'image du dockerfile / de l'agent.
2. L'instruction est envoyée sur stdin (avec le prompt système prepended).
3. Les events JSON émis sur stdout sont streamés à la réponse HTTP (newline-delimited).
4. Le container est retiré automatiquement à la sortie.

Une ligne `launched_tasks` est créée pour audit. Le client peut lister via `GET /api/v1/launched?dockerfile_id=…` et arrêter via `DELETE /api/v1/launched/{task_id}`.

Cette mécanique est utile pour les tâches batch, les agents stateless (ex: analyseurs de code en CI), ou les démos.

## 7. Inter-agent routing

Quand un message admin / public a un champ `route_to`, il est routé vers une autre instance d'agent de la même session (par `agent_id` slug, label match, etc.). Cela permet à un agent « orchestrateur » d'envoyer du work à un agent « spécialiste » dans la même session.

Le mécanisme repose sur `agent_message_delivery` : chaque message a une ligne de delivery pour chaque destinataire candidat, qui passe en `claimed` quand le destinataire lit le message, en `acked` quand il en a fini, ou en `failed` en cas d'erreur.

## 8. Récupération après crash

L'orchestrateur externe ag.flow peut crasher et redémarrer entre l'envoi d'un work et la réception du hook de fin. Pour pouvoir reconnecter, il consulte :

```
GET /api/admin/tasks/{task_id}
```

qui retourne le `TaskStatusResponse` :

```json
{
  "task_id": "uuid",
  "kind": "agent_work",
  "status": "pending | running | completed | failed | cancelled",
  "session_id": "uuid",
  "agent_instance_id": "uuid",
  "agflow_correlation_id": "uuid",
  "agflow_action_execution_id": "uuid",
  "result": { … },
  "error": { … },
  "started_at": "ISO 8601",
  "completed_at": "ISO 8601",
  "created_at": "ISO 8601"
}
```

L'orchestrateur peut donc, au redémarrage, lister ses corrélations en attente et faire le polling sur chaque `task_id`.
