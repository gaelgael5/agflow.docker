from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VaultStatus(BaseModel):
    initialized: bool
    salt: str | None = None
    test_ciphertext: str | None = None
    test_iv: str | None = None


class VaultSetup(BaseModel):
    salt: str = Field(min_length=1)
    test_ciphertext: str = Field(min_length=1)
    test_iv: str = Field(min_length=1)


class ReEncryptedSecret(BaseModel):
    id: UUID
    ciphertext: str
    iv: str


class VaultChangePassphrase(BaseModel):
    salt: str = Field(min_length=1)
    test_ciphertext: str = Field(min_length=1)
    test_iv: str = Field(min_length=1)
    re_encrypted_secrets: list[ReEncryptedSecret] = Field(default_factory=list)


class UserSecretCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    ciphertext: str = Field(min_length=1)
    iv: str = Field(min_length=1)


class UserSecretSummary(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    ciphertext: str
    iv: str
    created_at: datetime
    updated_at: datetime


class UserSecretUpdate(BaseModel):
    ciphertext: str = Field(min_length=1)
    iv: str = Field(min_length=1)
