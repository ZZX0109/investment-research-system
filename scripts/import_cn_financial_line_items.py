#!/usr/bin/env python3
"""Import reconciled CNINFO financial fields into the PIT knowledge catalog.

The importer consumes only the append-only reconciled JSONL produced by
``reconcile_cn_financial_pit.py``.  It preserves the announcement timestamp as
the research availability assumption, lets ``FinancialKnowledgeService``
create revisions, and never promotes the resulting rows to formal PIT.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.knowledge import FinancialLineItem
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.financial_knowledge import FinancialKnowledgeService


FIELD_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("profit", "MBRevenue"): ("revenue", "营业收入", "CNY"),
    ("profit", "netProfit"): ("net_profit", "归母净利润", "CNY"),
    ("profit", "roeAvg"): ("roe", "平均净资产收益率", "ratio"),
    ("profit", "npMargin"): ("net_margin", "净利率", "ratio"),
    ("profit", "gpMargin"): ("gross_margin", "毛利率", "ratio"),
    ("profit", "epsTTM"): ("eps_ttm", "每股收益TTM", "CNY_per_share"),
    ("profit", "totalShare"): ("total_shares", "总股本", "shares"),
    ("profit", "liqaShare"): ("liquid_shares", "流通股本", "shares"),
    ("growth", "YOYNI"): ("net_income_yoy", "净利润同比", "ratio"),
    ("growth", "YOYPNI"): ("parent_net_income_yoy", "归母净利润同比", "ratio"),
    ("growth", "YOYEPSBasic"): ("eps_yoy", "每股收益同比", "ratio"),
    ("growth", "YOYAsset"): ("asset_yoy", "资产同比", "ratio"),
    ("growth", "YOYEquity"): ("equity_yoy", "权益同比", "ratio"),
    ("operation", "AssetTurnRatio"): ("asset_turnover", "资产周转率", "ratio"),
    ("operation", "CATurnRatio"): ("current_asset_turnover", "流动资产周转率", "ratio"),
    ("operation", "INVTurnRatio"): ("inventory_turnover", "存货周转率", "ratio"),
    ("operation", "NRTurnRatio"): ("receivable_turnover", "应收账款周转率", "ratio"),
    ("operation", "INVTurnDays"): ("inventory_turnover_days", "存货周转天数", "days"),
    ("operation", "NRTurnDays"): ("receivable_turnover_days", "应收账款周转天数", "days"),
    ("balance", "currentRatio"): ("current_ratio", "流动比率", "ratio"),
    ("balance", "quickRatio"): ("quick_ratio", "速动比率", "ratio"),
    ("balance", "cashRatio"): ("cash_ratio", "现金比率", "ratio"),
    ("balance", "liabilityToAsset"): ("liability_to_asset", "资产负债率", "ratio"),
    ("balance", "assetToEquity"): ("equity_multiplier", "权益乘数", "ratio"),
    ("balance", "YOYLiability"): ("liability_yoy", "负债同比", "ratio"),
    ("cash_flow", "CFOToNP"): ("cfo_to_net_profit", "经营现金流/净利润", "ratio"),
    ("cash_flow", "CFOToOR"): ("cfo_to_revenue", "经营现金流/营业收入", "ratio"),
    ("cash_flow", "CFOToGr"): ("cfo_to_gross_revenue", "经营现金流/毛收入", "ratio"),
    ("dupont", "dupontROE"): ("dupont_roe", "杜邦ROE", "ratio"),
    ("dupont", "dupontAssetTurn"): ("dupont_asset_turnover", "杜邦资产周转率", "ratio"),
    ("dupont", "dupontNitogr"): ("dupont_net_margin", "杜邦净利率", "ratio"),
    ("dupont", "dupontTaxBurden"): ("dupont_tax_burden", "杜邦税负", "ratio"),
    ("dupont", "dupontIntburden"): ("dupont_interest_burden", "杜邦利息负担", "ratio"),
    ("dupont", "dupontEbittogr"): ("dupont_ebit_margin", "杜邦EBIT率", "ratio"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT / "artifacts/cn_financial_disclosures_cninfo/fundamentals_pit_reconciled.jsonl",
    )
    parser.add_argument("--database", type=Path, default=PROJECT / "var/investment_research.db")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/cn_financial_disclosures_cninfo/line-item-import-latest.json")
    return parser.parse_args()


def _number(value: Any) -> float | None:
    if value in (None, "", "nan", "NaN", "None"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _period_code(value: str) -> str | None:
    text = str(value or "")[:10]
    if len(text) != 10:
        return None
    year, month, day = text.split("-")
    if (month, day) == ("12", "31"):
        return f"{year}FY"
    if (month, day) == ("06", "30"):
        return f"{year}H1"
    if (month, day) == ("03", "31"):
        return f"{year}Q1"
    if (month, day) == ("09", "30"):
        return f"{year}Q3"
    return None


def _published(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> int:
    args = parse_args()
    allowed = {str(item).rsplit(".", 1)[-1].zfill(6) for item in args.symbols} if args.symbols else None
    if not args.input.is_file():
        raise SystemExit(f"financial PIT input missing: {args.input}")
    # Deduplicate identical collector rows while keeping distinct publication
    # dates as revision candidates for the service layer.
    records: dict[tuple[str, str, str, str, float, str], dict[str, Any]] = {}
    skipped = 0
    for line in args.input.open(encoding="utf-8"):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        symbol = str(row.get("symbol") or row.get("code") or "").rsplit(".", 1)[-1].zfill(6)
        if not symbol or (allowed is not None and symbol not in allowed):
            continue
        period = _period_code(str(row.get("report_period") or row.get("statDate") or ""))
        published = _published(row.get("cninfo_published_at"))
        if period is None or published is None:
            skipped += 1
            continue
        family = str(row.get("feature_family") or "")
        for (mapped_family, field), (metric, label, unit) in FIELD_MAP.items():
            if mapped_family != family:
                continue
            value = _number(row.get(field))
            if value is None:
                continue
            key = (symbol, period, metric, published.isoformat(), value, unit)
            records.setdefault(key, {"row": row, "metric": metric, "label": label, "unit": unit, "value": value, "published": published, "period": period, "symbol": symbol})

    uow = SQLiteUnitOfWork(args.database)
    service = FinancialKnowledgeService(uow)
    imported = 0
    errors: list[dict[str, str]] = []
    try:
        for item in records.values():
            source_url = "https://www.cninfo.com.cn/"
            content_hash = FinancialLineItem.content_hash_of(
                symbol=item["symbol"], period=item["period"], metric=item["metric"],
                source_url=source_url, value=item["value"], unit=item["unit"], scale=1.0,
                published_at=item["published"], metric_label=item["label"],
            )
            try:
                service.ingest_line_item(FinancialLineItem(
                    market="CN", symbol=item["symbol"], period=item["period"], metric=item["metric"],
                    metric_label=item["label"], value=item["value"], unit=item["unit"], scale=1.0,
                    source_name="巨潮资讯网", source_url=source_url,
                    published_at=item["published"], available_at=item["published"], valid_from=item["published"],
                    authority_level=5, data_tier="research_pit", content_hash=content_hash,
                ))
                imported += 1
            except Exception as exc:  # retain the row-level failure without aborting the batch
                errors.append({"symbol": item["symbol"], "metric": item["metric"], "period": item["period"], "reason": f"{type(exc).__name__}:{exc}"})
    finally:
        uow.close()
    report = {
        "schema_version": "cn-financial-line-item-import-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "input": str(args.input),
        "candidate_record_count": len(records),
        "imported_count": imported,
        "skipped_count": skipped,
        "error_count": len(errors),
        "errors": errors[:200],
        "status": "complete" if not errors else "partial",
        "missing_reason": "formal PIT remains unavailable until provider revision and available_at semantics are verified",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "candidate_record_count", "imported_count", "error_count")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
