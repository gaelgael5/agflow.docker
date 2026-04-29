# Test 07 — Découverte du catalogue avant instanciation

> **📋 Cartouche — Cas applicatif 07**
>
> **Scénario fonctionnel** : `../07-discovery-before-instantiation.md`
> **Objectif** : exploration du catalogue avant instanciation — purement en lecture
> **Durée** : <10s
> **Dépendances** : A01 (catalogue peuplé : ≥1 rôle + ≥1 agent)
>
> **Étapes vérifiées (7)** :
> 1. `GET /scopes` → contient `agents:read`, `agents:run`, `roles:read`
> 2. `GET /roles` → liste non vide, structure `{id, display_name}`
> 3. `GET /roles/{id}` → role + sections
> 4. `GET /agents` → agent attendu présent
> 5. `GET /agents/{uuid}` → `AgentDetail` riche (`mcp_bindings`, `skills`, `timeout`, `image_status`)
> 6. État opérationnel (warn-only) : `has_errors=false`, `image_status=up_to_date`
> 7. Récap des slugs disponibles (informatif)
>
> **Limitation V1** : `AgentDetail` n'expose pas `profiles[]` (pas de sélection de profil de mission)

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/07-discovery-before-instantiation.md`.

## Préconditions

- `BASE_URL`, `API_KEY` exportées (scopes `agents:read`, `roles:read` requis)
- Au moins 1 agent au catalogue (`claude-code` ou autre, override `AGENT_SLUG`)

## Données utilisées

Voir `00-test-data.md` §3.7. Aucun objet à créer côté plateforme — test purement
en lecture.

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
AGENT_SLUG="${AGENT_SLUG:-claude-code}"

H_AUTH=(-H "Authorization: Bearer $API_KEY")

# 1. Lister les scopes disponibles
echo "==> 1. GET /scopes"
SCOPES=$(curl -fsS "$BASE_URL/api/v1/scopes")
echo "$SCOPES" | jq -e 'length >= 1' >/dev/null \
  || { echo "FAIL: catalogue scopes vide"; exit 1; }
# Vérifier la présence des scopes minimum requis pour 01-09
for needed in "agents:read" "agents:run" "roles:read"; do
  echo "$SCOPES" | jq -e --arg s "$needed" \
      'any(.[]; .scopes | any(. == $s))' >/dev/null \
    || { echo "FAIL: scope '$needed' absent du catalogue"; exit 1; }
done
echo "    scopes OK"

# 2. Lister les rôles
echo "==> 2. GET /roles"
ROLES=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/roles")
echo "$ROLES" | jq -e 'length >= 1 and all(.[]; .id and .display_name)' >/dev/null \
  || { echo "FAIL: rôles invalides ou vide"; exit 1; }
ROLE_ID=$(echo "$ROLES" | jq -r '.[0].id')
echo "    premier rôle: $ROLE_ID"

# 3. Détail du premier rôle
echo "==> 3. GET /roles/{id}"
ROLE_DETAIL=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/roles/$ROLE_ID")
echo "$ROLE_DETAIL" | jq -e '.role.id and .sections' >/dev/null \
  || { echo "FAIL: detail rôle mal formé"; exit 1; }

# 4. Lister les agents
echo "==> 4. GET /agents"
AGENTS=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/agents")
echo "$AGENTS" | jq -e 'length >= 1' >/dev/null \
  || { echo "FAIL: catalogue agents vide"; exit 1; }

# Trouver l'agent attendu
AGENT_UUID=$(echo "$AGENTS" | jq -r --arg slug "$AGENT_SLUG" \
  '.[] | select(.slug == $slug) | .id' | head -1)
[[ -n "$AGENT_UUID" && "$AGENT_UUID" != "null" ]] \
  || { echo "FAIL: agent '$AGENT_SLUG' absent"; exit 1; }
echo "    AGENT_UUID=$AGENT_UUID"

# 5. Détail de l'agent : champs riches attendus
echo "==> 5. GET /agents/{id}"
DETAIL=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/agents/$AGENT_UUID")
echo "$DETAIL" | jq -e '
  .id and .slug and .role_id
  and (.mcp_bindings | type == "array")
  and (.skill_bindings | type == "array")
  and (.timeout_seconds | type == "number")
  and (.has_errors | type == "boolean")
  and .image_status
' >/dev/null \
  || { echo "FAIL: AgentDetail incomplet"; exit 1; }

# 6. Vérifier que l'agent est utilisable (image build OK + pas d'erreurs)
echo "==> 6. État de l'agent"
echo "$DETAIL" | jq -e '.has_errors == false' >/dev/null \
  || echo "WARN: agent.has_errors == true — test en aval échouera"
echo "$DETAIL" | jq -e '.image_status == "up_to_date"' >/dev/null \
  || echo "WARN: image_status != up_to_date (instanciation refusée par run-time)"

# 7. (informatif) Tableau des slugs disponibles
echo "==> 7. Récap : slugs disponibles"
echo "$AGENTS" | jq -r '.[] | "    - \(.slug) (\(.id)) image=\(.image_status // "?")"'

echo "PASS — Test 07 discovery-before-instantiation"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 — GET /scopes | 200 | tableau non vide, contient `agents:read`, `agents:run`, `roles:read` |
| 2 — GET /roles | 200 | tableau non vide, chaque entrée a `id`, `display_name` |
| 3 — GET /roles/{id} | 200 | `.role.id` et `.sections` présents |
| 4 — GET /agents | 200 | au moins 1 agent ; agent attendu trouvé |
| 5 — GET /agents/{id} | 200 | `AgentDetail` avec `role_id`, `mcp_bindings[]`, `skill_bindings[]`, `timeout_seconds`, `has_errors`, `image_status` |
| 6 — État opérationnel | warn-only | `has_errors=false`, `image_status="up_to_date"` |

## Nettoyage

Aucun — test purement en lecture.

## Notes

- **Limitation V1 (cf. COVERAGE.md écart 2)** : `AgentDetail` n'expose pas de
  tableau `profiles[]`. Le test ne couvre donc pas la sélection de profil de
  mission. La mission reste une string libre passée à `POST /agents`.
- Le test n'authentifie pas `GET /scopes` (endpoint public sans `require_api_key`
  dans le code actuel). Si l'auth est ajoutée, ajouter `H_AUTH` à l'étape 1.
