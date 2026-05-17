"""Tests HTTP des 9 endpoints /api/admin/git-sync (mocks services)."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_admin_token()}"}


@pytest.fixture
def _config_dto():
    from agflow.schemas.git_sync import GitSyncConfigDTO
    return GitSyncConfigDTO(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https", auth_secret_ref="${vault://default:git/pat}",
        branch="main", commit_author_name="bot", commit_author_email="bot@local",
        excluded_columns={}, selected_tables=["users"],
        cron_expr=None, cron_enabled=False,
        last_export_at=None, last_export_status=None, last_export_sha=None,
        last_export_error=None, last_export_tables_count=None,
        last_import_at=None, last_import_status=None, last_import_error=None,
        last_import_rows_inserted=None, last_import_rows_updated=None,
        last_import_rows_deleted=None,
        created_at=datetime(2026, 5, 17, tzinfo=UTC),
        updated_at=datetime(2026, 5, 17, tzinfo=UTC),
    )


# ── /config GET / PUT / DELETE ─────────────────────────────────────────


def test_get_config_returns_404_when_empty(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.git_sync.svc.get_config",
        AsyncMock(return_value=None),
    ):
        resp = client.get("/api/admin/git-sync/config", headers=_admin_headers())
    assert resp.status_code == 404


def test_get_config_returns_200_when_set(client: TestClient, _config_dto) -> None:
    with patch(
        "agflow.api.admin.git_sync.svc.get_config",
        AsyncMock(return_value=_config_dto),
    ):
        resp = client.get("/api/admin/git-sync/config", headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["repo_url"] == "https://github.com/owner/repo"


def test_put_config_upserts_and_reloads_scheduler(
    client: TestClient, _config_dto
) -> None:
    with (
        patch(
            "agflow.api.admin.git_sync.svc.upsert_config",
            AsyncMock(return_value=_config_dto),
        ) as up,
        patch(
            "agflow.api.admin.git_sync.git_sync_scheduler.reload_schedule",
            AsyncMock(),
        ) as rel,
    ):
        resp = client.put(
            "/api/admin/git-sync/config",
            headers=_admin_headers(),
            json={
                "repo_url": "https://github.com/owner/repo",
                "auth_mode": "pat_https",
                "auth_secret_ref": "${vault://default:git/pat}",
                "branch": "main",
                "commit_author_name": "bot",
                "commit_author_email": "bot@local",
                "excluded_columns": {},
                "selected_tables": ["users"],
                "cron_expr": None,
                "cron_enabled": False,
            },
        )
    assert resp.status_code == 200
    up.assert_called_once()
    rel.assert_called_once()


def test_put_config_rejects_invalid_cron(client: TestClient) -> None:
    resp = client.put(
        "/api/admin/git-sync/config",
        headers=_admin_headers(),
        json={
            "repo_url": "https://github.com/owner/repo",
            "auth_mode": "pat_https",
            "auth_secret_ref": "ref",
            "branch": "main",
            "commit_author_name": "bot",
            "commit_author_email": "bot@local",
            "excluded_columns": {},
            "selected_tables": ["users"],
            "cron_expr": "not-a-cron",
            "cron_enabled": True,
        },
    )
    assert resp.status_code == 422


def test_delete_config_returns_204(client: TestClient) -> None:
    with (
        patch(
            "agflow.api.admin.git_sync.svc.delete_config", AsyncMock()
        ) as del_,
        patch(
            "agflow.api.admin.git_sync.git_sync_scheduler.reload_schedule",
            AsyncMock(),
        ),
    ):
        resp = client.delete(
            "/api/admin/git-sync/config", headers=_admin_headers()
        )
    assert resp.status_code == 204
    del_.assert_called_once()


# ── /available-tables ──────────────────────────────────────────────────


def test_get_available_tables(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.git_sync.svc.list_available_tables",
        AsyncMock(return_value=["users", "git_sync_config"]),
    ):
        resp = client.get(
            "/api/admin/git-sync/available-tables", headers=_admin_headers()
        )
    assert resp.status_code == 200
    assert resp.json() == ["users", "git_sync_config"]


# ── /test-secret-ref ───────────────────────────────────────────────────


def test_post_test_secret_ref_ok(client: TestClient) -> None:
    from agflow.schemas.git_sync import GitSyncTestSecretRefResult
    with patch(
        "agflow.api.admin.git_sync.git_sync_runner.test_secret_ref",
        AsyncMock(return_value=GitSyncTestSecretRefResult(ok=True)),
    ):
        resp = client.post(
            "/api/admin/git-sync/test-secret-ref",
            headers=_admin_headers(),
            json={"auth_secret_ref": "${vault://default:git/pat}"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "error": None}


# ── /export ────────────────────────────────────────────────────────────


def test_post_export(client: TestClient) -> None:
    from agflow.schemas.git_sync import GitSyncExportResult
    with patch(
        "agflow.api.admin.git_sync.git_sync_runner.run_export",
        AsyncMock(return_value=GitSyncExportResult(sha="abc1234", tables_count=2)),
    ):
        resp = client.post(
            "/api/admin/git-sync/export", headers=_admin_headers()
        )
    assert resp.status_code == 200
    assert resp.json() == {"sha": "abc1234", "tables_count": 2}


# ── /preview-import ────────────────────────────────────────────────────


def test_post_preview_import(client: TestClient) -> None:
    from agflow.schemas.git_sync import (
        GitSyncImportPreviewResult,
        GitSyncTablePreview,
    )
    payload = GitSyncImportPreviewResult(
        tables=[
            GitSyncTablePreview(
                table="public.users", to_insert=3, to_update=1, to_delete=0,
            ),
        ],
    )
    with patch(
        "agflow.api.admin.git_sync.git_sync_runner.run_preview",
        AsyncMock(return_value=payload),
    ):
        resp = client.post(
            "/api/admin/git-sync/preview-import", headers=_admin_headers()
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tables"][0]["table"] == "public.users"


# ── /import ────────────────────────────────────────────────────────────


def test_post_import(client: TestClient) -> None:
    from agflow.schemas.git_sync import GitSyncImportResult
    with patch(
        "agflow.api.admin.git_sync.git_sync_runner.run_import",
        AsyncMock(return_value=GitSyncImportResult(
            rows_inserted=10, rows_updated=5, rows_deleted=2,
        )),
    ):
        resp = client.post(
            "/api/admin/git-sync/import", headers=_admin_headers()
        )
    assert resp.status_code == 200
    assert resp.json() == {
        "rows_inserted": 10, "rows_updated": 5, "rows_deleted": 2,
    }


# ── /commits ───────────────────────────────────────────────────────────


def test_get_commits_returns_list(client: TestClient, _config_dto) -> None:
    from agflow.services.git_sync_github_client import GitCommit
    commits = [
        GitCommit(
            sha="abc1234567890", short_sha="abc1234",
            message="feat: x", author_name="Alice", author_email="a@x.com",
            authored_at=datetime(2026, 5, 17, tzinfo=UTC),
            html_url="https://github.com/o/r/commit/abc1234",
        ),
    ]
    with (
        patch(
            "agflow.api.admin.git_sync.svc.get_config",
            AsyncMock(return_value=_config_dto),
        ),
        patch(
            "agflow.api.admin.git_sync.gh.list_commits",
            AsyncMock(return_value=commits),
        ),
    ):
        resp = client.get(
            "/api/admin/git-sync/commits?limit=5", headers=_admin_headers()
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["short_sha"] == "abc1234"


def test_get_commits_unsupported_host(client: TestClient, _config_dto) -> None:
    from agflow.services.git_sync_github_client import UnsupportedHostError
    with (
        patch(
            "agflow.api.admin.git_sync.svc.get_config",
            AsyncMock(return_value=_config_dto),
        ),
        patch(
            "agflow.api.admin.git_sync.gh.list_commits",
            AsyncMock(side_effect=UnsupportedHostError("gitlab.com")),
        ),
    ):
        resp = client.get(
            "/api/admin/git-sync/commits", headers=_admin_headers()
        )
    assert resp.status_code == 422
