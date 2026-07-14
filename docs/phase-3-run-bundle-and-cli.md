# Phase 3 Run Bundle And CLI

This phase turns the runtime result into a portable run bundle and makes the platform executable from the command line.

## Bundle structure

Each run is now persisted into a deterministic directory tree:

```text
runs/<run-id>/
  manifest.json
  artifacts/
  evidence/
  reports/
    run-report.json
    junit.xml
```

The manifest is the canonical source for:

- project and target app context
- mission, scenario, and oracle contracts
- run, step, evidence, artifact, finding, and judge report records
- selector maps
- fixture manifests

That means UI, judge, CLI, and future CI integrations can all read the same bundle instead of reconstructing paths independently.

## Machine-readable outputs

The platform now emits:

- JSON summary report for downstream tooling
- JUnit XML for CI systems that expect test-suite shaped output

Both are generated from the same typed run result so they stay aligned with the manifest.

## CLI flow

The CLI reads the minimal onboarding protocol JSON, generates a mission package, executes the current runtime, persists the run bundle, and prints a machine-readable summary.

Example:

```bash
npm run build
npm run run:cli -- --input ./onboarding.json --output-root ./runs --mode plan-assisted
```

Real-project preview example:

```bash
npm run run:cli -- --input ./examples/onboarding/real-project-preview.json --output-root ./runs --mode ai-exploratory
```

Expected input shape:

```json
{
  "baseUrl": "https://app.example.test",
  "accountRef": "vault://accounts/test-user",
  "keyPages": ["/login", "/orders", "/orders/create-form"],
  "businessObjective": "Verify users can log in and submit new orders.",
  "selectorHints": ["data-testid=login-submit"]
}
```

## What this unlocks next

- Replace `MemoryExecutor` with a Playwright-backed executor while preserving bundle format
- Point workbench UI directly at `manifest.json`
- Add history comparison and artifact diffing across runs
- Promote JSON and JUnit outputs into CI gating
