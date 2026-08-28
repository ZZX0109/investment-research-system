#!/usr/bin/env python3
"""Write a concise, evidence-backed local CN training-data completion audit."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.research_data_quality import (
    _research_sample_progress,
    load_free_research_catalog_batches,
    normalise_symbol,
)
ETF = {"510050", "510300", "510500", "159915", "512100"}


def _read(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _current_universe() -> tuple[set[str], set[str]]:
    """Prefer the full current enumeration and retain the 167-symbol fallback."""
    universe_path = PROJECT / "artifacts/cn_security_master_universe/security_master_current.json"
    if universe_path.is_file():
        try:
            values = json.loads(universe_path.read_text(encoding="utf-8"))
            rows = values if isinstance(values, list) else values.get("symbols", [])
            symbols = {
                str(item.get("code") if isinstance(item, dict) else item).rsplit(".", 1)[-1].zfill(6)
                for item in rows
                if item not in (None, "")
            }
            if symbols:
                return symbols - ETF, symbols & ETF
        except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
            pass
    fallback = _read(PROJECT / "config/cn_research_target_167_symbols.json").get("cn", [])
    symbols = {str(item).rsplit(".", 1)[-1].zfill(6) for item in fallback}
    return symbols - ETF, symbols & ETF


def _rebuild_artifacts() -> tuple[Path, dict, list[dict]]:
    """Resolve the newest broad-universe rebuild, then use the legacy pool."""
    broad_root = PROJECT / "artifacts/free_research_rebuild_all_raw_standard"
    candidates = [broad_root / "latest.json"] + sorted(broad_root.glob("rebuild-*.json"), reverse=True)
    for index in candidates:
        report = _read(index)
        if not report:
            continue
        refs = report.get("standard_manifest_refs") or []
        manifests = []
        for value in refs:
            path = Path(value)
            if not path.is_absolute():
                path = PROJECT / path
            item = _read(path)
            if item:
                manifests.append(item)
        if manifests or report.get("standard_manifest_count") == 0:
            return broad_root, report, manifests
    legacy_root = PROJECT / "artifacts/free_research_rebuild/aligned-20260817-final-v2"
    candidates = sorted(legacy_root.glob("rebuild-*.json"), reverse=True)
    report = _read(candidates[0]) if candidates else {}
    manifests = [_read(path) for path in (legacy_root / "standard").glob("*.json")]
    return legacy_root, report, [item for item in manifests if item]


def main() -> int:
    equity, etfs = _current_universe()
    target = equity | etfs
    final_root, rebuild_report, manifests = _rebuild_artifacts()
    event_report_path = PROJECT / "artifacts/cn_event_backfill_full/latest.json"
    if not event_report_path.is_file():
        event_report_path = PROJECT / "artifacts/cn_event_backfill/latest.json"
    events = _read(event_report_path)
    news = _read(PROJECT / "artifacts/cn_news_backfill/latest.json")
    event_pit = _read(PROJECT / "artifacts/cn_event_backfill/pit_normalized.json")
    actions = _read(PROJECT / "artifacts/cn_corporate_actions_detailed/latest.json")
    auxiliary = _read(PROJECT / "artifacts/cn_research_auxiliary/latest.json")
    financial = _read(PROJECT / "artifacts/cn_financial_coverage/latest.json")
    financial_pit_path = PROJECT / "artifacts/cn_financial_disclosures_cninfo/pit-reconciled-latest.json"
    financial_pit = _read(financial_pit_path)
    lifecycle_path = PROJECT / "artifacts/cn_security_lifecycle_akshare/latest.json"
    lifecycle = _read(lifecycle_path)
    membership_path = PROJECT / "artifacts/cn_security_master/latest.json"
    membership = _read(membership_path)
    security_status_path = PROJECT / "artifacts/cn_security_status_disclosures_cninfo/latest.json"
    security_status = _read(security_status_path)
    macro_pit_path = PROJECT / "artifacts/cn_research_auxiliary/macro_pit_latest.json"
    macro_pit = _read(macro_pit_path)
    macro_calendar_path = PROJECT / "artifacts/cn_macro_release_calendar_nbs/latest.json"
    macro_calendar = _read(macro_calendar_path)
    name_history_path = PROJECT / "artifacts/cn_security_name_history_sina/latest.json"
    name_history = _read(name_history_path)
    delegated_financial_path = PROJECT / "artifacts/subagent_financial_pit/fetch_manifest.json"
    delegated_financial = _read(delegated_financial_path)
    delegated_security_path = PROJECT / "artifacts/subagent_security_status/latest.json"
    delegated_security = _read(delegated_security_path)
    delegated_macro_path = PROJECT / "artifacts/subagent_macro_release/latest.json"
    delegated_macro = _read(delegated_macro_path)
    macro_retry = _read(PROJECT / "artifacts/subagent_macro_history_retry/latest.json")
    macro_retry_coverage = _read(PROJECT / "artifacts/subagent_macro_history_retry/coverage.json")
    delegated_membership_path = PROJECT / "artifacts/subagent_membership_breadth/latest.json"
    delegated_membership = _read(delegated_membership_path)
    industry = _read(PROJECT / "config/cn_industry_map.json").get("symbols", {})
    security_master = _read(PROJECT / "artifacts/cn_security_master/latest.json")
    rows = sum(int(x.get("row_count", 0) or 0) for x in manifests)
    standard_symbols = {
        str(item.get("symbol") or "").rsplit(".", 1)[-1].zfill(6)
        for item in manifests
        if item.get("symbol")
    }
    price_batches = load_free_research_catalog_batches(PROJECT / "var/cn-research/catalog.db")
    raw_symbols = {
        normalise_symbol(batch.symbol)
        for batch in price_batches
        if batch.dataset == "daily_bars_raw" and batch.symbol
    }
    qfq_symbols = {
        normalise_symbol(batch.symbol)
        for batch in price_batches
        if batch.dataset == "daily_bars_qfq" and batch.symbol
    }
    raw_current = raw_symbols & target
    qfq_current = qfq_symbols & target
    daily_bar_symbol_count = len(raw_current) if target else int(security_master.get("daily_bar_symbol_count", len(standard_symbols)) or 0)
    industry_mapped = int(security_master.get("industry_mapped_applicable_count", len(equity & set(industry))) or 0)
    industry_target = int(security_master.get("industry_applicable_symbol_count", len(equity)) or 0)
    context = rebuild_report.get("contexts", {}).get("close_confirmed", {}) if isinstance(rebuild_report, dict) else {}
    indexed_sample_refs = [
        str(ref)
        for values in (context.get("sample_manifests", {}) or {}).values()
        if isinstance(values, list)
        for ref in values
    ] if isinstance(context, dict) else []
    # The merged index may deliberately point at an isolated staging/object
    # root.  Count the immutable refs in that index first, then verify that
    # each referenced manifest still exists; scanning only final_root/samples
    # silently reported zero after a valid external-root merge.
    indexed_existing_refs = [
        ref for ref in indexed_sample_refs
        if (Path(ref) if Path(ref).is_absolute() else PROJECT / ref).is_file()
    ]
    missing_indexed_sample_refs = max(0, len(indexed_sample_refs) - len(indexed_existing_refs))
    sample_manifest_count = len(indexed_existing_refs)
    if not indexed_sample_refs:
        sample_manifest_count = (
            len(list((final_root / "samples/close_confirmed").glob("*/*/*.json")))
            if final_root.is_dir()
            else 0
        )
    # A standard-bar index is not by itself trainable.  Training and
    # inference consume snapshot-bound sample manifests, so a broad
    # standard-only rebuild (usually produced with --skip-samples) must be
    # reported as training-blocked even when the cohort-size check passes.
    rebuild_training_blocked = bool(rebuild_report.get("training_blocked"))
    if sample_manifest_count == 0 or missing_indexed_sample_refs:
        rebuild_training_blocked = True
    sample_progress = _research_sample_progress(PROJECT)
    audit = {
        "schema_version": "cn-data-completion-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked",
        "data_tier": "research_pit",
        "formal_pit_eligible": False,
        "deployment_ready": False,
        "target": {"equities": len(equity), "etfs": len(etfs), "total": len(target), "scope": "current_cn_security_master_universe"},
        "training_ready_research_layer": {
            "status": rebuild_report.get("status"),
            "as_of": rebuild_report.get("as_of"),
            "standard_symbols": len(standard_symbols) or len(manifests),
            "standard_rows": rows,
            "sample_manifests": sample_manifest_count,
            "missing_indexed_sample_manifests": missing_indexed_sample_refs,
            "staging_sample_manifests": sample_progress.get("staging_manifest_count", 0),
            "staging_symbols": sample_progress.get("staging_symbol_count", 0),
            "failures": rebuild_report.get("failures", []),
            "training_blocked": rebuild_training_blocked,
        },
        "coverage": {
            "daily_bars": {
                "covered": daily_bar_symbol_count or len(standard_symbols),
                "target": len(target),
                "coverage_ratio": (daily_bar_symbol_count or len(standard_symbols)) / len(target) if target else 0.0,
                "source": "append_only_catalog" if raw_current else "standard_manifest_fallback",
                "latest_trading_date": rebuild_report.get("as_of"),
            },
            "front_adjusted_prices": {
                "covered": len(qfq_current),
                "target": len(target),
                "coverage_ratio": len(qfq_current) / len(target) if target else 0.0,
                "status": "research_only_unverified",
            },
            "standardized_final_bars": {"covered": len(standard_symbols), "target": len(target), "status": "research_only_unverified"},
            "trading_state_in_final_bars": {"covered": len(standard_symbols), "target": len(target), "status": "research_only_unverified"},
            "industry_mapping": {"equities_mapped": industry_mapped, "equities_target": industry_target, "coverage_ratio": industry_mapped / industry_target if industry_target else 0.0, "etf_mapping": "not_applicable"},
            "events": {"symbols": events.get("completed_equity_count"), "rows": events.get("event_row_count"), "status": events.get("status")},
            "news_window": {"symbols": news.get("completed_equity_count"), "rows": news.get("news_row_count"), "status": news.get("status")},
            "event_pit_normalized": {"rows": event_pit.get("row_count"), "available_at": event_pit.get("available_at_present"), "revision": event_pit.get("revision_present"), "status": event_pit.get("status")},
            "corporate_actions_detailed": {"symbols": actions.get("completed_equity_count"), "rows": actions.get("row_count"), "dividend_rows": actions.get("dividend_row_count"), "rights_issue_rows": actions.get("rights_issue_row_count"), "status": actions.get("status")},
            "auxiliary": {
                "margin_financing": auxiliary.get("datasets", {}).get("margin_financing", {}).get("row_count"),
                "market_breadth": auxiliary.get("datasets", {}).get("market_breadth", {}).get("row_count"),
                "macro_status": auxiliary.get("datasets", {}).get("macro", {}).get("status"),
            },
        },
        "remaining_limitations": [
            "financial ratios remain source-dependent for a minority of fields/reporting periods",
            "historical security-state availability and historical event visibility are not formally proven",
            "research layer is not formal PIT/deployment eligible",
            f"current universe has {len(target)} securities; raw daily bars cover {daily_bar_symbol_count or len(standard_symbols)}, qfq bars cover {len(qfq_current)}, and only {len(standard_symbols)} have standardized final bars",
        ],
        "supplemental_audits": {
            "delegated_downloads": {
                "financial_pit": {
                    "status": delegated_financial.get("pit_status"),
                    "target_equity_count": delegated_financial.get("target_equity_count"),
                    "fetch_complete_job_count": delegated_financial.get("fetch_complete_job_count"),
                    "raw_announcement_record_count": delegated_financial.get("raw_announcement_record_count"),
                    "expected_key_count": delegated_financial.get("expected_key_count"),
                    "matched_key_count": delegated_financial.get("matched_key_count"),
                    "unmatched_key_count": delegated_financial.get("unmatched_key_count"),
                    "primary_matched_key_count": delegated_financial.get("primary_matched_key_count"),
                    "primary_unmatched_key_count": delegated_financial.get("primary_unmatched_key_count"),
                    "formal_pit_verified": delegated_financial.get("formal_pit_verified"),
                },
                "security_status": {
                    "status": delegated_security.get("status"),
                    "target_equity_count": delegated_security.get("target_equity_count"),
                    "daily_market_status": delegated_security.get("source_reports", {}).get("daily_market_status", {}),
                    "st_daily_status_coverage": delegated_security.get("source_reports", {}).get("daily_market_status", {}).get("st_daily_status_coverage"),
                    "cninfo": delegated_security.get("source_reports", {}).get("cninfo", {}),
                    "sina": delegated_security.get("source_reports", {}).get("sina", {}),
                },
                "macro_release": {
                    "status": delegated_macro.get("status"),
                    "raw_source_count": delegated_macro.get("raw_source_count"),
                    "normalized_observation_count": delegated_macro.get("normalized_observation_count"),
                    "coverage": delegated_macro.get("coverage"),
                    "failures": delegated_macro.get("failures"),
                },
                "macro_release_retry": {
                    "status": macro_retry.get("status"),
                    "as_of": macro_retry.get("as_of"),
                    "target_rows": macro_retry.get("target_rows"),
                    "mapped_rows": macro_retry.get("mapped_rows"),
                    "unresolved_rows": macro_retry.get("unresolved_rows"),
                    "evidence_levels": macro_retry.get("evidence_levels"),
                    "coverage": macro_retry_coverage.get("target_coverage"),
                    "source_manifest_ref": macro_retry.get("source_manifest_ref"),
                    "normalized_mapping_ref": macro_retry.get("normalized_mapping_ref"),
                    "formal_pit_verified": False,
                },
                "membership_breadth": {
                    "status": delegated_membership.get("status"),
                    "evidence_summary": delegated_membership.get("evidence_summary"),
                    "failures": delegated_membership.get("failures"),
                    "not_covered": delegated_membership.get("interpretation", {}).get("not_covered"),
                },
            },
            "financial": {
                "status": financial.get("status"),
                "field_coverage": financial.get("coverage"),
                "publication_period_join": financial.get("publication_period_join"),
            },
            "financial_pit_reconciled": {
                "status": financial_pit.get("status"),
                "formal_pit_verified": financial_pit.get("formal_pit_verified"),
                "datasets": financial_pit.get("datasets", {}),
            },
            "security_lifecycle": {
                "status": lifecycle.get("status"),
                "listing_date_coverage": lifecycle.get("listing_date_coverage"),
                "industry_history_coverage": lifecycle.get("industry_history_coverage"),
                "code_change_coverage": lifecycle.get("code_change_coverage"),
                "code_change_record_coverage": lifecycle.get("code_change_record_coverage"),
                "name_change_coverage": lifecycle.get("name_change_coverage"),
                "st_status_coverage": lifecycle.get("st_status_coverage"),
            },
            "security_status_disclosures": {
                "status": security_status.get("status"),
                "category": security_status.get("category"),
                "target_equity_count": security_status.get("target_equity_count"),
                "completed_equity_count": security_status.get("completed_equity_count"),
                "row_count": security_status.get("row_count"),
                "published_at_coverage": security_status.get("published_at_coverage"),
                "daily_state_coverage": False,
                "missing_reason": security_status.get("missing_reason"),
            },
            "security_name_history": {
                "status": name_history.get("status"),
                "target_equity_count": name_history.get("target_equity_count"),
                "completed_equity_count": name_history.get("completed_equity_count"),
                "row_count": name_history.get("row_count"),
                "st_name_evidence_symbol_count": name_history.get("st_name_evidence_symbol_count"),
                "dated_status_coverage": name_history.get("dated_status_coverage"),
                "missing_reason": name_history.get("missing_reason"),
            },
            "macro_release_evidence": {
                "macro_record_count": macro_pit.get("record_count"),
                "actual_published_at_coverage": macro_pit.get("published_at_coverage"),
                "source_release_date_coverage": macro_pit.get("source_release_date_coverage"),
                "planned_release_coverage": macro_pit.get("planned_published_at_coverage"),
                "evidence_levels": macro_retry.get("evidence_levels"),
                "calendar_row_count": macro_calendar.get("row_count"),
                "calendar_assumption_row_count": macro_calendar.get("assumption_row_count"),
                "calendar_assumption_coverage": macro_calendar.get("assumption_coverage"),
                "formal_pit_verified": False,
            },
            "historical_membership": {
                "status": membership.get("status"),
                "quality_status": membership.get("quality_status"),
                "row_count": membership.get("row_count"),
                "available_at_policy": "effective_from_listing_date_assumption",
            },
        },
        "strict_pit_gate": {
            "formal_pit_eligible": False,
            "reason": "publication/revision reconciliation, historical security state, macro release time, and true historical cohort membership remain incomplete",
        },
    }
    out = PROJECT / "artifacts/cn_data_completion_audit/latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
