"""Shared CN universe-file parsing for resumable research collectors.

The current public enumeration is intentionally treated as a denominator only;
it does not provide historical lifecycle or PIT publication evidence.  Keeping
parsing in one module prevents individual backfill scripts from silently
falling back to the old 167-symbol research pool when a full-universe file is
requested.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

ETF_SYMBOLS = frozenset({"159915", "510050", "510300", "510500", "512100"})


def normalize_cn_symbols(values: Iterable[Any], *, exclude_etf: bool = False) -> list[str]:
    symbols: set[str] = set()
    for value in values:
        raw = value.get("code") if isinstance(value, dict) else value
        if raw in (None, ""):
            continue
        symbol = str(raw).strip().rsplit(".", 1)[-1].zfill(6)
        if len(symbol) != 6 or not symbol.isdigit():
            continue
        if exclude_etf and symbol in ETF_SYMBOLS:
            continue
        symbols.add(symbol)
    return sorted(symbols)


def load_cn_symbols(path: Path, *, exclude_etf: bool = False) -> list[str]:
    """Load list, ``{"cn": [...]}``, or current-master record JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cn_universe_file_unreadable:{path}") from exc
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = payload.get("cn")
        if values is None:
            values = payload.get("symbols")
        if values is None:
            values = payload.get("securities")
    else:
        values = None
    if not isinstance(values, list):
        raise ValueError(f"cn_universe_file_shape_invalid:{path}")
    symbols = normalize_cn_symbols(values, exclude_etf=exclude_etf)
    if not symbols:
        raise ValueError(f"cn_universe_file_empty:{path}")
    return symbols
