from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-abc")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")

from agflow.auth.jwt import InvalidTokenError, decode_token, encode_token


def test_encode_decode_roundtrip() -> None:
    token = encode_token("admin@example.org")
    payload = decode_token(token)
    assert payload["sub"] == "admin@example.org"
    assert payload["exp"] > time.time()


def test_decode_invalid_token_raises() -> None:
    with pytest.raises(InvalidTokenError):
        decode_token("not.a.token")
