#!/bin/bash
###############################################################################
# Script : Installation K3s (lightweight Kubernetes) sur un container LXC
#
# A executer DANS le container LXC (pas sur l'hote Proxmox).
# Le script est telecharge et lance via SSH depuis agflow.
#
# Installe :
#   - K3s (server mode, single node)
#   - kubectl alias
#   - Desactive Traefik (optionnel, parametre)
#
# Usage : ./install-k3s.sh [--no-traefik]
#
# Pre-requis :
#   - Container LXC avec Docker installe
#   - Acces internet (curl vers get.k3s.io)
#   - systemd actif
###############################################################################
set -euo pipefail

DISABLE_TRAEFIK="${1:-}"

echo "==========================================="
echo "  Installation K3s"
echo "==========================================="
echo ""

# ── Verifier les pre-requis ──────────────────────────────────────────────────
echo "[1/5] Verification des pre-requis..."

if ! command -v curl &>/dev/null; then
    echo "  -> Installation curl..."
    apt-get update -qq >/dev/null 2>&1
    apt-get install -y -qq curl >/dev/null 2>&1
fi
echo "  -> curl: OK"

if ! systemctl --version &>/dev/null 2>&1; then
    echo "  ERREUR: systemd requis mais non disponible"
    exit 1
fi
echo "  -> systemd: OK"

# ── Installer K3s ───────────────────────────────────────────────────────────
echo ""
echo "[2/5] Installation K3s..."

K3S_OPTS=""
if [ "${DISABLE_TRAEFIK}" = "--no-traefik" ]; then
    K3S_OPTS="--disable=traefik"
    echo "  -> Traefik desactive"
fi

# K3s utilise Docker comme runtime si disponible, sinon containerd
if command -v docker &>/dev/null; then
    K3S_OPTS="${K3S_OPTS} --docker"
    echo "  -> Runtime: Docker"
else
    echo "  -> Runtime: containerd (built-in)"
fi

curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server ${K3S_OPTS}" sh -

echo "  -> K3s installe"

# ── Attendre que K3s soit pret ──────────────────────────────────────────────
echo ""
echo "[3/5] Attente demarrage K3s..."

for i in $(seq 1 30); do
    if k3s kubectl get nodes &>/dev/null; then
        echo "  -> K3s pret (${i}s)"
        break
    fi
    sleep 2
done

if ! k3s kubectl get nodes &>/dev/null; then
    echo "  ERREUR: K3s n'a pas demarre apres 60s"
    echo "  Verifiez: journalctl -u k3s"
    exit 1
fi

# ── Configurer kubectl ──────────────────────────────────────────────────────
echo ""
echo "[4/5] Configuration kubectl..."

mkdir -p /root/.kube
cp /etc/rancher/k3s/k3s.yaml /root/.kube/config
chmod 600 /root/.kube/config

# Alias kubectl
if ! grep -q "alias kubectl" /root/.bashrc 2>/dev/null; then
    echo "alias kubectl='k3s kubectl'" >> /root/.bashrc
    echo "  -> Alias kubectl ajoute"
fi

# Installer kubectl standalone si pas present
if ! command -v kubectl &>/dev/null; then
    ln -sf /usr/local/bin/k3s /usr/local/bin/kubectl 2>/dev/null || true
    echo "  -> Symlink kubectl cree"
fi

echo "  -> kubeconfig: /root/.kube/config"

# ── Resume ──────────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Verification finale..."

K3S_VERSION=$(k3s --version 2>/dev/null | head -1 || echo "inconnu")
NODE_STATUS=$(k3s kubectl get nodes -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
NODE_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
KUBECONFIG_CONTENT=$(cat /root/.kube/config 2>/dev/null | base64 -w0 || echo "")

echo ""
echo "==========================================="
echo "  K3s INSTALLE"
echo "==========================================="
echo ""
echo "  Version    : ${K3S_VERSION}"
echo "  Node Ready : ${NODE_STATUS}"
echo "  Traefik    : $([ "${DISABLE_TRAEFIK}" = "--no-traefik" ] && echo "desactive" || echo "actif")"
echo "  kubeconfig : /root/.kube/config"
echo ""
echo "  Commandes utiles :"
echo "    k3s kubectl get nodes"
echo "    k3s kubectl get pods -A"
echo ""
echo "==========================================="

# ── Sortie JSON (convention pipeline agflow) ─────────────────────────────────
echo "{\"status\":\"ok\",\"k3s_version\":\"${K3S_VERSION}\",\"node_ready\":\"${NODE_STATUS}\",\"ip\":\"${NODE_IP}\",\"kubeconfig_b64\":\"${KUBECONFIG_CONTENT}\"}"
