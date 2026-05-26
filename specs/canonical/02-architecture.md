# 02 — Architecture

## Vue d'ensemble

agflow.docker est une application web full-stack composée de :

- un **backend FastAPI** (Python 3.12) qui expose deux familles d'API : `/api/admin/*` + `/api/infra/*` pour l'administration, `/api/v1/*` pour les clients externes ;
- un **frontend React** (Vite + TypeScript strict) qui consomme l'API admin et propose le panneau d'administration en huit modules ;
- une **base de données PostgreSQL 16** comme source de vérité de toute la configuration et de l'état applicatif ;
- des **workers asyncio internes** (build d'images, exécution de tasks, push de déploiements, planificateurs de backups et PITR) intégrés au processus FastAPI ;
- des **conteneurs Docker** créés et pilotés via `aiodocker`, soit localement (sur l'hôte de la plateforme) pour les agents one-shot, soit à distance via SSH sur les machines cibles pour les instances projet ;
- un **coffre-fort Harpocrate** externe pour tous les secrets ;
- une **stack d'observabilité Loki + Grafana** déployée séparément, qui collecte les logs JSON structlog via Grafana Alloy.

## Stack technique

### Backend

| Composant | Choix |
|---|---|
| Langage | Python 3.12 (async/await partout) |
| Framework | FastAPI |
| Pilote DB | `asyncpg` (pas de SQLAlchemy : SQL direct via helpers `fetch_one` / `fetch_all` / `execute`) |
| Validation | Pydantic v2 (schemas DTO + `Pydantic Settings` pour la configuration) |
| Logs | `structlog` JSON, jamais `print()` |
| Tests | `pytest` + `pytest-asyncio` |
| Lint / format | `ruff` (check + format) |
| Conteneurs | `aiodocker` (jamais `subprocess` pour Docker) |
| SSH | `asyncssh` |
| Templating | `Jinja2` en mode sandboxed |
| Web sockets / SSE | natif FastAPI / `Starlette` |

### Frontend

| Composant | Choix |
|---|---|
| Build | Vite |
| Framework | React 18 (composants fonctionnels + hooks, pas de classes) |
| Langage | TypeScript avec `strict: true` + `noUncheckedIndexedAccess: true` |
| Routing | `react-router-dom` |
| Data fetching | `@tanstack/react-query` (jamais `useEffect + fetch` directs) |
| Styles | Tailwind CSS |
| Composants UI | `shadcn/ui` |
| Internationalisation | `i18next` (toutes les chaînes affichées passent par `useTranslation()`) |
| Tests | `Vitest` + React Testing Library |

### Base de données

- **PostgreSQL 16** avec extensions `pgcrypto` et `uuid-ossp`.
- **Schéma versionné** : un unique fichier `backend/migrations/001_init.sql` qui crée l'état complet, et un répertoire `backend/migrations/` qui peut accueillir des migrations incrémentales numérotées (`002_*.sql`, etc.).
- **Source de vérité unique** : toute la configuration (rôles, agents, MCP catalog, scripts, machines, projets, etc.) vit en base. Le filesystem ne contient que des templates et des données opérationnelles (logs, builds, workspaces d'agents).

### Coffre-fort

- **Harpocrate** : service externe accessible via HTTPS, authentifié par clé API stockée localement (chiffrée par `harpocrate_dek`).
- **Multi-coffres** : plusieurs Harpocrate vaults peuvent être déclarés ; l'un est marqué comme `default` et reçoit les nouveaux secrets.
- **SDK local** : `agflow.services.vault_client` encapsule les appels HTTPS et la résolution des références `${vault://api:NAME}`.

### Observabilité

- **Loki** + **Grafana** déployés sur un LXC dédié `agflow-logs` (`https://log.yoops.org` derrière Cloudflare Tunnel + auth SSO Keycloak realm `yoops`).
- **Grafana Alloy** déployé sur toutes les machines actives (Docker socket + journald + fichiers de logs applicatifs).
- **Rétention** : 7 jours.
- **Format** : tous les logs backend sont JSON structlog avec champs typés (`event`, `level`, et toute clé contextuelle).

## Organisation du code

```
agflow.docker/
├── backend/
│   ├── pyproject.toml
│   ├── migrations/                            # SQL bruts numérotés
│   ├── src/agflow/
│   │   ├── main.py                            # FastAPI app + lifespan (workers démarrés ici)
│   │   ├── config.py                          # Pydantic Settings
│   │   ├── logging_setup.py                   # structlog JSON
│   │   ├── auth/                              # JWT Keycloak / local + dépendances FastAPI
│   │   ├── db/                                # pool asyncpg + runner de migrations
│   │   ├── api/
│   │   │   ├── admin/                         # Endpoints /api/admin/*
│   │   │   ├── infra/                         # Endpoints /api/infra/*
│   │   │   └── public/                        # Endpoints /api/v1/*
│   │   ├── docker/                            # aiodocker wrappers (build, run, exec, logs)
│   │   ├── services/                          # Logique métier (≈ 80 services)
│   │   ├── schemas/                           # DTOs Pydantic
│   │   ├── workers/                           # Workers asyncio (build, deploy, pitr, hooks…)
│   │   └── templates/                         # Templates de bootstrap éventuels
│   └── tests/
│       ├── api/                               # Tests d'endpoints
│       ├── services/                          # Tests de services (intégration DB)
│       └── workers/                           # Tests de workers
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── pages/                             # ≈ 30 pages React (≈ 1 par module + sous-pages)
│       ├── components/                        # Composants réutilisables
│       ├── hooks/                             # Hooks personnalisés
│       ├── lib/                               # api client par module
│       └── i18n/                              # fr.json, en.json
├── specs/
│   ├── canonical/                             # Spécification canonique (CE document)
│   └── …                                       # Spécifications archivées (historique)
├── docs/
│   ├── contracts/                             # Contrats d'intégration externes
│   ├── functionnalTests/                      # Scénarios E2E
│   ├── superpowers/                           # Spécifications et plans de chantiers
│   └── …                                       # Documentation technique transversale
├── infra/
│   ├── logs-stack/                            # Stack Loki + Grafana (LXC agflow-logs)
│   ├── alloy-agent/                           # Configuration Alloy à déployer
│   └── …
├── scripts/                                   # Scripts de provisioning (LXC, deploy, run-test, …)
├── docker-compose.yml                         # Dev : postgres + redis dépendances
└── docker-compose.prod.yml                    # Prod : stack complète
```

## Architecture interne du backend

### Couches

1. **API layer** (`api/`) : routers FastAPI qui définissent les endpoints, valident les inputs Pydantic et délèguent à la couche service.
2. **Service layer** (`services/`) : la logique métier. Chaque service est un module `*_service.py` avec des fonctions async qui acceptent et renvoient des DTOs Pydantic.
3. **Schemas layer** (`schemas/`) : les DTOs Pydantic exposés par les services.
4. **DB layer** (`db/pool.py`) : helpers `fetch_one`, `fetch_all`, `execute`, `transaction`, `get_pool`. La couche service appelle directement le pool ; pas d'ORM, pas de repository pattern.
5. **Workers layer** (`workers/`) : tâches asyncio démarrées au lifespan de FastAPI — runner de builds, runner de déploiements, hook dispatcher, planificateurs PITR / backups, consumers de tâches.

### Principes de découpage

- Un service par domaine (ex: `agents_service`, `roles_service`, `projects_service`).
- Un service par préoccupation transversale (ex: `input_resolver`, `platform_secrets_service`, `harpocrate_vaults_service`).
- Fichier max **300 lignes**, classes SRP, méthodes 5-15 lignes.
- Pas d'effets de bord dans les services — toute mutation passe par un appel SQL explicite.

## Cibles d'infrastructure

La plateforme se déploie sur trois familles de cibles, **au choix de l'administrateur à l'installation**.

### Mode Docker simple

**Pour qui** : déploiements légers, quelques nœuds, pas de besoin d'orchestration avancée.

**Comment** : une ou plusieurs machines avec un démon Docker accessible par SSH. agflow.docker pousse un `docker-compose.yml` rendu depuis le template `compose_template_slug` du groupe, exécute `docker compose up -d` à distance via SSH, et utilise `aiodocker` (au travers du socket Docker remote ou des commandes shell SSH) pour piloter les conteneurs.

**Avantages** : configuration triviale, pas de cluster à maintenir.
**Limites** : pas d'auto-rescheduling, pas de load balancing intégré, redondance manuelle.

### Mode Docker Swarm

**Pour qui** : montée en charge avec plusieurs nœuds, besoin de gestion centralisée et de re-scheduling automatique en cas de panne d'un nœud.

**Comment** : un nœud manager initialise le cluster Swarm via `POST /api/infra/machines/{id}/actions/swarm_init` ; les nœuds additionnels rejoignent via `swarm_join` (en rôle `manager` ou `worker`) en utilisant le token approprié (stocké dans Harpocrate). Les déploiements rendent une `stack.yml` depuis le template `swarm_template_slug` du groupe et utilisent `docker stack deploy` via SSH sur un manager.

**Particularités prises en compte** :
- Ports LAN exposés depuis un service Swarm : `mode: host` pour préserver l'IP source.
- Services Swarm qui sont eux-mêmes la cible d'autres services overlay : `endpoint_mode: dnsrr` pour éviter le LB IPVS.

**Avantages** : gestion simplifiée du cluster, intégrée à Docker.
**Limites** : moins expressif que Kubernetes, communauté restreinte.

### Mode K3s / K8s

**Pour qui** : infrastructures plus larges, besoin de patterns Kubernetes (operators, CRDs, ingress controllers, etc.).

**Comment** : agflow.docker détecte le mode K3s (présence du port 6443 sur la machine) lors du health check ; les artefacts générés deviennent des manifests Kubernetes (Deployments, Services, etc.) au lieu de compose ; le déploiement se fait via `kubectl apply` côté machine cible.

**Avantages** : écosystème mature, scalabilité horizontale poussée.
**Limites** : courbe d'apprentissage, plus de surface d'administration.

### Choix entre les trois modes

Le choix se fait au niveau du **groupe** d'une ressource projet, via :
- `compose_template_slug` → le groupe sera déployé en mode Docker (simple ou Swarm).
- `swarm_template_slug` → variante explicite pour Swarm si différente du Docker simple.

Le mode K3s utilise des templates dédiés (typiquement `<slug>/<culture>.k3s.j2`).

### Auto-détection du mode local

Le backend détecte au démarrage **le mode de la machine sur laquelle il tourne lui-même** (utile pour les builds d'images, les tâches one-shot, le wizard de production de docker-compose). Le résultat est persisté dans la table `infra_runtime_config` (clé `mode`).

Procédure au lifespan FastAPI (`container.detection.load_or_detect`) :
1. Lecture de `runtime_config[key='mode']`.
2. Validation que le mode stocké est encore opérationnel (`docker.version()` répond, et `docker.services.list()` détermine Swarm vs standalone).
3. Si la valeur est invalide ou absente, redétection : un `docker.services.list()` qui répond → `docker_swarm` ; un 503 sur cet appel mais `docker.version()` OK → `docker_standalone` ; rien d'accessible → `none`.
4. Persistance via `INSERT … ON CONFLICT (key) DO UPDATE`, avec mise à jour de `validated_at`.

Le champ `filter` des entrées `infra_runtime_config` permet de restreindre la portée d'une clé à un sous-ensemble de modes (ex: `filter='docker_swarm|k3s'` pour une option spécifique aux orchestrateurs).

## Réseau et communication entre ressources

### Réseau Docker par projet

Chaque instance projet dispose d'un **réseau Docker dédié** (par défaut nommé `agflow-user-{user_id}`). Tous les conteneurs des groupes de l'instance rejoignent ce réseau ; ils peuvent se résoudre mutuellement par hostname.

### Hostnames préfixés

Pour permettre plusieurs instances d'un même projet sur la même machine (cas SaaS multi-utilisateur), les hostnames Docker sont préfixés par l'identifiant utilisateur ou par un préfixe configuré sur l'instance projet. Cela évite les collisions entre les conteneurs « wiki », « gitea », etc. de deux utilisateurs différents.

### Communication agents ↔ ressources

Quand une session est liée à une instance projet, le rendu Jinja du prompt, de la config MCP et du `.env` de l'agent intègre les URLs des ressources de l'instance projet. L'agent peut donc adresser directement (via son réseau Docker partagé avec ces ressources) la base, le wiki, le dépôt Git, etc.

## Workers internes

Démarrés au lifespan de FastAPI dans `main.py`. Chacun est une tâche `asyncio` autonome qui consomme un état persistant en base.

| Worker | Rôle |
|---|---|
| `dockerfile_build_worker` | Consomme les `dockerfile_builds` en statut `pending`, fait tourner `aiodocker build`, persiste les logs et le tag final. |
| `deployment_executor` | Pour chaque `project_deployment` à pousser : exécute les `before` scripts, rend les artefacts, fait le `docker compose up` ou `docker stack deploy`, exécute les `after` scripts, met à jour les `project_runtimes`. |
| `hook_dispatcher_worker` | Consomme les `outbound_hooks` à envoyer, calcule la signature HMAC, fait l'appel HTTP, gère les retries avec backoff exponentiel. |
| `pitr_scheduler` | Déclenche les basebackups pgbackrest selon le cron configuré, gère la rétention, lance les pushes vers remotes. |
| `backup_scheduler` | Déclenche les schedules de backups full (pg_dump multi-remote) selon leur cron. |
| `git_sync_scheduler` | Si activé, déclenche périodiquement l'export Git de la configuration (tables sélectionnées). |
| `session_reaper` | Marque comme `expired` les sessions dont la `expires_at` est dépassée et libère leurs conteneurs d'agents. |
| `agent_lifecycle_watcher` | Surveille les `agents_instances` ; si une instance reste `idle` au-delà d'un timeout paramétré, elle est `destroyed`. |

Tous les workers publient des événements de supervision via PostgreSQL `pg_notify` (canal `supervision_events`), consommés par le module M6 pour mettre à jour le dashboard temps réel via WebSocket.

## Dépendances externes opérationnelles

| Dépendance | Rôle | Provisionning |
|---|---|---|
| PostgreSQL 16 | Source de vérité | Conteneur ou service managé |
| Harpocrate | Coffre-fort secrets | Service externe (déployé séparément) |
| Keycloak | SSO admin UI | Service externe (realm `yoops` sur `security.yoops.org`) |
| Loki + Grafana | Observabilité | LXC dédié `agflow-logs` |
| `mcp.yoops.org` (par défaut) | Registre MCP / skills | Service externe (configurable) |
| Providers IA (Anthropic, OpenAI, …) | Modèles LLM | Configurés par l'administrateur dans M3 |

## Environnements

| Environnement | Rôle | Caractéristiques |
|---|---|---|
| Dev local | Développement | Backend en local (Windows + uv), frontend en local (npm), PostgreSQL + Redis hébergés sur un LXC d'intégration. Pas de stack de test complète locale. |
| Test (LXC 400-499) | Tests d'intégration auto Claude | Provisionnés et détruits à la demande via `./scripts/run-test.sh`. 1 LXC = 1 stack agflow.docker fraîche. |
| Test (LXC 300-399) | Tests humains | Déployés sur demande explicite via `remote-deploy.ps1 <id>`. Persistants entre sessions de test. |
| Prod | Production | À définir selon le déploiement de l'opérateur. La plateforme est livrée avec les scripts `scripts/infra/` pour bootstrapper un LXC sur Proxmox, mais peut tourner sur n'importe quelle cible Docker. |

## Communication entre instances de la plateforme

agflow.docker ne fait pas de fédération multi-instances. Une instance est autonome ; pour orchestrer plusieurs instances, on passe par l'orchestrateur externe (ag.flow) qui peut appeler successivement plusieurs instances via leurs API publiques respectives.
