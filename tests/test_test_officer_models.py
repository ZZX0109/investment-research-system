from __future__ import annotations

import pytest
from pydantic import ValidationError

from investment_research.service.test_officer_models import TestOfficerMissionPreviewRequest as TOPreviewRequest
from investment_research.service.test_officer_models import TestOfficerRunRequest as TORunRequest


def test_mission_preview_request_builds_normalized_onboarding_payload() -> None:
    request = TOPreviewRequest.model_validate(
        {
            "projectName": "Customer Portal QA",
            "targetAppName": "Customer Portal",
            "baseUrl": "https://portal.example.test",
            "accountRef": "",
            "businessObjective": "Verify admins can sign in and create a customer.",
            "mode": "plan-assisted",
            "keyPages": ["/login", "", "/customers/new"],
            "selectorHints": ["data-testid=login-submit", ""],
            "scenarioRequests": [
                {"family": "auth-login", "pagePath": "/login", "enabled": True},
                {"family": "customer-create", "pagePath": "/customers/new", "enabled": False},
            ],
        }
    )

    assert request.to_onboarding_payload() == {
        "project": {"name": "Customer Portal QA"},
        "targetApp": {"name": "Customer Portal", "defaultMode": "plan-assisted"},
        "baseUrl": "https://portal.example.test",
        "keyPages": ["/login", "/customers/new"],
        "businessObjective": "Verify admins can sign in and create a customer.",
        "selectorHints": ["data-testid=login-submit"],
        "scenarioRequests": [{"family": "auth-login", "pagePath": "/login"}],
    }


def test_mission_preview_request_carries_real_project_runtime_contract() -> None:
    request = TOPreviewRequest.model_validate(
        {
            "projectName": "Customer Portal QA",
            "targetAppName": "Customer Portal",
            "baseUrl": "https://portal.example.test",
            "accountRef": "vault://accounts/customer-admin",
            "authStrategy": "session",
            "loginPagePath": "/login",
            "environments": ["staging"],
            "runtime": {
                "start": {
                    "command": "pnpm",
                    "args": ["preview"],
                    "cwd": "/workspace/customer-portal",
                    "env": [
                        {"name": "FEATURE_FLAG_CHECKOUT", "value": "enabled", "scope": "launch"}
                    ],
                    "timeoutMs": 60_000,
                },
                "healthCheck": {
                    "url": "https://portal.example.test/healthz",
                    "expectedStatus": [200, 204],
                    "retries": 5,
                    "intervalMs": 250,
                    "timeoutMs": 10_000,
                },
                "routes": [
                    {"id": "login", "path": "/login", "purpose": "login", "authenticated": False},
                    {"id": "customers", "path": "/customers", "purpose": "workflow", "authenticated": True},
                ],
                "testAccounts": [
                    {
                        "id": "admin",
                        "role": "admin",
                        "credentialRef": "vault://accounts/customer-admin",
                        "username": "admin@example.test",
                    }
                ],
                "env": [
                    {"name": "API_TOKEN", "secretRef": "vault://secrets/api-token", "scope": "test"}
                ],
                "cleanup": {
                    "command": "pnpm",
                    "args": ["run", "test:cleanup"],
                    "timeoutMs": 30_000,
                },
            },
            "businessObjective": "Verify admins can sign in and create a customer.",
            "mode": "plan-assisted",
            "keyPages": ["/login", "/customers"],
            "selectorHints": ["data-testid=login-submit"],
            "scenarioRequests": [
                {"family": "auth-login", "pagePath": "/login", "enabled": True}
            ],
        }
    )

    payload = request.to_onboarding_payload()

    assert payload["auth"] == {
        "strategy": "session",
        "accountRef": "vault://accounts/customer-admin",
        "loginPagePath": "/login",
    }
    assert payload["targetApp"] == {
        "name": "Customer Portal",
        "defaultMode": "plan-assisted",
        "environments": ["staging"],
    }
    assert payload["runtime"] == {
        "start": {
            "command": "pnpm",
            "args": ["preview"],
            "cwd": "/workspace/customer-portal",
            "env": [
                {
                    "name": "FEATURE_FLAG_CHECKOUT",
                    "value": "enabled",
                    "required": False,
                    "scope": "launch",
                }
            ],
            "timeoutMs": 60_000,
        },
        "healthCheck": {
            "url": "https://portal.example.test/healthz",
            "expectedStatus": [200, 204],
            "timeoutMs": 10_000,
            "intervalMs": 250,
            "retries": 5,
        },
        "routes": [
            {"id": "login", "path": "/login", "purpose": "login", "authenticated": False},
            {"id": "customers", "path": "/customers", "purpose": "workflow", "authenticated": True},
        ],
        "testAccounts": [
            {
                "id": "admin",
                "role": "admin",
                "credentialRef": "vault://accounts/customer-admin",
                "username": "admin@example.test",
            }
        ],
        "env": [
            {
                "name": "API_TOKEN",
                "secretRef": "vault://secrets/api-token",
                "required": False,
                "scope": "test",
            }
        ],
        "cleanup": {
            "command": "pnpm",
            "args": ["run", "test:cleanup"],
            "env": [],
            "timeoutMs": 30_000,
        },
    }


def test_mission_preview_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TOPreviewRequest.model_validate(
            {
                "projectName": "Customer Portal QA",
                "targetAppName": "Customer Portal",
                "baseUrl": "https://portal.example.test",
                "businessObjective": "Verify admins can sign in and create a customer.",
                "mode": "plan-assisted",
                "unexpected": "nope",
            }
        )


def test_run_request_builds_source_connector_cli_args() -> None:
    request = TORunRequest.model_validate(
        {
            "projectName": "Customer Portal QA",
            "targetAppName": "Customer Portal",
            "baseUrl": "https://portal.example.test",
            "businessObjective": "Verify admins can sign in and create a customer.",
            "mode": "plan-assisted",
            "keyPages": ["/login"],
            "workspaceRoot": "/workspace/customer-portal",
            "prUrl": "https://github.com/acme/customer-portal/pull/42",
            "requirementDocs": ["docs/requirements/login.md", ""],
            "bugTickets": ["docs/bugs/BUG-123.md"],
            "apiDocs": ["docs/openapi.json"],
            "gitDiffs": ["patches/pr-42.diff"],
            "githubIssues": ["https://github.com/acme/customer-portal/issues/43"],
            "jiraIssues": ["https://company.atlassian.net/browse/QA-123"],
            "openApiUrls": ["https://api.example.test/openapi.json"],
            "requirementText": "Admins must be able to sign in.",
        }
    )

    assert request.source_cli_args() == [
        "--workspace-root",
        "/workspace/customer-portal",
        "--pr-url",
        "https://github.com/acme/customer-portal/pull/42",
        "--requirement-text",
        "Admins must be able to sign in.",
        "--requirement-doc",
        "docs/requirements/login.md",
        "--bug-ticket",
        "docs/bugs/BUG-123.md",
        "--api-doc",
        "docs/openapi.json",
        "--git-diff",
        "patches/pr-42.diff",
        "--github-issue",
        "https://github.com/acme/customer-portal/issues/43",
        "--jira-issue",
        "https://company.atlassian.net/browse/QA-123",
        "--openapi-url",
        "https://api.example.test/openapi.json",
    ]
