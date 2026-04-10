# Analysis Chat — Interactive Conversation with Team Orchestrator

## Context

The wizard step 6 "Analysis" (`WizardStepAnalysis.tsx`) is currently a passive display: it launches an analysis task via the dispatcher and shows progress events in a polling-based list. There is no interactivity — the user cannot respond to agent questions, send messages, or see HITL requests inline.

**Goal:** Transform the Analysis step into a real-time interactive chat where the user converses with the team's orchestrator. The orchestrator analyzes uploaded documents (via RAG), asks clarifying questions, delegates to specialized agents, and produces a structured project synthesis.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Thread ID pattern | `onboarding-{slug}` | More generic than `analysis-`, covers the full onboarding conversation scope. Breaking change — old `analysis-{slug}` data is not migrated (acceptable: feature was non-functional). |
| Free messages | Full (relaunch agent) | When no question is pending, cancel current task, relaunch agent with enriched context (previous conversation + new message) |
| Real-time strategy | WS + polling fallback | WebSocket for instant updates; polling `/conversation` every 5s when WS disconnected |
| WS backend changes | None | Frontend filters existing events by `thread_id` (for questions) and `task_id` (for progress/artifacts). No new WS event types. |
| Orchestrator resolution | Dynamic from registry | Read `agents_registry.json`, find agent with `type: "orchestrator"`. Never hardcoded. |

## Architecture

### Data Flow

```
User arrives at step 6
  |
  v
POST /api/projects/{slug}/analysis/start
  |
  v
analysis_service.start_analysis()
  1. Resolve orchestrator from agents_registry.json
  2. List uploaded documents
  3. Build instruction with RAG context
  4. POST to dispatcher /api/tasks/run
  5. Store task_id in pm_projects.analysis_task_id, set analysis_status='in_progress'
  6. Return { task_id, agent_id, status }
  |
  v
Dispatcher runs agent container
  |
  +-- ProgressEvent --> PG NOTIFY task_progress {task_id, data, team_id}
  |     --> WS broadcast to team --> Frontend filters by task_id --> Chat message
  |
  +-- QuestionEvent --> hitl_requests INSERT {thread_id, agent_id, team_id, prompt}
  |     --> PG NOTIFY hitl_request --> WS broadcast as "new_question" {thread_id, agent_id, prompt, id}
  |     --> Frontend filters by thread_id == "onboarding-{slug}" --> Shows question
  |     --> Backend sets analysis_status='waiting_input'
  |                                                    |
  |                                       User types reply in ChatInput
  |                                                    |
  |                                       POST /analysis/reply {request_id, response}
  |                                                    |
  |     hitl_requests UPDATE status='answered'
  |     --> PG NOTIFY hitl_response --> Dispatcher resumes
  |     --> WS broadcast "question_answered" {request_id} --> Frontend clears pendingQuestion
  |     --> Backend sets analysis_status='in_progress'
  |
  +-- ArtifactEvent --> PG NOTIFY task_artifact {task_id, key, team_id}
  |     --> WS broadcast --> Frontend filters by task_id
  |     --> GET /api/tasks/{task_id}/events to load artifact content
  |
  +-- ResultEvent --> Task status = 'success'|'failure'
        --> Backend sets analysis_status='completed'|'failed'
        --> Detected by next polling cycle or task_progress with terminal data
```

### Free Message Flow (No Pending Question)

```
User types message (no pending question)
  |
  v
POST /api/projects/{slug}/analysis/message { content }
  |
  v
analysis_service.send_free_message()
  1. Save message in rag_conversations
  2. If current task is running: cancel it via POST dispatcher /api/tasks/{task_id}/cancel
  3. Load full conversation history
  4. Build enriched instruction (original + conversation summary + new message)
     - Truncate to last 20 exchanges to stay within LLM context
  5. POST to dispatcher /api/tasks/run (new task, thread_id="onboarding-{slug}")
  6. Update pm_projects.analysis_task_id with new task_id
  7. Return { task_id, status: "started" }
  |
  v
Frontend updates taskId, filters new events
```

## Backend Changes

### SQL Schema

```sql
ALTER TABLE project.pm_projects
  ADD COLUMN IF NOT EXISTS analysis_task_id TEXT;
ALTER TABLE project.pm_projects
  ADD COLUMN IF NOT EXISTS analysis_status TEXT DEFAULT 'not_started'
    CHECK (analysis_status IN ('not_started', 'in_progress', 'waiting_input', 'completed', 'failed'));
```

### `analysis_status` State Transitions

| Transition | Triggered by | In function |
|------------|-------------|-------------|
| `not_started` -> `in_progress` | `start_analysis()` after dispatcher returns task_id | `analysis_service.start_analysis()` |
| `in_progress` -> `waiting_input` | `reply_to_question()` detects pending request exists | `analysis_service._sync_status()` called from `get_analysis_status()` |
| `waiting_input` -> `in_progress` | `reply_to_question()` answers the question | `analysis_service.reply_to_question()` |
| `in_progress` -> `completed` | `get_analysis_status()` polls dispatcher, sees task success | `analysis_service._sync_status()` |
| `in_progress` -> `failed` | `get_analysis_status()` polls dispatcher, sees task failure | `analysis_service._sync_status()` |
| `*` -> `in_progress` | `send_free_message()` relaunches agent | `analysis_service.send_free_message()` |

The `_sync_status()` helper is called by `get_analysis_status()` and queries the dispatcher for the current task state. If the dispatcher reports a terminal state (success/failure), it updates `analysis_status` in pm_projects. If `hitl_requests` has a pending row for this thread_id, it sets `waiting_input`.

### `hitl/services/analysis_service.py` — Rewrite

Functions:

| Function | Purpose |
|----------|---------|
| `start_analysis(slug, team_id, workflow_id=None)` | Resolve orchestrator, build instruction with RAG context, dispatch task, save task_id + set status |
| `get_analysis_status(slug)` | Read from pm_projects, sync with dispatcher, check pending questions. Returns `{ status, task_id, has_pending_question, pending_request_id }` |
| `get_conversation(slug)` | Merge 3 sources into chronological `AnalysisMessage` list |
| `reply_to_question(slug, request_id, response, reviewer)` | Verify thread_id match, answer via hitl route, save in rag_conversations, set status=in_progress. Returns 400 if thread mismatch. |
| `send_free_message(slug, content, user_email)` | Save message, cancel running task, relaunch with enriched context. Returns `{ task_id, status }` |
| `_resolve_orchestrator(team_id)` | Read agents_registry.json, find type=orchestrator. Raises 400 if not found. |
| `_build_instruction(slug, name, team_name, documents)` | Build initial orchestrator instruction |
| `_build_relaunch_instruction(slug, conversation, new_message)` | Build re-launch instruction, truncated to last 20 exchanges |
| `_sync_status(slug, task_id)` | Query dispatcher + hitl_requests, update analysis_status column |

### `hitl/routes/rag.py` — New/Modified Endpoints

| Method | Path | Body | Response | Purpose |
|--------|------|------|----------|---------|
| POST | `/api/projects/{slug}/analysis/start` | `{ workflow_id?: int }` (team_id resolved from project) | `{ task_id, agent_id, status }` | Start analysis |
| GET | `/api/projects/{slug}/analysis/status` | — | `{ status, task_id, has_pending_question, pending_request_id }` | Status with sync |
| GET | `/api/projects/{slug}/analysis/conversation` | — | `AnalysisMessage[]` | Merged conversation |
| POST | `/api/projects/{slug}/analysis/reply` | `{ request_id: str, response: str }` | `{ ok: true }` | Reply to question |
| POST | `/api/projects/{slug}/analysis/message` | `{ content: str }` | `{ task_id, status }` | Free message (relaunch) |

### Conversation Merge Logic

The `get_conversation()` function merges 3 data sources into a unified chronological list:

1. **dispatcher_task_events** (WHERE thread_id = `onboarding-{slug}`, via JOIN on dispatcher_tasks) — progress, artifact, result events
2. **hitl_requests** (WHERE thread_id = `onboarding-{slug}`) — questions from agent + their answers
3. **rag_conversations** (WHERE project_slug = slug) — user free messages

Query dispatcher events by joining `dispatcher_task_events` with `dispatcher_tasks` on `task_id`, filtering `WHERE dispatcher_tasks.thread_id = 'onboarding-{slug}'`. This captures events across all tasks for this thread (including relaunched tasks).

Each source maps to an `AnalysisMessage` (Pydantic v2):

```python
class AnalysisMessage(BaseModel):
    id: str
    sender: Literal["agent", "user", "system"]
    type: Literal["progress", "question", "reply", "artifact", "result", "system"]
    content: str
    request_id: str | None = None       # For questions (UUID, to reply)
    status: str | None = None            # For questions: pending, answered
    artifact_key: str | None = None      # For artifacts
    created_at: str                      # ISO 8601
```

Sort all by `created_at` ascending.

### Artifact Content Loading

When `get_conversation()` encounters an artifact event, it reads the artifact content from `dispatcher_task_artifacts.file_path` on disk (or from the `data` JSON field in `dispatcher_task_events`). The content is included inline in the `AnalysisMessage.content` field as Markdown. If the file is not found, content falls back to the event data summary.

The frontend does NOT make a separate API call for artifacts — they come pre-loaded in the conversation response.

## Frontend Changes

### TypeScript Types (`src/api/types.ts`)

```typescript
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

Keep existing `ConversationMessage` and `AnalysisStatusResponse` (old shape) for backward compatibility until all references are migrated.

### New Files

| File | Purpose |
|------|---------|
| `hitl-frontend/src/api/analysis.ts` | API functions: startAnalysis, getStatus, getConversation, reply, sendMessage |
| `hitl-frontend/src/stores/analysisStore.ts` | Zustand store: status, taskId, messages, pendingQuestion |
| `hitl-frontend/src/components/features/project/AnalysisChatMessage.tsx` | Single message renderer (dispatches by type) |
| `hitl-frontend/src/components/features/project/AnalysisQuestionBanner.tsx` | Banner above ChatInput when a question is pending |

### Modified Files

| File | Change |
|------|--------|
| `WizardStepAnalysis.tsx` | Full rewrite — interactive chat with WS + polling |
| `AnalysisChat.tsx` | Delete (replaced by WizardStepAnalysis internals) |
| `src/api/types.ts` | Add types above |

### `WizardStepAnalysis.tsx` — Behavior

**States:** `idle` | `starting` | `running` | `waiting_input` | `completed` | `failed`

1. **Mount:** GET `/analysis/status`
   - `not_started` -> show "Start analysis" button
   - `in_progress` / `waiting_input` -> load conversation via GET `/analysis/conversation`, resume real-time
   - `completed` -> show conversation read-only

2. **Start:** POST `/analysis/start` -> receive task_id -> state=running

3. **Real-time (WS connected):** Watch `wsStore.lastEvent` via `useEffect`:
   - `task_progress` where `event.data.task_id === taskId` -> add progress message
   - `new_question` where `event.data.thread_id === "onboarding-{slug}"` -> add question message, set pendingQuestion
   - `question_answered` where `event.data.request_id === pendingQuestion?.requestId` -> clear pendingQuestion
   - `task_artifact` where `event.data.task_id === taskId` -> trigger conversation reload (artifact content needs server-side loading)

4. **Polling fallback (WS disconnected):** Detect via `wsStore.connected === false`. Start interval polling GET `/analysis/conversation` every 5s. Reconcile by replacing messages array (server is source of truth). Deduplicate by `id`. Stop polling when WS reconnects.

5. **Reply:** When pendingQuestion exists and user submits:
   - POST `/analysis/reply { request_id, response }`
   - Optimistically add user message to chat, clear pendingQuestion

6. **Free message:** When no pendingQuestion and status is `running`:
   - POST `/analysis/message { content }`
   - Optimistically add user message + system message "Relance de l'agent..."
   - Receive new task_id from response, update store

7. **Input states:**
   - `pendingQuestion` -> placeholder i18n `analysis.reply_placeholder`, send button label "Repondre"
   - `running` (no question) -> placeholder i18n `analysis.message_placeholder`
   - `completed` / `failed` -> input disabled
   - `idle` -> input hidden, "Start" button shown
   - `starting` -> input hidden, spinner shown

### `AnalysisChatMessage.tsx` — Rendering by Type

Reuses `ChatBubble` for bubble layout and `MarkdownRenderer` for content.

| Type | Visual |
|------|--------|
| `progress` | Agent avatar + left-aligned bubble, gray background |
| `question` | Agent avatar + left bubble + orange border + "Question" badge. If status=pending: pulsing dot |
| `reply` | User avatar + right-aligned bubble, blue tint |
| `artifact` | Agent avatar + left bubble + card with MarkdownRenderer, max-h with expand toggle if > 300px |
| `result` | Agent avatar + left bubble + green "Complete" or red "Error" badge |
| `system` | Centered italic gray text, no bubble |

### `analysisStore.ts` — Zustand Store

```typescript
type AnalysisStatus = 'idle' | 'starting' | 'running' | 'waiting_input' | 'completed' | 'failed';

interface AnalysisStore {
  status: AnalysisStatus;
  taskId: string | null;
  threadId: string | null;           // "onboarding-{slug}" for WS filtering
  messages: AnalysisMessage[];
  pendingQuestion: { requestId: string; prompt: string } | null;

  setStatus(s: AnalysisStatus): void;
  setTaskId(id: string | null): void;
  setThreadId(id: string | null): void;
  addMessage(msg: AnalysisMessage): void;
  setMessages(msgs: AnalysisMessage[]): void;
  setPendingQuestion(q: { requestId: string; prompt: string } | null): void;
  reset(): void;
}
```

## i18n Keys

**French (fr):**
```json
{
  "analysis.title": "Analyse du projet",
  "analysis.start": "Lancer l'analyse",
  "analysis.starting": "Lancement de l'agent d'analyse...",
  "analysis.running": "L'agent analyse vos documents...",
  "analysis.waiting_input": "L'agent attend votre reponse",
  "analysis.completed": "Analyse terminee",
  "analysis.failed": "L'analyse a echoue",
  "analysis.reply_placeholder": "Repondez a la question...",
  "analysis.message_placeholder": "Envoyer un message a l'agent...",
  "analysis.relaunching": "Relance de l'agent avec votre message...",
  "analysis.no_orchestrator": "Aucun orchestrateur configure pour cette equipe",
  "analysis.no_documents": "Aucun document uploade",
  "analysis.question_badge": "Question",
  "analysis.artifact_badge": "Livrable",
  "analysis.result_success": "L'analyse est terminee. Vous pouvez passer a la suite.",
  "analysis.result_failure": "L'analyse a echoue. Vous pouvez relancer ou passer.",
  "analysis.relaunch": "Relancer l'analyse",
  "analysis.conversation_empty": "La conversation apparaitra ici une fois l'analyse lancee",
  "analysis.reconnecting": "Reconnexion en cours..."
}
```

**English (en):**
```json
{
  "analysis.title": "Project analysis",
  "analysis.start": "Start analysis",
  "analysis.starting": "Launching analysis agent...",
  "analysis.running": "Agent is analyzing your documents...",
  "analysis.waiting_input": "Agent is waiting for your response",
  "analysis.completed": "Analysis complete",
  "analysis.failed": "Analysis failed",
  "analysis.reply_placeholder": "Reply to the question...",
  "analysis.message_placeholder": "Send a message to the agent...",
  "analysis.relaunching": "Relaunching agent with your message...",
  "analysis.no_orchestrator": "No orchestrator configured for this team",
  "analysis.no_documents": "No documents uploaded",
  "analysis.question_badge": "Question",
  "analysis.artifact_badge": "Deliverable",
  "analysis.result_success": "Analysis complete. You can proceed to the next step.",
  "analysis.result_failure": "Analysis failed. You can retry or skip.",
  "analysis.relaunch": "Relaunch analysis",
  "analysis.conversation_empty": "The conversation will appear here once the analysis starts",
  "analysis.reconnecting": "Reconnecting..."
}
```

## Testing

### Backend (pytest)
- `test_start_analysis` — mock dispatcher, verify orchestrator resolved from registry, instruction built correctly
- `test_start_analysis_no_orchestrator` — 400 error when no orchestrator in registry
- `test_get_conversation` — correct merge of 3 sources in chronological order
- `test_reply_to_question` — answer saved + hitl_service called + status updated
- `test_reply_wrong_thread` — 400 when request_id thread doesn't match onboarding-{slug}
- `test_send_free_message` — message saved + old task cancelled + new task dispatched with enriched context
- `test_send_free_message_truncation` — conversation truncated to last 20 exchanges
- `test_get_status` — sync with dispatcher, detect pending questions
- `test_sync_status_completed` — dispatcher reports success -> analysis_status updated

### Frontend (vitest)
- `WizardStepAnalysis` — idle shows start button, running shows messages, question activates input, reply sends and clears, completed disables input, free message triggers relaunch
- `AnalysisChatMessage` — renders all 6 message types correctly
- `analysisStore` — initial state, message management, pendingQuestion lifecycle

## Constraints

- Reuse existing ChatBubble, ChatInput, ChatTypingIndicator, MarkdownRenderer
- No new WS event types backend-side — frontend filters by task_id and thread_id
- Orchestrator agent_id never hardcoded — resolved from agents_registry.json
- Thread ID: `onboarding-{slug}` (constant `ONBOARDING_THREAD_PREFIX = "onboarding-"`)
- No file > 300 lines
- TypeScript strict, i18n complete, Pydantic v2
- Conversation context for relaunch truncated to last 20 exchanges
