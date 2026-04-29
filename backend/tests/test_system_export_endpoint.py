from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _operator_token() -> str:
    return jwt.encode(
        {"sub": "op@example.com", "role": "operator"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def test_export_requires_token(client: TestClient) -> None:
    r = client.get("/api/admin/system/export")
    assert r.status_code == 401


def test_export_rejects_non_admin(client: TestClient) -> None:
    r = client.get(
        "/api/admin/system/export",
        headers={"Authorization": f"Bearer {_operator_token()}"},
    )
    assert r.status_code == 403


def test_export_returns_zip_for_admin(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "hello.txt").write_bytes(b"hi")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "world.txt").write_bytes(b"world")
    monkeypatch.setenv("AGFLOW_DATA_DIR", str(tmp_path))

    r = client.get(
        "/api/admin/system/export",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    cd = r.headers["content-disposition"]
    m = re.match(r'attachment; filename="(agflow-data-\d{8}-\d{6}\.zip)"', cd)
    assert m, cd

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert sorted(zf.namelist()) == ["hello.txt", "sub/world.txt"]
        assert zf.read("hello.txt") == b"hi"
        assert zf.read("sub/world.txt") == b"world"


def test_export_returns_empty_zip_when_data_dir_missing(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGFLOW_DATA_DIR", str(tmp_path / "missing"))
    r = client.get(
        "/api/admin/system/export",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.namelist() == []
