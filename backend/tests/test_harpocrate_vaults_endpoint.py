"""Tests d'intégration HTTP du router admin harpocrate-vaults.

Mock le service pour isoler la couche routing/auth/serialization.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from agflow.schemas.harpocrate_vaults import VaultSummary, VaultTestConnectionResult


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


def _summary(name: str = "default", is_default: bool = True) -> VaultSummary:
    return VaultSummary(
        id=uuid4(),
        name=name,
        base_url="https://vault.example.com",
        api_key_id="default",
        is_default=is_default,
        created_at=datetime(2026, 5, 16, tzinfo=UTC),
        updated_at=datetime(2026, 5, 16, tzinfo=UTC),
    )


def test_list_requires_token(client: TestClient) -> None:
    r = client.get("/api/admin/harpocrate-vaults")
    assert r.status_code == 401


def test_list_rejects_viewer(client: TestClient) -> None:
    r = client.get(
        "/api/admin/harpocrate-vaults",
        headers={"Authorization": f"Bearer {_viewer_token()}"},
    )
    assert r.status_code == 403


def test_list_returns_summaries_for_admin(client: TestClient) -> None:
    fake = [_summary(name="v1"), _summary(name="v2", is_default=False)]
    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.list_all",
        AsyncMock(return_value=fake),
    ):
        r = client.get(
            "/api/admin/harpocrate-vaults",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    # Aucun api_key leak — vérifie spécifiquement la clé JSON et la colonne DB
    assert '"api_key":' not in r.text
    assert "api_key_encrypted" not in r.text


def test_create_returns_201(client: TestClient) -> None:
    fake = _summary(name="created")
    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.create",
        AsyncMock(return_value=fake),
    ):
        r = client.post(
            "/api/admin/harpocrate-vaults",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "created",
                "base_url": "https://vault.example.com",
                "api_key_id": "default",
                "api_key": "hrpv_1_secret_value",
                "is_default": True,
            },
        )
    assert r.status_code == 201
    assert r.json()["name"] == "created"
    assert '"api_key":' not in r.text


def test_create_returns_409_on_duplicate(client: TestClient) -> None:
    from agflow.services.harpocrate_vaults_service import DuplicateVaultNameError

    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.create",
        AsyncMock(side_effect=DuplicateVaultNameError("Vault 'x' already exists")),
    ):
        r = client.post(
            "/api/admin/harpocrate-vaults",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "x",
                "base_url": "https://vault.example.com",
                "api_key_id": "default",
                "api_key": "hrpv_1_x",
            },
        )
    assert r.status_code == 409


def test_create_returns_503_when_no_dek(client: TestClient) -> None:
    from agflow.services.harpocrate_vaults_service import NoDekConfiguredError

    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.create",
        AsyncMock(side_effect=NoDekConfiguredError("HARPOCRATE_DEK is not configured")),
    ):
        r = client.post(
            "/api/admin/harpocrate-vaults",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "x",
                "base_url": "https://vault.example.com",
                "api_key_id": "default",
                "api_key": "hrpv_1_x",
            },
        )
    assert r.status_code == 503


def test_delete_returns_204(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.delete",
        AsyncMock(return_value=None),
    ):
        r = client.delete(
            f"/api/admin/harpocrate-vaults/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 204


def test_delete_returns_404_when_missing(client: TestClient) -> None:
    from agflow.services.harpocrate_vaults_service import VaultNotFoundError

    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.delete",
        AsyncMock(side_effect=VaultNotFoundError("Vault x not found")),
    ):
        r = client.delete(
            f"/api/admin/harpocrate-vaults/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


def test_set_default_returns_summary(client: TestClient) -> None:
    fake = _summary(name="promoted", is_default=True)
    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.set_default",
        AsyncMock(return_value=fake),
    ):
        r = client.post(
            f"/api/admin/harpocrate-vaults/{uuid4()}/set-default",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["is_default"] is True


def test_test_connection_returns_result(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.test_connection",
        AsyncMock(return_value=VaultTestConnectionResult(ok=True)),
    ):
        r = client.post(
            f"/api/admin/harpocrate-vaults/{uuid4()}/test-connection",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "error": None}


def test_test_connection_returns_error_message(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.harpocrate_vaults.vaults.test_connection",
        AsyncMock(return_value=VaultTestConnectionResult(ok=False, error="401 Unauthorized")),
    ):
        r = client.post(
            f"/api/admin/harpocrate-vaults/{uuid4()}/test-connection",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "401" in body["error"]
