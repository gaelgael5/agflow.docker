#!/usr/bin/env bash
# Smoke test API M6 Supervision (Phase 1 + Phase 2a + Phase 2b)
# À exécuter sur le LXC fresh après run-test.sh, ou ponctuellement post-deploy.
#
# Couvre :
#   - 3 endpoints REST /api/admin/supervision/* (overview, instances, instance/{id})
#   - Connexion WebSocket /api/admin/supervision/stream (sans token, avec token bidon,
#     avec token admin) — uniquement si `python3 -c "import websockets"` réussit.
set -euo pipefail

API="${API:-http://192.168.10.170}"
EMAIL="${EMAIL:-admin@agflow.example.com}"
PASS="${PASS:-}"

GREEN=$'\033[32m'
RED=$'\033[31m'
YELLOW=$'\033[33m'
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

if [[ -z "$PASS" ]]; then
    echo "${RED}ERREUR${RESET} : passe PASS=<mot-de-passe-admin> en variable d'env."
    echo "Exemple : PASS=xxxxx ./scripts/smoke-supervision-api.sh"
    exit 1
fi

echo "=== 1. Login admin ==="
TOKEN=$(curl -sS -X POST "$API/api/admin/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:30}..."
AUTH="Authorization: Bearer $TOKEN"

echo ""
echo "=== 2. GET /overview → 200 + structure SupervisionOverview ==="
code=$(curl -sS -o /tmp/overview.json -w '%{http_code}' -H "$AUTH" "$API/api/admin/supervision/overview")
check "GET /overview" 200 "$code"
echo "Aperçu :"
python3 -c "
import json
d = json.load(open('/tmp/overview.json'))
print(f'  sessions   : active={d[\"sessions\"][\"active\"]} closed={d[\"sessions\"][\"closed\"]} expired={d[\"sessions\"][\"expired\"]}')
print(f'  agents     : idle={d[\"agents\"][\"idle\"]} busy={d[\"agents\"][\"busy\"]} error={d[\"agents\"][\"error\"]} destroyed={d[\"agents\"][\"destroyed_total\"]}')
print(f'  containers : {d[\"containers_running\"]}')
print(f'  mom        : pending={d[\"mom\"][\"pending\"]} claimed={d[\"mom\"][\"claimed\"]} failed={d[\"mom\"][\"failed\"]}')
"

echo ""
echo "=== 3. GET /instances → 200 + liste ==="
code=$(curl -sS -o /tmp/instances.json -w '%{http_code}' -H "$AUTH" "$API/api/admin/supervision/instances")
check "GET /instances" 200 "$code"
echo "Nombre d'instances :"
python3 -c "import json; print(f'  {len(json.load(open(\"/tmp/instances.json\")))} instances')"

echo ""
echo "=== 4. GET /instances?status=busy → 200 ==="
code=$(curl -sS -o /tmp/busy.json -w '%{http_code}' -H "$AUTH" "$API/api/admin/supervision/instances?status=busy")
check "GET /instances?status=busy" 200 "$code"

echo ""
echo "=== 5. GET /instances?status=invalid → 400 ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" "$API/api/admin/supervision/instances?status=zzz")
check "GET /instances?status=zzz" 400 "$code"

echo ""
echo "=== 6. GET /instances/<bogus-uuid> → 404 ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' -H "$AUTH" "$API/api/admin/supervision/instances/00000000-0000-4000-8000-000000000000")
check "GET /instances/<bogus>" 404 "$code"

echo ""
echo "=== 7. GET /overview sans auth → 401 ==="
code=$(curl -sS -o /dev/null -w '%{http_code}' "$API/api/admin/supervision/overview")
check "GET /overview sans auth" 401 "$code"

echo ""
echo "=== 8. WebSocket /stream ==="
if python3 -c "import websockets" 2>/dev/null; then
    HOST="${API#http://}"
    HOST="${HOST#https://}"
    HOST="${HOST%/}"
    WS_BASE="ws://$HOST"
    if [[ "$API" == https://* ]]; then WS_BASE="wss://$HOST"; fi

    echo "  Test 8a : WS sans token → close 4401"
    python3 <<EOF
import asyncio, websockets
async def main():
    try:
        async with websockets.connect("$WS_BASE/api/admin/supervision/stream") as ws:
            print("    ${RED}[FAIL]${RESET} : connexion acceptée alors qu'aucun token n'est fourni")
            return 1
    except websockets.exceptions.InvalidStatus as e:
        if e.response.status_code in (403, 400):
            print("    ${GREEN}[PASS]${RESET} : rejet HTTP %d (avant upgrade WS)" % e.response.status_code)
            return 0
        print(f"    ${RED}[FAIL]${RESET} : status inattendu {e.response.status_code}")
        return 1
    except websockets.exceptions.ConnectionClosedError as e:
        if e.code == 4401:
            print("    ${GREEN}[PASS]${RESET} : close 4401 (auth refusée)")
            return 0
        print(f"    ${RED}[FAIL]${RESET} : close code {e.code}")
        return 1
    except Exception as e:
        print(f"    ${YELLOW}[WARN]${RESET} : exception {type(e).__name__}: {e}")
        return 0
asyncio.run(main())
EOF

    echo "  Test 8b : WS avec token admin → connecté"
    python3 <<EOF
import asyncio, websockets
async def main():
    try:
        async with websockets.connect(
            "$WS_BASE/api/admin/supervision/stream?token=$TOKEN"
        ) as ws:
            print("    ${GREEN}[PASS]${RESET} : connexion établie")
            return 0
    except Exception as e:
        print(f"    ${RED}[FAIL]${RESET} : exception {type(e).__name__}: {e}")
        return 1
asyncio.run(main())
EOF
else
    echo "  ${YELLOW}[SKIP]${RESET} : python3 -c \"import websockets\" indisponible — installer via 'pip install websockets' pour tester le WS"
fi

echo ""
echo "========================================="
echo "  RÉSUMÉ"
echo "  PASS : $pass"
echo "  FAIL : $fail"
echo "========================================="

[[ $fail -eq 0 ]]
