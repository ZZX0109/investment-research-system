# Phase 6 CI Gates And Artifact Previews

This phase makes two practical upgrades for real QA workflows:

- CLI-level CI gate decisions
- workbench rendering of inline artifact previews

## CI gate rules

[src/platform/cli.ts](../src/platform/cli.ts) now exposes explicit gate evaluation instead of relying only on a simple pass/fail run status.

Supported inputs:

- `--comparison-report <path>`
- `--gate-config <path>`
- `--fail-on-new-findings`
- `--fail-on-regression`

The preferred CI entrypoint is now a checked-in gate contract:

- [examples/ci/ai-test-officer.ci.json](../examples/ci/ai-test-officer.ci.json)
- [.github/workflows/ai-test-officer.yml](../.github/workflows/ai-test-officer.yml)

The GitHub Actions workflow installs Playwright Chromium, runs the standalone `customer-portal-lite` Playwright smoke, and then runs the main AI Test Officer gate. That keeps the CI proof anchored in both a non-built-in target-project onboarding contract and the existing golden demo path.

When `--gate-config` is not provided, the CLI looks for `ai-test-officer.ci.json` and `.ai-test-officer-ci.json` in the working directory or `--workspace-root`.

The CLI still fails when the current run is not a pass, but it can now also fail when:

- a comparison report contains newly added findings
- the latest run regresses versus the baseline run
- the comparison report contains newly added artifact failure signals such as first console errors or first network failures
- flaky or blocked runs are not explicitly allowed by the gate config

The CLI summary now returns a `gate` object with:

- `passed`
- `exitCode`
- `reasons`
- `diagnostics.newFindings`
- `diagnostics.newArtifactSignals`
- `diagnostics.regression`
- `diagnostics.policy`
- `diagnostics.flakyQuarantine`

That gives CI systems a typed explanation for why a run failed its gate.
The CLI also writes the same machine-readable decision to `reports/gate.json` and returns that path as `reports.gatePath`.

## Stable CI outputs

Every CLI run now emits a small CI contract beside the normal run bundle:

- `reports/gate.json`: machine-readable pass/fail/flaky/blocked gate decision.
- `reports/pr-annotation.md`: GitHub Step Summary / PR comment body with the run verdict, deltas, new findings, artifact signals, and likely causes.
- `reports/pr-annotations.json`: GitHub Checks-compatible annotation payloads. When a changed file is known, annotations point at that file; otherwise they point at `.github/AI_TEST_OFFICER.md` as a synthetic review surface.
- `reports/artifact-upload-manifest.json`: upload manifest that lists exact files to archive, retention days, file sizes, hashes where available, and the large-artifact strategy for trace/video files.

The GitHub Actions example reads `reports.ciArtifactManifestPath` from CLI stdout, expands `githubActions.uploadPaths`, appends `pr-annotation.md` to `$GITHUB_STEP_SUMMARY`, and uploads the declared paths with `actions/upload-artifact`.

Exit codes are stable:

- `0`: gate passed.
- `1`: CLI usage or unexpected command failure.
- `2`: gate failed because the run, judge, comparison, or regression policy failed.
- `3`: harness gap, meaning the platform could not prove an executable scenario/oracle contract existed.
- `4`: target app runtime unavailable before the mission could execute.

The shell-level test suite covers these codes with real CLI processes: pass (`0`), usage/unexpected command failure (`1`), gate failure (`2`), harness gap (`3`), and target runtime unavailable (`4`).

## Flaky and quarantine policy

The gate config supports `allowFlaky`, `allowBlocked`, and `flakyQuarantine`.
The default sample keeps flaky and blocked runs failing CI, but records the quarantine label and reason in `gate.json` so downstream automation can route the run into a deliberate quarantine workflow rather than silently accepting it.

## Artifact upload policy

The upload manifest is generated from the run bundle, not from glob guesses. It can include:

- the manifest and reports
- typed registry files
- evidence payloads
- screenshots, DOM snapshots, console/network logs
- Playwright traces and videos

Large trace/video behavior is controlled by `artifacts.maxUploadBytes` and `artifacts.largeArtifactStrategy`. The initial strategy is `skip-over-limit`, so oversized files stay referenced in the manifest without breaking the CI upload step.

Run bundle downloads have a separate storage strategy for the same class of large runtime artifacts:

- `AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_STRATEGY=include` keeps large traces/videos in `run-bundle.zip`.
- `AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_STRATEGY=reference-only` records the trace/video in `reports/download-manifest.json` but omits the payload from the zip.
- `AI_TEST_OFFICER_DOWNLOAD_LARGE_ARTIFACT_BYTES` controls the threshold. Persisted artifact metadata also records `largeArtifact`, `storageClass`, and the recommended download/retention actions.

## Inline artifact previews

[src/platform/bundle.ts](../src/platform/bundle.ts) now enriches persisted artifact metadata with preview-oriented fields:

- `relativePath`
- `previewMode`
- `inlinePreview`

Current preview modes:

- `image`
- `html`
- `json`
- `text`
- `download`

This allows the workbench to render:

- screenshot placeholders or real data URLs
- DOM snapshot excerpts
- console logs
- network logs

without inventing a separate preview protocol outside the run bundle.

## Workbench support

[workbench-ui/src/components/Inspector.tsx](../workbench-ui/src/components/Inspector.tsx) now renders inline previews directly inside the artifact cards when the run bundle includes them.

This moves the workbench closer to the target operator experience:

- evidence is visible, not just listed
- failure context is faster to inspect
- judge output is easier to validate against concrete artifacts

## Verification

- CLI gate logic: [tests/bundle.test.ts](../tests/bundle.test.ts)
- shell-level CLI exit contract: [tests/cli-shell.test.ts](../tests/cli-shell.test.ts)
- preview-aware sample bundle/view model: [tests/workbench-model.test.ts](../tests/workbench-model.test.ts)
