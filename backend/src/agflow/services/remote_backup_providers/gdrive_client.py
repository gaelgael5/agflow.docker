"""Couche fine au-dessus du SDK Google pour Drive + OAuth2.

Toutes les fonctions wrappent un appel sync du SDK (qui n'est pas async-native)
soit dans un `asyncio.to_thread`, soit en sync direct si le caller orchestre lui-même.
Permet de mocker proprement le SDK dans les tests.
"""
from __future__ import annotations

import asyncio

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import Resource, build

_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_USERINFO_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


def build_credentials(creds_dict: dict) -> Credentials:
    """Reconstruit un objet Credentials Google depuis le dict stocké en vault."""
    return Credentials(
        token=None,
        refresh_token=creds_dict["refresh_token"],
        token_uri=creds_dict["token_uri"],
        client_id=creds_dict["client_id"],
        client_secret=creds_dict["client_secret"],
        scopes=[creds_dict["scope"]],
    )


def build_drive_service(creds: Credentials) -> Resource:
    """Instancie le client Drive v3."""
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def build_flow(
    *, client_id: str, client_secret: str, redirect_uri: str,
) -> Flow:
    """Construit un Flow OAuth2 pour Drive (scope drive.file + userinfo.email)."""
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        },
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=[_DRIVE_SCOPE, _USERINFO_SCOPE],
        redirect_uri=redirect_uri,
    )
    return flow


async def fetch_user_email(creds: Credentials) -> str:
    """Retourne l'email du compte Google associé aux credentials."""
    def _sync() -> str:
        service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = service.userinfo().get().execute()
        return str(info["email"])

    return await asyncio.to_thread(_sync)


async def refresh(creds: Credentials) -> Credentials:
    """Refresh l'access_token via le refresh_token. Mutation en place de creds."""
    def _sync() -> None:
        creds.refresh(Request())

    await asyncio.to_thread(_sync)
    return creds
