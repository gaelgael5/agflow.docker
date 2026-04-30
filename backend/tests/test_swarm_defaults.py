from __future__ import annotations

from agflow.services.swarm_defaults import _DEFAULT_DEPLOY, deep_merge, resolve_deploy


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


def test_resolve_deploy_with_none_returns_full_defaults() -> None:
    result = resolve_deploy(None)
    assert result == _DEFAULT_DEPLOY
    # Independance : modifier le resultat ne doit pas muter les defaults
    result["replicas"] = 999
    assert _DEFAULT_DEPLOY["replicas"] == 1


def test_resolve_deploy_overrides_replicas() -> None:
    result = resolve_deploy({"replicas": 3})
    assert result["replicas"] == 3
    # Les autres defaults restent intacts
    assert result["endpoint_mode"] == "dnsrr"
    assert result["restart_policy"]["condition"] == "on-failure"


def test_resolve_deploy_deep_merges_resources() -> None:
    result = resolve_deploy(
        {
            "resources": {"limits": {"memory": "1G"}},
        }
    )
    assert result["resources"]["limits"]["memory"] == "1G"
    # Restart_policy intact
    assert result["restart_policy"]["max_attempts"] == 5


def test_resolve_deploy_replaces_constraints_list() -> None:
    result = resolve_deploy(
        {
            "placement": {"constraints": ["node.role == worker"]},
        }
    )
    assert result["placement"]["constraints"] == ["node.role == worker"]


def test_resolve_deploy_partial_restart_policy() -> None:
    result = resolve_deploy(
        {
            "restart_policy": {"max_attempts": 10},
        }
    )
    assert result["restart_policy"]["max_attempts"] == 10
    assert result["restart_policy"]["condition"] == "on-failure"
    assert result["restart_policy"]["delay"] == "10s"
