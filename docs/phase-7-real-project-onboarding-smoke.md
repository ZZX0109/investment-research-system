# Phase 7 Real Project Onboarding Smoke

The platform now has a standalone target-project fixture that is separate from the built-in `app-under-test` demo:

- [examples/target-projects/customer-portal-lite/server.mjs](../examples/target-projects/customer-portal-lite/server.mjs)
- [examples/target-projects/customer-portal-lite/cleanup.mjs](../examples/target-projects/customer-portal-lite/cleanup.mjs)
- [examples/onboarding/customer-portal-lite.json](../examples/onboarding/customer-portal-lite.json)

This fixture behaves like a small external customer portal project. It declares its own runtime start command, health endpoint, test account context, business pages, selector hints, and cleanup command.

## What The Smoke Proves

The automated smoke test in [tests/bundle.test.ts](../tests/bundle.test.ts) now validates:

- a non-built-in target project can be started from the onboarding runtime contract
- runtime environment variables reach the target app process
- the configured health check gates mission execution
- cleanup runs after the mission and records its own marker
- mission generation preserves auth, page, selector, scenario, and runtime contracts
- the resulting run bundle persists onboarding, mission package, runtime lifecycle, evidence, artifacts, Judge report, and audit rows

The smoke uses the memory executor intentionally so the test stays deterministic and isolates the real-project onboarding boundary. The same onboarding contract can be run with `--executor playwright` for browser execution once the local machine or CI image has Playwright browsers installed.

There is also an opt-in Playwright smoke test that drives the standalone fixture through the real browser executor and verifies the resulting run bundle contains screenshot, DOM, console, network, Judge, and gate artifacts:

```bash
npx playwright install chromium
RUN_PLAYWRIGHT_SMOKE=1 HEADLESS=1 npm run smoke:customer-portal:playwright
```

The GitHub Actions workflow installs Chromium and runs this smoke before the main demo gate, so CI proves the platform can attach a non-built-in target project instead of only testing the bundled task app.

## Example Command

```bash
npm run build:platform
node dist/platform/cli.js \
  --input examples/onboarding/customer-portal-lite.json \
  --output-root runs \
  --mode plan-assisted
```

For a full browser run, start from the same onboarding file and add:

```bash
HEADLESS=1 node dist/platform/cli.js \
  --input examples/onboarding/customer-portal-lite.json \
  --output-root runs \
  --mode plan-assisted \
  --executor playwright
```
