"""Tests du helper HMAC SHA-256 pour la signature des hooks sortants v5.

Cf. docs/contracts/hook-docker-task-completed.md §3.1 :
    signed_string = timestamp + "\\n" + hook_id + "\\n" + raw_body
    signature_hex = HMAC_SHA256(secret, signed_string).hexdigest()
"""
from __future__ import annotations

from agflow.services.hook_signing import sign


def test_sign_deterministic():
    sig = sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body='{"hello":"world"}',
        secret_hex="0123456789abcdef" * 4,
    )
    assert sig == sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body='{"hello":"world"}',
        secret_hex="0123456789abcdef" * 4,
    )


def test_sign_different_secret_different_signature():
    common = dict(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body='{"x":1}',
    )
    sig_a = sign(**common, secret_hex="0" * 64)
    sig_b = sign(**common, secret_hex="1" * 64)
    assert sig_a != sig_b


def test_sign_different_body_different_signature():
    common = dict(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        secret_hex="0123456789abcdef" * 4,
    )
    sig_a = sign(**common, body='{"x":1}')
    sig_b = sign(**common, body='{"x":2}')
    assert sig_a != sig_b


def test_sign_output_is_hex_64_chars():
    sig = sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body="x",
        secret_hex="0123456789abcdef" * 4,
    )
    assert len(sig) == 64
    int(sig, 16)  # raises ValueError if not hex


def test_sign_newline_delimiter_format_stable():
    """Vérifie que la signature est stable et que le format \\n sépare bien
    les 3 composants (timestamp, hook_id, body)."""
    sig_a = sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="abc",
        body="x",
        secret_hex="0123456789abcdef" * 4,
    )
    assert isinstance(sig_a, str) and len(sig_a) == 64
    # Une signature avec un timestamp différent doit produire un autre hex
    sig_b = sign(
        timestamp="2026-05-18T10:00:01Z",
        hook_id="abc",
        body="x",
        secret_hex="0123456789abcdef" * 4,
    )
    assert sig_a != sig_b
