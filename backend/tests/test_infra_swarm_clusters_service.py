"""Tests purs (pas de DB, pas de vault) pour les helpers vault refs."""
from __future__ import annotations

from uuid import UUID

from agflow.services.infra_swarm_clusters_service import (
    _parse_vault_ref,
    _vault_path_manager,
    _vault_path_worker,
    _vault_ref,
)

_CLUSTER_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_vault_paths_are_distinct_per_role() -> None:
    worker = _vault_path_worker(_CLUSTER_ID)
    manager = _vault_path_manager(_CLUSTER_ID)
    assert worker != manager
    assert str(_CLUSTER_ID) in worker
    assert str(_CLUSTER_ID) in manager


def test_vault_ref_format_round_trips_through_parser() -> None:
    path = _vault_path_worker(_CLUSTER_ID)
    ref = _vault_ref(path)
    assert ref.startswith("${vault://HARPOCRATE_KEY:")
    assert _parse_vault_ref(ref) == path


def test_parse_vault_ref_rejects_unknown_key_name() -> None:
    assert _parse_vault_ref("${vault://OTHER_KEY:foo/bar}") is None


def test_parse_vault_ref_rejects_non_refs() -> None:
    assert _parse_vault_ref(None) is None
    assert _parse_vault_ref("") is None
    assert _parse_vault_ref("plain-text-token") is None
