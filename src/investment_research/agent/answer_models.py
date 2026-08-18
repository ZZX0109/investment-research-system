"""Shared answer/evidence pydantic models for the long-term investment AI assistant.

This module breaks the circular dependency that previously existed between
``plain_answer`` (which held the shared models), ``reasoning_chain`` (which
imported ``PlainReadingObservation`` from plain_answer) and ``evidence_merge``
(which imported ``EvidenceItem``/``PlainSource`` from plain_answer, while
plain_answer inline-imported back from both).

These models are deliberately kept separate from ``agent/models.py`` (which
holds the agent runtime models such as ``AgentRun``) so the two concerns never
collide.  The builder classes (``PlainAnswerBuilder``, ``EvidenceMerger``,
``ReasoningChainBuilder``) stay in their own modules and import these models at
module top-level — no function-level imports are needed because there is no
import cycle.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Evidence classification
# ---------------------------------------------------------------------------

EvidenceClass = Literal["confirmed_fact", "explanation", "conflict", "missing"]


class PlainSource(BaseModel):
    """A citable material used by the answer.  Always carries a link."""

    title: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    published_at: str | None = None
    kind: Literal["announcement", "knowledge", "news", "calculation", "model"] = "knowledge"
    citation_id: str | None = None
    note: str | None = None


class EvidenceItem(BaseModel):
    classification: EvidenceClass
    text: str = Field(min_length=1)
    sources: list[PlainSource] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Long-term model observation + conflict arbitration
# ---------------------------------------------------------------------------


class PlainReadingObservation(BaseModel):
    """One long-term model observation translated for a retail user."""

    label: str
    horizon: str
    tendency: str
    interpretation: str
    available: bool
    data_as_of: str | None = None


class ConflictArbitration(BaseModel):
    """A resolved (or unresolved) disagreement between sources.

    The policy is authority_level > recency > corroboration; when two sources
    tie on authority and recency and neither is corroborated, the arbitration
    stays ``unresolved`` and BOTH views are retained — the merger never
    silently picks one side.
    """

    topic: str
    resolved_stance: str  # "knowledge", "web", "unresolved"
    reasoning: str
    authority_basis: str
    recency_basis: str
    corroboration_basis: str
    unresolved: bool
    sources: list[str] = Field(default_factory=list)


class EvidenceMergeResult(BaseModel):
    evidence: list[EvidenceItem]
    sources: list[PlainSource]
    conflict_present: bool
    missing_present: bool
    confirmed_count: int
    explanation_count: int
    arbitrations: list[ConflictArbitration] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Causal reasoning + portfolio note + plain answer
# ---------------------------------------------------------------------------


class CausalObservation(BaseModel):
    observation: str
    evidence_refs: list[str] = Field(default_factory=list)
    invalidation_refs: list[str] = Field(default_factory=list)
    confidence_note: str = "研究展示推理，非验证结论，不构成操作建议。"


class PlainPortfolioNote(BaseModel):
    concentration: str
    possible_impact: str
    missing_info: str
    is_example_scenario: bool = True


class PlainAnswer(BaseModel):
    """The five-section structured answer shown on the homepage."""

    schema_version: str = "plain-answer-v1"
    business_condition: str
    long_term_changes: str
    possible_risks: str
    missing_evidence: str
    sources_summary: str
    result_status: Literal["research_observation", "insufficient_evidence", "conflict_present"]
    data_as_of: str | None = None
    next_observation_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    long_term_observations: list[PlainReadingObservation] = Field(default_factory=list)
    fundamental_dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    sources: list[PlainSource] = Field(default_factory=list)
    portfolio_note: PlainPortfolioNote | None = None
    tools_used: list[str] = Field(default_factory=list)
    compliance_allowed: bool = True
    generated_by: Literal["llm", "deterministic_fallback"] = "deterministic_fallback"
    arbitrations: list[dict[str, object]] = Field(default_factory=list)
    causal_observations: list[dict[str, object]] = Field(default_factory=list)
