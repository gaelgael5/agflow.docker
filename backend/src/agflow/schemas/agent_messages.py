from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentMessageOut(BaseModel):
    """Message persisté dans `agent_messages`, renvoyé par les endpoints.

    Le champ `payload` est exposé en `Any` car la colonne est JSONB : selon
    la connexion asyncpg (codec JSON enregistré ou non), le driver peut
    retourner un `dict` ou une `str` JSON brute. Idem pour `route`. Aligner
    le codec au niveau du pool est suivi via TODO dans
    `services/agent_messages_service.py`.
    """

    msg_id: str
    parent_msg_id: str | None = None
    direction: str
    kind: str
    payload: Any
    source: str
    created_at: str
    route: Any = None
