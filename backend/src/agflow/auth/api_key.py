from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime

import bcrypt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


def _err(code: str, message: str) -> dict:
    """Structured error response for public API."""
    return {"error": {"code": code, "message": message}}


async def _check_rate_limit(prefix: str, limit: int) -> None:
    from agflow.redis.client import get_redis

    redis = await get_redis()
    key = f"ratelimit:agfd_{prefix}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)
    if current > limit:
        ttl = await redis.ttl(key)
        raise HTTPException(
            status_code=429,
            detail=_err("rate_limited", f"Rate limit exceeded ({limit}/min)"),
            headers={
                "Retry-After": str(ttl),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(int(time.time()) + ttl),
            },
        )


async def _update_last_used_bg(key_id: object) -> None:
    """Fire-and-forget update of last_used_at."""
    try:
        from agflow.services import api_keys_service

        await api_keys_service.update_last_used(key_id)
    except Exception:
        pass


def require_api_key(*required_scopes: str) -> object:
    """FastAPI Depends() factory. Validates API key in 3 levels:
    1. O(1) HMAC checksum + expiry (no I/O)
    2. DB lookup + bcrypt verify (~100ms)
    3. Redis rate limit check
    Returns the api_key DB row dict on success.
    """
    _bearer = HTTPBearer(auto_error=False)

    async def _dep(
        creds: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
    ) -> dict:
        if creds is None:
            raise HTTPException(401, _err("missing_token", "Authorization header required"))
        token = creds.credentials

        # ── Level 1: structure + HMAC + expiry (O(1), zero I/O) ──
        parsed = parse_api_key(token)
        if parsed is None:
            raise HTTPException(
                401, _err("invalid_format", "Token must start with agfd_ and be 53 chars")
            )

        from agflow.config import get_settings

        settings = get_settings()
        if not verify_hmac(parsed, settings.api_key_salt):
            raise HTTPException(401, _err("invalid_checksum", "Token checksum failed"))

        if is_expired(parsed):
            raise HTTPException(401, _err("expired", "API key has expired"))

        # ── Level 2: DB lookup + bcrypt (~100ms) ──
        from agflow.services import api_keys_service

        row = await api_keys_service.get_by_prefix(parsed.prefix)
        if row is None or row["revoked"]:
            raise HTTPException(
                401, _err("revoked_or_unknown", "API key not found or revoked")
            )

        if not verify_bcrypt(token, row["key_hash"]):
            raise HTTPException(401, _err("hash_mismatch", "Invalid API key"))

        # Scope check
        granted = set(row["scopes"])
        if "*" not in granted:
            for scope in required_scopes:
                if scope not in granted:
                    raise HTTPException(
                        403,
                        _err("missing_scope", f"This key lacks the '{scope}' scope"),
                    )

        # ── Level 3: rate limit (1 Redis call) ──
        await _check_rate_limit(parsed.prefix, row["rate_limit"])

        # Update last_used (fire-and-forget)
        asyncio.create_task(_update_last_used_bg(row["id"]))  # noqa: RUF006

        return dict(row)

    return Depends(_dep)
