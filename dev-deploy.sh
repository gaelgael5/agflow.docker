#!/usr/bin/env bash
#
# dev-deploy.sh — Build local + déploiement Docker pour une instance DEV.
#
# Cible : machine de dev (LXC, VM, poste local) avec Docker installé.
# Le script :
#   1. git pull (ou clone si pas encore fait)
#   2. .env : création depuis .env.example si absent (+ génération des secrets
#      aléatoires), sinon sync des nouvelles vars + vérification ADMIN_PASSWORD
#      et ADMIN_PASSWORD_HASH
#   3. Crée le dossier data/ pour les volumes Docker (gitignored)
#   4. Génère la clé SSH backend si absente (/root/.ssh/backend_key)
#   5. Build les images locales backend + frontend
#   6. Down + up de la stack via docker-compose.dev.yml
#
# Usage :
#   ./dev-deploy.sh                       # reste sur la branche courante, pull
#   ./dev-deploy.sh feat/ma-branche       # checkout cette branche, puis pull
#   ./dev-deploy.sh --reset               # DESTRUCTIF : down -v + redeploy
#   ./dev-deploy.sh feat/ma-branche --reset
#
# Le flag --reset force `down -v` (suppression des volumes nommés, dont
# `postgres_data`). Utile pour repartir d'une base fraîche en dev. Ne supprime
# PAS le dossier `data/` (backups, dockerfiles, roles) ni `.env`.
#
# Pour la PROD (pull GHCR, pas de build local), utiliser scripts/refresh.sh.
#
# ─── Réutilisabilité ────────────────────────────────────────────────────────
# Ce script est conçu comme un template. Pour le reprendre dans un autre
# projet, modifier UNIQUEMENT la section « Configuration du projet » ci-dessous
# (PROJECT_NAME, REPO_URL et éventuellement APP_DIR). Tous les noms dérivés —
# images Docker, env vars préfixées, message clé SSH — sont calculés à partir
# de PROJECT_NAME.

set -euo pipefail

# ─── Configuration du projet (À MODIFIER lors d'une réutilisation) ──────────
PROJECT_NAME="agflow"
PROJECT_NAME_UPPER="$(echo "$PROJECT_NAME" | tr '[:lower:]' '[:upper:]')"
REPO_URL="${REPO_URL:-git@github.com:gaelgael5/agflow.docker.git}"
# Nom du dossier local de clone. Pour agflow.docker on garde le nom historique
# du repo (sinon le clone tomberait dans `./agflow/` et casserait les
# scripts qui assument `agflow.docker/`).
APP_DIR_NAME="agflow.docker"

COMPOSE_FILE="docker-compose.dev.yml"

# Parse args : on accepte un mix « branche optionnelle » + « flags --xxx ».
# Tout ce qui commence par `--` est un flag ; le reste est la branche.
TARGET_BRANCH=""
RESET_DATA=0
for arg in "$@"; do
  case "$arg" in
    --reset)
      RESET_DATA=1
      ;;
    --*)
      echo "✗ Flag inconnu : ${arg}" >&2
      echo "  Flags supportés : --reset" >&2
      exit 1
      ;;
    *)
      if [ -n "$TARGET_BRANCH" ]; then
        echo "✗ Plusieurs branches passées en argument : '${TARGET_BRANCH}' et '${arg}'" >&2
        exit 1
      fi
      TARGET_BRANCH="$arg"
      ;;
  esac
done

# ─── 0) Pré-requis : Docker installé ─────────────────────────────────────────

if ! command -v docker >/dev/null 2>&1; then
  cat >&2 <<EOF
✗ Docker n'est pas installé sur ce serveur.

Installer Docker sur Debian/Ubuntu :
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable --now docker

Ou si tu utilises un LXC Proxmox, le recréer avec le flag --docker :
    bash <(wget -qO- .../create-lxc.sh) <CTID> ${PROJECT_NAME}-dev --docker

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
  APP_DIR="$APP_DIR_NAME"
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

# Upsert idempotent d'une variable dans un .env :
#   - substitue la ligne `KEY=...` si la clé existe déjà
#   - append `KEY=value` sinon
#
# Implémenté via awk (et non sed) pour gérer correctement les valeurs
# contenant `$`, `/`, `#`, `&`, etc. Cas critique : les hashes bcrypt
# (`$2b$12$...`) sont mangés par bash dans un `sed -i "s#…#${value}#"`
# car bash interpole `$2`, `$2y`, … avant que sed ne voie la chaîne.
# `awk -v v="$value"` passe la valeur littéralement, sans réinterprétation.
set_env_value() {
  local file="$1" key="$2" value="$3"
  local tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { matched = 0 }
    {
      if ($0 ~ "^" k "=") {
        print k "=" v
        matched = 1
      } else {
        print
      }
    }
    END { if (!matched) print k "=" v }
  ' "$file" > "$tmp" && mv "$tmp" "$file"
}

# Alias historique — l'upsert est désormais le comportement par défaut.
upsert_env_value() {
  set_env_value "$@"
}

# Lit la valeur d'une variable depuis .env. Retourne une chaîne vide si le
# fichier n'existe pas ou si la clé est absente. La valeur conserve les
# espaces internes ; on strip uniquement le \r terminal (fichiers édités
# sous Windows).
read_env_var() {
  local key="$1"
  [ -f ".env" ] || return 0
  awk -F'=' -v k="$key" '$1 == k {sub(/^[^=]*=/, ""); print; exit}' .env | tr -d '\r'
}

# Calcule le hash bcrypt d'un mot de passe en clair. Stdout = hash bcrypt.
# Hypothèse : `ensure_bcrypt_available` a été appelée et a réussi en amont.
# Stderr n'est PAS muselé : si bcrypt explose à l'exécution (cas pathologique
# de cffi mal lié, etc.), on veut voir la stacktrace plutôt qu'écrire un
# .env silencieusement vide.
bcrypt_hash() {
  local password="$1"
  python3 - "$password" <<'PY'
import sys
import bcrypt
pwd = sys.argv[1].encode()
print(bcrypt.hashpw(pwd, bcrypt.gensalt()).decode())
PY
}

# Vérifie que python3 + bcrypt sont opérationnels. Test FONCTIONNEL (un
# hashpw réel) plutôt qu'un simple `import` : sur certaines installs,
# `import bcrypt` réussit mais `bcrypt.hashpw` échoue (cffi cassé,
# binaires manquants, etc.).
# Si manque et qu'on a apt, on tente d'installer python3-bcrypt
# automatiquement (script de dev → on s'autorise à modifier l'env). Sinon
# on renvoie 1 — l'appelant doit prendre une décision (typiquement: exit).
ensure_bcrypt_available() {
  if python3 -c "import bcrypt; bcrypt.hashpw(b'x', bcrypt.gensalt())" >/dev/null 2>&1; then
    return 0
  fi
  if command -v apt-get >/dev/null 2>&1; then
    echo "      python3-bcrypt indisponible — installation via apt..."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-bcrypt >/dev/null 2>&1 || true
  fi
  if python3 -c "import bcrypt; bcrypt.hashpw(b'x', bcrypt.gensalt())" >/dev/null 2>&1; then
    echo "      ✓ python3-bcrypt installé."
    return 0
  fi
  return 1
}

# Ajoute au .env les clés présentes dans .env.example mais manquantes côté
# local (typiquement : nouvelles variables introduites par un git pull). Les
# valeurs existantes ne sont JAMAIS écrasées — on ajoute seulement les clés
# absentes, avec la valeur par défaut du .env.example.
sync_new_vars_from_example() {
  local env_file=".env" example_file=".env.example"
  [ -f "$env_file" ] || return 0
  [ -f "$example_file" ] || return 0
  local added=()
  while IFS= read -r line; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    local key="${line%%=*}"
    [ -z "$key" ] && continue
    if ! grep -qE "^${key}=" "$env_file"; then
      if [ ${#added[@]} -eq 0 ]; then
        {
          echo ""
          echo "# Nouvelles variables ajoutées par dev-deploy.sh ($(date -I))"
        } >> "$env_file"
      fi
      echo "$line" >> "$env_file"
      added+=("$key")
    fi
  done < "$example_file"
  if [ ${#added[@]} -gt 0 ]; then
    echo "      + ${#added[@]} nouvelle(s) variable(s) ajoutée(s) au .env :"
    for k in "${added[@]}"; do
      echo "          - ${k}"
    done
  fi
}

# Garantit que ADMIN_PASSWORD (clair) et ADMIN_PASSWORD_HASH (bcrypt) sont
# remplis dans .env. Logique :
#   - ADMIN_PASSWORD vide   → génère un mot de passe aléatoire et l'inscrit
#   - ADMIN_PASSWORD_HASH vide → recalcule le hash bcrypt depuis ADMIN_PASSWORD
# Si on regénère ADMIN_PASSWORD, le hash existant est invalidé et recalculé
# automatiquement. Idempotent : si les deux sont déjà remplis, ne fait rien.
ensure_admin_credentials() {
  local file=".env"
  [ -f "$file" ] || return 0

  local current_pass current_hash
  current_pass="$(read_env_var ADMIN_PASSWORD)"
  current_hash="$(read_env_var ADMIN_PASSWORD_HASH)"

  local pass_was_generated=0
  if [ -z "$current_pass" ]; then
    current_pass="$(gen_urlsafe 24)"
    upsert_env_value "$file" "ADMIN_PASSWORD" "$current_pass"
    pass_was_generated=1
    # Le hash existant (s'il y en avait un) ne correspond plus au nouveau pass.
    current_hash=""
    echo "      ✓ ADMIN_PASSWORD régénéré (était vide)"
  fi

  if [ -z "$current_hash" ]; then
    if ! ensure_bcrypt_available; then
      echo "      ✗ python3-bcrypt indisponible et installation automatique échouée." >&2
      echo "         Installer manuellement : apt install python3-bcrypt" >&2
      echo "         Puis relancer ./dev-deploy.sh" >&2
      exit 1
    fi
    local new_hash
    new_hash="$(bcrypt_hash "$current_pass")"
    if [ -z "$new_hash" ] || [ "${new_hash#\$2}" = "$new_hash" ]; then
      echo "      ✗ bcrypt_hash a retourné une valeur invalide : '${new_hash}'" >&2
      echo "         (un hash bcrypt commence par \$2a/\$2b/\$2y)" >&2
      exit 1
    fi
    set_env_value "$file" "ADMIN_PASSWORD_HASH" "$new_hash"

    # Sanity check : on relit la valeur écrite. Si elle ne ressemble plus
    # à un bcrypt, on a un bug dans set_env_value et il faut planter
    # immédiatement plutôt que de produire un .env inutilisable.
    local readback
    readback="$(read_env_var ADMIN_PASSWORD_HASH)"
    if [ -z "$readback" ] || [ "${readback#\$2}" = "$readback" ]; then
      echo "      ✗ Hash relu depuis .env corrompu : '${readback}'" >&2
      echo "         Le hash a été calculé correctement mais l'écriture .env l'a abîmé." >&2
      exit 1
    fi
    echo "      ✓ ADMIN_PASSWORD_HASH régénéré (bcrypt depuis ADMIN_PASSWORD)"
  fi

  # Si on a généré le pass cette fois, on l'affiche en clair une fois pour
  # que l'admin puisse le copier sans aller fouiller dans .env.
  if [ "$pass_was_generated" = "1" ]; then
    echo "      → Nouveau mot de passe admin : ${current_pass}"
  fi
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
    set_env_value .env "${PROJECT_NAME_UPPER}_INFRA_KEY" "$INFRA_KEY"

    # ADMIN_PASSWORD + ADMIN_PASSWORD_HASH : générés via la routine partagée
    # (idempotente). À ce stade les deux sont vides → génération complète.
    ensure_admin_credentials

    # `.env` contient des secrets : restreindre les permissions.
    chmod 600 .env

    echo "      ✓ POSTGRES_PASSWORD                    : généré ($(echo -n "$PG_PASS" | wc -c) chars)"
    echo "      ✓ JWT_SECRET                           : généré ($(echo -n "$JWT_SECRET" | wc -c) chars)"
    echo "      ✓ API_KEY_SALT                         : généré ($(echo -n "$API_SALT" | wc -c) chars)"
    echo "      ✓ ${PROJECT_NAME_UPPER}_INFRA_KEY      : généré (clé Fernet)"
    echo
    echo "      ⚠  À RENSEIGNER MANUELLEMENT dans .env :"
    echo "         - ADMIN_EMAIL                (si autre que admin@${PROJECT_NAME}.example.com)"
    echo "         - HARPOCRATE_KEY / URL        (token hrpv_1_* fourni par le coffre)"
    echo "         - KEYCLOAK_* + AUTH_MODE      (si auth OIDC Keycloak)"
  else
    echo "[2/6] ⚠  .env absent et .env.example introuvable — config requise pour démarrer"
  fi
else
  echo "[2/6] .env déjà présent — sync des nouvelles vars + vérification admin..."
  sync_new_vars_from_example
  ensure_admin_credentials
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
  ssh-keygen -t ed25519 -f /root/.ssh/backend_key -N "" -C "${PROJECT_NAME}-backend" -q
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

echo "[5/6] Build de ${PROJECT_NAME}-backend:latest..."
docker build -t "${PROJECT_NAME}-backend:latest" backend/

echo "      Build de ${PROJECT_NAME}-frontend:latest..."
docker build -t "${PROJECT_NAME}-frontend:latest" frontend/

# ─── 6) Stop + cleanup orphelins + pull registry + up ────────────────────────

echo "[6/6] Arrêt de la stack (incl. orphelins)..."
if [ "$RESET_DATA" = "1" ]; then
  # `down -v` supprime aussi les volumes nommés (postgres_data, caddy_data,
  # caddy_config). Les bind mounts (`./data`, `/root/.ssh/backend_key`) ne
  # sont jamais touchés par Compose.
  echo "      ⚠  --reset : down -v (suppression des volumes nommés, DESTRUCTIF)..."
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true
  echo "      ✓ Volumes nommés supprimés — Postgres se réinitialisera avec POSTGRES_PASSWORD du .env"
else
  docker compose -f "$COMPOSE_FILE" down --remove-orphans || true
fi

echo "      Pull images registry (tous les services avec image:, skip les build:)..."
# `docker compose pull` sans argument pull tous les services qui ont une
# `image:` (postgres, redis, caddy, pgweb…) et skip automatiquement ceux
# qui ont un `build:` (backend, frontend custom). Plus robuste qu'un
# listing explicite : si on ajoute un nouveau service registry au compose,
# pas besoin de mettre à jour ce script.
docker compose -f "$COMPOSE_FILE" pull || true

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

# ─── Affichage credentials admin local ──────────────────────────────────────
# Rappel à chaque déploiement : login + mot de passe admin. Évite à l'admin
# d'aller fouiller dans .env quand il lance le script depuis une nouvelle
# session. Affiché uniquement si les deux valeurs sont présentes.
ADMIN_EMAIL_VAL="$(read_env_var ADMIN_EMAIL)"
ADMIN_PWD_VAL="$(read_env_var ADMIN_PASSWORD)"
if [ -n "$ADMIN_EMAIL_VAL" ] && [ -n "$ADMIN_PWD_VAL" ]; then
  cat <<EOF
  → Admin local :
      email    : ${ADMIN_EMAIL_VAL}
      password : ${ADMIN_PWD_VAL}
═════════════════════════════════════════════════════════════════
EOF
fi
