#!/usr/bin/env python3
"""Parallel, append-only BaoStock backfill for the current CN universe.

This is a research-tier downloader.  Workers only fetch and return provider
bytes; the parent process is the sole writer to SQLite/object storage.  A
failed request is retained in the coverage ledger and never interpreted as an
empty event or a complete market history.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
import argparse
import json
from pathlib import Path
import signal
import sys
import time
from typing import Any
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.free_research_ledger import build_coverage_ledgers
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

ETF_SYMBOLS = {"159915", "510050", "510300", "510500", "512100"}


def _raise_worker_timeout(_signum, _frame):
    raise TimeoutError("baostock worker deadline exceeded")


def _load_symbols(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        values = [item.get("code") if isinstance(item, dict) else item for item in payload]
    elif isinstance(payload, dict):
        values = payload.get("cn", [])
    else:
        raise ValueError("symbols file must be a current-universe list or market mapping")
    symbols = {
        str(value).strip().rsplit(".", 1)[-1].zfill(6)
        for value in values
        if value not in (None, "")
    }
    return sorted(symbols)


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _latest_trade_date(payload: bytes, fallback: date) -> date:
    previous_handler = None
    previous_timer = (0.0, 0.0)
    try:
        rows = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    values: list[date] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        raw = row.get("日期") or row.get("date")
        try:
            values.append(date.fromisoformat(str(raw)[:10]))
        except (TypeError, ValueError):
            continue
    return max(values, default=fallback)


def _fetch_with_deadline(provider: Any, symbol: str, *, start: date, end: date, mode: str, timeout_seconds: float):
    """Apply a process-local deadline around providers that ignore socket timeouts."""
    if not hasattr(signal, "setitimer"):
        return provider.fetch(symbol, start=start, end=end, adjustment_mode=mode)

    def _raise_timeout(_signum, _frame):
        raise TimeoutError(f"baostock fetch exceeded {timeout_seconds:.1f}s")

    previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return provider.fetch(symbol, start=start, end=end, adjustment_mode=mode)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _worker_fetch(
    chunk: list[str], start: date, end: date, timeout_seconds: float,
    provider_mode: str = "hybrid", modes: tuple[str, ...] = ("raw", "qfq"),
    inter_request_delay: float = 0.0,
) -> list[dict[str, Any]]:
    """Fetch one chunk in an isolated process with one provider session."""
    from investment_research.training.cn_free_providers import (
        AkshareDailyResearchProvider,
        BaostockDailyResearchProvider,
        EastmoneyDailyResearchProvider,
        SinaDailyResearchProvider,
        TencentDailyResearchProvider,
        YahooDailyResearchProvider,
    )

    output: list[dict[str, Any]] = []
    akshare = AkshareDailyResearchProvider()

    def fetch_fallback(symbol: str, mode: str, primary_error: Exception) -> dict[str, Any]:
        """Use the configured public backup after a Baostock failure.

        The old parallel collector treated one Baostock protocol/encoding
        failure as a permanent symbol failure.  That made a full-universe run
        under-count coverage even though the serial collector already had an
        AKShare fallback.  Keep both errors and the provider chain explicit;
        a fallback never upgrades the data tier or hides a conflict.
        """
        try:
            result = _fetch_with_deadline(
                akshare, symbol, start=start, end=end, mode=mode,
                timeout_seconds=timeout_seconds,
            )
            return {
                "market": "cn", "dataset": f"daily_bars_{mode}",
                "provider": "akshare", "provider_chain": ["baostock", "akshare"],
                "symbol": symbol, "adjustment_mode": mode, "status": "backfilled",
                "row_count": result.row_count, "payload": result.payload,
                "degraded_reason": f"baostock_failed:{type(primary_error).__name__}",
            }
        except Exception as fallback_error:
            return {
                "market": "cn", "dataset": f"daily_bars_{mode}",
                "provider": "baostock", "provider_chain": ["baostock", "akshare"],
                "symbol": symbol, "adjustment_mode": mode, "status": "fetch_failed",
                "reason": (
                    f"baostock={type(primary_error).__name__}:{primary_error};"
                    f"akshare={type(fallback_error).__name__}:{fallback_error}"
                ),
            }

    if provider_mode == "public":
        # Independently reachable public endpoints: Sina raw bars and
        # Tencent forward-adjusted bars.  Keep the provider chain explicit in
        # every ledger record; this remains research-only data.
        public_providers = {
            # Yahoo is first for the bulk pass because Sina/Eastmoney may
            # temporarily return empty payloads after a public-rate burst.
            "raw": [YahooDailyResearchProvider(), SinaDailyResearchProvider(), akshare],
            "qfq": [
                YahooDailyResearchProvider(), TencentDailyResearchProvider(),
                EastmoneyDailyResearchProvider(), akshare,
            ],
        }
        for symbol in chunk:
            for mode, providers in public_providers.items():
                if mode not in modes:
                    continue
                # Yahoo and Tencent do not carry the remaining BSE qfq
                # history.  Go directly to the endpoint that does, while
                # retaining the general fallback chain for other symbols.
                # Do not fall through to AKShare here: its underlying public
                # request may itself block behind the same Eastmoney proxy,
                # defeating this worker's hard per-symbol deadline.  Failed
                # BSE calls are explicitly retained and retried by the next
                # resumable repair pass.
                if mode == "qfq" and symbol.startswith(("4", "8", "9")):
                    providers = [EastmoneyDailyResearchProvider()]
                errors: list[str] = []
                for index, provider in enumerate(providers):
                    try:
                        result = _fetch_with_deadline(
                            provider, symbol, start=start, end=end, mode=mode,
                            timeout_seconds=timeout_seconds,
                        )
                        degraded = result.degraded_reason
                        if index:
                            degraded = ";".join(filter(None, [degraded, f"primary_failed:{errors[0]}"]))
                        output.append({
                            "market": "cn", "dataset": f"daily_bars_{mode}",
                            "provider": provider.name, "provider_chain": [item.name for item in providers[:index + 1]],
                            "symbol": symbol, "adjustment_mode": mode, "status": "backfilled",
                            "row_count": result.row_count, "payload": result.payload,
                            "degraded_reason": degraded,
                        })
                        break
                    except Exception as exc:
                        errors.append(f"{provider.name}={type(exc).__name__}:{exc}")
                else:
                    output.append({
                        "market": "cn", "dataset": f"daily_bars_{mode}",
                        "provider": providers[0].name, "provider_chain": [item.name for item in providers],
                        "symbol": symbol, "adjustment_mode": mode, "status": "fetch_failed",
                        "reason": ";".join(errors),
                    })
                if inter_request_delay > 0:
                    time.sleep(inter_request_delay)
        return output
    if provider_mode == "akshare":
        for symbol in chunk:
            for mode in modes:
                try:
                    result = _fetch_with_deadline(
                        akshare, symbol, start=start, end=end, mode=mode,
                        timeout_seconds=timeout_seconds,
                    )
                    output.append({
                        "market": "cn", "dataset": f"daily_bars_{mode}",
                        "provider": "akshare", "provider_chain": ["akshare"],
                        "symbol": symbol, "adjustment_mode": mode, "status": "backfilled",
                        "row_count": result.row_count, "payload": result.payload,
                    })
                except Exception as exc:
                    output.append({
                        "market": "cn", "dataset": f"daily_bars_{mode}",
                        "provider": "akshare", "provider_chain": ["akshare"],
                        "symbol": symbol, "adjustment_mode": mode, "status": "fetch_failed",
                        "reason": f"akshare={type(exc).__name__}:{exc}",
                    })
        return output
    try:
        # Login itself can block in the third-party client, before the socket
        # is available to configure. Bound the complete worker as a final
        # safety net; individual requests have the tighter deadline above.
        worker_deadline = timeout_seconds * max(2 * len(chunk) + 1, 1)
        previous_handler = signal.signal(signal.SIGALRM, _raise_worker_timeout)
        previous_timer = signal.setitimer(signal.ITIMER_REAL, worker_deadline)
        with BaostockDailyResearchProvider(timeout_seconds=timeout_seconds) as provider:
            for symbol in chunk:
                for mode in modes:
                    try:
                        result = _fetch_with_deadline(
                            provider, symbol, start=start, end=end, mode=mode,
                            timeout_seconds=timeout_seconds,
                        )
                        output.append({
                            "market": "cn", "dataset": f"daily_bars_{mode}",
                            "provider": "baostock", "provider_chain": ["baostock"], "symbol": symbol,
                            "adjustment_mode": mode, "status": "backfilled",
                            "row_count": result.row_count, "payload": result.payload,
                        })
                    except Exception as exc:
                        output.append(fetch_fallback(symbol, mode, exc))
    except Exception as exc:
        # Login/initialization can fail before the inner loop runs.  Give the
        # backup provider the same chance, otherwise one transient Baostock
        # outage marks the whole worker chunk as unavailable.
        for symbol in chunk:
            for mode in ("raw", "qfq"):
                output.append(fetch_fallback(symbol, mode, exc))
    finally:
        # Login/worker timeouts can jump directly to the outer exception
        # handler.  Always restore the caller's timer and handler so an
        # in-process test or embedding application cannot receive a stale
        # SIGALRM several seconds after this worker has returned.
        if hasattr(signal, "setitimer"):
            signal.setitimer(signal.ITIMER_REAL, 0)
        if previous_handler is not None:
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])
    return output


def _has_full_history(uow: SQLiteUnitOfWork, object_store: LocalObjectStore, symbol: str, mode: str, end: date) -> bool:
    dataset = f"daily_bars_{mode}"
    for batch in reversed(uow.trusted_market.raw_batches(dataset=dataset, data_tier=DataTier.RESEARCH_PIT.value, symbol=symbol)):
        if batch.coverage_start is not None or batch.coverage_end is None:
            continue
        if (end - batch.coverage_end.date()).days > 10:
            continue
        try:
            rows = json.loads(object_store.get(batch.payload_ref.removeprefix("file-object://")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(rows, list) and len(rows) >= 960:
            return True
    return False


def _full_history_symbols(
    uow: SQLiteUnitOfWork, object_store: LocalObjectStore, *, end: date,
) -> set[tuple[str, str]]:
    """Build the completion index once instead of hydrating the catalog per symbol."""
    complete: set[tuple[str, str]] = set()
    batches = uow.trusted_market.raw_batches(data_tier=DataTier.RESEARCH_PIT.value)
    for batch in batches:
        if batch.dataset not in {"daily_bars_raw", "daily_bars_qfq"}:
            continue
        if not batch.symbol or batch.coverage_end is None or (end - batch.coverage_end.date()).days > 10:
            continue
        try:
            rows = json.loads(object_store.get(batch.payload_ref.removeprefix("file-object://")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(rows, list) and len(rows) >= 960:
            mode = "qfq" if batch.dataset.endswith("_qfq") else "raw"
            complete.add((batch.symbol, mode))
    return complete


def _catalog_symbols(uow: SQLiteUnitOfWork) -> set[tuple[str, str]]:
    """Return symbols with any stored research payload for each requested mode.

    This is intentionally separate from ``_full_history_symbols``.  A newly
    listed BSE security cannot have 960 observations yet, but it is not a
    missing qfq series.  Targeted repair passes must therefore avoid
    repeatedly downloading valid young listings merely to satisfy a generic
    full-history heuristic.
    """
    present: set[tuple[str, str]] = set()
    for batch in uow.trusted_market.raw_batches(data_tier=DataTier.RESEARCH_PIT.value):
        if not batch.symbol or batch.dataset not in {"daily_bars_raw", "daily_bars_qfq"}:
            continue
        present.add((batch.symbol, "qfq" if batch.dataset.endswith("_qfq") else "raw"))
    return present


def _persist(service: RawPayloadIngestionService, item: dict[str, Any], *, end: date) -> dict:
    payload = item.get("payload")
    if not isinstance(payload, bytes):
        return {key: value for key, value in item.items() if key != "payload"}
    provider = str(item.get("provider") or "baostock")
    provider_chain = list(item.get("provider_chain") or [provider])
    observed_end = _latest_trade_date(payload, end)
    now = datetime.now(timezone.utc)
    digest = __import__("hashlib").sha256(payload).hexdigest()
    batch = service.persist(
        provider=provider,
        request_id=f"parallel-{provider}-{item['symbol']}-{item['adjustment_mode']}-{digest}",
        dataset=item["dataset"], payload=payload, schema_version="free-research-v1",
        symbol=item["symbol"], interval="1d", available_at=now, received_at=now,
        market_session="research_parallel_backfill", data_tier=DataTier.RESEARCH_PIT,
        coverage_start=None,
        coverage_end=datetime.combine(observed_end, datetime.max.time(), timezone.utc),
    )
    return {
        "market": "cn", "dataset": item["dataset"], "provider": provider,
        "symbol": item["symbol"], "adjustment_mode": item["adjustment_mode"],
        "status": "backfilled", "rows_or_bytes": item.get("row_count"),
        "payload_hash": batch.payload_hash, "provider_chain": provider_chain,
        "data_tier": DataTier.RESEARCH_PIT.value,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "degraded_reason": item.get("degraded_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols-file", type=Path, required=True)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--chunk-size", type=int, default=5)
    parser.add_argument("--start", type=date.fromisoformat, default=date(1990, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--inter-request-delay", type=float, default=0.0,
        help="Pause between public symbol/mode requests; useful for source rate limits.",
    )
    parser.add_argument(
        "--provider", choices=("hybrid", "akshare", "public"), default="hybrid",
        help="Use direct AKShare, Sina+Tencent public fallback, or BaoStock+AKShare hybrid.",
    )
    parser.add_argument(
        "--modes", default="raw,qfq",
        help="Comma-separated adjustment modes to fetch (raw, qfq); defaults to both.",
    )
    parser.add_argument(
        "--missing-only", action="store_true",
        help="Only fetch symbol/mode pairs absent from the raw research catalog.",
    )
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.workers <= 0 or args.chunk_size <= 0 or args.timeout_seconds <= 0 or args.inter_request_delay < 0:
        raise SystemExit("workers, chunk-size and timeout-seconds must be positive; inter-request-delay cannot be negative")
    modes = tuple(mode.strip() for mode in args.modes.split(",") if mode.strip())
    if not modes or any(mode not in {"raw", "qfq"} for mode in modes):
        raise SystemExit("modes must contain raw and/or qfq")
    symbols = _load_symbols(args.symbols_file)
    if args.max_symbols is not None:
        if args.max_symbols <= 0:
            raise SystemExit("max-symbols must be positive")
        symbols = symbols[:args.max_symbols]

    uow = SQLiteUnitOfWork(args.database)
    object_store = LocalObjectStore(args.object_store)
    service = RawPayloadIngestionService(uow, object_store=object_store)
    try:
        # A targeted repair asks only whether a payload exists; avoid opening
        # every historical object merely to evaluate the 960-row heuristic.
        complete_symbols = set() if args.missing_only else _full_history_symbols(uow, object_store, end=args.end)
        catalog_symbols = _catalog_symbols(uow)
        completion_index = catalog_symbols if args.missing_only else complete_symbols
        pending = [
            symbol for symbol in symbols
            if not all((symbol, mode) in completion_index for mode in modes)
        ]
        records: list[dict] = []
        chunks = _chunks(pending, args.chunk_size)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_worker_fetch, chunk, args.start, args.end, args.timeout_seconds, args.provider, modes, args.inter_request_delay) for chunk in chunks]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    result = [{
                        "market": "cn", "dataset": "daily_bars_raw", "provider": "baostock",
                        "symbol": "WORKER", "status": "fetch_failed",
                        "reason": f"worker_future:{type(exc).__name__}:{exc}",
                    }]
                for item in result:
                    records.append(_persist(service, item, end=args.end) if item.get("status") == "backfilled" else {
                        key: value for key, value in item.items() if key != "payload"
                    })
                print(f"completed chunks {len(records)}/{len(pending) * len(modes)}", flush=True)
    finally:
        uow.close()

    # The downloader is resumable: symbols that already have both verified
    # research batches are intentionally skipped.  Represent those catalog
    # hits in the run ledger so the final coverage ratio describes the whole
    # requested universe rather than only the newly fetched tail.
    for symbol in symbols:
        if all((symbol, mode) in completion_index for mode in modes):
            for mode in modes:
                records.append({
                    "market": "cn", "dataset": f"daily_bars_{mode}",
                    "provider": "catalog", "provider_chain": ["catalog"],
                    "symbol": symbol, "adjustment_mode": mode, "status": "backfilled",
                    "degraded_reason": (
                        "existing_research_batch" if args.missing_only
                        else "existing_verified_research_batch"
                    ),
                })

    generated_at = datetime.now(timezone.utc)
    targets = {"cn": set(symbols), "us": set(), "hk": set(), "jp": set()}
    ledgers = build_coverage_ledgers(records=records, targets=targets, generated_at=generated_at)
    payload = {
        "schema_version": "free-research-coverage-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "historical_visibility_assumption": RESEARCH_VISIBILITY_ASSUMPTION,
        "generated_at": generated_at.isoformat(), "mode": "research_only",
        "formal_deployment_allowed": False, "synthetic_count": 0,
        "records": records, "market_coverage": [item.model_dump(mode="json") for item in ledgers],
        "parallel_config": {"workers": args.workers, "chunk_size": args.chunk_size, "provider": args.provider, "modes": list(modes), "missing_only": args.missing_only, "inter_request_delay": args.inter_request_delay, "start": args.start.isoformat(), "end": args.end.isoformat()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cn = next(item for item in payload["market_coverage"] if item["market"] == "cn")
    print(json.dumps({"status": "research_only", "target_count": cn["target_count"], "successful_target_count": cn["successful_target_count"], "coverage_ratio": cn["coverage_ratio"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
