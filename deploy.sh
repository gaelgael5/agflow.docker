#!/usr/bin/env bash
set -euo pipefail

REPO_URL="git@github.com:gaelgael5/agflow.docker.git"
BRANCH="feat/mom-bus"

# --- 1) Positionnement dans le repo (mode "dans le repo" ou "bootstrap clone") ---
if [ -d ".git" ]; then
  echo "Repo détecté dans le répertoire courant: $(pwd)"
  echo "Mise à jour sur la branche ${BRANCH}..."
  git fetch origin
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
else
  APP_DIR="agflow.docker"
  if [ -d "$APP_DIR/.git" ]; then
    echo "Repo déjà cloné dans ./${APP_DIR}"
    echo "Mise à jour sur la branche ${BRANCH}..."
    git -C "$APP_DIR" fetch origin
    git -C "$APP_DIR" checkout "$BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
  else
    echo "Clone du repo dans ./${APP_DIR} (branche ${BRANCH})..."
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  cd "$APP_DIR"
fi

# --- 2) .env ---
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  echo ".env absent -> création depuis .env.example"
  cp .env.example .env
fi

# --- 3) Build images locales ---
echo "Build de l'image backend..."
docker build -t agflow-backend:latest backend/

echo "Build de l'image frontend..."
docker build -t agflow-frontend:latest frontend/

# --- 4) Nettoyage containers orphelins / anciennes runs du projet ---
echo "Arrêt/cleanup du projet docker compose (incl. orphelins)..."
docker compose -f docker-compose.dev.yml down --remove-orphans || true

# --- 5) Pull images registry (postgres, redis, caddy, pgweb) si absentes ---
echo "Pull images registry..."
docker compose -f docker-compose.dev.yml pull postgres redis caddy pgweb || true

# --- 6) Relance ---
echo "Démarrage docker compose..."
docker compose -f docker-compose.dev.yml up -d --remove-orphans --pull never

echo "OK. Services actifs:"
docker compose -f docker-compose.dev.yml ps
