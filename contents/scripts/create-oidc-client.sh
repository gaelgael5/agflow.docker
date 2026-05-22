#!/usr/bin/env bash
#
# create-oidc-client.sh — Crée un client OIDC sur le Keycloak LOCAL via
# kcadm.sh. À exécuter sur la machine qui héberge Keycloak (typiquement le
# LXC, via SSH).
#
# Dépendances : bash, kcadm.sh (livré avec Keycloak dans $KC_HOME/bin/)
# Aucune dépendance externe (pas de curl, pas de jq).
#
# Variables d'environnement :
#   KC_ADMIN             Utilisateur admin master (défaut: admin)
#   KC_ADMIN_PASSWORD    Mot de passe admin (OBLIGATOIRE)
#   KC_SERVER_URL        URL locale du serveur (défaut: http://127.0.0.1:8080)
#   KC_HOME              Racine de l'install Keycloak (défaut: /opt/keycloak)
#
# Exemples :
#   export KC_ADMIN_PASSWORD='xxx'
#
#   # Backend confidential (cas par défaut)
#   ./create-oidc-client.sh --realm yoops --client-id mon-app \
#     --redirect-uri 'https://app.example.org/oauth2/callback'
#
#   # SPA public (PKCE auto)
#   ./create-oidc-client.sh --realm yoops --client-id mon-spa --type public \
#     --redirect-uri 'https://app.example.org/*'
#
#   # API bearer-only
#   ./create-oidc-client.sh --realm yoops --client-id mon-api --type bearer-only
#
#   # Service account M2M
#   ./create-oidc-client.sh --realm yoops --client-id mon-worker --type service-account
#
# Output (stdout, dernière instruction) :
#   {"clientId":"mon-app","clientSecret":"abc123-..."}
#   clientSecret = null pour public et bearer-only.
#
# Logs / erreurs : stderr. Exit codes : 0 OK, 1 usage, 2 erreur Keycloak.

set -euo pipefail

# ----- Globals ---------------------------------------------------------------

KC_HOME="${KC_HOME:-/opt/keycloak}"
KCADM="${KC_HOME}/bin/kcadm.sh"
KC_SERVER_URL="${KC_SERVER_URL:-http://127.0.0.1:8080}"
KC_ADMIN="${KC_ADMIN:-admin}"

ARG_REALM=""
ARG_CLIENT_ID=""
ARG_TYPE="confidential"
ARG_REDIRECT_URIS=()

# ----- Logging ---------------------------------------------------------------

log() { printf '==> %s\n' "$*" >&2; }
err() { printf 'ERR: %s\n' "$*" >&2; }

# ----- Usage -----------------------------------------------------------------

usage() {
  cat >&2 <<EOF
Usage:
  $(basename "$0") --realm <name> --client-id <id> [--type <type>] [--redirect-uri <uri>]...

Obligatoire :
  --realm <name>       Realm cible
  --client-id <id>     clientId du nouveau client (alphanum + . _ -)

Optionnel :
  --type <type>        public | confidential | bearer-only | service-account
                       (défaut: confidential)
  --redirect-uri <uri> Répétable. Requis pour public/confidential, refusé sinon.
  -h, --help           Cette aide

Variables d'environnement :
  KC_ADMIN_PASSWORD    OBLIGATOIRE
  KC_ADMIN             Utilisateur admin (défaut: admin)
  KC_SERVER_URL        URL Keycloak (défaut: http://127.0.0.1:8080)
  KC_HOME              Racine Keycloak (défaut: /opt/keycloak)

Output stdout (dernière instruction) :
  {"clientId":"...","clientSecret":"..." | null}
EOF
}

# ----- Arg parsing -----------------------------------------------------------

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --realm)         ARG_REALM="$2";      shift 2 ;;
      --client-id)     ARG_CLIENT_ID="$2";  shift 2 ;;
      --type)          ARG_TYPE="$2";       shift 2 ;;
      --redirect-uri)  ARG_REDIRECT_URIS+=("$2"); shift 2 ;;
      -h|--help)       usage; exit 0 ;;
      *)               err "argument inconnu : $1"; usage; exit 1 ;;
    esac
  done
}

# ----- Validation ------------------------------------------------------------

validate_args() {
  [[ -n "$ARG_REALM" ]]     || { err "--realm est requis"; return 1; }
  [[ -n "$ARG_CLIENT_ID" ]] || { err "--client-id est requis"; return 1; }

  # clientId restreint à un jeu sûr (évite tout problème d'échappement JSON
  # dans le payload final).
  [[ "$ARG_CLIENT_ID" =~ ^[A-Za-z0-9._-]+$ ]] || {
    err "--client-id contient des caractères non autorisés : $ARG_CLIENT_ID"
    err "autorisé : [A-Za-z0-9._-]"
    return 1
  }

  case "$ARG_TYPE" in
    public|confidential|bearer-only|service-account) ;;
    *) err "--type invalide : $ARG_TYPE"
       err "attendu : public | confidential | bearer-only | service-account"
       return 1 ;;
  esac

  [[ -n "${KC_ADMIN_PASSWORD:-}" ]] || {
    err "variable d'environnement KC_ADMIN_PASSWORD non définie"
    err "exemple : export KC_ADMIN_PASSWORD='...'"
    return 1
  }

  [[ -x "$KCADM" ]] || {
    err "kcadm.sh introuvable ou non exécutable : $KCADM"
    err "définis KC_HOME si Keycloak est installé ailleurs (export KC_HOME=...)"
    return 1
  }

  case "$ARG_TYPE" in
    public|confidential)
      [[ "${#ARG_REDIRECT_URIS[@]}" -gt 0 ]] || {
        err "au moins un --redirect-uri est requis pour --type=$ARG_TYPE"
        return 1
      }
      ;;
    bearer-only|service-account)
      [[ "${#ARG_REDIRECT_URIS[@]}" -eq 0 ]] || {
        err "--redirect-uri n'est pas valide pour --type=$ARG_TYPE"
        return 1
      }
      ;;
  esac

  # Validation des redirect URIs (jeu sûr pour insertion JSON sans échappement).
  local uri uri_regex='^[A-Za-z0-9._:/?=&*+%~#@-]+$'
  for uri in "${ARG_REDIRECT_URIS[@]}"; do
    [[ "$uri" =~ $uri_regex ]] || {
      err "--redirect-uri contient des caractères non autorisés : $uri"
      return 1
    }
  done
}

# ----- Helpers ---------------------------------------------------------------

# Encode un tableau bash en JSON array de strings.
#   bash_array_to_json_strings "https://a" "https://b"  →  ["https://a","https://b"]
bash_array_to_json_strings() {
  local sep="" out="["
  local item
  for item in "$@"; do
    out+="${sep}\"${item}\""
    sep=","
  done
  out+="]"
  printf '%s' "$out"
}

# Dérive les webOrigins (scheme://host[:port]) depuis les redirectUris,
# dédupliqués, un par ligne.
derive_web_origins() {
  local uri origin
  declare -A seen=()
  for uri in "$@"; do
    if [[ "$uri" =~ ^([a-z]+://[^/]+) ]]; then
      origin="${BASH_REMATCH[1]}"
      if [[ -z "${seen[$origin]:-}" ]]; then
        seen[$origin]=1
        printf '%s\n' "$origin"
      fi
    fi
  done
}

# ----- main ------------------------------------------------------------------

main() {
  if [[ $# -eq 0 ]]; then
    usage
    exit 1
  fi
  case "${1:-}" in
    -h|--help) usage; exit 0 ;;
  esac

  parse_args "$@"
  validate_args || exit 1

  log "[1/4] Authentification kcadm (user=${KC_ADMIN}, server=${KC_SERVER_URL})"
  "$KCADM" config credentials \
    --server "$KC_SERVER_URL" \
    --realm master \
    --user "$KC_ADMIN" \
    --password "$KC_ADMIN_PASSWORD" >&2 || {
      err "auth admin échouée — vérifie KC_ADMIN / KC_ADMIN_PASSWORD"
      exit 2
    }

  log "[2/4] Vérification de non-existence du client '${ARG_CLIENT_ID}' dans realm '${ARG_REALM}'"
  local existing
  existing=$("$KCADM" get clients -r "$ARG_REALM" \
    -q "clientId=$ARG_CLIENT_ID" \
    --fields id --format csv --noquotes 2>/dev/null | tail -n +1 | tr -d '\r' | grep -v '^$' || true)
  if [[ -n "$existing" ]]; then
    err "client '${ARG_CLIENT_ID}' existe déjà dans realm '${ARG_REALM}'"
    exit 1
  fi

  log "[3/4] Création du client (type=${ARG_TYPE})"
  local -a flags=(
    -s "clientId=$ARG_CLIENT_ID"
    -s "protocol=openid-connect"
    -s "enabled=true"
    -s "implicitFlowEnabled=false"
    -s "directAccessGrantsEnabled=false"
  )
  case "$ARG_TYPE" in
    public)
      flags+=(
        -s "publicClient=true"
        -s "standardFlowEnabled=true"
        -s "serviceAccountsEnabled=false"
        -s "bearerOnly=false"
        -s 'attributes."pkce.code.challenge.method"=S256'
      )
      ;;
    confidential)
      flags+=(
        -s "publicClient=false"
        -s "standardFlowEnabled=true"
        -s "serviceAccountsEnabled=false"
        -s "bearerOnly=false"
      )
      ;;
    bearer-only)
      flags+=(
        -s "publicClient=false"
        -s "standardFlowEnabled=false"
        -s "serviceAccountsEnabled=false"
        -s "bearerOnly=true"
      )
      ;;
    service-account)
      flags+=(
        -s "publicClient=false"
        -s "standardFlowEnabled=false"
        -s "serviceAccountsEnabled=true"
        -s "bearerOnly=false"
      )
      ;;
  esac

  if [[ "${#ARG_REDIRECT_URIS[@]}" -gt 0 ]]; then
    flags+=( -s "redirectUris=$(bash_array_to_json_strings "${ARG_REDIRECT_URIS[@]}")" )
    if [[ "$ARG_TYPE" == "public" ]]; then
      local -a origins=()
      while IFS= read -r o; do
        [[ -n "$o" ]] && origins+=("$o")
      done < <(derive_web_origins "${ARG_REDIRECT_URIS[@]}")
      if [[ "${#origins[@]}" -gt 0 ]]; then
        flags+=( -s "webOrigins=$(bash_array_to_json_strings "${origins[@]}")" )
      fi
    fi
  fi

  local uuid
  uuid=$("$KCADM" create clients -r "$ARG_REALM" "${flags[@]}" -i 2>&1) || {
    err "création échouée :"
    err "$uuid"
    exit 2
  }
  uuid=$(printf '%s' "$uuid" | tr -d '\r\n')

  log "[4/4] Récupération du secret (si applicable)"
  local secret_json='null'
  case "$ARG_TYPE" in
    confidential|service-account)
      local secret
      secret=$("$KCADM" get "clients/$uuid/client-secret" -r "$ARG_REALM" \
        --fields value --format csv --noquotes 2>/dev/null \
        | tr -d '\r' | tail -n1)
      [[ -n "$secret" ]] || { err "secret introuvable pour $uuid"; exit 2; }
      # Le secret Keycloak est un UUID, pas d'échappement JSON nécessaire,
      # mais on l'enveloppe en string JSON par sécurité.
      secret_json="\"$secret\""
      ;;
  esac

  # Dernière instruction : un seul objet JSON sur stdout.
  printf '{"clientId":"%s","clientSecret":%s}\n' "$ARG_CLIENT_ID" "$secret_json"
}

main "$@"
