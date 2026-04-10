# Wizard Step 3 Enriched — Chat Onboarding + Workflow Selection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After selecting a project type in step 3, the user can choose an onboarding chat and select workflows, with a horizontal phase timeline preview. All choices persist in create-project.json.

**Architecture:** Extend backend `ProjectTypeResponse` with `chats` field. Enrich `ProjectTypeSelector` frontend component with two new collapsible sections (Chat + Workflows) that appear after type selection. Persist all selections to `create-project.json` step_id:3.

**Tech Stack:** FastAPI/Pydantic (backend schema), React/TypeScript/Tailwind (frontend), existing wizard persistence API.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `hitl/schemas/project_type.py` | Add `ChatTemplate` model, add `chats` to `ProjectTypeResponse` |
| Modify | `hitl/services/project_type_service.py:57-80` | Include chats from project.json in response |
| Modify | `hitl-frontend/src/api/types.ts:552-558` | Add `ChatTemplate` interface, extend `ProjectTypeResponse` |
| Modify | `hitl-frontend/src/components/features/project/ProjectTypeSelector.tsx` | Add chat selector + workflow selector sections |
| Modify | `hitl-frontend/src/components/features/project/WizardShell.tsx` | Add state for selectedChatId/selectedWorkflowIds, persist to wizard data |

---

### Task 1: Backend — Add chats to ProjectTypeResponse

**Files:**
- Modify: `hitl/schemas/project_type.py`
- Modify: `hitl/services/project_type_service.py`

- [ ] **Step 1: Add ChatTemplate model to schema**

In `hitl/schemas/project_type.py`, add before `ProjectTypeResponse`:

```python
class ChatTemplate(BaseModel):
    """A chat definition within a project type."""

    id: str
    type: str = ""
    agents: list[str] = Field(default_factory=list)
    source_prompt: str = ""
```

Then add `chats` field to `ProjectTypeResponse`:

```python
class ProjectTypeResponse(BaseModel):
    """A project type read from Shared/Projects/*/project.json."""

    id: str
    name: str
    description: str = ""
    team: str = ""
    workflows: list[WorkflowTemplate] = Field(default_factory=list)
    chats: list[ChatTemplate] = Field(default_factory=list)
```

- [ ] **Step 2: Include chats in _build_project_type**

In `hitl/services/project_type_service.py`, modify `_build_project_type` to build chats from project.json data. After the workflows loop (line ~73), add:

```python
    chats_cfg = data.get("chats", [])
    chats: list[ChatTemplate] = []
    for c in chats_cfg:
        chats.append(ChatTemplate(
            id=c.get("id", ""),
            type=c.get("type", ""),
            agents=c.get("agents", []),
            source_prompt=c.get("source_prompt", ""),
        ))
```

And update the return statement to include `chats=chats`:

```python
    return ProjectTypeResponse(
        id=type_id,
        name=data.get("name", type_id),
        description=data.get("description", ""),
        team=data.get("team", ""),
        workflows=workflows,
        chats=chats,
    )
```

Don't forget to import `ChatTemplate` at the top of the service file:

```python
from schemas.project_type import (
    ChatTemplate,
    PhaseFileContentResponse,
    ...
)
```

- [ ] **Step 3: Commit**

```bash
git add hitl/schemas/project_type.py hitl/services/project_type_service.py
git commit -m "feat(hitl): ajouter chats dans ProjectTypeResponse"
```

---

### Task 2: Frontend — Add ChatTemplate type

**Files:**
- Modify: `hitl-frontend/src/api/types.ts`

- [ ] **Step 1: Add ChatTemplate interface and extend ProjectTypeResponse**

In `hitl-frontend/src/api/types.ts`, add before `ProjectTypeResponse` (around line 552):

```typescript
export interface ChatTemplate {
  id: string;
  type: string;
  agents: string[];
  source_prompt: string;
}
```

Then extend `ProjectTypeResponse` to include chats:

```typescript
export interface ProjectTypeResponse {
  id: string;
  name: string;
  description: string;
  team: string;
  workflows: WorkflowTemplate[];
  chats: ChatTemplate[];
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/api/types.ts
git commit -m "feat(hitl): type ChatTemplate + chats dans ProjectTypeResponse"
```

---

### Task 3: Frontend — Enrich ProjectTypeSelector with Chat + Workflow sections

**Files:**
- Modify: `hitl-frontend/src/components/features/project/ProjectTypeSelector.tsx`

This is the main UI task. After the user selects a type, two new sections appear:

1. **Chat onboarding** — grid of cards (same style as project type cards) showing chats from the selected type
2. **Workflows** — grid of cards showing workflows, clicking one expands a horizontal phase timeline below

- [ ] **Step 1: Update the component props to support new selections**

Replace the entire `ProjectTypeSelector.tsx` with:

```tsx
import { useEffect, useMemo, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../ui/Button';
import { Badge } from '../../ui/Badge';
import { Spinner } from '../../ui/Spinner';
import { ProjectTypeCard } from './ProjectTypeCard';
import { WorkflowBlock } from './WorkflowBlock';
import type { PhaseInfo } from './WorkflowBlock';
import * as projectTypesApi from '../../../api/projectTypes';
import type { ProjectTypeResponse, ChatTemplate, WorkflowTemplate } from '../../../api/types';

interface ProjectTypeSelectorProps {
  selectedTypeId: string | null;
  selectedChatId: string | null;
  selectedWorkflowIds: string[];
  onSelect: (typeId: string | null, chatId: string | null, workflowIds: string[], workflowFilename?: string) => void;
  className?: string;
}

export function ProjectTypeSelector({
  selectedTypeId,
  selectedChatId,
  selectedWorkflowIds,
  onSelect,
  className = '',
}: ProjectTypeSelectorProps): JSX.Element {
  const { t } = useTranslation();
  const [types, setTypes] = useState<ProjectTypeResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedWfIdx, setExpandedWfIdx] = useState<number | null>(null);
  const [phasesMap, setPhasesMap] = useState<Record<string, PhaseInfo[]>>({});

  useEffect(() => {
    setLoading(true);
    projectTypesApi
      .listProjectTypes()
      .then(setTypes)
      .catch(() => setTypes([]))
      .finally(() => setLoading(false));
  }, []);

  const selectedType = useMemo(
    () => types.find((pt) => pt.id === selectedTypeId) ?? null,
    [types, selectedTypeId],
  );

  // Load phases for all workflows of the selected type
  useEffect(() => {
    if (!selectedType) {
      setPhasesMap({});
      return;
    }
    let cancelled = false;
    async function loadPhases() {
      const map: Record<string, PhaseInfo[]> = {};
      for (const wf of selectedType!.workflows) {
        try {
          const files = await projectTypesApi.fetchPhaseFiles(selectedType!.id, wf.filename);
          map[wf.filename] = files.map((f, idx) => ({
            id: f.phase_id,
            name: f.phase_id.replace(/_/g, ' '),
            order: idx + 1,
            agents: [],
            deliverables: [],
            humanGate: false,
          }));
        } catch {
          map[wf.filename] = [];
        }
      }
      if (!cancelled) setPhasesMap(map);
    }
    loadPhases();
    return () => { cancelled = true; };
  }, [selectedType]);

  const handleTypeSelect = useCallback((typeId: string) => {
    const pt = types.find((t) => t.id === typeId);
    const wf = pt?.workflows[0];
    // Auto-select all workflows
    const wfIds = pt?.workflows.map((w) => w.filename) ?? [];
    onSelect(typeId, null, wfIds, wf?.filename);
    setExpandedWfIdx(null);
  }, [types, onSelect]);

  const handleChatSelect = useCallback((chatId: string) => {
    const newChatId = chatId === selectedChatId ? null : chatId;
    onSelect(selectedTypeId, newChatId, selectedWorkflowIds);
  }, [selectedTypeId, selectedChatId, selectedWorkflowIds, onSelect]);

  const handleWorkflowToggle = useCallback((filename: string) => {
    const newIds = selectedWorkflowIds.includes(filename)
      ? selectedWorkflowIds.filter((id) => id !== filename)
      : [...selectedWorkflowIds, filename];
    onSelect(selectedTypeId, selectedChatId, newIds);
  }, [selectedTypeId, selectedChatId, selectedWorkflowIds, onSelect]);

  if (loading) {
    return (
      <div className={`flex justify-center py-8 ${className}`}>
        <Spinner />
      </div>
    );
  }

  if (types.length === 0) {
    return (
      <div className={`text-center py-8 ${className}`}>
        <p className="text-sm text-content-tertiary">{t('project_type.no_types')}</p>
        <Button variant="ghost" size="sm" onClick={() => onSelect(null, null, [])} className="mt-3">
          {t('project_type.skip')}
        </Button>
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-6 ${className}`}>
      {/* Section 1: Project Type */}
      <div>
        <h3 className="text-sm font-semibold text-content-secondary mb-3">
          {t('project_type.select_type')}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {types.map((pt) => (
            <ProjectTypeCard
              key={pt.id}
              projectType={pt}
              selected={selectedTypeId === pt.id}
              onSelect={handleTypeSelect}
            />
          ))}
        </div>
      </div>

      {/* Section 2: Chat Onboarding (visible after type selection) */}
      {selectedType && selectedType.chats.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-content-secondary mb-3">
            {t('project_type.select_chat')}
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {selectedType.chats.map((chat) => (
              <button
                key={chat.id}
                onClick={() => handleChatSelect(chat.id)}
                className={[
                  'flex flex-col gap-2 rounded-xl border-2 p-4 text-left transition-all',
                  'hover:border-accent-blue/60 hover:bg-surface-hover',
                  selectedChatId === chat.id
                    ? 'border-accent-blue bg-accent-blue/5'
                    : 'border-border bg-surface-secondary',
                ].join(' ')}
              >
                <h4 className="text-sm font-semibold text-content-primary">
                  {chat.id.replace(/_/g, ' ')}
                </h4>
                <p className="text-xs text-content-tertiary">
                  {chat.type}
                </p>
                <div className="flex flex-wrap gap-1 mt-auto pt-2">
                  {chat.agents.map((a) => (
                    <Badge key={a} color="blue" size="sm">{a}</Badge>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Section 3: Workflows (visible after type selection) */}
      {selectedType && selectedType.workflows.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-content-secondary mb-3">
            {t('project_type.select_workflows')}
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {selectedType.workflows.map((wf, i) => (
              <button
                key={wf.filename}
                onClick={() => handleWorkflowToggle(wf.filename)}
                className={[
                  'flex flex-col gap-2 rounded-xl border-2 p-4 text-left transition-all',
                  'hover:border-accent-blue/60 hover:bg-surface-hover',
                  selectedWorkflowIds.includes(wf.filename)
                    ? 'border-accent-blue bg-accent-blue/5'
                    : 'border-border bg-surface-secondary',
                ].join(' ')}
              >
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-content-primary truncate">
                    {wf.name}
                  </h4>
                  <span
                    className="text-xs text-accent-blue cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedWfIdx(expandedWfIdx === i ? null : i);
                    }}
                  >
                    {expandedWfIdx === i ? '▼' : '▶'}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge color={wf.mode === 'sequential' ? 'green' : 'red'} size="sm">
                    {wf.mode}
                  </Badge>
                  <Badge color="purple" size="sm">
                    prio: {wf.priority}
                  </Badge>
                </div>
              </button>
            ))}
          </div>

          {/* Phase timeline for expanded workflow */}
          {expandedWfIdx !== null && selectedType.workflows[expandedWfIdx] && (
            <div className="mt-3">
              <WorkflowBlock
                typeId={selectedType.id}
                workflow={selectedType.workflows[expandedWfIdx]}
                expanded={true}
                onToggle={() => setExpandedWfIdx(null)}
                phases={phasesMap[selectedType.workflows[expandedWfIdx].filename] ?? []}
              />
            </div>
          )}
        </div>
      )}

      <Button variant="ghost" size="sm" onClick={() => onSelect(null, null, [])} className="self-start">
        {t('project_type.skip')}
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add hitl-frontend/src/components/features/project/ProjectTypeSelector.tsx
git commit -m "feat(hitl): sections chat onboarding + workflows dans ProjectTypeSelector"
```

---

### Task 4: WizardShell — Wire new state + persistence

**Files:**
- Modify: `hitl-frontend/src/components/features/project/WizardShell.tsx`

- [ ] **Step 1: Add new state variables**

After `const [selectedWorkflowFilename, setSelectedWorkflowFilename] = useState<string>('');` (line 48), add:

```typescript
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [selectedWorkflowIds, setSelectedWorkflowIds] = useState<string[]>([]);
```

- [ ] **Step 2: Update the ProjectTypeSelector rendering (step 3)**

Replace the step 3 block (lines 173-180):

```tsx
        {wizardStep === 3 && (
          <ProjectTypeSelector
            selectedTypeId={selectedTypeId}
            selectedChatId={selectedChatId}
            selectedWorkflowIds={selectedWorkflowIds}
            onSelect={(typeId, chatId, workflowIds, workflowFilename) => {
              setSelectedTypeId(typeId);
              setSelectedChatId(chatId ?? null);
              setSelectedWorkflowIds(workflowIds ?? []);
              if (workflowFilename) setSelectedWorkflowFilename(workflowFilename);
            }}
          />
        )}
```

- [ ] **Step 3: Update handleNext step 3 persistence**

Replace the `if (wizardStep === 3 && selectedTypeId)` block (lines 118-137) with:

```typescript
    if (wizardStep === 3 && selectedTypeId) {
      setCreating(true);
      setError(null);
      try {
        const result = await projectTypesApi.applyProjectType(
          wizardData.slug, selectedTypeId, selectedWorkflowFilename,
        );
        updateWizardData({ orchestratorPrompt: result.orchestrator_prompt });
        void wizardDataApi.saveWizardStep(wizardData.slug, 3, {
          selectedTypeId,
          selectedChatId,
          selectedWorkflowIds,
          workflowFilename: selectedWorkflowFilename,
          orchestratorPrompt: result.orchestrator_prompt,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setCreating(false);
        return;
      }
      setCreating(false);
    }
```

- [ ] **Step 4: Restore selections on resume**

In the WizardShell, find where wizard data is restored on mount (look for `getWizardData` or resume logic). Add restoration of the new fields. If there's a useEffect that loads wizard data, add after existing restoration:

```typescript
const step3 = steps.find((s) => s.step_id === 3);
if (step3?.data) {
  if (step3.data.selectedTypeId) setSelectedTypeId(step3.data.selectedTypeId as string);
  if (step3.data.selectedChatId) setSelectedChatId(step3.data.selectedChatId as string);
  if (step3.data.selectedWorkflowIds) setSelectedWorkflowIds(step3.data.selectedWorkflowIds as string[]);
  if (step3.data.workflowFilename) setSelectedWorkflowFilename(step3.data.workflowFilename as string);
}
```

Check `ProjectWizardPage.tsx` and `projectStore.ts` for the resume flow to find the exact location.

- [ ] **Step 5: Update useCallback dependency array**

The `handleNext` useCallback dependencies must include `selectedChatId` and `selectedWorkflowIds`:

```typescript
  }, [wizardStep, wizardData, completed, selectedTypeId, selectedChatId, selectedWorkflowIds, selectedWorkflowFilename, markComplete, setWizardStep, navigate, resetWizard, loadProjects, updateWizardData, activeTeamId, teams]);
```

- [ ] **Step 6: Commit**

```bash
git add hitl-frontend/src/components/features/project/WizardShell.tsx
git commit -m "feat(hitl): persistence chat + workflows dans WizardShell step 3"
```

---

### Task 5: i18n keys

**Files:**
- Modify: `hitl-frontend/public/locales/fr/translation.json`
- Modify: `hitl-frontend/public/locales/en/translation.json`

- [ ] **Step 1: Add French keys**

In the `"project_type"` section, add:

```json
"select_chat": "Chat d'onboarding",
"select_workflows": "Workflows"
```

- [ ] **Step 2: Add English keys**

```json
"select_chat": "Onboarding chat",
"select_workflows": "Workflows"
```

- [ ] **Step 3: Commit**

```bash
git add hitl-frontend/public/locales/fr/translation.json hitl-frontend/public/locales/en/translation.json
git commit -m "feat(hitl): i18n keys pour chat + workflow selection"
```

---

### Task 6: Build + Deploy + Verify

- [ ] **Step 1: Build frontend**

```bash
cd hitl-frontend && npm run build
```

- [ ] **Step 2: Copy to hitl/static**

```bash
rm -rf hitl/static/assets && cp -r hitl-frontend/dist/* hitl/static/
```

- [ ] **Step 3: Deploy**

```bash
bash deploy.sh AGT1
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose up -d --build hitl-console"
```

- [ ] **Step 4: Verify**

1. Open HITL console, start new project wizard
2. Reach step 3 → select a project type
3. Verify chat onboarding section appears with cards
4. Select a chat → verify blue border
5. Verify workflows section appears with cards
6. Click workflow expand arrow → verify horizontal phase timeline
7. Click Next → verify all selections saved
8. Leave wizard, come back → verify selections restored
9. Check `create-project.json` on server: step_id:3 should contain `selectedTypeId`, `selectedChatId`, `selectedWorkflowIds`
