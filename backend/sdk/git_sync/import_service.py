"""Import d'un snapshot Git vers PostgreSQL en six phases.

Hors-transaction (Phases 1-3) :
  1. CREATE TABLE tmp_<schema>_<table> (LIKE source ...)
  2. COPY tmp_... FROM STDIN (depuis CSV)
  3. ALTER tmp_... ADD PRIMARY KEY (récupère les PK depuis information_schema)

Transaction unique (Phases 4-5) :
  4. INSERT INTO target SELECT ... FROM tmp WHERE NOT EXISTS (...)   ← insertions
     UPDATE target SET ... FROM tmp WHERE pk_match AND any_col_distinct ← updates
  5. DELETE FROM target WHERE NOT EXISTS (... FROM tmp ...)            ← suppressions

Finally hors-transaction (Phase 6) :
  6. DROP TABLE tmp_*

Sur PG 15+, on utilise INSERT/UPDATE séparés plutôt que MERGE pour
obtenir des rowcounts précis (le MERGE de PG 15/16 ne distingue pas
INSERT vs UPDATE dans son rowcount global). C'est sémantiquement
équivalent dans une transaction unique.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sdk.git_sync.dependency_resolver import DependencyResolver
from sdk.git_sync.exceptions import TableNotFoundError
from sdk.git_sync.git_service import GitService
from sdk.git_sync.models import (
    DependencyGraph,
    ImportPreview,
    ImportResult,
    TablePreview,
    TableRef,
)

_COLUMNS_QUERY = """
SELECT column_name, is_generated, identity_generation
FROM information_schema.columns
WHERE table_schema = $1 AND table_name = $2
ORDER BY ordinal_position
"""

_PK_QUERY = """
SELECT kcu.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
    AND tc.constraint_schema = kcu.constraint_schema
WHERE tc.constraint_type = 'PRIMARY KEY'
    AND tc.table_schema = $1
    AND tc.table_name = $2
ORDER BY kcu.ordinal_position
"""


def _parse_affected_rows(command_tag: str) -> int:
    """Extrait le rowcount d'un command tag asyncpg (« INSERT 0 5 », « UPDATE 3 »)."""
    if not command_tag:
        return 0
    parts = command_tag.split()
    # INSERT donne « INSERT <oid> <count> », UPDATE/DELETE « <verb> <count> »
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


class ImportService:
    def __init__(self, db_conn: Any, git_service: GitService) -> None:
        self._conn = db_conn
        self._git = git_service

    # ─── API publique ────────────────────────────────────────────────────

    async def import_(
        self, selected_tables: list[TableRef] | None = None
    ) -> ImportResult:
        repo_root: Path | None = None
        tmp_to_drop: list[TableRef] = []
        try:
            repo_root = await self._git.clone()
            module_path = self._git.get_module_path(repo_root)
            tables = self._discover_tables(module_path, selected_tables)
            graph = self._load_dependencies(module_path)
            ordered = self._order_tables(graph, tables)

            # Phases 1-3 hors transaction
            for table in ordered:
                await self._create_tmp_table(table)
                tmp_to_drop.append(table)
                await self._load_csv_into_tmp(table, module_path)
                await self._add_pk_to_tmp(table)

            # Phases 4-5 dans une transaction unique
            rows_inserted: dict[str, int] = {}
            rows_updated: dict[str, int] = {}
            rows_deleted: dict[str, int] = {}
            async with self._conn.transaction():
                for table in ordered:
                    ins, upd = await self._merge_inserts_then_updates(table)
                    rows_inserted[table.full_name] = ins
                    rows_updated[table.full_name] = upd
                for table in reversed(ordered):
                    rows_deleted[table.full_name] = await self._delete_orphans(table)

            return ImportResult(
                success=True,
                tables_processed=list(ordered),
                rows_inserted=rows_inserted,
                rows_updated=rows_updated,
                rows_deleted=rows_deleted,
            )
        finally:
            # Phase 6 : DROP tmp même en cas d'échec dans la transaction.
            # Hors transaction donc les drops persistent.
            for table in reversed(tmp_to_drop):
                await self._drop_tmp_table(table)
            if repo_root is not None:
                self._git.cleanup(repo_root)

    async def preview(
        self, selected_tables: list[TableRef] | None = None
    ) -> ImportPreview:
        repo_root: Path | None = None
        tmp_to_drop: list[TableRef] = []
        try:
            repo_root = await self._git.clone()
            module_path = self._git.get_module_path(repo_root)
            tables = self._discover_tables(module_path, selected_tables)
            graph = self._load_dependencies(module_path)
            ordered = self._order_tables(graph, tables)

            for table in ordered:
                await self._create_tmp_table(table)
                tmp_to_drop.append(table)
                await self._load_csv_into_tmp(table, module_path)
                await self._add_pk_to_tmp(table)

            previews: list[TablePreview] = []
            async with self._conn.transaction():
                for table in ordered:
                    ins = await self._count_to_insert(table)
                    upd = await self._count_to_update(table)
                    dels = await self._count_to_delete(table)
                    previews.append(
                        TablePreview(
                            table=table,
                            to_insert=ins,
                            to_update=upd,
                            to_delete=dels,
                        )
                    )
                # Rollback en sortant du context (pas de COMMIT) : la
                # transaction n'a fait que des SELECT donc rien à annuler,
                # mais on garde la sémantique « preview est read-only ».
                raise _PreviewRollback(previews)
        except _PreviewRollback as marker:
            return ImportPreview(tables=marker.previews)
        finally:
            for table in reversed(tmp_to_drop):
                await self._drop_tmp_table(table)
            if repo_root is not None:
                self._git.cleanup(repo_root)

    # ─── Découverte fichiers + ordre ─────────────────────────────────────

    def _discover_tables(
        self, module_path: Path, selected: list[TableRef] | None
    ) -> list[TableRef]:
        available = [
            TableRef(schema=p.stem.split(".", 1)[0], table=p.stem.split(".", 1)[1])
            for p in sorted(module_path.glob("*.csv"))
            if "." in p.stem
        ]

        if selected is None:
            return available

        available_set = set(available)
        for s in selected:
            if s not in available_set:
                raise TableNotFoundError(
                    f"CSV missing for {s.full_name} in {module_path}"
                )
        return list(selected)

    def _load_dependencies(self, module_path: Path) -> DependencyGraph:
        deps_path = module_path / "dependencies.json"
        data = json.loads(deps_path.read_text(encoding="utf-8"))
        return DependencyResolver.deserialize(data)

    def _order_tables(
        self, graph: DependencyGraph, tables: list[TableRef]
    ) -> list[TableRef]:
        """Garde uniquement les tables demandées, dans l'ordre topo du graphe."""
        tables_set = set(tables)
        full = graph.ordered
        ordered = [t for t in full if t in tables_set]
        # Tables découvertes via CSV mais absentes du graphe → ajoutées en
        # fin (pas de dépendance déclarée pour elles).
        for t in tables:
            if t not in ordered:
                ordered.append(t)
        return ordered

    # ─── Phases 1-3 : préparation tmp tables ─────────────────────────────

    async def _create_tmp_table(self, table: TableRef) -> None:
        sql = (
            f'CREATE TABLE "{table.tmp_name}" '
            f'(LIKE "{table.schema}"."{table.table}" '
            f"INCLUDING DEFAULTS INCLUDING GENERATED "
            f"EXCLUDING CONSTRAINTS EXCLUDING INDEXES)"
        )
        await self._conn.execute(sql)

    async def _load_csv_into_tmp(self, table: TableRef, module_path: Path) -> None:
        csv_path = module_path / table.csv_name
        with csv_path.open("rb") as f:
            await self._conn.copy_to_table(
                table.tmp_name,
                source=f,
                format="csv",
                header=True,
            )

    async def _add_pk_to_tmp(self, table: TableRef) -> None:
        pk_columns = await self._pk_columns(table)
        if not pk_columns:
            # Pas de PK → on ne peut pas MERGE/DELETE proprement. Cela
            # signale typiquement une table de log sans clé. On laisse
            # passer mais l'UPDATE/DELETE seront no-op faute de match.
            return
        cols_sql = ", ".join(f'"{c}"' for c in pk_columns)
        await self._conn.execute(
            f'ALTER TABLE "{table.tmp_name}" ADD PRIMARY KEY ({cols_sql})'
        )

    # ─── Phase 4 : INSERT puis UPDATE ────────────────────────────────────

    async def _merge_inserts_then_updates(self, table: TableRef) -> tuple[int, int]:
        all_cols = await self._all_columns(table)
        pk_cols = await self._pk_columns(table)
        non_pk_cols = [c for c in all_cols if c not in pk_cols]

        if not all_cols:
            return (0, 0)

        target = f'"{table.schema}"."{table.table}"'
        tmp = f'"{table.tmp_name}"'

        cols_list = ", ".join(f'"{c}"' for c in all_cols)
        select_list = ", ".join(f's."{c}"' for c in all_cols)
        pk_join = (
            " AND ".join(f't."{c}" = s."{c}"' for c in pk_cols)
            if pk_cols
            else "FALSE"
        )

        # INSERT : lignes du tmp qui n'existent pas dans target
        insert_sql = (
            f"INSERT INTO {target} ({cols_list}) "
            f"SELECT {select_list} FROM {tmp} AS s "
            f"WHERE NOT EXISTS (SELECT 1 FROM {target} AS t WHERE {pk_join})"
        )
        ins_tag = await self._conn.execute(insert_sql)
        inserted = _parse_affected_rows(ins_tag)

        # UPDATE : lignes du tmp qui existent ET diffèrent
        if non_pk_cols and pk_cols:
            set_clause = ", ".join(f'"{c}" = s."{c}"' for c in non_pk_cols)
            distinct_clause = " OR ".join(
                f't."{c}" IS DISTINCT FROM s."{c}"' for c in non_pk_cols
            )
            update_sql = (
                f"UPDATE {target} AS t SET {set_clause} "
                f"FROM {tmp} AS s "
                f"WHERE {pk_join} AND ({distinct_clause})"
            )
            upd_tag = await self._conn.execute(update_sql)
            updated = _parse_affected_rows(upd_tag)
        else:
            updated = 0

        return (inserted, updated)

    # ─── Phase 5 : DELETE orphans ────────────────────────────────────────

    async def _delete_orphans(self, table: TableRef) -> int:
        pk_cols = await self._pk_columns(table)
        if not pk_cols:
            return 0

        target = f'"{table.schema}"."{table.table}"'
        tmp = f'"{table.tmp_name}"'
        pk_join = " AND ".join(f't."{c}" = s."{c}"' for c in pk_cols)
        delete_sql = (
            f"DELETE FROM {target} AS t "
            f"WHERE NOT EXISTS (SELECT 1 FROM {tmp} AS s WHERE {pk_join})"
        )
        tag = await self._conn.execute(delete_sql)
        return _parse_affected_rows(tag)

    # ─── Phase 6 : DROP tmp ──────────────────────────────────────────────

    async def _drop_tmp_table(self, table: TableRef) -> None:
        await self._conn.execute(f'DROP TABLE IF EXISTS "{table.tmp_name}"')

    # ─── Preview : counts (read-only) ────────────────────────────────────

    async def _count_to_insert(self, table: TableRef) -> int:
        pk_cols = await self._pk_columns(table)
        if not pk_cols:
            return 0
        target = f'"{table.schema}"."{table.table}"'
        tmp = f'"{table.tmp_name}"'
        pk_join = " AND ".join(f't."{c}" = s."{c}"' for c in pk_cols)
        query = (
            f"SELECT COUNT(*) /*count_to_insert*/ FROM {tmp} AS s "
            f"WHERE NOT EXISTS (SELECT 1 FROM {target} AS t WHERE {pk_join})"
        )
        return int(await self._conn.fetchval(query) or 0)

    async def _count_to_update(self, table: TableRef) -> int:
        all_cols = await self._all_columns(table)
        pk_cols = await self._pk_columns(table)
        non_pk_cols = [c for c in all_cols if c not in pk_cols]
        if not pk_cols or not non_pk_cols:
            return 0
        target = f'"{table.schema}"."{table.table}"'
        tmp = f'"{table.tmp_name}"'
        pk_join = " AND ".join(f't."{c}" = s."{c}"' for c in pk_cols)
        distinct_clause = " OR ".join(
            f't."{c}" IS DISTINCT FROM s."{c}"' for c in non_pk_cols
        )
        query = (
            f"SELECT COUNT(*) /*count_to_update*/ FROM {target} AS t "
            f"JOIN {tmp} AS s ON ({pk_join}) "
            f"WHERE ({distinct_clause})"
        )
        return int(await self._conn.fetchval(query) or 0)

    async def _count_to_delete(self, table: TableRef) -> int:
        pk_cols = await self._pk_columns(table)
        if not pk_cols:
            return 0
        target = f'"{table.schema}"."{table.table}"'
        tmp = f'"{table.tmp_name}"'
        pk_join = " AND ".join(f't."{c}" = s."{c}"' for c in pk_cols)
        query = (
            f"SELECT COUNT(*) /*count_to_delete*/ FROM {target} AS t "
            f"WHERE NOT EXISTS (SELECT 1 FROM {tmp} AS s WHERE {pk_join})"
        )
        return int(await self._conn.fetchval(query) or 0)

    # ─── Helpers SQL information_schema ─────────────────────────────────

    async def _all_columns(self, table: TableRef) -> list[str]:
        rows = await self._conn.fetch(_COLUMNS_QUERY, table.schema, table.table)
        excluded = set(
            self._git.config.excluded_columns.get(table.full_name, [])
        )
        result: list[str] = []
        for row in rows:
            name = row["column_name"]
            if name in excluded:
                continue
            if row["is_generated"] == "ALWAYS":
                continue
            if row["identity_generation"] == "ALWAYS":
                continue
            result.append(name)
        return result

    async def _pk_columns(self, table: TableRef) -> list[str]:
        rows = await self._conn.fetch(_PK_QUERY, table.schema, table.table)
        return [r["column_name"] for r in rows]


class _PreviewRollback(Exception):
    """Sentinel pour quitter la transaction de preview sans COMMIT.

    Pas un vrai ImportConflictError : c'est un mécanisme interne propre
    au flux preview qui doit faire un rollback explicite après les COUNT.
    """

    def __init__(self, previews: list[TablePreview]) -> None:
        super().__init__("preview-rollback")
        self.previews = previews
