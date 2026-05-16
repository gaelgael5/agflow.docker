"""Tests purs (pas de DB, pas de vault) pour les helpers de paths vault swarm."""
from __future__ import annotations

from uuid import UUID

from agflow.services import vault_client
from agflow.services.infra_swarm_clusters_service import (
    _path_manager,
    _path_worker,
)

_CLUSTER_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_vault_paths_are_distinct_per_role() -> None:
    worker = _path_worker(_CLUSTER_ID)
    manager = _path_manager(_CLUSTER_ID)
    assert worker != manager
    assert str(_CLUSTER_ID) in worker
    assert str(_CLUSTER_ID) in manager


def test_ref_round_trips_through_vault_client() -> None:
    path = _path_worker(_CLUSTER_ID)
    ref = vault_client.build_ref("default", path)
    parsed = vault_client.parse_ref(ref)
    assert parsed == ("default", path)


def test_parse_ref_accepts_any_vault_name() -> None:
    # Le ref porte un nom logique de coffre — il n'y a plus de constante figée.
    parsed = vault_client.parse_ref(f"${{vault://my-vault:{_path_manager(_CLUSTER_ID)}}}")
    assert parsed is not None
    name, path = parsed
    assert name == "my-vault"
    assert path == _path_manager(_CLUSTER_ID)
