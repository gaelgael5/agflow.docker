from __future__ import annotations

from pathlib import Path

import pytest

from agflow.utils import swarm_secrets


@pytest.fixture
def fake_secrets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(swarm_secrets, "_SECRETS_DIR", tmp_path)
    return tmp_path


def test_get_swarm_secret_reads_file(fake_secrets_dir: Path) -> None:
    (fake_secrets_dir / "jwt_secret").write_text("from-file-secret\n", encoding="utf-8")
    assert swarm_secrets.get_swarm_secret("jwt_secret") == "from-file-secret"


def test_get_swarm_secret_strips_whitespace(fake_secrets_dir: Path) -> None:
    (fake_secrets_dir / "secret").write_text("  trimmed  \n", encoding="utf-8")
    assert swarm_secrets.get_swarm_secret("secret") == "trimmed"


def test_get_swarm_secret_falls_back_to_env(
    fake_secrets_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_VAR", "from-env")
    result = swarm_secrets.get_swarm_secret("absent", env_fallback="MY_VAR")
    assert result == "from-env"


def test_get_swarm_secret_returns_default_when_no_file_no_env(
    fake_secrets_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    result = swarm_secrets.get_swarm_secret(
        "absent", env_fallback="DOES_NOT_EXIST", default="fallback-default"
    )
    assert result == "fallback-default"


def test_get_swarm_secret_returns_default_without_env_fallback(
    fake_secrets_dir: Path,
) -> None:
    assert swarm_secrets.get_swarm_secret("absent", default="x") == "x"
    assert swarm_secrets.get_swarm_secret("absent") == ""


def test_get_swarm_secret_bytes_reads_binary(fake_secrets_dir: Path) -> None:
    payload = b"\x00\x01\x02private-key-bytes"
    (fake_secrets_dir / "key").write_bytes(payload)
    assert swarm_secrets.get_swarm_secret_bytes("key") == payload


def test_get_swarm_secret_bytes_default_when_absent(fake_secrets_dir: Path) -> None:
    assert swarm_secrets.get_swarm_secret_bytes("absent") == b""
    assert swarm_secrets.get_swarm_secret_bytes("absent", default=b"x") == b"x"


def test_secret_path_returns_path_when_present(fake_secrets_dir: Path) -> None:
    (fake_secrets_dir / "key").write_text("x", encoding="utf-8")
    p = swarm_secrets.secret_path("key")
    assert p is not None
    assert p.read_text() == "x"


def test_secret_path_returns_none_when_absent(fake_secrets_dir: Path) -> None:
    assert swarm_secrets.secret_path("absent") is None
