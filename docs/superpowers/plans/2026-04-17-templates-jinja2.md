# Module Templates Jinja2 — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un module CRUD "Templates" avec stockage filesystem, éditeur CodeMirror Jinja2, et navigation dans le menu Plateforme.

**Architecture:** Stockage 100% filesystem (`/app/data/templates/{slug}/`). Backend FastAPI service + routeur CRUD. Frontend page avec layout fichiers + éditeur CodeMirror pour la coloration Jinja. Même patterns que les modules Dockerfiles et Rôles.

**Tech Stack:** Python 3.12 + FastAPI (backend), React 18 + TypeScript + CodeMirror 6 (frontend), Jinja2 (dépendance Python pour le lot suivant)

**Spec de référence:** `docs/superpowers/specs/2026-04-17-templates-jinja2-design.md`

---

## File Structure

**Backend — créés :**
- `backend/src/agflow/schemas/templates.py` — Pydantic models
- `backend/src/agflow/services/template_files_service.py` — CRUD filesystem
- `backend/src/agflow/api/admin/templates.py` — routeur FastAPI

**Backend — modifiés :**
- `backend/pyproject.toml` — ajout dépendance `jinja2`
- `backend/src/agflow/main.py` — enregistrer le routeur templates

**Frontend — créés :**
- `frontend/src/lib/templatesApi.ts` — client API
- `frontend/src/hooks/useTemplates.ts` — hook TanStack Query
- `frontend/src/pages/TemplatesPage.tsx` — page principale
- `frontend/src/components/JinjaEditor.tsx` — éditeur CodeMirror

**Frontend — modifiés :**
- `frontend/package.json` — dépendances CodeMirror
- `frontend/src/App.tsx` — route `/templates`
- `frontend/src/components/layout/Sidebar.tsx` — entrée menu
- `frontend/src/i18n/fr.json`, `en.json` — clés `templates.*`

---

## Task 1 : Backend — schémas Pydantic

**Files:**
- Create: `backend/src/agflow/schemas/templates.py`

- [ ] **Step 1.1 : Créer les schémas**

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""


class TemplateUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None


class TemplateSummary(BaseModel):
    slug: str
    display_name: str
    description: str
    cultures: list[str]


class TemplateFileInfo(BaseModel):
    filename: str
    culture: str
    size: int


class TemplateDetail(BaseModel):
    slug: str
    display_name: str
    description: str
    files: list[TemplateFileInfo]


class FileCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content: str = ""


class FileUpdate(BaseModel):
    content: str
```

- [ ] **Step 1.2 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/schemas/templates.py
git add backend/src/agflow/schemas/templates.py
git commit -m "feat(templates): schémas Pydantic pour le module Templates"
```

---

## Task 2 : Backend — service filesystem

**Files:**
- Create: `backend/src/agflow/services/template_files_service.py`

- [ ] **Step 2.1 : Créer le service**

```python
from __future__ import annotations

import json
import os
import shutil

import structlog

_log = structlog.get_logger(__name__)


def _data_dir() -> str:
    return os.environ.get("AGFLOW_DATA_DIR", "/app/data")


def _templates_dir() -> str:
    return os.path.join(_data_dir(), "templates")


def _template_dir(slug: str) -> str:
    return os.path.join(_templates_dir(), slug)


def _extract_culture(filename: str) -> str:
    """Extract culture from filename: 'fr.md.j2' → 'fr'."""
    return filename.split(".")[0] if "." in filename else ""


# ── Template CRUD ────────────────────────────────────────────────────────

def list_all() -> list[dict]:
    base = _templates_dir()
    if not os.path.isdir(base):
        return []
    results = []
    for slug in sorted(os.listdir(base)):
        d = os.path.join(base, slug)
        if not os.path.isdir(d):
            continue
        meta = read_meta(slug)
        if meta is None:
            continue
        j2_files = [f for f in os.listdir(d) if f.endswith(".j2")]
        cultures = sorted(set(_extract_culture(f) for f in j2_files if _extract_culture(f)))
        results.append({
            "slug": slug,
            "display_name": meta.get("display_name", slug),
            "description": meta.get("description", ""),
            "cultures": cultures,
        })
    return results


def read_meta(slug: str) -> dict | None:
    path = os.path.join(_template_dir(slug), "template.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def write_meta(slug: str, meta: dict) -> None:
    d = _template_dir(slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "template.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False, indent=2))


def create(slug: str, display_name: str, description: str = "") -> dict:
    d = _template_dir(slug)
    if os.path.isdir(d):
        raise FileExistsError(f"Template '{slug}' already exists")
    write_meta(slug, {"display_name": display_name, "description": description})
    _log.info("template_files.create", slug=slug)
    return {"slug": slug, "display_name": display_name, "description": description, "cultures": []}


def update(slug: str, display_name: str | None = None, description: str | None = None) -> dict:
    meta = read_meta(slug)
    if meta is None:
        raise FileNotFoundError(f"Template '{slug}' not found")
    if display_name is not None:
        meta["display_name"] = display_name
    if description is not None:
        meta["description"] = description
    write_meta(slug, meta)
    _log.info("template_files.update", slug=slug)
    summary = list_all()
    return next((t for t in summary if t["slug"] == slug), meta)


def delete(slug: str) -> None:
    d = _template_dir(slug)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"Template '{slug}' not found")
    shutil.rmtree(d)
    _log.info("template_files.delete", slug=slug)


# ── File CRUD ────────────────────────────────────────────────────────────

def list_files(slug: str) -> list[dict]:
    d = _template_dir(slug)
    if not os.path.isdir(d):
        return []
    results = []
    for filename in sorted(os.listdir(d)):
        if not filename.endswith(".j2"):
            continue
        full = os.path.join(d, filename)
        results.append({
            "filename": filename,
            "culture": _extract_culture(filename),
            "size": os.path.getsize(full),
        })
    return results


def read_file(slug: str, filename: str) -> str:
    path = os.path.join(_template_dir(slug), filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File '{filename}' not found in template '{slug}'")
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_file(slug: str, filename: str, content: str) -> None:
    d = _template_dir(slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, filename), "w", encoding="utf-8") as f:
        f.write(content)
    _log.info("template_files.write_file", slug=slug, filename=filename)


def delete_file(slug: str, filename: str) -> None:
    path = os.path.join(_template_dir(slug), filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File '{filename}' not found in template '{slug}'")
    os.unlink(path)
    _log.info("template_files.delete_file", slug=slug, filename=filename)


def get_detail(slug: str) -> dict:
    meta = read_meta(slug)
    if meta is None:
        raise FileNotFoundError(f"Template '{slug}' not found")
    return {
        "slug": slug,
        "display_name": meta.get("display_name", slug),
        "description": meta.get("description", ""),
        "files": list_files(slug),
    }
```

- [ ] **Step 2.2 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/template_files_service.py
git add backend/src/agflow/services/template_files_service.py
git commit -m "feat(templates): service filesystem CRUD templates + fichiers .j2"
```

---

## Task 3 : Backend — routeur API + dépendance jinja2

**Files:**
- Create: `backend/src/agflow/api/admin/templates.py`
- Modify: `backend/src/agflow/main.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 3.1 : Créer le routeur**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.templates import (
    FileCreate,
    FileUpdate,
    TemplateCreate,
    TemplateDetail,
    TemplateSummary,
    TemplateUpdate,
)
from agflow.services import template_files_service

router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin-templates"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[TemplateSummary])
async def list_templates():
    return template_files_service.list_all()


@router.post("", response_model=TemplateSummary, status_code=status.HTTP_201_CREATED)
async def create_template(payload: TemplateCreate):
    try:
        return template_files_service.create(
            payload.slug, payload.display_name, payload.description
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{slug}", response_model=TemplateDetail)
async def get_template(slug: str):
    try:
        return template_files_service.get_detail(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{slug}", response_model=TemplateSummary)
async def update_template(slug: str, payload: TemplateUpdate):
    try:
        return template_files_service.update(
            slug, display_name=payload.display_name, description=payload.description
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(slug: str):
    try:
        template_files_service.delete(slug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{slug}/files", status_code=status.HTTP_201_CREATED)
async def create_file(slug: str, payload: FileCreate):
    template_files_service.write_file(slug, payload.filename, payload.content)
    return {"filename": payload.filename}


@router.get("/{slug}/files/{filename}")
async def get_file(slug: str, filename: str):
    try:
        content = template_files_service.read_file(slug, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"filename": filename, "content": content}


@router.put("/{slug}/files/{filename}")
async def update_file(slug: str, filename: str, payload: FileUpdate):
    template_files_service.write_file(slug, filename, payload.content)
    return {"filename": filename}


@router.delete("/{slug}/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(slug: str, filename: str):
    try:
        template_files_service.delete_file(slug, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 3.2 : Enregistrer le routeur dans main.py**

Chercher les lignes d'import des routeurs admin (ex: `from agflow.api.admin.roles import router as admin_roles_router`) et ajouter :

```python
from agflow.api.admin.templates import router as admin_templates_router
```

Puis dans la section `app.include_router(...)`, ajouter :

```python
app.include_router(admin_templates_router)
```

- [ ] **Step 3.3 : Ajouter jinja2 dans pyproject.toml**

Dans la section `dependencies` de `[project]`, ajouter :

```toml
    "jinja2>=3.1",
```

- [ ] **Step 3.4 : Lint + commit**

```bash
cd backend && uv sync && uv run ruff check src/agflow/api/admin/templates.py src/agflow/schemas/templates.py
git add backend/src/agflow/api/admin/templates.py backend/src/agflow/main.py backend/pyproject.toml
git commit -m "feat(templates): routeur API CRUD + dépendance jinja2"
```

---

## Task 4 : Frontend — API client + hook + i18n

**Files:**
- Create: `frontend/src/lib/templatesApi.ts`
- Create: `frontend/src/hooks/useTemplates.ts`
- Modify: `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json`

- [ ] **Step 4.1 : Créer templatesApi.ts**

```typescript
import { api } from "@/lib/api";

export interface TemplateSummary {
  slug: string;
  display_name: string;
  description: string;
  cultures: string[];
}

export interface TemplateFileInfo {
  filename: string;
  culture: string;
  size: number;
}

export interface TemplateDetail {
  slug: string;
  display_name: string;
  description: string;
  files: TemplateFileInfo[];
}

export const templatesApi = {
  async list(): Promise<TemplateSummary[]> {
    const res = await api.get<TemplateSummary[]>("/admin/templates");
    return res.data;
  },
  async get(slug: string): Promise<TemplateDetail> {
    const res = await api.get<TemplateDetail>(`/admin/templates/${slug}`);
    return res.data;
  },
  async create(payload: {
    slug: string;
    display_name: string;
    description?: string;
  }): Promise<TemplateSummary> {
    const res = await api.post<TemplateSummary>("/admin/templates", payload);
    return res.data;
  },
  async update(
    slug: string,
    payload: { display_name?: string; description?: string },
  ): Promise<TemplateSummary> {
    const res = await api.put<TemplateSummary>(
      `/admin/templates/${slug}`,
      payload,
    );
    return res.data;
  },
  async remove(slug: string): Promise<void> {
    await api.delete(`/admin/templates/${slug}`);
  },
  async getFile(
    slug: string,
    filename: string,
  ): Promise<{ filename: string; content: string }> {
    const res = await api.get<{ filename: string; content: string }>(
      `/admin/templates/${slug}/files/${filename}`,
    );
    return res.data;
  },
  async createFile(
    slug: string,
    filename: string,
    content: string,
  ): Promise<void> {
    await api.post(`/admin/templates/${slug}/files`, { filename, content });
  },
  async updateFile(
    slug: string,
    filename: string,
    content: string,
  ): Promise<void> {
    await api.put(`/admin/templates/${slug}/files/${filename}`, { content });
  },
  async deleteFile(slug: string, filename: string): Promise<void> {
    await api.delete(`/admin/templates/${slug}/files/${filename}`);
  },
};
```

- [ ] **Step 4.2 : Créer useTemplates.ts**

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { templatesApi, type TemplateSummary } from "@/lib/templatesApi";

const TEMPLATES_KEY = ["templates"] as const;

export function useTemplates() {
  const qc = useQueryClient();

  const listQuery = useQuery<TemplateSummary[]>({
    queryKey: TEMPLATES_KEY,
    queryFn: () => templatesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: {
      slug: string;
      display_name: string;
      description?: string;
    }) => templatesApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: TEMPLATES_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => templatesApi.remove(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: TEMPLATES_KEY }),
  });

  return {
    templates: listQuery.data,
    isLoading: listQuery.isLoading,
    createMutation,
    deleteMutation,
  };
}
```

- [ ] **Step 4.3 : Clés i18n FR/EN**

Ajouter dans les deux fichiers un bloc `"templates"` :

FR:
```json
"templates": {
  "page_title": "Templates Jinja2",
  "page_subtitle": "Modèles de génération multilingues pour les fichiers agent",
  "add_button": "+ Nouveau template",
  "select_template": "Sélectionne un template",
  "no_templates": "Aucun template — crée ton premier template",
  "add_file_button": "+ Ajouter un fichier .j2",
  "add_file_dialog_title": "Nouveau fichier Jinja2",
  "add_file_name": "Nom du fichier (ex: fr.md.j2)",
  "new_template_dialog_title": "Nouveau template",
  "new_template_slug": "Slug (identifiant)",
  "new_template_name": "Nom d'affichage",
  "new_template_description": "Description",
  "delete_button": "Supprimer",
  "confirm_delete_title": "Supprimer le template",
  "confirm_delete_message": "Supprimer le template \"{{name}}\" et tous ses fichiers ? Cette action est irréversible.",
  "save": "Enregistrer",
  "select_file": "Sélectionne un fichier .j2"
}
```

EN:
```json
"templates": {
  "page_title": "Jinja2 Templates",
  "page_subtitle": "Multilingual generation templates for agent files",
  "add_button": "+ New template",
  "select_template": "Select a template",
  "no_templates": "No templates — create your first template",
  "add_file_button": "+ Add .j2 file",
  "add_file_dialog_title": "New Jinja2 file",
  "add_file_name": "Filename (e.g. fr.md.j2)",
  "new_template_dialog_title": "New template",
  "new_template_slug": "Slug (identifier)",
  "new_template_name": "Display name",
  "new_template_description": "Description",
  "delete_button": "Delete",
  "confirm_delete_title": "Delete template",
  "confirm_delete_message": "Delete template \"{{name}}\" and all its files? This action is irreversible.",
  "save": "Save",
  "select_file": "Select a .j2 file"
}
```

- [ ] **Step 4.4 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/templatesApi.ts frontend/src/hooks/useTemplates.ts frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(templates): API client + hook TanStack Query + i18n FR/EN"
```

---

## Task 5 : Frontend — dépendances CodeMirror + composant JinjaEditor

**Files:**
- Create: `frontend/src/components/JinjaEditor.tsx`
- Modify: `frontend/package.json` (via npm install)

- [ ] **Step 5.1 : Installer les dépendances CodeMirror**

```bash
cd frontend && npm install codemirror @codemirror/view @codemirror/state @codemirror/lang-html @codemirror/theme-one-dark @codemirror/language
```

- [ ] **Step 5.2 : Créer JinjaEditor.tsx**

```tsx
import { useEffect, useRef } from "react";
import { EditorView, keymap } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { html } from "@codemirror/lang-html";
import { oneDark } from "@codemirror/theme-one-dark";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import {
  bracketMatching,
  defaultHighlightStyle,
  syntaxHighlighting,
} from "@codemirror/language";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

export function JinjaEditor({ value, onChange, readOnly = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const state = EditorState.create({
      doc: value,
      extensions: [
        html(),
        syntaxHighlighting(defaultHighlightStyle),
        oneDark,
        history(),
        bracketMatching(),
        keymap.of([...defaultKeymap, ...historyKeymap]),
        EditorView.lineWrapping,
        EditorView.editable.of(!readOnly),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            onChange(update.state.doc.toString());
          }
        }),
      ],
    });

    const view = new EditorView({ state, parent: containerRef.current });
    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  // Sync external value changes (e.g. switching files)
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({
        changes: { from: 0, to: current.length, insert: value },
      });
    }
  }, [value]);

  return (
    <div
      ref={containerRef}
      className="border rounded-md overflow-hidden flex-1 min-h-[240px]"
      style={{ fontSize: "13px" }}
    />
  );
}
```

- [ ] **Step 5.3 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/JinjaEditor.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat(templates): composant JinjaEditor CodeMirror avec coloration HTML/Jinja"
```

---

## Task 6 : Frontend — TemplatesPage + route + sidebar

**Files:**
- Create: `frontend/src/pages/TemplatesPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 6.1 : Créer TemplatesPage.tsx**

Page avec layout split : liste templates à gauche, éditeur fichier .j2 à droite. Pattern simplifié par rapport à DockerfilesPage (pas de build/run/terminal).

Le sous-agent doit créer cette page complète avec :
- Sélecteur de template (dropdown ou liste)
- Liste des fichiers .j2 avec badges culture
- Bouton ajouter template (PromptDialog)
- Bouton ajouter fichier .j2 (PromptDialog)
- Bouton supprimer template (ConfirmDialog)
- Bouton supprimer fichier
- JinjaEditor pour éditer le fichier sélectionné
- Sauvegarde Ctrl+S + bouton Save
- État draft pour détecter les modifications non sauvées

Imports nécessaires : `useTemplates`, `templatesApi`, `JinjaEditor`, `PromptDialog`, `ConfirmDialog`, `PageHeader`, `PageShell`, `Badge`, `Button`, `Select`, i18n.

- [ ] **Step 6.2 : Ajouter la route dans App.tsx**

Importer `TemplatesPage` et ajouter la route entre dockerfiles et roles :

```tsx
import { TemplatesPage } from "@/pages/TemplatesPage";

// Dans les routes, après /dockerfiles et avant /roles :
<Route path="/templates" element={<ProtectedRoute><TemplatesPage /></ProtectedRoute>} />
```

- [ ] **Step 6.3 : Ajouter l'entrée dans Sidebar.tsx**

Importer l'icône `FileText` (ou `Braces`) de lucide-react. Ajouter un item dans la section "Plateforme" entre Dockerfiles et Rôles :

```typescript
{ to: "/templates", label: t("templates.page_title"), icon: Braces },
```

- [ ] **Step 6.4 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/pages/TemplatesPage.tsx frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(templates): page Templates + route + entrée sidebar"
```

---

## Task 7 : Vérification + déploiement

- [ ] **Step 7.1 : TypeScript strict**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 7.2 : Ruff backend**

```bash
cd backend && uv run ruff check src/
```

- [ ] **Step 7.3 : Déploiement**

```bash
bash scripts/deploy.sh --rebuild
```

- [ ] **Step 7.4 : Test E2E**

1. Menu latéral : "Templates Jinja2" visible entre Dockerfiles et Rôles
2. Créer un template "agent-prompt" avec description
3. Ajouter `fr.md.j2` avec contenu `# {{ role.display_name }}\n\n{{ role.identity_md }}`
4. Ajouter `en.md.j2`
5. Vérifier badges cultures (fr, en)
6. Ouvrir `fr.md.j2` → éditeur CodeMirror avec coloration
7. Modifier et sauvegarder → contenu persisté
8. Supprimer `en.md.j2` → disparu
9. Supprimer le template → tout supprimé

---

## Self-review

- **Couverture spec** : stockage disque (T2), API CRUD (T3), schémas (T1), route+sidebar (T6), éditeur CodeMirror (T5), i18n (T4), dépendance jinja2 (T3). ✓
- **Placeholder scan** : aucun TBD. T6 décrit la page en détail sans code complet car c'est une page UI complexe (~300 lignes) — le sous-agent a les specs et les patterns (DockerfilesPage comme référence). ✓
- **Type consistency** : `TemplateSummary`, `TemplateDetail`, `TemplateFileInfo` cohérents entre backend et frontend. ✓
- **Hors scope respecté** : pas d'intégration agent_generator, pas de preview rendu, pas d'autocomplétion. ✓
