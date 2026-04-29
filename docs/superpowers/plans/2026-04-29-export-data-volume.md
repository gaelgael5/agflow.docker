# Bouton "Exporter" du volume `data/` — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un bouton "Exporter" dans la topbar (admin uniquement) qui télécharge un zip streamé du volume `./data/` mappé dans le container backend.

**Architecture:** Backend FastAPI expose `GET /api/admin/system/export` protégé par `require_admin`, qui répond en `StreamingResponse` un zip généré en flux (lib `stream-zip`, pas de tempfile). Frontend ajoute un bouton dans `TopBar.tsx` qui télécharge via axios `responseType: blob` puis déclenche le download via anchor temporaire.

**Tech Stack:** Python 3.12 + FastAPI + `stream-zip` (nouveau) + structlog | React 18 + TypeScript strict + axios + lucide-react + i18next | Vitest + React Testing Library | pytest + TestClient.

**Spec source:** `docs/superpowers/specs/2026-04-29-export-data-volume-design.md`

---

## File Structure

| Fichier | Rôle |
|---------|------|
| `backend/pyproject.toml` (modifié) | Ajoute la dépendance `stream-zip` |
| `backend/src/agflow/services/system_export.py` (nouveau) | Service pur : génère le zip en flux à partir d'un répertoire racine. Aucune dépendance FastAPI/HTTP. |
| `backend/src/agflow/api/admin/system.py` (nouveau) | Router FastAPI `/api/admin/system` ; expose `GET /export`. Dépendance `require_admin` au niveau du router. |
| `backend/src/agflow/main.py` (modifié) | Import + `app.include_router(admin_system_router)` |
| `backend/tests/test_system_export_service.py` (nouveau) | Tests unitaires du service (zip valide, dossier vide, dossier inexistant, contenu attendu) |
| `backend/tests/test_system_export_endpoint.py` (nouveau) | Tests d'intégration TestClient (401, 403, 200 + Content-Disposition) |
| `frontend/src/i18n/fr.json` (modifié) | Clés `topbar.export`, `topbar.export_tooltip`, `topbar.export_error` |
| `frontend/src/i18n/en.json` (modifié) | Mêmes clés en anglais |
| `frontend/src/components/layout/TopBar.tsx` (modifié) | Bouton Export (icône `Download`), guard `useAuth().isAdmin`, handler download blob |
| `frontend/tests/components/TopBar.test.tsx` (nouveau) | Tests : bouton visible/masqué selon rôle, click déclenche bien `api.get(... blob)` + anchor |

Aucun autre fichier touché. La migration CI GHCR (`docs/superpowers/specs/2026-04-29-github-build-images-design.md`) est un chantier séparé qui suivra.

---

## Task 1 — Ajouter la dépendance `stream-zip`

**Files:**
- Modify: `backend/pyproject.toml` (bloc `dependencies`, après `jinja2>=3.1`)

- [ ] **Step 1 : Ajouter la dépendance**

Modifier `backend/pyproject.toml` :

```diff
 dependencies = [
     ...
     "jinja2>=3.1",
+    "stream-zip>=0.0.83",
 ]
```

- [ ] **Step 2 : Lock & install**

Run depuis `backend/` :

```bash
uv sync
```

Expected : pas d'erreur, `stream-zip` apparaît dans `uv.lock`.

- [ ] **Step 3 : Vérifier l'import**

Run :

```bash
cd backend && uv run python -c "from stream_zip import async_stream_zip, ZIP_64; print('ok')"
```

Expected : `ok`.

- [ ] **Step 4 : Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(backend): ajoute la dépendance stream-zip pour l'export data"
```

---

## Task 2 — Service `system_export` : helper `export_filename()`

**Files:**
- Create: `backend/src/agflow/services/system_export.py`
- Create: `backend/tests/test_system_export_service.py`

- [ ] **Step 1 : Test rouge**

Créer `backend/tests/test_system_export_service.py` :

```python
from __future__ import annotations

import re

from agflow.services.system_export import export_filename


def test_export_filename_format() -> None:
    name = export_filename()
    assert re.fullmatch(r"agflow-data-\d{8}-\d{6}\.zip", name), name
```

- [ ] **Step 2 : Run, vérifier qu'il échoue**

```bash
cd backend && uv run pytest tests/test_system_export_service.py::test_export_filename_format -v
```

Expected : `ImportError` ou `ModuleNotFoundError: agflow.services.system_export`.

- [ ] **Step 3 : Implémentation minimale**

Créer `backend/src/agflow/services/system_export.py` :

```python
"""Stream a zip archive of the data volume.

The data volume is the directory pointed at by AGFLOW_DATA_DIR (defaults to
/app/data inside the backend container, bind-mounted from the host as ./data).
We stream the zip without buffering: each file is read and zipped on the fly,
so memory stays flat regardless of the volume size.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path  # noqa: F401  (used in subsequent tasks)


def export_filename() -> str:
    """Return a UTC-timestamped filename like agflow-data-20260429-141500.zip."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"agflow-data-{ts}.zip"
```

> **Note :** l'import `Path` est introduit dès Task 2 pour éviter de toucher le bloc d'imports à chaque task. `# noqa: F401` neutralise temporairement l'avertissement "import inutilisé" — il sera consommé dès Task 3.

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_system_export_service.py::test_export_filename_format -v
```

Expected : `PASSED`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/system_export.py backend/tests/test_system_export_service.py
git commit -m "feat(system-export): helper export_filename horodaté UTC"
```

---

## Task 3 — Service `system_export` : itérateur de fichiers `_iter_files()`

**Files:**
- Modify: `backend/src/agflow/services/system_export.py`
- Modify: `backend/tests/test_system_export_service.py`

- [ ] **Step 1 : Tests rouges**

Ajouter dans `backend/tests/test_system_export_service.py` :

```python
from pathlib import Path

import pytest

from agflow.services.system_export import _iter_files


def test_iter_files_yields_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"world")

    rels = sorted(rel for rel, _ in _iter_files(tmp_path))
    assert rels == ["a.txt", "sub/b.txt"]


def test_iter_files_skips_directories(tmp_path: Path) -> None:
    (tmp_path / "empty_dir").mkdir()
    (tmp_path / "f.txt").write_bytes(b"x")
    rels = [rel for rel, _ in _iter_files(tmp_path)]
    assert rels == ["f.txt"]


def test_iter_files_returns_empty_when_root_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list(_iter_files(missing)) == []


def test_iter_files_returns_empty_when_root_is_empty(tmp_path: Path) -> None:
    assert list(_iter_files(tmp_path)) == []
```

- [ ] **Step 2 : Run, vérifier que ça échoue**

```bash
cd backend && uv run pytest tests/test_system_export_service.py -v
```

Expected : 4 tests rouges sur `_iter_files`, le test `export_filename` reste vert.

- [ ] **Step 3 : Implémentation**

Modifier `backend/src/agflow/services/system_export.py` :

1. Ajouter au bloc d'imports `from collections.abc import Iterator` (juste avant `from datetime`).
2. Retirer le `# noqa: F401` sur l'import `Path` (il devient consommé).
3. Ajouter la fonction `_iter_files` à la fin du fichier :

```python
def _iter_files(root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (relative_posix_path, absolute_path) for every regular file under root.

    Empty directories and broken symlinks are skipped. If root does not exist or
    is not a directory, the iterator yields nothing (no exception).
    """
    if not root.exists() or not root.is_dir():
        return
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        yield rel, p
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_system_export_service.py -v
```

Expected : 5 tests verts.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/system_export.py backend/tests/test_system_export_service.py
git commit -m "feat(system-export): itérateur de fichiers récursif tolérant aux dossiers absents/vides"
```

---

## Task 4 — Service `system_export` : générateur async `iter_data_zip()`

**Files:**
- Modify: `backend/src/agflow/services/system_export.py`
- Modify: `backend/tests/test_system_export_service.py`

- [ ] **Step 1 : Tests rouges**

Ajouter dans `backend/tests/test_system_export_service.py` :

```python
import io
import zipfile

from agflow.services.system_export import iter_data_zip


async def _collect(gen) -> bytes:
    chunks: list[bytes] = []
    async for c in gen:
        chunks.append(c)
    return b"".join(chunks)


@pytest.mark.asyncio
async def test_iter_data_zip_produces_valid_zip(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"hello")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"world")

    blob = await _collect(iter_data_zip(tmp_path, user_id="admin@example.com"))

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert sorted(zf.namelist()) == ["a.txt", "sub/b.txt"]
        assert zf.read("a.txt") == b"hello"
        assert zf.read("sub/b.txt") == b"world"


@pytest.mark.asyncio
async def test_iter_data_zip_handles_empty_dir(tmp_path: Path) -> None:
    blob = await _collect(iter_data_zip(tmp_path, user_id="admin@example.com"))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.namelist() == []


@pytest.mark.asyncio
async def test_iter_data_zip_handles_missing_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    blob = await _collect(iter_data_zip(missing, user_id="admin@example.com"))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        assert zf.namelist() == []
```

- [ ] **Step 2 : Run, vérifier que ça échoue**

```bash
cd backend && uv run pytest tests/test_system_export_service.py -v
```

Expected : 3 tests rouges sur `iter_data_zip` (ImportError).

- [ ] **Step 3 : Implémentation**

Modifier `backend/src/agflow/services/system_export.py` — le bloc d'imports en tête de fichier devient (remplace l'existant) :

```python
"""Stream a zip archive of the data volume.

The data volume is the directory pointed at by AGFLOW_DATA_DIR (defaults to
/app/data inside the backend container, bind-mounted from the host as ./data).
We stream the zip without buffering: each file is read and zipped on the fly,
so memory stays flat regardless of the volume size.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from pathlib import Path

import structlog
from stream_zip import ZIP_64, async_stream_zip

logger = structlog.get_logger(__name__)

_CHUNK_SIZE = 64 * 1024
_DEFAULT_PERMS = 0o644
```

> **Note :** la docstring de tête, `from __future__ import annotations`, et l'import `from pathlib import Path` étaient déjà présents (cf. Tasks 2 et 3). Cette étape ajoute `AsyncIterator`, `structlog`, les imports `stream_zip`, le logger et les constantes.

Ajouter à la fin du fichier :

```python
async def iter_data_zip(root: Path, *, user_id: str) -> AsyncIterator[bytes]:
    """Stream a zip archive of `root` as bytes chunks.

    Yields raw zip bytes suitable for an HTTP StreamingResponse. The archive is
    flat (paths inside the zip are relative to `root`). When `root` is missing
    or empty, yields a valid empty zip. Logs total size & duration on completion.
    """
    started = datetime.now(timezone.utc)
    total = 0

    async def _members():
        modified = datetime.now(timezone.utc)
        for rel, abs_path in _iter_files(root):
            yield rel, modified, _DEFAULT_PERMS, ZIP_64, _read_file_chunks(abs_path)

    async for chunk in async_stream_zip(_members()):
        total += len(chunk)
        yield chunk

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    logger.info(
        "system.export",
        user_id=user_id,
        size_bytes=total,
        duration_s=round(duration, 3),
    )


def _read_file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as f:
        while True:
            buf = f.read(_CHUNK_SIZE)
            if not buf:
                return
            yield buf
```

> **Note pour l'implémenteur :** `async_stream_zip` accepte un async generator de tuples `(name, modified_at, perms, zip64_flag, chunks_iter)`. `chunks_iter` peut être un générateur sync — la lib le consomme correctement. Pas besoin d'`aiofiles`.

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_system_export_service.py -v
```

Expected : 8 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/system_export.py tests/test_system_export_service.py
cd backend && uv run ruff format src/agflow/services/system_export.py tests/test_system_export_service.py
```

Expected : aucune violation.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/system_export.py backend/tests/test_system_export_service.py
git commit -m "feat(system-export): générateur zip streamé via stream-zip avec audit log"
```

---

## Task 5 — Router admin `/api/admin/system/export`

**Files:**
- Create: `backend/src/agflow/api/admin/system.py`
- Modify: `backend/src/agflow/main.py` (imports + `include_router`)

- [ ] **Step 1 : Créer le router**

Créer `backend/src/agflow/api/admin/system.py` :

```python
"""Admin endpoints touching system-level concerns (data export, etc.)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agflow.auth.dependencies import require_admin
from agflow.services.system_export import export_filename, iter_data_zip

router = APIRouter(
    prefix="/api/admin/system",
    tags=["admin-system"],
    dependencies=[Depends(require_admin)],
)


def _data_dir() -> Path:
    return Path(os.environ.get("AGFLOW_DATA_DIR", "/app/data"))


@router.get("/export")
async def export_data_volume(
    user_id: str = Depends(require_admin),
) -> StreamingResponse:
    filename = export_filename()
    return StreamingResponse(
        iter_data_zip(_data_dir(), user_id=user_id),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

> **Note :** `require_admin` apparaît à la fois en `dependencies` (router) et en `Depends(require_admin)` (param) — la version param injecte la valeur (l'email du user) dans le handler. C'est le pattern utilisé par les autres routers du projet.

- [ ] **Step 2 : Enregistrer dans `main.py`**

Modifier `backend/src/agflow/main.py` :

Ajouter l'import (à insérer dans la liste alphabétique des imports `admin.*`, juste après la ligne `from agflow.api.admin.supervision`) :

```python
from agflow.api.admin.system import router as admin_system_router
```

Ajouter l'enregistrement (à insérer après la ligne `app.include_router(admin_supervision_router)`, ligne 246) :

```python
    app.include_router(admin_system_router)
```

- [ ] **Step 3 : Vérifier que l'app charge**

```bash
cd backend && uv run python -c "from agflow.main import create_app; app = create_app(); print('ok')"
```

Expected : `ok` (et la liste des routes contient `/api/admin/system/export`).

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/api/admin/system.py backend/src/agflow/main.py
git commit -m "feat(api): router admin /api/admin/system avec endpoint export"
```

---

## Task 6 — Tests d'intégration de l'endpoint

**Files:**
- Create: `backend/tests/test_system_export_endpoint.py`

- [ ] **Step 1 : Test rouge**

Créer `backend/tests/test_system_export_endpoint.py` :

```python
from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _operator_token() -> str:
    return jwt.encode(
        {"sub": "op@example.com", "role": "operator"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def test_export_requires_token(client: TestClient) -> None:
    r = client.get("/api/admin/system/export")
    assert r.status_code == 401


def test_export_rejects_non_admin(client: TestClient) -> None:
    r = client.get(
        "/api/admin/system/export",
        headers={"Authorization": f"Bearer {_operator_token()}"},
    )
    assert r.status_code == 403


def test_export_returns_zip_for_admin(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "hello.txt").write_bytes(b"hi")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "world.txt").write_bytes(b"world")
    monkeypatch.setenv("AGFLOW_DATA_DIR", str(tmp_path))

    r = client.get(
        "/api/admin/system/export",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    cd = r.headers["content-disposition"]
    m = re.match(r'attachment; filename="(agflow-data-\d{8}-\d{6}\.zip)"', cd)
    assert m, cd

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert sorted(zf.namelist()) == ["hello.txt", "sub/world.txt"]
        assert zf.read("hello.txt") == b"hi"
        assert zf.read("sub/world.txt") == b"world"


def test_export_returns_empty_zip_when_data_dir_missing(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGFLOW_DATA_DIR", str(tmp_path / "missing"))
    r = client.get(
        "/api/admin/system/export",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == []
```

- [ ] **Step 2 : Run**

```bash
cd backend && uv run pytest tests/test_system_export_endpoint.py -v
```

Expected : 4 tests verts.

- [ ] **Step 3 : Lint**

```bash
cd backend && uv run ruff check tests/test_system_export_endpoint.py
cd backend && uv run ruff format tests/test_system_export_endpoint.py
```

- [ ] **Step 4 : Commit**

```bash
git add backend/tests/test_system_export_endpoint.py
git commit -m "test(system-export): endpoint /api/admin/system/export (auth + zip valide)"
```

---

## Task 7 — Frontend : i18n keys

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés FR**

Modifier `frontend/src/i18n/fr.json` — ajouter le bloc `"topbar"` au niveau racine de l'objet (à mettre par ordre alphabétique près d'`"app"`/`"chat"`) :

```json
  "topbar": {
    "export": "Exporter les données",
    "export_tooltip": "Télécharger une archive ZIP du volume data/",
    "export_error": "Échec de l'export. Réessayez."
  },
```

- [ ] **Step 2 : Ajouter les clés EN**

Modifier `frontend/src/i18n/en.json` — même bloc :

```json
  "topbar": {
    "export": "Export data",
    "export_tooltip": "Download a ZIP archive of the data/ volume",
    "export_error": "Export failed. Try again."
  },
```

- [ ] **Step 3 : Vérifier la validité JSON**

```bash
cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json'))" && node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json'))" && echo ok
```

Expected : `ok`.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "i18n(topbar): clés export pour le bouton de téléchargement data"
```

---

## Task 8 — Frontend : bouton Export dans `TopBar.tsx`

**Files:**
- Modify: `frontend/src/components/layout/TopBar.tsx`

- [ ] **Step 1 : Modifier `TopBar.tsx`**

Remplacer le contenu complet par :

```tsx
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell, BotMessageSquare, ChevronRight, Download, Loader2, Menu, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface Props {
  onOpenSidebar?: () => void;
  onToggleAssistant?: () => void;
  assistantActive?: boolean;
  assistantName?: string;
}

interface Crumb {
  section: string;
  page: string;
}

function resolveCrumbs(path: string, t: (k: string) => string): Crumb | null {
  if (path === "/") return null;
  if (path.startsWith("/secrets"))
    return { section: t("sidebar.section_platform"), page: t("secrets.page_title") };
  if (path.startsWith("/dockerfiles"))
    return {
      section: t("sidebar.section_platform"),
      page: t("dockerfiles.page_title"),
    };
  if (path.startsWith("/roles"))
    return { section: t("sidebar.section_platform"), page: t("roles.page_title") };
  if (path.startsWith("/service-types"))
    return {
      section: t("sidebar.section_platform"),
      page: t("service_types.page_title"),
    };
  if (path.startsWith("/discovery-services"))
    return {
      section: t("sidebar.section_catalogs"),
      page: t("discovery.page_title"),
    };
  if (path.startsWith("/mcp-catalog"))
    return {
      section: t("sidebar.section_catalogs"),
      page: t("mcp_catalog.page_title"),
    };
  if (path.startsWith("/skills-catalog"))
    return {
      section: t("sidebar.section_catalogs"),
      page: t("skills_catalog.page_title"),
    };
  if (path.startsWith("/agents"))
    return {
      section: t("sidebar.section_orchestration"),
      page: t("agents.page_title"),
    };
  if (path.startsWith("/users"))
    return { section: t("sidebar.section_platform"), page: t("users.page_title") };
  if (path.startsWith("/api-keys"))
    return { section: t("sidebar.section_platform"), page: t("api_keys.page_title") };
  if (path.startsWith("/my-secrets"))
    return { section: t("sidebar.section_platform"), page: t("my_secrets.page_title") };
  return null;
}

function extractFilename(contentDisposition: string | undefined, fallback: string): string {
  if (!contentDisposition) return fallback;
  const match = /filename="([^"]+)"/.exec(contentDisposition);
  return match?.[1] ?? fallback;
}

export function TopBar({ onOpenSidebar, onToggleAssistant, assistantActive, assistantName }: Props) {
  const { t } = useTranslation();
  const location = useLocation();
  const { isAdmin } = useAuth();
  const [exporting, setExporting] = useState(false);
  const crumb = resolveCrumbs(location.pathname, t);

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const r = await api.get("/admin/system/export", { responseType: "blob" });
      const filename = extractFilename(
        r.headers["content-disposition"] as string | undefined,
        "agflow-data.zip",
      );
      const url = URL.createObjectURL(r.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t("topbar.export_error"));
    } finally {
      setExporting(false);
    }
  };

  return (
    <header className="h-14 border-b bg-card flex items-center justify-between px-4 md:px-6 shrink-0">
      <div className="flex items-center gap-2 text-[13px] min-w-0">
        {onOpenSidebar && (
          <button
            type="button"
            onClick={onOpenSidebar}
            className="md:hidden w-8 h-8 rounded-md hover:bg-secondary flex items-center justify-center text-muted-foreground shrink-0"
            aria-label="Open menu"
          >
            <Menu className="w-4 h-4" />
          </button>
        )}
        {crumb ? (
          <>
            {/* Section label hidden on small screens to save space */}
            <span className="text-muted-foreground hidden sm:inline">
              {crumb.section}
            </span>
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/50 hidden sm:inline" />
            <span className="text-foreground font-medium truncate">
              {crumb.page}
            </span>
          </>
        ) : (
          <span className="text-foreground font-medium truncate">
            {t("home.welcome")}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {isAdmin && (
          <button
            type="button"
            onClick={handleExport}
            disabled={exporting}
            className={cn(
              "hidden sm:flex w-8 h-8 rounded-md hover:bg-secondary items-center justify-center text-muted-foreground transition-colors",
              exporting && "opacity-50 cursor-wait",
            )}
            aria-label={t("topbar.export")}
            title={t("topbar.export_tooltip")}
          >
            {exporting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
          </button>
        )}
        <button
          type="button"
          className="hidden sm:flex w-8 h-8 rounded-md hover:bg-secondary items-center justify-center text-muted-foreground transition-colors"
          aria-label="Search"
        >
          <Search className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={onToggleAssistant}
          disabled={!onToggleAssistant}
          className={cn(
            "flex w-8 h-8 rounded-md items-center justify-center transition-colors",
            !onToggleAssistant && "opacity-30 cursor-not-allowed",
            onToggleAssistant && assistantActive && "bg-primary text-primary-foreground",
            onToggleAssistant && !assistantActive && "hover:bg-secondary text-muted-foreground",
          )}
          aria-label="Assistant"
          title={
            onToggleAssistant
              ? `Assistant — ${assistantName ?? "?"}`
              : t("assistant.not_configured")
          }
        >
          <BotMessageSquare className="w-4 h-4" />
        </button>
        <button
          type="button"
          className="hidden sm:flex w-8 h-8 rounded-md hover:bg-secondary items-center justify-center text-muted-foreground transition-colors"
          aria-label="Notifications"
        >
          <Bell className="w-4 h-4" />
        </button>
        <div className="hidden sm:block w-px h-5 bg-border mx-1" />
        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary text-[11px] font-semibold shrink-0">
          GB
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 2 : TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected : pas d'erreur.

- [ ] **Step 3 : Lint**

```bash
cd frontend && npm run lint
```

Expected : pas d'erreur (un warning unused-import éventuel sur `Loader2` est inacceptable, doit être 0).

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/layout/TopBar.tsx
git commit -m "feat(topbar): bouton Exporter (admin only) — download zip via blob"
```

---

## Task 9 — Frontend : tests Vitest du bouton Export

**Files:**
- Create: `frontend/tests/components/TopBar.test.tsx`

- [ ] **Step 1 : Test rouge**

Créer `frontend/tests/components/TopBar.test.tsx` :

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { TopBar } from "@/components/layout/TopBar";
import "@/lib/i18n";

// Helper to set/clear the JWT used by useAuth().
function setToken(role: "admin" | "operator" | "viewer" | null): void {
  if (role === null) {
    localStorage.removeItem("agflow_token");
    return;
  }
  // unsigned JWT — useAuth only reads the payload via atob(), no verification
  const payload = btoa(JSON.stringify({ role, sub: "test@example.com" }));
  localStorage.setItem("agflow_token", `header.${payload}.sig`);
}

// Mock the api module — actual axios import is replaced.
vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/lib/api";

describe("TopBar — Export button", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    setToken(null);
  });

  it("renders the export button when user is admin", () => {
    setToken("admin");
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText(/Exporter|Export/i)).toBeInTheDocument();
  });

  it("does NOT render the export button when user is operator", () => {
    setToken("operator");
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/Exporter|Export/i)).toBeNull();
  });

  it("does NOT render the export button when user is viewer", () => {
    setToken("viewer");
    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/Exporter|Export/i)).toBeNull();
  });

  it("triggers a blob download when admin clicks the button", async () => {
    setToken("admin");
    const blob = new Blob(["zip-bytes"], { type: "application/zip" });
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: blob,
      headers: { "content-disposition": 'attachment; filename="agflow-data-20260429-141500.zip"' },
    });

    const clickSpy = vi.fn();
    const origCreate = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreate(tag);
      if (tag === "a") {
        el.click = clickSpy;
      }
      return el;
    });

    render(
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByLabelText(/Exporter|Export/i));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/admin/system/export", { responseType: "blob" });
    });
    expect(clickSpy).toHaveBeenCalled();
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });
});
```

- [ ] **Step 2 : Run, vérifier que ça échoue puis passe**

```bash
cd frontend && npm test -- TopBar.test.tsx
```

Expected : 4 tests verts.

- [ ] **Step 3 : Run la suite complète pour s'assurer qu'on n'a rien cassé**

```bash
cd frontend && npm test
```

Expected : tous les tests verts.

- [ ] **Step 4 : Commit**

```bash
git add frontend/tests/components/TopBar.test.tsx
git commit -m "test(topbar): bouton Export visible admin only + déclenche download blob"
```

---

## Task 10 — Vérifications globales avant déploiement

- [ ] **Step 1 : Suite backend complète**

```bash
cd backend && uv run pytest -v
```

Expected : tous verts. Si certains tests existants étaient déjà rouges à cause du `DATABASE_URL` hardcodé (cf. mémoire `project_tests_hardcoded_db_ip.md`), s'assurer **a minima** que la nouvelle suite `test_system_export_*` passe et que les autres ne sont pas plus rouges qu'avant.

- [ ] **Step 2 : Lint backend complet**

```bash
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format --check src/ tests/
```

Expected : aucune violation.

- [ ] **Step 3 : Suite frontend complète**

```bash
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

Expected : tout vert / 0 warning.

- [ ] **Step 4 : Build frontend**

```bash
cd frontend && npm run build
```

Expected : pas d'erreur, `dist/` créé.

- [ ] **Step 5 : Commit éventuel des fixes lint**

S'il a fallu corriger des choses détectées par lint/tsc, créer un commit `chore: fixes lint/tsc post-export-button`.

---

## Task 11 — Déploiement et test manuel sur LXC 201

**Important :** garder le `deploy.sh` actuel (build local sur LXC) — la migration CI GHCR est l'initiative suivante, pas celle-ci.

- [ ] **Step 1 : Push de la branche**

L'utilisateur décide quand pousser et merge. Si feature branch dédiée :

```bash
git push -u origin <branch>
```

- [ ] **Step 2 : Déployer**

```bash
./scripts/deploy.sh --rebuild
```

Expected : containers `agflow-backend` et `agflow-frontend` redémarrés, `docker compose ps` montre tout `healthy`.

- [ ] **Step 3 : Smoke test backend**

```bash
TOKEN=$(curl -s http://192.168.10.158/api/admin/auth/login -X POST -H 'Content-Type: application/json' -d '{"email":"<admin_email>","password":"<admin_password>"}' | jq -r .access_token)

curl -i http://192.168.10.158/api/admin/system/export -H "Authorization: Bearer $TOKEN" -o /tmp/agflow-test.zip --max-time 120 -D /tmp/headers.txt

cat /tmp/headers.txt | grep -i 'content-disposition'   # → attachment; filename="agflow-data-...zip"
unzip -l /tmp/agflow-test.zip | head -30                # → liste des fichiers de data/
```

Expected : zip de plusieurs MB contenant `avatars/`, `templates/`, `agents/`, etc.

- [ ] **Step 4 : Test UI bout en bout**

1. Ouvrir https://docker-agflow.yoops.org/
2. Login admin
3. Vérifier le bouton "Export" (icône `Download`) à droite dans la topbar
4. Click → spinner → fichier `agflow-data-YYYYMMDD-HHMMSS.zip` téléchargé
5. Ouvrir le zip côté Windows : doit contenir l'arbo `data/` (avatars, templates, agents, roles, etc.)
6. Logout, relogin en operator (si compte dispo) → bouton absent

- [ ] **Step 5 : Logs & audit**

```bash
ssh pve "pct exec 201 -- bash -c 'docker logs agflow-backend 2>&1 | grep system.export | tail -3'"
```

Expected : entrée structlog `system.export` avec `user_id`, `size_bytes`, `duration_s`.

---

## Critères d'acceptation finaux

- [ ] `GET /api/admin/system/export` renvoie 401/403/200 selon le rôle
- [ ] Le zip téléchargé est valide et contient le contenu de `data/`
- [ ] Le filename contient un timestamp UTC `YYYYMMDD-HHMMSS`
- [ ] Bouton Export visible pour admin, masqué pour operator/viewer
- [ ] Spinner pendant le download, toast d'erreur en cas d'échec
- [ ] Suite backend + frontend verte
- [ ] Lint + tsc + format propres
- [ ] Smoke test prod OK, archive ouverte sur Windows avec contenu cohérent
- [ ] Une ligne `system.export` dans les logs structlog par export effectué
