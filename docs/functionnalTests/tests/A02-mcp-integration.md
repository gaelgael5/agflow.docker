# Test A02 — Intégration d'un MCP externe (opérateur)

> **📋 Cartouche — Scénario opérateur A02**
>
> **Scénario fonctionnel** : `../A02-mcp-integration.md`
> **Objectif** : installer un MCP filesystem et le binder à l'agent `claude-code`
> **Durée** : 30s-2min (selon réponse du registre)
> **Dépendances** : A01 + connectivité sortante vers `mcp.yoops.org` + `ADMIN_JWT`
> **Idempotent** : oui
>
> **Étapes vérifiées (6)** :
> 1. Création/vérif discovery service `yoops-mcp`
> 2. `POST /discovery-services/{id}/test` → ok
> 3. `GET /search/mcp?q=filesystem` → ≥1 résultat
> 4. `POST /mcp-catalog` (si non installé)
> 5. `PUT /agents/{uuid}` avec `mcp_bindings += MCP_ID`
> 6. (warn-only) Visibilité du binding via `/api/v1/agents/{uuid}` (discovery publique)

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/A02-mcp-integration.md`. Pré-requis pour le cas
applicatif 04.

## Préconditions

- A01 exécuté (agent `claude-code` existe)
- `BASE_URL`, `ADMIN_JWT` exportés (le JWT est récupéré via le login admin —
  cf. A01 étape 1)
- Connectivité sortante depuis l'env de test vers `https://mcp.yoops.org`

## Données utilisées

Voir `00-test-data.md` §4.2.

| Donnée | Valeur |
|--------|--------|
| Discovery service ID | `yoops-mcp` |
| Discovery service URL | `https://mcp.yoops.org/api/v1` |
| Package recherché | mot-clé `filesystem` |
| Recipe attendue | `stdio` (ou la première disponible) |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${ADMIN_JWT:?ADMIN_JWT must be set (cf. A01 étape 1)}"

H_ADMIN=(-H "Authorization: Bearer $ADMIN_JWT")
H_JSON=(-H "Content-Type: application/json")

# 1. Créer ou réutiliser le discovery service yoops-mcp
echo "==> 1. Création/vérification discovery service yoops-mcp"
DS_EXISTS=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/discovery-services" \
  | jq -r '.[] | select(.id == "yoops-mcp") | .id' | head -1)
if [[ -z "$DS_EXISTS" ]]; then
  curl -fsS -X POST "$BASE_URL/api/admin/discovery-services" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d '{
      "id":"yoops-mcp",
      "name":"Yoops MCP Registry",
      "base_url":"https://mcp.yoops.org/api/v1",
      "description":"Registre MCP public yoops",
      "enabled":true
    }' \
    | jq -e '.id == "yoops-mcp"' >/dev/null \
    || { echo "FAIL: création discovery service"; exit 1; }
  echo "    discovery service créé"
else
  echo "    discovery service existant réutilisé"
fi

# 2. Tester la connectivité
echo "==> 2. Test connectivité discovery service"
PROBE=$(curl -fsS -X POST "$BASE_URL/api/admin/discovery-services/yoops-mcp/test" \
  "${H_ADMIN[@]}")
echo "$PROBE" | jq -e '.ok == true or .status == "ok"' >/dev/null \
  || { echo "FAIL: discovery service injoignable ($(echo "$PROBE" | jq -c .))"; exit 1; }

# 3. Rechercher un package "filesystem"
echo "==> 3. Recherche MCP filesystem"
SEARCH=$(curl -fsS "${H_ADMIN[@]}" \
  "$BASE_URL/api/admin/discovery-services/yoops-mcp/search/mcp?q=filesystem")
echo "$SEARCH" | jq -e 'length >= 1' >/dev/null \
  || { echo "FAIL: aucun package filesystem trouvé"; exit 1; }
PKG_ID=$(echo "$SEARCH" | jq -r '.[0].package_id // .[0].id')
PKG_RECIPES=$(echo "$SEARCH" | jq -c '.[0].recipes // {}')
echo "    package: $PKG_ID"
echo "    recipes: $PKG_RECIPES"

# 4. Installer le MCP (recipe stdio si dispo, sinon tout le bloc recipes)
echo "==> 4. Installation MCP filesystem"
# Vérifier si déjà installé
INST_EXISTS=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/mcp-catalog" \
  | jq -r --arg pkg "$PKG_ID" '.[] | select(.package_id == $pkg) | .id' | head -1)
if [[ -z "$INST_EXISTS" ]]; then
  INSTALL=$(curl -fsS -X POST "$BASE_URL/api/admin/mcp-catalog" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d "{
      \"discovery_service_id\":\"yoops-mcp\",
      \"package_id\":\"$PKG_ID\",
      \"recipes\":$PKG_RECIPES,
      \"parameters\":[],
      \"category\":\"filesystem\"
    }")
  MCP_ID=$(echo "$INSTALL" | jq -r '.id')
  [[ -n "$MCP_ID" && "$MCP_ID" != "null" ]] \
    || { echo "FAIL: installation MCP ($(echo "$INSTALL" | jq -c .))"; exit 1; }
  echo "    MCP installé : $MCP_ID"
else
  MCP_ID="$INST_EXISTS"
  echo "    MCP déjà installé : $MCP_ID"
fi

# 5. Récupérer l'agent claude-code et binder le MCP
echo "==> 5. Binding MCP à l'agent claude-code"
AGENT_UUID=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/agents" \
  | jq -r '.[] | select(.slug == "claude-code") | .id')
[[ -n "$AGENT_UUID" && "$AGENT_UUID" != "null" ]] \
  || { echo "FAIL: agent claude-code introuvable (lancer A01 d'abord)"; exit 1; }

# Récupérer le détail courant pour préserver les autres champs
AGENT_DETAIL=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/agents/$AGENT_UUID")

# Vérifier si le binding existe déjà
ALREADY_BOUND=$(echo "$AGENT_DETAIL" \
  | jq -r --arg mid "$MCP_ID" '.mcp_bindings // [] | any(.[]; .mcp_server_id == $mid)')
if [[ "$ALREADY_BOUND" == "true" ]]; then
  echo "    binding déjà présent — skip"
else
  # Construire le payload PUT en réutilisant le détail courant + ajout du binding
  NEW_BINDINGS=$(echo "$AGENT_DETAIL" \
    | jq --arg mid "$MCP_ID" \
        '.mcp_bindings // [] | . + [{"mcp_server_id": $mid, "parameters_override": {}, "position": (length)}]')
  PUT_BODY=$(echo "$AGENT_DETAIL" | jq --argjson b "$NEW_BINDINGS" \
    'del(.id, .slug, .created_at, .updated_at, .image_status, .has_errors, .image_built_at) | .mcp_bindings = $b')
  curl -fsS -X PUT "$BASE_URL/api/admin/agents/$AGENT_UUID" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d "$PUT_BODY" \
    | jq -e --arg mid "$MCP_ID" '.mcp_bindings | any(.[]; .mcp_server_id == $mid)' >/dev/null \
    || { echo "FAIL: binding non persisté"; exit 1; }
  echo "    binding ajouté"
fi

# 6. Vérification finale via la discovery publique
echo "==> 6. Vérification visibilité du binding (discovery publique)"
if [[ -n "${API_KEY:-}" ]]; then
  curl -fsS -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/agents/$AGENT_UUID" \
    | jq -e '.mcp_bindings | length >= 1' >/dev/null \
    && echo "    binding visible côté discovery publique" \
    || echo "WARN: binding non remonté côté discovery publique (gap connu — cf. COVERAGE.md)"
else
  echo "    SKIP : API_KEY non exportée (pas de vérification publique)"
fi

echo "PASS — Test A02 mcp-integration"
echo "MCP_ID=$MCP_ID"
echo "AGENT_UUID=$AGENT_UUID"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 — POST /discovery-services | 201 ou idempotent | `.id == "yoops-mcp"` |
| 2 — POST /discovery-services/{id}/test | 200 | `.ok == true` ou `.status == "ok"` |
| 3 — GET /search/mcp | 200 | au moins 1 résultat |
| 4 — POST /mcp-catalog | 201 ou idempotent | `.id` UUID |
| 5 — PUT /agents/{id} | 200 | `mcp_bindings` contient le `mcp_server_id` |
| 6 — GET /api/v1/agents/{id} (publique) | 200 | warn-only — binding peut ne pas être remonté |

## Nettoyage (optionnel)

```bash
# Retirer le binding (PUT avec mcp_bindings vidé du MCP en question)
# Désinstaller le MCP
curl -fsS -X DELETE "${H_ADMIN[@]}" "$BASE_URL/api/admin/mcp-catalog/$MCP_ID" || true

# Supprimer le discovery service (optionnel — peut être conservé pour autres tests)
curl -fsS -X DELETE "${H_ADMIN[@]}" "$BASE_URL/api/admin/discovery-services/yoops-mcp" || true
```

## Notes

- Le format exact du champ `recipes` retourné par la search varie selon le
  registre yoops. Le test injecte tel quel ce que renvoie la search dans le
  payload d'install. Si l'install échoue avec un message du type
  `parameters required`, ajouter les paramètres requis dans `"parameters":[...]`.
- Le binding agent←MCP se fait via **PUT /admin/agents/{id}** avec le champ
  `mcp_bindings`. Le test reconstruit le payload complet en supprimant les champs
  read-only (`id`, `slug`, `created_at`, etc.).
- **Limitation V1** : `AgentDetail` côté public n'expose pas systématiquement le
  bloc `mcp_bindings` détaillé. L'étape 6 est tolérante (warn-only).
- Si la connectivité vers `mcp.yoops.org` est bloquée (firewall sortant), le
  test ne peut pas s'exécuter. Prévoir un mock MCP local pour les envs offline.
