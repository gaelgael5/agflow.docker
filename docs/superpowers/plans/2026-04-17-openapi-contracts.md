# Contrats OpenAPI — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre d'attacher des contrats OpenAPI à un agent, parser les tags, générer un markdown par tag avec commandes curl, et injecter les références dans le prompt généré.

**Architecture:** Contrats stockés en DB (table `agent_api_contracts` — le spec_content peut être volumineux). Parser OpenAPI dédié (`openapi_parser.py`) qui extrait les tags et génère le markdown. Le générateur d'agent écrit les fichiers dans `generated/docs/ctr/{slug}/` et passe `api_contracts` au template Jinja2 du prompt.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg (backend), React 18 + TypeScript (frontend), pyyaml (parsing YAML), OpenAPI 3.x

**Spec de référence:** `docs/superpowers/specs/2026-04-17-openapi-contracts-design.md` (le spec collé par l'utilisateur dans le chat)

---

## File Structure

**Backend — créés :**
- `backend/migrations/044_agent_api_contracts.sql` — table SQL
- `backend/src/agflow/schemas/contracts.py` — Pydantic models
- `backend/src/agflow/services/openapi_parser.py` — parser + générateur markdown
- `backend/src/agflow/services/api_contracts_service.py` — CRUD asyncpg
- `backend/src/agflow/api/admin/contracts.py` — routeur FastAPI

**Backend — modifiés :**
- `backend/pyproject.toml` — ajout `pyyaml>=6.0`
- `backend/src/agflow/main.py` — enregistrement routeur contracts
- `backend/src/agflow/services/agent_generator.py` — génération docs/ctr/ + injection prompt

**Frontend — créés :**
- `frontend/src/lib/contractsApi.ts` — client API
- `frontend/src/hooks/useContracts.ts` — hook TanStack Query
- `frontend/src/components/ContractFormDialog.tsx` — dialog création/édition

**Frontend — modifiés :**
- `frontend/src/pages/AgentEditorPage.tsx` — nouvel onglet Contrats API
- `frontend/src/i18n/fr.json`, `en.json` — clés `contracts.*`

---

## Task 1 : Backend — migration SQL + schémas + dépendance pyyaml

**Files:**
- Create: `backend/migrations/044_agent_api_contracts.sql`
- Create: `backend/src/agflow/schemas/contracts.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1.1 : Créer la migration SQL**

```sql
CREATE TABLE IF NOT EXISTS agent_api_contracts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        TEXT NOT NULL,
    slug            TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source_type IN ('upload', 'url', 'manual')),
    source_url      TEXT,
    spec_content    TEXT NOT NULL,
    base_url        TEXT NOT NULL DEFAULT '',
    auth_header     TEXT NOT NULL DEFAULT 'Authorization',
    auth_prefix     TEXT NOT NULL DEFAULT 'Bearer',
    auth_secret_ref TEXT,
    parsed_tags     JSONB NOT NULL DEFAULT '[]',
    position        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_agent_api_contracts_agent
    ON agent_api_contracts(agent_id, position);
```

Note : `agent_id` est TEXT (pas UUID FK) car les agents sont sur filesystem, pas en DB.

- [ ] **Step 1.2 : Créer les schémas Pydantic**

`backend/src/agflow/schemas/contracts.py` :

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ContractCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    source_type: Literal["upload", "url", "manual"] = "manual"
    source_url: str | None = None
    spec_content: str = Field(min_length=1)
    base_url: str = ""
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer"
    auth_secret_ref: str | None = None


class ContractUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    source_url: str | None = None
    spec_content: str | None = None
    base_url: str | None = None
    auth_header: str | None = None
    auth_prefix: str | None = None
    auth_secret_ref: str | None = None


class TagSummary(BaseModel):
    slug: str
    name: str
    description: str
    operation_count: int


class ContractSummary(BaseModel):
    id: UUID
    agent_id: str
    slug: str
    display_name: str
    description: str
    source_type: str
    source_url: str | None
    base_url: str
    auth_header: str
    auth_prefix: str
    auth_secret_ref: str | None
    parsed_tags: list[TagSummary]
    position: int
    created_at: datetime
    updated_at: datetime


class ContractDetail(ContractSummary):
    spec_content: str
```

- [ ] **Step 1.3 : Ajouter pyyaml dans pyproject.toml**

Dans `[project].dependencies`, ajouter `"pyyaml>=6.0",`.

Puis `cd backend && uv sync`.

- [ ] **Step 1.4 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/schemas/contracts.py
git add backend/migrations/044_agent_api_contracts.sql backend/src/agflow/schemas/contracts.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(contracts): migration SQL + schémas Pydantic + dépendance pyyaml"
```

---

## Task 2 : Backend — parser OpenAPI

**Files:**
- Create: `backend/src/agflow/services/openapi_parser.py`

Ce module est pur (pas d'IO, pas de DB) — il parse un string OpenAPI et génère du markdown.

- [ ] **Step 2.1 : Créer le parser**

```python
from __future__ import annotations

import json
import re
from typing import Any

import yaml


def _load_spec(content: str) -> dict[str, Any]:
    """Parse JSON ou YAML automatiquement."""
    content = content.strip()
    if content.startswith("{"):
        return json.loads(content)
    return yaml.safe_load(content)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")


def parse_openapi_tags(spec_content: str) -> list[dict[str, Any]]:
    """Parse un contrat OpenAPI et retourne la liste des tags avec leurs opérations."""
    spec = _load_spec(spec_content)

    declared_tags = {
        t["name"]: t.get("description", "")
        for t in spec.get("tags", [])
    }

    tag_ops: dict[str, list[dict[str, Any]]] = {}
    for path, methods in spec.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            if not isinstance(operation, dict):
                continue
            op_tags = operation.get("tags", ["untagged"])
            for tag in op_tags:
                tag_ops.setdefault(tag, []).append({
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""),
                    "description": operation.get("description", ""),
                    "parameters": operation.get("parameters", []),
                    "request_body": operation.get("requestBody"),
                    "responses": operation.get("responses", {}),
                })

    return [
        {
            "slug": _slugify(tag_name),
            "name": tag_name,
            "description": declared_tags.get(tag_name, ""),
            "operation_count": len(ops),
            "operations": ops,
        }
        for tag_name, ops in sorted(tag_ops.items())
    ]


def detect_base_url(spec_content: str) -> str:
    """Extrait base_url depuis servers[0].url si disponible."""
    try:
        spec = _load_spec(spec_content)
        servers = spec.get("servers", [])
        if servers and isinstance(servers[0], dict):
            return servers[0].get("url", "")
    except Exception:
        pass
    return ""


def _extract_body_schema(request_body: dict[str, Any] | None) -> dict[str, Any] | None:
    """Extrait le schema JSON du body (simplifié)."""
    if not request_body:
        return None
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    if not schema:
        return None
    # Build a simple example from properties
    properties = schema.get("properties", {})
    if not properties:
        return schema
    example: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get("type", "string")
        if prop_type == "string":
            example[prop_name] = prop_schema.get("example", f"<{prop_name}>")
        elif prop_type == "integer":
            example[prop_name] = prop_schema.get("example", 0)
        elif prop_type == "boolean":
            example[prop_name] = prop_schema.get("example", False)
        elif prop_type == "array":
            example[prop_name] = []
        elif prop_type == "object":
            example[prop_name] = {}
        else:
            example[prop_name] = f"<{prop_name}>"
    return example


def _build_curl(
    op: dict[str, Any],
    base_url: str,
    auth_header: str,
    auth_prefix: str,
    auth_secret_ref: str,
) -> str:
    method = op["method"]
    path = op["path"]
    parts = ["curl -s"]
    if method != "GET":
        parts.append(f"-X {method}")
    if auth_secret_ref:
        parts.append(f'-H "{auth_header}: {auth_prefix} {auth_secret_ref}"')
    if op["request_body"]:
        parts.append('-H "Content-Type: application/json"')
        body = _extract_body_schema(op["request_body"])
        if body:
            parts.append(f"-d '{json.dumps(body, ensure_ascii=False)}'")
    parts.append(f"{base_url}{path}")
    return " \\\n  ".join(parts)


def generate_tag_markdown(
    tag: dict[str, Any],
    base_url: str,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer",
    auth_secret_ref: str = "",
) -> str:
    """Génère le markdown documentant un tag avec les commandes curl."""
    lines = [f"# {tag['name']}", ""]

    if tag["description"]:
        lines.append(tag["description"])
        lines.append("")

    lines.append(f"Base URL : `{base_url}`")
    if auth_secret_ref:
        lines.append(f"Auth : `{auth_header}: {auth_prefix} {auth_secret_ref}`")
    lines.append("")

    for op in tag.get("operations", []):
        lines.append(f"## {op['method']} {op['path']}")
        if op["summary"]:
            lines.append(op["summary"])
        lines.append("")

        path_params = [p for p in op.get("parameters", []) if p.get("in") == "path"]
        query_params = [p for p in op.get("parameters", []) if p.get("in") == "query"]

        if path_params:
            lines.append("Paramètres URL :")
            for p in path_params:
                req = " (requis)" if p.get("required") else ""
                lines.append(f"- `{p['name']}`{req} — {p.get('description', '')}")
            lines.append("")

        if query_params:
            lines.append("Paramètres query :")
            for p in query_params:
                req = " (requis)" if p.get("required") else ""
                lines.append(f"- `{p['name']}`{req} — {p.get('description', '')}")
            lines.append("")

        if op.get("request_body"):
            body = _extract_body_schema(op["request_body"])
            if body:
                lines.append("Body JSON :")
                lines.append("```json")
                lines.append(json.dumps(body, indent=2, ensure_ascii=False))
                lines.append("```")
                lines.append("")

        lines.append("```bash")
        lines.append(_build_curl(op, base_url, auth_header, auth_prefix, auth_secret_ref))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2.2 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/openapi_parser.py
git add backend/src/agflow/services/openapi_parser.py
git commit -m "feat(contracts): parser OpenAPI + générateur markdown par tag"
```

---

## Task 3 : Backend — service CRUD asyncpg

**Files:**
- Create: `backend/src/agflow/services/api_contracts_service.py`

- [ ] **Step 3.1 : Créer le service**

```python
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.contracts import ContractDetail, ContractSummary, TagSummary
from agflow.services import openapi_parser

_log = structlog.get_logger(__name__)

_SUMMARY_COLS = (
    "id, agent_id, slug, display_name, description, source_type, source_url, "
    "base_url, auth_header, auth_prefix, auth_secret_ref, parsed_tags, "
    "position, created_at, updated_at"
)

_DETAIL_COLS = f"{_SUMMARY_COLS}, spec_content"


def _parse_tags(raw: Any) -> list[TagSummary]:
    tags = raw if isinstance(raw, list) else json.loads(raw or "[]")
    return [
        TagSummary(
            slug=t.get("slug", ""),
            name=t.get("name", ""),
            description=t.get("description", ""),
            operation_count=t.get("operation_count", 0),
        )
        for t in tags
    ]


def _row_to_summary(row: dict[str, Any]) -> ContractSummary:
    return ContractSummary(
        id=row["id"],
        agent_id=row["agent_id"],
        slug=row["slug"],
        display_name=row["display_name"],
        description=row["description"],
        source_type=row["source_type"],
        source_url=row["source_url"],
        base_url=row["base_url"],
        auth_header=row["auth_header"],
        auth_prefix=row["auth_prefix"],
        auth_secret_ref=row["auth_secret_ref"],
        parsed_tags=_parse_tags(row["parsed_tags"]),
        position=row["position"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_detail(row: dict[str, Any]) -> ContractDetail:
    return ContractDetail(
        **_row_to_summary(row).model_dump(),
        spec_content=row["spec_content"],
    )


class ContractNotFoundError(Exception):
    pass


class DuplicateContractError(Exception):
    pass


async def list_for_agent(agent_id: str) -> list[ContractSummary]:
    rows = await fetch_all(
        f"SELECT {_SUMMARY_COLS} FROM agent_api_contracts "
        "WHERE agent_id = $1 ORDER BY position, slug",
        agent_id,
    )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(contract_id: UUID) -> ContractDetail:
    row = await fetch_one(
        f"SELECT {_DETAIL_COLS} FROM agent_api_contracts WHERE id = $1",
        contract_id,
    )
    if row is None:
        raise ContractNotFoundError(f"Contract {contract_id} not found")
    return _row_to_detail(row)


async def create(agent_id: str, slug: str, display_name: str, description: str,
                 source_type: str, source_url: str | None, spec_content: str,
                 base_url: str, auth_header: str, auth_prefix: str,
                 auth_secret_ref: str | None) -> ContractSummary:
    # Parse tags from spec
    tags = openapi_parser.parse_openapi_tags(spec_content)
    tag_summaries = [
        {"slug": t["slug"], "name": t["name"],
         "description": t["description"], "operation_count": t["operation_count"]}
        for t in tags
    ]

    # Auto-detect base_url if not provided
    if not base_url:
        base_url = openapi_parser.detect_base_url(spec_content)

    import asyncpg
    try:
        row = await fetch_one(
            f"""
            INSERT INTO agent_api_contracts (
                agent_id, slug, display_name, description, source_type,
                source_url, spec_content, base_url, auth_header, auth_prefix,
                auth_secret_ref, parsed_tags
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
            RETURNING {_SUMMARY_COLS}
            """,
            agent_id, slug, display_name, description, source_type,
            source_url, spec_content, base_url, auth_header, auth_prefix,
            auth_secret_ref, json.dumps(tag_summaries),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateContractError(
            f"Contract '{slug}' already exists for this agent"
        ) from exc
    assert row is not None
    _log.info("api_contracts.create", agent_id=agent_id, slug=slug, tags=len(tags))
    return _row_to_summary(row)


async def update(contract_id: UUID, **kwargs: Any) -> ContractSummary:
    current = await get_by_id(contract_id)
    updates: dict[str, Any] = {}
    for field in ("display_name", "description", "source_url", "spec_content",
                   "base_url", "auth_header", "auth_prefix", "auth_secret_ref"):
        if field in kwargs and kwargs[field] is not None:
            updates[field] = kwargs[field]

    if not updates:
        return _row_to_summary((await fetch_one(
            f"SELECT {_SUMMARY_COLS} FROM agent_api_contracts WHERE id = $1", contract_id
        )))

    # Re-parse if spec changed
    if "spec_content" in updates:
        tags = openapi_parser.parse_openapi_tags(updates["spec_content"])
        updates["parsed_tags"] = json.dumps([
            {"slug": t["slug"], "name": t["name"],
             "description": t["description"], "operation_count": t["operation_count"]}
            for t in tags
        ])

    set_parts = []
    values = []
    for i, (k, v) in enumerate(updates.items(), start=1):
        if k == "parsed_tags":
            set_parts.append(f"{k} = ${i}::jsonb")
        else:
            set_parts.append(f"{k} = ${i}")
        values.append(v)
    values.append(contract_id)
    set_clause = ", ".join(set_parts)

    row = await fetch_one(
        f"UPDATE agent_api_contracts SET {set_clause}, updated_at = NOW() "
        f"WHERE id = ${len(values)} RETURNING {_SUMMARY_COLS}",
        *values,
    )
    assert row is not None
    _log.info("api_contracts.update", contract_id=str(contract_id))
    return _row_to_summary(row)


async def delete(contract_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM agent_api_contracts WHERE id = $1 RETURNING id",
        contract_id,
    )
    if row is None:
        raise ContractNotFoundError(f"Contract {contract_id} not found")
    _log.info("api_contracts.delete", contract_id=str(contract_id))
```

- [ ] **Step 3.2 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/api_contracts_service.py
git add backend/src/agflow/services/api_contracts_service.py
git commit -m "feat(contracts): service CRUD asyncpg pour agent_api_contracts"
```

---

## Task 4 : Backend — routeur API + registration main.py

**Files:**
- Create: `backend/src/agflow/api/admin/contracts.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 4.1 : Créer le routeur**

```python
from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_admin
from agflow.schemas.contracts import (
    ContractCreate,
    ContractDetail,
    ContractSummary,
    ContractUpdate,
)
from agflow.services import api_contracts_service

router = APIRouter(
    prefix="/api/admin/agents/{agent_id}/contracts",
    tags=["admin-contracts"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ContractSummary])
async def list_contracts(agent_id: str):
    return await api_contracts_service.list_for_agent(agent_id)


@router.post("", response_model=ContractSummary, status_code=status.HTTP_201_CREATED)
async def create_contract(agent_id: str, payload: ContractCreate):
    try:
        return await api_contracts_service.create(
            agent_id=agent_id,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            source_type=payload.source_type,
            source_url=payload.source_url,
            spec_content=payload.spec_content,
            base_url=payload.base_url,
            auth_header=payload.auth_header,
            auth_prefix=payload.auth_prefix,
            auth_secret_ref=payload.auth_secret_ref,
        )
    except api_contracts_service.DuplicateContractError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{contract_id}", response_model=ContractDetail)
async def get_contract(contract_id: UUID):
    try:
        return await api_contracts_service.get_by_id(contract_id)
    except api_contracts_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contract_id}", response_model=ContractSummary)
async def update_contract(contract_id: UUID, payload: ContractUpdate):
    try:
        return await api_contracts_service.update(
            contract_id, **payload.model_dump(exclude_unset=True)
        )
    except api_contracts_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(contract_id: UUID):
    try:
        await api_contracts_service.delete(contract_id)
    except api_contracts_service.ContractNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class FetchSpecRequest(BaseModel):
    url: str


@router.post("/fetch-spec")
async def fetch_spec(payload: FetchSpecRequest):
    """Utilitaire : fetch une URL OpenAPI et retourne le contenu pour preview."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True) as client:
            response = await client.get(payload.url)
            response.raise_for_status()
            return {"content": response.text}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
```

- [ ] **Step 4.2 : Enregistrer le routeur dans main.py**

Ajouter l'import et l'include_router :
```python
from agflow.api.admin.contracts import router as admin_contracts_router
app.include_router(admin_contracts_router)
```

- [ ] **Step 4.3 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/api/admin/contracts.py
git add backend/src/agflow/api/admin/contracts.py backend/src/agflow/main.py
git commit -m "feat(contracts): routeur API CRUD /agents/{id}/contracts + registration"
```

---

## Task 5 : Backend — intégration générateur

**Files:**
- Modify: `backend/src/agflow/services/agent_generator.py`

- [ ] **Step 5.1 : Ajouter la génération docs/ctr/ + injection prompt**

Dans `agent_generator.py`, après la section qui génère les profils dans `docs/missions/` et avant le rendu final de `prompt.md` :

1. Importer `api_contracts_service` et `openapi_parser`
2. Charger les contrats de l'agent depuis la DB
3. Pour chaque contrat : créer `docs/ctr/{slug}/`, générer un `.md` par tag
4. Construire `contract_context` pour le template Jinja2
5. Passer `api_contracts=contract_context` au template

Le template prompt recevra `api_contracts` en plus de `missions`. Le fallback (sans template) appende la section "API disponibles" en Python.

Code à ajouter (entre la boucle des profils et le rendu de prompt.md) :

```python
    # ── Contrats API ────────────────────────────────────────
    from agflow.services import api_contracts_service, openapi_parser

    ctr_base_dir = os.path.join(out_dir, "docs", "ctr")
    if os.path.isdir(ctr_base_dir):
        shutil.rmtree(ctr_base_dir)

    contracts = await api_contracts_service.list_for_agent(slug)
    contract_context: list[dict[str, Any]] = []

    for contract in contracts:
        ctr_dir = os.path.join(ctr_base_dir, contract.slug)
        os.makedirs(ctr_dir, exist_ok=True)

        tags = [t.model_dump() for t in contract.parsed_tags]
        # Re-parse to get operations (parsed_tags only has summaries)
        full_detail = await api_contracts_service.get_by_id(contract.id)
        full_tags = openapi_parser.parse_openapi_tags(full_detail.spec_content)

        for tag in full_tags:
            md = openapi_parser.generate_tag_markdown(
                tag=tag,
                base_url=contract.base_url,
                auth_header=contract.auth_header,
                auth_prefix=contract.auth_prefix,
                auth_secret_ref=contract.auth_secret_ref or "",
            )
            _write(ctr_dir, f"{tag['slug']}.md", md)

        contract_context.append({
            "slug": contract.slug,
            "description": contract.description,
            "tags": [{"name": t["name"], "slug": t["slug"]} for t in full_tags],
        })

    _log.info("agent_generator.contracts_written", count=len(contracts))
```

Et dans le rendu du template prompt, ajouter `api_contracts=contract_context` aux variables :

```python
    if _prompt_template is not None:
        prompt_md = _prompt_template.render(
            role=role,
            agent=agent,
            load_section=_prompt_loader,
            missions=generated_profiles,
            api_contracts=contract_context,  # NOUVEAU
        )
```

Et dans le fallback (sans template) :

```python
    if contract_context:
        prompt_md += "\n\n## API disponibles\n"
        for ctr in contract_context:
            prompt_md += f"\n### {ctr['description']}\n"
            for tag in ctr["tags"]:
                prompt_md += f"\n- {tag['name']} : `@docs/ctr/{ctr['slug']}/{tag['slug']}.md`"
        prompt_md += "\n"
```

- [ ] **Step 5.2 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/agent_generator.py
git add backend/src/agflow/services/agent_generator.py
git commit -m "feat(contracts): génération docs/ctr/ + injection API disponibles dans prompt"
```

---

## Task 6 : Frontend — API client + hook + i18n

**Files:**
- Create: `frontend/src/lib/contractsApi.ts`
- Create: `frontend/src/hooks/useContracts.ts`
- Modify: `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json`

- [ ] **Step 6.1 : Créer contractsApi.ts**

Types + fonctions CRUD pour `/admin/agents/{agentId}/contracts`.

- [ ] **Step 6.2 : Créer useContracts.ts**

Hook TanStack Query avec `listQuery`, `createMutation`, `updateMutation`, `deleteMutation`.

- [ ] **Step 6.3 : Clés i18n**

Bloc `"contracts"` dans fr.json et en.json avec : page_title, add_button, slug, display_name, description, source_type, source_url, spec_content, base_url, auth_header, auth_prefix, auth_secret_ref, tags_detected, tag_count, confirm_delete_title, confirm_delete_message, fetch_button, save, edit, delete, refresh, no_contracts, etc.

- [ ] **Step 6.4 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/contractsApi.ts frontend/src/hooks/useContracts.ts frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(contracts): API client + hook TanStack Query + i18n FR/EN"
```

---

## Task 7 : Frontend — ContractFormDialog + onglet AgentEditorPage

**Files:**
- Create: `frontend/src/components/ContractFormDialog.tsx`
- Modify: `frontend/src/pages/AgentEditorPage.tsx`

- [ ] **Step 7.1 : Créer ContractFormDialog.tsx**

Dialog avec formulaire : slug, display_name, description, source_type (radio: url/upload/manual), source_url + fetch button, textarea pour spec_content, base_url, auth_header, auth_prefix, auth_secret_ref. Section "Tags détectés" qui se remplit après parsing du spec.

- [ ] **Step 7.2 : Ajouter l'onglet "Contrats API" dans AgentEditorPage**

Ajouter un `<TabsTrigger value="contracts">` après "roles" dans le TabsList. Ajouter le `<TabsContent value="contracts">` avec :
- Liste des contrats (cards avec slug, description, tags badges, boutons edit/delete/refresh)
- Bouton "+ Nouveau contrat" qui ouvre le dialog

- [ ] **Step 7.3 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/ContractFormDialog.tsx frontend/src/pages/AgentEditorPage.tsx
git commit -m "feat(contracts): dialog création + onglet Contrats API dans Agent Editor"
```

---

## Task 8 : Mise à jour template prompt Jinja2

**Files:** Aucun fichier code — mise à jour du template sur disque.

- [ ] **Step 8.1 : Mettre à jour agent-prompt/fr.md.j2 sur LXC 201**

Ajouter la section `api_contracts` dans le template :

```jinja2
# {{ role.display_name }}

{{ role.identity_md }}
{% if missions %}

### Missions
{% for m in missions %}
- {{ m.description }} : `{{ m.path }}`
{% endfor %}
{% endif %}
{% if api_contracts %}

## API disponibles

Tu disposes des API REST suivantes. Consulte les fiches pour les détails :
{% for contract in api_contracts %}

### {{ contract.description }}
{% for tag in contract.tags %}
- {{ tag.name }} : `@docs/ctr/{{ contract.slug }}/{{ tag.slug }}.md`
{% endfor %}
{% endfor %}
{% endif %}
```

- [ ] **Step 8.2 : Commit note (pas de fichier code modifié)**

Le template est sur le disque de production, pas dans le repo.

---

## Task 9 : Vérification + déploiement

- [ ] **Step 9.1 : TypeScript strict**
- [ ] **Step 9.2 : Ruff backend**
- [ ] **Step 9.3 : Déploiement `bash scripts/deploy.sh --rebuild`**
- [ ] **Step 9.4 : Appliquer migration SQL**
- [ ] **Step 9.5 : Test E2E**

1. Agent "agent-helper" → onglet "Contrats API" → "+ Nouveau contrat"
2. Slug: `agflow-docker-admin`, fetch depuis `http://agflow-backend:8000/openapi.json`
3. Tags détectés s'affichent
4. base_url = `${AGFLOW_API_URL}`, auth_secret_ref = `${AGFLOW_TOKEN}`
5. Sauvegarder → contrat visible avec ses tags
6. Générer → `generated/docs/ctr/agflow-docker-admin/` contient les .md
7. `prompt.md` contient "API disponibles" avec les liens `@docs/ctr/...`

---

## Self-review

- **Couverture spec** : Migration (T1), schémas (T1), parser (T2), service CRUD (T3), routeur (T4), génération (T5), frontend client+hook+i18n (T6), dialog+onglet (T7), template (T8), vérification (T9). ✓
- **Placeholder scan** : T6 et T7 décrivent le contenu en détail mais sans code complet (pages UI complexes — le sous-agent a les specs et les patterns). Les tasks backend ont le code complet. ✓
- **Type consistency** : `ContractSummary`, `ContractDetail`, `ContractCreate`, `ContractUpdate`, `TagSummary` cohérents entre backend et frontend. ✓
- **Hors scope respecté** : pas de sélection de tags, pas de SDK, pas de validation stricte, pas de versioning, pas de catalogue partagé. ✓
