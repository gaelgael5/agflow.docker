# Procédure de test d'intégration — agflow.docker

Cette procédure valide bout-en-bout que le code de la branche `dev` se déploie
proprement sur un LXC Proxmox fraîchement créé : création du container,
installation Docker, clone du repo, exécution de `dev-deploy.sh`, et smoke
test du backend.

Cible : opérateur sur l'**hôte Proxmox**. Aucune intervention manuelle dans
le LXC n'est nécessaire.

Script : [`scripts/test-create-lxc.sh`](../scripts/test-create-lxc.sh).

---

## Pré-requis sur l'hôte Proxmox

| Pré-requis | Vérification |
|---|---|
| `pct` (cli Proxmox) | `command -v pct` |
| `python3` | `command -v python3` |
| `curl` | `command -v curl` |
| PAT GitHub valide avec scope `repo` | voir § « Préparer le `.env.git` » |

Le script télécharge automatiquement `create-lxc.sh` et `list-instances.sh`
depuis le repo public `Configurations/Proxmox` si ils ne sont pas déjà
présents sous `/opt/scripts/`. Aucune action manuelle pour eux.

---

## Préparer le `.env.git`

Le script lit le token GitHub depuis `/opt/scripts/.env.git`. La procédure
détaillée de création du token est documentée dans
[`Install-dev.md` § Étape 2](../Install-dev.md#étape-2--accès-github-via-personal-access-token-pat).

Résumé minimal :

```bash
mkdir -p /opt/scripts && chmod 700 /opt/scripts
cat > /opt/scripts/.env.git <<'EOF'
TOKEN=ghp_REMPLACE_PAR_TON_TOKEN
EOF
chmod 600 /opt/scripts/.env.git
```

Le script échoue tôt avec un message explicite si :
- le fichier n'existe pas,
- la valeur `TOKEN=` est vide,
- le token est invalide (réponse `/user` GitHub vide),
- le compte GitHub authentifié n'a pas accès au repo `gaelgael5/agflow.docker`.

---

## Lancer le test

```bash
# Depuis le repo agflow.docker (par exemple cloné sur l'hôte Proxmox)
./scripts/test-create-lxc.sh
```

Le LXC créé est **conservé** par défaut pour permettre l'inspection
post-test. Pour le supprimer automatiquement à la fin :

```bash
CLEANUP=1 ./scripts/test-create-lxc.sh
```

---

## Ce que fait le script (8 étapes)

| # | Étape | Description |
|---|---|---|
| 0 | Bootstrap | Télécharge `list-instances.sh` et `create-lxc.sh` depuis le repo `Configurations/Proxmox` si absents de `/opt/scripts/`. |
| 1 | Auth GitHub | Lit `/opt/scripts/.env.git`, vérifie le token via `/api/github.com/user` et `/api/github.com/repos/gaelgael5/agflow.docker`. Échoue tôt si KO. |
| 2 | CTID libre | Énumère les LXC existants via `list-instances.sh` et choisit le premier CTID disponible dans la plage `[900..999]`. |
| 3 | Nom | Calcule le nom du LXC : `test-agflow.docker-<CTID>`. |
| 4 | Création LXC | `create-lxc.sh <CTID> <NAME> --docker`. Provisionne le container, installe Docker, lance `hello-world` pour valider. Récupère le JSON de sortie (IP, version Docker, etc.). |
| 5 | Push `.env.git` + clone | `pct push` du token dans le LXC, puis `git clone --branch dev https://${TOKEN}@github.com/gaelgael5/agflow.docker.git /opt/agflow.docker`. |
| 6 | Déploiement | Exécute `./dev-deploy.sh` dans le LXC. Ce script provisionne `.env` (auto-génération secrets), build les images backend + frontend, lance la stack. |
| 7 | Validation | Joue 7 assertions (cf. tableau ci-dessous). Compte pass / fail. |
| 8 | Nettoyage | Si `CLEANUP=1` : `pct stop` + `pct destroy --purge`. Sinon, affiche les commandes manuelles pour entrer dans le LXC ou le supprimer plus tard. |

### Tests joués à l'étape 7

| Test | Critère |
|---|---|
| 1 | `status == "ok"` dans le JSON de `create-lxc.sh` |
| 2 | `machine.systeme.ip` non vide (DHCP obtenu) |
| 3 | `docker.docker_ok == 1` |
| 4 | `docker.hello_world_ok == true` |
| 5 | `/opt/agflow.docker` existe dans le LXC |
| 6 | `/opt/agflow.docker/.git` existe (clone complet) |
| 7 | `curl http://<CT_IP>:8000/health` répond — **smoke applicatif backend agflow** |

---

## Sortie attendue

Le script affiche un rapport final :

```
=========================================
  RÉSULTAT DES TESTS
=========================================
  Projet       : agflow.docker
  CTID         : 900
  Nom          : test-agflow.docker-900
  IP           : 192.168.10.xxx
  Branche      : dev
  Sources      : /opt/agflow.docker
  -----------------------------------------
  Tests OK     : 7/7
  Tests FAIL   : 0/7

  Statut       : OK SUCCES
=========================================
```

Codes de sortie :
- `0` : tous les tests passés
- `1` : au moins un test a échoué (échec partiel ou complet) ou erreur fatale en cours de route

---

## Inspecter le LXC créé (CLEANUP non défini)

```bash
# Entrer dans le LXC
pct enter <CTID>

# Logs backend
pct exec <CTID> -- docker compose -f /opt/agflow.docker/docker-compose.dev.yml logs --tail=200 backend

# Inspecter la conf .env générée par dev-deploy.sh
pct exec <CTID> -- cat /opt/agflow.docker/.env
```

Pour supprimer manuellement après inspection :

```bash
pct stop <CTID>
pct destroy <CTID> --purge
```

---

## Dépannage

### `ARRÊT : /opt/scripts/.env.git absent`
Créer le fichier — voir § « Préparer le `.env.git` » ci-dessus.

### `ARRÊT : token invalide ou expiré` (HTTP 401)
Le PAT a expiré ou a été révoqué. En regénérer un sur
<https://github.com/settings/tokens>, scope `repo`.

### `ARRÊT : impossible d'accéder au repo (HTTP 404)`
Soit le token n'a pas le scope `repo`, soit le compte GitHub authentifié
n'a pas accès au repo privé. Vérifier les deux.

### `Aucun CTID disponible dans la plage 900–999`
Plus de 100 LXC de test traînent. Supprimer les anciens :
```bash
for id in $(seq 900 999); do
  pct status $id 2>/dev/null && pct destroy $id --purge 2>/dev/null
done
```

### `dev-deploy.sh a échoué dans le LXC`
Le déploiement a planté côté LXC. Entrer dedans et regarder les logs :
```bash
pct enter <CTID>
cd /opt/agflow.docker
docker compose -f docker-compose.dev.yml logs --tail=200 backend
```
Causes fréquentes : `HARPOCRATE_KEY` non renseignée, image backend qui
ne build pas, port 5432/8000 déjà pris (rare en LXC isolé).

### `Backend agflow ne répond pas sur /health` (test 7 FAIL)
La stack a démarré mais le backend n'a pas atteint l'état healthy dans
le délai imparti. Vérifier :
1. `docker compose ps` dans le LXC — le container `agflow-backend` doit
   être `Up (healthy)`.
2. Migrations DB : `docker compose logs backend | grep migration`.
3. Connexion Postgres : `DATABASE_URL` dans `.env` cohérente avec le
   `POSTGRES_PASSWORD` généré.

---

## Quand l'utiliser

- **Avant une PR vers `main`** : valider que la branche `dev` est
  déployable depuis zéro.
- **Après refactor du `dev-deploy.sh` ou `docker-compose.dev.yml`** :
  vérifier qu'on n'a pas cassé l'amorçage.
- **Smoke quotidien** (cron sur l'hôte Proxmox) : détecter au plus tôt
  une régression de boot du backend.

Hors de ces cas, préférer le déploiement direct sur LXC 201 via
`./scripts/deploy.sh` (sans création de LXC à chaque fois).
