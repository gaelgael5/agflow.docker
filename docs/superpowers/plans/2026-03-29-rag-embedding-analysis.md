# RAG Embedding + Analysis Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable document indexation via Ollama embeddings, test embedding from admin UI, auto-index at analysis start, show synthesis, improve chat UX.

**Architecture:** Admin gets a test-embedding button per provider (both scopes). At analysis start, documents are indexed via RAG before calling the orchestrator. Chat UI enlarged with Ctrl+Enter to send.

**Tech Stack:** FastAPI, Ollama `/api/embeddings`, pgvector, React/TypeScript/Tailwind

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `web/server.py` | Add test-embedding endpoint |
| Modify | `web/static/js/app.js` | Add test button in provider table + edit modal (both scopes) |
| Modify | `web/static/index.html` | Cache buster |
| Modify | `hitl/services/analysis_service.py` | Index documents + generate synthesis before calling gateway |
| Modify | `hitl/services/rag_service.py` | Support `api_key` field in provider config (like llm_provider.py) |
| Modify | `hitl-frontend/src/components/features/chat/ChatInput.tsx` | Ctrl+Enter to send, Enter for newline |
| Modify | `hitl-frontend/src/components/features/project/WizardStepAnalysis.tsx` | Larger chat window |
| Modify | `hitl-frontend/public/locales/fr/translation.json` | i18n keys |
| Modify | `hitl-frontend/public/locales/en/translation.json` | i18n keys |
| SQL | `project.rag_documents` | ALTER column vector(1536) → vector(1024) |

---

### Task 1: ALTER pgvector column dimension

- [ ] **Step 1: Change column from vector(1536) to vector(1024)**

Run on the remote PostgreSQL:

```sql
-- Purge old vectors (incompatible dimension)
DELETE FROM project.rag_documents WHERE embedding IS NOT NULL;
-- Drop the old index
DROP INDEX IF EXISTS project.rag_documents_embedding_idx;
-- Change column type
ALTER TABLE project.rag_documents ALTER COLUMN embedding TYPE vector(1024);
-- Recreate index
CREATE INDEX rag_documents_embedding_idx ON project.rag_documents USING ivfflat (embedding vector_cosine_ops);
```

Execute via SSH:
```bash
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "docker exec langgraph-postgres psql -U langgraph -d langgraph -c \"DELETE FROM project.rag_documents WHERE embedding IS NOT NULL; DROP INDEX IF EXISTS project.rag_documents_embedding_idx; ALTER TABLE project.rag_documents ALTER COLUMN embedding TYPE vector(1024); CREATE INDEX rag_documents_embedding_idx ON project.rag_documents USING ivfflat (embedding vector_cosine_ops);\""
```

---

### Task 2: Backend — test-embedding endpoint

**Files:**
- Modify: `web/server.py`

- [ ] **Step 1: Add POST /api/llm/providers/test-embedding/{provider_id} endpoint**

Add after the existing `delete_llm_provider` endpoint (~line 1323):

```python
@app.post("/api/llm/providers/test-embedding/{provider_id}")
async def test_embedding_provider(provider_id: str):
    """Test if a provider supports embeddings and return dimension."""
    data = _read_json(LLM_PROVIDERS_FILE)
    providers = data.get("providers", {})
    if provider_id not in providers:
        raise HTTPException(404, f"Provider '{provider_id}' introuvable")
    p = providers[provider_id]
    ptype = p.get("type", "")
    model = p.get("model", "")
    base_url = p.get("base_url", "")

    import httpx as _httpx

    try:
        if ptype == "ollama":
            url = f"{base_url or 'http://localhost:11434'}/api/embeddings"
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json={"model": model, "prompt": "test embedding"})
                resp.raise_for_status()
                result = resp.json()
                if "error" in result:
                    raise ValueError(result["error"])
                dim = len(result.get("embedding", []))
        elif ptype in ("openai", "azure_openai"):
            url = f"{base_url or 'https://api.openai.com/v1'}/embeddings"
            env_key = p.get("env_key", "")
            api_key = p.get("api_key", "") or (os.environ.get(env_key, "") if env_key else "")
            headers = {"Authorization": f"Bearer {api_key}"}
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json={"model": model, "input": "test embedding"})
                resp.raise_for_status()
                result = resp.json()
                dim = len(result["data"][0]["embedding"])
        else:
            return {"ok": False, "error": f"Type '{ptype}' ne supporte pas le test embedding"}
    except Exception as exc:
        # Flag as not embedding
        p["embedding"] = False
        p.pop("embedding_dimension", None)
        data["providers"][provider_id] = p
        _write_json(LLM_PROVIDERS_FILE, data)
        return {"ok": False, "error": str(exc)}

    # Flag as embedding-capable
    p["embedding"] = True
    p["embedding_dimension"] = dim
    data["providers"][provider_id] = p
    _write_json(LLM_PROVIDERS_FILE, data)
    return {"ok": True, "dimension": dim}
```

- [ ] **Step 2: Add same endpoint for templates scope**

Add after the templates LLM endpoints:

```python
@app.post("/api/templates/llm/test-embedding/{provider_id}")
async def test_embedding_template_provider(provider_id: str):
    """Test if a template provider supports embeddings and return dimension."""
    data = _read_json(SHARED_LLM_FILE)
    providers = data.get("providers", {})
    if provider_id not in providers:
        raise HTTPException(404, f"Provider '{provider_id}' introuvable")
    p = providers[provider_id]
    ptype = p.get("type", "")
    model = p.get("model", "")
    base_url = p.get("base_url", "")

    import httpx as _httpx

    try:
        if ptype == "ollama":
            url = f"{base_url or 'http://localhost:11434'}/api/embeddings"
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json={"model": model, "prompt": "test embedding"})
                resp.raise_for_status()
                result = resp.json()
                if "error" in result:
                    raise ValueError(result["error"])
                dim = len(result.get("embedding", []))
        elif ptype in ("openai", "azure_openai"):
            url = f"{base_url or 'https://api.openai.com/v1'}/embeddings"
            env_key = p.get("env_key", "")
            api_key = p.get("api_key", "") or (os.environ.get(env_key, "") if env_key else "")
            headers = {"Authorization": f"Bearer {api_key}"}
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json={"model": model, "input": "test embedding"})
                resp.raise_for_status()
                result = resp.json()
                dim = len(result["data"][0]["embedding"])
        else:
            return {"ok": False, "error": f"Type '{ptype}' ne supporte pas le test embedding"}
    except Exception as exc:
        p["embedding"] = False
        p.pop("embedding_dimension", None)
        data["providers"][provider_id] = p
        _write_json(SHARED_LLM_FILE, data)
        return {"ok": False, "error": str(exc)}

    p["embedding"] = True
    p["embedding_dimension"] = dim
    data["providers"][provider_id] = p
    _write_json(SHARED_LLM_FILE, data)
    return {"ok": True, "dimension": dim}
```

---

### Task 3: Admin UI — test embedding button

**Files:**
- Modify: `web/static/js/app.js`
- Modify: `web/static/index.html`

- [ ] **Step 1: Add test button in provider table rows (Production)**

In the `renderLLM()` function (Production), where the action buttons are rendered for each provider (Clone, Edit, Delete icons), add a "Test embedding" button. Find the provider action cell rendering and add:

```javascript
'<button class="btn-icon" onclick="testEmbedding(\'' + escHtml(id) + '\')" title="Tester embedding">🧲</button>'
```

- [ ] **Step 2: Add test button in provider table rows (Configuration — Templates)**

Same for `loadTplLLM()` / template provider rendering. Add:

```javascript
'<button class="btn-icon" onclick="testTplEmbedding(\'' + escHtml(id) + '\')" title="Tester embedding">🧲</button>'
```

- [ ] **Step 3: Show embedding badge in table**

In both tables, after the API key column, show an embedding badge if the provider has `embedding: true`:

```javascript
p.embedding ? '<span class="tag tag-green" style="font-size:0.6rem">emb:' + (p.embedding_dimension || '?') + '</span>' : ''
```

- [ ] **Step 4: Add testEmbedding() and testTplEmbedding() functions**

```javascript
async function testEmbedding(id) {
  try {
    const res = await api('/api/llm/providers/test-embedding/' + encodeURIComponent(id), { method: 'POST' });
    if (res.ok) {
      toast('Embedding OK — dimension: ' + res.dimension, 'success');
    } else {
      toast('Embedding non supporte: ' + (res.error || ''), 'error');
    }
    loadLLM();
  } catch (e) { toast(e.message, 'error'); }
}

async function testTplEmbedding(id) {
  try {
    const res = await api('/api/templates/llm/test-embedding/' + encodeURIComponent(id), { method: 'POST' });
    if (res.ok) {
      toast('Embedding OK — dimension: ' + res.dimension, 'success');
    } else {
      toast('Embedding non supporte: ' + (res.error || ''), 'error');
    }
    loadTplLLM();
  } catch (e) { toast(e.message, 'error'); }
}
```

- [ ] **Step 5: Cache buster**

Bump version in `index.html`.

---

### Task 4: Index documents at analysis start

**Files:**
- Modify: `hitl/services/analysis_service.py`
- Modify: `hitl/services/rag_service.py`

- [ ] **Step 1: Update rag_service to support api_key from provider config**

In `_find_embedding_provider()` and `get_embedding()`, the api_key resolution currently uses only `os.getenv(env_key)`. Add support for `api_key` field (like `_resolve_api_key` in llm_provider.py):

In `get_embedding()` at line 48, change:
```python
    api_key = os.getenv(env_key, "") if env_key else ""
```
to:
```python
    api_key = provider.get("api_key", "") or (os.getenv(env_key, "") if env_key else "")
```

- [ ] **Step 2: Add index_project_documents() helper in analysis_service.py**

Add after the existing helpers:

```python
async def _index_project_documents(project_slug: str) -> tuple[int, list[str]]:
    """Index all uploaded documents into RAG. Returns (total_chunks, filenames)."""
    from services import rag_service, upload_service

    uploads = _uploads_dir(project_slug)
    if not os.path.isdir(uploads):
        return 0, []

    filenames = []
    total_chunks = 0

    for root, _dirs, files in os.walk(uploads):
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            filepath = os.path.join(root, fname)
            rel_name = os.path.relpath(filepath, uploads)
            text = upload_service.extract_text(filepath)
            if not text.strip():
                continue
            ext = os.path.splitext(fname)[1].lower()
            content_type = "text/markdown" if ext == ".md" else "text/plain"
            try:
                chunks = await rag_service.index_document(project_slug, rel_name, text, content_type)
                total_chunks += chunks
                filenames.append(rel_name)
            except Exception as exc:
                log.warning("index_doc_failed", file=rel_name, error=str(exc))

    return total_chunks, filenames
```

- [ ] **Step 3: Add _generate_documents_synthesis() helper**

```python
async def _generate_documents_synthesis(
    project_slug: str,
    filenames: list[str],
    total_chunks: int,
) -> str:
    """Generate a max 30-line synthesis of indexed documents using RAG search."""
    from services import rag_service

    # Search for broad overview content
    results = await rag_service.search(project_slug, "project description overview objectives features", top_k=10)
    if not results:
        return f"📄 {len(filenames)} documents indexes ({total_chunks} chunks). Aucun contenu extractible."

    combined = "\n\n".join(r.content[:500] for r in results)
    synthesis_lines = [
        f"📄 **{len(filenames)} documents indexes** ({total_chunks} chunks)",
        "",
    ]
    for r in results[:8]:
        line = r.content.strip().split("\n")[0][:120]
        synthesis_lines.append(f"- [{r.filename}] {line}")

    return "\n".join(synthesis_lines[:30])
```

- [ ] **Step 4: Modify start_analysis() to index first and store synthesis**

In `start_analysis()`, after the `documents` list is built (~line 229) and before the `thread_id` assignment (~line 231), add:

```python
    # Index documents into RAG before calling orchestrator
    total_chunks, indexed_files = await _index_project_documents(project_slug)

    # Store indexation progress message
    if indexed_files:
        synthesis = await _generate_documents_synthesis(project_slug, indexed_files, total_chunks)
    else:
        synthesis = "Aucun document a indexer."
```

Then after the task_row is created (~line 249), store the synthesis as the first event:

```python
    # Store synthesis as first progress event
    if task_id:
        await execute(
            """INSERT INTO project.dispatcher_task_events (task_id, event_type, data)
               VALUES ($1::uuid, 'progress', $2::jsonb)""",
            task_id,
            json.dumps({"data": synthesis}, ensure_ascii=False),
        )
```

- [ ] **Step 5: Update instruction to mention indexed documents**

In `_build_instruction()`, change the instruction text to tell the orchestrator that documents are indexed in the RAG:

```python
    return (
        f"Tu es l'orchestrateur de l'equipe {team_name}. "
        f"Un nouveau projet '{project_name}' (slug: {project_slug}) vient d'etre cree.\n\n"
        f"Documents fournis et indexes dans le RAG :\n{doc_list}\n\n"
        "Ta mission :\n"
        "1. Consulte les documents indexes via le RAG pour comprendre le projet\n"
        "2. Pose des questions pour clarifier le perimetre, les objectifs, les contraintes\n"
        "3. Delegue aux agents specialises si necessaire\n"
        "4. Quand le projet est clair, produis une synthese structuree\n"
    )
```

---

### Task 5: Chat UI — Ctrl+Enter to send + larger window

**Files:**
- Modify: `hitl-frontend/src/components/features/chat/ChatInput.tsx`
- Modify: `hitl-frontend/src/components/features/project/WizardStepAnalysis.tsx`

- [ ] **Step 1: Change ChatInput to Ctrl+Enter for send**

In `ChatInput.tsx`, find the `onKeyDown` handler. Change the logic:

Current: Enter sends, Shift+Enter newlines.
New: Ctrl+Enter sends, Enter newlines.

```typescript
const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    handleSend();
  }
};
```

- [ ] **Step 2: Update placeholder text**

Update the default placeholder or add a hint below the input to indicate "Ctrl+Enter pour envoyer".

- [ ] **Step 3: Enlarge chat window in WizardStepAnalysis**

In `WizardStepAnalysis.tsx`, change the container class:

From: `max-w-2xl h-[500px]`
To: `max-w-5xl h-[calc(100vh-12rem)]`

This makes the chat nearly full-width and uses available viewport height minus header/stepper/footer.

- [ ] **Step 4: Add i18n keys**

FR: `"analysis.ctrl_enter_hint": "Ctrl+Enter pour envoyer"`
EN: `"analysis.ctrl_enter_hint": "Ctrl+Enter to send"`

---

### Task 6: Apply all selected workflows

**Files:**
- Modify: `hitl-frontend/src/components/features/project/WizardShell.tsx`

- [ ] **Step 1: Apply all workflows from selectedWorkflowIds**

In `WizardShell.tsx`, the step 3 `handleNext` currently calls `applyProjectType` with a single `selectedWorkflowFilename`. Change to apply all selected workflows.

Find the step 3 block in `handleNext`:

```typescript
    if (wizardStep === 3 && selectedTypeId) {
      setCreating(true);
      setError(null);
      try {
        const result = await projectTypesApi.applyProjectType(
          wizardData.slug, selectedTypeId, selectedWorkflowFilename,
        );
```

The `applyProjectType` backend already copies the entire project type directory (all workflow files). The `selectedWorkflowFilename` is only used to deduce the orchestrator prompt. Update to use the first selected workflow:

```typescript
    if (wizardStep === 3 && selectedTypeId) {
      setCreating(true);
      setError(null);
      try {
        const firstWf = selectedWorkflowIds[0] || selectedWorkflowFilename;
        const result = await projectTypesApi.applyProjectType(
          wizardData.slug, selectedTypeId, firstWf,
        );
```

Save all selected workflow IDs in the wizard data for later use:

```typescript
        void wizardDataApi.saveWizardStep(wizardData.slug, 3, {
          selectedTypeId,
          selectedChatId,
          selectedWorkflowIds,
          workflowFilename: firstWf,
          orchestratorPrompt: result.orchestrator_prompt,
        });
```

---

### Task 7: Build + Deploy + Verify

- [ ] **Step 1: Run SQL migration**
- [ ] **Step 2: Build HITL frontend**

```bash
cd hitl-frontend && npm run build
rm -rf ../hitl/static/assets && cp -r dist/* ../hitl/static/
```

- [ ] **Step 3: Deploy**

```bash
bash deploy.sh AGT1
ssh -i ~/.ssh/id_shellia root@192.168.10.147 "cd /root/tests/lang && docker compose up -d --build langgraph-admin langgraph-api hitl-console"
```

- [ ] **Step 4: Verify**

1. Admin > Production > LLM > click "Test embedding" on ollama-qwen3 → should show "emb:1024" badge
2. Admin > Configuration > LLM > same test
3. HITL > create project > upload documents > start analysis → should see "Analyse des documents en cours..." then a 30-line synthesis
4. Chat input: Enter adds newline, Ctrl+Enter sends
5. Chat window is larger (full width, taller)
