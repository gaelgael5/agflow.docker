# Test 01 — Demande minimale à un agent

> **📋 Cartouche — Cas applicatif 01**
>
> **Scénario fonctionnel** : `../01-single-agent-request.md`
> **Objectif** : valider le flux minimal session → agent → message → résultat (polling)
> **Durée** : 30-90s (selon latence LLM)
> **Dépendances** : A01 (clé API + agent `claude-code` disponible)
>
> **Étapes vérifiées (10)** :
> 1. Agent présent au catalogue
> 2. `POST /sessions` → `status=active`
> 3. `GET /sessions/{id}` → active
> 4. `POST /sessions/{id}/agents count=1` → `instance_ids[0]`
> 5. `GET /sessions/{id}/agents` → instance listée
> 6. `POST /agents/{iid}/message` kind=instruction
> 7. Polling `/messages?direction=out` (max 60s)
> 8. `GET /sessions/{id}/messages` → non vide
> 9. `DELETE /sessions/{id}` → 204
> 10. `GET /sessions/{id}` après close → `status=closed`

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/01-single-agent-request.md`.

## Préconditions

- Variables `BASE_URL`, `API_KEY` exportées (cf. `00-test-data.md` §1)
- Catalogue contient un agent `claude-code` (cf. §2.2) — override via `AGENT_SLUG`
- Secret `ANTHROPIC_API_KEY` plateforme valide (cf. §2.1)

## Données utilisées

Voir `00-test-data.md` §3.1.

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-01-single` |
| `session.duration_seconds` | `600` |
| `agent.mission` | `"Réponds en une phrase à la question de l'utilisateur."` |
| `message.payload` | `{"text": "Quel est le code ISO du Japon ?"}` |
| Polling result | 30 itérations max × 2s |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
AGENT_SLUG="${AGENT_SLUG:-claude-code}"

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Vérifier que l'agent existe au catalogue
echo "==> 1. Vérification catalogue"
AGENT_PRESENT=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/agents" \
  | jq -r --arg slug "$AGENT_SLUG" 'map(select(.slug == $slug)) | length')
[[ "$AGENT_PRESENT" -ge 1 ]] || { echo "FAIL: agent '$AGENT_SLUG' absent du catalogue"; exit 1; }

# 2. Créer la session
echo "==> 2. Création session"
SESSION=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"name":"test-01-single","duration_seconds":600}')
SID=$(echo "$SESSION" | jq -r '.id')
echo "$SESSION" | jq -e '.id and .status == "active"' >/dev/null \
  || { echo "FAIL: session non créée ou inactive"; exit 1; }
echo "    SID=$SID"

# 3. GET session — vérifier statut active
echo "==> 3. GET session"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID" \
  | jq -e '.status == "active"' >/dev/null \
  || { echo "FAIL: session pas active après création"; exit 1; }

# 4. Instancier l'agent
echo "==> 4. Création agent"
SPAWN=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1,\"mission\":\"Réponds en une phrase à la question de l'utilisateur.\"}")
IID=$(echo "$SPAWN" | jq -r '.instance_ids[0]')
[[ -n "$IID" && "$IID" != "null" ]] || { echo "FAIL: instance_id absent"; exit 1; }
echo "    IID=$IID"

# 5. Lister les agents — au moins 1 actif
echo "==> 5. List agents"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID/agents" \
  | jq -e --arg iid "$IID" '[.[] | select(.id == $iid)] | length == 1' >/dev/null \
  || { echo "FAIL: instance non listée"; exit 1; }

# 6. Poster une demande
echo "==> 6. POST message"
MSG=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"kind":"instruction","payload":{"text":"Quel est le code ISO du Japon ?"}}')
MID=$(echo "$MSG" | jq -r '.msg_id')
[[ -n "$MID" && "$MID" != "null" ]] || { echo "FAIL: msg_id absent"; exit 1; }
echo "    MID=$MID"

# 7. Polling : attendre une réponse (direction=out) jusqu'à 60s
echo "==> 7. Polling pour récupérer la réponse de l'agent (max 60s)"
RESULT_FOUND=0
for i in $(seq 1 30); do
  COUNT=$(curl -fsS "${H_AUTH[@]}" \
    "$BASE_URL/api/v1/sessions/$SID/agents/$IID/messages?direction=out&limit=20" \
    | jq 'length')
  if [[ "$COUNT" -ge 1 ]]; then
    RESULT_FOUND=1
    echo "    réponse reçue après ${i}*2s"
    break
  fi
  sleep 2
done
[[ "$RESULT_FOUND" -eq 1 ]] || { echo "FAIL: aucune réponse reçue en 60s"; exit 1; }

# 8. Vérifier que la session liste bien le message dans son flux
echo "==> 8. GET messages session"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID/messages?limit=10" \
  | jq -e 'length >= 1' >/dev/null \
  || { echo "FAIL: messages session vides"; exit 1; }

# 9. Fermer la session
echo "==> 9. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

# 10. GET après fermeture — status=closed
echo "==> 10. GET session après close"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID" \
  | jq -e '.status == "closed"' >/dev/null \
  || { echo "FAIL: session pas closed après DELETE"; exit 1; }

echo "PASS — Test 01 single-agent-request"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 2 — POST session | 201 | `.id` UUID, `.status="active"` |
| 4 — POST agents | 201 | `.instance_ids[0]` UUID |
| 6 — POST message | 201 | `.msg_id` UUID |
| 7 — GET messages (polling) | 200 | au moins 1 message `direction=out` apparaît avant 60s |
| 9 — DELETE session | 204 | corps vide |
| 10 — GET après close | 200 | `.status="closed"` |

## Nettoyage

Session déjà fermée à l'étape 9. Aucune ressource à nettoyer.

## Notes

- Le test n'inspecte pas le **contenu** de la réponse de l'agent (dépend du LLM).
  Il vérifie uniquement la propagation de bout en bout : la demande passe par le
  bus, l'agent répond, le résultat est lisible côté client.
- Si le timeout LLM dépasse 60s, augmenter le polling (`for i in $(seq 1 60)` =
  120s).
