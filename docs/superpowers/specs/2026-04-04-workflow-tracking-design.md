# Workflow Tracking — Design Spec

## Tables

```sql
CREATE TABLE project.project_workflows (
    id SERIAL PRIMARY KEY,
    project_slug TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    workflow_type TEXT DEFAULT 'custom',
    workflow_json_path TEXT,
    status TEXT DEFAULT 'pending',
    mode TEXT DEFAULT 'sequential',
    priority INTEGER DEFAULT 50,
    iteration INTEGER DEFAULT 1,
    current_phase_id INTEGER,
    config JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE project.workflow_phases (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER REFERENCES project.project_workflows(id),
    phase_key TEXT NOT NULL,
    phase_name TEXT,
    group_key TEXT DEFAULT 'A',
    phase_order INTEGER DEFAULT 0,
    group_order INTEGER DEFAULT 0,
    iteration INTEGER DEFAULT 1,
    depends_on_workflow_id INTEGER REFERENCES project.project_workflows(id),
    status TEXT DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE project.project_workflows 
    ADD CONSTRAINT fk_current_phase 
    FOREIGN KEY (current_phase_id) REFERENCES project.workflow_phases(id);

ALTER TABLE project.dispatcher_tasks 
    ADD COLUMN phase_id INTEGER REFERENCES project.workflow_phases(id);
```

## Chemin fichier

```
projects/{slug}/{team_id}/{workflow_id}:{workflow_name}/{phase_id}:{phase_key}-{group_key}/{agent_id}/{deliverable_key}.md
```

## Patterns appliqués

- **Repository** : `db_*` pour l'accès DB, `file_*` pour l'accès fichier
- **Facade** : `resolve_next_phase` orchestre file + DB derrière une interface simple
- **Composite** : workflow → phases → groupes → agents, navigation uniforme
- **Récursivité** : `db_get_current_position` suit les workflows externes avec limite de profondeur et sans effets de bord

## Méthodes

### file_find_phase_def — lecture Workflow.json (une responsabilité : trouver une phase par order)

```python
def file_find_phase_def(workflow_json_path: str, phase_order: int) -> tuple[str, dict] | None:
    """Trouve la définition d'une phase dans le Workflow.json par son order.
    
    Returns:
        (phase_key, phase_def) ou None si non trouvée
    """
    if not workflow_json_path:
        return None
    wf_def = _load_workflow_json(workflow_json_path)
    phases_def = wf_def.get("phases", {})
    for pkey, pdef in sorted(phases_def.items(), key=lambda x: x[1].get("order", 0)):
        if pdef.get("order", 0) == phase_order:
            return pkey, pdef
    return None
```

### file_find_phase_by_key — lecture Workflow.json (trouver une phase par key)

```python
def file_find_phase_by_key(workflow_json_path: str, phase_key: str) -> dict | None:
    """Trouve la définition d'une phase dans le Workflow.json par sa key.
    
    Returns:
        phase_def ou None
    """
    if not workflow_json_path:
        return None
    wf_def = _load_workflow_json(workflow_json_path)
    return wf_def.get("phases", {}).get(phase_key)
```

### file_find_first_group — lecture Workflow.json (premier groupe par order)

```python
def file_find_first_group(phase_def: dict) -> tuple[str, int]:
    """Trouve le premier groupe d'une phase par son order.
    
    Returns:
        (group_key, group_order)
    """
    groups = phase_def.get("groups", [])
    if not groups:
        return "A", 0
    sorted_groups = sorted(groups, key=lambda g: g.get("order", 0))
    first = sorted_groups[0]
    return first.get("id", "A"), first.get("order", 0)
```

### file_find_next_group — lecture Workflow.json (groupe suivant par order)

```python
def file_find_next_group(phase_def: dict, current_group_order: int) -> tuple[str, int] | None:
    """Trouve le groupe suivant dans une phase par order.
    
    Returns:
        (group_key, group_order) ou None si dernier groupe
    """
    groups = phase_def.get("groups", [])
    if not groups:
        return None
    sorted_groups = sorted(groups, key=lambda g: g.get("order", 0))
    for g in sorted_groups:
        if g.get("order", 0) > current_group_order:
            return g.get("id", ""), g.get("order", 0)
    return None
```

### file_has_human_gate — lecture Workflow.json (vérifier si human_gate existe)

```python
def file_has_human_gate(workflow_json_path: str, phase_key: str) -> bool:
    """Vérifie si une phase a un human_gate dans ses exit_conditions."""
    phase_def = file_find_phase_by_key(workflow_json_path, phase_key)
    if not phase_def:
        return False
    return bool(phase_def.get("exit_conditions", {}).get("human_gate"))
```

### db_get_phase — lecture DB (une responsabilité)

```python
async def db_get_phase(phase_id: int) -> dict | None:
    """Récupère une phase par son ID."""
    if not phase_id:
        return None
    return await fetch_one(
        "SELECT * FROM project.workflow_phases WHERE id = $1",
        phase_id,
    )
```

### db_get_workflow — lecture DB

```python
async def db_get_workflow(workflow_id: int) -> dict | None:
    """Récupère un workflow par son ID."""
    if not workflow_id:
        return None
    return await fetch_one(
        "SELECT * FROM project.project_workflows WHERE id = $1",
        workflow_id,
    )
```

### db_check_human_gate — lecture DB uniquement (l'existence du gate est vérifiée par l'appelant via file_has_human_gate)

```python
async def db_check_human_gate(workflow_id: int, phase_key: str) -> str:
    """Vérifie l'état d'un human_gate en DB.
    
    L'appelant doit d'abord vérifier que la phase a un human_gate
    via file_has_human_gate.
    
    Returns:
        'not_created' — pas encore de hitl_request pour ce gate
        'pending' — en attente de validation
        'approved' — validé
        'rejected' — rejeté
    """
    thread_id = "workflow-{}".format(workflow_id)
    like_pattern = "%{}%".format(phase_key)

    pending = await fetch_one(
        """SELECT id FROM project.hitl_requests 
           WHERE thread_id = $1 AND request_type = 'approval' AND status = 'pending'
           AND context::text LIKE $2""",
        thread_id, like_pattern,
    )
    if pending:
        return "pending"
    
    answered = await fetch_one(
        """SELECT response FROM project.hitl_requests 
           WHERE thread_id = $1 AND request_type = 'approval' AND status = 'answered'
           AND context::text LIKE $2
           ORDER BY answered_at DESC LIMIT 1""",
        thread_id, like_pattern,
    )
    if not answered:
        return "not_created"
    
    if answered["response"] == "rejected":
        return "rejected"
    
    return "approved"
```

### db_create_next_group — écriture DB (une responsabilité : créer + mettre à jour le pointeur)

```python
async def db_create_next_group(workflow_id: int, phase_key: str, phase_name: str,
                               phase_order: int, group_key: str, group_order: int,
                               iteration: int) -> dict:
    """Crée la ligne pour le groupe suivant dans la même phase.
    Met à jour current_phase_id sur le workflow."""
    new_phase = await fetch_one(
        """INSERT INTO project.workflow_phases 
           (workflow_id, phase_key, phase_name, group_key, phase_order, group_order, iteration, status)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
           RETURNING *""",
        workflow_id, phase_key, phase_name,
        group_key, phase_order, group_order, iteration,
    )
    await execute(
        "UPDATE project.project_workflows SET current_phase_id = $1 WHERE id = $2",
        new_phase["id"], workflow_id,
    )
    return new_phase
```

### db_create_workflow — écriture DB (une responsabilité : créer un workflow)

```python
async def db_create_workflow(parent_workflow_id: int, workflow_name: str,
                              workflow_json_path: str) -> dict | None:
    """Crée un workflow enfant (externe) lié à un parent."""
    return await fetch_one(
        """INSERT INTO project.project_workflows
           (project_slug, workflow_name, workflow_type, workflow_json_path, status, iteration)
           SELECT project_slug, $2, 'external', $3, 'pending', 1
           FROM project.project_workflows WHERE id = $1
           RETURNING *""",
        parent_workflow_id, workflow_name, workflow_json_path,
    )
```

### db_create_phase — écriture DB (une responsabilité : créer une phase)

```python
async def db_create_phase(workflow_id: int, phase_key: str, phase_name: str,
                           group_key: str, phase_order: int, group_order: int,
                           iteration: int, depends_on_workflow_id: int | None = None) -> dict:
    """Crée une ligne workflow_phases et met à jour current_phase_id."""
    new_phase = await fetch_one(
        """INSERT INTO project.workflow_phases 
           (workflow_id, phase_key, phase_name, group_key, phase_order, group_order,
            iteration, depends_on_workflow_id, status)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending')
           RETURNING *""",
        workflow_id, phase_key, phase_name,
        group_key, phase_order, group_order, iteration, depends_on_workflow_id,
    )
    await execute(
        "UPDATE project.project_workflows SET current_phase_id = $1 WHERE id = $2",
        new_phase["id"], workflow_id,
    )
    return new_phase
```

### resolve_create_external_workflow — orchestration File + DB (création récursive)

```python
MAX_EXTERNAL_DEPTH = 10

async def resolve_create_external_workflow(parent_workflow_id: int, ext_workflow_path: str,
                                            _depth: int = 0) -> dict | None:
    """Crée un workflow externe et initialise sa première phase.
    
    Récursif avec limite de profondeur : si la première phase est aussi externe,
    crée le sous-workflow.
    """
    if _depth >= MAX_EXTERNAL_DEPTH:
        raise ValueError("Profondeur max atteinte ({}) — cycle detecte dans les workflows externes".format(MAX_EXTERNAL_DEPTH))
    
    ext_name = ext_workflow_path.replace(".wrk.json", "")
    
    # 1. Créer le workflow
    child_wf = await db_create_workflow(parent_workflow_id, ext_name, ext_workflow_path)
    if not child_wf:
        return None
    
    # 2. Trouver la première phase
    first_phase = file_find_phase_def(ext_workflow_path, 0)
    if not first_phase:
        first_phase = file_find_phase_def(ext_workflow_path, 1)
    if not first_phase:
        return child_wf
    
    first_phase_key, first_phase_def = first_phase
    first_group_key, first_group_order = file_find_first_group(first_phase_def)
    
    # 3. Si la première phase est externe, récursion
    depends_on = None
    if first_phase_def.get("type") == "external":
        sub_ext = first_phase_def.get("external_workflow", "")
        if sub_ext:
            sub_wf = await resolve_create_external_workflow(
                child_wf["id"], sub_ext, _depth=_depth + 1,
            )
            depends_on = sub_wf["id"] if sub_wf else None
    
    # 4. Créer la première phase
    await db_create_phase(
        child_wf["id"], first_phase_key, first_phase_def.get("name", first_phase_key),
        first_group_key, first_phase_def.get("order", 0), first_group_order,
        1, depends_on,
    )
    
    return child_wf
```

### resolve_next_phase — orchestration File + DB (logique de transition)

```python
async def resolve_next_phase(workflow_id: int, current_phase_order: int, 
                             current_group_order: int) -> dict | None:
    """Trouve et crée la prochaine phase/groupe à exécuter.
    
    Lit le Workflow.json (file) pour la définition, écrit en DB pour le tracking.
    
    Returns:
        La nouvelle ligne workflow_phases créée, ou None si bloqué/terminé
    """
    workflow = await db_get_workflow(workflow_id)
    if not workflow or not workflow["workflow_json_path"]:
        return None
    
    wf_path = workflow["workflow_json_path"]
    
    # Trouver la phase courante dans la définition
    result = file_find_phase_def(wf_path, current_phase_order)
    if not result:
        return None
    current_phase_key, current_phase_def = result
    
    # 1. Groupe suivant dans la même phase ?
    next_group = file_find_next_group(current_phase_def, current_group_order)
    if next_group:
        group_key, group_order = next_group
        return await db_create_next_group(
            workflow_id, current_phase_key,
            current_phase_def.get("name", current_phase_key),
            current_phase_order, group_key, group_order,
            workflow["iteration"],
        )
    
    # 2. Dernier groupe — vérifier le human_gate
    if file_has_human_gate(wf_path, current_phase_key):
        gate_status = await db_check_human_gate(workflow_id, current_phase_key)
        if gate_status in ("pending", "not_created", "rejected"):
            return None  # Bloqué par le human_gate
    
    # 3. Phase suivante
    next_result = file_find_phase_def(wf_path, current_phase_order + 1)
    if not next_result:
        return None  # Workflow terminé
    next_phase_key, next_phase_def = next_result
    
    first_group_key, first_group_order = file_find_first_group(next_phase_def)
    
    # Phase externe ? Créer le workflow enfant
    depends_on = None
    if next_phase_def.get("type") == "external":
        ext_workflow = next_phase_def.get("external_workflow", "")
        if ext_workflow:
            child_wf = await resolve_create_external_workflow(workflow_id, ext_workflow)
            depends_on = child_wf["id"] if child_wf else None
    
    return await db_create_phase(
        workflow_id, next_phase_key, next_phase_def.get("name", next_phase_key),
        first_group_key, current_phase_order + 1, first_group_order,
        workflow["iteration"], depends_on,
    )
```

### db_get_current_position — navigation récursive (lecture seule, pas d'effets de bord)

```python
MAX_POSITION_DEPTH = 10

async def db_get_current_position(workflow_id: int, _depth: int = 0) -> dict:
    """Retourne la position courante dans un workflow, en suivant les phases externes.
    
    Navigation PURE — ne crée ni ne modifie rien en DB.
    L'avancement (resolve_next_phase) est fait par l'appelant si nécessaire.
    
    Suit la chaîne : workflow → current_phase_id → workflow_phases
    Si phase externe → depends_on_workflow_id → récursion
    """
    if _depth >= MAX_POSITION_DEPTH:
        return {"error": "Profondeur max atteinte — cycle detecte"}
    
    workflow = await db_get_workflow(workflow_id)
    if not workflow:
        return {"error": "Workflow not found"}
    
    if not workflow["current_phase_id"]:
        return {"workflow": workflow, "phase": None, "status": "not_started"}
    
    phase = await db_get_phase(workflow["current_phase_id"])
    if not phase:
        return {"workflow": workflow, "phase": None, "status": "error"}
    
    # Phase completed → signaler à l'appelant qu'il faut avancer
    if phase["completed_at"]:
        return {"workflow": workflow, "phase": phase, "status": "phase_completed"}
    
    # Phase externe → suivre le workflow enfant
    if phase.get("depends_on_workflow_id"):
        return await db_get_current_position(
            phase["depends_on_workflow_id"], _depth=_depth + 1,
        )
    
    return {
        "workflow": workflow,
        "phase": phase,
        "status": phase["status"],
    }
```

## Usage typique

```python
# 1. Où en est le workflow ?
position = await db_get_current_position(workflow_id)

# 2. Si la phase est terminée, avancer
if position["status"] == "phase_completed":
    phase = position["phase"]
    next_phase = await resolve_next_phase(
        position["workflow"]["id"], phase["phase_order"], phase["group_order"],
    )
    if next_phase:
        # Nouvelle phase créée, relancer
        position = await db_get_current_position(workflow_id)

# 3. Utiliser la position pour construire le chemin fichier
if position["phase"]:
    path = "projects/{slug}/{team}/{wf_id}:{wf_name}/{ph_id}:{phase}-{group}".format(
        slug=position["workflow"]["project_slug"],
        team=team_id,
        wf_id=position["workflow"]["id"],
        wf_name=position["workflow"]["workflow_name"],
        ph_id=position["phase"]["id"],
        phase=position["phase"]["phase_key"],
        group=position["phase"]["group_key"],
    )
```
