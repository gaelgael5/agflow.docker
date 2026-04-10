# Design : Refactoring groups/deliverables — Phase 1

**Date** : 2026-03-26
**Scope** : Schema + Engine Python + Migration + Validation (pas l'éditeur visuel)

## Contexte

Le `parallel_group` est défini sur l'AGENT. Les livrables sont dans un dict séparé.
Un agent ne peut avoir ses livrables que dans un seul groupe. Le bloc `agents` dans
la phase duplique de l'info. Les `depends_on` existent à deux niveaux (agent ET livrable).

## Nouveau format .wrk.json

### Ce qui disparaît de la phase

- Bloc `agents` (dict d'agents avec role, required, parallel_group, depends_on, etc.)
- Bloc `deliverables` (dict plat de livrables)
- `parallel_groups` racine (objet metadata {description, order})

### Ce qui apparaît : `groups` (array dans la phase)

```json
{
  "_1": {
    "name": "Design",
    "order": 2,
    "groups": [
      {
        "id": "A",
        "deliverables": [
          { "id": "adrs", "Name": "ADR", "agent": "Architect", "required": true, "type": "specs", "description": "ADR du projet", "depends_on": [] },
          { "id": "wireframes", "Name": "Wireframes", "agent": "ux_designer", "required": true, "type": "design", "description": "Wireframes mobile", "depends_on": [] }
        ]
      },
      {
        "id": "B",
        "deliverables": [
          { "id": "openapi_spec", "Name": "Spec OpenAPI", "agent": "Architect", "required": true, "type": "specs", "description": "Spec OpenAPI", "depends_on": ["A:adrs"] }
        ]
      },
      {
        "id": "C",
        "deliverables": [
          { "id": "sprint_backlog", "Name": "Sprint backlog", "agent": "planner", "required": true, "type": "tasklist", "description": "Sprint backlog", "depends_on": ["B:openapi_spec", "A:wireframes"] }
        ]
      }
    ],
    "exit_conditions": { "all_deliverables_complete": true, "human_gate": true }
  }
}
```

### Champs d'un livrable

| Champ | Type | Description |
|-------|------|-------------|
| `id` | string | Identifiant unique dans le workflow (ex: `adrs`) |
| `Name` | string | Nom d'affichage |
| `description` | string | Description du livrable |
| `agent` | string | Agent assigné (doit exister dans le registry) |
| `required` | bool | Bloquant pour la complétion du groupe |
| `type` | string | Documentation, Code, Design, Automation, Tasklist, Specs, Contract |
| `depends_on` | string[] | Format `"GROUPE_ID:LIVRABLE_ID"` — info contextuelle pour l'agent |
| `roles` | string[] | (optionnel) Rôles actifs de l'agent |
| `missions` | string[] | (optionnel) Missions actives |
| `skills` | string[] | (optionnel) Skills actifs |
| `category` | string | (optionnel) Catégorie du livrable |

### Rôle du depends_on

Le `depends_on` est une **information contextuelle**, pas une contrainte de dispatch.
Il dit à l'agent "utilise les résultats de ces livrables pour produire le tien".
Le dispatch est géré uniquement par l'ordre séquentiel des groupes (A → B → C).

### Clé de sortie dans le state

`{GROUP}:{deliverable_id}` — ex: `"A:adrs"`, `"B:wireframes"`

### Délégation

Supprimée pour l'instant. Tous les agents sont dispatchés directement.

### Phases externes

Inchangées — `type: "external"` + `external_workflow` restent tels quels.

## Script de migration

Pour chaque `.wrk.json` dans `Shared/Projects/` :

1. Pour chaque phase non-externe :
   a. Collecter les groupes depuis `agent.parallel_group` (default "A")
   b. Pour chaque livrable, trouver son agent, trouver le groupe de cet agent
   c. Construire l'objet livrable : `pipeline_step` → `id`, ajouter `Name`
   d. Convertir `depends_on` de `"agent:step"` en `"GROUPE:step"`
   e. Placer le livrable dans le bon groupe
2. Remplacer `agents` + `deliverables` par `groups`
3. Supprimer `parallel_groups` racine si présent
4. Écrire le fichier migré

**Cutover net** — l'ancien format n'est plus supporté.

## Workflow engine (`workflow_engine.py`)

### Fonctions modifiées

**`get_ordered_groups(phase_id, team_id)`**
- Lit `phase.groups` array, retourne les ids dans l'ordre du array

**`get_deliverables_for_group(phase_id, group_id, team_id)`** (nouvelle)
- Retourne la liste des livrables du groupe donné

**`get_agents_for_group(phase_id, group_id, team_id)`**
- Déduit les agents uniques depuis `group.deliverables[].agent`

**`get_deliverables_to_dispatch(phase_id, agent_outputs, team_id)`**
- Itère sur `phase.groups` dans l'ordre
- Pour chaque groupe : vérifie que tous les required des groupes précédents sont terminés
  (vérifie `agent_outputs["{agent}:{id}"]`)
- Si groupe précédent pas terminé → stop
- Pour chaque livrable du groupe courant non terminé → ajouter au dispatch
- Retourne le premier groupe avec des livrables à dispatcher

**`get_agents_to_dispatch(phase_id, agent_outputs, team_id)`**
- Appelle `get_deliverables_to_dispatch()`, extrait les agents uniques

**`check_phase_complete(phase_id, agent_outputs, team_id)`**
- Itère sur tous les `groups[].deliverables` pour trouver les required
- Vérifie `agent_outputs["{agent}:{id}"]`

### Interface de retour inchangée

```python
# get_deliverables_to_dispatch retourne :
[{"deliverable_key": "Architect:adrs", "agent_id": "Architect", "step": "adrs",
  "parallel_group": "A", "required": True, "type": "specs", "description": "..."}]

# get_agents_to_dispatch retourne :
[{"agent_id": "Architect", "role": "..."}]
```

Gateway et orchestrateur ne changent pas.

## Validation (`web/server.py`)

### Supprimé
- Validation de `parallel_group` sur les agents
- Validation de `depends_on` sur les agents
- Toute validation du bloc `agents`

### Ajouté
- Chaque phase non-externe a au moins un groupe avec un livrable required
- Chaque `depends_on` au format `"GROUPE:ID"` référence un livrable existant dans un groupe de la même phase
- Les ids de livrables sont uniques au sein du workflow
- Chaque agent référencé dans un livrable existe dans le registry d'équipe

### Inchangé
- Validation des transitions
- Validation des exit_conditions

## Fichiers impactés

| Fichier | Modification |
|---------|-------------|
| `Agents/Shared/workflow_engine.py` | Réécriture dispatch |
| `web/server.py` | Validation |
| `docs/workflow-model.md` | Mise à jour spec |
| `tests/conftest.py` | Fixtures nouveau format |
| `tests/shared/test_workflow_engine.py` | Tests dispatch |
| `migrate_groups.py` (nouveau) | Script migration |

## Ce qui NE change PAS en Phase 1

- L'éditeur visuel admin (Phase 2)
- Les prompts LLM (séparé)
- `gateway.py` (même interface de retour)
- `orchestrator.py` (même interface de retour)

## Vérification

- [ ] Workflow migré se charge sans erreur
- [ ] Dispatch exécute groupes A → B → C
- [ ] Un agent peut avoir des livrables dans des groupes différents
- [ ] depends_on "A:adrs" = info contextuelle, pas bloquant au dispatch
- [ ] Validation rejette depends_on référençant un livrable inexistant
- [ ] Validation rejette agent inexistant dans le registry
- [ ] exit_conditions fonctionnent comme avant
- [ ] Clé de sortie state = {agent_id}:{deliverable_id}
