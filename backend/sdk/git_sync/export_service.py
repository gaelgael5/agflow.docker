"""Export d'un snapshot de tables vers le repo Git du module.

Flux (spec §8) :
    1. clone le repo via GitService
    2. résout le graphe de dépendances
    3. écrit `dependencies.json` dans le module_path
    4. pour chaque table : COPY ... TO CSV (streaming asyncpg)
    5. commit + push
    6. retourne SyncResult — cleanup garanti dans un finally

Filtre des colonnes pour chaque table :
    - colonnes listées dans `config.excluded_columns[table.full_name]`
    - colonnes `is_generated = 'ALWAYS'`
    - colonnes `identity_generation = 'ALWAYS'`

Règle « table vide » :
    Une table sans aucune ligne ne produit pas de fichier CSV. Si une exécution
    précédente avait écrit un fichier pour cette table (table peuplée à
    l'époque, vidée depuis), le fichier existant est supprimé pour que la
    suppression soit propagée par le commit Git.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sdk.git_sync.dependency_resolver import DependencyResolver
from sdk.git_sync.git_service import GitService
from sdk.git_sync.models import SyncResult, TableRef

_COLUMNS_QUERY = """
SELECT column_name, is_generated, identity_generation
FROM information_schema.columns
WHERE table_schema = $1 AND table_name = $2
ORDER BY ordinal_position
"""


class ExportService:
    def __init__(self, db_conn: Any, git_service: GitService) -> None:
        self._conn = db_conn
        self._git = git_service

    async def export(self, tables: list[TableRef]) -> SyncResult:
        repo_root: Path | None = None
        try:
            repo_root = await self._git.clone()
            module_path = self._git.get_module_path(repo_root)

            # Graphe de dépendances + sérialisation dans le repo.
            resolver = DependencyResolver(self._conn)
            graph = await resolver.resolve(tables)
            (module_path / "dependencies.json").write_text(
                json.dumps(
                    DependencyResolver.serialize(graph), indent=2, ensure_ascii=False
                ),
                encoding="utf-8",
            )

            exported: list[TableRef] = []
            for table in tables:
                await self._export_table(table, module_path)
                exported.append(table)

            message = (
                f"export({self._git.config.module_name}): "
                f"{len(exported)} tables"
            )
            commit_sha = await self._git.commit_and_push(repo_root, message)

            return SyncResult(
                success=True,
                commit_sha=commit_sha,
                tables_exported=exported,
            )
        finally:
            if repo_root is not None:
                self._git.cleanup(repo_root)

    async def _export_table(self, table: TableRef, module_path: Path) -> None:
        columns = await self._select_exportable_columns(table)
        csv_path = module_path / table.csv_name

        if not columns:
            # Aucune colonne à exporter (toutes exclues / table virtuelle) :
            # on n'écrit pas de fichier. Si un fichier d'une exécution
            # précédente existe, on le supprime pour cohérence.
            if csv_path.exists():
                csv_path.unlink()
            return

        if not await self._has_any_row(table):
            # Table vide : pas de fichier. Si un fichier précédent existait
            # (table peuplée puis vidée), on le supprime pour que la
            # suppression soit propagée par le commit.
            if csv_path.exists():
                csv_path.unlink()
            return

        cols_sql = ", ".join(f'"{c}"' for c in columns)
        query = (
            f'SELECT {cols_sql} FROM "{table.schema}"."{table.table}"'
        )
        with csv_path.open("wb") as f:
            await self._conn.copy_from_query(
                query, output=f, format="csv", header=True
            )

    async def _has_any_row(self, table: TableRef) -> bool:
        """True si la table contient au moins une ligne, False sinon."""
        return bool(
            await self._conn.fetchval(
                f'SELECT EXISTS (SELECT 1 FROM "{table.schema}"."{table.table}" LIMIT 1)'
            )
        )

    async def _select_exportable_columns(self, table: TableRef) -> list[str]:
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
