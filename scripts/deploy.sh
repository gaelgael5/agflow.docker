#!/usr/bin/env bash
###############################################################################
# Deploy agflow.docker to LXC 201 (192.168.10.154)
#
# Prereqs :
#   - ssh alias `pve` in ~/.ssh/config
#   - CT 201 running with Docker + Compose installed
#   - Local repo has a .env file with production values (never committed)
#   - Backend + frontend images already built on LXC 201 (or this script rebuilds)
#
# Usage : ./scripts/deploy.sh [--rebuild]
#   --rebuild : rebuild backend & frontend images on CT 201 before starting stack
###############################################################################
set -euo pipefail

CTID="${CTID:-201}"
REPO_DIR_ON_CT="/root/agflow.docker"
REBUILD=0

if [[ "${1:-}" == "--rebuild" ]]; then
    REBUILD=1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .env ]; then
    echo "ERROR: .env missing. Copy .env.example to .env and fill in real values."
    exit 1
fi

echo "==> Packaging deploy context (.env + compose + Caddyfile + apps.json + backend + frontend)..."
tar czf /tmp/agflow-deploy.tar.gz \
    .env docker-compose.dev.yml Caddyfile apps.json \
    backend/Dockerfile backend/pyproject.toml backend/src backend/migrations \
    frontend/Dockerfile frontend/nginx.conf frontend/package.json frontend/package-lock.json \
    frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts \
    frontend/tailwind.config.js frontend/postcss.config.js \
    frontend/index.html frontend/src

echo "==> Uploading to pve..."
scp /tmp/agflow-deploy.tar.gz pve:/tmp/

echo "==> Stopping backend/frontend before code update..."
ssh pve "pct exec ${CTID} -- bash -c '
  cd ${REPO_DIR_ON_CT} 2>/dev/null && \
  docker compose -f docker-compose.dev.yml stop backend frontend 2>/dev/null || true
'"

echo "==> Pushing into CT ${CTID} and extracting..."
# IMPORTANT — préservations côté CT :
# 1. .env : peut avoir été patché côté CT (AUTH_MODE, secrets etc.). On le
#    sauvegarde avant l'extract et on le restaure après ; le .env du tarball
#    sert uniquement de bootstrap pour un CT vierge.
# 2. data/ N'EST PAS dans le tarball : aucun risque de corrompre les données.
# 3. Sous-dossiers tracés (backend/src, backend/migrations, frontend/src) :
#    purgés AVANT l'extract pour éviter que des fichiers obsolètes
#    (renommés/supprimés en local) trainent côté CT. Symptôme historique :
#    la consolidation 86 → 1 migrations laissait les anciennes migrations
#    (002_*, 003_*, ...) → UndefinedColumnError au boot, crashloop.
# Note : le `\$ENV_PRESERVE` est échappé pour rester littéral et être
# évalué par le shell distant — `${CTID}` et `${REPO_DIR_ON_CT}` sont
# au contraire interpolés volontairement côté local.
ssh pve "pct push ${CTID} /tmp/agflow-deploy.tar.gz /tmp/agflow-deploy.tar.gz && \
         pct exec ${CTID} -- bash -c '
           mkdir -p ${REPO_DIR_ON_CT}
           mkdir -p ${REPO_DIR_ON_CT}/data
           # Sauvegarde le .env CT s il existe
           ENV_PRESERVE=
           if [ -f ${REPO_DIR_ON_CT}/.env ]; then
             ENV_PRESERVE=/tmp/agflow-env-preserve.txt
             cp ${REPO_DIR_ON_CT}/.env \"\$ENV_PRESERVE\"
           fi
           # Purge les répertoires entièrement tracés avant l extract.
           rm -rf ${REPO_DIR_ON_CT}/backend/src \
                  ${REPO_DIR_ON_CT}/backend/migrations \
                  ${REPO_DIR_ON_CT}/frontend/src
           # apps.json doit etre un FICHIER (le mount Docker le voit comme dir
           # si le source manque au premier up). Si c est un dir vide, vire-le
           # pour que le tar extract puisse y poser le fichier.
           if [ -d ${REPO_DIR_ON_CT}/apps.json ]; then
             rm -rf ${REPO_DIR_ON_CT}/apps.json
           fi
           cd ${REPO_DIR_ON_CT} && tar xzf /tmp/agflow-deploy.tar.gz
           # Restaure le .env CT (le bootstrap du tarball ne ecrase plus)
           if [ -n \"\$ENV_PRESERVE\" ] && [ -f \"\$ENV_PRESERVE\" ]; then
             mv \"\$ENV_PRESERVE\" ${REPO_DIR_ON_CT}/.env
           fi
         '"

if [ "$REBUILD" -eq 1 ]; then
    echo "==> Rebuilding images on CT ${CTID}..."
    ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT}/backend && docker build -t agflow-backend:latest .'"
    ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT}/frontend && docker build -t agflow-frontend:latest .'"
fi

echo "==> Starting stack on CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && docker compose -f docker-compose.dev.yml up -d && sleep 3 && docker compose -f docker-compose.dev.yml ps'"

echo ""
echo "==> Deployed. Smoke test:"
echo "    curl http://192.168.10.154/health"
echo "    curl http://192.168.10.154/api/admin/auth/login -X POST -H 'Content-Type: application/json' -d '{\"email\":\"<admin_email>\",\"password\":\"<admin_password>\"}'"
