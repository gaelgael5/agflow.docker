# 06 — Déploiement de projets

Le déploiement d'une **ressource projet** consiste à matérialiser ses groupes (et leurs instances de produits) sous forme de conteneurs Docker tournant sur des machines réelles. Cette section décrit :
- Les trois modes d'infrastructure cible.
- Le wizard de déploiement et sa machine à états.
- La résolution des variables et secrets.
- Le cycle de vie d'une instance projet (`project_runtime`).

## Modes d'infrastructure cible

L'administrateur choisit **par groupe**, via le template Jinja associé, comment ses conteneurs sont orchestrés. Trois cibles sont supportées.

### Docker simple

**Cas d'usage** : déploiement léger, 1 à quelques nœuds, pas d'auto-rescheduling requis.

**Configuration** : le groupe pointe vers un template `compose_template_slug` qui rend un `docker-compose.yml` complet. Le déploiement écrit ce fichier dans un dossier remote (typiquement `/opt/agflow/runtimes/<runtime_id>/<group_id>/`) puis exécute `docker compose up -d` via SSH.

**Communication entre conteneurs** : tous les conteneurs d'un même `project_runtime` rejoignent un **réseau Docker** dédié (par défaut `agflow-user-{X}`) ; ils se résolvent mutuellement par hostname.

### Docker Swarm

**Cas d'usage** : montée en charge avec plusieurs nœuds, besoin de re-scheduling automatique, gestion centralisée du cluster.

**Configuration** : le groupe pointe vers un template `swarm_template_slug` qui rend une `stack.yml` (format Swarm avec `deploy.replicas`, `placement.constraints`, etc.). Le déploiement écrit la stack côté manager du cluster et exécute `docker stack deploy --compose-file stack.yml <stack_name>`.

**Particularités opérationnelles** :
- Ports LAN exposés depuis un service Swarm : utiliser `mode: host` pour préserver l'IP source du client. Sans cela, le LB IPVS de Swarm interpose une SNAT et le service applicatif voit les requêtes venir d'une IP interne.
- Services Swarm cibles d'autres services overlay : ajouter `endpoint_mode: dnsrr` pour court-circuiter le LB IPVS et permettre la résolution DNS round-robin entre replicas.
- Tokens de jointure (manager / worker) stockés dans Harpocrate, jamais retournés en clair par l'API.

**Init et joining** : voir module M5 (machines / clusters Swarm) — `POST /api/infra/machines/{id}/actions/swarm_init`, `swarm_join`, `swarm_leave`.

### K3s / K8s

**Cas d'usage** : infrastructures plus larges, besoin d'écosystème Kubernetes (operators, ingress controllers, CRDs).

**Configuration** : le groupe pointe vers un template qui rend des manifests Kubernetes (Deployment, Service, ConfigMap, Secret, Ingress…). Le déploiement écrit ces manifests côté machine cible et exécute `kubectl apply -f`.

**Détection** : le health check des machines (`GET /api/infra/machines/{id}/health`) auto-détecte le mode K3s via la présence du port 6443 ouvert. Les machines en K3s ont leur named type configuré pour exécuter les actions via `kubectl` plutôt que `docker`.

### Choix du mode

Le choix se fait au moment de la conception du projet :
- L'administrateur compose les groupes en sachant sur quel mode ils seront déployés.
- Il crée des **templates Jinja distincts** pour chaque mode (slug `myapp-compose`, `myapp-swarm`, `myapp-k3s`).
- Le groupe référence le slug du template approprié dans `compose_template_slug` ou `swarm_template_slug`.

L'opérateur qui pousse le déploiement choisit la machine cible parmi celles du mode attendu (M5 expose la catégorie de chaque machine).

## Conception d'un déploiement

Le déploiement réel suit plusieurs étapes, partagées entre la composition (admin) et l'exécution (opérateur).

### 1. Composition (admin, M6)

1. **Créer la ressource projet** (`POST /api/admin/projects`) avec `display_name`, `description`, `tags`, `network`.
2. **Ajouter les groupes** (`POST /api/admin/groups`) avec `max_replicas`, `compose_template_slug` et/ou `swarm_template_slug`.
3. **Ajouter les instances de produits** dans chaque groupe (`POST /api/admin/product-instances`) en référençant le `catalog_id` (slug d'un produit) et en personnalisant les `variables`.
4. **Déclarer les variables de groupe** (`POST /api/admin/groups/{id}/variables`) pour les valeurs partagées entre instances.
5. **Attacher les scripts de groupe** (`POST /api/admin/groups/{id}/scripts`) en timing `before` ou `after` avec leurs `input_values`.

À tout moment, l'admin peut vérifier la résolubilité des variables via la bannière de la page `ProjectDetailPage` (cf. `GET /api/admin/projects/{id}/env-vars-check`).

### 2. Préparation (opérateur)

1. **Créer un brouillon de déploiement** (`POST /api/admin/project-deployments`) avec `project_id` et `group_servers` (mapping `group_id → machine_id`).
2. **Générer les artefacts** (`POST /api/admin/project-deployments/{id}/generate?…`) qui :
   - Résout tous les secrets via l'`input_resolver`.
   - Rend les templates Jinja (compose ou swarm).
   - Persiste les résultats dans `generated_compose`, `generated_env`, `generated_secrets`, `generated_data`.
   - Passe le déploiement en statut `generated`.

Endpoint additionnel : `GET /api/admin/project-deployments/{id}/groups/{group_id}/compose` retourne le YAML rendu d'un groupe pour prévisualisation.

### 3. Exécution (opérateur)

L'opérateur déclenche le **wizard de déploiement** depuis l'UI (`DeployWizardDialog`) ou directement `POST /api/admin/project-deployments/{id}/push`.

## Wizard de déploiement

`DeployWizardDialog` est un dialogue 3 onglets piloté par une machine à états backend.

### États du déploiement

```
draft
  │ POST /generate
  ▼
generated
  │ start
  ▼
executing_step ─────► step_failed (retry possible)
  │                       │ retry
  │ step réussit          ▼
  │                  executing_step
  ▼
step_complete
  │ tous les before scripts passés
  ▼
before_complete
  │ start docker compose / stack deploy
  ▼
deploying
  │
  ├──► deployed   (tous les after scripts passés)
  └──► failed
```

### Onglet 1 — Configuration

Affiche les `group_servers` choisis, les secrets à fournir (variables `via_env` non résolubles autrement), un récapitulatif des scripts `before` et `after` qui s'exécuteront. L'opérateur ajuste si nécessaire et lance `POST /generate`.

### Onglet 2 — Exécution step-by-step

Pour chaque script `before` (par groupe, dans l'ordre `position`) :
1. L'utilisateur clique « Lancer le step » (ou auto-run si configuré).
2. `POST /api/admin/project-deployments/{id}/execute-step` démarre une tâche `asyncio` isolée.
3. Le script est uploadé via SSH sur la machine cible (`target_kind=fixed_machine` → `machine_id` fixe ; `target_kind=deployment_host` → machine du groupe).
4. Le contenu du script est rendu (substitution `{VAR}` depuis `input_values` résolus, env vars depuis `accumulated_env`) avant exécution.
5. Le script tourne ; ses lignes stdout/stderr sont publiées dans un **bus in-process** (`asyncio.Queue` par déploiement).
6. Le frontend consomme un **flux SSE** (`GET /api/admin/project-deployments/{id}/stream`) qui multiplexe les lignes des steps en cours.
7. Si la dernière ligne du stdout est un JSON parseable, ses clés sont mergées dans `accumulated_env` (selon `env_mapping` du script) pour les steps suivants.
8. À la fin du script :
   - Exit code 0 → `step_complete` ; passage au step suivant.
   - Exit code ≠ 0 → `step_failed` ; l'opérateur voit l'erreur et peut soit `POST /retry-step`, soit corriger les variables et relancer.

### Onglet 3 — Déploiement

Une fois tous les `before` réussis (`status='before_complete'`), l'opérateur clique « Déployer » → `POST /deploy` :
1. Le `compose.yml` ou `stack.yml` rendu est uploadé sur la machine cible.
2. `docker compose up -d` (Docker simple) ou `docker stack deploy` (Swarm) est exécuté via SSH.
3. Les conteneurs démarrent.
4. Les scripts `after` sont exécutés dans l'ordre.
5. Si tout passe → `deployed`. Sinon → `failed`.
6. Les `project_group_runtimes` sont insérés avec leur `remote_path` et leur `compose_yaml` ou `env_text` actuel.

## Résolution des variables

Tout le rendu (scripts, compose, stack, env, MCP config, prompts) passe par le **résolveur unifié** (`input_resolver`) qui supporte quatre syntaxes de placeholders :

| Syntaxe | Résolution |
|---|---|
| `${env-machine://<machine>:<VAR>}` | Lecture dans les `infra_machine_env_vars` de la machine `<machine>` |
| `${vault://api:<NAME>}` | Lecture dans Harpocrate via la clé `<NAME>` |
| `${env://<NAME>}` | Lecture dans la table `platform_secrets` type `env` |
| `${VAR}` ou `$VAR` (MAJUSCULES) | Lecture dans le `.env` du déploiement courant (variables de groupe + accumulated_env) |

### Ordre de résolution

Les substitutions sont appliquées dans l'ordre `env-machine` → `vault` → `env` → `${VAR}`. Une référence non résoluble lève `UnresolvedPlaceholderError` avec un `kind` typé.

### Fail-fast à l'exécution

À l'exécution (push de déploiement, lancement d'agent), une référence non résoluble fait **échouer le step immédiatement** avant tout effet de bord (pas d'upload SSH, pas de lancement de container). Le message d'erreur précise la variable et la raison.

### Collect-all pour le check pré-déploiement

`GET /api/admin/projects/{id}/env-vars-check` utilise la variante `resolve_input_values_collect` du résolveur : au lieu de s'arrêter à la première erreur, il accumule toutes les références non résolubles et retourne un rapport :

```json
{
  "project_id": "uuid",
  "total_missing": 3,
  "items": [
    {
      "group_script_id": "uuid",
      "script_name": "create-oidc-client",
      "group_name": "primary",
      "machine_name": "keycloak1",
      "missing": [
        {
          "var_name": "KC_ADMIN_PASSWORD",
          "kind": "machine_not_found",
          "ref": "${env-machine://ghost:KC_ADMIN_PASSWORD}",
          "detail": "machine 'ghost' inconnue"
        }
      ]
    }
  ]
}
```

Les `kind` possibles : `value_empty`, `var_not_in_env`, `platform_secret_missing`, `machine_not_found`, `env_machine_var_not_found`, `unknown_ref`.

### Garantie de cohérence

Le check pré-déploiement et l'exécution utilisent **le même résolveur** : check vert ⇒ exécution OK. Toute divergence entre les deux est un bug.

## Cycle de vie d'une instance projet

Après un déploiement réussi, une `project_runtimes` existe avec ses `project_group_runtimes` (un par groupe).

### Actions admin sur un group_runtime

| Endpoint | Effet |
|---|---|
| `GET /api/admin/group-runtimes/{id}/status` | Status agrégé (containers up / down / restarting). Interroge la machine cible via SSH. |
| `POST /api/admin/group-runtimes/{id}/start` | `docker compose up -d` ou `docker stack deploy` (si stack existante mais arrêtée). |
| `POST /api/admin/group-runtimes/{id}/stop` | `docker compose down` ou `docker stack rm`. |
| `DELETE /api/admin/group-runtimes/{id}` | Arrête les conteneurs, supprime le dossier remote, soft-delete la ligne. Idempotent : OK même si conteneurs ou dossier déjà absents. |

### Listing

- `GET /api/admin/projects/{project_id}/runtimes` : tous les runtimes d'un projet.
- `GET /api/admin/groups/{group_id}/runtimes` : tous les group_runtimes d'un groupe.
- `GET /api/admin/group-runtimes/{id}` : détail d'un group_runtime avec `env_text` et `compose_yaml` rendus.

### Provisioning v5 (contrat ag.flow)

Endpoint admin public-orienté : `POST /api/admin/projects/{project_id}/runtimes` (async).

- Retourne immédiatement `202 Accepted` avec `{runtime_id, status: "provisioning"}`.
- Un worker asynchrone provisionne le runtime : crée le `project_runtime`, ses `project_group_runtimes` et exécute le déploiement complet.
- Le client poll `GET /api/admin/project-runtimes/{id}/resources` pour suivre l'avancement.

Réponse `RuntimeResourcesResponse` :

```json
{
  "runtime_id": "uuid",
  "status": "provisioning | ready | partially_ready | failed",
  "resources": [
    {
      "resource_id": "uuid-stable-par-runtime",
      "type": "wiki" | "tasks" | "code" | …,
      "name": "string",
      "status": "provisioning | ready | failed | pending_setup",
      "connection_params": { "url": "…", "credentials_ref": "…" },
      "mcp_bindings": [ … ],
      "setup_steps": [ { "name": "…", "status": "…" } ],
      "error_message": "string ou null"
    }
  ]
}
```

Cette réponse alimente l'orchestrateur externe (cf. section 09) pour qu'il connaisse les ressources disponibles et leurs URL avant d'envoyer du work à un agent dans une session liée à ce runtime.

## Décommissionnement

Pour supprimer une instance projet :

```
DELETE /api/admin/group-runtimes/{id}   # un groupe à la fois
DELETE /api/admin/project-deployments/{deployment_id}   # supprime le brouillon
```

L'arrêt est **idempotent** : un nouvel appel sur un runtime déjà supprimé retourne 204 sans erreur.

Les fichiers générés sur la machine cible sont supprimés, mais les volumes Docker nommés (si déclarés dans le compose) sont conservés sauf si l'opérateur les retire explicitement via SSH. Cela évite de perdre des données par accident.

## Sécurité du déploiement

- Tous les secrets résolus pour le déploiement (`generated_secrets`) sont chiffrés en base avant persistance et ne sont jamais retournés en clair par l'API liste, seulement par un endpoint reveal explicite.
- Les connexions SSH utilisent les certificats / mots de passe stockés dans Harpocrate ; les clés privées ne quittent jamais la mémoire du backend.
- Les scripts shell rendus sont uploadés via `cat > /tmp/agflow-script-<random>.sh && chmod +x` puis supprimés à la sortie (même en cas d'erreur, via `finally`).
- Les `.env` rendus ne sont jamais loggés. Les valeurs sensibles sont **masquées** dans les events SSE du wizard (regex `password|secret|key|token` → `***`).
