from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.auth.jwt import encode_token
from agflow.config import get_settings
from agflow.schemas.auth import LoginRequest, LoginResponse, Me

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    settings = get_settings()
    if payload.email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not bcrypt.checkpw(payload.password.encode(), settings.admin_password_hash.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = encode_token(settings.admin_email)
    return LoginResponse(access_token=token)


@router.get("/me", response_model=Me)
async def me(admin_email: str = Depends(require_admin)) -> Me:
    return Me(email=admin_email)
