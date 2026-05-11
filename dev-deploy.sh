#!/usr/bin/env bash
#
# dev-deploy.sh — Build local + déploiement Docker pour une instance DEV.
#
# Cible : machine de dev (LXC, VM, poste local) avec Docker installé.
# Le script :
#   1. git pull (ou clone si pas encore fait)
#   2. Crée .env depuis .env.example si absent, génère les secrets aléatoires
#   3. Crée le dossier data/ pour les volumes Docker (gitignored)
#   4. Génère la clé SSH backend si absente (/root/.ssh/backend_key)
#   5. Build les images locales backend + frontend
#   6. Down + up de la stack via docker-compose.dev.yml
#
# Usage :
#   ./dev-deploy.sh                       # reste sur la branche courante, pull
#   ./dev-deploy.sh feat/ma-branche       # checkout cette branche, puis pull
#
# Pour la PROD (pull GHCR, pas de build local), utiliser scripts/refresh.sh.

set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:gaelgael5/agflow.docker.git}"
COMPOSE_FILE="docker-compose.dev.yml"

# Branche cible : argument positionnel optionnel. Si absent, on reste sur la
# branche courante du repo (pas de switch automatique).
TARGET_BRANCH="${1:-}"

# ─── 0) Pré-requis : Docker installé ─────────────────────────────────────────

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<'EOF'
✗ Docker n'est pas installé sur ce serveur.

Installer Docker sur Debian/Ubuntu :
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable --now docker

Ou si tu utilises un LXC Proxmox, le recréer avec le flag --docker :
    bash <(wget -qO- .../create-lxc.sh) <CTID> agflow-docker-dev --docker

Puis relancer ./dev-deploy.sh.
EOF
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "✗ Docker Compose v2 manquant (commande 'docker compose' absente)." >&2
  echo "  Installer le plugin compose : sudo apt install docker-compose-plugin" >&2
  exit 1
fi

# ─── 1) Positionnement dans le repo ─────────────────────────────────────────

if [ -d ".git" ]; then
  if [ -n "$TARGET_BRANCH" ]; then
    echo "[1/6] Repo détecté dans $(pwd) — switch vers ${TARGET_BRANCH}..."
    git fetch origin
    git checkout "$TARGET_BRANCH"
    git pull --ff-only origin "$TARGET_BRANCH"
  else
    CURRENT_BRANCH="$(git branch --show-current)"
    echo "[1/6] Repo détecté dans $(pwd) — pull branche courante (${CURRENT_BRANCH})..."
    git pull --ff-only
  fi
else
  APP_DIR="agflow.docker"
  if [ -d "$APP_DIR/.git" ]; then
    if [ -n "$TARGET_BRANCH" ]; then
      echo "[1/6] Repo dans ./${APP_DIR} — switch vers ${TARGET_BRANCH}..."
      git -C "$APP_DIR" fetch origin
      git -C "$APP_DIR" checkout "$TARGET_BRANCH"
      git -C "$APP_DIR" pull --ff-only origin "$TARGET_BRANCH"
    else
      CURRENT_BRANCH="$(git -C "$APP_DIR" branch --show-current)"
      echo "[1/6] Repo dans ./${APP_DIR} — pull branche courante (${CURRENT_BRANCH})..."
      git -C "$APP_DIR" pull --ff-only
    fi
  else
    # Premier clone : on demande explicitement une branche cible (sinon
    # on ne sait pas laquelle prendre — pas de "branche courante" possible).
    if [ -z "$TARGET_BRANCH" ]; then
      echo "[1/6] Aucun repo trouvé. Premier clone — précise la branche en argument :"
      echo "      ./dev-deploy.sh main"
      exit 1
    fi
    echo "[1/6] Clone du repo dans ./${APP_DIR} (branche ${TARGET_BRANCH})..."
    git clone --branch "$TARGET_BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  cd "$APP_DIR"
fi

# ─── 2) .env ─────────────────────────────────────────────────────────────────

# Génère un secret URL-safe de N chars (base64-derived, sans +/=).
# Utilisable directement dans une URL ou un DSN sans escape.
gen_urlsafe() {
  openssl rand -base64 48 | tr '+/' '-_' | tr -d '=' | head -c "${1:-32}"
}

# Génère une clé Fernet (base64url de 32 bytes aléatoires) avec stdlib Python.
# La bibliothèque cryptography n'est pas requise.
gen_fernet_key() {
  python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
}

# Substitue la valeur d'une clé `KEY=...` dans un .env.
# Délimiteur sed = `#` pour ne pas être gêné par `/` (présent dans base64).
# Les valeurs générées ne contiennent ni `#` ni `&` (caractères spéciaux sed).
set_env_value() {
  local file="$1" key="$2" value="$3"
  sed -i "s#^${key}=.*#${key}=${value}#" "$file"
}

# Détecte l'IPv4 de l'interface eth0.
detect_eth0_ip() {
  ip -4 -o addr show dev eth0 2>/dev/null \
    | awk '{print $4}' | cut -d/ -f1 | head -1
}

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo "[2/6] .env absent → création depuis .env.example + génération secrets aléatoires"
    cp .env.example .env

    # Secrets auto-générés : tout ce qui PEUT être random sans casser l'usage.
    # HARPOCRATE_KEY et HARPOCRATE_URL restent à renseigner manuellement.
    PG_PASS="$(gen_urlsafe 32)"
    JWT_SECRET="$(gen_urlsafe 48)"
    API_SALT="$(gen_urlsafe 32)"
    INFRA_KEY="$(gen_fernet_key)"

    # POSTGRES_PASSWORD apparaît dans DATABASE_URL et en variable propre.
    sed -i "s#REPLACE_ME_WITH_STRONG_PASSWORD#${PG_PASS}#g" .env
    set_env_value .env "JWT_SECRET" "$JWT_SECRET"
    set_env_value .env "API_KEY_SALT" "$API_SALT"
    set_env_value .env "AGFLOW_INFRA_KEY" "$INFRA_KEY"

    # ADMIN_PASSWORD_HASH : nécessite python3 + bcrypt. Génère un mot de passe
    # aléatoire et essaie de le hasher. Si bcrypt absent, affiche le mdp en
    # clair pour que l'admin puisse le hasher manuellement.
    ADMIN_PASS="$(gen_urlsafe 24)"
    set_env_value .env "ADMIN_PASSWORD" "$ADMIN_PASS"
    if python3 -c "import bcrypt" 2>/dev/null; then
      ADMIN_HASH="$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'${ADMIN_PASS}', bcrypt.gensalt()).decode())")"
      set_env_value .env "ADMIN_PASSWORD_HASH" "$ADMIN_HASH"
      ADMIN_HASH_OK=1
    else
      ADMIN_HASH_OK=0
    fi

    # `.env` contient des secrets : restreindre les permissions.
    chmod 600 .env

    echo "      ✓ POSTGRES_PASSWORD : généré ($(echo -n "$PG_PASS" | wc -c) chars)"
    echo "      ✓ JWT_SECRET        : généré ($(echo -n "$JWT_SECRET" | wc -c) chars)"
    echo "      ✓ API_KEY_SALT      : généré ($(echo -n "$API_SALT" | wc -c) chars)"
    echo "      ✓ AGFLOW_INFRA_KEY  : généré (clé Fernet)"
    echo "      ✓ ADMIN_PASSWORD    : généré (stocké dans .env)"
    if [ "$ADMIN_HASH_OK" -eq 1 ]; then
      echo "      ✓ ADMIN_PASSWORD_HASH : généré (bcrypt)"
    else
      echo "      ⚠  ADMIN_PASSWORD_HASH : bcrypt absent — à renseigner manuellement :"
      echo "         python3 -c \"import bcrypt; print(bcrypt.hashpw(b'MOT_DE_PASSE', bcrypt.gensalt()).decode())\""
    fi
    echo
    echo "      ⚠  Login admin : ${ADMIN_EMAIL:-admin@agflow.local} / ${ADMIN_PASS}"
    echo "         (stocké dans .env — chmod 600)"
    echo
    echo "      ⚠  À RENSEIGNER MANUELLEMENT dans .env :"
    echo "         - ADMIN_EMAIL                (si autre que admin@agflow.local)"
    echo "         - HARPOCRATE_KEY / URL        (token hrpv_1_* fourni par le coffre)"
    echo "         - KEYCLOAK_* + AUTH_MODE      (si auth OIDC Keycloak)"
  else
    echo "[2/6] ⚠  .env absent et .env.example introuvable — config requise pour démarrer"
  fi
else
  echo "[2/6] .env déjà présent (secrets non régénérés)."
fi

# ─── 3) Dossier data/ pour volumes Docker (ignoré par .gitignore) ────────────

echo "[3/6] Création du dossier data/ (gitignored) si absent..."
mkdir -p data
# UID 1001 = user applicatif dans le container backend.
# `|| true` car en local Windows/MINGW, chown n'est pas utile.
chown -R 1001:1001 data 2>/dev/null || true

# ─── 4) Clé SSH backend (connexion aux machines infra) ───────────────────────

if [ ! -f /root/.ssh/backend_key ]; then
  echo "[4/6] Génération de la clé SSH backend (/root/.ssh/backend_key)..."
  mkdir -p /root/.ssh
  ssh-keygen -t ed25519 -f /root/.ssh/backend_key -N "" -C "agflow-backend" -q
  chmod 600 /root/.ssh/backend_key
  echo "      ✓ Clé générée."
  echo "      Clé publique à ajouter sur les machines infra cibles :"
  echo
  cat /root/.ssh/backend_key.pub
  echo
else
  echo "[4/6] Clé SSH backend existante conservée."
fi

# ─── 5) Build images locales ─────────────────────────────────────────────────

echo "[5/6] Build de agflow-backend:latest..."
docker build -t agflow-backend:latest backend/

echo "      Build de agflow-frontend:latest..."
docker build -t agflow-frontend:latest frontend/

# ─── 6) Stop + cleanup orphelins + pull registry + up ────────────────────────

echo "[6/6] Arrêt de la stack (incl. orphelins)..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans || true

echo "      Pull images registry (postgres, redis, caddy, pgweb)..."
docker compose -f "$COMPOSE_FILE" pull postgres redis caddy pgweb || true

echo "      Démarrage de la stack..."
docker compose -f "$COMPOSE_FILE" up -d --remove-orphans --pull never

echo
echo "✓ Déploiement DEV terminé. Services :"
docker compose -f "$COMPOSE_FILE" ps
echo
echo "Logs en direct :"
echo "  docker compose -f ${COMPOSE_FILE} logs -f backend"
echo "  docker compose -f ${COMPOSE_FILE} logs -f frontend"
echo

# ─── Affichage final : URL d'accès ───────────────────────────────────────────
ETH0_IP="$(detect_eth0_ip)"
HOST="${ETH0_IP:-localhost}"

cat <<EOF
═════════════════════════════════════════════════════════════════
  UI       →  http://${HOST}:80
  API      →  http://${HOST}:8000/health
  pgweb    →  http://${HOST}:8081
═════════════════════════════════════════════════════════════════
EOF
