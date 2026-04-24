# Couverture OpenAPI des scénarios fonctionnels

Audit effectué le **2026-04-24** contre le contrat OpenAPI exposé sur
`https://docker-agflow.yoops.org/openapi.json` (version déployée : `0.1.0`, 195 paths,
dont 43 publics sous `/api/v1/*`).

L'objectif est de confronter chaque scénario de `docs/functionnalTests/` aux endpoints
réellement exposés, de signaler les zones floues, et d'indiquer ce qui relève d'une
**mise à jour du scénario** ou d'un **ajout d'API à planifier**.

## Méthode

- Scope examiné : `/api/v1/*` (API publique destinée aux clients) + `/health`.
- Routes WebSocket non incluses dans l'OpenAPI : vérifiées par lecture directe du code (`backend/src/agflow/api/public/`).
- Schémas Pydantic inspectés pour les requêtes/réponses critiques (`SessionCreate`, `SessionOut`, `AgentInstanceCreate`, `MessageIn`, `AgentDetail`).

## Endpoints publics confirmés

### Sessions & agents instanciés (tag par défaut du router `public/sessions.py`)

| Endpoint | Couvert par | Remarques |
|----------|-------------|-----------|
| `POST /api/v1/sessions` → `SessionOut` | 01, 02, 03, 04, 05, 06, 07 | `project_id` optionnel côté request, exposé côté response |
| `GET /api/v1/sessions/{session_id}` | 06 | Renvoie `status`, `expires_at`, `closed_at` |
| `PATCH /api/v1/sessions/{session_id}/extend` | 06 | Clé du cas 06 |
| `DELETE /api/v1/sessions/{session_id}` | 01-07 | Close explicite |
| `POST /api/v1/sessions/{session_id}/agents` → `AgentInstanceCreated` | 01-07 | `count`, `mission` (string libre), `labels` |
| `GET /api/v1/sessions/{session_id}/agents` | non utilisé explicitement | Disponible pour cas futurs (liste instances d'une session) |
| `DELETE /api/v1/sessions/{session_id}/agents/{instance_id}` | implicite (close session) | Destruction ciblée d'une instance |

### Messages MOM

| Endpoint | Couvert par | Remarques |
|----------|-------------|-----------|
| `POST .../agents/{instance_id}/message` | 01-05, 08 | Body `MessageIn` : `kind` (enum), `payload`, `route_to` (inter-agent cas 03) |
| `GET .../agents/{instance_id}/messages` | 01, 02, 03, 05, 09 | Polling par instance |
| `GET /api/v1/sessions/{session_id}/messages` | 02, 05 | Polling session-level (multi-agents) |
| `GET .../agents/{instance_id}/logs` | 09 | Dump texte des logs |
| `GET .../agents/{instance_id}/files` | 09 | Navigation workspace |

**Enum `Kind`** : `instruction`, `cancel`, `event`, `result`, `error`. Les scénarios
parlent de "demande" et "résultat" génériquement ; à terme il serait utile de mapper
explicitement (demande = `instruction`, résultat final = `result`, intermédiaires = `event`).

### WebSockets publiques (hors OpenAPI, lues dans le code)

| Endpoint | Fichier source | Couvert par |
|----------|---------------|-------------|
| `WS /api/v1/sessions/{session_id}/stream` | `api/public/sessions.py:218` | 05 (streaming session-level) |
| `WS /api/v1/sessions/{session_id}/agents/{instance_id}/stream` | `api/public/messages.py:129` | 05 (streaming instance-level) |
| `WS /api/v1/sessions/{session_id}/agents/{instance_id}/exec` | `api/public/messages.py:269` | non utilisé (shell interactif, cas d'usage opérateur) |

**Gap de documentation** : FastAPI n'inclut pas les WebSockets dans OpenAPI par défaut. Un consommateur externe ne les découvre pas via `/openapi.json`. À compenser par une section dédiée dans la doc API (ou un schéma AsyncAPI).

### Découverte catalogue

| Endpoint | Couvert par | Remarques |
|----------|-------------|-----------|
| `GET /api/v1/scopes` | 07 | Catalogue des scopes (public sans auth probablement — à vérifier) |
| `GET /api/v1/roles` | 07 | Liste rôles blueprint |
| `GET /api/v1/roles/{role_id}` | 07 | Détail rôle avec sections |
| `GET /api/v1/agents` | 07 | Liste agents du catalogue |
| `GET /api/v1/agents/{agent_id}` → `AgentDetail` | 07 | Schéma riche : `role_id`, `mcp_bindings`, `skill_bindings`, `timeout_seconds`, `has_errors`, `image_status` |
| `POST /api/v1/agents/{agent_id}/generate` | non utilisé | Génère les fichiers runtime (prompt, .env, config MCP) |
| `GET /api/v1/agents/{agent_id}/generated` | non utilisé | Liste les fichiers générés |

### Tâches ponctuelles (task one-shot)

| Endpoint | Couvert par | Remarques |
|----------|-------------|-----------|
| `POST /api/v1/dockerfiles/{dockerfile_id}/task` | 08 | Description officielle : "Launch a one-shot task and stream events back". Content-type response = `application/json` (spec vague sur le streaming NDJSON, à clarifier). |
| `GET /api/v1/launched` | 08 implicite | Historique des tâches lancées |
| `DELETE /api/v1/launched/{task_id}` | non utilisé | Cancel d'une tâche en cours |

### Dockerfiles, params, files, containers

Les endpoints `GET/POST/PUT/DELETE /api/v1/dockerfiles/{id}/...` (9 endpoints pour le
CRUD dockerfile + 5 pour les fichiers + 3 pour les params + 3 pour les containers
one-shot) sont **exposés côté public mais non mobilisés par les scénarios actuels**.
Ils relèvent plus du parcours opérateur (voir scénarios `A*`) ou d'un cas d'usage
"gestion de builds" qui n'est pas encore rédigé.

## Écarts identifiés

### 1. Cas 04 — Ressources projet

Le scénario décrit l'agent qui **lit les specs et écrit le livrable** sur le projet via
l'acteur `Project`. Or :

- **Aucun endpoint public `/api/v1/projects/*`** : les projets sont gérés uniquement par `/api/admin/projects/*` (tag `admin-projects`).
- **Un client ne peut pas CRUD les ressources d'un projet via l'API publique**.
- La session hérite du `project_id` (passé dans `SessionCreate.project_id`) — ça marche —, mais la lecture/écriture des ressources par l'agent passe en pratique par **montage de volume Docker** géré côté plateforme, pas par un appel HTTP à agflow.

**Décision à prendre** :

- Option A — **Ajuster le scénario 04** pour refléter la réalité : l'agent accède aux ressources projet via son workspace monté, et non via une API publique. Le flèche `AgentA → Project` devient interne/implicite.
- Option B — **Ouvrir une partie publique** des projets (`GET /api/v1/projects/{project_id}/files/*`), cohérent avec l'idée d'un client qui orchestre des agents à distance. C'est un ajout d'API non trivial qui nécessite un cadrage de sécurité (quel scope, quelle ACL).

### 2. Cas 07 — Profils de mission

Le scénario évoque la découverte des **profils de mission** d'un agent (ex : `strict`/`lenient`). Or :

- `AgentDetail` (response de `GET /api/v1/agents/{agent_id}`) n'expose **pas** de tableau `profiles`.
- L'endpoint `GET /api/admin/agents/{agent_id}/profiles` existe mais est **admin-only**.
- `AgentInstanceCreate` (body pour instancier) a un champ `mission` (string libre), pas de `profile_id`.

**Décision à prendre** :

- Option A — **Ajuster le cas 07** : retirer la mention des profils de mission, dire que la mission est une string que l'application fournit librement.
- Option B — **Exposer publiquement** les profils de mission dans `AgentDetail` (tableau `profiles[]` avec `id`, `name`, `description`), et accepter `profile_id` dans `AgentInstanceCreate` (résolu en mission côté backend).

### 3. Schéma de réponse de `POST .../message` non typé

La réponse est déclarée comme `dict[str, str]` (`additionalProperties: string`) sans
schéma nommé. Concrètement c'est probablement `{"msg_id": "<uuid>"}`, mais aucune
garantie côté contrat.

**À faire** : nommer un DTO `MessagePosted` (ex : `{msg_id: str, created_at: datetime}`) pour figer le contrat, et le référencer dans les scénarios qui parlent d'"identifiant de corrélation".

### 4. `parent_msg_id` non exposé côté public

Le cas 03 mentionne "Parent/enfant de message" comme permettant à l'application de
reconstituer la chaîne. Or `MessageIn` (body du POST) n'a **pas** de `parent_msg_id`
dans son schéma public ; seul l'admin en dispose côté `agent_messages_service`. Côté
public, impossible pour un client d'émettre un message enfant d'un autre.

**Décision à prendre** :

- Option A — **Ajuster le cas 03** pour dire que le parent/enfant est une trace interne utile à la supervision mais pas exploitée par le client.
- Option B — **Exposer `parent_msg_id`** en optionnel dans `MessageIn` public, si le use case client le justifie (ex : agent qui doit dire "cette réponse correspond à la demande X").

### 5. WebSockets absents d'OpenAPI

Trois WebSockets publics existent (cf. plus haut) mais ne sont pas dans
`/openapi.json`. Un client qui se fie uniquement au contrat généré passera à côté du
cas 05 (streaming) et du shell interactif.

**À faire** : documenter les WS dans un fichier complémentaire (`docs/api/websockets.md` par exemple) ou générer un AsyncAPI spec en parallèle. Mentionner la référence explicite dans la doc OpenAPI (via `x-extensions`) peut aussi aider.

### 6. Task streaming content-type imprécis

`POST /api/v1/dockerfiles/{id}/task` est annoncé dans sa description comme "stream
events back", mais le `Content-Type` de la réponse 200 est `application/json` — ce qui
suggère un JSON unique et pas un NDJSON.

**À faire** : vérifier le comportement runtime (est-ce du NDJSON / SSE / JSON unique ?) et aligner la spec OpenAPI (`application/x-ndjson` ou `text/event-stream`) pour que le client génère le bon code.

## Endpoints couverts / non couverts par les scénarios

### Couverts au moins partiellement (18 endpoints)

Sessions CRUD (4), agents lifecycle (3), messages (5), découverte catalogue (5), task one-shot (1).

### Non couverts mais exposés côté public (25 endpoints)

Dockerfiles CRUD + files + params + builds + import/export (17 endpoints) → relèvent
d'un cas "opérateur gère le catalogue" qui pourrait devenir **A04 — Gestion dynamique
des dockerfiles côté API publique** si on veut qu'un client dev ait la main dessus.

Containers run/stop (3), launched list/stop (2), agents generate (2), scopes (1) →
utilisables dans des scénarios futurs (test/debug, CLI admin, ou tooling maison).

## Prochains pas suggérés

1. **Trancher les écarts 1 et 2** (Projet + profils) : impact direct sur les cas 04 et 07.
2. **Nommer un DTO** pour la réponse de `POST .../message` (écart 3).
3. **Documenter les WebSockets** (écart 5) — au minimum dans ce répertoire, idéalement dans une spec AsyncAPI.
4. **Clarifier le content-type du task streaming** (écart 6).
5. **Ajouter un scénario "erreurs"** maintenant que les happy paths sont posés (session expirée, rate limit, scope insuffisant, timeout agent) — cohérent avec `docs/test-plans/sessions-v1-scenarios.md` mais en version fonctionnelle.

## Source

Contrat analysé : `https://docker-agflow.yoops.org/openapi.json` (copie locale : `C:\Users\g.beard\AppData\Local\Temp\openapi.json`, 305 kB). Version déployée au moment de l'audit = celle du LXC 201 avant déploiement de la Phase 1 M6 (aucune modification publique dans M6 Phase 1).
