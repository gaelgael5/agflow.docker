"""Tests d'integration HTTP : auth + serialization + bypass services via mocks."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ["AGFLOW_INFRA_KEY"] = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE="

import jwt
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _viewer_token() -> str:
    return jwt.encode(
        {"sub": "viewer@example.com", "role": "viewer"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def test_list_swarm_clusters_requires_token(client: TestClient) -> None:
    r = client.get("/api/infra/swarm-clusters")
    assert r.status_code == 401


def test_list_swarm_clusters_rejects_viewer(client: TestClient) -> None:
    r = client.get(
        "/api/infra/swarm-clusters",
        headers={"Authorization": f"Bearer {_viewer_token()}"},
    )
    assert r.status_code == 403


def test_list_swarm_clusters_returns_list_for_admin(client: TestClient) -> None:
    cluster_id = uuid4()
    fake_clusters = [{
        "id": cluster_id, "name": "swarm1", "manager_addr": "10.0.0.1:2377",
        "node_count": 2, "manager_count": 1, "worker_count": 1,
        "created_at": "2026-04-30T00:00:00Z", "updated_at": "2026-04-30T00:00:00Z",
    }]
    with patch("agflow.api.infra.swarm_clusters.infra_swarm_clusters_service.list_all",
               AsyncMock(return_value=fake_clusters)):
        r = client.get(
            "/api/infra/swarm-clusters",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "swarm1"
    # Aucun token leak
    assert "join_token_worker" not in r.text
    assert "join_token_manager" not in r.text


def test_get_swarm_cluster_404_when_unknown(client: TestClient) -> None:
    with patch("agflow.api.infra.swarm_clusters.infra_swarm_clusters_service.get_by_id",
               AsyncMock(return_value=None)):
        r = client.get(
            f"/api/infra/swarm-clusters/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


def test_swarm_init_success(client: TestClient) -> None:
    cluster_dto = {"id": str(uuid4()), "name": "swarm1", "manager_addr": "10.0.0.1:2377",
                   "created_at": "2026-04-30T00:00:00Z", "updated_at": "2026-04-30T00:00:00Z"}
    with patch("agflow.api.infra.machines.swarm_actions_service.init_cluster",
               AsyncMock(return_value=cluster_dto)):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_init",
            json={"cluster_name": "swarm1"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["name"] == "swarm1"


def test_swarm_init_400_when_action_error(client: TestClient) -> None:
    from agflow.services.swarm_actions_service import SwarmActionError

    with patch("agflow.api.infra.machines.swarm_actions_service.init_cluster",
               AsyncMock(side_effect=SwarmActionError("Machine not swarm-ready"))):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_init",
            json={"cluster_name": "swarm1"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 400
    assert "swarm-ready" in r.text


def test_swarm_join_success(client: TestClient) -> None:
    with patch("agflow.api.infra.machines.swarm_actions_service.join_cluster",
               AsyncMock(return_value={"joined": True, "node_id": "n1", "role": "worker"})):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_join",
            json={"cluster_id": str(uuid4()), "role": "worker"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["joined"] is True


def test_swarm_join_400_invalid_role(client: TestClient) -> None:
    r = client.post(
        f"/api/infra/machines/{uuid4()}/actions/swarm_join",
        json={"cluster_id": str(uuid4()), "role": "boss"},
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    # Pydantic validation rejects -> 422
    assert r.status_code == 422


def test_swarm_leave_success(client: TestClient) -> None:
    with patch("agflow.api.infra.machines.swarm_actions_service.leave_cluster",
               AsyncMock(return_value={"left": True, "cluster_dropped": False})):
        r = client.post(
            f"/api/infra/machines/{uuid4()}/actions/swarm_leave",
            json={"force": False},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["left"] is True
