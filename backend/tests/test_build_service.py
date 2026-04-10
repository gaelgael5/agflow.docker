from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")
os.environ.setdefault("SECRETS_MASTER_KEY", "x")

from agflow.services.build_service import compute_hash, image_tag_for  # noqa: E402


def _file(path: str, content: str) -> dict:
    return {"path": path, "content": content}


def test_compute_hash_is_deterministic() -> None:
    files = [
        _file("Dockerfile", "FROM alpine"),
        _file("entrypoint.sh", "#!/bin/sh\necho hi"),
    ]
    h1 = compute_hash(files)
    h2 = compute_hash(list(reversed(files)))
    assert h1 == h2
    assert len(h1) == 12


def test_compute_hash_ignores_non_dockerfile_non_sh() -> None:
    files = [
        _file("Dockerfile", "FROM alpine"),
        _file("README.md", "anything"),
    ]
    files_with_readme = files + [_file("README.md", "different content")]
    assert compute_hash(files) == compute_hash(files_with_readme)


def test_compute_hash_changes_when_dockerfile_changes() -> None:
    files_a = [_file("Dockerfile", "FROM alpine:3.18")]
    files_b = [_file("Dockerfile", "FROM alpine:3.19")]
    assert compute_hash(files_a) != compute_hash(files_b)


def test_compute_hash_includes_all_sh_files() -> None:
    files_a = [
        _file("Dockerfile", "FROM alpine"),
        _file("a.sh", "echo A"),
        _file("b.sh", "echo B"),
    ]
    files_b = [
        _file("Dockerfile", "FROM alpine"),
        _file("a.sh", "echo A"),
        _file("b.sh", "echo B_CHANGED"),
    ]
    assert compute_hash(files_a) != compute_hash(files_b)


def test_image_tag_format() -> None:
    assert (
        image_tag_for("claude-code", "a1b2c3d4e5f6")
        == "agflow-claude-code:a1b2c3d4e5f6"
    )
