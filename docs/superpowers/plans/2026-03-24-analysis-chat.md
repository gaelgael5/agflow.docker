# Analysis Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the wizard Analysis step into an interactive real-time chat with the team's orchestrator via the dispatcher.

**Architecture:** Backend rewrites `analysis_service.py` to resolve the orchestrator dynamically, merge 3 conversation sources (dispatcher events + HITL requests + rag_conversations), and support reply/free-message endpoints. Frontend rewrites `WizardStepAnalysis.tsx` as an interactive chat using WebSocket events filtered by task_id/thread_id with polling fallback.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / asyncpg, React 18 / TypeScript / Zustand / Vite, PostgreSQL PG NOTIFY, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-24-analysis-chat-design.md`

---

## File Map

### Backend — New/Modified

| File | Action | Responsibility |
|------|--------|----------------|
| `hitl/schemas/rag.py` | Modify | Add `AnalysisMessage`, `AnalysisReplyRequest`, `AnalysisFreeMessageRequest` schemas |
| `hitl/services/analysis_service.py` | Rewrite | Orchestrator resolution, conversation merge, reply, free message, status sync |
| `hitl/routes/rag.py` | Modify | Add `/reply` and `/message` endpoints, rewrite `/start` and `/status` |
| `scripts/init.sql` | Modify | Add `analysis_task_id` and `analysis_status` columns to `pm_projects` |

### Backend — Tests

| File | Action |
|------|--------|
| `hitl/tests/test_analysis_service.py` | Create |

### Frontend — New

| File | Responsibility |
|------|----------------|
| `hitl-frontend/src/api/analysis.ts` | API client for all 5 analysis endpoints |
| `hitl-frontend/src/stores/analysisStore.ts` | Zustand store: status, taskId, threadId, messages, pendingQuestion |
| `hitl-frontend/src/components/features/project/AnalysisChatMessage.tsx` | Render a single message by type (progress/question/reply/artifact/result/system) |
| `hitl-frontend/src/components/features/project/AnalysisQuestionBanner.tsx` | Banner above input when question pending |

### Frontend — Modified

| File | Change |
|------|--------|
| `hitl-frontend/src/api/types.ts` | Add `AnalysisMessage`, `AnalysisStatus`, `AnalysisStatusResponse`, `AnalysisStartResponse` |
| `hitl-frontend/src/components/features/project/WizardStepAnalysis.tsx` | Full rewrite — interactive chat |
| `hitl-frontend/src/components/features/project/AnalysisChat.tsx` | Delete |
| `hitl-frontend/public/locales/fr/translation.json` | Expand `analysis.*` keys |
| `hitl-frontend/public/locales/en/translation.json` | Add `analysis.*` keys |

---

## Task 1: SQL Schema — Add analysis columns

**Files:**
- Modify: `scripts/init.sql`

- [ ] **Step 1: Add ALTER statements to init.sql**

Find the section with `pm_projects` ALTERs and append:

```sql
ALTER TABLE project.pm_projects ADD COLUMN IF NOT EXISTS analysis_task_id TEXT;
ALTER TABLE project.pm_projects ADD COLUMN IF NOT EXISTS analysis_status TEXT DEFAULT 'not_started';
```

No CHECK constraint (init.sql uses IF NOT EXISTS pattern, CHECK can't be added idempotently).

- [ ] **Step 2: Commit**

```
feat(sql): add analysis_task_id and analysis_status to pm_projects
```

---

## Task 2: Backend schemas — AnalysisMessage + request models

**Files:**
- Modify: `hitl/schemas/rag.py`

- [ ] **Step 1: Add new Pydantic models after existing `ConversationMessage`**

```python
from typing import Literal


class AnalysisMessage(BaseModel):
    """A message in the unified analysis conversation."""

    id: str
    sender: Literal["agent", "user", "system"]
    type: Literal["progress", "question", "reply", "artifact", "result", "system"]
    content: str
    request_id: Optional[str] = None
    status: Optional[str] = None
    artifact_key: Optional[str] = None
    created_at: str


class AnalysisReplyRequest(BaseModel):
    """Reply to an agent question."""

    request_id: str
    response: str


class AnalysisFreeMessageRequest(BaseModel):
    """Free message to the agent (triggers relaunch)."""

    content: str
```

- [ ] **Step 2: Commit**

```
feat(schemas): add AnalysisMessage and request models
```

---

## Task 3: Backend service — Rewrite analysis_service.py

**Files:**
- Rewrite: `hitl/services/analysis_service.py`
- Reference: `hitl/core/config.py` (for `settings.dispatcher_url`, `settings.hitl_internal_url`)

This is the largest backend task. Split into sub-steps.

- [ ] **Step 1: Write `_resolve_orchestrator(team_id)` and `_build_instruction()`**

```python
"""Analysis service — orchestrator-driven project analysis conversation."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import httpx
import structlog

from core.config import settings, _find_config_dir, load_teams
from core.database import execute, fetch_all, fetch_one
from schemas.rag import AnalysisMessage

log = structlog.get_logger(__name__)

ONBOARDING_THREAD_PREFIX = "onboarding-"
_HTTP_TIMEOUT = 30
_MAX_CONVERSATION_CONTEXT = 20


async def _resolve_orchestrator(team_id: str) -> dict[str, str]:
    """Find orchestrator agent from agents_registry.json. Returns {agent_id, name}."""
    teams = load_teams()
    team_dir = ""
    for t in teams:
        if t["id"] == team_id:
            team_dir = t.get("directory", "")
            break
    if not team_dir:
        raise ValueError(f"Team {team_id} not found")

    config_dir = _find_config_dir()
    for candidate in [
        os.path.join(config_dir, "Teams", team_dir, "agents_registry.json"),
        os.path.join(config_dir, team_dir, "agents_registry.json"),
    ]:
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                registry = json.load(f)
            for aid, cfg in registry.get("agents", {}).items():
                if cfg.get("type") == "orchestrator":
                    return {"agent_id": aid, "name": cfg.get("name", aid)}
            break

    raise ValueError(f"No orchestrator found for team {team_id}")


def _build_instruction(
    project_slug: str,
    project_name: str,
    team_name: str,
    documents: list[str],
) -> str:
    doc_list = "\n".join(f"- {d}" for d in documents) if documents else "(aucun document)"
    return (
        f"Tu es l'orchestrateur de l'equipe {team_name}. "
        f"Un nouveau projet '{project_name}' (slug: {project_slug}) vient d'etre cree.\n\n"
        f"Documents fournis :\n{doc_list}\n\n"
        "Ta mission :\n"
        "1. Analyse les documents fournis via le RAG\n"
        "2. Pose des questions pour clarifier le perimetre, les objectifs, les contraintes\n"
        "3. Delegue aux agents specialises si necessaire\n"
        "4. Quand le projet est clair, produis une synthese structuree\n"
    )


def _build_relaunch_instruction(
    conversation: list[AnalysisMessage],
    new_message: str,
) -> str:
    recent = conversation[-_MAX_CONVERSATION_CONTEXT:]
    lines = []
    for m in recent:
        prefix = "Agent" if m.sender == "agent" else "Utilisateur"
        lines.append(f"[{prefix}] {m.content[:500]}")
    history = "\n".join(lines)
    return (
        "Voici l'historique de la conversation d'analyse du projet :\n\n"
        f"{history}\n\n"
        f"Nouveau message de l'utilisateur : {new_message}\n\n"
        "Continue l'analyse en tenant compte de ce nouveau message."
    )
```

- [ ] **Step 2: Write `start_analysis()`**

```python
async def start_analysis(
    project_slug: str,
    team_id: str,
    workflow_id: Optional[int] = None,
) -> dict[str, Any]:
    """Launch the team orchestrator to analyze the project."""
    orch = await _resolve_orchestrator(team_id)
    agent_id = orch["agent_id"]

    # Project name
    proj = await fetch_one(
        "SELECT name FROM project.pm_projects WHERE slug = $1", project_slug,
    )
    project_name = proj["name"] if proj else project_slug

    # Team name
    teams = load_teams()
    team_name = team_id
    for t in teams:
        if t["id"] == team_id:
            team_name = t.get("name", team_id)
            break

    # Uploaded documents
    uploads_dir = os.path.join(settings.uploads_root, project_slug)
    documents: list[str] = []
    if os.path.isdir(uploads_dir):
        documents = [f for f in os.listdir(uploads_dir) if not f.startswith(".")]

    thread_id = f"{ONBOARDING_THREAD_PREFIX}{project_slug}"
    rag_endpoint = f"{settings.hitl_internal_url}/api/internal/rag/search"
    instruction = _build_instruction(project_slug, project_name, team_name, documents)

    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "team_id": team_id,
        "thread_id": thread_id,
        "project_slug": project_slug,
        "phase": "onboarding",
        "payload": {
            "instruction": instruction,
            "context": {
                "rag_endpoint": rag_endpoint,
                "project_slug": project_slug,
                "documents": documents,
            },
        },
    }
    if workflow_id is not None:
        payload["workflow_id"] = workflow_id

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.dispatcher_url}/api/tasks/run", json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        log.error("analysis_dispatch_failed", slug=project_slug, error=str(exc))
        return {"error": "dispatcher_unavailable"}

    task_id = data.get("task_id", data.get("id", ""))

    await execute(
        "UPDATE project.pm_projects SET analysis_task_id = $1, analysis_status = 'in_progress' WHERE slug = $2",
        str(task_id), project_slug,
    )

    log.info("analysis_started", slug=project_slug, task_id=task_id, agent_id=agent_id)
    return {"task_id": str(task_id), "agent_id": agent_id, "status": "started"}
```

- [ ] **Step 3: Write `get_analysis_status()` and `_sync_status()`**

```python
async def _sync_status(project_slug: str, task_id: str) -> str:
    """Sync analysis_status with dispatcher state and pending questions."""
    thread_id = f"{ONBOARDING_THREAD_PREFIX}{project_slug}"

    # Check pending HITL questions
    pending = await fetch_one(
        "SELECT id FROM project.hitl_requests WHERE thread_id = $1 AND status = 'pending' LIMIT 1",
        thread_id,
    )
    if pending:
        await execute(
            "UPDATE project.pm_projects SET analysis_status = 'waiting_input' WHERE slug = $1",
            project_slug,
        )
        return "waiting_input"

    # Check dispatcher task state
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{settings.dispatcher_url}/api/tasks/{task_id}")
            resp.raise_for_status()
            task_data = resp.json()
    except httpx.HTTPError:
        return "in_progress"  # Assume still running if dispatcher unavailable

    status = task_data.get("status", "")
    if status in ("success",):
        new_status = "completed"
    elif status in ("failure", "timeout", "cancelled"):
        new_status = "failed"
    else:
        new_status = "in_progress"

    await execute(
        "UPDATE project.pm_projects SET analysis_status = $1 WHERE slug = $2",
        new_status, project_slug,
    )
    return new_status


async def get_analysis_status(project_slug: str) -> dict[str, Any]:
    """Get analysis status, syncing with dispatcher."""
    row = await fetch_one(
        "SELECT analysis_task_id, analysis_status FROM project.pm_projects WHERE slug = $1",
        project_slug,
    )
    if not row or not row["analysis_task_id"]:
        return {"status": "not_started", "task_id": None, "has_pending_question": False, "pending_request_id": None}

    task_id = row["analysis_task_id"]
    current = row["analysis_status"] or "not_started"

    # Sync if not terminal
    if current not in ("completed", "failed", "not_started"):
        current = await _sync_status(project_slug, task_id)

    # Check pending question
    thread_id = f"{ONBOARDING_THREAD_PREFIX}{project_slug}"
    pending = await fetch_one(
        "SELECT id FROM project.hitl_requests WHERE thread_id = $1 AND status = 'pending' LIMIT 1",
        thread_id,
    )

    return {
        "status": current,
        "task_id": task_id,
        "has_pending_question": pending is not None,
        "pending_request_id": str(pending["id"]) if pending else None,
    }
```

- [ ] **Step 4: Write `get_conversation()` — merge 3 sources**

```python
async def get_conversation(project_slug: str) -> list[AnalysisMessage]:
    """Merge dispatcher events + HITL requests + rag_conversations."""
    thread_id = f"{ONBOARDING_THREAD_PREFIX}{project_slug}"
    messages: list[AnalysisMessage] = []

    # 1. Dispatcher events (progress, artifact, result) via thread_id
    event_rows = await fetch_all(
        """
        SELECT e.id, e.event_type, e.data, e.created_at
        FROM project.dispatcher_task_events e
        JOIN project.dispatcher_tasks t ON e.task_id = t.id
        WHERE t.thread_id = $1
        ORDER BY e.created_at ASC
        """,
        thread_id,
    )
    for r in event_rows:
        etype = r["event_type"]
        data = r["data"] if isinstance(r["data"], dict) else {}
        content = data.get("data", data.get("content", str(data)))
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)

        msg_type = etype  # progress, artifact, result
        if msg_type not in ("progress", "artifact", "result"):
            msg_type = "progress"

        messages.append(AnalysisMessage(
            id=f"evt-{r['id']}",
            sender="agent",
            type=msg_type,
            content=str(content)[:5000],
            artifact_key=data.get("key") if etype == "artifact" else None,
            created_at=r["created_at"].isoformat(),
        ))

    # 2. HITL requests (questions + answers)
    hitl_rows = await fetch_all(
        """
        SELECT id, prompt, response, status, created_at, answered_at
        FROM project.hitl_requests
        WHERE thread_id = $1
        ORDER BY created_at ASC
        """,
        thread_id,
    )
    for r in hitl_rows:
        # Question message
        messages.append(AnalysisMessage(
            id=f"q-{r['id']}",
            sender="agent",
            type="question",
            content=r["prompt"],
            request_id=str(r["id"]),
            status=r["status"],
            created_at=r["created_at"].isoformat(),
        ))
        # Answer message (if answered)
        if r["status"] == "answered" and r["response"]:
            ts = r["answered_at"] or r["created_at"]
            messages.append(AnalysisMessage(
                id=f"a-{r['id']}",
                sender="user",
                type="reply",
                content=r["response"],
                request_id=str(r["id"]),
                created_at=ts.isoformat(),
            ))

    # 3. User free messages from rag_conversations
    conv_rows = await fetch_all(
        """
        SELECT id, sender, content, created_at
        FROM project.rag_conversations
        WHERE project_slug = $1
        ORDER BY created_at ASC
        """,
        project_slug,
    )
    for r in conv_rows:
        messages.append(AnalysisMessage(
            id=f"msg-{r['id']}",
            sender=r["sender"],
            type="reply" if r["sender"] == "user" else "progress",
            content=r["content"],
            created_at=r["created_at"].isoformat(),
        ))

    # Sort chronologically
    messages.sort(key=lambda m: m.created_at)
    return messages
```

- [ ] **Step 5: Write `reply_to_question()` and `send_free_message()`**

```python
async def reply_to_question(
    project_slug: str,
    request_id: str,
    response: str,
    reviewer: str,
) -> dict[str, Any]:
    """Reply to an agent HITL question."""
    thread_id = f"{ONBOARDING_THREAD_PREFIX}{project_slug}"

    # Verify the question belongs to this project
    row = await fetch_one(
        "SELECT id, thread_id, status FROM project.hitl_requests WHERE id = $1::uuid",
        request_id,
    )
    if not row:
        raise ValueError("Question not found")
    if row["thread_id"] != thread_id:
        raise ValueError("Question does not belong to this project")
    if row["status"] != "pending":
        raise ValueError("Question already answered")

    # Answer the question (same mechanism as inbox)
    await execute(
        """
        UPDATE project.hitl_requests
        SET status = 'answered', response = $1, reviewer = $2,
            response_channel = 'hitl-console', answered_at = NOW()
        WHERE id = $3::uuid
        """,
        response, reviewer, request_id,
    )

    # Save in rag_conversations for history
    await execute(
        "INSERT INTO project.rag_conversations (project_slug, sender, content) VALUES ($1, $2, $3)",
        project_slug, "user", response,
    )

    # Update status
    await execute(
        "UPDATE project.pm_projects SET analysis_status = 'in_progress' WHERE slug = $1",
        project_slug,
    )

    return {"ok": True}


async def send_free_message(
    project_slug: str,
    content: str,
    user_email: str,
) -> dict[str, Any]:
    """Send a free message — cancel current task and relaunch agent."""
    # Save user message
    await execute(
        "INSERT INTO project.rag_conversations (project_slug, sender, content) VALUES ($1, $2, $3)",
        project_slug, "user", content,
    )

    # Get current task_id and team_id
    proj = await fetch_one(
        "SELECT team_id, analysis_task_id FROM project.pm_projects WHERE slug = $1",
        project_slug,
    )
    if not proj:
        raise ValueError("Project not found")

    team_id = proj["team_id"]
    old_task_id = proj["analysis_task_id"]

    # Cancel current task if running
    if old_task_id:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{settings.dispatcher_url}/api/tasks/{old_task_id}/cancel")
        except httpx.HTTPError:
            pass  # Best effort

    # Build enriched instruction
    conversation = await get_conversation(project_slug)
    instruction = _build_relaunch_instruction(conversation, content)

    orch = await _resolve_orchestrator(team_id)
    thread_id = f"{ONBOARDING_THREAD_PREFIX}{project_slug}"

    payload: dict[str, Any] = {
        "agent_id": orch["agent_id"],
        "team_id": team_id,
        "thread_id": thread_id,
        "project_slug": project_slug,
        "phase": "onboarding",
        "payload": {
            "instruction": instruction,
            "context": {
                "rag_endpoint": f"{settings.hitl_internal_url}/api/internal/rag/search",
                "project_slug": project_slug,
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(f"{settings.dispatcher_url}/api/tasks/run", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        log.error("analysis_relaunch_failed", slug=project_slug, error=str(exc))
        return {"error": "dispatcher_unavailable"}

    task_id = data.get("task_id", data.get("id", ""))
    await execute(
        "UPDATE project.pm_projects SET analysis_task_id = $1, analysis_status = 'in_progress' WHERE slug = $2",
        str(task_id), project_slug,
    )

    return {"task_id": str(task_id), "status": "started"}
```

- [ ] **Step 6: Commit**

```
feat(analysis): rewrite analysis_service with orchestrator resolution, conversation merge, reply and free message
```

---

## Task 4: Backend routes — Update rag.py endpoints

**Files:**
- Modify: `hitl/routes/rag.py` (lines 175-209)

- [ ] **Step 1: Rewrite existing endpoints + add reply and message**

Replace lines 175-209 with:

```python
from schemas.rag import AnalysisMessage, AnalysisReplyRequest, AnalysisFreeMessageRequest


@router.post("/{slug}/analysis/start")
async def start_analysis(
    slug: str,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Start an AI analysis of project documents."""
    project = await project_service.get_project(slug)
    if not project:
        raise HTTPException(status_code=404, detail="project.not_found")
    _check_project_access(user, project.team_id)
    return await analysis_service.start_analysis(slug, project.team_id)


@router.get("/{slug}/analysis/status")
async def analysis_status(
    slug: str,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Check analysis status with dispatcher sync."""
    await _require_project(slug, user)
    return await analysis_service.get_analysis_status(slug)


@router.get(
    "/{slug}/analysis/conversation",
    response_model=list[AnalysisMessage],
)
async def get_conversation(
    slug: str,
    user: TokenData = Depends(get_current_user),
) -> list[AnalysisMessage]:
    """Get the merged analysis conversation history."""
    await _require_project(slug, user)
    return await analysis_service.get_conversation(slug)


@router.post("/{slug}/analysis/reply")
async def reply_to_question(
    slug: str,
    body: AnalysisReplyRequest,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Reply to an agent question in the analysis conversation."""
    await _require_project(slug, user)
    try:
        return await analysis_service.reply_to_question(
            slug, body.request_id, body.response, user.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{slug}/analysis/message")
async def send_free_message(
    slug: str,
    body: AnalysisFreeMessageRequest,
    user: TokenData = Depends(get_current_user),
) -> dict:
    """Send a free message — relaunches the agent with enriched context."""
    await _require_project(slug, user)
    try:
        return await analysis_service.send_free_message(slug, body.content, user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
```

- [ ] **Step 2: Remove unused imports** (`ConversationMessage` from old schema import if no longer used)

- [ ] **Step 3: Commit**

```
feat(routes): add analysis reply and message endpoints, rewrite status to use slug
```

---

## Task 5: Backend tests

**Files:**
- Create: `hitl/tests/test_analysis_service.py`

- [ ] **Step 1: Write tests**

Follow existing test patterns from `hitl/tests/conftest.py` (use `FakeRecord`, `make_record`, mock `fetch_one`/`fetch_all`/`execute` from `core.database`, mock `httpx.AsyncClient`).

Key tests:
- `test_resolve_orchestrator` — mock `load_teams`, mock `os.path.isfile` + `open` for registry JSON, verify returns orchestrator agent_id
- `test_resolve_orchestrator_not_found` — raises ValueError
- `test_start_analysis` — mock dispatcher POST, verify payload includes resolved orchestrator, thread_id = `onboarding-{slug}`, pm_projects updated
- `test_get_conversation_merge` — mock all 3 queries (events, hitl_requests, rag_conversations), verify chronological merge
- `test_reply_to_question` — mock fetch_one for request, verify UPDATE called with answered status
- `test_reply_wrong_thread` — mock request with different thread_id, verify ValueError
- `test_send_free_message` — mock cancel POST + new task POST, verify old task cancelled and new one created
- `test_get_status_sync` — mock dispatcher GET + pending question check

- [ ] **Step 2: Run tests**

```bash
cd hitl && python -m pytest tests/test_analysis_service.py -v
```

- [ ] **Step 3: Commit**

```
test(analysis): add analysis service tests
```

---

## Task 6: Frontend types

**Files:**
- Modify: `hitl-frontend/src/api/types.ts`

- [ ] **Step 1: Add new types at end of file** (after existing types, before EOF)

```typescript
/* ── Analysis Chat ── */

export type AnalysisStatus = 'not_started' | 'in_progress' | 'waiting_input' | 'completed' | 'failed';

export interface AnalysisStatusResponse {
  status: AnalysisStatus;
  task_id: string | null;
  has_pending_question: boolean;
  pending_request_id: string | null;
}

export interface AnalysisStartResponse {
  task_id: string;
  agent_id: string;
  status: string;
}

export interface AnalysisMessage {
  id: string;
  sender: 'agent' | 'user' | 'system';
  type: 'progress' | 'question' | 'reply' | 'artifact' | 'result' | 'system';
  content: string;
  request_id?: string;
  status?: string;
  artifact_key?: string;
  created_at: string;
}
```

- [ ] **Step 2: Commit**

```
feat(types): add AnalysisMessage and AnalysisStatus types
```

---

## Task 7: Frontend API client

**Files:**
- Create: `hitl-frontend/src/api/analysis.ts`

- [ ] **Step 1: Create API module**

```typescript
import { apiFetch } from './client';
import type { AnalysisStartResponse, AnalysisStatusResponse, AnalysisMessage } from './types';

const enc = encodeURIComponent;

export function startAnalysis(slug: string): Promise<AnalysisStartResponse> {
  return apiFetch<AnalysisStartResponse>(`/api/projects/${enc(slug)}/analysis/start`, { method: 'POST' });
}

export function getStatus(slug: string): Promise<AnalysisStatusResponse> {
  return apiFetch<AnalysisStatusResponse>(`/api/projects/${enc(slug)}/analysis/status`);
}

export function getConversation(slug: string): Promise<AnalysisMessage[]> {
  return apiFetch<AnalysisMessage[]>(`/api/projects/${enc(slug)}/analysis/conversation`);
}

export function reply(slug: string, requestId: string, response: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/projects/${enc(slug)}/analysis/reply`, {
    method: 'POST',
    body: JSON.stringify({ request_id: requestId, response }),
  });
}

export function sendMessage(slug: string, content: string): Promise<{ task_id: string; status: string }> {
  return apiFetch<{ task_id: string; status: string }>(`/api/projects/${enc(slug)}/analysis/message`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}
```

- [ ] **Step 2: Commit**

```
feat(api): add analysis API client
```

---

## Task 8: Frontend store — analysisStore

**Files:**
- Create: `hitl-frontend/src/stores/analysisStore.ts`

- [ ] **Step 1: Create Zustand store**

```typescript
import { create } from 'zustand';
import type { AnalysisMessage } from '../api/types';

type AnalysisUiStatus = 'idle' | 'starting' | 'running' | 'waiting_input' | 'completed' | 'failed';

interface PendingQuestion {
  requestId: string;
  prompt: string;
}

interface AnalysisState {
  status: AnalysisUiStatus;
  taskId: string | null;
  threadId: string | null;
  messages: AnalysisMessage[];
  pendingQuestion: PendingQuestion | null;

  setStatus: (s: AnalysisUiStatus) => void;
  setTaskId: (id: string | null) => void;
  setThreadId: (id: string | null) => void;
  addMessage: (msg: AnalysisMessage) => void;
  setMessages: (msgs: AnalysisMessage[]) => void;
  setPendingQuestion: (q: PendingQuestion | null) => void;
  reset: () => void;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  status: 'idle',
  taskId: null,
  threadId: null,
  messages: [],
  pendingQuestion: null,

  setStatus: (status) => set({ status }),
  setTaskId: (taskId) => set({ taskId }),
  setThreadId: (threadId) => set({ threadId }),
  addMessage: (msg) => set((s) => {
    if (s.messages.some((m) => m.id === msg.id)) return s;
    return { messages: [...s.messages, msg] };
  }),
  setMessages: (messages) => set({ messages }),
  setPendingQuestion: (pendingQuestion) => set({ pendingQuestion }),
  reset: () => set({ status: 'idle', taskId: null, threadId: null, messages: [], pendingQuestion: null }),
}));
```

- [ ] **Step 2: Commit**

```
feat(store): add analysisStore for analysis chat state
```

---

## Task 9: Frontend component — AnalysisChatMessage

**Files:**
- Create: `hitl-frontend/src/components/features/project/AnalysisChatMessage.tsx`

- [ ] **Step 1: Create message renderer**

```typescript
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Avatar } from '../../ui/Avatar';
import { Badge } from '../../ui/Badge';
import { MarkdownRenderer } from '../deliverable/MarkdownRenderer';
import type { AnalysisMessage } from '../../../api/types';

interface AnalysisChatMessageProps {
  message: AnalysisMessage;
  className?: string;
}

export function AnalysisChatMessage({ message, className = '' }: AnalysisChatMessageProps): JSX.Element {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const time = new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (message.type === 'system') {
    return (
      <p className={`text-center text-xs italic text-content-quaternary py-1 ${className}`}>
        {message.content}
      </p>
    );
  }

  const isUser = message.sender === 'user';
  const isQuestion = message.type === 'question';
  const isArtifact = message.type === 'artifact';
  const isResult = message.type === 'result';

  return (
    <div className={`flex max-w-[85%] gap-2 ${isUser ? 'self-end flex-row-reverse' : 'self-start'} ${className}`}>
      {!isUser && <Avatar name="Agent" size="sm" className="flex-shrink-0 mt-1" />}
      <div className="flex flex-col gap-1">
        <div
          className={[
            'rounded-lg px-3 py-2 text-sm',
            isUser ? 'bg-accent-blue/20 text-content-primary' : 'bg-surface-tertiary text-content-primary',
            isQuestion && message.status === 'pending' ? 'border border-accent-orange' : '',
          ].join(' ')}
        >
          {isQuestion && (
            <div className="flex items-center gap-1.5 mb-1">
              <Badge size="sm" color="orange">{t('analysis.question_badge')}</Badge>
              {message.status === 'pending' && <span className="h-2 w-2 rounded-full bg-accent-orange animate-pulse" />}
            </div>
          )}
          {isResult && (
            <Badge size="sm" color={message.content.includes('fail') || message.content.includes('error') ? 'red' : 'green'} className="mb-1">
              {message.content.includes('fail') || message.content.includes('error') ? t('analysis.failed') : t('analysis.completed')}
            </Badge>
          )}
          {isArtifact ? (
            <div>
              <Badge size="sm" color="purple" className="mb-1">{t('analysis.artifact_badge')}</Badge>
              <div className={`${expanded ? '' : 'max-h-[300px] overflow-hidden'}`}>
                <MarkdownRenderer content={message.content} />
              </div>
              {message.content.length > 500 && (
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="text-xs text-accent-blue mt-1 hover:underline"
                >
                  {expanded ? '▲' : '▼'}
                </button>
              )}
            </div>
          ) : (
            <MarkdownRenderer content={message.content} />
          )}
        </div>
        <span className={`text-[10px] text-content-quaternary px-1 ${isUser ? 'text-right' : ''}`}>{time}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```
feat(ui): add AnalysisChatMessage component
```

---

## Task 10: Frontend component — AnalysisQuestionBanner

**Files:**
- Create: `hitl-frontend/src/components/features/project/AnalysisQuestionBanner.tsx`

- [ ] **Step 1: Create banner**

```typescript
import { useTranslation } from 'react-i18next';

interface AnalysisQuestionBannerProps {
  className?: string;
}

export function AnalysisQuestionBanner({ className = '' }: AnalysisQuestionBannerProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-t-lg bg-accent-orange/10 border border-accent-orange/30 text-xs text-accent-orange ${className}`}>
      <span className="h-2 w-2 rounded-full bg-accent-orange animate-pulse" />
      {t('analysis.waiting_input')}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```
feat(ui): add AnalysisQuestionBanner component
```

---

## Task 11: Frontend — Rewrite WizardStepAnalysis

**Files:**
- Rewrite: `hitl-frontend/src/components/features/project/WizardStepAnalysis.tsx`
- Delete: `hitl-frontend/src/components/features/project/AnalysisChat.tsx`

- [ ] **Step 1: Rewrite WizardStepAnalysis.tsx**

```typescript
import { useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../ui/Button';
import { Spinner } from '../../ui/Spinner';
import { ChatInput } from '../chat/ChatInput';
import { ChatTypingIndicator } from '../chat/ChatTypingIndicator';
import { AnalysisChatMessage } from './AnalysisChatMessage';
import { AnalysisQuestionBanner } from './AnalysisQuestionBanner';
import { useAnalysisStore } from '../../../stores/analysisStore';
import { useWsStore } from '../../../stores/wsStore';
import { useProjectStore } from '../../../stores/projectStore';
import { useTeamStore } from '../../../stores/teamStore';
import * as analysisApi from '../../../api/analysis';
import type { AnalysisMessage, WebSocketEvent } from '../../../api/types';

const POLL_INTERVAL = 5_000;
const THREAD_PREFIX = 'onboarding-';

interface WizardStepAnalysisProps {
  className?: string;
}

export function WizardStepAnalysis({ className = '' }: WizardStepAnalysisProps): JSX.Element {
  const { t } = useTranslation();
  const slug = useProjectStore((s) => s.wizardData.slug);
  const teamId = useProjectStore((s) => s.wizardData.teamId) || useTeamStore((s) => s.activeTeamId);
  const bottomRef = useRef<HTMLDivElement>(null);

  const {
    status, taskId, threadId, messages, pendingQuestion,
    setStatus, setTaskId, setThreadId, addMessage, setMessages, setPendingQuestion, reset,
  } = useAnalysisStore();

  const wsConnected = useWsStore((s) => s.connected);
  const lastEvent = useWsStore((s) => s.lastEvent);

  // ── Init: check status on mount ──
  useEffect(() => {
    if (!slug) return;
    reset();
    setThreadId(`${THREAD_PREFIX}${slug}`);

    analysisApi.getStatus(slug).then((res) => {
      if (res.status === 'not_started') {
        setStatus('idle');
      } else {
        setStatus(res.status === 'waiting_input' ? 'waiting_input' : res.status === 'completed' ? 'completed' : res.status === 'failed' ? 'failed' : 'running');
        if (res.task_id) setTaskId(res.task_id);
        if (res.has_pending_question && res.pending_request_id) {
          setPendingQuestion({ requestId: res.pending_request_id, prompt: '' });
        }
        // Load conversation
        analysisApi.getConversation(slug).then(setMessages).catch(() => {});
      }
    }).catch(() => setStatus('idle'));
  }, [slug]);

  // ── Start analysis ──
  const handleStart = useCallback(async () => {
    if (!slug) return;
    setStatus('starting');
    try {
      const res = await analysisApi.startAnalysis(slug);
      setTaskId(res.task_id);
      setStatus('running');
    } catch {
      setStatus('failed');
    }
  }, [slug]);

  // ── WS event handler ──
  useEffect(() => {
    if (!lastEvent || !taskId || !threadId) return;
    const ev: WebSocketEvent = lastEvent;
    const d = ev.data ?? {};

    if (ev.type === 'task_progress' && d.task_id === taskId) {
      const content = typeof d.data === 'string' ? d.data : JSON.stringify(d.data);
      addMessage({
        id: `ws-prog-${Date.now()}`,
        sender: 'agent',
        type: 'progress',
        content,
        created_at: new Date().toISOString(),
      });
    }

    if (ev.type === 'new_question' && d.thread_id === threadId) {
      const msg: AnalysisMessage = {
        id: `ws-q-${d.id ?? Date.now()}`,
        sender: 'agent',
        type: 'question',
        content: typeof d.prompt === 'string' ? d.prompt : '',
        request_id: typeof d.id === 'string' ? d.id : String(d.id ?? ''),
        status: 'pending',
        created_at: new Date().toISOString(),
      };
      addMessage(msg);
      setPendingQuestion({ requestId: msg.request_id!, prompt: msg.content });
      setStatus('waiting_input');
    }

    if (ev.type === 'question_answered' && pendingQuestion && String(d.request_id) === pendingQuestion.requestId) {
      setPendingQuestion(null);
      setStatus('running');
    }

    if (ev.type === 'task_artifact' && d.task_id === taskId) {
      // Reload conversation to get artifact content from server
      if (slug) analysisApi.getConversation(slug).then(setMessages).catch(() => {});
    }
  }, [lastEvent]);

  // ── Polling fallback when WS disconnected ──
  useEffect(() => {
    if (wsConnected || !slug || status === 'idle' || status === 'completed' || status === 'failed') return;
    const interval = setInterval(() => {
      analysisApi.getConversation(slug).then(setMessages).catch(() => {});
      analysisApi.getStatus(slug).then((res) => {
        if (res.status === 'completed') setStatus('completed');
        else if (res.status === 'failed') setStatus('failed');
        else if (res.has_pending_question && res.pending_request_id) {
          setPendingQuestion({ requestId: res.pending_request_id, prompt: '' });
          setStatus('waiting_input');
        }
        if (res.task_id && res.task_id !== taskId) setTaskId(res.task_id);
      }).catch(() => {});
    }, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [wsConnected, slug, status, taskId]);

  // ── Auto-scroll ──
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ── Send handler ──
  const handleSend = useCallback(async (text: string) => {
    if (!slug) return;

    if (pendingQuestion) {
      // Reply to question
      addMessage({
        id: `opt-reply-${Date.now()}`,
        sender: 'user',
        type: 'reply',
        content: text,
        request_id: pendingQuestion.requestId,
        created_at: new Date().toISOString(),
      });
      setPendingQuestion(null);
      setStatus('running');
      await analysisApi.reply(slug, pendingQuestion.requestId, text).catch(() => {});
    } else {
      // Free message — relaunch
      addMessage({
        id: `opt-msg-${Date.now()}`,
        sender: 'user',
        type: 'reply',
        content: text,
        created_at: new Date().toISOString(),
      });
      addMessage({
        id: `sys-${Date.now()}`,
        sender: 'system',
        type: 'system',
        content: t('analysis.relaunching'),
        created_at: new Date().toISOString(),
      });
      setStatus('starting');
      try {
        const res = await analysisApi.sendMessage(slug, text);
        setTaskId(res.task_id);
        setStatus('running');
      } catch {
        setStatus('failed');
      }
    }
  }, [slug, pendingQuestion, t]);

  const isActive = status === 'running' || status === 'starting';
  const inputDisabled = status === 'completed' || status === 'failed' || status === 'idle' || status === 'starting';

  return (
    <div className={`flex flex-col max-w-2xl h-[500px] ${className}`}>
      <h3 className="text-sm font-semibold text-content-primary mb-2">{t('analysis.title')}</h3>

      {status === 'idle' && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3">
          <p className="text-sm text-content-tertiary">{t('analysis.conversation_empty')}</p>
          <Button onClick={() => void handleStart()}>{t('analysis.start')}</Button>
        </div>
      )}

      {status !== 'idle' && (
        <>
          <div className="flex-1 overflow-y-auto flex flex-col gap-2 rounded-lg border border-border bg-surface-primary p-4">
            {messages.map((msg) => (
              <AnalysisChatMessage key={msg.id} message={msg} />
            ))}
            {isActive && <ChatTypingIndicator agentName="Orchestrateur" />}
            <div ref={bottomRef} />
          </div>

          {pendingQuestion && <AnalysisQuestionBanner />}

          {!inputDisabled && (
            <ChatInput
              onSend={(text) => void handleSend(text)}
              placeholder={pendingQuestion ? t('analysis.reply_placeholder') : t('analysis.message_placeholder')}
            />
          )}

          {(status === 'completed' || status === 'failed') && (
            <div className="flex items-center justify-between px-3 py-2">
              <p className="text-xs text-content-tertiary">
                {status === 'completed' ? t('analysis.result_success') : t('analysis.result_failure')}
              </p>
              {status === 'failed' && (
                <Button size="sm" variant="ghost" onClick={() => void handleStart()}>
                  {t('analysis.relaunch')}
                </Button>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Delete AnalysisChat.tsx**

```bash
rm hitl-frontend/src/components/features/project/AnalysisChat.tsx
```

- [ ] **Step 3: Verify build**

```bash
cd hitl-frontend && npm run build
```

- [ ] **Step 4: Commit**

```
feat(wizard): rewrite WizardStepAnalysis as interactive chat with WS + polling
```

---

## Task 12: i18n — Add analysis keys

**Files:**
- Modify: `hitl-frontend/public/locales/fr/translation.json`
- Modify: `hitl-frontend/public/locales/en/translation.json`

- [ ] **Step 1: Replace the `"analysis"` block in fr/translation.json**

Replace existing `"analysis": { ... }` block with the full set from the spec (19 keys).

- [ ] **Step 2: Add equivalent `"analysis"` block in en/translation.json**

- [ ] **Step 3: Commit**

```
feat(i18n): add analysis chat keys for fr and en
```

---

## Task 13: Final build + verification

- [ ] **Step 1: Build frontend**

```bash
cd hitl-frontend && npm run build
```

Expected: exit 0, no TypeScript errors.

- [ ] **Step 2: Run backend tests**

```bash
cd hitl && python -m pytest tests/test_analysis_service.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Deploy**

```bash
bash deploy.sh AGT1
```

- [ ] **Step 4: Manual verification**

1. Open project wizard, reach step 6
2. Click "Lancer l'analyse"
3. Verify messages appear in real-time
4. If agent asks a question — verify it shows with orange border + "Question" badge
5. Reply to the question — verify it's sent and agent continues
6. Send a free message — verify agent relaunches
7. Refresh page — verify conversation is restored
