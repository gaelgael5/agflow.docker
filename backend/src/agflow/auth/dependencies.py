from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agflow.auth.jwt import InvalidTokenError, decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> str:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        payload = decode_token(creds.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    return sub


async def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> dict:
    """Accept both JWT (admin session) and API key (agfd_...).
    Returns {"type": "jwt", "sub": email} or {"type": "api_key", ...row}.
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )
    token = creds.credentials
    if token.startswith("agfd_"):
        from agflow.auth.api_key import (
            _check_rate_limit,
            _err,
            _update_last_used_bg,
            is_expired,
            parse_api_key,
            verify_bcrypt,
            verify_hmac,
        )
        from agflow.config import get_settings
        from agflow.services import api_keys_service

        parsed = parse_api_key(token)
        if parsed is None:
            raise HTTPException(401, _err("invalid_format", "Invalid API key format"))
        settings = get_settings()
        if not verify_hmac(parsed, settings.api_key_salt):
            raise HTTPException(401, _err("invalid_checksum", "Token checksum failed"))
        if is_expired(parsed):
            raise HTTPException(401, _err("expired", "API key expired"))
        row = await api_keys_service.get_by_prefix(parsed.prefix)
        if row is None or row["revoked"]:
            raise HTTPException(401, _err("revoked_or_unknown", "API key not found"))
        if not verify_bcrypt(token, row["key_hash"]):
            raise HTTPException(401, _err("hash_mismatch", "Invalid API key"))
        await _check_rate_limit(parsed.prefix, row["rate_limit"])
        asyncio.create_task(_update_last_used_bg(row["id"]))  # noqa: RUF006
        return {"type": "api_key", **dict(row)}
    else:
        # JWT path (existing logic)
        try:
            payload = decode_token(token)
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
            ) from exc
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        return {"type": "jwt", "sub": sub}
