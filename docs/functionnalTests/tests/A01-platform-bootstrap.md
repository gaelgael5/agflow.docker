# Test A01 — Bootstrap de la plateforme (opérateur)

> **📋 Cartouche — Scénario opérateur A01**
>
> **Scénario fonctionnel** : `../A01-platform-bootstrap.md`
> **Objectif** : bootstrap minimal d'une plateforme vierge → produit `API_KEY` pour les tests 01-09
> **Durée** : 5-15 min (build Docker possible)
> **Dépendances** : `ADMIN_EMAIL`/`ADMIN_PASSWORD` + `ANTHROPIC_API_KEY_VALUE`
> **Idempotent** : oui (réutilise les ressources existantes si présentes)
>
> **Étapes vérifiées (9)** :
> 1. `POST /auth/login` → JWT admin
> 2. Création/vérif secret `ANTHROPIC_API_KEY`
> 3. `POST /secrets/{id}/test` → `ok=true`
> 4. Vérif/création dockerfile `claude-code`
> 5. `POST /build` (si pas `up_to_date`) → polling jusqu'à `succeeded` (max 10 min)
> 6. Création/vérif rôle `test-assistant`
> 7. Création/vérif agent `claude-code`
> 8. `POST /api-keys` → **`API_KEY` (affichée une seule fois)**
> 9. Smoke test : la clé permet `GET /api/v1/agents`

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/A01-platform-bootstrap.md`. Ce test produit la valeur de
`API_KEY` qui sera utilisée par les tests applicatifs 01-09.

## Préconditions

- `BASE_URL` exporté
- `ADMIN_EMAIL`, `ADMIN_PASSWORD` exportés (créés au déploiement initial)
- `ANTHROPIC_API_KEY_VALUE` exporté (clé valide `sk-ant-...` à pousser dans la
  plateforme — **jamais** committée dans le repo)
- Le repo agflow.docker est cloné localement (pour utiliser le dockerfile
  `claude-code` packagé)

## Données utilisées

Voir `00-test-data.md` §4.1.

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${ADMIN_EMAIL:?ADMIN_EMAIL must be set}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set}"
: "${ANTHROPIC_API_KEY_VALUE:?ANTHROPIC_API_KEY_VALUE must be set}"

H_JSON=(-H "Content-Type: application/json")

# 1. Login admin
echo "==> 1. POST /api/admin/auth/login"
ADMIN_JWT=$(curl -fsS -X POST "$BASE_URL/api/admin/auth/login" \
  "${H_JSON[@]}" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" \
  | jq -r '.access_token')
[[ -n "$ADMIN_JWT" && "$ADMIN_JWT" != "null" ]] \
  || { echo "FAIL: login admin (vérifier credentials)"; exit 1; }
echo "    JWT obtenu (${#ADMIN_JWT} chars)"
H_ADMIN=(-H "Authorization: Bearer $ADMIN_JWT")

# 2. Créer ou réutiliser le secret ANTHROPIC_API_KEY
echo "==> 2. Création/vérification secret ANTHROPIC_API_KEY"
EXISTING=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/secrets" \
  | jq -r '.[] | select(.var_name == "ANTHROPIC_API_KEY") | .id' | head -1)
if [[ -z "$EXISTING" ]]; then
  SECRET=$(curl -fsS -X POST "$BASE_URL/api/admin/secrets" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d "{\"var_name\":\"ANTHROPIC_API_KEY\",\"value\":\"$ANTHROPIC_API_KEY_VALUE\",\"scope\":\"global\"}")
  SECRET_ID=$(echo "$SECRET" | jq -r '.id')
  echo "    secret créé : $SECRET_ID"
else
  SECRET_ID="$EXISTING"
  echo "    secret existant réutilisé : $SECRET_ID"
fi

# 3. Tester le secret (validation auprès du provider)
echo "==> 3. POST /secrets/$SECRET_ID/test"
TEST=$(curl -fsS -X POST "$BASE_URL/api/admin/secrets/$SECRET_ID/test" "${H_ADMIN[@]}")
echo "$TEST" | jq -e '.ok == true' >/dev/null \
  || { echo "FAIL: clé Anthropic invalide ($(echo "$TEST" | jq -c .))"; exit 1; }

# 4. Vérifier que le dockerfile claude-code existe (sinon le créer/importer)
echo "==> 4. Vérification dockerfile claude-code"
DF=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/dockerfiles" \
  | jq -r '.[] | select(.id == "claude-code") | .id' | head -1)
if [[ -z "$DF" ]]; then
  echo "    dockerfile absent — création"
  curl -fsS -X POST "$BASE_URL/api/admin/dockerfiles" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d '{"id":"claude-code","display_name":"Claude Code","description":"Bootstrap test"}' \
    | jq -e '.id == "claude-code"' >/dev/null \
    || { echo "FAIL: création dockerfile"; exit 1; }
  echo "    NB: les fichiers Dockerfile/entrypoint.sh/Dockerfile.json doivent être"
  echo "        importés via POST /api/admin/dockerfiles/claude-code/import (zip)."
  echo "        Voir tests/fixtures/dockerfile-claude-code/ ou documentation déploiement."
  echo "WARN: import des fichiers à automatiser dans une itération future"
fi

# 5. Lancer un build et attendre qu'il réussisse (max 10 min)
echo "==> 5. Build claude-code"
DF_DETAIL=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/dockerfiles/claude-code")
DISPLAY_STATUS=$(echo "$DF_DETAIL" | jq -r '.display_status // .image_status // ""')
echo "    display_status = $DISPLAY_STATUS"
if [[ "$DISPLAY_STATUS" != "up_to_date" ]]; then
  echo "    déclenchement build…"
  BUILD=$(curl -fsS -X POST "$BASE_URL/api/admin/dockerfiles/claude-code/build" \
    "${H_ADMIN[@]}" -w "\n%{http_code}")
  CODE=$(echo "$BUILD" | tail -1)
  [[ "$CODE" == "202" ]] || { echo "FAIL: build refusé (HTTP $CODE)"; exit 1; }
  echo "    polling builds (max 10 min)…"
  for i in $(seq 1 60); do
    sleep 10
    LAST=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/dockerfiles/claude-code/builds" \
      | jq -r 'sort_by(.started_at) | last | .status')
    echo "      build #${i} status=$LAST"
    [[ "$LAST" == "succeeded" ]] && break
    [[ "$LAST" == "failed" ]] && { echo "FAIL: build failed"; exit 1; }
  done
  [[ "$LAST" == "succeeded" ]] || { echo "FAIL: build timeout"; exit 1; }
fi

# 6. Créer ou réutiliser le rôle test-assistant
echo "==> 6. Création/vérification rôle test-assistant"
ROLE_EXISTS=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/roles" \
  | jq -r '.[] | select(.id == "test-assistant") | .id' | head -1)
if [[ -z "$ROLE_EXISTS" ]]; then
  curl -fsS -X POST "$BASE_URL/api/admin/roles" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d '{"id":"test-assistant","display_name":"Test Assistant","description":"Rôle minimal pour tests fonctionnels"}' \
    | jq -e '.id == "test-assistant"' >/dev/null \
    || { echo "FAIL: création rôle"; exit 1; }
  echo "    rôle créé"
else
  echo "    rôle existant réutilisé"
fi

# 7. Créer ou réutiliser l'agent claude-code
echo "==> 7. Création/vérification agent claude-code"
AGENT_EXISTS=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/agents" \
  | jq -r '.[] | select(.slug == "claude-code") | .id' | head -1)
if [[ -z "$AGENT_EXISTS" ]]; then
  curl -fsS -X POST "$BASE_URL/api/admin/agents" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d '{"slug":"claude-code","display_name":"Claude Code Agent","dockerfile_id":"claude-code","role_id":"test-assistant"}' \
    | jq -e '.slug == "claude-code"' >/dev/null \
    || { echo "FAIL: création agent"; exit 1; }
  echo "    agent créé"
else
  echo "    agent existant réutilisé : $AGENT_EXISTS"
fi

# 8. Créer une API key dédiée aux tests fonctionnels
echo "==> 8. Création API key tests-functional"
KEY_RESP=$(curl -fsS -X POST "$BASE_URL/api/admin/api-keys" \
  "${H_ADMIN[@]}" "${H_JSON[@]}" \
  -d '{
    "name":"tests-functional",
    "scopes":["agents:read","agents:run","roles:read","containers.chat:read","containers.chat:write"],
    "rate_limit":120,
    "expires_in":"3m"
  }')
API_KEY=$(echo "$KEY_RESP" | jq -r '.full_key')
KEY_ID=$(echo "$KEY_RESP" | jq -r '.id')
[[ -n "$API_KEY" && "$API_KEY" != "null" ]] \
  || { echo "FAIL: création API key ($(echo "$KEY_RESP" | jq -c .))"; exit 1; }
echo "    API key ID : $KEY_ID"
echo
echo "================================================================"
echo "API_KEY=$API_KEY"
echo "================================================================"
echo "Stocker cette valeur dans un endroit sûr (1password, env var locale)."
echo "Elle ne sera **plus jamais** affichée par la plateforme."
echo "Export :  export API_KEY='$API_KEY'"
echo

# 9. Smoke test : utiliser la clé pour lister les agents
echo "==> 9. Smoke test API key"
curl -fsS -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/agents" \
  | jq -e --arg slug "claude-code" 'any(.[]; .slug == $slug)' >/dev/null \
  || { echo "FAIL: la clé ne permet pas de lister claude-code"; exit 1; }

echo "PASS — Test A01 platform-bootstrap"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 — POST /auth/login | 200 | `.access_token` JWT |
| 2 — POST /secrets | 201 ou réutilise existant | `.id` UUID |
| 3 — POST /secrets/{id}/test | 200 | `.ok == true` |
| 4 — Vérif dockerfile | 200 | `claude-code` présent |
| 5 — POST /build (si nécessaire) | 202 | dernier build `succeeded` en ≤ 10 min |
| 6 — Création rôle | 201 ou idempotent | `.id == "test-assistant"` |
| 7 — Création agent | 201 ou idempotent | `.slug == "claude-code"` |
| 8 — POST /api-keys | 201 | `.full_key` retourné une seule fois |
| 9 — Smoke test | 200 | `claude-code` listé |

## Nettoyage (optionnel)

À exécuter pour réinitialiser entre runs :

```bash
# Révoquer la clé API de test (la valeur ne sera plus utilisable)
curl -fsS -X DELETE "${H_ADMIN[@]}" "$BASE_URL/api/admin/api-keys/$KEY_ID"

# Supprimer l'agent et le rôle
AGENT_UUID=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/agents" \
  | jq -r '.[] | select(.slug == "claude-code") | .id')
[[ -n "$AGENT_UUID" ]] && \
  curl -fsS -X DELETE "${H_ADMIN[@]}" "$BASE_URL/api/admin/agents/$AGENT_UUID"
curl -fsS -X DELETE "${H_ADMIN[@]}" "$BASE_URL/api/admin/roles/test-assistant" || true

# Le secret reste — il sert aux autres déploiements
# Le dockerfile reste — l'image build est précieuse
```

## Notes

- **Idempotence** : le test détecte les ressources déjà présentes et les
  réutilise. Il peut être relancé sans nettoyer.
- **Import des fichiers Dockerfile** : si l'agent `claude-code` n'existe pas du
  tout dans la plateforme, l'opérateur doit fournir le contenu du Dockerfile,
  entrypoint.sh et Dockerfile.json. Cette étape n'est pas automatisée dans ce
  test (warning à l'étape 4) — elle suppose que l'image Docker est déjà
  disponible dans le registre, ou que l'opérateur a importé un zip avant.
- L'étape 5 peut prendre **plusieurs minutes** (build Docker complet). En CI,
  augmenter le timeout de `curl` ou utiliser `--max-time 900`.
- La clé `API_KEY` doit être exportée dans le shell avant de lancer les tests
  01-09.
