# CI GitHub Actions → GHCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Several tasks contain USER GATES** — actions that must be done by the human (creating GitHub PAT, validating CI run from GitHub UI, etc.). The implementer subagent must STOP at each USER GATE and report what's needed.

**Goal:** Construire les images Docker `agflow-backend` et `agflow-frontend` automatiquement sur GitHub Actions à chaque push `main`, les publier sur GHCR (privé), et basculer le déploiement LXC 201 sur `docker compose pull` au lieu de `docker build`.

**Architecture:** 1 workflow GitHub Actions avec 2 jobs parallèles (path-filter), publication via `docker/build-push-action` + cache `type=gha`, auth push via `GITHUB_TOKEN` éphémère, auth pull côté LXC via PAT classique stocké une fois. `docker-compose.prod.yml` bascule sur les images GHCR ; `scripts/deploy.sh` perd l'étape `docker build` et gagne `docker compose pull`.

**Tech Stack:** GitHub Actions YAML | docker/setup-buildx-action@v3 + docker/login-action@v3 + docker/build-push-action@v6 | dorny/paths-filter@v3 | bash | docker compose v2.

**Spec source:** `docs/superpowers/specs/2026-04-29-github-build-images-design.md`

---

## File Structure

| Fichier | Rôle |
|---------|------|
| `.github/workflows/build-images.yml` (nouveau) | Workflow CI : path-filter + 2 jobs parallèles `build-backend` / `build-frontend` qui pushent sur `ghcr.io/gaelgael5/agflow-{backend,frontend}:latest`. |
| `docker-compose.prod.yml` (modifié, 2 lignes) | Bascule des `image: agflow-backend:latest` (locale) vers `image: ghcr.io/gaelgael5/agflow-backend:latest` (registry). Idem frontend. |
| `scripts/deploy.sh` (modifié, gros allègement) | Tarball réduit à `.env` + `compose` + `Caddyfile`. Plus de `docker build`. Ajout d'un `docker compose pull` avant `up -d`. Suppression du flag `--rebuild`. |

Aucun fichier backend/frontend modifié. Pas de migration DB. Plusieurs USER GATES manuels (génération PAT, premier `workflow_dispatch`, login GHCR sur LXC).

---

## Task 1 — Créer le workflow GitHub Actions

**Files:**
- Create: `.github/workflows/build-images.yml`

- [ ] **Step 1 : Vérifier qu'aucun workflow n'existe**

```bash
ls .github/workflows/ 2>/dev/null || echo "no .github/workflows yet"
```

Attendu : `no .github/workflows yet` (le repo n'a pas encore de CI).

- [ ] **Step 2 : Créer le workflow**

Créer `.github/workflows/build-images.yml` :

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
  packages: write

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

- [ ] **Step 3 : Vérification syntaxe YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/build-images.yml'))" && echo ok
```

Attendu : `ok` (parsing YAML réussi, pas d'erreur d'indentation).

- [ ] **Step 4 : Commit**

```bash
git add .github/workflows/build-images.yml
git commit -m "ci: workflow build-images publie agflow-backend/frontend sur GHCR"
```

---

## Task 2 — USER GATE : pousser la branche et déclencher la première build

> **Cette task est manuelle.** L'agent doit STOPPER ici et reporter ce qui est attendu côté utilisateur.

**Files:** Aucun changement local.

- [ ] **Step 1 : Pousser la branche `feat/mom-bus`**

```bash
git push -u origin feat/mom-bus
```

Attendu : le push s'effectue, la branche apparaît sur https://github.com/gaelgael5/agflow.docker/branches

- [ ] **Step 2 : Déclencher la première build manuellement**

1. Aller sur https://github.com/gaelgael5/agflow.docker/actions
2. Cliquer sur le workflow "Build & publish images" dans la sidebar gauche
3. Cliquer sur "Run workflow" (bouton à droite)
4. Sélectionner :
   - Branch : `feat/mom-bus`
   - `force_all` : ✅ true (case cochée)
5. Cliquer "Run workflow" pour confirmer

- [ ] **Step 3 : Vérifier le run**

Attendre que les 3 jobs terminent (job `changes` instant, puis `build-backend` et `build-frontend` en parallèle, ~3-8 min chacun la première fois — beaucoup plus rapide ensuite grâce au cache GHA).

Attendu :
- ✅ `changes` (vert) — outputs `backend=true`, `frontend=true` puisque `force_all=true`
- ✅ `build-backend` (vert) — image poussée avec succès vers GHCR
- ✅ `build-frontend` (vert) — image poussée avec succès vers GHCR

Si un job rouge : ouvrir les logs, identifier l'étape qui échoue. Causes typiques :
- Permissions manquantes sur le repo → vérifier que les workflows GitHub Actions ont accès à `packages: write` (Settings → Actions → General → Workflow permissions → "Read and write")
- Erreur de build du Dockerfile → cf. logs détaillés du job

- [ ] **Step 4 : Vérifier que les images apparaissent sur GHCR**

Aller sur https://github.com/gaelgael5?tab=packages

Attendu : 2 packages visibles
- `agflow-backend` (privé, lié à ce repo)
- `agflow-frontend` (privé, lié à ce repo)

Cliquer dessus → tag `latest` doit apparaître avec date récente.

---

## Task 3 — USER GATE : créer le PAT GitHub pour le pull côté LXC

> **Cette task est manuelle.** L'agent doit STOPPER ici.

**Files:** Aucun changement de code. Note la valeur du PAT dans un endroit sûr — elle ne sera affichée qu'une fois.

- [ ] **Step 1 : Créer le PAT (Personal Access Token classic)**

1. Aller sur https://github.com/settings/tokens
2. Cliquer "Generate new token" → "Generate new token (classic)"
3. Remplir :
   - **Note** : `agflow-docker LXC 201 pull`
   - **Expiration** : `Custom...` → choisir 1 an (ex: 2027-04-29)
   - **Scopes** : cocher UNIQUEMENT `read:packages`
4. Cliquer "Generate token"
5. **Copier la valeur affichée** (commence par `ghp_...`) — elle ne sera plus affichée après cette page.

- [ ] **Step 2 : Stocker le PAT temporairement**

Le coller dans un gestionnaire de mots de passe / Bitwarden / 1Password. La référence à utiliser dans la suite : "le PAT GHCR" ou `<PAT>`.

- [ ] **Step 3 : Pas de commit nécessaire — la suite reprend en Task 4.**

---

## Task 4 — USER GATE : `docker login ghcr.io` côté LXC 201

> **Cette task est manuelle (avec assistance Claude).**

**Files:** Aucun changement de code. Stocke le credential dans `/root/.docker/config.json` du LXC.

- [ ] **Step 1 : Lancer le login depuis Windows via SSH**

Remplacer `<PAT>` par la vraie valeur du token, puis exécuter (UN SEUL coup, le PAT ne sera pas dans l'historique bash si tu utilises `--password-stdin`) :

```bash
ssh pve "pct exec 201 -- bash -c 'echo <PAT> | docker login ghcr.io -u gaelgael5 --password-stdin'"
```

Attendu :
```
WARNING! Your password will be stored unencrypted in /root/.docker/config.json.
Configure a credential helper to remove this warning.
Login Succeeded
```

L'avertissement est normal sur LXC — il n'y a pas de keyring system.

- [ ] **Step 2 : Vérifier le credential stocké**

```bash
ssh pve "pct exec 201 -- bash -c 'cat /root/.docker/config.json'"
```

Attendu : un JSON contenant `"ghcr.io"` dans `auths` avec une `auth` base64.

- [ ] **Step 3 : Tester le pull manuel**

```bash
ssh pve "pct exec 201 -- docker pull ghcr.io/gaelgael5/agflow-backend:latest"
ssh pve "pct exec 201 -- docker pull ghcr.io/gaelgael5/agflow-frontend:latest"
```

Attendu : les 2 pulls réussissent et affichent `Status: Downloaded newer image for ghcr.io/...`.

Si erreur `denied: requested access to the resource is denied` → le PAT n'a pas le scope `read:packages`, ou la visibilité GHCR n'est pas correcte (vérifier sur https://github.com/users/gaelgael5/packages que les 2 packages existent et que tu en es bien propriétaire).

- [ ] **Step 4 : Lister les images locales sur le LXC**

```bash
ssh pve "pct exec 201 -- bash -c 'docker images | grep -E \"agflow|ghcr\"'"
```

Attendu : 4 lignes
- `agflow-backend:latest` (locale, datée d'aujourd'hui — issue du dernier `deploy.sh --rebuild`)
- `ghcr.io/gaelgael5/agflow-backend:latest` (vient d'être pull)
- `agflow-frontend:latest` (locale)
- `ghcr.io/gaelgael5/agflow-frontend:latest` (vient d'être pull)

> Ce n'est pas grave d'avoir les deux pour l'instant. Quand le compose va basculer sur `ghcr.io/...`, l'image locale `agflow-backend:latest` deviendra orpheline — on la nettoiera plus tard avec `docker image prune`.

---

## Task 5 — Bascule de `docker-compose.prod.yml` sur les images GHCR

**Files:**
- Modify: `docker-compose.prod.yml` (2 lignes : services `backend` et `frontend`)

- [ ] **Step 1 : Voir l'état actuel**

```bash
grep -n "image: agflow" docker-compose.prod.yml
```

Attendu :
```
23:    image: agflow-backend:latest
50:    image: agflow-frontend:latest
```

- [ ] **Step 2 : Modifier les 2 lignes**

Changer dans `docker-compose.prod.yml` :

```diff
   backend:
-    image: agflow-backend:latest
+    image: ghcr.io/gaelgael5/agflow-backend:latest
     container_name: agflow-backend
```

```diff
   frontend:
-    image: agflow-frontend:latest
+    image: ghcr.io/gaelgael5/agflow-frontend:latest
     container_name: agflow-frontend
```

- [ ] **Step 3 : Vérifier la validité YAML**

```bash
python -c "import yaml; yaml.safe_load(open('docker-compose.prod.yml')); print('ok')"
```

Attendu : `ok`.

- [ ] **Step 4 : Pas de commit ici — Task 6 le fait avec deploy.sh**

(Garder les 2 changements en working tree pour les committer ensemble en Task 6.)

---

## Task 6 — Simplifier `scripts/deploy.sh`

**Files:**
- Modify: `scripts/deploy.sh` (réécriture complète)

- [ ] **Step 1 : Remplacer le contenu intégral du script**

Écrire `scripts/deploy.sh` :

```bash
#!/usr/bin/env bash
###############################################################################
# Deploy agflow.docker to LXC 201 (192.168.10.158)
#
# Cette version pull les images depuis GHCR (ghcr.io/gaelgael5/agflow-{backend,
# frontend}:latest) construites par GitHub Actions sur push main. Plus de
# docker build local sur le LXC.
#
# Prereqs :
#   - ssh alias `pve` configuré dans ~/.ssh/config
#   - CT 201 a Docker + Compose installés
#   - Local repo a un fichier .env (jamais commité, valeurs prod)
#   - CT 201 est loggé sur ghcr.io via PAT (`docker login ghcr.io ...`)
#     pour pouvoir pull les images privées
#   - Le workflow GitHub Actions a déjà publié les images :latest récentes
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
echo "    curl http://192.168.10.158/api/admin/auth/login -X POST -H 'Content-Type: application/json' -d '{\"email\":\"<admin_email>\",\"password\":\"<admin_password>\"}'"
```

> **Notes** :
> - Le flag `--rebuild` a disparu (la build se passe sur GitHub Actions maintenant)
> - Le tarball ne contient plus les sources backend/frontend — juste 3 fichiers de conf (~quelques KB vs ~10 MB avant)
> - `docker compose pull` est explicite avant le `up -d`, sinon `up -d` peut redémarrer sur des images cachées sans détecter les nouveautés

- [ ] **Step 2 : Vérifier que le script est syntactiquement valide**

```bash
bash -n scripts/deploy.sh && echo ok
```

Attendu : `ok`.

- [ ] **Step 3 : Commit (compose + deploy.sh ensemble)**

```bash
git add docker-compose.prod.yml scripts/deploy.sh
git commit -m "feat(deploy): bascule sur les images GHCR — fini le docker build local

docker-compose.prod.yml référence désormais
ghcr.io/gaelgael5/agflow-{backend,frontend}:latest. deploy.sh perd
l'étape build (faite par GitHub Actions sur push main) et gagne un
docker compose pull explicite avant le up -d.

Tarball réduit à 3 fichiers (.env + compose + Caddyfile) — ~quelques
KB au lieu de ~10 MB.

Pré-requis côté LXC 201 : être loggé sur ghcr.io via PAT (cf. spec
docs/superpowers/specs/2026-04-29-github-build-images-design.md §3.4)."
```

---

## Task 7 — USER GATE : push de la branche puis déploiement bout-en-bout

> **Cette task est manuelle (déploiement = action visible/partagée).** L'agent doit STOPPER avant le déploiement et demander GO explicite.

**Files:** Aucun changement local. Le déploiement applique les commits aux images sur le LXC.

- [ ] **Step 1 : Push des commits**

```bash
git push origin feat/mom-bus
```

Si la branche est déjà tracké (Task 2), ça suffit. Sinon `git push -u origin feat/mom-bus`.

- [ ] **Step 2 : Vérifier que les images GHCR sont à jour avec le code à déployer**

> **Important** : le trigger automatique est `on: push: branches: [main]`. Un push sur `feat/mom-bus` **NE déclenche PAS** le workflow. Donc à ce stade les images `:latest` sur GHCR contiennent le code de Task 2 (avant les modifs compose+deploy.sh — mais ces modifs ne touchent pas le contenu des images, c'est juste la conf de déploiement). Donc les images GHCR existantes sont **suffisantes** pour le déploiement de cette tâche.

Vérifier sur https://github.com/gaelgael5?tab=packages :
- Les 2 packages `agflow-backend` et `agflow-frontend` existent
- Le tag `latest` a une date récente (Task 2)

Si pour une raison quelconque tu veux re-builder (par ex. si Tasks 3/4/5/6 ont mis du temps et que tu veux un rebuild propre) : déclencher manuellement via "Run workflow" sur la branche `feat/mom-bus` avec `force_all=true`.

- [ ] **Step 3 : USER GO/NO-GO pour le déploiement**

Confirmer avec l'humain :
- ✅ Les images CI sont à jour (timestamps récents sur https://github.com/gaelgael5?tab=packages)
- ✅ Le `docker pull` sur le LXC fonctionne (Task 4 step 3)
- ✅ Backup du volume `data/` existe (Task Export effectuée plus tôt)

- [ ] **Step 4 : Déploiement**

```bash
./scripts/deploy.sh
```

> ⚠️ Plus de `--rebuild` — c'est volontaire. Si quelqu'un l'utilise par habitude, le script refusera (flag inconnu) car la nouvelle version n'accepte plus d'arguments.

Attendu : sortie qui montre :
- Tarball créé localement (~few KB)
- Upload `pve:/tmp/`
- Extract sur LXC
- `docker compose pull` télécharge les 2 images si elles ne sont pas déjà à jour
- `docker compose up -d` recrée les containers backend/frontend
- `ps` final montre `agflow-backend` et `agflow-frontend` `Up (healthy)`

- [ ] **Step 5 : Smoke test prod**

```bash
ssh pve "pct exec 201 -- bash -c 'curl -s -o /dev/null -w \"GET /health → %{http_code}\n\" http://localhost/health && curl -s -o /tmp/probe.zip http://localhost/api/admin/system/export -w \"GET /export sans token → %{http_code}\n\"'"
```

Attendu :
```
GET /health → 200
GET /export sans token → 401
```

- [ ] **Step 6 : Vérifier les images effectivement utilisées**

```bash
ssh pve "pct exec 201 -- bash -c 'docker inspect agflow-backend agflow-frontend --format \"{{.Name}} {{.Config.Image}}\"'"
```

Attendu :
```
/agflow-backend ghcr.io/gaelgael5/agflow-backend:latest
/agflow-frontend ghcr.io/gaelgael5/agflow-frontend:latest
```

(Plus de `agflow-backend:latest` locale.)

- [ ] **Step 7 : Test UI**

L'humain ouvre https://docker-agflow.yoops.org/ , se logue, vérifie que :
- La page d'accueil charge
- La page Dockerfiles liste les 7 images (validation du refactor `data/dockerfiles/`)
- Le bouton Export dans la topbar marche (download du zip)

---

## Task 8 — Path-filter sanity check (validation passive)

**Files:** Aucun. C'est une vérification fonctionnelle qui se fera **naturellement** à la première occasion où un commit ne touche QUE le backend ou QUE le frontend, après merge de `feat/mom-bus` sur `main`.

> **Pas de changement synthétique à faire.** Forcer un commit no-op pour tester ajoute du bruit dans l'historique sans valeur réelle. À la place : observer le prochain run "naturel".

- [ ] **Step 1 : À la prochaine livraison qui ne touche que backend OU frontend**

Quand un commit poussé sur `main` modifie uniquement `backend/**` ou uniquement `frontend/**`, ouvrir le run associé sur https://github.com/gaelgael5/agflow.docker/actions et vérifier :

Cas "backend only" attendu :
- ✅ `changes` — outputs `backend=true`, `frontend=false`
- ✅ `build-backend` (vert)
- ⏭️ `build-frontend` (skipped)

Cas "frontend only" attendu : symétrique.

Si jamais ce ne se produit pas naturellement dans les 2-3 livraisons qui suivent ce plan, déclencher la vérif manuellement avec un changement non-trivial réellement utile (par ex. amélioration d'un message d'erreur backend, ou bump d'un texte i18n).

- [ ] **Step 2 : Si comportement inattendu**

Si les 2 jobs s'exécutent alors qu'un seul devrait, le filtre `dorny/paths-filter` ne fait pas son boulot. Causes possibles :
- L'action `actions/checkout` ne récupère pas l'historique → vérifier la documentation `paths-filter` (option `base` peut être nécessaire pour les pushs main)
- Le filtre matche des fichiers communs → vérifier les patterns YAML

C'est diagnostiqué facilement en lisant les logs du job `changes`.

---

## Task 9 — Vérifications finales et nettoyage

**Files:** Aucun changement de code.

- [ ] **Step 1 : Confirmer la liste des commits livrés**

```bash
git log --oneline 63cf3f9..HEAD
```

Attendu :
- `ci: workflow build-images publie agflow-backend/frontend sur GHCR`
- `feat(deploy): bascule sur les images GHCR — fini le docker build local`

- [ ] **Step 2 : Cleanup éventuel des images locales orphelines sur LXC**

Une fois confirmé que les nouveaux containers tournent bien sur les images GHCR :

```bash
ssh pve "pct exec 201 -- docker image prune -f"
```

Cela retirera les anciennes images `agflow-backend:latest` (locale) qui ne sont plus référencées par aucun container.

- [ ] **Step 3 : Documenter la procédure de rollback**

Pour info — si la bascule pose problème, le rollback consiste à :

```bash
git revert <SHA-deploy-bascule>   # commit "feat(deploy): bascule sur les images GHCR"
./scripts/deploy.sh --rebuild      # ATTENTION : le script revert sera l'ancienne version qui supporte --rebuild
```

> **Limite** : le script `deploy.sh` reverté a besoin que les sources `backend/` et `frontend/` soient packagées dans le tarball — ce qui marchera car le revert restaure l'ancien script. Le compose reverté pointera vers les images locales `agflow-backend:latest` que `--rebuild` recréera.

- [ ] **Step 4 : Rappel pour la suite (Swarm)**

Cette initiative est l'étape 1 du chantier global "migration vers Docker Swarm". Les étapes suivantes (à brainstormer/specifier après livraison de cette task) :
- Convertir `docker-compose.prod.yml` en stack Swarm (`docker stack deploy`)
- Initialiser un cluster Swarm (1 node manager + 0..N workers)
- Stratégie de stockage pour le volume `data/` (replicated avec NFS, ou single-node attachment ?)
- Stratégie de secrets (Docker Swarm secrets vs `.env`)

---

## Critères d'acceptation finaux

- [ ] Workflow `.github/workflows/build-images.yml` mergé/présent et fonctionnel
- [ ] Les 2 images `ghcr.io/gaelgael5/agflow-{backend,frontend}:latest` existent et sont à jour
- [ ] Le LXC 201 peut pull ces images via le PAT (vérifié par Task 4 step 3)
- [ ] `docker-compose.prod.yml` référence les images GHCR (plus d'images locales)
- [ ] `scripts/deploy.sh` ne fait plus de `docker build` — uniquement `docker compose pull && up -d`
- [ ] Le smoke test `/health` répond 200 sur la prod après bascule
- [ ] Path-filter validé (commit frontend-only ne rebuild pas le backend, et inversement)
- [ ] Les containers tournent sur les images GHCR (vérifié par `docker inspect`)
- [ ] L'UI prod fonctionne (login, page Dockerfiles, bouton Export)

---

## Hors scope (à NE PAS faire dans cette initiative)

- Migration vers Docker Swarm (étape suivante du chantier global)
- Tags `:vX.Y.Z` versionnés / rollback ciblé
- Tags `:sha-<short>` immuables
- Build multi-arch `linux/arm64`
- PR builds / preview environments
- Scan Trivy/Grype des images
- Auto-deploy via webhook GitHub
- Docker Hub mirror (V2, "quand stable")
