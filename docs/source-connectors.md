# Source Connector Contract

The connector layer turns project context into auditable `sourceContexts` inside each run bundle.
It is intentionally typed because planning, execution, judge, reporting, and Workbench all need the same source boundary.

## Supported Inputs

CLI inputs:

- `--pr-url <github-pr-url>`
- `--github-issue <github-issue-url>`
- `--jira-issue <jira-issue-url>`
- `--requirement-doc <workspace-path>`
- `--bug-ticket <workspace-path>`
- `--api-doc <workspace-path>`
- `--openapi-url <url>`
- `--git-diff <workspace-path>`
- `--connector-cache-dir <path>`
- `--connector-cache-ttl-ms <milliseconds>`
- `--no-connector-cache`

Workbench/API run requests expose the same connector families as:

- `prUrl`
- `githubIssues`
- `jiraIssues`
- `requirementDocs`
- `bugTickets`
- `apiDocs`
- `openApiUrls`
- `gitDiffs`

## Envelope

Every source is persisted as a `sourceConnectorReadEnvelope` with:

- `adapter.kind`: `git-diff`, `github-pr`, `github-issue`, `jira-issue`, `requirement-doc`, `bug-ticket`, or `api-doc`.
- `adapter.permissions`: `workspace-read`, `network-read`, and optionally `credential-read`.
- `adapter.usageScopes`: where the source can be used, such as `planning`, `judge`, `failure-analysis`, and `reporting`.
- `readState`: `ready`, `failed`, or `blocked`.
- `failureReason`: retained when the source cannot be read.
- `metadata.trust`: `trusted`, `verified`, `unverified`, or `low-confidence`.
- `metadata.permissionExplanations`: human-readable explanation of why each permission was needed.
- `metadata.retry`, `metadata.pagination`, `metadata.rateLimit`, `metadata.cache`, and `metadata.version`.

## Real-Project Behavior

Workspace files are constrained to the configured workspace root and receive a SHA-256 document version.
GitHub PR files are paginated through Link headers, with rate-limit headers and retry attempts recorded.
GitHub Issues and Jira Issues are normalized into typed payloads so bugs and requirements can be linked to failure attribution.
OpenAPI JSON is parsed into a summary of title, version, servers, paths, and operation count.

Network connector payloads can use cache files under `runs/.connector-cache` by default.
Cache hits are recorded in the run bundle, so CI and Workbench can tell whether a run used fresh or cached source context.
Expired cache entries are now marked as `cache.status=stale` before the connector refreshes the source, which distinguishes "no cache existed" from "a prior source version existed but was too old to trust."

## Workbench

The Workbench source context summary now shows:

- a connector trust-boundary status (`trusted`, `sensitive`, `degraded`, `blocked`, or `missing`)
- warning lines for credentialed, failed/blocked, low-confidence, and judge-consumed sources
- permission cards that group `workspace-read`, `network-read`, and `credential-read` by source and explanation
- source kind and read state
- trust level
- cache status
- retry attempts
- paginated page count
- rate-limit remaining count
- permission explanations

This keeps connector permissions visible to the operator instead of hiding them behind CLI flags. The UI reads these fields from the same run bundle `sourceContexts` manifest that agent, judge, audit, and CI consume.
