# MOM Bus — Design

**Date** : 2026-04-15
**Scope** : Module 5e — bus de communication central entre utilisateurs / orchestrateurs / agents / autres agents
**Status** : design validé, prêt pour plan d'implémentation

## Contexte

Aujourd'hui, le chat de test d'un agent (M1) lance un container one-shot via `subprocess bash run.sh`, lui pousse une `task.json` sur stdin, lit stdout ligne par ligne, renvoie au client HTTP. Pas de bus, pas de persistance, pas de multi-consumer, pas d'inter-agents.

Pour que M4 (composition multi-agents), M5 (API publique) et M6 (supervision) fonctionnent, il faut un **middleware orienté messages (MOM)** qui soit l'unique canal d'entrée/sortie des agents.

### Choix de transport : PostgreSQL, pas Redis

`specs/home.md` proposait initialement Redis Streams. Après analyse, on bascule sur **PostgreSQL comme transport du bus** (pattern `SELECT … FOR UPDATE SKIP LOCKED` + `LISTEN / NOTIFY`). Raisons :

- **Redis ne sert presque à rien dans la stack actuelle** — une seule utilisation (rate-limiting d'un endpoint login). Le garder uniquement pour le MOM ajoute un service à maintenir sans gain significatif.
- **Une seule source de vérité** : aligné avec la règle « PostgreSQL comme source de vérité unique » de `CLAUDE.md`. Le bus ET l'archive dans le même système, plus de divergence hot/cold.
- **Atomicité transactionnelle** entre publish d'un message et modification d'état applicatif (pas besoin d'outbox pattern).
- **Durabilité forte** native, sans tuning AOF/RDB.
- **Traçabilité gratuite** : les messages sont déjà en DB dès la publication. Plus de consumer dédié juste pour persister.
- **-1 service à opérer** dans le docker-compose.

Compromis acceptés :
- Latence ~50–100 ms (polling + `LISTEN/NOTIFY`) vs sub-ms Redis. Négligeable pour un stream LLM ligne-par-ligne (~500 ms entre lignes).
- Implémentation soigneuse du claim/ack/reclaim à la main (pattern standard, bien documenté).
- Charge DB additionnelle. Pour des dizaines de messages/s à notre échelle MVP, négligeable devant le reste du trafic CRUD.

L'abstraction `MomPublisher`/`MomConsumer` reste identique à ce qu'elle aurait été avec Redis — si on veut pivoter vers Redis Streams ou NATS plus tard (ex: fédération multi-machines), seules ces deux classes changent.

### Scope V1

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
  "msg_id": "a1b2c3d4-...",
  "parent_msg_id": "e5f6a7b8-..." | null,
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
| `msg_id` | UUID | oui | backend (généré par `gen_random_uuid()` à l'INSERT) |
| `parent_msg_id` | UUID | non | backend (chaînage : dispatch, fan-out, réponse à instruction) |
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

### Schéma Postgres du bus

Deux tables, rien d'autre :

```sql
-- Le log append-only. Jamais UPDATE, jamais DELETE (sauf purge planifiée).
CREATE TABLE agent_messages (
    msg_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_msg_id  UUID REFERENCES agent_messages(msg_id),  -- chaînage : dispatch, fan-out, réponse
    v              INT  NOT NULL DEFAULT 1,
    session_id     UUID NOT NULL,
    instance_id    UUID NOT NULL,   -- cible si direction='in', origine si direction='out'
    direction      TEXT NOT NULL CHECK (direction IN ('in','out')),
    kind           TEXT NOT NULL CHECK (kind IN ('instruction','cancel','event','result','error')),
    payload        JSONB NOT NULL,
    route          JSONB,           -- {target: "...", policy: "direct"} ou NULL
    source         TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON agent_messages (instance_id, direction, created_at);
CREATE INDEX ON agent_messages (session_id, created_at);
CREATE INDEX ON agent_messages (parent_msg_id) WHERE parent_msg_id IS NOT NULL;

-- L'état de livraison par consumer group. 1 ligne par (group, message).
CREATE TABLE agent_message_delivery (
    group_name    TEXT NOT NULL,
    msg_id        UUID NOT NULL REFERENCES agent_messages(msg_id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('pending','claimed','acked','failed')),
    claimed_at    TIMESTAMPTZ,
    claimed_by    TEXT,            -- identité du consumer (pid@host / worker id)
    acked_at      TIMESTAMPTZ,
    retry_count   INT NOT NULL DEFAULT 0,
    last_error    TEXT,
    PRIMARY KEY (group_name, msg_id)
);

CREATE INDEX ON agent_message_delivery (group_name, status, msg_id)
    WHERE status IN ('pending','claimed');
```

Analogie avec Redis Streams (pour comprendre la correspondance) :

| Redis Streams | Postgres MOM |
|---|---|
| Stream `agent:{id}:in` | Lignes de `agent_messages` avec `instance_id=X AND direction='in'` |
| Entrée `XADD` | INSERT transactionnel dans `agent_messages` + 1 INSERT delivery par group abonné |
| Consumer group | Valeur de `group_name` dans `agent_message_delivery` |
| `XREADGROUP` (claim) | `UPDATE … SET status='claimed' WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED)` |
| `XACK` | `UPDATE … SET status='acked', acked_at=now()` |
| Pending Entries List | Lignes `status='claimed'` |
| `XAUTOCLAIM` (reclaim) | Balayage périodique : `UPDATE … SET status='pending' WHERE status='claimed' AND claimed_at < now() - interval '30 seconds'` |
| `MAXLEN ~N` | Job périodique `DELETE FROM agent_messages WHERE created_at < now() - interval '30 days'` |

### Wake-up des consumers

Le polling seul donnerait 50–200 ms de latence. Pour descendre à ~10 ms, chaque `INSERT` suit d'un `pg_notify` :

```sql
SELECT pg_notify(
    'agent_' || instance_id || '_' || direction,
    msg_id::text
);
```

Les consumers font `LISTEN agent_<instance_id>_<direction>` (ou un canal générique `LISTEN agent_bus`) et lisent dès réception du signal. Si le consumer rate un `NOTIFY` (reconnexion DB, démarrage), le polling backup (1 Hz) finit par le rattraper.

### Consumer groups de la V1

Pas de découverte dynamique : les groupes abonnés à chaque direction sont définis en config :

| Direction | Groupes abonnés | Rôle |
|---|---|---|
| `in` (vers agent) | `dispatcher:{instance_id}` | lecture unique par le dispatcher de cet agent |
| `out` (depuis agent) | `ws_push`, `router`, `tracing` | 3 groupes indépendants |

À l'INSERT d'un message, le publisher génère les lignes de `agent_message_delivery` correspondantes (1 par groupe abonné à cette direction).

Les labels vivent en DB (colonne `agents_instances.labels`), pas dans le naming des messages. Si un jour on fédère sur plusieurs machines, on réutilisera la même table via pg-réplication ou FDW — ou on pivotera sur NATS JetStream, la couche d'abstraction `MomPublisher` isolant le transport.

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
    def __init__(self, pool: asyncpg.Pool, groups_config: dict[Direction, list[str]]):
        """groups_config déclare quels groups sont abonnés à chaque direction.
        Ex: {IN: ["dispatcher"], OUT: ["ws_push", "router", "tracing"]}."""

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
        """Construit l'enveloppe, INSERT dans agent_messages + 1 delivery par
        group abonné, émet un pg_notify, retourne le msg_id.
        Seul endroit qui fait INSERT dans tout le code. Transactionnel."""
```

Si le publisher est appelé à l'intérieur d'une transaction applicative (ex: lors d'un commit d'état), il réutilise la connexion en cours → atomicité gratuite entre publish et état métier.

### 3. `consumer.py` — générique

```python
class MomConsumer:
    def __init__(self, pool: asyncpg.Pool, group_name: str, consumer_id: str):
        """consumer_id identifie l'instance de ce worker (ex: f'{pid}@{host}')."""

    async def iter_messages(
        self,
        *,
        instance_id: UUID | None = None,
        direction: Direction | None = None,
        batch_size: int = 50,
    ) -> AsyncIterator[Envelope]:
        """Boucle: LISTEN sur le canal notify, puis claim batch via
        SELECT FOR UPDATE SKIP LOCKED + UPDATE status='claimed'.
        Yield les enveloppes une par une. L'appelant doit ACK après traitement."""

    async def ack(self, msg_id: UUID) -> None:
        """UPDATE status='acked', acked_at=now() pour (group_name, msg_id)."""

    async def fail(self, msg_id: UUID, error: str) -> None:
        """Marque échec: incrémente retry_count, repasse en pending ou 'failed'
        selon un seuil max_retries configurable."""

    async def reclaim_stale(self, max_idle: timedelta = timedelta(seconds=30)) -> int:
        """Balayage périodique: UPDATE status='pending' WHERE status='claimed'
        AND claimed_at < now() - max_idle. Retourne le nombre rebasculé.
        À appeler depuis un worker de supervision (M6)."""
```

Le claim se fait en une seule requête :

```sql
WITH claimed AS (
    SELECT d.msg_id
    FROM agent_message_delivery d
    JOIN agent_messages m USING (msg_id)
    WHERE d.group_name = $1
      AND d.status = 'pending'
      AND ($2::uuid IS NULL OR m.instance_id = $2)
      AND ($3::text IS NULL OR m.direction = $3)
    ORDER BY m.created_at
    FOR UPDATE OF d SKIP LOCKED
    LIMIT $4
)
UPDATE agent_message_delivery d
SET status = 'claimed',
    claimed_at = now(),
    claimed_by = $5
FROM claimed
WHERE d.group_name = $1 AND d.msg_id = claimed.msg_id
RETURNING d.msg_id;
```

`SKIP LOCKED` permet à N consumers concurrents dans le même groupe de se partager la file sans se bloquer.

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
        - in_loop: consumer.iter_messages(instance_id, IN) → adapter.format_stdin → container.stdin
        - out_loop: container.stdout line → adapter.parse_stdout_line → publisher.publish(OUT)
        - termination: quand result reçu ou container exit → publish result si manquant
        """
```

### 8. `consumers/router.py` — spécialisé mais générique (aucune connaissance d'agent)

Consumer group `router`, lit `agent_messages WHERE direction='out'`. Quand `envelope.route.target` est présent :
- `agent:X` → `publisher.publish(direction=IN, instance_id=X, kind=envelope.kind, payload=envelope.payload, source=envelope.source)`.
- `team:*` / `pool:*` / `session:*` → `publisher.publish(OUT, kind=ERROR, payload={"message": "route_type_not_yet_supported", "target": target}, source="system")` vers la source initiale, puis ACK.

### 9. `consumers/tracing.py`

Rôle particulier : comme les messages sont **déjà persistés** dans `agent_messages` par le publisher, ce consumer n'a **rien à écrire**. Il existe uniquement pour :
- exposer des métriques (compteur par kind/direction),
- ACK sa copie de delivery pour que le GC puisse purger les vieilles lignes proprement.

C'est la force du transport Postgres : **la persistance est un effet de bord gratuit de la publication**. `GET /api/v1/sessions/{s}/agents/{i}/messages` est simplement `SELECT * FROM agent_messages WHERE … ORDER BY created_at` — pas de consumer dédié à écrire.

### 10. `consumers/ws_push.py`

Consumer group `ws_push_{ws_connection_id}` (un groupe éphémère par WebSocket cliente connectée). Lit `agent_messages WHERE instance_id=X AND direction='out'`. Pousse chaque enveloppe vers la WebSocket. À la déconnexion, le groupe est nettoyé (les lignes de delivery restantes peuvent être supprimées). Sert le endpoint `WebSocket /api/v1/sessions/{s}/agents/{i}/stream`.

## Flow de bout en bout

```
Web/HTTP client
  │
  ├── POST /api/v1/sessions/{s}/agents/{a}/message  { "kind":"instruction", "payload":{"text":"..."} }
  ▼
Backend REST handler
  │ enrichit l'enveloppe (msg_id, session_id, instance_id, direction=in, source, timestamp, v)
  ▼
MomPublisher.publish()  ──INSERT agent_messages + delivery + pg_notify──▶ Postgres
                                                    │
                                                    │ LISTEN + SELECT FOR UPDATE SKIP LOCKED
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
                                              MomPublisher.publish() ──INSERT agent_messages + delivery──▶ Postgres
                                                                                                │
                                                                ┌───────────────────────────────┼──────────────────────────┐
                                                                ▼                               ▼                          ▼
                                                         ws_push consumer             tracing consumer              router consumer
                                                         push vers WebSocket       (archive déjà en DB,          si route.target présent
                                                                                    juste ACK pour le group)              ▼
                                                                                                           publish direction=in
                                                                                                           vers instance target
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

L'agent émet alors littéralement `route_to = "agent:specialist-python-xyz"` dans sa sortie JSON. L'adapter reconnaît ce champ, le mappe vers `route.target` dans l'enveloppe, et le supprime du `payload`.

## Chaînage des messages (`parent_msg_id`)

Chaque message peut référencer le message qui l'a déclenché via `parent_msg_id`. Cela permet de reconstruire les arbres de conversations : instruction → events → result, dispatch → fan-out → réponses.

### Quand `parent_msg_id` est rempli

| Situation | `parent_msg_id` |
|---|---|---|
| Message initial (user → agent via API) | `NULL` |
| Router re-publie un OUT comme IN vers un autre agent | `msg_id` du message OUT original |
| Agent répond (direction=out) à une instruction reçue (direction=in) | `msg_id` du message IN qui l'a déclenché |
| Événements de progression (stdout) pendant le traitement d'une instruction | `msg_id` de l'instruction IN en cours |

Le dispatcher connaît le `msg_id` de l'instruction courante (il vient de la consommer) et le transmet au publisher pour chaque ligne de sortie.

### Requêtes de traçabilité

```sql
-- Qui a consommé (reçu en IN) un message produit par l'agent tech-lead ?
SELECT * FROM agent_messages WHERE parent_msg_id = $original_msg_id;

-- Chaîne complète instruction → dispatch → sous-résultats (CTE récursif)
WITH RECURSIVE chain AS (
    SELECT *, 0 AS depth FROM agent_messages WHERE msg_id = $root_msg_id
    UNION ALL
    SELECT m.*, c.depth + 1 FROM agent_messages m JOIN chain c ON m.parent_msg_id = c.msg_id
)
SELECT depth, instance_id, direction, kind, payload->>'text' AS preview, source, created_at
FROM chain ORDER BY created_at;
```

## Routage additif

Le routage vers un autre agent est **additif** : le message reste visible par tous les consumer groups OUT habituels (ws_push, tracing, router). L'utilisateur voit toujours tout ce que l'agent produit, y compris les dispatches inter-agents. L'UI peut afficher les messages routés avec un badge "→ dispatché à X".

Concrètement :
- Message OUT avec `route=null` → ws_push + tracing l'ACK. Router ignore.
- Message OUT avec `route.target="agent:X"` → ws_push + tracing l'ACK. Router crée un **nouveau** message IN pour agent X avec `parent_msg_id` pointant vers l'original.

Fan-out (futur) : si `route.target="team:python"`, le Router crée N messages IN (un par agent du team), tous chaînés au même parent.

## Signature adapter enrichie

L'adapter retourne un 3e élément optionnel (`Route | None`) pour le routage :

```python
class AgentAdapter(Protocol):
    name: str

    def format_stdin(self, envelope: Envelope) -> bytes:
        """Enveloppe entrante → octets à écrire sur stdin du container."""

    def parse_stdout_line(self, raw: str) -> tuple[Kind, dict, Route | None]:
        """Une ligne stdout → (kind, payload, route optionnel).
        Route is extracted from agent-specific conventions (e.g. 'route_to' field).
        GenericAdapter retourne toujours None pour route."""
```

Pour le `MistralAdapter` : si le JSON de la ligne contient un champ `route_to`, l'adapter le retire du payload et le convertit en `Route(target=route_to)`.

## Observabilité

Tout est en Postgres — l'observation est un `SELECT`.

### Endpoints admin

| Endpoint | Données |
|---|---|
| `GET /api/admin/mom/dashboard` | Agents : instance_id, status, labels, last_activity, error_count |
| `GET /api/admin/mom/consumers` | Santé consumers : group_name, pending, in_flight, acked, failed, oldest_pending |
| `GET /api/admin/mom/messages?instance_id=&kind=&direction=&limit=` | Timeline messages brute, enveloppes complètes |
| `GET /api/admin/mom/chain?msg_id=` | CTE récursif : arbre complet depuis un msg_id racine |

### SupervisionPage (M6)

5 vues :
1. **Dashboard agents** — table instance / type / status / team / dernière activité / erreurs.
2. **Timeline messages** — chronologie d'une instance avec icônes direction, badges kind, preview texte.
3. **Santé consumers** — lag par group, alertes visuelles si pending > seuil.
4. **Erreurs** — liste filtrée `kind=error`, payload expandable.
5. **Graphe routage** — qui parle à qui (source → route.target), volumes.

## Cas non traités en V1 (extensions prévues)

| Sujet | Pourquoi différé | Point d'extension prévu |
|---|---|---|
| `tool_call` / `tool_result` sur le bus | Les tools passent hors-bus (MCP direct). | Ajouter 2 kinds au vocabulaire ; consumer dédié qui mirror les MCP calls pour audit. |
| Routage `team:` / `pool:` / `session:` | MVP à 1 agent puis inter-agents directs suffit. | Router déjà câblé sur les préfixes, il suffit d'ajouter les branches de résolution. |
| `route.policy` = `broadcast` / `any` / `round_robin` | Sans team/pool, pas d'usage. | Champ déjà déclaré dans l'enveloppe. |
| Agents long-running | Complexifie le lifecycle et le cancel. | Dispatcher déjà une boucle `async for` sur les messages ; il suffira de ne pas terminer quand le container ne meurt pas. |
| Fédération multi-machines | MVP mono-nœud, un Postgres suffit largement. | Options : (a) pg-replication logique + FDW ; (b) pivoter `MomPublisher`/`MomConsumer` vers NATS JetStream. Les deux restent confinés derrière l'abstraction. |
| MCP proxy pour audit | Latence et complexité, pas demandé pour V1. | Ajouter une classe qui s'interpose entre agent et serveur MCP et mirror vers le bus. |

## Livrables V1

1. Migration SQL : `agent_messages` + `agent_message_delivery` + index + `agents_instances.labels JSONB`.
2. Module `backend/src/agflow/mom/` : `envelope.py`, `publisher.py` (asyncpg), `consumer.py` (SKIP LOCKED + LISTEN/NOTIFY), `dispatcher.py`.
3. Module `backend/src/agflow/mom/adapters/` : `base.py`, `generic.py`, `mistral.py`.
4. Module `backend/src/agflow/mom/consumers/` : `router.py`, `ws_push.py`, `tracing.py`.
5. Refactor de `container_runner.py` : l'ancien flux subprocess direct est remplacé par l'appel `AgentDispatcher.run()`.
6. Refactor de `entrypoint.sh` (Mistral) : lit l'enveloppe complète sur stdin, émet `{kind, payload}` minimal sur stdout, un `result` final.
7. Endpoints API : `POST /api/v1/sessions/{s}/agents/{a}/message`, `WS /api/v1/sessions/{s}/agents/{a}/stream`, `GET /api/v1/sessions/{s}/agents/{a}/messages`.
8. Worker de supervision (M6) : job périodique `reclaim_stale()` (rebascule les claims zombies) + purge `DELETE FROM agent_messages WHERE created_at < now() - retention`.
9. Tests : producteur → consumer roundtrip, adapter Mistral (format_stdin + parse_stdout_line), router direct-to-agent, wrapping tolérant des lignes non-conformes, claim concurrent (deux consumers du même groupe ne prennent pas le même message), reclaim après crash.

### Retrait de Redis (bonus inclus dans la bascule)

La bascule Postgres rend Redis inutile dans la stack. À faire dans le même plan :

10. Migrer le rate-limiting de `auth/api_key.py` (`INCR` + `EXPIRE`) vers Postgres : table `rate_limit_counters (prefix, window_start, count)` + `ON CONFLICT DO UPDATE`. ~30 lignes.
11. Retirer le service `redis` de `docker-compose.prod.yml` et `docker-compose.yml`.
12. Retirer la dépendance `redis` de `backend/pyproject.toml`.
13. Supprimer le module `backend/src/agflow/redis/` et le réglage `redis_url` de `config.py`.

## Vérification

- `pytest backend/tests/mom/` passe (TDD rouge → vert pour chaque brique).
- Smoke test : depuis l'UI, envoyer un prompt à un agent Mistral dans une session → recevoir le stream propre via WebSocket, avec les messages archivés en Postgres (`SELECT * FROM agent_messages WHERE instance_id=... ORDER BY created_at`).
- Inter-agent direct : composer 2 agents dans une session, prompt du tech-lead inclut l'`instance_id` du specialist, dispatcher un message → il arrive sur le specialist, son résultat revient.
- Claim concurrent : lancer 2 workers dans le même consumer group, publier 100 messages → vérifier que chaque message est livré à **un** seul consumer (pas de doublon, pas de perte).
- Reclaim : publier un message, simuler crash du consumer après claim (kill -9), attendre `max_idle` → vérifier qu'un autre consumer du même groupe récupère le message.
- Cas d'erreur : route.target `team:x` → `error/route_type_not_yet_supported` renvoyée à la source ; ligne non-JSON d'un agent → wrapping `event/raw` sans crash.
- Retrait de Redis : `docker compose ps` ne liste plus `agflow-redis`, les tests de rate-limiting passent sur le nouveau backend Postgres.
