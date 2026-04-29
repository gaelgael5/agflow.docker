# Sessions UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter au panneau admin trois pages pour visualiser le hub sessions→agents→messages (`/sessions`, `/sessions/:id`, `/sessions/:id/agents/:instanceId`) avec un design de timeline verticale à bullets indigo/pulsations.

**Architecture :** Pages read‑only côté admin. Le backend expose 4 routes admin (`/api/admin/sessions*`) qui appellent les services existants `sessions_service` + `agents_instances_service` + MOM messages. Côté frontend : un client `sessionsApi.ts` + une famille de composants timeline (`TimelineRail`, `TimelineBullet`, `TimelineRow`) réutilisés par les 3 pages. TanStack Query pour le data fetching (pattern `ProjectDetailPage`). Les messages sont tirés via polling (WebSocket temps réel = V2).

**Tech Stack :** FastAPI + asyncpg (services déjà en place) / React 18 + TypeScript strict + TanStack Query + react-router v6 + Tailwind + shadcn/ui + i18next + Vitest.

**Design de référence :** direction visuelle validée 2026-04-23, previews dans `.superpowers/brainstorm/1715-1776957819/content/v4-session-detail-et-projet.preview.html` et `v5-vues-mixtes.preview.html`. Couleur bullets/rail = `hsl(var(--primary))` (indigo agflow). Pas de cyan.

**Scope exclu (V2)** :
- Création / suppression / extension de sessions depuis l'UI admin (mutations) — V1 visualisation pure
- WebSocket streaming live — polling 5s pour les pages actives, pas de WS
- Page projet `/projects/:id` — l'onglet "sessions" dans cette page est V2 (les groupes projet sont déjà visibles dans `/sessions`)

---

## File structure

### Backend — nouveaux fichiers

| Fichier | Responsabilité |
|---|---|
| `backend/src/agflow/api/admin/sessions.py` | Router admin avec 4 GET (list, detail, agents, messages) |
| `backend/src/agflow/schemas/admin_sessions.py` | DTO `AdminSessionListItem` (= `SessionOut` + `agent_count`) |
| `backend/tests/admin/test_admin_sessions_api.py` | Tests endpoints admin |

### Backend — fichiers modifiés

| Fichier | Modification |
|---|---|
| `backend/src/agflow/main.py` | Import + `app.include_router(admin_sessions_router)` |
| `backend/src/agflow/services/sessions_service.py` | Ajouter `list_all_with_counts()` qui joint `agent_instances` |

### Frontend — nouveaux fichiers

| Fichier | Responsabilité |
|---|---|
| `frontend/src/lib/sessionsApi.ts` | Client typé (list / get / listAgents / listMessages) |
| `frontend/src/components/timeline/TimelineRail.tsx` | Rail vertical + CSS `--bullet-size` paramétrable |
| `frontend/src/components/timeline/TimelineBullet.tsx` | Pastille (variants : default, selected, live, muted) |
| `frontend/src/components/timeline/TimelineRow.tsx` | Ligne 3-colonnes (date\|bullet\|card), wrapper cliquable |
| `frontend/src/pages/SessionsPage.tsx` | Vue 1 v5 : flat + groupes projet |
| `frontend/src/pages/SessionDetailPage.tsx` | Page 2a/2b v4 : timeline des agents de la session |
| `frontend/src/pages/SessionAgentTimelinePage.tsx` | Page 3 v4 : timeline messages MOM d'un agent |
| `frontend/tests/pages/SessionsPage.test.tsx` | Tests liste |
| `frontend/tests/pages/SessionDetailPage.test.tsx` | Tests détail session |
| `frontend/tests/pages/SessionAgentTimelinePage.test.tsx` | Tests timeline agent |
| `frontend/tests/components/TimelineBullet.test.tsx` | Tests variantes visuelles |

### Frontend — fichiers modifiés

| Fichier | Modification |
|---|---|
| `frontend/src/App.tsx` | Imports + 3 nouvelles `<Route>` avec `ProtectedRoute` |
| `frontend/src/components/layout/Sidebar.tsx` | Entrée `{ to: "/sessions", icon: Activity, label: t("sessions.page_title") }` dans `section_orchestration` (avant `/agents`) |
| `frontend/src/i18n/fr.json` | Bloc `"sessions": { … }` |
| `frontend/src/i18n/en.json` | Même bloc en anglais |

---

## Task 1 — Backend : service `list_all_with_counts()`

**Files:**
- Modify: `backend/src/agflow/services/sessions_service.py` (ajouter fonction en bas)
- Test: `backend/tests/test_sessions_service.py` (créer si absent)

- [ ] **Step 1.1 : Écrire le test qui échoue**

```python
# backend/tests/test_sessions_service.py
from __future__ import annotations

import pytest

from agflow.services import sessions_service

pytestmark = pytest.mark.asyncio


async def test_list_all_with_counts_returns_agent_count(db_conn, seeded_api_key):
    sess = await sessions_service.create(
        api_key_id=seeded_api_key["id"],
        name="t1", duration_seconds=3600, project_id="proj-a",
    )
    # Insertion directe d'un agent_instance pour éviter d'appeler tout le flow
    await db_conn.execute(
        """
        INSERT INTO agent_instances (session_id, agent_id, labels, mission)
        VALUES ($1, 'claude-code', '{}'::jsonb, 'mission test')
        """,
        sess["id"],
    )

    rows = await sessions_service.list_all_with_counts()
    row = next(r for r in rows if r["id"] == sess["id"])
    assert row["agent_count"] == 1
    assert row["project_id"] == "proj-a"
```

- [ ] **Step 1.2 : Lancer le test, vérifier qu'il échoue**

```
cd backend && uv run pytest tests/test_sessions_service.py::test_list_all_with_counts_returns_agent_count -v
```

Attendu : FAIL (`AttributeError: module 'sessions_service' has no attribute 'list_all_with_counts'`).

- [ ] **Step 1.3 : Écrire l'implémentation minimale**

Ajouter en bas de `backend/src/agflow/services/sessions_service.py` :

```python
async def list_all_with_counts() -> list[dict]:
    """Admin-scoped list : toutes les sessions + count des agent_instances.

    Renvoie tous les champs de `_COLS` enrichis de `agent_count` (int).
    Tri : `created_at DESC`.
    """
    rows = await fetch_all(
        f"""
        SELECT
            s.id, s.api_key_id, s.name, s.status, s.project_id,
            s.created_at, s.expires_at, s.closed_at,
            COUNT(ai.id) FILTER (WHERE ai.destroyed_at IS NULL) AS agent_count
        FROM sessions s
        LEFT JOIN agent_instances ai ON ai.session_id = s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        """,
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 1.4 : Lancer le test, vérifier qu'il passe**

```
cd backend && uv run pytest tests/test_sessions_service.py::test_list_all_with_counts_returns_agent_count -v
```

Attendu : PASS.

- [ ] **Step 1.5 : Commit**

```bash
git add backend/src/agflow/services/sessions_service.py backend/tests/test_sessions_service.py
git commit -m "feat(sessions): service list_all_with_counts pour l'admin"
```

---

## Task 2 — Backend : DTO `AdminSessionListItem`

**Files:**
- Create: `backend/src/agflow/schemas/admin_sessions.py`

- [ ] **Step 2.1 : Créer le fichier de schéma**

```python
# backend/src/agflow/schemas/admin_sessions.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AdminSessionListItem(BaseModel):
    id: UUID
    name: str | None
    status: str
    project_id: str | None
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    api_key_id: UUID
    agent_count: int
```

- [ ] **Step 2.2 : Commit**

```bash
git add backend/src/agflow/schemas/admin_sessions.py
git commit -m "feat(sessions): DTO AdminSessionListItem"
```

---

## Task 3 — Backend : router admin `/api/admin/sessions`

**Files:**
- Create: `backend/src/agflow/api/admin/sessions.py`
- Test: `backend/tests/admin/test_admin_sessions_api.py`

- [ ] **Step 3.1 : Écrire les tests qui échouent**

```python
# backend/tests/admin/test_admin_sessions_api.py
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_admin_list_sessions_returns_agent_count(admin_client, seeded_session_with_agent):
    res = await admin_client.get("/api/admin/sessions")
    assert res.status_code == 200
    body = res.json()
    found = next(s for s in body if s["id"] == str(seeded_session_with_agent["id"]))
    assert found["agent_count"] >= 1
    assert "api_key_id" in found
    assert "project_id" in found


async def test_admin_get_session_detail(admin_client, seeded_session_with_agent):
    sid = seeded_session_with_agent["id"]
    res = await admin_client.get(f"/api/admin/sessions/{sid}")
    assert res.status_code == 200
    assert res.json()["id"] == str(sid)


async def test_admin_get_session_404(admin_client):
    import uuid
    res = await admin_client.get(f"/api/admin/sessions/{uuid.uuid4()}")
    assert res.status_code == 404


async def test_admin_list_session_agents(admin_client, seeded_session_with_agent):
    sid = seeded_session_with_agent["id"]
    res = await admin_client.get(f"/api/admin/sessions/{sid}/agents")
    assert res.status_code == 200
    assert len(res.json()) >= 1
    assert "agent_id" in res.json()[0]
    assert "mission" in res.json()[0]


async def test_admin_list_agent_messages(admin_client, seeded_session_with_agent_and_msgs):
    sid = seeded_session_with_agent_and_msgs["session_id"]
    inst = seeded_session_with_agent_and_msgs["instance_id"]
    res = await admin_client.get(
        f"/api/admin/sessions/{sid}/agents/{inst}/messages?limit=50"
    )
    assert res.status_code == 200
    msgs = res.json()
    assert len(msgs) >= 1
    assert msgs[0]["direction"] in ("in", "out")
    assert "kind" in msgs[0]
    assert "payload" in msgs[0]
```

**Fixtures à ajouter dans `backend/tests/conftest.py`** (si absentes) :
- `admin_client` : AsyncClient qui injecte un header `Authorization: Bearer <admin_jwt>` valide.
- `seeded_session_with_agent` : crée session + 1 agent_instance, yield le dict.
- `seeded_session_with_agent_and_msgs` : en plus, insère 2 messages via le MOM ou directement dans `mom_messages`.

Vérifier la convention existante — d'autres tests `backend/tests/admin/` peuvent déjà avoir `admin_client`.

- [ ] **Step 3.2 : Lancer les tests, vérifier qu'ils échouent**

```
cd backend && uv run pytest tests/admin/test_admin_sessions_api.py -v
```

Attendu : tous FAIL (404 sur `/api/admin/sessions*`).

- [ ] **Step 3.3 : Écrire l'implémentation du router**

```python
# backend/src/agflow/api/admin/sessions.py
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.admin_sessions import AdminSessionListItem
from agflow.schemas.sessions import AgentInstanceOut, SessionOut
from agflow.services import (
    agents_instances_service,
    mom_messages_service,
    sessions_service,
)

router = APIRouter(prefix="/api/admin/sessions", tags=["admin/sessions"])


@router.get("", response_model=list[AdminSessionListItem])
async def admin_list_sessions(
    _admin: dict = Depends(require_admin),  # noqa: B008
    project_id: str | None = Query(default=None),
) -> list[AdminSessionListItem]:
    rows = await sessions_service.list_all_with_counts()
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    return [AdminSessionListItem(**r) for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def admin_get_session(
    session_id: UUID,
    _admin: dict = Depends(require_admin),  # noqa: B008
) -> SessionOut:
    # api_key_id ignoré parce qu'admin, on passe un UUID zero
    row = await sessions_service.get(
        session_id=session_id, api_key_id=UUID(int=0), is_admin=True,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionOut(**row)


@router.get("/{session_id}/agents", response_model=list[AgentInstanceOut])
async def admin_list_agents(
    session_id: UUID,
    _admin: dict = Depends(require_admin),  # noqa: B008
) -> list[AgentInstanceOut]:
    rows = await agents_instances_service.list_by_session(session_id=session_id)
    return [AgentInstanceOut(**r) for r in rows]


@router.get("/{session_id}/agents/{instance_id}/messages")
async def admin_list_agent_messages(
    session_id: UUID,
    instance_id: UUID,
    _admin: dict = Depends(require_admin),  # noqa: B008
    kind: str | None = Query(default=None),
    direction: str | None = Query(default=None, regex="^(in|out)$"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    # même helper que l'API v1 (même table mom_messages)
    rows = await mom_messages_service.list_for_instance(
        session_id=session_id, instance_id=instance_id,
        kind=kind, direction=direction, limit=limit,
    )
    return rows
```

**Vérifier avant :** existence de `agents_instances_service.list_by_session()` et `mom_messages_service.list_for_instance()`. Si noms différents, adapter (`grep -rn "list_by_session\|list_for_instance" backend/src/agflow/services/`). Si absents, importer les fonctions déjà utilisées par `api/public/sessions.py` et `api/public/messages.py` — elles existent forcément car ces endpoints publics fonctionnent.

- [ ] **Step 3.4 : Enregistrer le router dans main.py**

Dans `backend/src/agflow/main.py` :
- Ajouter l'import, par ordre alphabétique dans le bloc `from agflow.api.admin.*` :
  ```python
  from agflow.api.admin.sessions import router as admin_sessions_router
  ```
- Dans le bloc `app.include_router(...)` (chercher `app.include_router(admin_scripts_router)` comme ancre), ajouter juste après :
  ```python
  app.include_router(admin_sessions_router)
  ```

- [ ] **Step 3.5 : Lancer les tests, vérifier qu'ils passent**

```
cd backend && uv run pytest tests/admin/test_admin_sessions_api.py -v
```

Attendu : tous PASS. Si échec sur fixtures `seeded_session_with_agent*`, créer/ajuster les fixtures dans `conftest.py`.

- [ ] **Step 3.6 : Lint + format**

```
cd backend && uv run ruff check src/ tests/ && uv run ruff format src/ tests/
```

Attendu : 0 erreur.

- [ ] **Step 3.7 : Commit**

```bash
git add backend/src/agflow/api/admin/sessions.py backend/src/agflow/main.py backend/tests/admin/test_admin_sessions_api.py backend/tests/conftest.py
git commit -m "feat(sessions): endpoints admin /api/admin/sessions* (list, detail, agents, messages)"
```

---

## Task 4 — Frontend : `sessionsApi.ts`

**Files:**
- Create: `frontend/src/lib/sessionsApi.ts`

- [ ] **Step 4.1 : Écrire le client**

```typescript
// frontend/src/lib/sessionsApi.ts
import { api } from "./api";

export interface SessionListItem {
  id: string;
  name: string | null;
  status: "active" | "closed" | "expired";
  project_id: string | null;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
  api_key_id: string;
  agent_count: number;
}

export interface SessionDetail {
  id: string;
  name: string | null;
  status: "active" | "closed" | "expired";
  project_id: string | null;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
  api_key_id: string;
}

export interface AgentInstance {
  id: string;
  session_id: string;
  agent_id: string;
  labels: Record<string, unknown>;
  mission: string | null;
  status: "busy" | "idle";
  created_at: string;
}

export type MessageKind = "llm_call" | "tool_call" | "mcp_call" | "file_change" | "error" | string;
export type MessageDirection = "in" | "out";

export interface MomMessage {
  msg_id: string;
  parent_msg_id: string | null;
  direction: MessageDirection;
  kind: MessageKind;
  payload: Record<string, unknown>;
  source: string | null;
  created_at: string;
  route: string | null;
}

export const sessionsApi = {
  async list(projectId?: string): Promise<SessionListItem[]> {
    const params = projectId ? { project_id: projectId } : undefined;
    return (await api.get<SessionListItem[]>("/admin/sessions", { params })).data;
  },
  async get(id: string): Promise<SessionDetail> {
    return (await api.get<SessionDetail>(`/admin/sessions/${id}`)).data;
  },
  async listAgents(sessionId: string): Promise<AgentInstance[]> {
    return (await api.get<AgentInstance[]>(`/admin/sessions/${sessionId}/agents`)).data;
  },
  async listMessages(
    sessionId: string,
    instanceId: string,
    opts?: { kind?: string; direction?: MessageDirection; limit?: number },
  ): Promise<MomMessage[]> {
    return (
      await api.get<MomMessage[]>(
        `/admin/sessions/${sessionId}/agents/${instanceId}/messages`,
        { params: opts },
      )
    ).data;
  },
};
```

- [ ] **Step 4.2 : Type-check**

```
cd frontend && npx tsc --noEmit
```

Attendu : 0 erreur sur `sessionsApi.ts`.

- [ ] **Step 4.3 : Commit**

```bash
git add frontend/src/lib/sessionsApi.ts
git commit -m "feat(sessions): client typé sessionsApi (4 endpoints)"
```

---

## Task 5 — Frontend : composants timeline

**Files:**
- Create: `frontend/src/components/timeline/TimelineRail.tsx`
- Create: `frontend/src/components/timeline/TimelineBullet.tsx`
- Create: `frontend/src/components/timeline/TimelineRow.tsx`
- Test: `frontend/tests/components/TimelineBullet.test.tsx`

- [ ] **Step 5.1 : Écrire le test bullet**

```typescript
// frontend/tests/components/TimelineBullet.test.tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { TimelineBullet } from "@/components/timeline/TimelineBullet";

describe("TimelineBullet", () => {
  it("rend un bullet par défaut", () => {
    const { container } = render(<TimelineBullet />);
    const bullet = container.querySelector("[data-timeline-bullet]");
    expect(bullet).toBeTruthy();
    expect(bullet).not.toHaveAttribute("data-variant", "selected");
    expect(bullet).not.toHaveAttribute("data-variant", "live");
  });

  it("applique la variante selected", () => {
    const { container } = render(<TimelineBullet variant="selected" />);
    expect(
      container.querySelector('[data-timeline-bullet][data-variant="selected"]'),
    ).toBeTruthy();
  });

  it("applique la variante live avec animation", () => {
    const { container } = render(<TimelineBullet variant="live" />);
    const bullet = container.querySelector(
      '[data-timeline-bullet][data-variant="live"]',
    );
    expect(bullet).toBeTruthy();
  });

  it("applique la variante muted", () => {
    const { container } = render(<TimelineBullet variant="muted" />);
    expect(
      container.querySelector('[data-timeline-bullet][data-variant="muted"]'),
    ).toBeTruthy();
  });
});
```

- [ ] **Step 5.2 : Lancer le test, vérifier qu'il échoue**

```
cd frontend && npm test -- TimelineBullet
```

Attendu : FAIL (module non trouvé).

- [ ] **Step 5.3 : Écrire `TimelineBullet.tsx`**

```typescript
// frontend/src/components/timeline/TimelineBullet.tsx
import { cn } from "@/lib/utils";

type Variant = "default" | "selected" | "live" | "muted";

interface Props {
  variant?: Variant;
  size?: number; // px, default 10
  className?: string;
}

export function TimelineBullet({ variant = "default", size = 10, className }: Props) {
  const effectiveSize = variant === "selected" ? size + 4 : size;
  return (
    <span
      data-timeline-bullet
      data-variant={variant}
      style={{ width: effectiveSize, height: effectiveSize }}
      className={cn(
        "relative inline-block rounded-full shrink-0 transition-all",
        // Default : couleur primary, glow léger, ring sur bg
        variant === "default" &&
          "bg-primary shadow-[0_0_0_3px_hsl(var(--background)),0_0_10px_hsl(var(--primary))]",
        // Selected : plus grand + contour solide
        variant === "selected" &&
          "bg-primary shadow-[0_0_0_3px_hsl(var(--background)),0_0_0_2px_hsl(var(--primary)),0_0_18px_hsl(var(--primary))]",
        // Live : pulse-dot + halo qui irradie via ::after (anneau)
        variant === "live" &&
          "bg-primary shadow-[0_0_0_3px_hsl(var(--background)),0_0_10px_hsl(var(--primary))] animate-pulse-dot before:content-[''] before:absolute before:top-1/2 before:left-1/2 before:w-full before:h-full before:border-2 before:border-primary before:rounded-full before:box-border before:animate-ring-expand before:pointer-events-none",
        // Muted : gris, sans glow
        variant === "muted" &&
          "bg-muted-foreground opacity-50 shadow-[0_0_0_3px_hsl(var(--background))]",
        className,
      )}
    />
  );
}
```

**Ajouter les keyframes Tailwind** dans `frontend/tailwind.config.js` (bloc `keyframes` + `animation`) :

```javascript
keyframes: {
  "accordion-down": { /* existing */ },
  "accordion-up":   { /* existing */ },
  "pulse-dot": {
    "0%, 100%": { transform: "scale(1)",   opacity: "1" },
    "50%":      { transform: "scale(1.3)", opacity: "0.85" },
  },
  "ring-expand": {
    "0%":   { transform: "translate(-50%, -50%) scale(0.8)", opacity: "0.65" },
    "100%": { transform: "translate(-50%, -50%) scale(3.2)", opacity: "0" },
  },
},
animation: {
  "accordion-down": "accordion-down 0.2s ease-out",
  "accordion-up":   "accordion-up 0.2s ease-out",
  "pulse-dot":      "pulse-dot 1.4s ease-in-out infinite",
  "ring-expand":    "ring-expand 1.6s ease-out infinite",
},
```

Vérifier que `cn` existe : `ls frontend/src/lib/utils.ts` (pattern shadcn). Si absent, créer avec `import { clsx, type ClassValue } from "clsx"; import { twMerge } from "tailwind-merge"; export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }` — mais il doit déjà exister.

- [ ] **Step 5.4 : Écrire `TimelineRail.tsx`**

```typescript
// frontend/src/components/timeline/TimelineRail.tsx
import { cn } from "@/lib/utils";

interface Props {
  variant?: "gradient" | "solid";
  className?: string;
}

export function TimelineRail({ variant = "gradient", className }: Props) {
  return (
    <div
      aria-hidden
      className={cn(
        "absolute top-8 bottom-8 left-1/2 -translate-x-px w-0.5 rounded-full",
        variant === "gradient" &&
          "bg-gradient-to-b from-primary/40 to-transparent",
        variant === "solid" && "bg-primary/40",
        className,
      )}
    />
  );
}
```

- [ ] **Step 5.5 : Écrire `TimelineRow.tsx`**

```typescript
// frontend/src/components/timeline/TimelineRow.tsx
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import { TimelineBullet } from "./TimelineBullet";

interface Props {
  leftContent: ReactNode;
  bulletVariant?: "default" | "selected" | "live" | "muted";
  rightContent: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function TimelineRow({
  leftContent, bulletVariant = "default", rightContent, onClick, className,
}: Props) {
  return (
    <div
      className={cn(
        "grid grid-cols-[1fr_36px_1fr] items-center mb-4",
        onClick && "cursor-pointer transition-transform hover:translate-x-0.5",
        className,
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="text-right pr-4 text-xs text-muted-foreground">
        {leftContent}
      </div>
      <div className="flex items-center justify-center relative z-[1]">
        <TimelineBullet variant={bulletVariant} />
      </div>
      <div className="pl-4">{rightContent}</div>
    </div>
  );
}
```

- [ ] **Step 5.6 : Lancer le test, vérifier qu'il passe**

```
cd frontend && npm test -- TimelineBullet
```

Attendu : PASS.

- [ ] **Step 5.7 : Type-check**

```
cd frontend && npx tsc --noEmit
```

Attendu : 0 erreur.

- [ ] **Step 5.8 : Commit**

```bash
git add frontend/src/components/timeline/ frontend/tests/components/TimelineBullet.test.tsx frontend/tailwind.config.js
git commit -m "feat(sessions): composants timeline (Rail, Bullet, Row) avec variantes"
```

---

## Task 6 — Frontend : i18n

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 6.1 : Ajouter le bloc FR**

Dans `frontend/src/i18n/fr.json`, insérer avant la dernière `}` fermante du JSON :

```json
  "sessions": {
    "page_title": "Sessions",
    "subtitle": "Sessions actives et agents rattachés",
    "search_placeholder": "Filtrer sessions ou projet…",
    "empty": "Aucune session pour le moment",
    "ad_hoc_label": "Ad hoc",
    "project_label": "Projet",
    "agents_count_one": "{{count}} agent",
    "agents_count_other": "{{count}} agents",
    "status_active": "active",
    "status_closed": "fermée",
    "status_expired": "expirée",
    "expires_in": "expire {{when}}",
    "session_detail": {
      "back_to_list": "← Sessions",
      "back_to_project": "← {{project}}",
      "no_agents": "Aucun agent dans cette session"
    },
    "agent_timeline": {
      "back_to_session": "← Session {{id}}",
      "no_messages": "Aucun message échangé",
      "filter_placeholder": "🔎 filtre…",
      "live_badge": "● Live",
      "direction_in": "◀ in",
      "direction_out": "▶ out"
    }
  },
```

- [ ] **Step 6.2 : Ajouter le bloc EN**

Dans `frontend/src/i18n/en.json`, insérer la clé `"sessions"` avec les traductions (même structure, valeurs traduites). Ex. :

```json
  "sessions": {
    "page_title": "Sessions",
    "subtitle": "Active sessions and attached agents",
    "search_placeholder": "Filter sessions or project…",
    "empty": "No sessions yet",
    "ad_hoc_label": "Ad hoc",
    "project_label": "Project",
    "agents_count_one": "{{count}} agent",
    "agents_count_other": "{{count}} agents",
    "status_active": "active",
    "status_closed": "closed",
    "status_expired": "expired",
    "expires_in": "expires {{when}}",
    "session_detail": {
      "back_to_list": "← Sessions",
      "back_to_project": "← {{project}}",
      "no_agents": "No agents in this session"
    },
    "agent_timeline": {
      "back_to_session": "← Session {{id}}",
      "no_messages": "No messages exchanged",
      "filter_placeholder": "🔎 filter…",
      "live_badge": "● Live",
      "direction_in": "◀ in",
      "direction_out": "▶ out"
    }
  },
```

- [ ] **Step 6.3 : Vérifier validité JSON**

```
cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json','utf8')); JSON.parse(require('fs').readFileSync('src/i18n/en.json','utf8')); console.log('OK')"
```

Attendu : `OK`.

- [ ] **Step 6.4 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "i18n(sessions): ajout des clés sessions.* (fr/en)"
```

---

## Task 7 — Frontend : `SessionsPage.tsx` (liste)

**Files:**
- Create: `frontend/src/pages/SessionsPage.tsx`
- Test: `frontend/tests/pages/SessionsPage.test.tsx`

- [ ] **Step 7.1 : Écrire le test**

```typescript
// frontend/tests/pages/SessionsPage.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionsPage } from "@/pages/SessionsPage";
import { sessionsApi } from "@/lib/sessionsApi";
import "@/lib/i18n";

vi.mock("@/lib/sessionsApi", () => ({
  sessionsApi: {
    list: vi.fn(),
    get: vi.fn(),
    listAgents: vi.fn(),
    listMessages: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SessionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("affiche les sessions ad hoc et les groupes projet", async () => {
    vi.mocked(sessionsApi.list).mockResolvedValueOnce([
      {
        id: "s1", name: "sess-1", status: "active",
        project_id: null, api_key_id: "k1",
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        closed_at: null, agent_count: 2,
      },
      {
        id: "s2", name: "sess-2", status: "active",
        project_id: "frontend-refactor", api_key_id: "k1",
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + 3600_000).toISOString(),
        closed_at: null, agent_count: 1,
      },
    ]);

    renderPage();
    await waitFor(() => expect(screen.getByText(/sess-1/)).toBeInTheDocument());
    expect(screen.getByText(/sess-2/)).toBeInTheDocument();
    expect(screen.getByText(/frontend-refactor/)).toBeInTheDocument();
  });

  it("affiche l'état vide quand aucune session", async () => {
    vi.mocked(sessionsApi.list).mockResolvedValueOnce([]);
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/aucune session/i)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 7.2 : Lancer le test, vérifier qu'il échoue**

```
cd frontend && npm test -- SessionsPage
```

Attendu : FAIL (module non trouvé).

- [ ] **Step 7.3 : Écrire la page**

```typescript
// frontend/src/pages/SessionsPage.tsx
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineBullet } from "@/components/timeline/TimelineBullet";
import { sessionsApi, type SessionListItem } from "@/lib/sessionsApi";
import { cn } from "@/lib/utils";

function bulletVariantFor(s: SessionListItem) {
  if (s.status !== "active") return "muted" as const;
  if (s.agent_count > 0) return "live" as const;
  return "default" as const;
}

export function SessionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("");

  const q = useQuery({
    queryKey: ["sessions", "list"],
    queryFn: () => sessionsApi.list(),
    refetchInterval: 5_000,
  });

  const grouped = useMemo(() => {
    const list = q.data ?? [];
    const fl = filter.trim().toLowerCase();
    const filtered = fl
      ? list.filter(
          (s) =>
            (s.name?.toLowerCase().includes(fl) ?? false) ||
            (s.project_id?.toLowerCase().includes(fl) ?? false) ||
            s.id.toLowerCase().includes(fl),
        )
      : list;
    const adHoc = filtered.filter((s) => !s.project_id);
    const byProject = new Map<string, SessionListItem[]>();
    for (const s of filtered) {
      if (!s.project_id) continue;
      const arr = byProject.get(s.project_id) ?? [];
      arr.push(s);
      byProject.set(s.project_id, arr);
    }
    return { adHoc, byProject };
  }, [q.data, filter]);

  return (
    <PageShell>
      <PageHeader
        title={t("sessions.page_title")}
        subtitle={t("sessions.subtitle")}
      />

      <div className="max-w-4xl mx-auto space-y-2">
        <Input
          placeholder={t("sessions.search_placeholder")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="max-w-sm"
        />

        {q.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-14 w-full rounded-md" />
            ))}
          </div>
        ) : q.data?.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("sessions.empty")}
          </p>
        ) : (
          <>
            {grouped.adHoc.map((s) => (
              <SessionRow key={s.id} session={s} onOpen={() => navigate(`/sessions/${s.id}`)} t={t} />
            ))}

            {[...grouped.byProject.entries()].map(([pid, items]) => (
              <div
                key={pid}
                className="border-l-2 border-dashed border-primary/30 bg-gradient-to-r from-primary/5 to-transparent rounded-r-lg px-4 py-2 my-3"
              >
                <div className="flex items-center gap-2 text-sm font-semibold text-primary mb-2">
                  <FolderKanban className="h-4 w-4" />
                  <span>{pid}</span>
                  <span className="text-muted-foreground font-normal text-xs">
                    · {items.length} sessions
                  </span>
                </div>
                {items.map((s) => (
                  <SessionRow
                    key={s.id}
                    session={s}
                    onOpen={() => navigate(`/sessions/${s.id}`)}
                    t={t}
                  />
                ))}
              </div>
            ))}
          </>
        )}
      </div>
    </PageShell>
  );
}

function SessionRow({
  session, onOpen, t,
}: {
  session: SessionListItem;
  onOpen: () => void;
  t: (k: string, opts?: Record<string, unknown>) => string;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onOpen()}
      className={cn(
        "grid grid-cols-[20px_2fr_1fr_1fr_1fr] gap-3 items-center",
        "rounded-md px-3 py-2 cursor-pointer transition-colors",
        "hover:bg-primary/5",
      )}
    >
      <TimelineBullet variant={bulletVariantFor(session)} />
      <div className="min-w-0">
        <div className="font-medium truncate">{session.name ?? session.id.slice(0, 12)}</div>
        <div className="text-xs text-muted-foreground truncate">
          {session.project_id ? t("sessions.project_label") : t("sessions.ad_hoc_label")}
          {" · "}
          <code className="font-mono">{session.id.slice(0, 8)}</code>
        </div>
      </div>
      <span className="text-sm">
        {session.agent_count === 1
          ? t("sessions.agents_count_one", { count: 1 })
          : t("sessions.agents_count_other", { count: session.agent_count })}
      </span>
      <Badge
        variant={session.status === "active" ? "default" : "secondary"}
        className="w-fit"
      >
        {t(`sessions.status_${session.status}`)}
      </Badge>
      <span className="text-xs text-muted-foreground">
        {new Date(session.created_at).toLocaleString()}
      </span>
    </div>
  );
}
```

**Vérifier avant :** existence de `PageShell`, `PageHeader`, `Input`, `Badge`, `Skeleton` :
```
ls frontend/src/components/layout/PageShell.tsx frontend/src/components/layout/PageHeader.tsx frontend/src/components/ui/{input,badge,skeleton}.tsx
```
Si certains manquent, regarder ce que `ProjectsPage.tsx` utilise pour son layout et aligner.

- [ ] **Step 7.4 : Lancer les tests, vérifier qu'ils passent**

```
cd frontend && npm test -- SessionsPage
```

Attendu : PASS.

- [ ] **Step 7.5 : Type-check + lint**

```
cd frontend && npx tsc --noEmit && npm run lint
```

Attendu : 0 erreur.

- [ ] **Step 7.6 : Commit**

```bash
git add frontend/src/pages/SessionsPage.tsx frontend/tests/pages/SessionsPage.test.tsx
git commit -m "feat(sessions): page /sessions (liste flat + groupes projet)"
```

---

## Task 8 — Frontend : `SessionDetailPage.tsx`

**Files:**
- Create: `frontend/src/pages/SessionDetailPage.tsx`
- Test: `frontend/tests/pages/SessionDetailPage.test.tsx`

- [ ] **Step 8.1 : Écrire le test**

```typescript
// frontend/tests/pages/SessionDetailPage.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionDetailPage } from "@/pages/SessionDetailPage";
import { sessionsApi } from "@/lib/sessionsApi";
import "@/lib/i18n";

vi.mock("@/lib/sessionsApi", () => ({
  sessionsApi: {
    list: vi.fn(),
    get: vi.fn(),
    listAgents: vi.fn(),
    listMessages: vi.fn(),
  },
}));

function renderAt(sessionId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/sessions/${sessionId}`]}>
        <Routes>
          <Route path="/sessions/:id" element={<SessionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionDetailPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("affiche les agents rattachés à la session", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "s1", name: "My session", status: "active",
      project_id: null, api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60 * 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([
      {
        id: "a1", session_id: "s1", agent_id: "claude-code",
        labels: {}, mission: "refactor auth", status: "busy",
        created_at: new Date().toISOString(),
      },
    ]);

    renderAt("s1");
    await waitFor(() => expect(screen.getByText("claude-code")).toBeInTheDocument());
    expect(screen.getByText(/refactor auth/)).toBeInTheDocument();
  });

  it("affiche état vide si aucun agent", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "s1", name: null, status: "active",
      project_id: null, api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([]);

    renderAt("s1");
    await waitFor(() =>
      expect(screen.getByText(/aucun agent/i)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 8.2 : Lancer le test, vérifier qu'il échoue**

```
cd frontend && npm test -- SessionDetailPage
```

Attendu : FAIL.

- [ ] **Step 8.3 : Écrire la page**

```typescript
// frontend/src/pages/SessionDetailPage.tsx
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import { TimelineRow } from "@/components/timeline/TimelineRow";
import { sessionsApi, type AgentInstance } from "@/lib/sessionsApi";
import { cn } from "@/lib/utils";

function bulletForAgent(a: AgentInstance) {
  // Les agents qui ne sont pas destroyed et non idle-deep sont considérés en traitement
  if (a.status === "busy") return "live" as const;
  return "default" as const;
}

export function SessionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const sQ = useQuery({
    queryKey: ["sessions", id],
    queryFn: () => sessionsApi.get(id!),
    enabled: Boolean(id),
    refetchInterval: 5_000,
  });
  const aQ = useQuery({
    queryKey: ["sessions", id, "agents"],
    queryFn: () => sessionsApi.listAgents(id!),
    enabled: Boolean(id),
    refetchInterval: 5_000,
  });

  const hasProject = Boolean(sQ.data?.project_id);

  return (
    <PageShell>
      <PageHeader
        breadcrumb={
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Link to="/sessions" className="hover:text-primary">
              {t("sessions.page_title")}
            </Link>
            {hasProject && (
              <>
                <span className="opacity-50">/</span>
                <Link
                  to={`/projects/${sQ.data!.project_id}`}
                  className="text-primary hover:underline flex items-center gap-1"
                >
                  <FolderKanban className="h-3 w-3" /> {sQ.data!.project_id}
                </Link>
              </>
            )}
            <span className="opacity-50">/</span>
            <code className="font-mono">{id?.slice(0, 8)}</code>
          </div>
        }
        title={sQ.data?.name ?? (id ? `Session ${id.slice(0, 8)}` : "Session")}
        subtitle={
          sQ.data ? (
            <div className="flex items-center gap-2 flex-wrap text-xs">
              <Badge variant={sQ.data.status === "active" ? "default" : "secondary"}>
                {t(`sessions.status_${sQ.data.status}`)}
              </Badge>
              <span className="text-muted-foreground">
                {aQ.data?.length ?? 0}{" "}
                {aQ.data?.length === 1 ? t("sessions.agents_count_one", { count: 1 }).split(" ").slice(1).join(" ") : t("sessions.agents_count_other", { count: aQ.data?.length ?? 0 }).split(" ").slice(1).join(" ")}
              </span>
              <span className="text-muted-foreground">
                · expire {new Date(sQ.data.expires_at).toLocaleTimeString()}
              </span>
            </div>
          ) : null
        }
      />

      <div
        className={cn(
          "max-w-3xl mx-auto px-5 py-7 relative",
          hasProject && "bg-gradient-to-r from-primary/5 to-transparent rounded-lg",
        )}
      >
        <TimelineRail variant="gradient" />

        {aQ.isLoading ? (
          <div className="space-y-4">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-16 w-full rounded-md" />
            ))}
          </div>
        ) : aQ.data?.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-6">
            {t("sessions.session_detail.no_agents")}
          </p>
        ) : (
          aQ.data?.map((a) => (
            <TimelineRow
              key={a.id}
              leftContent={
                <>
                  {t("sessions.status_" + (a.status === "busy" ? "active" : "closed"))}
                  <br />
                  <small className="opacity-70">
                    {new Date(a.created_at).toLocaleTimeString()}
                  </small>
                </>
              }
              bulletVariant={bulletForAgent(a)}
              onClick={() => navigate(`/sessions/${id}/agents/${a.id}`)}
              rightContent={
                <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
                  <div className="flex items-center gap-2">
                    <strong>{a.agent_id}</strong>
                    <Badge variant="default" className="h-5">
                      {a.status}
                    </Badge>
                  </div>
                  {a.mission && (
                    <div className="text-xs text-muted-foreground mt-1">
                      mission: {a.mission}
                    </div>
                  )}
                </div>
              }
            />
          ))
        )}
      </div>
    </PageShell>
  );
}
```

- [ ] **Step 8.4 : Lancer les tests, vérifier qu'ils passent**

```
cd frontend && npm test -- SessionDetailPage
```

Attendu : PASS.

- [ ] **Step 8.5 : Type-check + lint**

```
cd frontend && npx tsc --noEmit && npm run lint
```

Attendu : 0 erreur.

- [ ] **Step 8.6 : Commit**

```bash
git add frontend/src/pages/SessionDetailPage.tsx frontend/tests/pages/SessionDetailPage.test.tsx
git commit -m "feat(sessions): page /sessions/:id (détail + timeline agents)"
```

---

## Task 9 — Frontend : `SessionAgentTimelinePage.tsx`

**Files:**
- Create: `frontend/src/pages/SessionAgentTimelinePage.tsx`
- Test: `frontend/tests/pages/SessionAgentTimelinePage.test.tsx`

- [ ] **Step 9.1 : Écrire le test**

```typescript
// frontend/tests/pages/SessionAgentTimelinePage.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SessionAgentTimelinePage } from "@/pages/SessionAgentTimelinePage";
import { sessionsApi } from "@/lib/sessionsApi";
import "@/lib/i18n";

vi.mock("@/lib/sessionsApi", () => ({
  sessionsApi: {
    list: vi.fn(),
    get: vi.fn(),
    listAgents: vi.fn(),
    listMessages: vi.fn(),
  },
}));

function renderAt(sessionId: string, instanceId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/sessions/${sessionId}/agents/${instanceId}`]}>
        <Routes>
          <Route
            path="/sessions/:id/agents/:instanceId"
            element={<SessionAgentTimelinePage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SessionAgentTimelinePage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("affiche la timeline des messages", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "s1", name: null, status: "active",
      project_id: null, api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([
      { id: "a1", session_id: "s1", agent_id: "claude-code", labels: {}, mission: "m", status: "busy", created_at: new Date().toISOString() },
    ]);
    vi.mocked(sessionsApi.listMessages).mockResolvedValueOnce([
      { msg_id: "m1", parent_msg_id: null, direction: "in", kind: "llm_call", payload: { prompt: "Hello" }, source: null, created_at: new Date().toISOString(), route: null },
      { msg_id: "m2", parent_msg_id: "m1", direction: "out", kind: "tool_call", payload: { tool: "read_file" }, source: null, created_at: new Date().toISOString(), route: null },
    ]);

    renderAt("s1", "a1");
    await waitFor(() => expect(screen.getByText(/llm_call/)).toBeInTheDocument());
    expect(screen.getByText(/tool_call/)).toBeInTheDocument();
  });

  it("affiche état vide", async () => {
    vi.mocked(sessionsApi.get).mockResolvedValueOnce({
      id: "s1", name: null, status: "active",
      project_id: null, api_key_id: "k1",
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      closed_at: null,
    });
    vi.mocked(sessionsApi.listAgents).mockResolvedValueOnce([
      { id: "a1", session_id: "s1", agent_id: "claude-code", labels: {}, mission: "m", status: "busy", created_at: new Date().toISOString() },
    ]);
    vi.mocked(sessionsApi.listMessages).mockResolvedValueOnce([]);

    renderAt("s1", "a1");
    await waitFor(() =>
      expect(screen.getByText(/aucun message/i)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 9.2 : Lancer le test, vérifier qu'il échoue**

```
cd frontend && npm test -- SessionAgentTimelinePage
```

Attendu : FAIL.

- [ ] **Step 9.3 : Écrire la page**

```typescript
// frontend/src/pages/SessionAgentTimelinePage.tsx
import { useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { FolderKanban } from "lucide-react";

import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/layout/PageHeader";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TimelineRail } from "@/components/timeline/TimelineRail";
import { TimelineRow } from "@/components/timeline/TimelineRow";
import { sessionsApi, type MomMessage } from "@/lib/sessionsApi";
import { cn } from "@/lib/utils";

const BADGE_BY_KIND: Record<string, string> = {
  llm_call:    "bg-emerald-500/20 text-emerald-500 border border-emerald-500/30",
  tool_call:   "bg-blue-500/20 text-blue-500 border border-blue-500/30",
  mcp_call:    "bg-purple-500/20 text-purple-500 border border-purple-500/30",
  file_change: "bg-amber-500/20 text-amber-500 border border-amber-500/30",
  error:       "bg-red-500/20 text-red-500 border border-red-500/30",
};

function summarize(m: MomMessage): string {
  const p = m.payload ?? {};
  if (typeof p.prompt === "string") return p.prompt;
  if (typeof p.tool === "string") return p.tool;
  if (typeof p.message === "string") return p.message;
  return JSON.stringify(p).slice(0, 80);
}

export function SessionAgentTimelinePage() {
  const { id, instanceId } = useParams<{ id: string; instanceId: string }>();
  const { t } = useTranslation();
  const [filter, setFilter] = useState("");

  const sQ = useQuery({
    queryKey: ["sessions", id],
    queryFn: () => sessionsApi.get(id!),
    enabled: Boolean(id),
  });
  const aQ = useQuery({
    queryKey: ["sessions", id, "agents"],
    queryFn: () => sessionsApi.listAgents(id!),
    enabled: Boolean(id),
  });
  const mQ = useQuery({
    queryKey: ["sessions", id, "agents", instanceId, "messages"],
    queryFn: () => sessionsApi.listMessages(id!, instanceId!, { limit: 200 }),
    enabled: Boolean(id && instanceId),
    refetchInterval: 5_000,
  });

  const agent = aQ.data?.find((a) => a.id === instanceId);
  const messages = useMemo(() => {
    const data = mQ.data ?? [];
    const fl = filter.trim().toLowerCase();
    return fl
      ? data.filter(
          (m) =>
            m.kind.toLowerCase().includes(fl) ||
            summarize(m).toLowerCase().includes(fl),
        )
      : data;
  }, [mQ.data, filter]);

  const lastIndex = messages.length - 1;

  return (
    <PageShell>
      <PageHeader
        breadcrumb={
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Link to="/sessions" className="hover:text-primary">
              {t("sessions.page_title")}
            </Link>
            {sQ.data?.project_id && (
              <>
                <span className="opacity-50">/</span>
                <Link
                  to={`/projects/${sQ.data.project_id}`}
                  className="text-primary flex items-center gap-1"
                >
                  <FolderKanban className="h-3 w-3" /> {sQ.data.project_id}
                </Link>
              </>
            )}
            <span className="opacity-50">/</span>
            <Link to={`/sessions/${id}`} className="hover:text-primary">
              <code className="font-mono">{id?.slice(0, 8)}</code>
            </Link>
            <span className="opacity-50">/</span>
            <span>{agent?.agent_id ?? "…"}</span>
          </div>
        }
        title={agent?.agent_id ?? t("sessions.page_title")}
        subtitle={agent?.mission ?? undefined}
        actions={
          <div className="flex gap-2">
            <Input
              placeholder={t("sessions.agent_timeline.filter_placeholder")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-48"
            />
            <Badge variant="default">{t("sessions.agent_timeline.live_badge")}</Badge>
          </div>
        }
      />

      <div className="max-w-3xl mx-auto px-5 py-8 relative">
        <TimelineRail variant="solid" />

        {mQ.isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full rounded-md" />
            ))}
          </div>
        ) : messages.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-6">
            {t("sessions.agent_timeline.no_messages")}
          </p>
        ) : (
          messages.map((m, idx) => {
            const isLast = idx === lastIndex;
            const isLiveTail = isLast && sQ.data?.status === "active";
            return (
              <TimelineRow
                key={m.msg_id}
                bulletVariant={isLiveTail ? "live" : "default"}
                leftContent={
                  <span className="font-mono">
                    {new Date(m.created_at).toLocaleTimeString(undefined, {
                      hour: "2-digit", minute: "2-digit", second: "2-digit",
                    })}
                  </span>
                }
                rightContent={
                  <div className="rounded-md border border-border bg-muted/20 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "text-[11px] px-2 py-0.5 rounded-full font-medium",
                          BADGE_BY_KIND[m.kind] ??
                            "bg-muted text-muted-foreground",
                        )}
                      >
                        {m.kind}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {m.direction === "in"
                          ? t("sessions.agent_timeline.direction_in")
                          : t("sessions.agent_timeline.direction_out")}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 truncate">
                      {summarize(m)}
                    </p>
                  </div>
                }
              />
            );
          })
        )}
      </div>
    </PageShell>
  );
}
```

- [ ] **Step 9.4 : Lancer les tests, vérifier qu'ils passent**

```
cd frontend && npm test -- SessionAgentTimelinePage
```

Attendu : PASS.

- [ ] **Step 9.5 : Type-check + lint**

```
cd frontend && npx tsc --noEmit && npm run lint
```

Attendu : 0 erreur.

- [ ] **Step 9.6 : Commit**

```bash
git add frontend/src/pages/SessionAgentTimelinePage.tsx frontend/tests/pages/SessionAgentTimelinePage.test.tsx
git commit -m "feat(sessions): page /sessions/:id/agents/:instanceId (timeline messages MOM)"
```

---

## Task 10 — Frontend : Routes + Sidebar

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 10.1 : Ajouter les imports et routes dans App.tsx**

Ajouter après la ligne `import { AgentEditorPage } from "./pages/AgentEditorPage";` :

```typescript
import { SessionsPage } from "./pages/SessionsPage";
import { SessionDetailPage } from "./pages/SessionDetailPage";
import { SessionAgentTimelinePage } from "./pages/SessionAgentTimelinePage";
```

Insérer les routes juste avant `<Route path="*" ...>` (route fallback) :

```tsx
      <Route
        path="/sessions"
        element={
          <ProtectedRoute>
            <SessionsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/sessions/:id"
        element={
          <ProtectedRoute>
            <SessionDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/sessions/:id/agents/:instanceId"
        element={
          <ProtectedRoute>
            <SessionAgentTimelinePage />
          </ProtectedRoute>
        }
      />
```

- [ ] **Step 10.2 : Ajouter l'entrée sidebar**

Dans `frontend/src/components/layout/Sidebar.tsx`, importer `Activity` depuis `lucide-react` en haut (vérifier s'il est déjà importé, sinon l'ajouter).

Dans la section `section_orchestration` (ligne ~105), insérer en première position :

```typescript
{ to: "/sessions", label: t("sessions.page_title"), icon: Activity },
```

Résultat : l'item `sessions` apparaît avant `roles` / `agents`.

- [ ] **Step 10.3 : Type-check**

```
cd frontend && npx tsc --noEmit
```

Attendu : 0 erreur.

- [ ] **Step 10.4 : Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(sessions): routes /sessions/* + entrée sidebar"
```

---

## Task 11 — Vérification end-to-end sur LXC 201

**Files:** aucun (verification)

- [ ] **Step 11.1 : Lancer le build frontend**

```
cd frontend && npm run build
```

Attendu : build réussi, aucun warning TS bloquant.

- [ ] **Step 11.2 : Déployer sur LXC 201**

```
./scripts/deploy.sh
```

Attendu : docker-compose up sans erreur, `agflow-backend` + `agflow-frontend` up.

- [ ] **Step 11.3 : Tester le cas nominal (via navigateur)**

Ouvrir `https://docker-agflow.yoops.org/sessions` (ou l'URL locale du reverse-proxy).

- Se connecter en admin.
- Vérifier la page /sessions : liste + groupes projet visibles, bullets pulsent pour les sessions actives.
- Créer une session via un `curl` avec une clé API (si pas de session existante) :
  ```bash
  curl -X POST https://docker-agflow.yoops.org/api/v1/sessions \
    -H "Authorization: Bearer <API_KEY>" \
    -H "Content-Type: application/json" \
    -d '{"name":"test","duration_seconds":3600}'
  ```
- Retour UI /sessions → la nouvelle session apparaît.
- Cliquer dessus → page détail charge, affiche 0 agents (état vide).
- Créer un agent via `curl POST /api/v1/sessions/{id}/agents` (agent_id existant dans le catalogue).
- Retour UI → timeline affiche l'agent + bullet pulse.
- Cliquer l'agent → page /sessions/:id/agents/:instanceId → timeline messages vide (état vide).

- [ ] **Step 11.4 : Vérifier les logs Grafana**

Sur `https://log.yoops.org`, query Loki :
```
{compose_service="agflow-backend"} |= "admin_list_sessions"
```
Attendu : appels logués, 200 status.

- [ ] **Step 11.5 : Commit tag**

Si tout OK :

```bash
git tag sessions-ui-v1 -m "sessions UI V1 : liste + détail + timeline messages"
```

---

## Vérification finale (checklist)

Après `Task 11`, rien ne manque si :
- [ ] `GET /api/admin/sessions` retourne la liste avec `agent_count` en admin
- [ ] 3 pages accessibles via la sidebar, naviguables entre elles
- [ ] Bullet en couleur thème (indigo), pulsation visible sur agents actifs
- [ ] Breadcrumb enrichi quand `project_id` présent
- [ ] État vide i18n correctement affiché dans les 3 pages
- [ ] `npx tsc --noEmit` + `npm run lint` + `uv run pytest` + `uv run ruff check` tous OK
- [ ] Aucun `console.error` dans le navigateur sur les 3 pages
