"""Helpers de lecture des secrets Docker Swarm avec fallback env vars.

En production sur Docker Swarm, les secrets sensibles sont mountés en
lecture seule sous ``/run/secrets/<nom>``. En développement local, ces
mêmes valeurs sont fournies via variables d'environnement (chargées depuis
un ``.env``).

Ce module expose trois helpers qui priorisent toujours le fichier secret
quand il existe, puis retombent sur la variable d'environnement, puis sur
une valeur par défaut. Aucune dépendance Python supplémentaire requise.
"""

from __future__ import annotations

import os
from pathlib import Path

# Path racine où Docker Swarm monte les secrets en lecture seule.
# Exposé en module-level pour permettre le monkeypatching dans les tests.
_SECRETS_DIR = Path("/run/secrets")


def get_swarm_secret(
    secret_name: str,
    env_fallback: str | None = None,
    default: str = "",
) -> str:
    """Lit un secret en priorité depuis /run/secrets/<secret_name>, sinon env var.

    Le contenu du fichier est strippé (whitespace en bord). Si le fichier est
    absent ET ``env_fallback`` est défini, retourne
    ``os.environ.get(env_fallback, default)``. Sinon retourne ``default``.

    Exemples :

        # Lit /run/secrets/jwt_secret en prod Swarm, JWT_SECRET en dev local.
        secret = get_swarm_secret("jwt_secret", env_fallback="JWT_SECRET")
    """
    path = _SECRETS_DIR / secret_name
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    if env_fallback is not None:
        return os.environ.get(env_fallback, default)
    return default


def get_swarm_secret_bytes(
    secret_name: str,
    default: bytes = b"",
) -> bytes:
    """Variante binaire pour les secrets non-texte (par ex. clés SSH).

    Pas de strip ni de décodage : les bytes sont retournés tels quels.
    Pas d'``env_fallback`` car les bytes ne transitent pas bien via env vars.

    Exemple :

        key_bytes = get_swarm_secret_bytes("agflow_backend_key")
    """
    path = _SECRETS_DIR / secret_name
    if path.exists():
        try:
            return path.read_bytes()
        except OSError:
            pass
    return default


def secret_path(secret_name: str) -> Path | None:
    """Retourne le path absolu du secret s'il existe, sinon None.

    Utile pour les bibliothèques qui veulent un chemin (par ex.
    ``asyncssh.read_private_key(path)``).

    Exemple :

        from agflow.utils.swarm_secrets import secret_path
        key_file = secret_path("agflow_backend_key") or Path("/app/.ssh/backend_key")
    """
    path = _SECRETS_DIR / secret_name
    return path if path.exists() else None
