from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sdk.git_sync.export_service import ExportService
from sdk.git_sync.models import AuthMode, GitConfig, TableRef


def _make_config(**overrides) -> GitConfig:
    base = dict(
        repo_url="file:///tmp/fake.git",
        auth_mode=AuthMode.SSH_KEY,
        auth_secret_ref="dummy",
        module_name="docker",
        commit_author_name="bot",
        commit_author_email="bot@example.org",
    )
    base.update(overrides)
    return GitConfig(**base)


def _t(name: str) -> TableRef:
    return TableRef(schema="public", table=name)


def _build_git_service_mock(tmp_path: Path, config: GitConfig) -> MagicMock:
    """Fake GitService : clone retourne tmp_path et expose un module_path concret."""
    git = MagicMock()
    git.config = config
    git.clone = AsyncMock(return_value=tmp_path)
    module_path = tmp_path / config.module_name / "datas"
    module_path.mkdir(parents=True, exist_ok=True)
    git.get_module_path = MagicMock(return_value=module_path)
    git.commit_and_push = AsyncMock(return_value="abc123def456")
    git.cleanup = MagicMock()
    return git


_EXISTS_TABLE_RE = re.compile(r'FROM "([^"]+)"\."([^"]+)"')


def _build_db_conn_mock(
    *,
    columns_per_table: dict[str, list[dict]] | None = None,
    fk_rows: list[dict] | None = None,
    has_rows_per_table: dict[str, bool] | None = None,
) -> AsyncMock:
    """Mock asyncpg connection : retourne colonnes + FK + EXISTS selon la query.

    `has_rows_per_table` mappe `schema.table` → bool pour stub `_has_any_row`.
    Default : True (tables peuplées).
    """
    columns_per_table = columns_per_table or {}
    fk_rows = fk_rows or []
    has_rows_per_table = has_rows_per_table or {}

    async def _fetch(query: str, *args):
        if "information_schema.columns" in query:
            schema, table = args
            return columns_per_table.get(f"{schema}.{table}", [])
        if "information_schema.table_constraints" in query:
            return fk_rows
        return []

    async def _fetchval(query: str, *args):
        # ExportService._has_any_row : `SELECT EXISTS (SELECT 1 FROM "s"."t" LIMIT 1)`
        match = _EXISTS_TABLE_RE.search(query)
        if match:
            full = f"{match.group(1)}.{match.group(2)}"
            return has_rows_per_table.get(full, True)
        return None

    async def _copy(query: str, *, output, **kwargs):
        # Écrit un CSV minimaliste à partir du SELECT — c'est ce que ferait
        # PostgreSQL côté production. Le contenu importe peu, ce qu'on teste
        # c'est que le fichier est créé et non vide.
        payload = b"col\nrow1\nrow2\n"
        if hasattr(output, "write"):
            output.write(payload)
        else:
            Path(output).write_bytes(payload)

    conn = AsyncMock()
    conn.fetch = _fetch
    conn.fetchval = _fetchval
    conn.copy_from_query = _copy
    return conn


# ─── export() flow complet ───────────────────────────────────────────────────


async def test_export_writes_dependencies_json_and_csv_per_table(tmp_path):
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)
    conn = _build_db_conn_mock(
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
                {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
            ],
            "public.services": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
                {"column_name": "stack_id", "is_generated": "NEVER", "identity_generation": None},
            ],
        },
        fk_rows=[
            {"dependent_table": "public.services", "depends_on": "public.stacks"},
        ],
    )

    result = await ExportService(conn, git).export([_t("stacks"), _t("services")])

    module_path = tmp_path / "docker" / "datas"
    assert (module_path / "dependencies.json").exists()
    assert (module_path / "public.stacks.csv").exists()
    assert (module_path / "public.services.csv").exists()

    deps = json.loads((module_path / "dependencies.json").read_text())
    assert deps["version"] == "1.0"
    assert {"schema": "public", "table": "stacks"} in deps["tables"]
    assert {"from": "public.services", "to": "public.stacks"} in deps["edges"]

    git.clone.assert_awaited_once()
    git.commit_and_push.assert_awaited_once()
    git.cleanup.assert_called_once_with(tmp_path)

    assert result.success is True
    assert result.commit_sha == "abc123def456"
    assert set(result.tables_exported) == {_t("stacks"), _t("services")}


async def test_export_excludes_generated_always_and_identity_always(tmp_path):
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)

    captured_queries: list[str] = []

    async def _capturing_copy(query, *, output, **kwargs):
        captured_queries.append(query)
        Path(output.name if hasattr(output, "name") else output).write_bytes(b"x\n")

    columns = [
        {"column_name": "id", "is_generated": "NEVER", "identity_generation": "ALWAYS"},
        {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
        {"column_name": "computed", "is_generated": "ALWAYS", "identity_generation": None},
    ]
    conn = _build_db_conn_mock(columns_per_table={"public.t": columns})
    conn.copy_from_query = _capturing_copy

    await ExportService(conn, git).export([_t("t")])

    assert len(captured_queries) == 1
    query = captured_queries[0]
    assert '"name"' in query
    # id (identity ALWAYS) et computed (generated ALWAYS) exclus du SELECT
    assert '"id"' not in query
    assert '"computed"' not in query


async def test_export_respects_excluded_columns_config(tmp_path):
    config = _make_config(
        excluded_columns={"public.stacks": ["created_at", "updated_at"]}
    )
    git = _build_git_service_mock(tmp_path, config)

    captured_queries: list[str] = []

    async def _capturing_copy(query, *, output, **kwargs):
        captured_queries.append(query)
        Path(output.name if hasattr(output, "name") else output).write_bytes(b"x\n")

    columns = [
        {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
        {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
        {"column_name": "created_at", "is_generated": "NEVER", "identity_generation": None},
        {"column_name": "updated_at", "is_generated": "NEVER", "identity_generation": None},
    ]
    conn = _build_db_conn_mock(columns_per_table={"public.stacks": columns})
    conn.copy_from_query = _capturing_copy

    await ExportService(conn, git).export([_t("stacks")])

    query = captured_queries[0]
    assert '"id"' in query
    assert '"name"' in query
    assert '"created_at"' not in query
    assert '"updated_at"' not in query


async def test_export_calls_cleanup_even_on_failure(tmp_path):
    """Si commit_and_push lève, cleanup doit quand même être appelé."""
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)
    git.commit_and_push = AsyncMock(side_effect=RuntimeError("network down"))
    conn = _build_db_conn_mock(
        columns_per_table={
            "public.t": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ]
        }
    )

    with pytest.raises(RuntimeError, match="network down"):
        await ExportService(conn, git).export([_t("t")])

    git.cleanup.assert_called_once()


async def test_export_sets_commit_sha_none_when_no_changes(tmp_path):
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)
    git.commit_and_push = AsyncMock(return_value=None)  # rien à committer
    conn = _build_db_conn_mock(
        columns_per_table={
            "public.t": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ]
        }
    )

    result = await ExportService(conn, git).export([_t("t")])

    assert result.success is True
    assert result.commit_sha is None


async def test_export_empty_tables_list_short_circuits(tmp_path):
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)
    conn = _build_db_conn_mock()

    result = await ExportService(conn, git).export([])

    # On clone et on commit quand même (potentiellement pour produire un
    # commit vide avec juste un dependencies.json à jour), mais aucun CSV
    # n'est écrit. Le SyncResult.tables_exported reste vide.
    assert result.tables_exported == []
    module_path = tmp_path / "docker" / "datas"
    csvs = list(module_path.glob("*.csv")) if module_path.exists() else []
    assert csvs == []


# ─── Règle « table vide → pas de fichier » ───────────────────────────────────


async def test_export_skips_csv_when_table_is_empty(tmp_path):
    """Table sans aucune ligne → aucun fichier CSV créé."""
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)
    conn = _build_db_conn_mock(
        columns_per_table={
            "public.empty_t": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ]
        },
        has_rows_per_table={"public.empty_t": False},
    )

    await ExportService(conn, git).export([_t("empty_t")])

    module_path = tmp_path / "docker" / "datas"
    assert not (module_path / "public.empty_t.csv").exists()


async def test_export_deletes_stale_csv_when_table_becomes_empty(tmp_path):
    """Une exécution précédente avait laissé un CSV, la table est désormais vide
    → le CSV obsolète est supprimé pour que la suppression soit propagée par Git.
    """
    config = _make_config()
    git = _build_git_service_mock(tmp_path, config)

    module_path = tmp_path / "docker" / "datas"
    stale_csv = module_path / "public.now_empty.csv"
    stale_csv.write_bytes(b"id\n1\n")

    conn = _build_db_conn_mock(
        columns_per_table={
            "public.now_empty": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ]
        },
        has_rows_per_table={"public.now_empty": False},
    )

    await ExportService(conn, git).export([_t("now_empty")])

    assert not stale_csv.exists()


async def test_export_deletes_stale_csv_when_no_exportable_columns(tmp_path):
    """Toutes les colonnes sont exclues → pas d'export ET on nettoie un CSV précédent."""
    config = _make_config(excluded_columns={"public.only_excluded": ["x"]})
    git = _build_git_service_mock(tmp_path, config)

    module_path = tmp_path / "docker" / "datas"
    stale_csv = module_path / "public.only_excluded.csv"
    stale_csv.write_bytes(b"x\nval\n")

    conn = _build_db_conn_mock(
        columns_per_table={
            "public.only_excluded": [
                {"column_name": "x", "is_generated": "NEVER", "identity_generation": None}
            ]
        },
    )

    await ExportService(conn, git).export([_t("only_excluded")])

    assert not stale_csv.exists()
