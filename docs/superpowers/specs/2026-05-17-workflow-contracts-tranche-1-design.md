# Workflow Contracts — Tranche 1 (contract-shaped scaffold)

**Date** : 2026-05-17
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Livrer le **squelette complet** des 8 endpoints `/api/admin/*` définis dans `docs/contracts/docker-orchestration-flow.md` (v5), ainsi qu'un 9ᵉ endpoint utilitaire `POST /api/admin/hmac-keys`, permettant à `ag.flow` (service workflow externe) de :

- enregistrer ses clés HMAC de callback ;
- piloter un round-trip complet (catalogue → runtime → session → agent → work → close) contre un agflow.docker fonctionnellement minimal ;
- valider le wire-format contract-shaped sans attendre l'implémentation du worker provisioning ni du worker hook dispatcher (différés tranche 2).

Cette tranche pose les **fondations DB** (migration 111) et l'**enveloppe HTTP** (9 endpoints wrappant des services existants ou créant des artefacts minimaux). Pas de vrai async runtime, pas de hook outbound.

## Contexte

### Acquis (déjà livré sur `dev`)

- **Auth M2M** : `require_operator_or_m2m` (`backend/src/agflow/auth/dependencies.py:56-106`) accepte Bearer JWT (admin/operator) OU API key `agfd_*` avec scope `m2m:orchestrate`. Le scope est déjà reconnu (`api_keys_service.py:33`).
- **API keys** : table `api_keys` + `api_keys_service` + `require_api_key(*scopes)` factory (HMAC + bcrypt + rate limit Redis).
- **Endpoints partiels** :
  - `GET /api/admin/projects` et `GET /api/admin/projects/{id}` existent (`api/admin/projects.py`), à adapter au DTO contrat v5.
  - `GET /api/admin/projects/{id}/runtimes` (list) existe (`project_runtimes.py:33`).
- **Sessions M5 (`/api/v1/*`)** : `POST /api/v1/sessions`, `POST /api/v1/sessions/{sid}/agents`, etc. existent côté public avec auth API key. Services réutilisables : `sessions_service`, `agents_instances_service`.
- **MOM bus** : `agflow.mom.publisher` + `agflow.mom.envelope` (`Direction.IN/OUT`) — pattern pg_notify déjà utilisé pour les messages agents.
- **Mock + smoke kit** : `docs/contracts/mock-docker/` + `smoke-test.sh` (14/14 PASS au 2026-04-28). Le contrat v5 est gelé.

### Contraintes V5 figées

Référence : `docs/contracts/docker-orchestration-flow.md` + mémoire `project_workflow_contracts.md`.

- UUID v4 strict pour tous les IDs.
- Catalogue = projets templates (resources viennent AVEC le template, pas dynamiquement).
- Callback HMAC sur la **session** (pas le runtime).
- Une session peut référencer un `project_runtime_id` ou être standalone.
- `_agflow_correlation_id` UUID v4 dans `instruction.work`.

## Décisions structurantes (tranchées en brainstorming)

| # | Question | Décision | Rationale |
|---|---|---|---|
| 1 | Routes physiques `/api/admin/*` vs alias des `/api/v1/*` existants | **Routes physiques distinctes** wrappant les services M5 (`sessions_service`, `agents_instances_service`) | Spec contract exige `/api/admin/*` avec scope `m2m:orchestrate`. Wrappers thin = DRY, divergence évitée. |
| 2 | Numéro de migration | **111** (pas 086 comme dit la mémoire — projet a déjà 110) | Vérifié contre `backend/migrations/`. |
| 3 | `POST /runtimes` mode async | **Sync simulé** : INSERT runtime + copie resources + UPDATE status=ready dans la même requête, retourne 202 + status="provisioning" | Permet à ag.flow de polling et voir "ready" immédiatement. Pas de vrai worker en tranche 1. Réaliste vis-à-vis du contrat (pattern async). |
| 4 | `POST /work` mode async | **INSERT tasks (status=pending) + MOM publish vers l'agent, retourne 202 + task_id**. PAS de hook outbound. | L'aller est livré (l'agent peut traiter). Le retour (hook task-completed) est différé tranche 2. ag.flow ne pourra pas tester le hook receiver en tranche 1. |
| 5 | Resources copie | **Copie brute** des template resources dans `product_instances` avec `connection_params={}`, `mcp_bindings=[]`, `setup_steps=[]`, `provisioning_status="ready"` | Le Jinja templating dynamique des connection_params (paramètres host/port/credentials) vient en tranche 2 avec le worker. En tranche 1 = juste la structure. |
| 6 | Injection MCP au create agent | **Data tracing** : si la session est liée à un runtime, on agrège les `mcp_bindings` des resources et on les stocke dans `agents_instances.mcp_bindings_injected`. Pas de vraie injection container. | La vraie injection (adaptation du `composition_builder` pour passer ces MCP au runtime Docker) vient en tranche 2. Tranche 1 = traçabilité. |
| 7 | HMAC keys référencement | **Endpoint dédié `POST /api/admin/hmac-keys`** pour pre-créer. Session référence par `callback_hmac_key_id`. | Pattern clean conforme spec v5 (hmac_keys = entité réutilisable). Coût : +1 endpoint dans le scope. |
| 8 | DELETE /sessions force=true | **Toujours 204**, même si session déjà fermée. Sans force=true et status non-active : 409. | Conforme contrat v5. Permet à ag.flow de "nettoyer" sans état préalable. |
| 9 | Idempotence `POST /work` | **UNIQUE (session_id, correlation_id)**. Conflit → 409 + `{"task_id": "<existant>"}` | Permet à ag.flow de retry safely sans dupliquer la tâche. Conforme contrat. |
| 10 | Worker hook dispatcher | **Hors scope tranche 1** | Table `outbound_hooks` créée et indexée, mais aucun consumer. Différé tranche 2. |

## Modèle de données (migration 111)

```sql
-- Migration 111 : Workflow orchestration scaffold

-- 1. Extension des tables existantes
ALTER TABLE sessions
  ADD COLUMN project_runtime_id UUID REFERENCES project_runtimes(id),
  ADD COLUMN callback_url TEXT,
  ADD COLUMN callback_hmac_key_id VARCHAR(64);

ALTER TABLE product_instances
  ADD COLUMN connection_params JSONB,
  ADD COLUMN mcp_bindings JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN setup_steps JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN provisioning_status VARCHAR(32) DEFAULT 'ready';

ALTER TABLE agents_instances
  ADD COLUMN mcp_bindings_injected JSONB DEFAULT '[]'::jsonb;

-- 2. Tables nouvelles
CREATE TABLE hmac_keys (
  key_id VARCHAR(64) PRIMARY KEY,
  secret_hex TEXT NOT NULL,           -- 64 chars hex = 256 bits
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

CREATE TABLE tasks (
  task_id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  agent_instance_id UUID NOT NULL REFERENCES agents_instances(id) ON DELETE CASCADE,
  correlation_id UUID NOT NULL,
  instruction JSONB NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  result JSONB,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (session_id, correlation_id)
);

CREATE TABLE outbound_hooks (
  hook_id UUID PRIMARY KEY,
  task_id UUID REFERENCES tasks(task_id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  hmac_key_id VARCHAR(64) NOT NULL REFERENCES hmac_keys(key_id),
  payload JSONB NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  next_retry_at TIMESTAMPTZ,
  last_response_code INT,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ
);

CREATE INDEX idx_outbound_hooks_pending
  ON outbound_hooks(status, next_retry_at)
  WHERE status IN ('pending', 'retrying');

CREATE INDEX idx_tasks_session
  ON tasks(session_id, created_at DESC);
```

## Catalogue des 9 endpoints

Tous sous `/api/admin/*` avec `Depends(require_operator_or_m2m)`.

| # | Méthode + Path | Comportement tranche 1 | Statut |
|---|---|---|---|
| 1 | `GET /api/admin/projects` | Liste catalogue (DTO contrat v5 : `project_id`, `name`, `description`, `resources_summary[{type,label}]`) | Existe, **adapter DTO** |
| 2 | `GET /api/admin/projects/{project_id}` | Détail template (DTO contrat v5 complet : resources, system_prompts, etc.) | Existe, **adapter DTO** |
| 3 | `POST /api/admin/projects/{project_id}/runtimes` | Sync simulé : INSERT project_runtimes (status=provisioning) → copie resources → UPDATE status=ready. Retourne 202 `{runtime_id, status:"provisioning"}` | **À créer** |
| 4 | `GET /api/admin/project-runtimes/{runtime_id}/resources` | Liste resources (product_instances) du runtime avec leur status courant | **À créer** |
| 5 | `POST /api/admin/sessions` | Wrapper `sessions_service.create()` étendu : stocke `callback_url`, `callback_hmac_key_id`, `project_runtime_id`. Validation : hmac_key_id existe, runtime_id existe si fournis | **À créer** |
| 6 | `POST /api/admin/sessions/{session_id}/agents` | Wrapper `agents_instances_service.create()`. Si session liée à runtime → fusion MCP : agrège `mcp_bindings` des resources et stocke dans `mcp_bindings_injected` | **À créer** |
| 7 | `POST /api/admin/sessions/{sid}/agents/{aid}/work` | INSERT tasks (status=pending), MOM publish vers l'agent (`Direction.IN`, kind=`instruction.work`), retourne 202 + `{task_id, _agflow_correlation_id}` | **À créer** |
| 8 | `DELETE /api/admin/sessions/{session_id}?force=true` | Wrapper `sessions_service.close()`. Sans force=true → 409 si non-active. Avec force=true → toujours 204 | **À créer** |
| 9 | `POST /api/admin/hmac-keys` | INSERT hmac_keys. Body `{key_id, secret_hex, description?}`. 201 ou 409 sur duplicate | **À créer** |

## Fichiers

| Fichier | Rôle | Lignes |
|---|---|---|
| `backend/migrations/111_workflow_orchestration.sql` (nouveau) | Migration | ~80 |
| `backend/src/agflow/schemas/workflow.py` (nouveau) | DTOs Pydantic v5 (ProjectSummary v5, RuntimeCreate, SessionCreate, AgentCreate, WorkRequest, HmacKeyCreate, etc.) | ~180 |
| `backend/src/agflow/services/workflow_provisioning_service.py` (nouveau) | `provision_runtime(project_id)` : INSERT runtime + copy resources + return runtime_id | ~100 |
| `backend/src/agflow/services/tasks_service.py` (nouveau) | `create()`, `get()`, conflict handling | ~80 |
| `backend/src/agflow/services/hmac_keys_service.py` (nouveau) | `create()`, `get()`, `list()` | ~60 |
| `backend/src/agflow/api/admin/workflow_runtimes.py` (nouveau) | Endpoints #3, #4 | ~140 |
| `backend/src/agflow/api/admin/workflow_sessions.py` (nouveau) | Endpoints #5, #6, #7, #8 | ~220 |
| `backend/src/agflow/api/admin/hmac_keys.py` (nouveau) | Endpoint #9 | ~80 |
| `backend/src/agflow/api/admin/projects.py` (modif) | Adapter DTO endpoints #1, #2 au contrat v5 | +30 |
| `backend/src/agflow/main.py` (modif) | `include_router` × 3 (workflow_runtimes, workflow_sessions, hmac_keys) | +6 |

**Total : ~1100 lignes prod + ~80 lignes migration.**

## Data flow critiques

### Provisioning runtime (sync simulé)

```
POST /api/admin/projects/{project_id}/runtimes
       │
       ▼
workflow_provisioning_service.provision_runtime(project_id) :
  1. INSERT project_runtimes (project_id, provisioning_status="provisioning")
     RETURNING runtime_id
  2. SELECT resources WHERE project_id=... (table resources, déjà existante)
  3. POUR CHAQUE template resource :
       INSERT product_instances (
         runtime_id, type, name, ...,
         connection_params={}, mcp_bindings=[], setup_steps=[],
         provisioning_status="ready"
       )
  4. UPDATE project_runtimes SET provisioning_status="ready"
  5. RETURN runtime_id
       │
       ▼
HTTP 202 + {"runtime_id":"...", "status":"provisioning"}
```

### Injection MCP au create agent

```
POST /api/admin/sessions/{sid}/agents
       │
1. SELECT session.project_runtime_id WHERE id=sid
2. SI runtime_id NULL → comportement standard (mcp_bindings_injected=[])
3. SI runtime_id NOT NULL :
     a. SELECT product_instances WHERE runtime_id=...
     b. AGRÉGER les mcp_bindings (concat des arrays JSONB)
4. agents_instances_service.create() + UPDATE mcp_bindings_injected
```

### Work + task creation

```
POST /api/admin/sessions/{sid}/agents/{aid}/work
Body: {"_agflow_correlation_id": "<uuid>", "instruction": {...}}
       │
       ▼
1. tasks_service.create(
     session_id=sid, agent_instance_id=aid,
     correlation_id=body["_agflow_correlation_id"],
     instruction=body["instruction"]
   ) → INSERT tasks (status="pending") RETURNING task_id
      → conflit UNIQUE → 409 + {"task_id": "<existant>"}
2. MOM publish (agflow.mom.publisher) :
     direction=IN, kind="instruction.work",
     payload={...instruction, _agflow_correlation_id, _agflow_task_id}
3. RETURN 202 + {task_id, _agflow_correlation_id}
```

### Idempotence

| Endpoint | Clé | Comportement conflit |
|---|---|---|
| `POST /work` | UNIQUE (session_id, correlation_id) | 409 + `{"task_id": "<existant>"}` (retry safe) |
| `POST /hmac-keys` | PRIMARY KEY (key_id) | 409 `{"error":"key_id_already_exists"}` |
| Autres POST | Pas d'idempotence native | OK |

## Error handling

| Cas | Comportement |
|---|---|
| API key absente / invalide | 401 (déjà géré par `require_operator_or_m2m`) |
| API key sans scope `m2m:orchestrate` ET pas JWT admin/operator | 403 (déjà géré) |
| `POST /runtimes` avec project_id inexistant | 404 `{"error":"project_not_found"}` |
| `POST /sessions` avec `callback_hmac_key_id` inexistant | 422 `{"error":"hmac_key_not_found"}` |
| `POST /sessions` avec `project_runtime_id` inexistant | 422 `{"error":"runtime_not_found"}` |
| `POST /work` correlation_id déjà utilisé pour la session | 409 + `{"task_id": "<existant>"}` |
| `DELETE /sessions` sans `force=true` sur session non-active | 409 `{"error":"session_not_active"}` |
| `DELETE /sessions?force=true` | Toujours 204 |
| DTO Pydantic invalide (UUID malformé, etc.) | 422 (géré par FastAPI) |
| Erreur DB inattendue | 500 + log structlog (pas de stack au client) |

## Tests (pytest, ~22 tests)

| Fichier | Tests |
|---|---|
| `backend/tests/db/test_migration_111.py` | 4 : ALTER columns présents, tables hmac_keys/tasks/outbound_hooks créées, index pending hook, FK cascades |
| `backend/tests/services/test_workflow_provisioning_service.py` | 3 : provision_runtime copie resources, status final ready, runtime sans template erreur |
| `backend/tests/services/test_tasks_service.py` | 3 : create insère pending, conflit (session_id, correlation_id), get_by_id |
| `backend/tests/services/test_hmac_keys_service.py` | 2 : create + duplicate raise |
| `backend/tests/api/test_admin_workflow_runtimes.py` | 3 : POST /runtimes auth m2m + 202, GET /resources auth + structure, 404 runtime inexistant |
| `backend/tests/api/test_admin_workflow_sessions.py` | 5 : POST /sessions avec callback+hmac, POST /agents fusion MCP, POST /work crée task + MOM publish, POST /work idempotent 409, DELETE force=true |
| `backend/tests/api/test_admin_hmac_keys.py` | 2 : POST 201 + duplicate 409 |

Convention : pytest+pytest-asyncio strict, DONE_WITH_CONCERNS acceptable si LXC injoignable depuis Windows (validation E2E via `./scripts/run-test.sh`).

## Observabilité

- Logs structurés via `structlog.get_logger(__name__)` :
  - `workflow.runtime.provisioned` (runtime_id, project_id, resources_count)
  - `workflow.session.created` (session_id, callback_url, project_runtime_id)
  - `workflow.task.created` (task_id, session_id, agent_instance_id, correlation_id)
  - `workflow.task.conflict` (correlation_id, existing_task_id)
  - `workflow.hmac_key.created` (key_id)
- Pas de métriques Prometheus en tranche 1.

## Volume et estimation

| Catégorie | Lignes |
|---|---|
| Code backend (8 nouveaux + 2 modifs) | ~1100 |
| Migration SQL | ~80 |
| Tests pytest | ~600 |
| Spec (ce doc) | ~290 |
| **Total** | **~2070 lignes** |

**Effort estimé** : 4-5 jours en pipeline allégé.

## Hors scope explicite (différé tranche 2)

- **Worker provisioning** Jinja templating des `connection_params` (host/port/credentials dynamiques) → tranche 2.
- **Worker hook dispatcher** : table `outbound_hooks` créée, mais aucun worker ne la consomme. En tranche 2 : worker qui scan `WHERE status IN ('pending','retrying') AND next_retry_at <= now()`, signe HMAC SHA-256, POST au `callback_url`, retry exponentiel 1h.
- **Réception côté agent** de `instruction.work` : déjà couvert par le pattern M5 MOM (consumer existant). Pas de modif nécessaire.
- **Hook task-completed côté outbound** : nécessite consumer MOM qui détecte `kind="task.completed"` de l'agent, met à jour `tasks.status="completed"`, INSERT `outbound_hooks`. → tranche 2.
- **DELETE /api/admin/hmac-keys/{key_id}** (revoke) → tranche 2.
- **Tests E2E** contre le mock-receiver ag.flow → tranche 2 (besoin du dispatcher).
- **Endpoint GET /api/admin/tasks/{task_id}** (lecture status) → tranche 2 ou plus tard.

## Cohabitation Phase 1 SaaS Runtimes

La table `project_runtimes` est partagée entre :
- **SaaS humain** (Phase 1, livrée 2026-04-27) : `user_id NOT NULL`.
- **Workflow ag.flow** (cette tranche) : `user_id NULL`.

Discriminant clair, pas de collision. Le service `workflow_provisioning_service.provision_runtime()` insère avec `user_id=NULL`. Les workers/UI SaaS filtrent sur `user_id IS NOT NULL` et inversement.

## Migration et compat

- Pas de breaking change sur les endpoints existants `/api/v1/*` (laissés intacts).
- Les nouveaux endpoints `/api/admin/*` sont additifs.
- La migration 111 ajoute uniquement des colonnes/tables (pas de DROP, pas de RENAME). Compatible avec un rollback partiel.
- Les colonnes ALTER ont des `DEFAULT` ou sont nullable → pas de panne d'application existante.
