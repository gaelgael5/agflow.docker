#!/usr/bin/env bash
# 00-test-data.sh — Helpers et données de référence pour les tests fonctionnels
#
# Source ce fichier depuis n'importe quel test :
#   source "$(dirname "$0")/00-test-data.sh"
#
# Ou en standalone pour valider l'environnement :
#   bash 00-test-data.sh check
#   bash 00-test-data.sh jwt          # imprime ADMIN_JWT
#   bash 00-test-data.sh cleanup      # purge les sessions de test
#
# Voir 00-test-data.md pour la documentation complète.

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# 1. Variables d'environnement requises
# ─────────────────────────────────────────────────────────────────────────────

# Variables toujours requises
: "${BASE_URL:?BASE_URL must be set (ex: https://docker-agflow-staging.yoops.org)}"

# WS_URL est dérivé de BASE_URL si non explicitement défini
if [[ -z "${WS_URL:-}" ]]; then
  if [[ "$BASE_URL" == https://* ]]; then
    WS_URL="${BASE_URL/https:/wss:}"
  elif [[ "$BASE_URL" == http://* ]]; then
    WS_URL="${BASE_URL/http:/ws:}"
  else
    echo "ERROR: BASE_URL doit commencer par http:// ou https:// (got: $BASE_URL)" >&2
    exit 1
  fi
  export WS_URL
fi

# Strip trailing slash
BASE_URL="${BASE_URL%/}"
WS_URL="${WS_URL%/}"
export BASE_URL WS_URL

# ─────────────────────────────────────────────────────────────────────────────
# 2. Outils requis
# ─────────────────────────────────────────────────────────────────────────────

_require_cli() {
  local missing=()
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: outils manquants : ${missing[*]}" >&2
    echo "  - jq      : https://stedolan.github.io/jq/download/" >&2
    echo "  - curl    : (devrait être présent par défaut)" >&2
    echo "  - wscat   : npm install -g wscat" >&2
    return 1
  fi
}

# Tous les tests ont besoin de curl + jq ; wscat seulement pour 05 et 09.
# La vérification est différée si on est en mode CLI 'help' pour permettre
# d'afficher l'aide sur une machine sans jq installé.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]] || [[ "${1:-}" != "help" && "${1:-}" != "--help" && "${1:-}" != "-h" ]]; then
  _require_cli curl jq
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Helpers HTTP
# ─────────────────────────────────────────────────────────────────────────────

# Headers prêts à l'emploi (tableaux à étendre dans les commandes curl)
H_JSON=(-H "Content-Type: application/json")

# Header d'authentification pour les tests applicatifs (01-09)
# Usage : curl -fsS "${H_AUTH[@]}" "$BASE_URL/api/v1/..."
if [[ -n "${API_KEY:-}" ]]; then
  H_AUTH=(-H "Authorization: Bearer $API_KEY")
  export API_KEY
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Bootstrap admin JWT (pour A01-A03)
# ─────────────────────────────────────────────────────────────────────────────

get_admin_jwt() {
  : "${ADMIN_EMAIL:?ADMIN_EMAIL must be set for admin operations}"
  : "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set for admin operations}"

  local response
  response=$(curl -fsS -X POST "$BASE_URL/api/admin/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}")

  local jwt
  jwt=$(echo "$response" | jq -r '.access_token')
  if [[ -z "$jwt" || "$jwt" == "null" ]]; then
    echo "ERROR: login admin a échoué (réponse: $response)" >&2
    return 1
  fi
  echo "$jwt"
}

# Charge ADMIN_JWT dans l'env si non défini
ensure_admin_jwt() {
  if [[ -z "${ADMIN_JWT:-}" ]]; then
    ADMIN_JWT=$(get_admin_jwt) || return 1
    export ADMIN_JWT
  fi
  H_ADMIN=(-H "Authorization: Bearer $ADMIN_JWT")
}

# ─────────────────────────────────────────────────────────────────────────────
# 5. Vérification de l'état de la plateforme
# ─────────────────────────────────────────────────────────────────────────────

# Renvoie 0 si l'API publique répond, 1 sinon
check_platform_up() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/health" || echo "000")
  if [[ "$code" == "200" ]]; then
    return 0
  fi
  echo "ERROR: $BASE_URL/health a renvoyé HTTP $code" >&2
  return 1
}

# Renvoie 0 si la clé API est utilisable, 1 sinon
check_api_key() {
  : "${API_KEY:?API_KEY must be set}"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
    -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/agents")
  if [[ "$code" == "200" ]]; then
    return 0
  fi
  echo "ERROR: API_KEY refusée (HTTP $code sur GET /api/v1/agents)" >&2
  return 1
}

# Renvoie 0 si l'agent attendu est instanciable (pas d'erreurs, image up_to_date)
# Usage : check_agent_ready [slug]   (default: claude-code)
check_agent_ready() {
  : "${API_KEY:?API_KEY must be set}"
  local slug="${1:-${AGENT_SLUG:-claude-code}}"
  local detail
  detail=$(curl -fsS -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/v1/agents" \
    | jq --arg slug "$slug" '.[] | select(.slug == $slug)')
  if [[ -z "$detail" || "$detail" == "null" ]]; then
    echo "ERROR: agent '$slug' absent du catalogue" >&2
    return 1
  fi
  local has_errors image_status
  has_errors=$(echo "$detail" | jq -r '.has_errors // false')
  image_status=$(echo "$detail" | jq -r '.image_status // "?"')
  if [[ "$has_errors" == "true" ]]; then
    echo "ERROR: agent '$slug' a des erreurs (has_errors=true)" >&2
    return 1
  fi
  if [[ "$image_status" != "up_to_date" ]]; then
    echo "WARN: agent '$slug' image_status=$image_status (attendu: up_to_date)" >&2
  fi
  return 0
}

# ─────────────────────────────────────────────────────────────────────────────
# 6. Utilitaires de polling
# ─────────────────────────────────────────────────────────────────────────────

# wait_for_messages_out <session_id> <instance_id> <timeout_s> [min_count]
# Attend qu'au moins min_count message(s) direction=out apparaisse(nt) sur l'instance.
# Renvoie 0 si trouvé avant timeout, 1 sinon.
wait_for_messages_out() {
  local sid="$1" iid="$2" timeout="${3:-60}" min="${4:-1}"
  local elapsed=0 interval=2 count=0
  while (( elapsed < timeout )); do
    count=$(curl -fsS -H "Authorization: Bearer $API_KEY" \
      "$BASE_URL/api/v1/sessions/$sid/agents/$iid/messages?direction=out&limit=20" \
      | jq 'length')
    if (( count >= min )); then
      return 0
    fi
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done
  echo "ERROR: timeout après ${timeout}s — $count message(s) reçu(s), attendu $min" >&2
  return 1
}

# ─────────────────────────────────────────────────────────────────────────────
# 7. Nettoyage
# ─────────────────────────────────────────────────────────────────────────────

# close_session <session_id>  — best effort, ne fail pas
close_session() {
  local sid="$1"
  [[ -z "$sid" || "$sid" == "null" ]] && return 0
  curl -s -o /dev/null -X DELETE \
    -H "Authorization: Bearer ${API_KEY:?}" \
    "$BASE_URL/api/v1/sessions/$sid" || true
}

# cleanup_test_sessions  — purge toutes les sessions ouvertes par les tests
# (utilise un fichier de tracking si présent, sinon best-effort)
cleanup_test_sessions() {
  local tracking="${SESSION_TRACKING_FILE:-/tmp/agflow-test-sessions.txt}"
  if [[ -f "$tracking" ]]; then
    while IFS= read -r sid; do
      [[ -n "$sid" ]] && close_session "$sid"
    done < "$tracking"
    rm -f "$tracking"
    echo "  $(wc -l < "$tracking" 2>/dev/null || echo 0) session(s) purgée(s)"
  else
    echo "  pas de fichier de tracking trouvé — rien à nettoyer"
    echo "  (les sessions s'auto-fermeront via le timeout idle ~2 min)"
  fi
}

# track_session <session_id>  — ajoute un SID au fichier de tracking pour cleanup ultérieur
track_session() {
  local sid="$1"
  [[ -z "$sid" ]] && return 0
  echo "$sid" >> "${SESSION_TRACKING_FILE:-/tmp/agflow-test-sessions.txt}"
}

# ─────────────────────────────────────────────────────────────────────────────
# 8. Mode CLI : bash 00-test-data.sh <commande>
# ─────────────────────────────────────────────────────────────────────────────

# Si le script est exécuté directement (pas sourcé), exposer les commandes
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  cmd="${1:-help}"
  case "$cmd" in
    check)
      echo "==> Vérification de l'environnement"
      echo "    BASE_URL=$BASE_URL"
      echo "    WS_URL=$WS_URL"
      echo "    API_KEY=${API_KEY:+(défini, ${#API_KEY} chars)}${API_KEY:-(non défini)}"
      echo
      echo "==> Health platform"
      check_platform_up && echo "    OK" || exit 1
      echo
      if [[ -n "${API_KEY:-}" ]]; then
        echo "==> API_KEY"
        check_api_key && echo "    OK" || exit 1
        echo
        echo "==> Agent ${AGENT_SLUG:-claude-code}"
        check_agent_ready && echo "    OK" || exit 1
      else
        echo "==> API_KEY non défini — checks API publique skippés"
      fi
      echo
      echo "PASS — environnement prêt"
      ;;
    jwt)
      get_admin_jwt
      ;;
    cleanup)
      echo "==> Cleanup sessions de test"
      cleanup_test_sessions
      ;;
    help|--help|-h|*)
      cat <<EOF
Usage: bash 00-test-data.sh <commande>

Commandes :
  check     Valide l'environnement (BASE_URL, API_KEY, agent ready)
  jwt       Imprime un JWT admin (nécessite ADMIN_EMAIL + ADMIN_PASSWORD)
  cleanup   Purge les sessions trackées par les tests
  help      Affiche cette aide

Variables d'environnement :
  BASE_URL          URL de l'env de test (requis)
  WS_URL            URL WebSocket (auto-dérivé si absent)
  API_KEY           Clé API publique (requis pour 01-09)
  ADMIN_EMAIL       Email admin (requis pour A01-A03 et jwt)
  ADMIN_PASSWORD    Password admin (id.)
  ADMIN_JWT         JWT admin (auto-généré si absent via ensure_admin_jwt)
  AGENT_SLUG        Slug d'agent à utiliser (default: claude-code)
  PROJECT_UUID      UUID projet (sortie de A03, requis pour test 04)

Pour utiliser dans un test :
  source 00-test-data.sh
  ensure_admin_jwt          # si test admin
  check_platform_up || exit 1

Documentation complète : 00-test-data.md
EOF
      ;;
  esac
fi
