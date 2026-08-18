#!/usr/bin/env python3
"""Write a concise, evidence-backed local CN training-data completion audit."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ETF = {"510050", "510300", "510500", "159915", "512100"}


def main() -> int:
    target = set(json.loads((PROJECT / "config/cn_research_target_167_symbols.json").read_text())["cn"])
    equity = target - ETF
    final_root = PROJECT / "artifacts/free_research_rebuild/aligned-20260817-final-v2"
    rebuild = next(final_root.glob("rebuild-*.json"))
    rebuild_report = json.loads(rebuild.read_text())
    manifests = [json.loads(p.read_text()) for p in (final_root / "standard").glob("*.json")]
    event_report_path = PROJECT / "artifacts/cn_event_backfill_full/latest.json"
    if not event_report_path.is_file():
        event_report_path = PROJECT / "artifacts/cn_event_backfill/latest.json"
    events = json.loads(event_report_path.read_text())
    news = json.loads((PROJECT / "artifacts/cn_news_backfill/latest.json").read_text())
    event_pit = json.loads((PROJECT / "artifacts/cn_event_backfill/pit_normalized.json").read_text())
    actions = json.loads((PROJECT / "artifacts/cn_corporate_actions_detailed/latest.json").read_text())
    auxiliary = json.loads((PROJECT / "artifacts/cn_research_auxiliary/latest.json").read_text())
    financial = json.loads((PROJECT / "artifacts/cn_financial_coverage/latest.json").read_text())
    financial_pit_path = PROJECT / "artifacts/cn_financial_disclosures_cninfo/pit-reconciled-latest.json"
    financial_pit = json.loads(financial_pit_path.read_text()) if financial_pit_path.is_file() else {}
    lifecycle_path = PROJECT / "artifacts/cn_security_lifecycle_akshare/latest.json"
    lifecycle = json.loads(lifecycle_path.read_text()) if lifecycle_path.is_file() else {}
    membership_path = PROJECT / "artifacts/cn_security_master/latest.json"
    membership = json.loads(membership_path.read_text()) if membership_path.is_file() else {}
    security_status_path = PROJECT / "artifacts/cn_security_status_disclosures_cninfo/latest.json"
    security_status = json.loads(security_status_path.read_text()) if security_status_path.is_file() else {}
    macro_pit_path = PROJECT / "artifacts/cn_research_auxiliary/macro_pit_latest.json"
    macro_pit = json.loads(macro_pit_path.read_text()) if macro_pit_path.is_file() else {}
    macro_calendar_path = PROJECT / "artifacts/cn_macro_release_calendar_nbs/latest.json"
    macro_calendar = json.loads(macro_calendar_path.read_text()) if macro_calendar_path.is_file() else {}
    name_history_path = PROJECT / "artifacts/cn_security_name_history_sina/latest.json"
    name_history = json.loads(name_history_path.read_text()) if name_history_path.is_file() else {}
    delegated_financial_path = PROJECT / "artifacts/subagent_financial_pit/fetch_manifest.json"
    delegated_financial = json.loads(delegated_financial_path.read_text()) if delegated_financial_path.is_file() else {}
    delegated_security_path = PROJECT / "artifacts/subagent_security_status/latest.json"
    delegated_security = json.loads(delegated_security_path.read_text()) if delegated_security_path.is_file() else {}
    delegated_macro_path = PROJECT / "artifacts/subagent_macro_release/latest.json"
    delegated_macro = json.loads(delegated_macro_path.read_text()) if delegated_macro_path.is_file() else {}
    delegated_membership_path = PROJECT / "artifacts/subagent_membership_breadth/latest.json"
    delegated_membership = json.loads(delegated_membership_path.read_text()) if delegated_membership_path.is_file() else {}
    industry = json.loads((PROJECT / "config/cn_industry_map.json").read_text()).get("symbols", {})
    rows = sum(int(x.get("row_count", 0)) for x in manifests)
    audit = {
        "schema_version": "cn-data-completion-audit-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": {"equities": len(equity), "etfs": len(ETF), "total": len(target)},
        "training_ready_research_layer": {
            "status": rebuild_report.get("status"),
            "as_of": rebuild_report.get("as_of"),
            "standard_symbols": len(manifests),
            "standard_rows": rows,
            "sample_manifests": len(list((final_root / "samples/close_confirmed").glob("*/*/*.json"))),
            "failures": rebuild_report.get("failures", []),
            "training_blocked": rebuild_report.get("training_blocked"),
        },
        "coverage": {
            "daily_bars": {"covered": len(manifests), "target": len(target), "latest_trading_date": rebuild_report.get("as_of")},
            "adjustment_factor_in_final_bars": {"covered": len(manifests), "target": len(target), "status": "complete"},
            "trading_state_in_final_bars": {"covered": len(manifests), "target": len(target), "status": "complete"},
            "industry_mapping": {"equities_mapped": len(equity & set(industry)), "equities_target": len(equity), "etf_mapping": "not_applicable"},
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
