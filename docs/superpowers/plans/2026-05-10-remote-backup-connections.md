# Remote Backup Connections — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à un admin de déclarer des connexions distantes (SFTP, S3, FTPS), tester la connexion, et pousser des backups DB vers ces destinations, avec credentials zéro-knowledge via Harpocrate.

**Architecture:** Service `remote_backup_connections_service` orchestre le CRUD avec credentials délégués à Harpocrate via `vault_client.py` existant (valeur JSON sérialisée). Abstraction Provider stateless par kind (SFTP/S3/FTPS). Service `local_backups_service` stream `db_backup.stream_dump()` vers disque. Worker async périodique déclenche le push automatique. UI React avec modal création/édition et bouton test inline.

**Tech Stack:** FastAPI + asyncpg (`fetch_one/fetch_all/execute` de `db/pool.py`) + asyncssh (SFTP, déjà en dep) + aioftp (FTPS, à ajouter) + boto3 (S3 sync via `asyncio.to_thread`, à ajouter) + SDK Harpocrate local (`backend/secrets/`) + React 18 / TanStack Query / shadcn + i18next.

**Contexte existant critique :**
- `vault_client.py` : `get_secret(name)→str`, `create_secret(name, value, desc?)→str`, `update_secret(name, value)→None`, `delete_secret(name)→None`. Le nom supporte les paths-style (`remote-backups/uuid` → résolu via listing). Valeurs = strings → JSON-sérialiser les dicts credentials.
- `db_backup.stream_dump()` : `AsyncIterator[bytes]`, flux `pg_dump | gzip` depuis le container postgres.
- `set_updated_at()` : fonction trigger SQL existante (voir migration 001).
- Dernière migration : `102_runtime_config_kv_and_named_type_rules.sql` → prochaine : `103`.
- Worker pattern : `async def run_xxx_loop(stop_event: asyncio.Event)` enregistré dans `main.py` lifespan.
- Auth admin : `Depends(require_admin)` sur tous les routers `/api/admin/*`.

---

## File Structure

```
backend/
  pyproject.toml                                  MODIFY  add aioftp, boto3
  migrations/
    103_remote_backups.sql                        CREATE
  src/agflow/
    config.py                                     MODIFY  add agflow_data_dir, harpocrate_vault_api_key_id
    schemas/
      remote_backup_connections.py                CREATE  DTOs Pydantic (Connection, CreateReq, UpdateReq, TestReq, TestResult)
      local_backups.py                            CREATE  DTOs Pydantic (LocalBackup)
    services/
      remote_backup_connections_service.py        CREATE  CRUD + vault
      local_backups_service.py                    CREATE  create (dump→disk) + list + get
      system_anomaly_service.py                   CREATE  create (avec hystérésis) + list + ack
      backup_lock.py                              CREATE  asyncio.Lock singleton partagé
      remote_backup_providers/
        __init__.py                               CREATE
        protocol.py                               CREATE  RemoteBackupProvider Protocol + RemoteBackupProviderError
        sftp_provider.py                          CREATE  SftpProvider
        ftps_provider.py                          CREATE  FtpsProvider
        s3_provider.py                            CREATE  S3CompatibleProvider
        factory.py                                CREATE  get_provider(kind, config, credentials)
    api/admin/
      remote_backup_connections.py                CREATE  router /api/admin/backup-remotes
      local_backups.py                            CREATE  router /api/admin/local-backups
    workers/
      remote_backup_pusher.py                     CREATE  async loop
    main.py                                       MODIFY  add worker (5e stop event + task)

frontend/src/
  pages/RemoteBackupConnectionsPage.tsx           CREATE
  i18n/fr.json                                   MODIFY  add keys
  i18n/en.json                                   MODIFY  add keys

tests/
  services/
    test_remote_backup_connections.py             CREATE
    test_remote_backup_providers.py              CREATE
    test_system_anomaly_service.py               CREATE
  api/
    test_remote_backup_connections_api.py        CREATE
```

---

## LOT 1 — Migration + Dépendances + Config

### Task 1.1 : Dépendances et config

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/agflow/config.py`

- [ ] **Step 1 : Ajouter aioftp et boto3 dans pyproject.toml**

Dans la liste `dependencies`, ajouter après `asyncssh>=2.14` :
```toml
    "aioftp>=0.22",
    "boto3>=1.35",
```

- [ ] **Step 2 : Ajouter les settings dans config.py**

Dans la classe `Settings`, ajouter après `harpocrate_url` :
```python
    harpocrate_vault_api_key_id: str = "default"
    agflow_data_dir: str = "/app/data"
```

- [ ] **Step 1b : Documenter les nouvelles vars dans `.env.example`**

Ajouter à la fin de `.env.example` :
```bash
# ─── Remote Backups ───
# Identifiant de l'API key Harpocrate utilisée pour les connexions distantes.
HARPOCRATE_VAULT_API_KEY_ID=default
```

- [ ] **Step 3 : Synchroniser les dépendances**

```bash
cd backend && uv sync
```

Attendu : résolution sans erreur, `aioftp` et `boto3` apparaissent dans le lock.

- [ ] **Step 4 : Vérifier que le backend démarre toujours**

```bash
cd backend && uv run python -c "from agflow.config import get_settings; s = get_settings(); print(s.agflow_data_dir)"
```

Attendu : `/app/data`

- [ ] **Step 5 : Commit**

```bash
git add backend/pyproject.toml backend/src/agflow/config.py
git commit -m "feat(remote-backups): add aioftp, boto3 deps + agflow_data_dir, vault_api_key_id settings"
```

---

### Task 1.2 : Migration SQL 103

**Files:**
- Create: `backend/migrations/103_remote_backups.sql`

- [ ] **Step 1 : Écrire la migration**

```sql
-- 103 — remote_backup_connections, local_backups, system_anomaly_events

-- ─── remote_backup_connections ─────────────────────────────────────────────

CREATE TABLE remote_backup_connections (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT        NOT NULL,
    kind                TEXT        NOT NULL CHECK (kind IN ('sftp', 's3', 'ftps')),
    config              JSONB       NOT NULL DEFAULT '{}',
    vault_api_key_id    TEXT,
    vault_secret_path   TEXT,
    CONSTRAINT rbc_vault_both_or_none CHECK (
        (vault_api_key_id IS NULL) = (vault_secret_path IS NULL)
    ),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    deleted_at          TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_rbc_name_active
    ON remote_backup_connections(lower(name))
    WHERE deleted_at IS NULL;

CREATE INDEX idx_rbc_deleted ON remote_backup_connections(deleted_at);

CREATE TRIGGER trg_rbc_updated_at
    BEFORE UPDATE ON remote_backup_connections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── local_backups ─────────────────────────────────────────────────────────

CREATE TABLE local_backups (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    filename            TEXT        NOT NULL,
    file_path           TEXT        NOT NULL,
    size_bytes          BIGINT,
    status              TEXT        NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('in_progress', 'completed', 'failed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_local_backups_created ON local_backups(created_at DESC);

-- ─── system_anomaly_events ─────────────────────────────────────────────────

CREATE TABLE system_anomaly_events (
    id                          BIGSERIAL   PRIMARY KEY,
    detected_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity                    TEXT        NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    anomaly_type                TEXT        NOT NULL,
    source                      TEXT        NOT NULL,
    source_ref_id               UUID,
    message                     TEXT        NOT NULL,
    metadata                    JSONB       NOT NULL DEFAULT '{}',
    acknowledged_at             TIMESTAMPTZ,
    acknowledged_by_user_id     UUID        REFERENCES users(id) ON DELETE SET NULL
);

-- query principale UI : anomalies non-ack, les plus récentes en premier
CREATE INDEX idx_sae_pending
    ON system_anomaly_events(detected_at DESC)
    WHERE acknowledged_at IS NULL;

-- hystérésis : vérifier unicité (source, source_ref_id) avant insertion
CREATE INDEX idx_sae_source ON system_anomaly_events(source, source_ref_id);
```

- [ ] **Step 2 : Appliquer la migration**

```bash
cd backend && uv run python -m agflow.db.migrations
```

Attendu : `Applied migration 103_remote_backups.sql`

- [ ] **Step 3 : Vérifier les tables dans pgweb**

Ouvrir http://192.168.10.154:8081/ → vérifier `remote_backup_connections`, `local_backups`, `system_anomaly_events`.

- [ ] **Step 4 : Commit**

```bash
git add backend/migrations/103_remote_backups.sql
git commit -m "feat(remote-backups): migration 103 — remote_backup_connections, local_backups, system_anomaly_events"
```

---

## LOT 2 — Service remote_backup_connections + Schémas

### Task 2.1 : Schémas Pydantic

**Files:**
- Create: `backend/src/agflow/schemas/remote_backup_connections.py`

- [ ] **Step 1 : Écrire le fichier de schémas**

```python
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator


class RemoteBackupConnectionSummary(BaseModel):
    id: UUID
    name: str
    kind: str  # 'sftp' | 's3' | 'ftps'
    config: dict[str, Any]
    has_credentials: bool
    created_at: datetime
    updated_at: datetime


class RemoteBackupConnectionCreate(BaseModel):
    name: str
    kind: str
    config: dict[str, Any] = {}
    credentials: dict[str, Any] | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in ("sftp", "s3", "ftps"):
            raise ValueError("kind must be one of: sftp, s3, ftps")
        return v


class RemoteBackupConnectionUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class TestConnectionRequest(BaseModel):
    """Pour POST /backup-remotes/test (creds non sauvegardés)."""
    kind: str
    config: dict[str, Any]
    credentials: dict[str, Any]
    path: str  # remote_path SFTP/FTPS ou prefix S3


class TestConnectionWithIdRequest(BaseModel):
    """Pour POST /backup-remotes/{id}/test (creds en vault)."""
    path: str
    config: dict[str, Any] | None = None  # override partiel


class TestConnectionResult(BaseModel):
    ok: bool
    error: str | None = None
    message: str | None = None
```

- [ ] **Step 2 : Écrire le schéma local_backups**

```python
# backend/src/agflow/schemas/local_backups.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LocalBackupSummary(BaseModel):
    id: UUID
    filename: str
    size_bytes: int | None
    status: str
    created_at: datetime
```

- [ ] **Step 3 : Commit**

```bash
git add backend/src/agflow/schemas/remote_backup_connections.py backend/src/agflow/schemas/local_backups.py
git commit -m "feat(remote-backups): schémas Pydantic RemoteBackupConnection + LocalBackup"
```

---

### Task 2.2 : Tests du service remote_backup_connections

**Files:**
- Create: `tests/services/test_remote_backup_connections.py`

- [ ] **Step 1 : Écrire les tests (vault mocké)**

```python
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Helpers pour mocker la DB
async def _one(query, *args):
    return None
async def _all(query, *args):
    return []
async def _exec(query, *args):
    return "INSERT 0 1"


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    return conn


@pytest.mark.asyncio
async def test_create_connection_stores_creds_in_vault(mock_conn):
    """create_connection appelle vault_client.create_secret avec json.dumps(credentials)."""
    from agflow.services import remote_backup_connections_service as svc

    credentials = {"username": "user", "auth_method": "password", "password": "s3cr3t"}
    connection_id = uuid4()

    with (
        patch.object(svc, "_insert_row", AsyncMock(return_value=connection_id)),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
        patch("agflow.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.harpocrate_vault_api_key_id = "default"
        mock_vault.create_secret = AsyncMock(return_value="secret-uuid")

        result = await svc.create_connection(
            conn=mock_conn,
            name="sftp-prod",
            kind="sftp",
            config={"host": "sftp.example.com", "port": 22},
            credentials=credentials,
        )

    mock_vault.create_secret.assert_called_once()
    call_args = mock_vault.create_secret.call_args
    assert call_args.args[0] == f"remote-backups/{result}"
    stored = json.loads(call_args.args[1])
    assert stored["password"] == "s3cr3t"


@pytest.mark.asyncio
async def test_create_connection_rolls_back_vault_on_db_failure(mock_conn):
    """Si l'insert DB échoue après vault.create_secret, delete_secret est appelé."""
    from agflow.services import remote_backup_connections_service as svc

    with (
        patch.object(svc, "_insert_row", AsyncMock(side_effect=Exception("DB down"))),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
        patch("agflow.config.get_settings") as mock_settings,
    ):
        mock_settings.return_value.harpocrate_vault_api_key_id = "default"
        mock_vault.create_secret = AsyncMock(return_value="secret-uuid")
        mock_vault.delete_secret = AsyncMock()

        with pytest.raises(Exception, match="DB down"):
            await svc.create_connection(
                conn=mock_conn,
                name="sftp-prod",
                kind="sftp",
                config={},
                credentials={"username": "u", "password": "p"},
            )

    mock_vault.delete_secret.assert_called_once()


@pytest.mark.asyncio
async def test_list_connections_never_calls_vault(mock_conn):
    """list_connections ne doit PAS appeler vault_client."""
    from agflow.services import remote_backup_connections_service as svc

    with (
        patch.object(svc, "_fetch_all_rows", AsyncMock(return_value=[])),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
    ):
        await svc.list_connections(mock_conn)
        mock_vault.get_secret.assert_not_called()


@pytest.mark.asyncio
async def test_delete_connection_soft_deletes_then_removes_vault(mock_conn):
    """delete_connection soft-delete DB en premier, puis delete_secret best-effort."""
    from agflow.services import remote_backup_connections_service as svc

    conn_id = uuid4()
    row = {
        "id": conn_id, "name": "test", "kind": "sftp", "config": {},
        "vault_api_key_id": "default", "vault_secret_path": f"remote-backups/{conn_id}",
        "has_credentials": True, "created_at": None, "updated_at": None,
    }

    with (
        patch.object(svc, "_fetch_row_by_id", AsyncMock(return_value=row)),
        patch.object(svc, "_soft_delete_row", AsyncMock()),
        patch("agflow.services.remote_backup_connections_service.vault_client") as mock_vault,
    ):
        mock_vault.delete_secret = AsyncMock()
        await svc.delete_connection(mock_conn, conn_id)

    mock_vault.delete_secret.assert_called_once_with(f"remote-backups/{conn_id}")
```

- [ ] **Step 2 : Vérifier que les tests échouent (service pas encore écrit)**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_connections.py -v
```

Attendu : `ImportError` ou `ModuleNotFoundError` sur `remote_backup_connections_service`.

---

### Task 2.3 : Implémenter remote_backup_connections_service

**Files:**
- Create: `backend/src/agflow/services/remote_backup_connections_service.py`

- [ ] **Step 1 : Écrire le service**

```python
from __future__ import annotations

import json
from uuid import UUID, uuid4

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.remote_backup_connections import RemoteBackupConnectionSummary
from agflow.services import vault_client

_log = structlog.get_logger(__name__)

# ─── helpers DB internes (facilement mockables dans les tests) ─────────────

async def _insert_row(conn, *, connection_id: UUID, name: str, kind: str,
                      config: dict, vault_api_key_id: str | None,
                      vault_secret_path: str | None,
                      created_by_user_id: UUID | None) -> None:
    await execute(
        """
        INSERT INTO remote_backup_connections
            (id, name, kind, config, vault_api_key_id, vault_secret_path, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        connection_id, name, kind, json.dumps(config),
        vault_api_key_id, vault_secret_path, created_by_user_id,
    )


async def _fetch_all_rows(conn) -> list[dict]:
    return await fetch_all(
        "SELECT id, name, kind, config, vault_api_key_id, vault_secret_path, "
        "       created_at, updated_at, "
        "       (vault_secret_path IS NOT NULL) AS has_credentials "
        "FROM remote_backup_connections "
        "WHERE deleted_at IS NULL ORDER BY name"
    )


async def _fetch_row_by_id(conn, connection_id: UUID) -> dict | None:
    return await fetch_one(
        "SELECT id, name, kind, config, vault_api_key_id, vault_secret_path, "
        "       created_at, updated_at, "
        "       (vault_secret_path IS NOT NULL) AS has_credentials "
        "FROM remote_backup_connections "
        "WHERE id = $1 AND deleted_at IS NULL",
        connection_id,
    )


async def _soft_delete_row(conn, connection_id: UUID) -> None:
    await execute(
        "UPDATE remote_backup_connections SET deleted_at = NOW() WHERE id = $1",
        connection_id,
    )


def _to_dto(row: dict) -> RemoteBackupConnectionSummary:
    return RemoteBackupConnectionSummary(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        config=row["config"] if isinstance(row["config"], dict) else json.loads(row["config"]),
        has_credentials=row["has_credentials"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ─── API publique ──────────────────────────────────────────────────────────

async def list_connections(conn) -> list[RemoteBackupConnectionSummary]:
    rows = await _fetch_all_rows(conn)
    return [_to_dto(r) for r in rows]


async def get_connection(conn, connection_id: UUID) -> RemoteBackupConnectionSummary | None:
    row = await _fetch_row_by_id(conn, connection_id)
    return _to_dto(row) if row else None


async def fetch_credentials(connection: RemoteBackupConnectionSummary) -> dict | None:
    """Lit les credentials depuis Harpocrate. NE PAS appeler dans les listings."""
    if not connection.has_credentials:
        return None
    # Le path est déterministe depuis l'ID — pas besoin de le stocker dans le DTO.
    path = f"remote-backups/{connection.id}"
    raw = await vault_client.get_secret(path)
    return json.loads(raw)


async def create_connection(
    conn,
    *,
    name: str,
    kind: str,
    config: dict,
    credentials: dict | None,
    created_by_user_id: UUID | None = None,
) -> UUID:
    settings = get_settings()
    connection_id = uuid4()
    vault_api_key_id: str | None = None
    vault_secret_path: str | None = None

    if credentials:
        path = f"remote-backups/{connection_id}"
        await vault_client.create_secret(path, json.dumps(credentials))
        vault_api_key_id = settings.harpocrate_vault_api_key_id
        vault_secret_path = path

    try:
        await _insert_row(
            conn,
            connection_id=connection_id,
            name=name, kind=kind, config=config,
            vault_api_key_id=vault_api_key_id,
            vault_secret_path=vault_secret_path,
            created_by_user_id=created_by_user_id,
        )
    except Exception:
        if vault_secret_path:
            try:
                await vault_client.delete_secret(vault_secret_path)
            except Exception as cleanup_err:
                _log.warning("rbc.vault_cleanup_failed", path=vault_secret_path, error=str(cleanup_err))
        raise

    _log.info("rbc.created", connection_id=str(connection_id), kind=kind)
    return connection_id


async def update_connection(
    conn,
    connection_id: UUID,
    *,
    name: str | None = None,
    config: dict | None = None,
    credentials: dict | None = None,
) -> None:
    row = await _fetch_row_by_id(conn, connection_id)
    if row is None:
        raise ValueError(f"Connection {connection_id} not found")

    if credentials is not None and row["vault_secret_path"]:
        await vault_client.update_secret(row["vault_secret_path"], json.dumps(credentials))
    elif credentials is not None:
        settings = get_settings()
        path = f"remote-backups/{connection_id}"
        await vault_client.create_secret(path, json.dumps(credentials))
        await execute(
            "UPDATE remote_backup_connections SET vault_api_key_id=$1, vault_secret_path=$2 WHERE id=$3",
            settings.harpocrate_vault_api_key_id, path, connection_id,
        )

    updates: list[str] = []
    params: list = []
    idx = 1
    if name is not None:
        updates.append(f"name = ${idx}"); params.append(name); idx += 1
    if config is not None:
        updates.append(f"config = ${idx}"); params.append(json.dumps(config)); idx += 1
    if updates:
        params.append(connection_id)
        await execute(
            f"UPDATE remote_backup_connections SET {', '.join(updates)} WHERE id = ${idx}",
            *params,
        )


async def delete_connection(conn, connection_id: UUID) -> None:
    row = await _fetch_row_by_id(conn, connection_id)
    if row is None:
        return
    await _soft_delete_row(conn, connection_id)
    if row["vault_secret_path"]:
        try:
            await vault_client.delete_secret(row["vault_secret_path"])
        except Exception as exc:
            _log.warning("rbc.vault_delete_failed",
                         path=row["vault_secret_path"], error=str(exc),
                         note="secret orphan in vault — cleanup manually")


def resolve_remote_path(config: dict, kind: str, usage: str) -> str | None:
    """Retourne le path côté serveur (SFTP/S3) selon kind et usage (snapshots|full)."""
    if kind in ("sftp", "ftps"):
        key = "remote_path_snapshots" if usage == "snapshots" else "remote_path_full"
    else:  # s3
        key = "prefix_snapshots" if usage == "snapshots" else "prefix_full"
    return config.get(key) or None
```

- [ ] **Step 2 : Lancer les tests**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_connections.py -v
```

Attendu : 4 tests PASS.

- [ ] **Step 3 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/remote_backup_connections_service.py
```

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_connections_service.py \
        tests/services/test_remote_backup_connections.py
git commit -m "feat(remote-backups): service CRUD remote_backup_connections avec vault zéro-knowledge"
```

---

## LOT 3 — Provider Abstraction + SFTP + S3 + FTPS

### Task 3.1 : Protocol + erreur commune

**Files:**
- Create: `backend/src/agflow/services/remote_backup_providers/protocol.py`
- Create: `backend/src/agflow/services/remote_backup_providers/__init__.py`

- [ ] **Step 1 : Écrire le Protocol**

```python
# protocol.py
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


class RemoteBackupProviderError(Exception):
    """Erreur provider remote backup — propagée en 422 par les endpoints."""


@runtime_checkable
class RemoteBackupProvider(Protocol):
    async def test_connection(self, path: str) -> None:
        """Teste que le path est accessible. Lève RemoteBackupProviderError si KO."""
        ...

    async def upload_stream(
        self,
        path: str,
        filename: str,
        source: AsyncIterator[bytes],
    ) -> int:
        """Upload le stream vers path/filename. Retourne le nombre de bytes écrits."""
        ...
```

```python
# __init__.py
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
)

__all__ = ["RemoteBackupProvider", "RemoteBackupProviderError"]
```

---

### Task 3.2 : SftpProvider (asyncssh)

**Files:**
- Create: `backend/src/agflow/services/remote_backup_providers/sftp_provider.py`
- Create: `tests/services/test_remote_backup_providers.py` (SFTP section)

- [ ] **Step 1 : Écrire le test SFTP (mock asyncssh)**

```python
# tests/services/test_remote_backup_providers.py
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services.remote_backup_providers import RemoteBackupProviderError


# ─── SFTP ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sftp_test_connection_success():
    from agflow.services.remote_backup_providers.sftp_provider import SftpProvider

    mock_sftp = AsyncMock()
    mock_sftp.stat = AsyncMock(return_value=MagicMock())

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.start_client = AsyncMock()

    mock_sftp_ctx = MagicMock()
    mock_sftp_ctx.__aenter__ = AsyncMock(return_value=mock_sftp)
    mock_sftp_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.start_sftp_client = MagicMock(return_value=mock_sftp_ctx)

    config = {"host": "sftp.example.com", "port": 22}
    creds = {"username": "user", "auth_method": "password", "password": "secret"}
    provider = SftpProvider(config=config, credentials=creds)

    with patch("asyncssh.connect", AsyncMock(return_value=mock_conn)):
        await provider.test_connection("/backups")

    mock_sftp.stat.assert_called_once()


@pytest.mark.asyncio
async def test_sftp_upload_stream_creates_parent_dirs():
    from agflow.services.remote_backup_providers.sftp_provider import SftpProvider

    mock_sftp = AsyncMock()
    mock_sftp.stat = AsyncMock(side_effect=OSError("not found"))
    mock_sftp.makedirs = AsyncMock()
    mock_sftp.realpath = AsyncMock(return_value="/")

    mock_file = MagicMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=False)
    mock_file.write = AsyncMock()
    mock_sftp.open = AsyncMock(return_value=mock_file)

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_sftp_ctx = MagicMock()
    mock_sftp_ctx.__aenter__ = AsyncMock(return_value=mock_sftp)
    mock_sftp_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.start_sftp_client = MagicMock(return_value=mock_sftp_ctx)

    async def _source():
        yield b"chunk1"
        yield b"chunk2"

    config = {"host": "sftp.example.com", "port": 22}
    creds = {"username": "user", "auth_method": "password", "password": "s"}
    provider = SftpProvider(config=config, credentials=creds)

    with patch("asyncssh.connect", AsyncMock(return_value=mock_conn)):
        n = await provider.upload_stream("/backups", "dump.sql.gz", _source())

    assert n == len(b"chunk1") + len(b"chunk2")
    mock_sftp.makedirs.assert_called_once_with("/backups", exist_ok=True)
```

- [ ] **Step 2 : Lancer les tests pour vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers.py::test_sftp_test_connection_success -v
```

Attendu : `ImportError` ou `ModuleNotFoundError`.

- [ ] **Step 3 : Implémenter SftpProvider**

```python
# sftp_provider.py
from __future__ import annotations

from collections.abc import AsyncIterator

import asyncssh
import structlog

from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_log = structlog.get_logger(__name__)
_CHUNK = 64 * 1024


class SftpProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._host: str = config["host"]
        self._port: int = int(config.get("port", 22))
        self._fingerprint: str | None = config.get("host_key_fingerprint")
        self._username: str = credentials.get("username", "")
        self._password: str | None = credentials.get("password")
        self._known_hosts = None if not self._fingerprint else asyncssh.import_known_hosts(
            f"{self._host} {self._fingerprint}"
        )

    def _connect_kwargs(self) -> dict:
        kw: dict = {
            "host": self._host, "port": self._port,
            "username": self._username,
            "known_hosts": self._known_hosts,
        }
        if self._password:
            kw["password"] = self._password
        return kw

    async def _ensure_path(self, sftp, path: str) -> None:
        try:
            await sftp.stat(path)
            return
        except (OSError, asyncssh.Error):
            pass
        try:
            await sftp.makedirs(path, exist_ok=True)
        except (OSError, asyncssh.Error) as exc:
            cwd = await sftp.realpath(".")
            raise RemoteBackupProviderError(
                f"SFTP cannot prepare path={path!r}: {exc}. "
                f"User home (after login) is {cwd!r}."
            ) from exc

    async def test_connection(self, path: str) -> None:
        try:
            async with asyncssh.connect(**self._connect_kwargs()) as conn:
                async with conn.start_sftp_client() as sftp:
                    await self._ensure_path(sftp, path)
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"SFTP test failed: {exc}") from exc

    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int:
        if "/" in filename or "\\" in filename:
            raise ValueError("filename must not contain path separators")
        try:
            async with asyncssh.connect(**self._connect_kwargs()) as conn:
                async with conn.start_sftp_client() as sftp:
                    await self._ensure_path(sftp, path)
                    remote_file = f"{path.rstrip('/')}/{filename}"
                    written = 0
                    async with sftp.open(remote_file, "wb") as f:
                        async for chunk in source:
                            await f.write(chunk)
                            written += len(chunk)
            _log.info("sftp.upload_done", path=remote_file, bytes=written)
            return written
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"SFTP upload failed: {exc}") from exc
```

- [ ] **Step 4 : Tests PASS**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers.py -k "sftp" -v
```

Attendu : 2 tests PASS.

---

### Task 3.3 : FtpsProvider (aioftp)

**Files:**
- Create: `backend/src/agflow/services/remote_backup_providers/ftps_provider.py`

- [ ] **Step 1 : Ajouter le test FTPS dans test_remote_backup_providers.py**

```python
@pytest.mark.asyncio
async def test_ftps_upload_stream_success():
    from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.login = AsyncMock()
    mock_client.upload_stream = AsyncMock()
    mock_client.make_directory = AsyncMock()

    async def _source():
        yield b"data"

    config = {"host": "ftp.example.com", "port": 21, "use_tls": True, "remote_path_full": "/backups"}
    creds = {"username": "user", "password": "pass"}
    provider = FtpsProvider(config=config, credentials=creds)

    with patch("aioftp.Client", return_value=mock_client):
        await provider.upload_stream("/backups", "dump.sql.gz", _source())

    mock_client.upload_stream.assert_called_once()
```

- [ ] **Step 2 : Implémenter FtpsProvider**

```python
# ftps_provider.py
from __future__ import annotations

import ssl
from collections.abc import AsyncIterator

import aioftp
import structlog

from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_log = structlog.get_logger(__name__)


class FtpsProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._host: str = config["host"]
        self._port: int = int(config.get("port", 21))
        self._use_tls: bool = config.get("use_tls", True)
        self._username: str = credentials.get("username", "")
        self._password: str = credentials.get("password", "")

    def _ssl_context(self) -> ssl.SSLContext | None:
        if not self._use_tls:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def test_connection(self, path: str) -> None:
        try:
            async with aioftp.Client.context(
                self._host, port=self._port, ssl=self._ssl_context()
            ) as client:
                await client.login(self._username, self._password)
                await client.make_directory(path, parents=True)
        except Exception as exc:
            raise RemoteBackupProviderError(f"FTPS test failed: {exc}") from exc

    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int:
        if "/" in filename or "\\" in filename:
            raise ValueError("filename must not contain path separators")
        try:
            async with aioftp.Client.context(
                self._host, port=self._port, ssl=self._ssl_context()
            ) as client:
                await client.login(self._username, self._password)
                remote_path = f"{path.rstrip('/')}/{filename}"
                written = 0

                async def _gen():
                    nonlocal written
                    async for chunk in source:
                        written += len(chunk)
                        yield chunk

                await client.upload_stream(_gen(), remote_path)
            _log.info("ftps.upload_done", path=remote_path, bytes=written)
            return written
        except Exception as exc:
            raise RemoteBackupProviderError(f"FTPS upload failed: {exc}") from exc
```

- [ ] **Step 3 : Tests PASS**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers.py -v
```

---

### Task 3.4 : S3CompatibleProvider (boto3 + asyncio.to_thread)

**Files:**
- Create: `backend/src/agflow/services/remote_backup_providers/s3_provider.py`

- [ ] **Step 1 : Ajouter le test S3**

```python
@pytest.mark.asyncio
async def test_s3_upload_creates_temp_file_and_cleans_up():
    from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider
    import tempfile, os

    mock_s3 = MagicMock()
    mock_s3.upload_fileobj = MagicMock()

    async def _source():
        yield b"s3data"

    config = {
        "endpoint_url": "https://s3.fr-par.scw.cloud",
        "region": "fr-par",
        "bucket": "my-bucket",
        "path_style": True,
    }
    creds = {"access_key_id": "AK", "secret_access_key": "SK"}
    provider = S3CompatibleProvider(config=config, credentials=creds)

    with patch("boto3.client", return_value=mock_s3):
        n = await provider.upload_stream("snapshots/", "dump.sql.gz", _source())

    mock_s3.upload_fileobj.assert_called_once()
    assert n == len(b"s3data")
```

- [ ] **Step 2 : Implémenter S3CompatibleProvider**

```python
# s3_provider.py
from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import boto3
import structlog

from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_log = structlog.get_logger(__name__)
_CHUNK = 64 * 1024


class S3CompatibleProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._endpoint_url: str | None = config.get("endpoint_url") or None
        self._region: str = config.get("region", "us-east-1")
        self._bucket: str = config["bucket"]
        self._access_key: str = credentials["access_key_id"]
        self._secret_key: str = credentials["secret_access_key"]

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        )

    async def test_connection(self, path: str) -> None:
        try:
            client = self._client()
            key = f"{path.lstrip('/')}.agflow-test"
            await asyncio.to_thread(client.put_object, Bucket=self._bucket, Key=key, Body=b"")
            await asyncio.to_thread(client.delete_object, Bucket=self._bucket, Key=key)
        except Exception as exc:
            raise RemoteBackupProviderError(f"S3 test failed: {exc}") from exc

    async def upload_stream(self, path: str, filename: str, source: AsyncIterator[bytes]) -> int:
        if "/" in filename or "\\" in filename:
            raise ValueError("filename must not contain path separators")
        key = f"{path.lstrip('/')}{filename}"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sql.gz")
        tmp_path = Path(tmp.name)
        written = 0
        try:
            try:
                async for chunk in source:
                    await asyncio.to_thread(tmp.write, chunk)
                    written += len(chunk)
            finally:
                await asyncio.to_thread(tmp.close)

            client = self._client()
            with tmp_path.open("rb") as fobj:
                await asyncio.to_thread(client.upload_fileobj, fobj, self._bucket, key)
            _log.info("s3.upload_done", bucket=self._bucket, key=key, bytes=written)
            return written
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"S3 upload failed: {exc}") from exc
        finally:
            await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
```

- [ ] **Step 3 : Écrire la factory**

```python
# factory.py
from __future__ import annotations

from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
)
from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider
from agflow.services.remote_backup_providers.sftp_provider import SftpProvider


def get_provider(kind: str, config: dict, credentials: dict) -> RemoteBackupProvider:
    match kind:
        case "sftp":
            return SftpProvider(config=config, credentials=credentials)
        case "ftps":
            return FtpsProvider(config=config, credentials=credentials)
        case "s3":
            return S3CompatibleProvider(config=config, credentials=credentials)
        case _:
            raise RemoteBackupProviderError(f"Unknown kind: {kind!r}")
```

- [ ] **Step 4 : Tous les tests providers PASS**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers.py -v
```

Attendu : tous PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/ \
        tests/services/test_remote_backup_providers.py
git commit -m "feat(remote-backups): provider abstraction + SFTP/FTPS/S3 implementations"
```

---

## LOT 4 — local_backups + system_anomaly + backup_lock

### Task 4.1 : backup_lock partagé

**Files:**
- Create: `backend/src/agflow/services/backup_lock.py`

- [ ] **Step 1 : Écrire le lock singleton**

```python
# backup_lock.py
from __future__ import annotations

import asyncio

# Lock global pour sérialiser les opérations longues (dump, push).
# Acquis par local_backups_service et remote_backup_pusher.
backup_lock: asyncio.Lock = asyncio.Lock()
```

---

### Task 4.2 : local_backups_service

**Files:**
- Create: `backend/src/agflow/services/local_backups_service.py`

- [ ] **Step 1 : Écrire le service**

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.local_backups import LocalBackupSummary
from agflow.services import db_backup
from agflow.services.backup_lock import backup_lock

_log = structlog.get_logger(__name__)


def _backups_dir() -> Path:
    settings = get_settings()
    d = Path(settings.agflow_data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _to_dto(row: dict) -> LocalBackupSummary:
    return LocalBackupSummary(
        id=row["id"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        status=row["status"],
        created_at=row["created_at"],
    )


async def list_backups() -> list[LocalBackupSummary]:
    rows = await fetch_all(
        "SELECT id, filename, size_bytes, status, created_at "
        "FROM local_backups ORDER BY created_at DESC LIMIT 100"
    )
    return [_to_dto(r) for r in rows]


async def get_backup(backup_id: UUID) -> LocalBackupSummary | None:
    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at FROM local_backups WHERE id = $1",
        backup_id,
    )
    return _to_dto(row) if row else None


async def create_backup(created_by_user_id: UUID | None = None) -> LocalBackupSummary:
    """Stream pg_dump vers disque, enregistre en DB. Sérialise via backup_lock."""
    async with backup_lock:
        backup_id = uuid4()
        filename = db_backup.export_filename()
        file_path = _backups_dir() / filename

        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, created_by_user_id) "
            "VALUES ($1, $2, $3, 'in_progress', $4)",
            backup_id, filename, str(file_path), created_by_user_id,
        )
        try:
            written = 0
            with file_path.open("wb") as f:
                async for chunk in db_backup.stream_dump():
                    await asyncio.to_thread(f.write, chunk)
                    written += len(chunk)
            await execute(
                "UPDATE local_backups SET status='completed', size_bytes=$1 WHERE id=$2",
                written, backup_id,
            )
            _log.info("local_backup.created", id=str(backup_id), size=written)
        except Exception as exc:
            await execute("UPDATE local_backups SET status='failed' WHERE id=$1", backup_id)
            file_path.unlink(missing_ok=True)
            raise RuntimeError(f"Backup creation failed: {exc}") from exc

    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at FROM local_backups WHERE id=$1",
        backup_id,
    )
    return _to_dto(row)


async def stream_backup_chunks(backup_id: UUID):
    """AsyncIterator[bytes] depuis le fichier backup local."""
    row = await fetch_one("SELECT file_path, status FROM local_backups WHERE id=$1", backup_id)
    if row is None:
        raise FileNotFoundError(f"Backup {backup_id} not found")
    if row["status"] != "completed":
        raise ValueError(f"Backup {backup_id} has status={row['status']!r}")
    path = Path(row["file_path"])
    if not path.exists():
        raise FileNotFoundError(f"Backup file missing: {path}")

    async def _gen():
        f = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(f.read, 64 * 1024)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(f.close)

    return _gen()
```

---

### Task 4.3 : system_anomaly_service

**Files:**
- Create: `backend/src/agflow/services/system_anomaly_service.py`
- Create: `tests/services/test_system_anomaly_service.py`

- [ ] **Step 1 : Écrire le test hystérésis**

```python
# tests/services/test_system_anomaly_service.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_create_anomaly_deduplicates_open_anomalies():
    """Ne crée pas une nouvelle anomalie si une non-ack existe déjà pour (source, source_ref_id, severity)."""
    from agflow.services import system_anomaly_service as svc

    ref_id = uuid4()

    with patch("agflow.services.system_anomaly_service.fetch_one", AsyncMock(
        return_value={"id": 1}  # anomalie déjà ouverte
    )) as mock_fetch, \
    patch("agflow.services.system_anomaly_service.execute", AsyncMock()) as mock_exec:

        await svc.create_anomaly(
            severity="critical",
            anomaly_type="remote_push_failed",
            source="snapshot_remote_push",
            source_ref_id=ref_id,
            message="Connection refused",
            metadata={"remote_id": str(ref_id)},
        )

        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_create_anomaly_inserts_if_no_open():
    """Crée l'anomalie si aucune n'est ouverte pour ce (source, source_ref_id, severity)."""
    from agflow.services import system_anomaly_service as svc

    ref_id = uuid4()

    with patch("agflow.services.system_anomaly_service.fetch_one", AsyncMock(return_value=None)) as mock_fetch, \
    patch("agflow.services.system_anomaly_service.execute", AsyncMock()) as mock_exec:

        await svc.create_anomaly(
            severity="critical",
            anomaly_type="remote_push_failed",
            source="snapshot_remote_push",
            source_ref_id=ref_id,
            message="Connection refused",
        )

        mock_exec.assert_called_once()
```

- [ ] **Step 2 : Vérifier FAIL**

```bash
cd backend && uv run pytest tests/services/test_system_anomaly_service.py -v
```

- [ ] **Step 3 : Implémenter system_anomaly_service**

```python
from __future__ import annotations

import json
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create_anomaly(
    *,
    severity: str,
    anomaly_type: str,
    source: str,
    source_ref_id: UUID | None = None,
    message: str,
    metadata: dict | None = None,
) -> None:
    """Crée une anomalie système. Hystérésis : skip si une non-ack existe déjà."""
    existing = await fetch_one(
        "SELECT id FROM system_anomaly_events "
        "WHERE source = $1 AND source_ref_id IS NOT DISTINCT FROM $2 "
        "AND severity = $3 AND acknowledged_at IS NULL",
        source, source_ref_id, severity,
    )
    if existing:
        _log.debug("system_anomaly.skip_duplicate", source=source, severity=severity)
        return

    await execute(
        "INSERT INTO system_anomaly_events "
        "(severity, anomaly_type, source, source_ref_id, message, metadata) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        severity, anomaly_type, source, source_ref_id,
        message, json.dumps(metadata or {}),
    )
    _log.warning("system_anomaly.created", source=source, severity=severity, message=message)


async def list_unacknowledged() -> list[dict]:
    return await fetch_all(
        "SELECT id, detected_at, severity, anomaly_type, source, source_ref_id, message, metadata "
        "FROM system_anomaly_events WHERE acknowledged_at IS NULL ORDER BY detected_at DESC"
    )


async def acknowledge(anomaly_id: int, by_user_id: UUID) -> None:
    await execute(
        "UPDATE system_anomaly_events SET acknowledged_at=NOW(), acknowledged_by_user_id=$1 WHERE id=$2",
        by_user_id, anomaly_id,
    )
```

- [ ] **Step 4 : Tests PASS**

```bash
cd backend && uv run pytest tests/services/test_system_anomaly_service.py -v
```

Attendu : 2 tests PASS.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/backup_lock.py \
        backend/src/agflow/services/local_backups_service.py \
        backend/src/agflow/services/system_anomaly_service.py \
        tests/services/test_system_anomaly_service.py
git commit -m "feat(remote-backups): local_backups_service, system_anomaly_service (hystérésis), backup_lock"
```

---

## LOT 5 — Endpoints Admin

### Task 5.1 : Endpoints remote_backup_connections

**Files:**
- Create: `backend/src/agflow/api/admin/remote_backup_connections.py`
- Create: `tests/api/test_remote_backup_connections_api.py`

- [ ] **Step 1 : Écrire 2 tests API**

```python
# tests/api/test_remote_backup_connections_api.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agflow.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_test_connection_always_returns_200_on_provider_error(client):
    """POST /api/admin/backup-remotes/test retourne 200 même si provider échoue."""
    from agflow.services.remote_backup_providers import RemoteBackupProviderError

    with patch(
        "agflow.api.admin.remote_backup_connections.get_provider",
    ) as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.test_connection = AsyncMock(
            side_effect=RemoteBackupProviderError("Connection refused")
        )
        mock_factory.return_value = mock_provider

        resp = client.post(
            "/api/admin/backup-remotes/test",
            json={
                "kind": "sftp",
                "config": {"host": "sftp.example.com", "port": 22},
                "credentials": {"username": "u", "password": "p"},
                "path": "/backups",
            },
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "Connection refused" in data.get("message", "")


def test_create_connection_returns_409_on_duplicate_name(client):
    """POST /api/admin/backup-remotes retourne 409 si le nom existe déjà."""
    from asyncpg import UniqueViolationError

    with patch(
        "agflow.api.admin.remote_backup_connections.rbc_service.create_connection",
        AsyncMock(side_effect=UniqueViolationError("duplicate")),
    ):
        resp = client.post(
            "/api/admin/backup-remotes",
            json={"name": "existing", "kind": "sftp", "config": {}},
            headers={"Authorization": "Bearer fake-token"},
        )

    assert resp.status_code == 409
```

- [ ] **Step 2 : Implémenter le router**

```python
# remote_backup_connections.py
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.db.pool import get_pool
from agflow.schemas.remote_backup_connections import (
    RemoteBackupConnectionCreate,
    RemoteBackupConnectionSummary,
    RemoteBackupConnectionUpdate,
    TestConnectionRequest,
    TestConnectionResult,
    TestConnectionWithIdRequest,
)
from agflow.services import remote_backup_connections_service as rbc_service
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/backup-remotes",
    tags=["admin", "backup-remotes"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[RemoteBackupConnectionSummary])
async def list_connections():
    async with (await get_pool()).acquire() as conn:
        return await rbc_service.list_connections(conn)


@router.post("", response_model=RemoteBackupConnectionSummary, status_code=201)
async def create_connection(body: RemoteBackupConnectionCreate, user=Depends(require_admin)):
    try:
        async with (await get_pool()).acquire() as conn:
            connection_id = await rbc_service.create_connection(
                conn,
                name=body.name,
                kind=body.kind,
                config=body.config,
                credentials=body.credentials,
                created_by_user_id=getattr(user, "id", None),
            )
            dto = await rbc_service.get_connection(conn, connection_id)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="A connection with this name already exists")
    return dto


@router.get("/{connection_id}", response_model=RemoteBackupConnectionSummary)
async def get_connection(connection_id: UUID):
    async with (await get_pool()).acquire() as conn:
        dto = await rbc_service.get_connection(conn, connection_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return dto


@router.patch("/{connection_id}", response_model=RemoteBackupConnectionSummary)
async def update_connection(connection_id: UUID, body: RemoteBackupConnectionUpdate):
    async with (await get_pool()).acquire() as conn:
        await rbc_service.update_connection(
            conn, connection_id,
            name=body.name, config=body.config, credentials=body.credentials,
        )
        return await rbc_service.get_connection(conn, connection_id)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: UUID):
    async with (await get_pool()).acquire() as conn:
        await rbc_service.delete_connection(conn, connection_id)


@router.post("/test", response_model=TestConnectionResult)
async def test_connection_unsaved(body: TestConnectionRequest):
    """Test avec creds fournis dans le body (création / édition avec resaisie)."""
    try:
        provider = get_provider(body.kind, body.config, body.credentials)
        await provider.test_connection(body.path)
        return TestConnectionResult(ok=True)
    except RemoteBackupProviderError as exc:
        return TestConnectionResult(ok=False, error="provider_error", message=str(exc))
    except Exception as exc:
        _log.warning("rbc.test_connection.unexpected", error=str(exc))
        return TestConnectionResult(ok=False, error="unexpected", message=str(exc))


@router.post("/{connection_id}/test", response_model=TestConnectionResult)
async def test_connection_saved(connection_id: UUID, body: TestConnectionWithIdRequest):
    """Test avec creds stockés en vault (édition sans resaisie)."""
    async with (await get_pool()).acquire() as conn:
        dto = await rbc_service.get_connection(conn, connection_id)
        if dto is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        config = {**dto.config, **(body.config or {})}
        credentials = await rbc_service.fetch_credentials(dto)
    if credentials is None:
        return TestConnectionResult(ok=False, error="no_credentials",
                                   message="No credentials stored for this connection")
    try:
        provider = get_provider(dto.kind, config, credentials)
        await provider.test_connection(body.path)
        return TestConnectionResult(ok=True)
    except RemoteBackupProviderError as exc:
        return TestConnectionResult(ok=False, error="provider_error", message=str(exc))
```

- [ ] **Step 3 : Enregistrer le router dans main.py**

Dans `main.py`, ajouter l'import et l'`include_router` (suivre le pattern existant) :

```python
from agflow.api.admin.remote_backup_connections import router as admin_rbc_router
# Dans la liste des include_router :
app.include_router(admin_rbc_router)
```

---

### Task 5.2 : Endpoints local_backups + push

**Files:**
- Create: `backend/src/agflow/api/admin/local_backups.py`

- [ ] **Step 1 : Implémenter le router local_backups**

```python
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from agflow.auth.dependencies import require_admin
from agflow.schemas.local_backups import LocalBackupSummary
from agflow.services import (
    local_backups_service,
    remote_backup_connections_service as rbc_service,
    system_anomaly_service,
)
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/local-backups",
    tags=["admin", "local-backups"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[LocalBackupSummary])
async def list_backups():
    return await local_backups_service.list_backups()


@router.post("", response_model=LocalBackupSummary, status_code=201)
async def create_backup(user=Depends(require_admin)):
    """Déclenche un pg_dump et le sauvegarde sur disque."""
    return await local_backups_service.create_backup(
        created_by_user_id=getattr(user, "id", None)
    )


@router.post("/{backup_id}/push-to-remote/{remote_id}", status_code=200)
async def push_to_remote(backup_id: UUID, remote_id: UUID):
    """Push un backup local vers une connexion distante (usage 'full')."""
    from agflow.db.pool import get_pool

    backup = await local_backups_service.get_backup(backup_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    if backup.status != "completed":
        raise HTTPException(status_code=422, detail=f"Backup status is {backup.status!r}")

    async with (await get_pool()).acquire() as conn:
        connection = await rbc_service.get_connection(conn, remote_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Remote connection not found")
        credentials = await rbc_service.fetch_credentials(connection)

    if credentials is None:
        raise HTTPException(status_code=422, detail="No credentials configured for this remote")

    remote_path = rbc_service.resolve_remote_path(connection.config, connection.kind, "full")
    if remote_path is None:
        raise HTTPException(status_code=422, detail="No full backup path configured on this remote")

    try:
        provider = get_provider(connection.kind, connection.config, credentials)
        source = await local_backups_service.stream_backup_chunks(backup_id)
        written = await provider.upload_stream(remote_path, backup.filename, source)
        _log.info("push_to_remote.success", backup_id=str(backup_id),
                  remote_id=str(remote_id), bytes=written)
        return {"ok": True, "bytes_written": written}
    except RemoteBackupProviderError as exc:
        _log.warning("push_to_remote.provider_error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))
```

- [ ] **Step 2 : Enregistrer le router dans main.py**

```python
from agflow.api.admin.local_backups import router as admin_local_backups_router
app.include_router(admin_local_backups_router)
```

- [ ] **Step 3 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/remote_backup_connections.py \
                                src/agflow/api/admin/local_backups.py
```

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/api/admin/remote_backup_connections.py \
        backend/src/agflow/api/admin/local_backups.py \
        backend/src/agflow/main.py \
        tests/api/test_remote_backup_connections_api.py
git commit -m "feat(remote-backups): endpoints admin backup-remotes + local-backups + push"
```

---

## LOT 6 — Worker Périodique

### Task 6.1 : remote_backup_pusher worker

**Files:**
- Create: `backend/src/agflow/workers/remote_backup_pusher.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1 : Écrire le worker**

```python
# remote_backup_pusher.py
from __future__ import annotations

import asyncio

import structlog

from agflow.db.pool import fetch_all, get_pool
from agflow.services import (
    local_backups_service,
    remote_backup_connections_service as rbc_service,
    system_anomaly_service,
)
from agflow.services.backup_lock import backup_lock
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)
POLL_INTERVAL_S = 300  # toutes les 5 minutes


async def _has_new_data_since_last_backup() -> bool:
    """Retourne True si des données ont changé depuis le dernier backup (§2.7 skip-if-no-change)."""
    from agflow.db.pool import fetch_one
    row = await fetch_one(
        """
        SELECT
            (SELECT MAX(updated_at) FROM users) AS users_max,
            (SELECT MAX(created_at) FROM local_backups WHERE status = 'completed') AS last_backup
        """
    )
    if row is None or row["last_backup"] is None:
        return True  # pas encore de backup → toujours créer
    return (row["users_max"] or row["last_backup"]) > row["last_backup"]


async def _run_scheduled_push() -> None:
    """Crée un backup local et le pousse vers toutes les connexions configurées pour les snapshots."""
    async with (await get_pool()).acquire() as conn:
        connections = await rbc_service.list_connections(conn)

    snapshot_connections = [
        c for c in connections
        if c.has_credentials and rbc_service.resolve_remote_path(c.config, c.kind, "snapshots")
    ]

    if not snapshot_connections:
        return

    # §2.7 — skip si aucune donnée n'a changé depuis le dernier backup
    if not await _has_new_data_since_last_backup():
        _log.debug("remote_backup_pusher.skip_no_change")
        return

    async with backup_lock:
        try:
            backup = await local_backups_service.create_backup()
        except Exception as exc:
            _log.error("remote_backup_pusher.backup_failed", error=str(exc))
            return

    for connection in snapshot_connections:
        remote_path = rbc_service.resolve_remote_path(connection.config, connection.kind, "snapshots")
        async with (await get_pool()).acquire() as conn:
            credentials = await rbc_service.fetch_credentials(connection)
        if credentials is None:
            continue
        try:
            provider = get_provider(connection.kind, connection.config, credentials)
            source = await local_backups_service.stream_backup_chunks(backup.id)
            await provider.upload_stream(remote_path, backup.filename, source)
            _log.info("remote_backup_pusher.push_ok",
                      connection=connection.name, backup=backup.filename)
        except (RemoteBackupProviderError, Exception) as exc:
            _log.error("remote_backup_pusher.push_failed",
                       connection=connection.name, error=str(exc))
            await system_anomaly_service.create_anomaly(
                severity="critical",
                anomaly_type="remote_push_failed",
                source="snapshot_remote_push",
                source_ref_id=connection.id,
                message=f"Push vers {connection.name!r} échoué : {exc}",
                metadata={"filename": backup.filename, "error": str(exc)},
            )


async def run_remote_backup_pusher_loop(stop_event: asyncio.Event) -> None:
    _log.info("remote_backup_pusher.started", interval_s=POLL_INTERVAL_S)
    try:
        while not stop_event.is_set():
            try:
                await _run_scheduled_push()
            except Exception as exc:
                _log.warning("remote_backup_pusher.tick_error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
            except TimeoutError:
                continue
    finally:
        _log.info("remote_backup_pusher.stopped")
```

- [ ] **Step 2 : Enregistrer dans main.py**

Dans `main.py`, ajouter dans le bloc des workers (suivre le pattern exact existant) :

```python
# Import à ajouter en haut avec les autres workers :
from agflow.workers.remote_backup_pusher import run_remote_backup_pusher_loop as _run_rbc_pusher_loop

# Dans le lifespan, changer le range(4) en range(5) et ajouter le 5e task :
_stops = [_asyncio.Event() for _ in range(5)]
_tasks = [
    _asyncio.create_task(_run_expiry_loop(_stops[0])),
    _asyncio.create_task(_run_agent_reaper_loop(_stops[1])),
    _asyncio.create_task(_run_session_idle_reaper_loop(_stops[2])),
    _asyncio.create_task(_run_mom_reclaimer_loop(_stops[3])),
    _asyncio.create_task(_run_rbc_pusher_loop(_stops[4])),
]
```

- [ ] **Step 3 : Vérifier que le backend démarre**

```bash
cd backend && uv run uvicorn agflow.main:app --port 8000 &
sleep 3 && curl -s http://localhost:8000/health && kill %1
```

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/workers/remote_backup_pusher.py backend/src/agflow/main.py
git commit -m "feat(remote-backups): worker périodique remote_backup_pusher avec hystérésis anomalies"
```

---

## LOT 7 — UI + i18n

### Task 7.1 : Page RemoteBackupConnections

**Files:**
- Create: `frontend/src/pages/RemoteBackupConnectionsPage.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `fr.json`, sous un objet `"backup_remotes"` :
```json
"backup_remotes": {
  "title": "Connexions distantes (Backups)",
  "add": "Nouvelle connexion",
  "name": "Nom",
  "kind": "Type",
  "host": "Hôte",
  "paths": "Chemins",
  "has_credentials": "Identifiants",
  "credentials_ok": "✓ Identifiants enregistrés (Vault). Laisser vide pour conserver.",
  "credentials_missing": "⚠ Aucun identifiant enregistré.",
  "path_snapshots": "Chemin snapshots",
  "path_full": "Chemin full backup",
  "test": "Tester",
  "test_ok": "✓ Connexion réussie",
  "test_fail": "✗ Échec",
  "save": "Enregistrer",
  "delete_confirm": "Supprimer cette connexion ?",
  "kind_sftp": "SFTP",
  "kind_ftps": "FTPS",
  "kind_s3": "S3 / Compatible",
  "username": "Nom d'utilisateur",
  "password": "Mot de passe",
  "access_key_id": "Access Key ID",
  "secret_access_key": "Secret Access Key",
  "endpoint_url": "URL endpoint (vide = AWS)",
  "bucket": "Bucket",
  "region": "Région",
  "port": "Port",
  "not_configured": "Non configuré"
}
```

Mêmes clés en `en.json` (traduction anglaise).

- [ ] **Step 2 : Implémenter RemoteBackupConnectionsPage.tsx**

La page contient :
- `useQuery(["backup-remotes"], () => api.get("/api/admin/backup-remotes").then(r => r.data))` pour la liste
- Un tableau : colonnes Name, Kind, Host, Paths (snapshots / full), Identifiants (✓/✗)
- Bouton "Nouvelle connexion" → ouvre `ConnectionModal` (create)
- Clic sur une ligne → ouvre `ConnectionModal` (edit)
- `ConnectionModal` : Dialog shadcn avec :
  - Input Name + Select Kind
  - Champs config selon kind (SFTP : host/port/path_snapshots/path_full ; S3 : endpoint/region/bucket/prefix_snapshots/prefix_full ; FTPS : host/port/use_tls/paths)
  - Pour chaque path (snapshots, full) : Input + Bouton "Tester" inline → `POST /test` ou `/{id}/test`
  - Section credentials : Alert verte si has_credentials=true, orange sinon. Inputs username/password (SFTP/FTPS) ou access_key_id/secret_access_key (S3). Placeholder "laisser vide pour conserver" si édition + has_credentials=true.
  - Boutons : Annuler | Enregistrer (useMutation POST ou PATCH)
- Bouton Supprimer (avec confirm Dialog) → DELETE, invalidate query

Structure du composant (squelette à implémenter) :

```tsx
import { useTranslation } from "react-i18next"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Alert, AlertDescription } from "@/components/ui/alert"
import api from "@/lib/api"

interface Connection {
  id: string
  name: string
  kind: "sftp" | "ftps" | "s3"
  config: Record<string, unknown>
  has_credentials: boolean
  created_at: string
  updated_at: string
}

export default function RemoteBackupConnectionsPage() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const [modalConn, setModalConn] = useState<Connection | null | "new">(null)

  const { data: connections = [] } = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get("/api/admin/backup-remotes").then(r => r.data),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/api/admin/backup-remotes/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["backup-remotes"] }),
  })

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">{t("backup_remotes.title")}</h1>
        <Button onClick={() => setModalConn("new")}>{t("backup_remotes.add")}</Button>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="py-2 pr-4">{t("backup_remotes.name")}</th>
            <th className="pr-4">{t("backup_remotes.kind")}</th>
            <th className="pr-4">{t("backup_remotes.host")}</th>
            <th className="pr-4">{t("backup_remotes.paths")}</th>
            <th>{t("backup_remotes.has_credentials")}</th>
          </tr>
        </thead>
        <tbody>
          {connections.map(c => (
            <tr key={c.id} className="border-b hover:bg-muted/50 cursor-pointer"
                onClick={() => setModalConn(c)}>
              <td className="py-2 pr-4 font-medium">{c.name}</td>
              <td className="pr-4 uppercase text-xs">{c.kind}</td>
              <td className="pr-4">{(c.config as Record<string, string>).host ?? "—"}</td>
              <td className="pr-4 text-xs text-muted-foreground">
                {[
                  (c.config as Record<string, string>).remote_path_snapshots,
                  (c.config as Record<string, string>).remote_path_full,
                  (c.config as Record<string, string>).prefix_snapshots,
                  (c.config as Record<string, string>).prefix_full,
                ].filter(Boolean).join(" / ") || t("backup_remotes.not_configured")}
              </td>
              <td>{c.has_credentials ? "✓" : "✗"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {modalConn !== null && (
        <ConnectionModal
          connection={modalConn === "new" ? null : modalConn}
          onClose={() => setModalConn(null)}
          onSaved={() => { qc.invalidateQueries({ queryKey: ["backup-remotes"] }); setModalConn(null) }}
        />
      )}
    </div>
  )
}

// ─── ConnectionModal ────────────────────────────────────────────────────────

interface ConnectionModalProps {
  connection: Connection | null
  onClose: () => void
  onSaved: () => void
}

function ConnectionModal({ connection, onClose, onSaved }: ConnectionModalProps) {
  const { t } = useTranslation()
  const isEdit = connection !== null
  const [kind, setKind] = useState<string>(connection?.kind ?? "sftp")
  const [name, setName] = useState(connection?.name ?? "")
  const [config, setConfig] = useState<Record<string, string>>(
    (connection?.config as Record<string, string>) ?? {}
  )
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; msg?: string }>>({})

  const saveMutation = useMutation({
    mutationFn: () => {
      const credentials = (username || password)
        ? { username, password }
        : undefined
      if (isEdit) {
        return api.patch(`/api/admin/backup-remotes/${connection!.id}`, { name, config, credentials })
      }
      return api.post("/api/admin/backup-remotes", { name, kind, config, credentials })
    },
    onSuccess: onSaved,
  })

  const handleTest = async (pathKey: string) => {
    const path = config[pathKey] ?? ""
    if (!path) return
    const body = isEdit && !username
      ? { path, config }
      : { kind, config, credentials: { username, password }, path }
    const url = isEdit && !username
      ? `/api/admin/backup-remotes/${connection!.id}/test`
      : "/api/admin/backup-remotes/test"
    try {
      const res = await api.post(url, body)
      setTestResults(r => ({ ...r, [pathKey]: { ok: res.data.ok, msg: res.data.message } }))
    } catch {
      setTestResults(r => ({ ...r, [pathKey]: { ok: false, msg: "request failed" } }))
    }
  }

  const pathKeys = kind === "s3"
    ? ["prefix_snapshots", "prefix_full"]
    : ["remote_path_snapshots", "remote_path_full"]

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? connection!.name : t("backup_remotes.add")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>{t("backup_remotes.name")}</Label>
            <Input value={name} onChange={e => setName(e.target.value)} />
          </div>
          {!isEdit && (
            <div>
              <Label>{t("backup_remotes.kind")}</Label>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="sftp">{t("backup_remotes.kind_sftp")}</SelectItem>
                  <SelectItem value="ftps">{t("backup_remotes.kind_ftps")}</SelectItem>
                  <SelectItem value="s3">{t("backup_remotes.kind_s3")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
          {kind !== "s3" && (
            <>
              <div>
                <Label>{t("backup_remotes.host")}</Label>
                <Input value={config.host ?? ""} onChange={e => setConfig(c => ({ ...c, host: e.target.value }))} />
              </div>
              <div>
                <Label>{t("backup_remotes.port")}</Label>
                <Input type="number" value={config.port ?? (kind === "ftps" ? "21" : "22")}
                  onChange={e => setConfig(c => ({ ...c, port: e.target.value }))} />
              </div>
            </>
          )}
          {kind === "s3" && (
            <>
              <div>
                <Label>{t("backup_remotes.endpoint_url")}</Label>
                <Input value={config.endpoint_url ?? ""} onChange={e => setConfig(c => ({ ...c, endpoint_url: e.target.value }))} />
              </div>
              <div>
                <Label>{t("backup_remotes.bucket")}</Label>
                <Input value={config.bucket ?? ""} onChange={e => setConfig(c => ({ ...c, bucket: e.target.value }))} />
              </div>
              <div>
                <Label>{t("backup_remotes.region")}</Label>
                <Input value={config.region ?? ""} onChange={e => setConfig(c => ({ ...c, region: e.target.value }))} />
              </div>
            </>
          )}
          {pathKeys.map(key => (
            <div key={key}>
              <Label>{t(`backup_remotes.${key === "prefix_snapshots" || key === "remote_path_snapshots" ? "path_snapshots" : "path_full"}`)}</Label>
              <div className="flex gap-2">
                <Input value={config[key] ?? ""} onChange={e => setConfig(c => ({ ...c, [key]: e.target.value }))} />
                <Button variant="outline" size="sm" onClick={() => handleTest(key)}>
                  {t("backup_remotes.test")}
                </Button>
              </div>
              {testResults[key] && (
                <p className={`text-xs mt-0.5 ${testResults[key].ok ? "text-green-600" : "text-red-600"}`}>
                  {testResults[key].ok ? t("backup_remotes.test_ok") : `${t("backup_remotes.test_fail")}: ${testResults[key].msg}`}
                </p>
              )}
            </div>
          ))}
          <Alert variant={isEdit && connection?.has_credentials ? "default" : "destructive"} className="text-sm">
            <AlertDescription>
              {isEdit && connection?.has_credentials
                ? t("backup_remotes.credentials_ok")
                : t("backup_remotes.credentials_missing")}
            </AlertDescription>
          </Alert>
          <div>
            <Label>{t("backup_remotes.username")}</Label>
            <Input placeholder={isEdit && connection?.has_credentials ? "••••••••" : ""}
              value={username} onChange={e => setUsername(e.target.value)} />
          </div>
          {kind !== "s3" ? (
            <div>
              <Label>{t("backup_remotes.password")}</Label>
              <Input type="password" placeholder={isEdit && connection?.has_credentials ? "••••••••" : ""}
                value={password} onChange={e => setPassword(e.target.value)} />
            </div>
          ) : (
            <div>
              <Label>{t("backup_remotes.secret_access_key")}</Label>
              <Input type="password" placeholder={isEdit && connection?.has_credentials ? "••••••••" : ""}
                value={password} onChange={e => setPassword(e.target.value)} />
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>Annuler</Button>
            <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
              {t("backup_remotes.save")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 3 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Attendu : 0 erreurs.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/pages/RemoteBackupConnectionsPage.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(remote-backups): page UI connexions distantes + i18n"
```

---

## Checklist de validation finale

Avant de déclarer terminé, vérifier :

- [ ] Credentials jamais retournés dans une réponse HTTP (GET detail, list).
- [ ] `vault_client.get_secret()` appelé uniquement dans `fetch_credentials`, pas dans `list_connections` ni `get_connection`.
- [ ] Table `remote_backup_connections` : pas de colonne `credentials_encrypted`. Colonnes `vault_api_key_id` + `vault_secret_path` avec CHECK `both-or-none`.
- [ ] `vault_secret_path` toujours `"remote-backups/{uuid}"`, jamais saisi par l'admin.
- [ ] `create_connection` : `vault_client.create_secret` AVANT INSERT, rollback (`delete_secret`) si INSERT échoue.
- [ ] `POST /backup-remotes/test` et `POST /backup-remotes/{id}/test` retournent **toujours 200**.
- [ ] `push-to-remote` retourne **422** (pas 500/502) si provider échoue.
- [ ] Filename validé (`"/" in filename` → ValueError) avant upload.
- [ ] Anomalie de push raté créée une seule fois (hystérésis sur `source + source_ref_id + severity + acknowledged_at IS NULL`).
- [ ] `aioftp` et `boto3` dans `pyproject.toml` + `uv.lock`.
- [ ] `AGFLOW_DATA_DIR` dans `config.py` et dans `.env.example`.
- [ ] `backup_lock` acquis dans `create_backup` et dans `_run_scheduled_push`.
- [ ] Worker enregistré dans `main.py` avec son stop_event.
- [ ] Tous les tests passent : `cd backend && uv run pytest -v`
- [ ] Lint propre : `cd backend && uv run ruff check src/ tests/`
