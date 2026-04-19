# M7 Phase 7a — Catalog + Registries + Projets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser les fondations du module Product Registry : registries d'images, catalogue de produits (recettes YAML en lecture seule), et projets CRUD.

**Architecture:** 3 tables PostgreSQL, 3 services asyncpg CRUD, 3 routers FastAPI admin, 5 recettes YAML chargées au startup, 2 pages frontend (Registries + Projets), catalogue en lecture seule dans une page dédiée.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg, React 18 + TypeScript + TanStack Query + shadcn/ui, PyYAML pour le parsing des recettes.

---

## File Structure

### Backend — créés

| Fichier | Responsabilité |
|---------|---------------|
| `backend/migrations/048_image_registries.sql` | Table registries d'images |
| `backend/migrations/049_product_catalog.sql` | Table catalogue produits |
| `backend/migrations/050_projects.sql` | Table projets |
| `backend/src/agflow/schemas/products.py` | DTOs Pydantic (registries, catalog, projects) |
| `backend/src/agflow/services/image_registries_service.py` | CRUD registries |
| `backend/src/agflow/services/product_catalog_service.py` | Chargement YAML + lecture catalogue |
| `backend/src/agflow/services/projects_service.py` | CRUD projets |
| `backend/src/agflow/api/admin/image_registries.py` | Router REST registries |
| `backend/src/agflow/api/admin/products.py` | Router REST catalogue (lecture seule) |
| `backend/src/agflow/api/admin/projects.py` | Router REST projets |
| `backend/data/products/outline.yaml` | Recette Outline |
| `backend/data/products/github.yaml` | Recette GitHub |
| `backend/data/products/gitlab.yaml` | Recette GitLab |
| `backend/data/products/jira.yaml` | Recette Jira |
| `backend/data/products/postgres_inline.yaml` | Recette Postgres inline |

### Backend — modifiés

| Fichier | Modification |
|---------|-------------|
| `backend/src/agflow/main.py` | Enregistrer 3 routers + sync catalogue au startup |

### Frontend — créés

| Fichier | Responsabilité |
|---------|---------------|
| `frontend/src/lib/imageRegistriesApi.ts` | Client API registries |
| `frontend/src/lib/productsApi.ts` | Client API catalogue |
| `frontend/src/lib/projectsApi.ts` | Client API projets |
| `frontend/src/hooks/useImageRegistries.ts` | Hook TanStack Query registries |
| `frontend/src/hooks/useProducts.ts` | Hook TanStack Query catalogue |
| `frontend/src/hooks/useProjects.ts` | Hook TanStack Query projets |
| `frontend/src/pages/ImageRegistriesPage.tsx` | Page CRUD registries |
| `frontend/src/pages/ProductCatalogPage.tsx` | Page catalogue (lecture seule) |
| `frontend/src/pages/ProjectsPage.tsx` | Page CRUD projets |

### Frontend — modifiés

| Fichier | Modification |
|---------|-------------|
| `frontend/src/App.tsx` | 3 routes |
| `frontend/src/components/layout/Sidebar.tsx` | 3 entrées + section Ressources |
| `frontend/src/i18n/fr.json` | Clés registries.*, products.*, projects.* |
| `frontend/src/i18n/en.json` | Idem EN |

---

### Task 1: Migrations SQL (3 tables)

**Files:**
- Create: `backend/migrations/048_image_registries.sql`
- Create: `backend/migrations/049_product_catalog.sql`
- Create: `backend/migrations/050_projects.sql`

- [ ] **Step 1: Créer la migration image_registries**

```sql
CREATE TABLE IF NOT EXISTS image_registries (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    url             TEXT NOT NULL,
    auth_type       TEXT NOT NULL DEFAULT 'none'
                    CHECK (auth_type IN ('none', 'basic', 'token')),
    credential_ref  TEXT,
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default registries
INSERT INTO image_registries (id, display_name, url, is_default)
VALUES
    ('docker-io', 'Docker Hub', 'https://docker.io', TRUE),
    ('ghcr-io', 'GitHub Container Registry', 'https://ghcr.io', TRUE)
ON CONFLICT (id) DO NOTHING;
```

- [ ] **Step 2: Créer la migration product_catalog**

```sql
CREATE TABLE IF NOT EXISTS product_catalog (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'other'
                    CHECK (category IN ('wiki', 'tasks', 'code', 'design', 'infra', 'other')),
    tags            TEXT[] NOT NULL DEFAULT '{}',
    min_ram_mb      INTEGER NOT NULL DEFAULT 512,
    mcp_package_id  TEXT,
    config_only     BOOLEAN NOT NULL DEFAULT FALSE,
    has_openapi     BOOLEAN NOT NULL DEFAULT FALSE,
    recipe_yaml     TEXT NOT NULL,
    recipe_version  TEXT NOT NULL DEFAULT '1.0.0',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 3: Créer la migration projects**

```sql
CREATE TABLE IF NOT EXISTS projects (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    environment     TEXT NOT NULL DEFAULT 'dev'
                    CHECK (environment IN ('dev', 'staging', 'prod')),
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 4: Vérifier le lint et commit**

Run: `cd backend && uv run ruff check src/`
```bash
git add backend/migrations/048_image_registries.sql backend/migrations/049_product_catalog.sql backend/migrations/050_projects.sql
git commit -m "feat(m7): migrations tables image_registries, product_catalog, projects"
```

---

### Task 2: Schemas Pydantic products.py

**Files:**
- Create: `backend/src/agflow/schemas/products.py`

- [ ] **Step 1: Créer les schemas**

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Image Registries ─────────────────────────────────────

AuthType = Literal["none", "basic", "token"]


class RegistryCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    auth_type: AuthType = "none"
    credential_ref: str | None = None


class RegistryUpdate(BaseModel):
    display_name: str | None = None
    url: str | None = None
    auth_type: AuthType | None = None
    credential_ref: str | None = None


class RegistrySummary(BaseModel):
    id: str
    display_name: str
    url: str
    auth_type: AuthType
    credential_ref: str | None
    is_default: bool
    created_at: datetime
    updated_at: datetime


# ── Product Catalog ──────────────────────────────────────

Category = Literal["wiki", "tasks", "code", "design", "infra", "other"]


class ProductSummary(BaseModel):
    id: str
    display_name: str
    description: str
    category: Category
    tags: list[str]
    min_ram_mb: int
    config_only: bool
    has_openapi: bool
    mcp_package_id: str | None
    recipe_version: str
    created_at: datetime
    updated_at: datetime


class ProductDetail(ProductSummary):
    recipe_yaml: str
    recipe_parsed: dict[str, Any] | None = None


# ── Projects ─────────────────────────────────────────────

Environment = Literal["dev", "staging", "prod"]


class ProjectCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    environment: Environment = "dev"
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    environment: Environment | None = None
    tags: list[str] | None = None


class ProjectSummary(BaseModel):
    id: str
    display_name: str
    description: str
    environment: Environment
    tags: list[str]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 2: Vérifier le lint**

Run: `cd backend && uv run ruff check src/agflow/schemas/products.py`

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/schemas/products.py
git commit -m "feat(m7): schemas Pydantic registries, catalogue, projets"
```

---

### Task 3: Recettes YAML (5 produits)

**Files:**
- Create: `backend/data/products/outline.yaml`
- Create: `backend/data/products/github.yaml`
- Create: `backend/data/products/gitlab.yaml`
- Create: `backend/data/products/jira.yaml`
- Create: `backend/data/products/postgres_inline.yaml`

- [ ] **Step 1: Créer les 5 recettes**

Les recettes sont celles définies dans la spec M7 §2.2 et §6.1. Chaque fichier YAML contient : id, display_name, description, category, tags, services (si applicable), openapi (si applicable), secrets_required, variables.

- [ ] **Step 2: Commit**

```bash
git add backend/data/products/
git commit -m "feat(m7): recettes YAML — Outline, GitHub, GitLab, Jira, Postgres inline"
```

---

### Task 4: Service image_registries_service.py

**Files:**
- Create: `backend/src/agflow/services/image_registries_service.py`

- [ ] **Step 1: Créer le service**

```python
from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.products import RegistrySummary

_log = structlog.get_logger(__name__)


class RegistryNotFoundError(Exception):
    pass


class DuplicateRegistryError(Exception):
    pass


async def list_all() -> list[RegistrySummary]:
    rows = await fetch_all(
        "SELECT * FROM image_registries ORDER BY is_default DESC, display_name"
    )
    return [RegistrySummary(**r) for r in rows]


async def get_by_id(registry_id: str) -> RegistrySummary:
    row = await fetch_one(
        "SELECT * FROM image_registries WHERE id = $1", registry_id
    )
    if row is None:
        raise RegistryNotFoundError(f"Registry '{registry_id}' not found")
    return RegistrySummary(**row)


async def create(
    registry_id: str,
    display_name: str,
    url: str,
    auth_type: str = "none",
    credential_ref: str | None = None,
) -> RegistrySummary:
    try:
        row = await fetch_one(
            """
            INSERT INTO image_registries (id, display_name, url, auth_type, credential_ref)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            registry_id, display_name, url, auth_type, credential_ref,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateRegistryError(f"Registry '{registry_id}' already exists") from exc
    assert row is not None
    _log.info("registries.create", id=registry_id)
    return RegistrySummary(**row)


async def update(registry_id: str, **kwargs: Any) -> RegistrySummary:
    existing = await get_by_id(registry_id)
    if existing.is_default:
        # Only allow display_name update on defaults
        kwargs = {k: v for k, v in kwargs.items() if k == "display_name" and v is not None}
    updates = {k: v for k, v in kwargs.items() if v is not None}
    if not updates:
        return existing
    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    row = await fetch_one(
        f"UPDATE image_registries SET {', '.join(sets)}, updated_at = NOW() WHERE id = $1 RETURNING *",
        registry_id, *updates.values(),
    )
    assert row is not None
    _log.info("registries.update", id=registry_id)
    return RegistrySummary(**row)


async def delete(registry_id: str) -> None:
    existing = await get_by_id(registry_id)
    if existing.is_default:
        raise RegistryNotFoundError("Cannot delete default registry")
    from agflow.db.pool import execute
    await execute("DELETE FROM image_registries WHERE id = $1", registry_id)
    _log.info("registries.delete", id=registry_id)
```

- [ ] **Step 2: Vérifier le lint et commit**

Run: `cd backend && uv run ruff check src/agflow/services/image_registries_service.py`

```bash
git add backend/src/agflow/services/image_registries_service.py
git commit -m "feat(m7): service CRUD image registries"
```

---

### Task 5: Service product_catalog_service.py

**Files:**
- Create: `backend/src/agflow/services/product_catalog_service.py`

- [ ] **Step 1: Créer le service**

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog
import yaml

from agflow.db.pool import fetch_all, fetch_one
from agflow.schemas.products import ProductDetail, ProductSummary

_log = structlog.get_logger(__name__)


class ProductNotFoundError(Exception):
    pass


def _products_dir() -> Path:
    """Directory containing product recipe YAML files."""
    return Path(__file__).parent.parent.parent.parent / "data" / "products"


async def sync_from_disk() -> int:
    """Load/update product recipes from YAML files into the database."""
    from agflow.db.pool import execute

    products_dir = _products_dir()
    if not products_dir.is_dir():
        _log.warning("product_catalog.no_dir", path=str(products_dir))
        return 0

    count = 0
    for yaml_path in sorted(products_dir.glob("*.yaml")):
        with open(yaml_path, encoding="utf-8") as f:
            raw = f.read()
        recipe = yaml.safe_load(raw)
        if not isinstance(recipe, dict) or "id" not in recipe:
            continue

        await execute(
            """
            INSERT INTO product_catalog (
                id, display_name, description, category, tags,
                min_ram_mb, mcp_package_id, config_only, has_openapi,
                recipe_yaml, recipe_version
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                tags = EXCLUDED.tags,
                min_ram_mb = EXCLUDED.min_ram_mb,
                mcp_package_id = EXCLUDED.mcp_package_id,
                config_only = EXCLUDED.config_only,
                has_openapi = EXCLUDED.has_openapi,
                recipe_yaml = EXCLUDED.recipe_yaml,
                recipe_version = EXCLUDED.recipe_version,
                updated_at = NOW()
            """,
            recipe["id"],
            recipe.get("display_name", recipe["id"]),
            recipe.get("description", ""),
            recipe.get("category", "other"),
            recipe.get("tags", []),
            recipe.get("min_ram_mb", 512),
            recipe.get("mcp_package_id"),
            recipe.get("config_only", False),
            "openapi" in recipe,
            raw,
            recipe.get("recipe_version", "1.0.0"),
        )
        count += 1
        _log.info("product_catalog.sync", id=recipe["id"])

    return count


async def list_all() -> list[ProductSummary]:
    rows = await fetch_all(
        "SELECT * FROM product_catalog ORDER BY category, display_name"
    )
    return [ProductSummary(**r) for r in rows]


async def get_by_id(product_id: str) -> ProductDetail:
    row = await fetch_one(
        "SELECT * FROM product_catalog WHERE id = $1", product_id
    )
    if row is None:
        raise ProductNotFoundError(f"Product '{product_id}' not found")
    parsed = None
    try:
        parsed = yaml.safe_load(row["recipe_yaml"])
    except Exception:
        pass
    return ProductDetail(**row, recipe_parsed=parsed)
```

- [ ] **Step 2: Vérifier le lint et commit**

```bash
git add backend/src/agflow/services/product_catalog_service.py
git commit -m "feat(m7): service product catalog — chargement YAML + lecture"
```

---

### Task 6: Service projects_service.py

**Files:**
- Create: `backend/src/agflow/services/projects_service.py`

- [ ] **Step 1: Créer le service**

```python
from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.products import ProjectSummary

_log = structlog.get_logger(__name__)


class ProjectNotFoundError(Exception):
    pass


class DuplicateProjectError(Exception):
    pass


async def list_all() -> list[ProjectSummary]:
    rows = await fetch_all("SELECT * FROM projects ORDER BY display_name")
    return [ProjectSummary(**r) for r in rows]


async def get_by_id(project_id: str) -> ProjectSummary:
    row = await fetch_one("SELECT * FROM projects WHERE id = $1", project_id)
    if row is None:
        raise ProjectNotFoundError(f"Project '{project_id}' not found")
    return ProjectSummary(**row)


async def create(
    project_id: str,
    display_name: str,
    description: str = "",
    environment: str = "dev",
    tags: list[str] | None = None,
) -> ProjectSummary:
    try:
        row = await fetch_one(
            """
            INSERT INTO projects (id, display_name, description, environment, tags)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            project_id, display_name, description, environment, tags or [],
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateProjectError(f"Project '{project_id}' already exists") from exc
    assert row is not None
    _log.info("projects.create", id=project_id)
    return ProjectSummary(**row)


async def update(project_id: str, **kwargs: Any) -> ProjectSummary:
    await get_by_id(project_id)
    updates = {k: v for k, v in kwargs.items() if v is not None}
    if not updates:
        return await get_by_id(project_id)
    sets = [f"{k} = ${i}" for i, k in enumerate(updates, 2)]
    row = await fetch_one(
        f"UPDATE projects SET {', '.join(sets)}, updated_at = NOW() WHERE id = $1 RETURNING *",
        project_id, *updates.values(),
    )
    assert row is not None
    _log.info("projects.update", id=project_id)
    return ProjectSummary(**row)


async def delete(project_id: str) -> None:
    row = await fetch_one("DELETE FROM projects WHERE id = $1 RETURNING id", project_id)
    if row is None:
        raise ProjectNotFoundError(f"Project '{project_id}' not found")
    _log.info("projects.delete", id=project_id)
```

- [ ] **Step 2: Vérifier le lint et commit**

```bash
git add backend/src/agflow/services/projects_service.py
git commit -m "feat(m7): service CRUD projets"
```

---

### Task 7: Routers API admin (3 routers + main.py)

**Files:**
- Create: `backend/src/agflow/api/admin/image_registries.py`
- Create: `backend/src/agflow/api/admin/products.py`
- Create: `backend/src/agflow/api/admin/projects.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Créer les 3 routers**

Chaque router suit le pattern existant (require_admin, response_model, HTTPException mapping). Le router products est en lecture seule (GET list + GET detail).

- [ ] **Step 2: Enregistrer dans main.py**

Ajouter les 3 imports et `app.include_router()`. Ajouter `product_catalog_service.sync_from_disk()` dans le lifespan (après les migrations).

- [ ] **Step 3: Vérifier le lint et commit**

```bash
git add backend/src/agflow/api/admin/image_registries.py backend/src/agflow/api/admin/products.py backend/src/agflow/api/admin/projects.py backend/src/agflow/main.py
git commit -m "feat(m7): routers admin registries + catalogue + projets"
```

---

### Task 8: Frontend — API clients + hooks (6 fichiers)

**Files:**
- Create: `frontend/src/lib/imageRegistriesApi.ts`
- Create: `frontend/src/lib/productsApi.ts`
- Create: `frontend/src/lib/projectsApi.ts`
- Create: `frontend/src/hooks/useImageRegistries.ts`
- Create: `frontend/src/hooks/useProducts.ts`
- Create: `frontend/src/hooks/useProjects.ts`

- [ ] **Step 1: Créer les 3 API clients**

Chaque client suit le pattern `secretsApi.ts` : objet exporté avec méthodes async typées.

- [ ] **Step 2: Créer les 3 hooks**

Chaque hook suit le pattern `useSecrets.ts` : useQuery + useMutation + invalidateQueries.

- [ ] **Step 3: TypeScript check et commit**

Run: `cd frontend && npx tsc --noEmit`

```bash
git add frontend/src/lib/imageRegistriesApi.ts frontend/src/lib/productsApi.ts frontend/src/lib/projectsApi.ts frontend/src/hooks/useImageRegistries.ts frontend/src/hooks/useProducts.ts frontend/src/hooks/useProjects.ts
git commit -m "feat(m7): clients API + hooks TanStack Query (registries, catalogue, projets)"
```

---

### Task 9: Frontend — i18n + routes + sidebar

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Ajouter les clés i18n**

Blocs `registries.*`, `products.*`, `projects.*` en FR et EN.

- [ ] **Step 2: Ajouter 3 routes dans App.tsx**

`/image-registries`, `/product-catalog`, `/projects`

- [ ] **Step 3: Ajouter la section Ressources dans Sidebar**

Nouvelle section "Ressources" entre Plateforme et Catalogues :
```typescript
{ to: "/image-registries", label: t("registries.page_title"), icon: Boxes },
{ to: "/product-catalog", label: t("products.page_title"), icon: Package },
{ to: "/projects", label: t("projects.page_title"), icon: FolderKanban },
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(m7): i18n + routes + sidebar (registries, catalogue, projets)"
```

---

### Task 10: Frontend — ImageRegistriesPage.tsx

**Files:**
- Create: `frontend/src/pages/ImageRegistriesPage.tsx`

- [ ] **Step 1: Créer la page**

Table CRUD avec : id, display_name, url, auth_type, is_default (badge). Boutons : ajouter (PromptDialog), supprimer (ConfirmDialog, disabled pour defaults). Pattern ServiceTypesPage.

- [ ] **Step 2: TypeScript check et commit**

---

### Task 11: Frontend — ProductCatalogPage.tsx (lecture seule)

**Files:**
- Create: `frontend/src/pages/ProductCatalogPage.tsx`

- [ ] **Step 1: Créer la page**

Liste des produits avec : display_name, description, category (badge couleur), tags (badges), config_only (badge SaaS), has_openapi (badge API). Clic sur un produit → dialog détail avec la recette YAML formatée.

- [ ] **Step 2: TypeScript check et commit**

---

### Task 12: Frontend — ProjectsPage.tsx

**Files:**
- Create: `frontend/src/pages/ProjectsPage.tsx`

- [ ] **Step 1: Créer la page**

Table CRUD avec : id, display_name, environment (badge dev/staging/prod), tags, description. Boutons : ajouter (PromptDialog), éditer, supprimer (ConfirmDialog).

- [ ] **Step 2: TypeScript check et commit**

---

### Task 13: Intégration + déploiement

- [ ] **Step 1: Lint backend complet**

Run: `cd backend && uv run ruff check src/`

- [ ] **Step 2: TypeScript check complet**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 3: Déployer**

Run: `bash scripts/deploy.sh --rebuild`

- [ ] **Step 4: Test de fumée**

1. Vérifier que les 3 migrations passent (tables créées)
2. Catalogue : 5 produits chargés au startup → page catalogue les liste
3. Registries : docker.io + ghcr.io visibles avec badge "default" → ajouter une custom → supprimer
4. Projets : créer "pickup-prod" (env: prod) → modifier → supprimer
5. Sidebar : section Ressources visible avec 3 entrées
