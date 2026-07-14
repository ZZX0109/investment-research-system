# Phase 6 Local Demo App Under Test

This phase adds a real local `app-under-test` so the platform can demonstrate onboarding and execution against more than a fixed internal fixture set.

## What was added

- [app-under-test/server.mjs](../app-under-test/server.mjs)
  A tiny Node HTTP server that hosts the demo target app at `http://127.0.0.1:4173`
- [app-under-test/public/login.html](../app-under-test/public/login.html)
  Login scenario surface with stable `data-testid` hooks
- [app-under-test/public/orders.html](../app-under-test/public/orders.html)
  Stateful order list for status transition testing
- [app-under-test/public/create-form.html](../app-under-test/public/create-form.html)
  Form submission scenario with success feedback
- [app-under-test/public/tasks.html](../app-under-test/public/tasks.html)
  Preserved `task_filter_completed` golden path
- [examples/onboarding/local-demo-app.json](../examples/onboarding/local-demo-app.json)
  The minimum onboarding protocol for connecting this project as a target app

## Why it matters

The platform story now has a concrete bridge between "generic onboarding protocol" and "real project adapter":

- login and permission-style entry flow
- form submission flow
- stateful list/status mutation flow
- filtered task-list golden scenario

That means the hackathon demo can still stay deterministic, while the underlying platform proves it can describe and attach to several scenario families through one mission contract.

## How to use it

Start the target app:

```bash
npm run dev:app-under-test
```

Then point mission generation and CLI execution at:

```bash
examples/onboarding/local-demo-app.json
```

This keeps the "new project" story grounded in a real base URL plus explicit selector hints, instead of only internal sample objects.
