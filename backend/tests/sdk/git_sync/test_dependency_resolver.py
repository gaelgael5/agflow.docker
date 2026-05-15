from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sdk.git_sync.dependency_resolver import DependencyResolver
from sdk.git_sync.exceptions import DependencyResolveError
from sdk.git_sync.models import DependencyGraph, TableRef


def _t(name: str) -> TableRef:
    return TableRef(schema="public", table=name)


# ─── resolve() ───────────────────────────────────────────────────────────────


async def test_resolve_builds_graph_from_information_schema_query():
    """Le résolveur interroge information_schema et filtre sur les tables demandées."""
    # Simule : services → stacks, networks → stacks
    fake_rows = [
        {
            "dependent_table": "public.services",
            "depends_on": "public.stacks",
        },
        {
            "dependent_table": "public.networks",
            "depends_on": "public.stacks",
        },
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fake_rows)
    resolver = DependencyResolver(conn)

    stacks, services, networks = _t("stacks"), _t("services"), _t("networks")
    graph = await resolver.resolve([stacks, services, networks])

    assert isinstance(graph, DependencyGraph)
    assert set(graph.tables) == {stacks, services, networks}
    assert (services, stacks) in graph.edges
    assert (networks, stacks) in graph.edges
    # Et le tri topologique fonctionne sur ce graphe
    ordered = graph.ordered
    assert ordered[0] == stacks


async def test_resolve_ignores_edges_to_tables_not_in_list():
    """Si une FK pointe vers une table hors-scope, elle est ignorée."""
    fake_rows = [
        {
            "dependent_table": "public.services",
            "depends_on": "public.stacks",
        },
        {
            # Cette FK référence une table NON demandée → doit être ignorée
            "dependent_table": "public.services",
            "depends_on": "public.users",
        },
    ]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=fake_rows)
    resolver = DependencyResolver(conn)

    graph = await resolver.resolve([_t("stacks"), _t("services")])

    # Une seule edge dans le graphe — la FK vers users a été dropée
    assert len(graph.edges) == 1


async def test_resolve_empty_tables_returns_empty_graph():
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    resolver = DependencyResolver(conn)

    graph = await resolver.resolve([])

    assert graph.tables == []
    assert graph.edges == []
    # Avec aucune table demandée, on n'a même pas besoin d'aller en base
    conn.fetch.assert_not_called()


# ─── serialize() ─────────────────────────────────────────────────────────────


def test_serialize_produces_expected_structure():
    a, b = _t("a"), _t("b")
    graph = DependencyGraph(tables=[a, b], edges=[(b, a)])

    data = DependencyResolver.serialize(graph)

    assert data["version"] == "1.0"
    assert data["tables"] == [
        {"schema": "public", "table": "a"},
        {"schema": "public", "table": "b"},
    ]
    assert data["edges"] == [
        {"from": "public.b", "to": "public.a"},
    ]
    assert data["ordered"] == ["public.a", "public.b"]


# ─── deserialize() ───────────────────────────────────────────────────────────


def test_deserialize_roundtrip():
    a, b = _t("a"), _t("b")
    original = DependencyGraph(tables=[a, b], edges=[(b, a)])
    serialized = DependencyResolver.serialize(original)

    restored = DependencyResolver.deserialize(serialized)

    assert set(restored.tables) == set(original.tables)
    assert set(restored.edges) == set(original.edges)
    assert restored.ordered == original.ordered


def test_deserialize_missing_version_raises():
    with pytest.raises(DependencyResolveError, match="version"):
        DependencyResolver.deserialize({"tables": [], "edges": [], "ordered": []})


def test_deserialize_missing_tables_raises():
    with pytest.raises(DependencyResolveError, match="tables"):
        DependencyResolver.deserialize({"version": "1.0", "edges": [], "ordered": []})


def test_deserialize_bad_table_structure_raises():
    with pytest.raises(DependencyResolveError):
        DependencyResolver.deserialize(
            {
                "version": "1.0",
                "tables": [{"schema": "public"}],  # manque `table`
                "edges": [],
                "ordered": [],
            }
        )
