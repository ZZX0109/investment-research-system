from __future__ import annotations

import math
from datetime import date, timedelta


def synthetic_history(symbol: str, days: int = 780) -> list[dict[str, float | str]]:
    seed = sum(ord(char) for char in symbol)
    base = 80 + (seed % 180)
    today = date.today()
    rows: list[dict[str, float | str]] = []
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        if day.weekday() >= 5:
            continue
        wave = math.sin(offset / 24) * 0.018 + math.cos(offset / 51) * 0.011
        drift = 1 + offset * 0.00035
        close = max(5, base * drift * (1 + wave))
        volume = 1_000_000 + (seed % 9) * 130_000 + abs(math.sin(offset / 9)) * 800_000
        rows.append({"trade_date": day.isoformat(), "close_price": round(close, 4), "volume": round(volume, 0), "source_name": "synthetic_demo_price_path"})
    return rows

