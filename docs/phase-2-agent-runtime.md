# Phase 2 Agent Runtime

This phase moves the project from a static contract layer toward a real test-agent platform runtime.

## Runtime boundaries

The agent runtime is intentionally split into four replaceable parts:

- `Planner`
  Expands `TestMission + Scenario[]` into an explainable ordered step plan.
- `Executor`
  Runs one planned step through Playwright or another connector.
- `EvidenceCollector`
  Turns step outcomes into typed `Evidence` and `Artifact` records.
- `Judge`
  Consumes runs, steps, evidence, artifacts, and oracles to emit `Finding[]` plus a machine-readable `JudgeReport`.

These boundaries are implemented in [src/platform/agent.ts](../src/platform/agent.ts).

## Supported modes

The runtime now supports the three target modes from the product goal:

- `scripted`
  Replays scenario steps as-authored for stable demos and golden runs.
- `plan-assisted`
  Preserves authored intent but exposes a clearer numbered plan suitable for real-project execution.
- `ai-exploratory`
  Builds a bounded exploration contract around the deterministic base path. Each run starts with an exploration charter, preserves the authored scenario steps, adds a limited number of risk probes, and ends with an explicit stop-condition step.

This is intentionally not an unbounded autonomous crawler. The current contract favors landing completeness and auditability: the planner declares hypotheses, probe budget, stop condition, selector drafts, oracle drafts, and evidence requirements before execution. A future frontier planner can replace the hypothesis generator without changing executor, collector, judge, or run bundle consumers.

## AI exploratory contract

`ai-exploratory` mode now emits typed plan metadata instead of relying on hidden prompt strings:

- `charter`
  Records the bounded exploration scope, hypothesis ids, probe budget, stop condition, and human-review requirement.
- `deterministic-baseline`
  Executes the authored scenario path while expanding evidence capture for drift signals such as screenshot, DOM, console, and network logs.
- `risk-probe`
  Adds small, executable probes for selector drift, state consistency, auth boundaries, network/runtime instability, or requirement ambiguity.
- `stop-condition`
  Closes the exploration loop and records whether the declared budget and evidence contract were respected.

The metadata is copied into both `PlannedStepRecord` and `Step`, and the evidence collector mirrors the step exploration metadata into `Evidence.metadata.exploration`. That lets the Workbench timeline, Judge, and CI reports explain why the agent took a step, what evidence it expected, and where a human should review the result.

## Source-aware exploration

`PlannerContext` now accepts `sourceContexts` plus an optional `explorationPolicy`.
The planner uses connector envelopes as bounded risk signals:

- OpenAPI/API-doc context can add a `network-runtime` probe.
- Git diff, GitHub PR, GitHub/Jira issue, bug-ticket, and requirement docs can add state or requirement probes.
- Failed, blocked, unverified, or low-confidence sources force human review when the default policy is active.

Every exploration record now includes stable metadata for `riskKind`, `sourceContextIds`, `probeBudget`, `stopCondition`, and `humanReviewRequired`.
This keeps the AI exploration layer evidence-bound and auditable instead of turning source text into uncontrolled instructions.

## Execution flow

`TestAgentService.runMission(...)` now orchestrates:

1. Create a typed `Run`
2. Ask the planner for step plans
3. Materialize typed `Step` entities
4. Execute each step
5. Collect typed evidence and artifacts for each step
6. Judge the run and emit:
   - final `Run.status`
   - machine-readable `reviewStatus`
   - `Finding[]`
   - `JudgeReport`

The result already matches the future workbench and CI direction because the service returns a full run bundle shape rather than only a summary string.

## New-project onboarding

[src/platform/mission-generator.ts](../src/platform/mission-generator.ts) converts the minimal onboarding protocol into a real mission package:

- `Project`
- `TargetApp`
- `TestMission`
- `Scenario[]`
- `Oracle[]`

The generator always aims to cover multiple scenario families:

- `golden-path`
- `form-submission`
- `auth-login`
- `list-state-change`

That gives the platform a concrete path toward "new project in, typed mission out" instead of only preserving one fixed demo path.

## What this unlocks next

- Replace `MemoryExecutor` with a Playwright-backed executor
- Persist `AgentRunResult` as a real run bundle manifest on disk
- Feed the run bundle directly into workbench UI panels
- Emit CI-oriented JSON and JUnit outputs from `JudgeReport`
