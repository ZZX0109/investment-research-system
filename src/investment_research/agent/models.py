"""Evidence-bound investment research agent runtime models.

These are the persistence/runtime pydantic models for the agent execution
engine: ``AgentRun``, ``AgentRunState``, ``AgentBudget``, ``AgentEvent``,
``AgentToolCall`` and ``ProviderProfile``.  They are stored in the agent
runtime SQLite tables (migration 0008) and round-tripped through
``AgentRuntimeRepository``.

The answer/evidence presentation models (``PlainAnswer``, ``EvidenceItem``...)
live in ``agent/answer_models.py`` to keep the two concerns separate.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.base import utc_now


class AgentRunState(str, Enum):
    """Lifecycle states for an evidence-bound agent run.

    ``str, Enum`` so the value round-trips through the SQLite ``state`` column:
    ``add_run`` writes ``run.state.value`` and ``_run_from_row`` reconstructs
    with ``AgentRunState(value)``.
    """

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    ABSTAINED = "abstained"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REPAIRING = "repairing"


class AgentBudget(BaseModel):
    """Token/tool budget counters and hard limits for a single run.

    Only the five ``*_used`` / ``repair_count`` counters are persisted in the
    ``agent_runs`` columns; the ``max_*`` limits are configuration defaults
    enforced in-memory by the orchestrator (service.py guards each LLM/tool
    call against them before it fires).
    """

    llm_calls_used: int = 0
    tool_calls_used: int = 0
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    repair_count: int = 0
    max_llm_calls: int = 12
    max_tool_calls: int = 24
    max_input_tokens: int = 24000
    max_output_tokens: int = 4000
    max_evidence: int = 6
    max_evidence_rounds: int = 2
    max_repair_count: int = 1


class AgentRun(BaseModel):
    """A single evidence-bound research run for one asset and one task."""

    id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID
    asset_id: UUID
    research_run_id: UUID | None = None
    report_id: UUID | None = None
    provider_profile_id: UUID | None = None
    task_type: str = "research"
    task_text: str
    user_preference: str = "conservative"
    as_of: datetime
    state: AgentRunState = AgentRunState.CREATED
    current_node: str | None = None
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    verdict: str | None = None
    abstain_reason: str | None = None
    budget: AgentBudget = Field(default_factory=AgentBudget)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AgentEvent(BaseModel):
    """An append-only lifecycle event for an agent run."""

    id: UUID = Field(default_factory=uuid4)
    agent_run_id: UUID
    sequence: int = 0
    event_type: str
    node_name: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AgentToolCall(BaseModel):
    """A recorded function/tool call made during an agent run."""

    id: UUID = Field(default_factory=uuid4)
    agent_run_id: UUID
    node_name: str
    tool_id: str
    input_hash: str
    output_hash: str | None = None
    state: str
    error: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class ProviderProfile(BaseModel):
    """A user-owned LLM provider profile (endpoint + model + credentials ref).

    A static (construction-time) check requires HTTPS for the public remote
    protocols (``openai_compatible`` / ``anthropic_messages`` /
    ``gemini_generate_content``); ``ollama`` and ``mock`` are exempt because
    they legitimately run on a local plain-http endpoint.  The deeper
    private-IP / non-resolvable-hostname check lives on
    ``HTTPStructuredProvider._validate_runtime_endpoint`` and raises
    ``LLMProviderError`` at invoke time.
    """

    id: UUID = Field(default_factory=uuid4)
    owner_user_id: UUID
    name: str
    protocol: str
    endpoint: str | None = None
    model: str
    credential_ref: str | None = None
    timeout_seconds: float = 20.0
    context_limit: int = 4096
    fallback_profile_id: UUID | None = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _require_https_for_remote_protocols(self) -> "ProviderProfile":
        endpoint = self.endpoint
        if not endpoint or self.protocol in {"ollama", "mock"}:
            return self
        if not endpoint.startswith("https://"):
            raise ValueError(
                f"provider endpoint must use HTTPS for protocol {self.protocol!r}; got {endpoint!r}"
            )
        return self


class AgentPlan(BaseModel):
    """The ordered tool plan for an agent run (LLM-selected or default)."""

    tool_ids: list[str] = Field(default_factory=list)


class TaskClassification(BaseModel):
    """The LLM-or-default task classification for an agent run."""

    task_type: str = "single_asset_risk_research"
    user_preference: str = "conservative"


class CounterEvidenceQuery(BaseModel):
    """The counter-evidence search query produced at the counter-evidence node."""

    query_terms: list[str] = Field(default_factory=list)
    challenged_claim: str = ""
    evidence_ids: list = Field(default_factory=list)


class CitationAudit(BaseModel):
    """Result of checking that every narrative claim maps to cited evidence."""

    supported: bool = False
    unsupported_claims: list[str] = Field(default_factory=list)
    evidence_ids: list = Field(default_factory=list)


class ReportNarrative(BaseModel):
    """The structured narrative produced at report generation."""

    summary: str = ""
    supporting_view: str = ""
    contrary_view: str = ""
    observation_conditions: list[str] = Field(default_factory=list)
    applicable_horizon: str = ""
    current_assessment: str = ""
    reasoning: list[str] = Field(default_factory=list)
    major_risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    data_as_of: str | None = None
    evidence_ids: list = Field(default_factory=list)
    contains_trade_instruction: bool = False


__all__ = [
    "AgentRunState",
    "AgentBudget",
    "AgentRun",
    "AgentEvent",
    "AgentToolCall",
    "ProviderProfile",
    "AgentPlan",
    "TaskClassification",
    "CounterEvidenceQuery",
    "CitationAudit",
    "ReportNarrative",
]
