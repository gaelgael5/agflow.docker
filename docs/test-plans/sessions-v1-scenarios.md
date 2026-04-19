# Plan de test — Sessions V1 (10 scénarios E2E)

## Objectif

Valider le comportement de l'API Sessions V1 sur LXC 201 après déploiement, en couvrant
le chemin nominal, le scoping propriétaire, le bypass admin, l'expiration, l'extension,
la reconstruction d'agents, les contraintes FK, le routage inter-agents (MOM),
la durabilité WebSocket et le rate limit.

## Environnement

```bash
export API=http://192.168.10.158
```

Outils requis : `curl`, `jq`, `wscat` (`npm install -g wscat`)

## Tokens utilisés

| Variable     | Rôle                                     | Scopes                              |
|--------------|------------------------------------------|-------------------------------------|
| `TOKEN_A`    | Propriétaire non-admin (tests nominaux)  | `sessions:read sessions:write`      |
| `TOKEN_B`    | Étranger non-admin (tests scoping)       | `sessions:read sessions:write`      |
| `TOKEN_ADMIN`| Admin bypass (toutes ressources)         | `*`                                 |
| `TOKEN_RL`   | Token rate-limit bas (S10 uniquement)    | `sessions:read sessions:write`      |

### Générer les tokens de test

Se connecter à l'admin (`POST /api/admin/auth/login`) avec les credentials admin pour
obtenir un JWT. Utiliser ensuite `POST /api/admin/api-keys` pour créer chaque token.
Exemple pour TOKEN_A :

```bash
# 1. Login admin
ADMIN_JWT=$(curl -s -X POST $API/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"<password>"}' \
  | jq -r '.access_token')

# 2. Créer TOKEN_A (owner non-admin)
TOKEN_A=$(curl -s -X POST $API/api/admin/api-keys \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"test-owner-a","scopes":["sessions:read","sessions:write"],"rate_limit":120,"expires_in":"3m"}' \
  | jq -r '.full_key')

# 3. Créer TOKEN_B (étranger, propriétaire distinct)
TOKEN_B=$(curl -s -X POST $API/api/admin/api-keys \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"test-stranger-b","scopes":["sessions:read","sessions:write"],"rate_limit":120,"expires_in":"3m"}' \
  | jq -r '.full_key')

# 4. Créer TOKEN_ADMIN (bypass total)
TOKEN_ADMIN=$(curl -s -X POST $API/api/admin/api-keys \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"test-admin-bypass","scopes":["*"],"rate_limit":1000,"expires_in":"3m"}' \
  | jq -r '.full_key')

# 5. Créer TOKEN_RL (rate limit = 5/min — pour S10)
TOKEN_RL=$(curl -s -X POST $API/api/admin/api-keys \
  -H "Authorization: Bearer $ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name":"test-ratelimit","scopes":["sessions:read","sessions:write"],"rate_limit":5,"expires_in":"3m"}' \
  | jq -r '.full_key')

echo "TOKEN_A=$TOKEN_A"
echo "TOKEN_B=$TOKEN_B"
echo "TOKEN_ADMIN=$TOKEN_ADMIN"
echo "TOKEN_RL=$TOKEN_RL"
```

Exporter les variables avant d'exécuter les scénarios :

```bash
export TOKEN_A="agflow_..."
export TOKEN_B="agflow_..."
export TOKEN_ADMIN="agflow_..."
export TOKEN_RL="agflow_..."
```

---

## S1 — Chemin nominal : ouvrir → spawn agents → dialogue → fermer

**Description** : Créer une session, spawner un agent, lire la liste, poster un message,
observer le stream WebSocket, puis fermer proprement la session.

### Préconditions

- `TOKEN_A` exporté
- Au moins un agent présent dans le catalogue (vérifier avec
  `GET /api/v1/agents` — renvoie un tableau non vide ; noter le champ `slug`)
- `wscat` installé

### Étapes

```bash
# 1. Vérifier le catalogue et noter un slug valide
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/agents | jq '.[0].slug'
# Exemple de résultat : "agent-helper" — adapter AGENT_SLUG si différent
export AGENT_SLUG="agent-helper"

# 2. Créer la session
SESSION=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s1-nominal","duration_seconds":3600}')
echo $SESSION | jq .
export SID=$(echo $SESSION | jq -r '.id')
echo "Session ID: $SID"

# 3. Vérifier le statut initial
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID | jq '{status,expires_at}'

# 4. Ouvrir le stream WebSocket en arrière-plan (laisser tourner)
wscat -c "ws://192.168.10.158/api/v1/sessions/$SID/stream" &
WS_PID=$!

# 5. Spawner 1 agent
SPAWN=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1,\"mission\":\"Répondre aux questions de test\"}")
echo $SPAWN | jq .
export IID=$(echo $SPAWN | jq -r '.instance_ids[0]')
echo "Instance ID: $IID"

# 6. Lister les agents de la session
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID/agents | jq '.[].id'

# 7. Poster un message vers l'instance
MSG=$(curl -s -X POST $API/api/v1/sessions/$SID/agents/$IID/message \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"kind":"instruction","payload":{"text":"Hello from S1 test"}}')
echo $MSG | jq .

# 8. Lire les messages de la session
curl -s -H "Authorization: Bearer $TOKEN_A" \
  "$API/api/v1/sessions/$SID/messages?limit=10" | jq 'length'

# 9. Fermer la session
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"

# 10. Vérifier le statut final
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID | jq '.status'

kill $WS_PID 2>/dev/null
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 2 — Créer session | 201 | `id` UUID, `status=active`, `expires_at` dans ~1h |
| 3 — GET session | 200 | `status=active` |
| 5 — Spawn agent | 201 | `instance_ids` tableau de 1 UUID |
| 6 — List agents | 200 | Tableau avec 1 élément, `status=active` |
| 7 — POST message | 201 | `msg_id` UUID |
| 8 — GET messages | 200 | Longueur >= 1 |
| 9 — DELETE session | 204 | Corps vide |
| 10 — GET session après close | 200 | `status=closed` |

WebSocket (étape 4) : les événements de direction `out` arrivent en temps réel.

### Nettoyage

Session déjà fermée à l'étape 9. Supprimer les tokens si nécessaire :

```bash
# Rien à faire — session fermée proprement
```

---

## S2 — Scoping : un étranger ne peut pas voir ma session

**Description** : TOKEN_B (propriétaire différent) tente toutes les opérations sur une
session appartenant à TOKEN_A. Toutes doivent retourner 404.

### Préconditions

- `TOKEN_A` et `TOKEN_B` exportés (deux clés API distinctes avec des `owner_id` différents)

### Étapes

```bash
# 1. TOKEN_A crée une session
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s2-scoping","duration_seconds":600}' | jq -r '.id')
echo "Session créée: $SID"

# 2. TOKEN_B tente GET session
curl -s -H "Authorization: Bearer $TOKEN_B" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n" | tail -1

# 3. TOKEN_B tente PATCH /extend
curl -s -X PATCH $API/api/v1/sessions/$SID/extend \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds":600}' \
  -w "\nHTTP %{http_code}\n" | tail -1

# 4. TOKEN_B tente DELETE
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_B" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n" | tail -1

# 5. TOKEN_B tente POST /agents
curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"agent-helper","count":1}' \
  -w "\nHTTP %{http_code}\n" | tail -1
```

### Résultats attendus

Toutes les étapes 2 à 5 : **HTTP 404** — la session n'est pas visible par TOKEN_B.

### Nettoyage

```bash
# TOKEN_A ferme sa propre session
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"
```

---

## S3 — Admin bypass : l'admin voit et agit sur toute session

**Description** : TOKEN_ADMIN peut lire, lister les agents, lire les messages et fermer
une session créée par TOKEN_A, sans en être propriétaire.

### Préconditions

- `TOKEN_A` et `TOKEN_ADMIN` exportés
- `AGENT_SLUG` défini (cf. S1)

### Étapes

```bash
# 1. TOKEN_A crée une session et spawn un agent
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s3-admin-bypass","duration_seconds":3600}' | jq -r '.id')

IID=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1}" | jq -r '.instance_ids[0]')

echo "SID=$SID  IID=$IID"

# 2. ADMIN lit la session (devrait voir même si pas propriétaire)
curl -s -H "Authorization: Bearer $TOKEN_ADMIN" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"

# 3. ADMIN liste les agents
curl -s -H "Authorization: Bearer $TOKEN_ADMIN" $API/api/v1/sessions/$SID/agents \
  -w "\nHTTP %{http_code}\n" | jq '.[].id'

# 4. ADMIN lit les messages de session
curl -s -H "Authorization: Bearer $TOKEN_ADMIN" \
  "$API/api/v1/sessions/$SID/messages" \
  -w "\nHTTP %{http_code}\n"

# 5. ADMIN ferme la session
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_ADMIN" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"

# 6. Vérifier que la session est bien closed
curl -s -H "Authorization: Bearer $TOKEN_ADMIN" $API/api/v1/sessions/$SID | jq '.status'
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 2 — GET session | 200 | Objet session complet |
| 3 — GET agents | 200 | Tableau avec 1 élément |
| 4 — GET messages | 200 | Tableau (peut être vide) |
| 5 — DELETE | 204 | Corps vide |
| 6 — GET après close | 200 | `status=closed` |

### Nettoyage

Session déjà fermée à l'étape 5.

---

## S4 — Expiration automatique

**Description** : Une session créée avec `duration_seconds=60` doit passer au statut
`expired` après que le worker d'expiration s'est exécuté (~30s de fréquence).

### Préconditions

- `TOKEN_A` exporté
- Worker d'expiration sessions en cours d'exécution sur LXC 201

### Étapes

```bash
# 1. Créer une session avec TTL de 60s
SESSION=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s4-expiration","duration_seconds":60}')
SID=$(echo $SESSION | jq -r '.id')
echo "Session: $SID — expires_at: $(echo $SESSION | jq -r '.expires_at')"

# 2. Vérifier immédiatement : status = active
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID | jq '.status'

# 3. Attendre 90s (TTL + latence worker)
echo "Attente 90s..."
sleep 90

# 4. GET session → doit être expired
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID | jq '{status,closed_at}'

# 5. Tenter de spawner un agent sur session expirée → doit échouer
curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"agent-helper","count":1}' \
  -w "\nHTTP %{http_code}\n"
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 2 — GET immédiat | 200 | `status=active` |
| 4 — GET après 90s | 200 | `status=expired`, `closed_at` non nul |
| 5 — POST agents sur session expirée | 404 | `session not found or not active` |

### Nettoyage

Session expirée automatiquement — aucun nettoyage requis.

---

## S5 — Extension avant expiration

**Description** : Une session à TTL court est étendue avant expiration ;
après le délai initial, elle reste active.

### Préconditions

- `TOKEN_A` exporté

### Étapes

```bash
# 1. Créer une session avec TTL de 60s
SESSION=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s5-extend","duration_seconds":60}')
SID=$(echo $SESSION | jq -r '.id')
echo "Session: $SID — expires_at initial: $(echo $SESSION | jq -r '.expires_at')"

# 2. Étendre de 1800s supplémentaires
EXTENDED=$(curl -s -X PATCH $API/api/v1/sessions/$SID/extend \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"duration_seconds":1800}')
echo "expires_at après extension: $(echo $EXTENDED | jq -r '.expires_at')"

# 3. Attendre 90s (dépassement du TTL original)
echo "Attente 90s..."
sleep 90

# 4. GET session → doit être toujours active
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID | jq '{status,expires_at}'
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 2 — PATCH extend | 200 | `expires_at` repoussé de ~1800s par rapport à l'original |
| 4 — GET après 90s | 200 | `status=active` (session non expirée) |

### Nettoyage

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"
```

---

## S6 — Destroy + rebuild d'un agent en cours de session

**Description** : Supprimer une instance d'agent (soft-delete), vérifier que la liste
ne l'inclut plus, puis spawner un nouvel agent avec un ID différent.

### Préconditions

- `TOKEN_A` exporté
- `AGENT_SLUG` défini

### Étapes

```bash
# 1. Créer session avec 2 instances du même agent
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s6-rebuild","duration_seconds":3600}' | jq -r '.id')

SPAWN=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":2}")
IID1=$(echo $SPAWN | jq -r '.instance_ids[0]')
IID2=$(echo $SPAWN | jq -r '.instance_ids[1]')
echo "Instance 1: $IID1"
echo "Instance 2: $IID2"

# 2. Vérifier : 2 agents actifs
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID/agents \
  | jq 'length'

# 3. Détruire l'instance 1
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" \
  $API/api/v1/sessions/$SID/agents/$IID1 \
  -w "\nHTTP %{http_code}\n"

# 4. Lister les agents → doit en rester 1 (IID2 uniquement)
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID/agents \
  | jq '[.[] | {id, status}]'

# 5. Spawner un nouvel agent
NEW=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1,\"mission\":\"Rebuilt agent\"}")
IID3=$(echo $NEW | jq -r '.instance_ids[0]')
echo "Nouvel agent: $IID3"

# 6. Lister les agents → doit en avoir 2 actifs, avec IID3 != IID1
curl -s -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID/agents \
  | jq '[.[] | {id, status}]'
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 2 — List agents initial | 200 | `length = 2` |
| 3 — DELETE instance 1 | 204 | Corps vide |
| 4 — List après destroy | 200 | `length = 1`, seul `IID2` présent |
| 5 — POST nouvel agent | 201 | `IID3` différent de `IID1` |
| 6 — List final | 200 | `length = 2`, `IID2` et `IID3` présents |

### Nettoyage

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"
```

---

## S7 — Contrainte FK catalogue : agent inexistant refusé

**Description** : Tenter de spawner un agent dont le slug n'existe pas dans le catalogue
doit retourner une erreur 400 avec un message explicite.

### Préconditions

- `TOKEN_A` exporté

### Étapes

```bash
# 1. Créer une session valide
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s7-fk-test","duration_seconds":600}' | jq -r '.id')

# 2. Tenter de spawner un agent avec un slug invalide
RESP=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"does-not-exist-bogus","count":1}' \
  -w "\n%{http_code}")
echo "$RESP"

# Extraire le body et le code séparément
BODY=$(echo "$RESP" | head -1)
CODE=$(echo "$RESP" | tail -1)
echo "HTTP $CODE"
echo $BODY | jq '.detail'
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 2 — POST avec slug invalide | 400 | `detail` contient `not found in catalog` |

Le message doit mentionner le slug `does-not-exist-bogus`.

### Nettoyage

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"
```

---

## S8 — Routage inter-agents (MOM Router)

**Description** : Un message posté sur l'agent A avec `route_to: "agent:{IID_B}"` doit
être reçu par l'agent B sous forme d'un message IN, avec `parent_msg_id` chaîné au
message OUT original de A.

### Préconditions

- `TOKEN_A` exporté
- `AGENT_SLUG` défini
- Worker MOM Router en cours d'exécution sur LXC 201

### Étapes

```bash
# 1. Créer session
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s8-routing","duration_seconds":3600}' | jq -r '.id')

# 2. Spawner agents A et B
SPAWN=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":2}")
IID_A=$(echo $SPAWN | jq -r '.instance_ids[0]')
IID_B=$(echo $SPAWN | jq -r '.instance_ids[1]')
echo "Agent A: $IID_A"
echo "Agent B: $IID_B"

# 3. Ouvrir WS sur agent B pour observer l'arrivée du message routé
wscat -c "ws://192.168.10.158/api/v1/sessions/$SID/agents/$IID_B/stream" &
WS_PID=$!

# 4. Poster un message sur agent A avec route_to → agent B
MSG=$(curl -s -X POST $API/api/v1/sessions/$SID/agents/$IID_A/message \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"kind\":\"instruction\",\"payload\":{\"text\":\"Redirige vers B\"},\"route_to\":\"agent:$IID_B\"}")
MID_A=$(echo $MSG | jq -r '.msg_id')
echo "msg_id posté sur A: $MID_A"

# 5. Attendre traitement Router (~2s)
sleep 3

# 6. Lire les messages IN de l'agent B
curl -s -H "Authorization: Bearer $TOKEN_A" \
  "$API/api/v1/sessions/$SID/agents/$IID_B/messages?direction=in" \
  | jq '.[] | {msg_id, parent_msg_id, direction, kind, payload}'

# 7. Vérifier que parent_msg_id = msg_id d'un message OUT de A
curl -s -H "Authorization: Bearer $TOKEN_A" \
  "$API/api/v1/sessions/$SID/agents/$IID_A/messages?direction=out" \
  | jq '.[0] | {msg_id, route}'

kill $WS_PID 2>/dev/null
```

### Résultats attendus

| Étape | Code HTTP | Contenu attendu |
|-------|-----------|-----------------|
| 4 — POST message sur A | 201 | `msg_id` UUID |
| 6 — GET messages IN de B | 200 | Tableau contenant au moins 1 message avec `direction=in`, `parent_msg_id` non nul |
| 7 — GET messages OUT de A | 200 | Message avec `route.target = "agent:{IID_B}"` |

Le `parent_msg_id` du message IN de B doit correspondre au `msg_id` du message OUT produit
par le Router, lui-même chaîné au message original via la table `agent_messages`.

### Nettoyage

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"
```

---

## S9 — WebSocket reconnect : l'historique est préservé

**Description** : Fermer le WebSocket pendant qu'un événement est produit, puis
vérifier que l'événement est bien en base (GET /messages), et que la reconnexion
permet de recevoir les futurs événements.

### Préconditions

- `TOKEN_A` exporté
- `AGENT_SLUG` défini
- `wscat` installé

### Étapes

```bash
# 1. Créer session et spawner un agent
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name":"s9-ws-reconnect","duration_seconds":3600}' | jq -r '.id')

IID=$(curl -s -X POST $API/api/v1/sessions/$SID/agents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1}" | jq -r '.instance_ids[0]')

echo "SID=$SID  IID=$IID"

# 2. Ouvrir WS et enregistrer l'événement 1
wscat -c "ws://192.168.10.158/api/v1/sessions/$SID/agents/$IID/stream" &
WS_PID=$!

# 3. Poster message 1 (WS ouvert)
MID1=$(curl -s -X POST $API/api/v1/sessions/$SID/agents/$IID/message \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"kind":"instruction","payload":{"text":"Message 1 - WS ouvert"}}' | jq -r '.msg_id')
echo "Message 1: $MID1"
sleep 1

# 4. Fermer le WebSocket
kill $WS_PID 2>/dev/null
echo "WS fermé"

# 5. Poster message 2 (WS fermé)
MID2=$(curl -s -X POST $API/api/v1/sessions/$SID/agents/$IID/message \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"kind":"instruction","payload":{"text":"Message 2 - WS fermé"}}' | jq -r '.msg_id')
echo "Message 2: $MID2"

# 6. Vérifier que les 2 messages sont en base
curl -s -H "Authorization: Bearer $TOKEN_A" \
  "$API/api/v1/sessions/$SID/agents/$IID/messages?limit=10" \
  | jq '[.[] | {msg_id, direction, kind}]'

# 7. Vérifier que message 2 est présent (direction=in)
curl -s -H "Authorization: Bearer $TOKEN_A" \
  "$API/api/v1/sessions/$SID/agents/$IID/messages?direction=in" \
  | jq '[.[] | .msg_id]'

# 8. Rouvrir le WS et poster un 3ème message
wscat -c "ws://192.168.10.158/api/v1/sessions/$SID/agents/$IID/stream" &
WS_PID2=$!
sleep 1

curl -s -X POST $API/api/v1/sessions/$SID/agents/$IID/message \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"kind":"instruction","payload":{"text":"Message 3 - WS rouvert"}}' | jq .

sleep 1
kill $WS_PID2 2>/dev/null
```

### Résultats attendus

| Étape | Attendu |
|-------|---------|
| 6 — GET messages | Au moins 2 messages en base (MID1 et MID2) |
| 7 — direction=in | MID1 et MID2 présents (persistés indépendamment du WS) |
| 8 — WS reconnecté | Message 3 reçu sur le stream en temps réel |

L'état du WebSocket n'affecte pas la persistance en base.

### Nettoyage

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n"
```

---

## S10 — Rate limit

**Description** : Un token configuré à 5 req/min doit retourner 429 avec un header
`Retry-After` à la 6ème requête dans la même fenêtre.

### Préconditions

- `TOKEN_RL` exporté (créé avec `rate_limit=5` lors de l'initialisation)

### Étapes

```bash
# 1. Créer une session avec TOKEN_RL
SID=$(curl -s -X POST $API/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN_RL" \
  -H "Content-Type: application/json" \
  -d '{"name":"s10-ratelimit","duration_seconds":300}' | jq -r '.id')
echo "Session: $SID"

# 2. Envoyer 6 requêtes rapides — la 6ème doit retourner 429
for i in 1 2 3 4 5 6; do
  RESP=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN_RL" $API/api/v1/sessions/$SID)
  echo "Requête $i : HTTP $RESP"
done

# 3. Vérifier la présence du header Retry-After sur le 429
curl -sv -H "Authorization: Bearer $TOKEN_RL" $API/api/v1/sessions/$SID 2>&1 \
  | grep -i "retry-after\|HTTP/"

# 4. Inspecter le body de la réponse 429
curl -s -H "Authorization: Bearer $TOKEN_RL" $API/api/v1/sessions/$SID | jq .
```

### Résultats attendus

| Requête | Code HTTP | Contenu attendu |
|---------|-----------|-----------------|
| 1–5 | 200 | Objet session valide |
| 6 | 429 | Body avec message `rate limit exceeded`, header `Retry-After` présent |

### Nettoyage

```bash
# Attendre expiry naturelle du token ou supprimer via admin
curl -s -X DELETE -H "Authorization: Bearer $TOKEN_A" $API/api/v1/sessions/$SID \
  -w "\nHTTP %{http_code}\n" 2>/dev/null || true
```

---

## Tableau de couverture

| Exigence | Scénario(s) |
|---|---|
| Chemin nominal complet | S1 |
| Scoping propriétaire (isolation) | S2 |
| Bypass admin | S3 |
| Expiration TTL automatique | S4 |
| Extension avant expiration | S5 |
| Soft-delete et rebuild d'instance | S6 |
| Contrainte FK catalogue | S7 |
| Routage inter-agents via MOM Router | S8 |
| Durabilité messages hors WebSocket | S9 |
| Rate limit (429 + Retry-After) | S10 |
