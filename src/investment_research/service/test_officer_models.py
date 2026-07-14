from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TestOfficerRuntimeEnvVar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    value: str | None = None
    secretRef: str | None = None
    required: bool = False
    scope: Literal["launch", "test", "cleanup"] = "launch"


class TestOfficerRuntimeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: list[TestOfficerRuntimeEnvVar] = Field(default_factory=list)
    timeoutMs: int | None = Field(default=None, gt=0)


class TestOfficerRuntimeHealthCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    expectedStatus: list[int] = Field(default_factory=lambda: [200])
    timeoutMs: int = Field(default=30_000, gt=0)
    intervalMs: int = Field(default=500, gt=0)
    retries: int = Field(default=30, ge=0)


class TestOfficerRuntimeRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    purpose: Literal["login", "home", "workflow", "admin", "api", "health", "custom"] = "workflow"
    authenticated: bool = False


class TestOfficerRuntimeAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    credentialRef: str = Field(min_length=1)
    username: str | None = None


class TestOfficerRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: TestOfficerRuntimeCommand | None = None
    healthCheck: TestOfficerRuntimeHealthCheck | None = None
    routes: list[TestOfficerRuntimeRoute] = Field(default_factory=list)
    testAccounts: list[TestOfficerRuntimeAccount] = Field(default_factory=list)
    env: list[TestOfficerRuntimeEnvVar] = Field(default_factory=list)
    cleanup: TestOfficerRuntimeCommand | None = None

    def to_payload(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class TestOfficerScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str = Field(min_length=1)
    pagePath: str = Field(min_length=1)
    enabled: bool = True


class TestOfficerMissionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projectName: str = Field(min_length=1)
    targetAppName: str = Field(min_length=1)
    baseUrl: str = Field(min_length=1)
    accountRef: str = ""
    authStrategy: Literal["none", "basic", "session", "oauth", "custom"] = "session"
    loginPagePath: str | None = None
    authNotes: str | None = None
    environments: list[str] = Field(default_factory=list)
    runtime: TestOfficerRuntimeConfig | None = None
    businessObjective: str = Field(min_length=1)
    mode: Literal["scripted", "plan-assisted", "ai-exploratory"]
    keyPages: list[str] = Field(default_factory=list)
    selectorHints: list[str] = Field(default_factory=list)
    scenarioRequests: list[TestOfficerScenarioRequest] = Field(default_factory=list)

    def to_onboarding_payload(self) -> dict[str, object]:
        target_app: dict[str, object] = {
            "name": self.targetAppName,
            "defaultMode": self.mode,
        }
        if self.environments:
            target_app["environments"] = [environment for environment in self.environments if environment]

        payload: dict[str, object] = {
            "project": {
                "name": self.projectName,
            },
            "targetApp": target_app,
            "baseUrl": self.baseUrl,
            "keyPages": [page for page in self.keyPages if page],
            "businessObjective": self.businessObjective,
            "selectorHints": [hint for hint in self.selectorHints if hint],
            "scenarioRequests": [
                {
                    "family": scenario.family,
                    "pagePath": scenario.pagePath,
                }
                for scenario in self.scenarioRequests
                if scenario.enabled
            ],
        }
        if self.accountRef:
            payload["accountRef"] = self.accountRef
        if self.runtime:
            payload["runtime"] = self.runtime.to_payload()
        if self.authStrategy != "session" or self.accountRef or self.loginPagePath or self.authNotes:
            auth = {
                "strategy": self.authStrategy,
                "accountRef": self.accountRef or None,
                "loginPagePath": self.loginPagePath,
                "notes": self.authNotes,
            }
            payload["auth"] = {key: value for key, value in auth.items() if value is not None}
        return payload


class TestOfficerMissionPreviewCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: int
    selectorHints: int
    scenarios: int
    oracles: int


class TestOfficerMissionPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: dict[str, object]
    targetApp: dict[str, object]
    mission: dict[str, object]
    scenarios: list[dict[str, object]]
    oracles: list[dict[str, object]]
    counts: TestOfficerMissionPreviewCounts


class TestOfficerRunRequest(TestOfficerMissionPreviewRequest):
    executor: Literal["memory", "playwright"] = "playwright"
    headless: bool = True
    trace: bool = False
    recordVideo: bool = False
    workspaceRoot: str | None = None
    prUrl: str | None = None
    requirementDocs: list[str] = Field(default_factory=list)
    bugTickets: list[str] = Field(default_factory=list)
    apiDocs: list[str] = Field(default_factory=list)
    gitDiffs: list[str] = Field(default_factory=list)
    githubIssues: list[str] = Field(default_factory=list)
    jiraIssues: list[str] = Field(default_factory=list)
    openApiUrls: list[str] = Field(default_factory=list)
    requirementText: str | None = None

    def source_cli_args(self) -> list[str]:
        args: list[str] = []
        if self.workspaceRoot:
            args.extend(["--workspace-root", self.workspaceRoot])
        if self.prUrl:
            args.extend(["--pr-url", self.prUrl])
        if self.requirementText:
            args.extend(["--requirement-text", self.requirementText])
        for doc_path in self.requirementDocs:
            if doc_path:
                args.extend(["--requirement-doc", doc_path])
        for doc_path in self.bugTickets:
            if doc_path:
                args.extend(["--bug-ticket", doc_path])
        for doc_path in self.apiDocs:
            if doc_path:
                args.extend(["--api-doc", doc_path])
        for diff_path in self.gitDiffs:
            if diff_path:
                args.extend(["--git-diff", diff_path])
        for issue_url in self.githubIssues:
            if issue_url:
                args.extend(["--github-issue", issue_url])
        for issue_url in self.jiraIssues:
            if issue_url:
                args.extend(["--jira-issue", issue_url])
        for api_url in self.openApiUrls:
            if api_url:
                args.extend(["--openapi-url", api_url])
        return args


class TestOfficerGateRegressionDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statusChanged: bool = False
    reviewChanged: bool = False
    failedStepDelta: int = 0
    findingDelta: int = 0
    artifactSignalDelta: int = 0


class TestOfficerGatePolicyDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failOnNewFindings: bool = False
    failOnRegression: bool = False
    allowFlaky: bool = False
    allowBlocked: bool = False


class TestOfficerFlakyQuarantineDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    label: str = Field(min_length=1)
    reason: str | None = None


class TestOfficerGateDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newFindings: list[str] = Field(default_factory=list)
    newArtifactSignals: list[str] = Field(default_factory=list)
    regression: TestOfficerGateRegressionDiagnostics | None = None
    policy: TestOfficerGatePolicyDiagnostics | None = None
    flakyQuarantine: TestOfficerFlakyQuarantineDiagnostics | None = None


class TestOfficerGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    exitCode: int
    reasons: list[str] = Field(default_factory=list)
    diagnostics: TestOfficerGateDiagnostics = Field(default_factory=TestOfficerGateDiagnostics)


class TestOfficerRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str = Field(min_length=1)
    status: str = Field(min_length=1)
    reviewStatus: str = Field(min_length=1)
    executor: Literal["memory", "playwright"]
    headless: bool
    trace: bool
    recordVideo: bool
    manifest: dict[str, object]
    gate: TestOfficerGateResponse | None = None
