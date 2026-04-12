from __future__ import annotations

import hashlib
import hmac as hmac_mod
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime

import bcrypt

_KEY_RE = re.compile(
    r"^agfd_"
    r"(?P<prefix>[0-9a-f]{12})"
    r"(?P<expiry>[0-9a-f]{8})"
    r"(?P<random>[0-9a-f]{20})"
    r"(?P<hmac>[0-9a-f]{8})$"
)

NO_EXPIRY = 0xFFFFFFFF


@dataclass
class ParsedKey:
    prefix: str
    expiry_ts: int
    random: str
    hmac_value: str
    body: str


def generate_api_key(
    salt: str,
    expires_at: datetime | None,
) -> tuple[str, str, str]:
    """Generate a self-validating API key.

    Returns (full_key, prefix, bcrypt_hash).
    """
    prefix = secrets.token_hex(6)
    expiry_hex = (
        "ffffffff"
        if expires_at is None
        else f"{int(expires_at.timestamp()):08x}"
    )
    random_part = secrets.token_hex(10)
    body = prefix + expiry_hex + random_part
    checksum = hmac_mod.new(
        salt.encode(), body.encode(), hashlib.sha256
    ).hexdigest()[:8]
    full_key = f"agfd_{body}{checksum}"
    key_hash = bcrypt.hashpw(full_key.encode(), bcrypt.gensalt()).decode()
    return full_key, prefix, key_hash


def parse_api_key(raw: str) -> ParsedKey | None:
    m = _KEY_RE.match(raw.strip().lower())
    if not m:
        return None
    return ParsedKey(
        prefix=m.group("prefix"),
        expiry_ts=int(m.group("expiry"), 16),
        random=m.group("random"),
        hmac_value=m.group("hmac"),
        body=m.group("prefix") + m.group("expiry") + m.group("random"),
    )


def verify_hmac(parsed: ParsedKey, salt: str) -> bool:
    expected = hmac_mod.new(
        salt.encode(), parsed.body.encode(), hashlib.sha256
    ).hexdigest()[:8]
    return hmac_mod.compare_digest(expected, parsed.hmac_value)


def is_expired(parsed: ParsedKey) -> bool:
    if parsed.expiry_ts == NO_EXPIRY:
        return False
    return parsed.expiry_ts < int(time.time())


def verify_bcrypt(full_key: str, key_hash: str) -> bool:
    return bcrypt.checkpw(full_key.encode(), key_hash.encode())
