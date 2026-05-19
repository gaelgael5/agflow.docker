# OIDC Config UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Référence détaillée** : `docs/superpowers/specs/2026-05-19-oidc-config-ui-design.md` (spec validée, commits `46f9dda` + `c189474`) — tous les schémas SQL, signatures Python, payloads JSON y sont fournis verbatim.

**Goal:** Ajouter une UI de paramétrage Keycloak/OIDC dans `/settings` qui persiste la config en DB (singleton + secret dans Harpocrate vault) au lieu des env vars, avec un bouton « Tester la connexion ».

**Architecture:** Table singleton `auth_config` (PK fixe id=1, comme `pitr_config`). Service `auth_config_service.py` expose get/update/test_connection. Le `client_secret` est poussé dans Harpocrate via `vault_client.update_secret`/`create_secret`, seule la ref `${vault://<name>:auth/keycloak/client_secret}` est stockée en DB. 3 endpoints REST sous `/api/admin/auth-config`. Le router OIDC existant (`api/admin/auth.py`) est refactoré pour lire la DB au lieu de `get_settings()`. Frontend : onglet « Authentification » dans `SettingsPage` (à côté de Harpocrate et Git Sync).

**Tech Stack:** Python 3.12 + asyncpg + httpx + Pydantic v2 + FastAPI + structlog + pytest / Postgres 16 / Harpocrate vault (SDK existant) / Vite + React 18 + TanStack Query + shadcn/ui + i18next + Vitest

---

## File Structure

### Backend — créés

| Fichier | Responsabilité |
|---|---|
| `backend/migrations/113_auth_config.sql` | Table singleton `auth_config` + trigger updated_at + seed |
| `backend/src/agflow/schemas/auth_config.py` | Pydantic : AuthConfigOut, AuthConfigUpdate, AuthTestRequest, AuthTestResult |
| `backend/src/agflow/services/auth_config_service.py` | get_config/get_config_internal/update_config/test_connection + exceptions |
| `backend/src/agflow/api/admin/auth_config.py` | 3 endpoints REST |
| `backend/tests/db/test_migration_113_auth_config.py` | Singleton, CHECK, trigger |
| `backend/tests/services/test_auth_config_service.py` | CRUD + validation + push vault + has_secret |
| `backend/tests/services/test_auth_config_test_connection.py` | discovery + token, happy + failures |
| `backend/tests/api/test_admin_auth_config.py` | 3 endpoints × auth + happy + erreurs |
| `backend/tests/api/test_admin_auth_oidc_uses_db.py` | /mode + /oidc/login + /oidc/callback lisent la DB |

### Backend — modifiés

| Fichier | Modification |
|---|---|
| `backend/src/agflow/main.py` | Enregistrer le nouveau router `admin_auth_config_router` |
| `backend/src/agflow/api/admin/auth.py` | Les 3 endpoints OIDC existants lisent `auth_config_service.get_config_internal()` au lieu de `get_settings()` |
| `backend/src/agflow/config.py` | Retirer `auth_mode`, `keycloak_url`, `keycloak_realm`, `keycloak_client_id`, `keycloak_client_secret`, property `keycloak_base` |
| `.env.example` | Retirer les 5 lignes Keycloak |

### Frontend — créés

| Fichier | Responsabilité |
|---|---|
| `frontend/src/lib/authConfigApi.ts` | 3 fonctions REST + types |
| `frontend/src/hooks/useAuthConfig.ts` | React Query : useAuthConfig (query + 2 mutations) |
| `frontend/src/components/settings/AuthTab.tsx` | Onglet complet (form + bouton test + zone résultat) |
| `frontend/src/components/settings/__tests__/AuthTab.test.tsx` | Tests Vitest |
| `frontend/src/hooks/__tests__/useAuthConfig.test.ts` | Tests Vitest hook |

### Frontend — modifiés

| Fichier | Modification |
|---|---|
| `frontend/src/pages/SettingsPage.tsx` | Ajouter `<TabsTrigger value="auth">` + `<TabsContent value="auth"><AuthTab /></TabsContent>` |
| `frontend/src/i18n/fr.json` | + ~25 clés `settings.auth.*` + `settings.tabs.auth` |
| `frontend/src/i18n/en.json` | mêmes clés EN |

---

## LOT 1 — DB + schemas + service (P1)

### Task 1 : Migration 113 + test

**Files:**
- Create: `backend/migrations/113_auth_config.sql`
- Create: `backend/tests/db/test_migration_113_auth_config.py`

- [ ] **Step 1 : Écrire le test (TDD red)**

```python
# backend/tests/db/test_migration_113_auth_config.py
"""Migration 113 — table auth_config singleton."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import CheckViolationError, Connection, UniqueViolationError

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    """Reset DB then yield an asyncpg connection."""
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_auth_config_table_exists(fresh_db):
    table = await fresh_db.fetchval("SELECT to_regclass('public.auth_config')")
    assert table is not None


async def test_auth_config_singleton_seeded(fresh_db):
    row = await fresh_db.fetchrow("SELECT * FROM auth_config WHERE id = 1")
    assert row is not None
    assert row["mode"] == "local"
    assert row["keycloak_url"] == ""
    assert row["keycloak_realm"] == ""
    assert row["keycloak_client_id"] == ""
    assert row["keycloak_client_secret_ref"] == ""
    assert row["vault_name"] == "default"


async def test_auth_config_check_id_rejects_second_row(fresh_db):
    """CHECK (id = 1) interdit toute autre ligne."""
    with pytest.raises(CheckViolationError):
        await fresh_db.execute("INSERT INTO auth_config (id, mode) VALUES (2, 'local')")


async def test_auth_config_check_mode_rejects_invalid(fresh_db):
    """CHECK mode rejette une valeur hors enum."""
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "UPDATE auth_config SET mode = 'invalid' WHERE id = 1"
        )


async def test_auth_config_updated_at_trigger(fresh_db):
    before = await fresh_db.fetchval("SELECT updated_at FROM auth_config WHERE id = 1")
    await fresh_db.execute("UPDATE auth_config SET keycloak_url = 'https://x' WHERE id = 1")
    after = await fresh_db.fetchval("SELECT updated_at FROM auth_config WHERE id = 1")
    assert after > before
```

- [ ] **Step 2 : Run, échoue (migration absente)**

```bash
cd backend && uv run pytest tests/db/test_migration_113_auth_config.py -v
```

Expected : 5 FAIL (table n'existe pas). Si la DB n'est pas joignable depuis Windows → connection error, accepte DONE_WITH_CONCERNS (tests à valider au moment du run-test.sh LXC).

- [ ] **Step 3 : Écrire la migration**

```sql
-- backend/migrations/113_auth_config.sql
-- Configuration d'authentification (singleton)

CREATE TABLE auth_config (
    id                          int PRIMARY KEY CHECK (id = 1),
    mode                        text NOT NULL DEFAULT 'local'
                                CHECK (mode IN ('local', 'keycloak')),
    keycloak_url                text NOT NULL DEFAULT '',
    keycloak_realm              text NOT NULL DEFAULT '',
    keycloak_client_id          text NOT NULL DEFAULT '',
    keycloak_client_secret_ref  text NOT NULL DEFAULT '',
    vault_name                  text NOT NULL DEFAULT 'default',
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    updated_by_user_id          uuid REFERENCES users(id) ON DELETE SET NULL
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_auth_config_updated_at') THEN
        CREATE TRIGGER trg_auth_config_updated_at
            BEFORE UPDATE ON auth_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

INSERT INTO auth_config (id, mode) VALUES (1, 'local') ON CONFLICT (id) DO NOTHING;
```

- [ ] **Step 4 : Run tests, doivent passer**

```bash
cd backend && uv run pytest tests/db/test_migration_113_auth_config.py -v
```

Expected : 5 PASS si DB OK. Si DB injoignable → DONE_WITH_CONCERNS (validation E2E plus tard).

- [ ] **Step 5 : Commit**

```bash
git add backend/migrations/113_auth_config.sql backend/tests/db/test_migration_113_auth_config.py
git commit -m "feat(auth-db): migration 113 — table auth_config singleton"
```

### Task 2 : Schemas Pydantic

**Files:**
- Create: `backend/src/agflow/schemas/auth_config.py`

- [ ] **Step 1 : Écrire le module**

```python
# backend/src/agflow/schemas/auth_config.py
"""DTOs pour le paramétrage OIDC/Keycloak."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthConfigOut(BaseModel):
    """Configuration retournée par GET. Le secret n'est jamais exposé : seul
    `has_secret` (bool) indique sa présence."""
    mode: Literal["local", "keycloak"]
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    has_secret: bool
    vault_name: str
    updated_at: datetime
    updated_by_user_id: UUID | None


class AuthConfigUpdate(BaseModel):
    """Payload PUT. Tous champs optionnels — seuls les champs présents sont
    mis à jour. `keycloak_client_secret` vide/None = ne pas modifier."""
    mode: Literal["local", "keycloak"] | None = None
    keycloak_url: str | None = None
    keycloak_realm: str | None = None
    keycloak_client_id: str | None = None
    keycloak_client_secret: str | None = None
    vault_name: str | None = None


class AuthTestRequest(BaseModel):
    """Payload pour POST /test. Si keycloak_client_secret est vide, le backend
    lit le secret actuel via le ref stocké en DB."""
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_client_secret: str | None = None
    vault_name: str | None = None


class AuthTestResult(BaseModel):
    """Résultat du test. Toujours retourné en HTTP 200 ; le succès/échec est
    indiqué par `ok`. `step` dit jusqu'où on est allé."""
    ok: bool
    step: Literal["discovery", "token", "done"]
    detail: str
    discovery_ok: bool
    token_ok: bool
```

- [ ] **Step 2 : Vérifier import**

```bash
cd backend && uv run python -c "from agflow.schemas.auth_config import AuthConfigOut, AuthConfigUpdate, AuthTestRequest, AuthTestResult; print('ok')"
```

Expected : `ok`.

- [ ] **Step 3 : Lint**

```bash
cd backend && uv run ruff check src/agflow/schemas/auth_config.py
```

Expected : clean.

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/schemas/auth_config.py
git commit -m "feat(auth-services): schemas Pydantic auth_config (Out, Update, TestRequest, TestResult)"
```

### Task 3 : `auth_config_service` — get/update + tests

**Files:**
- Create: `backend/src/agflow/services/auth_config_service.py`
- Create: `backend/tests/services/test_auth_config_service.py`

- [ ] **Step 1 : Écrire les tests (TDD red)**

```python
# backend/tests/services/test_auth_config_service.py
"""Tests pour auth_config_service — get + update."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import auth_config_service
from agflow.services.auth_config_service import (
    InvalidUrlError,
    VaultNameUnknownError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _fresh_db():
    await reset_schema_and_migrate()


async def test_get_config_returns_seeded_defaults():
    cfg = await auth_config_service.get_config()
    assert cfg.mode == "local"
    assert cfg.keycloak_url == ""
    assert cfg.keycloak_realm == ""
    assert cfg.keycloak_client_id == ""
    assert cfg.has_secret is False
    assert cfg.vault_name == "default"


async def test_get_config_has_secret_true_when_ref_set():
    """Si la colonne keycloak_client_secret_ref n'est pas vide, has_secret=True."""
    await execute(
        "UPDATE auth_config SET keycloak_client_secret_ref = $1 WHERE id = 1",
        "${vault://default:auth/keycloak/client_secret}",
    )
    cfg = await auth_config_service.get_config()
    assert cfg.has_secret is True


async def test_update_config_changes_mode():
    payload = auth_config_service.AuthConfigUpdate(mode="keycloak")
    cfg = await auth_config_service.update_config(payload, actor_user_id=None)
    assert cfg.mode == "keycloak"


async def test_update_config_invalid_url_raises():
    payload = auth_config_service.AuthConfigUpdate(keycloak_url="not-a-url")
    with pytest.raises(InvalidUrlError):
        await auth_config_service.update_config(payload, actor_user_id=None)


async def test_update_config_unknown_vault_raises():
    payload = auth_config_service.AuthConfigUpdate(vault_name="nonexistent-vault-xyz")
    # Mock harpocrate_vaults_service.get_by_name to return None
    with patch(
        "agflow.services.auth_config_service.harpocrate_vaults_service.get_by_name",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(VaultNameUnknownError):
            await auth_config_service.update_config(payload, actor_user_id=None)


async def test_update_config_pushes_secret_to_vault_when_provided():
    """Quand le payload contient keycloak_client_secret, le service appelle
    update_secret (ou create_secret en fallback) puis stocke la ref dans la colonne."""
    # Setup : un coffre "default" existe
    fake_vault = type("V", (), {"name": "default"})()
    with patch(
        "agflow.services.auth_config_service.harpocrate_vaults_service.get_by_name",
        new=AsyncMock(return_value=fake_vault),
    ), patch(
        "agflow.services.auth_config_service.vault_client.update_secret",
        new=AsyncMock(),
    ) as mock_update:
        payload = auth_config_service.AuthConfigUpdate(
            keycloak_client_secret="super-secret",
            vault_name="default",
        )
        cfg = await auth_config_service.update_config(payload, actor_user_id=None)

    # Le secret a été poussé
    mock_update.assert_called_once_with(
        "auth/keycloak/client_secret", "super-secret", vault_name="default"
    )
    # La ref est stockée
    row = await fetch_one("SELECT keycloak_client_secret_ref FROM auth_config WHERE id = 1")
    assert row["keycloak_client_secret_ref"] == "${vault://default:auth/keycloak/client_secret}"
    assert cfg.has_secret is True


async def test_update_config_creates_secret_if_not_exists():
    """Si update_secret renvoie 404 (secret n'existe pas encore), fallback sur create_secret."""
    from harpocrate.exceptions import VaultHttpError

    fake_vault = type("V", (), {"name": "default"})()
    err_404 = VaultHttpError("not found", status_code=404)
    with patch(
        "agflow.services.auth_config_service.harpocrate_vaults_service.get_by_name",
        new=AsyncMock(return_value=fake_vault),
    ), patch(
        "agflow.services.auth_config_service.vault_client.update_secret",
        new=AsyncMock(side_effect=err_404),
    ), patch(
        "agflow.services.auth_config_service.vault_client.create_secret",
        new=AsyncMock(),
    ) as mock_create:
        payload = auth_config_service.AuthConfigUpdate(
            keycloak_client_secret="new-secret",
            vault_name="default",
        )
        await auth_config_service.update_config(payload, actor_user_id=None)

    mock_create.assert_called_once_with(
        "auth/keycloak/client_secret",
        "new-secret",
        description="Keycloak OIDC client_secret",
        vault_name="default",
    )


async def test_update_config_stores_actor_user_id():
    actor = uuid4()
    # Seed a user row so the FK is valid
    await execute(
        "INSERT INTO users (id, email, name, role, status) VALUES ($1, 'a@b.c', 'A', 'admin', 'active')",
        actor,
    )
    payload = auth_config_service.AuthConfigUpdate(mode="keycloak")
    await auth_config_service.update_config(payload, actor_user_id=actor)
    row = await fetch_one("SELECT updated_by_user_id FROM auth_config WHERE id = 1")
    assert row["updated_by_user_id"] == actor
```

- [ ] **Step 2 : Run, échouent**

```bash
cd backend && uv run pytest tests/services/test_auth_config_service.py -v
```

Expected : FAIL (service inexistant). DB unreachable → DONE_WITH_CONCERNS.

- [ ] **Step 3 : Écrire le service**

```python
# backend/src/agflow/services/auth_config_service.py
"""Singleton config pour l'authentification (mode local/keycloak + credentials)."""
from __future__ import annotations

from uuid import UUID

import structlog
from harpocrate.exceptions import VaultHttpError

from agflow.db.pool import execute, fetch_one
from agflow.schemas.auth_config import (
    AuthConfigOut,
    AuthConfigUpdate,
    AuthTestRequest,
    AuthTestResult,
)
from agflow.services import harpocrate_vaults_service, vault_client

log = structlog.get_logger(__name__)

CLIENT_SECRET_PATH = "auth/keycloak/client_secret"


class InvalidUrlError(ValueError):
    """URL Keycloak invalide (ne commence pas par http:// ou https://)."""


class VaultNameUnknownError(LookupError):
    """vault_name fourni n'existe pas dans la table harpocrate_vaults.
    À ne pas confondre avec vault_client.VaultNotFoundError (coffre SDK absent)."""


async def get_config() -> AuthConfigOut:
    """Lit la config en masquant le secret (juste has_secret: bool)."""
    row = await fetch_one(
        "SELECT mode, keycloak_url, keycloak_realm, keycloak_client_id, "
        "keycloak_client_secret_ref, vault_name, updated_at, updated_by_user_id "
        "FROM auth_config WHERE id = 1"
    )
    if row is None:
        raise RuntimeError("auth_config singleton missing — migration 113 not applied")
    return AuthConfigOut(
        mode=row["mode"],
        keycloak_url=row["keycloak_url"],
        keycloak_realm=row["keycloak_realm"],
        keycloak_client_id=row["keycloak_client_id"],
        has_secret=bool(row["keycloak_client_secret_ref"]),
        vault_name=row["vault_name"],
        updated_at=row["updated_at"],
        updated_by_user_id=row["updated_by_user_id"],
    )


async def get_config_internal() -> dict:
    """Lit la config avec la ref complète (usage interne — auth.py, test_connection).
    Retourne un dict pour ne pas leak la ref dans un type partagé avec l'API."""
    row = await fetch_one(
        "SELECT mode, keycloak_url, keycloak_realm, keycloak_client_id, "
        "keycloak_client_secret_ref, vault_name, updated_at, updated_by_user_id "
        "FROM auth_config WHERE id = 1"
    )
    if row is None:
        raise RuntimeError("auth_config singleton missing — migration 113 not applied")
    return dict(row)


async def update_config(
    payload: AuthConfigUpdate, *, actor_user_id: UUID | None
) -> AuthConfigOut:
    """Met à jour la config. Si keycloak_client_secret est fourni, le pousse
    dans Harpocrate avant de stocker la ref."""
    # Validation URL
    if payload.keycloak_url is not None and payload.keycloak_url:
        if not (
            payload.keycloak_url.startswith("http://")
            or payload.keycloak_url.startswith("https://")
        ):
            raise InvalidUrlError(
                f"keycloak_url must start with http(s)://: {payload.keycloak_url!r}"
            )

    # Validation vault_name (si fourni)
    if payload.vault_name is not None:
        vault = await harpocrate_vaults_service.get_by_name(payload.vault_name)
        if vault is None:
            raise VaultNameUnknownError(payload.vault_name)

    # Push secret dans Harpocrate (si fourni en clair)
    new_ref: str | None = None
    if payload.keycloak_client_secret:
        # Détermine le coffre cible : celui du payload sinon celui de la DB
        target_vault = payload.vault_name
        if target_vault is None:
            current = await get_config_internal()
            target_vault = current["vault_name"]

        try:
            await vault_client.update_secret(
                CLIENT_SECRET_PATH,
                payload.keycloak_client_secret,
                vault_name=target_vault,
            )
        except VaultHttpError as exc:
            if exc.status_code == 404:
                # Le secret n'existe pas encore → create
                await vault_client.create_secret(
                    CLIENT_SECRET_PATH,
                    payload.keycloak_client_secret,
                    description="Keycloak OIDC client_secret",
                    vault_name=target_vault,
                )
            else:
                raise
        new_ref = vault_client.build_ref(target_vault, CLIENT_SECRET_PATH)

    # UPDATE conditionnel
    sets: list[str] = []
    params: list[object] = []
    if payload.mode is not None:
        params.append(payload.mode)
        sets.append(f"mode = ${len(params)}")
    if payload.keycloak_url is not None:
        params.append(payload.keycloak_url)
        sets.append(f"keycloak_url = ${len(params)}")
    if payload.keycloak_realm is not None:
        params.append(payload.keycloak_realm)
        sets.append(f"keycloak_realm = ${len(params)}")
    if payload.keycloak_client_id is not None:
        params.append(payload.keycloak_client_id)
        sets.append(f"keycloak_client_id = ${len(params)}")
    if new_ref is not None:
        params.append(new_ref)
        sets.append(f"keycloak_client_secret_ref = ${len(params)}")
    if payload.vault_name is not None:
        params.append(payload.vault_name)
        sets.append(f"vault_name = ${len(params)}")
    params.append(actor_user_id)
    sets.append(f"updated_by_user_id = ${len(params)}")

    if sets:
        await execute(
            f"UPDATE auth_config SET {', '.join(sets)} WHERE id = 1", *params
        )

    log.info(
        "auth_config.updated",
        mode=payload.mode,
        keycloak_url=payload.keycloak_url,
        actor_user_id=str(actor_user_id) if actor_user_id else None,
    )
    return await get_config()
```

- [ ] **Step 4 : Run tests, doivent passer**

```bash
cd backend && uv run pytest tests/services/test_auth_config_service.py -v
```

Expected : 8 PASS (DB ok) ou DONE_WITH_CONCERNS si DB unreachable.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/auth_config_service.py tests/services/test_auth_config_service.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/auth_config_service.py backend/tests/services/test_auth_config_service.py
git commit -m "feat(auth-services): auth_config_service.get + update (push vault, validation URL/vault_name)"
```

### Task 4 : `auth_config_service.test_connection` + tests

**Files:**
- Modify: `backend/src/agflow/services/auth_config_service.py`
- Create: `backend/tests/services/test_auth_config_test_connection.py`

- [ ] **Step 1 : Écrire les tests (TDD red)**

```python
# backend/tests/services/test_auth_config_test_connection.py
"""Tests pour auth_config_service.test_connection (httpx mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agflow.services import auth_config_service
from agflow.schemas.auth_config import AuthTestRequest

pytestmark = pytest.mark.asyncio


def _ok_response(status_code: int = 200, json_payload: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = "" if json_payload is None else str(json_payload)
    r.json = MagicMock(return_value=json_payload or {})
    return r


def _make_async_client(get_resp: MagicMock, post_resp: MagicMock) -> MagicMock:
    """Helper to build a fake httpx.AsyncClient context manager."""
    fake = MagicMock()
    fake.get = AsyncMock(return_value=get_resp)
    fake.post = AsyncMock(return_value=post_resp)
    # Async context manager
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    return fake


async def test_test_connection_happy_path():
    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
        keycloak_client_secret="secret",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(200, {"issuer": "https://kc.example.com/realms/yoops"}),
        post_resp=_ok_response(200, {"access_token": "tok", "token_type": "Bearer"}),
    )
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is True
    assert result.step == "done"
    assert result.discovery_ok is True
    assert result.token_ok is True


async def test_test_connection_discovery_404():
    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="missing-realm",
        keycloak_client_id="agflow",
        keycloak_client_secret="secret",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(404),
        post_resp=_ok_response(200),
    )
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is False
    assert result.step == "discovery"
    assert result.discovery_ok is False
    assert result.token_ok is False
    assert "404" in result.detail


async def test_test_connection_discovery_network_error():
    payload = AuthTestRequest(
        keycloak_url="https://unreachable.invalid",
        keycloak_realm="y",
        keycloak_client_id="agflow",
        keycloak_client_secret="secret",
    )
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is False
    assert result.step == "discovery"
    assert "unreachable" in result.detail.lower() or "conn refused" in result.detail


async def test_test_connection_token_401():
    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
        keycloak_client_secret="wrong",
    )
    error_body = {"error": "invalid_client"}
    fake_client = _make_async_client(
        get_resp=_ok_response(200, {"issuer": "x"}),
        post_resp=_ok_response(401, error_body),
    )
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is False
    assert result.step == "token"
    assert result.discovery_ok is True
    assert result.token_ok is False
    assert "401" in result.detail


async def test_test_connection_no_secret_no_ref():
    """Si pas de secret dans le payload et pas de ref en DB → échec discovery
    avec un message clair."""
    from tests._db_reset import reset_schema_and_migrate
    await reset_schema_and_migrate()

    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
        # keycloak_client_secret omis
    )
    result = await auth_config_service.test_connection(payload)
    assert result.ok is False
    assert "secret" in result.detail.lower()


async def test_test_connection_secret_from_vault():
    """Si payload.keycloak_client_secret est vide mais qu'une ref est en DB,
    résout via vault_client.resolve_ref."""
    from tests._db_reset import reset_schema_and_migrate
    from agflow.db.pool import execute as _execute

    await reset_schema_and_migrate()
    await _execute(
        "UPDATE auth_config SET keycloak_client_secret_ref = $1 WHERE id = 1",
        "${vault://default:auth/keycloak/client_secret}",
    )

    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(200, {"issuer": "x"}),
        post_resp=_ok_response(200, {"access_token": "tok"}),
    )
    with patch("httpx.AsyncClient", return_value=fake_client), patch(
        "agflow.services.auth_config_service.vault_client.resolve_ref",
        new=AsyncMock(return_value="actual-secret"),
    ) as mock_resolve:
        result = await auth_config_service.test_connection(payload)

    mock_resolve.assert_called_once_with("${vault://default:auth/keycloak/client_secret}")
    assert result.ok is True
```

- [ ] **Step 2 : Run, échouent**

```bash
cd backend && uv run pytest tests/services/test_auth_config_test_connection.py -v
```

Expected : 6 FAIL (`test_connection` n'existe pas).

- [ ] **Step 3 : Ajouter `test_connection` au service**

Append à `backend/src/agflow/services/auth_config_service.py` :

```python
import httpx


async def test_connection(payload: AuthTestRequest) -> AuthTestResult:
    """Teste la connexion Keycloak en 2 étapes : discovery + client_credentials grant.

    Si payload.keycloak_client_secret est vide, lit le secret actuel via le
    ref stocké en DB (permet de tester une modif partielle).
    """
    # Résolution du secret
    secret = payload.keycloak_client_secret
    if not secret:
        cfg_internal = await get_config_internal()
        ref = cfg_internal["keycloak_client_secret_ref"]
        if ref:
            try:
                secret = await vault_client.resolve_ref(ref)
            except Exception as exc:
                return AuthTestResult(
                    ok=False,
                    step="discovery",
                    discovery_ok=False,
                    token_ok=False,
                    detail=f"impossible de récupérer le secret depuis le vault : {exc}",
                )
        else:
            return AuthTestResult(
                ok=False,
                step="discovery",
                discovery_ok=False,
                token_ok=False,
                detail="client_secret non fourni et aucun secret enregistré en DB",
            )

    base = f"{payload.keycloak_url.rstrip('/')}/realms/{payload.keycloak_realm}"

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Step 1 : discovery
        try:
            r = await client.get(f"{base}/.well-known/openid-configuration")
            if r.status_code != 200:
                return AuthTestResult(
                    ok=False,
                    step="discovery",
                    discovery_ok=False,
                    token_ok=False,
                    detail=f"discovery HTTP {r.status_code} : {r.text[:200]}",
                )
        except httpx.RequestError as exc:
            return AuthTestResult(
                ok=False,
                step="discovery",
                discovery_ok=False,
                token_ok=False,
                detail=f"discovery unreachable : {exc}",
            )

        # Step 2 : token
        try:
            r = await client.post(
                f"{base}/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": payload.keycloak_client_id,
                    "client_secret": secret,
                },
            )
            if r.status_code != 200:
                return AuthTestResult(
                    ok=False,
                    step="token",
                    discovery_ok=True,
                    token_ok=False,
                    detail=f"token HTTP {r.status_code} : {r.text[:200]}",
                )
        except httpx.RequestError as exc:
            return AuthTestResult(
                ok=False,
                step="token",
                discovery_ok=True,
                token_ok=False,
                detail=f"token unreachable : {exc}",
            )

    return AuthTestResult(
        ok=True,
        step="done",
        discovery_ok=True,
        token_ok=True,
        detail="connexion OK : discovery + client_credentials grant validés",
    )
```

- [ ] **Step 4 : Run tests**

```bash
cd backend && uv run pytest tests/services/test_auth_config_test_connection.py -v
```

Expected : 6 PASS (mocks httpx → tests purs, pas de DB pour 4/6 ; 2/6 utilisent reset_schema_and_migrate donc DONE_WITH_CONCERNS si DB unreachable).

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/auth_config_service.py tests/services/test_auth_config_test_connection.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/auth_config_service.py backend/tests/services/test_auth_config_test_connection.py
git commit -m "feat(auth-services): auth_config_service.test_connection (discovery + client_credentials)"
```

---

## LOT 2 — API REST + refactor auth.py (P2)

### Task 5 : Router `/auth-config` (GET + PUT + POST test)

**Files:**
- Create: `backend/src/agflow/api/admin/auth_config.py`
- Modify: `backend/src/agflow/main.py`
- Create: `backend/tests/api/test_admin_auth_config.py`

- [ ] **Step 1 : Écrire les tests (TDD red)**

```python
# backend/tests/api/test_admin_auth_config.py
"""Tests pour /api/admin/auth-config endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token
from agflow.schemas.auth_config import (
    AuthConfigOut,
    AuthTestResult,
)


def _admin_token() -> str:
    return encode_token("admin@example.com", role="admin")


def _viewer_token() -> str:
    return encode_token("viewer@example.com", role="viewer")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mk_config_out(**overrides) -> AuthConfigOut:
    from datetime import UTC, datetime
    base = dict(
        mode="local",
        keycloak_url="",
        keycloak_realm="",
        keycloak_client_id="",
        has_secret=False,
        vault_name="default",
        updated_at=datetime.now(UTC),
        updated_by_user_id=None,
    )
    base.update(overrides)
    return AuthConfigOut(**base)


def test_get_auth_config_admin_ok(client: TestClient):
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.get_config",
        new=AsyncMock(return_value=_mk_config_out(mode="keycloak", has_secret=True)),
    ):
        r = client.get("/api/admin/auth-config", headers=_auth(_admin_token()))
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "keycloak"
    assert body["has_secret"] is True
    # Le secret_ref ne DOIT PAS apparaître dans la réponse
    assert "keycloak_client_secret_ref" not in body
    assert "keycloak_client_secret" not in body


def test_get_auth_config_viewer_403(client: TestClient):
    r = client.get("/api/admin/auth-config", headers=_auth(_viewer_token()))
    assert r.status_code == 403


def test_get_auth_config_no_token_401(client: TestClient):
    r = client.get("/api/admin/auth-config")
    assert r.status_code == 401


def test_put_auth_config_updates(client: TestClient):
    refreshed = _mk_config_out(mode="keycloak", keycloak_url="https://kc.x.com")
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.update_config",
        new=AsyncMock(return_value=refreshed),
    ):
        r = client.put(
            "/api/admin/auth-config",
            headers=_auth(_admin_token()),
            json={"mode": "keycloak", "keycloak_url": "https://kc.x.com"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "keycloak"


def test_put_auth_config_invalid_url_422(client: TestClient):
    from agflow.services.auth_config_service import InvalidUrlError
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.update_config",
        new=AsyncMock(side_effect=InvalidUrlError("bad")),
    ):
        r = client.put(
            "/api/admin/auth-config",
            headers=_auth(_admin_token()),
            json={"keycloak_url": "not-a-url"},
        )
    assert r.status_code == 422


def test_put_auth_config_vault_unknown_404(client: TestClient):
    from agflow.services.auth_config_service import VaultNameUnknownError
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.update_config",
        new=AsyncMock(side_effect=VaultNameUnknownError("nope")),
    ):
        r = client.put(
            "/api/admin/auth-config",
            headers=_auth(_admin_token()),
            json={"vault_name": "nope"},
        )
    assert r.status_code == 404


def test_put_auth_config_viewer_403(client: TestClient):
    r = client.put(
        "/api/admin/auth-config",
        headers=_auth(_viewer_token()),
        json={"mode": "local"},
    )
    assert r.status_code == 403


def test_post_test_returns_200_even_on_failure(client: TestClient):
    """POST /test renvoie toujours 200 ; le statut est dans le payload."""
    fail = AuthTestResult(
        ok=False, step="token", discovery_ok=True, token_ok=False,
        detail="HTTP 401 invalid_client",
    )
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.test_connection",
        new=AsyncMock(return_value=fail),
    ):
        r = client.post(
            "/api/admin/auth-config/test",
            headers=_auth(_admin_token()),
            json={
                "keycloak_url": "https://kc.x.com",
                "keycloak_realm": "y",
                "keycloak_client_id": "a",
                "keycloak_client_secret": "s",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["step"] == "token"


def test_post_test_viewer_403(client: TestClient):
    r = client.post(
        "/api/admin/auth-config/test",
        headers=_auth(_viewer_token()),
        json={
            "keycloak_url": "https://kc.x.com",
            "keycloak_realm": "y",
            "keycloak_client_id": "a",
            "keycloak_client_secret": "s",
        },
    )
    assert r.status_code == 403
```

- [ ] **Step 2 : Run, échouent (router absent)**

```bash
cd backend && uv run pytest tests/api/test_admin_auth_config.py -v
```

Expected : tous FAIL (route inexistante, 404).

- [ ] **Step 3 : Écrire le router**

```python
# backend/src/agflow/api/admin/auth_config.py
"""Endpoints REST pour le paramétrage OIDC/Keycloak."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.schemas.auth_config import (
    AuthConfigOut,
    AuthConfigUpdate,
    AuthTestRequest,
    AuthTestResult,
)
from agflow.services import auth_config_service

router = APIRouter(
    prefix="/api/admin/auth-config",
    tags=["admin-auth-config"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AuthConfigOut)
async def get_auth_config() -> AuthConfigOut:
    """Retourne la config OIDC (sans révéler le secret)."""
    return await auth_config_service.get_config()


@router.put("", response_model=AuthConfigOut)
async def update_auth_config(
    payload: AuthConfigUpdate, actor_user_id: str = Depends(require_admin)
) -> AuthConfigOut:
    """Met à jour la config. Le client_secret (si fourni en clair) est
    poussé dans Harpocrate et seul le ref est stocké en DB."""
    actor_uuid: UUID | None
    try:
        actor_uuid = UUID(actor_user_id) if actor_user_id else None
    except ValueError:
        # require_admin retourne l'email (sub) — pas un UUID. Audit best-effort, on tolère.
        actor_uuid = None

    try:
        return await auth_config_service.update_config(payload, actor_user_id=actor_uuid)
    except auth_config_service.InvalidUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except auth_config_service.VaultNameUnknownError as exc:
        raise HTTPException(status_code=404, detail=f"vault not found: {exc}") from exc


@router.post("/test", response_model=AuthTestResult)
async def test_auth_config(payload: AuthTestRequest) -> AuthTestResult:
    """Teste la connexion Keycloak. Toujours HTTP 200 ; le succès/échec
    est dans `ok`."""
    return await auth_config_service.test_connection(payload)
```

- [ ] **Step 4 : Enregistrer le router dans `main.py`**

Ajouter l'import (en ordre alphabétique avec les autres `admin_*_router`) :

```python
from agflow.api.admin.auth_config import router as admin_auth_config_router
```

Et l'enregistrement (chercher la section `app.include_router(admin_auth_router)` et ajouter juste après) :

```python
app.include_router(admin_auth_config_router)
```

- [ ] **Step 5 : Run tests, doivent passer**

```bash
cd backend && uv run pytest tests/api/test_admin_auth_config.py -v
```

Expected : 9 PASS (tests mockent les services).

- [ ] **Step 6 : Lint + import sanity**

```bash
cd backend && uv run ruff check src/agflow/api/admin/auth_config.py src/agflow/main.py tests/api/test_admin_auth_config.py
cd backend && uv run python -c "from agflow.main import create_app; print('ok')"
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/api/admin/auth_config.py backend/src/agflow/main.py backend/tests/api/test_admin_auth_config.py
git commit -m "feat(auth-api): 3 endpoints /admin/auth-config (GET/PUT/POST test)"
```

### Task 6 : Refactor `auth.py` pour lire la DB

**Files:**
- Modify: `backend/src/agflow/api/admin/auth.py`
- Create: `backend/tests/api/test_admin_auth_oidc_uses_db.py`

- [ ] **Step 1 : Écrire le test (TDD red)**

```python
# backend/tests/api/test_admin_auth_oidc_uses_db.py
"""Vérifie que les endpoints OIDC de auth.py lisent la DB et non get_settings()."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token

pytestmark = pytest.mark.asyncio


def _admin_token() -> str:
    return encode_token("admin@example.com", role="admin")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_mode_endpoint_reads_db(client: TestClient):
    """GET /admin/auth/mode lit auth_config_service.get_config_internal()."""
    fake_cfg = {
        "mode": "keycloak",
        "keycloak_url": "https://kc.x.com",
        "keycloak_realm": "y",
        "keycloak_client_id": "agflow",
        "keycloak_client_secret_ref": "${vault://default:auth/keycloak/client_secret}",
        "vault_name": "default",
        "updated_at": None,
        "updated_by_user_id": None,
    }
    with patch(
        "agflow.api.admin.auth.auth_config_service.get_config_internal",
        new=AsyncMock(return_value=fake_cfg),
    ):
        r = client.get("/api/admin/auth/mode")
    assert r.status_code == 200
    assert r.json() == {"mode": "keycloak"}


def test_oidc_login_uses_db_config(client: TestClient):
    """GET /admin/auth/oidc/login construit l'URL avec les valeurs DB."""
    fake_cfg = {
        "mode": "keycloak",
        "keycloak_url": "https://kc.x.com",
        "keycloak_realm": "yoops",
        "keycloak_client_id": "agflow",
        "keycloak_client_secret_ref": "${vault://default:auth/keycloak/client_secret}",
        "vault_name": "default",
        "updated_at": None,
        "updated_by_user_id": None,
    }
    with patch(
        "agflow.api.admin.auth.auth_config_service.get_config_internal",
        new=AsyncMock(return_value=fake_cfg),
    ):
        r = client.get("/api/admin/auth/oidc/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "kc.x.com" in location
    assert "realms/yoops" in location
    assert "client_id=agflow" in location


def test_oidc_login_rejects_when_keycloak_not_configured(client: TestClient):
    """Si keycloak_url est vide en DB, /oidc/login retourne 400."""
    fake_cfg = {
        "mode": "local",
        "keycloak_url": "",
        "keycloak_realm": "",
        "keycloak_client_id": "",
        "keycloak_client_secret_ref": "",
        "vault_name": "default",
        "updated_at": None,
        "updated_by_user_id": None,
    }
    with patch(
        "agflow.api.admin.auth.auth_config_service.get_config_internal",
        new=AsyncMock(return_value=fake_cfg),
    ):
        r = client.get("/api/admin/auth/oidc/login")
    assert r.status_code == 400
```

- [ ] **Step 2 : Run, échouent (auth.py utilise encore get_settings)**

```bash
cd backend && uv run pytest tests/api/test_admin_auth_oidc_uses_db.py -v
```

Expected : tous FAIL ou erreurs car `agflow.api.admin.auth.auth_config_service` n'est pas encore importé.

- [ ] **Step 3 : Refactor `auth.py`**

Ajouter en haut de `backend/src/agflow/api/admin/auth.py` :

```python
from agflow.services import auth_config_service, vault_client
```

Puis remplacer toutes les occurrences de `settings.<champ keycloak>` :

Pour `auth_mode()` :
```python
@router.get("/mode")
async def auth_mode():
    cfg = await auth_config_service.get_config_internal()
    return {"mode": cfg["mode"]}
```

Pour `oidc_login(request)` — remplacer les lectures `settings.keycloak_*` par `cfg["keycloak_*"]`. Reconstruire `keycloak_base` localement :
```python
@router.get("/oidc/login", summary="Initiate Keycloak OIDC login")
async def oidc_login(request: Request) -> RedirectResponse:
    cfg = await auth_config_service.get_config_internal()
    if not cfg["keycloak_url"]:
        raise HTTPException(400, "Keycloak OIDC not configured")

    state = secrets.token_urlsafe(32)
    _oidc_states[state] = True

    redirect_uri = _build_oidc_redirect_uri(request)
    keycloak_base = f"{cfg['keycloak_url'].rstrip('/')}/realms/{cfg['keycloak_realm']}"
    authorize_url = f"{keycloak_base}/protocol/openid-connect/auth"

    params = {
        "client_id": cfg["keycloak_client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    return RedirectResponse(f"{authorize_url}?{urlencode(params)}")
```

Pour `oidc_callback(...)` :
- Remplacer la lecture de `settings.keycloak_base` par la construction locale `keycloak_base = f"{cfg['keycloak_url'].rstrip('/')}/realms/{cfg['keycloak_realm']}"`
- Remplacer `settings.keycloak_client_id` par `cfg["keycloak_client_id"]`
- Remplacer `settings.keycloak_client_secret` par une résolution : `client_secret_value = await vault_client.resolve_ref(cfg["keycloak_client_secret_ref"])` (à faire avant la requête token)

Repère les `settings = get_settings()` dans la fonction `oidc_callback` et remplace par :
```python
cfg = await auth_config_service.get_config_internal()
keycloak_base = f"{cfg['keycloak_url'].rstrip('/')}/realms/{cfg['keycloak_realm']}"
token_url = f"{keycloak_base}/protocol/openid-connect/token"
userinfo_url = f"{keycloak_base}/protocol/openid-connect/userinfo"

# Résoudre le client_secret depuis Harpocrate
if not cfg["keycloak_client_secret_ref"]:
    raise HTTPException(500, "Keycloak client_secret not configured")
client_secret_value = await vault_client.resolve_ref(cfg["keycloak_client_secret_ref"])
```

Puis dans le `client.post(token_url, data={...})` plus bas, remplacer `settings.keycloak_client_secret` par `client_secret_value` et `settings.keycloak_client_id` par `cfg["keycloak_client_id"]`.

Dans la section role extraction, remplacer `settings.keycloak_client_id` par `cfg["keycloak_client_id"]` dans :
```python
client_roles = (
    kc_payload
    .get("resource_access", {})
    .get(cfg["keycloak_client_id"], {})
    .get("roles", [])
)
```

- [ ] **Step 4 : Run tests, doivent passer**

```bash
cd backend && uv run pytest tests/api/test_admin_auth_oidc_uses_db.py -v
```

Expected : 3 PASS.

- [ ] **Step 5 : Vérifier que les anciens tests `auth.py` passent toujours**

```bash
cd backend && uv run pytest tests/api/ -v -k "auth" 2>&1 | tail -20
```

Expected : pas de nouvelle régression. Si un test ancien casse à cause de `get_settings`, l'adapter pour mocker `auth_config_service.get_config_internal` à la place.

- [ ] **Step 6 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/auth.py tests/api/test_admin_auth_oidc_uses_db.py
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/api/admin/auth.py backend/tests/api/test_admin_auth_oidc_uses_db.py
git commit -m "refactor(auth-api): endpoints OIDC lisent auth_config_service au lieu de get_settings()"
```

### Task 7 : Cleanup `config.py` + `.env.example`

**Files:**
- Modify: `backend/src/agflow/config.py`
- Modify: `.env.example`

- [ ] **Step 1 : Retirer les attributs Keycloak de `config.py`**

Supprimer dans `backend/src/agflow/config.py` :

```python
# À SUPPRIMER (toutes ces lignes)
    auth_mode: str = "local"
    keycloak_url: str = ""
    keycloak_realm: str = ""
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""
```

Et la property :

```python
# À SUPPRIMER
    @property
    def keycloak_base(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"
```

- [ ] **Step 2 : Retirer du `.env.example`**

Dans `.env.example`, retirer les lignes :
```
KEYCLOAK_URL=
KEYCLOAK_REALM=
KEYCLOAK_CLIENT_ID=
KEYCLOAK_CLIENT_SECRET=
AUTH_MODE=local
```

- [ ] **Step 3 : Vérifier qu'aucun reste**

```bash
cd backend && grep -rn "keycloak_url\|keycloak_realm\|keycloak_client_id\|keycloak_client_secret\|keycloak_base\|auth_mode" src/agflow/ | grep -v "auth_config" | grep -v "schemas/auth_config"
```

Expected : aucune sortie (toutes les références sont passées par `auth_config_service` ou les schemas). Si des références traînent, les corriger.

- [ ] **Step 4 : Vérifier import + lint**

```bash
cd backend && uv run python -c "from agflow.main import create_app; print('ok')"
cd backend && uv run ruff check src/agflow/config.py
```

Expected : `ok` + clean.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/config.py .env.example
git commit -m "chore(auth): retire les env vars Keycloak (config.py + .env.example) — DB est désormais source de vérité"
```

---

## LOT 3 — Frontend (P3)

### Task 8 : `authConfigApi.ts` (client TypeScript)

**Files:**
- Create: `frontend/src/lib/authConfigApi.ts`

- [ ] **Step 1 : Écrire le module**

```typescript
// frontend/src/lib/authConfigApi.ts
import { api } from "./api";

export type AuthMode = "local" | "keycloak";

export interface AuthConfig {
  mode: AuthMode;
  keycloak_url: string;
  keycloak_realm: string;
  keycloak_client_id: string;
  has_secret: boolean;
  vault_name: string;
  updated_at: string;
  updated_by_user_id: string | null;
}

export interface AuthConfigUpdate {
  mode?: AuthMode;
  keycloak_url?: string;
  keycloak_realm?: string;
  keycloak_client_id?: string;
  keycloak_client_secret?: string;
  vault_name?: string;
}

export interface AuthTestRequest {
  keycloak_url: string;
  keycloak_realm: string;
  keycloak_client_id: string;
  keycloak_client_secret?: string;
  vault_name?: string;
}

export interface AuthTestResult {
  ok: boolean;
  step: "discovery" | "token" | "done";
  detail: string;
  discovery_ok: boolean;
  token_ok: boolean;
}

export const authConfigApi = {
  getConfig: async (): Promise<AuthConfig> =>
    (await api.get<AuthConfig>("/admin/auth-config")).data,
  updateConfig: async (payload: AuthConfigUpdate): Promise<AuthConfig> =>
    (await api.put<AuthConfig>("/admin/auth-config", payload)).data,
  testConnection: async (payload: AuthTestRequest): Promise<AuthTestResult> =>
    (await api.post<AuthTestResult>("/admin/auth-config/test", payload)).data,
};
```

- [ ] **Step 2 : Vérifier TS**

```bash
cd frontend && npx tsc --noEmit
```

Expected : 0 nouvelle erreur pour ce fichier.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/lib/authConfigApi.ts
git commit -m "feat(auth-ui): authConfigApi client (3 endpoints typés)"
```

### Task 9 : Hook `useAuthConfig.ts` + test

**Files:**
- Create: `frontend/src/hooks/useAuthConfig.ts`
- Create: `frontend/src/hooks/__tests__/useAuthConfig.test.ts`

- [ ] **Step 1 : Écrire le hook**

```typescript
// frontend/src/hooks/useAuthConfig.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  type AuthConfig,
  type AuthConfigUpdate,
  type AuthTestRequest,
  authConfigApi,
} from "@/lib/authConfigApi";

const AUTH_KEY = ["auth-config"] as const;

export function useAuthConfig() {
  const qc = useQueryClient();
  const query = useQuery<AuthConfig>({
    queryKey: AUTH_KEY,
    queryFn: () => authConfigApi.getConfig(),
  });
  const updateMutation = useMutation({
    mutationFn: (payload: AuthConfigUpdate) => authConfigApi.updateConfig(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: AUTH_KEY }),
  });
  const testMutation = useMutation({
    mutationFn: (payload: AuthTestRequest) => authConfigApi.testConnection(payload),
    // Pas d'invalidation — test ne modifie pas la conf
  });
  return { ...query, update: updateMutation, test: testMutation };
}
```

- [ ] **Step 2 : Écrire le test Vitest**

```typescript
// frontend/src/hooks/__tests__/useAuthConfig.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { useAuthConfig } from "../useAuthConfig";
import { authConfigApi, type AuthConfig } from "@/lib/authConfigApi";

vi.mock("@/lib/authConfigApi");

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const fakeConfig: AuthConfig = {
  mode: "local",
  keycloak_url: "",
  keycloak_realm: "",
  keycloak_client_id: "",
  has_secret: false,
  vault_name: "default",
  updated_at: "2026-05-19T12:00:00Z",
  updated_by_user_id: null,
};

describe("useAuthConfig", () => {
  beforeEach(() => vi.resetAllMocks());

  it("fetches the config", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(fakeConfig);
    const { result } = renderHook(() => useAuthConfig(), { wrapper });
    await waitFor(() => expect(result.current.data?.mode).toBe("local"));
  });

  it("calls update when mutate is invoked", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(fakeConfig);
    (authConfigApi.updateConfig as any).mockResolvedValue({ ...fakeConfig, mode: "keycloak" });
    const { result } = renderHook(() => useAuthConfig(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    result.current.update.mutate({ mode: "keycloak" });
    await waitFor(() =>
      expect(authConfigApi.updateConfig).toHaveBeenCalledWith({ mode: "keycloak" })
    );
  });

  it("calls test connection", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(fakeConfig);
    (authConfigApi.testConnection as any).mockResolvedValue({
      ok: true, step: "done", detail: "OK", discovery_ok: true, token_ok: true,
    });
    const { result } = renderHook(() => useAuthConfig(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    result.current.test.mutate({
      keycloak_url: "https://x.com", keycloak_realm: "r", keycloak_client_id: "c", keycloak_client_secret: "s",
    });
    await waitFor(() => expect(authConfigApi.testConnection).toHaveBeenCalled());
  });
});
```

- [ ] **Step 3 : Run tests Vitest**

```bash
cd frontend && npm test -- --run useAuthConfig
```

Expected : 3 PASS.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/hooks/useAuthConfig.ts frontend/src/hooks/__tests__/useAuthConfig.test.ts
git commit -m "feat(auth-ui): hook useAuthConfig (query + update + test mutations)"
```

### Task 10 : Composant `AuthTab.tsx` + test

**Files:**
- Create: `frontend/src/components/settings/AuthTab.tsx`
- Create: `frontend/src/components/settings/__tests__/AuthTab.test.tsx`

- [ ] **Step 1 : Écrire le composant**

```tsx
// frontend/src/components/settings/AuthTab.tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { useAuthConfig } from "@/hooks/useAuthConfig";
import { type AuthTestResult } from "@/lib/authConfigApi";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Vault {
  id: string;
  name: string;
  url: string;
  is_default: boolean;
}

export function AuthTab() {
  const { t } = useTranslation();
  const { data: cfg, update, test } = useAuthConfig();
  const vaultsQuery = useQuery<Vault[]>({
    queryKey: ["harpocrate-vaults"],
    queryFn: () => api.get<Vault[]>("/admin/harpocrate-vaults").then((r) => r.data),
  });

  const [mode, setMode] = useState<"local" | "keycloak">("local");
  const [kcUrl, setKcUrl] = useState("");
  const [realm, setRealm] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [vaultName, setVaultName] = useState("default");
  const [testResult, setTestResult] = useState<AuthTestResult | null>(null);

  useEffect(() => {
    if (cfg) {
      setMode(cfg.mode);
      setKcUrl(cfg.keycloak_url);
      setRealm(cfg.keycloak_realm);
      setClientId(cfg.keycloak_client_id);
      setVaultName(cfg.vault_name);
      // Ne pas pré-remplir clientSecret — on garde le champ vide (placeholder dynamique)
    }
  }, [cfg]);

  const isKeycloakMode = mode === "keycloak";

  const onTest = () => {
    setTestResult(null);
    test.mutate(
      {
        keycloak_url: kcUrl,
        keycloak_realm: realm,
        keycloak_client_id: clientId,
        keycloak_client_secret: clientSecret || undefined,
        vault_name: vaultName,
      },
      { onSuccess: (res) => setTestResult(res) }
    );
  };

  const onSave = () => {
    update.mutate(
      {
        mode,
        keycloak_url: kcUrl,
        keycloak_realm: realm,
        keycloak_client_id: clientId,
        keycloak_client_secret: clientSecret || undefined,
        vault_name: vaultName,
      },
      {
        onSuccess: () => {
          toast.success(t("settings.auth.toast_saved"));
          setClientSecret(""); // reset le champ secret après save réussi
        },
        onError: (err) => {
          toast.error(`${t("settings.auth.toast_save_error")} : ${(err as Error).message}`);
        },
      }
    );
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">{t("settings.auth.title")}</h3>
        <p className="text-sm text-muted-foreground">{t("settings.auth.subtitle")}</p>
      </div>

      <div className="space-y-2">
        <Label>{t("settings.auth.mode_label")}</Label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              value="local"
              checked={mode === "local"}
              onChange={() => setMode("local")}
            />
            {t("settings.auth.mode_local")}
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              value="keycloak"
              checked={mode === "keycloak"}
              onChange={() => setMode("keycloak")}
            />
            {t("settings.auth.mode_keycloak")}
          </label>
        </div>
      </div>

      <fieldset
        disabled={!isKeycloakMode}
        className={`space-y-3 rounded border p-4 ${
          isKeycloakMode ? "" : "opacity-50"
        }`}
      >
        <legend className="px-2 text-sm font-medium">
          {t("settings.auth.keycloak_section")}
        </legend>
        <div className="space-y-1.5">
          <Label htmlFor="kc-url">{t("settings.auth.keycloak_url")}</Label>
          <Input
            id="kc-url"
            type="url"
            value={kcUrl}
            onChange={(e) => setKcUrl(e.target.value)}
            placeholder="https://keycloak.example.com"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-realm">{t("settings.auth.keycloak_realm")}</Label>
          <Input
            id="kc-realm"
            value={realm}
            onChange={(e) => setRealm(e.target.value)}
            placeholder="yoops"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-cid">{t("settings.auth.keycloak_client_id")}</Label>
          <Input
            id="kc-cid"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder="agflow-docker"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-secret">{t("settings.auth.keycloak_client_secret")}</Label>
          <Input
            id="kc-secret"
            type="password"
            value={clientSecret}
            onChange={(e) => setClientSecret(e.target.value)}
            placeholder={
              cfg?.has_secret
                ? t("settings.auth.secret_keep")
                : t("settings.auth.secret_required")
            }
            autoComplete="off"
          />
          <p className="text-xs text-muted-foreground">
            ⓘ {t("settings.auth.secret_hint_vault")}
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="kc-vault">{t("settings.auth.vault_name")}</Label>
          <select
            id="kc-vault"
            value={vaultName}
            onChange={(e) => setVaultName(e.target.value)}
            className="w-full rounded border px-2 py-1.5"
          >
            {vaultsQuery.data?.map((v) => (
              <option key={v.id} value={v.name}>
                {v.name} {v.is_default ? " (défaut)" : ""}
              </option>
            ))}
          </select>
        </div>
      </fieldset>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={!isKeycloakMode || test.isPending}
          onClick={onTest}
        >
          {t("settings.auth.test_button")}
        </Button>
        <Button onClick={onSave} disabled={update.isPending}>
          {t("settings.auth.save_button")}
        </Button>
      </div>

      {testResult && (
        <div className="space-y-1 rounded border p-3 text-sm">
          <p className="font-medium">{t("settings.auth.test_result_title")}</p>
          <p>
            {testResult.discovery_ok ? "✓" : "✗"}{" "}
            {testResult.discovery_ok
              ? t("settings.auth.test_discovery_ok")
              : t("settings.auth.test_discovery_ko")}
          </p>
          <p>
            {testResult.token_ok ? "✓" : "✗"}{" "}
            {testResult.token_ok
              ? t("settings.auth.test_token_ok")
              : t("settings.auth.test_token_ko")}
          </p>
          {testResult.ok ? (
            <p className="text-green-600">→ {t("settings.auth.test_done")}</p>
          ) : (
            <p className="text-destructive">→ {testResult.detail}</p>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2 : Écrire le test Vitest**

```tsx
// frontend/src/components/settings/__tests__/AuthTab.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { AuthTab } from "../AuthTab";
import { authConfigApi, type AuthConfig } from "@/lib/authConfigApi";
import { api } from "@/lib/api";

vi.mock("@/lib/authConfigApi");
vi.mock("@/lib/api");

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

const baseCfg: AuthConfig = {
  mode: "local",
  keycloak_url: "",
  keycloak_realm: "",
  keycloak_client_id: "",
  has_secret: false,
  vault_name: "default",
  updated_at: "2026-05-19T12:00:00Z",
  updated_by_user_id: null,
};

describe("AuthTab", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (api.get as any).mockResolvedValue({
      data: [{ id: "v1", name: "default", url: "http://h", is_default: true }],
    });
  });

  it("renders form with local mode by default", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => expect(screen.getByLabelText(/Mode/i)).toBeTruthy());
    const radioLocal = screen.getByRole("radio", { name: /local/i }) as HTMLInputElement;
    expect(radioLocal.checked).toBe(true);
  });

  it("disables Test button in local mode", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("button", { name: /Tester/i }));
    const testBtn = screen.getByRole("button", { name: /Tester/i });
    expect(testBtn).toBeDisabled();
  });

  it("enables Test button after switching to keycloak", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByRole("radio", { name: /Keycloak/i }));
    fireEvent.click(screen.getByRole("radio", { name: /Keycloak/i }));
    const testBtn = screen.getByRole("button", { name: /Tester/i });
    expect(testBtn).not.toBeDisabled();
  });

  it("calls update with the form values when Save clicked", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    (authConfigApi.updateConfig as any).mockResolvedValue(baseCfg);
    wrap(<AuthTab />);
    await waitFor(() => screen.getByLabelText(/URL Keycloak/i));
    fireEvent.click(screen.getByRole("radio", { name: /Keycloak/i }));
    fireEvent.change(screen.getByLabelText(/URL Keycloak/i), {
      target: { value: "https://kc.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enregistrer/i }));
    await waitFor(() =>
      expect(authConfigApi.updateConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: "keycloak",
          keycloak_url: "https://kc.example.com",
        })
      )
    );
  });

  it("shows test result with check marks on success", async () => {
    (authConfigApi.getConfig as any).mockResolvedValue(baseCfg);
    (authConfigApi.testConnection as any).mockResolvedValue({
      ok: true, step: "done", detail: "OK",
      discovery_ok: true, token_ok: true,
    });
    wrap(<AuthTab />);
    await waitFor(() => screen.getByLabelText(/URL Keycloak/i));
    fireEvent.click(screen.getByRole("radio", { name: /Keycloak/i }));
    fireEvent.click(screen.getByRole("button", { name: /Tester/i }));
    await waitFor(() => screen.getByText(/Connexion validée|validated/i));
    expect(screen.getByText(/✓/)).toBeTruthy();
  });
});
```

- [ ] **Step 3 : Run tests**

```bash
cd frontend && npm test -- --run AuthTab
```

Expected : 5 PASS.

- [ ] **Step 4 : TS check**

```bash
cd frontend && npx tsc --noEmit
```

Expected : 0 nouvelle erreur.

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/components/settings/AuthTab.tsx frontend/src/components/settings/__tests__/AuthTab.test.tsx
git commit -m "feat(auth-ui): AuthTab component (form mode + champs Keycloak + test + save)"
```

### Task 11 : Intégrer dans `SettingsPage.tsx`

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1 : Ajouter l'import + l'onglet**

Modifier `frontend/src/pages/SettingsPage.tsx` :

```tsx
import { useTranslation } from "react-i18next";

import { AuthTab } from "@/components/settings/AuthTab";
import { GitSyncTab } from "@/components/settings/GitSyncTab";
import { HarpocrateVaultsTab } from "@/components/settings/HarpocrateVaultsTab";
import { PageHeader, PageShell } from "@/components/layout/PageHeader";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

export function SettingsPage() {
  const { t } = useTranslation();

  return (
    <PageShell>
      <PageHeader
        title={t("settings.title")}
        subtitle={t("settings.description")}
      />
      <Tabs defaultValue="harpocrate" className="w-full">
        <TabsList>
          <TabsTrigger value="harpocrate">
            {t("settings.tabs.harpocrate")}
          </TabsTrigger>
          <TabsTrigger value="git-sync">
            {t("settings.tabs.gitSync")}
          </TabsTrigger>
          <TabsTrigger value="auth">
            {t("settings.tabs.auth")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="harpocrate" className="mt-4">
          <HarpocrateVaultsTab />
        </TabsContent>
        <TabsContent value="git-sync" className="mt-4">
          <GitSyncTab />
        </TabsContent>
        <TabsContent value="auth" className="mt-4">
          <AuthTab />
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}
```

- [ ] **Step 2 : TS check + lint**

```bash
cd frontend && npx tsc --noEmit
```

Expected : 0 erreur.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat(auth-ui): ajoute l'onglet Authentification dans SettingsPage"
```

### Task 12 : i18n FR + EN

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés FR**

Dans `frontend/src/i18n/fr.json`, sous `settings.tabs` ajouter `"auth": "Authentification"` et sous `settings` ajouter le bloc `auth` :

```json
{
  "settings": {
    "tabs": {
      "harpocrate": "Harpocrate",
      "gitSync": "Git Sync",
      "auth": "Authentification"
    },
    "auth": {
      "title": "Authentification",
      "subtitle": "Configurer le mode de connexion (local et/ou Keycloak SSO)",
      "mode_label": "Mode d'authentification",
      "mode_local": "Local seulement",
      "mode_keycloak": "Local + Keycloak SSO",
      "keycloak_section": "Identifiants Keycloak",
      "keycloak_url": "URL Keycloak",
      "keycloak_realm": "Realm",
      "keycloak_client_id": "Client ID",
      "keycloak_client_secret": "Client Secret",
      "secret_keep": "Laisser vide pour conserver le secret actuel",
      "secret_required": "Coller le secret du client",
      "secret_hint_vault": "Stocké chiffré dans Harpocrate",
      "vault_name": "Coffre Harpocrate",
      "test_button": "Tester la connexion",
      "save_button": "Enregistrer",
      "test_result_title": "Résultat du test",
      "test_discovery_ok": "Discovery OK",
      "test_discovery_ko": "Discovery échoué",
      "test_token_ok": "client_credentials grant OK",
      "test_token_ko": "client_credentials échoué",
      "test_done": "Connexion validée",
      "toast_saved": "Configuration enregistrée",
      "toast_save_error": "Erreur lors de l'enregistrement"
    }
  }
}
```

- [ ] **Step 2 : Ajouter les clés EN équivalentes**

Dans `frontend/src/i18n/en.json` :

```json
{
  "settings": {
    "tabs": {
      "auth": "Authentication"
    },
    "auth": {
      "title": "Authentication",
      "subtitle": "Configure login mode (local and/or Keycloak SSO)",
      "mode_label": "Authentication mode",
      "mode_local": "Local only",
      "mode_keycloak": "Local + Keycloak SSO",
      "keycloak_section": "Keycloak credentials",
      "keycloak_url": "Keycloak URL",
      "keycloak_realm": "Realm",
      "keycloak_client_id": "Client ID",
      "keycloak_client_secret": "Client Secret",
      "secret_keep": "Leave empty to keep current secret",
      "secret_required": "Paste the client secret",
      "secret_hint_vault": "Stored encrypted in Harpocrate",
      "vault_name": "Harpocrate vault",
      "test_button": "Test connection",
      "save_button": "Save",
      "test_result_title": "Test result",
      "test_discovery_ok": "Discovery OK",
      "test_discovery_ko": "Discovery failed",
      "test_token_ok": "client_credentials grant OK",
      "test_token_ko": "client_credentials failed",
      "test_done": "Connection validated",
      "toast_saved": "Configuration saved",
      "toast_save_error": "Save error"
    }
  }
}
```

- [ ] **Step 3 : Vérifier la validité JSON**

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/fr.json','utf8'))"
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/en.json','utf8'))"
```

Expected : pas d'erreur.

- [ ] **Step 4 : TS check**

```bash
cd frontend && npx tsc --noEmit
```

Expected : 0 erreur.

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(auth-ui): i18n FR + EN — ~25 clés settings.auth.*"
```

---

## LOT 4 — Cleanup + validation (P4)

### Task 13 : Sanity check global

**Files:**
- (validation only — aucun fichier modifié sauf si régressions)

- [ ] **Step 1 : Aucun reste de env vars Keycloak côté backend**

```bash
cd backend && grep -rn "keycloak_url\|keycloak_realm\|keycloak_client_id\|keycloak_client_secret\|keycloak_base\|auth_mode" src/agflow/ | grep -v "auth_config" | grep -v "schemas/auth_config"
```

Expected : aucune sortie.

```bash
cd backend && grep -rn "KEYCLOAK_URL\|KEYCLOAK_REALM\|KEYCLOAK_CLIENT_ID\|KEYCLOAK_CLIENT_SECRET\|AUTH_MODE" . --include="*.py" --include="*.example"
```

Expected : aucune sortie.

- [ ] **Step 2 : Tests backend + frontend passent**

```bash
cd backend && uv run pytest tests/services/test_auth_config_service.py tests/services/test_auth_config_test_connection.py tests/api/test_admin_auth_config.py tests/api/test_admin_auth_oidc_uses_db.py tests/db/test_migration_113_auth_config.py -v
```

Si DB joignable : tous PASS. Sinon DONE_WITH_CONCERNS sur les tests DB.

```bash
cd frontend && npm test -- --run useAuthConfig AuthTab
```

Expected : tous PASS.

- [ ] **Step 3 : Lint global**

```bash
cd backend && uv run ruff check src/agflow/services/auth_config_service.py src/agflow/api/admin/auth_config.py src/agflow/api/admin/auth.py src/agflow/main.py src/agflow/config.py src/agflow/schemas/auth_config.py
cd frontend && npx tsc --noEmit
```

Expected : tout clean.

- [ ] **Step 4 : Si une régression est détectée → fix inline**

Si grep révèle un reste, ou si un test casse, corriger via Edit puis re-commit avec un message `fix(auth-*): ...` adapté.

- [ ] **Step 5 : (Si tout est clean) Commit éventuel ou rien**

Si aucun fichier modifié, pas de commit. Sinon adapter.

### Task 14 : Validation E2E manuelle (par l'utilisateur)

**Files:**
- (rien à modifier — c'est une checklist manuelle)

- [ ] **Step 1 : `git push origin dev` puis déploiement via `./dev-deploy.sh` sur machine 303**

(Exécuté par l'utilisateur — pas par le subagent.)

- [ ] **Step 2 : Login local OK**

Ouvrir `/login` → form local visible (mode=local par défaut après migration 113). Login admin@... → JWT obtenu → arrive sur la home.

- [ ] **Step 3 : Page `/settings > Authentification` accessible**

L'onglet `Authentification` apparaît à côté de `Harpocrate` et `Git Sync`. Le clic montre le form. Mode `local` sélectionné. Champs Keycloak grisés.

- [ ] **Step 4 : Saisir les identifiants Keycloak**

- Basculer le mode sur `keycloak`
- Champs deviennent éditables
- Saisir URL, realm, client_id, client_secret
- Sélectionner le coffre Harpocrate
- Cliquer « Tester la connexion » → résultat affiché (✓ Discovery + ✓ Token + → Connexion validée)
- Cliquer « Enregistrer » → toast vert
- Champ secret se vide automatiquement

- [ ] **Step 5 : Bascule du mode visible sur `/login`**

Refresh `/login` (déconnexion + retour) → bouton SSO Keycloak visible + lien fallback vers form local. Cliquer SSO → flow OIDC complet → retour avec JWT app.

- [ ] **Step 6 : Si une régression apparaît, partager le détail**

Logs backend, capture UI, état DB (`SELECT * FROM auth_config WHERE id = 1` via pgweb).

---

## Validation finale

- [ ] Migration 113 appliquée, singleton seedé, contraintes vérifiées
- [ ] Service Python : 8 tests verts + 6 tests test_connection verts (mocks httpx)
- [ ] API : 9 tests verts (3 endpoints × auth + happy + erreurs)
- [ ] Refactor `auth.py` : 3 tests OIDC verts (DB lue, pas `get_settings()`)
- [ ] `config.py` ne contient plus aucun attribut Keycloak ; `.env.example` nettoyé
- [ ] Frontend : 3 tests `useAuthConfig` + 5 tests `AuthTab` verts
- [ ] tsc + ruff + ESLint clean
- [ ] Smoke E2E manuel passé sur LXC 201 (login local, page Settings, save, bascule SSO sur /login)
