from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CredentialKind = Literal["api-key", "test-account", "connector-token", "custom"]


class CredentialUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    label: str = Field(min_length=1, max_length=180)
    kind: CredentialKind
    secret: str = Field(min_length=1, max_length=20000)
    username: str | None = Field(default=None, max_length=256)
    metadata: dict[str, str] = Field(default_factory=dict)


class CredentialSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    kind: CredentialKind
    username: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    createdAt: str
    updatedAt: str
    secretPreview: str
    secretLength: int
