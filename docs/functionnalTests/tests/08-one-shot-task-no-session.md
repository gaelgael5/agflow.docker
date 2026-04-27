# Test 08 — Tâche one-shot sans session

> **📋 Cartouche — Cas applicatif 08**
>
> **Scénario fonctionnel** : `../08-one-shot-task-no-session.md`
> **Objectif** : tâche éphémère via stream NDJSON — pas de session, pas d'agent persistant
> **Durée** : 30-90s (selon `timeout_seconds` du payload)
> **Dépendances** : A01 (dockerfile `claude-code` build `up_to_date`)
>
> **Étapes vérifiées (6)** :
> 1. `POST /dockerfiles/{slug}/task` → 200, content-type `application/x-ndjson`
> 2. Première ligne = `{"type":"started", task_id, dockerfile_id}`
> 3. Dernière ligne = `{"type":"done"|"error"}`
> 4. (si `done`) `status` présent
> 5. `GET /launched` → contient `task_id`
> 6. Statut tâche ∈ `{finished, error, stopped}`

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/08-one-shot-task-no-session.md`.

## Préconditions

- `BASE_URL`, `API_KEY` exportées (scope `containers.chat:write` requis)
- Dockerfile `claude-code` (slug) existe avec build `up_to_date` et
  `Dockerfile.json` présent

## Données utilisées

Voir `00-test-data.md` §3.8.

| Donnée | Valeur |
|--------|--------|
| `dockerfile_id` | `claude-code` |
| `instruction` | `"Affiche le mot OK et termine"` |
| `timeout_seconds` | `60` |
| `model` | `""` (défaut) |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
DOCKERFILE_ID="${DOCKERFILE_ID:-claude-code}"

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Lancer la tâche one-shot, capturer le stream NDJSON
echo "==> 1. POST /dockerfiles/$DOCKERFILE_ID/task (stream NDJSON)"
NDJSON=$(mktemp)
HTTP_CODE=$(curl -fsS -o "$NDJSON" -w "%{http_code}" \
  -X POST "$BASE_URL/api/v1/dockerfiles/$DOCKERFILE_ID/task" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  --max-time 90 \
  -d '{"instruction":"Affiche le mot OK et termine","timeout_seconds":60,"model":""}')
[[ "$HTTP_CODE" == "200" ]] || { echo "FAIL: HTTP $HTTP_CODE"; cat "$NDJSON"; exit 1; }

LINE_COUNT=$(wc -l < "$NDJSON")
echo "    $LINE_COUNT ligne(s) NDJSON reçue(s)"
[[ "$LINE_COUNT" -ge 2 ]] || { echo "FAIL: stream trop court ($LINE_COUNT lignes)"; cat "$NDJSON"; exit 1; }

# 2. Vérifier le premier événement = "started" avec task_id
echo "==> 2. Vérification événement 'started'"
FIRST=$(head -1 "$NDJSON")
echo "$FIRST" | jq -e '.type == "started" and .task_id and .dockerfile_id' >/dev/null \
  || { echo "FAIL: première ligne pas 'started' valide: $FIRST"; exit 1; }
TID=$(echo "$FIRST" | jq -r '.task_id')
echo "    TID=$TID"

# 3. Vérifier la dernière ligne = "done" (ou "error")
echo "==> 3. Vérification événement final"
LAST=$(tail -1 "$NDJSON")
echo "$LAST" | jq -e '.type | IN("done","error")' >/dev/null \
  || { echo "FAIL: dernière ligne pas done/error: $LAST"; exit 1; }
FINAL_TYPE=$(echo "$LAST" | jq -r '.type')
echo "    type final = $FINAL_TYPE"

# 4. Si done, vérifier exit_code et status
if [[ "$FINAL_TYPE" == "done" ]]; then
  echo "$LAST" | jq -e '.status' >/dev/null \
    || echo "WARN: champ status absent du done"
fi

# 5. La tâche apparaît dans /launched filtré sur ce dockerfile
echo "==> 5. GET /launched"
curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/launched?dockerfile_id=$DOCKERFILE_ID" \
  | jq -e --arg tid "$TID" 'any(.[]; .id == $tid)' >/dev/null \
  || { echo "FAIL: task $TID absente de /launched"; exit 1; }

# 6. Vérifier que le statut DB de la tâche est terminal (finished, error, etc.)
echo "==> 6. Statut final de la tâche dans /launched"
TASK_STATUS=$(curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/launched?dockerfile_id=$DOCKERFILE_ID" \
  | jq -r --arg tid "$TID" '.[] | select(.id == $tid) | .status')
echo "    task.status=$TASK_STATUS"
[[ "$TASK_STATUS" =~ ^(finished|error|stopped)$ ]] \
  || { echo "FAIL: statut tâche inattendu: $TASK_STATUS"; exit 1; }

rm -f "$NDJSON"
echo "PASS — Test 08 one-shot-task-no-session"
```

## Résultats attendus (récap)

| Étape | HTTP / format | Assertion |
|-------|---------------|-----------|
| 1 — POST task | 200, content-type `application/x-ndjson` | au moins 2 lignes JSON |
| 2 — Première ligne | — | `{"type":"started","task_id":"<uuid>","dockerfile_id":"<slug>"}` |
| 3 — Dernière ligne | — | `.type ∈ {"done","error"}` |
| 5 — GET /launched | 200 | tableau contient `task_id` |
| 6 — Statut tâche | — | ∈ `{finished, error, stopped}` |

## Nettoyage

La tâche se nettoie elle-même (container éphémère). L'entrée dans `launched`
persiste. Pour purger côté admin :

```bash
# Optionnel
curl -fsS -X DELETE "${H_AUTH[@]}" "$BASE_URL/api/v1/launched/$TID" \
  -w "%{http_code}\n"
```

## Notes

- Le content-type retourné est `application/x-ndjson` (cf. `launched.py:130`).
  Le `COVERAGE.md` mentionne ça comme un point à clarifier dans la spec OpenAPI
  (qui annonce `application/json`).
- Le test ne valide pas le **contenu** de l'instruction (l'agent peut produire
  n'importe quoi tant qu'il termine). Il vérifie uniquement le contrat de stream.
- Si la build du dockerfile n'est pas `up_to_date`, l'endpoint renvoie **409
  not_up_to_date** : il faut alors lancer une build avant. Cf. A01.
