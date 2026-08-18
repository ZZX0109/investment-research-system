#!/usr/bin/env python3
"""End-to-end resumable research queue.

The existing baseline queue is treated as stage B.  This controller waits for
it, selects the strongest baseline per horizon using development-safe
holdout-screen metrics, runs the feature-profile ablations, then runs the
date-batched StockMixer and MASTER challengers and writes one final index.
The active path now consumes the quarterly long-term baseline queue. Legacy
sequence/panel stages remain available for auxiliary experiments but are not
started by the long-term controller.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
TASKS = ("excess_return_5d", "excess_return_20d")
ARCHITECTURES = ("patchtst", "tcn", "itransformer", "deep_mlp")
FEATURE_PROFILES = ("price_volume", "market_industry", "market_industry_fundamental", "market_industry_event")
PANEL_ARCHITECTURES = ("stockmixer", "master")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-status", type=Path, required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--object-store", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=PROJECT / "var/cn-research")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=30)
    parser.add_argument("--max-wait-hours", type=float, default=24.0)
    parser.add_argument("--maximum-dates", type=int, default=1260)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--panel-batch-dates", type=int, default=8)
    return parser.parse_args()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


def _env(batch_size: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(PROJECT / "src"),
        "CUDA_VISIBLE_DEVICES": "0",
        "INVESTMENT_RESEARCH_TORCH_DEVICE": "cuda",
        "INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION": "0.80",
        "INVESTMENT_RESEARCH_SEQUENCE_BATCH_SIZE": str(batch_size),
        "OMP_NUM_THREADS": "8",
        "MKL_NUM_THREADS": "8",
    })
    return env


def _baseline_done(status_path: Path) -> tuple[bool, dict]:
    payload = _read(status_path, {}) or {}
    return payload.get("status") in {
        "baseline_completed_panel_models_queued",
        "long_term_baseline_completed_auxiliary_short_horizon_queued",
    }, payload


def _baseline_architecture(root: Path, task: str) -> str:
    candidates = []
    for architecture in ARCHITECTURES:
        report = root / "cn" / "close_confirmed" / "cn_equity_core" / task / "sequence" / architecture / "sequence_evaluation.json"
        payload = _read(report, {}) or {}
        metrics = ((payload.get("result") or {}).get("holdout_metrics") or {})
        # Cost-after top-k is the primary selection metric; rank IC is the
        # fallback when a very small date bucket has no portfolio statistic.
        score = metrics.get("top_k_mean_excess_return_after_cost", metrics.get("rank_ic", float("-inf")))
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = float("-inf")
        candidates.append((score, architecture))
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else "patchtst"


def _run_stage(command: list[str], log: Path, env: dict[str, str]) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        return subprocess.run(command, cwd=PROJECT, env=env, stdout=handle, stderr=subprocess.STDOUT, check=False).returncode


def _sequence_complete(root: Path, task: str, architecture: str) -> bool:
    scope = root / "cn" / "close_confirmed" / "cn_equity_core" / task / "sequence" / architecture
    return all((scope / name).is_file() and (scope / name).stat().st_size > 0 for name in ("sequence_evaluation.json", "sequence_manifest.json", "model.pt"))


def _panel_complete(root: Path, task: str, architecture: str) -> bool:
    scope = root / "cn" / "close_confirmed" / "cn_equity_core" / task / "panel" / architecture
    return all((scope / name).is_file() and (scope / name).stat().st_size > 0 for name in ("sequence_evaluation.json", "sequence_manifest.json", "model.pt"))


def main() -> int:
    args = _args()
    baseline_status = args.baseline_status if args.baseline_status.is_absolute() else PROJECT / args.baseline_status
    manifest = args.manifest_file if args.manifest_file.is_absolute() else PROJECT / args.manifest_file
    object_store = args.object_store if args.object_store.is_absolute() else PROJECT / args.object_store
    root = args.output_root if args.output_root.is_absolute() else PROJECT / args.output_root
    status_path = root / "full-automation-status.json"
    status = _read(status_path, {}) or {"schema_version": "full-research-optimization-v1", "run_id": root.name, "started_at": _now(), "stages": []}
    status.update({"status": "waiting_for_baseline", "gpu_policy": {"CUDA_VISIBLE_DEVICES": "0", "torch_device": "cuda", "parallel_gpu_stages": False}, "updated_at": _now()})
    _write(status_path, status)
    deadline = time.monotonic() + args.max_wait_hours * 3600
    while True:
        done, baseline_payload = _baseline_done(baseline_status)
        if done:
            break
        if str(baseline_payload.get("status", "")).startswith("failed") or str(baseline_payload.get("status", "")).startswith("blocked"):
            status.update({"status": "blocked_baseline", "baseline_status": baseline_payload.get("status"), "updated_at": _now()})
            _write(status_path, status)
            return 20
        if time.monotonic() >= deadline:
            status.update({"status": "blocked_baseline_timeout", "updated_at": _now()})
            _write(status_path, status)
            return 21
        time.sleep(max(5, args.wait_seconds))

    if baseline_payload.get("status") == "long_term_baseline_completed_auxiliary_short_horizon_queued":
        summary = {
            "schema_version": "research-optimization-summary-v1",
            "generated_at": _now(),
            "status": "research_only",
            "mode": "long_term_investment_quality",
            "baseline_status": baseline_payload.get("status"),
            "primary_metric": "rank_ic_and_cost_adjusted_top_k_return",
            "auxiliary_short_horizon": "observation_only",
            "next_stage": "feature_group_ablation_after_long_term_baseline_stability",
        }
        _write(root / "research-optimization-summary.json", summary)
        status.update({"status": "completed_research_only", "finished_at": _now(), "summary": str(root / "research-optimization-summary.json"), "updated_at": _now()})
        _write(status_path, status)
        return 0

    status.update({"status": "running_feature_ablations", "baseline_status": baseline_payload.get("status"), "updated_at": _now()})
    status.setdefault("selected_baselines", {})
    for task in TASKS:
        best = _baseline_architecture(root, task)
        status["selected_baselines"][task] = best
        for profile in FEATURE_PROFILES:
            key = f"ablation:{task}:{best}:{profile}"
            if key in {item.get("id") for item in status["stages"] if item.get("status") == "completed"}:
                continue
            stage = {"id": key, "kind": "feature_ablation", "task": task, "architecture": best, "feature_profile": profile, "status": "running", "started_at": _now()}
            status["stages"] = [item for item in status["stages"] if item.get("id") != key] + [stage]
            _write(status_path, status)
            output = root / "feature-ablations" / profile
            command = [sys.executable, str(PROJECT / "scripts/run_sequence_research_training.py"), "--sample-manifest-file", str(manifest), "--object-store", str(object_store), "--data-root", str(args.data_root), "--output-root", str(output), "--task", task, "--architecture", best, "--feature-profile", profile, "--window", "60", "--cohort", "cn_equity_core", "--training-run-id", f"{root.name}-ablation-{task}-{best}-{profile}", "--screen-symbols", "0", "--maximum-dates", str(args.maximum_dates)]
            log = root / "logs" / f"ablation-{task}-{best}-{profile}.log"
            exit_code = _run_stage(command, log, _env(args.batch_size))
            stage.update({"exit_code": exit_code, "status": "completed" if exit_code == 0 else "failed", "log": str(log), "finished_at": _now()})
            _write(status_path, status)
            if exit_code != 0:
                status.update({"status": "failed_feature_ablation", "updated_at": _now()})
                _write(status_path, status)
                return exit_code

    status.update({"status": "running_panel_models", "updated_at": _now()})
    for task in TASKS:
        for architecture in PANEL_ARCHITECTURES:
            key = f"panel:{task}:{architecture}"
            if _panel_complete(root, task, architecture):
                status["stages"] = [item for item in status["stages"] if item.get("id") != key] + [{"id": key, "kind": "panel_model", "task": task, "architecture": architecture, "status": "completed", "resumed": True}]
                _write(status_path, status)
                continue
            stage = {"id": key, "kind": "panel_model", "task": task, "architecture": architecture, "status": "running", "started_at": _now()}
            status["stages"] = [item for item in status["stages"] if item.get("id") != key] + [stage]
            _write(status_path, status)
            command = [sys.executable, str(PROJECT / "scripts/run_panel_research_training.py"), "--sample-manifest-file", str(manifest), "--object-store", str(object_store), "--data-root", str(args.data_root), "--output-root", str(root), "--task", task, "--architecture", architecture, "--cohort", "cn_equity_core", "--window", "60", "--maximum-dates", str(args.maximum_dates), "--batch-dates", str(args.panel_batch_dates), "--training-run-id", f"{root.name}-{task}-{architecture}"]
            log = root / "logs" / f"panel-{task}-{architecture}.log"
            exit_code = _run_stage(command, log, _env(args.batch_size))
            stage.update({"exit_code": exit_code, "status": "completed" if exit_code == 0 else "failed", "log": str(log), "finished_at": _now()})
            _write(status_path, status)
            if exit_code != 0:
                status.update({"status": "failed_panel_model", "updated_at": _now()})
                _write(status_path, status)
                return exit_code

    summary = {"schema_version": "research-optimization-summary-v1", "generated_at": _now(), "status": "research_only", "baseline_root": str(root), "selected_baselines": status.get("selected_baselines", {}), "primary_metric": "top_k_mean_excess_return_after_cost", "candidates": []}
    for task in TASKS:
        for architecture in ARCHITECTURES:
            report = root / "cn" / "close_confirmed" / "cn_equity_core" / task / "sequence" / architecture / "sequence_evaluation.json"
            payload = _read(report, {}) or {}
            summary["candidates"].append({"stage": "baseline", "task": task, "architecture": architecture, "holdout_metrics": ((payload.get("result") or {}).get("holdout_metrics") or {})})
        for architecture in PANEL_ARCHITECTURES:
            report = root / "cn" / "close_confirmed" / "cn_equity_core" / task / "panel" / architecture / "sequence_evaluation.json"
            payload = _read(report, {}) or {}
            summary["candidates"].append({"stage": "panel", "task": task, "architecture": architecture, "holdout_metrics": ((payload.get("result") or {}).get("holdout_metrics") or {})})
    _write(root / "research-optimization-summary.json", summary)
    status.update({"status": "completed_research_only", "finished_at": _now(), "summary": str(root / "research-optimization-summary.json"), "updated_at": _now()})
    _write(status_path, status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
