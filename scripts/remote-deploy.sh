#!/usr/bin/env bash
###############################################################################
# remote-deploy.sh — Build + démarrage sur la machine de test, logs initiaux
#
# 1. SSH sur REMOTE_HOST
# 2. docker compose build  (dans REMOTE_DIR)
# 3. docker compose up -d
# 4. Affiche les logs des premiers LOG_LINES lignes pour vérifier le boot
#
# Configuration : copier scripts/.env.remote-deploy.example
#                 vers    scripts/.env.remote-deploy et remplir les valeurs.
###############################################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.remote-deploy"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE introuvable."
    echo "       Copier scripts/.env.remote-deploy.example → scripts/.env.remote-deploy"
    exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

: "${REMOTE_HOST:?REMOTE_HOST requis dans $ENV_FILE}"
: "${REMOTE_USER:?REMOTE_USER requis dans $ENV_FILE}"

REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/opt/agflow.docker}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.dev.yml}"
LOG_LINES="${LOG_LINES:-80}"

SSH_OPTS=(
    -o StrictHostKeyChecking=no
    -o BatchMode=no
    -p "$REMOTE_PORT"
)

if [ -n "${REMOTE_KEY:-}" ]; then
    [ -f "$REMOTE_KEY" ] || { echo "ERROR: clé SSH introuvable : $REMOTE_KEY"; exit 1; }
    SSH_OPTS+=(-i "$REMOTE_KEY")
    SSH_BIN="ssh"
elif [ -n "${REMOTE_PASSWORD:-}" ]; then
    command -v sshpass &>/dev/null || {
        echo "ERROR: sshpass requis pour l'auth par mot de passe."
        echo "       apt-get install sshpass  ou  brew install hudochenkov/sshpass/sshpass"
        exit 1
    }
    export SSHPASS="$REMOTE_PASSWORD"
    SSH_BIN="sshpass -e ssh"
else
    echo "ERROR: REMOTE_KEY ou REMOTE_PASSWORD doit être défini dans $ENV_FILE"
    exit 1
fi

echo "==> ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}  —  ${REMOTE_DIR}"
echo ""

# shellcheck disable=SC2086
$SSH_BIN "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" bash <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"

echo "--- Build des images ---"
docker compose -f ${COMPOSE_FILE} build

echo ""
echo "--- Démarrage de la stack ---"
docker compose -f ${COMPOSE_FILE} up -d

echo ""
echo "--- État des services ---"
docker compose -f ${COMPOSE_FILE} ps

echo ""
echo "--- Premiers logs (${LOG_LINES} lignes) ---"
sleep 3
docker compose -f ${COMPOSE_FILE} logs --tail=${LOG_LINES} --no-color
REMOTE
