# Restore Flow Remote → Local Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Boucler le chantier `remote-backups` en ajoutant le flow inverse : lister les fichiers présents sur un remote (SFTP/FTPS/S3), tirer un fichier vers `local_backups`, puis restaurer un backup local dans Postgres (DROP + recreate).

**Architecture:** Flow en 2 étapes côté admin (pull puis restore). Côté backend : extension du `Protocol` provider avec `list_remote` + `download_stream`, service `pull_remote_to_local` (réutilise `backup_lock` et le dossier `agflow_data_dir/backups`), service `restore_local_backup` (réutilise `db_backup.restore_dump` existant). Colonne `source_remote_connection_id` ajoutée à `local_backups` pour traçabilité. Côté frontend : nouvelle page `/backups` avec 2 sections (locaux + sélecteur de remote), `RestoreConfirmDialog` exige la saisie exacte du filename avant DROP.

**Tech Stack:** asyncpg + asyncssh (SFTP) + aioftp (FTPS) + boto3 (S3) + aiodocker (restore via pg) + FastAPI + Pydantic v2 / Vite + React 18 + TanStack Query + shadcn Dialog + i18next + Vitest

---

## File Structure

### Backend — fichiers à créer

```
backend/migrations/
  104_local_backups_source_remote.sql                    # Ajoute source_remote_connection_id

backend/src/agflow/schemas/
  remote_backup_files.py                                 # RemoteBackupFile, PullRequest, RestoreResult
                                                          # + ajout source_remote_connection_id dans LocalBackupSummary

backend/src/agflow/services/
  restore_service.py                                     # restore_local_backup() — lock + fichier + db_backup.restore_dump

backend/tests/services/
  test_pull_remote.py                                    # tests pull_remote_to_local (avec provider mocké)
  test_restore_service.py                                # tests restore_local_backup
  test_remote_backup_providers_listing.py                # tests des 3 providers (list + download mockés)
  test_local_backups_source_remote.py                    # tests migration + insert avec source_remote_connection_id
backend/tests/api/
  test_remote_backup_files_endpoints.py                  # tests endpoints (3 routes)
```

### Backend — fichiers à modifier

```
backend/src/agflow/services/remote_backup_providers/
  protocol.py                                            # Ajout list_remote + download_stream au Protocol + dataclass RemoteFile
  sftp_provider.py                                       # Impl list_remote + download_stream
  ftps_provider.py                                       # Impl list_remote + download_stream
  s3_provider.py                                         # Impl list_remote + download_stream

backend/src/agflow/services/
  local_backups_service.py                               # Ajout pull_remote_to_local() + _to_dto avec source_remote_connection_id

backend/src/agflow/schemas/
  local_backups.py                                       # Ajout source_remote_connection_id: UUID | None

backend/src/agflow/api/admin/
  remote_backup_connections.py                           # Ajout GET /{id}/files
  local_backups.py                                       # Ajout POST /pull-from-remote/{remote_id} + POST /{id}/restore

backend/src/agflow/main.py                               # Vérifier que les nouvelles routes sont incluses (probablement déjà OK)
```

### Frontend — fichiers à créer

```
frontend/src/lib/
  backupsApi.ts                                          # listRemoteFiles, pullFromRemote, restoreLocal + types

frontend/src/hooks/
  useBackups.ts                                          # useLocalBackups, useRemoteFiles, usePullMutation, useRestoreMutation

frontend/src/components/
  RestoreConfirmDialog.tsx                               # Dialog avec input qui doit matcher exactement le filename
  LocalBackupsSection.tsx                                # Table backups locaux avec actions push/restore/delete
  RemoteBackupsBrowser.tsx                               # Sélecteur connexion + liste fichiers distants + bouton Pull

frontend/src/pages/
  BackupsPage.tsx                                        # Composition des deux sections

frontend/src/__tests__/
  RestoreConfirmDialog.test.tsx                          # Test Vitest du dialog (cas mismatch / match / cancel)
  BackupsPage.test.tsx                                   # Test Vitest de la page (mock API)
```

### Frontend — fichiers à modifier

```
frontend/src/App.tsx                                     # Ajouter <Route path="/backups" element={<BackupsPage />} />
frontend/src/components/Sidebar.tsx                      # Ajouter entrée "Sauvegardes" (admin only)
frontend/src/i18n/fr.json                                # Bloc backups.* (~30 clés)
frontend/src/i18n/en.json                                # Bloc backups.* (~30 clés)
```

---

## Task 1 : Migration 104 — colonne source_remote_connection_id

**Files:**
- Create: `backend/migrations/104_local_backups_source_remote.sql`
- Create: `backend/tests/services/test_local_backups_source_remote.py`

- [ ] **Step 1 : Écrire le test rouge migration**

Créer `backend/tests/services/test_local_backups_source_remote.py` :

```python
from __future__ import annotations
from uuid import uuid4

import pytest
from agflow.db.pool import execute, fetch_one


@pytest.mark.asyncio
async def test_local_backups_has_source_remote_column(db_pool):
    """Après migration 104, la colonne source_remote_connection_id existe."""
    row = await fetch_one(
        """
        SELECT column_name, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_name = 'local_backups'
          AND column_name = 'source_remote_connection_id'
        """
    )
    assert row is not None
    assert row["is_nullable"] == "YES"
    assert row["data_type"] == "uuid"


@pytest.mark.asyncio
async def test_local_backups_fk_set_null_on_remote_delete(db_pool):
    """Si la connexion remote est soft-deletée, la colonne reste (on_delete='SET NULL').
    Si elle est hard-delete (suppression directe en SQL), la FK met à NULL."""
    remote_id = uuid4()
    backup_id = uuid4()

    await execute(
        "INSERT INTO remote_backup_connections (id, name, kind, config) "
        "VALUES ($1, 'test-remote', 'sftp', '{}'::jsonb)",
        remote_id,
    )
    await execute(
        "INSERT INTO local_backups (id, filename, file_path, status, source_remote_connection_id) "
        "VALUES ($1, 'test.sql.gz', '/tmp/test.sql.gz', 'completed', $2)",
        backup_id, remote_id,
    )
    # Hard delete pour tester le SET NULL (le soft delete ne touche pas la FK)
    await execute("DELETE FROM remote_backup_connections WHERE id = $1", remote_id)

    row = await fetch_one(
        "SELECT source_remote_connection_id FROM local_backups WHERE id = $1",
        backup_id,
    )
    assert row["source_remote_connection_id"] is None

    # Cleanup
    await execute("DELETE FROM local_backups WHERE id = $1", backup_id)
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_local_backups_source_remote.py -v
```

Attendu : FAIL (colonne inexistante).

- [ ] **Step 3 : Créer la migration**

Créer `backend/migrations/104_local_backups_source_remote.sql` :

```sql
-- 104 — Trace la connexion remote d'origine d'un backup local pull

ALTER TABLE local_backups
    ADD COLUMN source_remote_connection_id UUID
        REFERENCES remote_backup_connections(id) ON DELETE SET NULL;

CREATE INDEX idx_local_backups_source_remote
    ON local_backups(source_remote_connection_id)
    WHERE source_remote_connection_id IS NOT NULL;
```

- [ ] **Step 4 : Appliquer la migration et relancer le test**

```bash
cd backend && uv run python -m agflow.db.migrations
cd backend && uv run pytest tests/services/test_local_backups_source_remote.py -v
```

Attendu : 2 PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/migrations/104_local_backups_source_remote.sql \
        backend/tests/services/test_local_backups_source_remote.py
git commit -m "feat(remote-backups): migration 104 — source_remote_connection_id"
```

---

## Task 2 : Extension Protocol — RemoteFile + list_remote + download_stream

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/protocol.py`
- Create: `backend/tests/services/test_remote_backup_providers_listing.py` (Step 1 seulement)

- [ ] **Step 1 : Écrire le test rouge sur le Protocol**

Créer `backend/tests/services/test_remote_backup_providers_listing.py` :

```python
from __future__ import annotations
from datetime import datetime
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider, RemoteFile,
)


def test_remote_file_dataclass_fields():
    """RemoteFile expose filename, size, last_modified."""
    rf = RemoteFile(filename="x.sql.gz", size_bytes=1024, last_modified=datetime(2026, 5, 1))
    assert rf.filename == "x.sql.gz"
    assert rf.size_bytes == 1024
    assert rf.last_modified == datetime(2026, 5, 1)


def test_protocol_has_list_remote_and_download_stream():
    """Le Protocol expose les nouvelles méthodes."""
    assert hasattr(RemoteBackupProvider, "list_remote")
    assert hasattr(RemoteBackupProvider, "download_stream")
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -v
```

Attendu : FAIL (ImportError sur `RemoteFile`).

- [ ] **Step 3 : Modifier le Protocol**

Remplacer `backend/src/agflow/services/remote_backup_providers/protocol.py` :

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class RemoteBackupProviderError(Exception):
    """Erreur provider remote backup — propagée en 422 par les endpoints."""


@dataclass(frozen=True)
class RemoteFile:
    """Fichier listé sur un remote. last_modified peut être None si le provider ne le fournit pas."""
    filename: str
    size_bytes: int | None
    last_modified: datetime | None


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

    async def list_remote(self, path: str) -> list[RemoteFile]:
        """Liste les fichiers présents dans path. Lève RemoteBackupProviderError si KO."""
        ...

    async def download_stream(
        self,
        path: str,
        filename: str,
    ) -> AsyncIterator[bytes]:
        """Retourne un AsyncIterator[bytes] du fichier distant. Lève RemoteBackupProviderError si KO."""
        ...
```

- [ ] **Step 4 : Relancer le test**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -v
```

Attendu : 2 PASSED.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/protocol.py \
        backend/tests/services/test_remote_backup_providers_listing.py
git commit -m "feat(remote-backups): Protocol étendu — list_remote + download_stream + RemoteFile"
```

---

## Task 3 : SFTP — list_remote + download_stream

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/sftp_provider.py`
- Modify: `backend/tests/services/test_remote_backup_providers_listing.py`

- [ ] **Step 1 : Écrire les tests rouges SFTP**

Ajouter à `test_remote_backup_providers_listing.py` :

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from agflow.services.remote_backup_providers.sftp_provider import SftpProvider
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError


def _sftp_provider() -> SftpProvider:
    return SftpProvider(
        config={"host": "h", "port": 22},
        credentials={"username": "u", "password": "p"},
    )


@pytest.mark.asyncio
async def test_sftp_list_remote_returns_files():
    """list_remote retourne uniquement les fichiers (pas les sous-dirs)."""
    provider = _sftp_provider()

    file_attrs = MagicMock(size=1024, mtime=1714521600)  # 2024-05-01 00:00 UTC
    dir_attrs = MagicMock(size=0, mtime=1714521600)
    sftp = AsyncMock()
    sftp.readdir = AsyncMock(return_value=[
        MagicMock(filename="backup.sql.gz", attrs=file_attrs),
        MagicMock(filename="subdir", attrs=dir_attrs),
        MagicMock(filename=".", attrs=dir_attrs),
        MagicMock(filename="..", attrs=dir_attrs),
    ])
    sftp.isfile = AsyncMock(side_effect=lambda p: p.endswith("backup.sql.gz"))

    conn = AsyncMock()
    conn.__aenter__.return_value = conn
    conn.start_sftp_client.return_value.__aenter__.return_value = sftp

    with patch("agflow.services.remote_backup_providers.sftp_provider.asyncssh.connect", return_value=conn):
        files = await provider.list_remote("/backups")

    assert len(files) == 1
    assert files[0].filename == "backup.sql.gz"
    assert files[0].size_bytes == 1024


@pytest.mark.asyncio
async def test_sftp_list_remote_raises_on_error():
    """En cas d'erreur SFTP, list_remote lève RemoteBackupProviderError."""
    provider = _sftp_provider()
    with patch(
        "agflow.services.remote_backup_providers.sftp_provider.asyncssh.connect",
        side_effect=OSError("connection refused"),
    ), pytest.raises(RemoteBackupProviderError, match="SFTP list failed"):
        await provider.list_remote("/backups")


@pytest.mark.asyncio
async def test_sftp_download_stream_rejects_path_separator():
    """download_stream refuse les filenames avec / ou \\."""
    provider = _sftp_provider()
    with pytest.raises(RemoteBackupProviderError, match="path separators"):
        async for _ in await provider.download_stream("/p", "evil/../escape"):
            pass


@pytest.mark.asyncio
async def test_sftp_download_stream_yields_chunks():
    """download_stream lit le fichier par chunks de 64KB."""
    provider = _sftp_provider()

    chunks = [b"chunk1", b"chunk2", b""]  # EOF marker
    remote_file = AsyncMock()
    remote_file.read = AsyncMock(side_effect=chunks)
    remote_file.__aenter__.return_value = remote_file

    sftp = AsyncMock()
    sftp.open = AsyncMock(return_value=remote_file)

    conn = AsyncMock()
    conn.__aenter__.return_value = conn
    conn.start_sftp_client.return_value.__aenter__.return_value = sftp

    with patch(
        "agflow.services.remote_backup_providers.sftp_provider.asyncssh.connect",
        return_value=conn,
    ):
        result_chunks = []
        async for c in await provider.download_stream("/backups", "backup.sql.gz"):
            result_chunks.append(c)

    assert result_chunks == [b"chunk1", b"chunk2"]
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -k sftp -v
```

Attendu : 4 FAILED.

- [ ] **Step 3 : Implémenter list_remote + download_stream dans SftpProvider**

Ajouter à `sftp_provider.py` (en imports) :

```python
from datetime import datetime, timezone

from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError, RemoteFile,
)
```

Ajouter ces 2 méthodes à la classe `SftpProvider` (après `upload_stream`) :

```python
    async def list_remote(self, path: str) -> list[RemoteFile]:
        try:
            conn = await asyncssh.connect(**self._connect_kwargs())
            async with conn, conn.start_sftp_client() as sftp:
                entries = await sftp.readdir(path)
                files: list[RemoteFile] = []
                for entry in entries:
                    if entry.filename in (".", ".."):
                        continue
                    full = f"{path.rstrip('/')}/{entry.filename}"
                    if not await sftp.isfile(full):
                        continue
                    mtime = (
                        datetime.fromtimestamp(entry.attrs.mtime, tz=timezone.utc)
                        if entry.attrs.mtime else None
                    )
                    files.append(RemoteFile(
                        filename=entry.filename,
                        size_bytes=entry.attrs.size,
                        last_modified=mtime,
                    ))
                return files
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"SFTP list failed: {exc}") from exc

    async def download_stream(self, path: str, filename: str) -> AsyncIterator[bytes]:
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        remote_file_path = f"{path.rstrip('/')}/{filename}"

        async def _gen() -> AsyncIterator[bytes]:
            try:
                conn = await asyncssh.connect(**self._connect_kwargs())
                async with conn, conn.start_sftp_client() as sftp:
                    remote_file = await sftp.open(remote_file_path, "rb")
                    async with remote_file:
                        while True:
                            chunk = await remote_file.read(_CHUNK)
                            if not chunk:
                                return
                            yield chunk
            except RemoteBackupProviderError:
                raise
            except Exception as exc:
                raise RemoteBackupProviderError(f"SFTP download failed: {exc}") from exc

        return _gen()
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -k sftp -v
```

Attendu : 4 PASSED.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/remote_backup_providers/sftp_provider.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/sftp_provider.py \
        backend/tests/services/test_remote_backup_providers_listing.py
git commit -m "feat(remote-backups): SFTP list_remote + download_stream"
```

---

## Task 4 : FTPS — list_remote + download_stream

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/ftps_provider.py`
- Modify: `backend/tests/services/test_remote_backup_providers_listing.py`

- [ ] **Step 1 : Écrire les tests rouges FTPS**

Ajouter à `test_remote_backup_providers_listing.py` :

```python
from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider


def _ftps_provider() -> FtpsProvider:
    return FtpsProvider(
        config={"host": "h", "port": 21, "use_tls": False},
        credentials={"username": "u", "password": "p"},
    )


@pytest.mark.asyncio
async def test_ftps_list_remote_filters_directories():
    """list_remote ne retourne que les fichiers (type='file')."""
    provider = _ftps_provider()

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.list = AsyncMock(return_value=[
        (MagicMock(parts=["/backups", "x.sql.gz"]),
         {"type": "file", "size": "2048", "modify": "20260101000000"}),
        (MagicMock(parts=["/backups", "subdir"]),
         {"type": "dir", "size": "0"}),
    ])

    with patch(
        "agflow.services.remote_backup_providers.ftps_provider.aioftp.Client.context",
        return_value=client,
    ):
        files = await provider.list_remote("/backups")

    assert len(files) == 1
    assert files[0].filename == "x.sql.gz"
    assert files[0].size_bytes == 2048


@pytest.mark.asyncio
async def test_ftps_list_remote_raises_on_error():
    """En cas d'erreur aioftp, list_remote lève RemoteBackupProviderError."""
    provider = _ftps_provider()
    with patch(
        "agflow.services.remote_backup_providers.ftps_provider.aioftp.Client.context",
        side_effect=ConnectionError("nope"),
    ), pytest.raises(RemoteBackupProviderError, match="FTPS list failed"):
        await provider.list_remote("/backups")


@pytest.mark.asyncio
async def test_ftps_download_stream_yields_chunks():
    """download_stream itère sur le stream retourné par aioftp."""
    provider = _ftps_provider()

    stream = AsyncMock()
    stream.__aenter__.return_value = stream
    stream.iter_by_block = MagicMock(return_value=_async_iter([b"data1", b"data2"]))

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.login = AsyncMock()
    client.download_stream = MagicMock(return_value=stream)

    with patch(
        "agflow.services.remote_backup_providers.ftps_provider.aioftp.Client.context",
        return_value=client,
    ):
        result = []
        async for c in await provider.download_stream("/backups", "x.sql.gz"):
            result.append(c)

    assert result == [b"data1", b"data2"]


async def _async_iter(items):
    for it in items:
        yield it
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -k ftps -v
```

Attendu : 3 FAILED.

- [ ] **Step 3 : Implémenter list_remote + download_stream dans FtpsProvider**

Ajouter à `ftps_provider.py` (en imports) :

```python
from datetime import datetime

from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError, RemoteFile,
)
```

Ajouter ces 2 méthodes à la classe `FtpsProvider` (après `upload_stream`) :

```python
    @staticmethod
    def _parse_modify(modify: str | None) -> datetime | None:
        """aioftp expose 'modify' au format YYYYMMDDHHMMSS (sans timezone)."""
        if not modify or len(modify) < 14:
            return None
        try:
            return datetime.strptime(modify[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None

    async def list_remote(self, path: str) -> list[RemoteFile]:
        try:
            async with aioftp.Client.context(
                self._host, port=self._port, ssl=self._ssl_context()
            ) as client:
                await client.login(self._username, self._password)
                entries = await client.list(path)
                files: list[RemoteFile] = []
                for entry_path, info in entries:
                    if info.get("type") != "file":
                        continue
                    name = entry_path.parts[-1]
                    files.append(RemoteFile(
                        filename=name,
                        size_bytes=int(info["size"]) if "size" in info else None,
                        last_modified=self._parse_modify(info.get("modify")),
                    ))
                return files
        except RemoteBackupProviderError:
            raise
        except Exception as exc:
            raise RemoteBackupProviderError(f"FTPS list failed: {exc}") from exc

    async def download_stream(self, path: str, filename: str) -> AsyncIterator[bytes]:
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        remote_path = f"{path.rstrip('/')}/{filename}"

        async def _gen() -> AsyncIterator[bytes]:
            try:
                async with aioftp.Client.context(
                    self._host, port=self._port, ssl=self._ssl_context()
                ) as client:
                    await client.login(self._username, self._password)
                    async with client.download_stream(remote_path) as stream:
                        async for block in stream.iter_by_block(64 * 1024):
                            yield block
            except RemoteBackupProviderError:
                raise
            except Exception as exc:
                raise RemoteBackupProviderError(f"FTPS download failed: {exc}") from exc

        return _gen()
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -k ftps -v
```

Attendu : 3 PASSED.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/remote_backup_providers/ftps_provider.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/ftps_provider.py \
        backend/tests/services/test_remote_backup_providers_listing.py
git commit -m "feat(remote-backups): FTPS list_remote + download_stream"
```

---

## Task 5 : S3 — list_remote + download_stream

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/s3_provider.py`
- Modify: `backend/tests/services/test_remote_backup_providers_listing.py`

- [ ] **Step 1 : Écrire les tests rouges S3**

Ajouter à `test_remote_backup_providers_listing.py` :

```python
from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider


def _s3_provider() -> S3CompatibleProvider:
    return S3CompatibleProvider(
        config={"bucket": "b", "region": "us-east-1"},
        credentials={"access_key_id": "k", "secret_access_key": "s"},
    )


@pytest.mark.asyncio
async def test_s3_list_remote_returns_objects():
    """list_remote retourne les objets sous le prefix."""
    provider = _s3_provider()

    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "backups/x.sql.gz", "Size": 4096,
             "LastModified": datetime(2026, 5, 1, tzinfo=timezone.utc)},
            {"Key": "backups/y.sql.gz", "Size": 8192,
             "LastModified": datetime(2026, 5, 2, tzinfo=timezone.utc)},
            {"Key": "backups/", "Size": 0,
             "LastModified": datetime(2026, 5, 1, tzinfo=timezone.utc)},
        ]
    }

    with patch.object(provider, "_client", return_value=client):
        files = await provider.list_remote("backups")

    assert sorted(f.filename for f in files) == ["x.sql.gz", "y.sql.gz"]


@pytest.mark.asyncio
async def test_s3_list_remote_empty_bucket():
    """list_remote retourne [] si pas de Contents."""
    provider = _s3_provider()
    client = MagicMock()
    client.list_objects_v2.return_value = {}

    with patch.object(provider, "_client", return_value=client):
        files = await provider.list_remote("backups")

    assert files == []


@pytest.mark.asyncio
async def test_s3_list_remote_raises_on_error():
    provider = _s3_provider()
    client = MagicMock()
    client.list_objects_v2.side_effect = RuntimeError("NoSuchBucket")

    with patch.object(provider, "_client", return_value=client), \
         pytest.raises(RemoteBackupProviderError, match="S3 list failed"):
        await provider.list_remote("backups")


@pytest.mark.asyncio
async def test_s3_download_stream_yields_chunks():
    """download_stream lit Body de get_object par chunks."""
    provider = _s3_provider()

    body = MagicMock()
    body.read.side_effect = [b"chunk1", b"chunk2", b""]

    client = MagicMock()
    client.get_object.return_value = {"Body": body}

    with patch.object(provider, "_client", return_value=client):
        result = []
        async for c in await provider.download_stream("backups", "x.sql.gz"):
            result.append(c)

    assert result == [b"chunk1", b"chunk2"]
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -k s3 -v
```

Attendu : 4 FAILED.

- [ ] **Step 3 : Implémenter list_remote + download_stream dans S3CompatibleProvider**

Ajouter à `s3_provider.py` (en imports si pas déjà) :

```python
from datetime import datetime  # noqa: F401 (utilisé dans signature RemoteFile)
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError, RemoteFile,
)
```

Ajouter ces 2 méthodes à la classe `S3CompatibleProvider` (après `upload_stream`) :

```python
    async def list_remote(self, path: str) -> list[RemoteFile]:
        prefix = path.strip("/")
        prefix_with_slash = f"{prefix}/" if prefix else ""
        try:
            client = self._client()
            resp = await asyncio.to_thread(
                client.list_objects_v2, Bucket=self._bucket, Prefix=prefix_with_slash,
            )
            contents = resp.get("Contents", [])
            files: list[RemoteFile] = []
            for obj in contents:
                key: str = obj["Key"]
                if key.endswith("/"):
                    continue
                # Garder uniquement les fichiers immédiats (pas les "sous-dossiers")
                relative = key[len(prefix_with_slash):] if prefix_with_slash else key
                if "/" in relative:
                    continue
                files.append(RemoteFile(
                    filename=relative,
                    size_bytes=obj.get("Size"),
                    last_modified=obj.get("LastModified"),
                ))
            return files
        except Exception as exc:
            raise RemoteBackupProviderError(f"S3 list failed: {exc}") from exc

    async def download_stream(self, path: str, filename: str) -> AsyncIterator[bytes]:
        if "/" in filename or "\\" in filename:
            raise RemoteBackupProviderError("filename must not contain path separators")
        key = self._build_key(path, filename)

        async def _gen() -> AsyncIterator[bytes]:
            try:
                client = self._client()
                resp = await asyncio.to_thread(
                    client.get_object, Bucket=self._bucket, Key=key,
                )
                body = resp["Body"]
                while True:
                    chunk = await asyncio.to_thread(body.read, 64 * 1024)
                    if not chunk:
                        return
                    yield chunk
            except Exception as exc:
                raise RemoteBackupProviderError(f"S3 download failed: {exc}") from exc

        return _gen()
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_providers_listing.py -k s3 -v
```

Attendu : 4 PASSED.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/remote_backup_providers/s3_provider.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/s3_provider.py \
        backend/tests/services/test_remote_backup_providers_listing.py
git commit -m "feat(remote-backups): S3 list_remote + download_stream"
```

---

## Task 6 : Schémas Pydantic — RemoteBackupFile + PullRequest + RestoreResult

**Files:**
- Create: `backend/src/agflow/schemas/remote_backup_files.py`
- Modify: `backend/src/agflow/schemas/local_backups.py`

- [ ] **Step 1 : Écrire les tests rouges schémas**

Créer `backend/tests/schemas/test_remote_backup_files.py` :

```python
from __future__ import annotations
from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agflow.schemas.remote_backup_files import (
    RemoteBackupFileDTO, PullRequest, RestoreResult,
)


def test_remote_backup_file_dto_serializes():
    dto = RemoteBackupFileDTO(
        filename="x.sql.gz", size_bytes=1024,
        last_modified=datetime(2026, 5, 1),
    )
    assert dto.filename == "x.sql.gz"
    assert dto.size_bytes == 1024


def test_pull_request_validates_filename_no_path_separator():
    PullRequest(filename="x.sql.gz")  # ok
    with pytest.raises(ValidationError, match="path separator"):
        PullRequest(filename="evil/path.sql.gz")
    with pytest.raises(ValidationError, match="path separator"):
        PullRequest(filename="..\\backup.sql.gz")


def test_pull_request_requires_filename():
    with pytest.raises(ValidationError):
        PullRequest(filename="")


def test_restore_result_serializes():
    backup_id = uuid4()
    r = RestoreResult(
        backup_id=backup_id, exit_code=0, output_tail="...DONE",
    )
    assert r.backup_id == backup_id
    assert r.exit_code == 0
```

Créer aussi `backend/tests/schemas/test_local_backups_dto.py` :

```python
from __future__ import annotations
from datetime import datetime
from uuid import uuid4

from agflow.schemas.local_backups import LocalBackupSummary


def test_local_backup_summary_with_source_remote():
    """source_remote_connection_id est exposé et nullable."""
    remote_id = uuid4()
    dto = LocalBackupSummary(
        id=uuid4(), filename="x.sql.gz", size_bytes=1024,
        status="completed", created_at=datetime.now(),
        source_remote_connection_id=remote_id,
    )
    assert dto.source_remote_connection_id == remote_id


def test_local_backup_summary_source_remote_optional():
    """source_remote_connection_id est optionnel (créés par dump local)."""
    dto = LocalBackupSummary(
        id=uuid4(), filename="x.sql.gz", size_bytes=1024,
        status="completed", created_at=datetime.now(),
    )
    assert dto.source_remote_connection_id is None
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/schemas/test_remote_backup_files.py tests/schemas/test_local_backups_dto.py -v
```

Attendu : tests/schemas/test_remote_backup_files.py FAIL (ImportError) ; tests/schemas/test_local_backups_dto.py partial fail.

- [ ] **Step 3 : Créer remote_backup_files.py**

```python
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RemoteBackupFileDTO(BaseModel):
    filename: str
    size_bytes: int | None = None
    last_modified: datetime | None = None


class PullRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)

    @field_validator("filename")
    @classmethod
    def _no_path_separator(cls, v: str) -> str:
        if "/" in v or "\\" in v:
            raise ValueError("filename must not contain path separator")
        return v


class RestoreResult(BaseModel):
    backup_id: UUID
    exit_code: int
    output_tail: str
```

- [ ] **Step 4 : Modifier local_backups.py**

Remplacer le contenu de `backend/src/agflow/schemas/local_backups.py` :

```python
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
    source_remote_connection_id: UUID | None = None
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/schemas/test_remote_backup_files.py tests/schemas/test_local_backups_dto.py -v
```

Attendu : 6 PASSED.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/schemas/remote_backup_files.py \
        backend/src/agflow/schemas/local_backups.py \
        backend/tests/schemas/test_remote_backup_files.py \
        backend/tests/schemas/test_local_backups_dto.py
git commit -m "feat(remote-backups): schémas DTO restore + extension LocalBackupSummary"
```

---

## Task 7 : Service pull_remote_to_local

**Files:**
- Modify: `backend/src/agflow/services/local_backups_service.py`
- Create: `backend/tests/services/test_pull_remote.py`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/services/test_pull_remote.py` :

```python
from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agflow.services import local_backups_service as svc
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError


async def _async_iter(items: list[bytes]):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_pull_remote_to_local_creates_local_backup(tmp_path: Path):
    """pull_remote_to_local stream le fichier, l'enregistre, insère un local_backup."""
    remote_id, user_id = uuid4(), uuid4()
    chunks = [b"hello ", b"world!"]

    provider = MagicMock()
    provider.download_stream = AsyncMock(return_value=_async_iter(chunks))

    with (
        patch.object(svc, "_backups_dir", return_value=tmp_path),
        patch("agflow.services.local_backups_service.get_provider", return_value=provider),
        patch("agflow.services.local_backups_service.rbc_service") as mock_rbc,
        patch("agflow.services.local_backups_service.execute") as mock_exec,
        patch("agflow.services.local_backups_service.fetch_one") as mock_fetch,
    ):
        mock_rbc.get_connection = AsyncMock(return_value=MagicMock(
            id=remote_id, kind="sftp", config={"remote_path_full": "/backups"},
        ))
        mock_rbc.fetch_credentials = AsyncMock(return_value={"username": "u", "password": "p"})
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")
        mock_fetch.return_value = {
            "id": "x", "filename": "x.sql.gz", "size_bytes": 12,
            "status": "completed", "created_at": None,
            "source_remote_connection_id": remote_id,
        }

        result = await svc.pull_remote_to_local(
            remote_id, filename="x.sql.gz", created_by_user_id=user_id,
        )

    # 1. download_stream appelé avec le bon chemin/filename
    provider.download_stream.assert_called_once_with("/backups", "x.sql.gz")
    # 2. INSERT puis UPDATE status='completed' avec source_remote_connection_id
    assert mock_exec.await_count == 2
    insert_args = mock_exec.await_args_list[0].args
    assert "INSERT INTO local_backups" in insert_args[0]
    assert "source_remote_connection_id" in insert_args[0]
    # 3. Fichier écrit avec le contenu joint
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"hello world!"
    # 4. Le DTO retourné expose source_remote_connection_id
    assert result.source_remote_connection_id == remote_id


@pytest.mark.asyncio
async def test_pull_remote_to_local_rolls_back_on_provider_error(tmp_path: Path):
    """Si le provider échoue, le fichier partiel est supprimé et le row passe 'failed'."""
    remote_id = uuid4()

    provider = MagicMock()

    async def _failing_iter():
        yield b"partial"
        raise RemoteBackupProviderError("network down")

    provider.download_stream = AsyncMock(return_value=_failing_iter())

    with (
        patch.object(svc, "_backups_dir", return_value=tmp_path),
        patch("agflow.services.local_backups_service.get_provider", return_value=provider),
        patch("agflow.services.local_backups_service.rbc_service") as mock_rbc,
        patch("agflow.services.local_backups_service.execute") as mock_exec,
    ):
        mock_rbc.get_connection = AsyncMock(return_value=MagicMock(
            id=remote_id, kind="sftp", config={"remote_path_full": "/backups"},
        ))
        mock_rbc.fetch_credentials = AsyncMock(return_value={"username": "u", "password": "p"})
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")

        with pytest.raises(RuntimeError, match="Pull failed"):
            await svc.pull_remote_to_local(remote_id, filename="x.sql.gz")

    # Fichier supprimé
    assert list(tmp_path.iterdir()) == []
    # Dernier UPDATE marqué 'failed'
    assert any(
        "status='failed'" in (call.args[0] or "")
        for call in mock_exec.await_args_list
    )


@pytest.mark.asyncio
async def test_pull_remote_to_local_missing_connection_raises():
    """Si la connexion remote n'existe pas, ValueError."""
    with (
        patch("agflow.services.local_backups_service.rbc_service") as mock_rbc,
    ):
        mock_rbc.get_connection = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await svc.pull_remote_to_local(uuid4(), filename="x.sql.gz")


@pytest.mark.asyncio
async def test_pull_remote_to_local_no_credentials_raises():
    """Si fetch_credentials retourne None, ValueError."""
    with (
        patch("agflow.services.local_backups_service.rbc_service") as mock_rbc,
    ):
        mock_rbc.get_connection = AsyncMock(return_value=MagicMock(
            id=uuid4(), kind="sftp", config={},
        ))
        mock_rbc.fetch_credentials = AsyncMock(return_value=None)
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")
        with pytest.raises(ValueError, match="credentials"):
            await svc.pull_remote_to_local(uuid4(), filename="x.sql.gz")
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_pull_remote.py -v
```

Attendu : tous FAIL (`AttributeError: module has no attribute pull_remote_to_local`).

- [ ] **Step 3 : Modifier local_backups_service.py**

Ajouter en imports (en haut du fichier, après les imports existants) :

```python
from agflow.db.pool import get_pool
from agflow.schemas.local_backups import LocalBackupSummary
from agflow.services import remote_backup_connections_service as rbc_service
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider
```

Modifier `_to_dto` pour exposer la nouvelle colonne :

```python
def _to_dto(row: dict) -> LocalBackupSummary:
    return LocalBackupSummary(
        id=row["id"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        status=row["status"],
        created_at=row["created_at"],
        source_remote_connection_id=row.get("source_remote_connection_id"),
    )
```

Mettre à jour `list_backups` et `get_backup` pour SELECT la colonne :

```python
async def list_backups() -> list[LocalBackupSummary]:
    rows = await fetch_all(
        "SELECT id, filename, size_bytes, status, created_at, source_remote_connection_id "
        "FROM local_backups ORDER BY created_at DESC LIMIT 100"
    )
    return [_to_dto(r) for r in rows]


async def get_backup(backup_id: UUID) -> LocalBackupSummary | None:
    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at, source_remote_connection_id "
        "FROM local_backups WHERE id = $1",
        backup_id,
    )
    return _to_dto(row) if row else None
```

Idem pour le SELECT final de `create_backup` (existing) :

```python
    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at, source_remote_connection_id "
        "FROM local_backups WHERE id=$1",
        backup_id,
    )
    return _to_dto(row)
```

Ajouter la nouvelle fonction `pull_remote_to_local` :

```python
async def pull_remote_to_local(
    remote_id: UUID,
    *,
    filename: str,
    created_by_user_id: UUID | None = None,
) -> LocalBackupSummary:
    """Stream un fichier depuis un remote vers un fichier local + ligne local_backups."""
    async with (await get_pool()).acquire() as conn:
        connection = await rbc_service.get_connection(conn, remote_id)
        if connection is None:
            raise ValueError(f"Remote connection {remote_id} not found")
        credentials = await rbc_service.fetch_credentials(connection)

    if credentials is None:
        raise ValueError(f"No credentials configured for remote {remote_id}")

    remote_path = rbc_service.resolve_remote_path(connection.config, connection.kind, "full")
    if remote_path is None:
        raise ValueError(f"No full backup path configured on remote {remote_id}")

    async with backup_lock:
        backup_id = uuid4()
        file_path = _backups_dir() / filename

        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, "
            "                           created_by_user_id, source_remote_connection_id) "
            "VALUES ($1, $2, $3, 'in_progress', $4, $5)",
            backup_id, filename, str(file_path), created_by_user_id, remote_id,
        )
        try:
            provider = get_provider(connection.kind, connection.config, credentials)
            written = 0
            stream = await provider.download_stream(remote_path, filename)
            with file_path.open("wb") as f:
                async for chunk in stream:
                    await asyncio.to_thread(f.write, chunk)
                    written += len(chunk)
            await execute(
                "UPDATE local_backups SET status='completed', size_bytes=$1 WHERE id=$2",
                written, backup_id,
            )
            _log.info("local_backup.pulled",
                      id=str(backup_id), remote_id=str(remote_id), size=written)
        except Exception as exc:
            await execute("UPDATE local_backups SET status='failed' WHERE id=$1", backup_id)
            file_path.unlink(missing_ok=True)
            raise RuntimeError(f"Pull failed: {exc}") from exc

    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at, source_remote_connection_id "
        "FROM local_backups WHERE id=$1",
        backup_id,
    )
    return _to_dto(row)
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_pull_remote.py -v
```

Attendu : 4 PASSED.

- [ ] **Step 5 : Vérifier non-régression sur create_backup existant**

```bash
cd backend && uv run pytest tests/services/test_local_backups.py -v
```

Attendu : tous PASSED (les tests existants ne doivent pas casser après ajout de la colonne dans le SELECT).

- [ ] **Step 6 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/local_backups_service.py
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/local_backups_service.py \
        backend/tests/services/test_pull_remote.py
git commit -m "feat(remote-backups): service pull_remote_to_local"
```

---

## Task 8 : Service restore_local_backup

**Files:**
- Create: `backend/src/agflow/services/restore_service.py`
- Create: `backend/tests/services/test_restore_service.py`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/services/test_restore_service.py` :

```python
from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agflow.services import restore_service


@pytest.mark.asyncio
async def test_restore_local_backup_pipes_to_db_backup_restore_dump(tmp_path: Path):
    """restore_local_backup ouvre le fichier et le passe à db_backup.restore_dump."""
    backup_id = uuid4()
    file_path = tmp_path / "x.sql.gz"
    file_path.write_bytes(b"gzipped sql content")

    captured: list[bytes] = []

    async def _fake_restore(stream):
        async for chunk in stream:
            captured.append(chunk)
        return {"exit_code": 0, "tail": "DONE"}

    with (
        patch("agflow.services.restore_service.fetch_one") as mock_fetch,
        patch("agflow.services.restore_service.db_backup") as mock_db,
    ):
        mock_fetch.return_value = {
            "filename": "x.sql.gz", "file_path": str(file_path), "status": "completed",
        }
        mock_db.restore_dump = _fake_restore

        result = await restore_service.restore_local_backup(backup_id)

    assert result.exit_code == 0
    assert result.output_tail == "DONE"
    assert b"".join(captured) == b"gzipped sql content"


@pytest.mark.asyncio
async def test_restore_local_backup_raises_if_backup_not_completed(tmp_path: Path):
    """Si status != 'completed', ValueError."""
    with patch("agflow.services.restore_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "filename": "x.sql.gz", "file_path": "/tmp/x", "status": "failed",
        }
        with pytest.raises(ValueError, match="completed"):
            await restore_service.restore_local_backup(uuid4())


@pytest.mark.asyncio
async def test_restore_local_backup_raises_if_file_missing(tmp_path: Path):
    """Si le fichier sur disque a été supprimé, FileNotFoundError."""
    with patch("agflow.services.restore_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "filename": "x.sql.gz",
            "file_path": str(tmp_path / "does-not-exist.sql.gz"),
            "status": "completed",
        }
        with pytest.raises(FileNotFoundError, match="missing"):
            await restore_service.restore_local_backup(uuid4())


@pytest.mark.asyncio
async def test_restore_local_backup_raises_on_nonzero_exit(tmp_path: Path):
    """Si pg_restore exit != 0, RuntimeError."""
    file_path = tmp_path / "x.sql.gz"
    file_path.write_bytes(b"corrupted")

    async def _failing_restore(stream):
        async for _ in stream:
            pass
        return {"exit_code": 3, "tail": "ERROR: syntax"}

    with (
        patch("agflow.services.restore_service.fetch_one") as mock_fetch,
        patch("agflow.services.restore_service.db_backup") as mock_db,
    ):
        mock_fetch.return_value = {
            "filename": "x.sql.gz", "file_path": str(file_path), "status": "completed",
        }
        mock_db.restore_dump = _failing_restore

        with pytest.raises(RuntimeError, match="exit code 3"):
            await restore_service.restore_local_backup(uuid4())


@pytest.mark.asyncio
async def test_restore_local_backup_acquires_lock():
    """L'opération acquiert backup_lock pour exclure les autres jobs."""
    from agflow.services.backup_lock import backup_lock

    with patch("agflow.services.restore_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = None  # → not found avant le lock release

        # Pré-acquérir le lock pour observer la sérialisation
        await backup_lock.acquire()
        try:
            with pytest.raises(ValueError):
                # Va se bloquer sur le lock → on libère après pour finir le test
                import asyncio
                task = asyncio.create_task(restore_service.restore_local_backup(uuid4()))
                await asyncio.sleep(0.05)
                assert not task.done(), "should be waiting on backup_lock"
                backup_lock.release()
                await task
        finally:
            if backup_lock.locked():
                backup_lock.release()
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/services/test_restore_service.py -v
```

Attendu : tous FAIL (`ModuleNotFoundError: No module named 'agflow.services.restore_service'`).

- [ ] **Step 3 : Créer le service**

Créer `backend/src/agflow/services/restore_service.py` :

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import structlog

from agflow.db.pool import fetch_one
from agflow.schemas.remote_backup_files import RestoreResult
from agflow.services import db_backup
from agflow.services.backup_lock import backup_lock

_log = structlog.get_logger(__name__)
_CHUNK = 64 * 1024


async def _stream_file(path: Path) -> AsyncIterator[bytes]:
    f = await asyncio.to_thread(path.open, "rb")
    try:
        while True:
            chunk = await asyncio.to_thread(f.read, _CHUNK)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(f.close)


async def restore_local_backup(backup_id: UUID) -> RestoreResult:
    """⚠ DESTRUCTIF — restore un local_backup dans Postgres (DROP + recreate).

    Sérialisé via backup_lock pour exclure les opérations concurrentes (dump/pull).
    """
    async with backup_lock:
        row = await fetch_one(
            "SELECT filename, file_path, status FROM local_backups WHERE id = $1",
            backup_id,
        )
        if row is None:
            raise ValueError(f"Backup {backup_id} not found")
        if row["status"] != "completed":
            raise ValueError(f"Backup status is {row['status']!r}, must be 'completed'")

        path = Path(row["file_path"])
        if not path.exists():
            raise FileNotFoundError(f"Backup file missing: {path}")

        _log.info("restore.start", id=str(backup_id), filename=row["filename"])
        result = await db_backup.restore_dump(_stream_file(path))
        exit_code = int(result.get("exit_code", -1))
        tail = str(result.get("tail", ""))

        if exit_code != 0:
            _log.warning("restore.failed", id=str(backup_id), exit_code=exit_code, tail=tail)
            raise RuntimeError(
                f"Restore failed with exit code {exit_code}. Output tail: {tail}"
            )

        _log.info("restore.success", id=str(backup_id), exit_code=exit_code)
        return RestoreResult(backup_id=backup_id, exit_code=exit_code, output_tail=tail)
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/services/test_restore_service.py -v
```

Attendu : 5 PASSED.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/restore_service.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/restore_service.py \
        backend/tests/services/test_restore_service.py
git commit -m "feat(remote-backups): service restore_local_backup avec backup_lock"
```

---

## Task 9 : Endpoints HTTP — list files + pull + restore

**Files:**
- Modify: `backend/src/agflow/api/admin/remote_backup_connections.py`
- Modify: `backend/src/agflow/api/admin/local_backups.py`
- Create: `backend/tests/api/test_remote_backup_files_endpoints.py`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `backend/tests/api/test_remote_backup_files_endpoints.py` :

```python
from __future__ import annotations
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Fixture client / require_admin override est supposée venir d'un conftest existant.
# Voir docs/tests-python.md pour le pattern projet.


def test_list_remote_files_returns_files(client):
    """GET /api/admin/backup-remotes/{id}/files retourne la liste."""
    remote_id = uuid4()

    provider = MagicMock()
    provider.list_remote = AsyncMock(return_value=[
        MagicMock(filename="a.sql.gz", size_bytes=1024,
                  last_modified=datetime(2026, 5, 1)),
    ])

    with (
        patch("agflow.api.admin.remote_backup_connections.rbc_service") as mock_rbc,
        patch("agflow.api.admin.remote_backup_connections.get_provider", return_value=provider),
    ):
        mock_rbc.get_connection = AsyncMock(return_value=MagicMock(
            id=remote_id, kind="sftp", config={"remote_path_full": "/backups"},
        ))
        mock_rbc.fetch_credentials = AsyncMock(return_value={"username": "u"})
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")

        resp = client.get(f"/api/admin/backup-remotes/{remote_id}/files")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["filename"] == "a.sql.gz"
    provider.list_remote.assert_called_once_with("/backups")


def test_list_remote_files_404_if_connection_missing(client):
    """GET retourne 404 si connexion inconnue."""
    with patch("agflow.api.admin.remote_backup_connections.rbc_service") as mock_rbc:
        mock_rbc.get_connection = AsyncMock(return_value=None)
        resp = client.get(f"/api/admin/backup-remotes/{uuid4()}/files")
    assert resp.status_code == 404


def test_list_remote_files_422_on_provider_error(client):
    """GET retourne 422 si le provider échoue."""
    from agflow.services.remote_backup_providers import RemoteBackupProviderError

    provider = MagicMock()
    provider.list_remote = AsyncMock(side_effect=RemoteBackupProviderError("nope"))

    with (
        patch("agflow.api.admin.remote_backup_connections.rbc_service") as mock_rbc,
        patch("agflow.api.admin.remote_backup_connections.get_provider", return_value=provider),
    ):
        mock_rbc.get_connection = AsyncMock(return_value=MagicMock(
            id=uuid4(), kind="sftp", config={},
        ))
        mock_rbc.fetch_credentials = AsyncMock(return_value={"username": "u"})
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")

        resp = client.get(f"/api/admin/backup-remotes/{uuid4()}/files")

    assert resp.status_code == 422


def test_pull_from_remote_calls_service(client):
    """POST /api/admin/local-backups/pull-from-remote/{id} appelle le service."""
    remote_id = uuid4()
    summary_dict = {
        "id": str(uuid4()), "filename": "x.sql.gz", "size_bytes": 12,
        "status": "completed", "created_at": "2026-05-14T00:00:00",
        "source_remote_connection_id": str(remote_id),
    }

    with (
        patch("agflow.api.admin.local_backups.local_backups_service.pull_remote_to_local") as mock_pull,
        patch("agflow.api.admin.local_backups.users_service.get_by_email",
              new=AsyncMock(return_value=MagicMock(id=uuid4()))),
    ):
        mock_pull.return_value = MagicMock(model_dump=lambda: summary_dict)

        resp = client.post(
            f"/api/admin/local-backups/pull-from-remote/{remote_id}",
            json={"filename": "x.sql.gz"},
        )

    assert resp.status_code == 201
    mock_pull.assert_called_once()
    _, kwargs = mock_pull.call_args
    assert kwargs["filename"] == "x.sql.gz"


def test_pull_from_remote_rejects_path_separator(client):
    """POST rejette filename avec '/' avec 422."""
    resp = client.post(
        f"/api/admin/local-backups/pull-from-remote/{uuid4()}",
        json={"filename": "evil/escape.sql.gz"},
    )
    assert resp.status_code == 422


def test_restore_local_backup_requires_filename_match(client):
    """POST /restore retourne 422 si le filename ne matche pas le backup."""
    backup_id = uuid4()

    with (
        patch("agflow.api.admin.local_backups.local_backups_service.get_backup",
              new=AsyncMock(return_value=MagicMock(filename="actual.sql.gz"))),
    ):
        resp = client.post(
            f"/api/admin/local-backups/{backup_id}/restore",
            json={"filename": "wrong.sql.gz"},
        )

    assert resp.status_code == 422
    assert "match" in resp.json()["detail"].lower()


def test_restore_local_backup_success(client):
    """POST /restore appelle restore_service.restore_local_backup."""
    backup_id = uuid4()

    with (
        patch("agflow.api.admin.local_backups.local_backups_service.get_backup",
              new=AsyncMock(return_value=MagicMock(filename="x.sql.gz"))),
        patch("agflow.api.admin.local_backups.restore_service.restore_local_backup",
              new=AsyncMock(return_value=MagicMock(
                  model_dump=lambda: {
                      "backup_id": str(backup_id), "exit_code": 0, "output_tail": "DONE",
                  }
              ))),
    ):
        resp = client.post(
            f"/api/admin/local-backups/{backup_id}/restore",
            json={"filename": "x.sql.gz"},
        )

    assert resp.status_code == 200
    assert resp.json()["exit_code"] == 0


def test_restore_local_backup_404_if_missing(client):
    """POST /restore retourne 404 si le backup n'existe pas."""
    with patch("agflow.api.admin.local_backups.local_backups_service.get_backup",
               new=AsyncMock(return_value=None)):
        resp = client.post(
            f"/api/admin/local-backups/{uuid4()}/restore",
            json={"filename": "x.sql.gz"},
        )
    assert resp.status_code == 404
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd backend && uv run pytest tests/api/test_remote_backup_files_endpoints.py -v
```

Attendu : tous FAIL (routes inexistantes).

- [ ] **Step 3 : Ajouter GET /backup-remotes/{id}/files**

Ajouter à `backend/src/agflow/api/admin/remote_backup_connections.py` (en imports) :

```python
from agflow.schemas.remote_backup_files import RemoteBackupFileDTO
```

Ajouter cet endpoint à la fin du router :

```python
@router.get("/{connection_id}/files", response_model=list[RemoteBackupFileDTO])
async def list_remote_files(connection_id: UUID) -> list[RemoteBackupFileDTO]:
    """Liste les fichiers présents sur la cible distante (usage='full')."""
    async with (await get_pool()).acquire() as conn:
        dto = await rbc_service.get_connection(conn, connection_id)
        if dto is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        credentials = await rbc_service.fetch_credentials(dto)

    if credentials is None:
        raise HTTPException(status_code=422, detail="No credentials configured")

    remote_path = rbc_service.resolve_remote_path(dto.config, dto.kind, "full")
    if remote_path is None:
        raise HTTPException(status_code=422, detail="No full backup path configured")

    try:
        provider = get_provider(dto.kind, dto.config, credentials)
        files = await provider.list_remote(remote_path)
    except RemoteBackupProviderError as exc:
        _log.warning("list_remote_files.provider_error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return [
        RemoteBackupFileDTO(
            filename=f.filename,
            size_bytes=f.size_bytes,
            last_modified=f.last_modified,
        )
        for f in files
    ]
```

- [ ] **Step 4 : Ajouter POST /local-backups/pull-from-remote + /restore**

Ajouter à `backend/src/agflow/api/admin/local_backups.py` (en imports) :

```python
from agflow.schemas.local_backups import LocalBackupSummary
from agflow.schemas.remote_backup_files import PullRequest, RestoreResult
from agflow.services import restore_service
```

Ajouter ces 2 endpoints à la fin du router :

```python
@router.post(
    "/pull-from-remote/{remote_id}",
    response_model=LocalBackupSummary,
    status_code=201,
)
async def pull_from_remote(
    remote_id: UUID,
    body: PullRequest,
    admin_email: str = Depends(require_admin),
) -> LocalBackupSummary:
    """Pull un fichier distant vers les backups locaux."""
    admin_user = await users_service.get_by_email(admin_email)
    user_uuid = admin_user.id if admin_user else None
    try:
        return await local_backups_service.pull_remote_to_local(
            remote_id, filename=body.filename, created_by_user_id=user_uuid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Pull failed après début du transfert (provider down, disk full…)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class RestoreRequest(PullRequest):
    """Reuse PullRequest validator (filename no separator). Renamed for clarity."""


@router.post("/{backup_id}/restore", response_model=RestoreResult, status_code=200)
async def restore_backup(
    backup_id: UUID,
    body: RestoreRequest,
) -> RestoreResult:
    """⚠ DESTRUCTIF — restaure un backup local dans Postgres.

    L'admin doit retaper exactement le filename pour confirmer.
    """
    backup = await local_backups_service.get_backup(backup_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    if body.filename != backup.filename:
        raise HTTPException(
            status_code=422,
            detail=f"Filename does not match (expected {backup.filename!r})",
        )
    try:
        return await restore_service.restore_local_backup(backup_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd backend && uv run pytest tests/api/test_remote_backup_files_endpoints.py -v
```

Attendu : 8 PASSED.

- [ ] **Step 6 : Vérifier non-régression**

```bash
cd backend && uv run pytest tests/api/test_remote_backup_connections.py tests/api/test_local_backups.py -v
```

Attendu : tous PASSED (les tests existants restent verts).

- [ ] **Step 7 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/remote_backup_connections.py src/agflow/api/admin/local_backups.py
```

- [ ] **Step 8 : Commit**

```bash
git add backend/src/agflow/api/admin/remote_backup_connections.py \
        backend/src/agflow/api/admin/local_backups.py \
        backend/tests/api/test_remote_backup_files_endpoints.py
git commit -m "feat(remote-backups): endpoints list files + pull + restore"
```

---

## Task 10 : Frontend — API client backupsApi

**Files:**
- Create: `frontend/src/lib/backupsApi.ts`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `frontend/src/__tests__/backupsApi.test.ts` :

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { listRemoteFiles, pullFromRemote, restoreLocal, listLocalBackups } from "../lib/backupsApi";

const mockFetch = vi.fn();
beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockFetch.mockReset();
});

describe("backupsApi", () => {
  it("listRemoteFiles GETs /api/admin/backup-remotes/{id}/files", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ filename: "x.sql.gz", size_bytes: 1024, last_modified: null }],
    });

    const files = await listRemoteFiles("00000000-0000-0000-0000-000000000001");

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/admin/backup-remotes/00000000-0000-0000-0000-000000000001/files"),
      expect.any(Object),
    );
    expect(files[0].filename).toBe("x.sql.gz");
  });

  it("pullFromRemote POSTs filename payload", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        id: "id1", filename: "x.sql.gz", size_bytes: 12,
        status: "completed", created_at: "2026-05-14T00:00:00Z",
        source_remote_connection_id: "id-remote",
      }),
    });

    const result = await pullFromRemote("id-remote", "x.sql.gz");

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/admin/local-backups/pull-from-remote/id-remote"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ filename: "x.sql.gz" }),
      }),
    );
    expect(result.source_remote_connection_id).toBe("id-remote");
  });

  it("restoreLocal POSTs filename for confirmation", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ backup_id: "b1", exit_code: 0, output_tail: "DONE" }),
    });

    const result = await restoreLocal("b1", "x.sql.gz");

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/admin/local-backups/b1/restore"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ filename: "x.sql.gz" }),
      }),
    );
    expect(result.exit_code).toBe(0);
  });

  it("listLocalBackups returns the list from /api/admin/local-backups", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { id: "id1", filename: "x.sql.gz", size_bytes: 1024,
          status: "completed", created_at: "2026-05-14T00:00:00Z",
          source_remote_connection_id: null },
      ],
    });

    const backups = await listLocalBackups();
    expect(backups[0].filename).toBe("x.sql.gz");
  });

  it("throws on HTTP error with API detail", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: "Filename does not match" }),
    });

    await expect(restoreLocal("b1", "wrong.sql.gz")).rejects.toThrow("Filename does not match");
  });
});
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd frontend && npm test -- backupsApi.test.ts
```

Attendu : FAIL (module non trouvé).

- [ ] **Step 3 : Créer backupsApi.ts**

```typescript
export interface RemoteBackupFile {
  filename: string;
  size_bytes: number | null;
  last_modified: string | null;
}

export interface LocalBackup {
  id: string;
  filename: string;
  size_bytes: number | null;
  status: "in_progress" | "completed" | "failed";
  created_at: string;
  source_remote_connection_id: string | null;
}

export interface RestoreResult {
  backup_id: string;
  exit_code: number;
  output_tail: string;
}

async function _request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // body not JSON — keep generic detail
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export function listRemoteFiles(connectionId: string): Promise<RemoteBackupFile[]> {
  return _request<RemoteBackupFile[]>(`/api/admin/backup-remotes/${connectionId}/files`);
}

export function listLocalBackups(): Promise<LocalBackup[]> {
  return _request<LocalBackup[]>("/api/admin/local-backups");
}

export function pullFromRemote(connectionId: string, filename: string): Promise<LocalBackup> {
  return _request<LocalBackup>(
    `/api/admin/local-backups/pull-from-remote/${connectionId}`,
    { method: "POST", body: JSON.stringify({ filename }) },
  );
}

export function restoreLocal(backupId: string, filename: string): Promise<RestoreResult> {
  return _request<RestoreResult>(
    `/api/admin/local-backups/${backupId}/restore`,
    { method: "POST", body: JSON.stringify({ filename }) },
  );
}
```

- [ ] **Step 4 : Vérifier que les tests passent**

```bash
cd frontend && npm test -- backupsApi.test.ts
```

Attendu : 5 PASSED.

- [ ] **Step 5 : TypeCheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/lib/backupsApi.ts frontend/src/__tests__/backupsApi.test.ts
git commit -m "feat(frontend): API client backupsApi (list/pull/restore)"
```

---

## Task 11 : Hooks React Query

**Files:**
- Create: `frontend/src/hooks/useBackups.ts`

- [ ] **Step 1 : Implémenter les hooks**

Créer `frontend/src/hooks/useBackups.ts` :

```typescript
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  listLocalBackups,
  listRemoteFiles,
  pullFromRemote,
  restoreLocal,
  type LocalBackup,
  type RemoteBackupFile,
  type RestoreResult,
} from "../lib/backupsApi";

const LOCAL_BACKUPS_KEY = ["local-backups"] as const;
const remoteFilesKey = (connectionId: string | null) =>
  ["remote-backup-files", connectionId] as const;

export function useLocalBackups() {
  return useQuery<LocalBackup[]>({
    queryKey: LOCAL_BACKUPS_KEY,
    queryFn: listLocalBackups,
  });
}

export function useRemoteFiles(connectionId: string | null) {
  return useQuery<RemoteBackupFile[]>({
    queryKey: remoteFilesKey(connectionId),
    queryFn: () => {
      if (!connectionId) {
        return Promise.resolve([]);
      }
      return listRemoteFiles(connectionId);
    },
    enabled: !!connectionId,
  });
}

export function usePullMutation() {
  const qc = useQueryClient();
  return useMutation<LocalBackup, Error, { connectionId: string; filename: string }>({
    mutationFn: ({ connectionId, filename }) => pullFromRemote(connectionId, filename),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LOCAL_BACKUPS_KEY });
    },
  });
}

export function useRestoreMutation() {
  return useMutation<RestoreResult, Error, { backupId: string; filename: string }>({
    mutationFn: ({ backupId, filename }) => restoreLocal(backupId, filename),
  });
}
```

- [ ] **Step 2 : TypeCheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/hooks/useBackups.ts
git commit -m "feat(frontend): hooks React Query backups (local/remote/pull/restore)"
```

---

## Task 12 : Composant RestoreConfirmDialog

**Files:**
- Create: `frontend/src/components/RestoreConfirmDialog.tsx`
- Create: `frontend/src/__tests__/RestoreConfirmDialog.test.tsx`

- [ ] **Step 1 : Écrire les tests rouges**

Créer `frontend/src/__tests__/RestoreConfirmDialog.test.tsx` :

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "../i18n/i18n";
import { RestoreConfirmDialog } from "../components/RestoreConfirmDialog";

function renderDialog(props: Partial<React.ComponentProps<typeof RestoreConfirmDialog>> = {}) {
  return render(
    <I18nextProvider i18n={i18n}>
      <RestoreConfirmDialog
        open={true}
        filename="backup-2026-05-14.sql.gz"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isLoading={false}
        {...props}
      />
    </I18nextProvider>,
  );
}

describe("RestoreConfirmDialog", () => {
  it("disables confirm button until filename is typed exactly", () => {
    renderDialog();
    const confirm = screen.getByRole("button", { name: /confirm/i });
    expect(confirm).toBeDisabled();

    const input = screen.getByLabelText(/filename/i);
    fireEvent.change(input, { target: { value: "wrong.sql.gz" } });
    expect(confirm).toBeDisabled();

    fireEvent.change(input, { target: { value: "backup-2026-05-14.sql.gz" } });
    expect(confirm).not.toBeDisabled();
  });

  it("calls onConfirm with the filename when confirm is clicked", () => {
    const onConfirm = vi.fn();
    renderDialog({ onConfirm });

    const input = screen.getByLabelText(/filename/i);
    fireEvent.change(input, { target: { value: "backup-2026-05-14.sql.gz" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(onConfirm).toHaveBeenCalledWith("backup-2026-05-14.sql.gz");
  });

  it("calls onCancel when cancel is clicked", () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("disables both buttons during loading", () => {
    renderDialog({ isLoading: true });
    expect(screen.getByRole("button", { name: /confirm/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2 : Lancer pour vérifier l'échec**

```bash
cd frontend && npm test -- RestoreConfirmDialog
```

Attendu : FAIL (composant non trouvé).

- [ ] **Step 3 : Implémenter le composant**

Créer `frontend/src/components/RestoreConfirmDialog.tsx` :

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "./ui/dialog";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

interface RestoreConfirmDialogProps {
  open: boolean;
  filename: string;
  isLoading: boolean;
  onConfirm: (filename: string) => void;
  onCancel: () => void;
}

export function RestoreConfirmDialog({
  open, filename, isLoading, onConfirm, onCancel,
}: RestoreConfirmDialogProps) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");

  const matches = typed === filename;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-destructive">
            {t("backups.restore.dialog.title")}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p className="text-destructive font-semibold">
            {t("backups.restore.dialog.warning")}
          </p>
          <p>{t("backups.restore.dialog.instructions", { filename })}</p>
          <div className="space-y-2">
            <Label htmlFor="restore-confirm-input">
              {t("backups.restore.dialog.filenameLabel")}
            </Label>
            <Input
              id="restore-confirm-input"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={filename}
              autoComplete="off"
              disabled={isLoading}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={() => onConfirm(filename)}
            disabled={!matches || isLoading}
          >
            {t("backups.restore.dialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4 : Ajouter les clés i18n minimum pour faire passer les tests**

Ajouter à `frontend/src/i18n/fr.json` (bloc `backups`) :

```json
{
  "backups": {
    "restore": {
      "dialog": {
        "title": "Restaurer la base de données",
        "warning": "ATTENTION : cette opération va supprimer toutes les données actuelles et les remplacer par celles du backup.",
        "instructions": "Pour confirmer, saisissez exactement le nom du fichier : {{filename}}",
        "filenameLabel": "Nom du fichier",
        "confirm": "Confirmer la restauration"
      }
    }
  },
  "common": {
    "cancel": "Annuler"
  }
}
```

Idem en anglais dans `en.json` :

```json
{
  "backups": {
    "restore": {
      "dialog": {
        "title": "Restore database",
        "warning": "WARNING: this will drop all current data and replace it with the backup.",
        "instructions": "To confirm, type the filename exactly: {{filename}}",
        "filenameLabel": "Filename",
        "confirm": "Confirm restore"
      }
    }
  },
  "common": {
    "cancel": "Cancel"
  }
}
```

(Si `common.cancel` existe déjà, ne pas dupliquer.)

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
cd frontend && npm test -- RestoreConfirmDialog
```

Attendu : 4 PASSED.

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/components/RestoreConfirmDialog.tsx \
        frontend/src/__tests__/RestoreConfirmDialog.test.tsx \
        frontend/src/i18n/fr.json \
        frontend/src/i18n/en.json
git commit -m "feat(frontend): RestoreConfirmDialog avec saisie filename matching"
```

---

## Task 13 : Composant LocalBackupsSection

**Files:**
- Create: `frontend/src/components/LocalBackupsSection.tsx`

- [ ] **Step 1 : Implémenter le composant**

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocalBackups, useRestoreMutation } from "../hooks/useBackups";
import { RestoreConfirmDialog } from "./RestoreConfirmDialog";
import { Button } from "./ui/button";
import type { LocalBackup } from "../lib/backupsApi";

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function LocalBackupsSection() {
  const { t } = useTranslation();
  const { data: backups, isLoading, error } = useLocalBackups();
  const restore = useRestoreMutation();
  const [restoreTarget, setRestoreTarget] = useState<LocalBackup | null>(null);

  if (isLoading) return <div>{t("common.loading")}</div>;
  if (error) return <div className="text-destructive">{t("common.errorLoading")}</div>;

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">{t("backups.local.title")}</h2>

      {backups && backups.length === 0 ? (
        <p className="text-muted-foreground">{t("backups.local.empty")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2">{t("backups.local.columns.filename")}</th>
              <th>{t("backups.local.columns.size")}</th>
              <th>{t("backups.local.columns.status")}</th>
              <th>{t("backups.local.columns.origin")}</th>
              <th>{t("backups.local.columns.created")}</th>
              <th>{t("backups.local.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {backups?.map((b) => (
              <tr key={b.id} className="border-b">
                <td className="py-2 font-mono">{b.filename}</td>
                <td>{formatSize(b.size_bytes)}</td>
                <td>{b.status}</td>
                <td>
                  {b.source_remote_connection_id
                    ? t("backups.local.origin.remote")
                    : t("backups.local.origin.dump")}
                </td>
                <td>{new Date(b.created_at).toLocaleString()}</td>
                <td>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setRestoreTarget(b)}
                    disabled={b.status !== "completed"}
                  >
                    {t("backups.local.actions.restore")}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {restoreTarget && (
        <RestoreConfirmDialog
          open={true}
          filename={restoreTarget.filename}
          isLoading={restore.isPending}
          onCancel={() => setRestoreTarget(null)}
          onConfirm={(fname) => {
            restore.mutate(
              { backupId: restoreTarget.id, filename: fname },
              {
                onSuccess: () => {
                  setRestoreTarget(null);
                  alert(t("backups.restore.success"));
                },
                onError: (err) => alert(`${t("backups.restore.error")}: ${err.message}`),
              },
            );
          }}
        />
      )}
    </section>
  );
}
```

⚠ `alert()` est utilisé temporairement pour l'UX feedback — en respect de la memory `feedback_no_system_prompt`, on devrait utiliser un Toast shadcn. Mais le projet a-t-il un `Toaster` global ? À vérifier dans Task 15. Si oui, remplacer les 2 `alert()` par `toast.success` / `toast.error`. Sinon, garder `alert()` pour ce MVP et ouvrir un ticket de suivi.

- [ ] **Step 2 : Ajouter les clés i18n**

Compléter `frontend/src/i18n/fr.json` (sous `backups`) :

```json
{
  "local": {
    "title": "Backups locaux",
    "empty": "Aucun backup local.",
    "columns": {
      "filename": "Fichier",
      "size": "Taille",
      "status": "Statut",
      "origin": "Origine",
      "created": "Créé le",
      "actions": "Actions"
    },
    "origin": {
      "remote": "Pull depuis remote",
      "dump": "Dump local"
    },
    "actions": {
      "restore": "Restaurer"
    }
  },
  "restore": {
    "success": "Restauration réussie.",
    "error": "Erreur de restauration"
  }
}
```

Idem `en.json` (clés équivalentes en anglais).

- [ ] **Step 3 : TypeCheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/LocalBackupsSection.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): LocalBackupsSection avec action restore"
```

---

## Task 14 : Composant RemoteBackupsBrowser

**Files:**
- Create: `frontend/src/components/RemoteBackupsBrowser.tsx`

- [ ] **Step 1 : Implémenter le composant**

```typescript
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useRemoteFiles, usePullMutation } from "../hooks/useBackups";
import { Button } from "./ui/button";

interface RemoteConnection {
  id: string;
  name: string;
  kind: "sftp" | "ftps" | "s3";
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function RemoteBackupsBrowser() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pull = usePullMutation();

  const { data: connections } = useQuery<RemoteConnection[]>({
    queryKey: ["backup-remotes"],
    queryFn: async () => {
      const resp = await fetch("/api/admin/backup-remotes");
      if (!resp.ok) throw new Error("Failed to load connections");
      return resp.json();
    },
  });

  const { data: files, isLoading, error } = useRemoteFiles(selectedId);

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">{t("backups.remote.title")}</h2>

      <div className="space-y-2">
        <label htmlFor="remote-selector" className="text-sm font-medium">
          {t("backups.remote.selectConnection")}
        </label>
        <select
          id="remote-selector"
          className="w-full max-w-md rounded border px-2 py-1"
          value={selectedId ?? ""}
          onChange={(e) => setSelectedId(e.target.value || null)}
        >
          <option value="">{t("backups.remote.choosePlaceholder")}</option>
          {connections?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.kind})
            </option>
          ))}
        </select>
      </div>

      {!selectedId ? (
        <p className="text-muted-foreground text-sm">{t("backups.remote.noSelection")}</p>
      ) : isLoading ? (
        <p>{t("common.loading")}</p>
      ) : error ? (
        <p className="text-destructive">
          {t("backups.remote.error")}: {(error as Error).message}
        </p>
      ) : files && files.length === 0 ? (
        <p className="text-muted-foreground">{t("backups.remote.empty")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2">{t("backups.remote.columns.filename")}</th>
              <th>{t("backups.remote.columns.size")}</th>
              <th>{t("backups.remote.columns.lastModified")}</th>
              <th>{t("backups.remote.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {files?.map((f) => (
              <tr key={f.filename} className="border-b">
                <td className="py-2 font-mono">{f.filename}</td>
                <td>{formatSize(f.size_bytes)}</td>
                <td>{f.last_modified ? new Date(f.last_modified).toLocaleString() : "—"}</td>
                <td>
                  <Button
                    size="sm"
                    onClick={() =>
                      pull.mutate(
                        { connectionId: selectedId, filename: f.filename },
                        {
                          onSuccess: () => alert(t("backups.remote.pullSuccess")),
                          onError: (err) =>
                            alert(`${t("backups.remote.pullError")}: ${err.message}`),
                        },
                      )
                    }
                    disabled={pull.isPending}
                  >
                    {t("backups.remote.actions.pull")}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

- [ ] **Step 2 : Ajouter les clés i18n**

Compléter `frontend/src/i18n/fr.json` (sous `backups`) :

```json
{
  "remote": {
    "title": "Backups distants",
    "selectConnection": "Connexion",
    "choosePlaceholder": "— Choisir une connexion —",
    "noSelection": "Sélectionne une connexion pour lister ses fichiers.",
    "empty": "Aucun fichier sur ce remote.",
    "error": "Erreur de chargement",
    "pullSuccess": "Fichier téléchargé localement.",
    "pullError": "Erreur de téléchargement",
    "columns": {
      "filename": "Fichier",
      "size": "Taille",
      "lastModified": "Modifié le",
      "actions": "Actions"
    },
    "actions": {
      "pull": "Tirer en local"
    }
  }
}
```

Idem en anglais.

- [ ] **Step 3 : TypeCheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/RemoteBackupsBrowser.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): RemoteBackupsBrowser avec action pull"
```

---

## Task 15 : Page BackupsPage + routing + sidebar

**Files:**
- Create: `frontend/src/pages/BackupsPage.tsx`
- Create: `frontend/src/__tests__/BackupsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`

- [ ] **Step 1 : Créer la page**

`frontend/src/pages/BackupsPage.tsx` :

```typescript
import { useTranslation } from "react-i18next";
import { LocalBackupsSection } from "../components/LocalBackupsSection";
import { RemoteBackupsBrowser } from "../components/RemoteBackupsBrowser";

export default function BackupsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-8 p-6">
      <h1 className="text-2xl font-bold">{t("backups.pageTitle")}</h1>
      <LocalBackupsSection />
      <RemoteBackupsBrowser />
    </div>
  );
}
```

Ajouter les clés i18n :

```json
{
  "backups": {
    "pageTitle": "Sauvegardes"  // FR
    // "pageTitle": "Backups"   // EN
  }
}
```

- [ ] **Step 2 : Écrire un test smoke sur la page**

`frontend/src/__tests__/BackupsPage.test.tsx` :

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import i18n from "../i18n/i18n";
import BackupsPage from "../pages/BackupsPage";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("BackupsPage", () => {
  it("renders both sections (local + remote)", async () => {
    mockFetch.mockImplementation(async (url: string) => {
      if (url.includes("/api/admin/local-backups")) {
        return { ok: true, json: async () => [] };
      }
      if (url.includes("/api/admin/backup-remotes")) {
        return { ok: true, json: async () => [] };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <BackupsPage />
        </QueryClientProvider>
      </I18nextProvider>,
    );

    expect(await screen.findByText(/Sauvegardes|Backups/i)).toBeInTheDocument();
    expect(await screen.findByText(/Backups locaux|Local/i)).toBeInTheDocument();
    expect(await screen.findByText(/Backups distants|Remote/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3 : Ajouter la route dans App.tsx**

Lire `frontend/src/App.tsx`, repérer le pattern de route existant (par ex `<Route path="/remote-backups" ... />`), et ajouter :

```typescript
const BackupsPage = lazy(() => import("./pages/BackupsPage"));

// dans <Routes>:
<Route path="/backups" element={<BackupsPage />} />
```

(Adapter exactement à la convention `lazy/Suspense` du fichier.)

- [ ] **Step 4 : Ajouter l'entrée Sidebar**

Lire `frontend/src/components/Sidebar.tsx`, repérer la section "admin", ajouter une entrée vers `/backups` avec le label `t("backups.pageTitle")` et une icône (ex: `Archive` de lucide-react). Restriction `admin` only (suivre le pattern existant pour les autres entrées admin).

Exemple (à adapter au pattern réel du fichier) :

```typescript
{ to: "/backups", label: t("backups.pageTitle"), icon: Archive, roles: ["admin"] },
```

- [ ] **Step 5 : Vérifier les tests**

```bash
cd frontend && npm test -- BackupsPage
```

Attendu : 1 PASSED.

- [ ] **Step 6 : TypeCheck + lint**

```bash
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

- [ ] **Step 7 : Commit**

```bash
git add frontend/src/pages/BackupsPage.tsx \
        frontend/src/__tests__/BackupsPage.test.tsx \
        frontend/src/App.tsx \
        frontend/src/components/Sidebar.tsx \
        frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(frontend): page /backups + route + entrée Sidebar"
```

---

## Task 16 : Vérification finale + déploiement LXC 201

**Files:** aucun changement de code attendu ici, mais smoke tests.

- [ ] **Step 1 : Lancer toute la suite backend**

```bash
cd backend && uv run pytest -v
```

Attendu : tous PASSED. Identifier toute régression introduite.

- [ ] **Step 2 : Lancer toute la suite frontend**

```bash
cd frontend && npm test
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

Attendu : tous PASSED, 0 erreur TS, 0 warning lint.

- [ ] **Step 3 : Pousser sur origin**

⚠ Pousser uniquement après confirmation utilisateur. Suivre la mémoire `feedback_no_bypass_deploy`.

```bash
git push origin feat/mom-bus
```

- [ ] **Step 4 : Déployer sur LXC 201**

⚠ Demander confirmation utilisateur avant. Suivre `feedback_deploy_rebuild_for_new_files` — `--rebuild` est requis car nouveaux fichiers.

```bash
./scripts/deploy.sh --rebuild
```

- [ ] **Step 5 : Vérifier la migration 104 appliquée**

```bash
ssh pve "pct exec 201 -- docker exec agflow-backend python -m agflow.db.migrations"
```

Attendu : pas d'erreur, log indique 104 déjà appliquée (ou applique 104 si pas encore).

- [ ] **Step 6 : Smoke test manuel**

1. Ouvrir `/backups` → la page charge sans erreur console
2. Section locale : créer un dump (bouton existant) → apparaît dans la table
3. Section remote : sélectionner une connexion configurée → fichiers listés (ou message "vide" si nouvelle config)
4. Push un local backup vers remote → fichier apparaît dans la section remote après refresh
5. Pull le fichier remote → apparaît dans section locale avec `Origine = Pull depuis remote`
6. Cliquer Restaurer sur le fichier pull → dialog s'ouvre, le bouton confirm est désactivé tant que le filename n'est pas exact
7. Confirmer la restauration → la DB est restaurée (vérifier en relisant un table existante après op)

- [ ] **Step 7 : Documenter le smoke test**

Créer `docs/functionnalTests/tests/11-restore-from-remote.md` avec cartouche standard (suivre le pattern des fichiers 01-10 existants).

- [ ] **Step 8 : Commit final**

```bash
git add docs/functionnalTests/tests/11-restore-from-remote.md
git commit -m "docs(remote-backups): test fonctionnel 11 — pull + restore depuis remote"
```

---

## Checklist de validation finale

- [ ] Migration 104 ajoute `source_remote_connection_id` avec FK `ON DELETE SET NULL`
- [ ] Protocol étend `list_remote` + `download_stream` + dataclass `RemoteFile`
- [ ] 3 providers (SFTP/FTPS/S3) implémentent `list_remote` + `download_stream` avec gestion d'erreur cohérente (`RemoteBackupProviderError`)
- [ ] `pull_remote_to_local` acquiert `backup_lock`, fait rollback sur erreur, expose `source_remote_connection_id`
- [ ] `restore_local_backup` acquiert `backup_lock` et délègue à `db_backup.restore_dump` existant (réutilisation, pas de duplication)
- [ ] Endpoint `GET /api/admin/backup-remotes/{id}/files` retourne 404/422/200 selon état
- [ ] Endpoint `POST /api/admin/local-backups/pull-from-remote/{remote_id}` accepte uniquement filename sans separator (422 sinon)
- [ ] Endpoint `POST /api/admin/local-backups/{id}/restore` exige le filename matchant exactement (422 sinon)
- [ ] UI page `/backups` accessible admin only, sidebar mise à jour
- [ ] `RestoreConfirmDialog` n'active confirm QUE si l'input matche le filename
- [ ] i18n complète FR + EN sur toutes les clés `backups.*`
- [ ] Tous les tests backend + frontend passent
- [ ] Aucune régression sur `test_local_backups.py`, `test_remote_backup_connections.py`, `test_remote_backup_providers.py`
- [ ] Migration 104 appliquée sur LXC 201
- [ ] Smoke test 11 documenté

---

## Notes pour l'exécutant

1. **Toast vs alert** : la mémoire `feedback_no_system_prompt` interdit `window.prompt/confirm/alert`. Si le projet a déjà un `Toaster` shadcn (`shadcn add toast`), remplacer les 4 `alert()` dans `LocalBackupsSection` + `RemoteBackupsBrowser` par `toast.success` / `toast.error`. Sinon, faire une Task 17 dédiée à l'ajout du Toaster — ne pas livrer avec `alert()`.

2. **`backup_lock` partagé** : 4 opérations le contestent maintenant (dump, push, pull, restore). Toutes sont sérialisées — c'est intentionnel pour exclure restore concurrent avec un dump en cours. Bien le noter dans la docstring si elle existe sur `backup_lock`.

3. **Pattern `async def f() -> AsyncIterator` vs `async def f() -> AsyncIterator` qui retourne `_gen()`** : le code existant (`stream_backup_chunks`) utilise le pattern `async def` qui `return`s un AsyncIterator (pas un coroutine). Les tests existants l'utilisent comme tel (`await stream_backup_chunks(...)`). Ce plan suit le même pattern pour cohérence — ne pas réécrire en `def` synchrone.

4. **conftest backend** : les tests d'API supposent une fixture `client` (TestClient FastAPI) avec `require_admin` overridé. Vérifier qu'elle existe dans `backend/tests/conftest.py` — sinon adapter le pattern des autres tests `tests/api/test_*.py`.

5. **Volume Docker `agflow_data_dir`** : confirmer que le volume monté sur `/app/data` (path interne dans le container) survit aux `deploy.sh --rebuild` (cf mémoire `feedback_deploy_rebuild_for_new_files`). Sinon, les backups locaux sont perdus à chaque déploiement → bloquant fonctionnel.
