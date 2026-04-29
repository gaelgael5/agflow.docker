# Contrat — Flow d'orchestration `ag.flow → Docker service`

> **Statut :** v5 (2026-04-27)
>
> **Auteur :** ag.flow (workflow-service). **Implémenteur :** Docker service
> (agflow.docker).
>
> **À copier dans le projet workflow** : ce document est la spec d'intégration.
> Quand vous le copiez côté workflow, remplacez les chemins relatifs des liens
> vers `docs/contracts/*` par les vôtres et conservez la version v5 dans le
> header pour traçabilité.

> **Disclaimer pour le projet workflow** :
> - Côté Docker (agflow.docker) : ce contrat **doit** correspondre à des
>   endpoints exposés par `/api/admin/*` (ou `/api/m2m/*` selon convention
>   finale — voir §2 sur l'auth).
> - Côté workflow (ag.flow) : implémenter le **client** qui émet ces appels
>   + l'endpoint de **réception du hook** (cf. `hook-docker-task-completed.md`).
> - Toute évolution de ce contrat **doit** être versionnée (`v6`, `v7`, …) pour
>   éviter les désynchronisations entre les 2 services.
>
> **Mission :** Définir les endpoints REST que le Docker service expose pour
> qu'un client (ag.flow) puisse :
> 1. Lister les `projects` du catalogue admin.
> 2. Créer un `project_runtime` à partir d'un `project_id`. Les resources du
>    template sont provisionnées automatiquement par Docker.
> 3. Ouvrir une `session` (optionnellement liée à un `project_runtime`) — **la
>    session porte le callback HMAC réutilisé par tous les hooks émis pour les
>    works qui auront lieu dans cette session**.
> 4. Instancier des `agents` dans cette session (par slug). Si la session est
>    liée à un project_runtime, les MCP des resources sont injectés
>    automatiquement.
> 5. Soumettre du `work` à un agent → reçoit un `task_id` async → hook à la
>    fin (vers le callback de la session).

---

## 1. Concepts

### 1.1 Vocabulaire

| Terme | Sens |
|-------|------|
| **`project`** | Template (blueprint) pré-configuré par l'admin Docker, avec ses `resources` (`product_instances`). Identifié par `project_id` (UUID). Listé via `GET /projects`. **Lecture seule pour ag.flow**. |
| **`project_runtime`** | Instance déployée d'un `project`. Crée la matérialisation des resources sur la machine cible. Identifié par `docker_project_runtime_id` (UUID). Créé via `POST /projects/{project_id}/runtimes`. |
| **`resource`** | Élément consommable d'un `project_runtime` (wiki, code repo, …), provisionné automatiquement par Docker à partir du template. Expose `connection_params` + `mcp_bindings`. ID = `resource_id` (UUID). |
| **`session`** | Wrapper d'exécution qui contient ≥1 agent. **Porte le `callback_url` + `callback_hmac_key_id`** réutilisés par tous les hooks émis pour les works de cette session. Optionnellement liée à un `project_runtime`. ID = `session_id` (UUID). |
| **`agent`** | Instance d'un dockerfile/role catalogué Docker, instanciée EN session via `POST /sessions/{session_id}/agents` avec un `slug`. Si la session est liée à un project_runtime, l'agent reçoit la config MCP fusionnée des resources. ID = `agent_uuid` (UUID, alias de `instance_id` côté code M5). |
| **`work`** | Unité de travail soumise à un agent (`POST /sessions/{sid}/agents/{aid}/work`). Crée une `task` async, retourne un `task_id`. Plusieurs works successifs possibles sur le même agent. |
| **`task`** | Pivot d'asynchronisme : tout endpoint async retourne un `task_id` (UUID), repris dans le hook `task-completed`. |
| **`correlation_id`** | UUID v4 propagé bout-en-bout pour tracer une opération à travers les 2 services. Champ `_agflow_correlation_id` dans l'instruction du work. |

### 1.2 Identifiants — règle uniforme

**Tous les identifiants applicatifs sont des UUID v4** :
- `project_id`, `docker_project_runtime_id`, `resource_id`
- `session_id`, `agent_uuid`, `task_id`, `hook_id`
- `_agflow_action_execution_id`, `_agflow_correlation_id`

Format : `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx` où `y ∈ {8,9,a,b}`.

Pas de strings libres pour les corrélations. Pas de préfixés (`pi_*`, `res_*`).
Le contrat est plus strict, le code plus simple.

### 1.3 Pattern asynchrone

Tout endpoint long (provisioning, exécution agent) suit le pattern :

```
ag.flow → POST → Docker
              ← 202 + task_id
(plus tard)
Docker → POST hook task-completed → ag.flow
              ← 200
```

- Le `task_id` est l'identifiant pivot.
- ag.flow stocke le `task_id` côté `action_executions.docker_task_id` pour
  corréler le hook.
- Pour les opérations rapides (création DB seule), Docker peut émettre le hook
  immédiatement après la réponse — ag.flow doit traiter cet ordre quasi-simultané.

### 1.4 Vue d'ensemble

```
Setup project (one-shot par projet ag.flow) :

  ag.flow → GET /projects → Docker
              ← 200 [{project_id, name, description, resources_summary}]

  ag.flow → GET /projects/{project_id} → Docker
              ← 200 {project_id, resources:[{type, label, mcp_bindings_preview}]}

  ag.flow → POST /projects/{project_id}/runtimes → Docker
              body: {name, metadata}
              ← 202 {docker_project_runtime_id, task_id, status: provisioning}

  Docker provisionne automatiquement les resources du template
  ag.flow polle GET /project-runtimes/{id}/resources jusqu'à ce que
  toutes soient ready (ou pending_setup avec setup_steps à valider)

Exécution (au fil des actions du workflow) :

  ag.flow → POST /sessions → Docker
              body: {project_runtime_id?, callback_url, callback_hmac_key_id,
                     name?, duration_seconds?, metadata?}
              ← 201 {session_id, status: active}

  ag.flow → POST /sessions/{session_id}/agents → Docker
              body: {slug, mission?}
              ← 201 {agent_uuid, mcp_bindings_injected:[...]}

  ag.flow → POST /sessions/{session_id}/agents/{agent_uuid}/work → Docker
              body: {instruction:{_agflow_action_execution_id (UUID),
                                  _agflow_correlation_id (UUID),
                                  prompt, ...}}
              ← 202 {task_id, started_at}

  Docker → POST {session.callback_url}/api/v1/hooks/docker/task-completed
              headers: HMAC signé avec session.callback_hmac_key_id
              body: {hook_id, task_id, project_runtime_id?, session_id,
                     agent_uuid, action_execution_id, status, result, ...}
              ← 200

  (Plusieurs POST .../work successifs possibles sur le même agent_uuid —
   chaque work a son propre task_id et déclenche son propre hook)

  ag.flow → DELETE /sessions/{session_id} → Docker
              ← 204
```

---

## 2. Authentification

Tous les endpoints `ag.flow → Docker` exigent une **clé API** (pas un JWT)
transportée via le schéma HTTP `Bearer` (RFC 6750) :

```
Authorization: Bearer <DOCKER_API_KEY>
```

- **`<DOCKER_API_KEY>`** est une **clé API longue durée** émise côté Docker
  (table `api_keys` agflow.docker), distribuée out-of-band à ag.flow.
- Le format `agfd_xxxx...` est le format natif des clés API agflow.docker.
- Le mot **Bearer** est juste le **schéma de transport HTTP** (pas un JWT).
  C'est l'équivalent d'un header `X-API-Key` mais conforme RFC.
- Les routes `/api/admin/*` du Docker service doivent accepter ce schéma
  **en plus** du JWT humain existant (côté Docker, étendre `require_operator`
  pour accepter les 2 schémas).

> **Note pour l'implémentation Docker** : aujourd'hui les routes `/api/admin/*`
> sont protégées par JWT uniquement (`require_operator`). À étendre pour
> accepter aussi les clés API `agfd_*` avec scope dédié (ex : `m2m:orchestrate`).

---

## 3. Endpoints

### 3.1 `GET /api/admin/projects`

Catalogue des projets templates disponibles côté Docker.

**Réponse 200** :
```json
{
  "projects": [
    {
      "project_id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Plateforme location vélos",
      "description": "Stack wiki + repo git + RAG",
      "resources_summary": [
        { "type": "wiki", "label": "Wiki Outline" },
        { "type": "code_repo", "label": "Repo Git" }
      ]
    }
  ]
}
```

**Erreurs** : 401 API key invalide.

---

### 3.2 `GET /api/admin/projects/{project_id}`

Détail complet d'un project template.

**Réponse 200** :
```json
{
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Plateforme location vélos",
  "description": "...",
  "resources": [
    {
      "type": "wiki",
      "label": "Wiki Outline",
      "mcp_bindings_preview": [
        { "name": "wiki", "transport": "stdio" }
      ]
    }
  ]
}
```

**Erreurs** : 401, 404.

---

### 3.3 `POST /api/admin/projects/{project_id}/runtimes`

Crée un `project_runtime` à partir d'un template. Docker provisionne
automatiquement toutes les resources définies dans le template.

**Body** :
```json
{
  "name": "Vélos prod",
  "metadata": { "team": "alpha" }
}
```

- **Pas de `callback_url` ici** : le callback HMAC est porté par les sessions,
  pas par le runtime (cf. §3.4). Le runtime n'émet pas de hook ; ag.flow polle
  l'état des resources via `GET /project-runtimes/{id}/resources`.

**Réponse 202** :
```json
{
  "docker_project_runtime_id": "660e8400-e29b-41d4-a716-446655440001",
  "task_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "provisioning",
  "created_at": "2026-04-27T10:00:00Z"
}
```

**Erreurs** : 400 body invalide, 401, 404 project_id inconnu.

---

### 3.4 `GET /api/admin/project-runtimes/{id}/resources`

Liste les resources matérialisées d'un project_runtime (avec leurs
`connection_params`, `mcp_bindings`, `setup_steps`). ag.flow polle cet endpoint
pour suivre l'avancée du provisioning.

**Réponse 200** :
```json
{
  "docker_project_runtime_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "ready",
  "resources": [
    {
      "resource_id": "880e8400-e29b-41d4-a716-446655440003",
      "type": "wiki",
      "status": "ready",
      "connection_params": {
        "wiki_url": "https://outline.velos.example.com",
        "api_token_var_name": "OUTLINE_API_TOKEN"
      },
      "mcp_bindings": [
        {
          "name": "wiki",
          "transport": "stdio",
          "command": "npx",
          "args": ["-y", "@outline/mcp-server"],
          "env": {
            "OUTLINE_API_URL": "https://outline.velos.example.com",
            "OUTLINE_API_TOKEN_REF": "${OUTLINE_API_TOKEN}"
          }
        }
      ],
      "setup_steps": []
    }
  ]
}
```

**Statuts possibles côté `resource`** :
- `provisioning` : en cours
- `ready` : utilisable
- `pending_setup` : compose up OK mais `setup_steps` requis (action manuelle user)
- `failed` : provisioning KO

**Statut côté `project_runtime`** :
- `provisioning` : au moins une resource encore en cours
- `ready` : toutes les resources `ready`
- `partially_ready` : au moins une `pending_setup` (workflow peut continuer mais avec un avertissement)
- `failed` : au moins une resource `failed` non-récupérable

**Erreurs** : 401, 404.

---

### 3.5 `POST /api/admin/sessions`

Ouvre une session — wrapper d'exécution qui hébergera les agents. **C'est ici
qu'on fournit le callback HMAC** réutilisé par tous les hooks de la session.

**Body** :
```json
{
  "project_runtime_id": "660e8400-e29b-41d4-a716-446655440001",
  "callback_url": "https://workflow.agflow.dev",
  "callback_hmac_key_id": "v1",
  "name": "Phase design",
  "duration_seconds": 3600,
  "metadata": { "phase": "design" }
}
```

- **`project_runtime_id`** *(optionnel)* : si fourni, les agents instanciés dans
  cette session consommeront automatiquement les `mcp_bindings` des resources
  du runtime (cf. §3.6). Sans, la session est standalone.
- **`callback_url`** : base URL ag.flow ; le hook complet =
  `{callback_url}/api/v1/hooks/docker/task-completed`.
- **`callback_hmac_key_id`** : identifiant logique de la clé HMAC (la clé en
  clair est distribuée out-of-band).

**Réponse 201** (synchrone) :
```json
{
  "session_id": "990e8400-e29b-41d4-a716-446655440004",
  "task_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "project_runtime_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "active",
  "expires_at": "2026-04-27T11:00:00Z",
  "created_at": "2026-04-27T10:00:00Z"
}
```

**Erreurs** :
- 400 : body invalide
- 401
- 404 : `project_runtime_id` fourni mais inexistant

---

### 3.6 `POST /api/admin/sessions/{session_id}/agents`

Instancie un agent dans la session.

**Body** :
```json
{
  "slug": "architect-v1",
  "mission": "Définir l'architecture du module facturation"
}
```

- **`slug`** : référence vers le catalogue admin Docker (un dockerfile + role
  pré-construits côté Docker). Si inconnu → 400.
- **`mission`** *(optionnel)* : contexte de mission long-terme (passé à
  l'agent au démarrage).

**Réponse 201** (synchrone) :
```json
{
  "agent_uuid": "bb0e8400-e29b-41d4-a716-446655440006",
  "slug": "architect-v1",
  "session_id": "990e8400-e29b-41d4-a716-446655440004",
  "task_id": "cc0e8400-e29b-41d4-a716-446655440007",
  "status": "ready",
  "mcp_bindings_injected": [
    { "name": "wiki", "from_resource_id": "880e8400-e29b-41d4-a716-446655440003" }
  ],
  "created_at": "2026-04-27T10:05:00Z"
}
```

**Comportement** :
1. Si `session.project_runtime_id` non null → Docker fusionne :
   - MCP du catalogue de l'agent (base)
   - + `mcp_bindings` de chaque resource du runtime ayant `status=ready`
2. Container démarré avec cette config MCP fusionnée.
3. `mcp_bindings_injected` retourné pour transparence (liste les MCP réellement
   activés et leur source).

**Erreurs** :
- 400 : slug inconnu
- 404 : session inexistante ou expirée
- 409 : session non active

---

### 3.7 `POST /api/admin/sessions/{session_id}/agents/{agent_uuid}/work`

Soumet du travail à un agent. **Asynchrone**. Le hook arrive sur
`session.callback_url` à la fin.

**Body** :
```json
{
  "instruction": {
    "_agflow_action_execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "_agflow_correlation_id": "11ee8400-e29b-41d4-a716-446655440008",

    "title": "Définir l'architecture du module facturation",
    "description": "...",
    "prompt": "Tu es un architecte logiciel...",
    "context_stack": [],
    "dependencies": [
      { "action_id": "previous-uuid", "result_summary": "..." }
    ]
  }
}
```

- **`_agflow_action_execution_id`** (UUID) : identifiant de l'action côté ag.flow,
  retourné dans le hook pour permettre à ag.flow de retrouver l'action sans
  table de jointure.
- **`_agflow_correlation_id`** (UUID v4) : trace cross-service. Format strict
  UUID v4 (pas de string libre).
- **Pas de `_agflow_callback_url` ni `_agflow_hmac_key_id` ici** — ces deux
  champs vivent sur la session (cf. §3.5), Docker les lit depuis la session
  parente lors de l'émission du hook.

**Réponse 202** :
```json
{
  "task_id": "dd0e8400-e29b-41d4-a716-446655440009",
  "session_id": "990e8400-e29b-41d4-a716-446655440004",
  "agent_uuid": "bb0e8400-e29b-41d4-a716-446655440006",
  "started_at": "2026-04-27T10:10:00Z"
}
```

**Comportement** :
1. Docker valide que l'agent existe et n'est pas occupé.
2. Instruction passée à l'agent (bus MOM ou stdin selon implémentation).
3. À la fin (succès/échec/timeout/cancel), Docker émet le hook
   `task-completed` à `session.callback_url` (signé HMAC avec
   `session.callback_hmac_key_id`).
4. Plusieurs `POST .../work` successifs supportés sur le même `agent_uuid` :
   l'agent garde son contexte conversationnel entre les works (mode natif M5).

**Erreurs** : 400 instruction invalide, 404 session/agent inexistant, 409 agent occupé OU session non active.

---

### 3.8 `DELETE /api/admin/sessions/{session_id}`

Ferme la session — destruction de tous les agents et leur container.

**Query optionnel** : `?force=true` pour forcer même avec works actifs.

**Réponse 204** (synchrone).

**Comportement** :
1. Stop tous les containers d'agents.
2. Pour chaque task `running` : émettre hook `task-completed` avec
   `status: "cancelled", error.code: "USER_CANCELLED"`.
3. Marquer la session `closed`.

**Erreurs** : 404 session inconnue, 409 works actifs sans `?force=true`.

---

## 4. Injection MCP depuis les ressources

Quand un agent est instancié dans une session liée à un `project_runtime`,
Docker construit la config MCP du container :

```
mcp_finale = mcp_de_base_agent_catalogue
           + flatten(resource.mcp_bindings for resource in project_runtime.resources
                     if resource.status == 'ready')
```

- Ordre : catalogue agent d'abord, puis resources par ordre de provisioning.
- Conflit de nom MCP : catalogue agent gagne.
- Filtrage : seules les resources `ready` contribuent.
- Substitution `${VAR}` : résolus depuis `connection_params` + secrets plateforme
  + vault Docker.
- Réponse `mcp_bindings_injected` : transparence vers ag.flow (liste source).
- Injection **statique** au démarrage de l'agent (V1) — si une resource est
  ajoutée pendant la vie de l'agent, l'agent ne la voit pas.

---

## 5. Cycle de vie complet

```
T0  ag.flow → GET /projects
    ← 200 [{project_id: P1, ...}, ...]

T1  user choisit P1 → ag.flow stocke project_id

T2  ag.flow → POST /projects/P1/runtimes {name, metadata}
    ← 202 {docker_project_runtime_id: PR1, task_id: T_PR, status: provisioning}

T3  Docker provisionne les resources en background

T4  ag.flow polle → GET /project-runtimes/PR1/resources
    ← 200 {status: ready, resources: [{connection_params, mcp_bindings, ...}]}

T5  ag.flow → POST /sessions
                {project_runtime_id: PR1, callback_url, callback_hmac_key_id,
                 duration_seconds: 3600}
    ← 201 {session_id: S1, status: active}

T6  pour chaque action workflow :
    ag.flow → POST /sessions/S1/agents {slug: "architect-v1"}
    ← 201 {agent_uuid: A1, mcp_bindings_injected: [{name: wiki, ...}]}

T7  ag.flow → POST /sessions/S1/agents/A1/work
                {instruction: {_agflow_action_execution_id (UUID),
                               _agflow_correlation_id (UUID), prompt}}
    ← 202 {task_id: T_W1, started_at}

T8  Docker exécute, à la fin :
    Docker → POST {callback_url}/api/v1/hooks/docker/task-completed
        headers: HMAC signé avec callback_hmac_key_id
        body: {hook_id, task_id: T_W1, project_runtime_id: PR1,
               session_id: S1, agent_uuid: A1, action_execution_id,
               correlation_id, status, result}
    ← 200

T9  (V2) autre work sur le même agent — contexte gardé :
    ag.flow → POST /sessions/S1/agents/A1/work {instruction 2}
    ← 202 {task_id: T_W2, ...}

T10 Docker → hook T_W2

T11 fin de phase :
    ag.flow → DELETE /sessions/S1
    ← 204
```

---

## 6. Idempotence et résilience

| Endpoint | Idempotence | Mécanisme |
|----------|-------------|-----------|
| `GET /projects` | Oui (lecture) | natif |
| `GET /projects/{id}` | Oui | natif |
| `POST /projects/{id}/runtimes` | Non | ag.flow garde l'unicité côté ag.flow |
| `GET /project-runtimes/{id}/resources` | Oui (lecture) | natif |
| `POST /sessions` | Non | nouvelle session à chaque appel |
| `POST /sessions/{sid}/agents` | Non | plusieurs agents même slug possibles |
| `POST /work` | Non | nouveau task à chaque appel |
| `DELETE /sessions/{sid}` | Oui | 204 si déjà supprimée |

**Retry côté ag.flow** : sur 5xx, backoff exponentiel (1s, 5s, 30s) pendant 5 min.

**Retry côté Docker (hook)** : sur 5xx, backoff (1s, 5s, 30s, 2min, 10min) pendant 1h.

---

## 7. Observabilité

- **Logs Docker** : chaque appel ag.flow → Docker logger
  `(method, path, correlation_id, response_status, duration, task_id, session_id, agent_uuid)`.
- **Hook callbacks** : Docker logger chaque tentative POST hook avec
  `hook_id`, `task_id`, `attempt_number`.
- **Header `X-Request-Id`** : ag.flow propage le correlation_id, Docker le
  propage à son tour vers les workers.

---

## 8. Questions ouvertes

1. **`POST /sessions/{sid}/agents` requiert-il dockerfile_id et role_id explicites**, ou le slug suffit ?
2. **Multi-tasks par agent (V2)** : N works en parallèle, ou serialization stricte ?
3. **Concurrence agents dans une session** : un même slug instanciable N fois, ou unique ?
4. **Durée de vie d'un container agent après hook envoyé** : auto-stop idle, ou DELETE explicite ?
5. **MCP injection statique vs dynamique** : V1 statique, V2+ ?
6. **Format `connection_params`** : JSON libre ou normalisé par type ?
7. **Distribution clé HMAC** : variable d'env partagée ? endpoint admin Docker ?
8. **Polling de `GET /project-runtimes/{id}/resources`** : fréquence recommandée ? Webhook intermédiaire `runtime-ready` à V2 ?

---

## 9. Checklist d'implémentation Docker

- [ ] Endpoint `GET /api/admin/projects` (catalogue des templates)
- [ ] Endpoint `GET /api/admin/projects/{id}` (détail template)
- [ ] Endpoint `POST /api/admin/projects/{id}/runtimes` (async, retourne `task_id` + `docker_project_runtime_id`, Docker provisionne en background)
- [ ] Endpoint `GET /api/admin/project-runtimes/{id}/resources` (polling status)
- [ ] Endpoint `POST /api/admin/sessions` (sync, accepte `project_runtime_id?` + `callback_url` + `callback_hmac_key_id`)
- [ ] Endpoint `POST /api/admin/sessions/{sid}/agents` (sync, fusion MCP des resources du runtime si lié)
- [ ] Endpoint `POST /api/admin/sessions/{sid}/agents/{aid}/work` (async, retourne `task_id`, hook à la fin sur `session.callback_url`)
- [ ] Endpoint `DELETE /api/admin/sessions/{sid}` avec `?force=true`
- [ ] Émission du hook `task-completed` à la fin de chaque work, signé HMAC avec
      la clé désignée par `session.callback_hmac_key_id`
- [ ] Acceptation API key `agfd_*` via Bearer header sur `/api/admin/*` (en
      plus du JWT existant)
- [ ] Logging structuré + propagation `correlation_id` + `task_id` + `session_id`
      + `agent_uuid` dans tous les logs
- [ ] Validation des UUIDs sur tous les `_agflow_*` champs
- [ ] Templating Jinja `setup_steps` côté Docker avant exposition via
      `GET /project-runtimes/{id}/resources`
