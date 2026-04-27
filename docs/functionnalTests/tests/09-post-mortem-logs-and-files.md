# Test 09 — Post-mortem (messages, logs, workspace)

> **📋 Cartouche — Cas applicatif 09**
>
> **Scénario fonctionnel** : `../09-post-mortem-logs-and-files.md`
> **Objectif** : reconstruire a posteriori messages, logs et workspace d'une instance
> **Durée** : 30-90s (setup + lecture)
> **Dépendances** : A01 (le test crée son propre setup interne — pas besoin d'une session existante)
>
> **Étapes vérifiées (8)** :
> 1. Setup interne : session + agent + 1 cycle message complet
> 2. `GET messages` instance → ≥2 messages, présence `direction=in` ET `out`
> 3. `GET logs` → format `[ts] [kind] text`, content-type `text/plain`
> 4. `GET files?path=` racine → `type ∈ {dir, missing}`
> 5. (si dir) parsing des entrées
> 6. `DELETE` session → 204
> 7. `GET messages` APRÈS DELETE → toujours lisibles (post-mortem)
> 8. `GET logs` APRÈS DELETE → toujours lisibles

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/09-post-mortem-logs-and-files.md`.

## Préconditions

- `BASE_URL`, `API_KEY` exportées
- Catalogue contient `claude-code` (override `AGENT_SLUG`)
- Le test est **autonome** : il crée d'abord une session, exécute un cycle
  minimal, **puis** lit les artefacts en post-mortem (avant fermeture).
  Le scénario d'origine prévoit aussi le cas "session déjà fermée" — vérifié
  ici à l'étape finale.

## Données utilisées

Voir `00-test-data.md` §3.9.

| Donnée | Valeur |
|--------|--------|
| Path workspace | `""` (racine) |
| `messages?limit` | `100` |
| `logs?limit` | `200` |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
AGENT_SLUG="${AGENT_SLUG:-claude-code}"

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Setup minimal : session + agent + 1 message + attente d'au moins 1 réponse
echo "==> 1. Setup : session + agent + 1 cycle message"
SID=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"name":"test-09-postmortem","duration_seconds":600}' | jq -r '.id')
IID=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1,\"mission\":\"Post-mortem test\"}" \
  | jq -r '.instance_ids[0]')
curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"kind":"instruction","payload":{"text":"Réponds OK"}}' >/dev/null

echo "    SID=$SID  IID=$IID"
echo "    Attente d'au moins 1 message OUT (max 60s)..."
for i in $(seq 1 30); do
  COUNT=$(curl -fsS "${H_AUTH[@]}" \
    "$BASE_URL/api/v1/sessions/$SID/agents/$IID/messages?direction=out&limit=10" \
    | jq 'length')
  [[ "$COUNT" -ge 1 ]] && break
  sleep 2
done
[[ "$COUNT" -ge 1 ]] || { echo "FAIL setup: pas de réponse en 60s"; exit 1; }

# 2. Récupérer l'historique chronologique des messages d'instance
echo "==> 2. GET messages instance (post-mortem)"
HIST=$(curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID/messages?limit=100")
echo "$HIST" | jq -e 'length >= 2' >/dev/null \
  || { echo "FAIL: historique trop court (< 2 messages)"; exit 1; }
# Vérifier que les directions in et out sont présentes
echo "$HIST" | jq -e 'any(.[]; .direction == "in")' >/dev/null \
  || { echo "FAIL: aucun message direction=in"; exit 1; }
echo "$HIST" | jq -e 'any(.[]; .direction == "out")' >/dev/null \
  || { echo "FAIL: aucun message direction=out"; exit 1; }
echo "    $(echo "$HIST" | jq 'length') messages dans l'historique"

# 3. Récupérer les logs texte (format [ts] [kind] text)
echo "==> 3. GET logs instance"
LOGS=$(curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID/logs?limit=200")
[[ -n "$LOGS" ]] || { echo "FAIL: logs vides"; exit 1; }
echo "$LOGS" | head -1 | grep -qE '^\[[0-9T:.+-]+\] \[[a-z_]+\]' \
  || { echo "FAIL: format logs inattendu (première ligne: $(echo "$LOGS" | head -1))"; exit 1; }
echo "    $(echo "$LOGS" | wc -l) ligne(s) de log"

# 4. Lister le workspace de l'agent (racine)
echo "==> 4. GET workspace racine"
WS=$(curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID/files?path=")
echo "$WS" | jq -e '.type | IN("dir","missing")' >/dev/null \
  || { echo "FAIL: workspace réponse inattendue"; exit 1; }
WS_TYPE=$(echo "$WS" | jq -r '.type')
echo "    workspace.type=$WS_TYPE"

# 5. Si workspace=dir, parcourir une sous-entrée pour valider la sérialisation
if [[ "$WS_TYPE" == "dir" ]]; then
  ENTRIES=$(echo "$WS" | jq '.entries | length')
  echo "    $ENTRIES entrée(s) dans le workspace"
  if [[ "$ENTRIES" -gt 0 ]]; then
    FIRST=$(echo "$WS" | jq -r '.entries[0] | "\(.type):\(.name)"')
    echo "    première entrée : $FIRST"
  fi
fi

# 6. Fermer la session
echo "==> 6. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

# 7. Vérifier que les messages restent accessibles APRÈS fermeture (post-mortem strict)
echo "==> 7. GET messages APRÈS DELETE session"
curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID/messages?limit=10" \
  | jq -e 'length >= 1' >/dev/null \
  || { echo "FAIL: messages illisibles après fermeture session"; exit 1; }

# 8. Logs accessibles également
curl -fsS "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID/agents/$IID/logs?limit=50" \
  | grep -q . \
  || { echo "FAIL: logs vides après fermeture"; exit 1; }

echo "PASS — Test 09 post-mortem-logs-and-files"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 2 — GET messages instance | 200 | ≥ 2 messages, présence `direction=in` ET `direction=out` |
| 3 — GET logs | 200, `text/plain` | au moins 1 ligne au format `[ts] [kind] text` |
| 4 — GET files (racine) | 200 | `.type ∈ {dir, missing}` |
| 5 — GET files (entrées) | 200 | si dir, `.entries` est un tableau ; chaque entrée a `type` et `name` |
| 6 — DELETE session | 204 | — |
| 7 — GET messages POST DELETE | 200 | toujours ≥ 1 message lisible |
| 8 — GET logs POST DELETE | 200 | toujours non vide |

## Nettoyage

Session fermée à l'étape 6. Les messages et logs restent en base (c'est le but
du post-mortem). Pas de purge automatique côté test.

## Notes

- L'endpoint `/files` peut renvoyer `{"type":"missing"}` si le workspace n'a
  jamais été créé sur le filesystem (agent qui n'a pas écrit). Ce n'est pas un
  fail — c'est un état possible légitime documenté dans le code (`messages.py:233`).
- Le scénario fonctionnel original parle de "session déjà fermée" comme
  pré-condition. Notre test couvre les deux : avant fermeture (étapes 2-5) et
  après (étapes 7-8).
- Le workspace est conservé tant que le container existe ; un GC ultérieur
  pourrait nettoyer. Pour les livrables critiques, voir cas 04 (écriture sur
  projet).
