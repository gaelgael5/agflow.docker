"""Provider Git HTTPS avec couple `username:password`.

Le secret reçu est un payload JSON `{"username": "...", "password": "..."}`
(format imposé par la spec pour rester transportable via Harpocrate).
"""
from __future__ import annotations

import json

from sdk.git_sync.auth.base import GitAuthProvider
from sdk.git_sync.auth.pat_https import _inject_https_userinfo


class BasicHttpsAuthProvider(GitAuthProvider):
    def __init__(self, secret_json: str) -> None:
        try:
            data = json.loads(secret_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"BasicHttpsAuthProvider attend un JSON `{{username, password}}`, "
                f"reçu invalide : {exc}"
            ) from exc

        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            raise ValueError(
                "BasicHttpsAuthProvider : champs `username` et `password` requis"
            )
        self._username = str(username)
        self._password = str(password)

    def setup(self) -> None:
        return None

    def teardown(self) -> None:
        return None

    def get_clone_url(self, repo_url: str) -> str:
        userinfo = f"{self._username}:{self._password}"
        return _inject_https_userinfo(repo_url, userinfo)

    def get_env(self) -> dict[str, str]:
        return {}
