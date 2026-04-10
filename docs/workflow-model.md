# Workflow Model — Schema technique

## Structure racine

Les cles sont a la RACINE du JSON. Pas de wrapper.

| Champ | Type | Description |
|---|---|---|
| `team` | `string` | Equipe source des agents (`Shared/Teams/{team}/agents_registry.json`) |
| `phases` | `object` | Dictionnaire des phases (cle = snake_case ou `_N`) |
| `transitions` | `array` | Transitions entre phases |
| `rules` | `object` | Regles globales |
| `categories` | `array` | Categories de livrables (optionnel) |
| `coverage_report` | `object` | Rapport de couverture agents (optionnel, genere par LLM) |
| `missing_roles` | `array` | Postes manquants identifies (optionnel, genere par LLM) |

Le champ `team` determine quelle equipe fournit les agents disponibles dans le workflow.

## Phase

| Champ | Type | Requis | Description |
|---|---|---|---|
| `name` | `string` | oui | Nom affiche |
| `description` | `string` | non | Description fonctionnelle |
| `order` | `integer` | oui | Ordre sequentiel (1, 2, 3...) |
| `groups` | `array` | oui | Groupes paralleles contenant les livrables |
| `exit_conditions` | `object` | non | Conditions de sortie |
| `next_phase` | `string` | non | Override de transition (pour les boucles) |

### Phase externe

Une phase peut referencer un workflow externe. A l'execution, les phases du workflow reference sont inlinees a la place de la phase externe.

| Champ | Type | Description |
|---|---|---|
| `type` | `"external"` | Marque la phase comme externe |
| `external_workflow` | `string` | Nom du fichier `.wrk.json` reference |

Exemple :
```json
"phase_6": {
  "name": "Phase externe",
  "order": 1,
  "type": "external",
  "external_workflow": "onbording.wrk.json",
  "exit_conditions": { "human_gate": true }
}
```

La resolution des phases externes est recursive (max 10 niveaux) et detecte les cycles.

## Groupe parallele

Les groupes sont un ARRAY ordonne dans la phase. L'ordre du array determine l'ordre d'execution (le premier groupe est execute en premier).

| Champ | Type | Description |
|---|---|---|
| `id` | `string` | Identifiant du groupe (A, B, C, ...) |
| `deliverables` | `array` | Livrables de ce groupe |

```json
"groups": [
  { "id": "A", "deliverables": [...] },
  { "id": "B", "deliverables": [...] },
  { "id": "C", "deliverables": [...] }
]
```

- Groupe A dispatche en premier
- Groupe B attend que tous les livrables required du groupe A soient termines
- Groupe C attend que tous les livrables required du groupe B soient termines
- Auto-dispatch recursif (max 5 niveaux)

## Livrable (deliverable)

Chaque livrable est un objet DANS un groupe. Il represente une unite de travail assignee a un agent.

| Champ | Type | Requis | Description |
|---|---|---|---|
| `id` | `string` | oui | Identifiant unique du livrable |
| `Name` | `string` | oui | Nom d'affichage |
| `description` | `string` | non | Description du livrable |
| `agent` | `string` | oui | Agent responsable (doit exister dans le registry d'equipe) |
| `required` | `boolean` | oui | Bloquant pour la completion du groupe |
| `type` | `string` | oui | Type de livrable (voir ci-dessous) |
| `depends_on` | `array[string]` | non | Format `"GROUPE_ID:LIVRABLE_ID"` — info contextuelle pour l'agent |
| `roles` | `array[string]` | non | Roles actifs de l'agent pour ce livrable |
| `missions` | `array[string]` | non | Missions activees |
| `skills` | `array[string]` | non | Competences activees |
| `category` | `string` | non | Categorie du livrable |

### Types de livrables

| Type | Description |
|---|---|
| `documentation` | Documents textuels (PRD, specs, audit, guides) |
| `code` | Code source (implementation, scripts) |
| `design` | Maquettes, wireframes, diagrammes UX |
| `automation` | Pipelines CI/CD, scripts d'automatisation |
| `tasklist` | Backlogs, plannings, listes de taches |
| `specs` | Specifications techniques (architecture, ADR, schemas) |
| `contract` | Documents contractuels, CGU, mentions legales |

### depends_on (livrable)

Le `depends_on` est une **information contextuelle**, pas une contrainte de dispatch.
Il dit a l'agent "utilise les resultats de ces livrables pour produire le tien".
Le dispatch est gere uniquement par l'ordre sequentiel des groupes.

Format : `"GROUPE_ID:LIVRABLE_ID"` (ex: `"A:adrs"`, `"B:openapi_spec"`)

```
VALIDE :   "depends_on": ["A:adrs", "A:wireframes"]
INVALIDE : "depends_on": ["architect:adrs"]              <- format agent:step, pas GROUP:id
INVALIDE : "depends_on": ["design:A:adrs"]               <- cross-phase interdit
```

### Cle de sortie dans le state

`{GROUP_ID}:{deliverable_id}` — ex: `"A:adrs"`, `"B:wireframes"`

### Profil livrable (roles, missions, skills)

Chaque livrable peut specifier quels roles, missions et competences de l'agent sont actives.
Ces valeurs correspondent aux fichiers `role_*.md`, `mission_*.md` et `skill_*.md` dans le catalogue agent (`Shared/Agents/{id}/`).

Si absents, l'agent utilise son profil complet (identity + tous roles/missions/skills).
Si presents, seuls les roles/missions/skills listes sont injectes dans le prompt de l'agent.
L'editeur propose un skill-match automatique (baguette magique) via LLM.

Les roles/missions/skills invalides (fichier inexistant dans `Shared/Agents/{agent_id}/`) sont automatiquement nettoyes lors de la generation des prompts.

## Transition

`transitions` est un **ARRAY d'objets**, PAS un dictionnaire.

| Champ | Type | Description |
|---|---|---|
| `from` | `string` | Phase source |
| `to` | `string` | Phase destination |
| `human_gate` | `boolean` | Validation humaine requise avant transition |
| `from_side` | `string` | Cote de sortie sur le canvas (left, right, top, bottom) |
| `to_side` | `string` | Cote d'arrivee sur le canvas (left, right, top, bottom) |

## Regles globales

| Champ | Type | Description |
|---|---|---|
| `critical_alert_blocks_transition` | `boolean` | Bloque la transition si alertes critiques |
| `human_gate_required_for_all_transitions` | `boolean` | Force validation humaine sur toutes les transitions |
| `max_agents_parallel` | `integer` | Nombre maximum d'agents simultanes |

## Conditions de sortie

| Condition | Description |
|---|---|
| `all_deliverables_complete` | Tous les livrables required sont termines |
| `no_critical_alerts` | Aucune alerte critique en cours |
| `qa_verdict_go` | Le QA a donne un verdict positif |
| `staging_validated` | L'environnement de staging est valide |
| `human_gate` | Validation humaine requise |
| `no_critical_bugs` | Aucun bug critique ouvert |

## Statuts livrable

```
(absent) -> pending -> complete -> pending_review -> approved
```

Les statuts `complete`, `pending_review` et `approved` sont consideres comme termines pour la resolution des dependances.

## Dispatch

Pour chaque groupe dans l'ordre du array :

1. Verifier que tous les livrables required des groupes precedents sont termines
2. Pour chaque livrable du groupe courant non termine : dispatcher l'agent assigne
3. Un seul groupe actif a la fois
4. Quand le groupe courant termine, auto-dispatch du groupe suivant (recursif, max 5 niveaux)
5. Quand tous les groupes sont termines, verifier les exit conditions de la phase

Pas de delegation — tous les agents sont dispatches directement.

### Fallback disque

En cas de perte de state (redemarrage), le workflow engine peut verifier l'existence de fichiers livrables sur le disque et marquer les livrables correspondants comme `complete`.

## Fichiers associes

### Workflow

| Fichier | Emplacement | Description |
|---|---|---|
| `Workflow.json` | `Shared/Teams/{team}/` | Workflow template d'equipe |
| `{name}.wrk.json` | `Shared/Projects/{project}/` ou `config/Projects/{project}/` | Workflow de projet |
| `{name}.wrk.design.json` | meme emplacement | Positions des phases sur le canvas |
| `{name}.wrk.phase.{phase_id}.{group_id}.md` | meme emplacement | Prompt orchestrateur par phase/groupe |
| `{name}.wrk.livr.{phase_id}.{group_id}.{deliv_id}.{agent_id}.md` | meme emplacement | Prompt agent par livrable |

### Chats (onboarding)

| Fichier | Emplacement | Description |
|---|---|---|
| `{chat_id}.{type}.md` | `Shared/Projects/{project}/` ou `config/Projects/{project}/` | Prompt orchestrateur du chat |
| `{chat_id}.{type}.{agent_id}.md` | meme emplacement | Prompt agent pour le chat |

La configuration des chats est dans `project.json` :

```json
{
  "chats": [
    {
      "id": "discovering_project",
      "type": "onboarding",
      "source_prompt": "onboarding.md",
      "agents": ["Architect", "requirements_analyst", "ux_designer"],
      "agent_config": {
        "Architect": { "roles": [...], "missions": [...], "skills": [...] }
      },
      "prompt": "discovering_project.onboarding.md",
      "agent_prompts": {
        "Architect": "discovering_project.onboarding.Architect.md",
        "requirements_analyst": "discovering_project.onboarding.requirements_analyst.md",
        "ux_designer": "discovering_project.onboarding.ux_designer.md"
      }
    }
  ]
}
```

### Agents

| Fichier | Emplacement | Description |
|---|---|---|
| `agents_registry.json` | `Shared/Teams/{team}/` | Liste des agents de l'equipe |
| `agent.json` | `Shared/Agents/{id}/` | Config agent (name, description) |
| `identity.md` | `Shared/Agents/{id}/` | Identite de l'agent |
| `role_*.md` | `Shared/Agents/{id}/` | Fichiers de roles |
| `mission_*.md` | `Shared/Agents/{id}/` | Fichiers de missions |
| `skill_*.md` | `Shared/Agents/{id}/` | Fichiers de competences |

### Generation des prompts

La generation est declenchee depuis l'admin dashboard lors de la sauvegarde d'un workflow.

**Prompts orchestrateur** (`{name}.wrk.phase.{phase_id}.{group_id}.md`) :
- Template : `Shared/Models/{culture}/prompt-phase-orchestrator.md`
- Variables : `{project_context}`, `{agents}` (contenus orch_*.md), `{deliverables}`
- Les phases externes sont ignorees (leurs prompts viennent du workflow reference)

**Prompts agent** (`{name}.wrk.livr.{phase_id}.{group_id}.{deliv_id}.{agent_id}.md`) :
- Template : `Shared/Models/{culture}/prompt-delivrable.md`
- Variables : `{project_context}`, `{agent_card}` (identity + roles/missions/skills filtres), `{deliverable}`
- Les roles/missions/skills invalides sont nettoyes avant injection

### Scopes de stockage

| Scope | Emplacement | Usage |
|---|---|---|
| Configuration (templates) | `Shared/Projects/` | Modeles reutilisables, source pour copie |
| Production (config) | `config/Projects/` | Configuration active, utilisee par le runtime |

Les deux scopes supportent les memes fichiers. La copie Configuration -> Production est une copie recursive du repertoire complet (`shutil.copytree`).

