#!/bin/bash
###############################################################################
# Deploiement Alloy collecteur sur tous les LXC actifs du homelab.
#
# A executer depuis le poste local (Windows / Linux), depuis la racine du repo
# agflow.docker. Utilise le host Proxmox (alias SSH `pve`) comme bastion :
#   - pct push <CTID> ... pour copier les fichiers
#   - pct exec <CTID> -- bash ... pour executer le script d'install
#
# Variables :
#   LOKI_URL  - endpoint Loki central (LXC 116), defaut http://192.168.10.<IP>:3100/loki/api/v1/push
#   LXC_HOSTS - liste d'IDs LXC a deployer, defaut tous les LXC actifs du homelab
#   PVE_HOST  - alias SSH du host Proxmox, defaut `pve`
#
# Usage :
#   LOKI_URL="http://192.168.10.<IP_LXC116>:3100/loki/api/v1/push" ./scripts/infra/deploy-alloy-all.sh
#
# Pour deployer sur un sous-ensemble :
#   LXC_HOSTS="201 102" LOKI_URL="..." ./scripts/infra/deploy-alloy-all.sh
###############################################################################
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ALLOY_AGENT_DIR="${REPO_DIR}/infra/alloy-agent"
INSTALL_SCRIPT="${REPO_DIR}/scripts/infra/02-install-alloy.sh"

PVE_HOST="${PVE_HOST:-pve}"
LXC_HOSTS="${LXC_HOSTS:-101 102 108 111 112 113 114 115 116 117 201}"

if [ -z "${LOKI_URL:-}" ]; then
    echo "ERREUR : LOKI_URL doit etre defini."
    echo "Usage : LOKI_URL=\"http://192.168.10.<IP>:3100/loki/api/v1/push\" $0"
    exit 1
fi

if [ ! -d "${ALLOY_AGENT_DIR}" ]; then
    echo "ERREUR : ${ALLOY_AGENT_DIR} introuvable."
    exit 1
fi

if [ ! -f "${INSTALL_SCRIPT}" ]; then
    echo "ERREUR : ${INSTALL_SCRIPT} introuvable."
    exit 1
fi

echo "==========================================="
echo "  Deploiement Alloy collecteur"
echo "==========================================="
echo "  PVE_HOST   : ${PVE_HOST}"
echo "  LOKI_URL   : ${LOKI_URL}"
echo "  LXC_HOSTS  : ${LXC_HOSTS}"
echo ""

FAILED=()
for CTID in ${LXC_HOSTS}; do
    HOSTNAME_LABEL="lxc${CTID}"
    echo "──────────────────────────────────────────"
    echo "  LXC ${CTID} (${HOSTNAME_LABEL})"
    echo "──────────────────────────────────────────"

    # Verifier que le LXC est running
    STATUS=$(ssh "${PVE_HOST}" "pct status ${CTID} 2>/dev/null || echo absent")
    if ! echo "${STATUS}" | grep -q "running"; then
        echo "  [!] LXC ${CTID} status = ${STATUS} -> skip"
        FAILED+=("${CTID}:not-running")
        continue
    fi

    # Preparer le dossier source dans le LXC
    if ! ssh "${PVE_HOST}" "pct exec ${CTID} -- bash -c 'rm -rf /tmp/alloy-agent && mkdir -p /tmp/alloy-agent'"; then
        echo "  [!] Impossible de preparer /tmp/alloy-agent dans LXC ${CTID}"
        FAILED+=("${CTID}:mkdir-failed")
        continue
    fi

    # Pousser les fichiers via pct push
    echo "  [1/3] Copie des fichiers..."
    for FILE in config.alloy config-journald-only.alloy docker-compose.yml; do
        scp -q "${ALLOY_AGENT_DIR}/${FILE}" "${PVE_HOST}:/tmp/alloy-${CTID}-${FILE}"
        ssh "${PVE_HOST}" "pct push ${CTID} /tmp/alloy-${CTID}-${FILE} /tmp/alloy-agent/${FILE} && rm /tmp/alloy-${CTID}-${FILE}"
    done
    scp -q "${INSTALL_SCRIPT}" "${PVE_HOST}:/tmp/02-install-alloy-${CTID}.sh"
    ssh "${PVE_HOST}" "pct push ${CTID} /tmp/02-install-alloy-${CTID}.sh /tmp/02-install-alloy.sh && rm /tmp/02-install-alloy-${CTID}.sh"
    ssh "${PVE_HOST}" "pct exec ${CTID} -- chmod +x /tmp/02-install-alloy.sh"
    echo "  -> OK"

    # Lancer l'installation
    echo "  [2/3] Execution 02-install-alloy.sh..."
    if ssh "${PVE_HOST}" "pct exec ${CTID} -- env LOKI_URL='${LOKI_URL}' HOSTNAME='${HOSTNAME_LABEL}' bash /tmp/02-install-alloy.sh"; then
        echo "  -> OK"
    else
        echo "  [!] Echec installation sur LXC ${CTID}"
        FAILED+=("${CTID}:install-failed")
        continue
    fi

    echo "  [3/3] LXC ${CTID} -> Alloy actif"
    echo ""
done

echo "==========================================="
echo "  Resume"
echo "==========================================="
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "  Tous les deploiements ont reussi."
else
    echo "  Echecs (${#FAILED[@]}) :"
    for F in "${FAILED[@]}"; do
        echo "    - ${F}"
    done
    exit 1
fi
