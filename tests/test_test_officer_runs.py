from __future__ import annotations

import json

from investment_research.service.test_officer_models import TestOfficerRunRequest as TORunRequest
from investment_research.service.test_officer_runs import MissionRunService


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *args):  # noqa: ANN002, ANN204
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_run_service_calls_versioned_run_api(monkeypatch) -> None:
    captured: list[dict[str, object]] = []
    responses = iter([
        {"run": {"id": "run_real-project", "state": "awaiting-plan-approval", "version": 2}},
        {"run": {"id": "run_real-project", "state": "awaiting-permission", "version": 3}},
        {"run": {"id": "run_real-project", "state": "completed", "version": 8, "gateStatus": "pass"}},
        {"report": {"id": "result_real-project", "gateStatus": "pass", "finalStatus": "pass", "artifactsV2": []}},
    ])

    def fake_open_api_request(request, timeout):  # noqa: ANN001
        captured.append({"url": request.full_url, "authorization": request.headers["Authorization"], "payload": json.loads(request.data) if request.data else None, "timeout": timeout})
        return FakeResponse(next(responses))

    monkeypatch.setattr("investment_research.service.test_officer_runs.open_api_request", fake_open_api_request)
    service = MissionRunService(api_url="http://test-officer.internal", api_token="secret")
    response = service.create_run(
        TORunRequest.model_validate(
            {
                "projectName": "Customer Portal QA",
                "targetAppName": "Customer Portal",
                "baseUrl": "https://portal.example.test",
                "businessObjective": "Verify admins can sign in and create a customer.",
                "mode": "plan-assisted",
                "keyPages": ["/login"],
                "executor": "playwright",
                "headless": False,
                "trace": True,
                "recordVideo": True,
                "requirementDocs": ["docs/requirements/login.md"],
                "gitDiffs": ["patches/pr-42.diff"],
                "requirementText": "Admins must be able to sign in.",
            }
        )
    )

    assert [item["url"] for item in captured] == [
        "http://test-officer.internal/v1/runs",
        "http://test-officer.internal/v1/runs/run_real-project/plan-approval",
        "http://test-officer.internal/v1/runs/run_real-project/permissions",
        "http://test-officer.internal/v1/runs/run_real-project/report",
    ]
    assert all(item["authorization"] == "Bearer secret" for item in captured)
    api_payload = captured[0]["payload"]
    assert api_payload["input"]["appUrl"] == "https://portal.example.test"
    assert api_payload["input"]["requirement"] == "Admins must be able to sign in."
    assert response.runId == "run_real-project"
    assert response.executor == "playwright"
    assert response.reviewStatus == "pass"
