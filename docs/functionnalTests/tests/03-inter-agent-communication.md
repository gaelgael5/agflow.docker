# Test 03 — Communication inter-agents (MOM Router)

> **📋 Cartouche — Cas applicatif 03**
>
> **Scénario fonctionnel** : `../03-inter-agent-communication.md`
> **Objectif** : routage MOM Router entre 2 agents via `route_to` + chaînage `parent_msg_id`
> **Durée** : 15-30s
> **Dépendances** : A01 + worker MOM Router actif sur l'env
>
> **Étapes vérifiées (7)** :
> 1. `POST /sessions`
> 2. `POST /agents count=2` → `IID_A` et `IID_B`
> 3. POST message sur A avec `route_to="agent:$IID_B"`
> 4. Attente Router (max 10s) → message IN apparaît sur B
> 5. `parent_msg_id` non nul sur le message IN de B
> 6. Côté A : message OUT avec `route.target == "agent:$IID_B"`
> 7. `DELETE` session → 204

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/03-inter-agent-communication.md`.

## Préconditions

- `BASE_URL`, `API_KEY` exportées
- Catalogue contient `claude-code` (override `AGENT_SLUG`)
- Worker MOM Router en cours d'exécution sur l'env (cf. supervision Phase 1)

## Données utilisées

Voir `00-test-data.md` §3.3.

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-03-router` |
| `agent.count` | `2` |
| Message routé | `{"kind":"instruction","payload":{"text":"Demande à B"},"route_to":"agent:$IID_B"}` |
| Délai de routage | 5s avant assertion |

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
  -d '{"name":"test-03-router","duration_seconds":600}' | jq -r '.id')
echo "    SID=$SID"

# 2. Spawn 2 agents : A (orchestrateur) et B (spécialiste)
echo "==> 2. Spawn 2 agents"
SPAWN=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":2,\"mission\":\"Coopération test 03.\"}")
IID_A=$(echo "$SPAWN" | jq -r '.instance_ids[0]')
IID_B=$(echo "$SPAWN" | jq -r '.instance_ids[1]')
echo "    IID_A=$IID_A"
echo "    IID_B=$IID_B"

# 3. Poster un message sur A avec route_to → agent:IID_B
echo "==> 3. POST message routé vers B"
MSG=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID_A/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"kind\":\"instruction\",\"payload\":{\"text\":\"Demande à B\"},\"route_to\":\"agent:$IID_B\"}")
MID=$(echo "$MSG" | jq -r '.msg_id')
[[ -n "$MID" && "$MID" != "null" ]] || { echo "FAIL: msg_id absent"; exit 1; }
echo "    MID=$MID"

# 4. Attendre que le Router traite et redélivre vers B (max 10s)
echo "==> 4. Attente Router (max 10s)"
B_IN_FOUND=0
for i in $(seq 1 5); do
  sleep 2
  COUNT=$(curl -fsS "${H_AUTH[@]}" \
    "$BASE_URL/api/v1/sessions/$SID/agents/$IID_B/messages?direction=in&limit=20" \
    | jq 'length')
  if [[ "$COUNT" -ge 1 ]]; then
    B_IN_FOUND=1
    echo "    B a reçu $COUNT message(s) IN après ${i}*2s"
    break
  fi
done
[[ "$B_IN_FOUND" -eq 1 ]] || { echo "FAIL: B n'a reçu aucun message routé"; exit 1; }

# 5. Vérifier que parent_msg_id est non nul sur le message IN de B
echo "==> 5. Vérification chaînage parent_msg_id"
curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID_B/messages?direction=in&limit=5" \
  | jq -e 'any(.[]; .parent_msg_id != null)' >/dev/null \
  || { echo "FAIL: parent_msg_id absent sur les messages IN de B"; exit 1; }

# 6. Vérifier que le message OUT du Router (côté A) porte route.target = agent:IID_B
echo "==> 6. Vérification route.target côté A"
curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID_A/messages?direction=out&limit=10" \
  | jq -e --arg target "agent:$IID_B" \
      'any(.[]; .route.target == $target)' >/dev/null \
  || { echo "FAIL: aucun message OUT de A avec route.target=$IID_B"; exit 1; }

# 7. Fermer la session
echo "==> 7. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

echo "PASS — Test 03 inter-agent-communication"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 3 — POST message routé | 201 | `msg_id` UUID |
| 4 — GET messages IN de B | 200 | au moins 1 message en ≤ 10s |
| 5 — parent_msg_id sur B | 200 | au moins 1 message avec `parent_msg_id` non nul |
| 6 — route.target côté A | 200 | message OUT avec `route.target == "agent:$IID_B"` |
| 7 — DELETE session | 204 | — |

## Nettoyage

Session fermée à l'étape 7.

## Notes

- Le test ne valide pas le **contenu** sémantique de la coopération (l'agent B
  pourrait répondre n'importe quoi). Il vérifie uniquement la mécanique de routage
  du bus.
- Si le Router est down, l'étape 4 timeout après 10s. Vérifier
  `GET /api/admin/supervision/overview` côté admin.
