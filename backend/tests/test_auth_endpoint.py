from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_success(client: TestClient) -> None:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/api/admin/auth/login",
        json={"email": "other@example.com", "password": "anything"},
    )
    assert response.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    response = client.get("/api/admin/auth/me")
    assert response.status_code == 401


def test_me_with_valid_token(client: TestClient) -> None:
    login = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    token = login.json()["access_token"]
    response = client.get(
        "/api/admin/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"
