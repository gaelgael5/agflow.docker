#!/usr/bin/env bash
# Smoke test contract v5 — séquence happy path complète.
#
# Lance contre n'importe quelle implémentation Docker du contrat v5
# (mock fourni dans docs/contracts/mock-docker/, ou la vraie agflow.docker
# une fois implémentée).
#
# Vérifie chaque endpoint contre le contrat (statut HTTP + structure JSON).
#
# Pré-requis :
#   - curl, jq, python3 (pour générer des UUID)
#   - mock-docker tourne sur DOCKER_BASE
#   - hook_receiver tourne sur HOOK_BASE (sinon les hooks partent dans le vide)
#
# Variables d'env :
#   DOCKER_BASE     URL du Docker service (default: http://localhost:8080)
#   DOCKER_API_KEY  Clé API (default: agfd_test_key_12345)
#   HOOK_BASE       URL où le hook arrive (default: http://localhost:9090)
#   HMAC_KEY_ID     Identifiant logique de la clé HMAC (default: v1)

set -euo pipefail

DOCKER_BASE="${DOCKER_BASE:-http://localhost:8080}"
DOCKER_API_KEY="${DOCKER_API_KEY:-agfd_test_key_12345}"
HOOK_BASE="${HOOK_BASE:-http://localhost:9090}"
HMAC_KEY_ID="${HMAC_KEY_ID:-v1}"

# Project template fixe défini dans le mock — peut être remplacé.
PROJECT_ID="${PROJECT_ID:-11111111-1111-4111-a111-111111111111}"

H_AUTH=(-H "Authorization: Bearer $DOCKER_API_KEY")
H_JSON=(-H "Content-Type: application/json")

ok()   { echo -e "  \033[32m✓\033[0m $*"; }
fail() { echo -e "  \033[31m✗\033[0m $*"; exit 1; }
step() { echo; echo -e "\033[34m── $*\033[0m"; }

new_uuid() {
  # Portabilité : Linux, macOS, Windows mingw, CI.
  # On valide le format de sortie pour éviter les stubs Windows qui exit 0 vide.
  local out=""
  if [[ -r /proc/sys/kernel/random/uuid ]]; then
    out=$(cat /proc/sys/kernel/random/uuid)
  elif command -v uuidgen >/dev/null 2>&1; then
    out=$(uuidgen | tr 'A-Z' 'a-z')
  fi
  if [[ ! "$out" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    if command -v python3 >/dev/null 2>&1; then
      out=$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)
    fi
  fi
  if [[ ! "$out" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    if command -v python >/dev/null 2>&1; then
      out=$(python -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)
    fi
  fi
  if [[ ! "$out" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    if command -v uv >/dev/null 2>&1; then
      out=$(uv run --quiet python -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)
    fi
  fi
  if [[ ! "$out" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    echo "ERROR: no working UUID generator (install uuidgen or a working python)" >&2
    exit 1
  fi
  echo "$out"
}

# Validation UUID v4 strict
assert_uuid() {
  local val="$1" field="$2"
  [[ "$val" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]] \
    || fail "$field='$val' n'est pas un UUID v4"
}

# ── Health ───────────────────────────────────────────────────────────────────
step "1. Health check"
HEALTH=$(curl -fsS --max-time 5 "$DOCKER_BASE/health")
echo "$HEALTH" | jq -e '.status == "ok"' >/dev/null \
  || fail "health KO : $HEALTH"
ok "health OK"

# ── 2. Auth manquante = 401 ──────────────────────────────────────────────────
step "2. Auth check (sans Bearer = 401)"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$DOCKER_BASE/api/admin/projects")
[[ "$HTTP" == "401" ]] || fail "attendu 401 sans auth, reçu $HTTP"
ok "auth obligatoire : 401 sans Bearer"

# ── 3. GET /projects ─────────────────────────────────────────────────────────
step "3. GET /api/admin/projects (catalogue)"
RESP=$(curl -fsS "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/projects")
COUNT=$(echo "$RESP" | jq '.projects | length')
[[ "$COUNT" -ge 1 ]] || fail "catalogue vide"
echo "$RESP" | jq -e '.projects[0] | (.project_id and .name)' >/dev/null \
  || fail "structure projets KO"
ok "$COUNT projet(s) au catalogue"

# ── 4. GET /projects/{id} ────────────────────────────────────────────────────
step "4. GET /api/admin/projects/$PROJECT_ID (détail)"
RESP=$(curl -fsS "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/projects/$PROJECT_ID")
echo "$RESP" | jq -e '.project_id and .name and (.resources | type == "array")' >/dev/null \
  || fail "structure détail projet KO"
RES_COUNT=$(echo "$RESP" | jq '.resources | length')
ok "détail projet OK ($RES_COUNT resource(s) déclarée(s))"

# ── 5. POST /projects/{id}/runtimes (async 202) ──────────────────────────────
step "5. POST /api/admin/projects/$PROJECT_ID/runtimes (async)"
HTTP_CODE=$(curl -s -o /tmp/_rt.json -w "%{http_code}" \
  -X POST "$DOCKER_BASE/api/admin/projects/$PROJECT_ID/runtimes" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"name":"smoke-test-runtime","metadata":{"test":"smoke"}}')
[[ "$HTTP_CODE" == "202" ]] || fail "attendu 202, reçu $HTTP_CODE"
RT=$(cat /tmp/_rt.json)
RT_ID=$(echo "$RT" | jq -r '.docker_project_runtime_id')
RT_TASK=$(echo "$RT" | jq -r '.task_id')
RT_STATUS=$(echo "$RT" | jq -r '.status')
assert_uuid "$RT_ID" "docker_project_runtime_id"
assert_uuid "$RT_TASK" "task_id"
[[ "$RT_STATUS" == "provisioning" ]] || fail "status attendu provisioning, reçu $RT_STATUS"
ok "runtime $RT_ID en cours de provisioning (task=$RT_TASK)"

# ── 6. GET /project-runtimes/{id}/resources (polling) ────────────────────────
step "6. Polling GET /project-runtimes/$RT_ID/resources jusqu'à ready (max 30s)"
for i in $(seq 1 30); do
  RESP=$(curl -fsS "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/project-runtimes/$RT_ID/resources")
  STATUS=$(echo "$RESP" | jq -r '.status')
  echo "    iter $i : status=$STATUS"
  [[ "$STATUS" == "ready" ]] && break
  [[ "$STATUS" == "failed" ]] && fail "provisioning failed"
  sleep 1
done
[[ "$STATUS" == "ready" ]] || fail "provisioning n'a pas atteint ready en 30s"
RES_COUNT=$(echo "$RESP" | jq '.resources | length')
ok "$RES_COUNT resource(s) ready"

# Vérification structure d'une resource
echo "$RESP" | jq -e '.resources[0] | (.resource_id and .type and .status
  and (.connection_params | type == "object")
  and (.mcp_bindings | type == "array")
  and (.setup_steps | type == "array"))' >/dev/null \
  || fail "structure resource invalide"
FIRST_RES_ID=$(echo "$RESP" | jq -r '.resources[0].resource_id')
assert_uuid "$FIRST_RES_ID" "resource_id"
ok "structure resource conforme au contrat"

# ── 7. POST /sessions avec callback HMAC ─────────────────────────────────────
step "7. POST /api/admin/sessions (avec project_runtime_id + callback)"
HTTP_CODE=$(curl -s -o /tmp/_se.json -w "%{http_code}" \
  -X POST "$DOCKER_BASE/api/admin/sessions" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{
    \"project_runtime_id\": \"$RT_ID\",
    \"callback_url\": \"$HOOK_BASE\",
    \"callback_hmac_key_id\": \"$HMAC_KEY_ID\",
    \"name\": \"smoke phase\",
    \"duration_seconds\": 600
  }")
[[ "$HTTP_CODE" == "201" ]] || fail "attendu 201, reçu $HTTP_CODE"
SE=$(cat /tmp/_se.json)
SE_ID=$(echo "$SE" | jq -r '.session_id')
assert_uuid "$SE_ID" "session_id"
echo "$SE" | jq -e --arg rt "$RT_ID" '.project_runtime_id == $rt and .status == "active"' >/dev/null \
  || fail "session ne référence pas le runtime ou status pas active"
ok "session $SE_ID active liée au runtime"

# ── 8. POST /sessions/{sid}/agents avec injection MCP ────────────────────────
step "8. POST /api/admin/sessions/$SE_ID/agents (injection MCP attendue)"
HTTP_CODE=$(curl -s -o /tmp/_ag.json -w "%{http_code}" \
  -X POST "$DOCKER_BASE/api/admin/sessions/$SE_ID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"slug":"architect-v1","mission":"smoke test"}')
[[ "$HTTP_CODE" == "201" ]] || fail "attendu 201, reçu $HTTP_CODE"
AG=$(cat /tmp/_ag.json)
AG_ID=$(echo "$AG" | jq -r '.agent_uuid')
assert_uuid "$AG_ID" "agent_uuid"
INJECTED_COUNT=$(echo "$AG" | jq '.mcp_bindings_injected | length')
[[ "$INJECTED_COUNT" -ge 1 ]] \
  || fail "aucun MCP injecté (attendu : au moins 1 depuis les resources du runtime)"
echo "$AG" | jq -e '.mcp_bindings_injected[0] | (.name and .from_resource_id)' >/dev/null \
  || fail "structure mcp_bindings_injected invalide"
ok "agent $AG_ID instancié, $INJECTED_COUNT MCP injecté(s)"

# ── 9. POST /work avec UUID v4 stricts ───────────────────────────────────────
step "9. POST /api/admin/sessions/$SE_ID/agents/$AG_ID/work (async)"
ACTION_EXEC_ID=$(new_uuid)
CORRELATION_ID=$(new_uuid)
HTTP_CODE=$(curl -s -o /tmp/_wk.json -w "%{http_code}" \
  -X POST "$DOCKER_BASE/api/admin/sessions/$SE_ID/agents/$AG_ID/work" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d "{
    \"instruction\": {
      \"_agflow_action_execution_id\": \"$ACTION_EXEC_ID\",
      \"_agflow_correlation_id\": \"$CORRELATION_ID\",
      \"title\": \"Smoke architecture\",
      \"prompt\": \"You are a software architect. Reply in 3 lines.\"
    }
  }")
[[ "$HTTP_CODE" == "202" ]] || fail "attendu 202, reçu $HTTP_CODE"
WORK=$(cat /tmp/_wk.json)
TASK_ID=$(echo "$WORK" | jq -r '.task_id')
assert_uuid "$TASK_ID" "task_id"
ok "work soumis, task_id=$TASK_ID (hook attendu sur $HOOK_BASE)"

# ── 10. POST /work avec _agflow_correlation_id non-UUID = 400 ─────────────────
step "10. Validation UUID stricte sur _agflow_correlation_id"
HTTP_CODE=$(curl -s -o /tmp/_err.json -w "%{http_code}" \
  -X POST "$DOCKER_BASE/api/admin/sessions/$SE_ID/agents/$AG_ID/work" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{
    "instruction": {
      "_agflow_action_execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
      "_agflow_correlation_id": "not-a-uuid",
      "prompt": "test"
    }
  }')
[[ "$HTTP_CODE" == "400" ]] || fail "attendu 400 pour correlation_id invalide, reçu $HTTP_CODE"
ok "validation UUID stricte OK (400 sur format invalide)"

# ── 11. Attendre le hook ──────────────────────────────────────────────────────
step "11. Attente émission du hook (max 10s)"
sleep 5
# Le hook receiver renvoie le compte de hooks reçus dans /health
if curl -fsS --max-time 3 "$HOOK_BASE/health" >/dev/null 2>&1; then
  RECEIVED=$(curl -fsS "$HOOK_BASE/health" | jq -r '.received // "0"')
  [[ "$RECEIVED" -ge 1 ]] && ok "hook receiver a reçu $RECEIVED hook(s)" \
    || fail "hook receiver tourne mais 0 hook reçu"
else
  echo "  ⚠ hook receiver non joignable sur $HOOK_BASE — saut de la vérification réception"
fi

# ── 12. DELETE /sessions/{sid} ───────────────────────────────────────────────
step "12. DELETE /api/admin/sessions/$SE_ID"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X DELETE "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/sessions/$SE_ID")
[[ "$HTTP_CODE" == "204" ]] || fail "attendu 204, reçu $HTTP_CODE"
ok "session fermée"

# ── 13. POST sur session fermée = 409 ─────────────────────────────────────────
step "13. POST sur session fermée = 409"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$DOCKER_BASE/api/admin/sessions/$SE_ID/agents" \
  "${H_AUTH[@]}" "${H_JSON[@]}" \
  -d '{"slug":"architect-v1"}')
[[ "$HTTP_CODE" == "409" ]] || fail "attendu 409 sur session fermée, reçu $HTTP_CODE"
ok "409 sur session fermée"

# ── 14. GET projet inexistant = 404 ───────────────────────────────────────────
step "14. GET projet inexistant = 404"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  "${H_AUTH[@]}" "$DOCKER_BASE/api/admin/projects/00000000-0000-4000-a000-000000000000")
[[ "$HTTP_CODE" == "404" ]] || fail "attendu 404, reçu $HTTP_CODE"
ok "404 sur projet inexistant"

echo
echo -e "\033[32m═══════════════════════════════════════════════════════════════\033[0m"
echo -e "\033[32m  PASS — contrat v5 respecté sur les 14 checks\033[0m"
echo -e "\033[32m═══════════════════════════════════════════════════════════════\033[0m"
