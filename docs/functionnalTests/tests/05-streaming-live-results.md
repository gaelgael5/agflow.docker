# Test 05 — Réception en streaming (WebSocket)

> **📋 Cartouche — Cas applicatif 05**
>
> **Scénario fonctionnel** : `../05-streaming-live-results.md`
> **Objectif** : remplacer le polling par un WebSocket — streaming live des messages OUT
> **Durée** : 30-90s
> **Dépendances** : A01 + `wscat` installé (`npm install -g wscat`)
>
> **Étapes vérifiées (7)** :
> 1. `POST /sessions`
> 2. `POST /agents count=1`
> 3. Ouverture WS `/agents/{iid}/stream` + check pid vivant après 2s
> 4. POST message instruction
> 5. Capture frames WS (max 60s) — au moins 1 frame `< {...}`
> 6. Format frame : `{msg_id, instance_id, direction="out", kind, payload, created_at}`
> 7. Kill WS + `DELETE` session

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/05-streaming-live-results.md`.

## Préconditions

- `BASE_URL`, `WS_URL`, `API_KEY` exportées
- Catalogue contient `claude-code` (override `AGENT_SLUG`)
- `wscat` installé (`npm install -g wscat`)

## Données utilisées

Voir `00-test-data.md` §3.5.

| Donnée | Valeur |
|--------|--------|
| `session.name` | `test-05-stream` |
| Endpoint WS | `${WS_URL}/api/v1/sessions/{sid}/agents/{iid}/stream` |
| Message | `{"text": "Compte de 1 à 5 lentement"}` |
| Timeout WS | 60s |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${WS_URL:?WS_URL must be set}"
: "${API_KEY:?API_KEY must be set}"
AGENT_SLUG="${AGENT_SLUG:-claude-code}"
command -v wscat >/dev/null || { echo "FAIL: wscat absent (npm install -g wscat)"; exit 1; }

H_AUTH=(-H "Authorization: Bearer $API_KEY")
H_JSON=(-H "Content-Type: application/json")

# 1. Créer session + spawn agent
echo "==> 1. Création session"
SID=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"name":"test-05-stream","duration_seconds":600}' | jq -r '.id')
echo "    SID=$SID"

echo "==> 2. Spawn agent"
IID=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{\"agent_id\":\"$AGENT_SLUG\",\"count\":1,\"mission\":\"Stream test\"}" \
  | jq -r '.instance_ids[0]')
echo "    IID=$IID"

# 3. Ouvrir le WS en background, capturer les frames dans un fichier
echo "==> 3. Ouverture WS streaming"
WS_OUT=$(mktemp)
WS_LOG=$(mktemp)
# wscat avec timeout (kill après 60s) ; on accepte aussi la version sans tls
wscat -c "$WS_URL/api/v1/sessions/$SID/agents/$IID/stream" \
  > "$WS_OUT" 2> "$WS_LOG" &
WS_PID=$!
sleep 2  # laisser le temps à la connexion

# Vérifier que la connexion tient
if ! kill -0 "$WS_PID" 2>/dev/null; then
  echo "FAIL: wscat n'a pas tenu (logs: $(cat "$WS_LOG"))"
  rm -f "$WS_OUT" "$WS_LOG"
  exit 1
fi
echo "    WS connecté (pid $WS_PID)"

# 4. Poster une demande qui devrait produire plusieurs événements
echo "==> 4. POST message"
MID=$(curl -fsS -X POST "$BASE_URL/api/v1/sessions/$SID/agents/$IID/message" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"kind":"instruction","payload":{"text":"Compte de 1 à 5 lentement"}}' \
  | jq -r '.msg_id')
echo "    MID=$MID"

# 5. Attendre jusqu'à 60s qu'au moins une frame arrive sur le WS
echo "==> 5. Attente frames WS (max 60s)"
FRAMES=0
for i in $(seq 1 30); do
  sleep 2
  # wscat affiche "< {json}" pour chaque frame reçue
  FRAMES=$(grep -c '^< {' "$WS_OUT" 2>/dev/null || echo 0)
  if [[ "$FRAMES" -ge 1 ]]; then
    echo "    $FRAMES frame(s) reçue(s) après ${i}*2s"
    break
  fi
done
[[ "$FRAMES" -ge 1 ]] || {
  echo "FAIL: aucune frame en 60s"
  echo "WS stdout: $(cat "$WS_OUT")"
  echo "WS stderr: $(cat "$WS_LOG")"
  kill "$WS_PID" 2>/dev/null || true
  rm -f "$WS_OUT" "$WS_LOG"
  exit 1
}

# 6. Vérifier le format de la première frame
echo "==> 6. Vérification format de frame"
FIRST_FRAME=$(grep '^< {' "$WS_OUT" | head -1 | sed 's/^< //')
echo "$FIRST_FRAME" | jq -e '
  .msg_id and .instance_id and .direction and .kind and .payload and .created_at
  and .direction == "out"
' >/dev/null \
  || { echo "FAIL: frame mal formée: $FIRST_FRAME"; kill "$WS_PID" 2>/dev/null || true; exit 1; }

# 7. Fermer le WS et la session
kill "$WS_PID" 2>/dev/null || true
wait "$WS_PID" 2>/dev/null || true
rm -f "$WS_OUT" "$WS_LOG"

echo "==> 7. DELETE session"
curl -fsS -o /dev/null -w "%{http_code}\n" -X DELETE "${H_AUTH[@]}" \
  "$BASE_URL/api/v1/sessions/$SID" | grep -q "^204$" \
  || { echo "FAIL: DELETE session != 204"; exit 1; }

echo "PASS — Test 05 streaming-live-results"
```

## Résultats attendus (récap)

| Étape | Assertion |
|-------|-----------|
| 3 — Connexion wscat | reste vivante après 2s (handshake OK) |
| 4 — POST message | 201, `msg_id` UUID |
| 5 — Frames WS | au moins 1 frame `< {...}` en ≤ 60s |
| 6 — Format frame | JSON avec `msg_id`, `instance_id`, `direction="out"`, `kind`, `payload`, `created_at` |
| 7 — DELETE session | 204 |

## Nettoyage

WS et session fermés à l'étape 7. Fichiers temporaires `WS_OUT`/`WS_LOG`
supprimés.

## Notes

- Le test utilise `wscat` en sortie texte ; il parse la convention `< {json}` que
  cet outil applique pour les messages reçus. Si vous remplacez `wscat` par un
  autre client (`websocat`, etc.), adapter la regex.
- L'auth WS n'est pas vérifiée par le code actuel (cf. `messages.py:129`). Si
  l'auth est ajoutée en V1.x, passer `?api_key=$API_KEY` en query string.
- Pour aussi tester le **rattrapage post-coupure** (cas du scénario fonctionnel),
  voir le test 09 qui couvre le post-mortem messages.
