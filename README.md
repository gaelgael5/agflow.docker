# agflow.docker

Plateforme multi-agent orchestrant des agents IA pour le cycle de vie logiciel.
Stack : FastAPI + PostgreSQL (pgvector) + Redis + Docker Compose.

Voir [docs/architecture.md](docs/architecture.md) pour la stack complète et
[CLAUDE.md](CLAUDE.md) pour les conventions du projet.

## License

**agflow.docker** is distributed under the
[PolyForm Noncommercial License 1.0.0](./LICENSE).

You may freely use, modify, and share the source code for
**non-commercial purposes** (personal use, research, education, evaluation).

**Commercial use** (SaaS, hosted services, resale, integration in paid
products, production use by for-profit entities) requires a separate
commercial license.

See [COMMERCIAL-LICENSE.md](./COMMERCIAL-LICENSE.md) for details and to
request a commercial license.

Copyright (c) 2026 gaelgael5 &lt;llm.beard.family@gmail.com&gt;. All rights
reserved.

# Pour tester en mode dev

L'installation se fait en trois étapes exécutées sur l'**hôte Proxmox**, puis dans le **container LXC**.

---

### Étape 1 — Créer le container LXC

Sur l'hôte Proxmox, créer et configurer le LXC (Docker-ready, SSH, réseau DHCP).

> `bash <(wget -qO- URL)` est requis ici (pas `bash -c "$(wget ...)"`) car le script reçoit des arguments positionnels (`$1` = CTID, `$2` = nom).

```bash
bash <(wget -qO- https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC/create-lxc.sh) 203 agflow-docker --docker
```

Remplacer `203` par le CTID souhaité et `agflow-docker` par le nom du container.  
Le flag `--docker` installe Docker automatiquement dans le LXC.



## 🔐 1. Configurer l’accès SSH à GitHub

### 1.1 Générer une clé SSH

Sur la machine cible :

```bash

pct enter 203

ssh-keygen -t ed25519 -C "deploy-roles"
```

Appuyer sur Entrée pour accepter le chemin par défaut :
```bash
~/.ssh/id_ed25519
```

Passphrase :
- laisser vide pour un serveur (déploiement automatique)
- ou en définir une pour plus de sécurité

Démarrer l’agent SSH et charger la clé
```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

cat ~/.ssh/id_ed25519.pub

```



1 - Ajouter la clé dans GitHub
2 - Aller sur GitHub
3 - Settings
4 - (SSH and GPG keys)[https://github.com/settings/keys]
5 - New SSH key
6 - Name : deploy-roles
7 - Coller la clé publique
8 - Cliquer sur Add SSH key


Tester la connexion
```bash
ssh -T git@github.com
```

Cloner le repository
```bash
git clone --branch feat/mom-bus git@github.com:gaelgael5/agflow.docker.git
cd agflow.docker
```

Créer et configurer le fichier `.env`
```bash
cp .env.example .env
nano .env
```

Renseigner au minimum ces valeurs :

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | `postgresql://agflow:agflow_dev@postgres:5432/agflow` |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `ADMIN_EMAIL` | ex: `admin@agflow.local` |
| `ADMIN_PASSWORD_HASH` | `python3 -c "import bcrypt; print(bcrypt.hashpw(b'TONPASSWORD', bcrypt.gensalt()).decode())"` |
| `HARPOCRATE_KEY` | token `hrpv_1_*` fourni par le coffre |
| `HARPOCRATE_URL` | `https://vault.yoops.org` |

Lancer la stack
```bash
bash deploy.sh
```

Affiche les logs
```bash
docker compose -f docker-compose.dev.yml logs --tail=50 backend
docker compose -f docker-compose-dev.yml logs --tail=50 frontend
```


---

### Étape 2 — Initialiser la stack

Télécharge `docker-compose.yml`, `.env.example` et `refresh.sh` dans `/opt/harpocrate`, puis crée un `.env` prêt à éditer :

```bash
pct exec 202 -- bash -c "$(wget -qLO - https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts/setup.sh)"
```

---

### Étape 3 — Configurer `.env`

Se connecter au container et éditer le fichier :

```bash
pct exec 202 -- bash
nano /opt/harpocrate/.env
```


Auth locale (sans Keycloak) :

```env

```

---

### Étape 5 — Lancer la stack

```bash
pct exec 202 -- bash -c "cd /opt/harpocrate && ./refresh.sh"
```

La stack démarre, les images sont pullées depuis GHCR, les migrations DB sont appliquées au premier boot.

```bash
https://your ip :8443/
```


---

### 4. Configurer `.env`

```env
HARPOCRATE_KEYCLOAK_URL=https://security.yoops.org
HARPOCRATE_KEYCLOAK_REALM=yoops
HARPOCRATE_KEYCLOAK_CLIENT_ID=harpocrate-vault
HARPOCRATE_PUBLIC_URL=https://vault.yoops.org
```

### 5. Vérifier l'intégration

```bash
curl https://vault-api.yoops.org/v1/config/keycloak
```

Réponse attendue :
```json
{
  "realm": "yoops",
  "client_id": "harpocrate-vault",
  "issuer": "https://security.yoops.org/realms/yoops"
}
```

---

## Mise à jour

```bash
pct exec 202 -- bash -c "cd /opt/harpocrate && ./refresh.sh"
```

Pour épingler une version spécifique :

```bash
pct exec 202 -- bash -c "cd /opt/harpocrate && TAG=v1.2.0 ./refresh.sh"
```

---

## Développement local

```bash
# Dépendances infra (Postgres) sur le LXC
ssh pve "pct exec 202 -- bash -c 'cd /opt/harpocrate && docker compose up -d postgres'"

# Backend (hot-reload)
cd backend && uv run uvicorn app.main:app --reload

# Frontend (proxy Vite -> :8000)
cd frontend && npm run dev
```

```bash

# voir les logs du frontend
docker compose -f /opt/harpocrate/docker-compose.yml logs -f frontend

# voir les logs du backend
docker compose -f /opt/harpocrate/docker-compose.yml logs -f backend

```