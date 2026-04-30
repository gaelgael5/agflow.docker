from __future__ import annotations

from agflow.services.swarm_defaults import deep_merge


def test_deep_merge_returns_base_copy_when_override_is_none() -> None:
    base = {"a": 1, "b": {"c": 2}}
    result = deep_merge(base, None)
    assert result == base
    # Mutating result must not mutate base
    result["a"] = 999
    result["b"]["c"] = 999
    assert base == {"a": 1, "b": {"c": 2}}


def test_deep_merge_returns_base_copy_when_override_is_empty() -> None:
    base = {"a": 1}
    result = deep_merge(base, {})
    assert result == base


def test_deep_merge_override_replaces_scalar() -> None:
    base = {"a": 1, "b": 2}
    assert deep_merge(base, {"a": 10}) == {"a": 10, "b": 2}


def test_deep_merge_recurses_into_nested_dicts() -> None:
    base = {"outer": {"inner1": 1, "inner2": 2}}
    override = {"outer": {"inner1": 10}}
    assert deep_merge(base, override) == {"outer": {"inner1": 10, "inner2": 2}}


def test_deep_merge_lists_are_replaced_not_concatenated() -> None:
    base = {"items": [1, 2, 3]}
    override = {"items": [9]}
    assert deep_merge(base, override) == {"items": [9]}


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"a": {"b": 1}}
    override = {"a": {"c": 2}}
    base_snapshot = {"a": {"b": 1}}
    override_snapshot = {"a": {"c": 2}}
    deep_merge(base, override)
    assert base == base_snapshot
    assert override == override_snapshot
