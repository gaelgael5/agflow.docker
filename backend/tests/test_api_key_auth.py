from __future__ import annotations

import time

import pytest

from agflow.auth.api_key import (
    NO_EXPIRY,
    generate_api_key,
    is_expired,
    parse_api_key,
    verify_bcrypt,
    verify_hmac,
)

SALT = "test-salt-for-hmac-32chars-ok!!"


def test_generate_key_format() -> None:
    key, prefix, key_hash = generate_api_key(SALT, expires_at=None)
    assert key.startswith("agfd_")
    assert len(key) == 53
    assert len(prefix) == 12
    assert key_hash.startswith("$2b$")


def test_generate_key_roundtrip() -> None:
    key, prefix, key_hash = generate_api_key(SALT, expires_at=None)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert parsed.prefix == prefix
    assert parsed.expiry_ts == NO_EXPIRY
    assert verify_hmac(parsed, SALT)
    assert verify_bcrypt(key, key_hash)


def test_parse_invalid_key() -> None:
    assert parse_api_key("invalid") is None
    assert parse_api_key("agfd_tooshort") is None
    assert parse_api_key("agfx_" + "a" * 48) is None


def test_hmac_rejects_tampered_key() -> None:
    key, _, _ = generate_api_key(SALT, expires_at=None)
    tampered = key[:10] + ("1" if key[10] != "1" else "2") + key[11:]
    parsed = parse_api_key(tampered)
    if parsed is not None:
        assert not verify_hmac(parsed, SALT)


def test_expiry_encoding() -> None:
    from datetime import datetime, timezone

    future = datetime(2027, 6, 15, tzinfo=timezone.utc)
    key, _, _ = generate_api_key(SALT, expires_at=future)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert not is_expired(parsed)
    assert parsed.expiry_ts == int(future.timestamp())


def test_expired_key_detected() -> None:
    from datetime import datetime, timezone

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    key, _, _ = generate_api_key(SALT, expires_at=past)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert is_expired(parsed)


def test_no_expiry() -> None:
    key, _, _ = generate_api_key(SALT, expires_at=None)
    parsed = parse_api_key(key)
    assert parsed is not None
    assert parsed.expiry_ts == NO_EXPIRY
    assert not is_expired(parsed)
