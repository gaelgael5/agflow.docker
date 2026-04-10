# Workflow Execution View — Spec

## Objectif

Transformer l'onglet Workflow de la vue projet (`/projects/{slug}`) en centre de pilotage. L'utilisateur lance des workflows, suit l'avancement phase par phase, valide les livrables, et demande des corrections — le tout dans une interface verticale avec preview markdown.

## Contexte

- Les workflows sont definis dans le type de projet choisi au wizard (fichiers `.wrk.json`)
- Chaque workflow a des phases, chaque phase a des groupes, chaque groupe a des livrables assignes a des agents
- Les dependances entre livrables (`depends_on`) determinent si un groupe suivant peut demarrer
- Plusieurs workflows peuvent tourner en parallele
- Les phases externes (pointant vers un autre `.wrk.json`) sont resolues a la volee

## Architecture existante

| Element | Table/Fichier | Role |
|---------|--------------|------|
| Definition workflow | `{type_id}/{name}.wrk.json` | Structure phases/groupes/livrables |
| Instance workflow | `project.project_workflows` | Tracking runtime (status, current_phase_id) |
| Phases runtime | `project.workflow_phases` | Status par phase (pending/running/completed) |
| Tasks agent | `project.dispatcher_tasks` | Execution agent (status, instruction, resultat) |
| Livrables | `project.dispatcher_task_artifacts` | Fichiers produits + validation |
| Human gates | `project.hitl_requests` | Questions/validations bloquantes |

## Rendu

### Layout

```
+------------------------------------------------------------------+
| [Workflow selector: onboarding | main | security_audit]  [Lancer] |
+------------------------------------------------------------------+
| HUMAN GATE (si pending) — priorite absolue, toujours en haut     |
|   "Validez-vous la transition vers..." [Repondre]                |
+------------------------------------------------------------------+
| PHASE COURANTE — discovery / Groupe B                             |
|  +-----------------------------+-------------------------------+  |
|  | Livrables                   | Preview                       |  |
|  |                             |                               |  |
|  | > specs_fonctionnelles [v]  | # Specs fonctionnelles        |  |
|  |   agent: requirements_      | ## Contexte                   |  |
|  |   status: review            | Le projet vise...             |  |
|  |                             | ## Fonctionnalites            |  |
|  | > architecture_review       | ...                           |  |
|  |   agent: Architect          |                               |  |
|  |   status: approved          | [Valider] [Commenter] [Editer]|  |
|  |                             |-------------------------------|  |
|  |                             | Revisions (2)                 |  |
|  |                             | v2 14:32 — corrige            |  |
|  |                             |  > "Ajoute section RGPD"      |  |
|  |                             | v1 13:45 — version initiale   |  |
|  +-----------------------------+-------------------------------+  |
+------------------------------------------------------------------+
| PHASE PRECEDENTE — discovery / Groupe A (collapsed)               |
|   3 livrables — tous valides                                      |
+------------------------------------------------------------------+
```

### Principes

1. **Vertical** : phases empilees, la plus recente en haut
2. **Human gate en priorite** : si une hitl_request est pending, elle apparait tout en haut avec bouton de reponse
3. **Split view** : liste des livrables a gauche, preview markdown a droite
4. **Phase courante expanded** : les phases precedentes sont collapsed avec un resume
5. **Pas de prediction** : on n'affiche pas les phases futures. Quand la phase courante est terminee, on evalue et on affiche la suivante

### Workflow selector

- Dropdown listant les workflows du type de projet (`project_workflows` en base)
- Chaque workflow affiche son status (pending / active / completed)
- Bouton "Lancer" pour demarrer un workflow pending
- Plusieurs workflows actifs possibles (parallele)

### Phase courante

- Titre : nom de la phase + groupe en cours
- Liste des livrables du groupe avec :
  - Nom du livrable
  - Agent assigne
  - Status : `running` (spinner) | `pending` (gris) | `review` (orange, livrable produit en attente validation) | `approved` (vert) | `revision` (bleu, correction en cours)
- Click sur un livrable → affiche le contenu markdown a droite

### Panel livrable (droite)

Le panel droit a deux modes :

**Mode lecture (defaut)** :
- Rendu markdown (MarkdownRenderer)
- Historique des revisions visible en dessous (fil chronologique)
- Trois boutons :
  - **Valider** : marque approved
  - **Commenter** : ouvre une zone de commentaire en bas → aller-retour LLM
  - **Editer** : bascule en mode edition

**Mode edition** :
- Textarea markdown brut (contenu du fichier)
- Bouton **Sauvegarder** : ecrit le fichier, repasse en mode lecture
- Bouton **Annuler** : revient au mode lecture sans sauver

### Historique des revisions

Chaque livrable affiche son fil de revisions sous le contenu :

```
v3 (actuel) — 14:32 — Agent a corrige
  > Commentaire utilisateur : "Ajoute les contraintes RGPD"
v2 — 14:15 — Agent a corrige
  > Commentaire utilisateur : "Manque la section securite"
v1 — 13:45 — Version initiale
```

- Stocke dans `deliverable_remarks` (table existante) + un champ `version` sur l'artifact
- Chaque commentaire cree une entree dans `deliverable_remarks`
- Chaque re-generation par l'agent incremente la version
- Click sur une version ancienne → affiche son contenu (lecture seule)

### Cycle de correction

```
1. Agent produit livrable → status = "review", version = 1
2. Utilisateur lit le markdown
3a. [Valider] → status = "approved" → verifier si groupe suivant peut demarrer
3b. [Commenter] → commentaire stocke dans deliverable_remarks
    → status = "revision"
    → appel gateway: direct_agent={agent_id}
      message = "Corrige ce livrable:\n{contenu_actuel}\n\nCommentaire utilisateur:\n{commentaire}"
    → agent repropose → save_deliverable ecrase le fichier
    → version += 1, status = "review"
    → retour etape 2
3c. [Editer] → utilisateur modifie directement le markdown
    → sauvegarde le fichier
    → version += 1 (edition manuelle)
    → reste en status "review"
```

### Phases — expand/collapse

**Phase en cours** : toujours expanded, non collapsable

**Phases terminees** : collapsed par defaut avec resume :
```
+------------------------------------------------------------------+
| > discovery / Groupe A                              3/3 valides  |
+------------------------------------------------------------------+
```
Click → deplie et montre la liste des livrables avec leur status.
Re-click → replie.

**Phase avec livrable rejete ou en revision** : expanded par defaut (attire l'attention)

### Avancement automatique

Quand un livrable est valide :

1. Verifier si des livrables du groupe suivant en dependent (`depends_on`)
2. Si aucune dependance → le groupe suivant peut demarrer immediatement (dispatch agents)
3. Si dependance → attendre que le livrable requis soit approved
4. Quand tous les livrables de tous les groupes de la phase sont approved → phase complete
5. Evaluer la phase suivante via `resolve_next_phase` (ou human_gate si configuree)
6. Si phase externe → `resolve_create_external_workflow` la resout a la volee

### Lancement d'un workflow

1. Utilisateur selectionne un workflow pending et clique "Lancer"
2. Backend cree la premiere `workflow_phase` (status=running) + les `dispatcher_tasks` pour le groupe A
3. Les agents sont dispatches via le gateway
4. Le frontend poll ou recoit via WS les updates

## Endpoints necessaires

### Existants a adapter

| Endpoint | Adaptation |
|----------|-----------|
| `GET /api/projects/{slug}/workflows` | Deja OK — liste les workflows avec status |
| `GET /api/projects/{slug}/workflow` | Adapter pour retourner les phases runtime (pas seulement le JSON) |

### Nouveaux

| Endpoint | Methode | Role |
|----------|---------|------|
| `POST /api/projects/{slug}/workflows/{id}/start` | POST | Lancer un workflow (creer phase 1 + dispatch agents groupe A) |
| `GET /api/projects/{slug}/workflows/{id}/phases` | GET | Phases runtime avec livrables et status |
| `POST /api/deliverables/{id}/validate` | POST | Deja existant — marquer approved/rejected |
| `POST /api/deliverables/{id}/revise` | POST | Nouveau — envoyer commentaire → relancer agent pour correction |
| `PUT /api/deliverables/{id}/content` | PUT | Deja existant — edition directe du contenu par l'utilisateur |
| `GET /api/deliverables/{id}/remarks` | GET | Deja existant — historique des commentaires/versions |
| `POST /api/projects/{slug}/workflows/{id}/advance` | POST | Evaluer et creer la phase suivante si possible |

### Detail reponse `GET /workflows/{id}/phases`

```json
{
  "workflow_id": 443,
  "workflow_name": "onboarding",
  "status": "active",
  "human_gate": {
    "id": "uuid",
    "prompt": "Validez-vous...",
    "agent_id": "Orchestrator",
    "created_at": "..."
  },
  "phases": [
    {
      "id": 12,
      "phase_key": "discovery",
      "phase_name": "Comprendre le besoin",
      "group_key": "B",
      "status": "running",
      "deliverables": [
        {
          "id": 45,
          "key": "specs_fonctionnelles",
          "agent_id": "requirements_analyst",
          "status": "review",
          "file_path": "projects/perf/team1/...",
          "content": "# Specs fonctionnelles\n\n...",
          "created_at": "...",
          "reviewer": null,
          "review_comment": null
        }
      ]
    },
    {
      "id": 11,
      "phase_key": "discovery",
      "phase_name": "Comprendre le besoin",
      "group_key": "A",
      "status": "completed",
      "deliverables": [...]
    }
  ]
}
```

### Detail `POST /deliverables/{id}/revise`

```json
// Request
{ "comment": "Ajoute une section sur les contraintes RGPD" }

// Backend:
// 1. Met le status a "revision"
// 2. Lit le contenu actuel du fichier
// 3. Appelle gateway: direct_agent={agent_id}, message = livrable + commentaire
// 4. L'agent repropose → save_deliverable ecrase le fichier
// 5. Status repasse a "review"

// Response
{ "ok": true, "status": "revision" }
```

## Frontend — Composants

| Composant | Role |
|-----------|------|
| `WorkflowExecutionPanel` | Container principal — selector + liste phases |
| `WorkflowPhaseCard` | Une phase (expand/collapse) avec ses livrables |
| `DeliverableListItem` | Ligne livrable avec status badge + click pour selectionner |
| `DeliverablePanel` | Split right — mode lecture (markdown + historique) / mode edition (textarea) |
| `RevisionHistory` | Fil chronologique des commentaires + versions sous le contenu |
| `HumanGateBanner` | Banner prioritaire en haut pour les gates pending |
| `CommentInput` | Zone de commentaire inline (pas modal) en bas du panel droit |

## Schema DB — ajouts

```sql
-- Version tracking sur les artifacts
ALTER TABLE project.dispatcher_task_artifacts
  ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;

-- Le champ status existant est etendu :
-- 'pending' → agent pas encore lance
-- 'running' → agent en cours de production
-- 'review' → livrable produit, en attente de validation
-- 'revision' → commentaire envoye, agent corrige
-- 'approved' → valide par l'utilisateur
-- 'rejected' → rejete

-- Modifier la contrainte CHECK si necessaire
-- ALTER TABLE project.dispatcher_task_artifacts
--   DROP CONSTRAINT IF EXISTS dispatcher_task_artifacts_status_check,
--   ADD CONSTRAINT dispatcher_task_artifacts_status_check
--     CHECK (status IN ('pending', 'running', 'review', 'revision', 'approved', 'rejected'));
```

La table `deliverable_remarks` existe deja et stocke les commentaires :
```sql
-- Existant
CREATE TABLE project.deliverable_remarks (
    id SERIAL PRIMARY KEY,
    artifact_id INTEGER REFERENCES project.dispatcher_task_artifacts(id),
    reviewer TEXT NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## Ce qu'on ne fait PAS

- Predire les phases futures
- Afficher l'arbre complet du workflow
- Gerer les phases externes a l'avance (on les resout quand on y arrive)
- Produire du JSON — les agents produisent du markdown lisible
- Gerer les issues/taches (viendra apres via post-traitement des livrables)
