# Google Drive Remote Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter la connexion distante `kind='gdrive'` aux remote backups d'agflow.docker, avec setup OAuth 2.0 user-delegated, upload des dumps Postgres dans un dossier Google Drive dédié, et restore depuis Drive via le flow `pull_remote_to_local` existant.

**Architecture:** Provider Drive qui implémente le `RemoteBackupProvider` Protocol existant (4 méthodes : test_connection / upload_stream / list_remote / download_stream). Couche fine `gdrive_client.py` qui isole le SDK Google des tests. Flow OAuth orchestré par `gdrive_oauth_session.py` avec table dédiée `oauth_pending_session` (state + client_secret chiffré pgcrypto + TTL 10min + reaper). Credentials persistés dans le coffre Harpocrate par défaut, référencés via `${vault://default:remote_backups/<id>/oauth}` dans la colonne `config.credentials_ref`. Frontend wizard en 3 phases (Setup → Auth → Confirmed) avec popup + polling.

**Tech Stack:** Python 3.12, asyncpg, FastAPI, `google-auth>=2.30`, `google-auth-oauthlib>=1.2`, `google-api-python-client>=2.130`, structlog, pytest + pytest-asyncio / Vite + React 18 + TanStack Query + Zod + i18next + Vitest

---

## File Structure

### Backend — créés

| Fichier | Responsabilité |
|---|---|
| `backend/migrations/107_remote_backup_kinds_gdrive.sql` | Étend CHECK kind à inclure 'gdrive' |
| `backend/migrations/108_oauth_pending_session.sql` | Table state OAuth + index TTL |
| `backend/src/agflow/services/remote_backup_providers/gdrive_client.py` | Helpers SDK Google (build_credentials, build_drive_service, build_flow, fetch_user_email, refresh) |
| `backend/src/agflow/services/remote_backup_providers/gdrive_provider.py` | Implémentation `RemoteBackupProvider` pour Drive |
| `backend/src/agflow/services/gdrive_oauth_session.py` | Orchestration start/consume/get/reauthorize du flow OAuth |
| `backend/src/agflow/services/oauth_pending_reaper.py` | Worker startup qui purge les pending expirés (tick 5min) |
| `backend/tests/services/test_gdrive_client.py` | Tests purs des helpers SDK (mock googleapiclient) |
| `backend/tests/services/test_gdrive_provider.py` | Tests des 4 méthodes Protocol |
| `backend/tests/services/test_gdrive_oauth_session.py` | Tests orchestration OAuth |
| `backend/tests/services/test_oauth_pending_reaper.py` | Tests purge |
| `backend/tests/api/test_admin_backup_remotes_oauth_gdrive.py` | Tests intégration 5 endpoints OAuth |
| `docs/admin/gdrive-setup.md` | Guide admin Google Cloud Console |

### Backend — modifiés

| Fichier | Modification |
|---|---|
| `backend/pyproject.toml` | + 3 deps Google |
| `backend/Dockerfile` | + 3 deps Google (listes désynchronisées, leçon Harpocrate) |
| `backend/src/agflow/services/remote_backup_providers/factory.py` | + case `"gdrive"` |
| `backend/src/agflow/api/admin/remote_backup_connections.py` | + 5 endpoints OAuth + 1 reauthorize + refus 400 sur POST CRUD générique pour kind=gdrive |
| `backend/src/agflow/main.py` | + démarrage `oauth_pending_reaper` dans lifespan |

### Frontend — créés

| Fichier | Responsabilité |
|---|---|
| `frontend/src/lib/gdriveOAuth.ts` | Helper popup OAuth + polling, 3 erreurs typées |
| `frontend/src/lib/adminBackupRemotesApi.ts` | Wrapper REST des 6 nouveaux endpoints |
| `frontend/src/components/backup-remotes/GDriveFields.tsx` | Wizard 3 phases (Setup/Auth/Confirmed) |

### Frontend — modifiés

| Fichier | Modification |
|---|---|
| `frontend/src/components/backup-remotes/ConnectionModal.tsx` | + option 'gdrive' au sélecteur kind + branchement GDriveFields |
| `frontend/src/pages/RemoteBackupConnectionsPage.tsx` | + colonne « cible » adaptée (user_email + folder_name pour gdrive) + bouton Re-autoriser |
| `frontend/src/i18n/fr.json` | + clés `backups.gdrive.*` (~25) |
| `frontend/src/i18n/en.json` | + clés `backups.gdrive.*` (~25) |

---

## LOT 1 — Foundations (migrations + dépendances)

### Task 1 : Migration 107 (kind gdrive)

**Files:**
- Create: `backend/migrations/107_remote_backup_kinds_gdrive.sql`

- [ ] **Step 1 : Écrire la migration**

```sql
-- 107_remote_backup_kinds_gdrive.sql — Ajoute 'gdrive' au CHECK kind
--
-- Nouveau provider OAuth Google Drive pour les remote backups. Voir spec
-- docs/superpowers/specs/2026-05-16-google-drive-remote-backup-design.md.

ALTER TABLE remote_backup_connections
    DROP CONSTRAINT remote_backup_connections_kind_check;

ALTER TABLE remote_backup_connections
    ADD CONSTRAINT remote_backup_connections_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps', 'gdrive'));
```

- [ ] **Step 2 : Vérifier que la migration s'applique sans erreur**

La validation se fera au LOT 6 via `./scripts/run-test.sh`. Pour l'instant, juste vérifier la syntaxe :

```bash
# Doit retourner du SQL valide sans erreur
cat backend/migrations/107_remote_backup_kinds_gdrive.sql | grep -E "ALTER|CHECK"
```

Expected output : 3 lignes contenant les statements ALTER + CHECK.

- [ ] **Step 3 : Commit**

```bash
git add backend/migrations/107_remote_backup_kinds_gdrive.sql
git commit -m "feat(gdrive-db): migration 107 — ajoute 'gdrive' au CHECK kind"
```

---

### Task 2 : Migration 108 (oauth_pending_session)

**Files:**
- Create: `backend/migrations/108_oauth_pending_session.sql`

- [ ] **Step 1 : Écrire la migration**

```sql
-- 108_oauth_pending_session.sql — Table pour le round-trip OAuth
--
-- Persiste l'état OAuth entre `/start` (redirection Google) et `/callback`.
-- TTL court (10 min). Le `client_secret` est chiffré pgcrypto via HARPOCRATE_DEK
-- pendant le round-trip ; au callback il est déchiffré, utilisé pour fetch_token,
-- puis re-chiffré dans Harpocrate au path final remote_backups/<id>/oauth.
-- Worker `oauth_pending_reaper` purge les expirés/consumed (tick 5min).

CREATE TABLE oauth_pending_session (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    state                    text NOT NULL UNIQUE,
    kind                     text NOT NULL CHECK (kind IN ('gdrive')),
    actor_user_id            uuid REFERENCES users(id) ON DELETE SET NULL,
    redirect_uri             text NOT NULL,
    form_data                jsonb NOT NULL DEFAULT '{}'::jsonb,
    client_secret_encrypted  bytea NOT NULL,
    expires_at               timestamptz NOT NULL,
    consumed_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_pending_expires_at
    ON oauth_pending_session(expires_at)
    WHERE consumed_at IS NULL;
```

- [ ] **Step 2 : Vérifier la syntaxe SQL**

```bash
grep -c "CREATE" backend/migrations/108_oauth_pending_session.sql
```

Expected output : `2` (CREATE TABLE + CREATE INDEX).

- [ ] **Step 3 : Commit**

```bash
git add backend/migrations/108_oauth_pending_session.sql
git commit -m "feat(gdrive-db): migration 108 — table oauth_pending_session"
```

---

### Task 3 : Dépendances Python (pyproject + Dockerfile)

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/Dockerfile`

- [ ] **Step 1 : Identifier la section dependencies dans pyproject.toml**

```bash
grep -nA 30 "^dependencies = " backend/pyproject.toml | head -35
```

Note les lignes de la liste pour préserver le formatage.

- [ ] **Step 2 : Ajouter les 3 deps Google dans pyproject.toml**

Dans `backend/pyproject.toml`, dans la liste `dependencies = [...]`, ajouter ces 3 lignes (respecter l'indentation existante) :

```toml
    "google-auth>=2.30,<3",
    "google-auth-oauthlib>=1.2,<2",
    "google-api-python-client>=2.130,<3",
```

- [ ] **Step 3 : Identifier la liste hardcodée dans Dockerfile**

```bash
grep -nA 25 "uv pip install" backend/Dockerfile | head -30
```

- [ ] **Step 4 : Ajouter les 3 deps dans Dockerfile**

Localiser le bloc `RUN uv pip install --system --no-cache \` (vers ligne 33-52) et ajouter dans la liste (respecter le `\` de continuation) :

```dockerfile
    google-auth>=2.30 \
    google-auth-oauthlib>=1.2 \
    google-api-python-client>=2.130 \
```

- [ ] **Step 5 : Vérifier que `uv sync` ne casse pas localement**

```bash
cd backend && uv sync 2>&1 | tail -5
```

Expected output : `Resolved N packages` sans erreur de conflit. Ignorer le warning hardlink.

- [ ] **Step 6 : Commit**

```bash
git add backend/pyproject.toml backend/Dockerfile
git commit -m "chore(gdrive): + google-auth + google-auth-oauthlib + google-api-python-client"
```

---

## LOT 2 — Provider Drive (gdrive_client + gdrive_provider + factory)

### Task 4 : gdrive_client.py — couche SDK Google

**Files:**
- Create: `backend/src/agflow/services/remote_backup_providers/gdrive_client.py`
- Test: `backend/tests/services/test_gdrive_client.py`

- [ ] **Step 1 : Écrire les tests rouges**

`backend/tests/services/test_gdrive_client.py` :

```python
"""Tests purs des helpers gdrive_client (mocks du SDK Google)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agflow.services.remote_backup_providers import gdrive_client


def test_build_credentials_returns_credentials_from_dict() -> None:
    creds_dict = {
        "client_id": "abc.apps.googleusercontent.com",
        "client_secret": "GOCSPX-secret",
        "refresh_token": "1//0g-refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/drive.file",
    }
    creds = gdrive_client.build_credentials(creds_dict)
    assert creds.client_id == creds_dict["client_id"]
    assert creds.refresh_token == creds_dict["refresh_token"]


def test_build_flow_returns_flow_with_correct_scopes() -> None:
    flow = gdrive_client.build_flow(
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-secret",
        redirect_uri="https://example.com/cb",
    )
    assert "https://www.googleapis.com/auth/drive.file" in flow.oauth2session.scope


def test_build_drive_service_calls_googleapiclient_build() -> None:
    fake_creds = MagicMock()
    with patch(
        "agflow.services.remote_backup_providers.gdrive_client.build"
    ) as mock_build:
        gdrive_client.build_drive_service(fake_creds)
        mock_build.assert_called_once_with(
            "drive", "v3", credentials=fake_creds, cache_discovery=False,
        )


@pytest.mark.asyncio
async def test_fetch_user_email_returns_email_from_userinfo() -> None:
    fake_creds = MagicMock()
    with patch(
        "agflow.services.remote_backup_providers.gdrive_client.build"
    ) as mock_build:
        mock_service = MagicMock()
        mock_service.userinfo().get().execute.return_value = {
            "email": "user@example.com",
        }
        mock_build.return_value = mock_service
        email = await gdrive_client.fetch_user_email(fake_creds)
    assert email == "user@example.com"


@pytest.mark.asyncio
async def test_refresh_calls_credentials_refresh() -> None:
    fake_creds = MagicMock()
    with patch(
        "agflow.services.remote_backup_providers.gdrive_client.Request"
    ) as mock_request:
        await gdrive_client.refresh(fake_creds)
        fake_creds.refresh.assert_called_once_with(mock_request.return_value)
```

- [ ] **Step 2 : Run les tests, vérifier qu'ils échouent**

```bash
cd backend && uv run pytest tests/services/test_gdrive_client.py -v 2>&1 | tail -15
```

Expected : `ModuleNotFoundError: No module named 'agflow.services.remote_backup_providers.gdrive_client'`.

- [ ] **Step 3 : Écrire l'implémentation**

`backend/src/agflow/services/remote_backup_providers/gdrive_client.py` :

```python
"""Couche fine au-dessus du SDK Google pour Drive + OAuth2.

Toutes les fonctions wrappent un appel sync du SDK (qui n'est pas async-native)
soit dans un `asyncio.to_thread`, soit en sync direct si le caller orchestre lui-même.
Permet de mocker proprement le SDK dans les tests.
"""
from __future__ import annotations

import asyncio

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import Resource, build

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_USERINFO_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


def build_credentials(creds_dict: dict) -> Credentials:
    """Reconstruit un objet Credentials Google depuis le dict stocké en vault."""
    return Credentials(
        token=None,
        refresh_token=creds_dict["refresh_token"],
        token_uri=creds_dict["token_uri"],
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=[creds_dict["scope"]],
    )


def build_drive_service(creds: Credentials) -> Resource:
    """Instancie le client Drive v3."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def build_flow(
    *, client_id: str, client_secret: str, redirect_uri: str,
) -> Flow:
    """Construit un Flow OAuth2 pour Drive (scope drive.file + userinfo.email)."""
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        },
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=[_DRIVE_SCOPE, _USERINFO_SCOPE],
        redirect_uri=redirect_uri,
    )
    return flow


async def fetch_user_email(creds: Credentials) -> str:
    """Retourne l'email du compte Google associé aux credentials."""
    def _sync() -> str:
        service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = service.userinfo().get().execute()
        return str(info["email"])

    return await asyncio.to_thread(_sync)


async def refresh(creds: Credentials) -> Credentials:
    """Refresh l'access_token via le refresh_token. Mutation en place de creds."""
    def _sync() -> None:
        creds.refresh(Request())

    await asyncio.to_thread(_sync)
    return creds
```

- [ ] **Step 4 : Run les tests, vérifier qu'ils passent**

```bash
cd backend && uv run pytest tests/services/test_gdrive_client.py -v 2>&1 | tail -10
```

Expected : `5 passed`.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/remote_backup_providers/gdrive_client.py tests/services/test_gdrive_client.py 2>&1 | tail -3
```

Expected : `All checks passed!`.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/gdrive_client.py backend/tests/services/test_gdrive_client.py
git commit -m "feat(gdrive-provider): gdrive_client.py — helpers SDK Google"
```

---

### Task 5 : gdrive_provider.test_connection

**Files:**
- Create: `backend/src/agflow/services/remote_backup_providers/gdrive_provider.py`
- Test: `backend/tests/services/test_gdrive_provider.py`

- [ ] **Step 1 : Écrire le test rouge**

`backend/tests/services/test_gdrive_provider.py` :

```python
"""Tests des 4 méthodes Protocol du GoogleDriveProvider (mocks SDK)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agflow.services.remote_backup_providers.gdrive_provider import GoogleDriveProvider
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_CONFIG = {
    "client_id": "abc.apps.googleusercontent.com",
    "redirect_uri": "https://example.com/cb",
    "folder_name": "agflow-backups",
    "folder_id": "1a2B3c4D5e",
    "user_email": "ops@example.com",
}
_CREDS = {
    "client_id": _CONFIG["client_id"],
    "client_secret": "GOCSPX-secret",
    "refresh_token": "1//0g-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "scope": "https://www.googleapis.com/auth/drive.file",
}


@pytest.mark.asyncio
async def test_test_connection_lists_folder_ok() -> None:
    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_service.files().list().execute.return_value = {"files": []}
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        await provider.test_connection(path="")
    # Pas d'erreur = succès
    fake_service.files().list.assert_called()


@pytest.mark.asyncio
async def test_test_connection_raises_on_http_error() -> None:
    from googleapiclient.errors import HttpError

    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_resp = MagicMock(status=404, reason="Not Found")
    fake_service.files().list().execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error": "Folder not found"}',
    )
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        with pytest.raises(RemoteBackupProviderError, match="404"):
            await provider.test_connection(path="")
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py::test_test_connection_lists_folder_ok -v 2>&1 | tail -10
```

Expected : `ModuleNotFoundError: ... gdrive_provider`.

- [ ] **Step 3 : Écrire l'impl minimale (test_connection seule, les autres méthodes au prochains tasks)**

`backend/src/agflow/services/remote_backup_providers/gdrive_provider.py` :

```python
"""Provider Google Drive — implémente RemoteBackupProvider.

Le paramètre `path` est ignoré par toutes les méthodes : Drive n'a pas de
sous-path interne au folder configuré. On le garde dans la signature pour
préserver le contrat Protocol commun avec sftp/s3/ftps.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import structlog
from googleapiclient.errors import HttpError

from agflow.services.remote_backup_providers import gdrive_client
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProviderError,
    RemoteFile,
)

_log = structlog.get_logger(__name__)


class GoogleDriveProvider:
    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._folder_id: str = config["folder_id"]
        self._creds = gdrive_client.build_credentials(credentials)

    async def test_connection(self, path: str) -> None:
        def _sync() -> None:
            service = gdrive_client.build_drive_service(self._creds)
            service.files().list(
                q=f"'{self._folder_id}' in parents and trashed=false",
                pageSize=1,
                fields="files(id)",
            ).execute()

        try:
            await asyncio.to_thread(_sync)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive test_connection failed: {exc.resp.status} {exc.reason}",
            ) from exc

    async def upload_stream(
        self, path: str, filename: str, source: AsyncIterator[bytes],
    ) -> int:
        raise NotImplementedError("Implemented in next task")

    async def list_remote(self, path: str) -> list[RemoteFile]:
        raise NotImplementedError("Implemented in next task")

    async def download_stream(
        self, path: str, filename: str,
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("Implemented in next task")
        yield b""  # pour satisfaire le type hint AsyncIterator
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py -v 2>&1 | tail -10
```

Expected : `2 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/gdrive_provider.py backend/tests/services/test_gdrive_provider.py
git commit -m "feat(gdrive-provider): gdrive_provider.test_connection"
```

---

### Task 6 : gdrive_provider.upload_stream

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/gdrive_provider.py`
- Modify: `backend/tests/services/test_gdrive_provider.py`

- [ ] **Step 1 : Ajouter le test rouge**

Ajouter à `tests/services/test_gdrive_provider.py` :

```python
@pytest.mark.asyncio
async def test_upload_stream_writes_to_drive_and_returns_size() -> None:
    async def _source():
        yield b"chunk1-"
        yield b"chunk2"

    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_service.files().create().execute.return_value = {"id": "fileXYZ"}
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        size = await provider.upload_stream(
            path="", filename="backup.sql.gz", source=_source(),
        )
    assert size == len(b"chunk1-chunk2")
    fake_service.files().create.assert_called()


@pytest.mark.asyncio
async def test_upload_stream_maps_http_error_to_provider_error() -> None:
    from googleapiclient.errors import HttpError

    async def _source():
        yield b"data"

    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_resp = MagicMock(status=403, reason="Quota Exceeded")
    fake_service.files().create().execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error": "quota"}',
    )
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        with pytest.raises(RemoteBackupProviderError, match="403"):
            await provider.upload_stream(path="", filename="b.sql", source=_source())
```

- [ ] **Step 2 : Run, expect FAIL (NotImplementedError)**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py::test_upload_stream_writes_to_drive_and_returns_size -v 2>&1 | tail -10
```

- [ ] **Step 3 : Implémenter upload_stream**

Dans `gdrive_provider.py`, remplacer le `raise NotImplementedError` de `upload_stream` par :

```python
    async def upload_stream(
        self, path: str, filename: str, source: AsyncIterator[bytes],
    ) -> int:
        import tempfile
        from googleapiclient.http import MediaFileUpload

        # Streame le source dans un tmpfile (le SDK Google n'accepte qu'un FS path).
        bytes_written = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix="-" + filename) as tmp:
            tmp_path = tmp.name
            async for chunk in source:
                tmp.write(chunk)
                bytes_written += len(chunk)

        def _sync_upload() -> None:
            service = gdrive_client.build_drive_service(self._creds)
            media = MediaFileUpload(tmp_path, resumable=True)
            service.files().create(
                body={"name": filename, "parents": [self._folder_id]},
                media_body=media,
                fields="id",
            ).execute()

        try:
            await asyncio.to_thread(_sync_upload)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive upload_stream failed: {exc.resp.status} {exc.reason}",
            ) from exc
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                _log.warning("gdrive.upload_stream.tmpfile_cleanup_failed", path=tmp_path)

        _log.info(
            "gdrive.upload_stream.ok",
            filename=filename, bytes=bytes_written, folder=self._folder_id,
        )
        return bytes_written
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py -v 2>&1 | tail -10
```

Expected : `4 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/gdrive_provider.py backend/tests/services/test_gdrive_provider.py
git commit -m "feat(gdrive-provider): upload_stream resumable via tmpfile"
```

---

### Task 7 : gdrive_provider.list_remote

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/gdrive_provider.py`
- Modify: `backend/tests/services/test_gdrive_provider.py`

- [ ] **Step 1 : Ajouter le test rouge**

```python
@pytest.mark.asyncio
async def test_list_remote_returns_remote_files() -> None:
    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_service.files().list().execute.return_value = {
        "files": [
            {
                "id": "f1", "name": "backup-2026-05-15.sql.gz",
                "size": "12345", "modifiedTime": "2026-05-15T10:00:00.000Z",
            },
            {
                "id": "f2", "name": "backup-2026-05-16.sql.gz",
                "size": "23456", "modifiedTime": "2026-05-16T10:00:00.000Z",
            },
        ],
    }
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        files = await provider.list_remote(path="")
    assert len(files) == 2
    assert files[0].filename == "backup-2026-05-15.sql.gz"
    assert files[0].size_bytes == 12345
    assert files[0].last_modified is not None
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py::test_list_remote_returns_remote_files -v 2>&1 | tail -10
```

- [ ] **Step 3 : Implémenter list_remote**

Dans `gdrive_provider.py`, remplacer `list_remote` :

```python
    async def list_remote(self, path: str) -> list[RemoteFile]:
        from datetime import datetime

        def _sync() -> list[dict]:
            service = gdrive_client.build_drive_service(self._creds)
            resp = service.files().list(
                q=f"'{self._folder_id}' in parents and trashed=false",
                fields="files(id, name, size, modifiedTime)",
                pageSize=1000,
            ).execute()
            return resp.get("files", [])

        try:
            raw = await asyncio.to_thread(_sync)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive list_remote failed: {exc.resp.status} {exc.reason}",
            ) from exc

        result: list[RemoteFile] = []
        for entry in raw:
            ts = entry.get("modifiedTime")
            last_modified = (
                datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
            )
            size = int(entry["size"]) if entry.get("size") is not None else None
            result.append(RemoteFile(
                filename=entry["name"], size_bytes=size, last_modified=last_modified,
            ))
        return result
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py -v 2>&1 | tail -10
```

Expected : `5 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/gdrive_provider.py backend/tests/services/test_gdrive_provider.py
git commit -m "feat(gdrive-provider): list_remote — RemoteFile mapping"
```

---

### Task 8 : gdrive_provider.download_stream

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/gdrive_provider.py`
- Modify: `backend/tests/services/test_gdrive_provider.py`

- [ ] **Step 1 : Ajouter le test rouge**

```python
@pytest.mark.asyncio
async def test_download_stream_yields_file_bytes() -> None:
    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    # files.list pour résoudre l'ID depuis le filename
    fake_service.files().list().execute.return_value = {
        "files": [{"id": "fileXYZ", "name": "backup.sql.gz"}],
    }
    # files.get_media + download
    fake_service.files().get_media.return_value = MagicMock()

    fake_downloader = MagicMock()
    # Simule 2 chunks puis done=True
    fake_downloader.next_chunk.side_effect = [
        (MagicMock(progress=lambda: 0.5), False),
        (MagicMock(progress=lambda: 1.0), True),
    ]

    with (
        patch(
            "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
            return_value=fake_service,
        ),
        patch(
            "agflow.services.remote_backup_providers.gdrive_provider.MediaIoBaseDownload",
            return_value=fake_downloader,
        ),
        # Patch BytesIO pour récupérer le contenu accumulé entre les next_chunk
        patch(
            "agflow.services.remote_backup_providers.gdrive_provider.io.BytesIO",
        ) as mock_bytesio,
    ):
        mock_buf = MagicMock()
        mock_buf.getvalue.side_effect = [b"chunk1", b"chunk1chunk2"]
        mock_buf.seek.return_value = None
        mock_buf.truncate.return_value = None
        mock_bytesio.return_value = mock_buf
        chunks = [chunk async for chunk in provider.download_stream(path="", filename="backup.sql.gz")]

    assert b"".join(chunks) == b"chunk1chunk2"
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py::test_download_stream_yields_file_bytes -v 2>&1 | tail -10
```

- [ ] **Step 3 : Implémenter download_stream + import**

Dans `gdrive_provider.py`, ajouter en haut du fichier :

```python
import io

from googleapiclient.http import MediaIoBaseDownload
```

Puis remplacer `download_stream` :

```python
    async def download_stream(
        self, path: str, filename: str,
    ) -> AsyncIterator[bytes]:
        # Résoudre file_id depuis filename
        def _resolve_id() -> str:
            service = gdrive_client.build_drive_service(self._creds)
            resp = service.files().list(
                q=(
                    f"'{self._folder_id}' in parents and "
                    f"name='{filename}' and trashed=false"
                ),
                fields="files(id)",
                pageSize=1,
            ).execute()
            files = resp.get("files", [])
            if not files:
                raise RemoteBackupProviderError(
                    f"gdrive download_stream: file {filename!r} not found in folder",
                )
            return str(files[0]["id"])

        try:
            file_id = await asyncio.to_thread(_resolve_id)
        except HttpError as exc:
            raise RemoteBackupProviderError(
                f"gdrive download_stream resolve failed: {exc.resp.status}",
            ) from exc

        def _build_downloader() -> tuple[MediaIoBaseDownload, io.BytesIO]:
            service = gdrive_client.build_drive_service(self._creds)
            request = service.files().get_media(fileId=file_id)
            buf = io.BytesIO()
            return MediaIoBaseDownload(buf, request), buf

        downloader, buf = await asyncio.to_thread(_build_downloader)

        previous_pos = 0
        while True:
            def _step() -> tuple[bool, bytes]:
                _status, done = downloader.next_chunk()
                data = buf.getvalue()
                return done, data

            done, data = await asyncio.to_thread(_step)
            new_chunk = data[previous_pos:]
            if new_chunk:
                yield new_chunk
                previous_pos = len(data)
            if done:
                break
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_provider.py -v 2>&1 | tail -10
```

Expected : `6 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/gdrive_provider.py backend/tests/services/test_gdrive_provider.py
git commit -m "feat(gdrive-provider): download_stream — chunked yield"
```

---

### Task 9 : Factory — case 'gdrive'

**Files:**
- Modify: `backend/src/agflow/services/remote_backup_providers/factory.py`
- Create: `backend/tests/services/test_remote_backup_factory_gdrive.py`

- [ ] **Step 1 : Écrire le test rouge**

`backend/tests/services/test_remote_backup_factory_gdrive.py` :

```python
from __future__ import annotations

import pytest

from agflow.services.remote_backup_providers.factory import get_provider
from agflow.services.remote_backup_providers.gdrive_provider import GoogleDriveProvider
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError


def test_factory_returns_gdrive_provider_for_kind_gdrive() -> None:
    config = {"folder_id": "abc"}
    credentials = {
        "client_id": "x.apps.googleusercontent.com",
        "client_secret": "GOCSPX-x",
        "refresh_token": "x",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/drive.file",
    }
    p = get_provider("gdrive", config, credentials)
    assert isinstance(p, GoogleDriveProvider)


def test_factory_unknown_kind_still_raises() -> None:
    with pytest.raises(RemoteBackupProviderError, match="Unknown kind"):
        get_provider("dropbox", {}, {})
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_factory_gdrive.py -v 2>&1 | tail -10
```

Expected : `RemoteBackupProviderError: Unknown kind: 'gdrive'`.

- [ ] **Step 3 : Modifier factory.py**

Remplacer `backend/src/agflow/services/remote_backup_providers/factory.py` :

```python
from __future__ import annotations

from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider
from agflow.services.remote_backup_providers.gdrive_provider import GoogleDriveProvider
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
        case "gdrive":
            return GoogleDriveProvider(config=config, credentials=credentials)
        case _:
            raise RemoteBackupProviderError(f"Unknown kind: {kind!r}")
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_remote_backup_factory_gdrive.py -v 2>&1 | tail -5
```

Expected : `2 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/remote_backup_providers/factory.py backend/tests/services/test_remote_backup_factory_gdrive.py
git commit -m "feat(gdrive-provider): factory — case gdrive"
```

---

## LOT 3 — OAuth orchestration (gdrive_oauth_session)

### Task 10 : start_session

**Files:**
- Create: `backend/src/agflow/services/gdrive_oauth_session.py`
- Create: `backend/tests/services/test_gdrive_oauth_session.py`

- [ ] **Step 1 : Écrire le test rouge**

`backend/tests/services/test_gdrive_oauth_session.py` :

```python
"""Tests intégration de gdrive_oauth_session (DB + vault mockés)."""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Force HARPOCRATE_DEK pour les opérations PGP_SYM_*
os.environ["HARPOCRATE_DEK"] = "test-dek-passphrase-very-long-and-stable-2026"

from agflow.services import gdrive_oauth_session
from agflow.db.pool import fetch_one
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db():
    await reset_schema_and_migrate()
    yield


async def _create_admin_user() -> uuid.UUID:
    from agflow.db.pool import execute
    user_id = uuid.uuid4()
    await execute(
        "INSERT INTO users (id, email, name, role, status) "
        "VALUES ($1, $2, 'admin', 'admin', 'active')",
        user_id, f"admin-{user_id}@example.com",
    )
    return user_id


@pytest.mark.asyncio
async def test_start_session_creates_pending_row_and_returns_url(fresh_db) -> None:
    actor = await _create_admin_user()

    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?state=abc",
        "abc",
    )

    with patch(
        "agflow.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        state, url = await gdrive_oauth_session.start_session(
            actor_user_id=actor,
            name="My Drive Backups",
            folder_name="agflow-backups",
            client_id="abc.apps.googleusercontent.com",
            client_secret="GOCSPX-secret",
            redirect_uri="https://example.com/cb",
        )

    assert len(state) >= 32
    assert "accounts.google.com" in url

    row = await fetch_one(
        "SELECT kind, redirect_uri, form_data, consumed_at, "
        "PGP_SYM_DECRYPT(client_secret_encrypted, $2) AS secret "
        "FROM oauth_pending_session WHERE state = $1",
        state, os.environ["HARPOCRATE_DEK"],
    )
    assert row is not None
    assert row["kind"] == "gdrive"
    assert row["redirect_uri"] == "https://example.com/cb"
    assert row["consumed_at"] is None
    assert row["secret"] == "GOCSPX-secret"

    import json
    fd = row["form_data"]
    if isinstance(fd, str):
        fd = json.loads(fd)
    assert fd["name"] == "My Drive Backups"
    assert fd["folder_name"] == "agflow-backups"
    assert fd["client_id"] == "abc.apps.googleusercontent.com"
    # Le secret ne doit JAMAIS apparaître dans form_data
    assert "client_secret" not in fd
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_gdrive_oauth_session.py::test_start_session_creates_pending_row_and_returns_url -v 2>&1 | tail -10
```

Expected : `ModuleNotFoundError: ... gdrive_oauth_session`.

- [ ] **Step 3 : Implémenter start_session (juste cette fonction)**

`backend/src/agflow/services/gdrive_oauth_session.py` :

```python
"""Orchestration du flow OAuth Google Drive.

start_session    : ouvre une pending row + URL Google d'autorisation
consume_session  : callback Google → INSERT connection + push vault (task 11)
get_session      : polling de status pour le frontend (task 12)
reauthorize      : re-démarre le flow pour une connexion existante (task 13)
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_one
from agflow.services.remote_backup_providers import gdrive_client

_log = structlog.get_logger(__name__)

_PENDING_TTL = timedelta(minutes=10)


def _require_dek() -> str:
    dek = get_settings().harpocrate_dek
    if not dek:
        raise RuntimeError("HARPOCRATE_DEK is not configured")
    return dek


async def start_session(
    *,
    actor_user_id: UUID,
    name: str,
    folder_name: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> tuple[str, str]:
    """Crée une pending row + retourne (state, authorize_url Google)."""
    dek = _require_dek()
    state = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + _PENDING_TTL

    flow = gdrive_client.build_flow(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    authorize_url, _state_unused = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="false",
        state=state,
    )

    form_data = {
        "name": name,
        "folder_name": folder_name,
        "client_id": client_id,
    }
    await execute(
        """
        INSERT INTO oauth_pending_session
            (state, kind, actor_user_id, redirect_uri,
             form_data, client_secret_encrypted, expires_at)
        VALUES ($1, 'gdrive', $2, $3, $4::jsonb, PGP_SYM_ENCRYPT($5, $6), $7)
        """,
        state, actor_user_id, redirect_uri,
        json.dumps(form_data), client_secret, dek, expires_at,
    )
    _log.info(
        "remote_backup.gdrive.oauth_started",
        state=state, name=name, folder_name=folder_name,
        actor_user_id=str(actor_user_id),
    )
    return state, authorize_url


async def consume_session(*, state: str, code: str) -> dict:
    raise NotImplementedError("Task 11")


async def get_session(state: str) -> dict | None:
    raise NotImplementedError("Task 12")


async def reauthorize(*, connection_id: UUID, actor_user_id: UUID) -> tuple[str, str]:
    raise NotImplementedError("Task 13")
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_oauth_session.py::test_start_session_creates_pending_row_and_returns_url -v 2>&1 | tail -10
```

Expected : `1 passed`.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/gdrive_oauth_session.py tests/services/test_gdrive_oauth_session.py 2>&1 | tail -3
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/gdrive_oauth_session.py backend/tests/services/test_gdrive_oauth_session.py
git commit -m "feat(gdrive-oauth): start_session — pending row + url Google"
```

---

### Task 11 : consume_session (callback OAuth complet)

**Files:**
- Modify: `backend/src/agflow/services/gdrive_oauth_session.py`
- Modify: `backend/tests/services/test_gdrive_oauth_session.py`

- [ ] **Step 1 : Ajouter les tests rouges**

```python
@pytest.mark.asyncio
async def test_consume_session_happy_path_creates_connection_and_pushes_vault(
    fresh_db, vault_mock,
) -> None:
    actor = await _create_admin_user()

    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="1//refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-secret",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )

    fake_drive = MagicMock()
    # search-or-create: 0 résultat → on crée folder direct
    fake_drive.files().list().execute.return_value = {"files": []}
    fake_drive.files().create().execute.return_value = {"id": "folder-XYZ"}

    with (
        patch(
            "agflow.services.gdrive_oauth_session.gdrive_client.build_flow",
            return_value=fake_flow,
        ),
        patch(
            "agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service",
            return_value=fake_drive,
        ),
        patch(
            "agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email",
            return_value="ops@example.com",
        ),
    ):
        # 1. start_session pour créer la pending row
        state, _url = await gdrive_oauth_session.start_session(
            actor_user_id=actor,
            name="Backups",
            folder_name="agflow-backups",
            client_id="abc.apps.googleusercontent.com",
            client_secret="GOCSPX-secret",
            redirect_uri="https://example.com/cb",
        )
        # 2. consume_session avec le code Google
        result = await gdrive_oauth_session.consume_session(
            state=state, code="auth-code-from-google",
        )

    assert "connection_id" in result
    assert result["user_email"] == "ops@example.com"
    assert result["folder_id"] == "folder-XYZ"

    # Connexion en DB
    conn = await fetch_one(
        "SELECT kind, name, config FROM remote_backup_connections WHERE id = $1",
        result["connection_id"],
    )
    assert conn["kind"] == "gdrive"
    assert conn["name"] == "Backups"
    import json
    cfg = conn["config"] if isinstance(conn["config"], dict) else json.loads(conn["config"])
    assert cfg["folder_id"] == "folder-XYZ"
    assert cfg["user_email"] == "ops@example.com"
    assert cfg["credentials_ref"].startswith("${vault://")

    # Pending row marquée consumed
    pending = await fetch_one(
        "SELECT consumed_at FROM oauth_pending_session WHERE state = $1", state,
    )
    assert pending["consumed_at"] is not None

    # Vault contient le secret au bon path
    creds_in_vault = vault_mock.get(
        f"remote_backups/{result['connection_id']}/oauth"
    )
    creds_dict = json.loads(creds_in_vault)
    assert creds_dict["refresh_token"] == "1//refresh-token"
    assert creds_dict["client_secret"] == "GOCSPX-secret"


@pytest.mark.asyncio
async def test_consume_session_rejects_unknown_state(fresh_db, vault_mock) -> None:
    with pytest.raises(gdrive_oauth_session.PendingSessionError, match="not found"):
        await gdrive_oauth_session.consume_session(state="unknown", code="x")


@pytest.mark.asyncio
async def test_consume_session_rejects_already_consumed(fresh_db, vault_mock) -> None:
    actor = await _create_admin_user()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="rt", token_uri="https://x", client_id="c", client_secret="s",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    fake_drive = MagicMock()
    fake_drive.files().list().execute.return_value = {"files": []}
    fake_drive.files().create().execute.return_value = {"id": "f"}

    with (
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_flow", return_value=fake_flow),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service", return_value=fake_drive),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email", return_value="u@x"),
    ):
        state, _ = await gdrive_oauth_session.start_session(
            actor_user_id=actor, name="n", folder_name="f",
            client_id="c", client_secret="s", redirect_uri="r",
        )
        await gdrive_oauth_session.consume_session(state=state, code="c")
        with pytest.raises(gdrive_oauth_session.PendingSessionError, match="already consumed"):
            await gdrive_oauth_session.consume_session(state=state, code="c")


@pytest.mark.asyncio
async def test_consume_session_appends_date_suffix_if_folder_name_exists(
    fresh_db, vault_mock,
) -> None:
    actor = await _create_admin_user()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="rt", token_uri="https://x", client_id="c", client_secret="s",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    fake_drive = MagicMock()
    # Le folder demandé existe déjà → suffixe daté
    fake_drive.files().list().execute.return_value = {"files": [{"id": "existing", "name": "agflow-backups"}]}
    fake_drive.files().create().execute.return_value = {"id": "folder-NEW"}

    with (
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_flow", return_value=fake_flow),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service", return_value=fake_drive),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email", return_value="u@x"),
    ):
        state, _ = await gdrive_oauth_session.start_session(
            actor_user_id=actor, name="n", folder_name="agflow-backups",
            client_id="c", client_secret="s", redirect_uri="r",
        )
        await gdrive_oauth_session.consume_session(state=state, code="c")

    # files().create a été appelé avec un nom différent (avec suffixe daté)
    create_call = fake_drive.files().create.call_args
    created_name = create_call.kwargs["body"]["name"]
    assert created_name.startswith("agflow-backups (")
    assert created_name.endswith(")")
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_gdrive_oauth_session.py::test_consume_session_happy_path_creates_connection_and_pushes_vault -v 2>&1 | tail -10
```

- [ ] **Step 3 : Implémenter consume_session + exception + helpers**

Dans `gdrive_oauth_session.py`, remplacer le NotImplementedError de `consume_session` et ajouter en haut du fichier :

```python
from uuid import UUID, uuid4

from agflow.services import vault_client
```

Ajouter la classe d'exception au début du fichier (après les imports) :

```python
class PendingSessionError(Exception):
    """État OAuth introuvable / déjà consommé / expiré."""
```

Implémenter `consume_session` :

```python
async def consume_session(*, state: str, code: str) -> dict:
    dek = _require_dek()

    # 1. Lookup pending row + déchiffrement client_secret
    row = await fetch_one(
        """
        SELECT id, actor_user_id, redirect_uri, form_data,
               PGP_SYM_DECRYPT(client_secret_encrypted, $2) AS client_secret,
               expires_at, consumed_at
        FROM oauth_pending_session WHERE state = $1 AND kind = 'gdrive'
        """,
        state, dek,
    )
    if row is None:
        raise PendingSessionError(f"OAuth state not found: {state[:8]}...")
    if row["consumed_at"] is not None:
        raise PendingSessionError(f"OAuth state already consumed: {state[:8]}...")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise PendingSessionError(f"OAuth state expired: {state[:8]}...")

    form_data = row["form_data"]
    if isinstance(form_data, str):
        form_data = json.loads(form_data)

    # 2. Marquer consumed_at AVANT échange (idempotence stricte)
    await execute(
        "UPDATE oauth_pending_session SET consumed_at = now() WHERE id = $1",
        row["id"],
    )

    # 3. Échanger code → tokens
    flow = gdrive_client.build_flow(
        client_id=form_data["client_id"],
        client_secret=row["client_secret"],
        redirect_uri=row["redirect_uri"],
    )
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        _log.warning(
            "remote_backup.gdrive.oauth_failed",
            state=state[:8] + "...", error=str(exc)[:200],
        )
        raise PendingSessionError(f"OAuth token exchange failed: {exc}") from exc

    creds = flow.credentials

    # 4. Fetch user_email
    user_email = await gdrive_client.fetch_user_email(creds)

    # 5. Folder resolution : always-create avec suffixe daté si conflit
    folder_id = await _create_drive_folder(
        creds=creds, folder_name=form_data["folder_name"],
    )

    # 6. Génère l'UUID de la connexion (pour le path vault)
    connection_id = uuid4()

    # 7. Push credentials dans Harpocrate
    default_vault = await _require_default_vault_name()
    creds_payload = {
        "client_id": form_data["client_id"],
        "client_secret": row["client_secret"],
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scope": creds.scopes[0] if creds.scopes else "",
        "granted_at": datetime.now(timezone.utc).isoformat(),
    }
    vault_path = f"remote_backups/{connection_id}/oauth"
    await vault_client.create_secret(
        vault_path, json.dumps(creds_payload), vault_name=default_vault,
    )
    credentials_ref = vault_client.build_ref(default_vault, vault_path)

    # 8. INSERT connection
    config = {
        "client_id": form_data["client_id"],
        "redirect_uri": row["redirect_uri"],
        "folder_name": form_data["folder_name"],
        "folder_id": folder_id,
        "user_email": user_email,
        "credentials_ref": credentials_ref,
    }
    await execute(
        """
        INSERT INTO remote_backup_connections
            (id, name, kind, config, created_by_user_id)
        VALUES ($1, $2, 'gdrive', $3::jsonb, $4)
        """,
        connection_id, form_data["name"], json.dumps(config), row["actor_user_id"],
    )

    _log.info(
        "remote_backup.gdrive.oauth_completed",
        connection_id=str(connection_id), user_email=user_email,
        folder_id=folder_id, actor_user_id=str(row["actor_user_id"]),
    )

    return {
        "connection_id": connection_id,
        "user_email": user_email,
        "folder_id": folder_id,
    }


async def _require_default_vault_name() -> str:
    from agflow.services import harpocrate_vaults_service
    default = await harpocrate_vaults_service.get_default()
    if default is None:
        raise PendingSessionError(
            "No default Harpocrate vault configured — see /settings"
        )
    return default.name


async def _create_drive_folder(*, creds, folder_name: str) -> str:
    """Crée toujours un nouveau folder. Si `folder_name` existe déjà → suffixe daté."""
    import asyncio

    def _sync() -> str:
        service = gdrive_client.build_drive_service(creds)
        # Check si nom existe
        existing = service.files().list(
            q=(
                f"name='{folder_name}' "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            ),
            fields="files(id, name)",
            pageSize=1,
        ).execute()
        if existing.get("files"):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            name_to_use = f"{folder_name} ({ts})"
        else:
            name_to_use = folder_name
        created = service.files().create(
            body={
                "name": name_to_use,
                "mimeType": "application/vnd.google-apps.folder",
            },
            fields="id",
        ).execute()
        return str(created["id"])

    return await asyncio.to_thread(_sync)
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_oauth_session.py -v 2>&1 | tail -10
```

Expected : `4 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/gdrive_oauth_session.py backend/tests/services/test_gdrive_oauth_session.py
git commit -m "feat(gdrive-oauth): consume_session — INSERT connection + push vault"
```

---

### Task 12 : get_session + reauthorize

**Files:**
- Modify: `backend/src/agflow/services/gdrive_oauth_session.py`
- Modify: `backend/tests/services/test_gdrive_oauth_session.py`

- [ ] **Step 1 : Ajouter les tests rouges**

```python
@pytest.mark.asyncio
async def test_get_session_returns_pending_status(fresh_db, vault_mock) -> None:
    actor = await _create_admin_user()
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    with patch(
        "agflow.services.gdrive_oauth_session.gdrive_client.build_flow",
        return_value=fake_flow,
    ):
        state, _ = await gdrive_oauth_session.start_session(
            actor_user_id=actor, name="n", folder_name="f",
            client_id="c", client_secret="s", redirect_uri="r",
        )

    info = await gdrive_oauth_session.get_session(state)
    assert info is not None
    assert info["status"] == "pending"
    assert info["connection_id"] is None


@pytest.mark.asyncio
async def test_get_session_returns_none_for_unknown_state(fresh_db) -> None:
    assert await gdrive_oauth_session.get_session("unknown") is None


@pytest.mark.asyncio
async def test_reauthorize_starts_new_pending_for_existing_connection(
    fresh_db, vault_mock,
) -> None:
    actor = await _create_admin_user()
    # Setup : crée une connexion via consume_session
    fake_flow = MagicMock()
    fake_flow.authorization_url.return_value = ("https://x", "x")
    fake_flow.credentials = MagicMock(
        refresh_token="rt", token_uri="https://x", client_id="c", client_secret="s-original",
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    fake_drive = MagicMock()
    fake_drive.files().list().execute.return_value = {"files": []}
    fake_drive.files().create().execute.return_value = {"id": "f"}

    with (
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_flow", return_value=fake_flow),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.build_drive_service", return_value=fake_drive),
        patch("agflow.services.gdrive_oauth_session.gdrive_client.fetch_user_email", return_value="u@x"),
    ):
        state, _ = await gdrive_oauth_session.start_session(
            actor_user_id=actor, name="n", folder_name="f",
            client_id="c", client_secret="s-original", redirect_uri="r",
        )
        result = await gdrive_oauth_session.consume_session(state=state, code="c")
        # Maintenant reauthorize
        new_state, new_url = await gdrive_oauth_session.reauthorize(
            connection_id=result["connection_id"], actor_user_id=actor,
        )

    assert len(new_state) >= 32
    assert "https" in new_url

    pending = await fetch_one(
        "SELECT state, form_data FROM oauth_pending_session WHERE state = $1",
        new_state,
    )
    import json
    fd = pending["form_data"]
    if isinstance(fd, str):
        fd = json.loads(fd)
    assert fd["client_id"] == "c"  # Réutilise le client_id existant
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_gdrive_oauth_session.py::test_get_session_returns_pending_status -v 2>&1 | tail -10
```

- [ ] **Step 3 : Implémenter get_session + reauthorize**

Dans `gdrive_oauth_session.py`, remplacer les 2 `NotImplementedError` :

```python
async def get_session(state: str) -> dict | None:
    """Retourne le status d'un pending session (pour polling frontend)."""
    row = await fetch_one(
        """
        SELECT consumed_at, expires_at, form_data
        FROM oauth_pending_session WHERE state = $1
        """,
        state,
    )
    if row is None:
        return None

    # Si consumed, le frontend doit trouver la connexion résultante
    connection_id = None
    user_email = None
    folder_id = None
    if row["consumed_at"] is not None:
        # Lookup la connexion créée par actor + created_at >= consumed_at
        # Plus simple : lookup par la dernière connexion gdrive du form_data.name
        fd = row["form_data"] if isinstance(row["form_data"], dict) else json.loads(row["form_data"])
        conn = await fetch_one(
            """
            SELECT id, config
            FROM remote_backup_connections
            WHERE kind = 'gdrive' AND name = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            fd.get("name"),
        )
        if conn is not None:
            connection_id = conn["id"]
            cfg = conn["config"] if isinstance(conn["config"], dict) else json.loads(conn["config"])
            user_email = cfg.get("user_email")
            folder_id = cfg.get("folder_id")

    return {
        "status": "completed" if row["consumed_at"] else "pending",
        "connection_id": connection_id,
        "user_email": user_email,
        "folder_id": folder_id,
    }


async def reauthorize(
    *, connection_id: UUID, actor_user_id: UUID,
) -> tuple[str, str]:
    """Re-démarre le flow OAuth pour une connexion gdrive existante.

    Le `client_id` est récupéré depuis `config`, le `client_secret` est
    déchiffré depuis Harpocrate puis ré-encrypté dans la pending row.
    """
    row = await fetch_one(
        "SELECT name, kind, config FROM remote_backup_connections WHERE id = $1",
        connection_id,
    )
    if row is None:
        raise PendingSessionError(f"Connection {connection_id} not found")
    if row["kind"] != "gdrive":
        raise PendingSessionError(
            f"Connection {connection_id} has kind {row['kind']!r}, not gdrive"
        )
    cfg = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"])

    # Lecture du client_secret depuis le coffre Harpocrate
    creds_ref = cfg.get("credentials_ref")
    if not creds_ref:
        raise PendingSessionError(
            f"Connection {connection_id} missing credentials_ref in config"
        )
    creds_raw = await vault_client.resolve_ref(creds_ref)
    creds_data = json.loads(creds_raw)
    client_secret = creds_data["client_secret"]

    return await start_session(
        actor_user_id=actor_user_id,
        name=row["name"],
        folder_name=cfg["folder_name"],
        client_id=cfg["client_id"],
        client_secret=client_secret,
        redirect_uri=cfg["redirect_uri"],
    )
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_gdrive_oauth_session.py -v 2>&1 | tail -10
```

Expected : `7 passed`.

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/gdrive_oauth_session.py backend/tests/services/test_gdrive_oauth_session.py
git commit -m "feat(gdrive-oauth): get_session (polling) + reauthorize"
```

---

## LOT 4 — API endpoints + reaper

### Task 13 : Reaper des pending expirés

**Files:**
- Create: `backend/src/agflow/services/oauth_pending_reaper.py`
- Create: `backend/tests/services/test_oauth_pending_reaper.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1 : Écrire les tests rouges**

`backend/tests/services/test_oauth_pending_reaper.py` :

```python
"""Tests du reaper des oauth_pending_session expirés/consumed."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ["HARPOCRATE_DEK"] = "test-dek-passphrase-very-long-and-stable-2026"

from agflow.db.pool import execute, fetch_one
from agflow.services.oauth_pending_reaper import purge_oauth_pending
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db():
    await reset_schema_and_migrate()
    yield


async def _insert_pending(*, state: str, expires_at: datetime, consumed_at: datetime | None = None) -> None:
    dek = os.environ["HARPOCRATE_DEK"]
    await execute(
        """
        INSERT INTO oauth_pending_session
            (state, kind, redirect_uri, form_data,
             client_secret_encrypted, expires_at, consumed_at)
        VALUES ($1, 'gdrive', 'r', '{}'::jsonb, PGP_SYM_ENCRYPT('s', $4), $2, $3)
        """,
        state, expires_at, consumed_at, dek,
    )


@pytest.mark.asyncio
async def test_purge_removes_expired_rows(fresh_db) -> None:
    now = datetime.now(timezone.utc)
    await _insert_pending(state="expired", expires_at=now - timedelta(hours=2))
    await _insert_pending(state="fresh", expires_at=now + timedelta(minutes=5))

    purged = await purge_oauth_pending()
    assert purged >= 1

    assert await fetch_one("SELECT 1 FROM oauth_pending_session WHERE state = $1", "expired") is None
    assert await fetch_one("SELECT 1 FROM oauth_pending_session WHERE state = $1", "fresh") is not None


@pytest.mark.asyncio
async def test_purge_removes_consumed_rows(fresh_db) -> None:
    now = datetime.now(timezone.utc)
    await _insert_pending(
        state="consumed", expires_at=now + timedelta(minutes=5),
        consumed_at=now,
    )

    purged = await purge_oauth_pending()
    assert purged >= 1
    assert await fetch_one("SELECT 1 FROM oauth_pending_session WHERE state = $1", "consumed") is None
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/services/test_oauth_pending_reaper.py -v 2>&1 | tail -10
```

Expected : `ModuleNotFoundError`.

- [ ] **Step 3 : Implémenter le reaper**

`backend/src/agflow/services/oauth_pending_reaper.py` :

```python
"""Worker startup qui purge les pending OAuth expirés/consumed.

Tick configurable (défaut 5 min). Démarré dans `main.lifespan`.
"""
from __future__ import annotations

import asyncio

import structlog

from agflow.db.pool import execute, fetch_one

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 300  # 5 min


async def purge_oauth_pending() -> int:
    """Supprime les pending rows expirées (> 1h) OR consommées. Retourne le nb supprimé."""
    row = await fetch_one(
        """
        WITH deleted AS (
            DELETE FROM oauth_pending_session
            WHERE expires_at < now() - interval '1 hour'
               OR consumed_at IS NOT NULL
            RETURNING id
        )
        SELECT COUNT(*) AS n FROM deleted
        """,
    )
    n = int(row["n"]) if row else 0
    if n > 0:
        _log.info("oauth_pending.purged", count=n)
    return n


async def run_reaper_loop(interval_s: int = _DEFAULT_INTERVAL_S) -> None:
    """Boucle infinie qui appelle purge à intervalle régulier."""
    _log.info("oauth_pending_reaper.started", interval_s=interval_s)
    while True:
        try:
            await purge_oauth_pending()
        except Exception as exc:  # noqa: BLE001
            _log.warning("oauth_pending_reaper.error", error=str(exc)[:200])
        await asyncio.sleep(interval_s)
```

- [ ] **Step 4 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_oauth_pending_reaper.py -v 2>&1 | tail -5
```

Expected : `2 passed`.

- [ ] **Step 5 : Brancher dans le lifespan**

Dans `backend/src/agflow/main.py`, dans la fonction `lifespan`, après les autres workers (`session_expiry`, `remote_backup_pusher`, `mom_reclaimer`...) :

```python
    # OAuth pending reaper (purge des sessions expirées/consumed)
    from agflow.services.oauth_pending_reaper import run_reaper_loop as _run_oauth_reaper
    oauth_reaper_task = asyncio.create_task(_run_oauth_reaper())
```

Et dans le cleanup (après le `yield`) :

```python
    oauth_reaper_task.cancel()
```

- [ ] **Step 6 : Vérifier que l'app boot toujours**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('OK')" 2>&1 | tail -3
```

Expected : `OK`.

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/oauth_pending_reaper.py backend/tests/services/test_oauth_pending_reaper.py backend/src/agflow/main.py
git commit -m "feat(gdrive-oauth): reaper des pending OAuth + branchement lifespan"
```

---

### Task 14 : 5 endpoints OAuth dans le router

**Files:**
- Modify: `backend/src/agflow/api/admin/remote_backup_connections.py`
- Create: `backend/tests/api/test_admin_backup_remotes_oauth_gdrive.py`

- [ ] **Step 1 : Écrire les tests rouges**

`backend/tests/api/test_admin_backup_remotes_oauth_gdrive.py` :

```python
"""Tests des 5 endpoints OAuth gdrive (mocks du service)."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def _viewer_token() -> str:
    return jwt.encode(
        {"sub": "viewer@example.com", "role": "viewer"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def test_redirect_uri_requires_admin(client: TestClient) -> None:
    r = client.get("/api/admin/backup-remotes/oauth/gdrive/redirect-uri")
    assert r.status_code == 401


def test_redirect_uri_returns_callback_url(client: TestClient) -> None:
    r = client.get(
        "/api/admin/backup-remotes/oauth/gdrive/redirect-uri",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert r.status_code == 200
    assert "/api/admin/backup-remotes/oauth/gdrive/callback" in r.json()["redirect_uri"]


def test_start_returns_state_and_authorize_url(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.start_session",
        AsyncMock(return_value=("abc123def", "https://accounts.google.com/o/oauth2/auth?state=abc")),
    ):
        r = client.post(
            "/api/admin/backup-remotes/oauth/gdrive/start",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "My Backups",
                "folder_name": "agflow-backups",
                "client_id": "x.apps.googleusercontent.com",
                "client_secret": "GOCSPX-x",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "abc123def"
    assert "accounts.google.com" in body["authorize_url"]


def test_start_rejects_viewer(client: TestClient) -> None:
    r = client.post(
        "/api/admin/backup-remotes/oauth/gdrive/start",
        headers={"Authorization": f"Bearer {_viewer_token()}"},
        json={"name": "x", "folder_name": "x", "client_id": "x", "client_secret": "x"},
    )
    assert r.status_code == 403


def test_session_returns_status(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.get_session",
        AsyncMock(return_value={"status": "completed", "connection_id": uuid4(), "user_email": "u@x", "folder_id": "f"}),
    ):
        r = client.get(
            "/api/admin/backup-remotes/oauth/gdrive/session/somestate",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_session_returns_404_when_unknown(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.get_session",
        AsyncMock(return_value=None),
    ):
        r = client.get(
            "/api/admin/backup-remotes/oauth/gdrive/session/unknown",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


def test_callback_redirects_with_postmessage_html(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.consume_session",
        AsyncMock(return_value={"connection_id": uuid4(), "user_email": "u@x", "folder_id": "f"}),
    ):
        r = client.get(
            "/api/admin/backup-remotes/oauth/gdrive/callback?state=abc&code=xyz",
            follow_redirects=False,
        )
    # Public endpoint, retourne HTML (pas de 401)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "window.close" in r.text or "postMessage" in r.text


def test_reauthorize_returns_state_and_url(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.reauthorize",
        AsyncMock(return_value=("newstate", "https://accounts.google.com/o/oauth2/auth?state=newstate")),
    ):
        r = client.post(
            f"/api/admin/backup-remotes/{uuid4()}/reauthorize",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["state"] == "newstate"


def test_create_kind_gdrive_returns_400(client: TestClient) -> None:
    r = client.post(
        "/api/admin/backup-remotes",
        headers={"Authorization": f"Bearer {_admin_token()}"},
        json={"kind": "gdrive", "name": "x", "config": {}, "credentials": {}},
    )
    assert r.status_code == 400
    assert "oauth/gdrive/start" in r.text
```

- [ ] **Step 2 : Run, expect FAIL**

```bash
cd backend && uv run pytest tests/api/test_admin_backup_remotes_oauth_gdrive.py -v 2>&1 | tail -15
```

Expected : 404 sur tous les nouveaux paths (router pas implémenté).

- [ ] **Step 3 : Lire la structure du router existant**

```bash
head -30 backend/src/agflow/api/admin/remote_backup_connections.py
```

Note le préfixe du router (`/api/admin/backup-remotes`) et les imports.

- [ ] **Step 4 : Ajouter les 5 endpoints + l'extension du POST CRUD**

Modifier `backend/src/agflow/api/admin/remote_backup_connections.py`. En haut, ajouter aux imports (les imports `users_service`, `HTTPException`, `Depends`, `require_admin` existent déjà dans le fichier — vérifier et ne pas dupliquer) :

```python
from fastapi import Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agflow.services import gdrive_oauth_session
```

Ajouter les modèles Pydantic après les autres :

```python
class GDriveOAuthStartRequest(BaseModel):
    name: str = Field(min_length=1)
    folder_name: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)


class GDriveOAuthStartResponse(BaseModel):
    state: str
    authorize_url: str


class GDriveOAuthSessionResponse(BaseModel):
    status: str
    connection_id: str | None
    user_email: str | None
    folder_id: str | None
```

Ajouter les 5 endpoints à la fin du fichier (router déjà défini avec préfixe `/api/admin/backup-remotes`). **Pattern de récupération du `user_id`** : `require_admin` retourne l'email (str) ; convertir via `users_service.get_by_email()` pour avoir l'UUID. Cohérent avec le pattern déjà en place dans ce router (ligne ~45).

```python
@router.get("/oauth/gdrive/redirect-uri")
async def gdrive_redirect_uri(request: Request) -> dict:
    """Retourne l'URI de callback à coller dans Google Cloud Console."""
    base = str(request.base_url).rstrip("/")
    return {"redirect_uri": f"{base}/api/admin/backup-remotes/oauth/gdrive/callback"}


@router.post("/oauth/gdrive/start", response_model=GDriveOAuthStartResponse)
async def gdrive_oauth_start(
    payload: GDriveOAuthStartRequest,
    request: Request,
    admin_email: str = Depends(require_admin),
) -> GDriveOAuthStartResponse:
    admin_user = await users_service.get_by_email(admin_email)
    if admin_user is None:
        raise HTTPException(status_code=403, detail="Admin user not found")
    base = str(request.base_url).rstrip("/")
    redirect_uri = f"{base}/api/admin/backup-remotes/oauth/gdrive/callback"
    state, url = await gdrive_oauth_session.start_session(
        actor_user_id=admin_user.id,
        name=payload.name,
        folder_name=payload.folder_name,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        redirect_uri=redirect_uri,
    )
    return GDriveOAuthStartResponse(state=state, authorize_url=url)


@router.get("/oauth/gdrive/callback", response_class=HTMLResponse)
async def gdrive_oauth_callback(state: str, code: str | None = None, error: str | None = None) -> HTMLResponse:
    """Public endpoint — Google nous appelle sans cookie de session.

    Validation par le state token uniquement. Retourne du HTML qui ferme
    le popup et notifie l'opener.
    """
    if error or not code:
        html = f"""<!DOCTYPE html><html><body><script>
            window.opener && window.opener.postMessage({{type: 'gdrive-oauth-failed', error: {error!r}}}, '*');
            window.close();
        </script>Failed: {error or 'no code'}</body></html>"""
        return HTMLResponse(html, status_code=200)
    try:
        await gdrive_oauth_session.consume_session(state=state, code=code)
    except gdrive_oauth_session.PendingSessionError as exc:
        html = f"""<!DOCTYPE html><html><body><script>
            window.opener && window.opener.postMessage({{type: 'gdrive-oauth-failed', error: {str(exc)!r}}}, '*');
            window.close();
        </script>{exc}</body></html>"""
        return HTMLResponse(html, status_code=200)
    html = """<!DOCTYPE html><html><body><script>
        window.opener && window.opener.postMessage({type: 'gdrive-oauth-completed'}, '*');
        window.close();
    </script>OAuth completed. You can close this window.</body></html>"""
    return HTMLResponse(html, status_code=200)


@router.get("/oauth/gdrive/session/{state}", response_model=GDriveOAuthSessionResponse)
async def gdrive_oauth_session_status(
    state: str,
    admin_email: str = Depends(require_admin),
) -> GDriveOAuthSessionResponse:
    info = await gdrive_oauth_session.get_session(state)
    if info is None:
        raise HTTPException(status_code=404, detail="OAuth state not found")
    return GDriveOAuthSessionResponse(
        status=info["status"],
        connection_id=str(info["connection_id"]) if info.get("connection_id") else None,
        user_email=info.get("user_email"),
        folder_id=info.get("folder_id"),
    )


@router.post("/{connection_id}/reauthorize", response_model=GDriveOAuthStartResponse)
async def gdrive_reauthorize(
    connection_id: UUID,
    admin_email: str = Depends(require_admin),
) -> GDriveOAuthStartResponse:
    admin_user = await users_service.get_by_email(admin_email)
    if admin_user is None:
        raise HTTPException(status_code=403, detail="Admin user not found")
    try:
        state, url = await gdrive_oauth_session.reauthorize(
            connection_id=connection_id,
            actor_user_id=admin_user.id,
        )
    except gdrive_oauth_session.PendingSessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GDriveOAuthStartResponse(state=state, authorize_url=url)
```

Dans la fonction `create_remote_backup_connection` existante (POST CRUD générique), au début, ajouter :

```python
    if payload.kind == "gdrive":
        raise HTTPException(
            status_code=400,
            detail="kind='gdrive' must be created via /api/admin/backup-remotes/oauth/gdrive/start",
        )
```

- [ ] **Step 5 : Run, expect PASS**

```bash
cd backend && uv run pytest tests/api/test_admin_backup_remotes_oauth_gdrive.py -v 2>&1 | tail -15
```

Expected : `9 passed`.

- [ ] **Step 6 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/remote_backup_connections.py tests/api/test_admin_backup_remotes_oauth_gdrive.py 2>&1 | tail -3
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/api/admin/remote_backup_connections.py backend/tests/api/test_admin_backup_remotes_oauth_gdrive.py
git commit -m "feat(gdrive-oauth): 5 endpoints OAuth + reauthorize + refus POST kind=gdrive"
```

---

## LOT 5 — Frontend

### Task 15 : adminBackupRemotesApi.ts + gdriveOAuth.ts helper

**Files:**
- Create: `frontend/src/lib/adminBackupRemotesApi.ts`
- Create: `frontend/src/lib/gdriveOAuth.ts`

- [ ] **Step 1 : Créer `adminBackupRemotesApi.ts`**

`frontend/src/lib/adminBackupRemotesApi.ts` :

```typescript
import { api } from "./api";

export interface GDriveOAuthStartPayload {
  name: string;
  folder_name: string;
  client_id: string;
  client_secret: string;
}

export interface GDriveOAuthStartResponse {
  state: string;
  authorize_url: string;
}

export interface GDriveOAuthSessionInfo {
  status: "pending" | "completed" | "failed";
  connection_id: string | null;
  user_email: string | null;
  folder_id: string | null;
}

export const adminBackupRemotesApi = {
  async fetchGDriveRedirectUri(): Promise<{ redirect_uri: string }> {
    const r = await api.get<{ redirect_uri: string }>(
      "/admin/backup-remotes/oauth/gdrive/redirect-uri",
    );
    return r.data;
  },

  async startGDriveOAuth(payload: GDriveOAuthStartPayload): Promise<GDriveOAuthStartResponse> {
    const r = await api.post<GDriveOAuthStartResponse>(
      "/admin/backup-remotes/oauth/gdrive/start",
      payload,
    );
    return r.data;
  },

  async fetchGDriveOAuthSession(state: string): Promise<GDriveOAuthSessionInfo> {
    const r = await api.get<GDriveOAuthSessionInfo>(
      `/admin/backup-remotes/oauth/gdrive/session/${state}`,
    );
    return r.data;
  },

  async reauthorizeConnection(id: string): Promise<GDriveOAuthStartResponse> {
    const r = await api.post<GDriveOAuthStartResponse>(
      `/admin/backup-remotes/${id}/reauthorize`,
    );
    return r.data;
  },
};
```

- [ ] **Step 2 : Créer `gdriveOAuth.ts`**

`frontend/src/lib/gdriveOAuth.ts` :

```typescript
import { adminBackupRemotesApi, type GDriveOAuthSessionInfo } from "./adminBackupRemotesApi";

export class PopupBlockedError extends Error {
  constructor() {
    super("Popup blocked by browser");
  }
}

export class OAuthAbortedError extends Error {
  constructor() {
    super("OAuth flow aborted by user");
  }
}

export class OAuthError extends Error {}

const POLL_INTERVAL_MS = 1500;
const TIMEOUT_MS = 5 * 60 * 1000;

export async function runGDriveOAuthFlow(params: {
  authorizeUrl: string;
  state: string;
}): Promise<GDriveOAuthSessionInfo> {
  const popup = window.open(params.authorizeUrl, "gdrive-oauth", "width=520,height=720");
  if (!popup) {
    throw new PopupBlockedError();
  }

  const start = Date.now();
  while (true) {
    if (Date.now() - start > TIMEOUT_MS) {
      try { popup.close(); } catch { /* ignore */ }
      throw new OAuthError("OAuth flow timed out");
    }
    if (popup.closed) {
      // Check une dernière fois si la session a été complétée juste avant la fermeture
      const info = await adminBackupRemotesApi.fetchGDriveOAuthSession(params.state);
      if (info.status === "completed") return info;
      throw new OAuthAbortedError();
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
    try {
      const info = await adminBackupRemotesApi.fetchGDriveOAuthSession(params.state);
      if (info.status === "completed") {
        try { popup.close(); } catch { /* ignore */ }
        return info;
      }
      if (info.status === "failed") {
        try { popup.close(); } catch { /* ignore */ }
        throw new OAuthError("OAuth flow failed");
      }
    } catch (err) {
      // 404 sur la session = elle a expiré ou été purgée
      if ((err as { response?: { status?: number } }).response?.status === 404) {
        try { popup.close(); } catch { /* ignore */ }
        throw new OAuthError("OAuth session expired");
      }
      throw err;
    }
  }
}

export async function runGDriveReauthorize(connectionId: string): Promise<GDriveOAuthSessionInfo> {
  const { state, authorize_url } = await adminBackupRemotesApi.reauthorizeConnection(connectionId);
  return runGDriveOAuthFlow({ authorizeUrl: authorize_url, state });
}
```

- [ ] **Step 3 : Vérifier que TypeScript compile**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected : aucune erreur sur les 2 nouveaux fichiers.

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/lib/adminBackupRemotesApi.ts frontend/src/lib/gdriveOAuth.ts
git commit -m "feat(gdrive-ui): adminBackupRemotesApi + gdriveOAuth helper"
```

---

### Task 16 : GDriveFields.tsx wizard

**Files:**
- Create: `frontend/src/components/backup-remotes/GDriveFields.tsx`

- [ ] **Step 1 : Créer le composant**

`frontend/src/components/backup-remotes/GDriveFields.tsx` :

```typescript
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { adminBackupRemotesApi } from "@/lib/adminBackupRemotesApi";
import {
  OAuthAbortedError,
  OAuthError,
  PopupBlockedError,
  runGDriveOAuthFlow,
} from "@/lib/gdriveOAuth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Phase = "setup" | "auth" | "confirmed";

interface Props {
  onCompleted: (info: { connectionId: string; userEmail: string; folderId: string }) => void;
  onCancel: () => void;
}

export function GDriveFields({ onCompleted, onCancel }: Props) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("setup");
  const [name, setName] = useState("");
  const [folderName, setFolderName] = useState("agflow-backups");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [redirectUri, setRedirectUri] = useState("");
  const [confirmation, setConfirmation] = useState<{ userEmail: string; folderId: string } | null>(null);

  useEffect(() => {
    adminBackupRemotesApi.fetchGDriveRedirectUri()
      .then((r) => setRedirectUri(r.redirect_uri))
      .catch(() => { /* affichage retardé, non bloquant */ });
  }, []);

  const handleAuthorize = async () => {
    if (!name || !folderName || !clientId || !clientSecret) {
      toast.error(t("backups.gdrive.errorRequired"));
      return;
    }
    setPhase("auth");
    try {
      const { state, authorize_url } = await adminBackupRemotesApi.startGDriveOAuth({
        name, folder_name: folderName, client_id: clientId, client_secret: clientSecret,
      });
      const info = await runGDriveOAuthFlow({ authorizeUrl: authorize_url, state });
      if (info.connection_id && info.user_email && info.folder_id) {
        setConfirmation({ userEmail: info.user_email, folderId: info.folder_id });
        setPhase("confirmed");
        onCompleted({
          connectionId: info.connection_id,
          userEmail: info.user_email,
          folderId: info.folder_id,
        });
      } else {
        toast.error(t("backups.gdrive.errorGeneric"));
        setPhase("setup");
      }
    } catch (err) {
      if (err instanceof PopupBlockedError) toast.error(t("backups.gdrive.errorPopupBlocked"));
      else if (err instanceof OAuthAbortedError) toast.error(t("backups.gdrive.errorAborted"));
      else if (err instanceof OAuthError) toast.error(t("backups.gdrive.errorOauth", { msg: err.message }));
      else toast.error(t("backups.gdrive.errorGeneric"));
      setPhase("setup");
    }
  };

  if (phase === "auth") {
    return (
      <div className="space-y-3">
        <p className="text-sm">{t("backups.gdrive.phaseAuthInProgress")}</p>
        <Button variant="ghost" onClick={onCancel}>{t("common.cancel")}</Button>
      </div>
    );
  }

  if (phase === "confirmed" && confirmation) {
    return (
      <div className="space-y-3">
        <p className="font-medium">{t("backups.gdrive.phaseConfirmedTitle")}</p>
        <div className="text-sm text-muted-foreground">
          <div>{t("backups.gdrive.confirmedUserEmail")}: <strong>{confirmation.userEmail}</strong></div>
          <div>{t("backups.gdrive.confirmedFolderId")}: <code>{confirmation.folderId}</code></div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("backups.gdrive.phaseSetupTitle")}</p>

      <div>
        <Label htmlFor="gdrive-name">{t("backups.gdrive.fieldName")}</Label>
        <Input id="gdrive-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Drive backups" />
      </div>

      <div>
        <Label htmlFor="gdrive-redirect-uri">{t("backups.gdrive.fieldRedirectUri")}</Label>
        <Input id="gdrive-redirect-uri" value={redirectUri} readOnly className="font-mono text-xs" />
        <p className="text-xs text-muted-foreground mt-1">{t("backups.gdrive.fieldRedirectUriHint")}</p>
      </div>

      <div>
        <Label htmlFor="gdrive-client-id">{t("backups.gdrive.fieldClientId")}</Label>
        <Input id="gdrive-client-id" value={clientId} onChange={(e) => setClientId(e.target.value)}
          placeholder="123456789-abc.apps.googleusercontent.com" />
        <p className="text-xs text-muted-foreground mt-1">{t("backups.gdrive.fieldClientIdHint")}</p>
      </div>

      <div>
        <Label htmlFor="gdrive-client-secret">{t("backups.gdrive.fieldClientSecret")}</Label>
        <Input id="gdrive-client-secret" type="password" value={clientSecret}
          onChange={(e) => setClientSecret(e.target.value)} placeholder="GOCSPX-..." autoComplete="new-password" />
      </div>

      <div>
        <Label htmlFor="gdrive-folder-name">{t("backups.gdrive.fieldFolderName")}</Label>
        <Input id="gdrive-folder-name" value={folderName} onChange={(e) => setFolderName(e.target.value)} />
        <p className="text-xs text-muted-foreground mt-1">{t("backups.gdrive.fieldFolderNameHint")}</p>
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>{t("common.cancel")}</Button>
        <Button onClick={handleAuthorize}>{t("backups.gdrive.btnAuthorize")}</Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2 : Vérifier que TypeScript compile**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/components/backup-remotes/GDriveFields.tsx
git commit -m "feat(gdrive-ui): GDriveFields wizard 3 phases"
```

---

### Task 17 : Intégration ConnectionModal + page + i18n

**Files:**
- Modify: `frontend/src/components/backup-remotes/ConnectionModal.tsx`
- Modify: `frontend/src/pages/RemoteBackupConnectionsPage.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés i18n FR**

Dans `frontend/src/i18n/fr.json`, dans la section `backups` (chercher avec `grep -n "\"backups\":"`), ajouter une sous-clé `gdrive` :

```json
    "gdrive": {
      "kindLabel": "Google Drive",
      "phaseSetupTitle": "Configure ton projet Google Cloud (Client ID/Secret) puis autorise l'accès à Drive.",
      "phaseAuthInProgress": "Autorisation en cours dans la fenêtre Google… attends la confirmation puis cette fenêtre se mettra à jour automatiquement.",
      "phaseConfirmedTitle": "Connexion autorisée",
      "fieldName": "Nom logique",
      "fieldClientId": "Client ID",
      "fieldClientIdHint": "Format <id>.apps.googleusercontent.com",
      "fieldClientSecret": "Client Secret",
      "fieldFolderName": "Nom du dossier Drive",
      "fieldFolderNameHint": "Sera créé dans le Drive personnel. Si un dossier de ce nom existe déjà, un suffixe daté est ajouté.",
      "fieldRedirectUri": "Redirect URI (à coller dans Google Cloud Console)",
      "fieldRedirectUriHint": "Copie cette URL dans la section « Autorized redirect URIs » de ton OAuth client.",
      "btnAuthorize": "Autoriser dans Google Drive",
      "btnReauthorize": "Re-autoriser",
      "errorPopupBlocked": "Popup bloquée. Autorise les popups pour ce site et réessaie.",
      "errorAborted": "Tu as fermé la fenêtre Google avant la fin du processus.",
      "errorOauth": "Échec OAuth : {{msg}}",
      "errorGeneric": "Une erreur est survenue lors du flow OAuth.",
      "errorRequired": "Tous les champs sont obligatoires.",
      "confirmedUserEmail": "Compte Google",
      "confirmedFolderId": "Folder ID",
      "tableTargetEmail": "Compte",
      "tableTargetFolder": "Dossier"
    },
```

- [ ] **Step 2 : Ajouter les mêmes clés en EN**

Dans `frontend/src/i18n/en.json`, miroir de FR :

```json
    "gdrive": {
      "kindLabel": "Google Drive",
      "phaseSetupTitle": "Configure your Google Cloud project (Client ID/Secret) then authorize Drive access.",
      "phaseAuthInProgress": "Authorization in progress in the Google window… wait for the confirmation, this window will update automatically.",
      "phaseConfirmedTitle": "Connection authorized",
      "fieldName": "Logical name",
      "fieldClientId": "Client ID",
      "fieldClientIdHint": "Format <id>.apps.googleusercontent.com",
      "fieldClientSecret": "Client Secret",
      "fieldFolderName": "Drive folder name",
      "fieldFolderNameHint": "Will be created in the personal Drive. If a folder with this name exists, a dated suffix is appended.",
      "fieldRedirectUri": "Redirect URI (paste in Google Cloud Console)",
      "fieldRedirectUriHint": "Copy this URL into the \"Authorized redirect URIs\" section of your OAuth client.",
      "btnAuthorize": "Authorize with Google Drive",
      "btnReauthorize": "Reauthorize",
      "errorPopupBlocked": "Popup blocked. Allow popups for this site and try again.",
      "errorAborted": "You closed the Google window before completing the process.",
      "errorOauth": "OAuth failure: {{msg}}",
      "errorGeneric": "An error occurred during the OAuth flow.",
      "errorRequired": "All fields are required.",
      "confirmedUserEmail": "Google account",
      "confirmedFolderId": "Folder ID",
      "tableTargetEmail": "Account",
      "tableTargetFolder": "Folder"
    },
```

- [ ] **Step 3 : Vérifier que JSON valide**

```bash
cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json')); JSON.parse(require('fs').readFileSync('src/i18n/en.json')); console.log('json OK')"
```

Expected : `json OK`.

- [ ] **Step 4 : Inspecter ConnectionModal pour comprendre sa structure**

```bash
grep -nE "kind|interface Connection|sftp|s3|ftps" frontend/src/components/backup-remotes/ConnectionModal.tsx 2>&1 | head -20
```

Note les sections où le `kind` est utilisé (sélecteur + branchement des champs).

- [ ] **Step 5 : Modifier ConnectionModal — ajouter option gdrive + branchement**

Dans `ConnectionModal.tsx` :

1. Ajouter dans le type `Connection` ou l'interface : `kind: 'sftp' | 's3' | 'ftps' | 'gdrive'`.
2. Importer le wizard : `import { GDriveFields } from "./GDriveFields";`.
3. Dans le sélecteur kind du form, ajouter `<option value="gdrive">Google Drive</option>`.
4. Avant le rendu des champs sftp/s3/ftps, ajouter :

```typescript
if (form.kind === "gdrive" && !connection) {
  return (
    <GDriveFields
      onCompleted={(info) => {
        toast.success(t("backups.gdrive.phaseConfirmedTitle"));
        onSaved?.({ id: info.connectionId } as Connection);
        onClose();
      }}
      onCancel={onClose}
    />
  );
}
```

(Au cas où on édite une connexion existante `kind=gdrive`, afficher juste un message « pour modifier les credentials, utilise le bouton Re-autoriser » + le bouton.)

- [ ] **Step 6 : Modifier RemoteBackupConnectionsPage — colonne cible adaptée + bouton reauth**

Dans `RemoteBackupConnectionsPage.tsx`, dans la cellule « cible » (`host:port` actuellement) :

```typescript
{c.kind === "gdrive" ? (
  <span className="text-xs">
    {(c.config as { user_email?: string; folder_name?: string }).user_email}
    {" · "}
    {(c.config as { folder_name?: string }).folder_name}
  </span>
) : (
  <span>{c.config.host}:{c.config.port}</span>
)}
```

Dans la cellule actions, ajouter pour gdrive :

```typescript
{c.kind === "gdrive" && (
  <Button size="sm" variant="ghost" onClick={async () => {
    try {
      await runGDriveReauthorize(c.id);
      toast.success(t("backups.gdrive.phaseConfirmedTitle"));
    } catch (err) {
      toast.error(String(err));
    }
  }}>{t("backups.gdrive.btnReauthorize")}</Button>
)}
```

Import nécessaire : `import { runGDriveReauthorize } from "@/lib/gdriveOAuth";`.

- [ ] **Step 7 : Vérifier TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

Expected : aucune erreur.

- [ ] **Step 8 : Commit**

```bash
git add frontend/src/components/backup-remotes/ConnectionModal.tsx frontend/src/pages/RemoteBackupConnectionsPage.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(gdrive-ui): intégration ConnectionModal + page admin + i18n FR/EN"
```

---

## LOT 6 — Doc + validation E2E

### Task 18 : Guide admin Google Cloud Console

**Files:**
- Create: `docs/admin/gdrive-setup.md`

- [ ] **Step 1 : Créer le guide**

`docs/admin/gdrive-setup.md` :

```markdown
# Connexion Google Drive — guide admin

Cette procédure prépare un projet Google Cloud pour permettre à agflow d'écrire des backups dans le Drive d'un compte Google.

## Pré-requis

- Compte Google avec accès à <https://console.cloud.google.com>
- Quota Drive disponible (15 GB gratuits, +/- 5 TB sur Google Workspace)

## Étapes

### 1. Créer un projet Google Cloud

1. <https://console.cloud.google.com/projectcreate>
2. Nom : `agflow-backups` (ou autre)
3. Créer

### 2. Activer l'API Google Drive

1. Menu burger → **APIs & Services** → **Library**
2. Chercher « Google Drive API » → **Enable**

### 3. Configurer l'OAuth consent screen

1. **APIs & Services** → **OAuth consent screen**
2. User type : **External** (sauf si Workspace Internal)
3. App name : `agflow`
4. User support email : ton email
5. **Save and continue**
6. Scopes → **Add or remove scopes** → cocher `.../auth/drive.file`
7. **Save and continue**
8. Test users : ajoute ton compte Google qui hébergera les backups
9. **Save**

### 4. Créer l'identifiant OAuth Web Client

1. **APIs & Services** → **Credentials** → **+ Create Credentials** → **OAuth client ID**
2. Application type : **Web application**
3. Name : `agflow-web`
4. **Authorized redirect URIs** : récupère l'URL exacte depuis le wizard agflow (champ « Redirect URI »). Format :
   ```
   https://<your-agflow-host>/api/admin/backup-remotes/oauth/gdrive/callback
   ```
5. **Create**
6. **Copie** le `Client ID` et le `Client secret`

### 5. Coller les credentials dans agflow

1. Dans agflow → **Backups** → **Connexions distantes** → **+ Nouvelle**
2. Kind : **Google Drive**
3. Nom logique : `Mon backup quotidien` (ou autre)
4. Client ID + Client Secret : ceux récupérés à l'étape 4
5. Nom du dossier Drive : `agflow-backups` (sera créé dans le Drive du compte autorisé)
6. Bouton **Autoriser dans Google Drive** → popup Google → connecte-toi → accorde l'accès
7. La popup se ferme automatiquement, la connexion apparaît dans le tableau

## Limitations connues

- **Pas de pagination de `list_remote`** au-delà de 1000 fichiers. Suffisant pour des backups quotidiens sur plusieurs mois ; si tu dépasses, change la politique de rétention.
- **Pas de sub-folders** dans le dossier cible. Tous les backups vivent à la racine du dossier.
- **Quota Drive** : 15 GB par compte Google gratuit. Si plein, l'upload plante avec une erreur claire.
- **Refresh token révoqué** : si l'utilisateur révoque l'accès depuis <https://myaccount.google.com/permissions>, la connexion ne fonctionne plus. Utilise le bouton **Re-autoriser** dans le tableau.

## Vérification

Dans le tableau des connexions, clique **Tester** sur la connexion gdrive. Si la réponse est verte, l'OAuth fonctionne et le dossier est accessible.
```

- [ ] **Step 2 : Commit**

```bash
git add docs/admin/gdrive-setup.md
git commit -m "docs(gdrive): guide admin Google Cloud Console"
```

---

### Task 19 : Validation finale via `run-test.sh`

**Files:** aucun changement code — validation E2E.

- [ ] **Step 1 : Push toute la branche**

```bash
git push origin dev 2>&1 | tail -2
```

Expected : `<old>..<new>  dev -> dev`.

- [ ] **Step 2 : Lancer le run-test en CLEANUP=1 (LXC fresh + auto-purge)**

```bash
CLEANUP=1 ./scripts/run-test.sh
```

Expected report final :
```
RÉSULTAT DES TESTS
Tests OK     : 8/8
Tests FAIL   : 0/8
Statut       : OK SUCCES
```

- [ ] **Step 3 : Si le run-test échoue, garder le LXC pour inspection**

```bash
./scripts/run-test.sh    # sans CLEANUP, garde le LXC
# ssh pve "pct exec <CTID> -- bash -c 'cd /opt/agflow.docker && docker compose -f docker-compose.dev.yml logs --no-color --tail 200 backend'"
# Diagnostic + fix + commit + re-run
# Puis ./scripts/destroy-test.sh <CTID> à la fin
```

- [ ] **Step 4 : Smoke métier (optionnel — bloqué par bug SDK Harpocrate path-style)**

Une fois le SDK Harpocrate patché (read des secrets path-style fonctionne), faire :

```bash
# Sur le LXC live, après dev-deploy
# 1. Créer un coffre Harpocrate par défaut via /settings UI (avec un vrai HARPOCRATE_KEY)
# 2. Aller dans Backups → Connexions distantes → + Nouvelle → kind=Google Drive
# 3. Suivre le wizard OAuth avec un vrai projet Google Cloud
# 4. Vérifier que la connexion apparaît dans le tableau
# 5. Tester un backup réel : déclencher un push remote → vérifier que le fichier apparaît dans le Drive
```

Cette validation finale est documentée dans la spec section « Validation E2E ». Elle peut être faite plus tard, mais le LOT 6 commit-only valide que le code charge et que les ~30 tests pytest passent dans le LXC fresh.

- [ ] **Step 5 : Mettre à jour la mémoire**

```bash
# Optionnel : noter le statut dans MEMORY.md si pertinent
```

---

## Récap des commits

| # | Lot | Commit |
|---|---|---|
| 1 | 1 | `feat(gdrive-db): migration 107 — ajoute 'gdrive' au CHECK kind` |
| 2 | 1 | `feat(gdrive-db): migration 108 — table oauth_pending_session` |
| 3 | 1 | `chore(gdrive): + google-auth + google-auth-oauthlib + google-api-python-client` |
| 4 | 2 | `feat(gdrive-provider): gdrive_client.py — helpers SDK Google` |
| 5 | 2 | `feat(gdrive-provider): gdrive_provider.test_connection` |
| 6 | 2 | `feat(gdrive-provider): upload_stream resumable via tmpfile` |
| 7 | 2 | `feat(gdrive-provider): list_remote — RemoteFile mapping` |
| 8 | 2 | `feat(gdrive-provider): download_stream — chunked yield` |
| 9 | 2 | `feat(gdrive-provider): factory — case gdrive` |
| 10 | 3 | `feat(gdrive-oauth): start_session — pending row + url Google` |
| 11 | 3 | `feat(gdrive-oauth): consume_session — INSERT connection + push vault` |
| 12 | 3 | `feat(gdrive-oauth): get_session (polling) + reauthorize` |
| 13 | 4 | `feat(gdrive-oauth): reaper des pending OAuth + branchement lifespan` |
| 14 | 4 | `feat(gdrive-oauth): 5 endpoints OAuth + reauthorize + refus POST kind=gdrive` |
| 15 | 5 | `feat(gdrive-ui): adminBackupRemotesApi + gdriveOAuth helper` |
| 16 | 5 | `feat(gdrive-ui): GDriveFields wizard 3 phases` |
| 17 | 5 | `feat(gdrive-ui): intégration ConnectionModal + page admin + i18n FR/EN` |
| 18 | 6 | `docs(gdrive): guide admin Google Cloud Console` |

**19 commits** au total. Validation E2E (Task 19) ne fait pas commit en soi (déjà tout pushé).

## Notes finales

- À chaque étape de **commit**, le push vers `origin/dev` peut attendre la fin du LOT (préserve un historique propre) ou être fait après chaque commit (sécurise contre la perte). À toi de voir selon ta préférence.
- La règle CLAUDE.md interdit explicitement les feature branches : tout va sur `dev`. Pas de `git checkout -b feat/gdrive-...`.
- Pour la validation finale (Task 19), suivre strictement la règle « valider via `./scripts/run-test.sh` » (LXC fresh + auto-cleanup). Jamais valider sur un LXC partagé.
- Si un test fail au LOT 2-4 (backend), inspecter la sortie pytest verbose : `docker compose exec -T backend pytest <path> -vv` sur le LXC tenu sans CLEANUP.
- Si le composant `GDriveFields.tsx` dépasse 300 lignes à la Task 16, extraire les phases en sous-composants `GDrivePhaseSetup.tsx`, `GDrivePhaseAuth.tsx`, `GDrivePhaseConfirmed.tsx`.
- Les dépendances Python Google sont parmi les plus larges du Python écosystème (~30 MB). Le rebuild Docker à la Task 3 prendra plus de temps que d'habitude (~3-5 min de plus). C'est normal.
