from __future__ import annotations

import pytest

from sdk.git_sync.exceptions import DependencyResolveError
from sdk.git_sync.models import (
    AuthMode,
    DependencyGraph,
    GitConfig,
    TableRef,
)

# ─── TableRef ────────────────────────────────────────────────────────────────


def test_table_ref_full_name():
    assert TableRef(schema="public", table="stacks").full_name == "public.stacks"


def test_table_ref_csv_name():
    assert TableRef(schema="public", table="stacks").csv_name == "public.stacks.csv"


def test_table_ref_tmp_name_replaces_dot_with_underscore():
    # Convention : tmp_<schema>_<table> (le `.` de full_name devient `_`)
    assert TableRef(schema="public", table="stacks").tmp_name == "tmp_public_stacks"


def test_table_ref_equality_and_hashable():
    a = TableRef(schema="public", table="stacks")
    b = TableRef(schema="public", table="stacks")
    c = TableRef(schema="public", table="services")
    assert a == b
    assert a != c
    # Doit être hashable pour pouvoir être clé de dict / élément de set
    assert {a, b, c} == {a, c}


# ─── AuthMode ────────────────────────────────────────────────────────────────


def test_auth_mode_values():
    assert AuthMode.SSH_KEY.value == "ssh_key"
    assert AuthMode.PAT_HTTPS.value == "pat_https"
    assert AuthMode.BASIC_HTTPS.value == "basic_https"


# ─── GitConfig ───────────────────────────────────────────────────────────────


def test_git_config_defaults():
    cfg = GitConfig(
        repo_url="git@example.org:org/repo.git",
        auth_mode=AuthMode.SSH_KEY,
        auth_secret_ref="${vault://git/docker/ssh_key}",
        module_name="docker",
        commit_author_name="bot",
        commit_author_email="bot@example.org",
    )
    assert cfg.branch == "main"
    assert cfg.target_commit is None
    assert cfg.excluded_columns == {}


def test_git_config_excluded_columns_per_instance_isolated():
    """Le default_factory de excluded_columns ne doit pas être partagé entre instances."""
    a = GitConfig(
        repo_url="x", auth_mode=AuthMode.SSH_KEY, auth_secret_ref="y",
        module_name="m", commit_author_name="n", commit_author_email="e",
    )
    b = GitConfig(
        repo_url="x", auth_mode=AuthMode.SSH_KEY, auth_secret_ref="y",
        module_name="m", commit_author_name="n", commit_author_email="e",
    )
    a.excluded_columns["public.t"] = ["col"]
    assert b.excluded_columns == {}


# ─── DependencyGraph ─────────────────────────────────────────────────────────


def _t(name: str) -> TableRef:
    return TableRef(schema="public", table=name)


def test_dependency_graph_ordered_simple_chain():
    # A ← B ← C  (B depends_on A, C depends_on B)
    a, b, c = _t("a"), _t("b"), _t("c")
    graph = DependencyGraph(
        tables=[c, a, b],  # ordre d'entrée volontairement chaotique
        edges=[(b, a), (c, b)],
    )
    assert graph.ordered == [a, b, c]
    assert graph.ordered_reverse == [c, b, a]


def test_dependency_graph_ordered_no_edges():
    a, b = _t("a"), _t("b")
    graph = DependencyGraph(tables=[a, b], edges=[])
    # Sans dépendances, le tri topo est stable : ordre d'entrée préservé.
    assert graph.ordered == [a, b]


def test_dependency_graph_ordered_multiple_dependencies():
    # D dépend de B et C ; B et C dépendent de A.
    a, b, c, d = _t("a"), _t("b"), _t("c"), _t("d")
    graph = DependencyGraph(
        tables=[a, b, c, d],
        edges=[(b, a), (c, a), (d, b), (d, c)],
    )
    ordered = graph.ordered
    # A en premier, D en dernier ; B et C entre les deux dans un ordre quelconque.
    assert ordered[0] == a
    assert ordered[-1] == d
    assert set(ordered[1:3]) == {b, c}


def test_dependency_graph_cycle_raises():
    a, b = _t("a"), _t("b")
    graph = DependencyGraph(
        tables=[a, b],
        edges=[(a, b), (b, a)],
    )
    with pytest.raises(DependencyResolveError, match="cycle"):
        _ = graph.ordered


def test_dependency_graph_empty():
    graph = DependencyGraph(tables=[], edges=[])
    assert graph.ordered == []
    assert graph.ordered_reverse == []
