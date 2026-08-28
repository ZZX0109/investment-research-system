#!/usr/bin/env python3
"""Create and optionally execute the auditable CN data-completion plan.

The default mode is read-only: it inspects persisted artifacts and writes one
machine-readable plan with every missing dataset, threshold, provider option
and next command.  ``--execute --step <id>`` runs only an explicitly selected
bounded step.  No step can create an active snapshot; the existing PIT gate
remains the sole activation authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

import yaml

PROJECT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_config(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"completion_plan_unreadable:{path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
        raise ValueError("completion_plan_shape_invalid")
    return payload


def _universe_counts(root: Path) -> tuple[int, int, int]:
    universe = _read(root / "artifacts/cn_security_master_universe/latest.json")
    total = int(universe.get("row_count", 0) or 0)
    equity = int(universe.get("equity_count", 0) or 0)
    etf = int(universe.get("etf_count", 0) or 0)
    if total and not equity:
        equity = max(0, total - etf)
    return total, equity, etf


def _current_universe_symbols(root: Path) -> set[str]:
    """Return the current public denominator without falling back to 167 symbols."""
    path = root / "artifacts" / "cn_security_master_universe" / "security_master_current.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, list):
        return set()
    symbols: set[str] = set()
    for item in payload:
        value = item.get("code") if isinstance(item, dict) else item
        if value is None:
            continue
        symbols.add(str(value).strip().upper().rsplit(".", 1)[-1].zfill(6))
    return {value for value in symbols if value.isdigit() and len(value) == 6}


def _catalog_price_coverage(root: Path, target_symbols: set[str]) -> dict[str, object] | None:
    """Read broad price coverage from the append-only catalog, read-only.

    ``cn_security_master/latest.json`` only describes the last standardized
    rebuild.  Using it as a download denominator silently regressed a 5,554
    raw-price archive to the old 346-symbol manifest.  The catalog is the
    authoritative record for downloaded raw/qfq payloads; standard/PIT quality
    remains a separate gate and is reported explicitly below.
    """
    database = root / "var" / "cn-research" / "catalog.db"
    if not database.is_file() or not target_symbols:
        return None
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute(
            "SELECT dataset,payload_json FROM raw_data_batches "
            "WHERE data_tier=? AND dataset IN (?,?)",
            ("research_pit", "daily_bars_raw", "daily_bars_qfq"),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    raw: set[str] = set()
    qfq: set[str] = set()
    for dataset, payload_json in rows:
        try:
            payload = json.loads(str(payload_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        value = payload.get("symbol") if isinstance(payload, dict) else None
        if value is None:
            continue
        symbol = str(value).strip().upper().rsplit(".", 1)[-1].zfill(6)
        if symbol not in target_symbols:
            continue
        if dataset == "daily_bars_raw":
            raw.add(symbol)
        elif dataset == "daily_bars_qfq":
            qfq.add(symbol)
    benchmark_etfs = {"510050", "510300", "510500", "159915", "512100"}
    model_scope = {
        symbol for symbol in target_symbols
        if symbol.startswith(("0", "3", "6")) or symbol in benchmark_etfs
    }
    return {
        "raw_covered_symbols": len(raw),
        "raw_coverage_ratio": len(raw) / len(target_symbols),
        "qfq_covered_symbols": len(qfq),
        "qfq_coverage_ratio": len(qfq) / len(target_symbols),
        "model_scope_symbols": len(model_scope),
        "model_scope_qfq_symbols": len(model_scope & raw & qfq),
        "model_scope_qfq_coverage_ratio": (
            len(model_scope & raw & qfq) / len(model_scope) if model_scope else None
        ),
        "quote_only_symbols": len(raw - model_scope),
        "qfq_missing_symbols": len(target_symbols - qfq),
    }


def _ratio(value: object, denominator: float | None = None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if denominator is not None and denominator > 0 and number > 1:
        number /= denominator
    return number


def _step_evidence(step: dict, root: Path, universe_total: int, equity_total: int) -> tuple[str, dict, list[str]]:
    step_id = str(step.get("id"))
    artifact = root / str(step.get("artifact", ""))
    report = _read(artifact)
    if not report:
        if step_id in {
            "financial_core_bulk_reports",
            "financial_income_bulk_reports",
            "financial_cashflow_bulk_reports",
            "financial_balance_bulk_reports",
        }:
            landing = _financial_landing_progress(root, step_id)
            if landing is not None:
                return (
                    "partial" if landing["completed_period_count"] else "pending",
                    landing,
                    ["core_financial_bulk_download_or_publication_coverage_incomplete"],
                )
        if step_id == "financial_statement_landing_import":
            landing = _all_financial_landing_progress(root)
            if landing is not None:
                return (
                    "partial" if landing["completed_period_count"] < landing["target_period_count"] else "pending",
                    landing,
                    ["financial_landing_import_not_run_after_landing"]
                    if landing["completed_period_count"] >= landing["target_period_count"]
                    else ["core_financial_bulk_download_or_publication_coverage_incomplete"],
                )
        return "pending", {"artifact_exists": artifact.is_file()}, ["artifact_missing"]

    if step_id == "security_universe":
        observed = int(report.get("row_count", 0) or 0)
        passed = observed >= max(universe_total, 1) and report.get("status") in {"complete", "research_only"}
        return ("complete" if passed else "partial"), {"row_count": observed, "target": universe_total, "quality_status": report.get("quality_status")}, [] if passed else ["current_universe_incomplete"]

    if step_id == "historical_prices":
        catalog = _catalog_price_coverage(root, _current_universe_symbols(root))
        if catalog is not None:
            raw_coverage = float(catalog["raw_coverage_ratio"])
            qfq_coverage = float(catalog["qfq_coverage_ratio"])
            # ``research_ready`` is a valid data-layer quality state here:
            # it means the standardized market data is usable for research,
            # while formal PIT eligibility remains a separate gate.  Do not
            # regress a full catalog backfill to ``partial`` merely because
            # the security-master report correctly refuses deployment.
            quality_status = str(report.get("quality_status") or report.get("status") or "")
            quality_ok = quality_status in {"complete", "research_ready"}
            passed = raw_coverage >= 0.995 and qfq_coverage >= 0.995 and quality_ok
            reasons: list[str] = []
            if raw_coverage < 0.995:
                reasons.append("raw_price_coverage_below_99_5pct")
            if qfq_coverage < 0.995:
                reasons.append("front_adjusted_price_coverage_below_99_5pct")
            if not quality_ok:
                reasons.append("price_quality_not_complete")
            return (
                "complete" if passed else "partial",
                catalog | {
                    "target_symbols": universe_total,
                    "legacy_standard_manifest_symbols": int(report.get("daily_bar_symbol_count", 0) or 0),
                    "quality_status": quality_status,
                    "coverage_source": "append_only_catalog",
                },
                reasons,
            )
        observed = int(report.get("daily_bar_symbol_count", 0) or 0)
        coverage = observed / universe_total if universe_total else 0.0
        passed = coverage >= 0.995 and report.get("quality_status") == "complete"
        return ("complete" if passed else "partial"), {"covered_symbols": observed, "target_symbols": universe_total, "coverage_ratio": coverage, "quality_status": report.get("quality_status")}, [] if passed else ["price_coverage_below_99_5pct", "quality_not_complete"]

    if step_id == "security_lifecycle":
        # Code/name changes are rare events.  When the artifact exposes a
        # record-level denominator, use it; the raw event count divided by the
        # full universe is a breadth statistic and would incorrectly mark a
        # complete known-event table as incomplete.
        fields = {
            "listing_date_coverage": _ratio(report.get("listing_date_coverage")),
            "delisting_date_coverage": _ratio(report.get("delisting_date_coverage")),
            "st_status_coverage": _ratio(report.get("st_status_coverage")),
            "code_change_coverage": _ratio(
                report.get("code_change_record_coverage", report.get("code_change_coverage"))
            ),
            # Keep the breadth of known code-migration symbols visible next to
            # the record-quality metric used by the gate.  A rare event should
            # not be expected on every security, but its breadth must not be
            # silently hidden either.
            "code_change_symbol_coverage": _ratio(report.get("code_change_coverage")),
            "code_change_record_coverage": _ratio(report.get("code_change_record_coverage")),
        }
        report_status = str(report.get("status") or "")
        quality_status = str(report.get("quality_status") or "")
        # The consolidated lifecycle artifact intentionally keeps
        # ``research_only=true`` and ``deployment_ready=false`` while using
        # ``status=complete`` for data-field completeness.  Formal PIT is
        # checked by the publication/active-snapshot gates, not duplicated
        # here.
        data_complete = report_status == "complete" or quality_status in {"complete", "research_ready"}
        gate_fields = {
            name: value for name, value in fields.items()
            if name not in {"code_change_symbol_coverage", "code_change_record_coverage"}
        }
        passed = data_complete and all(value is not None and value >= 0.98 for value in gate_fields.values())
        return (
            "complete" if passed else "partial",
            fields | {"status": report_status, "quality_status": quality_status},
            [] if passed else [
                f"lifecycle_{name}_below_98pct"
                for name, value in gate_fields.items()
                if value is None or value < 0.98
            ],
        )

    if step_id in {"security_status_evidence", "security_name_history"}:
        target_count = int(report.get("target_equity_count", 0) or 0)
        completed_count = int(report.get("completed_equity_count", 0) or 0)
        passed = report.get("status") == "complete" and target_count >= equity_total and completed_count >= equity_total
        reason = f"{step_id}_scope_or_download_incomplete"
        return (
            "complete" if passed else "partial",
            {
                "status": report.get("status"),
                "target_equity_count": target_count,
                "completed_equity_count": completed_count,
                "published_at_coverage": report.get("published_at_coverage"),
            },
            [] if passed else [reason],
        )

    if step_id == "financial_publication_pit":
        fields = {"coverage": _ratio(report.get("coverage")), "published_at_coverage": _ratio(report.get("published_at_coverage")), "pit_verified": report.get("pit_verified")}
        passed = report.get("quality_status") == "complete" and (fields["coverage"] or 0) >= 0.98 and fields["pit_verified"] is True
        return ("complete" if passed else "partial"), fields | {"quality_status": report.get("quality_status")}, [] if passed else ["financial_coverage_or_pit_incomplete"]

    if step_id in {
        "financial_core_bulk_reports",
        "financial_income_bulk_reports",
        "financial_cashflow_bulk_reports",
        "financial_balance_bulk_reports",
    }:
        target = int(report.get("target_period_count", 0) or 0)
        completed = int(report.get("completed_period_count", 0) or 0)
        publication = _ratio(report.get("published_at_coverage"))
        passed = report.get("status") == "complete" and target > 0 and completed >= target and (publication or 0) >= 0.98
        return (
            "complete" if passed else "partial",
            {
                "status": report.get("status"),
                "target_period_count": target,
                "completed_period_count": completed,
                "row_count": report.get("row_count"),
                "published_at_coverage": publication,
                "research_only": report.get("research_only"),
            },
            [] if passed else ["core_financial_bulk_download_or_publication_coverage_incomplete"],
        )

    if step_id == "financial_statement_landing_import":
        landing = _all_financial_landing_progress(root)
        if landing is not None and landing["completed_period_count"] < landing["target_period_count"]:
            return (
                "partial",
                landing | {"import_artifact_status": report.get("status"), "dry_run": bool(report.get("dry_run"))},
                ["core_financial_bulk_download_or_publication_coverage_incomplete"],
            )
        target_periods = int(report.get("target_period_count", 0) or 0)
        completed_periods = int(report.get("completed_period_count", 0) or 0)
        source_rows = int(report.get("source_row_count", 0) or 0)
        matched_rows = int(report.get("matched_source_row_count", 0) or 0)
        coverage = matched_rows / source_rows if source_rows else 0.0
        passed = (
            report.get("status") == "complete"
            and not bool(report.get("dry_run"))
            and target_periods > 0
            and completed_periods >= target_periods
            and coverage >= 0.98
        )
        return (
            "complete" if passed else "partial",
            {
                "status": report.get("status"),
                "target_period_count": target_periods,
                "completed_period_count": completed_periods,
                "source_row_count": source_rows,
                "matched_source_row_count": matched_rows,
                "publication_join_coverage": coverage,
                "imported_row_count": report.get("imported_row_count"),
                "dry_run": bool(report.get("dry_run")),
            },
            [] if passed else ["financial_landing_import_or_publication_mapping_incomplete"],
        )

    if step_id == "financial_pit_reconciliation":
        verified = report.get("formal_pit_verified") is True
        passed = report.get("status") == "complete" and verified
        return (
            "complete" if passed else "partial",
            {"status": report.get("status"), "formal_pit_verified": report.get("formal_pit_verified"), "pit_report_ref": report.get("pit_report_ref")},
            [] if passed else ["financial_pit_reconciliation_unverified"],
        )

    if step_id == "financial_extended_ratios":
        # While the all-universe worker is running, latest.json still points
        # at the historical 162-name research target.  Prefer its versioned
        # resumable ledger so the plan exposes the real 5,549-equity
        # denominator and never reports a stale completion.
        progress = _read(root / "artifacts/cn_financial_ratios_akshare/progress.json")
        target_equities = int(progress.get("target_equity_count", 0) or 0)
        contract_version = progress.get("metric_contract_version")
        symbols = progress.get("symbols") if isinstance(progress.get("symbols"), dict) else {}
        if target_equities > 0 and contract_version:
            completed_equities = sum(
                1 for item in symbols.values()
                if isinstance(item, dict)
                and item.get("status") == "complete"
                and item.get("metric_contract_version") == contract_version
            )
            coverage = completed_equities / target_equities
            return (
                "complete" if coverage >= 0.95 else "partial",
                {
                    "coverage": coverage,
                    "target_equity_count": target_equities,
                    "completed_equity_count": completed_equities,
                    "metric_contract_version": contract_version,
                    "quality_status": report.get("quality_status"),
                    "low_coverage_fields": report.get("low_coverage_fields", []),
                },
                [] if coverage >= 0.95 else ["extended_financial_fields_incomplete"],
            )
        coverage = _ratio(report.get("coverage"))
        passed = report.get("quality_status") == "complete" and (coverage or 0) >= 0.95
        return ("complete" if passed else "partial"), {"coverage": coverage, "quality_status": report.get("quality_status"), "low_coverage_fields": report.get("low_coverage_fields", [])}, [] if passed else ["extended_financial_fields_incomplete"]

    if step_id in {"corporate_actions", "events_and_filings"}:
        status = str(report.get("status", "unknown"))
        target_count = int(report.get("target_equity_count", 0) or 0)
        completed_count = int(report.get("completed_equity_count", 0) or 0)
        passed = status == "complete" and completed_count >= equity_total and report.get("deployment_ready") is False
        reasons = [] if passed else [f"{step_id}_coverage_incomplete"]
        if target_count < equity_total:
            reasons.append(f"{step_id}_target_scope_is_{target_count}_not_{equity_total}")
        return ("complete" if passed else "partial"), {key: report.get(key) for key in ("status", "target_equity_count", "completed_equity_count", "row_count", "published_at_coverage")}, reasons

    if step_id == "macro_release_times":
        coverage = _ratio(report.get("published_at_coverage"))
        passed = report.get("quality_status") == "complete" and (coverage or 0) >= 0.98
        return ("complete" if passed else "partial"), {"published_at_coverage": coverage, "quality_status": report.get("quality_status"), "record_count": report.get("record_count")}, [] if passed else ["macro_publication_time_incomplete"]

    if step_id == "standard_and_quality_rebuild":
        count = int(report.get("standard_manifest_count", 0) or 0)
        passed = count > 0 and report.get("status") == "research_only" and report.get("formal_pit_eligible") is False
        return ("complete" if passed else "partial"), {"standard_manifest_count": count, "status": report.get("status"), "formal_pit_eligible": report.get("formal_pit_eligible")}, [] if passed else ["standard_layer_missing_or_unverified"]

    if step_id == "research_sample_layer":
        context = report.get("contexts", {}).get("close_confirmed", {}) if isinstance(report, dict) else {}
        manifests = context.get("sample_manifests", {}) if isinstance(context, dict) else {}
        count = sum(len(value) for value in manifests.values() if isinstance(value, list))
        staging_count = 0
        staging_symbols: set[str] = set()
        snapshot_id = context.get("snapshot_id") if isinstance(context, dict) else None
        snapshot_hash = context.get("snapshot_hash") if isinstance(context, dict) else None
        staging_root = PROJECT / "artifacts" / "free_research_sample_batches"
        if staging_root.is_dir() and snapshot_hash:
            for path in staging_root.glob("*/samples/*/*/*/*.json"):
                payload = _read(path)
                if (
                    payload.get("market_snapshot_id") == snapshot_id
                    and payload.get("market_snapshot_hash") == snapshot_hash
                    and payload.get("sample_parquet_ref")
                ):
                    staging_count += 1
                    if payload.get("symbol"):
                        staging_symbols.add(str(payload["symbol"]).rsplit(".", 1)[-1].zfill(6))
        # A sample layer is useful only when it is bound to the same immutable
        # snapshot as the rebuild index.  Keep the count visible even when a
        # broad standard-only rebuild intentionally skipped samples.
        passed = (
            report.get("status") == "research_only"
            and count > 0
            and bool(context.get("snapshot_id"))
            and bool(context.get("snapshot_hash"))
        )
        return (
            "complete" if passed else "partial",
            {
                "sample_manifest_count": count,
                "staging_sample_manifest_count": staging_count,
                "staging_symbol_count": len(staging_symbols),
                "snapshot_id": snapshot_id,
                "snapshot_hash": snapshot_hash,
                "research_only": report.get("status") == "research_only",
            },
            [] if passed else [
                "research_sample_manifests_missing_or_unbound",
                *(["sample_batches_staging_not_promoted"] if staging_count else []),
            ],
        )

    if step_id == "shadow_60_validation":
        valid_dates = int(report.get("valid_trade_date_count", report.get("valid_session_count", 0)) or 0)
        minimum = int(report.get("minimum_required_trade_dates", 60) or 60)
        passed = report.get("status") == "complete" and valid_dates >= minimum and report.get("deployment_ready") is False
        return (
            "complete" if passed else "partial",
            {
                "status": report.get("status"),
                "valid_trade_date_count": valid_dates,
                "minimum_required_trade_dates": minimum,
                "deployment_ready": report.get("deployment_ready"),
            },
            [] if passed else ["shadow_independent_trade_dates_below_60"],
        )

    if step_id == "audit_and_active_gate":
        passed = report.get("status") == "ready_for_long_term_training" and report.get("deployment_ready") is False
        return ("complete" if passed else "blocked"), {"status": report.get("status"), "blocking_reasons": report.get("blocking_reasons", [])}, [] if passed else ["active_snapshot_gate_not_passed"]

    passed = report.get("status") in {"complete", "passed", "ready_for_long_term_training"}
    return ("complete" if passed else "partial"), {"status": report.get("status")}, [] if passed else ["step_not_complete"]


def _financial_landing_progress(root: Path, step_id: str) -> dict[str, object] | None:
    """Expose an in-flight immutable landing run before its final report exists."""
    family = {
        "financial_core_bulk_reports": "performance",
        "financial_income_bulk_reports": "income",
        "financial_cashflow_bulk_reports": "cashflow",
        "financial_balance_bulk_reports": "balance",
    }.get(step_id)
    if family is None:
        return None
    base = root / "artifacts" / "cn_financial_reports_eastmoney" / "landing"
    manifests = sorted(base.glob(f"eastmoney-{family}-*/manifest.json"))
    if not manifests:
        return None
    manifest = _read(manifests[-1])
    periods = manifest.get("periods") if isinstance(manifest, dict) else None
    if not isinstance(periods, dict):
        return None
    states = [value for value in periods.values() if isinstance(value, dict)]
    completed = [value for value in states if value.get("status") == "complete"]
    rows = sum(int(value.get("record_count", 0) or 0) for value in completed)
    published = sum(int(value.get("published_at_count", 0) or 0) for value in completed)
    return {
        "status": manifest.get("status", "running"),
        "run_id": manifest.get("run_id"),
        "landing_manifest": str(manifests[-1]),
        "target_period_count": len(states),
        "completed_period_count": len(completed),
        "row_count": rows,
        "published_at_coverage": published / rows if rows else 0.0,
        "research_only": True,
    }


def _all_financial_landing_progress(root: Path) -> dict[str, object] | None:
    """Aggregate all four statement manifests for the import gate."""
    base = root / "artifacts" / "cn_financial_reports_eastmoney" / "landing"
    output: dict[str, dict[str, int]] = {}
    for family in ("performance", "income", "cashflow", "balance"):
        manifests = sorted(base.glob(f"eastmoney-{family}-*/manifest.json"))
        if not manifests:
            return None
        manifest = _read(manifests[-1])
        periods = manifest.get("periods") if isinstance(manifest, dict) else None
        if not isinstance(periods, dict):
            return None
        states = [item for item in periods.values() if isinstance(item, dict)]
        output[family] = {
            "target_period_count": len(states),
            "completed_period_count": sum(item.get("status") == "complete" for item in states),
        }
    target = sum(item["target_period_count"] for item in output.values())
    completed = sum(item["completed_period_count"] for item in output.values())
    return {
        "target_period_count": target,
        "completed_period_count": completed,
        "family_progress": output,
        "status": "complete" if completed >= target and target else "running",
    }


def build_plan(project_root: Path = PROJECT, *, config_path: Path | None = None) -> dict:
    root = project_root.resolve()
    config = _load_config((config_path or root / "config/cn_data_completion_plan.yaml").resolve())
    universe_total, equity_count, etf_count = _universe_counts(root)
    steps: list[dict[str, Any]] = []
    for raw in config["steps"]:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        status, evidence, reasons = _step_evidence(raw, root, universe_total, equity_count)
        command = [sys.executable]
        for value in raw.get("command", []):
            value = str(value)
            command.append(str(root / value) if value.startswith("scripts/") else value)
        steps.append({
            "id": str(raw["id"]),
            "priority": raw.get("priority", "P1"),
            "dataset": raw.get("dataset"),
            "status": status,
            "required": bool(raw.get("required", True)),
            "artifact_ref": str(root / str(raw.get("artifact", ""))),
            "evidence": evidence,
            "blocking_reasons": reasons,
            "provider_options": list(raw.get("provider_options", [])),
            "license_required_for_formal": bool(raw.get("license_required_for_formal", False)),
            "command": command,
            "depends_on": list(raw.get("depends_on", [])),
        })
    missing = [item for item in steps if item["status"] != "complete"]
    p0_missing = [item["id"] for item in missing if item["priority"] == "P0"]
    return {
        "schema_version": "cn-data-completion-plan-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if not missing else "blocked",
        "formal_pit_eligible": False,
        "deployment_ready": False,
        "target": {"total": universe_total, "equities": equity_count, "etfs": etf_count, "universe_ref": str(root / str(config["target"]["universe"]))},
        "step_count": len(steps),
        "completed_step_count": len(steps) - len(missing),
        "missing_step_count": len(missing),
        "p0_missing_steps": p0_missing,
        "steps": steps,
        "activation_rule": "all P0/P1 dataset gates, PIT leakage=0, immutable snapshot and model/Shadow/Agent gates must pass; this plan never writes active.json",
    }


def _execute_steps(plan: dict, selected: set[str], *, root: Path, timeout: int) -> list[dict]:
    results = []
    by_id = {item["id"]: item for item in plan.get("steps", [])}
    for step_id in sorted(selected):
        item = by_id.get(step_id)
        if item is None:
            results.append({"id": step_id, "status": "unknown_step"})
            continue
        started = datetime.now(timezone.utc)
        try:
            completed = subprocess.run(item["command"], cwd=root, capture_output=True, text=True, timeout=timeout, check=False)
            status = "completed" if completed.returncode == 0 else "failed"
            results.append({"id": step_id, "status": status, "return_code": completed.returncode, "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]})
        except subprocess.TimeoutExpired as exc:
            results.append({"id": step_id, "status": "timed_out", "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "stdout": str(exc.stdout or "")[-4000:], "stderr": str(exc.stderr or "")[-4000:]})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_data_completion_plan/latest.json")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--step", action="append", default=[], help="explicit step id; repeat to execute selected steps")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args()
    if args.execute and not args.step:
        parser.error("--execute requires at least one --step; this prevents accidental full-universe runs")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    root = args.project_root.resolve()
    output = args.output.resolve()
    plan = build_plan(root, config_path=args.config)
    if args.execute:
        plan["execution"] = _execute_steps(plan, set(args.step), root=root, timeout=args.timeout_seconds)
        plan = build_plan(root, config_path=args.config) | {"execution": plan["execution"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"status": plan["status"], "completed_step_count": plan["completed_step_count"], "missing_step_count": plan["missing_step_count"], "output": str(output)}, ensure_ascii=False))
    return 0 if plan["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
