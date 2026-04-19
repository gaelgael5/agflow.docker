from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthContext:
    api_key_id: UUID
    owner_id: UUID
    is_admin: bool

    @classmethod
    def from_api_key(cls, row: dict) -> AuthContext:
        return cls(
            api_key_id=row["id"],
            owner_id=row["owner_id"],
            is_admin="*" in row.get("scopes", []),
        )
