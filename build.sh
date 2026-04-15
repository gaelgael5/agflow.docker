#!/usr/bin/env bash
###############################################################################
# Rebuild des images agflow sur LXC 201, relance la stack via launch.sh,
# puis nettoie les images Docker obsoletes (dangling + anciennes versions).
#
# Usage : ./build.sh
#
# Prereq : le code doit deja etre synchronise sur la CT (via deploy.sh ou
#          un rsync manuel). Ce script ne transfere aucun fichier.
###############################################################################
set -euo pipefail

CTID="${CTID:-201}"
REPO_DIR_ON_CT="${REPO_DIR_ON_CT:-/root/agflow.docker}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Rebuild backend image (no-cache) sur CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT}/backend && docker build --no-cache -t agflow-backend:latest .'"

echo "==> Rebuild frontend image (no-cache) sur CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT}/frontend && docker build --no-cache -t agflow-frontend:latest .'"

echo "==> Relance de la stack via launch.sh..."
bash "${SCRIPT_DIR}/launch.sh" up

echo "==> Nettoyage des images Docker obsoletes sur CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'docker image prune -f && docker image prune -a -f --filter \"label!=keep\" --filter \"until=24h\"'"

echo "==> Termine."
ssh pve "pct exec ${CTID} -- bash -c 'docker images | head -20'"
