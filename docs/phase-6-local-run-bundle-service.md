# Phase 6 Local Run Bundle Service

This phase connects the run bundle layer to the local backend so the workbench can inspect real runs without manual file upload.

## New backend endpoints

[src/investment_research/api/run_bundle_routes.py](../src/investment_research/api/run_bundle_routes.py) now exposes local AI Test Officer bundle data through FastAPI:

- `GET /api/v1/test-officer/history`
- `GET /api/v1/test-officer/runs/latest/manifest`
- `GET /api/v1/test-officer/runs/{run_id}/manifest`
- `GET /api/v1/test-officer/runs/{run_id}/comparison`
- `GET /api/v1/test-officer/runs/{run_id}/artifacts/{artifact_name}`

These are backed by [src/investment_research/service/run_bundles.py](../src/investment_research/service/run_bundles.py), which reads the local `runs/` directory and respects the `AI_TEST_OFFICER_RUNS_ROOT` environment variable.

## Frontend integration

The existing React workbench now includes a dedicated `AI Test Officer` panel rather than a separate standalone app.

The panel is implemented in:

- [workbench-ui/src/features/testOfficer/TestOfficerPanel.tsx](../workbench-ui/src/features/testOfficer/TestOfficerPanel.tsx)
- [workbench-ui/src/features/testOfficer/model.ts](../workbench-ui/src/features/testOfficer/model.ts)

It uses the existing `client -> query hooks -> feature panel` structure already present in the workbench:

- [workbench-ui/src/api/client.ts](../workbench-ui/src/api/client.ts)
- [workbench-ui/src/hooks/useWorkbenchQueries.ts](../workbench-ui/src/hooks/useWorkbenchQueries.ts)

## What the panel shows

- latest test-officer run status
- step timeline
- evidence and artifact previews
- judge narrative
- recent run history for the same mission
- comparison delta versus the previous run

In `demo` mode it uses bundled fixture data. In `live` mode it reads the FastAPI endpoints above.

## Verification

- FastAPI route coverage: [tests/test_run_bundle_routes.py](../tests/test_run_bundle_routes.py)
- test-officer panel summary logic: [tests/workbench-model.test.ts](../tests/workbench-model.test.ts)
