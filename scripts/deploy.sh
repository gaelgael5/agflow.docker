#!/usr/bin/env bash
###############################################################################
# Deploy agflow.docker to LXC 201 (192.168.10.68)
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

echo "==> Packaging deploy context (.env + compose + Caddyfile + backend + frontend)..."
tar czf /tmp/agflow-deploy.tar.gz \
    .env docker-compose.prod.yml Caddyfile \
    backend/Dockerfile backend/pyproject.toml backend/src backend/migrations \
    frontend/Dockerfile frontend/nginx.conf frontend/package.json frontend/package-lock.json \
    frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts \
    frontend/tailwind.config.js frontend/postcss.config.js \
    frontend/index.html frontend/src

echo "==> Uploading to pve..."
scp /tmp/agflow-deploy.tar.gz pve:/tmp/

echo "==> Pushing into CT ${CTID} and extracting..."
ssh pve "pct push ${CTID} /tmp/agflow-deploy.tar.gz /tmp/agflow-deploy.tar.gz && \
         pct exec ${CTID} -- bash -c 'rm -rf ${REPO_DIR_ON_CT} && mkdir -p ${REPO_DIR_ON_CT} && cd ${REPO_DIR_ON_CT} && tar xzf /tmp/agflow-deploy.tar.gz'"

if [ "$REBUILD" -eq 1 ]; then
    echo "==> Rebuilding images on CT ${CTID}..."
    ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT}/backend && docker build -t agflow-backend:latest .'"
    ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT}/frontend && docker build -t agflow-frontend:latest .'"
fi

echo "==> Starting stack on CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && docker compose -f docker-compose.prod.yml up -d && sleep 3 && docker compose -f docker-compose.prod.yml ps'"

echo ""
echo "==> Deployed. Smoke test:"
echo "    curl http://192.168.10.68/health"
echo "    curl http://192.168.10.68/api/admin/auth/login -X POST -H 'Content-Type: application/json' -d '{\"email\":\"<admin_email>\",\"password\":\"<admin_password>\"}'"
