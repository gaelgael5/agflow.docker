"""Provider Git HTTPS avec Personal Access Token.

Le token est injecté dans le userinfo de l'URL au moment du clone. Les
credentials éventuellement déjà présents (URL `https://user:pass@host/...`)
sont remplacés.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from sdk.git_sync.auth.base import GitAuthProvider


class PATHttpsAuthProvider(GitAuthProvider):
    def __init__(self, token: str) -> None:
        self._token = token

    def setup(self) -> None:
        return None

    def teardown(self) -> None:
        return None

    def get_clone_url(self, repo_url: str) -> str:
        return _inject_https_userinfo(repo_url, self._token)

    def get_env(self) -> dict[str, str]:
        return {}


def _inject_https_userinfo(url: str, userinfo: str) -> str:
    """Remplace ou ajoute le userinfo dans une URL http(s).

    URLs non-HTTP (SSH, file://) sont retournées inchangées : l'injection
    n'a pas de sens pour elles.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return url
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    new_netloc = f"{userinfo}@{host}{port}"
    return urlunsplit(
        (parts.scheme, new_netloc, parts.path, parts.query, parts.fragment)
    )
