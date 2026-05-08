from __future__ import annotations

import hashlib

from agflow.services import vault_client
from agflow.schemas.user_secrets import UserSecretSummary, UserSecretReveal


class DuplicateSecretError(Exception): ...


class SecretNotFoundError(Exception): ...


def _prefix(email: str) -> str:
    h = hashlib.sha256(email.lower().encode()).hexdigest()[:32]
    return f"users/{h}"


def _full_name(email: str, name: str) -> str:
    return f"{_prefix(email)}/{name}"


def _strip_prefix(full_name: str, prefix: str) -> str:
    return full_name[len(prefix) + 1:]


async def list_secrets(email: str) -> list[UserSecretSummary]:
    from harpocrate.exceptions import VaultHttpError
    try:
        secrets = await vault_client.list_secrets()
    except VaultHttpError:
        return []
    prefix = _prefix(email)
    return [
        UserSecretSummary(name=_strip_prefix(s.name, prefix), description=getattr(s, "description", None))
        for s in secrets
        if s.name.startswith(prefix + "/")
    ]


async def create_secret(email: str, name: str, value: str, description: str | None = None) -> UserSecretSummary:
    from harpocrate.exceptions import VaultHttpError
    full_name = _full_name(email, name)
    try:
        await vault_client.create_secret(full_name, value, description)
    except VaultHttpError as exc:
        if exc.status_code == 409:
            raise DuplicateSecretError(f"Secret '{name}' already exists") from exc
        raise
    return UserSecretSummary(name=name, description=description)


async def reveal_secret(email: str, name: str) -> UserSecretReveal:
    from harpocrate.exceptions import VaultHttpError
    full_name = _full_name(email, name)
    try:
        value = await vault_client.get_secret(full_name)
    except VaultHttpError as exc:
        if exc.status_code == 404:
            raise SecretNotFoundError(f"Secret '{name}' not found") from exc
        raise
    return UserSecretReveal(name=name, value=value)


async def update_secret(email: str, name: str, value: str) -> UserSecretSummary:
    from harpocrate.exceptions import VaultHttpError
    full_name = _full_name(email, name)
    try:
        await vault_client.update_secret(full_name, value)
    except VaultHttpError as exc:
        if exc.status_code == 404:
            raise SecretNotFoundError(f"Secret '{name}' not found") from exc
        raise
    return UserSecretSummary(name=name)


async def delete_secret(email: str, name: str) -> None:
    from harpocrate.exceptions import VaultHttpError
    full_name = _full_name(email, name)
    try:
        await vault_client.delete_secret(full_name)
    except VaultHttpError as exc:
        if exc.status_code == 404:
            raise SecretNotFoundError(f"Secret '{name}' not found") from exc
        raise
