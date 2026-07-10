from __future__ import annotations

import argparse
from pathlib import Path
from statistics import quantiles
from typing import Any

from ml.common import FEATURE_VERSION, SYNTHETIC_HISTORY_SOURCE, artifact_path, connect, now_iso, write_json
from ml.data.feature_store import build_feature_metadata, validate_feature_metadata
from ml.data.point_in_time import assert_point_in_time, source_status
from ml.data.providers import synthetic_history
from ml.data.splits import temporal_split
from ml.features.labels import forward_volatility, labels_for_index
from ml.features.market import FEATURE_NAMES, feature_row

DEFAULT_SYMBOL_MARKETS = {
    "NVDA": "us",
    "TSLA": "us",
    "QQQ": "us",
    "XLE": "us",
    "600519": "cn",
    "510300": "cn",
}


def load_history(symbol: str, allow_synthetic: bool) -> list[dict[str, Any]]:
    with connect() as conn:
        if allow_synthetic:
            rows = conn.execute(
                "select trade_date, close_price, volume, source_name from historical_prices where symbol = ? order by trade_date",
                (symbol,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select trade_date, close_price, volume, source_name
                from historical_prices
                where symbol = ?
                  and lower(source_name) not like '%synthetic%'
                  and lower(source_name) not like '%demo%'
                  and lower(source_name) not like '%fallback%'
                order by trade_date
                """,
                (symbol,),
            ).fetchall()
    records = [dict(row) for row in rows]
    if not records and allow_synthetic:
        records = synthetic_history(symbol)
    return records


def volatility_thresholds(closes: list[float]) -> tuple[float, float]:
    vols = [forward_volatility(closes, idx, 21) for idx in range(63, max(64, len(closes) - 21))]
    if len(vols) < 10:
        return 0.35, 0.5
    qs = quantiles(vols, n=5)
    return qs[2], qs[3]


def build_samples(
    symbols: list[str],
    allow_synthetic: bool,
    smoke: bool,
    max_samples_per_symbol: int | None = None,
    compact_feature_metadata: bool = False,
    window_mode: str = "full",
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    per_symbol_limit = max_samples_per_symbol or (48 if smoke else 5000)
    for symbol in symbols:
        symbol_sample_count = 0
        market = DEFAULT_SYMBOL_MARKETS.get(symbol, "cn" if symbol.isdigit() else "us")
        rows = load_history(symbol, allow_synthetic)
        if len(rows) < 130:
            continue
        closes = [float(row["close_price"]) for row in rows]
        volumes = [float(row["volume"]) for row in rows]
        dates = [str(row["trade_date"]) for row in rows]
        source_names = [str(row["source_name"]) for row in rows]
        feature_rows = [feature_row(closes, volumes, idx) for idx in range(len(rows))]
        sources = set(source_names)
        degraded = any(source_status(source) == "degraded" for source in sources)
        vol60, vol80 = volatility_thresholds(closes)
        start = 120
        end = len(rows) - 64
        indexes = range(start, end, max(1, (end - start) // per_symbol_limit)) if (smoke or max_samples_per_symbol) else range(start, end)
        for index in indexes:
            as_of = dates[index]
            assert_point_in_time(as_of, dates[index - 119 : index + 1])
            source_status_value = "degraded" if degraded else "live"
            if source_status_value == "degraded" and not allow_synthetic:
                continue
            field_metadata = build_feature_metadata(
                as_of_date=as_of,
                source=", ".join(sorted(sources)),
                dates=dates[: index + 1],
                sources=source_names[: index + 1],
                tabular_field_count=len(FEATURE_NAMES),
                windows={} if compact_feature_metadata else {"window60": 60, "window120": 120},
            )
            pit_audit = validate_feature_metadata(field_metadata)
            sample = {
                "symbol": symbol,
                "market": market,
                "asOfDate": as_of,
                "featureVersion": FEATURE_VERSION,
                "sourceStatus": source_status_value,
                "fieldMetadata": field_metadata,
                "pointInTimeAudit": pit_audit,
                "split": temporal_split(as_of),
                "featureNames": FEATURE_NAMES,
                "tabular": feature_rows[index],
                "labels": labels_for_index(closes, index, vol60, vol80),
            }
            if window_mode == "full":
                sample["window60"] = feature_rows[index - 59 : index + 1]
                sample["window120"] = feature_rows[index - 119 : index + 1]
            elif window_mode == "window120":
                sample["window120"] = feature_rows[index - 119 : index + 1]
            samples.append(sample)
            symbol_sample_count += 1
            if (smoke or max_samples_per_symbol) and symbol_sample_count >= per_symbol_limit:
                break
    return samples


def build_dataset(
    symbols: list[str],
    output: Path,
    allow_synthetic: bool = False,
    smoke: bool = False,
    max_samples_per_symbol: int | None = None,
    compact_feature_metadata: bool = False,
    window_mode: str = "full",
) -> dict[str, Any]:
    samples = build_samples(
        symbols,
        allow_synthetic=allow_synthetic,
        smoke=smoke,
        max_samples_per_symbol=max_samples_per_symbol,
        compact_feature_metadata=compact_feature_metadata,
        window_mode=window_mode,
    )
    payload = {
        "datasetId": output.name,
        "createdAt": now_iso(),
        "featureVersion": FEATURE_VERSION,
        "symbols": symbols,
        "allowSynthetic": allow_synthetic,
        "smoke": smoke,
        "maxSamplesPerSymbol": max_samples_per_symbol,
        "metadataMode": "compact_tabular" if compact_feature_metadata else "full_window",
        "windowMode": window_mode,
        "sampleCount": len(samples),
        "samples": samples,
    }
    write_json(output / "dataset.json", payload)
    return {"ok": True, "datasetPath": str(output), "sampleCount": len(samples), "symbols": symbols}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="NVDA,TSLA,QQQ,XLE,600519,510300")
    parser.add_argument("--output", default=str(artifact_path("datasets", "investment_research_v1")))
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--max-samples-per-symbol", type=int, default=None)
    parser.add_argument("--compact-feature-metadata", action="store_true")
    parser.add_argument("--window-mode", choices=["full", "window120", "none"], default="full")
    args = parser.parse_args()
    result = build_dataset(
        [item.strip().upper() for item in args.symbols.split(",") if item.strip()],
        Path(args.output),
        allow_synthetic=args.allow_synthetic,
        smoke=args.smoke,
        max_samples_per_symbol=args.max_samples_per_symbol,
        compact_feature_metadata=args.compact_feature_metadata,
        window_mode=args.window_mode,
    )
    print(result)


if __name__ == "__main__":
    main()
