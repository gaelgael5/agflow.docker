from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agflow.auth.jwt import InvalidTokenError, decode_token

_bearer_scheme = HTTPBearer(auto_error=False)

VALID_ROLES = ("admin", "operator", "viewer")


def _extract_role(payload: dict) -> str:
    """Extract role from JWT payload with backward compat (default admin)."""
    role = payload.get("role", "admin")
    return role if role in VALID_ROLES else "viewer"


async def _get_jwt_payload(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        return decode_token(creds.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def require_admin(
    payload: dict = Depends(_get_jwt_payload),  # noqa: B008
) -> str:
    """Only admin role."""
    if _extract_role(payload) != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    sub = payload.get("sub", "")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return sub


async def require_operator(
    payload: dict = Depends(_get_jwt_payload),  # noqa: B008
) -> str:
    """Admin or operator role."""
    if _extract_role(payload) not in ("admin", "operator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator role required")
    sub = payload.get("sub", "")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return sub


async def require_operator_or_m2m(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> dict:
    """Accept JWT (admin/operator) OR API key with `m2m:orchestrate` scope.

    Used by the workflow orchestration endpoints (cf. `docs/contracts/`) so that
    ag.flow can call `/api/admin/*` with a long-lived API key (Bearer transport),
    while keeping the existing JWT-based admin UI access.

    Returns a dict :
      - {"type": "jwt", "sub": email, "role": "admin|operator"}
      - {"type": "api_key", "id": ..., "owner_id": ..., "scopes": [...], ...}
    """
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )
    token = creds.credentials

    # ── API key path (agfd_*) ──
    if token.startswith("agfd_"):
        # Lazy imports to avoid circular deps at module load.
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

        granted = set(row["scopes"])
        if "*" not in granted and "m2m:orchestrate" not in granted:
            raise HTTPException(
                403,
                _err(
                    "missing_scope",
                    "This key lacks the 'm2m:orchestrate' scope required for /api/admin/*",
                ),
            )

        await _check_rate_limit(parsed.prefix, row["rate_limit"])
        asyncio.create_task(_update_last_used_bg(row["id"]))  # noqa: RUF006
        return {"type": "api_key", **dict(row)}

    # ── JWT path (admin UI) ──
    try:
        payload = decode_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc),
        ) from exc
    if _extract_role(payload) not in ("admin", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Operator role required",
        )
    sub = payload.get("sub", "")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload",
        )
    return {"type": "jwt", "sub": sub, "role": _extract_role(payload)}


async def require_viewer(
    payload: dict = Depends(_get_jwt_payload),  # noqa: B008
) -> str:
    """Any authenticated role (admin, operator, viewer)."""
    sub = payload.get("sub", "")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    return sub


async def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),  # noqa: B008
) -> dict:
    """Accept both JWT (admin session) and API key (agfd_...).
    Returns {"type": "jwt", "sub": email, "role": role} or {"type": "api_key", ...row}.
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
        return {"type": "jwt", "sub": sub, "role": _extract_role(payload)}
