# Users & API Keys — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-user authentication with self-validating API keys (HMAC checksum + embedded expiry), scoped permissions, Redis rate limiting, and admin CRUD pages for users and keys.

**Architecture:** Three-layer backend (migrations → services → endpoints) + auth middleware with 3-level validation (O(1) checksum → DB+bcrypt → Redis rate limit). Frontend: two new admin pages (Users, API Keys) following existing shadcn/Tailwind patterns.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, bcrypt, HMAC-SHA256, redis.asyncio, React 18, TypeScript, TanStack Query, shadcn/ui, i18next

**Spec:** `docs/superpowers/specs/2026-04-12-users-apikeys-design.md`

---

## File Structure

### New files

| File | Responsibility |
|---|---|
| `backend/migrations/022_users.sql` | Users table |
| `backend/migrations/023_user_identities.sql` | OAuth identities table |
| `backend/migrations/024_seed_admin_user.sql` | Placeholder (seed in Python) |
| `backend/migrations/025_api_keys.sql` | API keys table |
| `backend/src/agflow/redis/client.py` | Redis async singleton client |
| `backend/src/agflow/schemas/users.py` | User Pydantic DTOs |
| `backend/src/agflow/schemas/api_keys.py` | API key Pydantic DTOs |
| `backend/src/agflow/services/users_service.py` | User CRUD + seed admin |
| `backend/src/agflow/services/api_keys_service.py` | Key generation, CRUD, scope validation |
| `backend/src/agflow/auth/api_key.py` | Token parsing, HMAC validation, require_api_key dependency, rate limit |
| `backend/src/agflow/api/admin/users.py` | Admin users router |
| `backend/src/agflow/api/admin/api_keys.py` | Admin API keys router |
| `backend/tests/test_users_service.py` | User service tests |
| `backend/tests/test_api_keys_service.py` | API key service tests |
| `backend/tests/test_api_key_auth.py` | Auth middleware tests |
| `frontend/src/lib/usersApi.ts` | Users API client |
| `frontend/src/lib/apiKeysApi.ts` | API keys API client |
| `frontend/src/hooks/useUsers.ts` | Users React Query hook |
| `frontend/src/hooks/useApiKeys.ts` | API keys React Query hook |
| `frontend/src/pages/UsersPage.tsx` | Admin users page |
| `frontend/src/pages/ApiKeysPage.tsx` | Admin API keys page |

### Modified files

| File | Change |
|---|---|
| `backend/src/agflow/config.py` | Add `api_key_salt` field |
| `backend/src/agflow/main.py` | Register users + api_keys routers, seed admin in lifespan |
| `backend/src/agflow/auth/dependencies.py` | Add `require_auth()` dual JWT/API key dependency |
| `backend/src/agflow/redis/__init__.py` | Empty package init |
| `.env.example` | Add `API_KEY_SALT=` |
| `frontend/src/App.tsx` | Add `/users` + `/api-keys` routes |
| `frontend/src/components/layout/Sidebar.tsx` | Add Users + API Keys menu items |
| `frontend/src/i18n/fr.json` | French translations |
| `frontend/src/i18n/en.json` | English translations |

---

## Task 1: SQL Migrations

**Files:**
- Create: `backend/migrations/022_users.sql`
- Create: `backend/migrations/023_user_identities.sql`
- Create: `backend/migrations/024_seed_admin_user.sql`
- Create: `backend/migrations/025_api_keys.sql`

- [ ] **Step 1: Write migration 022 — users table**

```sql
-- 022_users.sql
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT '',
    avatar_url  TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('admin', 'user')),
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id),
    last_login  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
```

- [ ] **Step 2: Write migration 023 — user_identities table**

```sql
-- 023_user_identities.sql
CREATE TABLE IF NOT EXISTS user_identities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    email       TEXT,
    raw_claims  JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_identities_lookup ON user_identities(provider, subject);
```

- [ ] **Step 3: Write migration 024 — seed admin placeholder**

```sql
-- 024_seed_admin_user.sql
-- The initial admin user is seeded in the backend lifespan (Python) because
-- it needs access to settings.admin_email. This file is a no-op placeholder
-- so the migration numbering stays sequential.
SELECT 1;
```

- [ ] **Step 4: Write migration 025 — api_keys table**

```sql
-- 025_api_keys.sql
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    prefix          TEXT NOT NULL UNIQUE,
    key_hash        TEXT NOT NULL,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    rate_limit      INT NOT NULL DEFAULT 120,
    expires_at      TIMESTAMPTZ,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner_id);
```

- [ ] **Step 5: Verify migrations apply cleanly**

Run: `cd backend && uv run python -m agflow.db.migrations`
Expected: 4 new migrations applied (022-025)

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/022_users.sql backend/migrations/023_user_identities.sql \
       backend/migrations/024_seed_admin_user.sql backend/migrations/025_api_keys.sql
git commit -m "feat(db): migrations 022-025 users + identities + api_keys tables"
```

---

## Task 2: Redis Client + Config

**Files:**
- Create: `backend/src/agflow/redis/__init__.py`
- Create: `backend/src/agflow/redis/client.py`
- Modify: `backend/src/agflow/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Create Redis package init**

```python
# backend/src/agflow/redis/__init__.py
```
(empty file)

- [ ] **Step 2: Write Redis client singleton**

```python
# backend/src/agflow/redis/client.py
from __future__ import annotations

import redis.asyncio as aioredis
import structlog

from agflow.config import get_settings

_log = structlog.get_logger(__name__)
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        _log.info("redis.connected", url=settings.redis_url)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        _log.info("redis.closed")
```

- [ ] **Step 3: Add api_key_salt to config**

In `backend/src/agflow/config.py`, add to the Settings class:

```python
api_key_salt: str = ""
```

- [ ] **Step 4: Update .env.example**

Add line:
```
API_KEY_SALT=change-me-to-a-random-32-plus-char-string
```

- [ ] **Step 5: Generate and set API_KEY_SALT in .env on LXC**

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Copy the output and add it to .env as API_KEY_SALT=<value>
```

- [ ] **Step 6: Verify Redis import works**

Run: `cd backend && uv run python -c "from agflow.redis.client import get_redis; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend/src/agflow/redis/ backend/src/agflow/config.py .env.example
git commit -m "feat: Redis client singleton + api_key_salt config"
```

---

## Task 3: User Schemas + Service

**Files:**
- Create: `backend/src/agflow/schemas/users.py`
- Create: `backend/src/agflow/services/users_service.py`
- Test: `backend/tests/test_users_service.py`

- [ ] **Step 1: Write user schemas**

```python
# backend/src/agflow/schemas/users.py
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=200)
    role: Literal["admin", "user"] = "user"
    scopes: list[str] = Field(default_factory=list)
    status: Literal["pending", "active"] = "active"


class UserSummary(BaseModel):
    id: UUID
    email: str
    name: str
    avatar_url: str
    role: str
    scopes: list[str]
    status: str
    created_at: datetime
    approved_at: datetime | None
    last_login: datetime | None
    api_key_count: int = 0


class UserUpdate(BaseModel):
    name: str | None = None
    role: Literal["admin", "user"] | None = None
    scopes: list[str] | None = None
```

- [ ] **Step 2: Write users service**

```python
# backend/src/agflow/services/users_service.py
from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.users import UserSummary

_log = structlog.get_logger(__name__)

_USER_COLS = """
    u.id, u.email, u.name, u.avatar_url, u.role, u.scopes, u.status,
    u.created_at, u.approved_at, u.last_login
"""


class UserNotFoundError(Exception):
    pass


class DuplicateUserError(Exception):
    pass


def _row_to_summary(row: dict[str, Any], key_count: int = 0) -> UserSummary:
    return UserSummary(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        avatar_url=row["avatar_url"],
        role=row["role"],
        scopes=row["scopes"] or [],
        status=row["status"],
        created_at=row["created_at"],
        approved_at=row.get("approved_at"),
        last_login=row.get("last_login"),
        api_key_count=key_count,
    )


async def list_all() -> list[UserSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_USER_COLS},
               (SELECT COUNT(*) FROM api_keys k
                WHERE k.owner_id = u.id AND k.revoked = FALSE) AS key_count
        FROM users u
        ORDER BY
            CASE u.status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END,
            u.created_at DESC
        """
    )
    return [_row_to_summary(r, r.get("key_count", 0)) for r in rows]


async def get_by_id(user_id: UUID) -> UserSummary:
    row = await fetch_one(
        f"""
        SELECT {_USER_COLS},
               (SELECT COUNT(*) FROM api_keys k
                WHERE k.owner_id = u.id AND k.revoked = FALSE) AS key_count
        FROM users u WHERE u.id = $1
        """,
        user_id,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    return _row_to_summary(row, row.get("key_count", 0))


async def get_by_email(email: str) -> UserSummary | None:
    row = await fetch_one(
        f"SELECT {_USER_COLS} FROM users u WHERE u.email = $1", email
    )
    return _row_to_summary(row) if row else None


async def create(
    email: str,
    name: str = "",
    role: str = "user",
    scopes: list[str] | None = None,
    status: str = "active",
) -> UserSummary:
    try:
        row = await fetch_one(
            """
            INSERT INTO users (email, name, role, scopes, status)
            VALUES ($1, $2, $3, $4::text[], $5)
            RETURNING id, email, name, avatar_url, role, scopes, status,
                      created_at, approved_at, last_login
            """,
            email,
            name,
            role,
            scopes or [],
            status,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateUserError(f"User '{email}' already exists") from exc
    assert row is not None
    _log.info("users.create", email=email, role=role)
    return _row_to_summary(row)


async def update(
    user_id: UUID,
    name: str | None = None,
    role: str | None = None,
    scopes: list[str] | None = None,
) -> UserSummary:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    if name is not None:
        sets.append(f"name = ${idx}")
        args.append(name)
        idx += 1
    if role is not None:
        sets.append(f"role = ${idx}")
        args.append(role)
        idx += 1
    if scopes is not None:
        sets.append(f"scopes = ${idx}::text[]")
        args.append(scopes)
        idx += 1
    if not sets:
        return await get_by_id(user_id)
    args.append(user_id)
    row = await fetch_one(
        f"""
        UPDATE users SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING id, email, name, avatar_url, role, scopes, status,
                  created_at, approved_at, last_login
        """,
        *args,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.update", user_id=str(user_id))
    return _row_to_summary(row)


async def approve(user_id: UUID, approved_by: UUID) -> UserSummary:
    row = await fetch_one(
        """
        UPDATE users SET status = 'active', approved_at = NOW(), approved_by = $2
        WHERE id = $1
        RETURNING id, email, name, avatar_url, role, scopes, status,
                  created_at, approved_at, last_login
        """,
        user_id,
        approved_by,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.approve", user_id=str(user_id))
    return _row_to_summary(row)


async def disable(user_id: UUID) -> UserSummary:
    row = await fetch_one(
        """
        UPDATE users SET status = 'disabled'
        WHERE id = $1
        RETURNING id, email, name, avatar_url, role, scopes, status,
                  created_at, approved_at, last_login
        """,
        user_id,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.disable", user_id=str(user_id))
    return _row_to_summary(row)


async def enable(user_id: UUID) -> UserSummary:
    row = await fetch_one(
        """
        UPDATE users SET status = 'active'
        WHERE id = $1
        RETURNING id, email, name, avatar_url, role, scopes, status,
                  created_at, approved_at, last_login
        """,
        user_id,
    )
    if row is None:
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.enable", user_id=str(user_id))
    return _row_to_summary(row)


async def delete(user_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    if result == "DELETE 0":
        raise UserNotFoundError(f"User {user_id} not found")
    _log.info("users.delete", user_id=str(user_id))


async def seed_admin(email: str) -> None:
    """Create the initial admin user if it doesn't exist yet."""
    existing = await get_by_email(email)
    if existing is not None:
        return
    await create(email=email, name="Admin", role="admin", scopes=[], status="active")
    _log.info("users.seed_admin", email=email)
```

- [ ] **Step 3: Write failing tests for users service**

```python
# backend/tests/test_users_service.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.68:5432/agflow_test"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")
os.environ.setdefault("API_KEY_SALT", "test-salt-for-hmac-32chars-ok!!")

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.services import users_service

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS api_keys CASCADE")
    await execute("DROP TABLE IF EXISTS user_identities CASCADE")
    await execute("DROP TABLE IF EXISTS users CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_user() -> None:
    user = await users_service.create(email="test@example.com", name="Test")
    assert user.email == "test@example.com"
    assert user.status == "active"
    assert user.role == "user"


@pytest.mark.asyncio
async def test_seed_admin() -> None:
    await users_service.seed_admin("admin@example.com")
    user = await users_service.get_by_email("admin@example.com")
    assert user is not None
    assert user.role == "admin"
    assert user.status == "active"


@pytest.mark.asyncio
async def test_seed_admin_idempotent() -> None:
    await users_service.seed_admin("admin@example.com")
    await users_service.seed_admin("admin@example.com")
    users = await users_service.list_all()
    admins = [u for u in users if u.email == "admin@example.com"]
    assert len(admins) == 1


@pytest.mark.asyncio
async def test_approve_user() -> None:
    admin = await users_service.create(
        email="admin@example.com", role="admin", status="active"
    )
    user = await users_service.create(
        email="user@example.com", status="pending"
    )
    assert user.status == "pending"
    approved = await users_service.approve(user.id, approved_by=admin.id)
    assert approved.status == "active"
    assert approved.approved_at is not None


@pytest.mark.asyncio
async def test_disable_and_enable() -> None:
    user = await users_service.create(email="user@example.com")
    disabled = await users_service.disable(user.id)
    assert disabled.status == "disabled"
    enabled = await users_service.enable(user.id)
    assert enabled.status == "active"


@pytest.mark.asyncio
async def test_update_scopes() -> None:
    user = await users_service.create(email="user@example.com")
    updated = await users_service.update(
        user.id, scopes=["roles:read", "agents:run"]
    )
    assert set(updated.scopes) == {"roles:read", "agents:run"}


@pytest.mark.asyncio
async def test_delete_user() -> None:
    user = await users_service.create(email="user@example.com")
    await users_service.delete(user.id)
    result = await users_service.get_by_email("user@example.com")
    assert result is None
```

- [ ] **Step 4: Run tests — they should pass**

Run: `cd backend && uv run pytest tests/test_users_service.py -v`

Note: these tests use `agflow_test` DB — create it first if it doesn't exist:
```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d postgres -c 'CREATE DATABASE agflow_test OWNER agflow;'"
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/schemas/users.py backend/src/agflow/services/users_service.py \
       backend/tests/test_users_service.py
git commit -m "feat: users service with CRUD + seed admin + tests"
```

---

## Task 4: API Key Token Library

**Files:**
- Create: `backend/src/agflow/auth/api_key.py`
- Test: `backend/tests/test_api_key_auth.py`

- [ ] **Step 1: Write token generation + parsing + HMAC validation**

```python
# backend/src/agflow/auth/api_key.py
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime

import bcrypt

_KEY_RE = re.compile(
    r"^agfd_"
    r"(?P<prefix>[0-9a-f]{12})"
    r"(?P<expiry>[0-9a-f]{8})"
    r"(?P<random>[0-9a-f]{20})"
    r"(?P<hmac>[0-9a-f]{8})$"
)

NO_EXPIRY = 0xFFFFFFFF


@dataclass
class ParsedKey:
    prefix: str
    expiry_ts: int
    random: str
    hmac_value: str
    body: str


def generate_api_key(
    salt: str,
    expires_at: datetime | None,
) -> tuple[str, str, str]:
    """Generate a self-validating API key.

    Returns (full_key, prefix, bcrypt_hash).
    """
    prefix = secrets.token_hex(6)
    expiry_hex = (
        "ffffffff"
        if expires_at is None
        else f"{int(expires_at.timestamp()):08x}"
    )
    random_part = secrets.token_hex(10)
    body = prefix + expiry_hex + random_part
    checksum = hmac_mod.new(
        salt.encode(), body.encode(), hashlib.sha256
    ).hexdigest()[:8]
    full_key = f"agfd_{body}{checksum}"
    key_hash = bcrypt.hashpw(full_key.encode(), bcrypt.gensalt()).decode()
    return full_key, prefix, key_hash


def parse_api_key(raw: str) -> ParsedKey | None:
    m = _KEY_RE.match(raw.strip().lower())
    if not m:
        return None
    return ParsedKey(
        prefix=m.group("prefix"),
        expiry_ts=int(m.group("expiry"), 16),
        random=m.group("random"),
        hmac_value=m.group("hmac"),
        body=m.group("prefix") + m.group("expiry") + m.group("random"),
    )


def verify_hmac(parsed: ParsedKey, salt: str) -> bool:
    expected = hmac_mod.new(
        salt.encode(), parsed.body.encode(), hashlib.sha256
    ).hexdigest()[:8]
    return hmac_mod.compare_digest(expected, parsed.hmac_value)


def is_expired(parsed: ParsedKey) -> bool:
    if parsed.expiry_ts == NO_EXPIRY:
        return False
    return parsed.expiry_ts < int(time.time())


def verify_bcrypt(full_key: str, key_hash: str) -> bool:
    return bcrypt.checkpw(full_key.encode(), key_hash.encode())
```

- [ ] **Step 2: Write failing tests**

```python
# backend/tests/test_api_key_auth.py
from __future__ import annotations

import time

import pytest

from agflow.auth.api_key import (
    NO_EXPIRY,
    generate_api_key,
    is_expired,
    parse_api_key,
    verify_bcrypt,
    verify_hmac,
)

SALT = "test-salt-for-hmac-32chars-ok!!"


def test_generate_key_format() -> None:
    key, prefix, key_hash = generate_api_key(SALT, expires_at=None)
    assert key.startswith("agfd_")
    assert len(key) == 53
    assert len(prefix) == 12
    assert key_hash.startswith("$2b$")


def test_generate_key_roundtrip() -> None:
    key, prefix, key_hash = generate_api_key(SALT, expires_at=None)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert parsed.prefix == prefix
    assert parsed.expiry_ts == NO_EXPIRY
    assert verify_hmac(parsed, SALT)
    assert verify_bcrypt(key, key_hash)


def test_parse_invalid_key() -> None:
    assert parse_api_key("invalid") is None
    assert parse_api_key("agfd_tooshort") is None
    assert parse_api_key("agfx_" + "a" * 48) is None


def test_hmac_rejects_tampered_key() -> None:
    key, _, _ = generate_api_key(SALT, expires_at=None)
    tampered = key[:10] + "0" + key[11:]
    parsed = parse_api_key(tampered)
    if parsed is not None:
        assert not verify_hmac(parsed, SALT)


def test_expiry_encoding() -> None:
    from datetime import datetime, timezone

    future = datetime(2027, 6, 15, tzinfo=timezone.utc)
    key, _, _ = generate_api_key(SALT, expires_at=future)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert not is_expired(parsed)
    assert parsed.expiry_ts == int(future.timestamp())


def test_expired_key_detected() -> None:
    from datetime import datetime, timezone

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    key, _, _ = generate_api_key(SALT, expires_at=past)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert is_expired(parsed)


def test_no_expiry() -> None:
    key, _, _ = generate_api_key(SALT, expires_at=None)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert parsed.expiry_ts == NO_EXPIRY
    assert not is_expired(parsed)
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/test_api_key_auth.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/auth/api_key.py backend/tests/test_api_key_auth.py
git commit -m "feat: self-validating API key generation + parsing + HMAC + tests"
```

---

## Task 5: API Keys Service

**Files:**
- Create: `backend/src/agflow/schemas/api_keys.py`
- Create: `backend/src/agflow/services/api_keys_service.py`
- Test: `backend/tests/test_api_keys_service.py`

- [ ] **Step 1: Write API key schemas**

```python
# backend/src/agflow/schemas/api_keys.py
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)
    rate_limit: int = Field(default=120, ge=1, le=10000)
    expires_in: Literal["3m", "6m", "9m", "12m", "never"] = "12m"


class ApiKeyCreated(BaseModel):
    id: UUID
    name: str
    prefix: str
    full_key: str
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None
    created_at: datetime


class ApiKeySummary(BaseModel):
    id: UUID
    owner_id: UUID | None
    name: str
    prefix: str
    scopes: list[str]
    rate_limit: int
    expires_at: datetime | None
    revoked: bool
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    rate_limit: int | None = Field(default=None, ge=1, le=10000)
```

- [ ] **Step 2: Write API keys service**

```python
# backend/src/agflow/services/api_keys_service.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import structlog

from agflow.auth.api_key import generate_api_key
from agflow.config import get_settings
from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.api_keys import ApiKeyCreated, ApiKeySummary

_log = structlog.get_logger(__name__)

ALL_SCOPES = {
    "*",
    "secrets:read", "secrets:write",
    "dockerfiles:read", "dockerfiles:write", "dockerfiles:delete", "dockerfiles:build",
    "dockerfiles.files:read", "dockerfiles.files:write", "dockerfiles.files:delete",
    "dockerfiles.params:read", "dockerfiles.params:write",
    "discovery:read", "discovery:write",
    "service_types:read", "service_types:write",
    "users:manage",
    "roles:read", "roles:write", "roles:delete",
    "catalogs:read", "catalogs:write",
    "agents:read", "agents:write", "agents:delete", "agents:run",
    "containers:read", "containers:run", "containers:stop",
    "containers.logs:read", "containers.chat:write",
    "keys:manage",
}

_EXPIRY_MAP = {
    "3m": timedelta(days=90),
    "6m": timedelta(days=180),
    "9m": timedelta(days=270),
    "12m": timedelta(days=365),
    "never": None,
}


class ApiKeyNotFoundError(Exception):
    pass


class InvalidScopesError(Exception):
    pass


def compute_expiry(expires_in: str) -> datetime | None:
    delta = _EXPIRY_MAP.get(expires_in)
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta


def validate_key_scopes(
    user_role: str,
    user_scopes: list[str],
    requested_scopes: list[str],
) -> list[str]:
    unknown = [s for s in requested_scopes if s not in ALL_SCOPES]
    if unknown:
        return unknown
    if user_role == "admin":
        return []
    granted = set(user_scopes) | {"keys:manage"}
    return [s for s in requested_scopes if s not in granted]


def _row_to_summary(row: dict[str, Any]) -> ApiKeySummary:
    return ApiKeySummary(**row)


async def create(
    *,
    name: str,
    scopes: list[str],
    rate_limit: int = 120,
    expires_at: datetime | None,
    owner_id: UUID | None,
) -> ApiKeyCreated:
    settings = get_settings()
    full_key, prefix, key_hash = generate_api_key(
        salt=settings.api_key_salt, expires_at=expires_at
    )
    row = await fetch_one(
        """
        INSERT INTO api_keys (owner_id, name, prefix, key_hash, scopes, rate_limit, expires_at)
        VALUES ($1, $2, $3, $4, $5::text[], $6, $7)
        RETURNING id, created_at
        """,
        owner_id,
        name,
        prefix,
        key_hash,
        scopes,
        rate_limit,
        expires_at,
    )
    assert row is not None
    _log.info("api_keys.create", prefix=prefix, name=name)
    return ApiKeyCreated(
        id=row["id"],
        name=name,
        prefix=prefix,
        full_key=full_key,
        scopes=scopes,
        rate_limit=rate_limit,
        expires_at=expires_at,
        created_at=row["created_at"],
    )


async def list_all(owner_id: UUID | None = None) -> list[ApiKeySummary]:
    if owner_id is not None:
        rows = await fetch_all(
            "SELECT * FROM api_keys WHERE owner_id = $1 ORDER BY created_at DESC",
            owner_id,
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM api_keys ORDER BY created_at DESC"
        )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(key_id: UUID) -> ApiKeySummary:
    row = await fetch_one("SELECT * FROM api_keys WHERE id = $1", key_id)
    if row is None:
        raise ApiKeyNotFoundError(f"API key {key_id} not found")
    return _row_to_summary(row)


async def get_by_prefix(prefix: str) -> dict[str, Any] | None:
    return await fetch_one(
        "SELECT * FROM api_keys WHERE prefix = $1", prefix
    )


async def update(
    key_id: UUID,
    name: str | None = None,
    scopes: list[str] | None = None,
    rate_limit: int | None = None,
) -> ApiKeySummary:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    if name is not None:
        sets.append(f"name = ${idx}")
        args.append(name)
        idx += 1
    if scopes is not None:
        sets.append(f"scopes = ${idx}::text[]")
        args.append(scopes)
        idx += 1
    if rate_limit is not None:
        sets.append(f"rate_limit = ${idx}")
        args.append(rate_limit)
        idx += 1
    if not sets:
        return await get_by_id(key_id)
    args.append(key_id)
    row = await fetch_one(
        f"UPDATE api_keys SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
        *args,
    )
    if row is None:
        raise ApiKeyNotFoundError(f"API key {key_id} not found")
    _log.info("api_keys.update", key_id=str(key_id))
    return _row_to_summary(row)


async def revoke(key_id: UUID) -> None:
    row = await fetch_one(
        "UPDATE api_keys SET revoked = TRUE WHERE id = $1 RETURNING id",
        key_id,
    )
    if row is None:
        raise ApiKeyNotFoundError(f"API key {key_id} not found")
    _log.info("api_keys.revoke", key_id=str(key_id))


async def update_last_used(key_id: UUID) -> None:
    await execute(
        "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1", key_id
    )
```

- [ ] **Step 3: Write tests**

```python
# backend/tests/test_api_keys_service.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.68:5432/agflow_test"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")
os.environ.setdefault("API_KEY_SALT", "test-salt-for-hmac-32chars-ok!!")

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.services import api_keys_service, users_service

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS api_keys CASCADE")
    await execute("DROP TABLE IF EXISTS user_identities CASCADE")
    await execute("DROP TABLE IF EXISTS users CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    await users_service.create(email="admin@test.com", role="admin", status="active")
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    admin = await users_service.get_by_email("admin@test.com")
    assert admin is not None
    created = await api_keys_service.create(
        name="Test key",
        scopes=["dockerfiles:read"],
        owner_id=admin.id,
        expires_at=None,
    )
    assert created.full_key.startswith("agfd_")
    assert len(created.full_key) == 53

    keys = await api_keys_service.list_all()
    assert len(keys) == 1
    assert keys[0].prefix == created.prefix
    assert keys[0].name == "Test key"


@pytest.mark.asyncio
async def test_revoke_key() -> None:
    admin = await users_service.get_by_email("admin@test.com")
    assert admin is not None
    created = await api_keys_service.create(
        name="Revoke me", scopes=[], owner_id=admin.id, expires_at=None
    )
    await api_keys_service.revoke(created.id)
    summary = await api_keys_service.get_by_id(created.id)
    assert summary.revoked is True


@pytest.mark.asyncio
async def test_validate_key_scopes_admin() -> None:
    rejected = api_keys_service.validate_key_scopes("admin", [], ["*", "dockerfiles:write"])
    assert rejected == []


@pytest.mark.asyncio
async def test_validate_key_scopes_user() -> None:
    rejected = api_keys_service.validate_key_scopes(
        "user", ["agents:read", "agents:run"], ["agents:read", "agents:write"]
    )
    assert rejected == ["agents:write"]


@pytest.mark.asyncio
async def test_keys_manage_always_implicit() -> None:
    rejected = api_keys_service.validate_key_scopes(
        "user", ["agents:read"], ["keys:manage"]
    )
    assert rejected == []
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_api_keys_service.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/schemas/api_keys.py backend/src/agflow/services/api_keys_service.py \
       backend/tests/test_api_keys_service.py
git commit -m "feat: API keys service with CRUD + scope validation + tests"
```

---

## Task 6: Admin Endpoints — Users + API Keys

**Files:**
- Create: `backend/src/agflow/api/admin/users.py`
- Create: `backend/src/agflow/api/admin/api_keys.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Write users admin router**

Following the pattern of existing admin routers (`agents.py`, `dockerfiles.py`): prefix `/api/admin/users`, dependency `require_admin`, standard CRUD + approve/disable/enable actions.

(Full code in spec section 7.1 — implement all 8 routes)

- [ ] **Step 2: Write api_keys admin router**

Prefix `/api/admin/api-keys`, dependency `require_admin`, 5 routes: POST create, GET list, GET detail, PATCH update, DELETE revoke.

The POST endpoint returns `ApiKeyCreated` (with `full_key`) and must call `validate_key_scopes()` before inserting.

- [ ] **Step 3: Register routers in main.py**

Add imports + `app.include_router(...)` for both routers.

- [ ] **Step 4: Add admin seed in lifespan**

In the `lifespan` function of `main.py`, after `configure_logging`:

```python
from agflow.services import users_service
await users_service.seed_admin(settings.admin_email)
```

- [ ] **Step 5: Import check**

Run: `cd backend && uv run python -c "from agflow.main import create_app; app = create_app(); print('OK', len(app.routes), 'routes')"`
Expected: route count increases by ~13

- [ ] **Step 6: Commit**

```bash
git add backend/src/agflow/api/admin/users.py backend/src/agflow/api/admin/api_keys.py \
       backend/src/agflow/main.py
git commit -m "feat: admin endpoints for users CRUD + API keys CRUD + admin seed"
```

---

## Task 7: API Key Auth Middleware + Rate Limiting

**Files:**
- Modify: `backend/src/agflow/auth/api_key.py` (add `require_api_key` dependency)
- Modify: `backend/src/agflow/auth/dependencies.py` (add `require_auth`)

- [ ] **Step 1: Add require_api_key FastAPI dependency**

Add to `api_key.py` the 3-level validation dependency as specified in spec section 4.1. Uses:
- `parse_api_key()` + `verify_hmac()` + `is_expired()` for level 1
- `api_keys_service.get_by_prefix()` + `verify_bcrypt()` for level 2
- Redis INCR + TTL for level 3

- [ ] **Step 2: Add require_auth dual dependency**

In `dependencies.py`, add a new dependency that accepts both JWT and API key based on prefix detection (`agfd_` → API key, else → JWT).

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/auth/api_key.py backend/src/agflow/auth/dependencies.py
git commit -m "feat: require_api_key middleware with 3-level validation + rate limit"
```

---

## Task 8: Frontend — API Clients + Hooks

**Files:**
- Create: `frontend/src/lib/usersApi.ts`
- Create: `frontend/src/lib/apiKeysApi.ts`
- Create: `frontend/src/hooks/useUsers.ts`
- Create: `frontend/src/hooks/useApiKeys.ts`

- [ ] **Step 1: Write users API client + hook**

Standard pattern: axios client + React Query hook with `useMutation` for CRUD actions.

- [ ] **Step 2: Write api keys API client + hook**

Same pattern. `create` mutation returns the `full_key` which must be displayed once.

- [ ] **Step 3: Verify TypeScript**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/usersApi.ts frontend/src/lib/apiKeysApi.ts \
       frontend/src/hooks/useUsers.ts frontend/src/hooks/useApiKeys.ts
git commit -m "feat(frontend): users + API keys API clients and React Query hooks"
```

---

## Task 9: Frontend — Users Page

**Files:**
- Create: `frontend/src/pages/UsersPage.tsx`

- [ ] **Step 1: Build UsersPage**

Table with columns: Avatar, Name, Email, Role (badge), Scopes (badge count), Status (badge), API Keys, Last login, Actions.
- Pending users at top (amber background)
- Actions: Approve, Disable/Enable, Change role, Scopes dialog (checkboxes grid), Delete (with confirmation)
- "Profil standard" shortcut button in scopes dialog
- Create user dialog (invitation by admin)

- [ ] **Step 2: Add i18n keys (fr + en)**

All labels, buttons, messages for the users page.

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/UsersPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): admin users page with CRUD + scopes grid"
```

---

## Task 10: Frontend — API Keys Page

**Files:**
- Create: `frontend/src/pages/ApiKeysPage.tsx`

- [ ] **Step 1: Build ApiKeysPage**

Table: Name, Prefix, Scopes (badges), Rate limit, Expires, Last used, Status, Actions.
- Create dialog: name, scopes (checkboxes), rate limit, expiration (dropdown)
- After creation: modal showing full key + copy button + warning "never shown again"
- Edit dialog: name, scopes, rate limit (expiration not editable)
- Revoke with confirmation

- [ ] **Step 2: Add i18n keys (fr + en)**

- [ ] **Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ApiKeysPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): admin API keys page with CRUD + token reveal dialog"
```

---

## Task 11: Frontend — Sidebar + Routes

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Add routes to App.tsx**

```tsx
<Route path="/users" element={<ProtectedRoute><UsersPage /></ProtectedRoute>} />
<Route path="/api-keys" element={<ProtectedRoute><ApiKeysPage /></ProtectedRoute>} />
```

- [ ] **Step 2: Add sidebar entries**

In the "Plateforme" section of `Sidebar.tsx`, add:
- "Utilisateurs" → `/users` → `Users` icon
- "API Keys" → `/api-keys` → `Key` icon

- [ ] **Step 3: Verify + test**

Run: `cd frontend && npx tsc --noEmit && npm test -- --run`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(frontend): sidebar + routes for Users and API Keys pages"
```

---

## Task 12: Deploy + Smoke Test

- [ ] **Step 1: Generate API_KEY_SALT on LXC**

```bash
ssh pve "pct exec 201 -- bash -c 'echo API_KEY_SALT=$(python3 -c \"import secrets; print(secrets.token_hex(32))\") >> /root/agflow.docker/.env'"
```

- [ ] **Step 2: Deploy**

```bash
./scripts/deploy.sh --rebuild
```

- [ ] **Step 3: Verify migrations applied**

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c \"SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 5;\""
```
Expected: 022_users, 023_user_identities, 024_seed_admin_user, 025_api_keys

- [ ] **Step 4: Verify admin was seeded**

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c \"SELECT email, role, status FROM users;\""
```
Expected: admin@... / admin / active

- [ ] **Step 5: Smoke test from browser**

1. Open `http://192.168.10.68/users` → see admin user in list
2. Open `http://192.168.10.68/api-keys` → empty list
3. Create a new API key → copy the token
4. Test with curl:
```bash
curl -H "Authorization: Bearer agfd_xxx..." http://192.168.10.68/api/v1/dockerfiles
```
(Will fail with 404 since public endpoints aren't built yet — but the auth middleware should parse the key. That's the next spec.)

- [ ] **Step 6: Commit any remaining changes**

```bash
git add -A && git commit -m "chore: deploy config for users + API keys"
```
