# Public API v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Dockerfiles, files, and parameters via authenticated public API endpoints (`/api/v1/*`) using the self-validating API key system (HMAC + bcrypt + Redis rate limit) already built.

**Architecture:** New `api/public/` router package parallel to `api/admin/`. Reuses existing services (dockerfiles_service, dockerfile_files_service, build_service). Auth via `require_api_key(*scopes)` from `auth/api_key.py`. Structured error responses `{"error": {"code": "...", "message": "..."}}`. Pagination on list endpoints.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, existing `require_api_key` middleware, existing services

**Spec:** Section 4 of `docs/superpowers/specs/2026-04-12-users-apikeys-design.md`

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `backend/src/agflow/api/public/__init__.py` | Package init |
| `backend/src/agflow/api/public/dockerfiles.py` | `/api/v1/dockerfiles` CRUD + build + export + import |
| `backend/src/agflow/api/public/files.py` | `/api/v1/dockerfiles/{id}/files` CRUD |
| `backend/src/agflow/api/public/params.py` | `/api/v1/dockerfiles/{id}/params` read + update + patch |
| `backend/src/agflow/api/public/errors.py` | Structured error helper + exception handlers |

### Modified files

| File | Change |
|---|---|
| `backend/src/agflow/main.py` | Register public routers |

---

## Task 1: Public API error helpers + package

**Files:**
- Create: `backend/src/agflow/api/public/__init__.py`
- Create: `backend/src/agflow/api/public/errors.py`

- [ ] **Step 1: Create package init**

Empty file `backend/src/agflow/api/public/__init__.py`.

- [ ] **Step 2: Create error helpers**

```python
# backend/src/agflow/api/public/errors.py
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message}},
    )


async def not_found_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "not_found", "message": str(detail)}},
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/api/public/
git commit -m "feat: public API package + structured error helpers"
```

---

## Task 2: Dockerfiles public endpoints

**Files:**
- Create: `backend/src/agflow/api/public/dockerfiles.py`

- [ ] **Step 1: Create dockerfiles router**

Router prefix `/api/v1/dockerfiles`, no global dependency (each route declares its own `require_api_key` scope).

Reuses: `dockerfiles_service`, `build_service`, `dockerfile_files_service` from `agflow.services`.

Routes:

| Method | Path | Scope | Reuses |
|---|---|---|---|
| `GET /` | list | `dockerfiles:read` | `dockerfiles_service.list_all()` |
| `GET /{id}` | detail | `dockerfiles:read` | `dockerfiles_service.get_by_id()` + `dockerfile_files_service.list_for_dockerfile()` |
| `POST /` | create | `dockerfiles:write` | `dockerfiles_service.create()` |
| `PUT /{id}` | update | `dockerfiles:write` | `dockerfiles_service.update()` |
| `DELETE /{id}` | delete | `dockerfiles:delete` | `dockerfiles_service.delete()` |
| `POST /{id}/build` | build | `dockerfiles:build` | Same as admin build endpoint |
| `GET /{id}/builds` | build history | `dockerfiles:read` | `build_service.list_builds()` |
| `GET /{id}/export` | download zip | `dockerfiles:read` | Same as admin export |
| `POST /{id}/import` | upload zip | `dockerfiles:write` | Same as admin import |

Each route catches service exceptions → `api_error(404, "not_found", ...)` or `api_error(409, "conflict", ...)`.

Pagination on `GET /`: accept `?limit=50&offset=0` query params, pass to a modified `list_all()` or slice in the endpoint.

Response schemas: reuse existing `DockerfileSummary`, `DockerfileDetail`, `BuildSummary` from `agflow.schemas.dockerfiles`.

- [ ] **Step 2: Verify imports**

```bash
cd backend && uv run python -c "from agflow.api.public.dockerfiles import router; print('OK', len(router.routes), 'routes')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/api/public/dockerfiles.py
git commit -m "feat: public API /api/v1/dockerfiles CRUD + build + export + import"
```

---

## Task 3: Files public endpoints

**Files:**
- Create: `backend/src/agflow/api/public/files.py`

- [ ] **Step 1: Create files router**

Router prefix `/api/v1/dockerfiles/{dockerfile_id}/files`.

Routes:

| Method | Path | Scope |
|---|---|---|
| `GET /` | list files | `dockerfiles.files:read` |
| `GET /{file_id}` | get file content | `dockerfiles.files:read` |
| `POST /` | create file | `dockerfiles.files:write` |
| `PUT /{file_id}` | update content | `dockerfiles.files:write` |
| `DELETE /{file_id}` | delete file | `dockerfiles.files:delete` |

Reuses `dockerfile_files_service`. Catches `FileNotFoundError`, `DuplicateFileError`, `ProtectedFileError`.

- [ ] **Step 2: Verify + commit**

```bash
cd backend && uv run python -c "from agflow.api.public.files import router; print('OK')"
git add backend/src/agflow/api/public/files.py
git commit -m "feat: public API /api/v1/dockerfiles/{id}/files CRUD"
```

---

## Task 4: Params public endpoints

**Files:**
- Create: `backend/src/agflow/api/public/params.py`

- [ ] **Step 1: Create params router**

Router prefix `/api/v1/dockerfiles/{dockerfile_id}/params`.

Routes:

| Method | Path | Scope | Description |
|---|---|---|---|
| `GET /` | read | `dockerfiles.params:read` | Returns Dockerfile.json content parsed as JSON |
| `PUT /` | replace | `dockerfiles.params:write` | Replaces entire Dockerfile.json (validates structure: must have `docker` + `Params` keys) |
| `PATCH /{section}` | patch section | `dockerfiles.params:write` | Updates one section (e.g., `Runtime`, `Environments`, `Params`) without touching the rest |

The `GET` finds the `Dockerfile.json` file via `dockerfile_files_service.list_for_dockerfile()`, parses JSON, returns the parsed object.

The `PUT` validates the JSON structure (same validation as the import endpoint: `docker` and `Params` keys must be objects), then serializes and writes via `dockerfile_files_service.update()`.

The `PATCH /{section}` reads current JSON, deep-merges the request body into the specified section, validates, writes back. Section must be one of: `Container`, `Network`, `Runtime`, `Resources`, `Environments`, `Mounts`, `Params` (case-sensitive, matches JSON keys).

- [ ] **Step 2: Verify + commit**

```bash
cd backend && uv run python -c "from agflow.api.public.params import router; print('OK')"
git add backend/src/agflow/api/public/params.py
git commit -m "feat: public API /api/v1/dockerfiles/{id}/params read + update + patch"
```

---

## Task 5: Register public routers in main.py

**Files:**
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Register all 3 public routers**

Add imports + `app.include_router(...)` for:
- `agflow.api.public.dockerfiles.router`
- `agflow.api.public.files.router`
- `agflow.api.public.params.router`

- [ ] **Step 2: Verify route count**

```bash
cd backend && uv run python -c "from agflow.main import create_app; app = create_app(); v1_routes = [r for r in app.routes if hasattr(r, 'path') and '/api/v1/' in r.path]; print(f'OK {len(v1_routes)} v1 routes, {len(app.routes)} total')"
```

Expected: ~18 v1 routes (9 dockerfiles + 5 files + 3 params + 1 builds)

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/main.py
git commit -m "feat: register public API v1 routers in main.py"
```

---

## Task 6: Deploy + smoke test with API key

- [ ] **Step 1: Deploy**

```bash
./scripts/deploy.sh --rebuild
```

- [ ] **Step 2: Create an API key via admin UI**

Go to `http://192.168.10.68/api-keys` → create a key with scopes `dockerfiles:read`, `dockerfiles:write`, `dockerfiles.files:read`, `dockerfiles.params:read`, `dockerfiles.params:write`. Copy the token.

- [ ] **Step 3: Test with curl**

```bash
# List dockerfiles
curl -H "Authorization: Bearer agfd_XXXX..." http://192.168.10.68/api/v1/dockerfiles

# Get detail
curl -H "Authorization: Bearer agfd_XXXX..." http://192.168.10.68/api/v1/dockerfiles/codex

# List files
curl -H "Authorization: Bearer agfd_XXXX..." http://192.168.10.68/api/v1/dockerfiles/codex/files

# Read params
curl -H "Authorization: Bearer agfd_XXXX..." http://192.168.10.68/api/v1/dockerfiles/codex/params

# Test rate limit (hit it 121 times rapidly)
for i in $(seq 1 125); do curl -s -o /dev/null -w "%{http_code} " -H "Authorization: Bearer agfd_XXXX..." http://192.168.10.68/api/v1/dockerfiles; done
# Should see 200s then 429s

# Test missing scope
# Create a key with only dockerfiles:read, then try to POST
curl -X POST -H "Authorization: Bearer agfd_READ_ONLY..." -H "Content-Type: application/json" \
  -d '{"id":"test","display_name":"Test"}' \
  http://192.168.10.68/api/v1/dockerfiles
# Expected: 403 {"error":{"code":"missing_scope","message":"..."}}

# Test invalid key
curl -H "Authorization: Bearer agfd_invalid" http://192.168.10.68/api/v1/dockerfiles
# Expected: 401
```

- [ ] **Step 4: Commit any remaining changes**

```bash
git add -A && git commit -m "chore: deploy public API v1"
```
