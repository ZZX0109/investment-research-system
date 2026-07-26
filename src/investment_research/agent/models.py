from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from pydantic import model_validator
from urllib.parse import urlparse
import ipaddress

from investment_research.domain.base import utc_now


class AgentRunState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentBudget(BaseModel):
    # Classification, planning, function selection, counter-evidence, audit and
    # the final explanation are separate bounded calls.  Eight leaves room for
    # a second tool-selection turn without silently replacing the explanation
    # with deterministic fallback text.
    max_llm_calls: int = 8
    max_tool_calls: int = 12
    max_input_tokens: int = 32_000
    max_output_tokens: int = 4_000
    max_evidence: int = 12
    max_evidence_rounds: int = 2
    max_repair_count: int = 1
    llm_calls_used: int = 0
    tool_calls_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    repair_count: int = 0


class AgentRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID
    asset_id: UUID
    research_run_id: UUID | None = None
    report_id: UUID | None = None
    provider_profile_id: UUID | None = None
    task_type: Literal["single_asset_risk_research"] = "single_asset_risk_research"
    task_text: str = Field(min_length=1, max_length=4000)
    user_preference: Literal["conservative", "growth", "short_term", "fund"] = "conservative"
    as_of: datetime
    state: AgentRunState = AgentRunState.CREATED
    current_node: str | None = None
    correlation_id: str
    verdict: Literal["pass", "warn", "hold", "block"] | None = None
    abstain_reason: str | None = None
    budget: AgentBudget = Field(default_factory=AgentBudget)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AgentEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent_run_id: UUID
    sequence: int
    event_type: str
    node_name: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AgentToolCall(BaseModel):
    """Auditable record of one server-side, read-only tool execution."""

    id: UUID
    agent_run_id: UUID
    node_name: str
    tool_id: str
    input_hash: str
    output_hash: str | None = None
    state: Literal["completed", "failed"]
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


class TaskClassification(BaseModel):
    task_type: Literal["single_asset_risk_research"]
    research_scope: Literal["asset"] = "asset"
    horizon: Literal["20d"] = "20d"
    user_preference: Literal["conservative", "growth", "short_term", "fund"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class AgentPlan(BaseModel):
    template_id: Literal["single-asset-risk-v1"] = "single-asset-risk-v1"
    tool_ids: list[str]
    observation_focus: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)


class CounterEvidenceQuery(BaseModel):
    query_terms: list[str] = Field(max_length=8)
    challenged_claim: str
    evidence_ids: list[UUID] = Field(default_factory=list)


class CitationAudit(BaseModel):
    supported: bool
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_counter_view: bool = False
    evidence_ids: list[UUID] = Field(default_factory=list)


class ReportNarrative(BaseModel):
    summary: str
    supporting_view: str
    contrary_view: str
    observation_conditions: list[str]
    evidence_ids: list[UUID]
    contains_trade_instruction: bool = False


class ProviderProfile(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID
    name: str = Field(min_length=1, max_length=128)
    protocol: Literal["openai_compatible", "anthropic_messages", "ollama", "mock"]
    endpoint: str | None = None
    model: str = Field(min_length=1, max_length=256)
    credential_ref: str | None = None
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    context_limit: int = Field(default=32_000, ge=1_000, le=1_000_000)
    fallback_profile_id: UUID | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_endpoint_policy(self) -> "ProviderProfile":
        if self.protocol == "mock":
            return self
        if not self.endpoint:
            raise ValueError("Non-mock provider requires an endpoint")
        parsed = urlparse(self.endpoint)
        if parsed.username or parsed.password:
            raise ValueError("Provider endpoint must not contain credentials")
        host = (parsed.hostname or "").lower()
        if self.protocol == "ollama":
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Ollama endpoint must use HTTP or HTTPS")
            if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Plain HTTP Ollama endpoint is restricted to localhost")
            return self
        if parsed.scheme != "https" or not host:
            raise ValueError("Remote LLM provider endpoint must use HTTPS")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return self
        if address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("Remote provider endpoint cannot use a private IP address")
        return self
