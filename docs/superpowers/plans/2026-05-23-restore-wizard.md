# Restore Wizard — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Page dédiée `/restore` permettant, sur une machine fraîchement installée, de connecter un vault Harpocrate ad-hoc, sélectionner une connexion distante et un certificat depuis le vault, naviguer les fichiers du remote et restaurer un backup — sans aucune configuration préalable en base.

**Architecture:** 3 nouveaux services backend stateless (`restore_wizard_vault_service`, `restore_wizard_browse_service`, `restore_wizard_job_service`) + router FastAPI `/api/admin/restore/` + page React avec wizard 4 étapes en state React local. Les providers existants (`SftpProvider`, `S3CompatibleProvider`, etc.) sont réutilisés via `get_provider`. La restauration finale appelle `db_backup.restore_dump` existant.

**Tech Stack:** FastAPI + asyncpg (pool direct) + asyncssh + harpocrate SDK direct / React 18 + TypeScript strict + TanStack Query + shadcn/ui + i18next + Vitest

---

## Structure des fichiers

### Nouveaux fichiers
```
backend/migrations/123_restore_jobs.sql
backend/src/agflow/schemas/restore_wizard.py
backend/src/agflow/services/restore_wizard_vault_service.py
backend/src/agflow/services/restore_wizard_browse_service.py
backend/src/agflow/services/restore_wizard_job_service.py
backend/src/agflow/api/admin/restore.py
backend/tests/services/test_restore_wizard_vault_service.py
backend/tests/services/test_restore_wizard_browse_service.py
backend/tests/services/test_restore_wizard_job_service.py
frontend/src/lib/restoreApi.ts
frontend/src/pages/RestorePage.tsx
frontend/src/components/restore/RestoreTimelineItem.tsx
frontend/src/components/restore/VaultConnectStep.tsx
frontend/src/components/restore/VaultSecretPicker.tsx
frontend/src/components/restore/RemoteConnectionStep.tsx
frontend/src/components/restore/RemoteFileBrowser.tsx
frontend/src/components/restore/RestoreConfirmStep.tsx
```

### Fichiers modifiés
```
backend/src/agflow/main.py                       (+2 lignes : import + include_router)
frontend/src/App.tsx                             (+route /restore)
frontend/src/components/layout/Sidebar.tsx       (+entrée nav Restauration)
frontend/src/i18n/fr.json                        (+clés restore.*)
frontend/src/i18n/en.json                        (+clés restore.*)
```

---

### Task 1 : Migration DB — table restore_jobs

**Files:**
- Create: `backend/migrations/123_restore_jobs.sql`

- [ ] **Step 1 : Écrire la migration**

```sql
-- 123_restore_jobs.sql
-- Jobs de restauration éphémères créés par le wizard de restauration.
-- Aucune FK — les jobs sont indépendants du reste du schéma.

CREATE TABLE restore_jobs (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    status        TEXT         NOT NULL DEFAULT 'running',  -- running | done | failed
    log           TEXT         NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
```

- [ ] **Step 2 : Appliquer la migration**

```bash
cd backend && uv run python -m agflow.db.migrations
```

Expected : `Applied 123_restore_jobs.sql` dans les logs.

- [ ] **Step 3 : Commit**

```bash
git add backend/migrations/123_restore_jobs.sql
git commit -m "feat(restore): migration table restore_jobs"
```

---

### Task 2 : Schémas Pydantic backend

**Files:**
- Create: `backend/src/agflow/schemas/restore_wizard.py`

- [ ] **Step 1 : Écrire les schémas**

```python
# backend/src/agflow/schemas/restore_wizard.py
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class VaultRef(BaseModel):
    url: str
    api_key: str


class VaultTestRequest(BaseModel):
    url: str
    api_key: str


class VaultSecretItem(BaseModel):
    name: str
    tags: list[str]


class RemoteBrowseRequest(BaseModel):
    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]  # field_name → vault secret name
    vault: VaultRef
    path: str = "/"


class RemoteEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_at: datetime | None


class RestoreExecuteRequest(BaseModel):
    connection_type: Literal["sftp", "s3", "ftps", "gdrive"]
    manual_fields: dict[str, str]
    vault_mappings: dict[str, str]
    vault: VaultRef
    file_path: str  # chemin complet du fichier sur le remote


class RestoreJobStarted(BaseModel):
    job_id: UUID


class RestoreJobStatus(BaseModel):
    job_id: UUID
    status: Literal["running", "done", "failed"]
    log: str
    created_at: datetime
    completed_at: datetime | None
```

- [ ] **Step 2 : Commit**

```bash
git add backend/src/agflow/schemas/restore_wizard.py
git commit -m "feat(restore): schemas Pydantic restore wizard"
```

---

### Task 3 : Service vault ad-hoc + tests

**Files:**
- Create: `backend/src/agflow/services/restore_wizard_vault_service.py`
- Test: `backend/tests/services/test_restore_wizard_vault_service.py`

- [ ] **Step 1 : Écrire le test (rouge)**

```python
# backend/tests/services/test_restore_wizard_vault_service.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agflow.services.restore_wizard_vault_service import (
    InvalidVaultCredentialsError,
    list_vault_secrets_by_prefix,
    test_vault_connection,
)


class _FakeSecretItem:
    def __init__(self, name: str, tags: list[str] | None = None) -> None:
        self.name = name
        self.tags = tags


class _FakeSecretsClient:
    def list_secrets(self, limit: int = 200):
        result = MagicMock()
        result.secrets = [
            _FakeSecretItem("certificates/id_prod", ["prod", "ssh"]),
            _FakeSecretItem("remote-backups/sftp-prod", ["prod"]),
            _FakeSecretItem("other/secret"),
        ]
        return result


@pytest.mark.asyncio
async def test_test_vault_connection_ok(monkeypatch):
    fake_client = MagicMock()
    fake_client.secrets = _FakeSecretsClient()
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        # Ne doit pas lever d'exception
        await test_vault_connection("https://vault.example.com", "valid-key")


@pytest.mark.asyncio
async def test_test_vault_connection_invalid_key(monkeypatch):
    from harpocrate.exceptions import VaultHttpError

    fake_client = MagicMock()
    err = VaultHttpError.__new__(VaultHttpError)
    err.status_code = 401
    fake_client.secrets.list_secrets.side_effect = err
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        with pytest.raises(InvalidVaultCredentialsError):
            await test_vault_connection("https://vault.example.com", "bad-key")


@pytest.mark.asyncio
async def test_list_vault_secrets_by_prefix_filters_correctly(monkeypatch):
    fake_client = MagicMock()
    fake_client.secrets = _FakeSecretsClient()
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        items = await list_vault_secrets_by_prefix(
            "https://vault.example.com", "valid-key", "certificates"
        )
    assert len(items) == 1
    assert items[0].name == "certificates/id_prod"
    assert "prod" in items[0].tags


@pytest.mark.asyncio
async def test_list_vault_secrets_by_prefix_returns_all_when_prefix_empty(monkeypatch):
    fake_client = MagicMock()
    fake_client.secrets = _FakeSecretsClient()
    with patch(
        "agflow.services.restore_wizard_vault_service.VaultClient",
        return_value=fake_client,
    ):
        items = await list_vault_secrets_by_prefix(
            "https://vault.example.com", "valid-key", ""
        )
    assert len(items) == 3
```

- [ ] **Step 2 : Vérifier que le test échoue**

```bash
cd backend && uv run pytest tests/services/test_restore_wizard_vault_service.py -v
```

Expected : `ModuleNotFoundError` ou `ImportError`.

- [ ] **Step 3 : Implémenter le service**

```python
# backend/src/agflow/services/restore_wizard_vault_service.py
from __future__ import annotations

import asyncio
from functools import partial

import structlog

from agflow.schemas.restore_wizard import VaultSecretItem

_log = structlog.get_logger(__name__)


class InvalidVaultCredentialsError(Exception):
    """API key ou URL invalide."""


async def _run_sync(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(fn, *args, **kwargs))


def _make_client(url: str, api_key: str):
    from harpocrate import VaultClient

    return VaultClient(token=api_key, base_url=url)


async def test_vault_connection(url: str, api_key: str) -> None:
    """Teste la connexion au vault. Lève InvalidVaultCredentialsError si invalide."""
    from harpocrate.exceptions import VaultHttpError

    client = _make_client(url, api_key)
    try:
        await _run_sync(client.secrets.list_secrets, limit=1)
    except VaultHttpError as exc:
        if exc.status_code == 401:
            raise InvalidVaultCredentialsError("API key invalide") from exc
        raise
    except Exception as exc:
        raise InvalidVaultCredentialsError(f"Vault injoignable : {exc}") from exc


async def list_vault_secrets_by_prefix(
    url: str, api_key: str, prefix: str
) -> list[VaultSecretItem]:
    """Liste les secrets du vault filtrés par préfixe de nom."""
    client = _make_client(url, api_key)
    resp = await _run_sync(client.secrets.list_secrets, limit=500)
    return [
        VaultSecretItem(
            name=s.name,
            tags=list(getattr(s, "tags", None) or []),
        )
        for s in resp.secrets
        if not prefix or s.name == prefix or s.name.startswith(prefix + "/")
    ]


async def get_vault_secret_value(url: str, api_key: str, name: str) -> str:
    """Lit la valeur déchiffrée d'un secret."""
    client = _make_client(url, api_key)
    return await _run_sync(client.secrets.get, name)
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_restore_wizard_vault_service.py -v
```

Expected : 4 tests PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/restore_wizard_vault_service.py \
        backend/tests/services/test_restore_wizard_vault_service.py
git commit -m "feat(restore): service vault ad-hoc + tests"
```

---

### Task 4 : Service browse ad-hoc + tests

**Files:**
- Create: `backend/src/agflow/services/restore_wizard_browse_service.py`
- Test: `backend/tests/services/test_restore_wizard_browse_service.py`

- [ ] **Step 1 : Écrire le test (rouge)**

```python
# backend/tests/services/test_restore_wizard_browse_service.py
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.schemas.restore_wizard import RemoteEntry
from agflow.services.restore_wizard_browse_service import browse_remote


@pytest.mark.asyncio
async def test_browse_remote_sftp_returns_files_and_dirs(monkeypatch):
    entry_dir = MagicMock()
    entry_dir.filename = "backups"
    entry_dir.attrs.permissions = 0o40755  # S_ISDIR
    entry_dir.attrs.size = None
    entry_dir.attrs.mtime = None

    entry_file = MagicMock()
    entry_file.filename = "dump.sql.gz"
    entry_file.attrs.permissions = 0o100644  # regular file
    entry_file.attrs.size = 1024
    entry_file.attrs.mtime = 1700000000

    dot = MagicMock()
    dot.filename = "."

    fake_sftp = AsyncMock()
    fake_sftp.readdir = AsyncMock(return_value=[dot, entry_dir, entry_file])

    fake_conn = AsyncMock()
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=None)
    fake_conn.start_sftp_client = MagicMock(return_value=fake_sftp)
    fake_sftp.__aenter__ = AsyncMock(return_value=fake_sftp)
    fake_sftp.__aexit__ = AsyncMock(return_value=None)

    with patch("asyncssh.connect", return_value=fake_conn):
        entries = await browse_remote(
            connection_type="sftp",
            manual_fields={"host": "192.168.1.1", "port": "22", "path": "/backups"},
            credentials={"username": "root", "private_key": None, "password": "secret"},
        )

    # Dirs en premier, puis fichiers
    assert entries[0].name == "backups"
    assert entries[0].is_dir is True
    assert entries[1].name == "dump.sql.gz"
    assert entries[1].is_dir is False
    assert entries[1].size_bytes == 1024


@pytest.mark.asyncio
async def test_browse_remote_other_provider_flat_list():
    fake_files = [
        MagicMock(filename="dump.sql.gz", size_bytes=2048, last_modified=None),
    ]
    fake_provider = AsyncMock()
    fake_provider.list_remote = AsyncMock(return_value=fake_files)

    with patch(
        "agflow.services.restore_wizard_browse_service.get_provider",
        return_value=fake_provider,
    ):
        entries = await browse_remote(
            connection_type="s3",
            manual_fields={"bucket": "mybucket", "region": "eu-west-1", "prefix": "backups/"},
            credentials={"access_key_id": "AK", "secret_access_key": "SK"},
        )

    assert len(entries) == 1
    assert entries[0].name == "dump.sql.gz"
    assert entries[0].is_dir is False
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```bash
cd backend && uv run pytest tests/services/test_restore_wizard_browse_service.py -v
```

Expected : `ImportError`.

- [ ] **Step 3 : Implémenter le service**

```python
# backend/src/agflow/services/restore_wizard_browse_service.py
from __future__ import annotations

import stat as stat_mod
from datetime import datetime, timezone

import structlog

from agflow.schemas.restore_wizard import RemoteEntry
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)


async def browse_remote(
    connection_type: str,
    manual_fields: dict[str, str],
    credentials: dict[str, str | None],
) -> list[RemoteEntry]:
    """Liste les entrées (fichiers + dossiers) d'un path distant.

    SFTP : navigation répertoire complète via asyncssh.
    Autres providers : liste plate via list_remote existant.
    """
    path = manual_fields.get("path", "/")
    if connection_type == "sftp":
        return await _browse_sftp(manual_fields, credentials, path)
    return await _browse_via_provider(connection_type, manual_fields, credentials, path)


async def _browse_sftp(
    config: dict[str, str],
    credentials: dict[str, str | None],
    path: str,
) -> list[RemoteEntry]:
    import asyncssh

    host = config["host"]
    port = int(config.get("port", "22"))
    username = credentials.get("username", "")
    password = credentials.get("password")
    private_key_str = credentials.get("private_key")
    passphrase = credentials.get("passphrase")

    connect_kwargs: dict = {
        "host": host,
        "port": port,
        "username": username,
        # Host key non vérifié dans le wizard de restauration d'urgence
        "known_hosts": None,
    }
    if private_key_str:
        import asyncssh as _ssh

        pkey = _ssh.import_private_key(
            private_key_str,
            passphrase=passphrase.encode() if passphrase else None,
        )
        connect_kwargs["client_keys"] = [pkey]
    elif password:
        connect_kwargs["password"] = password

    async with asyncssh.connect(**connect_kwargs) as conn:
        async with conn.start_sftp_client() as sftp:
            raw = await sftp.readdir(path)

    entries: list[RemoteEntry] = []
    for entry in raw:
        if entry.filename in (".", ".."):
            continue
        perms = getattr(entry.attrs, "permissions", None) or 0
        is_dir = stat_mod.S_ISDIR(perms)
        mtime = getattr(entry.attrs, "mtime", None)
        size = getattr(entry.attrs, "size", None)
        entries.append(
            RemoteEntry(
                name=entry.filename,
                path=path.rstrip("/") + "/" + entry.filename,
                is_dir=is_dir,
                size_bytes=None if is_dir else size,
                modified_at=(
                    datetime.fromtimestamp(mtime, tz=timezone.utc) if mtime else None
                ),
            )
        )
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


async def _browse_via_provider(
    kind: str,
    config: dict[str, str],
    credentials: dict[str, str | None],
    path: str,
) -> list[RemoteEntry]:
    provider = get_provider(kind, config, credentials)
    files = await provider.list_remote(path)
    return [
        RemoteEntry(
            name=f.filename,
            path=path.rstrip("/") + "/" + f.filename,
            is_dir=False,
            size_bytes=f.size_bytes,
            modified_at=f.last_modified,
        )
        for f in files
    ]
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_restore_wizard_browse_service.py -v
```

Expected : 2 tests PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/restore_wizard_browse_service.py \
        backend/tests/services/test_restore_wizard_browse_service.py
git commit -m "feat(restore): service browse ad-hoc SFTP + providers + tests"
```

---

### Task 5 : Service job runner + tests

**Files:**
- Create: `backend/src/agflow/services/restore_wizard_job_service.py`
- Test: `backend/tests/services/test_restore_wizard_job_service.py`

- [ ] **Step 1 : Écrire le test (rouge)**

```python
# backend/tests/services/test_restore_wizard_job_service.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agflow.schemas.restore_wizard import RestoreExecuteRequest, VaultRef
from agflow.services.restore_wizard_job_service import run_job


@pytest.mark.asyncio
async def test_run_job_success(monkeypatch):
    job_id = uuid4()

    # Mock vault secrets
    async def fake_get_secret(_url, _key, name):
        return f"value-of-{name}"

    # Mock provider download
    async def fake_stream():
        yield b"fake-backup-content"

    fake_provider = MagicMock()
    fake_provider.download_stream = AsyncMock(return_value=fake_stream())

    # Mock db_backup.restore_dump
    async def fake_restore(_stream):
        return {"exit_code": 0, "tail": "Restore OK"}

    # Mock DB operations
    executed = []

    async def fake_execute(sql, *args):
        executed.append((sql, args))

    with (
        patch(
            "agflow.services.restore_wizard_job_service.get_vault_secret_value",
            side_effect=fake_get_secret,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.get_provider",
            return_value=fake_provider,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.db_backup.restore_dump",
            side_effect=fake_restore,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.execute",
            side_effect=fake_execute,
        ),
    ):
        req = RestoreExecuteRequest(
            connection_type="sftp",
            manual_fields={"host": "192.168.1.1", "port": "22"},
            vault_mappings={"username": "remote-backups/user", "private_key": "certificates/key"},
            vault=VaultRef(url="https://vault.test", api_key="k"),
            file_path="/backups/dump.sql.gz",
        )
        await run_job(job_id, req)

    # Vérifie que le status final est 'done'
    done_calls = [c for c in executed if "done" in str(c)]
    assert done_calls, "Le job doit être marqué 'done'"


@pytest.mark.asyncio
async def test_run_job_restore_failure(monkeypatch):
    job_id = uuid4()

    async def fake_get_secret(_url, _key, name):
        return f"v-{name}"

    async def fake_stream():
        yield b"data"

    fake_provider = MagicMock()
    fake_provider.download_stream = AsyncMock(return_value=fake_stream())

    async def fake_restore_fail(_stream):
        return {"exit_code": 1, "tail": "ERROR: relation already exists"}

    executed = []

    async def fake_execute(sql, *args):
        executed.append((sql, args))

    with (
        patch(
            "agflow.services.restore_wizard_job_service.get_vault_secret_value",
            side_effect=fake_get_secret,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.get_provider",
            return_value=fake_provider,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.db_backup.restore_dump",
            side_effect=fake_restore_fail,
        ),
        patch(
            "agflow.services.restore_wizard_job_service.execute",
            side_effect=fake_execute,
        ),
    ):
        req = RestoreExecuteRequest(
            connection_type="sftp",
            manual_fields={"host": "192.168.1.1"},
            vault_mappings={"username": "remote-backups/u"},
            vault=VaultRef(url="https://v.test", api_key="k"),
            file_path="/b/dump.sql.gz",
        )
        await run_job(job_id, req)

    failed_calls = [c for c in executed if "failed" in str(c)]
    assert failed_calls, "Le job doit être marqué 'failed'"
```

- [ ] **Step 2 : Vérifier que le test échoue**

```bash
cd backend && uv run pytest tests/services/test_restore_wizard_job_service.py -v
```

Expected : `ImportError`.

- [ ] **Step 3 : Implémenter le service**

```python
# backend/src/agflow/services/restore_wizard_job_service.py
from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_one
from agflow.schemas.restore_wizard import RestoreExecuteRequest, RestoreJobStatus
from agflow.services import db_backup
from agflow.services.remote_backup_providers.factory import get_provider
from agflow.services.restore_wizard_vault_service import get_vault_secret_value

_log = structlog.get_logger(__name__)

_CHUNK = 65536


async def create_job() -> UUID:
    row = await fetch_one(
        "INSERT INTO restore_jobs (status) VALUES ('running') RETURNING id, status, log, created_at, completed_at",
    )
    return row["id"]


async def get_job(job_id: UUID) -> RestoreJobStatus | None:
    row = await fetch_one(
        "SELECT id, status, log, created_at, completed_at FROM restore_jobs WHERE id = $1",
        job_id,
    )
    if row is None:
        return None
    return RestoreJobStatus(
        job_id=row["id"],
        status=row["status"],
        log=row["log"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


async def _append_log(job_id: UUID, msg: str) -> None:
    await execute(
        "UPDATE restore_jobs SET log = log || $1 WHERE id = $2",
        msg + "\n",
        job_id,
    )


async def _set_done(job_id: UUID, tail: str) -> None:
    await execute(
        "UPDATE restore_jobs SET status = 'done', log = log || $1, completed_at = now() WHERE id = $2",
        tail + "\n",
        job_id,
    )


async def _set_failed(job_id: UUID, error: str) -> None:
    await execute(
        "UPDATE restore_jobs SET status = 'failed', log = log || $1, completed_at = now() WHERE id = $2",
        "ERREUR : " + error + "\n",
        job_id,
    )


async def _resolve_credentials(req: RestoreExecuteRequest) -> dict[str, str | None]:
    credentials: dict[str, str | None] = {}
    for field, secret_name in req.vault_mappings.items():
        if secret_name:
            credentials[field] = await get_vault_secret_value(
                req.vault.url, req.vault.api_key, secret_name
            )
    return credentials


async def _stream_file(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            yield chunk


async def run_job(job_id: UUID, req: RestoreExecuteRequest) -> None:
    tmp_path: Path | None = None
    try:
        await _append_log(job_id, "Résolution des credentials vault...")
        credentials = await _resolve_credentials(req)

        filename = req.file_path.split("/")[-1]
        dir_path = "/".join(req.file_path.split("/")[:-1]) or "/"

        await _append_log(job_id, f"Téléchargement de {filename}...")
        provider = get_provider(req.connection_type, req.manual_fields, credentials)

        fd, tmp_str = tempfile.mkstemp(suffix=f"-{filename}")
        tmp_path = Path(tmp_str)
        try:
            with os.fdopen(fd, "wb") as fh:
                async for chunk in await provider.download_stream(dir_path, filename):
                    fh.write(chunk)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            tmp_path = None
            raise

        await _append_log(job_id, "Restauration de la base en cours...")
        result = await db_backup.restore_dump(_stream_file(tmp_path))

        if result["exit_code"] != 0:
            raise RuntimeError(
                f"pg_restore a échoué (code {result['exit_code']}) :\n{result['tail']}"
            )

        await _set_done(job_id, f"Restauration terminée.\n{result['tail']}")

    except Exception as exc:
        _log.error("restore_wizard.job_failed", job_id=str(job_id), error=str(exc))
        await _set_failed(job_id, str(exc))
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_restore_wizard_job_service.py -v
```

Expected : 2 tests PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/restore_wizard_job_service.py \
        backend/tests/services/test_restore_wizard_job_service.py
git commit -m "feat(restore): service job runner restore + tests"
```

---

### Task 6 : Router FastAPI + wiring main.py

**Files:**
- Create: `backend/src/agflow/api/admin/restore.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1 : Écrire le router**

```python
# backend/src/agflow/api/admin/restore.py
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from agflow.auth.dependencies import require_admin
from agflow.schemas.restore_wizard import (
    RemoteBrowseRequest,
    RemoteEntry,
    RestoreExecuteRequest,
    RestoreJobStarted,
    RestoreJobStatus,
    VaultSecretItem,
    VaultTestRequest,
)
from agflow.services.restore_wizard_browse_service import browse_remote
from agflow.services.restore_wizard_job_service import (
    create_job,
    get_job,
    run_job,
)
from agflow.services.restore_wizard_vault_service import (
    InvalidVaultCredentialsError,
    list_vault_secrets_by_prefix,
    test_vault_connection,
)

router = APIRouter(
    prefix="/api/admin/restore",
    tags=["admin", "restore"],
    dependencies=[Depends(require_admin)],
)


@router.post("/vault/test", status_code=200)
async def vault_test(body: VaultTestRequest) -> dict:
    try:
        await test_vault_connection(body.url, body.api_key)
    except InvalidVaultCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {}


@router.get("/vault/secrets", response_model=list[VaultSecretItem])
async def vault_secrets(
    vault_url: str = Query(...),
    vault_api_key: str = Query(...),
    path: str = Query(default=""),
) -> list[VaultSecretItem]:
    try:
        return await list_vault_secrets_by_prefix(vault_url, vault_api_key, path)
    except InvalidVaultCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.post("/remote/browse", response_model=list[RemoteEntry])
async def remote_browse(body: RemoteBrowseRequest) -> list[RemoteEntry]:
    from agflow.services.restore_wizard_vault_service import get_vault_secret_value

    credentials: dict[str, str | None] = {}
    for field, secret_name in body.vault_mappings.items():
        if secret_name:
            credentials[field] = await get_vault_secret_value(
                body.vault.url, body.vault.api_key, secret_name
            )

    try:
        return await browse_remote(
            connection_type=body.connection_type,
            manual_fields=body.manual_fields,
            credentials=credentials,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/execute", status_code=202, response_model=RestoreJobStarted)
async def execute_restore(
    body: RestoreExecuteRequest,
    background_tasks: BackgroundTasks,
) -> RestoreJobStarted:
    job_id = await create_job()
    background_tasks.add_task(run_job, job_id, body)
    return RestoreJobStarted(job_id=job_id)


@router.get("/execute/{job_id}", response_model=RestoreJobStatus)
async def get_restore_job(job_id: UUID) -> RestoreJobStatus:
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job
```

- [ ] **Step 2 : Ajouter l'import dans main.py**

Dans `backend/src/agflow/main.py`, ajouter avec les autres imports admin (après la ligne `from agflow.api.admin.remote_backup_connections import ...`) :

```python
from agflow.api.admin.restore import router as admin_restore_router
```

- [ ] **Step 3 : Enregistrer le router dans main.py**

Dans la fonction qui appelle `app.include_router(...)`, ajouter après `admin_local_backups_router` :

```python
app.include_router(admin_restore_router)
```

- [ ] **Step 4 : Vérifier que le backend démarre sans erreur**

```bash
cd backend && uv run uvicorn agflow.main:app --reload
```

Expected : `Application startup complete.` sans erreur. Ctrl+C pour arrêter.

- [ ] **Step 5 : Vérifier que les routes sont visibles**

```bash
cd backend && uv run python -c "
from agflow.main import create_app
app = create_app()
routes = [r.path for r in app.routes if hasattr(r, 'path') and 'restore' in r.path]
print(routes)
"
```

Expected : `['/api/admin/restore/vault/test', '/api/admin/restore/vault/secrets', '/api/admin/restore/remote/browse', '/api/admin/restore/execute', '/api/admin/restore/execute/{job_id}']`

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/api/admin/restore.py backend/src/agflow/main.py
git commit -m "feat(restore): router FastAPI + wiring main.py"
```

---

### Task 7 : restoreApi.ts — client API frontend

**Files:**
- Create: `frontend/src/lib/restoreApi.ts`

- [ ] **Step 1 : Écrire le test (rouge)**

```typescript
// frontend/src/lib/__tests__/restoreApi.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../api";
import { restoreApi } from "../restoreApi";

vi.mock("../api", () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

const mockApi = api as { post: ReturnType<typeof vi.fn>; get: ReturnType<typeof vi.fn> };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("restoreApi.testVault", () => {
  it("appelle POST /admin/restore/vault/test", async () => {
    mockApi.post.mockResolvedValue({ data: {} });
    await restoreApi.testVault("https://v.test", "key123");
    expect(mockApi.post).toHaveBeenCalledWith("/admin/restore/vault/test", {
      url: "https://v.test",
      api_key: "key123",
    });
  });
});

describe("restoreApi.listSecrets", () => {
  it("appelle GET /admin/restore/vault/secrets avec params", async () => {
    mockApi.get.mockResolvedValue({ data: [] });
    await restoreApi.listSecrets("https://v.test", "key", "certificates");
    expect(mockApi.get).toHaveBeenCalledWith("/admin/restore/vault/secrets", {
      params: {
        vault_url: "https://v.test",
        vault_api_key: "key",
        path: "certificates",
      },
    });
  });
});

describe("restoreApi.startRestore", () => {
  it("retourne le job_id", async () => {
    const jobId = "abc-123";
    mockApi.post.mockResolvedValue({ data: { job_id: jobId } });
    const result = await restoreApi.startRestore({
      connection_type: "sftp",
      manual_fields: {},
      vault_mappings: {},
      vault: { url: "https://v.test", api_key: "k" },
      file_path: "/backups/dump.sql.gz",
    });
    expect(result.job_id).toBe(jobId);
  });
});
```

- [ ] **Step 2 : Vérifier que le test échoue**

```bash
cd frontend && npm test -- --run src/lib/__tests__/restoreApi.test.ts
```

Expected : `Cannot find module '../restoreApi'`.

- [ ] **Step 3 : Implémenter restoreApi.ts**

```typescript
// frontend/src/lib/restoreApi.ts
import { api } from "./api";

export interface VaultSecretItem {
  name: string;
  tags: string[];
}

export interface RemoteEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size_bytes: number | null;
  modified_at: string | null;
}

export interface RemoteBrowseRequest {
  connection_type: "sftp" | "s3" | "ftps" | "gdrive";
  manual_fields: Record<string, string>;
  vault_mappings: Record<string, string>;
  vault: { url: string; api_key: string };
  path?: string;
}

export interface RestoreExecuteRequest {
  connection_type: "sftp" | "s3" | "ftps" | "gdrive";
  manual_fields: Record<string, string>;
  vault_mappings: Record<string, string>;
  vault: { url: string; api_key: string };
  file_path: string;
}

export interface RestoreJobStatus {
  job_id: string;
  status: "running" | "done" | "failed";
  log: string;
  created_at: string;
  completed_at: string | null;
}

export const restoreApi = {
  async testVault(url: string, apiKey: string): Promise<void> {
    await api.post("/admin/restore/vault/test", { url, api_key: apiKey });
  },

  async listSecrets(
    vaultUrl: string,
    vaultApiKey: string,
    path: string,
  ): Promise<VaultSecretItem[]> {
    const res = await api.get<VaultSecretItem[]>("/admin/restore/vault/secrets", {
      params: { vault_url: vaultUrl, vault_api_key: vaultApiKey, path },
    });
    return res.data;
  },

  async browse(body: RemoteBrowseRequest): Promise<RemoteEntry[]> {
    const res = await api.post<RemoteEntry[]>("/admin/restore/remote/browse", body);
    return res.data;
  },

  async startRestore(body: RestoreExecuteRequest): Promise<{ job_id: string }> {
    const res = await api.post<{ job_id: string }>("/admin/restore/execute", body);
    return res.data;
  },

  async getJobStatus(jobId: string): Promise<RestoreJobStatus> {
    const res = await api.get<RestoreJobStatus>(`/admin/restore/execute/${jobId}`);
    return res.data;
  },
};
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd frontend && npm test -- --run src/lib/__tests__/restoreApi.test.ts
```

Expected : 3 tests PASSED.

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/lib/restoreApi.ts frontend/src/lib/__tests__/restoreApi.test.ts
git commit -m "feat(restore): restoreApi.ts client + tests"
```

---

### Task 8 : Route + sidebar + squelette RestorePage

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Create: `frontend/src/pages/RestorePage.tsx`
- Create: `frontend/src/components/restore/RestoreTimelineItem.tsx`

- [ ] **Step 1 : Créer RestoreTimelineItem**

```tsx
// frontend/src/components/restore/RestoreTimelineItem.tsx
import type { JSX } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface RestoreTimelineItemProps {
  step: number;
  title: string;
  status: "pending" | "active" | "done";
  children?: React.ReactNode;
}

export function RestoreTimelineItem({
  step,
  title,
  status,
  children,
}: RestoreTimelineItemProps): JSX.Element {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <div
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-bold shrink-0",
            status === "done" && "border-green-500 bg-green-500 text-white",
            status === "active" && "border-primary bg-primary text-primary-foreground",
            status === "pending" && "border-muted-foreground text-muted-foreground",
          )}
        >
          {status === "done" ? <Check className="h-4 w-4" /> : step}
        </div>
        <div className={cn("mt-2 w-0.5 flex-1 bg-border", status === "pending" && "bg-muted")} />
      </div>
      <div className="pb-8 flex-1 min-w-0">
        <h3
          className={cn(
            "mb-3 text-sm font-semibold",
            status === "pending" && "text-muted-foreground",
          )}
        >
          {title}
        </h3>
        {status !== "pending" && children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2 : Créer le squelette RestorePage**

```tsx
// frontend/src/pages/RestorePage.tsx
import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RestoreTimelineItem } from "@/components/restore/RestoreTimelineItem";

export interface RestoreWizardState {
  step: 1 | 2 | 3 | 4;
  vault: { url: string; apiKey: string } | null;
  secrets: { name: string; tags: string[] }[];
  connectionType: "sftp" | "s3" | "ftps" | "gdrive" | null;
  manualFields: Record<string, string>;
  vaultMappings: Record<string, string>;
  selectedFile: { path: string; name: string; size_bytes: number | null } | null;
  jobId: string | null;
}

const INITIAL_STATE: RestoreWizardState = {
  step: 1,
  vault: null,
  secrets: [],
  connectionType: null,
  manualFields: {},
  vaultMappings: {},
  selectedFile: null,
  jobId: null,
};

export function RestorePage(): JSX.Element {
  const { t } = useTranslation();
  const [state, setState] = useState<RestoreWizardState>(INITIAL_STATE);

  function stepStatus(n: number): "pending" | "active" | "done" {
    if (state.step > n) return "done";
    if (state.step === n) return "active";
    return "pending";
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-8 space-y-1">
        <h1 className="text-2xl font-bold">{t("restore.page_title")}</h1>
        <p className="text-sm text-muted-foreground">{t("restore.page_subtitle")}</p>
      </div>

      <RestoreTimelineItem step={1} title={t("restore.step_vault")} status={stepStatus(1)}>
        <p className="text-sm text-muted-foreground">étape 1 — à implémenter</p>
      </RestoreTimelineItem>

      <RestoreTimelineItem step={2} title={t("restore.step_connection")} status={stepStatus(2)}>
        <p className="text-sm text-muted-foreground">étape 2 — à implémenter</p>
      </RestoreTimelineItem>

      <RestoreTimelineItem step={3} title={t("restore.step_browse")} status={stepStatus(3)}>
        <p className="text-sm text-muted-foreground">étape 3 — à implémenter</p>
      </RestoreTimelineItem>

      <RestoreTimelineItem step={4} title={t("restore.step_confirm")} status={stepStatus(4)}>
        <p className="text-sm text-muted-foreground">étape 4 — à implémenter</p>
      </RestoreTimelineItem>
    </div>
  );
}
```

- [ ] **Step 3 : Ajouter la route dans App.tsx**

Dans `frontend/src/App.tsx`, ajouter l'import avec les autres pages :

```tsx
import { RestorePage } from "@/pages/RestorePage";
```

Ajouter la route après la route `/backups` (vers la ligne 283) :

```tsx
<Route
  path="/restore"
  element={
    <ProtectedRoute>
      <AppLayout>
        <RestorePage />
      </AppLayout>
    </ProtectedRoute>
  }
/>
```

- [ ] **Step 4 : Ajouter l'entrée dans la sidebar**

Dans `frontend/src/components/layout/Sidebar.tsx`, ajouter `RotateCcw` dans l'import lucide (ligne 3) :

```tsx
import {
  // ... existants ...
  RotateCcw,
  // ...
} from "lucide-react";
```

Dans le tableau `sections`, dans la section `section_backups` (vers ligne 124), ajouter après l'entrée `/backup-remotes` :

```tsx
{ to: "/restore", label: t("restore.nav_label"), icon: RotateCcw },
```

- [ ] **Step 5 : Vérifier visuellement**

```bash
cd frontend && npm run dev
```

Naviguer sur `http://localhost:5173/restore`. La page doit afficher la timeline avec 4 étapes (step 1 active, 2-4 grisées). Vérifier qu'il n'y a pas d'erreur console.

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/components/restore/RestoreTimelineItem.tsx \
        frontend/src/pages/RestorePage.tsx \
        frontend/src/App.tsx \
        frontend/src/components/layout/Sidebar.tsx
git commit -m "feat(restore): squelette page + timeline item + route + sidebar"
```

---

### Task 9 : VaultConnectStep — étape 1

**Files:**
- Create: `frontend/src/components/restore/VaultConnectStep.tsx`

- [ ] **Step 1 : Implémenter VaultConnectStep**

```tsx
// frontend/src/components/restore/VaultConnectStep.tsx
import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { restoreApi, type VaultSecretItem } from "@/lib/restoreApi";

interface VaultConnectStepProps {
  onDone: (vault: { url: string; apiKey: string }, secrets: VaultSecretItem[]) => void;
}

export function VaultConnectStep({ onDone }: VaultConnectStepProps): JSX.Element {
  const { t } = useTranslation();
  const [url, setUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      await restoreApi.testVault(url, apiKey);
      const secrets = await restoreApi.listSecrets(url, apiKey, "");
      return secrets;
    },
    onSuccess: (secrets) => {
      onDone({ url, apiKey }, secrets);
    },
    onError: () => {
      toast.error(t("restore.vault_connect_error"));
    },
  });

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="vault-url">{t("restore.vault_url_label")}</Label>
        <Input
          id="vault-url"
          placeholder="https://vault.example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="vault-apikey">{t("restore.vault_apikey_label")}</Label>
        <Input
          id="vault-apikey"
          type="password"
          placeholder="•••••••••••••"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>
      <Button
        onClick={() => mutation.mutate()}
        disabled={!url || !apiKey || mutation.isPending}
      >
        {mutation.isPending ? t("common.loading") : t("restore.btn_connect_vault")}
      </Button>
    </div>
  );
}
```

- [ ] **Step 2 : Brancher dans RestorePage**

Dans `frontend/src/pages/RestorePage.tsx`, remplacer le contenu de l'étape 1 :

```tsx
// Ajouter l'import en haut
import { VaultConnectStep } from "@/components/restore/VaultConnectStep";
import type { VaultSecretItem } from "@/lib/restoreApi";

// Remplacer le contenu de la première RestoreTimelineItem
<RestoreTimelineItem step={1} title={t("restore.step_vault")} status={stepStatus(1)}>
  <VaultConnectStep
    onDone={(vault, secrets) =>
      setState((s) => ({ ...s, step: 2, vault, secrets }))
    }
  />
</RestoreTimelineItem>
```

- [ ] **Step 3 : Vérifier visuellement**

```bash
cd frontend && npm run dev
```

Sur `/restore` : remplir URL + API key → clic "Connecter le vault" → l'étape 1 doit passer en vert et l'étape 2 s'activer.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/restore/VaultConnectStep.tsx \
        frontend/src/pages/RestorePage.tsx
git commit -m "feat(restore): VaultConnectStep etape 1"
```

---

### Task 10 : VaultSecretPicker + RemoteConnectionStep — étape 2

**Files:**
- Create: `frontend/src/components/restore/VaultSecretPicker.tsx`
- Create: `frontend/src/components/restore/RemoteConnectionStep.tsx`

- [ ] **Step 1 : Implémenter VaultSecretPicker**

```tsx
// frontend/src/components/restore/VaultSecretPicker.tsx
import type { JSX } from "react";
import { useTranslation } from "react-i18next";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { VaultSecretItem } from "@/lib/restoreApi";

interface VaultSecretPickerProps {
  label: string;
  secrets: VaultSecretItem[];
  value: string;
  onChange: (value: string) => void;
  optional?: boolean;
}

export function VaultSecretPicker({
  label,
  secrets,
  value,
  onChange,
  optional = false,
}: VaultSecretPickerProps): JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="space-y-1">
      <Label>{label}{optional && <span className="ml-1 text-muted-foreground text-xs">({t("common.optional")})</span>}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger>
          <SelectValue placeholder={t("restore.picker_placeholder")} />
        </SelectTrigger>
        <SelectContent>
          {optional && (
            <SelectItem value="">{t("restore.picker_none")}</SelectItem>
          )}
          {secrets.map((s) => (
            <SelectItem key={s.name} value={s.name}>
              <span className="font-mono text-sm">{s.name}</span>
              {s.tags.length > 0 && (
                <span className="ml-2 text-muted-foreground text-xs">
                  [{s.tags.join(", ")}]
                </span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
```

- [ ] **Step 2 : Implémenter RemoteConnectionStep**

```tsx
// frontend/src/components/restore/RemoteConnectionStep.tsx
import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { VaultSecretPicker } from "./VaultSecretPicker";
import { restoreApi, type VaultSecretItem } from "@/lib/restoreApi";

type ConnectionType = "sftp" | "s3" | "ftps" | "gdrive";

interface ConnectionConfig {
  type: ConnectionType;
  manual: Record<string, string>;
  vault: Record<string, string>;
}

interface RemoteConnectionStepProps {
  vaultUrl: string;
  vaultApiKey: string;
  secrets: VaultSecretItem[];
  onDone: (config: ConnectionConfig) => void;
}

// Définition des champs par type de connexion
const FIELDS: Record<
  ConnectionType,
  {
    manual: { key: string; label: string; placeholder?: string; required?: boolean }[];
    vault: { key: string; label: string; optional?: boolean; prefix?: string }[];
  }
> = {
  sftp: {
    manual: [
      { key: "host", label: "Host", placeholder: "192.168.1.1", required: true },
      { key: "port", label: "Port", placeholder: "22" },
      { key: "path", label: "Répertoire racine", placeholder: "/backups" },
    ],
    vault: [
      { key: "username", label: "Nom d'utilisateur", prefix: "remote-backups" },
      { key: "password", label: "Mot de passe", optional: true, prefix: "remote-backups" },
      { key: "private_key", label: "Clé privée SSH", optional: true, prefix: "certificates" },
      { key: "passphrase", label: "Passphrase clé", optional: true, prefix: "remote-backups" },
    ],
  },
  s3: {
    manual: [
      { key: "bucket", label: "Bucket", required: true },
      { key: "region", label: "Région", placeholder: "eu-west-1", required: true },
      { key: "prefix", label: "Préfixe", placeholder: "backups/" },
    ],
    vault: [
      { key: "access_key_id", label: "Access Key ID" },
      { key: "secret_access_key", label: "Secret Access Key" },
    ],
  },
  ftps: {
    manual: [
      { key: "host", label: "Host", required: true },
      { key: "port", label: "Port", placeholder: "21" },
      { key: "path", label: "Répertoire racine", placeholder: "/backups" },
    ],
    vault: [
      { key: "username", label: "Nom d'utilisateur" },
      { key: "password", label: "Mot de passe" },
    ],
  },
  gdrive: {
    manual: [],
    vault: [{ key: "credentials_json", label: "Credentials JSON" }],
  },
};

export function RemoteConnectionStep({
  vaultUrl,
  vaultApiKey,
  secrets,
  onDone,
}: RemoteConnectionStepProps): JSX.Element {
  const { t } = useTranslation();
  const [type, setType] = useState<ConnectionType>("sftp");
  const [manual, setManual] = useState<Record<string, string>>({});
  const [vaultMap, setVaultMap] = useState<Record<string, string>>({});

  const fields = FIELDS[type];

  function setManualField(key: string, value: string) {
    setManual((prev) => ({ ...prev, [key]: value }));
  }

  function setVaultField(key: string, value: string) {
    setVaultMap((prev) => ({ ...prev, [key]: value }));
  }

  function secretsForField(prefix?: string): VaultSecretItem[] {
    if (!prefix) return secrets;
    return secrets.filter((s) => s.name.startsWith(prefix + "/"));
  }

  const testMutation = useMutation({
    mutationFn: () =>
      restoreApi.browse({
        connection_type: type,
        manual_fields: { ...manual, path: manual.path ?? "/" },
        vault_mappings: vaultMap,
        vault: { url: vaultUrl, api_key: vaultApiKey },
        path: manual.path ?? "/",
      }),
    onSuccess: () => {
      onDone({ type, manual, vault: vaultMap });
    },
    onError: () => {
      toast.error(t("restore.connection_test_error"));
    },
  });

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <Label>{t("restore.connection_type_label")}</Label>
        <Select
          value={type}
          onValueChange={(v) => {
            setType(v as ConnectionType);
            setManual({});
            setVaultMap({});
          }}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="sftp">SFTP</SelectItem>
            <SelectItem value="s3">S3</SelectItem>
            <SelectItem value="ftps">FTPS</SelectItem>
            <SelectItem value="gdrive">Google Drive</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {fields.manual.map((f) => (
        <div key={f.key} className="space-y-1">
          <Label htmlFor={`manual-${f.key}`}>{f.label}</Label>
          <Input
            id={`manual-${f.key}`}
            placeholder={f.placeholder}
            value={manual[f.key] ?? ""}
            onChange={(e) => setManualField(f.key, e.target.value)}
          />
        </div>
      ))}

      {fields.vault.map((f) => (
        <VaultSecretPicker
          key={f.key}
          label={f.label}
          secrets={secretsForField(f.prefix)}
          value={vaultMap[f.key] ?? ""}
          onChange={(v) => setVaultField(f.key, v)}
          optional={f.optional}
        />
      ))}

      <Button
        onClick={() => testMutation.mutate()}
        disabled={testMutation.isPending}
      >
        {testMutation.isPending ? t("common.loading") : t("restore.btn_test_connection")}
      </Button>
    </div>
  );
}
```

- [ ] **Step 3 : Brancher dans RestorePage**

Dans `frontend/src/pages/RestorePage.tsx` :

```tsx
// Ajouter les imports
import { RemoteConnectionStep } from "@/components/restore/RemoteConnectionStep";

// Remplacer le contenu de la RestoreTimelineItem step=2
<RestoreTimelineItem step={2} title={t("restore.step_connection")} status={stepStatus(2)}>
  {state.vault && (
    <RemoteConnectionStep
      vaultUrl={state.vault.url}
      vaultApiKey={state.vault.apiKey}
      secrets={state.secrets}
      onDone={(cfg) =>
        setState((s) => ({
          ...s,
          step: 3,
          connectionType: cfg.type,
          manualFields: cfg.manual,
          vaultMappings: cfg.vault,
        }))
      }
    />
  )}
</RestoreTimelineItem>
```

- [ ] **Step 4 : Vérifier visuellement**

```bash
cd frontend && npm run dev
```

Sur `/restore` : après vault connecté, l'étape 2 s'active. Sélectionner le type, remplir les champs, choisir les secrets dans les pickers. Clic "Tester la connexion" → si OK, étape 3 s'active.

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/components/restore/VaultSecretPicker.tsx \
        frontend/src/components/restore/RemoteConnectionStep.tsx \
        frontend/src/pages/RestorePage.tsx
git commit -m "feat(restore): VaultSecretPicker + RemoteConnectionStep etape 2"
```

---

### Task 11 : RemoteFileBrowser — étape 3

**Files:**
- Create: `frontend/src/components/restore/RemoteFileBrowser.tsx`

- [ ] **Step 1 : Implémenter RemoteFileBrowser**

```tsx
// frontend/src/components/restore/RemoteFileBrowser.tsx
import type { JSX } from "react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Folder, File, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { restoreApi, type RemoteEntry } from "@/lib/restoreApi";

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isBackupFile(name: string): boolean {
  return name.endsWith(".sql.gz") || name.endsWith(".dump") || name.endsWith(".sql");
}

interface RemoteFileBrowserProps {
  vaultUrl: string;
  vaultApiKey: string;
  connectionType: "sftp" | "s3" | "ftps" | "gdrive";
  manualFields: Record<string, string>;
  vaultMappings: Record<string, string>;
  onSelect: (file: { path: string; name: string; size_bytes: number | null }) => void;
}

export function RemoteFileBrowser({
  vaultUrl,
  vaultApiKey,
  connectionType,
  manualFields,
  vaultMappings,
  onSelect,
}: RemoteFileBrowserProps): JSX.Element {
  const { t } = useTranslation();
  const [currentPath, setCurrentPath] = useState(manualFields.path ?? "/");
  const [breadcrumbs, setBreadcrumbs] = useState<string[]>([currentPath]);

  const { data: entries = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["restore-browse", connectionType, currentPath, vaultMappings],
    queryFn: () =>
      restoreApi.browse({
        connection_type: connectionType,
        manual_fields: manualFields,
        vault_mappings: vaultMappings,
        vault: { url: vaultUrl, api_key: vaultApiKey },
        path: currentPath,
      }),
  });

  function navigateTo(path: string) {
    setCurrentPath(path);
    setBreadcrumbs((prev) => [...prev, path]);
  }

  function navigateToBreadcrumb(index: number) {
    const path = breadcrumbs[index];
    if (!path) return;
    setBreadcrumbs((prev) => prev.slice(0, index + 1));
    setCurrentPath(path);
  }

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">{t("common.loading")}</p>;
  }

  if (isError) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-destructive">{t("restore.browse_error")}</p>
        <button className="text-sm text-primary underline" onClick={() => void refetch()}>
          {t("common.retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Fil d'Ariane */}
      <div className="flex items-center gap-1 text-sm text-muted-foreground flex-wrap">
        {breadcrumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="h-3 w-3" />}
            <button
              className={cn(
                "hover:text-foreground",
                i === breadcrumbs.length - 1 && "text-foreground font-medium",
              )}
              onClick={() => navigateToBreadcrumb(i)}
            >
              {i === 0 ? t("restore.browse_root") : crumb.split("/").at(-1)}
            </button>
          </span>
        ))}
      </div>

      {/* Liste des entrées */}
      <div className="rounded-md border divide-y">
        {entries.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            {t("restore.browse_empty")}
          </p>
        )}
        {entries.map((entry) => (
          <button
            key={entry.path}
            className={cn(
              "flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-muted/50 transition-colors",
              isBackupFile(entry.name) && "hover:bg-primary/5",
            )}
            onClick={() => {
              if (entry.is_dir) {
                navigateTo(entry.path);
              } else if (isBackupFile(entry.name)) {
                onSelect({ path: entry.path, name: entry.name, size_bytes: entry.size_bytes });
              }
            }}
          >
            {entry.is_dir ? (
              <Folder className="h-4 w-4 text-yellow-500 shrink-0" />
            ) : (
              <File
                className={cn(
                  "h-4 w-4 shrink-0",
                  isBackupFile(entry.name) ? "text-primary" : "text-muted-foreground",
                )}
              />
            )}
            <span className={cn("flex-1 text-sm", !entry.is_dir && !isBackupFile(entry.name) && "text-muted-foreground")}>
              {entry.name}
            </span>
            {!entry.is_dir && (
              <span className="text-xs text-muted-foreground">{formatBytes(entry.size_bytes)}</span>
            )}
            {isBackupFile(entry.name) && (
              <span className="text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                backup
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2 : Brancher dans RestorePage**

Dans `frontend/src/pages/RestorePage.tsx` :

```tsx
// Ajouter l'import
import { RemoteFileBrowser } from "@/components/restore/RemoteFileBrowser";

// Remplacer le contenu de la RestoreTimelineItem step=3
<RestoreTimelineItem step={3} title={t("restore.step_browse")} status={stepStatus(3)}>
  {state.vault && state.connectionType && (
    <RemoteFileBrowser
      vaultUrl={state.vault.url}
      vaultApiKey={state.vault.apiKey}
      connectionType={state.connectionType}
      manualFields={state.manualFields}
      vaultMappings={state.vaultMappings}
      onSelect={(file) =>
        setState((s) => ({ ...s, step: 4, selectedFile: file }))
      }
    />
  )}
</RestoreTimelineItem>
```

- [ ] **Step 3 : Vérifier visuellement**

Après étapes 1 et 2 complétées, l'étape 3 affiche la liste des fichiers. Dossiers = clic navigue, fichiers `.sql.gz`/`.dump` = badge "backup" + clic sélectionne et passe à l'étape 4.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/restore/RemoteFileBrowser.tsx \
        frontend/src/pages/RestorePage.tsx
git commit -m "feat(restore): RemoteFileBrowser navigation SFTP etape 3"
```

---

### Task 12 : RestoreConfirmStep + RestorePage assemblage final — étape 4

**Files:**
- Create: `frontend/src/components/restore/RestoreConfirmStep.tsx`
- Modify: `frontend/src/pages/RestorePage.tsx`

- [ ] **Step 1 : Implémenter RestoreConfirmStep**

```tsx
// frontend/src/components/restore/RestoreConfirmStep.tsx
import type { JSX } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { restoreApi, type RestoreExecuteRequest } from "@/lib/restoreApi";

interface RestoreConfirmStepProps {
  request: RestoreExecuteRequest;
  selectedFileName: string;
  selectedFileSize: number | null;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function RestoreConfirmStep({
  request,
  selectedFileName,
  selectedFileSize,
}: RestoreConfirmStepProps): JSX.Element {
  const { t } = useTranslation();

  const startMutation = useMutation({
    mutationFn: () => restoreApi.startRestore(request),
  });

  const jobId = startMutation.data?.job_id ?? null;

  const { data: jobStatus } = useQuery({
    queryKey: ["restore-job", jobId],
    queryFn: () => restoreApi.getJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 2000 : false,
  });

  const status = jobStatus?.status ?? null;

  return (
    <div className="space-y-5">
      {/* Résumé */}
      <div className="rounded-md border p-4 space-y-2 text-sm bg-muted/30">
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("restore.summary_file")}</span>
          <span className="font-mono font-medium">{selectedFileName}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("restore.summary_size")}</span>
          <span>{formatBytes(selectedFileSize)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("restore.summary_type")}</span>
          <span className="uppercase">{request.connection_type}</span>
        </div>
      </div>

      {/* Avertissement */}
      {!jobId && (
        <p className="text-sm text-amber-600">
          {t("restore.confirm_warning")}
        </p>
      )}

      {/* Bouton restaurer */}
      {!jobId && (
        <Button
          variant="destructive"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending}
        >
          {startMutation.isPending ? t("common.loading") : t("restore.btn_restore")}
        </Button>
      )}

      {/* Progression */}
      {jobId && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            {status === "running" && (
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
            )}
            {status === "done" && (
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            )}
            {status === "failed" && (
              <XCircle className="h-4 w-4 text-destructive" />
            )}
            <span className="text-sm font-medium">
              {status === "running" && t("restore.status_running")}
              {status === "done" && t("restore.status_done")}
              {status === "failed" && t("restore.status_failed")}
            </span>
          </div>
          {jobStatus?.log && (
            <pre className="rounded-md bg-muted p-3 text-xs font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">
              {jobStatus.log}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2 : Brancher dans RestorePage (assemblage final)**

Remplacer le contenu complet de `frontend/src/pages/RestorePage.tsx` :

```tsx
// frontend/src/pages/RestorePage.tsx
import type { JSX } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { RestoreTimelineItem } from "@/components/restore/RestoreTimelineItem";
import { VaultConnectStep } from "@/components/restore/VaultConnectStep";
import { RemoteConnectionStep } from "@/components/restore/RemoteConnectionStep";
import { RemoteFileBrowser } from "@/components/restore/RemoteFileBrowser";
import { RestoreConfirmStep } from "@/components/restore/RestoreConfirmStep";
import type { VaultSecretItem } from "@/lib/restoreApi";

interface RestoreWizardState {
  step: 1 | 2 | 3 | 4;
  vault: { url: string; apiKey: string } | null;
  secrets: VaultSecretItem[];
  connectionType: "sftp" | "s3" | "ftps" | "gdrive" | null;
  manualFields: Record<string, string>;
  vaultMappings: Record<string, string>;
  selectedFile: { path: string; name: string; size_bytes: number | null } | null;
}

const INITIAL_STATE: RestoreWizardState = {
  step: 1,
  vault: null,
  secrets: [],
  connectionType: null,
  manualFields: {},
  vaultMappings: {},
  selectedFile: null,
};

export function RestorePage(): JSX.Element {
  const { t } = useTranslation();
  const [state, setState] = useState<RestoreWizardState>(INITIAL_STATE);

  function stepStatus(n: number): "pending" | "active" | "done" {
    if (state.step > n) return "done";
    if (state.step === n) return "active";
    return "pending";
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-8 space-y-1">
        <h1 className="text-2xl font-bold">{t("restore.page_title")}</h1>
        <p className="text-sm text-muted-foreground">{t("restore.page_subtitle")}</p>
      </div>

      <RestoreTimelineItem step={1} title={t("restore.step_vault")} status={stepStatus(1)}>
        <VaultConnectStep
          onDone={(vault, secrets) =>
            setState((s) => ({ ...s, step: 2, vault, secrets }))
          }
        />
      </RestoreTimelineItem>

      <RestoreTimelineItem step={2} title={t("restore.step_connection")} status={stepStatus(2)}>
        {state.vault && (
          <RemoteConnectionStep
            vaultUrl={state.vault.url}
            vaultApiKey={state.vault.apiKey}
            secrets={state.secrets}
            onDone={(cfg) =>
              setState((s) => ({
                ...s,
                step: 3,
                connectionType: cfg.type,
                manualFields: cfg.manual,
                vaultMappings: cfg.vault,
              }))
            }
          />
        )}
      </RestoreTimelineItem>

      <RestoreTimelineItem step={3} title={t("restore.step_browse")} status={stepStatus(3)}>
        {state.vault && state.connectionType && (
          <RemoteFileBrowser
            vaultUrl={state.vault.url}
            vaultApiKey={state.vault.apiKey}
            connectionType={state.connectionType}
            manualFields={state.manualFields}
            vaultMappings={state.vaultMappings}
            onSelect={(file) =>
              setState((s) => ({ ...s, step: 4, selectedFile: file }))
            }
          />
        )}
      </RestoreTimelineItem>

      <RestoreTimelineItem step={4} title={t("restore.step_confirm")} status={stepStatus(4)}>
        {state.vault && state.connectionType && state.selectedFile && (
          <RestoreConfirmStep
            request={{
              connection_type: state.connectionType,
              manual_fields: state.manualFields,
              vault_mappings: state.vaultMappings,
              vault: { url: state.vault.url, api_key: state.vault.apiKey },
              file_path: state.selectedFile.path,
            }}
            selectedFileName={state.selectedFile.name}
            selectedFileSize={state.selectedFile.size_bytes}
          />
        )}
      </RestoreTimelineItem>
    </div>
  );
}
```

- [ ] **Step 3 : Vérifier le parcours complet visuellement**

```bash
cd frontend && npm run dev
```

Parcourir les 4 étapes en entier sur `/restore`. Vérifier :
- Étapes 1→2→3→4 progressent correctement
- Étapes complétées affichent une coche verte
- L'étape 4 affiche le récapitulatif + bouton "Restaurer"
- Aucune erreur console TypeScript

- [ ] **Step 4 : Vérifier le type check**

```bash
cd frontend && npx tsc --noEmit
```

Expected : aucune erreur.

- [ ] **Step 5 : Commit**

```bash
git add frontend/src/components/restore/RestoreConfirmStep.tsx \
        frontend/src/pages/RestorePage.tsx
git commit -m "feat(restore): RestoreConfirmStep + assemblage page finale etape 4"
```

---

### Task 13 : i18n — clés fr + en

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés dans fr.json**

Dans `frontend/src/i18n/fr.json`, ajouter la clé `"restore"` au niveau racine :

```json
"restore": {
  "nav_label": "Restauration",
  "page_title": "Restaurer la base de données",
  "page_subtitle": "Importez un backup depuis un stockage distant en utilisant vos credentials vault.",
  "step_vault": "Connexion au vault",
  "step_connection": "Connexion distante",
  "step_browse": "Sélection du backup",
  "step_confirm": "Confirmation et restauration",
  "vault_url_label": "URL du vault",
  "vault_apikey_label": "API key",
  "btn_connect_vault": "Connecter le vault",
  "vault_connect_error": "Impossible de se connecter au vault. Vérifiez l'URL et la clé.",
  "connection_type_label": "Type de connexion",
  "btn_test_connection": "Tester la connexion",
  "connection_test_error": "Connexion au remote échouée. Vérifiez les paramètres.",
  "picker_placeholder": "Choisir un secret...",
  "picker_none": "Aucun (optionnel)",
  "browse_root": "Racine",
  "browse_empty": "Répertoire vide",
  "browse_error": "Impossible de lister les fichiers. Vérifiez la connexion.",
  "summary_file": "Fichier",
  "summary_size": "Taille",
  "summary_type": "Type de connexion",
  "confirm_warning": "⚠️ La restauration va écraser la base de données actuelle. Cette opération est irréversible.",
  "btn_restore": "Restaurer la base",
  "status_running": "Restauration en cours...",
  "status_done": "Restauration terminée avec succès.",
  "status_failed": "La restauration a échoué."
}
```

- [ ] **Step 2 : Ajouter les clés dans en.json**

Dans `frontend/src/i18n/en.json`, ajouter la clé `"restore"` au niveau racine :

```json
"restore": {
  "nav_label": "Restore",
  "page_title": "Restore database",
  "page_subtitle": "Import a backup from remote storage using your vault credentials.",
  "step_vault": "Vault connection",
  "step_connection": "Remote connection",
  "step_browse": "Select backup",
  "step_confirm": "Confirm and restore",
  "vault_url_label": "Vault URL",
  "vault_apikey_label": "API key",
  "btn_connect_vault": "Connect vault",
  "vault_connect_error": "Cannot connect to vault. Check the URL and key.",
  "connection_type_label": "Connection type",
  "btn_test_connection": "Test connection",
  "connection_test_error": "Remote connection failed. Check the parameters.",
  "picker_placeholder": "Choose a secret...",
  "picker_none": "None (optional)",
  "browse_root": "Root",
  "browse_empty": "Empty directory",
  "browse_error": "Cannot list files. Check the connection.",
  "summary_file": "File",
  "summary_size": "Size",
  "summary_type": "Connection type",
  "confirm_warning": "⚠️ Restoring will overwrite the current database. This operation is irreversible.",
  "btn_restore": "Restore database",
  "status_running": "Restore in progress...",
  "status_done": "Restore completed successfully.",
  "status_failed": "Restore failed."
}
```

- [ ] **Step 3 : Vérifier qu'il n'y a pas de clé manquante**

```bash
cd frontend && npm run dev
```

Naviguer sur `/restore`. Aucune clé `restore.*` ne doit apparaître brute dans l'UI.

- [ ] **Step 4 : Vérifier le lint**

```bash
cd frontend && npm run lint
```

Expected : aucune erreur.

- [ ] **Step 5 : Commit final**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(restore): i18n fr + en clés restore wizard"
```
