# Installation environnement de DEV — agflow.docker

Cette procédure monte une instance agflow.docker **complète** (Postgres + Redis +
backend FastAPI + frontend Vite) sur un serveur de dev. Cible : LXC Proxmox, VM,
ou toute machine Linux avec Docker installé.

Pour le **développement local** (Windows, hot-reload sans Docker), voir §
[Développement local (hors container)](#développement-local-hors-container).

---

## Étape 1 — Préparer le serveur

### 1.1 Container LXC (si Proxmox)

Sur l'hôte Proxmox, créer un LXC Docker-ready :

```bash
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 201 agflow-docker-test --docker
```

Remplace `201` par le CTID souhaité et `agflow-docker-test` par le nom du container.
Le flag `--docker` installe Docker dans le LXC.

> **Hors Proxmox** : n'importe quelle machine Linux avec Docker ≥ 24.0 et
> Docker Compose v2 fonctionne. Skipper cette étape, passer directement à 1.2.

### 1.2 Entrer dans le serveur

```bash
pct enter 201                    # depuis l'hôte Proxmox
# ou : ssh user@agflow-docker    # autre serveur
```

---

## Étape 2 — Accès SSH GitHub

Le repo est privé. Génère une clé SSH dédiée au déploiement :

```bash
ssh-keygen -t ed25519 -C "agflow-deploy"
# Entrée pour accepter ~/.ssh/id_ed25519
# Passphrase vide (déploiement automatique)

eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub
```

Ajoute la clé publique sur GitHub :

1. <https://github.com/settings/keys> → **New SSH key**
2. Title : `agflow-dev <hostname>`
3. Coller la clé publique → **Add SSH key**

Tester :

```bash
ssh -T git@github.com
# → Hi gaelgael5! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## Étape 3 — Premier déploiement

### 3.1 Cloner le repo

```bash
cd /opt
git clone git@github.com:gaelgael5/agflow.docker.git
cd agflow.docker
```

Pour une branche spécifique :

```bash
cd /opt
git clone --branch feat/mom-bus git@github.com:gaelgael5/agflow.docker.git
cd agflow.docker
```

### 3.2 Configurer `.env`

```bash
cp .env.example .env
nano .env
```

**Variables obligatoires** :

| Variable | Description | Génération |
|---|---|---|
| `DATABASE_URL` | URL Postgres | `postgresql://agflow:<pass>@postgres:5432/agflow` |
| `POSTGRES_PASSWORD` | Mot de passe Postgres | `openssl rand -hex 32` |
| `JWT_SECRET` | Clé de signature JWT | `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ADMIN_EMAIL` | Email du compte admin local | ex : `admin@agflow.local` |
| `ADMIN_PASSWORD_HASH` | Hash bcrypt du mot de passe admin | voir ci-dessous |
| `API_KEY_SALT` | Sel de hashage des clés API | `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `AGFLOW_INFRA_KEY` | Clé Fernet (chiffrement secrets infra) | `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `HARPOCRATE_KEY` | Token API Harpocrate (`hrpv_1_*`) | fourni par le coffre |
| `HARPOCRATE_URL` | URL du coffre | `https://vault.yoops.org` |

Générer le hash bcrypt du mot de passe admin :

```bash
uv run python -c "import bcrypt; print(bcrypt.hashpw(b'TONPASSWORD', bcrypt.gensalt()).decode())"
```

**Variables optionnelles** (laisser les valeurs par défaut pour un dev local sans Keycloak) :

| Variable | Valeur par défaut | Description |
|---|---|---|
| `AUTH_MODE` | `local` | `local` ou `keycloak` |
| `KEYCLOAK_URL` | — | URL du serveur Keycloak |
| `KEYCLOAK_REALM` | — | Realm Keycloak |
| `KEYCLOAK_CLIENT_ID` | — | Client ID OIDC |
| `KEYCLOAK_CLIENT_SECRET` | — | Secret client Keycloak |
| `ENVIRONMENT` | `dev` | `dev` ou `prod` |
| `LOG_LEVEL` | `INFO` | Niveau de log |
| `HARPOCRATE_ALLOW_INSECURE` | — | `1` si Harpocrate dev avec cert auto-signé |

### 3.3 Lancer la stack

```bash
bash deploy.sh
```

Le script build les images et lance `docker compose -f docker-compose.dev.yml up -d`.

---

## Étape 4 — Vérifier

```bash
docker compose -f docker-compose.dev.yml ps
```

Les services doivent être `healthy` :

```
NAME              STATE     PORTS
agflow-postgres   healthy   127.0.0.1:5432->5432/tcp
agflow-redis      healthy   127.0.0.1:6379->6379/tcp
agflow-backend    healthy   127.0.0.1:8000->8000/tcp
agflow-frontend   healthy   0.0.0.0:5173->5173/tcp
```

Test rapide :

```bash
curl http://127.0.0.1:8000/api/health
```

Logs :

```bash
docker compose -f docker-compose.dev.yml logs -f backend
docker compose -f docker-compose.dev.yml logs -f frontend
docker compose -f docker-compose.dev.yml logs --tail=50 postgres
```

---

## Étape 5 — Workflow de mise à jour

```bash
git pull
bash deploy.sh
```

Le script rebuild les images et redémarre la stack. Les volumes Postgres et Redis
sont préservés.

---

## Développement local (hors container)

Pour itérer rapidement sans rebuild d'image, lancer backend et frontend
**directement sur Windows**, en gardant Postgres + Redis dans Docker sur LXC 201 :

```bash
# Démarrer l'infra sur LXC 201
ssh pve "pct exec 201 -- bash -c 'cd /root/agflow.docker && docker compose up -d'"

# Backend hot-reload (Windows, depuis E:\srcs\agflow.docker)
cd backend
uv sync
uv run uvicorn agflow.main:app --reload --port 8000

# Frontend (Windows) — proxy /api → :8000
cd frontend
npm install
npm run dev
```

UI dev : <http://localhost:5173>

### Commandes de vérification courantes

```bash
# Tests Python
cd backend && uv run pytest -v

# Lint + format
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format src/ tests/

# TypeScript strict check
cd frontend && npx tsc --noEmit

# Lint + format frontend
cd frontend && npm run lint
cd frontend && npm run format

# Migrations DB
cd backend && uv run python -m agflow.db.migrations
```

---

## Configurer le client Keycloak (optionnel)

Si tu veux activer l'auth OIDC (`AUTH_MODE=keycloak`) :

### 1. Créer le client dans Keycloak

Va sur `https://security.yoops.org/admin/` → realm **yoops** → **Clients** → **Create client**

| Onglet | Champ | Valeur |
|---|---|---|
| General | Client type | `OpenID Connect` |
| General | Client ID | `agflow-docker` |
| Capability | Client authentication | **ON** (client confidentiel — nécessaire pour avoir un secret) |
| Capability | Standard flow | **ON** |
| Capability | Direct access grants | OFF |
| Login | Root URL | `http://agflow-docker.home.lan` |
| Login | Valid redirect URIs | `http://agflow-docker.home.lan/*` |
| Login | Web origins | `http://agflow-docker.home.lan` |

→ **Save**

### 2. Récupérer le secret

Onglet **Credentials** → copier le **Client secret** → `.env` :

```env
AUTH_MODE=keycloak
KEYCLOAK_URL=https://security.yoops.org
KEYCLOAK_REALM=yoops
KEYCLOAK_CLIENT_ID=agflow-docker
KEYCLOAK_CLIENT_SECRET=<secret généré par Keycloak>
```

### 3. Rôles (optionnel)

**Realm roles → Create role** : `admin`, `operator`, `viewer`

Le backend lit `resource_access.agflow-docker.roles` dans le token JWT.

### 4. Relancer

```bash
docker compose -f docker-compose.dev.yml restart backend
curl http://agflow-docker.home.lan/api/admin/auth/mode
# → {"mode":"keycloak"}
```

---

## Arborescence après installation

```
/opt/agflow.docker/
├── backend/                    # FastAPI + asyncpg
├── frontend/                   # Vite + React + TypeScript
├── docs/                       # Architecture, patterns, règles dev
├── specs/                      # Spec produit + plans techniques
├── scripts/
│   ├── infra/                  # LXC Proxmox setup
│   └── deploy.sh               # Build + déploiement
├── migrations/                 # SQL bruts numérotés (001_*.sql …)
├── docker-compose.dev.yml      # Stack de dev
├── docker-compose.prod.yml     # Stack de prod
├── .env                        # ← gitignored, config locale
├── .env.example
└── apps.json                   # Menu cross-apps
```

---

## Dépannage

### Backend `unhealthy`

```bash
docker compose -f docker-compose.dev.yml logs --tail=100 backend
```

Causes fréquentes : `DATABASE_URL` incorrecte, `HARPOCRATE_KEY` manquante,
`AGFLOW_INFRA_KEY` absente ou invalide. Le backend log la variable manquante au boot.

### Postgres inaccessible

Vérifier que l'infra sur LXC 201 est bien démarrée :

```bash
ssh pve "pct exec 201 -- docker compose -f /root/agflow.docker/docker-compose.dev.yml ps"
```

### Reset complet de la DB

⚠ Détruit toutes les données :

```bash
docker compose -f docker-compose.dev.yml down -v
bash deploy.sh
```

---

## Documentation

Spec produit complète (7 modules) : [`specs/home.md`](specs/home.md)

Conventions de code et commandes : [`CLAUDE.md`](CLAUDE.md)
