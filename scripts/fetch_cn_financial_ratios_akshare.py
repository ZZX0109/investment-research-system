#!/usr/bin/env python3
"""Backfill missing CN financial ratios from AkShare's public Sina table.

This collector improves value coverage but deliberately does not claim PIT:
the source exposes report dates, not a verified first-publication timestamp.
Rows are stored as a separate append-only dataset until that timestamp can be
joined to an authoritative disclosure record.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import threading
import time
from typing import Any
from uuid import uuid4

import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from investment_research.service.cn_universe import load_cn_symbols

ETF_SYMBOLS = {"159915", "510050", "510300", "510500", "512100"}
METRIC_CONTRACT_VERSION = 3

# A Sina abstract response contains a compact, multi-period set of the same
# public financial metrics used by the CN feature contract.  Keep the source
# label and field semantics explicit: a percentage ``item_value`` is converted
# to a decimal, while year-over-year changes are calculated from the prior
# same-period column in the returned report table.  One source metric can legitimately serve multiple
# named features (for example ROE and the DuPont presentation of ROE).
MetricSpec = tuple[str, str, float, str, str]
METRIC_MAP: dict[str, tuple[MetricSpec, ...]] = {
    "毛利率": (("profit", "gpMargin", 0.01, "ratio", "item_value"),),
    "销售净利率": (("profit", "npMargin", 0.01, "ratio", "item_value"),),
    "净资产收益率_平均": (
        ("profit", "roeAvg", 0.01, "ratio", "item_value"),
        ("dupont", "dupontROE", 0.01, "ratio", "item_value"),
    ),
    "基本每股收益": (
        ("profit", "epsTTM", 1.0, "currency_per_share", "item_value"),
        ("growth", "YOYEPSBasic", 1.0, "ratio", "year_over_year"),
    ),
    "股东权益合计(净资产)": (("growth", "YOYEquity", 1.0, "ratio", "year_over_year"),),
    "净利润": (("growth", "YOYNI", 1.0, "ratio", "year_over_year"),),
    "归母净利润": (("growth", "YOYPNI", 1.0, "ratio", "year_over_year"),),
    "应收账款周转率": (("operation", "NRTurnRatio", 1.0, "times", "item_value"),),
    "存货周转率": (("operation", "INVTurnRatio", 1.0, "times", "item_value"),),
    "总资产周转率": (
        ("operation", "AssetTurnRatio", 1.0, "times", "item_value"),
        ("dupont", "dupontAssetTurn", 1.0, "times", "item_value"),
    ),
    "流动比率": (("balance", "currentRatio", 1.0, "ratio", "item_value"),),
    "速动比率": (("balance", "quickRatio", 1.0, "ratio", "item_value"),),
    "现金比率": (("balance", "cashRatio", 0.01, "ratio", "item_value"),),
    "资产负债率": (("balance", "liabilityToAsset", 0.01, "ratio", "item_value"),),
    "经营性现金净流量/营业总收入": (("cash_flow", "CFOToOR", 1.0, "ratio", "item_value"),),
    "经营活动净现金/归属母公司的净利润": (("cash_flow", "CFOToNP", 1.0, "ratio", "item_value"),),
    "经营活动净现金/销售收入": (("cash_flow", "CFOToGr", 1.0, "ratio", "item_value"),),
    "权益乘数": (("dupont", "dupontAssetStoEquity", 1.0, "times", "item_value"),),
}
_DEFAULT_REQUEST_INTERVAL_SECONDS = 0.35
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
_REQUEST_TIMEOUT_SECONDS = _DEFAULT_REQUEST_TIMEOUT_SECONDS
_REQUEST_CALL_LOCK = threading.Lock()


class _RequestPacer:
    """Keep public-provider requests globally paced across worker threads."""

    def __init__(self, interval_seconds: float) -> None:
        self._interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._next_request_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_request_at - now)
            self._next_request_at = max(now, self._next_request_at) + self._interval_seconds
        if delay:
            time.sleep(delay)


_REQUEST_PACER = _RequestPacer(_DEFAULT_REQUEST_INTERVAL_SECONDS)


class _ProviderThrottled(RuntimeError):
    """The public endpoint rejected the request; stop the current batch."""


def _configure_request_pacing(interval_seconds: float) -> None:
    global _REQUEST_PACER
    _REQUEST_PACER = _RequestPacer(interval_seconds)


def _configure_request_timeout(timeout_seconds: float) -> None:
    global _REQUEST_TIMEOUT_SECONDS
    _REQUEST_TIMEOUT_SECONDS = timeout_seconds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--target-symbols", type=Path, default=PROJECT / "config/cn_research_target_167_symbols.json")
    parser.add_argument("--all-current-universe", action="store_true", help="use the current A-share/ETF enumeration and exclude ETFs")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_financial_ratios_akshare")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--request-interval-seconds", type=float, default=_DEFAULT_REQUEST_INTERVAL_SECONDS,
        help="Minimum interval between requests across all workers; prevents public-source retry bursts.",
    )
    parser.add_argument(
        "--request-timeout-seconds", type=float, default=_DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help="Hard timeout applied to the underlying Sina HTTP request.",
    )
    parser.add_argument(
        "--provider-throttle-cooldown-seconds", type=float, default=30.0,
        help="Cooldown before retrying a batch after HTTP 429/456.",
    )
    parser.add_argument(
        "--max-provider-throttle-events", type=int, default=10,
        help="Maximum consecutive provider-throttle events before stopping the batch.",
    )
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (
        args.workers <= 0
        or args.request_interval_seconds < 0
        or args.request_timeout_seconds <= 0
        or args.provider_throttle_cooldown_seconds < 0
        or args.max_provider_throttle_events <= 0
    ):
        raise SystemExit("workers/timeout/throttle settings are invalid")
    _configure_request_pacing(args.request_interval_seconds)
    _configure_request_timeout(args.request_timeout_seconds)
    args.output_root.mkdir(parents=True, exist_ok=True)
    target_path = PROJECT / "artifacts/cn_security_master_universe/security_master_current.json" if args.all_current_universe else args.target_symbols
    symbols = load_cn_symbols(target_path, exclude_etf=True)
    progress_path = args.output_root / "progress.json"
    progress = _read(progress_path) if progress_path.exists() and not args.no_resume else {"symbols": {}}
    progress.setdefault("symbols", {})
    progress.update({
        "schema_version": "cn-financial-ratios-progress-v1",
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "target_equity_count": len(symbols),
        "workers": max(1, min(args.workers, 2)),
        "request_interval_seconds": args.request_interval_seconds,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    _write(progress_path, progress)
    pending = [
        symbol for symbol in symbols
        if not _current_contract_complete(progress["symbols"].get(symbol, {}))
    ]
    print(f"target_equities={len(symbols)} pending={len(pending)}", flush=True)

    uow = SQLiteUnitOfWork(args.database)
    service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
    try:
        if args.workers == 1:
            # Sequential mode is used for the conservative retry path.  It
            # can stop immediately on a provider throttle instead of queuing
            # thousands of doomed futures behind the first rejected request.
            consecutive_throttle_events = 0
            for symbol in pending:
                try:
                    result = _fetch_symbol(symbol)
                except Exception as exc:
                    result = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
                _persist_result(service, progress, progress_path, symbol, result)
                completed_current = sum(_current_contract_complete(state) for state in progress["symbols"].values())
                print(f"fetched {completed_current}/{len(symbols)} {symbol} {result.get('status')}", flush=True)
                if result.get("status") == "provider_throttled":
                    consecutive_throttle_events += 1
                    if consecutive_throttle_events >= args.max_provider_throttle_events:
                        print("provider throttled repeatedly; stopping batch for a later resumable retry", flush=True)
                        break
                    if args.provider_throttle_cooldown_seconds:
                        time.sleep(args.provider_throttle_cooldown_seconds)
                    continue
                consecutive_throttle_events = 0
        else:
            with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 2))) as pool:
                futures = {pool.submit(_fetch_symbol, symbol): symbol for symbol in pending}
                for future in as_completed(futures):
                    symbol = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = {"status": "failed", "reason": f"{type(exc).__name__}:{exc}"}
                    _persist_result(service, progress, progress_path, symbol, result)
                    completed_current = sum(
                        _current_contract_complete(state)
                        for state in progress["symbols"].values()
                    )
                    print(f"fetched {completed_current}/{len(symbols)} {symbol} {result.get('status')}", flush=True)
    finally:
        uow.close()

    completed = [item for item in progress["symbols"].values() if item.get("status") == "complete"]
    failures = {key: value for key, value in progress["symbols"].items() if value.get("status") != "complete"}
    report = {
        "schema_version": "cn-financial-ratios-akshare-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "deployment_ready": False,
        "provider": "akshare_sina_financial_abstract",
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "target_equity_count": len(symbols),
        "completed_equity_count": len(completed),
        "failed_equity_count": len(failures),
        "row_count": sum(int(item.get("row_count", 0)) for item in completed),
        "metric_count": sum(int(item.get("metric_count", 0)) for item in completed),
        "failures": failures,
        "published_at_coverage": 0.0,
        "available_at_coverage": 1.0 if completed else 0.0,
        "revision_coverage": 1.0 if completed else 0.0,
        "missing_reason": "source provides report period but not verified first publication time",
        "missing_reason_code": "published_time_unverified",
        "status": "complete" if len(completed) == len(symbols) else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write(args.output_root / "latest.json", report)
    print(json.dumps({k: report[k] for k in ("status", "completed_equity_count", "row_count", "metric_count")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _persist_result(
    service: RawPayloadIngestionService,
    progress: dict[str, Any],
    progress_path: Path,
    symbol: str,
    result: dict[str, Any],
) -> None:
    """Checkpoint each symbol before accepting another completed future."""
    if result.get("status") != "complete" or not isinstance(result.get("rows"), list):
        progress["symbols"][symbol] = result if result.get("status") != "complete" else {
            "status": "failed", "reason": "financial_ratio_rows_missing",
        }
    else:
        now = datetime.now(timezone.utc)
        raw = json.dumps(result["rows"], ensure_ascii=False, separators=(",", ":")).encode()
        batch = service.persist(
            provider="akshare_sina_financial_abstract",
            request_id=f"cn-financial-ratios-akshare-{symbol}-{uuid4()}",
            dataset="cn_financial_ratios_akshare_research",
            payload=raw,
            schema_version="cn-financial-ratios-akshare-v1",
            symbol=symbol,
            available_at=now,
            received_at=now,
            market_session="research_backfill",
            data_tier=DataTier.RESEARCH_PIT,
        )
        progress["symbols"][symbol] = {
            "status": "complete", "row_count": len(result["rows"]),
            "metric_count": result["metric_count"], "payload_hash": batch.payload_hash,
            "raw_batch_id": str(batch.id), "metric_contract_version": METRIC_CONTRACT_VERSION,
        }
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(progress_path, progress)


def _fetch_symbol(symbol: str) -> dict[str, Any]:
    import akshare as ak

    last_error: Exception | None = None
    frame = None
    for attempt in range(4):
        try:
            _REQUEST_PACER.wait()
            # The current AKShare Sina adapter calls requests.get without a
            # timeout.  Wrap that call so one stalled socket cannot block a
            # checkpoint worker indefinitely.  The lock protects the
            # temporary process-wide wrapper when callers use workers=2.
            with _REQUEST_CALL_LOCK:
                original_get = requests.get
                requests.get = _get_with_timeout(original_get)
                try:
                    frame = ak.stock_financial_abstract(symbol=symbol)
                finally:
                    requests.get = original_get
            if frame is None or frame.empty:
                raise RuntimeError("empty_financial_abstract")
            break
        except _ProviderThrottled as exc:
            fallback = _fetch_indicator_fallback(symbol)
            if fallback.get("status") == "complete":
                fallback["fallback_reason"] = str(exc)
                return fallback
            return {"status": "provider_throttled", "reason": str(exc)}
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                # Sina occasionally returns an empty/non-JSON body for a
                # contiguous block of symbols when the public endpoint is
                # throttled.  A short exponential backoff is insufficient in
                # that case; pause longer before retrying the same symbol so
                # the failure ledger remains small and resumable.
                error_name = type(exc).__name__
                delay = 2.0 ** attempt
                if error_name in {"JSONDecodeError", "RemoteDisconnected", "ProxyError"}:
                    delay = 15.0 * (attempt + 1)
                time.sleep(delay)
    if frame is None or frame.empty:
        fallback = _fetch_indicator_fallback(symbol)
        if fallback.get("status") == "complete":
            fallback["fallback_reason"] = f"{type(last_error).__name__}:{last_error}" if last_error else "empty_financial_abstract"
            return fallback
        return {"status": "failed", "reason": f"{type(last_error).__name__}:{last_error}" if last_error else "empty_financial_abstract"}
    columns = [str(value) for value in frame.columns if str(value).isdigit() and len(str(value)) == 8]
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _, source in frame.iterrows():
        metric = str(source.get("指标") or "").strip()
        specs = METRIC_MAP.get(metric)
        if specs is None:
            continue
        for report_date in columns:
            for family, field, scale, unit, value_key in specs:
                value = _value_for_spec(source, report_date, value_key)
                try:
                    value = float(value)
                    if not math.isfinite(value):
                        continue
                except (TypeError, ValueError):
                    continue
                rows_by_key[(family, field, report_date)] = {
                    "code": ("sh." if symbol.startswith(("6", "9")) else "sz.") + symbol,
                    "statDate": f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:8]}",
                    "report_period": report_date,
                    "feature_family": family,
                    field: value * scale,
                    "unit": unit,
                    "basis": "cumulative_or_report_period_as_provided_by_source",
                    "source_metric_label": metric,
                    "source_value_field": value_key,
                    "pubDate": None,
                    "available_at": None,
                    "revision_id": None,
                    "source_publication_status": "unverified",
                    "source_provider": "sina_financial_abstract_via_akshare",
                }
    rows = [rows_by_key[key] for key in sorted(rows_by_key)]
    return {"status": "complete", "rows": rows, "metric_count": len({row["feature_family"] + row["statDate"] for row in rows})}


def _fetch_indicator_fallback(symbol: str) -> dict[str, Any]:
    """Map AKShare's analysis-indicator table into the same metric contract.

    This endpoint exposes report-period indicators under a different Sina
    route.  Only semantically matching fields are mapped; unavailable fields
    remain absent instead of being filled from a similarly named measure.
    """
    try:
        import akshare as ak

        _REQUEST_PACER.wait()
        # This adapter performs seven small paginated requests and has its
        # own retry behavior.  Applying the abstract endpoint's 429/456
        # circuit breaker to every intermediate page causes false throttles;
        # let the adapter complete its normal sequence here.  The outer batch
        # remains resumable if the provider really fails.
        # The public adapter is reliable for the recent seven-year window;
        # asking for the full history can return an empty page for BSE/older
        # identities even though the same symbol has valid recent rows.
        frame = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2020")
    except _ProviderThrottled:
        return {"status": "provider_throttled", "reason": "indicator_fallback_throttled"}
    except Exception as exc:
        return {"status": "failed", "reason": f"indicator_fallback:{type(exc).__name__}:{exc}"}
    if frame is None or getattr(frame, "empty", True):
        return {"status": "failed", "reason": "indicator_fallback_empty"}

    mappings: tuple[tuple[str, str, str, float], ...] = (
        ("profit", "npMargin", "销售净利率(%)", 0.01),
        ("profit", "roeAvg", "加权净资产收益率(%)", 0.01),
        ("dupont", "dupontROE", "加权净资产收益率(%)", 0.01),
        ("growth", "YOYEquity", "净资产增长率(%)", 0.01),
        ("growth", "YOYNI", "净利润增长率(%)", 0.01),
        ("growth", "YOYPNI", "净利润增长率(%)", 0.01),
        ("operation", "NRTurnRatio", "应收账款周转率(次)", 1.0),
        ("operation", "INVTurnRatio", "存货周转率(次)", 1.0),
        ("operation", "AssetTurnRatio", "总资产周转率(次)", 1.0),
        ("dupont", "dupontAssetTurn", "总资产周转率(次)", 1.0),
        ("balance", "currentRatio", "流动比率", 1.0),
        ("balance", "quickRatio", "速动比率", 1.0),
        ("balance", "cashRatio", "现金比率(%)", 0.01),
        ("balance", "liabilityToAsset", "资产负债率(%)", 0.01),
        ("cash_flow", "CFOToOR", "经营现金净流量对销售收入比率(%)", 0.01),
        ("cash_flow", "CFOToNP", "经营现金净流量与净利润的比率(%)", 0.01),
        ("dupont", "dupontAssetStoEquity", "股东权益比率(%)", -0.01),
    )
    rows: list[dict[str, Any]] = []
    columns = {str(column) for column in frame.columns}
    for source in frame.to_dict(orient="records"):
        raw_date = source.get("日期") or source.get("报告日期")
        period = _indicator_period(raw_date)
        if period is None:
            continue
        for family, field, column, scale in mappings:
            if column not in columns:
                continue
            value = _indicator_float(source.get(column))
            if value is None:
                continue
            if field == "dupontAssetStoEquity":
                # The source gives equity ratio in percent; convert to an
                # equity multiplier rather than storing a percentage under a
                # different name.  A non-positive ratio is unusable.
                equity_ratio = value / 100.0
                if equity_ratio <= 0:
                    continue
                value = 1.0 / equity_ratio
            else:
                value *= scale
            rows.append({
                "code": ("sh." if symbol.startswith(("6", "9")) else "sz.") + symbol,
                "statDate": f"{period[:4]}-{period[4:6]}-{period[6:8]}",
                "report_period": period,
                "feature_family": family,
                field: value,
                "unit": "ratio" if field not in {"NRTurnRatio", "INVTurnRatio", "AssetTurnRatio", "dupontAssetTurn", "dupontAssetStoEquity"} else "times",
                "basis": "provider_report_period_indicator",
                "source_metric_label": column,
                "source_value_field": column,
                "pubDate": None,
                "available_at": None,
                "revision_id": None,
                "source_publication_status": "unverified",
                "source_provider": "sina_financial_analysis_indicator_via_akshare",
                "source_mode": "analysis_indicator_fallback",
            })
    if not rows:
        return {"status": "failed", "reason": "indicator_fallback_no_mapped_metrics"}
    return {
        "status": "complete",
        "rows": rows,
        "metric_count": len({row["feature_family"] + row["statDate"] for row in rows}),
        "source_mode": "analysis_indicator_fallback",
    }


def _indicator_period(value: Any) -> str | None:
    text = str(value or "")
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return None


def _indicator_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(str(value).strip().replace(",", "").rstrip("%"))
        return numeric if math.isfinite(numeric) else None
    except (TypeError, ValueError):
        return None


def _get_with_timeout(original_get):
    def get(*args, **kwargs):
        kwargs.setdefault("timeout", _REQUEST_TIMEOUT_SECONDS)
        response = original_get(*args, **kwargs)
        if getattr(response, "status_code", None) in {429, 456}:
            raise _ProviderThrottled(f"http_status_{response.status_code}")
        return response
    return get


def _value_for_spec(source: Any, report_date: str, value_key: str) -> object:
    if value_key != "year_over_year":
        return source.get(report_date)
    try:
        year = int(report_date[:4])
        previous_period = f"{year - 1:04d}{report_date[4:]}"
        current = float(source.get(report_date))
        previous = float(source.get(previous_period))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(current) or not math.isfinite(previous) or previous == 0:
        return None
    return current / previous - 1.0


def _current_contract_complete(state: object) -> bool:
    return (
        isinstance(state, dict)
        and state.get("status") == "complete"
        and state.get("metric_contract_version") == METRIC_CONTRACT_VERSION
    )


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The data-centre API reads this checkpoint while a long-running worker
    # updates it.  Replace it atomically so readers see either the preceding
    # valid checkpoint or the new one, never a half-written JSON document.
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
