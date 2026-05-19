"""DTOs pour le paramétrage OIDC/Keycloak."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthConfigOut(BaseModel):
    """Configuration retournée par GET. Le secret n'est jamais exposé : seul
    `has_secret` (bool) indique sa présence."""
    mode: Literal["local", "keycloak"]
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    has_secret: bool
    vault_name: str
    updated_at: datetime
    updated_by_user_id: UUID | None


class AuthConfigUpdate(BaseModel):
    """Payload PUT. Tous champs optionnels — seuls les champs présents sont
    mis à jour. `keycloak_client_secret` vide/None = ne pas modifier."""
    mode: Literal["local", "keycloak"] | None = None
    keycloak_url: str | None = None
    keycloak_realm: str | None = None
    keycloak_client_id: str | None = None
    keycloak_client_secret: str | None = None
    vault_name: str | None = None


class AuthTestRequest(BaseModel):
    """Payload pour POST /test. Si keycloak_client_secret est vide, le backend
    lit le secret actuel via le ref stocké en DB."""
    keycloak_url: str
    keycloak_realm: str
    keycloak_client_id: str
    keycloak_client_secret: str | None = None
    vault_name: str | None = None


class AuthTestResult(BaseModel):
    """Résultat du test. Toujours retourné en HTTP 200 ; le succès/échec est
    indiqué par `ok`. `step` dit jusqu'où on est allé."""
    ok: bool
    step: Literal["discovery", "token", "done"]
    detail: str
    discovery_ok: bool
    token_ok: bool
