# WorkBuddy Research System

WorkBuddy is a local, run-centric investment research system. It combines real point-in-time market data, a governed drawdown-risk model, historical analogies, portfolio risk, evidence lineage, deterministic audit gates, PDF extraction, scheduled inspection, and fixed-run report replay. Outputs are limited to risk probability, historical distributions, observation conditions, and contrary evidence. The system does not execute trades or issue deterministic buy/sell instructions.

Core technical proposition: an evidence-bound financial research Agent that operates under point-in-time data, model uncertainty, and conflicting evidence, and decides whether to generate, repair, degrade, or abstain.

- [Technical whitepaper](docs/technical-whitepaper.md)
- [Model research report](docs/model-research-report.md)
- [Failure casebook](docs/failure-casebook.md)
- [Demo script](docs/demo-script.md)

The AI Test Officer has one product implementation under `ai-test-officer/`. This project integrates with its versioned HTTP API through a thin client; Agent, Judge, browser runtime, evidence schemas, and CLI behavior are not duplicated here.

## Start

Install Python and Node dependencies, then start the API, scheduler, and web workbench together:

```bash
python3 -m pip install -e ".[dev,documents]"
npm install
npm run dev:workbuddy
```

Default URLs:

- Web: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`
- Health: `http://127.0.0.1:8000/health`

The startup script applies Alembic migrations, checks the approved model manifest and four market bundles, and starts APScheduler inside FastAPI. No default account or password is created. Register through the workbench or `/api/v1/auth/register`.

## Trusted Data Path

Formal analysis uses `real + full` artifacts only. Configure the analysis providers to read the timestamped authoritative bundles:

```bash
export INVESTMENT_RESEARCH_MARKET_DATA_PROVIDER=bundle_backed
export INVESTMENT_RESEARCH_EVIDENCE_PROVIDER=bundle_backed
```

Provider degradation is explicit: online authority source, timestamped real cache, then unavailable. Real mode never falls back to synthetic data. A cache-backed refresh is marked `degraded` when live refresh is unavailable.

The trusted A-share close path is versioned separately from delayed intraday observation. Production requires configured primary and backup licensed provider adapters; AKShare/yfinance are restricted to research and backfill. Raw provider bytes are persisted before normalization, daily/minute bars retain immutable revisions, and every formal forecast exposes `as_of`, source time, coverage, cache state, quality status, and provider chain. Minute collection is disabled by default.

Refresh requests create durable ingestion jobs. Job state is available at `/api/v1/ingestion-jobs/{job_id}`, while the frozen multi-task result is available at `/api/v1/analysis-runs/{run_id}/research-forecast`. Direction and return tasks remain unavailable until their independent manifests are approved; the API does not infer them from the approved drawdown model.

The shared deployment contract is `investment-risk-features-v1`, with 29 ordered features used by training and runtime. Runtime inference abstains below 75% feature coverage. The approved manifest controls primary and fallback models; research-only models are never loaded for inference.

## Full Training

The authoritative training route is:

```bash
python3 scripts/run_training_job.py --data-source real --profile full --refresh-real-data --refresh-real-events
```

For the complete fetch, train, test, audit, ablation, serialization, and gate pipeline:

```bash
bash scripts/run_full_regression.sh
```

Formal outputs include `output/results.json`, `output/evaluation.json`, `output/model_cards.json`, `output/invest_agent_models.json`, deployment artifacts under `output/models/`, audit files under `audits/`, and run status under `runs/`. Demo, sandbox, synthetic, and quick jobs cannot overwrite formal deployment artifacts.

## Workflows

The main workflow is login, add an asset and holding, refresh timestamped real data, generate an immutable analysis run, inspect the 29-feature model output, review historical analogies and portfolio risk, run the research audit, generate a fixed report, set an inspection frequency, and replay prior runs.

PDF uploads accept PDF files up to 20 MB and 100 pages. PyMuPDF extracts page text and images, pdfplumber extracts table structures, and unresolved figures are marked `needs_visual_review`. Numbers are never guessed when visual parsing is unavailable.

## Validation

```bash
python3 -m pytest
npm test
npm run build
```

The workbench uses TanStack Query for server state, Zustand for UI-only state, Recharts for research charts, and Lucide icons for controls. The backend uses FastAPI, Pydantic, Alembic, APScheduler, PostgreSQL in production, S3-compatible object storage for artifacts, and scikit-learn-compatible model artifacts. SQLite remains a local compatibility store during the replay migration.

## PostgreSQL and MinIO acceptance

The formal storage acceptance environment is defined in `deploy/local-infra/compose.yml`. It requires operator-supplied passwords and does not contain default credentials. After the services are healthy, set the PostgreSQL, object-store, and AWS credential environment variables from `.env.example`, then run:

```bash
python3 scripts/validate_postgres_minio.py
```

Pass `--owner-email` and `--legacy-db` to include two idempotent legacy replay runs in the same acceptance check.

The archived `investment-research-system/backend` directory is read-only and is not part of the runtime path. Use `scripts/replay_legacy_backend.py --owner-email <registered-email> --dry-run` to inspect a replay before importing historical records. See [the archive policy](docs/legacy-backend-archive.md).

Research background and current literature notes are recorded in [docs/frontier-research-pain-points.md](docs/frontier-research-pain-points.md).
# Authoritative training entry

Formal training now has one entry point and stages every run in an isolated
`training_run_id` directory:

```bash
python3 scripts/run_formal_pipeline.py --config config/formal_training.yaml --dry-run
```

Remove `--dry-run` only after every configured provider has confirmed
authorization/SLA metadata. Add `--publish` to request atomic publication;
publication still fails closed unless PIT V2, approval evidence, artifact
hashes, decision context, data source and training-run identity all match.
`scripts/run_full_pipeline.py` is retained only as a deprecated forwarder.
