# M6 Supervision — Phase 2b (WebSocket push)

**Date** : 2026-05-17
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Compléter la supervision livrée en Phase 2a (polling 5s) par un mécanisme de push temps-réel via WebSocket. Les changements pertinents (création/destruction d'instance, changement de status, ouverture/fermeture de session) sont diffusés immédiatement aux clients d'administration connectés à `/supervision`, qui invalident leurs queries TanStack et re-fetch.

Le polling 5s livré en Phase 2a **reste actif en parallèle** : il sert de fallback automatique quand le WS est déconnecté ou en cours de reconnexion.

## Contexte

### Acquis Phase 2a (commits sur `dev`, dernier `8e3b7a3`)

- Page `/supervision` avec 4 KPI cards, table filtrable, drawer détail
- Polling 5s sur `useOverview`, `useInstances`, `useInstanceDetail`
- Backend supervision déjà en place (`/api/admin/supervision/{overview,instances,instances/{id}}`)

### Backend existant côté pub/sub

- Le MOM bus utilise déjà `pg_notify` pour la diffusion des messages inter-agents (`backend/src/agflow/mom/publisher.py:37` : `SELECT pg_notify($1, $2)`).
- Endpoints WebSocket existants (patron de référence) :
  - `/api/v1/sessions/{sid}/agents/{iid}/stream` — messages MOM d'une instance
  - `/api/v1/sessions/{sid}/stream` — events de session
  - `/api/admin/containers/{cid}/terminal` — terminal Docker

### Mutations à hooker

`agents_instances_service.py` : 5 points `UPDATE ... SET status` ou destroyed_at, 1 INSERT.
`sessions_service.py` : 3 points (`status='closed'`, `status='expired'`, INSERT initial).

## Décisions structurantes (tranchées en brainstorming)

| # | Question | Décision | Rationale |
|---|---|---|---|
| 1 | Transport pub/sub | **PostgreSQL `LISTEN/NOTIFY`** (channel `supervision_events`) | Réutilise le pattern déjà en place pour le MOM bus. Pas de nouveau service (Redis évité). Multi-instance backend safe (Postgres broadcast cluster-wide). |
| 2 | Granularité payload | **Event-rich** : `{"type": "<event>", "id": "<uuid>", ...}` | Permet une invalidation TanStack chirurgicale (vs. invalidate-all). Logs serveur clairs. Évolutif vers event-full plus tard. |
| 3 | Stratégie fallback | **Polling 5s continu** (Phase 2a) + WS prioritaire | Pas de toggle, pas d'état "perdu". Si WS down, polling reprend automatiquement. |
| 4 | Auth WS | **JWT query param `?token=<jwt>`** | Cohérent avec patron existant (`/api/v1/sessions/.../stream`). Limite : token visible dans logs d'access — acceptable en interne admin. |
| 5 | Events MOM delivery | **Pas d'event sur changements de `agent_message_delivery`** | Volume potentiel trop élevé (centaines/sec). Polling 5s reste suffisamment frais pour les compteurs MOM. |
| 6 | Multi-pod / réplicas | **Supporté par construction** | LISTEN/NOTIFY est cluster-wide. Un pod publie, tous les pods avec clients connectés relaient. |

## Catalogue d'events

5 events, payloads JSON sérialisés via `pg_notify` (max 8KB, on est à ~80 octets) :

| Event type | Émis par | Quand | Payload |
|---|---|---|---|
| `instance.created` | `agents_instances_service.create()` | Après INSERT | `{"type":"instance.created","id":"<uuid>","session_id":"<uuid>"}` |
| `instance.status_changed` | `agents_instances_service.update_status()` | Après UPDATE status | `{"type":"instance.status_changed","id":"<uuid>"}` |
| `instance.destroyed` | `agents_instances_service.destroy()` | Après UPDATE destroyed_at | `{"type":"instance.destroyed","id":"<uuid>"}` |
| `session.created` | `sessions_service.create()` | Après INSERT | `{"type":"session.created","id":"<uuid>"}` |
| `session.closed` | `sessions_service.close()` / `expire()` | Après UPDATE status | `{"type":"session.closed","id":"<uuid>","status":"closed"\|"expired"}` |

L'invalidation côté frontend mappe :
- `instance.*` → invalide `["supervision","overview"]` + `["supervision","instances"]` + `["supervision","instance", id]` si id présent
- `session.*` → invalide `["supervision","overview"]`

## Architecture backend

### Fichiers

| Fichier | Responsabilité | Lignes cible |
|---|---|---|
| `backend/src/agflow/services/supervision_events.py` (nouveau) | 5 fonctions `publish_*` (1 par event type) + async generator `listen_events()` utilisé par l'endpoint WS | ~120 |
| `backend/src/agflow/api/admin/supervision_stream.py` (nouveau) | `@router.websocket("/api/admin/supervision/stream")` — auth JWT query param, asyncpg `add_listener`, broadcast | ~100 |
| `backend/src/agflow/services/agents_instances_service.py` (modif) | Appels `publish_instance_created/status_changed/destroyed` aux 5 UPDATE points + INSERT | +~15 |
| `backend/src/agflow/services/sessions_service.py` (modif) | Appels `publish_session_created/closed` aux 3 points | +~10 |
| `backend/src/agflow/main.py` (modif) | `include_router(admin_supervision_stream_router)` | +2 |

### Comportement publisher

`publish_*` appelle `pool.execute("SELECT pg_notify('supervision_events', $1)", json_payload)` dans un `try/except` qui loggue un warning structlog en cas d'échec mais ne propage **pas** l'erreur (la mutation métier reste atomique).

### Comportement WS endpoint

```python
@router.websocket("/api/admin/supervision/stream")
async def supervision_stream(websocket: WebSocket, token: str = Query(...)):
    # 1. Auth via JWT (réutilise le décodeur token existant + check rôle admin)
    # 2. accept()
    # 3. Récupère une connexion asyncpg dédiée du pool
    # 4. await conn.add_listener("supervision_events", callback)
    #    callback enqueue les events dans une asyncio.Queue locale
    # 5. boucle : pop queue → websocket.send_text(payload)
    # 6. finally : remove_listener + close conn
```

Heartbeat WebSocket : FastAPI/Starlette envoient automatiquement des ping/pong toutes les 20s par défaut. Aucune logique custom requise pour le keepalive.

## Architecture frontend

### Fichiers

| Fichier | Responsabilité | Lignes cible |
|---|---|---|
| `frontend/src/hooks/useSupervisionStream.ts` (nouveau) | Hook qui ouvre `WS /api/admin/supervision/stream?token=<jwt>`, reconnect avec backoff exponentiel 1s → 30s, invalide queries TanStack sur event reçu, expose un `status: "connecting"\|"open"\|"closed"` | ~110 |
| `frontend/src/components/supervision/SupervisionStreamIndicator.tsx` (nouveau) | Petit indicateur visuel : 🟢 connected / 🟡 reconnecting / ⚪ disconnected (en haut à droite de la PageHeader, à côté du bouton refresh) | ~60 |
| `frontend/src/pages/SupervisionPage.tsx` (modif) | Appelle `useSupervisionStream()` au mount, intègre l'indicateur dans le slot `actions` du PageHeader | +5 |
| `frontend/src/i18n/{fr,en}.json` (modif) | Bloc `supervision.ws.{connected,disconnected,reconnecting,title}` (~4 clés × 2 langues) | +20 |

### Hook `useSupervisionStream`

- `useEffect` au mount, déconnecte au unmount
- WebSocket URL construite via `import.meta.env.VITE_API_URL` ou fenêtre courante
- Reconnect : backoff exponentiel 1s, 2s, 4s, 8s, 16s, capped 30s, reset à 1s sur reconnect réussi
- Sur `onmessage` : parse JSON, mapping event type → `queryClient.invalidateQueries({ queryKey: [...] })`
- Pas de retry sur 401 (token expiré) → laisse le statut "closed" persistant ; l'utilisateur doit relogin

### Indicateur visuel

3 états mappés à un dot coloré + tooltip i18n :
- 🟢 (`bg-emerald-500`) `supervision.ws.connected` — "Temps-réel actif"
- 🟡 (`bg-amber-500 animate-pulse`) `supervision.ws.reconnecting` — "Reconnexion..."
- ⚪ (`bg-muted-foreground`) `supervision.ws.disconnected` — "Hors-ligne (polling 5s)"

## Tests

### Backend (pytest, ~10 tests)

| Fichier | Tests |
|---|---|
| `backend/tests/services/test_supervision_events.py` | 5 tests : 1 par `publish_*`, vérifient que `pg_notify` est appelé avec le bon channel et le bon payload JSON sérialisé |
| `backend/tests/api/test_admin_supervision_stream.py` | 5 tests : WS sans token → 401/403 ; WS avec token invalide → 401 ; WS admin → connecte ; émission `pg_notify` côté DB → message reçu côté client ; close propre côté serveur sur cancel client |

### Frontend (Vitest, ~4 tests)

| Fichier | Tests |
|---|---|
| `frontend/tests/hooks/useSupervisionStream.test.tsx` | 4 tests : ouvre WS au mount avec token en query param ; reçoit un event `instance.status_changed` → `invalidateQueries` appelé sur les bonnes keys (incluant `["supervision","instance", id]`) ; status passe à "open" puis "closed" sur close ; reconnect avec backoff exponentiel (mock timers Vitest) |

Pas de tests pour `SupervisionStreamIndicator` (composant trivial à 3 états, couvert visuellement à la validation E2E).

## Error handling

| Scénario | Comportement |
|---|---|
| `pg_notify` échoue (DB down, channel introuvable) | `try/except` côté publisher : log warning structlog, pas de propagation. La mutation métier reste atomique. Polling 5s prendra le relais. |
| WS endpoint déconnecté côté serveur (DB pool fermé, exception non gérée) | `finally` : `remove_listener` + retour connexion au pool. Client reçoit `WebSocketDisconnect`, déclenche reconnect frontend. |
| Client WS abandonné sans close (browser killed) | Ping/pong FastAPI built-in (20s) détecte et close côté serveur. |
| Token JWT expire pendant connexion | WS reste ouvert (validé seulement à l'open). Reconnexion suivante → 401 → status "closed" persistant. Pas de boucle. |
| Event publié avant qu'un client soit connecté | Transient by design. OK : polling 5s repassera. |
| Plusieurs clients admin simultanés | Chacun a son `add_listener` sur le même channel. Postgres broadcast naturellement. Pas d'état partagé côté Python. |
| Burst de 50 events en 100ms | TanStack Query debounce naturellement les invalidations (queries marquées "stale", refetch unique suit). Pas de throttle custom requis. |
| Multi-pod backend (réplicas) | LISTEN/NOTIFY est cluster-wide. Un pod publie, tous les pods avec clients connectés relaient. Aucune logique custom. |

## Volume et estimation

| Catégorie | Lignes |
|---|---|
| Code backend (2 nouveaux + 3 modifs) | ~290 |
| Code frontend (2 nouveaux + 2 modifs + i18n) | ~190 |
| Tests pytest + Vitest | ~250 |
| Spec (ce doc) | ~240 |
| **Total** | **~970 lignes** |

**Effort estimé** : 2-3 jours en mode pipeline allégé.

## Hors scope explicite

- Replay/historique des events manqués → polling 5s couvre les périodes "down" du WS, c'est le contrat de fiabilité retenu.
- Filtres côté serveur (n'envoyer que les events qui matchent le filtre status courant du client) → simplification : le client filtre déjà côté UI.
- Events MOM delivery (`pending → claimed → failed`) → trop fréquents, polling 5s reste pertinent.
- Server-Sent Events alternative → WS choisi pour cohérence avec patron existant.
- Compression `permessage-deflate` → non activée, payloads minuscules.

## Migration et compat

Pas de breaking change. Phase 2a reste fonctionnelle si Phase 2b est déployée sans le frontend (le WS endpoint est juste inutilisé). Le frontend Phase 2b est rétro-compatible avec un backend Phase 2a (le WS échouera, polling 5s prendra le relais, indicateur reste ⚪).
