#!/usr/bin/env bash
###############################################################################
# remote-deploy.sh — Déploiement sur une machine distante via SSH
#
# Se connecte sur REMOTE_HOST et lance REMOTE_SCRIPT dans REMOTE_DIR.
# Supporte l'auth par clé SSH ou par mot de passe (sshpass requis).
#
# Usage : ./scripts/remote-deploy.sh
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

# Charger les variables sans les exporter dans l'environnement courant
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# Variables obligatoires
: "${REMOTE_HOST:?REMOTE_HOST requis dans $ENV_FILE}"
: "${REMOTE_USER:?REMOTE_USER requis dans $ENV_FILE}"

REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_DIR="${REMOTE_DIR:-/opt/agflow.docker}"
REMOTE_SCRIPT="${REMOTE_SCRIPT:-./dev-deploy.sh}"

# Options SSH communes
SSH_OPTS=(
    -o StrictHostKeyChecking=no
    -o BatchMode=no
    -p "$REMOTE_PORT"
)

# Choisir la méthode d'authentification
if [ -n "${REMOTE_KEY:-}" ]; then
    if [ ! -f "$REMOTE_KEY" ]; then
        echo "ERROR: clé SSH introuvable : $REMOTE_KEY"
        exit 1
    fi
    SSH_OPTS+=(-i "$REMOTE_KEY")
    SSH_BIN="ssh"
elif [ -n "${REMOTE_PASSWORD:-}" ]; then
    if ! command -v sshpass &>/dev/null; then
        echo "ERROR: sshpass est requis pour l'auth par mot de passe."
        echo "       apt-get install sshpass  (Debian/Ubuntu)"
        echo "       brew install hudochenkov/sshpass/sshpass  (macOS)"
        exit 1
    fi
    export SSHPASS="$REMOTE_PASSWORD"
    SSH_BIN="sshpass -e ssh"
else
    echo "ERROR: REMOTE_KEY ou REMOTE_PASSWORD doit être défini dans $ENV_FILE"
    exit 1
fi

echo "==> Connexion à ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
echo "==> Répertoire : ${REMOTE_DIR}"
echo "==> Script     : ${REMOTE_SCRIPT}"
echo ""

# shellcheck disable=SC2086
$SSH_BIN "${SSH_OPTS[@]}" "${REMOTE_USER}@${REMOTE_HOST}" \
    "cd ${REMOTE_DIR} && ${REMOTE_SCRIPT}"
