# Test 10 — SaaS runtime creation (multi-replica + réseau user)

> **📋 Cartouche — Cas applicatif 10 (SaaS Phase 1)**
>
> **Scénario fonctionnel** : nouveau (pas dans `docs/functionnalTests/01-09`) — couvre
> la création d'un runtime depuis une API publique scopée par owner.
> **Objectif** : un owner crée un runtime d'un projet sur sa machine dédiée pour
> un environnement, sélectionne quels groupes lancer et combien de copies, fournit
> ses secrets, et récupère les endpoints (containers + IPs + ports).
> **Durée** : 1-3 min (push compose + démarrage Docker)
> **Dépendances** :
>   - A01 (admin + clé API)
>   - Au moins une machine `infra_machines` assignée à `(user, env)` via UI admin
>   - Au moins un projet avec ≥1 groupe (`max_replicas >= 1`) et ≥1 instance pointant
>     sur une recette MinIO ou équivalente
>   - Scopes API key : `projects:read`, `runtimes:read`, `runtimes:write`, `runtimes:delete`
>
> **Étapes vérifiées (10)** :
> 1. `GET /api/v1/projects` → projet attendu présent
> 2. `GET /api/v1/projects/{id}` → groupes + `max_replicas` exposés
> 3. `POST /api/v1/projects/{id}/runtimes` avec `groups: {<gid>: {replica_count: 2}}`, `environment: dev`, `user_secrets: {...}` → 201
> 4. `GET /api/v1/runtimes` → contient le runtime créé
> 5. `GET /api/v1/runtimes/{id}` → `status=deployed`, `group_runtimes` non vide
> 6. `GET /api/v1/runtimes/{id}/endpoints` → 2 entrées (2 replicas) avec ports dynamiques
> 7. Sur la machine cible : `docker ps --filter label=agflow.runtime_id={id}` → 2 containers
> 8. Sur la machine cible : `docker network inspect agflow-user-{X}` → réseau présent
> 9. `DELETE /api/v1/runtimes/{id}` → 204
> 10. `GET /api/v1/runtimes/{id}` après delete → 404

## Préconditions

```bash
: "${BASE_URL:?}"           # ex: https://docker-agflow.yoops.org
: "${API_KEY:?}"            # clé scopes runtimes:* + projects:read
: "${PROJECT_ID:?}"         # UUID du projet template à instancier
: "${GROUP_ID:?}"           # UUID d'un groupe du projet (max_replicas >= 2)
: "${ENVIRONMENT:=dev}"
```

## Étapes

```bash
set -euo pipefail
H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Lister le catalogue projet
echo "==> 1. GET /api/v1/projects"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/projects" \
  | jq -e --arg pid "$PROJECT_ID" 'any(.[]; .id == $pid)' >/dev/null \
  || { echo "FAIL: projet $PROJECT_ID absent du catalogue"; exit 1; }

# 2. Détail projet : groupes + max_replicas
echo "==> 2. GET /api/v1/projects/{id}"
DETAIL=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/projects/$PROJECT_ID")
echo "$DETAIL" | jq -e --arg gid "$GROUP_ID" \
    '.groups | any(.[]; .id == $gid and .max_replicas >= 2)' >/dev/null \
  || { echo "FAIL: groupe $GROUP_ID absent ou max_replicas < 2"; exit 1; }

# 3. Création runtime — 2 replicas du groupe + secrets utilisateur
echo "==> 3. POST /runtimes (replica_count=2)"
CREATE=$(curl -fsS -X POST "$BASE_URL/api/v1/projects/$PROJECT_ID/runtimes" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{
    \"environment\": \"$ENVIRONMENT\",
    \"groups\": {
      \"$GROUP_ID\": { \"replica_count\": 2 }
    },
    \"user_secrets\": {
      \"MINIO_ROOT_USER\": \"admin\",
      \"MINIO_ROOT_PASSWORD\": \"changeme-test-only\"
    }
  }")
RUNTIME_ID=$(echo "$CREATE" | jq -r '.id')
[[ -n "$RUNTIME_ID" && "$RUNTIME_ID" != "null" ]] \
  || { echo "FAIL: runtime non créé ($(echo "$CREATE" | jq -c .))"; exit 1; }
echo "    RUNTIME_ID=$RUNTIME_ID"
echo "$CREATE" | jq -e '.status == "deployed"' >/dev/null \
  || { echo "FAIL: status non 'deployed' (status=$(echo "$CREATE" | jq -r .status), error=$(echo "$CREATE" | jq -r .error_message))"; exit 1; }

# 4. Listing : mon runtime apparaît
echo "==> 4. GET /api/v1/runtimes"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/runtimes" \
  | jq -e --arg rid "$RUNTIME_ID" 'any(.[]; .id == $rid)' >/dev/null \
  || { echo "FAIL: runtime absent du listing"; exit 1; }

# 5. Détail : group_runtimes peuplé avec replica_count
echo "==> 5. GET /api/v1/runtimes/{id}"
DETAIL=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/runtimes/$RUNTIME_ID")
echo "$DETAIL" | jq -e \
    '.status == "deployed" and (.group_runtimes | length >= 1)
     and (.group_runtimes | any(.replica_count == 2))' >/dev/null \
  || { echo "FAIL: détail runtime invalide"; exit 1; }

# 6. Endpoints : containers + ports dynamiques
echo "==> 6. GET /api/v1/runtimes/{id}/endpoints"
ENDPOINTS=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/runtimes/$RUNTIME_ID/endpoints")
COUNT=$(echo "$ENDPOINTS" | jq 'length')
[[ "$COUNT" -ge 2 ]] \
  || { echo "FAIL: <2 endpoints (2 replicas attendues), got $COUNT"; exit 1; }
echo "$ENDPOINTS" | jq -e \
    'all(.[]; .container_name and .image and .host
              and (.ports | type == "array")
              and (.status | IN("running","created","starting","stopped","unknown")))' >/dev/null \
  || { echo "FAIL: structure endpoint invalide"; exit 1; }
echo "    $COUNT endpoint(s) :"
echo "$ENDPOINTS" | jq -r '.[] | "      \(.container_name) → \(.host):\(.ports[0].host // "?") status=\(.status)"'

# 7-8. (à valider à la main / via SSH si besoin) :
# docker ps --filter label=agflow.runtime_id=$RUNTIME_ID
# docker network inspect agflow-user-<8hex_du_user>

# 9. Suppression
echo "==> 9. DELETE /api/v1/runtimes/{id}"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/runtimes/$RUNTIME_ID" | grep -q "^204$" \
  || { echo "FAIL: DELETE != 204"; exit 1; }

# 10. Vérification post-delete
echo "==> 10. GET après DELETE → 404"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/runtimes/$RUNTIME_ID")
[[ "$HTTP" == "404" ]] || { echo "FAIL: GET après delete a renvoyé $HTTP, attendu 404"; exit 1; }

echo "PASS — Test 10 saas-runtime-creation"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 | 200 | catalogue contient `PROJECT_ID` |
| 2 | 200 | groupe avec `max_replicas >= 2` exposé |
| 3 | 201 | `id` UUID, `status == "deployed"`, pas d'`error_message` |
| 4 | 200 | runtime listé sous `GET /runtimes` |
| 5 | 200 | `group_runtimes` non vide, `replica_count == 2` présent |
| 6 | 200 | ≥2 endpoints, structure `{container_name, image, host, ports[], status}` |
| 9 | 204 | DELETE accepté |
| 10 | 404 | runtime invisible après delete (soft-delete) |

## Erreurs attendues

| Cas | HTTP | Détail |
|-----|------|--------|
| `replica_count > max_replicas` | 400 | message contient `requested N replicas, max allowed` |
| `(user, environment)` sans machine | 412 | message contient `No machine assigned to` |
| Scope manquant | 403 | `missing_scope` |
| Runtime d'un autre owner | 404 | jamais 403, on ne fuite pas l'existence |

## Nettoyage

Le test fait son propre cleanup à l'étape 9 (DELETE). Si interrompu en cours :

```bash
# Lister les runtimes orphelins
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/runtimes" \
  | jq -r '.[] | select(.status == "deployed" or .status == "failed") | .id' \
  | while read rid; do
      curl -s -o /dev/null -X DELETE "${H_AUTH[@]}" \
        "$BASE_URL/api/v1/runtimes/$rid"
    done
```

## Notes

- L'étape 7-8 (vérifications côté machine via SSH) sont marquées comme manuelles —
  elles supposent un accès SSH à la machine cible. À automatiser dans une itération
  future si besoin de validation systématique.
- Le `user_secrets` envoyé doit correspondre aux variables `${VAR}` que la recette
  attend. Si une variable est manquante, un warning est loggé côté backend mais le
  runtime se lance quand même (le container échouera au runtime si la var lui est
  vraiment indispensable).
- L'allocation de ports est dynamique via Docker → les valeurs `ports[].host`
  changent à chaque création. Le client doit lire `/endpoints` après chaque
  création pour récupérer les ports effectifs.
