# Spec — Build des images Docker via GitHub Actions + publication GHCR

> **Statut** : design validé 2026-04-29 — prêt pour le plan d'implémentation
> **Auteur** : brainstorming Claude + utilisateur
> **Initiative parente** : étape 1 de la migration progressive de la livraison agflow.docker vers Docker Swarm
> **Préalable** : `2026-04-29-export-data-volume-design.md` (backup du volume avant bascule)

## 1. Contexte et objectif

Aujourd'hui :

- `scripts/deploy.sh` package localement un tarball (Dockerfiles + sources + migrations) et le pousse sur LXC 201 via `pct push`
- `docker build` est exécuté **sur le LXC** à chaque déploiement
- `docker-compose.prod.yml` référence des images locales `agflow-backend:latest` / `agflow-frontend:latest`, jamais publiées

Cible de cette initiative :

- Les images Docker **backend** et **frontend** sont buildées par **GitHub Actions** sur push `main`
- Elles sont publiées sur **GitHub Container Registry (GHCR)**, en **privé**
- Le LXC 201 **pull** ces images au lieu de les builder
- `deploy.sh` est simplifié : il ne package plus que la conf (`.env`, `docker-compose.prod.yml`, `Caddyfile`) et fait `compose pull && up -d`

**Cette initiative ne touche PAS** :
- Docker Swarm — c'est l'étape suivante
- L'authentification déploiement automatique — `deploy.sh` reste lancé manuellement

## 2. Décisions verrouillées

| Décision | Choix | Raison |
|----------|-------|--------|
| Registry | **GHCR** (`ghcr.io/gaelgael5/agflow-{backend,frontend}`) | Auth GitHub native, gratuit en privé, plus tard Docker Hub quand stable |
| Visibilité | **Privé** | Code métier, pas exposable publiquement |
| Trigger | **Push `main` uniquement** + `workflow_dispatch` manuel | Pas de PR/feature branches, pas de tags versionnés en V1 |
| Tags | **`:latest` uniquement** | Simple, rollback non-traité en V1 |
| Architectures | **`linux/amd64`** seul | LXC 201 est amd64 |
| Cache build | **`type=gha`** (cache GitHub Actions natif) | Gratuit, ~10 GB, géré par GitHub |
| Path filtering | Oui, via `dorny/paths-filter` | Évite de rebuilder backend si seul `frontend/**` a bougé |
| Auth pull côté LXC | **PAT GitHub `read:packages`** stocké via `docker login ghcr.io` | Setup manuel une seule fois |
| Auth push côté CI | `secrets.GITHUB_TOKEN` (token éphémère du runner) | Aucun secret manuel à gérer |
| `deploy.sh` | Simplifié : tarball réduit, `compose pull && up -d` | Plus de `--rebuild`, plus de tarball lourd |

## 3. Architecture

### 3.1 Workflow CI — `.github/workflows/build-images.yml` (NOUVEAU)

```yaml
name: Build & publish images

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      force_all:
        description: "Build both images regardless of paths"
        type: boolean
        default: false

permissions:
  contents: read
  packages: write          # required to push to GHCR

jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      backend:  ${{ steps.f.outputs.backend }}
      frontend: ${{ steps.f.outputs.frontend }}
    steps:
      - uses: actions/checkout@v4
      - id: f
        uses: dorny/paths-filter@v3
        with:
          filters: |
            backend:
              - 'backend/**'
            frontend:
              - 'frontend/**'

  build-backend:
    needs: changes
    if: ${{ needs.changes.outputs.backend == 'true' || inputs.force_all }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: ./backend
          file: ./backend/Dockerfile
          platforms: linux/amd64
          push: true
          tags: ghcr.io/gaelgael5/agflow-backend:latest
          cache-from: type=gha,scope=backend
          cache-to:   type=gha,scope=backend,mode=max

  build-frontend:
    needs: changes
    if: ${{ needs.changes.outputs.frontend == 'true' || inputs.force_all }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: ./frontend
          file: ./frontend/Dockerfile
          platforms: linux/amd64
          push: true
          tags: ghcr.io/gaelgael5/agflow-frontend:latest
          cache-from: type=gha,scope=frontend
          cache-to:   type=gha,scope=frontend,mode=max
```

### 3.2 Modification `docker-compose.prod.yml`

Diff :

```diff
   backend:
-    image: agflow-backend:latest
+    image: ghcr.io/gaelgael5/agflow-backend:latest
     ...

   frontend:
-    image: agflow-frontend:latest
+    image: ghcr.io/gaelgael5/agflow-frontend:latest
     ...
```

Aucune autre modification du compose.

### 3.3 Modification `scripts/deploy.sh`

**Avant** : packagait `.env`, `docker-compose.prod.yml`, `Caddyfile`, **`backend/`** (Dockerfile + pyproject + src + migrations), **`frontend/`** (Dockerfile + nginx.conf + package.json + tsconfig + vite + tailwind + postcss + index.html + src). Build local sur LXC via `--rebuild`.

**Après** :

```bash
#!/usr/bin/env bash
###############################################################################
# Deploy agflow.docker to LXC 201 (192.168.10.158)
#
# Prereqs :
#   - ssh alias `pve` in ~/.ssh/config
#   - CT 201 has Docker + Compose installed
#   - Local repo has a .env file with production values (never committed)
#   - CT 201 is logged in to ghcr.io with a PAT (`docker login ghcr.io ...`)
#     so it can pull ghcr.io/gaelgael5/agflow-{backend,frontend}:latest
#
# Usage : ./scripts/deploy.sh
###############################################################################
set -euo pipefail

CTID="${CTID:-201}"
REPO_DIR_ON_CT="/root/agflow.docker"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -f .env ]; then
    echo "ERROR: .env missing. Copy .env.example to .env and fill in real values."
    exit 1
fi

echo "==> Packaging deploy context (.env + compose + Caddyfile)..."
tar czf /tmp/agflow-deploy.tar.gz .env docker-compose.prod.yml Caddyfile

echo "==> Uploading to pve..."
scp /tmp/agflow-deploy.tar.gz pve:/tmp/

echo "==> Pushing into CT ${CTID} and extracting..."
ssh pve "pct push ${CTID} /tmp/agflow-deploy.tar.gz /tmp/agflow-deploy.tar.gz && \
         pct exec ${CTID} -- bash -c '
           mkdir -p ${REPO_DIR_ON_CT} ${REPO_DIR_ON_CT}/data
           cd ${REPO_DIR_ON_CT} && tar xzf /tmp/agflow-deploy.tar.gz
         '"

echo "==> Pulling latest images from GHCR on CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && docker compose -f docker-compose.prod.yml pull backend frontend'"

echo "==> Restarting stack on CT ${CTID}..."
ssh pve "pct exec ${CTID} -- bash -c 'cd ${REPO_DIR_ON_CT} && docker compose -f docker-compose.prod.yml up -d && sleep 3 && docker compose -f docker-compose.prod.yml ps'"

echo ""
echo "==> Deployed. Smoke test:"
echo "    curl http://192.168.10.158/health"
```

Disparu : flag `--rebuild`, packaging des sources, étape `docker build` distante. Apparu : `docker compose pull` explicite avant le `up`.

### 3.4 Setup PAT côté LXC 201 (manuel, une fois)

Procédure documentée — exécutée par l'utilisateur, guidée par Claude au moment voulu :

1. **Côté GitHub** : Settings → Developer settings → Personal access tokens (classic) → Generate new token (classic)
   - Nom : `agflow-docker LXC 201 pull`
   - Expiration : custom (ex: 1 an)
   - Scope : **`read:packages`** uniquement
   - Copier le token (`ghp_...`)
2. **Côté LXC 201** :
   ```bash
   ssh pve "pct exec 201 -- bash -c 'echo <PAT> | docker login ghcr.io -u gaelgael5 --password-stdin'"
   ```
3. Vérifier : `ssh pve "pct exec 201 -- docker pull ghcr.io/gaelgael5/agflow-backend:latest"` (après le premier build CI)
4. Le credential est persisté dans `/root/.docker/config.json` du LXC

## 4. Migration progressive (sans casse)

| Étape | Action | Validation |
|-------|--------|------------|
| 0 | Pré-requis : avoir exporté le volume `data/` (cf. spec Export) | Archive `.zip` archivée hors LXC |
| A | Ajouter `.github/workflows/build-images.yml` dans une branche, merger | Première run via `workflow_dispatch` `force_all=true`. Vérifier les 2 images sur https://github.com/gaelgael5?tab=packages |
| B | Setup PAT côté LXC 201 (étape 3.4) | `docker pull ghcr.io/gaelgael5/agflow-backend:latest` réussit côté LXC |
| C | Modifier `docker-compose.prod.yml` (images GHCR) + `deploy.sh` (simplifié) | Premier déploiement via images GHCR, smoke test : `curl http://192.168.10.158/health` |

Si étape C foire, rollback :
- `git revert` du commit qui change compose + deploy.sh
- Relancer l'ancien `deploy.sh` qui rebuild local

## 5. Tests

### 5.1 CI — manuel via `workflow_dispatch`

Premier run : déclencher manuellement avec `force_all=true` après merge du workflow. Vérifier :

- [ ] Job `changes` sort `backend=true` et `frontend=true` (input forcé)
- [ ] Jobs `build-backend` et `build-frontend` réussissent en parallèle
- [ ] Images visibles sous github.com/gaelgael5?tab=packages
- [ ] `docker pull ghcr.io/gaelgael5/agflow-backend:latest` réussit côté LXC après login

Run suivant (push main réel) : modifier un fichier dans `backend/`, push. Vérifier :

- [ ] `changes.outputs.backend == 'true'`, `frontend == 'false'`
- [ ] Job `build-frontend` est skippé
- [ ] Image backend mise à jour, frontend inchangée

### 5.2 Déploiement — manuel

Après étape C :
- [ ] `./scripts/deploy.sh` exécute sans erreur
- [ ] Le tarball uploadé fait < 1 MB (vs ~10 MB avant)
- [ ] `docker compose ps` montre les 2 services healthy
- [ ] `curl http://192.168.10.158/health` répond `200 OK`
- [ ] `curl http://192.168.10.158/api/admin/auth/login -X POST -d ...` répond `200`

## 6. Risques et mitigation

| Risque | Mitigation |
|--------|------------|
| Build CI casse silencieusement (image d'avant utilisée à l'infini) | `docker compose pull` explicite dans `deploy.sh` ; vérifier `docker images` après deploy |
| PAT expire → pull casse | Setup expiration 1 an + alerte calendrier (`/schedule` 11 mois) |
| `docker login` perdu après reboot LXC | Persisté dans `/root/.docker/config.json`, OK par défaut. À confirmer après premier reboot. |
| Cache GHA exponentiellement gros | Limite 10 GB par scope ; GitHub évince automatiquement le LRU |
| Image privée pas trouvée par compose | Tester `docker pull` à la main avant de bouger compose |
| `path-filter` rate un changement transverse (ex: doc compose qui devrait rebuild) | `workflow_dispatch` `force_all=true` toujours dispo |
| Race entre `compose pull` et `up -d` (image récupérée mais conteneur pas redémarré) | `up -d` détecte les nouvelles images et recrée les conteneurs concernés |

## 7. Hors scope (à NE PAS faire dans cette initiative)

- Migration vers Docker Swarm (étape suivante du chantier global)
- Tags `:vX.Y.Z` versionnés / rollback ciblé (à introduire avec Swarm si besoin)
- Tags `:sha-<short>` (peut être ajouté ensuite, peu coûteux)
- Build multi-arch `linux/arm64` (LXC 201 amd64 seul)
- PR builds / preview environments
- Scan Trivy/Grype (à ajouter en V2)
- Auto-deploy via webhook (déclenchement manuel `deploy.sh` reste la règle)
- Docker Hub mirror (V2, "quand stable")
- Migration de la base ou export DB (autre initiative)

## 8. Critères d'acceptation

- [ ] Workflow `build-images.yml` mergé sur `main`
- [ ] Premier run réussit, 2 images visibles sur GHCR (privées)
- [ ] PAT côté LXC fonctionnel, `docker pull` réussit
- [ ] `docker-compose.prod.yml` référence les images GHCR
- [ ] `deploy.sh` simplifié, fonctionne bout en bout
- [ ] Smoke test prod : `/health` répond, login admin marche
- [ ] Path-filter vérifié : un commit `frontend-only` skip le job backend (et inversement)
- [ ] Pas de régression : taille tarball réduite, durée déploiement comparable ou meilleure
