# Workflow Execution View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Workflow tab into a project execution dashboard where users launch workflows, validate deliverables inline with markdown preview, request LLM corrections, and track parallel workflow progress.

**Architecture:** Backend adds 3 new endpoints (start, phases with content, revise) and extends the DB schema (version column, extended status CHECK). Frontend replaces the current WorkflowPhaseBar with a vertical split-view: phase cards on the left with expand/collapse, deliverable preview+edit+history on the right. All existing services (deliverable_service, multi_workflow_service, workflow_service) are reused and extended.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Tailwind (frontend), PostgreSQL (DB), httpx (gateway calls)

---

## File Structure

### Backend — modified
- `scripts/init.sql` — add `version` column to artifacts, extend status CHECK
- `hitl/schemas/deliverable.py` — add `version` field to DeliverableResponse/Detail
- `hitl/schemas/workflow.py` — new `WorkflowPhaseDetailResponse` schema with embedded deliverable content
- `hitl/services/deliverable_service.py` — add `revise_deliverable()` function
- `hitl/services/multi_workflow_service.py` — add `start_workflow()` with phase creation + agent dispatch
- `hitl/services/workflow_service.py` — add `get_workflow_phases_detail()` with deliverable content
- `hitl/routes/workflows.py` — add `POST /{slug}/workflows/{id}/start`, `GET /{slug}/workflows/{id}/phases`, `POST /deliverables/{id}/revise`

### Frontend — modified
- `hitl-frontend/src/api/types.ts` — new types for phase detail + deliverable with content
- `hitl-frontend/src/api/workflow.ts` — add `startWorkflow()`, `getWorkflowPhases()`
- `hitl-frontend/src/api/deliverables.ts` — add `reviseDeliverable()`
- `hitl-frontend/src/pages/ProjectDetailPage.tsx` — replace workflow tab content

### Frontend — new
- `hitl-frontend/src/components/features/workflow/WorkflowExecutionPanel.tsx` — main container
- `hitl-frontend/src/components/features/workflow/WorkflowPhaseCard.tsx` — expand/collapse phase with deliverable list
- `hitl-frontend/src/components/features/workflow/DeliverablePanel.tsx` — right panel: read/edit/comment modes
- `hitl-frontend/src/components/features/workflow/RevisionHistory.tsx` — chronological revision list
- `hitl-frontend/src/components/features/workflow/HumanGateBanner.tsx` — priority banner for pending gates

---

## Task 1: DB Schema — version column + extended status

**Files:**
- Modify: `scripts/init.sql`

- [ ] **Step 1: Add version column and extend status CHECK**

Add at the end of `init.sql` (after existing `DO $$ ... END $$;` blocks):

```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='project' AND table_name='dispatcher_task_artifacts' AND column_name='version') THEN
        ALTER TABLE project.dispatcher_task_artifacts ADD COLUMN version INTEGER DEFAULT 1;
    END IF;
END $$;

-- Extend status CHECK to include 'review' and 'revision'
DO $$
BEGIN
    ALTER TABLE project.dispatcher_task_artifacts
      DROP CONSTRAINT IF EXISTS dispatcher_task_artifacts_status_check;
    ALTER TABLE project.dispatcher_task_artifacts
      ADD CONSTRAINT dispatcher_task_artifacts_status_check
        CHECK (status IN ('pending', 'running', 'review', 'revision', 'approved', 'rejected'));
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
```

- [ ] **Step 2: Apply schema on server**

```bash
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose exec langgraph-postgres psql -U langgraph -d langgraph -f /docker-entrypoint-initdb.d/init.sql"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/init.sql
git commit -m "feat: add version column + extended status on dispatcher_task_artifacts"
```

---

## Task 2: Backend schemas — new types for workflow phases detail

**Files:**
- Modify: `hitl/schemas/deliverable.py`
- Modify: `hitl/schemas/workflow.py`

- [ ] **Step 1: Add version to DeliverableResponse**

In `hitl/schemas/deliverable.py`, add `version` field to `DeliverableResponse`:

```python
class DeliverableResponse(BaseModel):
    id: int
    task_id: str
    key: str
    deliverable_type: str
    file_path: Optional[str] = None
    git_branch: Optional[str] = None
    category: Optional[str] = None
    status: str
    version: int = 1  # ADD THIS
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    agent_id: str
    phase: str
    project_slug: str
```

- [ ] **Step 2: Add WorkflowPhaseDetailResponse to workflow schemas**

In `hitl/schemas/workflow.py`, add after `WorkflowStatusResponse`:

```python
class DeliverableWithContent(BaseModel):
    """Deliverable with full markdown content for inline preview."""
    id: int
    key: str
    agent_id: str
    agent_name: str = ""
    status: str  # pending | running | review | revision | approved | rejected
    version: int = 1
    file_path: Optional[str] = None
    content: str = ""
    reviewer: Optional[str] = None
    review_comment: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PhaseDetailResponse(BaseModel):
    """A single phase/group with its deliverables including content."""
    id: int
    phase_key: str
    phase_name: str
    group_key: str
    status: str  # pending | running | completed | failed
    deliverables: list[DeliverableWithContent] = []


class WorkflowPhasesResponse(BaseModel):
    """Full workflow execution state with phases and deliverables."""
    workflow_id: int
    workflow_name: str
    status: str
    human_gate: Optional[dict] = None  # pending hitl_request if any
    phases: list[PhaseDetailResponse] = []
```

- [ ] **Step 3: Commit**

```bash
git add hitl/schemas/deliverable.py hitl/schemas/workflow.py
git commit -m "feat: add version field + WorkflowPhasesResponse schema"
```

---

## Task 3: Backend service — get_workflow_phases_detail

**Files:**
- Modify: `hitl/services/workflow_service.py`

- [ ] **Step 1: Add get_workflow_phases_detail function**

Add at the end of `hitl/services/workflow_service.py`:

```python
async def get_workflow_phases_detail(
    project_slug: str,
    workflow_id: int,
) -> dict:
    """Get all phases for a workflow with deliverables including file content."""
    from schemas.workflow import DeliverableWithContent, PhaseDetailResponse, WorkflowPhasesResponse

    # Get workflow info
    wf = await fetch_one(
        "SELECT id, workflow_name, status FROM project.project_workflows WHERE id = $1 AND project_slug = $2",
        workflow_id, project_slug,
    )
    if not wf:
        return None

    # Get phases ordered: most recent first (by phase_order DESC, group_order DESC)
    phases = await fetch_all(
        """SELECT id, phase_key, phase_name, group_key, status
           FROM project.workflow_phases
           WHERE workflow_id = $1
           ORDER BY phase_order DESC, group_order DESC""",
        workflow_id,
    )

    # Get pending human gate
    thread_id = "workflow-{}".format(workflow_id)
    gate = await fetch_one(
        """SELECT id, prompt, agent_id, created_at::text
           FROM project.hitl_requests
           WHERE thread_id = $1 AND status = 'pending'
           ORDER BY created_at DESC LIMIT 1""",
        thread_id,
    )
    human_gate = None
    if gate:
        human_gate = {
            "id": str(gate["id"]),
            "prompt": gate["prompt"],
            "agent_id": gate["agent_id"],
            "created_at": gate["created_at"],
        }

    # Build phase details with deliverables
    phase_details = []
    for p in phases:
        # Get deliverables for this phase from dispatcher_task_artifacts
        delivs = await fetch_all(
            """SELECT a.id, a.key, a.status, a.version, a.file_path,
                      a.reviewer, a.review_comment, a.reviewed_at::text, a.created_at::text,
                      t.agent_id
               FROM project.dispatcher_task_artifacts a
               JOIN project.dispatcher_tasks t ON a.task_id = t.id
               WHERE t.project_slug = $1 AND t.phase_id = $2
               ORDER BY a.created_at""",
            project_slug, p["id"],
        )

        deliverable_list = []
        for d in delivs:
            # Read file content
            content = ""
            if d["file_path"]:
                import os
                ag_flow_root = os.getenv("AG_FLOW_ROOT", "/root/ag.flow")
                fpath = os.path.join(ag_flow_root, d["file_path"])
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, encoding="utf-8") as f:
                            content = f.read()
                    except Exception:
                        pass

            # Resolve agent name
            agent_name = d["agent_id"] or ""
            deliverable_list.append(DeliverableWithContent(
                id=d["id"],
                key=d["key"],
                agent_id=d["agent_id"] or "",
                agent_name=agent_name,
                status=d["status"] or "pending",
                version=d["version"] or 1,
                file_path=d["file_path"],
                content=content,
                reviewer=d["reviewer"],
                review_comment=d["review_comment"],
                reviewed_at=d["reviewed_at"],
                created_at=d["created_at"],
            ))

        phase_details.append(PhaseDetailResponse(
            id=p["id"],
            phase_key=p["phase_key"] or "",
            phase_name=p["phase_name"] or p["phase_key"] or "",
            group_key=p["group_key"] or "A",
            status=p["status"] or "pending",
            deliverables=deliverable_list,
        ))

    return WorkflowPhasesResponse(
        workflow_id=workflow_id,
        workflow_name=wf["workflow_name"],
        status=wf["status"],
        human_gate=human_gate,
        phases=phase_details,
    )
```

- [ ] **Step 2: Commit**

```bash
git add hitl/services/workflow_service.py
git commit -m "feat: get_workflow_phases_detail with deliverable content"
```

---

## Task 4: Backend service — revise_deliverable

**Files:**
- Modify: `hitl/services/deliverable_service.py`

- [ ] **Step 1: Add revise_deliverable function**

Add at the end of `hitl/services/deliverable_service.py`:

```python
async def revise_deliverable(
    artifact_id: int,
    comment: str,
    reviewer: str,
) -> dict:
    """Send a revision comment — relaunches the agent with the current content + comment."""
    row = await fetch_one(
        """SELECT a.id, a.key, a.file_path, a.status, a.version, a.task_id,
                  t.agent_id, t.project_slug, t.team_id, t.thread_id
           FROM project.dispatcher_task_artifacts a
           JOIN project.dispatcher_tasks t ON a.task_id = t.id
           WHERE a.id = $1""",
        artifact_id,
    )
    if not row:
        raise ValueError("Deliverable not found")

    # Store the remark
    await execute(
        "INSERT INTO project.deliverable_remarks (artifact_id, reviewer, comment) VALUES ($1, $2, $3)",
        artifact_id, reviewer, comment,
    )

    # Set status to revision
    await execute(
        "UPDATE project.dispatcher_task_artifacts SET status = 'revision' WHERE id = $1",
        artifact_id,
    )

    # Read current content
    import os
    content = ""
    if row["file_path"]:
        ag_flow_root = os.getenv("AG_FLOW_ROOT", "/root/ag.flow")
        fpath = os.path.join(ag_flow_root, row["file_path"])
        if os.path.isfile(fpath):
            with open(fpath, encoding="utf-8") as f:
                content = f.read()

    # Call gateway to re-dispatch the agent with correction instruction
    import httpx
    from core.config import settings
    gateway_url = settings.langgraph_api_url or "http://langgraph-api:8000"

    instruction = "Corrige le livrable '{}' en tenant compte du commentaire de l'utilisateur.\n\n--- LIVRABLE ACTUEL ---\n{}\n\n--- COMMENTAIRE ---\n{}\n\n--- CONSIGNE ---\nProduis une version corrigee complete du livrable. Utilise save_deliverable avec la meme cle '{}' pour sauvegarder.".format(
        row["key"], content[:8000], comment, row["key"]
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "{}/invoke".format(gateway_url),
                json={
                    "messages": [{"role": "user", "content": instruction}],
                    "team_id": row["team_id"] or "",
                    "thread_id": row["thread_id"] or "",
                    "project_slug": row["project_slug"] or "",
                    "direct_agent": row["agent_id"],
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        log.error("revise_dispatch_failed", artifact_id=artifact_id, error=str(exc)[:200])
        # Revert status
        await execute(
            "UPDATE project.dispatcher_task_artifacts SET status = 'review' WHERE id = $1",
            artifact_id,
        )
        raise ValueError("Agent dispatch failed: {}".format(str(exc)[:200]))

    return {"ok": True, "status": "revision"}
```

- [ ] **Step 2: Commit**

```bash
git add hitl/services/deliverable_service.py
git commit -m "feat: revise_deliverable — send correction to agent"
```

---

## Task 5: Backend service — start_workflow with phase creation + dispatch

**Files:**
- Modify: `hitl/services/multi_workflow_service.py`

- [ ] **Step 1: Add start_workflow function**

Add at the end of `hitl/services/multi_workflow_service.py`:

```python
async def start_workflow(
    project_slug: str,
    workflow_id: int,
) -> dict:
    """Start a workflow: activate it, create first phase, dispatch agents for group A."""
    import json as _json
    import os

    wf = await fetch_one(
        "SELECT id, workflow_name, workflow_json_path, status, team_id FROM project.project_workflows WHERE id = $1 AND project_slug = $2",
        workflow_id, project_slug,
    )
    if not wf:
        raise ValueError("Workflow not found")
    if wf["status"] not in ("pending", "paused"):
        raise ValueError("Workflow is already {}".format(wf["status"]))

    # Activate
    await execute(
        "UPDATE project.project_workflows SET status = 'active', started_at = NOW(), updated_at = NOW() WHERE id = $1",
        workflow_id,
    )

    # Read workflow JSON to find first phase + group
    wf_json_path = wf["workflow_json_path"] or ""
    wf_data = {}
    if os.path.isfile(wf_json_path):
        with open(wf_json_path, encoding="utf-8") as f:
            wf_data = _json.load(f)

    phases = wf_data.get("phases", {})
    if not phases:
        return {"ok": True, "workflow_id": workflow_id, "message": "No phases defined"}

    # Find first phase by order
    sorted_phases = sorted(phases.items(), key=lambda x: x[1].get("order", 0))
    first_key, first_phase = sorted_phases[0]
    groups = first_phase.get("groups", [{"id": "A"}])
    first_group = groups[0] if groups else {"id": "A"}
    group_key = first_group.get("id", "A")

    # Create workflow_phase
    phase_row = await fetch_one(
        """INSERT INTO project.workflow_phases
           (workflow_id, phase_key, phase_name, group_key, phase_order, group_order, iteration, status)
           VALUES ($1, $2, $3, $4, $5, 0, 1, 'running')
           RETURNING id""",
        workflow_id, first_key, first_phase.get("name", first_key), group_key,
        first_phase.get("order", 0),
    )
    phase_id = phase_row["id"] if phase_row else None

    # Update current_phase_id
    if phase_id:
        await execute(
            "UPDATE project.project_workflows SET current_phase_id = $1 WHERE id = $2",
            phase_id, workflow_id,
        )

    # Dispatch agents for group A deliverables
    import httpx
    from core.config import settings
    gateway_url = settings.langgraph_api_url or "http://langgraph-api:8000"
    team_id = wf["team_id"] or ""
    thread_id = "workflow-{}".format(workflow_id)
    dispatched = []

    for deliv in first_group.get("deliverables", []):
        agent_id = deliv.get("agent", "")
        if not agent_id:
            continue
        d_name = deliv.get("Name") or deliv.get("name") or deliv.get("id", "")
        d_desc = deliv.get("description", "")
        instruction = "Produis le livrable '{}'. {}\n\nUtilise save_deliverable avec deliverable_key='{}' pour sauvegarder le resultat.".format(
            d_name, d_desc[:2000], deliv.get("id", d_name),
        )

        # Create dispatcher_task
        task_row = await fetch_one(
            """INSERT INTO project.dispatcher_tasks
               (agent_id, team_id, thread_id, project_slug, phase, instruction, status, workflow_id, phase_id)
               VALUES ($1, $2, $3, $4, $5, $6, 'running', $7, $8)
               RETURNING id""",
            agent_id, team_id, thread_id, project_slug, first_key,
            instruction[:4000], workflow_id, phase_id,
        )

        # Dispatch via gateway
        if task_row:
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.post(
                        "{}/invoke".format(gateway_url),
                        json={
                            "messages": [{"role": "user", "content": instruction}],
                            "team_id": team_id,
                            "thread_id": thread_id,
                            "project_slug": project_slug,
                            "direct_agent": agent_id,
                            "workflow_id": workflow_id,
                            "phase_id": phase_id,
                        },
                    )
                dispatched.append(agent_id)
            except Exception as exc:
                log.error("start_workflow_dispatch_failed", agent=agent_id, error=str(exc)[:200])

    return {
        "ok": True,
        "workflow_id": workflow_id,
        "phase_id": phase_id,
        "dispatched": dispatched,
    }
```

- [ ] **Step 2: Commit**

```bash
git add hitl/services/multi_workflow_service.py
git commit -m "feat: start_workflow — create first phase + dispatch agents"
```

---

## Task 6: Backend routes — new endpoints

**Files:**
- Modify: `hitl/routes/workflows.py`
- Modify: `hitl/routes/deliverables.py`

- [ ] **Step 1: Add start and phases endpoints to workflows.py**

Add after the existing `relaunch` endpoint:

```python
@router.post("/{slug}/workflows/{workflow_id}/start")
async def start_workflow(
    slug: str,
    workflow_id: int,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Start a workflow: create first phase and dispatch agents."""
    await _require_project(slug, user)
    return await multi_workflow_service.start_workflow(slug, workflow_id)


@router.get("/{slug}/workflows/{workflow_id}/phases")
async def get_workflow_phases(
    slug: str,
    workflow_id: int,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Get workflow phases with deliverable content for inline preview."""
    await _require_project(slug, user)
    from services import workflow_service
    result = await workflow_service.get_workflow_phases_detail(slug, workflow_id)
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return result
```

- [ ] **Step 2: Add revise endpoint to deliverables.py**

Add after the existing `remark` endpoint:

```python
@router.post("/api/deliverables/{artifact_id}/revise")
async def revise_deliverable(
    artifact_id: int,
    body: RemarkRequest,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Send a revision comment and re-dispatch the agent for correction."""
    try:
        return await deliverable_service.revise_deliverable(artifact_id, body.comment, user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

- [ ] **Step 3: Commit**

```bash
git add hitl/routes/workflows.py hitl/routes/deliverables.py
git commit -m "feat: start, phases, revise endpoints"
```

---

## Task 7: Frontend types + API functions

**Files:**
- Modify: `hitl-frontend/src/api/types.ts`
- Modify: `hitl-frontend/src/api/workflow.ts`
- Modify: `hitl-frontend/src/api/deliverables.ts`

- [ ] **Step 1: Add types**

In `api/types.ts`, add:

```typescript
export interface DeliverableWithContent {
  id: number;
  key: string;
  agent_id: string;
  agent_name: string;
  status: 'pending' | 'running' | 'review' | 'revision' | 'approved' | 'rejected';
  version: number;
  file_path: string | null;
  content: string;
  reviewer: string | null;
  review_comment: string | null;
  reviewed_at: string | null;
  created_at: string | null;
}

export interface PhaseDetailResponse {
  id: number;
  phase_key: string;
  phase_name: string;
  group_key: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  deliverables: DeliverableWithContent[];
}

export interface HumanGateInfo {
  id: string;
  prompt: string;
  agent_id: string;
  created_at: string;
}

export interface WorkflowPhasesResponse {
  workflow_id: number;
  workflow_name: string;
  status: string;
  human_gate: HumanGateInfo | null;
  phases: PhaseDetailResponse[];
}
```

- [ ] **Step 2: Add API functions**

In `api/workflow.ts`, add:

```typescript
export function startWorkflow(slug: string, workflowId: number): Promise<{ ok: boolean; dispatched: string[] }> {
  return apiFetch(`/api/projects/${encodeURIComponent(slug)}/workflows/${workflowId}/start`, { method: 'POST' });
}

export function getWorkflowPhases(slug: string, workflowId: number): Promise<WorkflowPhasesResponse> {
  return apiFetch(`/api/projects/${encodeURIComponent(slug)}/workflows/${workflowId}/phases`);
}
```

In `api/deliverables.ts`, add:

```typescript
export function reviseDeliverable(id: number, comment: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/deliverables/${id}/revise`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  });
}
```

- [ ] **Step 3: Commit**

```bash
git add hitl-frontend/src/api/types.ts hitl-frontend/src/api/workflow.ts hitl-frontend/src/api/deliverables.ts
git commit -m "feat: frontend types + API for workflow execution"
```

---

## Task 8: Frontend — HumanGateBanner component

**Files:**
- Create: `hitl-frontend/src/components/features/workflow/HumanGateBanner.tsx`

- [ ] **Step 1: Create component**

```tsx
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../ui/Button';
import type { HumanGateInfo } from '../../../api/types';
import { MarkdownRenderer } from '../deliverable/MarkdownRenderer';

interface Props {
  gate: HumanGateInfo;
  onRespond: (response: string) => Promise<void>;
}

export function HumanGateBanner({ gate, onRespond }: Props): JSX.Element {
  const { t } = useTranslation();
  const [response, setResponse] = useState('');
  const [sending, setSending] = useState(false);

  const handleSubmit = async () => {
    if (!response.trim()) return;
    setSending(true);
    try {
      await onRespond(response);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="rounded-lg border-2 border-accent-orange bg-accent-orange/5 p-4 mb-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">&#9888;</span>
        <span className="font-semibold text-sm text-accent-orange">{t('workflow.human_gate')}</span>
        <span className="text-xs text-content-tertiary ml-auto">{gate.agent_id}</span>
      </div>
      <div className="text-sm mb-3">
        <MarkdownRenderer content={gate.prompt} />
      </div>
      <div className="flex gap-2">
        <textarea
          rows={2}
          className="flex-1 rounded border border-border bg-surface-primary px-3 py-2 text-sm"
          placeholder={t('workflow.gate_response_placeholder')}
          value={response}
          onChange={(e) => setResponse(e.target.value)}
        />
        <Button onClick={handleSubmit} loading={sending} disabled={!response.trim()}>
          {t('workflow.respond')}
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/components/features/workflow/HumanGateBanner.tsx
git commit -m "feat: HumanGateBanner component"
```

---

## Task 9: Frontend — RevisionHistory component

**Files:**
- Create: `hitl-frontend/src/components/features/workflow/RevisionHistory.tsx`

- [ ] **Step 1: Create component**

```tsx
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as deliverablesApi from '../../../api/deliverables';
import type { RemarkResponse } from '../../../api/types';

interface Props {
  artifactId: number;
  version: number;
}

export function RevisionHistory({ artifactId, version }: Props): JSX.Element {
  const { t } = useTranslation();
  const [remarks, setRemarks] = useState<RemarkResponse[]>([]);

  useEffect(() => {
    deliverablesApi.listRemarks(String(artifactId)).then(setRemarks).catch(() => {});
  }, [artifactId, version]);

  if (!remarks.length && version <= 1) return <></>;

  return (
    <div className="border-t border-border mt-4 pt-3">
      <h4 className="text-xs font-semibold text-content-secondary uppercase tracking-wide mb-2">
        {t('workflow.revisions')} ({version})
      </h4>
      <div className="flex flex-col gap-2">
        {remarks.map((r) => (
          <div key={r.id} className="text-xs border-l-2 border-accent-blue pl-3 py-1">
            <div className="text-content-tertiary">
              {r.reviewer} — {new Date(r.created_at).toLocaleString()}
            </div>
            <div className="text-content-secondary mt-0.5">{r.comment}</div>
          </div>
        ))}
        <div className="text-xs text-content-tertiary italic">
          v1 — version initiale
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/components/features/workflow/RevisionHistory.tsx
git commit -m "feat: RevisionHistory component"
```

---

## Task 10: Frontend — DeliverablePanel component

**Files:**
- Create: `hitl-frontend/src/components/features/workflow/DeliverablePanel.tsx`

- [ ] **Step 1: Create component**

```tsx
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../ui/Button';
import { MarkdownRenderer } from '../deliverable/MarkdownRenderer';
import { RevisionHistory } from './RevisionHistory';
import * as deliverablesApi from '../../../api/deliverables';
import type { DeliverableWithContent } from '../../../api/types';

interface Props {
  deliverable: DeliverableWithContent;
  onRefresh: () => void;
}

type Mode = 'read' | 'edit' | 'comment';

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-content-tertiary',
  running: 'text-accent-blue',
  review: 'text-accent-orange',
  revision: 'text-accent-blue',
  approved: 'text-accent-green',
  rejected: 'text-accent-red',
};

export function DeliverablePanel({ deliverable, onRefresh }: Props): JSX.Element {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>('read');
  const [editContent, setEditContent] = useState(deliverable.content);
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);

  const handleValidate = useCallback(async () => {
    setSaving(true);
    try {
      await deliverablesApi.validateDeliverable(String(deliverable.id), 'approved');
      onRefresh();
    } finally {
      setSaving(false);
    }
  }, [deliverable.id, onRefresh]);

  const handleSaveEdit = useCallback(async () => {
    setSaving(true);
    try {
      await deliverablesApi.updateContent(String(deliverable.id), editContent);
      setMode('read');
      onRefresh();
    } finally {
      setSaving(false);
    }
  }, [deliverable.id, editContent, onRefresh]);

  const handleRevise = useCallback(async () => {
    if (!comment.trim()) return;
    setSaving(true);
    try {
      await deliverablesApi.reviseDeliverable(deliverable.id, comment);
      setComment('');
      setMode('read');
      onRefresh();
    } finally {
      setSaving(false);
    }
  }, [deliverable.id, comment, onRefresh]);

  const statusLabel = deliverable.status;
  const statusColor = STATUS_COLORS[statusLabel] || '';
  const canAct = ['review', 'approved', 'rejected'].includes(statusLabel);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border flex-shrink-0">
        <div>
          <span className="font-semibold text-sm">{deliverable.key}</span>
          <span className="text-xs text-content-tertiary ml-2">{deliverable.agent_name || deliverable.agent_id}</span>
          <span className={`text-xs font-medium ml-2 ${statusColor}`}>{statusLabel}</span>
          {deliverable.version > 1 && <span className="text-xs text-content-tertiary ml-1">v{deliverable.version}</span>}
        </div>
        <div className="flex gap-1.5">
          {canAct && statusLabel !== 'approved' && (
            <Button size="sm" onClick={handleValidate} loading={saving}>{t('workflow.validate')}</Button>
          )}
          {canAct && (
            <Button size="sm" variant="secondary" onClick={() => setMode(mode === 'comment' ? 'read' : 'comment')}>
              {t('workflow.comment')}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => { setEditContent(deliverable.content); setMode(mode === 'edit' ? 'read' : 'edit'); }}>
            {mode === 'edit' ? t('common.cancel') : t('workflow.edit')}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {mode === 'edit' ? (
          <div className="flex flex-col gap-2 h-full">
            <textarea
              className="flex-1 w-full rounded border border-border bg-surface-primary px-3 py-2 text-sm font-mono min-h-[300px]"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setMode('read')}>{t('common.cancel')}</Button>
              <Button size="sm" onClick={handleSaveEdit} loading={saving}>{t('common.save')}</Button>
            </div>
          </div>
        ) : (
          <>
            {deliverable.content ? (
              <MarkdownRenderer content={deliverable.content} />
            ) : (
              <p className="text-sm text-content-tertiary italic">{t('workflow.no_content')}</p>
            )}
          </>
        )}

        {/* Comment input */}
        {mode === 'comment' && (
          <div className="mt-4 border-t border-border pt-3">
            <textarea
              rows={3}
              className="w-full rounded border border-border bg-surface-primary px-3 py-2 text-sm"
              placeholder={t('workflow.comment_placeholder')}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <div className="flex justify-end gap-2 mt-2">
              <Button size="sm" variant="ghost" onClick={() => setMode('read')}>{t('common.cancel')}</Button>
              <Button size="sm" onClick={handleRevise} loading={saving} disabled={!comment.trim()}>
                {t('workflow.send_revision')}
              </Button>
            </div>
          </div>
        )}

        {/* Revision history */}
        <RevisionHistory artifactId={deliverable.id} version={deliverable.version} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/components/features/workflow/DeliverablePanel.tsx
git commit -m "feat: DeliverablePanel — read/edit/comment modes + revision history"
```

---

## Task 11: Frontend — WorkflowPhaseCard component

**Files:**
- Create: `hitl-frontend/src/components/features/workflow/WorkflowPhaseCard.tsx`

- [ ] **Step 1: Create component**

```tsx
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DeliverableWithContent, PhaseDetailResponse } from '../../../api/types';

interface Props {
  phase: PhaseDetailResponse;
  defaultExpanded?: boolean;
  selectedDeliverableId: number | null;
  onSelectDeliverable: (d: DeliverableWithContent) => void;
}

const STATUS_DOT: Record<string, string> = {
  pending: 'bg-gray-400',
  running: 'bg-accent-blue animate-pulse',
  review: 'bg-accent-orange',
  revision: 'bg-accent-blue animate-pulse',
  approved: 'bg-accent-green',
  rejected: 'bg-accent-red',
};

export function WorkflowPhaseCard({ phase, defaultExpanded = false, selectedDeliverableId, onSelectDeliverable }: Props): JSX.Element {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(defaultExpanded);

  const total = phase.deliverables.length;
  const approved = phase.deliverables.filter(d => d.status === 'approved').length;
  const hasProblems = phase.deliverables.some(d => ['rejected', 'revision', 'review'].includes(d.status));
  const isRunning = phase.status === 'running';

  // Auto-expand if running or has problems
  const shouldExpand = expanded || isRunning || hasProblems;

  const summaryText = phase.status === 'completed'
    ? `${approved}/${total} ${t('workflow.validated')}`
    : phase.status === 'running'
      ? `${approved}/${total} — ${t('workflow.in_progress')}`
      : t('workflow.status_' + phase.status);

  return (
    <div className="rounded-lg border border-border bg-surface-primary mb-2">
      {/* Header — always visible */}
      <button
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-secondary transition-colors"
        onClick={() => setExpanded(!shouldExpand || !expanded)}
      >
        <span className="text-xs">{shouldExpand ? '\u25bc' : '\u25b6'}</span>
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${phase.status === 'completed' ? 'bg-accent-green' : phase.status === 'running' ? 'bg-accent-blue animate-pulse' : 'bg-gray-400'}`} />
        <span className="font-medium text-sm flex-1">
          {phase.phase_name} <span className="text-content-tertiary font-normal">/ {phase.group_key}</span>
        </span>
        <span className="text-xs text-content-tertiary">{summaryText}</span>
      </button>

      {/* Deliverables list — expanded */}
      {shouldExpand && (
        <div className="border-t border-border">
          {phase.deliverables.map((d) => (
            <button
              key={d.id}
              className={`w-full flex items-center gap-2 px-6 py-2 text-left text-sm hover:bg-surface-secondary transition-colors ${selectedDeliverableId === d.id ? 'bg-accent-blue/10 border-l-2 border-accent-blue' : ''}`}
              onClick={() => onSelectDeliverable(d)}
            >
              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${STATUS_DOT[d.status] || 'bg-gray-400'}`} />
              <span className="flex-1 truncate">{d.key}</span>
              <span className="text-xs text-content-tertiary">{d.agent_name || d.agent_id}</span>
              <span className={`text-xs font-medium ${d.status === 'approved' ? 'text-accent-green' : d.status === 'review' ? 'text-accent-orange' : 'text-content-tertiary'}`}>
                {d.status}
              </span>
            </button>
          ))}
          {phase.deliverables.length === 0 && (
            <p className="px-6 py-3 text-xs text-content-tertiary italic">{t('workflow.no_deliverables')}</p>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/components/features/workflow/WorkflowPhaseCard.tsx
git commit -m "feat: WorkflowPhaseCard — expand/collapse with deliverable list"
```

---

## Task 12: Frontend — WorkflowExecutionPanel + integration

**Files:**
- Create: `hitl-frontend/src/components/features/workflow/WorkflowExecutionPanel.tsx`
- Modify: `hitl-frontend/src/pages/ProjectDetailPage.tsx`

- [ ] **Step 1: Create WorkflowExecutionPanel**

```tsx
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../ui/Button';
import { Spinner } from '../../ui/Spinner';
import { WorkflowPhaseCard } from './WorkflowPhaseCard';
import { DeliverablePanel } from './DeliverablePanel';
import { HumanGateBanner } from './HumanGateBanner';
import * as workflowApi from '../../../api/workflow';
import * as analysisApi from '../../../api/projects';
import type {
  DeliverableWithContent,
  ProjectWorkflowResponse,
  WorkflowPhasesResponse,
} from '../../../api/types';

interface Props {
  slug: string;
  workflows: ProjectWorkflowResponse[];
  onRefreshWorkflows: () => void;
}

export function WorkflowExecutionPanel({ slug, workflows, onRefreshWorkflows }: Props): JSX.Element {
  const { t } = useTranslation();
  const [selectedWfId, setSelectedWfId] = useState<number | null>(null);
  const [phasesData, setPhasesData] = useState<WorkflowPhasesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [selectedDeliverable, setSelectedDeliverable] = useState<DeliverableWithContent | null>(null);

  // Auto-select first active workflow, or first workflow
  useEffect(() => {
    if (!selectedWfId && workflows.length > 0) {
      const active = workflows.find(w => w.status === 'active');
      setSelectedWfId(active ? Number(active.id) : Number(workflows[0].id));
    }
  }, [workflows, selectedWfId]);

  // Load phases when workflow selected
  const loadPhases = useCallback(async () => {
    if (!selectedWfId) return;
    setLoading(true);
    try {
      const data = await workflowApi.getWorkflowPhases(slug, selectedWfId);
      setPhasesData(data);
    } catch {
      setPhasesData(null);
    } finally {
      setLoading(false);
    }
  }, [slug, selectedWfId]);

  useEffect(() => {
    void loadPhases();
  }, [loadPhases]);

  const handleStart = useCallback(async () => {
    if (!selectedWfId) return;
    setStarting(true);
    try {
      await workflowApi.startWorkflow(slug, selectedWfId);
      onRefreshWorkflows();
      void loadPhases();
    } finally {
      setStarting(false);
    }
  }, [slug, selectedWfId, onRefreshWorkflows, loadPhases]);

  const handleGateRespond = useCallback(async (response: string) => {
    if (!phasesData?.human_gate) return;
    await analysisApi.replyToQuestion(slug, phasesData.human_gate.id, response);
    void loadPhases();
  }, [slug, phasesData, loadPhases]);

  const handleRefresh = useCallback(() => {
    setSelectedDeliverable(null);
    void loadPhases();
  }, [loadPhases]);

  const selectedWf = workflows.find(w => Number(w.id) === selectedWfId);
  const canStart = selectedWf && ['pending', 'paused'].includes(selectedWf.status);

  return (
    <div className="flex flex-col h-full">
      {/* Workflow selector */}
      <div className="flex items-center gap-3 mb-4 flex-shrink-0">
        <select
          className="rounded border border-border bg-surface-primary px-3 py-1.5 text-sm flex-1"
          value={selectedWfId ?? ''}
          onChange={(e) => { setSelectedWfId(Number(e.target.value)); setSelectedDeliverable(null); }}
        >
          {workflows.map(w => (
            <option key={w.id} value={w.id}>
              {w.workflow_name} — {w.status}
            </option>
          ))}
        </select>
        {canStart && (
          <Button size="sm" onClick={handleStart} loading={starting}>
            {t('workflow.start')}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={handleRefresh}>
          {t('common.refresh')}
        </Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Spinner size="sm" />
        </div>
      )}

      {!loading && phasesData && (
        <div className="flex gap-4 flex-1 min-h-0">
          {/* Left: phases + deliverables list */}
          <div className="w-2/5 overflow-y-auto flex-shrink-0">
            {/* Human gate banner */}
            {phasesData.human_gate && (
              <HumanGateBanner gate={phasesData.human_gate} onRespond={handleGateRespond} />
            )}

            {/* Phase cards */}
            {phasesData.phases.map((phase, idx) => (
              <WorkflowPhaseCard
                key={phase.id}
                phase={phase}
                defaultExpanded={idx === 0}
                selectedDeliverableId={selectedDeliverable?.id ?? null}
                onSelectDeliverable={setSelectedDeliverable}
              />
            ))}

            {phasesData.phases.length === 0 && (
              <p className="text-sm text-content-tertiary text-center py-8">
                {canStart ? t('workflow.click_start') : t('workflow.no_phases')}
              </p>
            )}
          </div>

          {/* Right: deliverable preview */}
          <div className="flex-1 border border-border rounded-lg bg-surface-primary min-h-0 overflow-hidden">
            {selectedDeliverable ? (
              <DeliverablePanel deliverable={selectedDeliverable} onRefresh={handleRefresh} />
            ) : (
              <div className="flex items-center justify-center h-full text-sm text-content-tertiary">
                {t('workflow.select_deliverable')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Integrate into ProjectDetailPage**

In `ProjectDetailPage.tsx`, replace the workflow tab content. Find the section that renders when `tab === 'workflow'` and replace with:

```tsx
{tab === 'workflow' && (
  <WorkflowExecutionPanel
    slug={slug!}
    workflows={projectWorkflows}
    onRefreshWorkflows={() => workflowApi.listProjectWorkflows(slug!).then(setProjectWorkflows)}
  />
)}
```

Add the import at the top:
```tsx
import { WorkflowExecutionPanel } from '../components/features/workflow/WorkflowExecutionPanel';
```

- [ ] **Step 3: Add i18n keys**

In `hitl-frontend/public/locales/fr/translation.json`, add in the `workflow` section:

```json
"human_gate": "Validation requise",
"gate_response_placeholder": "Votre reponse...",
"respond": "Repondre",
"revisions": "Revisions",
"validate": "Valider",
"comment": "Commenter",
"edit": "Editer",
"comment_placeholder": "Decrivez les corrections a apporter...",
"send_revision": "Envoyer correction",
"no_content": "Aucun contenu produit",
"no_deliverables": "Aucun livrable dans ce groupe",
"select_deliverable": "Selectionnez un livrable pour le consulter",
"click_start": "Cliquez Lancer pour demarrer ce workflow",
"no_phases": "Aucune phase",
"start": "Lancer",
"validated": "valides",
"in_progress": "en cours"
```

Same in `en/translation.json`:
```json
"human_gate": "Validation required",
"gate_response_placeholder": "Your response...",
"respond": "Respond",
"revisions": "Revisions",
"validate": "Validate",
"comment": "Comment",
"edit": "Edit",
"comment_placeholder": "Describe the corrections needed...",
"send_revision": "Send revision",
"no_content": "No content produced",
"no_deliverables": "No deliverables in this group",
"select_deliverable": "Select a deliverable to preview",
"click_start": "Click Start to launch this workflow",
"no_phases": "No phases",
"start": "Start",
"validated": "validated",
"in_progress": "in progress"
```

- [ ] **Step 4: Build and verify**

```bash
cd hitl-frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add hitl-frontend/src/components/features/workflow/WorkflowExecutionPanel.tsx
git add hitl-frontend/src/pages/ProjectDetailPage.tsx
git add hitl-frontend/public/locales/*/translation.json
git commit -m "feat: WorkflowExecutionPanel — split view with phase cards + deliverable preview"
```

---

## Task 13: Deploy and test

- [ ] **Step 1: Deploy**

```bash
cd /path/to/LandGraph && bash deploy.sh AGT1
```

Note: this rebuilds hitl-console (frontend + backend). Also rebuild langgraph-api if `deliverable_tools.py` was modified:

```bash
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose build --no-cache langgraph-api && docker compose up -d langgraph-api"
```

Apply SQL schema:
```bash
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose exec langgraph-postgres psql -U langgraph -d langgraph < scripts/init.sql"
```

- [ ] **Step 2: Verify**

1. Go to `/projects/performances-trainer` → Workflow tab
2. Should see workflow selector with onboarding + main + security_audit
3. Select a pending workflow → "Lancer" button visible
4. Click Lancer → first phase appears with agent dispatched
5. Wait for agent to produce deliverable → status changes to "review"
6. Click deliverable → markdown preview on the right
7. Click "Valider" → status = approved
8. Click "Commenter" → type correction → send → agent re-dispatches
9. Click "Editer" → direct markdown edit → save

---

## Notes for the implementer

- `replyToQuestion` in the frontend API (`api/projects.ts`) may need to be added if it doesn't exist yet — check for an existing function that calls `POST /api/projects/{slug}/analysis/reply`
- The `save_deliverable` tool already registers artifacts in `dispatcher_task_artifacts` (implemented earlier today)
- The `version` column is new — existing artifacts will default to 1
- When the agent re-dispatches via `revise_deliverable`, it uses the gateway `direct_agent` mode which runs the agent in a background task. The frontend should poll or use WS to detect when the revision is complete
- Status transitions: `pending → running → review → (revision → review)* → approved`
