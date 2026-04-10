# Docker Logs Streaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Logs" page to the HITL console that streams Docker container logs (HITL + API) in real-time via SSE.

**Architecture:** New SSE endpoint in HITL backend runs `docker logs -f` via async subprocess and streams lines as Server-Sent Events. New React page with terminal-style log viewer, container selector, and pause/clear controls.

**Tech Stack:** FastAPI SSE (StreamingResponse), asyncio.subprocess, React EventSource API, Tailwind CSS

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `hitl/routes/logs.py` | SSE streaming endpoint + static logs fallback |
| Modify | `hitl/main.py:237-283` | Register logs router |
| Create | `hitl-frontend/src/pages/LogsPage.tsx` | Logs page (container selector + LogViewer) |
| Create | `hitl-frontend/src/components/features/logs/LogViewer.tsx` | Terminal-style SSE log viewer component |
| Create | `hitl-frontend/src/api/logs.ts` | API helper (token URL builder for SSE) |
| Modify | `hitl-frontend/src/router.tsx` | Add `/logs` route |
| Modify | `hitl-frontend/src/components/layout/Sidebar.tsx` | Add "Logs" menu item |
| Modify | `hitl-frontend/public/locales/fr/translation.json` | French i18n keys |
| Modify | `hitl-frontend/public/locales/en/translation.json` | English i18n keys |

---

### Task 1: Backend — SSE log streaming endpoint

**Files:**
- Create: `hitl/routes/logs.py`
- Modify: `hitl/main.py`

- [ ] **Step 1: Create `hitl/routes/logs.py`**

```python
"""Docker log streaming routes."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from core.security import TokenData, get_current_user

log = structlog.get_logger(__name__)

router = APIRouter(tags=["logs"])

ALLOWED_CONTAINERS = {
    "langgraph-hitl",
    "langgraph-api",
    "langgraph-admin",
    "langgraph-dispatcher",
    "langgraph-discord",
    "langgraph-mail",
}


@router.get("/api/logs/stream")
async def stream_logs(
    container: str = Query("langgraph-api"),
    tail: int = Query(200, ge=10, le=5000),
    user: TokenData = Depends(get_current_user),
):
    """Stream Docker container logs via SSE. Admin only."""
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    if container not in ALLOWED_CONTAINERS:
        raise HTTPException(400, f"Container not allowed: {container}")

    log.info("logs_stream_start", container=container, tail=tail, user=user.email)

    async def event_stream():
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "logs", "--follow", "--timestamps", "--tail", str(tail), container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                yield f"data: {text}\n\n"
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            yield f"event: error\ndata: {exc}\n\n"
        finally:
            if proc and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
            log.info("logs_stream_end", container=container)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/logs/containers")
async def list_containers(
    user: TokenData = Depends(get_current_user),
):
    """List allowed containers for log streaming."""
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return sorted(ALLOWED_CONTAINERS)
```

- [ ] **Step 2: Register router in `hitl/main.py`**

After line 259 (`from routes.project_detail import router as project_detail_router`), add:

```python
from routes.logs import router as logs_router
```

After line 283 (`app.include_router(project_detail_router)`), add:

```python
app.include_router(logs_router)
```

- [ ] **Step 3: Commit**

```bash
git add hitl/routes/logs.py hitl/main.py
git commit -m "feat(hitl): endpoint SSE streaming logs Docker"
```

---

### Task 2: Frontend — API helper + i18n keys

**Files:**
- Create: `hitl-frontend/src/api/logs.ts`
- Modify: `hitl-frontend/public/locales/fr/translation.json`
- Modify: `hitl-frontend/public/locales/en/translation.json`

- [ ] **Step 1: Create `hitl-frontend/src/api/logs.ts`**

```typescript
import { getToken } from './client';

/**
 * Build the SSE URL for log streaming (token passed as query param
 * because EventSource doesn't support custom headers).
 */
export function buildStreamUrl(container: string, tail: number = 200): string {
  const token = getToken();
  const params = new URLSearchParams({
    container,
    tail: String(tail),
    token: token ?? '',
  });
  return `/api/logs/stream?${params}`;
}

export async function listContainers(): Promise<string[]> {
  const { apiFetch } = await import('./client');
  return apiFetch<string[]>('/api/logs/containers');
}
```

> **Note:** SSE via `EventSource` cannot send Authorization headers. The token is passed as a query param. The backend endpoint must accept `token` as a query param fallback. Update `hitl/routes/logs.py` accordingly (see Step 2).

- [ ] **Step 2: Update backend to accept token query param**

In `hitl/routes/logs.py`, update the `stream_logs` function signature to also accept a `token` query param and resolve the user from it when the header is absent:

Add to `hitl/routes/logs.py` at the top, after existing imports:

```python
from core.security import get_current_user, get_user_from_token
```

Update the `stream_logs` signature:

```python
from fastapi import Request

@router.get("/api/logs/stream")
async def stream_logs(
    request: Request,
    container: str = Query("langgraph-api"),
    tail: int = Query(200, ge=10, le=5000),
    token: str = Query(""),
):
    """Stream Docker container logs via SSE. Admin only."""
    # SSE EventSource can't send headers — accept token as query param
    try:
        user = await get_current_user(request)
    except Exception:
        if not token:
            raise HTTPException(401, "Authentication required")
        user = get_user_from_token(token)

    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    if container not in ALLOWED_CONTAINERS:
        raise HTTPException(400, f"Container not allowed: {container}")
    # ... rest unchanged
```

Check if `get_user_from_token` exists in `core/security.py`. If not, it needs to be added — it's the function that decodes a JWT string into a `TokenData` without going through FastAPI's `Depends`. Read `core/security.py` to find the existing decode logic and expose it as a standalone function.

- [ ] **Step 3: Add i18n keys to French translation**

In `hitl-frontend/public/locales/fr/translation.json`, inside the `"nav"` object, add:

```json
"logs": "Logs"
```

Add a new `"logs"` section at the top level:

```json
"logs": {
  "title": "Logs Docker",
  "container": "Container",
  "lines": "Lignes initiales",
  "pause": "Pause",
  "resume": "Reprendre",
  "clear": "Effacer",
  "connected": "Connecte",
  "disconnected": "Deconnecte",
  "reconnecting": "Reconnexion..."
}
```

- [ ] **Step 4: Add i18n keys to English translation**

Same structure in `hitl-frontend/public/locales/en/translation.json`:

Nav: `"logs": "Logs"`

```json
"logs": {
  "title": "Docker Logs",
  "container": "Container",
  "lines": "Initial lines",
  "pause": "Pause",
  "resume": "Resume",
  "clear": "Clear",
  "connected": "Connected",
  "disconnected": "Disconnected",
  "reconnecting": "Reconnecting..."
}
```

- [ ] **Step 5: Commit**

```bash
git add hitl-frontend/src/api/logs.ts hitl-frontend/public/locales/fr/translation.json hitl-frontend/public/locales/en/translation.json hitl/routes/logs.py
git commit -m "feat(hitl): API logs helper + i18n + token query param SSE"
```

---

### Task 3: Frontend — LogViewer component

**Files:**
- Create: `hitl-frontend/src/components/features/logs/LogViewer.tsx`

- [ ] **Step 1: Create the LogViewer component**

Terminal-style component that connects to SSE and renders log lines with auto-scroll.

```tsx
import { useEffect, useRef, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { buildStreamUrl } from '../../../api/logs';

interface LogViewerProps {
  container: string;
  tail: number;
}

export function LogViewer({ container, tail }: LogViewerProps): JSX.Element {
  const { t } = useTranslation();
  const [lines, setLines] = useState<string[]>([]);
  const [paused, setPaused] = useState(false);
  const [status, setStatus] = useState<'connected' | 'disconnected' | 'reconnecting'>('disconnected');
  const bottomRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);
  const pausedRef = useRef(paused);

  // Keep ref in sync for the EventSource callback
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  // Auto-scroll when new lines arrive (only if not paused)
  useEffect(() => {
    if (!paused && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [lines, paused]);

  // Connect / reconnect SSE
  useEffect(() => {
    const url = buildStreamUrl(container, tail);
    setLines([]);
    setStatus('reconnecting');

    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => setStatus('connected');

    es.onmessage = (ev) => {
      if (!pausedRef.current) {
        setLines((prev) => {
          const next = [...prev, ev.data];
          // Cap at 5000 lines to prevent memory issues
          return next.length > 5000 ? next.slice(-5000) : next;
        });
      }
    };

    es.onerror = () => {
      setStatus('disconnected');
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [container, tail]);

  const handleClear = useCallback(() => setLines([]), []);

  const statusColor = {
    connected: 'bg-green-500',
    disconnected: 'bg-red-500',
    reconnecting: 'bg-yellow-500',
  }[status];

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-surface-secondary border-b border-border">
        <span className={`h-2 w-2 rounded-full ${statusColor}`} />
        <span className="text-xs text-content-tertiary">{t(`logs.${status}`)}</span>
        <div className="flex-1" />
        <button
          onClick={() => setPaused((p) => !p)}
          className="px-3 py-1 text-xs rounded bg-surface-tertiary hover:bg-surface-hover text-content-secondary"
        >
          {paused ? t('logs.resume') : t('logs.pause')}
        </button>
        <button
          onClick={handleClear}
          className="px-3 py-1 text-xs rounded bg-surface-tertiary hover:bg-surface-hover text-content-secondary"
        >
          {t('logs.clear')}
        </button>
      </div>

      {/* Log output */}
      <div className="flex-1 overflow-y-auto bg-black px-4 py-2 font-mono text-xs leading-5 text-green-400">
        {lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-all">
            {line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/components/features/logs/LogViewer.tsx
git commit -m "feat(hitl): composant LogViewer terminal SSE"
```

---

### Task 4: Frontend — LogsPage + routing + sidebar

**Files:**
- Create: `hitl-frontend/src/pages/LogsPage.tsx`
- Modify: `hitl-frontend/src/router.tsx`
- Modify: `hitl-frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Create `hitl-frontend/src/pages/LogsPage.tsx`**

```tsx
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageContainer } from '../components/layout/PageContainer';
import { LogViewer } from '../components/features/logs/LogViewer';
import * as logsApi from '../api/logs';

const DEFAULT_TAIL = 200;
const TAIL_OPTIONS = [100, 200, 500, 1000, 2000];

export function LogsPage(): JSX.Element {
  const { t } = useTranslation();
  const [containers, setContainers] = useState<string[]>([]);
  const [selected, setSelected] = useState('langgraph-api');
  const [tail, setTail] = useState(DEFAULT_TAIL);

  useEffect(() => {
    logsApi.listContainers().then((list) => {
      setContainers(list);
      if (list.length > 0 && !list.includes(selected)) {
        setSelected(list[0]);
      }
    }).catch(() => {
      // Fallback if endpoint not ready
      setContainers(['langgraph-api', 'langgraph-hitl']);
    });
  }, []);

  return (
    <PageContainer className="flex flex-col h-[calc(100vh-3.5rem)]">
      <div className="flex items-center gap-4 mb-4">
        <h2 className="text-xl font-semibold">{t('logs.title')}</h2>
        <div className="flex items-center gap-2 ml-auto">
          <label className="text-xs text-content-tertiary">{t('logs.container')}</label>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="rounded bg-surface-tertiary border border-border px-2 py-1 text-sm text-content-primary"
          >
            {containers.map((c) => (
              <option key={c} value={c}>{c.replace('langgraph-', '')}</option>
            ))}
          </select>
          <label className="text-xs text-content-tertiary ml-2">{t('logs.lines')}</label>
          <select
            value={tail}
            onChange={(e) => setTail(Number(e.target.value))}
            className="rounded bg-surface-tertiary border border-border px-2 py-1 text-sm text-content-primary"
          >
            {TAIL_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="flex-1 rounded-lg border border-border overflow-hidden">
        <LogViewer container={selected} tail={tail} />
      </div>
    </PageContainer>
  );
}
```

- [ ] **Step 2: Add route in `hitl-frontend/src/router.tsx`**

Add import at the top:

```typescript
import { LogsPage } from './pages/LogsPage';
```

Add route inside the children array, after the `pulse` route:

```typescript
{ path: 'logs', element: <LogsPage /> },
```

- [ ] **Step 3: Add Logs item in Sidebar**

In `hitl-frontend/src/components/layout/Sidebar.tsx`, add a new `SidebarItem` after the Pulse item (after the closing `/>` of the Pulse SidebarItem, around line 118):

```tsx
<SidebarItem
  icon={
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
    </svg>
  }
  labelKey="nav.logs"
  to="/logs"
  active={location.pathname === '/logs'}
/>
```

This uses a terminal/command-line icon (consistent with the design).

- [ ] **Step 4: Commit**

```bash
git add hitl-frontend/src/pages/LogsPage.tsx hitl-frontend/src/router.tsx hitl-frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(hitl): page Logs avec routing et menu sidebar"
```

---

### Task 5: Build + deploy verification

- [ ] **Step 1: Build the frontend**

```bash
cd hitl-frontend && npm run build
```

Expected: Build succeeds, output in `hitl/static/`

- [ ] **Step 2: Copy built assets to hitl/static if not automatic**

Check if the Vite config outputs to `../hitl/static/`. If not, copy manually.

- [ ] **Step 3: Test locally or deploy to AGT1**

```bash
bash deploy.sh AGT1
```

Then SSH and restart:

```bash
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose up -d --build hitl-console"
```

- [ ] **Step 4: Verify in browser**

1. Navigate to `http://<AGT1_IP>:8090/logs`
2. Check that the Logs menu item appears in sidebar
3. Select a container from the dropdown
4. Verify log lines stream in real-time
5. Test pause/resume and clear buttons
6. Verify admin-only access (non-admin should get 403)

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(hitl): build frontend avec page Logs Docker streaming"
```

---

## Key Implementation Notes

- **SSE auth**: `EventSource` cannot set custom headers. Token is passed as `?token=` query param. Backend falls back to query token when no Authorization header is present.
- **Process cleanup**: The async subprocess (`docker logs -f`) is terminated when the client disconnects (SSE close triggers `CancelledError` → `finally` block kills the process).
- **Memory cap**: LogViewer caps at 5000 lines in the browser to prevent memory issues.
- **Admin only**: Both endpoints check `user.role == "admin"`. Non-admins get 403.
- **Container whitelist**: Only containers in `ALLOWED_CONTAINERS` can be streamed — prevents arbitrary command injection.
