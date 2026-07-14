# Generated from ai-test-officer/docs/openapi.json; do not edit manually.
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "1.0.0"

class CreateRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appUrl: str | None = None
    scenarioId: str | None = None
    requirement: str | None = None
    diff: str | None = None
    plannerMode: Literal["deterministic", "llm"] = "deterministic"
    judgeMode: Literal["deterministic", "llm-assisted"] = "deterministic"
    modelProfileId: str | None = None
    experimentId: str | None = None
    repetition: int | None = None
    promptVersion: str = "plan-v1"
    faultProfile: Literal["wrong-status", "api-503", "label-rename", "permission-bypass", "drop-trace", "ambiguous-oracle"] | None = None
    executionMode: Literal["oci", "trusted-local"] = "oci"
    capabilities: list[Literal["browser", "desktop"]] = Field(default_factory=lambda: ["browser"])
    permissionProfile: dict[str, bool] = Field(default_factory=dict)

class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organizationId: str = "local"
    projectId: str | None = None
    actor: str = "api-user"
    idempotencyKey: str
    input: CreateRunInput

class RunProjection(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    state: str
    version: int
    gateStatus: Literal["pass", "fail", "blocked", "needs-human-review"] | None = None
    machineGate: dict[str, Any] | None = None
    judgeRecommendation: dict[str, Any] | None = None
    humanDecision: dict[str, Any] | None = None
    planProvenance: dict[str, Any] | None = None
    plannerCall: dict[str, Any] | None = None
