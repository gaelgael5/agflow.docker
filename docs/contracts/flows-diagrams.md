# Diagrammes des flux — agflow.docker × workflow ag.flow

> Diagrammes mermaid issus des contrats `docker-orchestration-flow.md` v5 et
> `hook-docker-task-completed.md` v5.

> **À copier dans le projet workflow** : les diagrammes sont génériques (pas
> de référence à une implémentation Docker spécifique). Conserver la version
> v5 pour traçabilité.

> **Modèle clé V5** :
> - Catalogue = liste des **projects** (templates pré-configurés).
> - Phase 1 : `GET /projects`. Phase 2 : `POST /projects/{id}/runtimes` →
>   provisioning auto + polling `GET /project-runtimes/{id}/resources`.
> - Le **callback HMAC vit sur la session** (pas sur le runtime).
> - Tous les identifiants applicatifs sont des **UUID v4** (`task_id`,
>   `correlation_id`, `action_execution_id`, etc.).
> - Auth : **clé API** transportée via Bearer header HTTP (RFC 6750), pas un JWT.

---

## 1. Bootstrap d'un project_runtime depuis un projet du catalogue

Phase 1 : récupérer la liste des projets. Phase 2 : créer un runtime à partir
d'un `project_id` — Docker provisionne automatiquement les resources, ag.flow
polle le statut.

```mermaid
sequenceDiagram
    autonumber
    participant AF as ag.flow
    participant API as API admin
    participant SVC as Services
    participant DB as PostgreSQL
    participant W as Worker provisioning
    participant SSH as ssh_executor
    participant DK as Docker daemon
    participant CTR as Containers ressources

    Note over AF,DK: Phase 1 - récupérer la liste des projets (lecture)
    AF->>API: GET /api/admin/projects
    API->>SVC: projects_service.list_all()
    SVC->>DB: SELECT projects
    DB-->>SVC: projects
    SVC-->>API: liste des projets
    API-->>AF: 200 + liste

    AF->>API: GET /api/admin/projects/PROJECT_ID
    API->>SVC: projects_service.get_detail()
    SVC->>DB: SELECT projects + product_instances template
    SVC-->>API: detail du project
    API-->>AF: 200 + detail

    Note over AF,DK: Phase 2 - créer un runtime (async)
    AF->>API: POST /api/admin/projects/PROJECT_ID/runtimes<br/>body: name, metadata
    API->>SVC: project_runtimes_service.create_from_template
    SVC->>DB: INSERT project_runtimes (status=provisioning)
    SVC->>DB: INSERT tasks (kind=runtime_provision, status=pending)
    SVC-->>API: docker_project_runtime_id, task_id, status=provisioning
    API-->>AF: 202 + body

    W->>DB: SELECT tasks WHERE kind=runtime_provision AND status=pending
    W->>DB: UPDATE tasks SET status=running
    W->>DB: SELECT product_instances template WHERE project_id
    DB-->>W: liste des resources à provisionner

    loop Pour chaque resource du template
        W->>DB: INSERT product_instances runtime row (status=provisioning)
        W->>SSH: docker compose up
        SSH->>DK: SSH connect + docker compose up
        DK->>CTR: démarre containers
        CTR-->>DK: healthcheck OK
        SSH-->>W: result
        W->>W: Calcule connection_params<br/>Construit mcp_bindings<br/>Templating Jinja setup_steps
        W->>DB: UPDATE product_instances<br/>(connection_params, mcp_bindings, setup_steps,<br/>status=ready ou pending_setup)
    end

    W->>DB: UPDATE project_runtimes (status=ready ou partially_ready)
    W->>DB: UPDATE tasks (status=completed)

    Note over AF,DK: Polling côté ag.flow
    loop Tant que statut != ready
        AF->>API: GET /api/admin/project-runtimes/PR_ID/resources
        API->>SVC: read project_runtime + resources
        SVC->>DB: SELECT
        SVC-->>API: status + resources
        API-->>AF: 200 + body
    end

    Note over AF: ag.flow stocke les resources<br/>(connection_params, mcp_bindings, setup_steps)<br/>côté project_resources et propose les setup_steps<br/>pending_setup à l'utilisateur
```

---

## 2. Exécution d'une action : session → agent → work → hook

L'agent est instancié EN session. Le callback HMAC est porté par la session,
réutilisé pour tous les works.

```mermaid
sequenceDiagram
    autonumber
    participant AF as ag.flow
    participant API as API admin
    participant SVC as Services
    participant DB as PostgreSQL
    participant HW as Worker hook dispatcher
    participant SSH as ssh_executor
    participant DK as Docker daemon
    participant CTR as Container agent

    Note over AF,DK: Etape 1 - ouvrir une session avec callback (sync)
    AF->>API: POST /api/admin/sessions<br/>body avec project_runtime_id callback_url callback_hmac_key_id
    API->>SVC: sessions_service.create
    alt project_runtime_id fourni
        SVC->>DB: SELECT project_runtimes WHERE id
        DB-->>SVC: vérification existence
    end
    SVC->>DB: INSERT sessions avec callback_url et callback_hmac_key_id
    SVC->>DB: INSERT tasks kind=session_create status=completed
    SVC-->>API: session_id task_id status=active
    API-->>AF: 201 + body

    Note over AF,DK: Etape 2 - instancier un agent en session (sync)
    AF->>API: POST /api/admin/sessions/SID/agents<br/>body slug et mission
    API->>SVC: agents_instances_service.create_in_session

    alt session liée à un project_runtime
        SVC->>DB: SELECT product_instances ready pour project_runtime
        DB-->>SVC: resources avec mcp_bindings
        SVC->>SVC: Fusion mcp_bindings agent_catalogue plus resources
    else session standalone
        SVC->>SVC: mcp_bindings agent_catalogue uniquement
    end

    SVC->>SSH: docker run agent_image avec MCP fusionnée
    SSH->>DK: SSH plus docker run
    DK->>CTR: Démarre container agent avec MCP injectés
    DK-->>SSH: container_id
    SVC->>DB: INSERT agents_instances avec mcp_bindings_injected JSONB
    SVC->>DB: INSERT tasks kind=agent_create status=completed
    SVC-->>API: agent_uuid plus mcp_bindings_injected
    API-->>AF: 201 + body

    Note over AF,DK: Etape 3 - soumettre du travail (async)
    AF->>API: POST /api/admin/sessions/SID/agents/AID/work<br/>body instruction avec _agflow_action_execution_id et _agflow_correlation_id (UUID)
    API->>SVC: sessions_service.submit_work
    SVC->>DB: INSERT tasks kind=session_work status=pending<br/>champs _agflow persistés
    SVC->>SVC: Publie l'instruction sur le bus MOM
    SVC->>CTR: instruction délivrée à l'agent via MOM
    SVC->>DB: UPDATE tasks status=running
    SVC-->>API: task_id session_id agent_uuid started_at
    API-->>AF: 202 + body

    Note over CTR: Exécution agent (LLM, MCP wiki et git injectés)<br/>Produit result et artifacts

    CTR-->>SVC: response message via MOM direction=out kind=result
    SVC->>DB: UPDATE tasks status=completed ou failed avec result ou error
    SVC->>DB: SELECT session pour récupérer callback_url et callback_hmac_key_id
    SVC->>DB: INSERT outbound_hooks status=pending<br/>callback_url et hmac_key_id portés depuis la session

    HW->>DB: SELECT outbound_hooks WHERE status=pending
    HW->>DB: SELECT hmac_keys
    HW->>HW: Build payload plus signe HMAC
    HW->>AF: POST callback_url body avec hook_id task_id project_runtime_id<br/>session_id agent_uuid action_execution_id correlation_id status result
    AF-->>HW: 200 OK
    HW->>DB: UPDATE outbound_hooks status=delivered

    Note over AF,DK: Etape 4 V2 - autre work sur le même agent (contexte gardé)
    AF->>API: POST /sessions/SID/agents/AID/work avec instruction 2
    Note over API,CTR: Mêmes étapes l'agent garde son contexte<br/>Nouveau task_id et nouveau hook

    Note over AF,DK: Etape 5 - fermeture session (sync)
    AF->>API: DELETE /api/admin/sessions/SID avec query force=true
    API->>SVC: sessions_service.close
    SVC->>SSH: docker stop tous les containers agents
    SSH->>DK: docker stop plus rm
    SVC->>DB: UPDATE sessions status=closed
    SVC->>DB: UPDATE agents_instances status=destroyed
    alt force=true ET works actifs
        SVC->>DB: UPDATE tasks status=cancelled WHERE running
        SVC->>DB: INSERT outbound_hooks pour cancelled
    end
    API-->>AF: 204
```

---

## 3. Cycle de vie d'une `task`

```mermaid
stateDiagram-v2
    direction LR

    [*] --> completed_sync: API SVC<br/>POST sync<br/>(session_create, agent_create)

    [*] --> pending: API SVC<br/>POST async<br/>(runtime_provision, session_work)

    pending --> running: WORKER ou SVC<br/>SELECT pending<br/>UPDATE running

    running --> completed: container exit OK<br/>UPDATE DB
    running --> failed: erreur runtime<br/>UPDATE DB
    running --> cancelled: API DELETE force<br/>SSH docker stop

    completed --> hook_pending: SVC<br/>INSERT outbound_hooks<br/>si session.callback_url
    failed --> hook_pending
    cancelled --> hook_pending

    completed_sync --> [*]: pas de hook (sync)

    hook_pending --> hook_delivered: HOOK_W<br/>POST callback OK
    hook_pending --> hook_dead: HOOK_W<br/>1h sans succès

    hook_delivered --> [*]
    hook_dead --> [*]
```

---

## 4. Cycle de vie d'une `resource`

```mermaid
stateDiagram-v2
    direction LR

    [*] --> declared_in_template: ADMIN<br/>Resource définie dans le template<br/>(table product_instances template)

    declared_in_template --> provisioning: WORKER<br/>POST /projects/PID/runtimes<br/>déclenche INSERT runtime row

    provisioning --> ready: WORKER SSH DK<br/>compose up OK<br/>healthcheck OK<br/>pas de setup_steps<br/>mcp_bindings calculés
    provisioning --> pending_setup: WORKER<br/>compose up OK<br/>setup_steps requis
    provisioning --> failed: WORKER<br/>timeout ou image manquante ou healthcheck KO

    pending_setup --> ready: ag.flow externe<br/>user clique "J'ai tout fait"<br/>(état porté côté ag.flow)

    ready --> consumed_by_agents: API SVC<br/>POST /sessions/SID/agents<br/>injection mcp_bindings
    consumed_by_agents --> ready: agent destroyed

    ready --> deleted: V2 plus DELETE
    failed --> [*]
    deleted --> [*]
```

---

## 5. Cycle de vie d'une `session`

```mermaid
stateDiagram-v2
    direction LR

    [*] --> active: API SVC<br/>POST /sessions<br/>avec callback_url et project_runtime_id (optionnel)<br/>INSERT sessions

    active --> active_with_agents: API SVC<br/>POST /sessions/SID/agents (N times)<br/>INSERT agents_instances<br/>plus docker run plus MCP injection

    active_with_agents --> running_work: API SVC<br/>POST work<br/>tasks(session_work) pending puis running
    running_work --> active_with_agents: hook task-completed<br/>prêt pour autre work

    active_with_agents --> closed: API DELETE /sessions/SID<br/>SVC stop tous containers
    active --> closed: pareil même sans agent
    running_work --> closed: API DELETE force=true<br/>tasks running puis cancelled<br/>hooks cancelled enqueue

    active --> expired: timeout idle config<br/>SVC reaper
    active_with_agents --> expired: idem
    running_work --> expired: idem (force interruption)

    closed --> [*]
    expired --> [*]
```

---

## 6. Mécanisme de retry du hook outbound

```mermaid
sequenceDiagram
    autonumber
    participant HW as Worker hook dispatcher
    participant DB as PostgreSQL
    participant HMAC as hmac_keys_service
    participant AF as ag.flow callback

    loop Toutes les 5s
        HW->>DB: SELECT outbound_hooks WHERE status=pending<br/>AND next_retry_at moins ou égal à now LIMIT 50

        loop Pour chaque hook
            HW->>HMAC: get_key par session_id et key_id
            HMAC->>DB: SELECT hmac_keys
            HMAC->>HMAC: Fernet decrypt
            HMAC-->>HW: clé en clair

            HW->>HW: signed_str timestamp newline hook_id newline raw_body<br/>signature HMAC_SHA256

            HW->>AF: POST callback_url<br/>X-Agflow-Hook-Id<br/>X-Agflow-Timestamp<br/>X-Agflow-Signature<br/>body JSON

            alt 200 ou 202
                AF-->>HW: succès
                HW->>DB: UPDATE status=delivered
            else 400 ou 401 ou 409 (terminal)
                AF-->>HW: erreur cliente
                HW->>DB: UPDATE status=dead
                Note over HW: Pas de retry sur erreur cliente
            else 5xx ou timeout
                AF-->>HW: échec serveur
                HW->>HW: backoff par attempt_number<br/>1s 5s 30s 2min 10min
                HW->>DB: UPDATE attempt_number plus 1<br/>next_retry_at now plus backoff
                Note over HW: Si attempt sup 5 ou age sup 1h<br/>status=dead
            end
        end
    end
```

---

## 7. Architecture détaillée par layer

```mermaid
graph TB
    subgraph external [EXTERNE]
        AF_OUT[ag.flow workflow POST sortants]
        AF_IN[ag.flow callback POST hooks reçus]
    end

    subgraph layer_api [LAYER 1 - API publique]
        ADMIN_PROJ_GET["GET /api/admin/projects"]
        ADMIN_PROJ_DET["GET /api/admin/projects/PROJECT_ID"]
        ADMIN_PR_POST["POST /api/admin/projects/PROJECT_ID/runtimes - async"]
        ADMIN_PR_RES["GET /api/admin/project-runtimes/PR_ID/resources"]
        ADMIN_SESS_POST["POST /api/admin/sessions - sync"]
        ADMIN_AG_POST["POST /api/admin/sessions/SID/agents - sync"]
        ADMIN_WORK["POST /api/admin/sessions/SID/agents/AID/work - async"]
        ADMIN_SESS_DEL["DELETE /api/admin/sessions/SID - sync"]
    end

    subgraph layer_svc [LAYER 2 - Services métier]
        PJ_SVC["projects_service - existant M7"]
        PR_SVC["project_runtimes_service plus create_from_template"]
        PI_SVC["product_instances_service plus provisioning plus mcp_bindings"]
        AG_SVC["agents_instances_service M5 plus injection MCP"]
        SE_SVC["sessions_service M5 plus project_runtime_id et callback plus submit_work"]
        TK_SVC["tasks_service - NOUVEAU"]
        HK_SVC["outbound_hooks_service - NOUVEAU"]
        HM_SVC["hmac_keys_service - NOUVEAU"]
    end

    subgraph layer_db [LAYER 3 - PostgreSQL]
        T_PJ[("projects - existant templates admin")]
        T_PR[("project_runtimes - ALTER")]
        T_PI[("product_instances - ALTER")]
        T_AG[("agents_instances M5 - ALTER")]
        T_SE[("sessions M5 - ALTER avec callback_url et project_runtime_id")]
        T_TK[("tasks - NOUVEAU")]
        T_HK[("outbound_hooks - NOUVEAU")]
        T_HM[("hmac_keys - NOUVEAU")]
    end

    subgraph layer_w [LAYER 5 - Workers]
        W_PROV["Worker provisioning - NOUVEAU"]
        W_HOOK["Worker hook dispatcher - NOUVEAU"]
    end

    subgraph layer_ssh [LAYER 6 - SSH]
        SSH[ssh_executor existant]
    end

    subgraph layer_dk [LAYER 7 - Docker]
        DK[Docker daemon]
        NET[Docker networks par project_runtime]
        CTR_R[Containers ressources persistants]
        CTR_A[Containers agents plus MCP injectés]
    end

    AF_OUT -->|API key Bearer| ADMIN_PROJ_GET
    AF_OUT -->|API key Bearer| ADMIN_PROJ_DET
    AF_OUT -->|API key Bearer| ADMIN_PR_POST
    AF_OUT -->|API key Bearer| ADMIN_PR_RES
    AF_OUT -->|API key Bearer| ADMIN_SESS_POST
    AF_OUT -->|API key Bearer| ADMIN_AG_POST
    AF_OUT -->|API key Bearer| ADMIN_WORK
    AF_OUT -->|API key Bearer| ADMIN_SESS_DEL

    ADMIN_PROJ_GET --> PJ_SVC
    ADMIN_PROJ_DET --> PJ_SVC
    ADMIN_PR_POST --> PR_SVC
    ADMIN_PR_RES --> PI_SVC
    ADMIN_SESS_POST --> SE_SVC
    ADMIN_AG_POST --> AG_SVC
    ADMIN_WORK --> SE_SVC
    ADMIN_SESS_DEL --> SE_SVC

    PJ_SVC --> T_PJ
    PR_SVC --> T_PR
    PR_SVC --> T_PJ
    PR_SVC --> TK_SVC
    PI_SVC --> T_PI
    PI_SVC --> TK_SVC
    AG_SVC --> T_AG
    AG_SVC --> TK_SVC
    AG_SVC -->|lit mcp_bindings| T_PI
    SE_SVC --> T_SE
    SE_SVC --> TK_SVC
    SE_SVC --> HK_SVC

    TK_SVC --> T_TK
    HK_SVC --> T_HK
    HM_SVC --> T_HM

    T_TK -.poll.-> W_PROV
    T_HK -.poll.-> W_HOOK

    W_PROV --> PI_SVC
    W_PROV --> SSH

    W_HOOK --> HM_SVC
    W_HOOK -->|HMAC POST| AF_IN

    AG_SVC --> SSH
    SE_SVC --> SSH

    SSH --> DK
    DK --> NET
    DK --> CTR_R
    DK --> CTR_A
    CTR_R --- NET
    CTR_A --- NET
```

---

## 8. Cohabitation Phase 1 SaaS Runtimes ↔ Workflow

Les 2 chemins partent du même catalogue de projets, divergent sur l'auth et le
payload de création de runtime, atterrissent dans la même table
`project_runtimes` avec discriminant.

```mermaid
flowchart TB
    subgraph clients [LAYER 0 - Clients]
        SS_C[Frontend SaaS humain]
        WF_C[ag.flow workflow M2M]
    end

    subgraph api [LAYER 1 - API]
        SS_LIST[GET /api/v1/projects scope projects:read]
        SS_RUN[POST /api/v1/projects/PROJECT_ID/runtimes scope runtimes:write body environment et group_selection et user_secrets]
        WF_LIST[GET /api/admin/projects API key Bearer]
        WF_RUN[POST /api/admin/projects/PROJECT_ID/runtimes API key Bearer body name et metadata]
    end

    subgraph svc [LAYER 2 - Services]
        SS_SVC[project_runtimes_service create_for_user]
        WF_SVC[project_runtimes_service create_from_template_for_workflow]
    end

    subgraph db [LAYER 3 - Tables communes]
        PJ[("projects - catalogue partagé")]
        PR[("project_runtimes")]
        SS_ROW[Row SaaS user_id NOT NULL environment NOT NULL]
        WF_ROW[Row Workflow user_id NULL flag workflow=true]
    end

    subgraph dk [LAYER 7 - Docker]
        SS_DK[Containers SaaS réseau agflow-user-X]
        WF_DK[Containers Workflow resources persistants plus agents en sessions plus MCP injectés]
    end

    SS_C --> SS_LIST
    SS_C --> SS_RUN
    WF_C --> WF_LIST
    WF_C --> WF_RUN

    SS_LIST --> PJ
    WF_LIST --> PJ
    PJ -.template lu.- SS_RUN
    PJ -.template lu.- WF_RUN

    SS_RUN --> SS_SVC --> PR
    WF_RUN --> WF_SVC --> PR

    PR -->|user_id IS NOT NULL| SS_ROW
    PR -->|user_id IS NULL workflow| WF_ROW

    SS_ROW --> SS_DK
    WF_ROW --> WF_DK
```

**Note** : depuis v5 le `callback_url` n'est plus sur `project_runtimes` mais
sur **`sessions`**. Le discriminant entre row SaaS et row Workflow se fait
donc uniquement via `user_id` (NULL = workflow, NOT NULL = SaaS humain). Le
champ `callback_url` éventuel sur `project_runtimes` n'est plus nécessaire.

**Invariants à coder côté service** :
```python
# Chaque project_runtime est SOIT SaaS humain SOIT Workflow M2M
# (pas les deux). En V5, c'est trivial : SaaS a user_id, Workflow ne l'a pas.
```

---

## 9. Pour aller plus loin

- `docker-orchestration-flow.md` v5 — endpoints amont (catalogue, runtime, session, agent, work)
- `hook-docker-task-completed.md` v5 — hook outbound HMAC (callback porté par session)
- `docs/functionnalTests/tests/01-09` — tests M5 (modèle de référence session→agent→message)
- `backend/src/agflow/api/public/sessions.py` — implémentation M5 actuelle
- `backend/src/agflow/api/public/projects.py` — Phase 1 SaaS GET projects
- `backend/migrations/076_group_runtimes.sql` — origine `project_runtimes`
- `backend/migrations/085_saas_runtimes.sql` — extension Phase 1 SaaS
- Migration `086_workflow_orchestration.sql` (à créer) — extension Workflow v5
