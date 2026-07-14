from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "ai-test-officer" / "docs" / "openapi.json"
OUTPUT = ROOT / "src" / "investment_research" / "service" / "test_officer_generated.py"


def main() -> None:
    document = json.loads(OPENAPI.read_text(encoding="utf-8"))
    version = document["info"]["version"]
    OUTPUT.write_text(
        f'''# Generated from ai-test-officer/docs/openapi.json; do not edit manually.\nfrom typing import Any, Literal\nfrom pydantic import BaseModel, ConfigDict, Field\n\nAPI_VERSION = "{version}"\n\nclass CreateRunInput(BaseModel):\n    model_config = ConfigDict(extra="forbid")\n    appUrl: str | None = None\n    scenarioId: str | None = None\n    requirement: str | None = None\n    diff: str | None = None\n    executionMode: Literal["oci", "trusted-local"] = "oci"\n    capabilities: list[Literal["browser", "desktop"]] = Field(default_factory=lambda: ["browser"])\n    permissionProfile: dict[str, bool] = Field(default_factory=dict)\n\nclass CreateRunRequest(BaseModel):\n    model_config = ConfigDict(extra="forbid")\n    organizationId: str = "local"\n    projectId: str | None = None\n    actor: str = "api-user"\n    idempotencyKey: str\n    input: CreateRunInput\n\nclass RunProjection(BaseModel):\n    model_config = ConfigDict(extra="allow")\n    id: str\n    state: str\n    version: int\n    gateStatus: Literal["pass", "fail", "blocked", "needs-human-review"] | None = None\n    machineGate: dict[str, Any] | None = None\n    judgeRecommendation: dict[str, Any] | None = None\n    humanDecision: dict[str, Any] | None = None\n''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
