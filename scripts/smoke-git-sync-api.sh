#!/usr/bin/env bash
# Smoke test API des 9 endpoints /api/admin/git-sync/*
# À exécuter sur le LXC fresh après run-test.sh
set -euo pipefail

API="${API:-http://192.168.10.170}"
EMAIL="${EMAIL:-admin@agflow.example.com}"
PASS="${PASS:-Y4nU-r5X9p-WM3D8qxSTM9zB}"

GREEN=$'\033[32m'
RED=$'\033[31m'
RESET=$'\033[0m'

pass=0
fail=0

check() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
        echo "${GREEN}[PASS]${RESET} $name (HTTP $actual)"
        pass=$((pass + 1))
    else
        echo "${RED}[FAIL]${RESET} $name (attendu HTTP $expected, reçu $actual)"
        fail=$((fail + 1))
    fi
}

echo "=== 1. Login admin ==="
TOKEN=$(curl -sS -X POST "$API/api/admin/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:30}..."
AUTH="Authorization: Bearer $TOKEN"

echo ""
echo "=== 2. GET /config (pas de config → 404) ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" "$API/api/admin/git-sync/config")
check "GET /config sans config" 404 "$code"

echo ""
echo "=== 3. GET /available-tables → 200 + liste ==="
code=$(curl -sS -o /tmp/tables.json -w '%{http_code}' -H "$AUTH" "$API/api/admin/git-sync/available-tables")
check "GET /available-tables" 200 "$code"
echo "Tables (extrait):"
python3 -c "import json; d=json.load(open('/tmp/tables.json')); print(f'  {len(d)} tables, ex: {d[:5]}')"

echo ""
echo "=== 4. GET /commits sans config → 404 ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" "$API/api/admin/git-sync/commits")
check "GET /commits sans config" 404 "$code"

echo ""
echo "=== 5. POST /test-secret-ref avec ref bidon → 200 + ok=false ==="
code=$(curl -sS -o /tmp/secret.json -w '%{http_code}' -H "$AUTH" -H 'Content-Type: application/json' \
    -X POST "$API/api/admin/git-sync/test-secret-ref" \
    -d '{"auth_secret_ref":"${vault://inexistant:foo/bar}"}')
check "POST /test-secret-ref (ref bidon)" 200 "$code"
echo "Résultat:"
cat /tmp/secret.json | python3 -m json.tool

echo ""
echo "=== 6. POST /export sans config → 404 ==="
code=$(curl -sS -o /tmp/exp.json -w '%{http_code}' -H "$AUTH" -X POST "$API/api/admin/git-sync/export")
check "POST /export sans config" 404 "$code"

echo ""
echo "=== 7. POST /preview-import sans config → 404 ==="
code=$(curl -sS -o /tmp/prev.json -w '%{http_code}' -H "$AUTH" -X POST "$API/api/admin/git-sync/preview-import")
check "POST /preview-import sans config" 404 "$code"

echo ""
echo "=== 8. PUT /config (création) → 200 ==="
code=$(curl -sS -o /tmp/put.json -w '%{http_code}' -H "$AUTH" -H 'Content-Type: application/json' \
    -X PUT "$API/api/admin/git-sync/config" \
    -d '{"repo_url":"https://github.com/owner/repo","branch":"main","auth_mode":"pat_https","auth_secret_ref":"${vault://default:gitsync/pat}","author_name":"agflow bot","author_email":"bot@agflow.local","selected_tables":["users","ai_providers"],"excluded_columns":{},"schedule_enabled":false,"schedule_cron":null}')
check "PUT /config (création)" 200 "$code"
echo "Config:"
cat /tmp/put.json | python3 -m json.tool

echo ""
echo "=== 9. GET /config (après création) → 200 ==="
code=$(curl -sS -o /tmp/cfg.json -w '%{http_code}' -H "$AUTH" "$API/api/admin/git-sync/config")
check "GET /config après création" 200 "$code"

echo ""
echo "=== 10. GET /commits (config présente mais repo inexistant) → 502/500 attendu ==="
code=$(curl -sS -o /tmp/com.json -w '%{http_code}' -H "$AUTH" "$API/api/admin/git-sync/commits")
echo "  Code reçu: $code (repo bidon → erreur attendue)"

echo ""
echo "=== 11. DELETE /config → 204 ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" -X DELETE "$API/api/admin/git-sync/config")
check "DELETE /config" 204 "$code"

echo ""
echo "=== 12. GET /config (après suppression) → 404 ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" "$API/api/admin/git-sync/config")
check "GET /config après suppression" 404 "$code"

echo ""
echo "========================================="
echo "  RÉSUMÉ"
echo "  PASS : $pass"
echo "  FAIL : $fail"
echo "========================================="

[[ $fail -eq 0 ]]
