# Test 06 — Session longue avec extension

> **📋 Cartouche — Cas applicatif 06**
>
> **Scénario fonctionnel** : `../06-long-running-session-extension.md`
> **Objectif** : prolonger une session avant expiration sans interrompre les agents
> **Durée** : ~2 min 30s (skip via `SKIP_LONG_TESTS=1`)
> **Dépendances** : A01 + worker session-expiration actif
>
> **Étapes vérifiées (7)** :
> 1. `POST /sessions duration=120s` (TTL court)
> 2. `GET` → `status=active`
> 3. Attente 10s puis `PATCH /extend duration=1800s`
> 4. Calcul delta `expires_at` → ≥ 1500s
> 5. Attente 120s pour dépasser le TTL initial
> 6. `GET` → toujours `active` (l'extension a fonctionné)
> 7. `DELETE` session

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/06-long-running-session-extension.md`.

## Préconditions

- `BASE_URL`, `API_KEY` exportées
- Worker d'expiration sessions actif sur l'env (cf. supervision Phase 1)

## Données utilisées

Voir `00-test-data.md` §3.6.

| Donnée | Valeur |
|--------|--------|
| `session.duration_seconds` initial | `120` (le minimum est 60) |
| `extend.duration_seconds` | `1800` |
| Délai entre création et extension | `10s` |
| Délai entre extension et vérif post-expiration initiale | `120s` (assure dépassement de l'`expires_at` original) |

> Le test prend ~2 min 30. Il peut être skip via `SKIP_LONG_TESTS=1`.

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
[[ "${SKIP_LONG_TESTS:-0}" == "1" ]] && { echo "SKIP — test 06 (long)"; exit 0; }

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Créer session avec TTL = 120s
echo "==> 1. Création session TTL=120s"
SESSION=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"name":"test-06-extend","duration_seconds":120}')
SID=$(echo "$SESSION" | jq -r '.id')
EXP_INIT=$(echo "$SESSION" | jq -r '.expires_at')
echo "    SID=$SID"
echo "    expires_at initial: $EXP_INIT"

# 2. Vérifier statut active
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID" \
  | jq -e '.status == "active"' >/dev/null \
  || { echo "FAIL: pas active après création"; exit 1; }

# 3. Attendre 10s puis prolonger
echo "==> 3. Attente 10s puis PATCH extend +1800s"
sleep 10
EXTENDED=$(curl -fsS -X PATCH "$BASE_URL/api/v1/sessions/$SID/extend" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"duration_seconds":1800}')
EXP_NEW=$(echo "$EXTENDED" | jq -r '.expires_at')
echo "    expires_at après extension: $EXP_NEW"

# 4. Vérifier que expires_at a bien été repoussé (au moins 1500s plus loin que l'initial)
ts_init=$(date -d "$EXP_INIT" +%s 2>/dev/null || python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('$EXP_INIT'.replace('Z','+00:00')).timestamp()))")
ts_new=$(date -d "$EXP_NEW" +%s 2>/dev/null || python3 -c "from datetime import datetime; print(int(datetime.fromisoformat('$EXP_NEW'.replace('Z','+00:00')).timestamp()))")
DELTA=$((ts_new - ts_init))
echo "    delta = ${DELTA}s"
[[ "$DELTA" -ge 1500 ]] || { echo "FAIL: extension < 1500s (delta=$DELTA)"; exit 1; }

# 5. Attendre 120s pour dépasser le TTL initial (110s restants après extension à T+10)
echo "==> 5. Attente 120s pour dépasser le TTL initial..."
sleep 120

# 6. La session doit être TOUJOURS active
echo "==> 6. GET session après dépassement TTL initial"
STATUS=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/sessions/$SID" | jq -r '.status')
[[ "$STATUS" == "active" ]] \
  || { echo "FAIL: session expirée malgré l'extension (status=$STATUS)"; exit 1; }

# 7. Fermer la session explicitement
echo "==> 7. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

echo "PASS — Test 06 long-running-session-extension"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 — POST session TTL=120s | 201 | `.expires_at` ≈ `created_at + 120s` |
| 3 — PATCH extend +1800s | 200 | nouveau `.expires_at` |
| 4 — Delta entre `EXP_NEW` et `EXP_INIT` | — | ≥ 1500s |
| 6 — GET après 130s | 200 | `.status="active"` (pas expired) |
| 7 — DELETE session | 204 | — |

## Nettoyage

Session fermée à l'étape 7.

## Notes

- Pour tester aussi l'**expiration automatique** (sans extension), créer une autre
  session courte puis vérifier `status=expired` après dépassement. Hors scope de ce
  test (couvert dans `sessions-v1-scenarios.md` S4).
- Si `date -d` n'est pas disponible (BSD/macOS), le fallback Python est utilisé.
