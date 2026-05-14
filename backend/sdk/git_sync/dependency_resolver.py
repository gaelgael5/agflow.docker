"""Résolution du graphe de dépendances FK entre tables PostgreSQL.

Interroge `information_schema` pour extraire les FK, filtre sur les tables
demandées par l'appelant, et expose le résultat sous forme de
`DependencyGraph` (qui calcule le tri topologique à la demande).

Le SDK expose aussi `serialize` / `deserialize` pour persister le graphe
sous forme JSON dans le repo Git — pour que l'import puisse reconstruire
l'ordre sans avoir à re-requêter `information_schema` (utile quand on
importe vers une DB qui n'a pas encore les FK déclarées de la même façon).
"""
from __future__ import annotations

from typing import Any

from sdk.git_sync.exceptions import DependencyResolveError
from sdk.git_sync.models import DependencyGraph, TableRef

_SERIALIZATION_VERSION = "1.0"

# Requête tirée de la spec §7. Filtre côté SQL sur les full_names passés
# en paramètre — évite de tirer tout le graphe puis filtrer en Python.
_FK_QUERY = """
SELECT
    tc.table_schema || '.' || tc.table_name  AS dependent_table,
    ccu.table_schema || '.' || ccu.table_name AS depends_on
FROM information_schema.table_constraints tc
JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name
    AND tc.constraint_schema = rc.constraint_schema
JOIN information_schema.constraint_column_usage ccu
    ON rc.unique_constraint_name = ccu.constraint_name
    AND rc.unique_constraint_schema = ccu.constraint_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND (tc.table_schema || '.' || tc.table_name) = ANY($1::text[])
"""


class DependencyResolver:
    """Construit un `DependencyGraph` à partir d'une connexion asyncpg.

    L'instance est stateless en dehors de la connexion stockée — les
    méthodes `serialize` / `deserialize` sont statiques.
    """

    def __init__(self, db_conn: Any) -> None:
        self._conn = db_conn

    async def resolve(self, tables: list[TableRef]) -> DependencyGraph:
        """Interroge information_schema et retourne le graphe filtré.

        Avec `tables=[]`, retourne un graphe vide sans même toucher à la
        DB — c'est utile pour les modules qui n'exportent rien lors d'un
        cycle particulier.
        """
        if not tables:
            return DependencyGraph(tables=[], edges=[])

        full_names = [t.full_name for t in tables]
        rows = await self._conn.fetch(_FK_QUERY, full_names)

        by_name = {t.full_name: t for t in tables}
        edges: list[tuple[TableRef, TableRef]] = []
        for row in rows:
            dep_name = row["dependent_table"]
            ref_name = row["depends_on"]
            # Garde uniquement les edges où LES DEUX extrémités sont dans
            # la liste demandée. Les FK vers une table hors-scope sont
            # ignorées (l'import s'assurera de la cohérence en chargeant
            # d'abord la cible ou en la traitant comme externe).
            if dep_name in by_name and ref_name in by_name:
                edges.append((by_name[dep_name], by_name[ref_name]))

        return DependencyGraph(tables=list(tables), edges=edges)

    @staticmethod
    def serialize(graph: DependencyGraph) -> dict[str, Any]:
        """Sérialise un graphe en dict JSON-able (forme spec §7)."""
        return {
            "version": _SERIALIZATION_VERSION,
            "tables": [
                {"schema": t.schema, "table": t.table} for t in graph.tables
            ],
            "edges": [
                {"from": dep.full_name, "to": ref.full_name}
                for dep, ref in graph.edges
            ],
            "ordered": [t.full_name for t in graph.ordered],
        }

    @staticmethod
    def deserialize(data: dict[str, Any]) -> DependencyGraph:
        """Reconstruit un `DependencyGraph` depuis sa forme sérialisée.

        Lance `DependencyResolveError` si la structure est invalide. La
        liste `ordered` du dict est ignorée — elle est recalculée à la
        volée via `DependencyGraph.ordered`, garantissant la cohérence
        même si le sérialiseur d'une version antérieure avait un bug.
        """
        if not isinstance(data, dict):
            raise DependencyResolveError(
                f"format invalide : attendu dict, reçu {type(data).__name__}"
            )
        if "version" not in data:
            raise DependencyResolveError("champ requis manquant : 'version'")
        if "tables" not in data:
            raise DependencyResolveError("champ requis manquant : 'tables'")
        if "edges" not in data:
            raise DependencyResolveError("champ requis manquant : 'edges'")

        tables: list[TableRef] = []
        for i, entry in enumerate(data["tables"]):
            if (
                not isinstance(entry, dict)
                or "schema" not in entry
                or "table" not in entry
            ):
                raise DependencyResolveError(
                    f"tables[{i}] invalide : attendu {{schema, table}}, "
                    f"reçu {entry!r}"
                )
            tables.append(TableRef(schema=entry["schema"], table=entry["table"]))

        by_name = {t.full_name: t for t in tables}
        edges: list[tuple[TableRef, TableRef]] = []
        for i, edge in enumerate(data["edges"]):
            if not isinstance(edge, dict) or "from" not in edge or "to" not in edge:
                raise DependencyResolveError(
                    f"edges[{i}] invalide : attendu {{from, to}}, reçu {edge!r}"
                )
            if edge["from"] not in by_name or edge["to"] not in by_name:
                raise DependencyResolveError(
                    f"edges[{i}] référence une table non déclarée : {edge!r}"
                )
            edges.append((by_name[edge["from"]], by_name[edge["to"]]))

        return DependencyGraph(tables=tables, edges=edges)
