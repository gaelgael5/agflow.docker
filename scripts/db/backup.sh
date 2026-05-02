#!/usr/bin/env bash
###############################################################################
# Dump la base Postgres d'agflow.docker côté LXC 201.
#
# Usage :
#   ./scripts/db/backup.sh                    # → backups/agflow-YYYYMMDD-HHMMSS.sql.gz côté CT
#   ./scripts/db/backup.sh --download         # + rapatrie le fichier en local
#   ./scripts/db/backup.sh --label feature-x  # nom suffixé : agflow-YYYYMMDD-HHMMSS-feature-x.sql.gz
#
# Le dump est `pg_dump --clean --if-exists --no-owner --no-privileges`
# pour rendre le restore portable (drop + recreate, pas de dépendance owner).
# Compressé en gzip. Stocké côté CT dans /root/agflow.docker/backups/.
###############################################################################
set -euo pipefail

CTID="${CTID:-201}"
REPO_DIR_ON_CT="/root/agflow.docker"
BACKUPS_DIR_ON_CT="${REPO_DIR_ON_CT}/backups"

DOWNLOAD=0
LABEL=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --download) DOWNLOAD=1; shift ;;
        --label)    LABEL="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
SUFFIX=""
[[ -n "$LABEL" ]] && SUFFIX="-${LABEL}"
FILENAME="agflow-${TIMESTAMP}${SUFFIX}.sql.gz"
REMOTE_PATH="${BACKUPS_DIR_ON_CT}/${FILENAME}"

echo "==> Dumping into CT ${CTID}: ${REMOTE_PATH}"
# `sh -c` dans le container pour interpoler $POSTGRES_USER/$POSTGRES_DB côté
# postgres (où ces env sont définies par le compose). Plus propre que de
# faire transiter les valeurs à travers 4 niveaux d'escape.
ssh pve "pct exec ${CTID} -- bash -c '
  mkdir -p ${BACKUPS_DIR_ON_CT}
  docker exec agflow-postgres sh -c \
    \"pg_dump -U \\\"\\\$POSTGRES_USER\\\" -d \\\"\\\$POSTGRES_DB\\\" --clean --if-exists --no-owner --no-privileges\" \
  | gzip > ${REMOTE_PATH}
  ls -lh ${REMOTE_PATH}
'"

if [[ "$DOWNLOAD" -eq 1 ]]; then
    LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/backups"
    mkdir -p "$LOCAL_DIR"
    LOCAL_PATH="${LOCAL_DIR}/${FILENAME}"
    echo "==> Downloading to ${LOCAL_PATH}"
    ssh pve "pct exec ${CTID} -- cat ${REMOTE_PATH}" > "$LOCAL_PATH"
    ls -lh "$LOCAL_PATH"
fi

echo ""
echo "==> Done. Liste des backups CT :"
ssh pve "pct exec ${CTID} -- ls -lht ${BACKUPS_DIR_ON_CT}" | head -10
