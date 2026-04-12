from __future__ import annotations

from fastapi import HTTPException


def api_error(status: int, code: str, message: str) -> HTTPException:
    """Raise a structured error for the public API.

    Response shape: {"error": {"code": "...", "message": "..."}}
    """
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message}},
    )
