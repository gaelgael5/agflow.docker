# MOM Bus — Design

**Date** : 2026-04-15
**Scope** : Module 5e — bus de communication central entre utilisateurs / orchestrateurs / agents / autres agents
**Status** : design validé, prêt pour plan d'implémentation

## Contexte

Aujourd'hui, le chat de test d'un agent (M1) lance un container one-shot via `subprocess bash run.sh`, lui pousse une `task.json` sur stdin, lit stdout ligne par ligne, renvoie au client HTTP. Pas de bus, pas de persistance, pas de multi-consumer, pas d'inter-agents.

Pour que M4 (composition multi-agents), M5 (API publique) et M6 (supervision) fonctionnent, il faut un **middleware orienté messages (MOM)** qui soit l'unique canal d'entrée/sortie des agents. La spec M5e impose **Redis Streams avec consumer groups** comme transport.

Le design ci-dessous traite ce point sans refondre tout le flux : le MOM remplace le pipe stdin/stdout direct entre backend et container, mais garde le modèle one-shot de la V1 (un container par instruction). Les agents long-running restent une évolution future.

## Principes directeurs

1. **Deux couches séparées, contrats opposés**
   - **Bus (publisher / consumer)** : totalement générique. Ne connaît ni Mistral, ni Claude, ni la forme du `payload`. Sérialise/persiste/route des enveloppes opaques.
   - **Adapter (par famille d'agent)** : spécifique, extensible. Traduit enveloppe ⇄ IO natif du container.
2. **Les producteurs fournissent seulement la sémantique du message.** Client HTTP et agent ne remplissent que `kind`, `payload` et (optionnellement) `route`. Le backend écrit systématiquement les métadonnées d'audit : `v`, `msg_id`, `session_id`, `instance_id`, `direction`, `timestamp`, `source`. Un producteur ne peut ni forger son identité, ni dater un message dans le passé.
3. **Tools hors-bus**. Les appels MCP, skills et tools natifs du CLI ne transitent **pas** par le bus. Le bus porte les conversations (user↔agent, agent↔agent), pas les outils.
4. **Labels en metadata, target en string préfixée**. Le routage inter-agent est posé maintenant pour permettre plus tard teams/pools/sélecteurs sans breaking change.
5. **Tolérant aux producteurs non-conformes**. Une ligne non-JSON d'un agent → wrappée en `event/text/raw`. Jamais de crash du bus à cause d'un agent mal foutu.

## Enveloppe v1

Toute entrée/sortie sur le bus partage la même enveloppe, sérialisée JSON. C'est la **seule** structure que le bus parse.

```json
{
  "v": 1,
  "msg_id": "01HXY7ABC123...",
  "session_id": "sess-42",
  "instance_id": "agent-tech-lead-abc",
  "direction": "in" | "out",
  "timestamp": "2026-04-15T17:30:00.123Z",
  "source": "api_key:k_12" | "agent:xyz" | "user:g.beard" | "system",
  "kind": "instruction" | "cancel" | "event" | "result" | "error",
  "payload": { ... },
  "route": {
    "target": "agent:{instance_id}" | "team:{name}" | "pool:{name}" | "session:{id}",
    "policy": "direct"
  }
}
```

### Champs

| Champ | Type | Obligatoire | Rempli par |
|---|---|---|---|
| `v` | int | oui | backend (constant = 1) |
| `msg_id` | string | oui | backend (ID du `XADD`) |
| `session_id` | string | oui | backend (contexte HTTP / instance) |
| `instance_id` | string | oui | backend (contexte HTTP / instance) |
| `direction` | enum | oui | backend (`in` côté entrée, `out` côté sortie) |
| `timestamp` | ISO8601 | oui | backend |
| `source` | string | oui | backend (depuis auth pour `in`, `agent:{id}` pour `out`) |
| `kind` | enum | oui | producteur (client ou agent) |
| `payload` | object | oui | producteur |
| `route` | object | non | producteur si inter-agent |
| `route.target` | string | oui si `route` | producteur |
| `route.policy` | enum | non | producteur (défaut `direct`) |

### Vocabulaire `kind` (fermé, extensible par ajout rétrocompatible)

| kind | direction | sémantique |
|---|---|---|
| `instruction` | in | ordre à l'agent (user, inter-agent, orchestrateur) |
| `cancel` | in | demande d'arrêt |
| `event` | out | progrès, log, stream LLM, n'importe quelle sortie intermédiaire |
| `result` | out | fin de tâche, succès ou échec |
| `error` | out | erreur runtime (crash, timeout, format invalide) |

Non introduits pour V1 : `tool_call`, `tool_result`, `heartbeat`, `agent_message`. Ajoutables plus tard sans breaking change — les consumers actuels ignoreront les kinds inconnus.

### Conventions de `payload` (souples, jamais imposées)

- `payload.text: string` — cas simple, texte libre (99 % des cas).
- `payload.data: object` — structure riche quand un agent émet un format natif (ex: streaming LLM).
- `payload.format: "agent-name/v1"` — namespacing optionnel pour les consumers spécialisés qui veulent interpréter `data`.
- Le bus ne valide que la présence de `payload` ; son contenu est opaque.

Exemples :
```json
{"kind":"event","payload":{"text":"Analyse de login.py"}}
{"kind":"event","payload":{"data":{"role":"assistant","content":"..."},"format":"mistral.stream/v1"}}
{"kind":"result","payload":{"status":"success","exit_code":0}}
{"kind":"error","payload":{"message":"container exited with code 137","code":"oom","fatal":true}}
```

## Routage

### Préfixes de `route.target`

| Préfixe | Sens | V1 |
|---|---|---|
| `agent:{instance_id}` | target précise | **implémenté** |
| `team:{name}` | n'importe quel agent labelé `team=name` dans la session | parsé, rejeté runtime → `error/route_type_not_yet_supported` |
| `pool:{name}` | n'importe quel agent labelé `pool=name` | idem |
| `session:{id}` | broadcast aux agents de la session (utile pour `cancel`) | idem |

### Labels

Chaque instance d'agent porte un dictionnaire de labels, défini à la composition (M4) et stocké avec l'instance :

```sql
ALTER TABLE agents_instances
    ADD COLUMN labels JSONB NOT NULL DEFAULT '{}';
CREATE INDEX agents_instances_labels_team_idx ON agents_instances ((labels->>'team'));
CREATE INDEX agents_instances_labels_pool_idx ON agents_instances ((labels->>'pool'));
```

Clés réservées fixées dès maintenant (pour cohérence future) :
- `team` (string)
- `pool` (string)
- `role` (string, libre)

Toute autre clé K/V est autorisée (prépare les selectors futurs). V1 ne les lit pas.

### Streams Redis — naming plat

```
agent:{instance_id}:in      # une instance, un stream entrant
agent:{instance_id}:out     # une instance, un stream sortant
```

Les labels vivent en DB, pas dans les noms de streams. Si on fédère sur plusieurs Redis un jour (un par pool sur une machine différente), on ajoutera un préfixe au niveau du **connecteur réseau**, pas du schema des streams.

## Composants

### 1. `envelope.py`

```python
from enum import StrEnum
from pydantic import BaseModel, Field

class Kind(StrEnum):
    INSTRUCTION = "instruction"
    CANCEL = "cancel"
    EVENT = "event"
    RESULT = "result"
    ERROR = "error"

class Direction(StrEnum):
    IN = "in"
    OUT = "out"

class Route(BaseModel):
    target: str  # validated by prefix regex
    policy: str = "direct"

class Envelope(BaseModel):
    v: int = 1
    msg_id: str
    session_id: str
    instance_id: str
    direction: Direction
    timestamp: datetime
    source: str
    kind: Kind
    payload: dict
    route: Route | None = None
```

### 2. `publisher.py` — générique, aucune connaissance d'agent

```python
class MomPublisher:
    def __init__(self, redis: aioredis.Redis): ...

    async def publish(
        self,
        *,
        session_id: str,
        instance_id: str,
        direction: Direction,
        source: str,
        kind: Kind,
        payload: dict,
        route: Route | None = None,
    ) -> str:
        """Construit l'enveloppe, XADD, retourne le msg_id.
        Seul endroit qui fait XADD dans tout le code."""
```

Clé du stream déterminée par `direction` et `instance_id` (ou `target` si fan-out par le Router — mais le Router appelle aussi `publish()` comme tout le monde).

### 3. `consumer.py` — générique

```python
class MomConsumer:
    def __init__(self, redis: aioredis.Redis, group: str, consumer_name: str): ...

    async def ensure_group(self, stream: str) -> None: ...

    async def iter_messages(self, stream: str) -> AsyncIterator[Envelope]:
        """XREADGROUP boucle. Yield Envelope. L'appelant doit ACK."""

    async def ack(self, stream: str, msg_id: str) -> None: ...

    async def autoclaim_pending(self, stream: str, min_idle_ms: int) -> list[Envelope]:
        """XAUTOCLAIM pour récupérer les messages coincés par un consumer crashé."""
```

### 4. `adapters/base.py`

```python
class AgentAdapter(Protocol):
    name: str  # "mistral", "claude", "aider", "generic"

    def format_stdin(self, envelope: Envelope) -> bytes:
        """Enveloppe entrante → octets écrits sur stdin du container.
        A accès à envelope.source et envelope.payload pour adapter le format."""

    def parse_stdout_line(self, raw: str) -> tuple[Kind, dict] | None:
        """Une ligne stdout → (kind, payload) minimal. None = skip.
        Implémentation par défaut = wrap raw en (EVENT, {text: raw, format: "raw"})."""
```

### 5. `adapters/generic.py`

Fallback universel :
- `format_stdin` → émet `{"task_id": msg_id, "payload": payload}` en JSON sur stdin (contrat historique).
- `parse_stdout_line` → essaie `json.loads(line)`. Si objet avec `kind` + `payload` valides → retourne tel quel. Sinon → `(EVENT, {"text": line, "format": "raw"})`.

### 6. `adapters/mistral.py`

Spécialisation pour les containers Mistral Vibe :
- `format_stdin` → identique au générique (Mistral lit `TASK_JSON` sur stdin).
- `parse_stdout_line` → parse le streaming JSON de `vibe -p --output streaming`. Ignore `role=system/user`, retient `role=assistant` (+ `tool_calls` éventuels).

Même frontière pour Claude, Aider, etc. quand ils viendront.

### 7. `dispatcher.py`

Classe accrochée au cycle de vie du container. Orchestre :

```python
class AgentDispatcher:
    def __init__(
        self,
        adapter: AgentAdapter,
        publisher: MomPublisher,
        consumer: MomConsumer,
        container: DockerContainer,
        session_id: str,
        instance_id: str,
    ): ...

    async def run(self) -> None:
        """Tâches concurrentes:
        - in_loop: iter_messages agent:{id}:in → adapter.format_stdin → container.stdin
        - out_loop: container.stdout line → adapter.parse_stdout_line → publisher.publish(OUT)
        - termination: quand result reçu ou container exit → publish result si manquant
        """
```

### 8. `consumers/router.py` — spécialisé mais générique (aucune connaissance d'agent)

S'abonne à `agent:*:out`. Quand `envelope.route.target` est présent :
- `agent:X` → `publisher.publish(direction=IN, instance_id=X, kind=envelope.kind, payload=envelope.payload, source=envelope.source)`.
- `team:*` / `pool:*` / `session:*` → `publisher.publish(OUT, kind=ERROR, payload={"message": "route_type_not_yet_supported", "target": target}, source="system")` vers la source initiale, puis ACK.

### 9. `consumers/tracing.py`

S'abonne à `agent:*:out` (et optionnellement `:in`) ; insère chaque enveloppe en Postgres pour M5f. Non critique pour V1 du MOM mais trivial à brancher.

### 10. `consumers/ws_push.py`

S'abonne à `agent:*:out` pour une `instance_id` donnée (stream d'une WebSocket client). Pousse les enveloppes vers le client. Sert le endpoint `WebSocket /api/v1/sessions/{s}/agents/{i}/stream`.

## Flow de bout en bout

```
Web/HTTP client
  │
  ├── POST /api/v1/sessions/{s}/agents/{a}/message  { "kind":"instruction", "payload":{"text":"..."} }
  ▼
Backend REST handler
  │ enrichit l'enveloppe (msg_id, session_id, instance_id, direction=in, source, timestamp, v)
  ▼
MomPublisher.publish()  ──XADD agent:{a}:in──▶ Redis
                                                    │
                                                    │ XREADGROUP
                                                    ▼
                                              AgentDispatcher (instance {a})
                                                    │
                                                    │ adapter.format_stdin(envelope)
                                                    ▼
                                                Docker container stdin
                                                    │
                                                    │ agent CLI runs...
                                                    ▼
                                                Docker container stdout
                                                    │
                                                    │ line by line
                                                    ▼
                                              AgentDispatcher
                                                    │ adapter.parse_stdout_line(line) → (kind, payload)
                                                    ▼
                                              MomPublisher.publish() ──XADD agent:{a}:out──▶ Redis
                                                                                                │
                                                                ┌───────────────────────────────┼──────────────────────────┐
                                                                ▼                               ▼                          ▼
                                                         ws_push consumer             tracing consumer              router consumer
                                                         push vers WebSocket       insert en Postgres           si route.target présent
                                                                                                                      ▼
                                                                                                           publish direction=in
                                                                                                           vers agent:{target}:in
```

## Composition M4 — labels et peers

La composition d'un agent enrichit ses metadata :

```yaml
agent:
  name: specialist-python
  dockerfile: mistral
  labels:
    team: python-specialists
    pool: default
    role: reviewer
```

À l'instanciation dans une session, le backend :
1. Crée la row `agents_instances` avec `labels` copiés.
2. Résout la liste des `peers` (autres agents de la même session avec leurs `instance_id` + labels).
3. Injecte dans l'environnement du container :
   - `AGFLOW_SELF_INSTANCE_ID`
   - `AGFLOW_SELF_LABELS` (JSON)
   - `AGFLOW_PEERS` (JSON liste `[{instance_id, labels}]`)
4. Le system prompt de l'agent (défini au niveau du rôle M2) reçoit la liste des peers, avec des instructions explicites sur qui contacter pour quoi. **Le prompt dit quoi dispatcher à qui.**

L'agent émet alors littéralement `route.target = "agent:specialist-python-xyz"` dans sa sortie. Pas de résolution côté adapter.

## Cas non traités en V1 (extensions prévues)

| Sujet | Pourquoi différé | Point d'extension prévu |
|---|---|---|
| `tool_call` / `tool_result` sur le bus | Les tools passent hors-bus (MCP direct). | Ajouter 2 kinds au vocabulaire ; consumer dédié qui mirror les MCP calls pour audit. |
| Routage `team:` / `pool:` / `session:` | MVP à 1 agent puis inter-agents directs suffit. | Router déjà câblé sur les préfixes, il suffit d'ajouter les branches de résolution. |
| `route.policy` = `broadcast` / `any` / `round_robin` | Sans team/pool, pas d'usage. | Champ déjà déclaré dans l'enveloppe. |
| Agents long-running | Complexifie le lifecycle et le cancel. | Dispatcher déjà une boucle `async for` sur les messages ; il suffira de ne pas terminer quand le container ne meurt pas. |
| Fédération multi-Redis (1 par pool) | Un seul Redis suffit pour dizaines d'agents. | Préfixer les stream names au niveau du connecteur, pas du schema. |
| MCP proxy pour audit | Latence et complexité, pas demandé pour V1. | Ajouter une classe qui s'interpose entre agent et serveur MCP et mirror vers le bus. |

## Livrables V1

1. Module `backend/src/agflow/mom/` : `envelope.py`, `publisher.py`, `consumer.py`, `dispatcher.py`.
2. Module `backend/src/agflow/mom/adapters/` : `base.py`, `generic.py`, `mistral.py`.
3. Module `backend/src/agflow/mom/consumers/` : `router.py`, `ws_push.py`, `tracing.py`.
4. Migration SQL : `agents_instances.labels JSONB` + 2 index + table messages pour traçabilité (schéma à préciser dans le plan d'impl).
5. Refactor de `container_runner.py` : l'ancien flux subprocess direct est remplacé par l'appel `AgentDispatcher.run()`.
6. Refactor de `entrypoint.sh` (Mistral) : lit l'enveloppe complète sur stdin, émet `{kind, payload}` minimal sur stdout, un `result` final.
7. Endpoints API : `POST /api/v1/sessions/{s}/agents/{a}/message`, `WS /api/v1/sessions/{s}/agents/{a}/stream`.
8. Tests : producteur → consumer roundtrip, adapter Mistral (format_stdin + parse_stdout_line), router direct-to-agent, wrapping tolérant des lignes non-conformes.

## Vérification

- `pytest backend/tests/mom/` passe (TDD rouge → vert pour chaque brique).
- Smoke test : depuis l'UI, envoyer un prompt à un agent Mistral dans une session → recevoir le stream propre via WebSocket, avec les messages archivés en Postgres.
- Inter-agent direct : composer 2 agents dans une session, prompt du tech-lead inclut l'`instance_id` du specialist, dispatcher un message → il arrive sur le specialist, son résultat revient.
- Cas d'erreur : route.target `team:x` → `error/route_type_not_yet_supported` renvoyée à la source ; ligne non-JSON d'un agent → wrapping `event/raw` sans crash.
