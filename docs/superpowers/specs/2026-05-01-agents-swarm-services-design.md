# Spec — Lancement agents en Swarm services (Chantier B1)

> **Statut** : design validé 2026-05-01 — prêt pour le plan d'implémentation
> **Auteur** : brainstorming Claude + utilisateur
> **Initiative parente** : migration agflow.docker du paradigme Docker classique vers Docker Swarm
> **Prérequis livré** : Chantier B0 — modélisation Swarm clusters dans M8 Infra
> **Hors scope** : `run_task()` mode classique (déféré), frontend toggle UI (plan séparé), multi-cluster targeting (single-cluster pour B1), refacto `build_service.py`

## 1. Contexte

Aujourd'hui `services/container_runner.py` (1100 lignes) lance et pilote les containers agents via `aiodocker.containers.create(...)` (API Docker classique). Le backend agflow.docker tourne désormais en Swarm (cluster swarm1, single-node manager). Pour que les agents lancés via l'API admin s'exécutent **dans Swarm** (pas en containers Docker classiques), il faut migrer vers `aiodocker.services.create(...)` (API Swarm services).

**Contexte ops décidé en parallèle** : `agflow-internal` doit passer en `external: true` côté Configurations pour que les services agents (créés en dehors du scope du stack `agflow/docker`) puissent rejoindre ce réseau partagé avec le backend.

## 2. Décisions verrouillées

| Sujet | Choix | Raison |
|---|---|---|
| Schéma `ContainerInfo` | **Conservé** (résolution interne service → container, single-replica MVP) | API publique compatible, frontend pas impacté |
| Stratégie de transition | **Switch direct** — plus de code Docker classique dans `start()` | Pas de dette feature-flag, prod LXC 201 obsolète de toute façon |
| Cible cluster Swarm | **Single-cluster (socket local)** | YAGNI multi-cluster pour B1, futur chantier si besoin |
| Réseau agents | **`agflow-internal` external** (à passer côté ops) | Backend + agents partagent le réseau, communication directe |
| `run_task()` (mode classique) | **Inchangé** — `docker run --rm` via `bash run.sh` | Mode test classique conservé, déféré à un futur B5 |
| `run_task_swarm()` (mode test Swarm) | **NOUVEAU**, génère stack.yml + deploy.sh + task.json | Symétrique au mode classique, fichiers inspectables |
| Format fichier test Swarm | **stack.yml compose v3+** (`docker stack deploy`) | Standard Swarm, lisible, intégré aux outils existants |
| 1 service = combien d'agents | **1 service = 1 agent** (Mode.Replicated.Replicas=1) | MVP, simplification résolution service → container |
| `MAX_RUNNING_CONTAINERS` | **Devient `MAX_RUNNING_AGENT_SERVICES`** (compte les services agflow-managed) | Sémantique préservée, comptage adapté |
| `endpoint_mode` Swarm | **`dnsrr`** systématiquement (workaround IPVS LXC) | Cf. memory `project_swarm_lxc_ipvs_quirks` |
| `placement.constraints` | **`node.role == manager`** (single-node manager) | Aligne backend + agents sur le même node |

## 3. Architecture

```
┌─ services/container_runner.py (REFACTORÉ) ─────────────────────────────┐
│                                                                          │
│ build_run_config()        → Docker classique config (run_task INCHANGE) │
│ build_service_spec()      → NOUVEAU — produit aiodocker ServiceSpec      │
│                                                                          │
│ start(dockerfile_id, ...)                                                │
│   1. build_service_spec(...)                                             │
│   2. aiodocker.services.create(spec)                                     │
│   3. poll services.tasks() jusqu'à state=running                         │
│   4. resolve task.Status.ContainerStatus.ContainerID                     │
│   5. inspect container → produire ContainerInfo                          │
│                                                                          │
│ stop(id_or_name)                                                         │
│   → services.list(filters) pour trouver le service                       │
│   → services.delete(service_id)                                          │
│   → fallback containers.delete() si pas trouvé en service (rétro-compat) │
│                                                                          │
│ list_running()                                                           │
│   → services.list(filters={label agflow.managed=true})                  │
│   → pour chaque service, résoud le 1er task running → container         │
│   → produit list[ContainerInfo]                                          │
│                                                                          │
│ run_task(...)             → INCHANGÉ (subprocess bash run.sh)            │
│ run_task_swarm(...)       → NOUVEAU                                      │
│   _generate_tmp_files_swarm(...) → .tmp/{stack.yml, deploy.sh, task.json}│
│   subprocess `bash deploy.sh`                                            │
│     → docker stack deploy → service logs --follow → stack rm            │
└──────────────────────────────────────────────────────────────────────────┘
            │
            │ utilisé par
            ▼
┌─ Workers + API + Terminal (ADAPTATIONS) ───────────────────────────────┐
│ workers/agent_reaper       : INCHANGÉ (utilise stop() qui résout intern)│
│ workers/docker_reconciler  : INCHANGÉ (list_running() retourne          │
│                               ContainerInfo via résolution service)     │
│ api/admin/containers.py    : INCHANGÉ (signatures publiques préservées) │
│ api/admin/supervision.py   : INCHANGÉ                                   │
│ api/admin/terminal.py      : ADAPTÉ                                     │
│   → si container_id correspond à un service Swarm,                      │
│     résoud service → container du replica avant docker exec              │
└──────────────────────────────────────────────────────────────────────────┘
```

## 4. Mapping Docker config → Swarm ServiceSpec

C'est le cœur du chantier. La conversion entre les 2 formats :

### 4.1 Avant — Docker classique (`build_run_config` produit) :

```json
{
  "Image": "agflow-claude:abc123",
  "Env": ["KEY=value", "OTHER=foo"],
  "HostConfig": {
    "NetworkMode": "agflow-internal",
    "Binds": ["/srv/agflow/data/dockerfiles/claude/workspace:/app/workspace"],
    "Memory": 1073741824,
    "NanoCpus": 1500000000,
    "RestartPolicy": {"Name": "unless-stopped"},
    "Init": true
  },
  "Labels": {"agflow.managed": "true", "agflow.dockerfile_id": "claude", "agflow.instance_id": "..."},
  "Cmd": ["sleep", "infinity"]
}
```

### 4.2 Après — Swarm ServiceSpec (`build_service_spec` produit) :

```json
{
  "Name": "agent-claude-abc123",
  "TaskTemplate": {
    "ContainerSpec": {
      "Image": "agflow-claude:abc123",
      "Env": ["KEY=value", "OTHER=foo"],
      "Mounts": [
        {
          "Source": "/srv/agflow/data/dockerfiles/claude/workspace",
          "Target": "/app/workspace",
          "Type": "bind",
          "ReadOnly": false
        }
      ],
      "Labels": {"agflow.managed": "true", "agflow.dockerfile_id": "claude", "agflow.instance_id": "..."},
      "Command": ["sleep", "infinity"],
      "Init": true
    },
    "Resources": {
      "Limits": {"MemoryBytes": 1073741824, "NanoCPUs": 1500000000}
    },
    "RestartPolicy": {
      "Condition": "on-failure",
      "MaxAttempts": 5,
      "Delay": 10000000000
    },
    "Placement": {
      "Constraints": ["node.role == manager"]
    }
  },
  "Mode": {"Replicated": {"Replicas": 1}},
  "Networks": [{"Target": "agflow-internal"}],
  "EndpointSpec": {"Mode": "dnsrr"},
  "Labels": {"agflow.managed": "true", "agflow.dockerfile_id": "claude", "agflow.instance_id": "..."}
}
```

### 4.3 Règles de mapping

| Docker classique | Swarm ServiceSpec | Note |
|---|---|---|
| `Image` | `TaskTemplate.ContainerSpec.Image` | identique |
| `Env` | `TaskTemplate.ContainerSpec.Env` | identique |
| `HostConfig.Binds` (`"src:tgt:ro"`) | `TaskTemplate.ContainerSpec.Mounts` (objets) | parsing `src:tgt[:ro]` → 3 fields |
| `HostConfig.NetworkMode` | `Networks: [{Target: ...}]` | retransposé en list |
| `HostConfig.Memory` (bytes) | `TaskTemplate.Resources.Limits.MemoryBytes` | identique |
| `HostConfig.NanoCpus` | `TaskTemplate.Resources.Limits.NanoCPUs` | identique |
| `HostConfig.RestartPolicy.Name="unless-stopped"` | `RestartPolicy.Condition="on-failure"` (best match Swarm) | Swarm n'a pas `unless-stopped`, on prend `on-failure` |
| `HostConfig.Init` | `TaskTemplate.ContainerSpec.Init` | identique |
| `Labels` | `TaskTemplate.ContainerSpec.Labels` ET `Labels` (service-level) | dupliqué (container + service) |
| `Cmd` | `TaskTemplate.ContainerSpec.Command` | renommé Cmd → Command |
| (NOUVEAU) | `Mode: {Replicated: {Replicas: 1}}` | hardcodé replicas:1 |
| (NOUVEAU) | `EndpointSpec.Mode: "dnsrr"` | IPVS LXC workaround |
| (NOUVEAU) | `TaskTemplate.Placement.Constraints: ["node.role == manager"]` | single-node manager |

## 5. Modifications de fichiers

### 5.1 NOUVEAU `services/container_runner.py` — fonctions ajoutées

```python
# Constantes
MAX_RUNNING_AGENT_SERVICES = 50  # même valeur que MAX_RUNNING_CONTAINERS actuel

# Nouvelle fonction
def build_service_spec(
    *,
    dockerfile_id: str,
    params_json_content: str,
    content_hash: str,
    instance_id: str,
    extra_env: dict[str, str] | None = None,
    mount_base_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build Swarm ServiceSpec from Dockerfile.json. Mirror of build_run_config()
    but produces the Swarm services API payload instead of Docker classic config.
    """
    # Réutilise les helpers existants (resolve_templates, expand_shell_vars, etc.)
    # Convert le résultat en ServiceSpec via les règles §4.3.
```

### 5.2 MODIFIÉ `services/container_runner.py` — fonctions refactorisées

- `start()` : remplace `containers.create()` par `services.create()` + polling tasks
- `stop()` : remplace `containers.container().delete()` par `services.list()` + `services.delete()`
- `list_running()` : remplace `containers.list()` par `services.list()` + résolution containers

### 5.3 NOUVEAU `services/container_runner.py` — `run_task_swarm()`

```python
async def run_task_swarm(
    dockerfile_id: str,
    *,
    params_json_content: str,
    content_hash: str,
    task_payload: dict[str, Any],
    timeout_seconds: int = 600,
    user_secrets: dict[str, str] | None = None,
    on_container_started: Any | None = None,
    cleanup: bool = False,
    session_id: str | None = None,
    agent_instance_id: str | None = None,
    mount_base_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """One-shot task execution in Swarm mode (NEW, mirror of run_task()).
    
    Generates .tmp/{stack.yml, deploy.sh, task.json}, then subprocess runs
    deploy.sh which does:
      1. docker stack deploy -c stack.yml STACK_NAME
      2. docker service logs --follow STACK_NAME_agent (streamed to stdout)
      3. docker stack rm STACK_NAME (cleanup)
    
    Yields parsed event dicts (same format as run_task()) plus a final
    {"type": "done", "status": "success" | "failure", "exit_code": N}.
    """
```

### 5.4 NOUVEAU `services/container_runner.py` — `_generate_tmp_files_swarm()`

```python
def _generate_tmp_files_swarm(
    dockerfile_id: str,
    service_name: str,
    config: dict[str, Any],
    task_payload: dict[str, Any] | None = None,
) -> str:
    """Generate .env + stack.yml + deploy.sh (+ task.json if task_payload) 
    in {AGFLOW_DATA_DIR}/dockerfiles/{dockerfile_id}/.tmp/.
    
    Mirror de _generate_tmp_files() mais produit du Swarm stack au lieu de
    docker run command. La structure de fichiers générés est inspectable et
    runnable by hand par l'admin (philosophie identique).
    
    Returns le path absolu du deploy.sh généré.
    """
```

### 5.5 ADAPTÉ `api/admin/terminal.py`

Avant le `docker exec -ti {container_id}`, vérifier si le `container_id` correspond à un nom de service Swarm. Si oui, résoudre vers le container du task running.

```python
# Détection : si container_id matche un service agflow-managed, résoudre
async def _resolve_to_container_id(maybe_service_id_or_name: str) -> str:
    docker = aiodocker.Docker()
    try:
        # Tente résolution comme service Swarm d'abord
        try:
            svc = await docker.services.inspect(maybe_service_id_or_name)
        except aiodocker.exceptions.DockerError:
            return maybe_service_id_or_name  # pas un service, return tel quel (container classique)
        
        # Trouve le 1er task running du service
        tasks = await docker.tasks.list(filters={"service": svc["Spec"]["Name"]})
        for task in tasks:
            if task.get("Status", {}).get("State") == "running":
                container_id = task.get("Status", {}).get("ContainerStatus", {}).get("ContainerID")
                if container_id:
                    return container_id
        raise ValueError(f"Service {maybe_service_id_or_name} has no running task")
    finally:
        await docker.close()
```

### 5.6 INCHANGÉS

- `workers/agent_reaper.py` : utilise `stop()` qui s'occupe de la résolution
- `workers/docker_reconciler.py` : utilise `list_running()` qui retourne `ContainerInfo`
- `api/admin/containers.py` : signatures `start()`, `stop()`, `list_running()` préservées
- `api/admin/supervision.py` : utilise `list_running()`
- `services/build_service.py` : build d'images, hors scope (continue avec `aiodocker.images.build()`)
- `run_task()` : reste tel quel, mode test classique

## 6. Format `stack.yml` généré pour `run_task_swarm()`

Inspiré du compose Swarm validé par l'utilisateur (cf. Configurations) :

```yaml
services:
  agent:
    image: agflow-claude:abc123
    environment:
      KEY: value
      TASK_JSON: ${TASK_JSON_B64}      # injecté via deploy.sh
    networks:
      - agflow-internal
    volumes:
      - source: /srv/agflow/data/dockerfiles/claude/workspace
        target: /app/workspace
        type: bind
    command: ["bash", "-c", "echo $TASK_JSON | base64 -d | <agent_entrypoint>"]
    init: true
    deploy:
      mode: replicated
      replicas: 1
      endpoint_mode: dnsrr
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: none           # one-shot : pas de restart
      resources:
        limits:
          memory: 1G
          cpus: "1.5"
      labels:
        - "agflow.managed=true"
        - "agflow.test_mode=swarm"
        - "agflow.test_session_id=${TEST_SESSION_ID}"

networks:
  agflow-internal:
    external: true
```

Format `deploy.sh` :

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_NAME="agtest_${TEST_SESSION_ID}"

# Inject task.json content as env var (Swarm n'aime pas le stdin pipe)
export TASK_JSON_B64="$(base64 -w0 < "$SCRIPT_DIR/task.json")"
set -a; source "$SCRIPT_DIR/.env"; set +a

# Deploy
docker stack deploy -c "$SCRIPT_DIR/stack.yml" "$STACK_NAME"

# Stream logs jusqu'à la fin du task
docker service logs --follow --raw "${STACK_NAME}_agent" || true

# Cleanup
docker stack rm "$STACK_NAME"
```

## 7. Tests

### 7.1 Tests unitaires `build_service_spec()`

`backend/tests/test_container_runner_service_spec.py` (NOUVEAU) :

- Mapping basique : Dockerfile.json minimal → ServiceSpec valide
- Mapping avec ressources (memory, cpus) → Resources.Limits
- Mapping avec mounts → Mounts type=bind
- Mapping avec env → Env list
- Mapping avec restart_policy "unless-stopped" → RestartPolicy.Condition "on-failure"
- Defaults Swarm injectés : `endpoint_mode: dnsrr`, `placement: node.role == manager`, `Mode: Replicated.Replicas: 1`
- Labels dupliqués service-level + container-level

### 7.2 Tests intégration mockés `start()` / `stop()` / `list_running()`

`backend/tests/test_container_runner_swarm_lifecycle.py` (NOUVEAU) :

- `start()` : mock `services.create()` + `tasks.list()` + `containers.inspect()` → vérifie ContainerInfo retourné
- `start()` rejection si MAX_RUNNING_AGENT_SERVICES atteint
- `stop()` : mock `services.list()` + `services.delete()` → vérifie suppression
- `stop()` fallback containers.delete si pas trouvé en service
- `list_running()` : mock `services.list()` + résolution containers → list[ContainerInfo]

### 7.3 Tests `run_task_swarm()`

`backend/tests/test_container_runner_run_task_swarm.py` (NOUVEAU) :

- `_generate_tmp_files_swarm()` : snapshot des 4 fichiers générés (`.env`, `stack.yml`, `deploy.sh`, `task.json`) sur fixture Dockerfile.json
- `run_task_swarm()` : mock subprocess, vérifie commande lancée + parsing de stdout

### 7.4 Tests `terminal.py` adaptation

`backend/tests/test_terminal_service_resolution.py` (NOUVEAU) :

- `_resolve_to_container_id` : mock services.inspect → trouve container_id du 1er task running
- Fallback : si pas un service, retourne tel quel

### 7.5 Tests existants

- `test_container_runner_*` : refacto pour mocker `services.*` au lieu de `containers.*`
- `tests/workers/*` : devraient passer sans modif (signatures publiques préservées)

## 8. Décomposition en tâches (preview pour le plan)

| # | Tâche | Effort |
|---|---|---|
| T1 | `build_service_spec()` + tests unitaires (mapping Dockerfile.json → ServiceSpec) | 1j |
| T2 | `start()` Swarm + tests mockés (services.create + polling + résolution) | 1j |
| T3 | `stop()` + `list_running()` Swarm + tests mockés | 1j |
| T4 | Adaptation `terminal.py` (résolution service → container) + tests | 0.5j |
| T5 | Vérif non-régression `agent_reaper` + `docker_reconciler` | 0.5j |
| T6 | `_generate_tmp_files_swarm()` + snapshot tests (4 fichiers générés) | 1j |
| T7 | `run_task_swarm()` + tests subprocess mockés | 1j |
| T8 | Vérifs globales + smoke (lint, suite, boot) + commit propagation template ops | 0.5j |

Total : **~6,5j** estimé.

## 9. Hors scope (rappel)

- `run_task()` mode classique — inchangé, reste sur `docker run --rm` via `bash run.sh`
- Frontend toggle UI "Mode classique | Mode Swarm" dans le dialog de test — plan séparé
- Multi-cluster targeting (cibler swarm2 ou autre) — futur chantier B-multi-cluster
- Refacto `services/build_service.py` (build d'images) — non concerné, continue avec `aiodocker.images.build()`
- `MAX_RUNNING_CONTAINERS` → `MAX_RUNNING_AGENT_SERVICES` : on garde le concept mais on compte les services au lieu des containers
- Migration des agents en cours d'exécution sur la prod LXC 201 — la prod va être réinitialisée sur le cluster Swarm de toute façon
- Promotion automatique multi-replicas (Mode.Replicated.Replicas > 1) — futur si besoin

## 10. Critères d'acceptation

- [ ] `build_service_spec()` produit un ServiceSpec valide acceptable par l'API Docker Engine
- [ ] `start()` lance un service Swarm (vérifiable par `docker service ls`) avec les labels agflow
- [ ] `stop()` détruit le service ET son container
- [ ] `list_running()` retourne les containers concrets des services agflow-managed
- [ ] `terminal.py` résout correctement service_name → container_id pour les services Swarm
- [ ] `agent_reaper` marche sans modif (idle agents → service supprimé)
- [ ] `docker_reconciler` marche sans modif (orphelins détectés et nettoyés)
- [ ] `run_task_swarm()` génère 4 fichiers inspectables, exécute le stack, capture les logs, cleanup
- [ ] Tests : 25+ tests verts, 0 régression sur les workers
- [ ] Lint clean
- [ ] Smoke import + boot OK
