#!/usr/bin/env bash
###############################################################################
# Lance la stack agflow.docker sur LXC 201 via docker compose.
#
# Usage :
#   ./launch.sh            # up -d
#   ./launch.sh down       # stop + remove
#   ./launch.sh restart    # restart
#   ./launch.sh logs       # suit les logs
#   ./launch.sh ps         # statut des services
###############################################################################
set -euo pipefail

CTID="${CTID:-201}"
REPO_DIR_ON_CT="${REPO_DIR_ON_CT:-/root/agflow.docker}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

ACTION="${1:-up}"

case "$ACTION" in
    up)       CMD="docker compose -f ${COMPOSE_FILE} up -d && sleep 3 && docker compose -f ${COMPOSE_FILE} ps" ;;
    down)     CMD="docker compose -f ${COMPOSE_FILE} down" ;;
    restart)  CMD="docker compose -f ${COMPOSE_FILE} restart && docker compose -f ${COMPOSE_FILE} ps" ;;
    logs)     CMD="docker compose -f ${COMPOSE_FILE} logs -f --tail=100" ;;
    ps)       CMD="docker compose -f ${COMPOSE_FILE} ps" ;;
    *)        echo "Usage: $0 [up|down|restart|logs|ps]" >&2; exit 1 ;;
esac

exec ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && ${CMD}'"
