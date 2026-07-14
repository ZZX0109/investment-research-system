from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import ValidationError

from investment_research.service.test_officer_models import TestOfficerMissionPreviewRequest
from investment_research.service.test_officer_models import TestOfficerMissionPreviewResponse


class MissionPreviewError(RuntimeError):
    pass


def open_api_request(request: Request, timeout: float):
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


class MissionPreviewService:
    def __init__(
        self,
        project_root: Path | None = None,
        *,
        api_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self.project_root = (project_root or get_project_root()).resolve()
        self.api_url = (api_url or os.getenv("AI_TEST_OFFICER_URL", "http://127.0.0.1:4317")).rstrip("/")
        self.api_token = api_token or os.getenv("AI_TEST_OFFICER_TOKEN", "dev-local-token")
        self.timeout_seconds = timeout_seconds

    def preview_mission(
        self,
        payload: TestOfficerMissionPreviewRequest,
    ) -> TestOfficerMissionPreviewResponse:
        request = Request(
            f"{self.api_url}/v1/mission-preview",
            data=json.dumps(payload.to_onboarding_payload()).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with open_api_request(request, self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
            return TestOfficerMissionPreviewResponse.model_validate(response_payload)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MissionPreviewError(f"AI Test Officer API rejected mission preview ({exc.code}): {detail}") from exc
        except URLError as exc:
            raise MissionPreviewError(f"AI Test Officer API is unavailable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise MissionPreviewError("Mission preview returned invalid JSON") from exc
        except ValidationError as exc:
            raise MissionPreviewError("Mission preview returned an invalid schema") from exc
