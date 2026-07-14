from __future__ import annotations

import json
import sqlite3
import hashlib
import zipfile
from base64 import b64encode
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from investment_research.api.run_bundle_routes import (
    get_run_bundle_service,
    get_test_officer_preview_service,
    get_test_officer_run_service,
)
from investment_research.api.artifact_security import (
    ArtifactAccessSettings,
    build_project_access_token,
    build_run_access_token,
    build_signed_artifact_url,
    get_artifact_access_settings,
    require_artifact_access,
    require_report_access,
    require_run_access,
    should_sign_report_url,
    validate_agent_api_settings,
    validate_artifact_access_settings,
)
from investment_research.main import app
from investment_research.service.run_bundle_models import RunBundleAuditRunSummary
from investment_research.service.run_bundle_models import RunBundleAuditStatus
from investment_research.service.run_bundle_models import RunBundleComparisonReport
from investment_research.service.run_bundle_models import RunBundleHistoryIndex
from investment_research.service.run_bundle_models import RunBundleManifest
from investment_research.service.run_bundle_models import RunBundleManifestJudgeReport
from investment_research.service.run_bundle_models import RunBundleMissionPackage
from investment_research.service.run_bundle_models import RunBundleOnboardingProtocol
from investment_research.service.run_bundle_models import RunBundleRegistryManifest
from investment_research.service.run_bundle_models import RunBundleRegistryFailureAttribution
from investment_research.service.run_bundle_models import RunBundleRegistryResourceRecord
from investment_research.service.run_bundle_models import RunBundleRegistrySourceContext
from investment_research.service.run_bundle_artifact_service import RunBundleArtifactService
from investment_research.service.run_bundle_audit_service import RunBundleAuditService
from investment_research.service.run_bundle_manifest_service import RunBundleManifestService
from investment_research.service.run_bundle_registry_service import RunBundleRegistryService
from investment_research.service.run_bundle_retention_service import RunBundleRetentionService
from investment_research.service.run_bundles import RunBundleService
from investment_research.service.test_officer_models import TestOfficerMissionPreviewRequest as TOPreviewRequest
from investment_research.service.test_officer_models import TestOfficerMissionPreviewResponse as TOPreviewResponse
from investment_research.service.test_officer_models import TestOfficerRunRequest as TORunRequest
from investment_research.service.test_officer_models import TestOfficerRunResponse as TORunResponse
from investment_research.service.test_officer_preview import MissionPreviewService
from investment_research.service.test_officer_runs import MissionRunService


def write_run_bundle_fixture(tmp_path) -> None:
    run_dir = tmp_path / "run_demo-001"
    artifacts_dir = run_dir / "artifacts"
    evidence_dir = run_dir / "evidence"
    reports_dir = run_dir / "reports"
    registry_dir = run_dir / "registry"
    artifacts_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    registry_dir.mkdir(parents=True)

    history = {
        "schemaVersion": "1.0",
        "generatedAt": "2026-07-03T10:00:00Z",
        "runs": [
            {
                "runId": "run_demo-001",
                "missionId": "mission_demo",
                "missionName": "Demo Mission",
                "targetAppId": "targetapp_demo",
                "targetAppName": "Demo App",
                "status": "failed",
                "reviewStatus": "fail",
                "startedAt": "2026-07-03T10:00:00Z",
                "finishedAt": "2026-07-03T10:00:10Z",
                "manifestPath": str(run_dir / "manifest.json"),
                "findingCount": 1,
                "failedStepCount": 1,
                "artifactCount": 2,
            }
        ],
    }
    manifest = {
        "project": {"id": "project_demo", "name": "Demo", "status": "active"},
        "targetApp": {
            "id": "targetapp_demo",
            "name": "Demo App",
            "baseUrl": "https://example.test",
            "status": "reachable",
        },
        "mission": {
            "id": "mission_demo",
            "name": "Demo Mission",
            "objective": "Check demo path",
            "mode": "scripted",
            "status": "ready",
        },
        "scenarios": [],
        "run": {
            "id": "run_demo-001",
            "mode": "scripted",
            "status": "failed",
            "reviewStatus": "fail",
            "bundle": {
                "rootDir": str(run_dir),
                "manifestPath": str(run_dir / "manifest.json"),
                "artifactsDir": str(artifacts_dir),
                "evidenceDir": str(evidence_dir),
                "reportsDir": str(reports_dir),
                "accessPolicy": {
                    "profile": "deployment",
                    "tokenPolicy": {
                        "agentToken": "configured-secret",
                        "artifactToken": "configured-secret",
                        "runScopedTokens": True,
                        "signedUrlTtlSeconds": 900,
                    },
                    "reportAccess": {
                        "html": "signed-url",
                        "json": "agent-token",
                        "junit": "agent-token",
                        "sensitiveReportsRequireRunScope": True,
                    },
                    "credentialPolicy": {
                        "encryptedCredentialStore": True,
                        "secretRefsOnlyInManifests": True,
                        "credentialPreviewOnly": True,
                    },
                    "redaction": {
                        "redactArtifacts": True,
                        "redactReports": True,
                        "redactSourceContexts": True,
                        "redactScreenshots": True,
                    },
                },
                "registry": {
                    "rootDir": str(registry_dir),
                    "resourceManifestPath": str(registry_dir / "resources.json"),
                    "onboardingProtocolPath": str(registry_dir / "onboarding.json"),
                    "missionPackagePath": str(registry_dir / "mission-package.json"),
                    "selectorMapsPath": str(registry_dir / "selector-maps.json"),
                    "fixturesPath": str(registry_dir / "fixtures.json"),
                    "scenariosPath": str(registry_dir / "scenarios.json"),
                    "oraclesPath": str(registry_dir / "oracles.json"),
                    "artifactsPath": str(registry_dir / "artifacts.json"),
                    "evidencePath": str(registry_dir / "evidence.json"),
                    "judgeReportPath": str(registry_dir / "judge-report.json"),
                    "sourceContextsPath": str(registry_dir / "source-contexts.json"),
                    "failureAttributionsPath": str(registry_dir / "failure-attributions.json"),
                    "retentionCleanupPlanPath": str(registry_dir / "retention-cleanup-plan.json"),
                },
            },
        },
        "steps": [],
        "evidence": [],
        "artifacts": [],
        "findings": [],
        "judgeReport": {
            "id": "judge_demo",
            "result": "fail",
            "narrative": "Demo failed.",
            "machineSummary": {
                "decision": "fail",
                "confidence": 0.82,
                "flaky": False,
                "blocked": False,
            },
        },
    }
    comparison = {
        "schemaVersion": "1.0",
        "baselineRunId": "run_demo-000",
        "currentRunId": "run_demo-001",
        "missionId": "mission_demo",
        "summary": {
            "statusChanged": True,
            "reviewChanged": True,
            "findingDelta": 1,
            "failedStepDelta": 1,
            "artifactDelta": 0,
        },
        "stepChanges": [],
        "findingChanges": {
            "added": ["Regression"],
            "resolved": [],
            "unchanged": [],
        },
        "artifactSignalChanges": {
            "added": ["console:Uncaught TypeError: cannot read checkout total"],
            "resolved": [],
            "unchanged": [],
        },
    }
    registry_manifest = {
        "schemaVersion": "1.0",
        "runId": "run_demo-001",
        "missionId": "mission_demo",
        "generatedAt": "2026-07-03T10:00:10Z",
        "entries": [
            {"kind": "onboarding-protocol", "path": str(registry_dir / "onboarding.json"), "recordCount": 1},
            {"kind": "mission-package", "path": str(registry_dir / "mission-package.json"), "recordCount": 1},
            {"kind": "selector-map-registry", "path": str(registry_dir / "selector-maps.json"), "recordCount": 1},
            {"kind": "fixture-registry", "path": str(registry_dir / "fixtures.json"), "recordCount": 1},
            {"kind": "scenario-registry", "path": str(registry_dir / "scenarios.json"), "recordCount": 1},
            {"kind": "oracle-registry", "path": str(registry_dir / "oracles.json"), "recordCount": 1},
            {"kind": "artifact-index", "path": str(registry_dir / "artifacts.json"), "recordCount": 0},
            {"kind": "evidence-index", "path": str(registry_dir / "evidence.json"), "recordCount": 0},
            {"kind": "judge-report", "path": str(registry_dir / "judge-report.json"), "recordCount": 1},
            {"kind": "source-context-registry", "path": str(registry_dir / "source-contexts.json"), "recordCount": 1},
            {"kind": "failure-attribution-registry", "path": str(registry_dir / "failure-attributions.json"), "recordCount": 1},
            {"kind": "retention-cleanup-plan", "path": str(registry_dir / "retention-cleanup-plan.json"), "recordCount": 2},
        ],
        "counts": {
            "onboardingProtocols": 1,
            "missionPackages": 1,
            "selectorMaps": 1,
            "fixtures": 1,
            "scenarios": 1,
            "oracles": 1,
            "artifacts": 0,
            "evidence": 0,
            "judgeReports": 1,
            "sourceContexts": 1,
            "failureAttributions": 1,
            "retentionPlans": 1,
        },
    }
    selector_maps = [
        {
            "id": "selectors.demo-app",
            "appId": "targetapp_demo",
            "entries": [{"id": "login-submit", "preferredStrategies": ["test-id"], "queries": ["data-testid=login-submit"]}],
        }
    ]
    fixtures = [{"id": "fixture_demo-login", "scenarioId": "scenario_demo-login", "kind": "account", "manifestRef": "vault://demo/admin"}]
    scenarios = [
        {
            "id": "scenario_demo-login",
            "type": "scenario",
            "schemaVersion": "1.0",
            "createdAt": "2026-07-03T10:00:00Z",
            "updatedAt": "2026-07-03T10:00:00Z",
            "metadata": {},
            "projectId": "project_demo",
            "targetAppId": "targetapp_demo",
            "status": "ready",
            "name": "Demo login",
            "goal": "Verify login works",
            "tags": ["auth-login"],
            "targetPageId": "login-page",
            "fixtureRefs": ["fixture_demo-login"],
            "selectorMapId": "selectors.demo-app",
            "steps": [{"id": "demo-open", "title": "Open login", "intent": "Open login page", "action": "navigate", "evidenceRequirements": ["screenshot"]}],
            "expectedFindings": [],
            "failureClasses": ["product-bug"],
            "evidenceRequirements": ["screenshot"],
        }
    ]
    oracles = [
        {
            "id": "oracle_demo-login",
            "type": "oracle",
            "schemaVersion": "1.0",
            "createdAt": "2026-07-03T10:00:00Z",
            "updatedAt": "2026-07-03T10:00:00Z",
            "metadata": {},
            "scenarioId": "scenario_demo-login",
            "status": "ready",
            "name": "Demo login oracle",
            "checks": [{"id": "login-ok", "name": "login ok", "kind": "state", "description": "Session established", "requiredEvidence": ["screenshot"]}],
            "passPolicy": "all-required",
        }
    ]
    onboarding = {
        "baseUrl": "https://example.test",
        "accountRef": "vault://demo/admin",
        "keyPages": ["/login"],
        "businessObjective": "Verify login works",
        "selectorHints": ["data-testid=login-submit"],
        "scenarioRequests": [{"family": "auth-login", "pagePath": "/login"}],
    }
    mission_package = {
        "project": {
            "id": "project_demo",
            "type": "project",
            "schemaVersion": "1.0",
            "createdAt": "2026-07-03T10:00:00Z",
            "updatedAt": "2026-07-03T10:00:00Z",
            "metadata": {},
            "status": "active",
            "name": "Demo",
            "targetAppIds": ["targetapp_demo"],
            "missionIds": ["mission_demo"],
        },
        "targetApp": {
            "id": "targetapp_demo",
            "type": "target-app",
            "schemaVersion": "1.0",
            "createdAt": "2026-07-03T10:00:00Z",
            "updatedAt": "2026-07-03T10:00:00Z",
            "metadata": {},
            "projectId": "project_demo",
            "status": "configured",
            "name": "Demo App",
            "baseUrl": "https://example.test",
            "auth": {"strategy": "session", "credentialRef": "vault://demo/admin"},
            "environments": ["default"],
            "pages": [{"id": "login-page", "name": "Login", "path": "/login", "selectors": selector_maps[0]["entries"]}],
        },
        "mission": {
            "id": "mission_demo",
            "type": "mission",
            "schemaVersion": "1.0",
            "createdAt": "2026-07-03T10:00:00Z",
            "updatedAt": "2026-07-03T10:00:00Z",
            "metadata": {},
            "projectId": "project_demo",
            "targetAppId": "targetapp_demo",
            "status": "ready",
            "mode": "scripted",
            "name": "Demo Mission",
            "objective": "Check demo path",
            "scenarioIds": ["scenario_demo-login"],
            "oracleIds": ["oracle_demo-login"],
            "accountRef": "vault://demo/admin",
            "selectorHintRefs": ["selectors.demo-app#login-submit"],
        },
        "scenarios": scenarios,
        "oracles": oracles,
        "counts": {"pages": 1, "selectorHints": 1, "scenarios": 1, "oracles": 1},
    }

    (tmp_path / "history.json").write_text(json.dumps(history), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (reports_dir / "comparison.json").write_text(json.dumps(comparison), encoding="utf-8")
    (reports_dir / "run-report.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    (reports_dir / "pr-annotation.md").write_text("## AI Test Officer Gate: FAIL", encoding="utf-8")
    (reports_dir / "pr-annotations.json").write_text(json.dumps([{
        "path": ".github/AI_TEST_OFFICER.md",
        "start_line": 1,
        "end_line": 1,
        "annotation_level": "failure",
        "message": "regression-detected",
        "title": "AI Test Officer gate failed",
    }]), encoding="utf-8")
    (reports_dir / "artifact-upload-manifest.json").write_text(json.dumps({
        "schemaVersion": "1.0",
        "runId": "run_demo-001",
        "githubActions": {"uploadPaths": [str(run_dir / "manifest.json")]},
    }), encoding="utf-8")
    (reports_dir / "gate.json").write_text(json.dumps({
        "schemaVersion": "1.0",
        "runId": "run_demo-001",
        "gate": {
            "passed": False,
            "exitCode": 2,
            "reasons": ["regression-detected"],
            "diagnostics": {
                "newFindings": ["Regression"],
                "newArtifactSignals": ["console:Uncaught TypeError"],
            },
        },
    }), encoding="utf-8")
    (reports_dir / "junit.xml").write_text("<testsuite></testsuite>", encoding="utf-8")
    (reports_dir / "report.md").write_text("# Demo report", encoding="utf-8")
    (reports_dir / "report.html").write_text("<html><body>demo</body></html>", encoding="utf-8")
    (artifacts_dir / "failure.log").write_text("failure details", encoding="utf-8")
    (registry_dir / "resources.json").write_text(json.dumps(registry_manifest), encoding="utf-8")
    (registry_dir / "onboarding.json").write_text(json.dumps(onboarding), encoding="utf-8")
    (registry_dir / "mission-package.json").write_text(json.dumps(mission_package), encoding="utf-8")
    (registry_dir / "selector-maps.json").write_text(json.dumps(selector_maps), encoding="utf-8")
    (registry_dir / "fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
    (registry_dir / "scenarios.json").write_text(json.dumps(scenarios), encoding="utf-8")
    (registry_dir / "oracles.json").write_text(json.dumps(oracles), encoding="utf-8")
    (registry_dir / "artifacts.json").write_text("[]", encoding="utf-8")
    (registry_dir / "evidence.json").write_text("[]", encoding="utf-8")
    (registry_dir / "judge-report.json").write_text(json.dumps(manifest["judgeReport"]), encoding="utf-8")
    (registry_dir / "source-contexts.json").write_text(
        json.dumps([
            {
                "schemaVersion": "1.0",
                "adapter": {
                    "id": "github-pr:demo/app#1",
                    "kind": "github-pr",
                    "label": "Demo PR",
                    "permissions": ["network-read"],
                    "usageScopes": ["planning", "failure-analysis", "judge"],
                    "sourceRef": "https://github.com/demo/app/pull/1",
                },
                "readState": "ready",
                "readAt": "2026-07-03T10:00:00Z",
                "payload": {"changedFiles": ["src/demo.ts"]},
                "metadata": {"byteLength": 12, "truncated": False},
            }
        ]),
        encoding="utf-8",
    )
    (registry_dir / "failure-attributions.json").write_text(
        json.dumps([
            {
                "id": "failure-attribution:finding_demo",
                "findingId": "finding_demo",
                "rank": 1,
            }
        ]),
        encoding="utf-8",
    )
    (registry_dir / "retention-cleanup-plan.json").write_text(
        json.dumps({
            "schemaVersion": "1.0",
            "runId": "run_demo-001",
            "generatedAt": "2026-07-03T10:00:10Z",
            "policy": {
                "retainRunsDays": 30,
                "retainArtifactsDays": 14,
                "retainReportsDays": 30,
                "retainTraceDays": 7,
                "retainVideoDays": 7,
                "dryRun": True,
            },
            "candidates": [
                {
                    "id": "retention_report-html",
                    "kind": "report",
                    "path": str(reports_dir / "report.html"),
                    "action": "delete-after-retention",
                    "reason": "Derived report can be removed after retention.",
                    "expiresAt": "2026-08-02T10:00:00Z",
                    "protected": False,
                },
                {
                    "id": "retention_resource-catalog",
                    "kind": "registry",
                    "path": str(registry_dir / "resources.json"),
                    "action": "retain",
                    "reason": "Core run registry metadata remains protected.",
                    "protected": True,
                },
            ],
        }),
        encoding="utf-8",
    )


def write_audit_index_fixture(tmp_path) -> None:
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True)
    connection = sqlite3.connect(audit_dir / "audit.sqlite")
    try:
        connection.execute(
            """
            CREATE TABLE audit_schema_migrations (
              version TEXT PRIMARY KEY,
              description TEXT NOT NULL,
              applied_at TEXT NOT NULL,
              hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO audit_schema_migrations (
              version,
              description,
              applied_at,
              hash
            ) VALUES (?, ?, ?, ?)
            """,
            (
                "0003_project_scoped_artifact_metadata",
                "fixture migration",
                "2026-07-03T10:00:00Z",
                "hash-migration",
            ),
        )
        connection.execute(
            """
            CREATE TABLE runs (
              run_id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              mission_id TEXT NOT NULL,
              mission_name TEXT NOT NULL,
              target_app_id TEXT NOT NULL,
              target_app_name TEXT NOT NULL,
              status TEXT NOT NULL,
              review_status TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              bundle_uri TEXT NOT NULL,
              schema_version TEXT NOT NULL,
              hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
              run_id,
              project_id,
              mission_id,
              mission_name,
              target_app_id,
              target_app_name,
              status,
              review_status,
              started_at,
              finished_at,
              bundle_uri,
              schema_version,
              hash,
              created_at,
              updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run_demo-001",
                "project_demo",
                "mission_demo",
                "Demo Mission",
                "targetapp_demo",
                "Demo App",
                "failed",
                "fail",
                "2026-07-03T10:00:00Z",
                "2026-07-03T10:00:10Z",
                str(tmp_path / "run_demo-001" / "manifest.json"),
                "1.0",
                "hash-run-demo-001",
                "2026-07-03T10:00:00Z",
                "2026-07-03T10:00:10Z",
            ),
        )
        connection.execute(
            """
            CREATE TABLE source_contexts (
              source_context_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              read_state TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              failure_reason TEXT,
              permissions_json TEXT NOT NULL,
              usage_scopes_json TEXT NOT NULL,
              hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO source_contexts (
              source_context_id,
              run_id,
              kind,
              read_state,
              source_ref,
              failure_reason,
              permissions_json,
              usage_scopes_json,
              hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "github-pr:demo/app#1",
                "run_demo-001",
                "github-pr",
                "ready",
                "https://github.com/demo/app/pull/1",
                None,
                json.dumps(["network-read", "credential-read"]),
                json.dumps(["planning", "failure-analysis", "reporting"]),
                "hash-source-context",
            ),
        )
        connection.execute(
            """
            CREATE TABLE artifacts (
              artifact_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              evidence_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL,
              artifact_uri TEXT NOT NULL,
              media_type TEXT NOT NULL,
              sha256 TEXT NOT NULL,
              size_bytes INTEGER NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}',
              hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO artifacts (
              artifact_id,
              run_id,
              evidence_id,
              kind,
              status,
              artifact_uri,
              media_type,
              sha256,
              size_bytes,
              metadata_json,
              hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "artifact_checkout-console",
                "run_demo-001",
                "evidence_demo-login",
                "console-log",
                "indexed",
                "artifacts/checkout.console.log",
                "text/plain",
                "0" * 64,
                128,
                json.dumps({
                    "entryCount": 2,
                    "errorCount": 1,
                    "firstError": "Uncaught TypeError: cannot read checkout total",
                }),
                "hash-artifact-console",
            ),
        )
        connection.execute(
            """
            CREATE TABLE failure_attributions (
              attribution_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              finding_id TEXT NOT NULL,
              scenario_id TEXT NOT NULL,
              step_id TEXT,
              rank INTEGER NOT NULL,
              category TEXT NOT NULL,
              confidence REAL NOT NULL,
              likely_cause TEXT NOT NULL DEFAULT '',
              recommendation TEXT NOT NULL DEFAULT '',
              signals_json TEXT NOT NULL DEFAULT '{}',
              hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO failure_attributions (
              attribution_id,
              run_id,
              finding_id,
              scenario_id,
              step_id,
              rank,
              category,
              confidence,
              likely_cause,
              recommendation,
              signals_json,
              hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "failure-attribution:finding_demo",
                "run_demo-001",
                "finding_demo",
                "scenario_demo-login",
                "step_demo-login",
                1,
                "product-bug",
                0.83,
                "Checkout regression is closest to changed file src/checkout.ts.",
                "Inspect checkout state transition and retry the oracle.",
                json.dumps({
                    "changedFiles": ["src/checkout.ts"],
                    "runtimeSignals": [{"phase": "health-check", "status": "passed"}],
                }),
                "hash-failure-attribution",
            ),
        )
        connection.execute(
            """
            CREATE TABLE runtime_lifecycle (
              phase_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              phase TEXT NOT NULL,
              status TEXT NOT NULL,
              summary TEXT,
              hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO runtime_lifecycle (
              phase_id,
              run_id,
              phase,
              status,
              summary,
              hash
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "run_demo-001:runtime:0:health-check",
                "run_demo-001",
                "health-check",
                "passed",
                "Target app responded before execution.",
                "hash-runtime",
            ),
        )
        connection.execute(
            """
            CREATE TABLE gate_results (
              gate_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              passed INTEGER NOT NULL,
              exit_code INTEGER NOT NULL,
              reasons_json TEXT NOT NULL,
              diagnostics_json TEXT NOT NULL DEFAULT '{}',
              generated_at TEXT NOT NULL,
              hash TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO gate_results (
              gate_id,
              run_id,
              passed,
              exit_code,
              reasons_json,
              diagnostics_json,
              generated_at,
              hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run_demo-001:gate",
                "run_demo-001",
                0,
                2,
                json.dumps(["regression-detected", "new-artifact-signals:1"]),
                json.dumps({
                    "newFindings": ["Regression"],
                    "newArtifactSignals": ["console:Uncaught TypeError"],
                }),
                "2026-07-03T10:00:11Z",
                "hash-gate",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_run_bundle_routes_expose_history_manifest_comparison_and_artifacts(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    agent_headers = {"x-test-officer-token": "dev-local-token"}

    history_response = client.get("/api/v1/test-officer/history", headers=agent_headers)
    audit_response = client.get("/api/v1/test-officer/audit/status", headers=agent_headers)
    latest_manifest_response = client.get("/api/v1/test-officer/runs/latest/manifest", headers=agent_headers)
    manifest_response = client.get("/api/v1/test-officer/runs/run_demo-001/manifest", headers=agent_headers)
    comparison_response = client.get("/api/v1/test-officer/runs/run_demo-001/comparison", headers=agent_headers)
    registry_response = client.get("/api/v1/test-officer/runs/run_demo-001/registry", headers=agent_headers)
    registry_scenarios_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/scenarios",
        headers=agent_headers,
    )
    onboarding_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/onboarding",
        headers=agent_headers,
    )
    mission_package_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/mission-package",
        headers=agent_headers,
    )
    evidence_registry_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/evidence",
        headers=agent_headers,
    )
    judge_report_registry_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/judge-report",
        headers=agent_headers,
    )
    source_contexts_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/source-contexts",
        headers=agent_headers,
    )
    failure_attributions_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/failure-attributions",
        headers=agent_headers,
    )
    retention_cleanup_plan_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/registry/retention-cleanup-plan",
        headers=agent_headers,
    )
    unauthorized_artifact_response = client.get("/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log")
    artifact_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    report_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/reports/report.html",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    signed_report_path = latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["html"]
    json_report_path = latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["json"]
    run_access_token = latest_manifest_response.json()["run"]["bundle"]["artifactAccess"]["runToken"]
    run_scoped_manifest_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/manifest",
        headers={"x-test-officer-run-token": run_access_token},
    )
    run_scoped_artifact_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log",
        headers={"x-test-officer-run-token": run_access_token},
    )
    wrong_run_manifest_response = client.get(
        "/api/v1/test-officer/runs/run_demo-002/manifest",
        headers={"x-test-officer-run-token": run_access_token},
    )
    signed_report_response = client.get(signed_report_path)
    unsigned_json_report_response = client.get(json_report_path)
    run_scoped_json_report_response = client.get(
        json_report_path,
        headers={"x-test-officer-run-token": run_access_token},
    )
    agent_json_report_response = client.get(json_report_path, headers=agent_headers)

    app.dependency_overrides.clear()

    assert history_response.status_code == 200
    assert history_response.json()["runs"][0]["runId"] == "run_demo-001"
    assert audit_response.status_code == 200
    assert audit_response.json()["exists"] is False
    assert audit_response.json()["schemaVersion"] == "missing"
    assert latest_manifest_response.status_code == 200
    assert latest_manifest_response.json()["mission"]["id"] == "mission_demo"
    assert "/reports/report.html" in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["html"]
    assert latest_manifest_response.json()["run"]["bundle"]["artifactAccess"]["tokenRequired"] is True
    assert latest_manifest_response.json()["run"]["bundle"]["artifactAccess"]["runTokenHeader"] == "x-test-officer-run-token"
    assert latest_manifest_response.json()["run"]["bundle"]["artifactAccess"]["runTokenScope"] == "run_demo-001"
    assert latest_manifest_response.json()["run"]["bundle"]["accessPolicy"]["profile"] == "deployment"
    assert latest_manifest_response.json()["run"]["bundle"]["accessPolicy"]["tokenPolicy"]["agentToken"] == "configured-secret"
    assert latest_manifest_response.json()["run"]["bundle"]["accessPolicy"]["credentialPolicy"]["encryptedCredentialStore"] is True
    assert latest_manifest_response.json()["run"]["bundle"]["accessPolicy"]["redaction"]["redactReports"] is True
    assert run_access_token.startswith("run-v1.")
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceManifestUrl"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceUrls"]["scenarios"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry/scenarios"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceUrls"]["onboardingProtocol"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry/onboarding"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceUrls"]["evidence"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry/evidence"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceUrls"]["sourceContexts"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry/source-contexts"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceUrls"]["failureAttributions"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry/failure-attributions"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["registry"]["resourceUrls"]["retentionCleanupPlan"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/registry/retention-cleanup-plan"
    )
    assert "signature=" in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["html"]
    assert "signature=" not in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["json"]
    assert latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["gate"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/reports/gate.json"
    )
    assert "signature=" not in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["gate"]
    assert latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["prAnnotation"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/reports/pr-annotation.md"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["githubAnnotations"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/reports/pr-annotations.json"
    )
    assert latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["ciArtifactManifest"].endswith(
        "/api/v1/test-officer/runs/run_demo-001/reports/artifact-upload-manifest.json"
    )
    assert "signature=" not in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["prAnnotation"]
    assert "signature=" not in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["githubAnnotations"]
    assert "signature=" not in latest_manifest_response.json()["run"]["bundle"]["reportUrls"]["ciArtifactManifest"]
    assert "dev-local-token" not in json.dumps(latest_manifest_response.json())
    assert manifest_response.status_code == 200
    assert manifest_response.json()["run"]["status"] == "failed"
    assert comparison_response.status_code == 200
    assert comparison_response.json()["summary"]["findingDelta"] == 1
    assert registry_response.status_code == 200
    assert registry_response.json()["counts"]["scenarios"] == 1
    assert registry_response.json()["counts"]["onboardingProtocols"] == 1
    assert registry_scenarios_response.status_code == 200
    assert registry_scenarios_response.json()[0]["id"] == "scenario_demo-login"
    assert onboarding_response.status_code == 200
    assert onboarding_response.json()["baseUrl"] == "https://example.test"
    assert mission_package_response.status_code == 200
    assert mission_package_response.json()["counts"]["scenarios"] == 1
    assert evidence_registry_response.status_code == 200
    assert evidence_registry_response.json() == []
    assert judge_report_registry_response.status_code == 200
    assert judge_report_registry_response.json()["id"] == "judge_demo"
    assert source_contexts_response.status_code == 200
    assert source_contexts_response.json()[0]["adapter"]["id"] == "github-pr:demo/app#1"
    assert failure_attributions_response.status_code == 200
    assert failure_attributions_response.json()[0]["id"] == "failure-attribution:finding_demo"
    assert retention_cleanup_plan_response.status_code == 200
    assert retention_cleanup_plan_response.json()["policy"]["dryRun"] is True
    assert retention_cleanup_plan_response.json()["candidates"][1]["protected"] is True
    assert unauthorized_artifact_response.status_code == 401
    assert artifact_response.status_code == 200
    assert artifact_response.text == "failure details"
    assert report_response.status_code == 200
    assert "demo" in report_response.text
    assert run_scoped_manifest_response.status_code == 200
    assert run_scoped_manifest_response.json()["run"]["id"] == "run_demo-001"
    assert run_scoped_artifact_response.status_code == 200
    assert run_scoped_artifact_response.text == "failure details"
    assert wrong_run_manifest_response.status_code == 401
    assert signed_report_response.status_code == 200
    assert "demo" in signed_report_response.text
    assert unsigned_json_report_response.status_code == 401
    assert run_scoped_json_report_response.status_code == 401
    assert agent_json_report_response.status_code == 200
    assert agent_json_report_response.json()["status"] == "failed"


def test_run_bundle_api_decrypts_encrypted_artifacts_when_key_is_configured(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.delenv("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY_REF", raising=False)
    key = bytes([11]) * 32
    iv = bytes([3]) * 12
    plaintext = b"failure details"
    encrypted = AESGCM(key).encrypt(iv, plaintext, None)
    ciphertext = encrypted[:-16]
    auth_tag = encrypted[-16:]
    run_dir = tmp_path / "run_demo-001"
    artifact_path = run_dir / "artifacts" / "failure.log"
    artifact_path.write_bytes(ciphertext)
    artifact_record = {
        "id": "artifact_failure-log",
        "evidenceId": "evidence_failure-log",
        "kind": "console-log",
        "status": "published",
        "path": str(artifact_path),
        "mediaType": "text/plain",
        "sizeBytes": len(ciphertext),
        "sha256": hashlib.sha256(ciphertext).hexdigest(),
        "metadata": {
            "relativePath": "artifacts/failure.log",
            "encryptedAtRest": True,
            "encryptionAlgorithm": "AES-256-GCM",
            "encryptionKeyRef": "test-key://artifact-v1",
            "encryptionIv": b64encode(iv).decode("ascii"),
            "encryptionAuthTag": b64encode(auth_tag).decode("ascii"),
            "plaintextSha256": hashlib.sha256(plaintext).hexdigest(),
            "plaintextSizeBytes": len(plaintext),
        },
    }
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [artifact_record]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "registry" / "artifacts.json").write_text(json.dumps([artifact_record]), encoding="utf-8")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    missing_key_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    monkeypatch.setenv("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY", b64encode(key).decode("ascii"))
    monkeypatch.setenv("AI_TEST_OFFICER_ARTIFACT_ENCRYPTION_KEY_REF", "test-key://artifact-v1")
    decrypted_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    app.dependency_overrides.clear()

    assert missing_key_response.status_code == 503
    assert "ARTIFACT_ENCRYPTION_KEY" in missing_key_response.json()["detail"]
    assert decrypted_response.status_code == 200
    assert decrypted_response.text == "failure details"
    assert artifact_path.read_bytes() == ciphertext


def test_run_bundle_routes_execute_retention_job_with_dry_run_and_apply(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")
    run_dir = tmp_path / "run_demo-001"
    artifacts_dir = run_dir / "artifacts"
    registry_dir = run_dir / "registry"
    trace_path = artifacts_dir / "runtime.trace.zip"
    trace_path.write_text("trace payload", encoding="utf-8")
    plan_path = registry_dir / "retention-cleanup-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["candidates"].append({
        "id": "retention_runtime-trace",
        "kind": "playwright-trace",
        "path": str(trace_path),
        "action": "archive-after-retention",
        "reason": "Trace should be archived after retention.",
        "expiresAt": "2026-08-02T10:00:00Z",
        "protected": False,
    })
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    dry_run_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/retention-job?now=2026-09-01T00:00:00Z",
        headers={"x-test-officer-token": "dev-local-token"},
    )

    assert dry_run_response.status_code == 200
    assert dry_run_response.json()["dryRun"] is True
    assert dry_run_response.json()["summary"]["planned"] == 2
    assert (run_dir / "reports" / "report.html").exists()
    assert trace_path.exists()

    apply_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/retention-job?apply=true&now=2026-09-01T00:00:00Z",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    app.dependency_overrides.clear()

    assert apply_response.status_code == 200
    assert apply_response.json()["dryRun"] is False
    assert apply_response.json()["summary"]["deleted"] == 1
    assert apply_response.json()["summary"]["archived"] == 1
    assert not (run_dir / "reports" / "report.html").exists()
    assert not trace_path.exists()
    archive_path = apply_response.json()["records"][2]["archivedPath"]
    assert archive_path is not None
    with zipfile.ZipFile(archive_path) as archive:
        assert "artifacts/runtime.trace.zip" in archive.namelist()
    retention_report = json.loads((run_dir / "reports" / "retention-job.json").read_text(encoding="utf-8"))
    assert retention_report["summary"]["archived"] == 1


def test_run_bundle_routes_verify_artifact_integrity_and_create_download_bundle(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")
    run_dir = tmp_path / "run_demo-001"
    artifact_path = run_dir / "artifacts" / "failure.log"
    artifact_bytes = artifact_path.read_bytes()
    manifest_path = run_dir / "manifest.json"
    registry_artifacts_path = run_dir / "registry" / "artifacts.json"
    artifact_record = {
        "id": "artifact_failure-log",
        "evidenceId": "evidence_demo",
        "kind": "console-log",
        "status": "published",
        "path": str(artifact_path),
        "mediaType": "text/plain",
        "sizeBytes": len(artifact_bytes),
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "metadata": {},
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [artifact_record]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry_artifacts_path.write_text(json.dumps([artifact_record]), encoding="utf-8")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    integrity_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/integrity",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    download_manifest_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/download-bundle",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    download_response = client.get(
        "/api/v1/test-officer/runs/run_demo-001/download-bundle",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    app.dependency_overrides.clear()

    assert integrity_response.status_code == 200
    assert integrity_response.json()["passed"] is True
    assert integrity_response.json()["artifacts"][0]["actualSha256"] == artifact_record["sha256"]
    assert (run_dir / "reports" / "integrity-report.json").exists()
    assert download_manifest_response.status_code == 200
    assert download_manifest_response.json()["entryCount"] > 0
    assert download_manifest_response.json()["bundlePath"].endswith("run-bundle.zip")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/zip"
    bundle_path = run_dir / "reports" / "run-bundle.zip"
    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as archive:
        assert "manifest.json" in archive.namelist()
        assert "artifacts/failure.log" in archive.namelist()


def test_download_bundle_can_reference_large_trace_video_artifacts_without_zipping_payload(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_STRATEGY", "reference-only")
    monkeypatch.setenv("AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_BYTES", "8")
    run_dir = tmp_path / "run_demo-001"
    trace_path = run_dir / "artifacts" / "runtime.trace.zip"
    trace_path.write_text("trace payload larger than threshold", encoding="utf-8")
    manifest_path = run_dir / "manifest.json"
    registry_artifacts_path = run_dir / "registry" / "artifacts.json"
    artifact_record = {
        "id": "artifact_runtime-trace",
        "evidenceId": "evidence_demo",
        "kind": "playwright-trace",
        "status": "published",
        "path": str(trace_path),
        "mediaType": "application/zip",
        "sizeBytes": trace_path.stat().st_size,
        "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        "metadata": {"relativePath": "artifacts/runtime.trace.zip"},
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = [artifact_record]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    registry_artifacts_path.write_text(json.dumps([artifact_record]), encoding="utf-8")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/download-bundle",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["referencedOnlyCount"] == 1
    trace_entry = next(entry for entry in response.json()["entries"] if entry["relativePath"] == "artifacts/runtime.trace.zip")
    assert trace_entry["included"] is False
    assert trace_entry["largeArtifact"] is True
    assert trace_entry["artifactKind"] == "playwright-trace"
    assert trace_entry["largeArtifactStrategy"] == "reference-only"
    with zipfile.ZipFile(run_dir / "reports" / "run-bundle.zip") as archive:
        assert "manifest.json" in archive.namelist()
        assert "artifacts/runtime.trace.zip" not in archive.namelist()


def test_run_bundle_sensitive_storage_ops_require_project_operator_role(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")
    operator_token = build_project_access_token("project_demo", role="operator")
    viewer_token = build_project_access_token("project_demo", role="viewer")
    wrong_project_token = build_project_access_token("project_other", role="operator")
    run_token = build_run_access_token("run_demo-001")
    assert operator_token is not None
    assert viewer_token is not None
    assert wrong_project_token is not None
    assert run_token is not None

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    operator_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/integrity",
        headers={"x-test-officer-project-token": operator_token},
    )
    viewer_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/integrity",
        headers={"x-test-officer-project-token": viewer_token},
    )
    wrong_project_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/integrity",
        headers={"x-test-officer-project-token": wrong_project_token},
    )
    run_token_response = client.post(
        "/api/v1/test-officer/runs/run_demo-001/integrity",
        headers={"x-test-officer-run-token": run_token},
    )
    app.dependency_overrides.clear()

    assert operator_response.status_code == 200
    assert viewer_response.status_code == 401
    assert "below the required role" in viewer_response.json()["detail"]
    assert wrong_project_response.status_code == 401
    assert run_token_response.status_code == 401


def test_test_officer_cors_allows_run_scoped_token_header(monkeypatch) -> None:
    monkeypatch.setenv("NODE_ENV", "development")
    client = TestClient(app)

    response = client.options(
        "/api/v1/test-officer/runs/run_demo-001/manifest",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-test-officer-run-token, x-test-officer-project-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "x-test-officer-run-token" in response.headers["access-control-allow-headers"].lower()
    assert "x-test-officer-project-token" in response.headers["access-control-allow-headers"].lower()


def test_run_bundle_routes_expose_sqlite_audit_run_index(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    write_audit_index_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    unauthorized_response = client.get("/api/v1/test-officer/audit/runs")
    audit_runs_response = client.get(
        "/api/v1/test-officer/audit/runs?project_id=project_demo&status=failed",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    empty_runs_response = client.get(
        "/api/v1/test-officer/audit/runs?project_id=project_other",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    app.dependency_overrides.clear()

    assert unauthorized_response.status_code == 401
    assert audit_runs_response.status_code == 200
    assert audit_runs_response.json() == [
        {
            "runId": "run_demo-001",
            "projectId": "project_demo",
            "missionId": "mission_demo",
            "missionName": "Demo Mission",
            "targetAppId": "targetapp_demo",
            "targetAppName": "Demo App",
            "status": "failed",
            "reviewStatus": "fail",
            "startedAt": "2026-07-03T10:00:00Z",
            "finishedAt": "2026-07-03T10:00:10Z",
            "bundleUri": str(tmp_path / "run_demo-001" / "manifest.json"),
            "createdAt": "2026-07-03T10:00:00Z",
            "updatedAt": "2026-07-03T10:00:10Z",
        }
    ]
    assert empty_runs_response.status_code == 200
    assert empty_runs_response.json() == []


def test_project_viewer_token_can_read_only_scoped_audit_views(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    write_audit_index_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-token-123")
    monkeypatch.setenv("AI_TEST_OFFICER_ARTIFACT_TOKEN", "artifact-token-123")
    project_token = build_project_access_token("project_demo", role="viewer", now=2_000_000_000)
    wrong_project_token = build_project_access_token("project_other", role="viewer", now=2_000_000_000)
    assert project_token is not None
    assert wrong_project_token is not None

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    scoped_runs_response = client.get(
        "/api/v1/test-officer/audit/runs?project_id=project_demo",
        headers={"x-test-officer-project-token": project_token},
    )
    scoped_detail_response = client.get(
        "/api/v1/test-officer/audit/runs/run_demo-001",
        headers={"x-test-officer-project-token": project_token},
    )
    global_enumeration_response = client.get(
        "/api/v1/test-officer/audit/runs",
        headers={"x-test-officer-project-token": project_token},
    )
    wrong_project_list_response = client.get(
        "/api/v1/test-officer/audit/runs?project_id=project_other",
        headers={"x-test-officer-project-token": project_token},
    )
    wrong_project_detail_response = client.get(
        "/api/v1/test-officer/audit/runs/run_demo-001",
        headers={"x-test-officer-project-token": wrong_project_token},
    )
    app.dependency_overrides.clear()

    assert scoped_runs_response.status_code == 200
    assert scoped_runs_response.json()[0]["projectId"] == "project_demo"
    assert scoped_detail_response.status_code == 200
    assert scoped_detail_response.json()["runId"] == "run_demo-001"
    assert global_enumeration_response.status_code == 401
    assert wrong_project_list_response.status_code == 401
    assert wrong_project_detail_response.status_code == 401


def test_run_bundle_artifact_paths_cannot_escape_runs_root(tmp_path) -> None:
    write_run_bundle_fixture(tmp_path)
    service = RunBundleService(tmp_path)

    try:
        service.get_artifact_path("../run_demo-001", "failure.log")
    except FileNotFoundError as exc:
        assert "escaped runs root" in str(exc)
    else:
        raise AssertionError("Expected run_id traversal to be rejected")

    try:
        service.get_registry_resource("run_demo-001", "../reports")
    except FileNotFoundError as exc:
        assert "Registry resource not found" in str(exc)
    else:
        raise AssertionError("Expected invalid registry resource to be rejected")


def test_run_bundle_service_returns_typed_history_audit_and_registry_views(tmp_path) -> None:
    write_run_bundle_fixture(tmp_path)
    write_audit_index_fixture(tmp_path)
    service = RunBundleService(tmp_path)

    history = service.get_history()
    manifest = service.get_manifest("run_demo-001")
    audit_status = service.get_audit_status()
    audit_runs = service.list_audit_runs(project_id="project_demo")
    audit_detail = service.get_audit_run_detail("run_demo-001")
    comparison = service.get_comparison("run_demo-001")
    registry_manifest = service.get_registry_manifest("run_demo-001")
    onboarding = service.get_registry_resource("run_demo-001", "onboarding")
    mission_package = service.get_registry_resource("run_demo-001", "mission-package")
    registry_scenarios = service.get_registry_resource("run_demo-001", "scenarios")
    source_contexts = service.get_registry_resource("run_demo-001", "source-contexts")
    failure_attributions = service.get_registry_resource("run_demo-001", "failure-attributions")
    judge_report = service.get_registry_resource("run_demo-001", "judge-report")

    assert isinstance(history, RunBundleHistoryIndex)
    assert history.runs[0].runId == "run_demo-001"
    assert isinstance(manifest, RunBundleManifest)
    assert manifest.run.bundle.manifestUrl == "/api/v1/test-officer/runs/run_demo-001/manifest"
    assert manifest.run.bundle.registry is not None
    assert manifest.run.bundle.registry.resourceUrls is not None
    assert isinstance(audit_status, RunBundleAuditStatus)
    assert audit_status.exists is True
    assert audit_status.schemaVersion == "0003_project_scoped_artifact_metadata"
    assert audit_status.schemaMigrationCount == 1
    assert audit_status.schemaAppliedAt == "2026-07-03T10:00:00Z"
    assert audit_status.runs == 1
    assert audit_status.evidence == 0
    assert audit_status.sourceContexts == 1
    assert audit_status.failureAttributions == 1
    assert audit_status.runtimeLifecycle == 1
    assert audit_status.gateResults == 1
    assert isinstance(audit_runs[0], RunBundleAuditRunSummary)
    assert audit_runs[0].bundleUri.endswith("manifest.json")
    assert audit_detail.sourceContexts[0].kind == "github-pr"
    assert audit_detail.sourceContexts[0].permissions == ["network-read", "credential-read"]
    assert audit_detail.failureAttributions[0].rank == 1
    assert audit_detail.failureAttributions[0].confidence == 0.83
    assert audit_detail.failureAttributions[0].likelyCause.startswith("Checkout regression")
    assert audit_detail.failureAttributions[0].recommendation.startswith("Inspect checkout")
    assert audit_detail.failureAttributions[0].signals["changedFiles"] == ["src/checkout.ts"]
    assert audit_detail.artifacts[0].kind == "console-log"
    assert audit_detail.artifacts[0].metadata["firstError"].startswith("Uncaught TypeError")
    assert audit_detail.gateResults[0].exitCode == 2
    assert audit_detail.gateResults[0].diagnostics["newArtifactSignals"][0].startswith("console:")
    assert audit_detail.runtimeLifecycle[0].phase == "health-check"
    assert audit_detail.runtimeLifecycle[0].status == "passed"
    assert isinstance(comparison, RunBundleComparisonReport)
    assert comparison.summary.findingDelta == 1
    assert comparison.artifactSignalChanges.added[0].startswith("console:Uncaught TypeError")
    assert isinstance(registry_manifest, RunBundleRegistryManifest)
    assert registry_manifest.counts.scenarios == 1
    assert registry_manifest.counts.onboardingProtocols == 1
    assert registry_manifest.counts.retentionPlans == 1
    assert isinstance(onboarding, RunBundleOnboardingProtocol)
    assert onboarding.baseUrl == "https://example.test"
    assert isinstance(mission_package, RunBundleMissionPackage)
    assert isinstance(judge_report, RunBundleManifestJudgeReport)
    assert judge_report.id == "judge_demo"
    assert mission_package.counts.scenarios == 1
    assert isinstance(registry_scenarios[0], RunBundleRegistryResourceRecord)
    assert registry_scenarios[0].id == "scenario_demo-login"
    assert isinstance(source_contexts[0], RunBundleRegistrySourceContext)
    assert source_contexts[0].adapter.kind == "github-pr"
    assert source_contexts[0].payload["changedFiles"] == ["src/demo.ts"]
    assert isinstance(failure_attributions[0], RunBundleRegistryFailureAttribution)
    assert failure_attributions[0].findingId == "finding_demo"
    assert failure_attributions[0].rank == 1


def test_run_bundle_service_facade_delegates_to_split_services(tmp_path) -> None:
    service = RunBundleService(tmp_path)

    assert isinstance(service.manifests, RunBundleManifestService)
    assert isinstance(service.registry, RunBundleRegistryService)
    assert isinstance(service.artifacts, RunBundleArtifactService)
    assert isinstance(service.retention, RunBundleRetentionService)
    assert isinstance(service.audit, RunBundleAuditService)


def test_run_bundle_api_returns_audit_run_detail(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    write_audit_index_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "development")

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    response = client.get(
        "/api/v1/test-officer/audit/runs/run_demo-001",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    missing_response = client.get(
        "/api/v1/test-officer/audit/runs/run_missing",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["runId"] == "run_demo-001"
    assert response.json()["sourceContexts"][0]["kind"] == "github-pr"
    assert response.json()["failureAttributions"][0]["category"] == "product-bug"
    assert response.json()["failureAttributions"][0]["likelyCause"].startswith("Checkout regression")
    assert response.json()["failureAttributions"][0]["signals"]["changedFiles"] == ["src/checkout.ts"]
    assert response.json()["artifacts"][0]["metadata"]["firstError"].startswith("Uncaught TypeError")
    assert response.json()["gateResults"][0]["reasons"] == ["regression-detected", "new-artifact-signals:1"]
    assert response.json()["runtimeLifecycle"][0]["phase"] == "health-check"
    assert missing_response.status_code == 404


def test_test_officer_api_requires_agent_token_outside_development(tmp_path, monkeypatch) -> None:
    write_run_bundle_fixture(tmp_path)
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("AGENT_API_TOKEN", "agent-token-123")
    monkeypatch.delenv("AI_TEST_OFFICER_ARTIFACT_TOKEN", raising=False)

    def override_service() -> RunBundleService:
        return RunBundleService(tmp_path)

    app.dependency_overrides[get_run_bundle_service] = override_service
    client = TestClient(app)
    unauthorized = client.get("/api/v1/test-officer/history")
    dev_token_rejected = client.get(
        "/api/v1/test-officer/history",
        headers={"x-test-officer-token": "dev-local-token"},
    )
    authorized = client.get(
        "/api/v1/test-officer/history",
        headers={"x-test-officer-token": "agent-token-123"},
    )
    app.dependency_overrides.clear()

    assert unauthorized.status_code == 401
    assert dev_token_rejected.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["runs"][0]["runId"] == "run_demo-001"


def test_test_officer_mission_preview_route_returns_generated_platform_preview() -> None:
    class StubPreviewService(MissionPreviewService):
        def preview_mission(
            self,
            payload: TOPreviewRequest,
        ) -> TOPreviewResponse:
            return TOPreviewResponse.model_validate({
                "project": {"id": "project_preview", "name": payload.projectName, "status": "active"},
                "targetApp": {
                    "id": "targetapp_preview",
                    "name": payload.targetAppName,
                    "baseUrl": payload.baseUrl,
                    "status": "configured",
                },
                "mission": {
                    "id": "mission_preview",
                    "name": f"{payload.targetAppName} mission",
                    "objective": payload.businessObjective,
                    "mode": payload.mode,
                    "status": "ready",
                },
                "scenarios": [
                    {
                        "id": "scenario_auth-login",
                        "name": "Login flow succeeds",
                        "goal": "Verify login",
                        "tags": ["auth-login"],
                        "targetPageId": "page-login-1",
                    }
                ],
                "oracles": [{"id": "oracle_auth-login-0", "name": "Login oracle"}],
                "counts": {"pages": 2, "selectorHints": 1, "scenarios": 1, "oracles": 1},
            })

    app.dependency_overrides[get_test_officer_preview_service] = StubPreviewService
    client = TestClient(app)
    response = client.post(
        "/api/v1/test-officer/mission-preview",
        headers={"x-test-officer-token": "dev-local-token"},
        json={
            "projectName": "Customer Portal QA",
            "targetAppName": "Customer Portal",
            "baseUrl": "https://portal.example.test",
            "accountRef": "vault://accounts/customer-admin",
            "businessObjective": "Verify admins can sign in and create a customer.",
            "mode": "plan-assisted",
            "keyPages": ["/login", "/customers/new"],
            "selectorHints": ["data-testid=login-submit"],
            "scenarioRequests": [
                {"family": "auth-login", "pagePath": "/login", "enabled": True}
            ],
        },
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["mission"]["id"] == "mission_preview"
    assert response.json()["counts"]["scenarios"] == 1
    assert response.json()["project"]["name"] == "Customer Portal QA"


def test_test_officer_run_route_returns_created_manifest() -> None:
    class StubRunService(MissionRunService):
        def create_run(self, payload: TORunRequest) -> TORunResponse:
            return TORunResponse.model_validate({
                "runId": "run_preview-001",
                "status": "failed",
                "reviewStatus": "fail",
                "executor": "memory",
                "headless": True,
                "trace": False,
                "recordVideo": False,
                "manifest": {
                    "project": {"id": "project_preview", "name": payload.projectName, "status": "active"},
                    "targetApp": {
                        "id": "targetapp_preview",
                        "name": payload.targetAppName,
                        "baseUrl": payload.baseUrl,
                        "status": "configured",
                    },
                    "mission": {
                        "id": "mission_preview",
                        "name": f"{payload.targetAppName} mission",
                        "objective": payload.businessObjective,
                        "mode": payload.mode,
                        "status": "ready",
                    },
                    "scenarios": [],
                    "run": {
                        "id": "run_preview-001",
                        "mode": payload.mode,
                        "status": "failed",
                        "reviewStatus": "fail",
                        "bundle": {
                            "rootDir": "/runs/run_preview-001",
                            "manifestPath": "/runs/run_preview-001/manifest.json",
                            "artifactsDir": "/runs/run_preview-001/artifacts",
                            "evidenceDir": "/runs/run_preview-001/evidence",
                            "reportsDir": "/runs/run_preview-001/reports",
                        },
                    },
                    "steps": [],
                    "evidence": [],
                    "artifacts": [],
                    "findings": [],
                },
                "gate": {"passed": False, "exitCode": 2, "reasons": ["regression-detected"]},
            })

    app.dependency_overrides[get_test_officer_run_service] = StubRunService
    client = TestClient(app)
    response = client.post(
        "/api/v1/test-officer/runs",
        headers={"x-test-officer-token": "dev-local-token"},
        json={
            "projectName": "Customer Portal QA",
            "targetAppName": "Customer Portal",
            "baseUrl": "https://portal.example.test",
            "accountRef": "vault://accounts/customer-admin",
            "businessObjective": "Verify admins can sign in and create a customer.",
            "mode": "plan-assisted",
            "executor": "memory",
            "headless": True,
            "trace": False,
            "recordVideo": False,
            "keyPages": ["/login", "/customers/new"],
            "selectorHints": ["data-testid=login-submit"],
            "scenarioRequests": [
                {"family": "auth-login", "pagePath": "/login", "enabled": True}
            ],
        },
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["runId"] == "run_preview-001"
    assert response.json()["executor"] == "memory"
    assert response.json()["headless"] is True
    assert response.json()["manifest"]["mission"]["id"] == "mission_preview"
    assert response.json()["gate"]["exitCode"] == 2


def test_test_officer_mission_preview_route_rejects_unknown_fields() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/test-officer/mission-preview",
        headers={"x-test-officer-token": "dev-local-token"},
        json={
            "projectName": "Customer Portal QA",
            "targetAppName": "Customer Portal",
            "baseUrl": "https://portal.example.test",
            "businessObjective": "Verify admins can sign in and create a customer.",
            "mode": "plan-assisted",
            "unexpected": "nope",
        },
    )

    assert response.status_code == 422


def test_development_signed_urls_and_run_tokens_are_loopback_only() -> None:
    settings = ArtifactAccessSettings(
        token=None,
        agent_api_token=None,
        dev_mode=True,
        environment="development",
        signed_url_ttl_seconds=900,
    )
    signed_artifact_path = build_signed_artifact_url(
        "/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log",
        settings=settings,
    )
    run_token = build_run_access_token("run_demo-001", settings=settings)
    assert run_token is not None

    require_artifact_access(
        _request_for(signed_artifact_path, client_host="127.0.0.1"),
        run_id="run_demo-001",
        settings=settings,
    )
    require_run_access(
        _request_for(
            "/api/v1/test-officer/runs/run_demo-001/manifest",
            client_host="127.0.0.1",
            headers={"x-test-officer-run-token": run_token},
        ),
        "run_demo-001",
        settings=settings,
    )

    try:
        require_artifact_access(
            _request_for(signed_artifact_path, client_host="203.0.113.10"),
            run_id="run_demo-001",
            settings=settings,
        )
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("Expected non-loopback development signed URL to be rejected")

    try:
        require_run_access(
            _request_for(
                "/api/v1/test-officer/runs/run_demo-001/manifest",
                client_host="203.0.113.10",
                headers={"x-test-officer-run-token": run_token},
            ),
            "run_demo-001",
            settings=settings,
        )
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("Expected non-loopback development run token to be rejected")


def test_configured_artifact_token_allows_signed_urls_outside_loopback() -> None:
    settings = ArtifactAccessSettings(
        token="artifact-token-123",
        agent_api_token=None,
        dev_mode=True,
        environment="development",
        signed_url_ttl_seconds=900,
    )
    signed_artifact_path = build_signed_artifact_url(
        "/api/v1/test-officer/runs/run_demo-001/artifacts/failure.log",
        settings=settings,
    )

    require_artifact_access(
        _request_for(signed_artifact_path, client_host="203.0.113.10"),
        run_id="run_demo-001",
        settings=settings,
    )


def test_sensitive_reports_require_agent_token_even_with_run_scope() -> None:
    settings = ArtifactAccessSettings(
        token="artifact-token-123",
        agent_api_token="agent-token-123",
        dev_mode=False,
        environment="production",
        signed_url_ttl_seconds=900,
    )
    run_token = build_run_access_token("run_demo-001", settings=settings)
    assert run_token is not None
    assert should_sign_report_url("report.html") is True
    assert should_sign_report_url("run-report.json") is False
    assert should_sign_report_url("junit.xml") is False
    assert should_sign_report_url("gate.json") is False
    assert should_sign_report_url("pr-annotation.md") is False
    assert should_sign_report_url("pr-annotations.json") is False
    assert should_sign_report_url("artifact-upload-manifest.json") is False
    assert should_sign_report_url("retention-job.json") is False
    assert should_sign_report_url("integrity-report.json") is False
    assert should_sign_report_url("download-manifest.json") is False

    try:
        require_report_access(
            _request_for(
                "/api/v1/test-officer/runs/run_demo-001/reports/run-report.json",
                client_host="203.0.113.10",
                headers={"x-test-officer-run-token": run_token},
            ),
            "run-report.json",
            "run_demo-001",
            settings=settings,
        )
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Expected run-scoped token to be rejected for sensitive report")

    try:
        require_report_access(
            _request_for(
                "/api/v1/test-officer/runs/run_demo-001/reports/run-report.json",
                client_host="203.0.113.10",
                headers={"x-test-officer-token": "dev-local-token"},
            ),
            "run-report.json",
            "run_demo-001",
            settings=settings,
        )
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Expected dev-local-token to be rejected outside development")

    require_report_access(
        _request_for(
            "/api/v1/test-officer/runs/run_demo-001/reports/run-report.json",
            client_host="203.0.113.10",
            headers={"x-test-officer-token": "agent-token-123"},
        ),
        "run-report.json",
        "run_demo-001",
        settings=settings,
    )


def test_artifact_access_settings_fail_closed_outside_development_without_token(monkeypatch) -> None:
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.delenv("AI_TEST_OFFICER_ARTIFACT_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)

    settings = get_artifact_access_settings()
    assert settings.dev_mode is False
    try:
        validate_artifact_access_settings(settings)
    except RuntimeError as exc:
        assert "AI_TEST_OFFICER_ARTIFACT_TOKEN or AGENT_API_TOKEN is required" in str(exc)
    else:
        raise AssertionError("Expected production artifact settings without token to fail")


def test_agent_api_settings_fail_closed_outside_development_without_token(monkeypatch) -> None:
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.delenv("AGENT_API_TOKEN", raising=False)

    settings = get_artifact_access_settings()
    try:
        validate_agent_api_settings(settings)
    except RuntimeError as exc:
        assert "AGENT_API_TOKEN is required" in str(exc)
    else:
        raise AssertionError("Expected production agent API settings without token to fail")


def _request_for(
    path_with_query: str,
    *,
    client_host: str,
    headers: dict[str, str] | None = None,
) -> Request:
    parsed = urlsplit(path_with_query)
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": parsed.path,
            "raw_path": parsed.path.encode("utf-8"),
            "query_string": parsed.query.encode("utf-8"),
            "headers": raw_headers,
            "client": (client_host, 49152),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
