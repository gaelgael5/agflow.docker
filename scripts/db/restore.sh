#!/usr/bin/env bash
###############################################################################
# Restaure un dump dans la base Postgres d'agflow.docker côté LXC 201.
#
# Usage :
#   ./scripts/db/restore.sh agflow-20260502-153012.sql.gz       # depuis CT
#   ./scripts/db/restore.sh ./backups/agflow-...sql.gz --upload # depuis local
#
# DESTRUCTIF : le dump utilisé contient `--clean --if-exists` donc les tables
# existantes sont DROP avant recréation. Tout le contenu de la base est écrasé.
# Le script demande une confirmation explicite ("yes") avant de procéder.
#
# Étapes :
#   1. (--upload) push le fichier local vers /tmp côté CT
#   2. Stop backend (sinon connexions actives bloquent les DROP)
#   3. Restore via psql depuis le dump gzip
#   4. Restart backend
###############################################################################
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <backup.sql.gz> [--upload]" >&2
    exit 1
fi

CTID="${CTID:-201}"
REPO_DIR_ON_CT="/root/agflow.docker"
BACKUPS_DIR_ON_CT="${REPO_DIR_ON_CT}/backups"

INPUT="$1"
UPLOAD=0
[[ "${2:-}" == "--upload" ]] && UPLOAD=1

if [[ "$UPLOAD" -eq 1 ]]; then
    if [[ ! -f "$INPUT" ]]; then
        echo "ERROR: local file not found: $INPUT" >&2
        exit 1
    fi
    REMOTE_FILE="$(basename "$INPUT")"
    REMOTE_PATH="${BACKUPS_DIR_ON_CT}/${REMOTE_FILE}"
    echo "==> Uploading $INPUT → CT ${CTID}:${REMOTE_PATH}"
    ssh pve "pct exec ${CTID} -- mkdir -p ${BACKUPS_DIR_ON_CT}"
    scp "$INPUT" pve:/tmp/agflow-restore-input.sql.gz
    ssh pve "pct push ${CTID} /tmp/agflow-restore-input.sql.gz ${REMOTE_PATH} && rm -f /tmp/agflow-restore-input.sql.gz"
else
    REMOTE_FILE="$INPUT"
    REMOTE_PATH="${BACKUPS_DIR_ON_CT}/${REMOTE_FILE}"
fi

echo ""
echo "==> Backup utilisé : ${REMOTE_PATH}"
ssh pve "pct exec ${CTID} -- ls -lh ${REMOTE_PATH}"

echo ""
echo "⚠️  ATTENTION — toutes les données de la base agflow vont être ÉCRASÉES."
read -rp "Confirme en tapant 'yes' : " CONFIRM
[[ "$CONFIRM" == "yes" ]] || { echo "Annulé."; exit 1; }

echo ""
echo "==> Stop backend (déconnexion des sessions actives)"
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && docker compose -f docker-compose.prod.yml stop backend'"

echo ""
echo "==> Restore en cours..."
ssh pve "pct exec ${CTID} -- bash -c '
  gunzip -c ${REMOTE_PATH} \
  | docker exec -i agflow-postgres sh -c \
      \"psql -U \\\"\\\$POSTGRES_USER\\\" -d \\\"\\\$POSTGRES_DB\\\" -v ON_ERROR_STOP=1\"
'"

echo ""
echo "==> Restart backend"
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && docker compose -f docker-compose.prod.yml up -d backend'"

echo ""
echo "==> Done. Vérifie : curl http://192.168.10.154/health"
