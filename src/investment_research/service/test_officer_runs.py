from __future__ import annotations

import os
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import ValidationError

from investment_research.service.test_officer_models import TestOfficerRunRequest
from investment_research.service.test_officer_models import TestOfficerRunResponse
from investment_research.service.test_officer_preview import get_project_root


class MissionRunError(RuntimeError):
    pass


def open_api_request(request: Request, timeout: float):
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)


class MissionRunService:
    def __init__(
        self,
        *,
        project_root: Path | None = None,
        runs_root: Path | None = None,
        api_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: float = 1_300,
    ) -> None:
        self.project_root = (project_root or get_project_root()).resolve()
        self.runs_root = runs_root
        self.api_url = (api_url or os.getenv("AI_TEST_OFFICER_URL", "http://127.0.0.1:4317")).rstrip("/")
        self.api_token = api_token or os.getenv("AI_TEST_OFFICER_TOKEN", "dev-local-token")
        self.timeout_seconds = timeout_seconds

    def create_run(self, payload: TestOfficerRunRequest) -> TestOfficerRunResponse:
        if payload.executor == "memory" and os.getenv("NODE_ENV") != "test":
            raise MissionRunError("The production API does not accept the simulated memory executor")
        idempotency_key = str(uuid.uuid4())
        api_payload = {
            "organizationId": os.getenv("AI_TEST_OFFICER_ORGANIZATION", "local"),
            "actor": "research-platform-api",
            "idempotencyKey": idempotency_key,
            "input": {
                "appUrl": payload.baseUrl,
                "scenarioId": payload.scenarioRequests[0].family if payload.scenarioRequests else None,
                "requirement": payload.requirementText or payload.businessObjective,
                "permissionProfile": {
                    "observe": True,
                    "browserControl": True,
                    "workspaceControl": False,
                    "ideTerminalControl": False,
                    "systemControl": False,
                },
                "executionMode": "oci",
                "capabilities": ["browser"],
            },
        }

        def call(route: str, body: dict[str, object] | None = None, method: str = "GET") -> dict[str, object]:
            request = Request(
                f"{self.api_url}{route}",
                data=json.dumps(body).encode("utf-8") if body is not None else None,
                headers={"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"},
                method=method,
            )
            with open_api_request(request, self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        try:
            run = call("/v1/runs", api_payload, "POST")["run"]
            run_id = str(run["id"])
            run = call(f"/v1/runs/{run_id}/plan-approval", {"expectedVersion": run["version"], "actor": "research-platform-api", "idempotencyKey": f"{idempotency_key}:plan"}, "POST")["run"]
            run = call(f"/v1/runs/{run_id}/permissions", {"expectedVersion": run["version"], "actor": "research-platform-api", "idempotencyKey": f"{idempotency_key}:permission"}, "POST")["run"]
            deadline = time.monotonic() + self.timeout_seconds
            terminal = {"completed", "failed", "blocked", "cancelled", "awaiting-human-review"}
            while str(run["state"]) not in terminal:
                if time.monotonic() >= deadline:
                    raise MissionRunError("Run did not reach a terminal state before timeout")
                time.sleep(0.75)
                run = call(f"/v1/runs/{run_id}")["run"]
            summary = call(f"/v1/runs/{run_id}/report")["report"]
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MissionRunError(f"AI Test Officer API rejected run ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise MissionRunError(f"AI Test Officer API is unavailable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise MissionRunError("Run creation returned invalid JSON") from exc

        run_id = run.get("id") or summary.get("runId") or summary.get("id")
        if not isinstance(run_id, str) or not run_id:
            raise MissionRunError("Run creation did not return a runId")
        gate_status = str(run.get("gateStatus") or summary.get("gateStatus", "needs-human-review"))
        status = "passed" if gate_status == "pass" else "failed" if gate_status == "fail" else gate_status
        try:
            return TestOfficerRunResponse.model_validate(
                {
                    "runId": run_id,
                    "status": status,
                    "reviewStatus": gate_status,
                    "executor": "playwright",
                    "headless": payload.headless,
                    "trace": payload.trace,
                    "recordVideo": payload.recordVideo,
                    "manifest": summary,
                    "gate": None,
                }
            )
        except ValidationError as exc:
            raise MissionRunError("Run creation returned an invalid schema") from exc
