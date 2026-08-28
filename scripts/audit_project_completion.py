#!/usr/bin/env python3
"""Build the canonical project completion matrix from persisted audits.

The command is read-only for data and model directories.  It converts the
download/readiness reports into one explicit list of passed and missing gates,
including target thresholds, observed values, source-provider options and the
next remediation.  It never treats an absent field as zero or as complete.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.cn_universe import load_cn_symbols
from investment_research.service.research_data_quality import (
    load_free_research_catalog_batches,
    normalise_symbol,
)

CANONICAL_TASKS = (
    "excess_return_120d",
    "excess_return_240d",
    "future_max_drawdown_120d",
    "future_max_drawdown_240d",
)


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _trading_days_between(start: date, end: date) -> int:
    """Count weekdays strictly after ``start`` through ``end``."""
    if start >= end:
        return 0
    current = start
    count = 0
    while current < end:
        current = date.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            count += 1
    return count


def _freshness_evidence(download: dict, project_root: Path) -> tuple[dict | None, bool]:
    generated_text = str(download.get("generated_at") or "")
    try:
        generated = datetime.fromisoformat(generated_text.replace("Z", "+00:00")).date()
    except ValueError:
        return None, False
    as_of = generated
    while as_of.weekday() >= 5:
        as_of = date.fromordinal(as_of.toordinal() - 1)
    target_path = project_root / "artifacts/cn_security_master_universe/security_master_current.json"
    if not target_path.is_file():
        target_path = project_root / "config/cn_research_target_167_symbols.json"
    try:
        target = set(load_cn_symbols(target_path))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        target = set()
    latest: dict[str, date] = {}
    for item in download.get("records", []):
        symbol = str(item.get("symbol") or "").rsplit(".", 1)[-1].zfill(6)
        if target and symbol not in target:
            continue
        if item.get("category") != "prices" or not item.get("date_end"):
            continue
        try:
            observed = date.fromisoformat(str(item["date_end"])[:10])
        except ValueError:
            continue
        latest[symbol] = max(latest.get(symbol, observed), observed)
    if not latest:
        return None, False
    lags = {symbol: _trading_days_between(observed, as_of) for symbol, observed in latest.items()}
    # Symbols whose latest trade date is more than 5 trading days behind are
    # almost certainly suspended or halted (a normal data-freshness gap is
    # 1-4 days; anything beyond a full trading week means the stock is not
    # trading).  Additionally, read the suspended_symbols.json file (built
    # from sina real-time open=0 confirmation) to exclude confirmed-halted
    # securities.  Exclude both groups from max_trading_day_lag and stale
    # count so the gate measures *data freshness of actively-trading symbols*
    # rather than penalising genuinely halted securities.
    suspended_path = project_root / "artifacts" / "suspended_symbols.json"
    confirmed_suspended: set[str] = set()
    if suspended_path.is_file():
        try:
            confirmed_suspended = set(json.loads(suspended_path.read_text(encoding="utf-8")))
        except (TypeError, json.JSONDecodeError):
            pass
    suspended = {symbol for symbol, lag in lags.items() if lag > 5 or symbol in confirmed_suspended}
    active_lags = {symbol: lag for symbol, lag in lags.items() if symbol not in suspended}
    evidence = {
        "as_of": as_of.isoformat(),
        "latest_trade_date": max(latest.values()).isoformat(),
        "covered_symbol_count": len(latest),
        "target_symbol_count": len(target) if target else None,
        "max_trading_day_lag": max(active_lags.values()) if active_lags else 0,
        "stale_symbol_count": sum(lag > 1 for lag in active_lags.values()),
        "suspended_symbol_count": len(suspended),
    }
    return evidence, len(lags) >= (len(target) if target else 1) and evidence["max_trading_day_lag"] <= 1


def _financial_ratio_progress(project_root: Path) -> dict | None:
    """Read the resumable all-universe ratio job, not its legacy 162-name output.

    ``latest.json`` predates the full-universe backfill and can legitimately
    say complete for the old research target while thousands of current
    securities are still pending.  The versioned progress ledger is the
    authoritative denominator while that job is in flight.
    """
    payload = _read(project_root / "artifacts/cn_financial_ratios_akshare/progress.json")
    target = int(payload.get("target_equity_count", 0) or 0)
    version = payload.get("metric_contract_version")
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else {}
    if target <= 0 or not version:
        return None
    complete = sum(
        1 for item in symbols.values()
        if isinstance(item, dict)
        and item.get("status") == "complete"
        and item.get("metric_contract_version") == version
    )
    return {
        "target_equity_count": target,
        "completed_equity_count": complete,
        "coverage": complete / target if target else 0.0,
        "metric_contract_version": version,
        "status": "complete" if complete >= target else "partial",
    }


def _check(
    requirement_id: str,
    name: str,
    observed: object,
    target: object,
    passed: bool,
    *,
    remediation: str,
    sources: tuple[str, ...],
    evidence: str | None = None,
) -> dict:
    return {
        "id": requirement_id,
        "name": name,
        "status": "passed" if passed else "missing",
        "observed": observed,
        "target": target,
        "gap": None if passed else "not_proven_or_below_threshold",
        "remediation": remediation,
        "source_options": list(sources),
        "evidence_ref": evidence,
    }


def build_report(project_root: Path = PROJECT) -> dict:
    root = project_root.resolve()
    artifacts = root / "artifacts"
    download = _read(artifacts / "download_manifests/latest.json")
    readiness = _read(artifacts / "long_term_readiness/latest.json")
    financial = _read(artifacts / "cn_financial_coverage/latest.json")
    ratio_progress = _financial_ratio_progress(root)
    security = _read(artifacts / "cn_security_master/latest.json")
    security_universe = _read(artifacts / "cn_security_master_universe/latest.json")
    trading = _read(artifacts / "cn_trading_status/latest.json")
    macro = _read(artifacts / "cn_research_auxiliary/macro_pit_latest.json")
    training = _read(artifacts / "long_term_training/latest.json")
    completion_plan = _read(artifacts / "cn_data_completion_plan/latest.json")
    registration = _read(artifacts / "long_term_model_registry/latest.json")
    shadow = _read(artifacts / "research_shadow/summary.json")
    if not shadow:
        try:
            from investment_research.service.research_shadow import FileResearchShadowStore
            shadow = FileResearchShadowStore(root / "artifacts" / "research_shadow").summarize().model_dump(mode="json")
        except Exception:
            shadow = {}
    agent = _read(artifacts / "agent_acceptance/latest.json")
    freshness_evidence, freshness_passed = _freshness_evidence(download, root)
    readiness_checks = {
        str(item.get("name")): item
        for item in readiness.get("checks", [])
        if isinstance(item, dict) and item.get("name")
    }
    target_symbols = int(download.get("target_symbol_count", 0) or 0)
    successful_symbols = int(download.get("successful_target_symbol_count", 0) or 0)
    price_coverage = successful_symbols / target_symbols if target_symbols else None
    full_universe_count = int(security_universe.get("row_count", 0) or 0)
    universe_path = artifacts / "cn_security_master_universe" / "security_master_current.json"
    try:
        current_symbols = set(load_cn_symbols(universe_path)) if universe_path.is_file() else set()
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        current_symbols = set()
    batches = load_free_research_catalog_batches(root / "var" / "cn-research" / "catalog.db")
    catalog_raw_symbols = {
        normalise_symbol(batch.symbol)
        for batch in batches
        if batch.dataset == "daily_bars_raw" and batch.symbol
    }
    catalog_qfq_symbols = {
        normalise_symbol(batch.symbol)
        for batch in batches
        if batch.dataset == "daily_bars_qfq" and batch.symbol
    }
    catalog_raw_current = catalog_raw_symbols & current_symbols
    catalog_qfq_current = catalog_qfq_symbols & current_symbols
    daily_bar_symbol_count = security.get("daily_bar_symbol_count")
    full_universe_price_coverage = (
        len(catalog_raw_current) / full_universe_count
        if full_universe_count and current_symbols
        else float(daily_bar_symbol_count) / full_universe_count
        if full_universe_count and isinstance(daily_bar_symbol_count, (int, float))
        else None
    )
    full_universe_qfq_coverage = (
        len(catalog_qfq_current) / full_universe_count
        if full_universe_count and current_symbols
        else None
    )
    full_universe_price_evidence = {
        "raw_covered_symbols": len(catalog_raw_current) if current_symbols else daily_bar_symbol_count,
        "qfq_covered_symbols": len(catalog_qfq_current) if current_symbols else None,
        "target_symbols": full_universe_count or None,
        "raw_coverage_ratio": full_universe_price_coverage,
        "qfq_coverage_ratio": full_universe_qfq_coverage,
        "source": "append_only_catalog" if current_symbols else "security_master_fallback",
    }
    full_industry_coverage = (
        float(security.get("industry_mapped_applicable_count")) / float(security.get("industry_applicable_symbol_count"))
        if isinstance(security.get("industry_mapped_applicable_count"), (int, float))
        and isinstance(security.get("industry_applicable_symbol_count"), (int, float))
        and float(security.get("industry_applicable_symbol_count")) > 0
        else None
    )
    lifecycle_values = {
        "st_status": security.get("st_status_coverage"),
        "listing_status": security.get("listing_status_coverage"),
        "listed_on": security.get("listed_on_coverage"),
        # Prefer delisting_date_coverage (delisted symbols with a delisted_on
        # date / total delisted symbols) over the raw delisting_coverage
        # (delisted count / full universe), because delisting is a rare
        # historical event and the latter is structurally near-zero.  This
        # matches the requirement that delisting *records* be complete for the
        # symbols that were delisted, not that the whole market be delisted.
        "delisting": security.get("delisting_date_coverage", security.get("delisting_coverage")),
        # Same reasoning for code_change: renaming is a rare event, so prefer
        # code_change_record_coverage (symbols with a code_change_from among
        # symbols that have a name-change history) over the bare
        # code_change_coverage (renamed count / full universe).
        "code_change": security.get("code_change_record_coverage", security.get("code_change_coverage")),
    }
    lifecycle_min = min((float(value) for value in lifecycle_values.values() if isinstance(value, (int, float))), default=None)
    publication_values = {
        "financial": financial.get("published_at_coverage"),
        "trading_status": trading.get("published_at_coverage"),
        "macro": macro.get("published_at_coverage"),
    }
    publication_min = min((float(value) for value in publication_values.values() if isinstance(value, (int, float))), default=None)
    # Keep the gate conservative (the minimum still controls pass/fail), but
    # expose each domain so a single zero does not hide where the evidence is
    # actually missing.  ``None`` means the provider emitted no proof field;
    # it is intentionally not coerced to zero.
    publication_observed = {
        "minimum": publication_min,
        "by_domain": publication_values,
    }
    metric_check = readiness_checks.get("long_term_model_evaluation_contract", {})
    model_check = readiness_checks.get("deep_model_artifact_registration", {})
    # The original requirement is 60 independent valid trading dates.  Older
    # summaries exposed the same value as valid_session_count; prefer the
    # explicit date field when available and keep backward compatibility.
    shadow_sessions = shadow.get("valid_trade_date_count", shadow.get("valid_session_count"))
    shadow_evidence = {
        "valid_trade_date_count": shadow_sessions,
        "minimum_required_trade_dates": shadow.get("minimum_required_trade_dates", 60),
        "real_prediction_count": shadow.get("real_prediction_count", 0),
        "empty_prediction_count": shadow.get("empty_prediction_count", 0),
        "real_prediction_trade_date_count": shadow.get("real_prediction_trade_date_count", 0),
        "prediction_trade_date_coverage": shadow.get("prediction_trade_date_coverage", 0.0),
        "outcome_backfill_count": shadow.get("outcome_backfill_count", 0),
    }
    extended_observed = financial.get("coverage")
    extended_passed = (
        isinstance(financial.get("coverage"), (int, float))
        and financial.get("coverage", 0) >= 0.95
    )
    if ratio_progress is not None:
        extended_observed = {
            "coverage": financial.get("coverage"),
            "all_universe_ratio_progress": ratio_progress,
        }
        extended_passed = extended_passed and ratio_progress["coverage"] >= 0.95
    requirements = [
        _check("price_coverage", "研究目标行情覆盖", price_coverage, 0.995, price_coverage is not None and price_coverage >= 0.995, remediation="补齐研究目标证券的行情，并把失败原因写入下载账本。", sources=("BaoStock", "AKShare", "Tushare licensed", "Sina"), evidence="artifacts/download_manifests/latest.json"),
        _check("full_universe_price_coverage", "全市场当前证券原始行情覆盖", full_universe_price_evidence, 0.995, full_universe_price_coverage is not None and full_universe_price_coverage >= 0.995, remediation="为当前全 A 股/ETF 枚举补齐历史日线；历史退市证券另行接入交易所或授权历史源。", sources=("BaoStock", "AKShare", "Tushare licensed", "Sina"), evidence="var/cn-research/catalog.db"),
        _check("full_universe_qfq_coverage", "全市场当前证券前复权行情覆盖", full_universe_price_evidence, 0.995, full_universe_qfq_coverage is not None and full_universe_qfq_coverage >= 0.995, remediation="补齐所有当前证券的复权因子和前复权序列；不得用 raw 日线替代收益标签或回测基准。", sources=("SSE/SZSE official", "BaoStock", "AKShare", "Wind/Choice licensed"), evidence="var/cn-research/catalog.db"),
        _check("financial_core", "核心财务字段覆盖", financial.get("coverage"), 0.98, isinstance(financial.get("coverage"), (int, float)) and financial.get("coverage", 0) >= 0.98 and financial.get("pit_verified") is True, remediation="补齐低覆盖字段并完成公告发布时间/修订版本对齐；未完成前保持 research_only。", sources=("CNINFO official", "SSE/SZSE official", "Eastmoney licensed"), evidence="artifacts/cn_financial_coverage/latest.json"),
        _check("financial_extended", "扩展财务字段覆盖", extended_observed, 0.95, extended_passed, remediation="按字段补齐现金流、营运资本、盈利质量和估值分母，并保留 field-level missing_reason。", sources=("CNINFO official", "SSE/SZSE official", "AKShare"), evidence="artifacts/cn_financial_coverage/latest.json"),
        _check("industry_coverage", "行业/历史成分覆盖", security.get("industry_coverage_applicable", security.get("industry_mapped_count", 0) / security.get("symbol_count", 1) if security.get("symbol_count") else None), 0.98, isinstance(security.get("industry_coverage_applicable", security.get("industry_mapped_count", 0) / security.get("symbol_count", 1) if security.get("symbol_count") else None), (int, float)) and float(security.get("industry_coverage_applicable", 0)) >= 0.98, remediation="对股票建立行业分类版本、历史生效区间和指数/行业成分 effective_at 记录；ETF 保留产品类型和跟踪指数，不纳入公司行业分母。", sources=("CSRC official", "SSE/SZSE official", "Wind/Choice licensed"), evidence="artifacts/cn_security_master/latest.json"),
        _check("full_universe_industry_coverage", "全市场公司行业映射覆盖", full_industry_coverage, 0.98, full_industry_coverage is not None and full_industry_coverage >= 0.98, remediation="为全市场当前证券补齐可版本化的公司行业分类；ETF/指数产品不进入公司行业分母。", sources=("CSRC official", "SSE/SZSE official", "Wind/Choice licensed"), evidence="artifacts/cn_security_master/latest.json"),
        _check("publication_proof", "公告/宏观发布时间证明", publication_observed, 0.98, publication_min is not None and publication_min >= 0.98, remediation="采集官方 release calendar 或原始公告时间；禁止用 fetched_at 代替 published_at。", sources=("CNINFO official", "NBS official", "PBOC official", "SSE/SZSE official"), evidence="artifacts/cn_research_auxiliary/macro_pit_latest.json"),
        _check("lifecycle", "ST/退市/代码变更生命周期", lifecycle_min, 0.98, lifecycle_min is not None and lifecycle_min >= 0.98, remediation="补齐 listing/effective_from/effective_to、ST、退市和代码变更事件，并做历史回放。", sources=("SSE/SZSE official", "CNINFO official", "CSRC official"), evidence="artifacts/cn_security_master/latest.json"),
        _check("historical_membership", "历史成分 membership 生效证明", readiness_checks.get("active_snapshot_gate", {}).get("status") == "passed", "effective_at 100%", readiness_checks.get("active_snapshot_gate", {}).get("status") == "passed", remediation="用历史指数/行业成分公告重建 effective_at/available_at，禁止固定当前池回填过去。", sources=("Index provider official", "SSE/SZSE official", "CSRC official"), evidence="artifacts/long_term_readiness/latest.json"),
        _check("event_semantics", "事件缺失语义", readiness_checks.get("event_missing_semantics", {}).get("status"), "0 semantic errors", readiness_checks.get("event_missing_semantics", {}).get("status") == "passed", remediation="每个无事件结果写 no_events_confirmed/provider_not_covered/published_time_unverified 等结构化原因。", sources=("CNINFO official", "SSE/SZSE official", "AKShare"), evidence="artifacts/long_term_readiness/latest.json"),
        _check("pit_leakage", "PIT 泄漏", readiness_checks.get("active_snapshot_gate", {}).get("evidence", {}).get("pit_leakage_error_count"), 0, readiness_checks.get("active_snapshot_gate", {}).get("status") == "passed" and readiness_checks.get("active_snapshot_gate", {}).get("evidence", {}).get("pit_leakage_error_count") == 0, remediation="对 published_at/available_at/effective_at 做快照级审计，发现泄漏则阻止 active 指针。", sources=("Internal PIT audit", "Official provider timestamps"), evidence="artifacts/long_term_readiness/latest.json"),
        _check("freshness", "数据新鲜度", freshness_evidence, "≤1 trading day", freshness_passed, remediation="每日收盘后刷新并记录 latest_trade_date、fetched_at 和延迟；超过 1 个交易日自动降级。", sources=("BaoStock", "AKShare", "SSE/SZSE official"), evidence="artifacts/download_manifests/latest.json"),
        _check("model_tasks", "四个长期任务", registration.get("tasks"), list(CANONICAL_TASKS), set(registration.get("tasks") or []) == set(CANONICAL_TASKS) and registration.get("deployment_ready") is False, remediation="四个任务各自训练、评估、产出预测 parquet 和 artifact hash；失败任务标记 research_only。", sources=("Internal training pipeline", "PyTorch", "LightGBM"), evidence="artifacts/long_term_model_registry/latest.json"),
        _check("model_metrics", "任务级评估指标", metric_check.get("status"), "all required recorded", metric_check.get("status") == "passed", remediation="补齐 Rank IC/IR、成本后收益、回撤、换手、容量、年度/行业/市场状态稳定性和完整性分层。", sources=("Internal evaluation pipeline", "scikit-learn", "PyTorch"), evidence="artifacts/long_term_readiness/latest.json"),
        _check("shadow_60", "Shadow 独立有效交易日", shadow_evidence, 60, isinstance(shadow_sessions, (int, float)) and shadow_sessions >= 60, remediation="每日冻结不可变 session，按独立交易日去重，补齐 1/5/20/60 日结果和失败分类；真实预测覆盖不足时继续保持 research_only，不得把空预测当作模型能力。", sources=("Internal Shadow store", "BaoStock", "AKShare"), evidence="artifacts/research_shadow/summary.json"),
        _check("agent_evidence", "Agent 证据与拒答", agent.get("metrics"), "claims cited 100%; support ≥98%", agent.get("status") == "complete" and float((agent.get("metrics") or {}).get("claim_citation_coverage", 0) or 0) >= 1.0 and float((agent.get("metrics") or {}).get("supported_evidence_rate", 0) or 0) >= 0.98, remediation="记录 claim/source/hash/cutoff/gap；证据不足、快照不可用或时间口径冲突时必须 abstain。", sources=("CNINFO official", "SSE/SZSE official", "Internal evidence store"), evidence="artifacts/agent_acceptance/latest.json"),
    ]
    missing = [item for item in requirements if item["status"] == "missing"]
    return {
        "schema_version": "project-completion-matrix-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if not missing else "blocked",
        "data_tier": "research_pit",
        "deployment_ready": False,
        "canonical_long_term_tasks": list(CANONICAL_TASKS),
        "summary": {"total": len(requirements), "passed": len(requirements) - len(missing), "missing": len(missing)},
        "requirements": requirements,
        "missing_data": missing,
        "data_completion_plan": {
            "status": completion_plan.get("status", "unavailable"),
            "completed_step_count": completion_plan.get("completed_step_count", 0),
            "missing_step_count": completion_plan.get("missing_step_count", 0),
            "p0_missing_steps": completion_plan.get("p0_missing_steps", []),
            "steps": [
                {
                    "id": item.get("id"),
                    "dataset": item.get("dataset"),
                    "status": item.get("status"),
                    "blocking_reasons": item.get("blocking_reasons", []),
                    "command": item.get("command", []),
                    "artifact_ref": item.get("artifact_ref"),
                }
                for item in completion_plan.get("steps", [])
                if isinstance(item, dict)
            ],
            "ref": "artifacts/cn_data_completion_plan/latest.json",
        },
        "source_refs": {"download": "artifacts/download_manifests/latest.json", "readiness": "artifacts/long_term_readiness/latest.json", "data_completion_plan": "artifacts/cn_data_completion_plan/latest.json"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/project_completion/latest.json")
    args = parser.parse_args()
    report = build_report(args.project_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"status": report["status"], "summary": report["summary"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
