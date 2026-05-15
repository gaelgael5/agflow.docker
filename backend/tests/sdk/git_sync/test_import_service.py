from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sdk.git_sync.exceptions import TableNotFoundError
from sdk.git_sync.import_service import ImportService
from sdk.git_sync.models import AuthMode, GitConfig, TableRef

# ─── Helpers de fixture ──────────────────────────────────────────────────────


def _make_config(**overrides) -> GitConfig:
    base = dict(
        repo_url="file:///fake.git",
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


def _populate_module_dir(
    tmp_path: Path,
    *,
    module_name: str = "docker",
    csv_tables: list[str],
    edges: list[tuple[str, str]] | None = None,
) -> Path:
    """Crée le module_path avec dependencies.json + CSVs vides.

    Retourne le module_path. Les CSVs sont écrits avec un en-tête fictif.
    """
    edges = edges or []
    module_path = tmp_path / module_name / "datas"
    module_path.mkdir(parents=True, exist_ok=True)

    table_refs = [_t(name) for name in csv_tables]
    for ref in table_refs:
        (module_path / ref.csv_name).write_bytes(b"col\nrow1\n")

    deps_data = {
        "version": "1.0",
        "tables": [{"schema": "public", "table": name} for name in csv_tables],
        "edges": [
            {"from": f"public.{dep}", "to": f"public.{ref}"} for dep, ref in edges
        ],
        "ordered": [f"public.{name}" for name in csv_tables],
    }
    (module_path / "dependencies.json").write_text(json.dumps(deps_data))
    return module_path


def _build_git_service(tmp_path: Path, config: GitConfig) -> MagicMock:
    git = MagicMock()
    git.config = config
    git.clone = AsyncMock(return_value=tmp_path)
    module_path = tmp_path / config.module_name / "datas"
    git.get_module_path = MagicMock(return_value=module_path)
    git.cleanup = MagicMock()
    return git


def _build_conn(
    *,
    pk_per_table: dict[str, list[str]] | None = None,
    columns_per_table: dict[str, list[dict]] | None = None,
    execute_returns: dict[str, str] | None = None,
    fetchval_returns: dict[str, int] | None = None,
) -> AsyncMock:
    """Mock asyncpg.Connection capable de :
    - fetch information_schema.{table_constraints, columns}
    - execute → retourne le command tag (INSERT 0 N, UPDATE N, DELETE N)
    - copy_to_table → no-op
    - transaction() comme async context manager
    - fetchval → counts pour preview
    """
    pk_per_table = pk_per_table or {}
    columns_per_table = columns_per_table or {}
    execute_returns = execute_returns or {}
    fetchval_returns = fetchval_returns or {}

    executed: list[str] = []
    conn = AsyncMock()

    async def _fetch(query: str, *args):
        if "constraint_type = 'PRIMARY KEY'" in query:
            schema, table = args
            cols = pk_per_table.get(f"{schema}.{table}", [])
            return [{"column_name": c} for c in cols]
        if "information_schema.columns" in query:
            schema, table = args
            return columns_per_table.get(f"{schema}.{table}", [])
        return []

    async def _execute(query: str, *args):
        executed.append(query)
        for key, ret in execute_returns.items():
            if key in query:
                return ret
        # Defaults raisonnables pour les opérations DML
        if query.lstrip().upper().startswith("CREATE TABLE"):
            return "CREATE TABLE"
        if query.lstrip().upper().startswith("ALTER TABLE"):
            return "ALTER TABLE"
        if query.lstrip().upper().startswith("DROP TABLE"):
            return "DROP TABLE"
        if query.lstrip().upper().startswith("INSERT"):
            return "INSERT 0 0"
        if query.lstrip().upper().startswith("UPDATE"):
            return "UPDATE 0"
        if query.lstrip().upper().startswith("DELETE"):
            return "DELETE 0"
        return ""

    async def _fetchval(query: str, *args):
        for key, ret in fetchval_returns.items():
            if key in query:
                return ret
        return 0

    async def _copy_to_table(table, *, source, **kwargs):
        pass

    @asynccontextmanager
    async def _transaction():
        yield

    conn.fetch = _fetch
    conn.execute = _execute
    conn.fetchval = _fetchval
    conn.copy_to_table = _copy_to_table
    conn.transaction = MagicMock(side_effect=_transaction)
    conn._executed = executed  # type: ignore[attr-defined]
    return conn


# ─── discover_tables / load_dependencies ────────────────────────────────────


async def test_import_raises_table_not_found_when_csv_missing(tmp_path):
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["stacks"])
    git = _build_git_service(tmp_path, config)
    conn = _build_conn(
        pk_per_table={"public.stacks": ["id"]},
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ]
        },
    )

    # On demande explicitement une table dont le CSV n'existe pas
    with pytest.raises(TableNotFoundError, match="missing"):
        await ImportService(conn, git).import_([_t("stacks"), _t("missing")])


async def test_import_discovers_all_csvs_when_selected_tables_is_none(tmp_path):
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["a", "b"])
    git = _build_git_service(tmp_path, config)
    conn = _build_conn(
        pk_per_table={"public.a": ["id"], "public.b": ["id"]},
        columns_per_table={
            "public.a": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ],
            "public.b": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ],
        },
    )

    result = await ImportService(conn, git).import_(selected_tables=None)

    assert {t.table for t in result.tables_processed} == {"a", "b"}


# ─── import_ : flow et nettoyage ─────────────────────────────────────────────


async def test_import_creates_and_drops_tmp_tables(tmp_path):
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["stacks"])
    git = _build_git_service(tmp_path, config)
    conn = _build_conn(
        pk_per_table={"public.stacks": ["id"]},
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
                {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
            ]
        },
    )

    await ImportService(conn, git).import_()

    creates = [q for q in conn._executed if "CREATE TABLE" in q]
    drops = [q for q in conn._executed if "DROP TABLE" in q]
    assert any("tmp_public_stacks" in q for q in creates)
    assert any("tmp_public_stacks" in q for q in drops)


async def test_import_drops_tmp_tables_even_when_merge_phase_fails(tmp_path):
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["stacks"])
    git = _build_git_service(tmp_path, config)
    # Au moins une colonne non-PK pour que l'UPDATE soit construit et exécuté.
    conn = _build_conn(
        pk_per_table={"public.stacks": ["id"]},
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
                {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
            ]
        },
    )

    # Fait planter UPDATE pour simuler un échec dans la transaction
    original_execute = conn.execute

    async def _failing_execute(query, *args):
        if query.lstrip().upper().startswith("UPDATE"):
            raise RuntimeError("simulated merge failure")
        return await original_execute(query, *args)

    conn.execute = _failing_execute

    with pytest.raises(Exception, match=r"simulated|merge"):
        await ImportService(conn, git).import_()

    # DROP doit avoir été exécuté quand même via le finally
    drop_executed = any("DROP TABLE" in q for q in conn._executed)
    assert drop_executed, "DROP TABLE doit être appelé dans le finally"


async def test_import_calls_git_cleanup_in_finally(tmp_path):
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["stacks"])
    git = _build_git_service(tmp_path, config)
    conn = _build_conn(
        pk_per_table={"public.stacks": ["id"]},
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None}
            ]
        },
    )

    await ImportService(conn, git).import_()

    git.cleanup.assert_called_once()


async def test_import_counts_inserts_updates_deletes(tmp_path):
    """Le rowcount des commands DML doit être agrégé dans ImportResult."""
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["stacks"])
    git = _build_git_service(tmp_path, config)
    conn = _build_conn(
        pk_per_table={"public.stacks": ["id"]},
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
                {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
            ]
        },
        execute_returns={
            'INSERT INTO "public"."stacks"': "INSERT 0 7",
            'UPDATE "public"."stacks"': "UPDATE 3",
            'DELETE FROM "public"."stacks"': "DELETE 2",
        },
    )

    result = await ImportService(conn, git).import_()

    assert result.rows_inserted["public.stacks"] == 7
    assert result.rows_updated["public.stacks"] == 3
    assert result.rows_deleted["public.stacks"] == 2
    assert result.success is True


# ─── preview ────────────────────────────────────────────────────────────────


async def test_preview_returns_counts_per_table(tmp_path):
    config = _make_config()
    _populate_module_dir(tmp_path, csv_tables=["stacks"])
    git = _build_git_service(tmp_path, config)
    conn = _build_conn(
        pk_per_table={"public.stacks": ["id"]},
        columns_per_table={
            "public.stacks": [
                {"column_name": "id", "is_generated": "NEVER", "identity_generation": None},
                {"column_name": "name", "is_generated": "NEVER", "identity_generation": None},
            ]
        },
        fetchval_returns={
            "count_to_insert": 5,
            "count_to_update": 2,
            "count_to_delete": 1,
        },
    )

    preview = await ImportService(conn, git).preview()

    assert len(preview.tables) == 1
    stacks_preview = preview.tables[0]
    assert stacks_preview.table == _t("stacks")
    assert stacks_preview.to_insert == 5
    assert stacks_preview.to_update == 2
    assert stacks_preview.to_delete == 1
