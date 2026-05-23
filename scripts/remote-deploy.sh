#!/usr/bin/env bash
###############################################################################
# remote-deploy.sh — Lance /opt/agflow.docker/dev-deploy.sh sur la machine de test
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

SSH_OPTS=(-o StrictHostKeyChecking=no -p "$REMOTE_PORT")

if [ -n "${REMOTE_KEY:-}" ]; then
    [ -f "$REMOTE_KEY" ] || { echo "ERROR: clé SSH introuvable : $REMOTE_KEY"; exit 1; }
    SSH_OPTS+=(-i "$REMOTE_KEY")
    SSH_BIN="ssh"
elif [ -n "${REMOTE_PASSWORD:-}" ]; then
    command -v sshpass &>/dev/null || {
        echo "ERROR: sshpass requis — apt-get install sshpass"
        exit 1
    }
    export SSHPASS="$REMOTE_PASSWORD"
    SSH_BIN="sshpass -e ssh"
else
    echo "ERROR: REMOTE_KEY ou REMOTE_PASSWORD doit être défini dans $ENV_FILE"
    exit 1
fi

LOG_LINES="${LOG_LINES:-80}"

echo "==> ${REMOTE_USER}@${REMOTE_HOST}"

# shellcheck disable=SC2086
$SSH_BIN "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" bash <<REMOTE
set -euo pipefail
/opt/agflow.docker/dev-deploy.sh

echo ""
echo "--- logs initiaux (${LOG_LINES} lignes) ---"
sleep 3
docker compose -f /opt/agflow.docker/docker-compose.dev.yml logs --tail=${LOG_LINES} --no-color
REMOTE
