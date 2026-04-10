# Unification Onboarding → Workflow Tracking

> **Goal:** L'onboarding utilise les mêmes tables de persistance (`project_workflows` + `workflow_phases`) que les workflows normaux. Le code d'accès IO est factorisé dans `workflow_tracker.py`.

## Contexte

Aujourd'hui l'onboarding a son propre chemin de persistance :
- `pm_projects.analysis_task_id` / `analysis_status`
- Thread ID `onboarding-{slug}`
- INSERT directs dans `dispatcher_tasks` sans `workflow_id` / `phase_id`

Le workflow normal utilise `project_workflows` + `workflow_phases`.

L'objectif est que l'onboarding écrive dans les mêmes tables, via les mêmes méthodes (`workflow_tracker.db_*`), tout en gardant son code spécifique (orchestrateur, tools, prompts).

## Plan

### Task 1 : Création du workflow onboarding au démarrage

**Fichier** : `hitl/services/analysis_service.py` — `start_analysis()`

Aujourd'hui :
- INSERT dans `dispatcher_tasks` 
- UPDATE `pm_projects.analysis_task_id` + `analysis_status`

Après :
- INSERT dans `project_workflows` (type='onboarding', status='active') via `db_create_workflow` ou direct
- INSERT dans `workflow_phases` (phase='discovery', group='A') via `db_create_phase`
- Le `workflow_id` et `phase_id` sont connus dès ce moment
- INSERT dans `dispatcher_tasks` avec `workflow_id` + `phase_id`
- UPDATE `pm_projects.analysis_task_id` garde l'ancien champ pour compatibilité frontend
- Ajouter `pm_projects.onboarding_workflow_id` pour référencer le workflow

### Task 2 : Thread ID basé sur workflow_id

**Fichiers** : `analysis_service.py`, `orchestrator_tools.py`, `base_agent.py`, `hitl_service.py`, `gateway.py`

Aujourd'hui :
- `thread_id = "onboarding-{slug}"`
- Détection par `thread_id.startswith("onboarding-")`

Après :
- `thread_id = "workflow-{workflow_id}"` 
- Détection par lookup en DB : `SELECT workflow_type FROM project_workflows WHERE id = {workflow_id}`
- Ou garder un préfixe : `thread_id = "onboarding-wf-{workflow_id}"` pour rétrocompatibilité

**Format retenu** : `workflow-{id}` — générique, pas de cas particulier. Le type (onboarding, development, etc.) se résout en DB via `project_workflows.workflow_type`.

### Task 3 : orchestrator_tools.py — utiliser workflow_id + phase_id

**Fichier** : `Agents/Shared/orchestrator_tools.py`

Aujourd'hui `_ctx` contient :
- `thread_id`, `team_id`, `project_slug`

Après, ajouter :
- `workflow_id` — l'ID du workflow en cours
- `phase_id` — l'ID de la phase courante
- `workflow_name` — pour le chemin fichier

Les tools `dispatch_agent`, `ask_human`, `human_gate` utilisent ces IDs pour :
- INSERT `dispatcher_tasks` avec `workflow_id` + `phase_id`
- INSERT `hitl_requests` avec `thread_id = workflow-{workflow_id}`
- `save_deliverable` construit le chemin avec `workflow_id:name/phase_id:key-group/`

### Task 4 : gateway.py — propager workflow_id dans le state

**Fichier** : `Agents/gateway.py`

Aujourd'hui le state LangGraph contient `_thread_id = "onboarding-{slug}"`.

Après, ajouter au state :
- `_workflow_id` — l'ID du workflow
- `_phase_id` — l'ID de la phase courante

Le `/invoke` endpoint reçoit `workflow_id` dans le payload (envoyé par `analysis_service`) et le propage dans le state.

`run_orchestrated` utilise `workflow_id` + `phase_id` pour :
- UPDATE `dispatcher_tasks.completed_at` avec le bon `phase_id`
- Vérifier les agents pending par `phase_id`

### Task 5 : analysis_service.py — refactorer les accès DB

**Fichier** : `hitl/services/analysis_service.py`

Remplacements :
| Avant | Après |
|-------|-------|
| `pm_projects.analysis_status` | `project_workflows.status` (lu via `db_get_workflow`) |
| `pm_projects.analysis_task_id` | `project_workflows.id` (le workflow_id EST l'identifiant) |
| `"onboarding-{slug}"` | `"workflow-{workflow_id}"` |
| INSERT direct `dispatcher_tasks` | Via `workflow_tracker` ou avec `workflow_id` + `phase_id` |
| `_sync_status()` lit `pm_projects` | Lit `project_workflows` + `workflow_phases` |
| `get_analysis_status()` | Lit `project_workflows.status` + `current_phase_id` |

Les méthodes `_run_analysis_pipeline` et `send_free_message` passent `workflow_id` à la gateway au lieu de construire un thread_id.

### Task 6 : hitl_service.py — détecter l'onboarding par workflow_type

**Fichier** : `hitl/services/hitl_service.py`

Aujourd'hui :
```python
if thread_id.startswith("onboarding-"):
    project_slug = thread_id.replace("onboarding-", "", 1)
```

Après :
```python
# Extraire workflow_id du thread_id
workflow_id = int(thread_id.replace("workflow-", ""))
workflow = await db_get_workflow(workflow_id)
if workflow and workflow["workflow_type"] == "onboarding":
    project_slug = workflow["project_slug"]
```

### Task 7 : Frontend — WizardStepAnalysis

**Fichier** : `hitl-frontend/src/components/features/project/WizardStepAnalysis.tsx`

Aujourd'hui :
- Appelle `/api/projects/{slug}/analysis/status`
- Le thread_id WS est `onboarding-{slug}`

Après :
- L'API `/analysis/status` retourne aussi `workflow_id`
- Le thread_id WS est `workflow-{workflow_id}`
- Le composant stocke `workflowId` et l'utilise pour le WS matching

### Task 8 : Migration pm_projects

**Fichier** : `scripts/init.sql`

Ajouter :
```sql
ALTER TABLE project.pm_projects ADD COLUMN onboarding_workflow_id INTEGER REFERENCES project.project_workflows(id);
```

Garder `analysis_status` et `analysis_task_id` comme raccourcis (mis à jour en parallèle) jusqu'à ce que tout le frontend soit migré. Puis les supprimer.

## Ordre d'exécution

1. Task 1 (création workflow) + Task 8 (migration DB) — fondation
2. Task 3 (orchestrator_tools) + Task 4 (gateway) — propagation workflow_id
3. Task 2 (thread_id) — changement de format
4. Task 5 (analysis_service) — refactorer les accès DB
5. Task 6 (hitl_service) — détection par type
6. Task 7 (frontend) — adapter le WS matching

## Risques

- **Rétrocompatibilité** : les données existantes en DB ont `thread_id = "onboarding-{slug}"`. Les nouvelles auront `"workflow-{workflow_id}"`. Il faut gérer les deux pendant la transition.
- **Tests** : les tests existants (`test_analysis_service.py`) utilisent le format ancien. À adapter.
- **Onboarding en cours** : si un onboarding est en cours pendant la migration, il faut le terminer avec l'ancien format ou le migrer.

## Vérification

- Lancer un onboarding complet → vérifier que `project_workflows` + `workflow_phases` sont remplis
- Vérifier que les livrables sont au bon chemin (`{workflow_id}:{name}/...`)
- Vérifier que le frontend affiche correctement
- Vérifier que l'Inbox fonctionne (détection par workflow_type au lieu de thread_id prefix)
