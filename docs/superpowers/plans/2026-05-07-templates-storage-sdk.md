# Templates — Migration StorageSDK + résolution secrets plateforme

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le stockage fichier (`/app/data/templates/`) par StorageSDK (PostgreSQL) et résoudre les références `${vault://}` / `${env://}` au moment du rendu Jinja2.

**Architecture:** Les métadonnées de chaque template (slug, display_name, description) sont désormais stockées dans une table SQL `templates`. Les fichiers `.j2` vont dans le StorageSDK sous `templates/{slug}/{filename}`. La résolution des secrets plateforme (`${vault://HARPOCRATE_KEY:NAME}` et `${env://NAME}`) s'effectue en post-processing après chaque rendu Jinja2, via `platform_secrets_service.resolve_all()`.

**Tech Stack:** Python 3.12 / asyncpg / PostgreSQL 16 / StorageSDK (`agflow.storage.sdk`) / pytest-asyncio

---

## File Structure

| Action | Fichier |
|--------|---------|
| Créer | `backend/migrations/093_templates.sql` |
| Créer | `backend/src/agflow/services/template_storage_service.py` |
| Créer | `backend/tests/test_template_storage_service.py` |
| Modifier | `backend/src/agflow/services/platform_secrets_service.py` — ajouter `resolve_platform_refs()` |
| Modifier | `backend/src/agflow/api/admin/templates.py` — async + nouveau service |
| Modifier | `backend/src/agflow/services/compose_renderer_service.py` — async + résolution refs |
| Modifier | `backend/src/agflow/services/agent_generator.py` — async + résolution refs |
| Supprimer | `backend/src/agflow/services/template_files_service.py` |

---

### Task 1: Migration SQL — table `templates`

**Files:**
- Create: `backend/migrations/093_templates.sql`

- [ ] **Step 1: Créer la migration**

```sql
-- backend/migrations/093_templates.sql
CREATE TABLE IF NOT EXISTS templates (
    slug         VARCHAR(128) NOT NULL PRIMARY KEY,
    display_name TEXT         NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_templates
    BEFORE UPDATE ON templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

- [ ] **Step 2: Appliquer la migration**

```bash
cd backend && uv run python -m agflow.db.migrations
```

Expected output: `migration applied: 093_templates.sql`

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/093_templates.sql
git commit -m "feat(db): table templates pour migration stockage filesystem → StorageSDK"
```

---

### Task 2: `template_storage_service.py` — CRUD métadonnées + helper `resolve_platform_refs`

**Files:**
- Create: `backend/src/agflow/services/template_storage_service.py`
- Create: `backend/tests/test_template_storage_service.py` (partie metadata)
- Modify: `backend/src/agflow/services/platform_secrets_service.py`

- [ ] **Step 1: Écrire les tests rouge — metadata CRUD**

```python
# backend/tests/test_template_storage_service.py
from __future__ import annotations

import pytest

from agflow.db.pool import close_pool
from agflow.services import template_storage_service
from agflow.services.template_storage_service import (
    DuplicateTemplateError,
    TemplateNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_list_all_empty() -> None:
    result = await template_storage_service.list_all()
    assert result == []


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    summary = await template_storage_service.create("base-agent", "Agent de base", "desc")
    assert summary["slug"] == "base-agent"
    assert summary["display_name"] == "Agent de base"
    assert summary["cultures"] == []

    all_templates = await template_storage_service.list_all()
    assert len(all_templates) == 1
    assert all_templates[0]["slug"] == "base-agent"


@pytest.mark.asyncio
async def test_create_duplicate_raises() -> None:
    await template_storage_service.create("tpl", "T", "")
    with pytest.raises(DuplicateTemplateError):
        await template_storage_service.create("tpl", "T2", "")


@pytest.mark.asyncio
async def test_update_display_name() -> None:
    await template_storage_service.create("tpl", "Ancien nom", "")
    result = await template_storage_service.update("tpl", display_name="Nouveau nom")
    assert result["display_name"] == "Nouveau nom"
    assert result["description"] == ""


@pytest.mark.asyncio
async def test_update_not_found_raises() -> None:
    with pytest.raises(TemplateNotFoundError):
        await template_storage_service.update("inexistant", display_name="X")


@pytest.mark.asyncio
async def test_delete() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.delete("tpl")
    assert await template_storage_service.list_all() == []


@pytest.mark.asyncio
async def test_delete_not_found_raises() -> None:
    with pytest.raises(TemplateNotFoundError):
        await template_storage_service.delete("inexistant")
```

- [ ] **Step 2: Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/test_template_storage_service.py -v
```

Expected: FAIL avec `ModuleNotFoundError` ou `ImportError`

- [ ] **Step 3: Implémenter le service (partie metadata)**

```python
# backend/src/agflow/services/template_storage_service.py
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.storage import StorageSDK

_log = structlog.get_logger(__name__)

_TEMPLATES_ROOT = "templates"


class TemplateNotFoundError(Exception):
    pass


class DuplicateTemplateError(Exception):
    pass


class TemplateFileNotFoundError(Exception):
    pass


async def _storage() -> StorageSDK:
    return StorageSDK(await get_pool())


async def _root_id(s: StorageSDK) -> UUID:
    node_id = await s.resolve_node(_TEMPLATES_ROOT)
    if node_id is None:
        node_id = await s.create_folder(_TEMPLATES_ROOT)
    return node_id


async def _template_folder_id(
    s: StorageSDK, slug: str, *, create: bool = True
) -> UUID | None:
    root = await _root_id(s)
    node_id = await s.resolve_node(slug, root)
    if node_id is None and create:
        node_id = await s.create_folder(slug, root)
    return node_id


async def _build_summary(row: dict[str, Any]) -> dict[str, Any]:
    files = await list_files(row["slug"])
    cultures = sorted(set(f["culture"] for f in files if f["culture"]))
    return {
        "slug": row["slug"],
        "display_name": row["display_name"],
        "description": row["description"],
        "cultures": cultures,
    }


async def list_all() -> list[dict[str, Any]]:
    rows = await fetch_all(
        "SELECT slug, display_name, description FROM templates ORDER BY slug ASC"
    )
    return [await _build_summary(dict(r)) for r in rows]


async def create(slug: str, display_name: str, description: str = "") -> dict[str, Any]:
    import asyncpg

    try:
        await execute(
            "INSERT INTO templates (slug, display_name, description) VALUES ($1, $2, $3)",
            slug,
            display_name,
            description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateTemplateError(f"Template '{slug}' existe déjà") from exc

    s = await _storage()
    await _template_folder_id(s, slug, create=True)
    _log.info("template_storage.create", slug=slug)
    return {"slug": slug, "display_name": display_name, "description": description, "cultures": []}


async def get_detail(slug: str) -> dict[str, Any]:
    row = await fetch_one(
        "SELECT slug, display_name, description FROM templates WHERE slug = $1", slug
    )
    if row is None:
        raise TemplateNotFoundError(f"Template '{slug}' introuvable")
    files = await list_files(slug)
    return {
        "slug": row["slug"],
        "display_name": row["display_name"],
        "description": row["description"],
        "files": files,
    }


async def update(
    slug: str,
    display_name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    row = await fetch_one("SELECT slug FROM templates WHERE slug = $1", slug)
    if row is None:
        raise TemplateNotFoundError(f"Template '{slug}' introuvable")

    set_clauses: list[str] = []
    params: list[Any] = [slug]

    if display_name is not None:
        params.append(display_name)
        set_clauses.append(f"display_name = ${len(params)}")
    if description is not None:
        params.append(description)
        set_clauses.append(f"description = ${len(params)}")

    if set_clauses:
        await execute(
            f"UPDATE templates SET {', '.join(set_clauses)} WHERE slug = $1",
            *params,
        )

    updated = await fetch_one(
        "SELECT slug, display_name, description FROM templates WHERE slug = $1", slug
    )
    assert updated is not None
    return await _build_summary(dict(updated))


async def delete(slug: str) -> None:
    row = await fetch_one("SELECT slug FROM templates WHERE slug = $1", slug)
    if row is None:
        raise TemplateNotFoundError(f"Template '{slug}' introuvable")

    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is not None:
        await s.delete_node(folder_id)

    await execute("DELETE FROM templates WHERE slug = $1", slug)
    _log.info("template_storage.delete", slug=slug)


# ── File operations — defined in Task 3 ──────────────────────────────────────

async def list_files(slug: str) -> list[dict[str, Any]]:
    ...  # Task 3

async def read_file(slug: str, filename: str) -> str:
    ...  # Task 3

async def write_file(slug: str, filename: str, content: str) -> None:
    ...  # Task 3

async def delete_file(slug: str, filename: str) -> None:
    ...  # Task 3
```

- [ ] **Step 4: Ajouter `resolve_platform_refs` dans `platform_secrets_service.py`**

Ouvrir `backend/src/agflow/services/platform_secrets_service.py` et ajouter en bas du fichier (après les imports existants, ajouter `import re` en tête) :

```python
import re

# En bas du fichier, après resolve_all():

_VAULT_REF_RE = re.compile(r"\$\{vault://[^:}]+:([^}]+)\}")
_ENV_REF_RE = re.compile(r"\$\{env://([^}]+)\}")


def resolve_platform_refs(text: str, secrets: dict[str, str]) -> str:
    """Résout ${vault://KEY:NAME} et ${env://NAME} dans text.

    secrets = résultat de resolve_all() : {nom_variable: valeur}.
    Les références inconnues sont remplacées par une chaîne vide.
    """
    text = _VAULT_REF_RE.sub(lambda m: secrets.get(m.group(1), ""), text)
    text = _ENV_REF_RE.sub(lambda m: secrets.get(m.group(1), ""), text)
    return text
```

- [ ] **Step 5: Vérifier les tests metadata**

```bash
cd backend && uv run pytest tests/test_template_storage_service.py -v
```

Expected: tous les tests metadata PASS (les tests de fichiers ne sont pas encore écrits)

- [ ] **Step 6: Commit**

```bash
git add backend/src/agflow/services/template_storage_service.py \
        backend/src/agflow/services/platform_secrets_service.py \
        backend/tests/test_template_storage_service.py
git commit -m "feat(templates): service metadata CRUD StorageSDK + resolve_platform_refs"
```

---

### Task 3: `template_storage_service.py` — opérations sur les fichiers

**Files:**
- Modify: `backend/src/agflow/services/template_storage_service.py` (compléter les stubs)
- Modify: `backend/tests/test_template_storage_service.py` (ajouter tests fichiers)

- [ ] **Step 1: Ajouter les tests rouge — file operations**

Ajouter à la suite de `test_template_storage_service.py` :

```python
@pytest.mark.asyncio
async def test_write_and_read_file() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "Bonjour {{ name }}")
    content = await template_storage_service.read_file("tpl", "fr.md.j2")
    assert content == "Bonjour {{ name }}"


@pytest.mark.asyncio
async def test_list_files_returns_culture() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "")
    await template_storage_service.write_file("tpl", "en.md.j2", "")
    files = await template_storage_service.list_files("tpl")
    filenames = [f["filename"] for f in files]
    assert "fr.md.j2" in filenames
    assert "en.md.j2" in filenames
    cultures = [f["culture"] for f in files]
    assert "fr" in cultures and "en" in cultures


@pytest.mark.asyncio
async def test_cultures_reflected_in_list_all() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "")
    summaries = await template_storage_service.list_all()
    assert summaries[0]["cultures"] == ["fr"]


@pytest.mark.asyncio
async def test_read_file_not_found_raises() -> None:
    await template_storage_service.create("tpl", "T", "")
    with pytest.raises(template_storage_service.TemplateFileNotFoundError):
        await template_storage_service.read_file("tpl", "inexistant.j2")


@pytest.mark.asyncio
async def test_delete_file() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "contenu")
    await template_storage_service.delete_file("tpl", "fr.md.j2")
    with pytest.raises(template_storage_service.TemplateFileNotFoundError):
        await template_storage_service.read_file("tpl", "fr.md.j2")


@pytest.mark.asyncio
async def test_delete_file_not_found_raises() -> None:
    await template_storage_service.create("tpl", "T", "")
    with pytest.raises(template_storage_service.TemplateFileNotFoundError):
        await template_storage_service.delete_file("tpl", "inexistant.j2")


@pytest.mark.asyncio
async def test_delete_template_removes_files() -> None:
    await template_storage_service.create("tpl", "T", "")
    await template_storage_service.write_file("tpl", "fr.md.j2", "bonjour")
    await template_storage_service.delete("tpl")
    # Les fichiers disparaissent avec le template
    assert await template_storage_service.list_all() == []
```

- [ ] **Step 2: Vérifier que les nouveaux tests échouent**

```bash
cd backend && uv run pytest tests/test_template_storage_service.py -k "file" -v
```

Expected: FAIL avec `NotImplementedError` (les stubs `...` lèvent `TypeError`)

- [ ] **Step 3: Implémenter les opérations fichiers**

Remplacer les 4 stubs `...` dans `template_storage_service.py` :

```python
async def list_files(slug: str) -> list[dict[str, Any]]:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is None:
        return []
    children = await s.list_folder(folder_id)
    results = []
    for child in children:
        if child["kind"] == 0:
            continue
        filename = child["name"]
        culture = filename.split(".")[0] if "." in filename else ""
        results.append({
            "filename": filename,
            "culture": culture,
            "size": child["size"] or 0,
        })
    return results


async def read_file(slug: str, filename: str) -> str:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is None:
        raise TemplateFileNotFoundError(f"Template '{slug}' introuvable")
    doc = await s.read_document(folder_id, filename)
    if doc is None:
        raise TemplateFileNotFoundError(f"Fichier '{filename}' introuvable dans '{slug}'")
    return doc["content"] or ""


async def write_file(slug: str, filename: str, content: str) -> None:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=True)
    assert folder_id is not None
    await s.write_document(folder_id, filename, content)
    _log.info("template_storage.write_file", slug=slug, filename=filename)


async def delete_file(slug: str, filename: str) -> None:
    s = await _storage()
    folder_id = await _template_folder_id(s, slug, create=False)
    if folder_id is None:
        raise TemplateFileNotFoundError(f"Template '{slug}' introuvable")
    node_id = await s.resolve_node(filename, folder_id)
    if node_id is None:
        raise TemplateFileNotFoundError(f"Fichier '{filename}' introuvable dans '{slug}'")
    await s.delete_node(node_id)
    _log.info("template_storage.delete_file", slug=slug, filename=filename)
```

- [ ] **Step 4: Vérifier tous les tests**

```bash
cd backend && uv run pytest tests/test_template_storage_service.py -v
```

Expected: tous PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/template_storage_service.py \
        backend/tests/test_template_storage_service.py
git commit -m "feat(templates): opérations fichiers via StorageSDK"
```

---

### Task 4: Router `api/admin/templates.py` — passage async

**Files:**
- Modify: `backend/src/agflow/api/admin/templates.py`

- [ ] **Step 1: Réécrire le router**

Remplacer intégralement `backend/src/agflow/api/admin/templates.py` :

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.templates import (
    FileCreate,
    FileUpdate,
    TemplateCreate,
    TemplateDetail,
    TemplateSummary,
    TemplateUpdate,
)
from agflow.services import template_storage_service
from agflow.services.template_storage_service import (
    DuplicateTemplateError,
    TemplateFileNotFoundError,
    TemplateNotFoundError,
)

router = APIRouter(
    prefix="/api/admin/templates",
    tags=["admin-templates"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[TemplateSummary])
async def list_templates():
    return await template_storage_service.list_all()


@router.post("", response_model=TemplateSummary, status_code=status.HTTP_201_CREATED)
async def create_template(payload: TemplateCreate):
    try:
        return await template_storage_service.create(
            payload.slug, payload.display_name, payload.description
        )
    except DuplicateTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{slug}", response_model=TemplateDetail)
async def get_template(slug: str):
    try:
        return await template_storage_service.get_detail(slug)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{slug}", response_model=TemplateSummary)
async def update_template(slug: str, payload: TemplateUpdate):
    try:
        return await template_storage_service.update(
            slug, display_name=payload.display_name, description=payload.description
        )
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(slug: str):
    try:
        await template_storage_service.delete(slug)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{slug}/files", status_code=status.HTTP_201_CREATED)
async def create_file(slug: str, payload: FileCreate):
    await template_storage_service.write_file(slug, payload.filename, payload.content)
    return {"filename": payload.filename}


@router.get("/{slug}/files/{filename}")
async def get_file(slug: str, filename: str):
    try:
        content = await template_storage_service.read_file(slug, filename)
    except TemplateFileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"filename": filename, "content": content}


@router.put("/{slug}/files/{filename}")
async def update_file(slug: str, filename: str, payload: FileUpdate):
    await template_storage_service.write_file(slug, filename, payload.content)
    return {"filename": filename}


@router.delete("/{slug}/files/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(slug: str, filename: str):
    try:
        await template_storage_service.delete_file(slug, filename)
    except TemplateFileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 2: Vérifier lint + typage**

```bash
cd backend && uv run ruff check src/agflow/api/admin/templates.py && uv run ruff format src/agflow/api/admin/templates.py
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/api/admin/templates.py
git commit -m "feat(templates): router async via template_storage_service"
```

---

### Task 5: `compose_renderer_service.py` — appels async + résolution refs

**Files:**
- Modify: `backend/src/agflow/services/compose_renderer_service.py`

Le changement cible uniquement la fonction `render_group_compose()` (lignes ~306-357).

- [ ] **Step 1: Mettre à jour les imports**

Dans `compose_renderer_service.py`, modifier le bloc `from agflow.services import (...)` :

```python
from agflow.services import (
    groups_service,
    platform_secrets_service,
    product_catalog_service,
    product_instances_service,
    projects_service,
    swarm_defaults,
    template_storage_service,
)
```

(supprimer `template_files_service`, ajouter `platform_secrets_service` et `template_storage_service`)

- [ ] **Step 2: Réécrire `render_group_compose()`**

Remplacer la fonction `render_group_compose` en entier :

```python
async def render_group_compose(
    deployment_data: dict[str, Any],
    group_id: UUID,
) -> str:
    """Render le docker-compose YAML d'un groupe via son template Jinja2.

    Les références ${vault://} et ${env://} dans le rendu sont résolues
    via platform_secrets_service avant retour.
    """
    groups = deployment_data.get("groups", []) if isinstance(deployment_data, dict) else []
    block = next((g for g in groups if g.get("group", {}).get("id") == str(group_id)), None)
    if block is None:
        raise ComposeRenderError(
            f"Group {group_id} has no data in this deployment (was it regenerated?)"
        )

    try:
        group = await groups_service.get_by_id(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise ComposeRenderError(str(exc)) from exc

    slug = group.compose_template_slug
    if not slug:
        raise ComposeRenderError(
            f"Group {group.name!r} has no compose_template_slug — associate a "
            f"template via the group editor."
        )

    files = await template_storage_service.list_files(slug)
    sh_files = [f["filename"] for f in files if f["filename"].endswith(".sh.j2")]
    if not sh_files:
        raise ComposeRenderError(
            f"Template {slug!r} has no *.sh.j2 file — create one in the template editor."
        )
    filename = sh_files[0]

    try:
        content = await template_storage_service.read_file(slug, filename)
    except template_storage_service.TemplateFileNotFoundError as exc:
        raise ComposeRenderError(str(exc)) from exc

    try:
        template = _JINJA_ENV.from_string(content or "")
        rendered = template.render(**block)
    except TemplateError as exc:
        raise ComposeRenderError(
            f"Jinja2 rendering failed for template {slug!r}/{filename!r}: {exc}"
        ) from exc

    platform_secrets = await platform_secrets_service.resolve_all()
    return platform_secrets_service.resolve_platform_refs(rendered, platform_secrets)
```

- [ ] **Step 3: Vérifier lint**

```bash
cd backend && uv run ruff check src/agflow/services/compose_renderer_service.py
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/services/compose_renderer_service.py
git commit -m "feat(templates): compose_renderer async + résolution refs ${vault://} ${env://}"
```

---

### Task 6: `agent_generator.py` — lecture async + résolution refs

**Files:**
- Modify: `backend/src/agflow/services/agent_generator.py`

Il y a 4 points de lecture de templates dans `generate()` :
- Profil (ligne ~295) : `profile.template_slug` / `profile.template_culture`
- Prompt (ligne ~336) : `gen_block.template_slug` / `gen_block.template_culture`
- Config MCP (ligne ~526) : `mcp_tpl_slug` / `mcp_tpl_culture`
- Config Skills (ligne ~603) : `skills_tpl_slug` / `skills_tpl_culture`

- [ ] **Step 1: Mettre à jour les imports**

En haut de `agent_generator.py`, ajouter dans le bloc `from agflow.services import (...)` :

```python
from agflow.services import (
    agent_files_service,
    agents_service,
    dockerfile_files_service,
    mcp_catalog_service,
    platform_secrets_service,
    role_documents_service,
    roles_service,
    template_storage_service,
)
```

(ajouter `platform_secrets_service` et `template_storage_service`)

Supprimer les `import os` utilisés uniquement pour la lecture des templates (les autres usages d'`os` doivent être conservés — vérifier).

- [ ] **Step 2: Charger les secrets plateforme en début de `generate()`**

Au début de la fonction `generate()`, après la ligne `agent = await agents_service.get_by_id(agent_id)` :

```python
platform_secrets = await platform_secrets_service.resolve_all()
```

- [ ] **Step 3: Remplacer la lecture profil template (~ligne 293)**

Remplacer le bloc :

```python
if profile.template_slug and profile.template_culture:
    tpl_path = os.path.join(
        _data_dir(), "templates", profile.template_slug,
        f"{profile.template_culture}.md.j2",
    )
    if os.path.isfile(tpl_path):
        with open(tpl_path, encoding="utf-8") as f:
            tpl_content = f.read()
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        template = env.from_string(tpl_content)
        rendered = template.render(
            role=role, profile=profile, agent=agent,
            load_section=_make_loader(sections),
        )
        _log.info("agent_generator.profile_rendered",
                  profile=profile.name,
                  template=f"{profile.template_slug}/{profile.template_culture}.md.j2")
```

Par :

```python
if profile.template_slug and profile.template_culture:
    try:
        tpl_content = await template_storage_service.read_file(
            profile.template_slug, f"{profile.template_culture}.md.j2"
        )
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        template = env.from_string(tpl_content)
        raw = template.render(
            role=role, profile=profile, agent=agent,
            load_section=_make_loader(sections),
        )
        rendered = platform_secrets_service.resolve_platform_refs(raw, platform_secrets)
        _log.info("agent_generator.profile_rendered",
                  profile=profile.name,
                  template=f"{profile.template_slug}/{profile.template_culture}.md.j2")
    except template_storage_service.TemplateFileNotFoundError:
        generation_alerts.append({
            "level": "error",
            "variable": "profile_template",
            "message": (
                f"Template profil '{profile.template_slug}/"
                f"{profile.template_culture}.md.j2' introuvable"
            ),
        })
```

Note : s'assurer que `generation_alerts` est déclaré avant la boucle génération (il l'est déjà).

- [ ] **Step 4: Remplacer la lecture prompt template (~ligne 334)**

Remplacer le bloc :

```python
_prompt_template = None
_prompt_loader = None
if gen_block.template_slug and gen_block.template_culture:
    tpl_path = os.path.join(
        _data_dir(), "templates", gen_block.template_slug,
        f"{gen_block.template_culture}.md.j2",
    )
    if os.path.isfile(tpl_path):
        with open(tpl_path, encoding="utf-8") as f:
            tpl_content = f.read()
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        _prompt_template = env.from_string(tpl_content)
        _prompt_loader = _make_loader(all_sections)
```

Par :

```python
_prompt_template = None
_prompt_loader = None
if gen_block.template_slug and gen_block.template_culture:
    try:
        tpl_content = await template_storage_service.read_file(
            gen_block.template_slug, f"{gen_block.template_culture}.md.j2"
        )
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        _prompt_template = env.from_string(tpl_content)
        _prompt_loader = _make_loader(all_sections)
    except template_storage_service.TemplateFileNotFoundError:
        generation_alerts.append({
            "level": "error",
            "variable": "generation",
            "message": (
                f"Template prompt '{gen_block.template_slug}/"
                f"{gen_block.template_culture}.md.j2' introuvable"
            ),
        })
```

Et après le rendu du prompt (`prompt_md = _prompt_template.render(...)`), ajouter :

```python
prompt_md = platform_secrets_service.resolve_platform_refs(prompt_md, platform_secrets)
```

- [ ] **Step 5: Remplacer la lecture MCP template (~ligne 526)**

Remplacer le bloc :

```python
if mcp_tpl_slug and mcp_tpl_culture:
    tpl_path = os.path.join(
        _data_dir(), "templates", mcp_tpl_slug, f"{mcp_tpl_culture}.md.j2",
    )
    if os.path.isfile(tpl_path):
        with open(tpl_path, encoding="utf-8") as f:
            tpl_content = f.read()
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        mcp_template = env.from_string(tpl_content)
        mcp_content = mcp_template.render(
            agent=agent,
            mcp_servers=resolved_mcps,
            config_blocks=config_blocks,
        )
        ...
    else:
        generation_alerts.append({...})
```

Par :

```python
if mcp_tpl_slug and mcp_tpl_culture:
    try:
        tpl_content = await template_storage_service.read_file(
            mcp_tpl_slug, f"{mcp_tpl_culture}.md.j2"
        )
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        mcp_template = env.from_string(tpl_content)
        raw_mcp = mcp_template.render(
            agent=agent,
            mcp_servers=resolved_mcps,
            config_blocks=config_blocks,
        )
        mcp_content = platform_secrets_service.resolve_platform_refs(raw_mcp, platform_secrets)
        mcp_out_path = os.path.join(out_dir, mcp_config_fn)
        os.makedirs(os.path.dirname(mcp_out_path), exist_ok=True)
        with open(mcp_out_path, "w", encoding="utf-8") as fh:
            fh.write(mcp_content)
        data_base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
        mount_path = os.path.join(data_base, agent.dockerfile_id, mcp_config_fn)
        os.makedirs(os.path.dirname(mount_path), exist_ok=True)
        with open(mount_path, "w", encoding="utf-8") as fh:
            fh.write(mcp_content)
        _log.info("agent_generator.mcp_config_template", path=mount_path)
    except template_storage_service.TemplateFileNotFoundError:
        generation_alerts.append({
            "level": "error",
            "variable": "mcp_template",
            "message": f"Template MCP '{mcp_tpl_slug}/{mcp_tpl_culture}.md.j2' introuvable",
        })
```

- [ ] **Step 6: Remplacer la lecture Skills template (~ligne 603)**

Remplacer le bloc :

```python
if skills_tpl_slug and skills_tpl_culture:
    tpl_path = os.path.join(
        _data_dir(), "templates", skills_tpl_slug, f"{skills_tpl_culture}.md.j2",
    )
    if os.path.isfile(tpl_path):
        with open(tpl_path, encoding="utf-8") as f:
            tpl_content = f.read()
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        skills_template = env.from_string(tpl_content)
        skills_content = skills_template.render(agent=agent, skills=resolved_skills)
        ...
    else:
        generation_alerts.append({...})
```

Par :

```python
if skills_tpl_slug and skills_tpl_culture:
    try:
        tpl_content = await template_storage_service.read_file(
            skills_tpl_slug, f"{skills_tpl_culture}.md.j2"
        )
        env = Environment(
            trim_blocks=True, lstrip_blocks=True,
            keep_trailing_newline=True, autoescape=False,
        )
        skills_template = env.from_string(tpl_content)
        raw_skills = skills_template.render(agent=agent, skills=resolved_skills)
        skills_content = platform_secrets_service.resolve_platform_refs(raw_skills, platform_secrets)
        skills_out_path = os.path.join(out_dir, skills_config_fn)
        os.makedirs(os.path.dirname(skills_out_path), exist_ok=True)
        with open(skills_out_path, "w", encoding="utf-8") as fh:
            fh.write(skills_content)
        _log.info("agent_generator.skills_config_template", path=skills_out_path)
    except template_storage_service.TemplateFileNotFoundError:
        generation_alerts.append({
            "level": "error",
            "variable": "skills_template",
            "message": f"Template Skills '{skills_tpl_slug}/{skills_tpl_culture}.md.j2' introuvable",
        })
```

- [ ] **Step 7: Vérifier lint**

```bash
cd backend && uv run ruff check src/agflow/services/agent_generator.py
```

Expected: no errors (vérifier aussi les anciens alertes `elif` qui référençaient la branche `else` du `if os.path.isfile` — ils sont maintenant gérés dans l'`except`)

- [ ] **Step 8: Commit**

```bash
git add backend/src/agflow/services/agent_generator.py
git commit -m "feat(templates): agent_generator lecture async + résolution refs ${vault://} ${env://}"
```

---

### Task 7: Nettoyage — supprimer `template_files_service.py`

**Files:**
- Delete: `backend/src/agflow/services/template_files_service.py`

- [ ] **Step 1: Vérifier qu'il n'y a plus d'import**

```bash
cd backend && uv run grep -r "template_files_service" src/ tests/
```

Expected: aucun résultat

- [ ] **Step 2: Supprimer le fichier**

```bash
rm backend/src/agflow/services/template_files_service.py
```

- [ ] **Step 3: Lint global**

```bash
cd backend && uv run ruff check src/ tests/
```

Expected: no errors

- [ ] **Step 4: Suite de tests complète**

```bash
cd backend && uv run pytest tests/test_template_storage_service.py -v
```

Expected: tous PASS

- [ ] **Step 5: Commit final**

```bash
git add -u
git commit -m "chore(templates): suppression template_files_service.py (remplacé par template_storage_service)"
```

---

## Notes opérationnelles

**Migration des templates existants** : les templates déjà présents sur le filesystem du LXC 201 (`/app/data/templates/`) ne sont pas migrés automatiquement. Pour chaque template existant, il faut :
1. Créer le template via l'API POST `/api/admin/templates`
2. Uploader chaque fichier `.j2` via POST `/api/admin/templates/{slug}/files`

Le script de migration manuelle est hors scope de ce plan.

---

## Self-Review

**Spec coverage :**
- ✅ StorageSDK comme backend de stockage des fichiers `.j2`
- ✅ Métadonnées dans table SQL `templates`
- ✅ `${vault://HARPOCRATE_KEY:NAME}` résolu au rendu via `resolve_platform_refs`
- ✅ `${env://NAME}` résolu au rendu via `resolve_platform_refs`
- ✅ Router async
- ✅ `agent_generator.py` mis à jour (4 points de lecture template)
- ✅ `compose_renderer_service.py` mis à jour

**Placeholder scan :** Aucun TBD / TODO dans le code affiché.

**Type consistency :** `TemplateFileNotFoundError` et `TemplateNotFoundError` utilisés de façon cohérente dans les tâches 2, 3, 4, 5, 6.
