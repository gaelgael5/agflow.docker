# External Phases — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "External Phase" type to the workflow editor — a phase that references another `*.wrk.json` in the same project, with visual distinction, cycle detection, and apercu.

**Architecture:** New `type: "external"` + `external_workflow` fields on phase objects. Backend validates file existence and detects cycles. Frontend renders external phases with dashed purple border, hides agents/deliverables sections, shows workflow selector + apercu.

**Tech Stack:** Python/FastAPI backend (`web/server.py`), vanilla JS frontend (`web/static/js/app.js`), CSS (`web/static/css/style.css`)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `web/server.py` | Modify | New endpoint `available-workflows`, validation on PUT (cycles, file exists) |
| `web/static/js/app.js` | Modify | Toolbox item, phase rendering, props panel, drag-drop, save validation |
| `web/static/css/style.css` | Modify | `.wf-phase.wf-external` styling (dashed border, purple) |

---

### Task 1: Backend — Available workflows endpoint

**Files:**
- Modify: `web/server.py` (after line ~3534, near project-workflow endpoints)

- [ ] **Step 1: Add `GET /api/templates/projects/{project_id}/available-workflows`**

Insert after the `put_project_workflow_editor` endpoint:

```python
@app.get("/api/templates/projects/{project_id}/available-workflows")
async def list_available_workflows(project_id: str):
    """List *.wrk.json files in a project directory."""
    project_dir = _project_dir_or_404(project_id)
    results = []
    for f in sorted(project_dir.iterdir()):
        if f.suffix == ".json" and f.stem.endswith(".wrk"):
            data = _read_json(f)
            # Try to get name from root or first phase
            name = data.get("name", "")
            if not name:
                phases = data.get("phases", {})
                if isinstance(phases, dict) and phases:
                    first = next(iter(phases.values()))
                    name = first.get("name", f.stem)
                elif isinstance(phases, list) and phases:
                    name = phases[0].get("name", f.stem)
                else:
                    name = f.stem.replace(".wrk", "")
            results.append({"filename": f.name, "name": name})
    return results
```

- [ ] **Step 2: Add same endpoint for production**

```python
@app.get("/api/prod-projects/{project_id}/available-workflows")
async def list_prod_available_workflows(project_id: str):
    project_dir = _cfg_project_dir_or_404(project_id)
    results = []
    for f in sorted(project_dir.iterdir()):
        if f.suffix == ".json" and f.stem.endswith(".wrk"):
            data = _read_json(f)
            name = data.get("name", "")
            if not name:
                phases = data.get("phases", {})
                if isinstance(phases, dict) and phases:
                    first = next(iter(phases.values()))
                    name = first.get("name", f.stem)
                elif isinstance(phases, list) and phases:
                    name = phases[0].get("name", f.stem)
                else:
                    name = f.stem.replace(".wrk", "")
            results.append({"filename": f.name, "name": name})
    return results
```

---

### Task 2: Backend — Cycle detection + validation on save

**Files:**
- Modify: `web/server.py` (modify `put_project_workflow_editor` and `put_prod_project_workflow_editor`)

- [ ] **Step 1: Add cycle detection utility function**

Insert near the project workflow endpoints:

```python
def _check_external_cycles(project_dir: Path, workflow_name: str, visited: set = None) -> list[str]:
    """Detect cycles in external phase references. Returns list of error messages."""
    if visited is None:
        visited = set()
    if workflow_name in visited:
        return [f"Cycle detecte: {' -> '.join(visited)} -> {workflow_name}"]
    visited = visited | {workflow_name}
    wf_path = project_dir / workflow_name
    if not wf_path.exists():
        return [f"Workflow '{workflow_name}' introuvable"]
    data = _read_json(wf_path)
    phases = data.get("phases", {})
    if isinstance(phases, list):
        phase_list = phases
    else:
        phase_list = list(phases.values())
    errors = []
    for phase in phase_list:
        if phase.get("type") == "external":
            ext_wf = phase.get("external_workflow", "")
            if ext_wf:
                errors.extend(_check_external_cycles(project_dir, ext_wf, visited))
    return errors
```

- [ ] **Step 2: Add validation in `put_project_workflow_editor`**

Modify the existing PUT handler to validate before saving:

```python
@app.put("/api/templates/project-workflow/{project_id}/{wf_name}")
async def put_project_workflow_editor(project_id: str, wf_name: str, request: Request):
    project_dir = _project_dir_or_404(project_id)
    name = _wf_name_safe(wf_name)
    data = await request.json()
    # Validate external phases
    phases = data.get("phases", {})
    phase_list = list(phases.values()) if isinstance(phases, dict) else phases
    current_file = f"{name}.wrk.json"
    for phase in phase_list:
        if phase.get("type") == "external":
            ext_wf = phase.get("external_workflow", "")
            if ext_wf:
                if ext_wf == current_file:
                    raise HTTPException(400, f"La phase '{phase.get('name', phase.get('id', '?'))}' reference le workflow courant (recursion)")
                if not (project_dir / ext_wf).exists():
                    raise HTTPException(400, f"Workflow externe introuvable: {ext_wf}")
                cycle_errors = _check_external_cycles(project_dir, ext_wf, {current_file})
                if cycle_errors:
                    raise HTTPException(400, cycle_errors[0])
    _write_json(project_dir / current_file, data)
    team_id = data.get("team", "")
    _generate_phase_files(data, f"{name}.wrk", project_dir, team_id)
    return {"ok": True}
```

- [ ] **Step 3: Same validation for production PUT endpoint**

Apply same pattern to `put_prod_project_workflow_editor`.

---

### Task 3: Frontend — Toolbox item for External Phase

**Files:**
- Modify: `web/static/js/app.js` (line ~7612-7618, toolbox HTML)

- [ ] **Step 1: Add External Phase item to toolbox**

After the existing Phase toolbox item (line 7617), add:

```html
<div class="wf-toolbox-item" draggable="true" ondragstart="_wfToolDragStart(event, 'external')" title="Phase executant un autre workflow" style="border-left:3px solid var(--accent-purple, #8b5cf6)">
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="3" stroke-dasharray="4 2"/><path d="M12 8l4 4-4 4M8 12h8"/></svg>
  <span>Phase externe</span>
</div>
```

- [ ] **Step 2: Update `_wfToolDrop` to handle `'external'` type**

Modify `_wfToolDrop` (line 7685) to accept both `'phase'` and `'external'`:

```javascript
function _wfToolDrop(e) {
  e.preventDefault();
  document.getElementById('wf-workspace').classList.remove('wf-drop-target');
  const type = e.dataTransfer.getData('wf-tool-type');
  if (type !== 'phase' && type !== 'external') return;
  const ws = document.getElementById('wf-workspace');
  const rect = ws.getBoundingClientRect();
  const x = e.clientX - rect.left + ws.scrollLeft;
  const y = e.clientY - rect.top + ws.scrollTop;
  const phases = _wf.data.phases || {};
  let num = Object.keys(phases).length + 1;
  let id = 'phase_' + num;
  while (phases[id]) { num++; id = 'phase_' + num; }
  const maxOrder = Object.values(phases).reduce(function(m, p) { return Math.max(m, p.order || 0); }, 0);
  const phaseData = {
    name: type === 'external' ? 'Phase externe ' + num : 'Phase ' + num,
    description: '',
    order: maxOrder + 1,
    agents: {},
    deliverables: {},
    exit_conditions: { human_gate: true }
  };
  if (type === 'external') {
    phaseData.type = 'external';
    phaseData.external_workflow = '';
  }
  _wf.data.phases[id] = phaseData;
  _wf.positions[id] = { x: Math.max(20, x - 100), y: Math.max(20, y - 20) };
  _wf.selected = id;
  wfRender();
}
```

- [ ] **Step 3: Add `wfAddExternalPhase` button handler (for non-drag creation)**

```javascript
function wfAddExternalPhase() {
  const phases = _wf.data.phases || {};
  let num = Object.keys(phases).length + 1;
  let id = 'phase_' + num;
  while (phases[id]) { num++; id = 'phase_' + num; }
  const maxOrder = Object.values(phases).reduce((m, p) => Math.max(m, p.order || 0), 0);
  _wf.data.phases[id] = {
    name: 'Phase externe ' + num,
    description: '',
    order: maxOrder + 1,
    type: 'external',
    external_workflow: '',
    agents: {},
    deliverables: {},
    exit_conditions: { human_gate: true }
  };
  _wfCalcPositions();
  _wf.selected = id;
  wfRender();
}
```

---

### Task 4: Frontend — Visual rendering of External Phase blocks

**Files:**
- Modify: `web/static/js/app.js` (line ~7734-7784, `wfRender()`)
- Modify: `web/static/css/style.css`

- [ ] **Step 1: Add CSS for external phase**

In `style.css`, add after the existing `.wf-phase` styles:

```css
.wf-phase.wf-external {
  border: 2px dashed var(--accent-purple, #8b5cf6);
  background: rgba(139, 92, 246, 0.05);
}
.wf-phase.wf-external .wf-phase-head {
  background: rgba(139, 92, 246, 0.15);
  color: var(--accent-purple, #8b5cf6);
}
.wf-phase.wf-external .wf-phase-order {
  background: var(--accent-purple, #8b5cf6);
}
```

- [ ] **Step 2: Modify `wfRender()` to detect external phases and render differently**

In the phase rendering loop (line ~7734), add external detection:

Replace the phase HTML generation block to add the `wf-external` class and different body content for external phases:

```javascript
// Inside the for loop, after: const sel = _wf.selected === id ? ' wf-selected' : '';
const isExternal = p.type === 'external';
const extClass = isExternal ? ' wf-external' : '';

// In the class attribute:
// <div class="wf-phase${sel}${extClass}" ...>

// Replace the phase body content for external phases:
// If isExternal, show external workflow info instead of agents/deliverables
```

The external phase body shows:
- Icon + "Phase externe" label
- Referenced workflow name (or "Non configure" if empty)
- Link to open the referenced workflow

---

### Task 5: Frontend — Properties panel for External Phase

**Files:**
- Modify: `web/static/js/app.js` (line ~8182, `_wfRenderPhaseProps()`)

- [ ] **Step 1: Add external phase detection in `_wfRenderPhaseProps`**

At the top of `_wfRenderPhaseProps`, detect `phase.type === 'external'` and render a different panel:

The external phase props panel contains:
- **Informations section:** ID (editable), Name (editable), Description, Order
- **Workflow externe section:**
  - Select dropdown (fed by `GET /api/templates/projects/{projectId}/available-workflows`)
  - Exclude current workflow from list
  - On change: validate cycles, show apercu
- **Apercu section:** (read-only) phase count, phase names, agent count
- **Link:** "Ouvrir le workflow →" button

The agents and deliverables sections are NOT rendered for external phases.

- [ ] **Step 2: Add `_wfLoadExternalWorkflows` helper**

```javascript
async function _wfLoadExternalWorkflows(projectId) {
  // Determine API base from _wf.apiBase
  const base = _wf.apiBase.includes('prod-') ? '/api/prod-projects' : '/api/templates/projects';
  try {
    return await api(base + '/' + encodeURIComponent(projectId) + '/available-workflows');
  } catch { return []; }
}
```

- [ ] **Step 3: Add `_wfSetExternalWorkflow` handler**

Handles workflow selection, validates cycles via save attempt, loads apercu:

```javascript
async function _wfSetExternalWorkflow(phaseId, filename) {
  _wf.data.phases[phaseId].external_workflow = filename;
  wfRender(); // Re-render to show apercu
}
```

- [ ] **Step 4: Add `_wfOpenExternalWorkflow` handler**

Switches the editor to the referenced workflow:

```javascript
function _wfOpenExternalWorkflow(filename) {
  // Extract workflow name from filename (remove .wrk.json)
  const wfName = filename.replace('.wrk.json', '');
  // Re-open editor with new workflow, same project
  const projectId = _wf.dir;
  openWorkflowEditor(wfName, _wf.apiBase.replace(/\/[^/]+$/, ''), _wf.label, _wf.registryDir, _wf.inlineTargetId);
}
```

---

### Task 6: Frontend — Validation update

**Files:**
- Modify: `web/static/js/app.js` (line ~9698, `_wfValidate()`)

- [ ] **Step 1: Skip agent/deliverable validation for external phases**

In `_wfValidate`, when iterating phases, skip agent and deliverable checks if `phase.type === 'external'`:

```javascript
// Inside the phase validation loop:
if (phase.type === 'external') {
  if (!phase.external_workflow) {
    warnings.push('Phase "' + (phase.name || pid) + '" : aucun workflow externe configure');
  }
  continue; // Skip agent/deliverable checks
}
```

---

### Task 7: Deploy & verify

- [ ] **Step 1: Bump cache buster**
- [ ] **Step 2: Deploy via `bash deploy.sh AGT1`**
- [ ] **Step 3: Force rebuild admin**
- [ ] **Step 4: Verify checklist:**
  - Toolbox has "+ Phase externe" item
  - Drag-drop creates dashed purple block
  - Props panel shows workflow selector
  - Apercu loads when workflow selected
  - Save validates file existence + cycles
  - Standard phases unaffected
