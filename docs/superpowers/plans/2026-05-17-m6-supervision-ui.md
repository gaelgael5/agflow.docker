# M6 Supervision — Phase 2a UI (plan d'implémentation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher l'UI d'administration sur les endpoints `/api/admin/supervision/*` (Phase 1 déjà livrée) pour afficher KPI agrégés (4 cards), table filtrable des instances et drawer latéral de détail. Polling 5s. Lien partageable via `?instance=<uuid>`.

**Architecture:** 1 page assembleur + 4 composants découpés sous `components/supervision/` + 1 fichier `supervisionApi.ts` (Zod) + 1 hook `useSupervision.ts` (3 queries TanStack). Aucune modification backend (le toggle "inclure détruites" est implémenté par 2 requêtes mergées côté frontend, exploitant les filtres `status=None|destroyed` déjà offerts par `agents_instances_service.list_all_for_supervision`).

**Tech Stack:** React 18 + TypeScript strict · TanStack Query · Zod · shadcn/ui (Dialog, Card, Skeleton, Table, Badge, Input, Select, Separator) + nouveau composant `Sheet` à créer (Radix Dialog déjà installé) · i18next · Vitest + React Testing Library.

**Spec de référence :** `docs/superpowers/specs/2026-05-17-m6-supervision-ui-design.md` (commit `c090958`).

**Branche cible :** `dev`. Pas de feature branch.

**Mode pipeline allégé** (validé sur git-sync + backup_schedules) : implémenter subagent seul, pas de spec-reviewer ni code-reviewer intermédiaires entre tâches. Exécution continue (pas d'arrêt entre tâches sauf BLOCKED).

**Note tests** : pas d'env local pour pytest backend (LXC injoignable depuis Windows pour certains tests DB), mais Vitest tourne 100% en local (mocks). Validation E2E réelle = `./scripts/run-test.sh` à la dernière tâche.

---

## Structure des fichiers (vue d'ensemble)

### Composants UI partagés (1 fichier nouveau)

| Fichier | Responsabilité | Lignes cible |
|---|---|---|
| `frontend/src/components/ui/sheet.tsx` | Composant Sheet shadcn (Radix Dialog stylé en panneau latéral) | ~150 |

### Frontend Supervision (7 fichiers nouveaux)

| Fichier | Responsabilité | Lignes cible |
|---|---|---|
| `frontend/src/lib/supervisionApi.ts` | Types Zod + 3 fonctions API (overview, list, get) | ~110 |
| `frontend/src/hooks/useSupervision.ts` | 3 hooks TanStack (`useOverview`, `useInstances`, `useInstanceDetail`) + merge alive+destroyed | ~90 |
| `frontend/src/components/supervision/SupervisionKpiCards.tsx` | 4 cards (Sessions/Agents/Containers/MOM) + couleurs sévérité | ~170 |
| `frontend/src/components/supervision/SupervisionFilters.tsx` | Status select + search input + toggle "inclure détruites" | ~80 |
| `frontend/src/components/supervision/SupervisionInstancesTable.tsx` | Table filtrée + tri last_activity DESC + clic → setSearchParams | ~190 |
| `frontend/src/components/supervision/SupervisionInstanceDrawer.tsx` | Détail via Sheet + sections (mission/container/labels/mom/messages/error) | ~210 |
| `frontend/src/pages/SupervisionPage.tsx` | Assembleur + PageHeader + bouton refresh manuel + URL state | ~130 |

### Modifications fichiers existants (3)

| Fichier | Modification |
|---|---|
| `frontend/src/App.tsx` | Import `SupervisionPage` + route `<Route path="/supervision" element={<SupervisionPage />} />` |
| `frontend/src/components/layout/Sidebar.tsx:116` | Retirer `disabled: true` |
| `frontend/src/i18n/{fr,en}.json` | Bloc `supervision.*` (~35 clés × 2) |

### Tests (6 fichiers nouveaux)

| Fichier | Tests |
|---|---|
| `frontend/src/lib/__tests__/supervisionApi.test.ts` | 4 tests (Zod parsing, URL params) |
| `frontend/src/hooks/__tests__/useSupervision.test.ts` | 3 tests (queries enabled, merge alive+destroyed) |
| `frontend/src/components/supervision/__tests__/SupervisionKpiCards.test.tsx` | 4 tests (cards rendues, couleurs sévérité, containers null) |
| `frontend/src/components/supervision/__tests__/SupervisionFilters.test.tsx` | 3 tests (status select, search input, toggle destroyed) |
| `frontend/src/components/supervision/__tests__/SupervisionInstancesTable.test.tsx` | 6 tests (filtre texte, tri, empty, error+retry, clic ligne, destroyed) |
| `frontend/src/components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx` | 4 tests (rendu détail, labels {}, fermeture, recent_messages) |
| `frontend/src/pages/__tests__/SupervisionPage.test.tsx` | 2 tests (URL ?instance=<id> ouvre drawer, fermeture nettoie searchParam) |

**Total : 26 tests Vitest**.

---

## Tâche 1 — Composant `Sheet` (shadcn maison, Radix Dialog stylé latéral)

**Files:**
- Create: `frontend/src/components/ui/sheet.tsx`

Pas de test unitaire pour ce wrapper Radix (couvert par les tests du drawer en T7).

### Step 1 — Créer `frontend/src/components/ui/sheet.tsx`

- [ ] Coller le contenu suivant (pattern shadcn standard, basé sur `@radix-ui/react-dialog` déjà installé, positionnement à droite) :

```tsx
import * as React from "react";
import * as SheetPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export const Sheet = SheetPrimitive.Root;
export const SheetTrigger = SheetPrimitive.Trigger;
export const SheetClose = SheetPrimitive.Close;
export const SheetPortal = SheetPrimitive.Portal;

export const SheetOverlay = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Overlay
    ref={ref}
    className={cn(
      "fixed inset-0 z-50 bg-zinc-900/30 backdrop-blur-sm",
      "data-[state=open]:animate-in data-[state=closed]:animate-out",
      "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
      className,
    )}
    {...props}
  />
));
SheetOverlay.displayName = "SheetOverlay";

interface SheetContentProps
  extends React.ComponentPropsWithoutRef<typeof SheetPrimitive.Content> {
  side?: "right" | "left";
}

export const SheetContent = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Content>,
  SheetContentProps
>(({ className, children, side = "right", ...props }, ref) => (
  <SheetPortal>
    <SheetOverlay />
    <SheetPrimitive.Content
      ref={ref}
      className={cn(
        "fixed z-50 h-full w-full bg-background shadow-lg border-l",
        "sm:max-w-[560px] overflow-y-auto",
        "data-[state=open]:animate-in data-[state=closed]:animate-out",
        "transition-transform duration-300",
        side === "right" &&
          "right-0 top-0 data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right",
        side === "left" &&
          "left-0 top-0 border-r border-l-0 data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left",
        className,
      )}
      {...props}
    >
      {children}
      <SheetPrimitive.Close
        className={cn(
          "absolute right-4 top-4 rounded-sm opacity-70 transition-opacity",
          "hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring",
          "disabled:pointer-events-none",
        )}
      >
        <X className="h-4 w-4" />
        <span className="sr-only">Close</span>
      </SheetPrimitive.Close>
    </SheetPrimitive.Content>
  </SheetPortal>
));
SheetContent.displayName = "SheetContent";

export const SheetHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col gap-1 px-6 py-4 border-b sticky top-0 bg-background",
      className,
    )}
    {...props}
  />
);

export const SheetTitle = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Title>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Title
    ref={ref}
    className={cn("text-lg font-semibold", className)}
    {...props}
  />
));
SheetTitle.displayName = "SheetTitle";

export const SheetDescription = React.forwardRef<
  React.ElementRef<typeof SheetPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof SheetPrimitive.Description>
>(({ className, ...props }, ref) => (
  <SheetPrimitive.Description
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
));
SheetDescription.displayName = "SheetDescription";
```

### Step 2 — Vérifier TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 3 — Commit

```bash
git add frontend/src/components/ui/sheet.tsx
git commit -m "feat(ui): composant Sheet shadcn (Dialog Radix stylé latéral)"
```

---

## Tâche 2 — `lib/supervisionApi.ts` (types Zod + 3 fonctions)

**Files:**
- Create: `frontend/src/lib/supervisionApi.ts`
- Test: `frontend/src/lib/__tests__/supervisionApi.test.ts`

### Step 1 — Écrire le test (failing)

- [ ] Créer `frontend/src/lib/__tests__/supervisionApi.test.ts` :

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { supervisionApi, SupervisionOverviewSchema, SupervisedInstanceSchema } from "../supervisionApi";
import { api } from "../api";

vi.mock("../api", () => ({
  api: { get: vi.fn() },
}));

describe("supervisionApi", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("parse une réponse overview valide", () => {
    const raw = {
      sessions: { active: 3, closed: 2, expired: 0 },
      agents: { idle: 5, busy: 2, error: 0, destroyed_total: 8 },
      containers_running: 12,
      mom: { pending: 0, claimed: 3, failed: 1 },
    };
    const parsed = SupervisionOverviewSchema.parse(raw);
    expect(parsed.containers_running).toBe(12);
    expect(parsed.mom.failed).toBe(1);
  });

  it("accepte containers_running null", () => {
    const raw = {
      sessions: { active: 0, closed: 0, expired: 0 },
      agents: { idle: 0, busy: 0, error: 0, destroyed_total: 0 },
      containers_running: null,
      mom: { pending: 0, claimed: 0, failed: 0 },
    };
    const parsed = SupervisionOverviewSchema.parse(raw);
    expect(parsed.containers_running).toBeNull();
  });

  it("parse une SupervisedInstance avec destroyed_at null", () => {
    const raw = {
      id: "11111111-1111-1111-1111-111111111111",
      session_id: "22222222-2222-2222-2222-222222222222",
      agent_id: "claude-code-r1",
      mission: "refactor",
      status: "busy",
      last_activity_at: "2026-05-17T10:00:00Z",
      created_at: "2026-05-17T09:00:00Z",
      destroyed_at: null,
      error_message: null,
      last_container_name: "agent-abc",
    };
    const parsed = SupervisedInstanceSchema.parse(raw);
    expect(parsed.status).toBe("busy");
    expect(parsed.destroyed_at).toBeNull();
  });

  it("listInstances construit les bons query params", async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    await supervisionApi.listInstances({ status: "busy", limit: 50 });
    expect(api.get).toHaveBeenCalledWith("/admin/supervision/instances?status=busy&limit=50");
  });
});
```

### Step 2 — Lancer le test (verify it fails)

- [ ] Lancer : `cd frontend && npm test -- src/lib/__tests__/supervisionApi.test.ts`
- [ ] Attendu : `Cannot find module '../supervisionApi'`.

### Step 3 — Écrire `frontend/src/lib/supervisionApi.ts`

- [ ] Créer le fichier :

```ts
import { z } from "zod";
import { api } from "./api";

export const SessionStatusCountsSchema = z.object({
  active: z.number(),
  closed: z.number(),
  expired: z.number(),
});

export const AgentStatusCountsSchema = z.object({
  idle: z.number(),
  busy: z.number(),
  error: z.number(),
  destroyed_total: z.number(),
});

export const MomDeliveryCountsSchema = z.object({
  pending: z.number(),
  claimed: z.number(),
  failed: z.number(),
});

export const SupervisionOverviewSchema = z.object({
  sessions: SessionStatusCountsSchema,
  agents: AgentStatusCountsSchema,
  containers_running: z.number().nullable(),
  mom: MomDeliveryCountsSchema,
});

export const SupervisedInstanceSchema = z.object({
  id: z.string().uuid(),
  session_id: z.string().uuid(),
  agent_id: z.string(),
  mission: z.string().nullable(),
  status: z.string(),
  last_activity_at: z.string(),
  created_at: z.string(),
  destroyed_at: z.string().nullable(),
  error_message: z.string().nullable(),
  last_container_name: z.string().nullable(),
});

export const InstanceDetailSchema = SupervisedInstanceSchema.extend({
  labels: z.record(z.unknown()),
  container_status: z.string().nullable(),
  mom_counts: MomDeliveryCountsSchema,
  recent_messages: z.array(z.record(z.unknown())),
});

export type SupervisionOverview = z.infer<typeof SupervisionOverviewSchema>;
export type SupervisedInstance = z.infer<typeof SupervisedInstanceSchema>;
export type InstanceDetail = z.infer<typeof InstanceDetailSchema>;

export type InstanceStatusFilter = "all" | "idle" | "busy" | "error" | "destroyed";

interface ListParams {
  status?: "idle" | "busy" | "error" | "destroyed";
  limit?: number;
}

export const supervisionApi = {
  async getOverview(): Promise<SupervisionOverview> {
    const raw = await api.get<unknown>("/admin/supervision/overview");
    return SupervisionOverviewSchema.parse(raw);
  },

  async listInstances(params: ListParams = {}): Promise<SupervisedInstance[]> {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const path = qs.toString()
      ? `/admin/supervision/instances?${qs.toString()}`
      : "/admin/supervision/instances";
    const raw = await api.get<unknown>(path);
    return z.array(SupervisedInstanceSchema).parse(raw);
  },

  async getInstance(id: string): Promise<InstanceDetail> {
    const raw = await api.get<unknown>(`/admin/supervision/instances/${id}`);
    return InstanceDetailSchema.parse(raw);
  },
};
```

### Step 4 — Vérifier signature de `api.get`

- [ ] Lancer : `grep -n "export.*api\\b\\|get<" frontend/src/lib/api.ts | head -5`
- [ ] Si `api.get` n'existe pas ou a une signature différente, adapter l'import et les appels. Sinon, continuer.

### Step 5 — Re-lancer les tests

- [ ] Lancer : `cd frontend && npm test -- src/lib/__tests__/supervisionApi.test.ts`
- [ ] Attendu : **4 tests PASS**.

### Step 6 — TypeScript strict

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 7 — Commit

```bash
git add frontend/src/lib/supervisionApi.ts frontend/src/lib/__tests__/supervisionApi.test.ts
git commit -m "feat(supervision-api): types Zod + 3 fonctions (overview/list/get)"
```

---

## Tâche 3 — `hooks/useSupervision.ts` (3 hooks TanStack)

**Files:**
- Create: `frontend/src/hooks/useSupervision.ts`
- Test: `frontend/src/hooks/__tests__/useSupervision.test.ts`

### Step 1 — Écrire le test (failing)

- [ ] Créer `frontend/src/hooks/__tests__/useSupervision.test.ts` :

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useOverview, useInstances, useInstanceDetail } from "../useSupervision";
import { supervisionApi } from "@/lib/supervisionApi";
import type { ReactNode } from "react";

vi.mock("@/lib/supervisionApi", () => ({
  supervisionApi: {
    getOverview: vi.fn(),
    listInstances: vi.fn(),
    getInstance: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSupervision", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("useOverview appelle getOverview", async () => {
    (supervisionApi.getOverview as ReturnType<typeof vi.fn>).mockResolvedValue({
      sessions: { active: 1, closed: 0, expired: 0 },
      agents: { idle: 0, busy: 0, error: 0, destroyed_total: 0 },
      containers_running: null,
      mom: { pending: 0, claimed: 0, failed: 0 },
    });
    const { result } = renderHook(() => useOverview(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(supervisionApi.getOverview).toHaveBeenCalled();
  });

  it("useInstanceDetail est désactivé si id est null", () => {
    const { result } = renderHook(() => useInstanceDetail(null), { wrapper });
    expect(result.current.fetchStatus).toBe("idle");
    expect(supervisionApi.getInstance).not.toHaveBeenCalled();
  });

  it("useInstances avec includeDestroyed=true merge alive et destroyed", async () => {
    (supervisionApi.listInstances as ReturnType<typeof vi.fn>).mockImplementation(
      async (params: { status?: string }) => {
        if (params.status === "destroyed")
          return [{ id: "d-1", status: "destroyed", destroyed_at: "2026-05-17T00:00:00Z" }];
        return [{ id: "a-1", status: "idle", destroyed_at: null }];
      },
    );
    const { result } = renderHook(
      () => useInstances({ status: undefined, includeDestroyed: true }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const ids = (result.current.data ?? []).map((i: { id: string }) => i.id);
    expect(ids).toContain("a-1");
    expect(ids).toContain("d-1");
  });
});
```

### Step 2 — Lancer le test (verify fail)

- [ ] Lancer : `cd frontend && npm test -- src/hooks/__tests__/useSupervision.test.ts`
- [ ] Attendu : `Cannot find module '../useSupervision'`.

### Step 3 — Écrire `frontend/src/hooks/useSupervision.ts`

- [ ] Créer le fichier :

```ts
import { useQuery } from "@tanstack/react-query";
import {
  supervisionApi,
  type SupervisedInstance,
} from "@/lib/supervisionApi";

const REFETCH_MS = 5_000;

export function useOverview() {
  return useQuery({
    queryKey: ["supervision", "overview"],
    queryFn: () => supervisionApi.getOverview(),
    refetchInterval: REFETCH_MS,
  });
}

interface UseInstancesParams {
  status: "idle" | "busy" | "error" | undefined;
  includeDestroyed: boolean;
}

export function useInstances({ status, includeDestroyed }: UseInstancesParams) {
  return useQuery({
    queryKey: ["supervision", "instances", { status, includeDestroyed }],
    queryFn: async (): Promise<SupervisedInstance[]> => {
      const alive = await supervisionApi.listInstances({ status, limit: 200 });
      if (!includeDestroyed) return alive;
      const destroyed = await supervisionApi.listInstances({
        status: "destroyed",
        limit: 200,
      });
      return [...alive, ...destroyed];
    },
    refetchInterval: REFETCH_MS,
  });
}

export function useInstanceDetail(id: string | null) {
  return useQuery({
    queryKey: ["supervision", "instance", id],
    queryFn: () => supervisionApi.getInstance(id as string),
    enabled: !!id,
    refetchInterval: REFETCH_MS,
  });
}
```

### Step 4 — Re-lancer les tests

- [ ] Lancer : `cd frontend && npm test -- src/hooks/__tests__/useSupervision.test.ts`
- [ ] Attendu : **3 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 6 — Commit

```bash
git add frontend/src/hooks/useSupervision.ts frontend/src/hooks/__tests__/useSupervision.test.ts
git commit -m "feat(supervision-hooks): 3 queries TanStack + merge alive+destroyed"
```

---

## Tâche 4 — i18n FR + EN (bloc `supervision.*`)

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

### Step 1 — Localiser le point d'insertion

- [ ] Lancer : `grep -n '"sidebar"' frontend/src/i18n/fr.json | head -2`
- [ ] Repérer la fin de bloc cohérente (entre 2 sections existantes, ex: après `"settings"` ou avant `"templates"`). Ajouter le bloc `"supervision"` au bon niveau (racine).

### Step 2 — Ajouter le bloc dans `frontend/src/i18n/fr.json`

- [ ] Insérer (avant la dernière clé racine) :

```json
"supervision": {
  "page_title": "Supervision",
  "subtitle": "État temps réel des sessions, agents, containers et MOM",
  "refresh": "Rafraîchir",
  "kpi": {
    "sessions": {
      "title": "Sessions",
      "active": "Actives",
      "closed": "Fermées",
      "expired": "Expirées"
    },
    "agents": {
      "title": "Agents",
      "idle": "Idle",
      "busy": "Occupés",
      "error": "Erreur",
      "destroyed": "Détruits"
    },
    "containers": {
      "title": "Containers",
      "running": "Up",
      "unavailable": "Indisponible"
    },
    "mom": {
      "title": "MOM Delivery",
      "pending": "Pending",
      "claimed": "Claimed",
      "failed": "Failed"
    }
  },
  "filters": {
    "status": {
      "label": "Status",
      "all": "Tous",
      "idle": "Idle",
      "busy": "Occupés",
      "error": "Erreur"
    },
    "search_placeholder": "Mission, agent, session...",
    "include_destroyed": "Inclure les détruites"
  },
  "table": {
    "col": {
      "status": "Status",
      "mission": "Mission",
      "agent": "Agent",
      "session": "Session",
      "last_activity": "Dernière activité"
    },
    "empty": "Aucune instance active. Lance une session pour voir des agents apparaître.",
    "error": "Erreur de chargement",
    "retry": "Réessayer",
    "no_mission": "—"
  },
  "drawer": {
    "section": {
      "mission": "Mission",
      "container": "Container",
      "labels": "Labels",
      "mom": "MOM Delivery",
      "messages": "Derniers messages",
      "error": "Erreur"
    },
    "container_status": {
      "running": "running",
      "exited": "exited",
      "none": "—"
    },
    "not_found": "Instance introuvable (probablement détruite)",
    "close": "Fermer"
  },
  "status": {
    "idle": "Idle",
    "busy": "Occupé",
    "error": "Erreur",
    "destroyed": "Détruit"
  }
}
```

### Step 3 — Ajouter le bloc équivalent dans `frontend/src/i18n/en.json`

- [ ] Insérer la version anglaise (mêmes clés, valeurs traduites) :

```json
"supervision": {
  "page_title": "Supervision",
  "subtitle": "Real-time state of sessions, agents, containers and MOM",
  "refresh": "Refresh",
  "kpi": {
    "sessions": { "title": "Sessions", "active": "Active", "closed": "Closed", "expired": "Expired" },
    "agents": { "title": "Agents", "idle": "Idle", "busy": "Busy", "error": "Error", "destroyed": "Destroyed" },
    "containers": { "title": "Containers", "running": "Up", "unavailable": "Unavailable" },
    "mom": { "title": "MOM Delivery", "pending": "Pending", "claimed": "Claimed", "failed": "Failed" }
  },
  "filters": {
    "status": { "label": "Status", "all": "All", "idle": "Idle", "busy": "Busy", "error": "Error" },
    "search_placeholder": "Mission, agent, session...",
    "include_destroyed": "Include destroyed"
  },
  "table": {
    "col": { "status": "Status", "mission": "Mission", "agent": "Agent", "session": "Session", "last_activity": "Last activity" },
    "empty": "No active instance. Start a session to see agents appear.",
    "error": "Load error",
    "retry": "Retry",
    "no_mission": "—"
  },
  "drawer": {
    "section": { "mission": "Mission", "container": "Container", "labels": "Labels", "mom": "MOM Delivery", "messages": "Recent messages", "error": "Error" },
    "container_status": { "running": "running", "exited": "exited", "none": "—" },
    "not_found": "Instance not found (likely destroyed)",
    "close": "Close"
  },
  "status": { "idle": "Idle", "busy": "Busy", "error": "Error", "destroyed": "Destroyed" }
}
```

### Step 4 — Vérifier validité JSON

- [ ] Lancer : `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json'))" && node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json'))"`
- [ ] Attendu : aucune sortie (pas d'erreur).

### Step 5 — Commit

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(supervision-i18n): bloc supervision.* FR+EN (35 clés)"
```

---

## Tâche 5 — `SupervisionKpiCards.tsx` (4 cards KPI)

**Files:**
- Create: `frontend/src/components/supervision/SupervisionKpiCards.tsx`
- Test: `frontend/src/components/supervision/__tests__/SupervisionKpiCards.test.tsx`

### Step 1 — Écrire le test (failing)

- [ ] Créer `frontend/src/components/supervision/__tests__/SupervisionKpiCards.test.tsx` :

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionKpiCards } from "../SupervisionKpiCards";

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

const baseOverview = {
  sessions: { active: 3, closed: 2, expired: 0 },
  agents: { idle: 5, busy: 2, error: 0, destroyed_total: 8 },
  containers_running: 12,
  mom: { pending: 0, claimed: 3, failed: 0 },
};

describe("SupervisionKpiCards", () => {
  it("affiche les 4 cards avec les bonnes valeurs", () => {
    render(wrap(<SupervisionKpiCards data={baseOverview} />));
    expect(screen.getByText("3")).toBeInTheDocument(); // sessions active
    expect(screen.getByText("5")).toBeInTheDocument(); // agents idle
    expect(screen.getByText("12")).toBeInTheDocument(); // containers
    expect(screen.getByText(/Sessions/i)).toBeInTheDocument();
    expect(screen.getByText(/Agents/i)).toBeInTheDocument();
    expect(screen.getByText(/Containers/i)).toBeInTheDocument();
    expect(screen.getByText(/MOM/i)).toBeInTheDocument();
  });

  it("colore les compteurs erreur/failed en destructive quand > 0", () => {
    const overview = {
      ...baseOverview,
      agents: { ...baseOverview.agents, error: 2 },
      mom: { ...baseOverview.mom, failed: 1 },
    };
    const { container } = render(wrap(<SupervisionKpiCards data={overview} />));
    const destructiveEls = container.querySelectorAll(".text-destructive");
    expect(destructiveEls.length).toBeGreaterThanOrEqual(2);
  });

  it("affiche un dash si containers_running est null", () => {
    const overview = { ...baseOverview, containers_running: null };
    render(wrap(<SupervisionKpiCards data={overview} />));
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("affiche 4 skeletons si data est undefined", () => {
    const { container } = render(wrap(<SupervisionKpiCards data={undefined} />));
    const skeletons = container.querySelectorAll('[role="status"]');
    expect(skeletons.length).toBe(4);
  });
});
```

### Step 2 — Lancer le test (verify fail)

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionKpiCards.test.tsx`
- [ ] Attendu : `Cannot find module '../SupervisionKpiCards'`.

### Step 3 — Écrire `frontend/src/components/supervision/SupervisionKpiCards.tsx`

- [ ] Créer le fichier :

```tsx
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { SupervisionOverview } from "@/lib/supervisionApi";
import { FolderKanban, Bot, Container, Mailbox } from "lucide-react";

interface Props {
  data: SupervisionOverview | undefined;
}

interface Row {
  label: string;
  value: number | string;
  tone?: "default" | "primary" | "destructive" | "muted" | "success";
}

function Tone({ tone, children }: { tone: Row["tone"]; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "tabular-nums font-semibold text-2xl",
        tone === "primary" && "text-primary",
        tone === "destructive" && "text-destructive",
        tone === "muted" && "text-muted-foreground",
        tone === "success" && "text-emerald-600 dark:text-emerald-400",
      )}
    >
      {children}
    </span>
  );
}

function KpiCard({
  title,
  icon: Icon,
  rows,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  rows: Row[];
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {rows.map((r) => (
          <div key={r.label} className="flex justify-between items-baseline">
            <span className="text-sm text-muted-foreground">{r.label}</span>
            <Tone tone={r.tone}>{r.value}</Tone>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function SkeletonCard() {
  return (
    <div role="status" aria-busy="true" aria-live="polite">
      <Skeleton className="h-32 w-full rounded-md" />
    </div>
  );
}

export function SupervisionKpiCards({ data }: Props) {
  const { t } = useTranslation();

  if (!data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  const containersDisplay =
    data.containers_running === null ? "—" : data.containers_running;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
      <KpiCard
        title={t("supervision.kpi.sessions.title")}
        icon={FolderKanban}
        rows={[
          { label: t("supervision.kpi.sessions.active"), value: data.sessions.active, tone: "success" },
          { label: t("supervision.kpi.sessions.closed"), value: data.sessions.closed, tone: "muted" },
          { label: t("supervision.kpi.sessions.expired"), value: data.sessions.expired, tone: data.sessions.expired > 0 ? "destructive" : "muted" },
        ]}
      />
      <KpiCard
        title={t("supervision.kpi.agents.title")}
        icon={Bot}
        rows={[
          { label: t("supervision.kpi.agents.idle"), value: data.agents.idle, tone: "default" },
          { label: t("supervision.kpi.agents.busy"), value: data.agents.busy, tone: data.agents.busy > 0 ? "primary" : "default" },
          { label: t("supervision.kpi.agents.error"), value: data.agents.error, tone: data.agents.error > 0 ? "destructive" : "muted" },
          { label: t("supervision.kpi.agents.destroyed"), value: data.agents.destroyed_total, tone: "muted" },
        ]}
      />
      <KpiCard
        title={t("supervision.kpi.containers.title")}
        icon={Container}
        rows={[
          { label: t("supervision.kpi.containers.running"), value: containersDisplay, tone: "default" },
        ]}
      />
      <KpiCard
        title={t("supervision.kpi.mom.title")}
        icon={Mailbox}
        rows={[
          { label: t("supervision.kpi.mom.pending"), value: data.mom.pending, tone: "default" },
          { label: t("supervision.kpi.mom.claimed"), value: data.mom.claimed, tone: data.mom.claimed > 0 ? "primary" : "default" },
          { label: t("supervision.kpi.mom.failed"), value: data.mom.failed, tone: data.mom.failed > 0 ? "destructive" : "muted" },
        ]}
      />
    </div>
  );
}
```

### Step 4 — Re-lancer les tests

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionKpiCards.test.tsx`
- [ ] Attendu : **4 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 6 — Commit

```bash
git add frontend/src/components/supervision/SupervisionKpiCards.tsx \
         frontend/src/components/supervision/__tests__/SupervisionKpiCards.test.tsx
git commit -m "feat(supervision-ui): SupervisionKpiCards (4 cards + tones sévérité)"
```

---

## Tâche 6 — `SupervisionFilters.tsx` (status select + search + toggle destroyed)

**Files:**
- Create: `frontend/src/components/supervision/SupervisionFilters.tsx`
- Test: `frontend/src/components/supervision/__tests__/SupervisionFilters.test.tsx`

### Step 1 — Écrire le test

- [ ] Créer `frontend/src/components/supervision/__tests__/SupervisionFilters.test.tsx` :

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionFilters, type Filters } from "../SupervisionFilters";

const base: Filters = { status: "all", search: "", includeDestroyed: false };

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe("SupervisionFilters", () => {
  it("appelle onChange quand le toggle destroyed est coché", () => {
    const onChange = vi.fn();
    render(wrap(<SupervisionFilters value={base} onChange={onChange} />));
    const checkbox = screen.getByLabelText(/inclure/i) as HTMLInputElement;
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith({ ...base, includeDestroyed: true });
  });

  it("appelle onChange quand l'input recherche change", () => {
    const onChange = vi.fn();
    render(wrap(<SupervisionFilters value={base} onChange={onChange} />));
    const input = screen.getByPlaceholderText(/mission/i);
    fireEvent.change(input, { target: { value: "refactor" } });
    expect(onChange).toHaveBeenCalledWith({ ...base, search: "refactor" });
  });

  it("affiche le placeholder de recherche", () => {
    render(wrap(<SupervisionFilters value={base} onChange={() => {}} />));
    expect(screen.getByPlaceholderText(/mission/i)).toBeInTheDocument();
  });
});
```

### Step 2 — Lancer (fail)

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionFilters.test.tsx`
- [ ] Attendu : `Cannot find module '../SupervisionFilters'`.

### Step 3 — Écrire `frontend/src/components/supervision/SupervisionFilters.tsx`

- [ ] Créer le fichier :

```tsx
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface Filters {
  status: "all" | "idle" | "busy" | "error";
  search: string;
  includeDestroyed: boolean;
}

interface Props {
  value: Filters;
  onChange: (next: Filters) => void;
}

export function SupervisionFilters({ value, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Select
        value={value.status}
        onValueChange={(s) =>
          onChange({ ...value, status: s as Filters["status"] })
        }
      >
        <SelectTrigger className="w-[140px]">
          <SelectValue placeholder={t("supervision.filters.status.label")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("supervision.filters.status.all")}</SelectItem>
          <SelectItem value="idle">{t("supervision.filters.status.idle")}</SelectItem>
          <SelectItem value="busy">{t("supervision.filters.status.busy")}</SelectItem>
          <SelectItem value="error">{t("supervision.filters.status.error")}</SelectItem>
        </SelectContent>
      </Select>

      <Input
        type="search"
        placeholder={t("supervision.filters.search_placeholder")}
        value={value.search}
        onChange={(e) => onChange({ ...value, search: e.target.value })}
        className="max-w-xs"
      />

      <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
        <input
          type="checkbox"
          checked={value.includeDestroyed}
          onChange={(e) =>
            onChange({ ...value, includeDestroyed: e.target.checked })
          }
          className="h-4 w-4 rounded border-input"
        />
        {t("supervision.filters.include_destroyed")}
      </label>
    </div>
  );
}
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionFilters.test.tsx`
- [ ] Attendu : **3 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`

### Step 6 — Commit

```bash
git add frontend/src/components/supervision/SupervisionFilters.tsx \
         frontend/src/components/supervision/__tests__/SupervisionFilters.test.tsx
git commit -m "feat(supervision-ui): SupervisionFilters (status + search + toggle destroyed)"
```

---

## Tâche 7 — `SupervisionInstancesTable.tsx`

**Files:**
- Create: `frontend/src/components/supervision/SupervisionInstancesTable.tsx`
- Test: `frontend/src/components/supervision/__tests__/SupervisionInstancesTable.test.tsx`

### Step 1 — Écrire le test

- [ ] Créer `frontend/src/components/supervision/__tests__/SupervisionInstancesTable.test.tsx` :

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionInstancesTable } from "../SupervisionInstancesTable";
import type { SupervisedInstance } from "@/lib/supervisionApi";
import type { Filters } from "../SupervisionFilters";

const mkInstance = (over: Partial<SupervisedInstance> = {}): SupervisedInstance => ({
  id: over.id ?? "11111111-1111-1111-1111-111111111111",
  session_id: "22222222-2222-2222-2222-222222222222",
  agent_id: "claude-code-r1",
  mission: "refactor auth",
  status: "busy",
  last_activity_at: "2026-05-17T10:00:00Z",
  created_at: "2026-05-17T09:00:00Z",
  destroyed_at: null,
  error_message: null,
  last_container_name: "agent-abc",
  ...over,
});

const defaultFilters: Filters = { status: "all", search: "", includeDestroyed: false };

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe("SupervisionInstancesTable", () => {
  it("affiche l'état vide quand instances=[] et isSuccess", () => {
    render(
      wrap(
        <SupervisionInstancesTable
          instances={[]}
          filters={defaultFilters}
          isLoading={false}
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    expect(screen.getByText(/aucune instance/i)).toBeInTheDocument();
  });

  it("filtre par recherche texte (mission)", () => {
    const a = mkInstance({ id: "a-1", mission: "refactor auth" });
    const b = mkInstance({ id: "b-2", mission: "review PR" });
    render(
      wrap(
        <SupervisionInstancesTable
          instances={[a, b]}
          filters={{ ...defaultFilters, search: "review" }}
          isLoading={false}
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    expect(screen.getByText("review PR")).toBeInTheDocument();
    expect(screen.queryByText("refactor auth")).not.toBeInTheDocument();
  });

  it("trie par last_activity_at DESC", () => {
    const a = mkInstance({ id: "a-1", mission: "old", last_activity_at: "2026-05-17T08:00:00Z" });
    const b = mkInstance({ id: "b-2", mission: "new", last_activity_at: "2026-05-17T12:00:00Z" });
    const { container } = render(
      wrap(
        <SupervisionInstancesTable
          instances={[a, b]}
          filters={defaultFilters}
          isLoading={false}
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0]?.textContent).toContain("new");
    expect(rows[1]?.textContent).toContain("old");
  });

  it("appelle onSelect avec id au clic ligne", () => {
    const onSelect = vi.fn();
    const a = mkInstance({ id: "a-1" });
    render(
      wrap(
        <SupervisionInstancesTable
          instances={[a]}
          filters={defaultFilters}
          isLoading={false}
          error={null}
          onSelect={onSelect}
          onRetry={() => {}}
        />,
      ),
    );
    const row = screen.getByText(/refactor auth/i).closest("tr");
    fireEvent.click(row!);
    expect(onSelect).toHaveBeenCalledWith("a-1");
  });

  it("affiche skeletons quand isLoading=true", () => {
    const { container } = render(
      wrap(
        <SupervisionInstancesTable
          instances={undefined}
          filters={defaultFilters}
          isLoading
          error={null}
          onSelect={() => {}}
          onRetry={() => {}}
        />,
      ),
    );
    const skeletons = container.querySelectorAll('[data-skeleton-row]');
    expect(skeletons.length).toBeGreaterThanOrEqual(3);
  });

  it("affiche bloc erreur + bouton retry et appelle onRetry au clic", () => {
    const onRetry = vi.fn();
    render(
      wrap(
        <SupervisionInstancesTable
          instances={undefined}
          filters={defaultFilters}
          isLoading={false}
          error={new Error("boom")}
          onSelect={() => {}}
          onRetry={onRetry}
        />,
      ),
    );
    const btn = screen.getByRole("button", { name: /réessayer|retry/i });
    fireEvent.click(btn);
    expect(onRetry).toHaveBeenCalled();
  });
});
```

### Step 2 — Lancer (fail)

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionInstancesTable.test.tsx`
- [ ] Attendu : `Cannot find module '../SupervisionInstancesTable'`.

### Step 3 — Écrire `frontend/src/components/supervision/SupervisionInstancesTable.tsx`

- [ ] Créer le fichier :

```tsx
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { SupervisedInstance } from "@/lib/supervisionApi";
import type { Filters } from "./SupervisionFilters";

interface Props {
  instances: SupervisedInstance[] | undefined;
  filters: Filters;
  isLoading: boolean;
  error: Error | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}

function formatRelative(iso: string): string {
  const d = new Date(iso).getTime();
  const diffMs = Date.now() - d;
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `il y a ${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `il y a ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  const d2 = Math.floor(h / 24);
  return `il y a ${d2} j`;
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "busy"
      ? "bg-primary/15 text-primary"
      : status === "idle"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
      : status === "error"
      ? "bg-destructive/15 text-destructive"
      : "bg-muted text-muted-foreground"; // destroyed / unknown
  return (
    <Badge variant="outline" className={cn("font-mono uppercase tracking-wide", tone)}>
      <span className="mr-1.5 w-1.5 h-1.5 rounded-full bg-current" aria-hidden />
      {status}
    </Badge>
  );
}

export function SupervisionInstancesTable({
  instances,
  filters,
  isLoading,
  error,
  onSelect,
  onRetry,
}: Props) {
  const { t } = useTranslation();

  const filtered = useMemo(() => {
    if (!instances) return [];
    const q = filters.search.trim().toLowerCase();
    const list = q
      ? instances.filter(
          (i) =>
            (i.mission?.toLowerCase().includes(q) ?? false) ||
            i.agent_id.toLowerCase().includes(q) ||
            i.session_id.toLowerCase().includes(q),
        )
      : instances;
    return [...list].sort((a, b) =>
      a.last_activity_at < b.last_activity_at ? 1 : -1,
    );
  }, [instances, filters.search]);

  if (error) {
    return (
      <div
        role="alert"
        className="rounded-md border border-destructive/30 bg-destructive/5 p-4 flex items-center justify-between"
      >
        <span className="text-sm text-destructive">
          {t("supervision.table.error")} : {error.message}
        </span>
        <Button size="sm" variant="outline" onClick={onRetry}>
          {t("supervision.table.retry")}
        </Button>
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-[110px]">{t("supervision.table.col.status")}</TableHead>
          <TableHead>{t("supervision.table.col.mission")}</TableHead>
          <TableHead>{t("supervision.table.col.agent")}</TableHead>
          <TableHead>{t("supervision.table.col.session")}</TableHead>
          <TableHead className="w-[140px]">{t("supervision.table.col.last_activity")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading
          ? [0, 1, 2, 3, 4].map((i) => (
              <TableRow key={`sk-${i}`} data-skeleton-row>
                <TableCell colSpan={5}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            ))
          : filtered.length === 0
          ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-sm text-muted-foreground py-8">
                  {t("supervision.table.empty")}
                </TableCell>
              </TableRow>
            )
          : filtered.map((row) => (
              <TableRow
                key={row.id}
                role="button"
                tabIndex={0}
                onClick={() => onSelect(row.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(row.id);
                  }
                }}
                className={cn(
                  "cursor-pointer hover:bg-muted/50",
                  row.destroyed_at && "opacity-60",
                )}
              >
                <TableCell><StatusBadge status={row.destroyed_at ? "destroyed" : row.status} /></TableCell>
                <TableCell className={cn(!row.mission && "text-muted-foreground")}>
                  {row.mission ?? t("supervision.table.no_mission")}
                </TableCell>
                <TableCell className="font-mono text-xs">{row.agent_id}</TableCell>
                <TableCell className="font-mono text-xs">{row.session_id.slice(0, 8)}…</TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatRelative(row.last_activity_at)}
                </TableCell>
              </TableRow>
            ))}
      </TableBody>
    </Table>
  );
}
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionInstancesTable.test.tsx`
- [ ] Attendu : **6 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`

### Step 6 — Commit

```bash
git add frontend/src/components/supervision/SupervisionInstancesTable.tsx \
         frontend/src/components/supervision/__tests__/SupervisionInstancesTable.test.tsx
git commit -m "feat(supervision-ui): SupervisionInstancesTable (filtre+tri+skeleton+error)"
```

---

## Tâche 8 — `SupervisionInstanceDrawer.tsx`

**Files:**
- Create: `frontend/src/components/supervision/SupervisionInstanceDrawer.tsx`
- Test: `frontend/src/components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx`

### Step 1 — Écrire le test

- [ ] Créer `frontend/src/components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx` :

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionInstanceDrawer } from "../SupervisionInstanceDrawer";
import { supervisionApi, type InstanceDetail } from "@/lib/supervisionApi";

vi.mock("@/lib/supervisionApi", async () => {
  const real = await vi.importActual<typeof import("@/lib/supervisionApi")>(
    "@/lib/supervisionApi",
  );
  return { ...real, supervisionApi: { ...real.supervisionApi, getInstance: vi.fn() } };
});

const detail: InstanceDetail = {
  id: "11111111-1111-1111-1111-111111111111",
  session_id: "22222222-2222-2222-2222-222222222222",
  agent_id: "claude-code-r1",
  mission: "refactor auth",
  status: "busy",
  last_activity_at: "2026-05-17T10:00:00Z",
  created_at: "2026-05-17T09:00:00Z",
  destroyed_at: null,
  error_message: null,
  last_container_name: "agent-abc",
  container_status: "running",
  labels: { role: "developer" },
  mom_counts: { pending: 0, claimed: 3, failed: 0 },
  recent_messages: [
    { msg_id: "m1", direction: "in", kind: "instruction", payload: "go", created_at: "2026-05-17T09:50:00Z" },
    { msg_id: "m2", direction: "out", kind: "event", payload: "ack", created_at: "2026-05-17T09:55:00Z" },
  ],
};

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>
    </QueryClientProvider>
  );
}

describe("SupervisionInstanceDrawer", () => {
  beforeEach(() => {
    (supervisionApi.getInstance as ReturnType<typeof vi.fn>).mockResolvedValue(detail);
  });

  it("rend le détail quand instanceId est fourni", async () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={detail.id} onClose={() => {}} />));
    expect(await screen.findByText("refactor auth")).toBeInTheDocument();
    expect(screen.getByText("agent-abc")).toBeInTheDocument();
    expect(screen.getByText(/running/i)).toBeInTheDocument();
  });

  it("ne fetch pas si instanceId est null", () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={null} onClose={() => {}} />));
    expect(supervisionApi.getInstance).not.toHaveBeenCalled();
  });

  it("affiche les labels JSON", async () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={detail.id} onClose={() => {}} />));
    await screen.findByText("refactor auth");
    expect(screen.getByText(/"role"/)).toBeInTheDocument();
  });

  it("affiche les recent_messages", async () => {
    render(wrap(<SupervisionInstanceDrawer instanceId={detail.id} onClose={() => {}} />));
    await screen.findByText("refactor auth");
    expect(screen.getByText("instruction")).toBeInTheDocument();
    expect(screen.getByText("event")).toBeInTheDocument();
  });
});
```

### Step 2 — Lancer (fail)

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx`
- [ ] Attendu : `Cannot find module '../SupervisionInstanceDrawer'`.

### Step 3 — Écrire `frontend/src/components/supervision/SupervisionInstanceDrawer.tsx`

- [ ] Créer le fichier :

```tsx
import { useTranslation } from "react-i18next";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useInstanceDetail } from "@/hooks/useSupervision";
import type { InstanceDetail } from "@/lib/supervisionApi";

interface Props {
  instanceId: string | null;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <div className="text-sm">{children}</div>
    </div>
  );
}

function MessageRow({ m }: { m: Record<string, unknown> }) {
  const dir = m.direction as string;
  const arrow = dir === "in" ? "→" : "←";
  const time = typeof m.created_at === "string"
    ? new Date(m.created_at).toLocaleTimeString()
    : "";
  return (
    <div className="flex items-start gap-2 text-xs font-mono">
      <span className="text-muted-foreground w-12 shrink-0">{time}</span>
      <span className="w-3 text-muted-foreground">{arrow}</span>
      <span className="w-20 text-muted-foreground truncate">{m.kind as string}</span>
      <span className="flex-1 truncate">{JSON.stringify(m.payload)}</span>
    </div>
  );
}

function DetailBody({ data }: { data: InstanceDetail }) {
  const { t } = useTranslation();
  return (
    <div className="px-6 py-4 space-y-5">
      <Section title={t("supervision.drawer.section.mission")}>
        {data.mission ? (
          <span>« {data.mission} »</span>
        ) : (
          <span className="text-muted-foreground">{t("supervision.table.no_mission")}</span>
        )}
      </Section>

      <Section title={t("supervision.drawer.section.container")}>
        <div className="flex items-center gap-2">
          <code className="text-xs">{data.last_container_name ?? "—"}</code>
          {data.container_status && (
            <Badge variant="outline" className="text-xs">
              {data.container_status}
            </Badge>
          )}
        </div>
      </Section>

      <Section title={t("supervision.drawer.section.labels")}>
        <pre className="text-xs bg-muted/50 rounded p-2 overflow-x-auto">
          {JSON.stringify(data.labels, null, 2)}
        </pre>
      </Section>

      <Section title={t("supervision.drawer.section.mom")}>
        <div className="flex gap-4 text-xs">
          <span>{t("supervision.kpi.mom.pending")}: <strong>{data.mom_counts.pending}</strong></span>
          <span>{t("supervision.kpi.mom.claimed")}: <strong>{data.mom_counts.claimed}</strong></span>
          <span className={cn(data.mom_counts.failed > 0 && "text-destructive")}>
            {t("supervision.kpi.mom.failed")}: <strong>{data.mom_counts.failed}</strong>
          </span>
        </div>
      </Section>

      <Separator />

      <Section title={t("supervision.drawer.section.messages")}>
        {data.recent_messages.length === 0 ? (
          <span className="text-muted-foreground text-xs">—</span>
        ) : (
          <div className="space-y-1">
            {data.recent_messages.map((m, idx) => (
              <MessageRow key={(m.msg_id as string) ?? idx} m={m} />
            ))}
          </div>
        )}
      </Section>

      {data.error_message && (
        <Section title={t("supervision.drawer.section.error")}>
          <pre className="text-xs text-destructive whitespace-pre-wrap">
            {data.error_message}
          </pre>
        </Section>
      )}
    </div>
  );
}

export function SupervisionInstanceDrawer({ instanceId, onClose }: Props) {
  const { t } = useTranslation();
  const q = useInstanceDetail(instanceId);
  const open = !!instanceId;

  return (
    <Sheet open={open} onOpenChange={(o) => (!o ? onClose() : null)}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>
            {q.data?.agent_id ?? t("supervision.page_title")}
          </SheetTitle>
          <SheetDescription>
            {q.data?.session_id?.slice(0, 8) ?? ""}
          </SheetDescription>
        </SheetHeader>

        {q.isLoading && (
          <div className="p-6 space-y-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        )}

        {q.error && (
          <div role="alert" className="p-6 text-sm text-destructive">
            {t("supervision.drawer.not_found")}
          </div>
        )}

        {q.data && <DetailBody data={q.data} />}
      </SheetContent>
    </Sheet>
  );
}
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd frontend && npm test -- src/components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx`
- [ ] Attendu : **4 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`

### Step 6 — Commit

```bash
git add frontend/src/components/supervision/SupervisionInstanceDrawer.tsx \
         frontend/src/components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx
git commit -m "feat(supervision-ui): SupervisionInstanceDrawer (Sheet+sections détail)"
```

---

## Tâche 9 — `SupervisionPage.tsx` (assembleur + URL state)

**Files:**
- Create: `frontend/src/pages/SupervisionPage.tsx`
- Test: `frontend/src/pages/__tests__/SupervisionPage.test.tsx`

### Step 1 — Écrire le test

- [ ] Créer `frontend/src/pages/__tests__/SupervisionPage.test.tsx` :

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionPage } from "../SupervisionPage";
import { supervisionApi } from "@/lib/supervisionApi";

vi.mock("@/lib/supervisionApi", async () => {
  const real = await vi.importActual<typeof import("@/lib/supervisionApi")>(
    "@/lib/supervisionApi",
  );
  return {
    ...real,
    supervisionApi: {
      ...real.supervisionApi,
      getOverview: vi.fn().mockResolvedValue({
        sessions: { active: 1, closed: 0, expired: 0 },
        agents: { idle: 0, busy: 1, error: 0, destroyed_total: 0 },
        containers_running: 2,
        mom: { pending: 0, claimed: 0, failed: 0 },
      }),
      listInstances: vi.fn().mockResolvedValue([
        {
          id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
          session_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
          agent_id: "claude-code-r1",
          mission: "refactor auth",
          status: "busy",
          last_activity_at: "2026-05-17T10:00:00Z",
          created_at: "2026-05-17T09:00:00Z",
          destroyed_at: null,
          error_message: null,
          last_container_name: "agent-abc",
        },
      ]),
      getInstance: vi.fn().mockResolvedValue({
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        agent_id: "claude-code-r1",
        mission: "refactor auth",
        status: "busy",
        last_activity_at: "2026-05-17T10:00:00Z",
        created_at: "2026-05-17T09:00:00Z",
        destroyed_at: null,
        error_message: null,
        last_container_name: "agent-abc",
        container_status: "running",
        labels: {},
        mom_counts: { pending: 0, claimed: 0, failed: 0 },
        recent_messages: [],
      }),
    },
  };
});

function renderWithUrl(initialUrl: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <QueryClientProvider client={client}>
        <I18nextProvider i18n={i18n}>
          <SupervisionPage />
        </I18nextProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("SupervisionPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("ouvre le drawer quand ?instance=<id> est dans l'URL", async () => {
    renderWithUrl("/supervision?instance=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
    expect(await screen.findByText("refactor auth")).toBeInTheDocument();
    expect(supervisionApi.getInstance).toHaveBeenCalledWith(
      "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    );
  });

  it("clic sur une ligne ajoute ?instance=<id> et fetch le détail", async () => {
    renderWithUrl("/supervision");
    const row = await screen.findByText(/refactor auth/);
    fireEvent.click(row.closest("tr")!);
    // Le drawer doit déclencher le fetch du détail
    expect(supervisionApi.getInstance).toHaveBeenCalledWith(
      "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    );
  });
});
```

### Step 2 — Lancer (fail)

- [ ] Lancer : `cd frontend && npm test -- src/pages/__tests__/SupervisionPage.test.tsx`
- [ ] Attendu : `Cannot find module '../SupervisionPage'`.

### Step 3 — Écrire `frontend/src/pages/SupervisionPage.tsx`

- [ ] Créer le fichier :

```tsx
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Activity, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import { SupervisionKpiCards } from "@/components/supervision/SupervisionKpiCards";
import { SupervisionFilters, type Filters } from "@/components/supervision/SupervisionFilters";
import { SupervisionInstancesTable } from "@/components/supervision/SupervisionInstancesTable";
import { SupervisionInstanceDrawer } from "@/components/supervision/SupervisionInstanceDrawer";
import { useOverview, useInstances } from "@/hooks/useSupervision";

export function SupervisionPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();

  const instanceId = searchParams.get("instance");

  const [filters, setFilters] = useState<Filters>({
    status: "all",
    search: "",
    includeDestroyed: false,
  });

  const overview = useOverview();
  const instances = useInstances({
    status: filters.status === "all" ? undefined : filters.status,
    includeDestroyed: filters.includeDestroyed,
  });

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["supervision"] });

  const selectInstance = (id: string) => {
    setSearchParams((prev) => {
      prev.set("instance", id);
      return prev;
    });
  };
  const closeDrawer = () => {
    setSearchParams((prev) => {
      prev.delete("instance");
      return prev;
    });
  };

  return (
    <PageShell>
      <PageHeader
        title={t("supervision.page_title")}
        subtitle={t("supervision.subtitle")}
        icon={Activity}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            aria-label={t("supervision.refresh")}
          >
            <RotateCw className="h-4 w-4 mr-1" /> {t("supervision.refresh")}
          </Button>
        }
      />

      <div className="space-y-6">
        <SupervisionKpiCards data={overview.data} />

        <div className="space-y-3">
          <SupervisionFilters value={filters} onChange={setFilters} />

          <SupervisionInstancesTable
            instances={instances.data}
            filters={filters}
            isLoading={instances.isLoading}
            error={instances.error as Error | null}
            onSelect={selectInstance}
            onRetry={() => instances.refetch()}
          />
        </div>
      </div>

      <SupervisionInstanceDrawer instanceId={instanceId} onClose={closeDrawer} />
    </PageShell>
  );
}
```

### Step 4 — Vérifier signature `PageHeader`

- [ ] Lancer : `grep -n "interface\\|type\\|export function PageHeader" frontend/src/components/layout/PageHeader.tsx | head -10`
- [ ] Si `PageHeader` n'accepte pas les props `icon` ou `actions`, soit on adapte (lire le composant), soit on l'enrichit (préférer adapter en se conformant au pattern existant). Vérifier comment d'autres pages utilisent les actions (ex: `BackupsPage.tsx`).

### Step 5 — Re-lancer le test

- [ ] Lancer : `cd frontend && npm test -- src/pages/__tests__/SupervisionPage.test.tsx`
- [ ] Attendu : **2 tests PASS**.

### Step 6 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`

### Step 7 — Commit

```bash
git add frontend/src/pages/SupervisionPage.tsx \
         frontend/src/pages/__tests__/SupervisionPage.test.tsx
git commit -m "feat(supervision-ui): SupervisionPage (assembleur + URL state ?instance=)"
```

---

## Tâche 10 — Activation route + sidebar

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx:116`

### Step 1 — Activer la route dans `App.tsx`

- [ ] Lancer : `grep -n "import.*SessionsPage\\|import.*SupervisionPage\\|/sessions.*element" frontend/src/App.tsx | head -10`
- [ ] Repérer le bloc d'imports de pages et le bloc de routes.
- [ ] Ajouter l'import (à côté des autres pages) :
  ```tsx
  import { SupervisionPage } from "@/pages/SupervisionPage";
  ```
- [ ] Ajouter la route dans le `<Routes>` (à proximité de `/sessions`) :
  ```tsx
  <Route path="/supervision" element={<SupervisionPage />} />
  ```

### Step 2 — Retirer `disabled: true` dans `Sidebar.tsx`

- [ ] Ouvrir `frontend/src/components/layout/Sidebar.tsx`.
- [ ] Ligne 116 (ou approchant), remplacer :
  ```tsx
  { to: "/supervision", label: t("sidebar.supervision"), icon: Activity, disabled: true },
  ```
  par :
  ```tsx
  { to: "/supervision", label: t("sidebar.supervision"), icon: Activity },
  ```

### Step 3 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 4 — Test complet Vitest

- [ ] Lancer : `cd frontend && npm test`
- [ ] Attendu : tous les tests existants + les 26 nouveaux passent.

### Step 5 — Commit

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(supervision-ui): activation route /supervision + sidebar"
```

---

## Tâche 11 — Validation E2E sur LXC fresh

**Files:** Aucun (validation runtime).

### Step 1 — Vérifier le commit history complet

- [ ] Lancer : `git log --oneline dev ^main | head -20`
- [ ] Attendu : ~10 commits préfixés `feat(supervision-ui|api|hooks|i18n)` + 1 `feat(ui): Sheet`.

### Step 2 — Push origin/dev

- [ ] Lancer : `git push origin dev`
- [ ] Vérifier que la branche distante est à jour.

### Step 3 — Lancer run-test.sh

- [ ] Lancer : `./scripts/run-test.sh`
- [ ] Attendu :
  - LXC fresh créé
  - Code déployé via git pull
  - 8 assertions du smoke kit OK
  - pytest backend complet vert (790+ passed)
  - Build frontend OK (TypeScript strict)

### Step 4 — Smoke métier manuel

- [ ] Récupérer l'IP du LXC fresh (visible dans la sortie run-test.sh).
- [ ] Se logger sur `http://<IP>/login` (admin@agflow.example.com / mot de passe affiché en fin de run-test.sh).
- [ ] Naviguer vers `/supervision`. Vérifier :
  - 4 cards KPI affichées avec chiffres (probablement 0 partout — env vierge)
  - Table affiche "Aucune instance active..." (état vide)
  - Bouton "Rafraîchir" en haut à droite cliquable
  - Sidebar : item "Supervision" actif (non disabled)
- [ ] (Optionnel — si une session existe) cliquer sur une ligne → drawer s'ouvre, URL devient `?instance=<id>`.
- [ ] Vérifier console navigateur : 0 erreur (sauf 401/403 attendus quand non admin).

### Step 5 — Cleanup LXC

- [ ] Lancer : `ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"` (CTID visible dans la sortie run-test.sh).
- [ ] Vérifier : `ssh pve "pct list"` ne liste plus le CTID.

### Step 6 — Mettre à jour la mémoire des modules

- [ ] Mettre à jour `C:\Users\g.beard\.claude\projects\E--srcs-agflow-docker\memory\project_modules_status.md` : passer M6 de "INCOMPLET (~75% fait)" à "Phase 2a COMPLETE" et noter qu'il reste 2b (WS push) et 2c (actions kill/restart) à scoper si besoin.

---

## Récapitulatif

**~10 commits livrés :**

1. `feat(ui): composant Sheet shadcn (Dialog Radix stylé latéral)`
2. `feat(supervision-api): types Zod + 3 fonctions (overview/list/get)`
3. `feat(supervision-hooks): 3 queries TanStack + merge alive+destroyed`
4. `feat(supervision-i18n): bloc supervision.* FR+EN (35 clés)`
5. `feat(supervision-ui): SupervisionKpiCards (4 cards + tones sévérité)`
6. `feat(supervision-ui): SupervisionFilters (status + search + toggle destroyed)`
7. `feat(supervision-ui): SupervisionInstancesTable (filtre+tri+skeleton+error)`
8. `feat(supervision-ui): SupervisionInstanceDrawer (Sheet+sections détail)`
9. `feat(supervision-ui): SupervisionPage (assembleur + URL state ?instance=)`
10. `feat(supervision-ui): activation route /supervision + sidebar`

**~26 nouveaux tests** Vitest (4 api + 3 hooks + 4 KPI + 3 filters + 6 table + 4 drawer + 2 page).

**Wall time estimé :** 3-4 jours en mode pipeline allégé.

**Aucune modification backend** — la Phase 1 (migration 083 + workers + endpoints) couvre tout ce qui est nécessaire.

**Hors scope explicite (Phases ultérieures) :** WebSocket push (2b), actions kill/restart (2c), graphes/tendances (2d).
