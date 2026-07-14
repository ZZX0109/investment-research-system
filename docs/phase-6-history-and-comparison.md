# Phase 6 History And Comparison

This phase starts turning the project into a real QA service rather than a single-run demo.

## What changed

Run persistence now does more than write one bundle.

Every persisted run can also update:

- `history.json` at the run output root
- `comparison.json` inside the current run's `reports/` directory when a previous run for the same mission exists

That gives the platform a stable machine-readable history layer for:

- local workbench inspection
- CI trend tracking
- regression detection
- future run-to-run diffing of artifacts and judge outcomes

## History index

[src/platform/history.ts](../src/platform/history.ts) defines the history contract and update helpers.

Each history entry captures:

- run id
- mission and target app identity
- status and review status
- start and finish timestamps
- manifest path
- finding count
- failed step count
- artifact count

The history file is sorted newest-first and updated automatically when `persistRunBundle(...)` succeeds.

## Comparison report

When a previous run exists for the same mission, the platform now emits a comparison report with:

- status and review-status changes
- finding-count delta
- failed-step delta
- artifact-count delta
- artifact signal delta
- failure attribution delta
- judge result, machine decision, confidence, flaky, and blocked changes
- risk score delta and risk trend (`improved`, `regressed`, or `stable`)
- per-step status changes
- finding add/resolution summary
- failure attribution add/resolution summary, including top current likely causes
- console and network artifact signal add/resolution summary

This gives the workbench and CI a typed answer to "what changed from the last run?" and a second-level answer to "why does the current run look riskier or healthier?"

## Workbench integration

The workbench now supports:

- manifest upload
- history index upload
- comparison report upload

and includes a history panel that shows:

- recent runs for the same mission
- regression summary versus the previous run
- changed steps and finding deltas

## Verification

- history and comparison persistence: [tests/history.test.ts](../tests/history.test.ts)
- workbench history/comparison view model: [tests/workbench-model.test.ts](../tests/workbench-model.test.ts)
