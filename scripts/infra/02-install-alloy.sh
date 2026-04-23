#!/bin/bash
###############################################################################
# Script 02 : Installation Grafana Alloy (collecteur logs Docker + journald)
#
# A executer DANS le container LXC (en tant que root).
#
# Detecte automatiquement la presence de Docker :
#   - Si Docker present  -> deploiement via docker-compose (image grafana/alloy)
#   - Si Docker absent   -> installation paquet Debian + service systemd
#
# Variables d'environnement requises :
#   LOKI_URL  - endpoint Loki, ex: http://192.168.10.<IP_LXC116>:3100/loki/api/v1/push
#   HOSTNAME  - identifiant du LXC (label `host`), ex: lxc201
#
# Pre-requis (mode docker) :
#   - /tmp/alloy-agent/ contient docker-compose.yml + config.alloy + config-journald-only.alloy
#     (copie via : pct push <CTID> infra/alloy-agent/* /tmp/alloy-agent/)
###############################################################################
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef)

LOKI_URL="${LOKI_URL:-}"
HOSTNAME_LABEL="${HOSTNAME:-$(hostname)}"
ALLOY_SRC_DIR="${ALLOY_SRC_DIR:-/tmp/alloy-agent}"
ALLOY_DST_DIR="${ALLOY_DST_DIR:-/opt/alloy-agent}"

echo "==========================================="
echo "  Installation Grafana Alloy"
echo "==========================================="
echo "  HOSTNAME    : ${HOSTNAME_LABEL}"
echo "  LOKI_URL    : ${LOKI_URL}"
echo "  Source dir  : ${ALLOY_SRC_DIR}"
echo "  Target dir  : ${ALLOY_DST_DIR}"
echo ""

if [ -z "${LOKI_URL}" ]; then
    echo "ERREUR : LOKI_URL doit etre defini."
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "ERREUR : Ce script doit etre execute en tant que root."
    exit 1
fi

if [ ! -d "${ALLOY_SRC_DIR}" ]; then
    echo "ERREUR : Source dir ${ALLOY_SRC_DIR} introuvable."
    echo "         Copier infra/alloy-agent/ dans ${ALLOY_SRC_DIR} avant d'executer."
    exit 1
fi

# ── Detection Docker ─────────────────────────────────────────────────────────
HAS_DOCKER=0
if command -v docker &>/dev/null && [ -S /var/run/docker.sock ]; then
    HAS_DOCKER=1
    echo "  Docker detecte -> mode container"
else
    echo "  Docker absent -> mode binaire systemd"
fi
echo ""

mkdir -p "${ALLOY_DST_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
# MODE DOCKER
# ══════════════════════════════════════════════════════════════════════════════
if [ "${HAS_DOCKER}" -eq 1 ]; then

    echo "[1/3] Copie des fichiers vers ${ALLOY_DST_DIR}..."
    cp "${ALLOY_SRC_DIR}/docker-compose.yml" "${ALLOY_DST_DIR}/"
    cp "${ALLOY_SRC_DIR}/config.alloy" "${ALLOY_DST_DIR}/"
    echo "  -> OK"

    echo "[2/3] Ecriture .env..."
    cat > "${ALLOY_DST_DIR}/.env" << EOF
LOKI_URL=${LOKI_URL}
HOSTNAME=${HOSTNAME_LABEL}
EOF
    echo "  -> ${ALLOY_DST_DIR}/.env"

    echo "[3/3] Demarrage du container Alloy..."
    cd "${ALLOY_DST_DIR}"
    docker compose pull
    docker compose up -d
    echo "  -> OK"
    echo ""
    docker compose ps

# ══════════════════════════════════════════════════════════════════════════════
# MODE BINAIRE SYSTEMD
# ══════════════════════════════════════════════════════════════════════════════
else

    echo "[1/4] Ajout du depot Grafana..."
    # Pre-requis : wget + gnupg (LXC minimaux type alpine/debian-slim peuvent les omettre)
    if ! command -v wget &>/dev/null || ! command -v gpg &>/dev/null; then
        apt-get update -qq
        apt-get "${APT_OPTS[@]}" install -y -qq wget gnupg ca-certificates
    fi
    install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/grafana.gpg ] || [ ! -s /etc/apt/keyrings/grafana.gpg ]; then
        wget -qO- https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
        chmod a+r /etc/apt/keyrings/grafana.gpg
    fi
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list
    apt-get update -qq
    echo "  -> OK"

    echo "[2/4] Installation paquet alloy..."
    apt-get "${APT_OPTS[@]}" install -y -qq alloy
    echo "  -> OK"

    echo "[3/4] Ecriture config et environment..."
    cp "${ALLOY_SRC_DIR}/config-journald-only.alloy" /etc/alloy/config.alloy
    # L'unit systemd du paquet Debian attend CONFIG_FILE et CUSTOM_ARGS.
    # Sans CONFIG_FILE, `alloy run` echoue ("accepts 1 arg(s), received 0").
    cat > /etc/default/alloy << EOF
CONFIG_FILE="/etc/alloy/config.alloy"
CUSTOM_ARGS=""
RESTART_ON_UPGRADE=true
LOKI_URL=${LOKI_URL}
HOSTNAME=${HOSTNAME_LABEL}
EOF
    echo "  -> /etc/alloy/config.alloy"
    echo "  -> /etc/default/alloy"

    echo "[4/4] Demarrage service alloy..."
    systemctl daemon-reload
    systemctl enable alloy
    systemctl restart alloy
    sleep 2
    systemctl status alloy --no-pager --lines=5 || true
    echo "  -> OK"
fi

echo ""
echo "==========================================="
echo "  Alloy installe et demarre"
echo "==========================================="
echo "{\"status\":\"ok\",\"hostname\":\"${HOSTNAME_LABEL}\",\"loki_url\":\"${LOKI_URL}\",\"mode\":\"$([ ${HAS_DOCKER} -eq 1 ] && echo docker || echo systemd)\"}"
