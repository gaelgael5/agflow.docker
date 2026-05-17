"""Tests du runner : wrappers SDK ExportService / ImportService."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services import git_sync_runner

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_config():
    from agflow.schemas.git_sync import GitSyncConfigDTO

    return GitSyncConfigDTO(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https",
        auth_secret_ref="${vault://default:git/pat}",
        branch="main",
        commit_author_name="bot",
        commit_author_email="bot@local",
        excluded_columns={"users": ["password_hash"]},
        selected_tables=["infra_categories", "infra_named_types"],
        cron_expr=None,
        cron_enabled=False,
        last_export_at=None, last_export_status=None, last_export_sha=None,
        last_export_error=None, last_export_tables_count=None,
        last_import_at=None, last_import_status=None, last_import_error=None,
        last_import_rows_inserted=None, last_import_rows_updated=None,
        last_import_rows_deleted=None,
        created_at=datetime(2026, 5, 17), updated_at=datetime(2026, 5, 17),
    )


async def test_run_export_happy_path(fake_config):
    from sdk.git_sync import SyncResult, TableRef

    sync_result = SyncResult(
        success=True,
        commit_sha="abc1234",
        tables_exported=[
            TableRef(schema="public", table="infra_categories"),
            TableRef(schema="public", table="infra_named_types"),
        ],
    )

    fake_conn = MagicMock()
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "get_pool", AsyncMock(return_value=fake_pool)), \
         patch.object(git_sync_runner, "_build_export_service", return_value=MagicMock(
            export=AsyncMock(return_value=sync_result))), \
         patch.object(git_sync_runner.svc, "record_export_run", AsyncMock()) as rec:
        result = await git_sync_runner.run_export()

    assert result.sha == "abc1234"
    assert result.tables_count == 2
    rec.assert_called_once_with(
        status="ok", sha="abc1234", error=None, tables_count=2,
    )


async def test_run_export_failed_records_failure(fake_config):
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)),
        patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")),
        patch.object(git_sync_runner, "get_pool", AsyncMock(return_value=fake_pool)),
        patch.object(git_sync_runner, "_build_export_service", side_effect=RuntimeError("boom")),
        patch.object(git_sync_runner.svc, "record_export_run", AsyncMock()) as rec,
        pytest.raises(RuntimeError, match="boom"),
    ):
        await git_sync_runner.run_export()

    rec.assert_called_once()
    kwargs = rec.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert "boom" in kwargs["error"]


async def test_run_export_no_config_raises():
    with (
        patch.object(git_sync_runner, "get_config", AsyncMock(return_value=None)),
        pytest.raises(git_sync_runner.GitSyncNotConfiguredError),
    ):
        await git_sync_runner.run_export()


async def test_run_preview_happy_path(fake_config):
    from sdk.git_sync import ImportPreview, TablePreview, TableRef

    preview = ImportPreview(tables=[
        TablePreview(
            table=TableRef(schema="public", table="infra_categories"),
            to_insert=3, to_update=1, to_delete=0,
        ),
    ])

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "get_pool", AsyncMock(return_value=fake_pool)), \
         patch.object(git_sync_runner, "_build_import_service", return_value=MagicMock(
            preview=AsyncMock(return_value=preview))):
        result = await git_sync_runner.run_preview()

    assert len(result.tables) == 1
    assert result.tables[0].table == "public.infra_categories"
    assert result.tables[0].to_insert == 3


async def test_run_import_happy_path(fake_config):
    from sdk.git_sync import ImportResult, TableRef

    sdk_result = ImportResult(
        success=True,
        tables_processed=[TableRef(schema="public", table="infra_categories")],
        rows_inserted={"public.infra_categories": 3},
        rows_updated={"public.infra_categories": 1},
        rows_deleted={"public.infra_categories": 0},
    )

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "get_pool", AsyncMock(return_value=fake_pool)), \
         patch.object(git_sync_runner, "_build_import_service", return_value=MagicMock(
            import_=AsyncMock(return_value=sdk_result))), \
         patch.object(git_sync_runner.svc, "record_import_run", AsyncMock()) as rec:
        result = await git_sync_runner.run_import()

    assert result.rows_inserted == 3
    assert result.rows_updated == 1
    assert result.rows_deleted == 0
    rec.assert_called_once_with(
        status="ok", error=None,
        rows_inserted=3, rows_updated=1, rows_deleted=0,
    )


async def test_test_secret_ref_ok():
    with patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="resolved")):
        result = await git_sync_runner.test_secret_ref("${vault://default:git/pat}")
    assert result.ok is True
    assert result.error is None


async def test_test_secret_ref_ko():
    with patch.object(git_sync_runner.vault_client, "resolve_ref",
                       AsyncMock(side_effect=Exception("secret not found"))):
        result = await git_sync_runner.test_secret_ref("${vault://default:git/missing}")
    assert result.ok is False
    assert "secret not found" in result.error
