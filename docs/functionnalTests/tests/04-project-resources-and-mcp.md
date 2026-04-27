# Test 04 — Projet, ressources partagées et MCP externe

> **📋 Cartouche — Cas applicatif 04**
>
> **Scénario fonctionnel** : `../04-project-resources-and-mcp.md`
> **Objectif** : héritage du scope projet sur la session + accessibilité workspace + binding MCP
> **Durée** : 1-3 min (LLM + MCP)
> **Dépendances** : A01 + A02 (MCP filesystem) + A03 (`PROJECT_UUID`)
>
> **Étapes vérifiées (8)** :
> 1. `POST /sessions` avec `project_id` → projet hérité côté response
> 2. `GET /sessions` → `project_id` persisté + active
> 3. `POST /agents` avec mission projet
> 4. `GET /agents/{uuid}` → `mcp_bindings` (warn-only si vide)
> 5. POST message demande de doc
> 6. Polling OUT (max 120s)
> 7. `GET /files?path=` → `type ∈ {dir, missing}`
> 8. `DELETE` session → 204
>
> **Limitation V1** : pas d'API publique `/projects/*` — la lecture/écriture
> effective des ressources passe par le workspace ou le MCP, pas par HTTP direct.

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/04-project-resources-and-mcp.md`.

## Préconditions

- `BASE_URL`, `API_KEY`, `PROJECT_UUID` exportées
  (`PROJECT_UUID` est émis par A03)
- A02 exécuté → MCP `filesystem` (recipe `stdio`) installé et bindé à `claude-code`
- A03 exécuté → projet `Tests fonctionnels` existe (UUID dans `PROJECT_UUID`)

## Données utilisées

Voir `00-test-data.md` §3.4.

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-04-project` |
| `session.project_id` | `$PROJECT_UUID` (UUID émis par A03) |
| `session.duration_seconds` | `1200` |
| `agent.mission` | `"Lis specs/feature-x.md et propose un résumé."` |
| Message | `{"text": "Documente la fonctionnalité X en lisant les specs"}` |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
: "${PROJECT_UUID:?PROJECT_UUID must be set (cf. A03)}"
AGENT_SLUG="${AGENT_SLUG:-claude-code}"

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Créer une session liée au projet
echo "==> 1. Création session avec project_id"
SESSION=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"name\":\"test-04-project\",\"duration_seconds\":1200,\"project_id\":\"$PROJECT_UUID\"}")
SID=$(echo "$SESSION" | jq -r '.id')
echo "$SESSION" | jq -e --arg pid "$PROJECT_UUID" '.project_id == $pid' >/dev/null \
  || { echo "FAIL: project_id non persisté côté response (réponse: $(echo "$SESSION" | jq -c .))"; exit 1; }
echo "    SID=$SID"

# 2. GET session — vérifier l'héritage du project_id
echo "==> 2. GET session (vérif héritage)"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID" \
  | jq -e --arg pid "$PROJECT_UUID" '.project_id == $pid and .status == "active"' >/dev/null \
  || { echo "FAIL: project_id absent du GET session"; exit 1; }

# 3. Instancier l'agent (devrait avoir les bindings MCP via A02)
echo "==> 3. Création agent avec mission projet"
SPAWN=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1,\"mission\":\"Lis specs/feature-x.md et propose un résumé.\"}")
IID=$(echo "$SPAWN" | jq -r '.instance_ids[0]')
[[ -n "$IID" && "$IID" != "null" ]] || { echo "FAIL: instance_id absent"; exit 1; }
echo "    IID=$IID"

# 4. Vérifier que l'agent a bien le MCP filesystem bindé (visible via discovery détail)
echo "==> 4. Vérification MCP binding sur l'agent (discovery)"
AGENT_UUID=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/agents" \
  | jq -r --arg slug "$AGENT_SLUG" '.[] | select(.slug == $slug) | .id')
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/agents/$AGENT_UUID" \
  | jq -e '.mcp_bindings | length >= 1' >/dev/null \
  || echo "WARN: aucun mcp_bindings exposé sur l'agent — MCP non bindé ou non remonté en discovery"

# 5. Poster une demande qui devrait déclencher lecture de fichier
echo "==> 5. POST message demande de doc"
MSG=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"kind":"instruction","payload":{"text":"Documente la fonctionnalité X en lisant les specs"}}')
MID=$(echo "$MSG" | jq -r '.msg_id')
echo "    MID=$MID"

# 6. Polling jusqu'à un message OUT — max 120s (LLM + MCP peut être lent)
echo "==> 6. Polling résultat agent (max 120s)"
RESULT=0
for i in $(seq 1 60); do
  COUNT=$(curl -fsS "${H_AUTH[@]}" \
    "$BASE_URL/api/v1/sessions/$SID/agents/$IID/messages?direction=out&limit=20" \
    | jq 'length')
  if [[ "$COUNT" -ge 1 ]]; then
    RESULT=1
    echo "    réponse reçue après ${i}*2s"
    break
  fi
  sleep 2
done
[[ "$RESULT" -eq 1 ]] || { echo "FAIL: aucune réponse en 120s"; exit 1; }

# 7. Inspecter le workspace de l'instance — au minimum la racine est listable
echo "==> 7. Vérification workspace accessible"
WS_RESP=$(curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID/files?path=")
echo "$WS_RESP" | jq -e '.type | IN("dir","missing")' >/dev/null \
  || { echo "FAIL: workspace inattendu"; exit 1; }

# 8. Fermer la session — les ressources projet survivent (vérifié hors test ici)
echo "==> 8. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

echo "PASS — Test 04 project-resources-and-mcp"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 — POST session avec project_id | 201 | `.project_id` retourné |
| 2 — GET session | 200 | `.project_id` persisté + `status="active"` |
| 3 — POST agents | 201 | `.instance_ids[0]` UUID |
| 4 — GET `/agents/{id}` | 200 | `.mcp_bindings` exposé (warning seulement, pas de fail) |
| 5 — POST message | 201 | `msg_id` UUID |
| 6 — Polling messages | 200 | au moins 1 OUT en ≤ 120s |
| 7 — GET `/files?path=` | 200 | `.type` ∈ `{dir, missing}` |
| 8 — DELETE session | 204 | — |

## Nettoyage

- Session fermée à l'étape 8.
- Le projet et ses ressources **persistent** (c'est le but du scénario). Pour
  réinitialiser un environnement de test, supprimer manuellement via admin :
  `DELETE /api/admin/projects/tests-fixture-project`.

## Notes / limitations

- **Limitation V1 (cf. COVERAGE.md écart 1)** : il n'existe pas d'API publique
  `/api/v1/projects/*`. Le test ne peut donc pas valider la lecture/écriture
  effective des ressources via HTTP. Il vérifie l'**héritage du scope projet**
  (project_id sur la session) et la disponibilité du workspace. La lecture
  effective transite par le montage volume Docker et les outils MCP.
- Si `mcp_bindings` est vide à l'étape 4, le test affiche un WARN mais continue —
  le binding MCP n'est pas (encore) exposé dans le DTO public `AgentDetail`.
