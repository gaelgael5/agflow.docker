from __future__ import annotations

import json
import secrets
from urllib.parse import urlencode

import bcrypt
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from agflow.auth.dependencies import require_admin
from agflow.auth.jwt import encode_token
from agflow.config import get_settings
from agflow.db.pool import execute, fetch_one
from agflow.schemas.auth import LoginRequest, LoginResponse, Me
from agflow.services import users_service

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/admin/auth", tags=["admin-auth"])

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_oauth_states: dict[str, bool] = {}


def _build_redirect_uri(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return f"{proto}://{host}/api/admin/auth/google/callback"


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate admin user",
    description="Validates email/password credentials against the configured admin account and returns a signed JWT access token.",
)
async def login(payload: LoginRequest) -> LoginResponse:
    settings = get_settings()
    if payload.email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not bcrypt.checkpw(payload.password.encode(), settings.admin_password_hash.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = encode_token(settings.admin_email)
    return LoginResponse(access_token=token)


@router.get(
    "/google",
    summary="Initiate Google OAuth2 login",
    description="Redirects the browser to Google's OAuth2 consent page. Generates and stores a CSRF state token before redirecting.",
)
async def google_login(request: Request) -> RedirectResponse:
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(400, "Google OAuth not configured")

    state = secrets.token_urlsafe(32)
    _oauth_states[state] = True

    redirect_uri = _build_redirect_uri(request)

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get(
    "/google/callback",
    summary="Handle Google OAuth2 callback",
    description="Exchanges the authorization code for tokens, fetches user info from Google, creates or links the user account, and redirects to the frontend with a JWT token.",
)
async def google_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    if not state or state not in _oauth_states:
        raise HTTPException(400, "Invalid OAuth state")
    del _oauth_states[state]

    settings = get_settings()
    redirect_uri = _build_redirect_uri(request)

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_res.status_code != 200:
            _log.error("google.token_error", status=token_res.status_code, body=token_res.text)
            raise HTTPException(502, "Google token exchange failed")

        tokens = token_res.json()
        access_token = tokens["access_token"]

        userinfo_res = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_res.status_code != 200:
            raise HTTPException(502, "Failed to fetch Google user info")

        userinfo = userinfo_res.json()

    google_sub = userinfo["sub"]
    email = userinfo.get("email", "")
    name = userinfo.get("name", "")
    avatar = userinfo.get("picture", "")

    _log.info("google.login", email=email, sub=google_sub)

    identity = await fetch_one(
        "SELECT user_id FROM user_identities WHERE provider = 'google' AND subject = $1",
        google_sub,
    )

    if identity:
        user = await users_service.get_by_id(identity["user_id"])
    else:
        existing = await users_service.get_by_email(email)
        if existing:
            user = existing
        else:
            user = await users_service.create(
                email=email,
                name=name,
                role="user",
                status="active",
            )
            if avatar:
                await execute(
                    "UPDATE users SET avatar_url = $2 WHERE id = $1",
                    user.id, avatar,
                )

        await execute(
            """
            INSERT INTO user_identities (user_id, provider, subject, email, raw_claims)
            VALUES ($1, 'google', $2, $3, $4)
            ON CONFLICT (provider, subject) DO NOTHING
            """,
            user.id, google_sub, email, json.dumps(userinfo),
        )

    if user.status != "active":
        return RedirectResponse("/login?error=account_disabled")

    await execute("UPDATE users SET last_login = NOW() WHERE id = $1", user.id)

    jwt_token = encode_token(user.email)
    return RedirectResponse(f"/login?token={jwt_token}")


@router.get(
    "/me",
    response_model=Me,
    summary="Get current authenticated user",
    description="Returns the email address of the currently authenticated admin user based on the JWT token.",
)
async def me(admin_email: str = Depends(require_admin)) -> Me:
    return Me(email=admin_email)
