# Rôles — Migration StorageSDK

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le stockage filesystem (`{AGFLOW_DATA_DIR}/roles/`) par des colonnes SQL dans `roles` + une table `role_documents`, en supprimant `role_files_service.py`.

**Architecture:** La table `roles` reçoit les colonnes manquantes (display_name, description, service_types, identity_md, prompt_orchestrator_md). Une nouvelle table `role_documents` stocke les documents markdown avec un flag `protected` booléen (plus de suffix `_` dans les noms de fichiers). Les sections restent dans `role_sections` (déjà en DB). Les services `roles_service`, `role_documents_service`, `role_sections_service` sont réécrits pour utiliser SQL pur ; `role_files_service.py` est supprimé.

**Tech Stack:** Python 3.12 / asyncpg / PostgreSQL 16 / pytest-asyncio

---

## File Structure

| Action | Fichier |
|--------|---------|
| Créer | `backend/migrations/095_roles_storage.sql` |
| Réécrire | `backend/src/agflow/services/roles_service.py` |
| Réécrire | `backend/src/agflow/services/role_documents_service.py` |
| Modifier | `backend/src/agflow/services/role_sections_service.py` — supprimer dépendance filesystem dans `delete()` |
| Supprimer | `backend/src/agflow/services/role_files_service.py` |
| Inchangé | `backend/src/agflow/api/admin/roles.py` |
| Inchangé | `backend/src/agflow/schemas/roles.py` |
| Inchangé | `backend/tests/test_roles_service.py` |
| Inchangé | `backend/tests/test_role_documents_service.py` |
| Inchangé | `backend/tests/test_role_sections_service.py` |

---

### Task 1: Migration SQL 095 — colonnes roles + table role_documents

**Files:**
- Create: `backend/migrations/095_roles_storage.sql`

- [ ] **Step 1: Créer la migration**

```sql
-- backend/migrations/095_roles_storage.sql

-- Étendre la table roles avec les colonnes metadata (actuellement dans role.json)
ALTER TABLE roles
    ADD COLUMN IF NOT EXISTS display_name           TEXT    NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description            TEXT    NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS service_types          TEXT[]  NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS identity_md            TEXT    NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS prompt_orchestrator_md TEXT    NOT NULL DEFAULT '';

-- Trigger updated_at automatique pour roles (actuellement fait manuellement)
CREATE TRIGGER set_updated_at_roles
    BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- FK CASCADE sur role_sections → roles (actuellement absent = orphelins possibles)
ALTER TABLE role_sections
    ADD CONSTRAINT fk_role_sections_role_id
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE;

-- Table role_documents (remplace filesystem {AGFLOW_DATA_DIR}/roles/{id}/{section}/{name}.md)
CREATE TABLE IF NOT EXISTS role_documents (
    id          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    role_id     TEXT        NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    section     TEXT        NOT NULL,
    name        TEXT        NOT NULL,
    content_md  TEXT        NOT NULL DEFAULT '',
    protected   BOOLEAN     NOT NULL DEFAULT FALSE,
    parent_path TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role_id, section, name)
);

CREATE TRIGGER set_updated_at_role_documents
    BEFORE UPDATE ON role_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

- [ ] **Step 2: Vérifier la syntaxe (lint SQL optionnel)**

Le runner de migration (`uv run python -m agflow.db.migrations`) est sur LXC 201 — ne pas lancer depuis Windows. Vérification uniquement visuelle de la syntaxe SQL.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/095_roles_storage.sql
git commit -m "feat(db): colonnes roles + table role_documents pour migration StorageSDK"
```

---

### Task 2: roles_service.py — lecture/écriture SQL sans filesystem

**Files:**
- Modify: `backend/src/agflow/services/roles_service.py`
- Test: `backend/tests/test_roles_service.py` (inchangé — tests existants couvrent déjà)

- [ ] **Step 1: Réécrire roles_service.py**

```python
# backend/src/agflow/services/roles_service.py
from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.roles import RoleSummary

_log = structlog.get_logger(__name__)

_ROLE_DB_COLS = (
    "id, display_name, description, service_types, "
    "identity_md, prompt_orchestrator_md, created_at, updated_at"
)


class RoleNotFoundError(Exception):
    pass


class DuplicateRoleError(Exception):
    pass


class InvalidServiceTypeError(Exception):
    pass


def _row_to_summary(row: dict[str, Any]) -> RoleSummary:
    return RoleSummary(
        id=row["id"],
        display_name=row["display_name"],
        description=row["description"],
        service_types=list(row["service_types"] or []),
        identity_md=row["identity_md"],
        prompt_orchestrator_md=row["prompt_orchestrator_md"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _validate_service_types(names: list[str]) -> None:
    if not names:
        return
    from agflow.services import service_types_service
    unknown = await service_types_service.validate_names(names)
    if unknown:
        raise InvalidServiceTypeError(
            f"Unknown service types: {', '.join(sorted(unknown))}"
        )


async def create(
    role_id: str,
    display_name: str,
    description: str = "",
    service_types: list[str] | None = None,
    identity_md: str = "",
) -> RoleSummary:
    await _validate_service_types(service_types or [])
    try:
        row = await fetch_one(
            "INSERT INTO roles (id, display_name, description, service_types, identity_md) "
            f"VALUES ($1, $2, $3, $4, $5) RETURNING {_ROLE_DB_COLS}",
            role_id, display_name, description, service_types or [], identity_md,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateRoleError(f"Role '{role_id}' already exists") from exc
    assert row is not None
    from agflow.services import role_sections_service
    await role_sections_service.seed_natives(role_id)
    _log.info("roles.create", role_id=role_id)
    return _row_to_summary(dict(row))


async def list_all() -> list[RoleSummary]:
    rows = await fetch_all(
        f"SELECT {_ROLE_DB_COLS} FROM roles ORDER BY display_name ASC"
    )
    return [_row_to_summary(dict(r)) for r in rows]


async def get_by_id(role_id: str) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    return _row_to_summary(dict(row))


async def update(role_id: str, **fields: Any) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_DB_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")

    if "service_types" in fields and fields["service_types"] is not None:
        await _validate_service_types(fields["service_types"])

    allowed = {"display_name", "description", "service_types", "identity_md"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if updates:
        set_clauses: list[str] = []
        params: list[Any] = [role_id]
        for col, val in updates.items():
            params.append(val)
            set_clauses.append(f"{col} = ${len(params)}")
        row = await fetch_one(
            f"UPDATE roles SET {', '.join(set_clauses)} WHERE id = $1 RETURNING {_ROLE_DB_COLS}",
            *params,
        )
        assert row is not None

    _log.info("roles.update", role_id=role_id, fields=list(fields.keys()))
    return _row_to_summary(dict(row))


async def update_prompts(role_id: str, prompt_orchestrator_md: str) -> RoleSummary:
    row = await fetch_one(
        f"UPDATE roles SET prompt_orchestrator_md = $2 WHERE id = $1 RETURNING {_ROLE_DB_COLS}",
        role_id, prompt_orchestrator_md,
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.update_prompts", role_id=role_id)
    return _row_to_summary(dict(row))


async def delete(role_id: str) -> None:
    row = await fetch_one("SELECT id FROM roles WHERE id = $1", role_id)
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    await execute("DELETE FROM roles WHERE id = $1", role_id)
    _log.info("roles.delete", role_id=role_id)
```

- [ ] **Step 2: Lint**

```bash
cd backend && uv run ruff check src/agflow/services/roles_service.py
```

Expected: no errors.

- [ ] **Step 3: Tenter les tests (DB inaccessible depuis Windows — attendu)**

```bash
cd backend && uv run pytest tests/test_roles_service.py -v 2>&1 | head -30
```

Expected: tous les tests échouent en `ERROR` au setup (connexion DB refusée). Aucune `ImportError` ni `AttributeError` ne doit apparaître.

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/services/roles_service.py
git commit -m "feat(roles): roles_service lit/écrit tout en SQL (plus de role_files_service)"
```

---

### Task 3: role_documents_service.py — réécriture SQL

**Files:**
- Modify: `backend/src/agflow/services/role_documents_service.py`
- Test: `backend/tests/test_role_documents_service.py` (inchangé — tests existants couvrent déjà)

Changements clés vs l'implémentation filesystem :
- `get_by_id(doc_id)` → `SELECT` par UUID (fin du scan O(N) du filesystem)
- `protected` → colonne BOOLEAN (fin du suffix `_` dans les noms de fichiers)
- `rename_document` → `UPDATE name = $2` (pas de renommage de fichier)
- IDs réels via `gen_random_uuid()` (fin de UUID5 déterministe)

- [ ] **Step 1: Réécrire role_documents_service.py**

```python
# backend/src/agflow/services/role_documents_service.py
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.roles import DocumentSummary

_log = structlog.get_logger(__name__)

_COLS = (
    "id, role_id, section, name, content_md, protected, parent_path, "
    "created_at, updated_at"
)


class DocumentNotFoundError(Exception):
    pass


class DuplicateDocumentError(Exception):
    pass


class ProtectedDocumentError(Exception):
    pass


def _row(row: dict[str, Any]) -> DocumentSummary:
    return DocumentSummary(
        id=row["id"],
        role_id=row["role_id"],
        section=row["section"],
        name=row["name"],
        content_md=row["content_md"],
        protected=row["protected"],
        parent_path=row["parent_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create(
    role_id: str,
    section: str,
    name: str,
    parent_path: str = "",
    content_md: str = "",
    protected: bool = False,
) -> DocumentSummary:
    from agflow.services import role_sections_service
    await role_sections_service.get(role_id, section)
    try:
        row = await fetch_one(
            "INSERT INTO role_documents "
            "(role_id, section, name, content_md, protected, parent_path) "
            f"VALUES ($1, $2, $3, $4, $5, $6) RETURNING {_COLS}",
            role_id, section, name, content_md, protected, parent_path,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateDocumentError(
            f"Document '{name}' already exists in {section} for role '{role_id}'"
        ) from exc
    assert row is not None
    _log.info("role_documents.create", role_id=role_id, section=section, name=name)
    return _row(dict(row))


async def get_by_id(doc_id: UUID) -> DocumentSummary:
    row = await fetch_one(
        f"SELECT {_COLS} FROM role_documents WHERE id = $1", doc_id
    )
    if row is None:
        raise DocumentNotFoundError(f"Document {doc_id} not found")
    return _row(dict(row))


async def list_for_role(role_id: str) -> list[DocumentSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} FROM role_documents "
        "WHERE role_id = $1 ORDER BY section ASC, name ASC",
        role_id,
    )
    return [_row(dict(r)) for r in rows]


async def update(
    doc_id: UUID,
    name: str | None = None,
    content_md: str | None = None,
    protected: bool | None = None,
) -> DocumentSummary:
    current = await get_by_id(doc_id)
    if current.protected and content_md is not None:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is locked; unlock it first"
        )

    updates: dict[str, Any] = {}
    if name is not None:
        updates["name"] = name
    if content_md is not None:
        updates["content_md"] = content_md
    if protected is not None:
        updates["protected"] = protected

    if not updates:
        return current

    set_clauses: list[str] = []
    params: list[Any] = [doc_id]
    for col, val in updates.items():
        params.append(val)
        set_clauses.append(f"{col} = ${len(params)}")

    row = await fetch_one(
        f"UPDATE role_documents SET {', '.join(set_clauses)} "
        f"WHERE id = $1 RETURNING {_COLS}",
        *params,
    )
    assert row is not None
    _log.info("role_documents.update", doc_id=str(doc_id))
    return _row(dict(row))


async def delete(doc_id: UUID) -> None:
    current = await get_by_id(doc_id)
    if current.protected:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is locked; unlock it first"
        )
    await execute("DELETE FROM role_documents WHERE id = $1", doc_id)
    _log.info("role_documents.delete", doc_id=str(doc_id))
```

- [ ] **Step 2: Lint**

```bash
cd backend && uv run ruff check src/agflow/services/role_documents_service.py
```

Expected: no errors.

- [ ] **Step 3: Tenter les tests (DB inaccessible — attendu)**

```bash
cd backend && uv run pytest tests/test_role_documents_service.py tests/test_role_sections_service.py -v 2>&1 | head -40
```

Expected: tous échouent en `ERROR` au setup DB. Aucune `ImportError` ni `AttributeError`.

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/services/role_documents_service.py
git commit -m "feat(roles): role_documents_service SQL pur (fin filesystem + UUID5 déterministe)"
```

---

### Task 4: role_sections_service.py — supprimer la dépendance filesystem dans delete()

**Files:**
- Modify: `backend/src/agflow/services/role_sections_service.py`

La seule dépendance filesystem dans ce fichier est le comptage des documents dans `delete()`. On la remplace par une requête SQL sur la nouvelle table `role_documents`.

- [ ] **Step 1: Lire le fichier pour trouver les lignes exactes**

Le bloc à remplacer se trouve dans la fonction `delete()` (lignes ~130-138 environ) :

```python
    # role_documents are now filesystem-based (under AGFLOW_DATA_DIR/roles/<id>/<section>/),
    # so we count .md files in the section directory instead of querying the
    # old role_documents table.
    base = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    section_dir = os.path.join(base, "roles", role_id, name)
    doc_count = 0
    if os.path.isdir(section_dir):
        doc_count = sum(1 for f in os.listdir(section_dir) if f.endswith(".md"))
    if doc_count > 0:
        raise SectionNotEmptyError(
            f"Section '{name}' still has {doc_count} document(s)"
        )
```

- [ ] **Step 2: Remplacer ce bloc par une requête SQL**

Nouveau contenu du bloc :

```python
    row = await fetch_one(
        "SELECT COUNT(*) AS cnt FROM role_documents WHERE role_id = $1 AND section = $2",
        role_id, name,
    )
    doc_count = row["cnt"] if row else 0
    if doc_count > 0:
        raise SectionNotEmptyError(
            f"Section '{name}' still has {doc_count} document(s)"
        )
```

- [ ] **Step 3: Supprimer `import os` en tête du fichier**

La ligne `import os` (ligne 4) n'est plus nécessaire : la retirer.

- [ ] **Step 4: Lint**

```bash
cd backend && uv run ruff check src/agflow/services/role_sections_service.py
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/role_sections_service.py
git commit -m "fix(roles): role_sections.delete() compte les docs via SQL (plus de filesystem)"
```

---

### Task 5: Nettoyage — supprimer role_files_service.py

**Files:**
- Delete: `backend/src/agflow/services/role_files_service.py`

- [ ] **Step 1: Vérifier qu'il n'y a plus d'imports résiduels**

```bash
cd backend && grep -r "role_files_service" src/ tests/ 2>/dev/null
```

Expected: aucun résultat.

- [ ] **Step 2: Supprimer le fichier**

```powershell
Remove-Item "backend\src\agflow\services\role_files_service.py"
```

- [ ] **Step 3: Lint global**

```bash
cd backend && uv run ruff check src/agflow/
```

Expected: zéro nouvelles erreurs introduites par cette suppression (des erreurs préexistantes dans d'autres fichiers sont OK).

- [ ] **Step 4: Commit**

```bash
git add -u backend/src/agflow/services/role_files_service.py
git commit -m "chore(roles): suppression role_files_service.py (remplacé par SQL)"
```

---

## Self-Review

**Spec coverage :**
- ✅ `roles` table — colonnes display_name, description, service_types (TEXT[]), identity_md, prompt_orchestrator_md ajoutées via ALTER
- ✅ `role_sections` — FK CASCADE ajoutée (correction de bug préexistant)
- ✅ `role_documents` table — id UUID PK, role_id FK CASCADE, section, name, content_md, protected BOOLEAN, parent_path, timestamps + trigger
- ✅ `roles_service.py` — toutes les fonctions lisent/écrivent en SQL, trigger gère updated_at
- ✅ `role_documents_service.py` — `get_by_id()` par UUID SQL (O(1) vs O(N) filesystem), `protected` = colonne BOOLEAN
- ✅ `role_sections_service.py` — `delete()` compte les docs via SQL
- ✅ `role_files_service.py` supprimé
- ✅ Router `roles.py` inchangé — l'API REST reste identique
- ✅ Schemas `roles.py` inchangés — `DocumentSummary`, `RoleSummary` etc. compatibles
- ✅ Tests existants conservés — ils testent l'API des services, pas l'implémentation

**Placeholder scan :** aucun TBD/TODO dans le plan.

**Type consistency :**
- `_ROLE_DB_COLS` référencé identiquement dans `create`, `list_all`, `get_by_id`, `update`, `update_prompts`
- `_COLS` dans `role_documents_service` référencé identiquement dans `create`, `get_by_id`, `list_for_role`, `update`
- `DocumentSummary` reçoit exactement les colonnes de `_COLS`
- `RoleSummary` reçoit exactement les colonnes de `_ROLE_DB_COLS`

**Changements de comportement attendus (non-régressifs) :**
- `list_all()` passe de `ORDER BY id ASC` à `ORDER BY display_name ASC` (test existant passe dans les deux cas)
- Les IDs de `role_documents` sont maintenant des vrais UUIDs (`gen_random_uuid()`) au lieu de UUID5 déterministes — les clients UI doivent utiliser les IDs retournés par l'API (pas les calculer)
- Le flag `protected` est un booléen SQL au lieu d'un suffix `_` dans le nom du fichier — l'API reste identique (`protected: bool`)
