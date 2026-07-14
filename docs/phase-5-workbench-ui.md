# Phase 5 Workbench UI

This phase gives the platform a real operator-facing workbench instead of leaving run inspection to raw JSON files.

## Core principle

The workbench is run-centric and manifest-driven.

It does not reconstruct state from scattered paths or ad hoc logs. It reads a single run bundle manifest and derives the interface from:

- `run`
- `steps`
- `evidence`
- `artifacts`
- `findings`
- `judgeReport`

That makes the UI a consumer of the same platform contract as the agent, CLI, and future CI integrations.

## Structure

The new frontend lives in [workbench-ui](../workbench-ui).

Key files:

- [workbench-ui/src/main.tsx](../workbench-ui/src/main.tsx)
- [workbench-ui/src/App.tsx](../workbench-ui/src/App.tsx)
- [workbench-ui/src/model.ts](../workbench-ui/src/model.ts)
- [workbench-ui/src/components/Sidebar.tsx](../workbench-ui/src/components/Sidebar.tsx)
- [workbench-ui/src/components/Timeline.tsx](../workbench-ui/src/components/Timeline.tsx)
- [workbench-ui/src/components/Inspector.tsx](../workbench-ui/src/components/Inspector.tsx)

## Current experience

The current UI provides:

- left panel for project, target app, mission, scenario coverage, and run stats
- center timeline for step-by-step execution reasoning and status
- right inspector for evidence, artifacts, judge output, and findings
- local manifest upload so a real run bundle can replace the bundled sample

This is intentionally aligned with the product goal:

- the user can see why the agent acted
- what evidence was collected
- which step failed
- what the judge concluded
- how findings are classified

## Build and run

```bash
npm run build
npm run dev:workbench
```

The production build is emitted to `dist-workbench/`.

## Next moves

- load a manifest directly from the latest local run bundle directory
- render screenshots and traces, not just metadata
- add run-history comparison and diff views
- wire the Python backend to serve stored run manifests

The summary model now exposes stronger comparison fields from run bundles, including risk trend, confidence delta, Judge decision changes, artifact signal delta, and failure attribution delta. That lets the UI present historical regressions as operator-facing signals instead of only raw JSON diff counts.
