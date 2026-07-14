# Phase 4 Selector Registry And Executor

This phase pushes the platform closer to a real test-agent runtime by removing more hidden selector protocol and introducing a browser-style executor contract.

## Typed selector registry

[src/platform/selectors.ts](../src/platform/selectors.ts) now treats selector references as typed registry lookups instead of loose strings embedded in scripts.

Each selector entry:

- has a stable `id`
- declares `preferredStrategies`
- keeps one or more query candidates
- resolves into an ordered fallback list

Supported strategies:

- `role`
- `test-id`
- `text`
- `label`
- `placeholder`
- `css`
- `xpath`

That means a scenario step can refer to `selectorRef: "task-filter-completed-tab"` and the executor can resolve it consistently from the selector map manifest.

## Playwright-style executor contract

[src/platform/playwright.ts](../src/platform/playwright.ts) introduces a `PlaywrightLikeExecutor`.

It is intentionally adapter-based:

- the executor owns planning-step semantics
- the selector registry owns selector fallback
- the page adapter owns browser interaction

Current step actions covered:

- `navigate`
- `click`
- `fill`
- `login`
- `assert`
- `extract`
- `wait`
- `custom` via click fallback

This is not a hard dependency on the Playwright package yet, but the interface is shaped so a real Playwright `Page` wrapper can implement it without changing mission, run, or bundle contracts.

## Evidence expansion

Steps now carry `evidenceRequirements`, so execution and collection are driven by typed expectations instead of fixed artifact assumptions.

The executor can now emit:

- `screenshot`
- `dom-snapshot`
- `console-log`
- `network-log`
- `playwright-trace`
- extracted attachments

That gives the platform a more realistic evidence chain for local workbench inspection and future CI gating.

## Verification

The new coverage lives in [tests/playwright-executor.test.ts](../tests/playwright-executor.test.ts), which verifies:

- selector fallback order
- Playwright-style execution through the selector registry
- richer artifact output
- failure behavior when selector execution cannot succeed
