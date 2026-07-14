# Trustworthy Training Foundation

This document records the current training-oriented foundation added to the repository so model work can move from "trained something" toward "proved it does not leak future information and is useful in research workflow decisions."

## Scope implemented now

- Unified canonical instrument and price-bar contracts for US/CN equities, ETFs, and indices
- Expanded coverage presets for US/CN benchmark and sector references so walk-forward regime tagging can use real benchmark series
- Point-in-time event contract with explicit `published_at`
- Data-quality rule set for:
  - missing values
  - halted/suspended sessions
  - adjusted vs raw close
  - currency conversion requirements
  - calendar gap warnings
- Multi-task label generation for:
  - future 20/60/120 day max drawdown
  - future 20/60/120 day realized volatility
  - post-earnings abnormal move
  - news-event shock
  - excess return vs benchmark
  - industry excess return vs sector reference
- Walk-forward validation fold builder with regime tagging
- Point-in-time training dataset builder with feature rows for research/risk tasks
- Pure Python baseline trainer with bucket calibration and feature-contribution explanations
- Real-data source hub for US/CN covered symbols with cache-first normalization
- Multi-trainer experiment runner for baseline vs candidate comparison
- File-backed model registry with explicit `candidate -> approved -> rolled_back/rejected`
- Promotion gate that prevents weak candidates from replacing the current approved model
- Promotion gate now also blocks candidates when target-label coverage is too sparse or required reference coverage is too weak
- Research usefulness evaluator for top-risk-bucket drawdown lift and alert lead time

## Current module map

- `src/investment_research/training/models.py`
  Canonical contracts for instruments, price bars, events, labels, folds, model cards, and risk-bucket observations.
- `src/investment_research/training/data_quality.py`
  Training-data preparation, point-in-time filtering, and leakage detection.
- `src/investment_research/training/labels.py`
  Multi-task label generation from future windows only.
- `src/investment_research/training/validation.py`
  Walk-forward split construction and simple market-regime tagging.
- `src/investment_research/training/dataset.py`
  Converts canonical bars and point-in-time events into model-ready training samples.
- `src/investment_research/training/real_data.py`
  Pulls and caches covered-symbol raw rows, normalizes them, and builds real training samples.
- `src/investment_research/training/baseline.py`
  Correlation-weighted linear baseline, calibrated probabilities, and top-contributor explanations.
- `src/investment_research/training/workflow.py`
  End-to-end walk-forward baseline runner that emits model-card metrics plus regime-summary notes.
- `src/investment_research/training/trainers.py`
  Trainer specs for baseline and optional dependency-backed candidate families.
- `src/investment_research/training/experiments.py`
  Executes multiple trainer specs, emits experiment results, attaches promotion-gate outcomes, and records sample-coverage plus skipped-trainer audit metadata.
- `src/investment_research/training/promotion.py`
  Candidate-vs-baseline promotion gate with regime coverage checks.
- `src/investment_research/training/registry.py`
  Model registration, approval, and rollback guardrail.
- `src/investment_research/training/evaluation.py`
  Workflow-oriented evaluation beyond AUC or accuracy.

## Experiment audit fields

Every `TrainingExperimentReport` now carries an `audit` section so experiment outputs can be checked before anyone treats them as trustworthy:

- `sample_coverage`
  - sample count
  - symbol count and symbol list
  - market and instrument coverage
  - date span
  - feature/data version set
  - point-in-time event count
  - max point-in-time events per sample
  - data-issue counts and per-code breakdown
- `label_coverage`
  - per-label available count
  - per-label missing count
  - availability ratio so sparse labels are visible before model comparison
- `target_label`
  - explicit availability summary for the active experiment target
  - useful when the chosen task is a sparse label such as `industry_excess_return_*d`
- `reference_coverage`
  - benchmark / sector / style configuration counts
  - how many configured samples actually had non-zero reference-backed features
  - which reference symbols were used in the run
- `point_in_time_integrity`
  - how many samples had no PIT events at all
  - how many data issues were attached to the sample set
  - explicit counts for leakage-style issue codes such as `future_event` and `future_price_bar`
- `regime_coverage`
  - how many walk-forward folds landed in each market regime
  - how many validation predictions were produced in each regime
  - validation date span for each regime bucket
- `skipped_trainers`
  - trainer name
  - algorithm family
  - explicit skip reason such as missing optional dependency

This makes the experiment artifact answer basic audit questions directly: what universe the run actually covered, how much point-in-time evidence was available, whether data issues were present, and which candidate families did not really run.

## Data rules encoded

1. `published_at` is the gate for point-in-time inclusion.
   Events published after the feature cutoff are excluded.
2. Non-USD bars cannot be converted to USD without `fx_rate_to_usd`.
3. Adjusted-close policy requires `adjusted_close`.
4. Halts and suspensions are visible and policy-driven, not silently dropped.
5. Large calendar gaps are warned under strict calendar handling.
6. Raw upstream responses can be cached locally before sample generation so the same run can be rebuilt without silently changing provider output.

## Label semantics

- `future_max_drawdown_*d`
  Worst peak-to-trough decline inside the forward window.
- `future_volatility_*d`
  Realized volatility from forward daily returns.
- `post_earnings_abnormal_move_5d`
  Max absolute move in the days after the first earnings/filing/announcement event after `as_of_date`.
- `news_event_shock_3d`
  Max absolute move after the first future news event.
- `excess_return_*d`
  Asset forward return minus benchmark forward return on matched dates.

## What still remains

- Real vendor ingestion is scaffolded, but production auth/rate-limit handling and richer provider coverage are still missing
- Explicit corporate-action and split-adjustment backfill pipeline
- Production calibration implementation and persisted calibration artifacts
- Baseline model training adapters for logistic regression / RF / XGBoost / LightGBM
- Candidate deep-model runners such as PatchTST / TCN / iTransformer
- Full market-stage segmentation beyond the current heuristic regime tagging
- Persisted feature store and label store versioning
- Online/offline model promotion checks tied to approved run bundles
- Real benchmark/industry join logic for US/CN sector-relative evaluation

## Local build entrypoint

After installing training extras, the repository can build cached real samples with:

```bash
python3 -m pip install -e ".[train,dev]"
python3 scripts/build_training_samples.py --symbol AAPL --start 2024-01-01 --end 2026-01-01 --output var/aapl-samples.json
python3 scripts/run_training_experiment.py --symbol AAPL --start 2024-01-01 --end 2026-01-01 --output var/aapl-experiment.json
```

This script uses `var/training-cache/` by default and keeps provider responses on disk before canonical normalization and sample generation.

When the covered symbol has a configured `benchmark_symbol`, the experiment script now also prepares benchmark price bars and passes them into walk-forward validation as the regime reference. That allows `regime_coverage` to reflect actual benchmark-driven buckets such as `bull`, `bear`, `volatile_sideways`, or `range_bound` instead of defaulting to `unknown`.

The coverage catalog now includes a broader set of reusable references for training and audit runs, including US sector ETFs and growth benchmarks plus CN ETF/index references such as `159919.SZ` and `399006.SZ`. The CN fetcher now routes ETFs and indices by preset instrument type instead of relying only on ticker prefixes.

Reference fields are now separated conceptually:

- `benchmark_symbol`
  Broad market reference used for market-stage and benchmark-relative checks.
- `sector_reference_symbol`
  Industry or sector proxy used for sector-relative features and labels.
- `style_reference_symbol`
  Growth/value/style proxy used for style-relative features.

The training sample builder now emits sector/style relative-strength features and can generate `industry_excess_return_*d` labels when sector reference bars are available.

Promotion gating now uses audit evidence in addition to validation metrics:

- candidates can be blocked when `target_label.availability_ratio` is below the configured minimum
- relative-return tasks can be blocked when the required reference type does not have enough feature-backed samples
- candidates are blocked when leakage-style PIT issues are non-zero under the current policy
- candidates can be blocked when the sample data-issue ratio exceeds the configured maximum

This moves low-trust cases from "visible in the report" to "not eligible for approval."

Promotion results now carry machine-readable gate output:

- `effective_policy`
  the resolved task-specific gate policy after profile overrides
- `checks`
  structured pass/fail records with `check_name`, `actual_value`, `threshold_value`, and `detail`

That makes experiment artifacts and future UI surfaces able to distinguish "blocked by sparse labels" from "blocked by weak regime coverage" without parsing free-form reason strings.

The gate now also resolves task-specific profiles on top of the base policy:

- `future_max_drawdown_*`
  - stricter target-label availability
  - stricter sample data-issue ratio
  - explicit `bull` and `bear` regime requirements
  - minimum validation prediction count for each required regime
- `industry_excess_return_*`
  - stricter sector-reference coverage requirement
  - stricter sector-reference configured ratio
- `excess_return_*`
  - stricter benchmark-reference coverage requirement
  - stricter benchmark configured ratio
- `news_event_shock_*` and `post_earnings_abnormal_move_*`
  - looser target-label availability than drawdown tasks
  - stricter tolerance for dirty samples
  - minimum samples-with-events ratio
