# Contrat — Hook `docker → ag.flow : task-completed`

> **Statut :** v5 (2026-04-27)
>
> **Auteur :** ag.flow (workflow-service). **Implémenteur :** Docker service
> (agflow.docker).
>
> **À copier dans le projet workflow** : ce document est la spec du callback
> que ag.flow doit exposer pour recevoir les notifications de fin de work.
> Conserver la version `v5` dans le header pour traçabilité.

> **Disclaimer pour le projet workflow** :
> - Côté ag.flow : implémenter l'endpoint
>   `POST /api/v1/hooks/docker/task-completed` qui valide la signature HMAC,
>   stocke le `hook_id` pour idempotence, et déclenche le traitement métier.
> - Côté Docker (agflow.docker) : implémenter le worker outbound qui signe et
>   POST le payload conforme au schéma §4 sur l'URL fournie par ag.flow lors
>   de la création de session (cf. `docker-orchestration-flow.md` v5 §3.5).
> - Toute évolution doit être versionnée (`v6`, `v7`, …).
>
> **Cf. également** `docker-orchestration-flow.md` v5 qui détaille les
> endpoints amont (catalogue projects → project_runtime → session → agent → work).

---

## 1. Vue d'ensemble

Le hook est émis par Docker à la fin d'un **work** soumis à un agent dans une
session. Le callback HMAC (URL + `key_id`) est porté par la **session**
(`POST /api/admin/sessions` body — cf. orchestration v5 §3.5), pas par chaque
work. Tous les hooks d'une session utilisent les mêmes credentials de callback.

```
┌─────────────┐                                  ┌─────────────┐
│  ag.flow    │  POST /sessions                  │   Docker    │
│  workflow   │──{project_runtime_id?,           │  service    │
│  service    │   callback_url,                  │             │
│             │   callback_hmac_key_id} ────────▶│             │
│             │ ◀── 201 {session_id} ────────────┤             │
│             │                                  │             │
│             │  POST /sessions/{sid}/agents     │             │
│             │──{slug} ────────────────────────▶│             │
│             │ ◀── 201 {agent_uuid,             │             │
│             │   mcp_bindings_injected:[...]} ──┤             │
│             │                                  │             │
│             │  POST /sessions/{sid}/agents/    │             │
│             │       {aid}/work                 │             │
│             │──{instruction +                  │             │
│             │   _agflow_action_execution_id +  │             │
│             │   _agflow_correlation_id (UUID)}▶│             │
│             │ ◀── 202 {task_id, started_at} ───┤             │
│             │                                  │  exécute    │
│             │                                  │             │
│             │ ◀── POST hook task-completed ────┤             │
│             │ {hook_id, task_id,               │  signé HMAC │
│             │  project_runtime_id?, session_id,│  avec       │
│             │  agent_uuid, action_execution_id,│  session.   │
│             │  correlation_id, status, result} │  callback_  │
│             │                                  │  hmac_key_id│
│             │ ──────────── 200 ────────────────▶             │
└─────────────┘                                  └─────────────┘
```

**Granularité** : un agent peut recevoir plusieurs `work` successifs dans la
même session. Chaque `work` génère son propre `task_id` et son propre hook.

---

## 2. Endpoint exposé par ag.flow

```
POST {AGFLOW_PUBLIC_BASE_URL}/api/v1/hooks/docker/task-completed
Content-Type: application/json
```

L'URL exacte est fournie par ag.flow à la création de chaque session Docker
(champ `callback_url` du body de `POST /sessions` — cf. orchestration v5 §3.5).

**Réponse attendue par Docker** :

| Status | Sens                                                          | Action Docker         |
|--------|---------------------------------------------------------------|-----------------------|
| 200    | Hook accepté (idempotence : déjà reçu ou nouveau, peu importe) | Marquer comme délivré |
| 202    | Hook accepté pour traitement asynchrone                        | Marquer comme délivré |
| 400    | Payload invalide (schéma)                                      | Logger, ne pas retry  |
| 401    | Signature HMAC invalide                                        | Logger, ne pas retry  |
| 409    | Conflit métier (rare)                                          | Logger, ne pas retry  |
| 5xx    | Erreur serveur ag.flow                                         | Retry avec backoff    |

**Politique de retry** : backoff exponentiel (1s, 5s, 30s, 2min, 10min) pendant
1h, puis abandon avec log d'erreur.

---

## 3. Authentification — HMAC SHA-256

Le hook est signé par Docker avec une clé HMAC partagée. Le `key_id` désigné
par `session.callback_hmac_key_id` permet la rotation.

**Trois headers obligatoires** :

| Header                | Description                                                      |
|-----------------------|------------------------------------------------------------------|
| `X-Agflow-Hook-Id`    | UUID v4 unique par appel (idempotence côté ag.flow)              |
| `X-Agflow-Timestamp`  | Timestamp ISO-8601 UTC du moment de l'envoi                      |
| `X-Agflow-Signature`  | `hmac-sha256=<hex>` du payload signé (cf. §3.1)                  |

> **Note** : le hook **n'utilise pas** d'API key Bearer pour l'auth — la
> signature HMAC sur `(timestamp + hook_id + body)` suffit, plus l'anti-replay
> sur le timestamp + l'idempotence sur `hook_id`. C'est le standard pour les
> webhooks sortants.

### 3.1 Calcul de la signature

```
signed_string = X-Agflow-Timestamp + "\n" + X-Agflow-Hook-Id + "\n" + raw_request_body
signature_hex = HMAC_SHA256(shared_secret, signed_string).hexdigest()
header_value  = "hmac-sha256=" + signature_hex
```

- `shared_secret` : clé désignée par `session.callback_hmac_key_id`, distribuée
  out-of-band entre ag.flow et Docker. Côté Docker : variable d'env
  `AGFLOW_HOOK_HMAC_KEY_<id>` ou table `hmac_keys`.
- `raw_request_body` : le body JSON tel qu'envoyé sur le réseau, **byte-pour-byte**.

### 3.2 Validation côté ag.flow

ag.flow rejette en **401** si :
- `X-Agflow-Signature` absent ou mal formé.
- Signature recalculée ne correspond pas (comparaison constant-time).
- `X-Agflow-Timestamp` trop ancien (> 5 min) ou trop dans le futur (> 1 min).
- `X-Agflow-Hook-Id` n'est pas un UUID v4 valide.

### 3.3 Idempotence

ag.flow stocke `X-Agflow-Hook-Id` dans une table `hooks_received`
(PRIMARY KEY). Si le même `hook_id` arrive deux fois, ag.flow répond **200**
sans re-traiter.

---

## 4. Schéma du body — JSON

### 4.1 Identifiants — règle uniforme

Tous les identifiants applicatifs sont des UUID v4 :
`hook_id`, `task_id`, `action_execution_id`, `correlation_id`, `project_runtime_id`,
`session_id`, `agent_uuid`.

### 4.2 Exemple succès

```json
{
  "hook_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_id": "660e8400-e29b-41d4-a716-446655440001",
  "action_execution_id": "770e8400-e29b-41d4-a716-446655440002",
  "correlation_id": "880e8400-e29b-41d4-a716-446655440003",
  "project_runtime_id": "990e8400-e29b-41d4-a716-446655440004",
  "session_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "agent_uuid": "bb0e8400-e29b-41d4-a716-446655440006",
  "container_id": "ctr_xyz789",
  "agent_slug": "architect-v1",
  "status": "completed",
  "started_at": "2026-04-27T08:30:00Z",
  "completed_at": "2026-04-27T08:34:12Z",
  "result": {
    "summary": "Architecture du module facturation rédigée (3200 mots).",
    "output_size_bytes": 18432,
    "artifacts": [
      {
        "type": "markdown",
        "uri": "docker://documents/9f8e7d6c-4a2b-4e8f-a123-456789abcdef",
        "title": "facturation.md"
      }
    ]
  },
  "error": null,
  "metadata": {
    "duration_ms": 252000,
    "tokens_in": 12450,
    "tokens_out": 3200
  }
}
```

### 4.3 Exemple échec

```json
{
  "hook_id": "550e8400-e29b-41d4-a716-446655440010",
  "task_id": "660e8400-e29b-41d4-a716-446655440011",
  "action_execution_id": "770e8400-e29b-41d4-a716-446655440002",
  "correlation_id": "880e8400-e29b-41d4-a716-446655440013",
  "project_runtime_id": "990e8400-e29b-41d4-a716-446655440004",
  "session_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "agent_uuid": "bb0e8400-e29b-41d4-a716-446655440006",
  "container_id": "ctr_xyz790",
  "agent_slug": "architect-v1",
  "status": "failed",
  "started_at": "2026-04-27T08:30:00Z",
  "completed_at": "2026-04-27T08:31:05Z",
  "result": null,
  "error": {
    "code": "AGENT_RUNTIME_ERROR",
    "message": "Le conteneur a quitté avec exit code 137 (OOM killed).",
    "type": "ContainerExitError",
    "details": {
      "exit_code": 137,
      "container_logs_excerpt": "...allocator: out of memory..."
    }
  },
  "metadata": {
    "duration_ms": 65000
  }
}
```

### 4.4 Schéma JSON Schema 2020-12 (normatif)

```jsonc
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agflow.dev/contracts/hook-docker-task-completed.schema.json",
  "title": "Hook docker→ag.flow task-completed",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "hook_id",
    "task_id",
    "action_execution_id",
    "correlation_id",
    "session_id",
    "agent_uuid",
    "status",
    "started_at",
    "completed_at"
  ],
  "properties": {
    "hook_id": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4. Doit être identique à la valeur du header X-Agflow-Hook-Id."
    },
    "task_id": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4. Identifiant de la task asynchrone — retourné par POST /work lors de la soumission. Pivot de corrélation."
    },
    "action_execution_id": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4. Envoyé par ag.flow dans `_agflow_action_execution_id` lors de la soumission du work. Permet à ag.flow de retrouver l'action sans lookup par task_id."
    },
    "correlation_id": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4. Trace cross-service. Envoyé par ag.flow dans `_agflow_correlation_id`."
    },
    "project_runtime_id": {
      "type": ["string", "null"],
      "description": "UUID v4 ou null. Identifiant du project_runtime lié à la session ; null si la session était standalone."
    },
    "session_id": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4. Identifiant de la session — REQUIS (la session est le wrapper d'exécution obligatoire)."
    },
    "agent_uuid": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4. Agent qui a traité le work."
    },
    "container_id": {
      "type": "string",
      "description": "Identifiant du conteneur Docker (string libre, dépend de l'implémentation)."
    },
    "agent_slug": {
      "type": "string",
      "description": "Slug humain de l'agent."
    },
    "status": {
      "enum": ["completed", "failed", "cancelled"]
    },
    "started_at": {
      "type": "string",
      "format": "date-time"
    },
    "completed_at": {
      "type": "string",
      "format": "date-time"
    },
    "result": {
      "oneOf": [
        { "type": "null" },
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["summary"],
          "properties": {
            "summary": {
              "type": "string",
              "maxLength": 8000
            },
            "output_size_bytes": {
              "type": "integer",
              "minimum": 0
            },
            "artifacts": {
              "type": "array",
              "items": { "$ref": "#/$defs/Artifact" }
            }
          }
        }
      ]
    },
    "error": {
      "oneOf": [
        { "type": "null" },
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["code", "message"],
          "properties": {
            "code": { "type": "string" },
            "message": { "type": "string" },
            "type": { "type": "string" },
            "details": { "type": "object" }
          }
        }
      ]
    },
    "metadata": {
      "type": "object",
      "description": "Champs libres (durée, tokens, coût, ...). Non normés."
    }
  },
  "$defs": {
    "Artifact": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type", "uri"],
      "properties": {
        "type": { "enum": ["markdown", "json", "binary", "image", "code"] },
        "uri": { "type": "string" },
        "title": { "type": "string" },
        "size_bytes": { "type": "integer", "minimum": 0 }
      }
    }
  },
  "allOf": [
    {
      "if": { "properties": { "status": { "const": "completed" } } },
      "then": { "required": ["result"], "properties": { "error": { "const": null } } }
    },
    {
      "if": { "properties": { "status": { "const": "failed" } } },
      "then": { "required": ["error"], "properties": { "result": { "const": null } } }
    },
    {
      "if": { "properties": { "status": { "const": "cancelled" } } },
      "then": {}
    }
  ]
}
```

**Invariants** :
- `status: "completed"` → `result` non-null, `error: null`
- `status: "failed"` → `error` non-null, `result: null`
- `status: "cancelled"` → `result` peut être null ou contenir un `summary` partiel ;
  `error` peut être null (annulation utilisateur) ou non-null (annulation système)

---

## 5. Codes d'erreur normés (`error.code`)

| Code                       | Sens                                                   |
|----------------------------|--------------------------------------------------------|
| `AGENT_RUNTIME_ERROR`      | Erreur générique pendant l'exécution de l'agent        |
| `AGENT_TIMEOUT`            | Timeout dépassé                                        |
| `AGENT_CRASHED`            | Process crashé (segfault, panic)                       |
| `AGENT_OOM`                | Out-of-memory                                          |
| `AGENT_PERMISSION_DENIED`  | Refus d'accès                                          |
| `INFRASTRUCTURE_ERROR`     | Problème côté Docker (image manquante, …)              |
| `USER_CANCELLED`           | Annulation explicite via API                           |

Liste **fermée** en V1 — toute extension demande mise à jour de ce contrat.

---

## 6. Champs réservés `_agflow_*` dans l'instruction du work

Lors du `POST /sessions/{sid}/agents/{aid}/work` (cf. orchestration v5 §3.7),
le `body.instruction` doit contenir ces champs réservés (UUID v4 stricts) :

```jsonc
{
  "instruction": {
    "_agflow_action_execution_id": "770e8400-e29b-41d4-a716-446655440002",
    "_agflow_correlation_id": "880e8400-e29b-41d4-a716-446655440003",

    // Champs métier
    "title": "...",
    "prompt": "...",
    "context_stack": [],
    "dependencies": []
  }
}
```

**Important** :
- **Pas de `_agflow_callback_url` ni `_agflow_hmac_key_id` dans le work** — ces
  champs sont sur la **session** (cf. orchestration v5 §3.5), Docker les lit
  depuis la session parente lors de l'émission du hook.
- Les champs `_agflow_*` sont retournés tels quels dans le hook (côté top-level
  du payload, sans le préfixe `_agflow_`) :
  - `_agflow_action_execution_id` → `action_execution_id`
  - `_agflow_correlation_id` → `correlation_id`

---

## 7. Auth ag.flow → Docker (rappel)

Pour les appels sortants ag.flow → Docker (création de session, soumission de
work, …), ag.flow utilise une **clé API** transportée via Bearer header :

```
Authorization: Bearer <DOCKER_API_KEY>
```

- `<DOCKER_API_KEY>` est une clé API longue durée (format `agfd_*` côté
  agflow.docker), distribuée out-of-band.
- Bearer est juste le **schéma de transport HTTP** (RFC 6750) — la clé n'est
  pas un JWT.
- Le service Docker doit accepter ce schéma sur `/api/admin/*` en plus du JWT
  humain existant.

Cf. orchestration v5 §2 pour la clarification complète.

---

## 8. Sécurité

- **Toujours HTTPS** pour le hook (TLS 1.2+).
- **HMAC** sur header + body → impossible de rejouer ou forger sans la clé.
- **Anti-replay** : fenêtre 5 min sur `X-Agflow-Timestamp` + idempotence sur `hook_id`.
- **Pas de PII dans les logs** côté ag.flow (logger `hook_id`, `correlation_id`,
  `status` — pas le `result.summary`).
- **Rotation HMAC** via `session.callback_hmac_key_id` :
  1. Distribuer la nouvelle clé `v2` à Docker.
  2. ag.flow continue d'utiliser `v1` quelque temps (sessions existantes).
  3. ag.flow bascule sur `v2` pour les nouvelles sessions.
  4. Docker accepte `v1` une période grace, puis le retire.

---

## 9. OpenAPI fragment (côté ag.flow)

```yaml
paths:
  /api/v1/hooks/docker/task-completed:
    post:
      tags: [hooks]
      summary: Hook reçu de Docker à la fin d'un work
      operationId: dockerHookTaskCompleted
      parameters:
        - in: header
          name: X-Agflow-Hook-Id
          required: true
          schema: { type: string, format: uuid }
        - in: header
          name: X-Agflow-Timestamp
          required: true
          schema: { type: string, format: date-time }
        - in: header
          name: X-Agflow-Signature
          required: true
          schema:
            type: string
            pattern: ^hmac-sha256=[0-9a-f]{64}$
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: 'https://agflow.dev/contracts/hook-docker-task-completed.schema.json'
      responses:
        '200': { description: Hook accepté }
        '400': { description: Payload invalide }
        '401': { description: Signature HMAC invalide }
        '500': { description: Erreur serveur ag.flow — Docker doit retry }
```

---

## 10. Checklist d'implémentation Docker

- [ ] Lire `session.callback_url`, `session.callback_hmac_key_id` lors de la
      création de session — les conserver pour tous les hooks de la session.
- [ ] Lire `_agflow_action_execution_id`, `_agflow_correlation_id` (UUID v4
      stricts) depuis `body.instruction` du `POST /work` — les conserver pour
      le hook de fin.
- [ ] Charger la clé HMAC correspondant à `callback_hmac_key_id`.
- [ ] À la fin du work (succès / échec / annulation), construire le body
      conforme au schéma §4.4.
- [ ] Calculer la signature HMAC (cf. §3.1).
- [ ] POST sur `session.callback_url` avec les 3 headers + body.
- [ ] Retry avec backoff sur 5xx (cf. §2).
- [ ] Logger localement chaque tentative avec `hook_id`, `task_id`,
      `correlation_id` pour traçabilité.
- [ ] Cas particuliers :
  - `session.callback_url` absent → ne pas appeler de hook (mode legacy/debug).
  - Task tuée par admin (pas par hook) → status `cancelled` avec
    `error.code = USER_CANCELLED`.

---

## 11. Évolutions prévues (V2+)

Hors-scope V1 :

- Hook **`task-progress`** intermédiaire (pourcentage / step courant).
- Hook **log streaming** chunk par chunk.
- Hook **`runtime-ready`** émis par Docker quand un project_runtime est
  entièrement provisionné (au lieu de polling côté ag.flow).
- Hook **`resource-status-changed`** quand une resource bascule
  (ready ↔ pending_setup ↔ failed).
- Webhook bidirectionnel pour annulation (ag.flow demande l'annulation).
- mTLS en alternative à HMAC.

---

## 12. Questions ouvertes

1. **Distribution de la clé HMAC initiale** : variable d'env via gestionnaire
   de secrets ? Endpoint admin Docker `/admin/hmac-keys` ?
2. **Format `correlation_id` (UUID v4 obligatoire)** : OK pour V1 ; à
   standardiser W3C Trace Context en V2 ?
3. **`artifacts.uri`** : convention `docker://documents/{uuid}` figée ou détail
   d'implémentation Docker ?
4. **Rate limiting** côté ag.flow sur le hook : V1 = aucun, V2 si plusieurs
   Docker services concurrents.
5. **Compatibilité ag.flow derrière proxy/CDN** : endpoint dédié sans cache ?
