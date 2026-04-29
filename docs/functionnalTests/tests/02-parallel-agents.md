# Test 02 — Deux agents en parallèle

> **📋 Cartouche — Cas applicatif 02**
>
> **Scénario fonctionnel** : `../02-parallel-agents.md`
> **Objectif** : 2 agents dans une même session, demandes parallèles, isolation par `instance_id`
> **Durée** : 30-120s
> **Dépendances** : A01
>
> **Étapes vérifiées (8)** :
> 1. `POST /sessions`
> 2. `POST /agents count=2` → 2 `instance_ids` distincts
> 3. `GET /agents` → `length == 2`
> 4. POST messages A et B en parallèle (curl en background)
> 5. Polling session → ≥1 message OUT par instance (max 90s)
> 6. Isolation : `GET` par instance ne renvoie que ses propres messages
> 7. `DELETE /sessions/{id}` → 204 (détruit les 2 agents)
> 8. `GET` après close → `status=closed`

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/02-parallel-agents.md`.

## Préconditions

- `BASE_URL`, `API_KEY` exportées
- Catalogue contient `claude-code` (override `AGENT_SLUG`)

## Données utilisées

Voir `00-test-data.md` §3.2.

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-02-parallel` |
| `agent.count` | `2` (un seul appel POST avec count=2) |
| `agent.mission` | `"Tu es un agent de test parallèle."` |
| Message A | `{"text": "Liste 3 villes françaises."}` |
| Message B | `{"text": "Liste 3 villes japonaises."}` |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
AGENT_SLUG="${AGENT_SLUG:-claude-code}"

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Créer session
echo "==> 1. Création session"
SID=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"name":"test-02-parallel","duration_seconds":600}' | jq -r '.id')
[[ -n "$SID" && "$SID" != "null" ]] || { echo "FAIL: session non créée"; exit 1; }
echo "    SID=$SID"

# 2. Spawn 2 instances en un appel
echo "==> 2. Spawn 2 agents (count=2)"
SPAWN=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":2,\"mission\":\"Tu es un agent de test parallèle.\"}")
echo "$SPAWN" | jq -e '.instance_ids | length == 2' >/dev/null \
  || { echo "FAIL: count=2 attendu"; exit 1; }
IID_A=$(echo "$SPAWN" | jq -r '.instance_ids[0]')
IID_B=$(echo "$SPAWN" | jq -r '.instance_ids[1]')
echo "    IID_A=$IID_A"
echo "    IID_B=$IID_B"

# 3. Lister : 2 agents actifs
echo "==> 3. Vérification list agents"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID/agents" \
  | jq -e 'length == 2' >/dev/null \
  || { echo "FAIL: 2 agents attendus dans la liste"; exit 1; }

# 4. Poster les 2 messages en parallèle (curl en background)
echo "==> 4. POST messages parallèles"
RESP_A=$(mktemp)
RESP_B=$(mktemp)
curl -fsS -o "$RESP_A" -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID_A/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"kind":"instruction","payload":{"text":"Liste 3 villes françaises."}}' &
PID_A=$!
curl -fsS -o "$RESP_B" -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID_B/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"kind":"instruction","payload":{"text":"Liste 3 villes japonaises."}}' &
PID_B=$!
wait $PID_A $PID_B
MID_A=$(jq -r '.msg_id' < "$RESP_A")
MID_B=$(jq -r '.msg_id' < "$RESP_B")
[[ "$MID_A" != "null" && "$MID_B" != "null" && "$MID_A" != "$MID_B" ]] \
  || { echo "FAIL: msg_ids invalides ou identiques"; exit 1; }
echo "    MID_A=$MID_A"
echo "    MID_B=$MID_B"
rm -f "$RESP_A" "$RESP_B"

# 5. Polling au niveau session — récupérer 2 résultats OUT (un par instance) en max 90s
echo "==> 5. Polling pour collecter les 2 résultats (max 90s)"
COUNT_A=0
COUNT_B=0
for i in $(seq 1 45); do
  MSGS=$(curl -fsS "${H_AUTH[@]}" \
    "$BASE_URL/api/v1/sessions/$SID/messages?direction=out&limit=50")
  COUNT_A=$(echo "$MSGS" | jq --arg iid "$IID_A" '[.[] | select(.instance_id == $iid)] | length')
  COUNT_B=$(echo "$MSGS" | jq --arg iid "$IID_B" '[.[] | select(.instance_id == $iid)] | length')
  if [[ "$COUNT_A" -ge 1 && "$COUNT_B" -ge 1 ]]; then
    echo "    A=$COUNT_A messages, B=$COUNT_B messages après ${i}*2s"
    break
  fi
  sleep 2
done
[[ "$COUNT_A" -ge 1 ]] || { echo "FAIL: aucun message reçu pour IID_A"; exit 1; }
[[ "$COUNT_B" -ge 1 ]] || { echo "FAIL: aucun message reçu pour IID_B"; exit 1; }

# 6. Vérifier l'isolation : un GET par instance ne renvoie que ses propres messages
echo "==> 6. Vérification isolation par instance"
curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID_A/messages?direction=out&limit=10" \
  | jq -e --arg iid "$IID_A" 'all(.[]; .instance_id == $iid)' >/dev/null \
  || { echo "FAIL: isolation A violée"; exit 1; }
curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID_B/messages?direction=out&limit=10" \
  | jq -e --arg iid "$IID_B" 'all(.[]; .instance_id == $iid)' >/dev/null \
  || { echo "FAIL: isolation B violée"; exit 1; }

# 7. Fermer la session — détruit les 2 agents en une fois
echo "==> 7. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

# 8. Vérifier closed
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID" \
  | jq -e '.status == "closed"' >/dev/null \
  || { echo "FAIL: session pas closed"; exit 1; }

echo "PASS — Test 02 parallel-agents"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 2 — POST agents count=2 | 201 | `.instance_ids \| length == 2` |
| 4 — POST messages A et B | 201 chacun | `msg_id` distinct |
| 5 — Polling session | 200 | au moins 1 message OUT par `instance_id` en ≤ 90s |
| 6 — Isolation par instance | 200 | tous les messages renvoyés portent l'`instance_id` filtré |
| 7 — DELETE session | 204 | corps vide |

## Nettoyage

Session fermée à l'étape 7.
