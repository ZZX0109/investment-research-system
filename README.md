# WorkBuddy Research System

WorkBuddy currently ships as a **zero-budget, research-grade, reproducible and evidence-driven A-share quantitative research platform**. The active path uses public AKShare data with Baostock fallback/cross-check, A-share daily bars and a small fixed ETF benchmark cohort. Every public-data artifact is permanently `research_pit / research_only / deployment_ready=false`. It is suitable for experiments, backtests and close/pre-open research updates; it is not real-time market data, an executable trading service or investment advice.

The four-market licensed PIT architecture remains available as a future extension. It fails closed when authorization, SLA and historical visibility evidence are missing, so free public backfills can never be presented as formal PIT data.

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

The workbench opens in `A股研究模式` by default and visibly labels public-data limitations.

## Zero-budget A-share research workflow

Install the research/training dependencies:

```bash
python3 -m pip install -e ".[dev,train]"
```

Run the scheduled close-confirmed collection and rebuild. The collector enumerates the current public A-share universe, always includes the ETF benchmark cohort, stores raw provider bytes append-only, uses AKShare as primary, Baostock as fallback, and cross-checks all ETFs plus a deterministic 20% equity sample. Use `--max-symbols 20` only for a quick local smoke run.

```bash
python3 scripts/run_free_research_cycle.py --decision-context close_confirmed
```

`pre_open`, four-market scheduling and minute collection remain code-compatible but disabled in the zero-budget mainline. The active scheduler freezes only `CN + close_confirmed` after 15:10 Asia/Shanghai.

The complete demonstration has one fail-closed entry point. It performs collection, raw/hash persistence, quality audit, fixed-cohort snapshotting, same-fold training, research roster freezing, hash-verified inference and immutable Shadow freezing in that order:

```bash
python3 scripts/run_cn_research_demo.py
python3 scripts/run_cn_research_demo.py --dry-run
```

The rebuild index under `artifacts/free_research_rebuild/` links raw hashes to year-partitioned standard Parquet, immutable market snapshots, the `cn_equity_core` and `cn_etf_benchmark` cohorts, Feature V2 sample manifests, and machine-readable leakage reports. Train a complete cohort by passing every sample manifest from exactly one market snapshot and context:

```bash
python3 scripts/run_free_research_training.py \
  --sample-manifest artifacts/free_research_rebuild/samples/close_confirmed/cn_equity_core/*/*.json \
  --cohort cn_equity_core
```

Risk (`drawdown_20d`), direction (`direction_1d`, `direction_5d`) and return (`return_20d`) are independent research manifests. The runner uses purged walk-forward validation, task-horizon embargo, a 252-session final holdout, a 126-session stress slice and time-OOF calibration. Traditional models remain primary; deep models are challengers and require at least two regimes with AUROC improvement of 0.03 before entering candidate evaluation. Public-data results remain non-deployable regardless of metrics.

Generate hash-verified task predictions from one frozen rebuild, freeze them in Research Shadow, then backfill immutable 1/5/20/60-session outcomes:

```bash
python3 scripts/run_cn_research_inference.py \
  --rebuild-index artifacts/free_research_rebuild/rebuild-<date>-<hash>.json \
  --decision-context close_confirmed --cohort cn_equity_core \
  --symbols 600519 000001
python3 scripts/run_free_research_cycle.py --decision-context close_confirmed \
  --skip-collection --skip-rebuild --freeze-shadow \
  --prediction-file artifacts/predictions/cn-research.json
python3 scripts/backfill_research_shadow.py --session-id <uuid>
```

Research Shadow progress is exposed through `/api/v1/research-shadow/sessions`, `/api/v1/research-shadow/summary`, and the workbench. It is forward research evidence and never counts toward a formal release gate.

## Future licensed data path

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
