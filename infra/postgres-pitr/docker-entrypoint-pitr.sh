#!/bin/sh
set -eu

if [ "${AGFLOW_PITR_MODE:-normal}" = "restore" ]; then
    : "${AGFLOW_PITR_TARGET_TIME:?required}"
    echo "[pitr] Restore mode: target=${AGFLOW_PITR_TARGET_TIME}"
    pgbackrest --stanza=agflow restore \
        --type=time \
        --target="${AGFLOW_PITR_TARGET_TIME}" \
        --target-action=promote \
        --pg1-path=/var/lib/postgresql/data
    exec docker-entrypoint.sh "$@"
fi

exec docker-entrypoint.sh "$@"
