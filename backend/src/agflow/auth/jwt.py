from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt

from agflow.config import get_settings


class InvalidTokenError(Exception):
    pass


def encode_token(subject: str) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.jwt_expire_hours * 3600,
    }
    return pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except pyjwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
