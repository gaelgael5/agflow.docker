#!/bin/bash
###############################################################################
# Script : Installation K3s (lightweight Kubernetes) sur un container LXC
#
# Executé via SSH depuis agflow en tant qu'utilisateur agflow (sudo NOPASSWD).
#
# Installe :
#   - K3s (server mode, single node)
#   - kubectl alias
#   - Desactive Traefik (optionnel, parametre)
#
# Usage : ./install-k3s.sh [--no-traefik]
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
    sudo apt-get update -qq 2>&1
    sudo apt-get install -y -qq curl 2>&1
fi
echo "  -> curl: OK"

if ! sudo systemctl --version &>/dev/null 2>&1; then
    echo "  ERREUR: systemd requis mais non disponible"
    exit 1
fi
echo "  -> systemd: OK"

# ── Installer K3s ───────────────────────────────────────────────────────────
echo ""
echo "[2/5] Installation K3s..."

# Fix LXC : /dev/kmsg manquant (kubelet en a besoin)
if [ ! -e /dev/kmsg ]; then
    sudo ln -sf /dev/console /dev/kmsg
    echo "  -> /dev/kmsg cree (symlink -> /dev/console)"
fi
# Rendre permanent au reboot
if [ ! -f /etc/tmpfiles.d/kmsg.conf ]; then
    echo "L /dev/kmsg - - - - /dev/console" | sudo tee /etc/tmpfiles.d/kmsg.conf >/dev/null
    echo "  -> /dev/kmsg persistant via tmpfiles.d"
fi

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

curl -sfL https://get.k3s.io | sudo INSTALL_K3S_EXEC="server ${K3S_OPTS}" sh -

echo "  -> K3s installe"

# ── Attendre que K3s soit pret ──────────────────────────────────────────────
echo ""
echo "[3/5] Attente demarrage K3s..."

for i in $(seq 1 30); do
    if sudo k3s kubectl get nodes &>/dev/null; then
        echo "  -> K3s pret (${i}s)"
        break
    fi
    sleep 2
done

if ! sudo k3s kubectl get nodes &>/dev/null; then
    echo "  ERREUR: K3s n'a pas demarre apres 60s"
    echo "  Verifiez: sudo journalctl -u k3s"
    exit 1
fi

# ── Configurer kubectl ──────────────────────────────────────────────────────
echo ""
echo "[4/5] Configuration kubectl..."

sudo mkdir -p /home/${USER}/.kube
sudo cp /etc/rancher/k3s/k3s.yaml /home/${USER}/.kube/config
sudo chown -R ${USER}:${USER} /home/${USER}/.kube
chmod 600 /home/${USER}/.kube/config

# Alias kubectl
if ! grep -q "alias kubectl" ~/.bashrc 2>/dev/null; then
    echo "alias kubectl='sudo k3s kubectl'" >> ~/.bashrc
    echo "  -> Alias kubectl ajoute"
fi

# Symlink kubectl
if ! command -v kubectl &>/dev/null; then
    sudo ln -sf /usr/local/bin/k3s /usr/local/bin/kubectl 2>/dev/null || true
    echo "  -> Symlink kubectl cree"
fi

echo "  -> kubeconfig: ~/.kube/config"

# ── Resume ──────────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Verification finale..."

K3S_VERSION=$(sudo k3s --version 2>/dev/null | head -1 || echo "inconnu")
NODE_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
KUBECONFIG_CONTENT=$(sudo cat /etc/rancher/k3s/k3s.yaml 2>/dev/null | base64 -w0 || echo "")

# Verification K3s nodes (JSON complet)
echo ""
echo "  Verification K3s nodes :"
NODES_JSON=$(sudo k3s kubectl get nodes -o json 2>/dev/null || echo '{}')
echo "${NODES_JSON}" | head -30

NODE_STATUS=$(echo "${NODES_JSON}" | grep -o '"status":"[^"]*"' | head -1 || echo "")
NODE_READY=$(echo "${NODES_JSON}" | sudo k3s kubectl get nodes -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")

echo ""
echo "==========================================="
echo "  K3s INSTALLE"
echo "==========================================="
echo ""
echo "  Version    : ${K3S_VERSION}"
echo "  Node Ready : ${NODE_READY}"
echo "  Traefik    : $([ "${DISABLE_TRAEFIK}" = "--no-traefik" ] && echo "desactive" || echo "actif")"
echo "  kubeconfig : ~/.kube/config"
echo ""
echo "==========================================="

# ── Sortie JSON (convention pipeline agflow) ─────────────────────────────────
echo "{\"status\":\"ok\",\"k3s_version\":\"${K3S_VERSION}\",\"node_ready\":\"${NODE_READY}\",\"ip\":\"${NODE_IP}\",\"kubeconfig_b64\":\"${KUBECONFIG_CONTENT}\"}"
