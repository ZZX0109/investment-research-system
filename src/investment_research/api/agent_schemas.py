from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AgentRunCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    task_text: str = Field(min_length=1, max_length=4000)
    as_of: datetime
    provider_profile_id: str | None = None
    user_preference: Literal["conservative", "growth", "short_term", "fund"] = "conservative"


class ConversationCreateRequest(BaseModel):
    """Bind a multi-turn conversation to one asset + one as_of."""

    asset_id: str = Field(min_length=1)
    as_of: datetime
    title: str | None = Field(default=None, max_length=200)


class ConversationMessageCreateRequest(BaseModel):
    """A user's question in an existing conversation."""

    content: str = Field(min_length=1, max_length=4000)
    provider_profile_id: str | None = None
    user_preference: Literal["conservative", "growth", "short_term", "fund"] = "conservative"


class ProviderProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    protocol: Literal["openai_compatible", "anthropic_messages", "gemini_generate_content", "ollama", "mock"]
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=256)
    credential_ref: str | None = None
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    context_limit: int = Field(default=32_000, ge=1000, le=1_000_000)
    fallback_profile_id: str | None = None
    enabled: bool = True


class ProviderProfilePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    protocol: Literal["openai_compatible", "anthropic_messages", "gemini_generate_content", "ollama", "mock"] | None = None
    endpoint: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=256)
    credential_ref: str | None = None
    timeout_seconds: float | None = Field(default=None, ge=1.0, le=120.0)
    context_limit: int | None = Field(default=None, ge=1000, le=1_000_000)
    fallback_profile_id: str | None = None
    enabled: bool | None = None
