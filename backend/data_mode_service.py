from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable


DATA_MODE_COPY = {
    "demo": {
        "label": "Demo Mode",
        "description": "固定合成数据，用于稳定演示和评审路径，不声明为真实市场事实。",
        "providerPolicy": "fixed_synthetic_demo",
    },
    "sandbox": {
        "label": "Sandbox Mode",
        "description": "可配置合成/回填数据，用于训练、回归测试和实验，不与真实结论混用。",
        "providerPolicy": "configurable_synthetic_or_backfilled",
    },
    "real": {
        "label": "Real Data Mode",
        "description": "优先连接真实行情、披露、新闻和上传报告；失败时必须显式降级。",
        "providerPolicy": "real_first_with_labeled_fallback",
    },
}


def demo_as_of() -> str:
    return os.getenv("INVESTMENT_RESEARCH_DEMO_AS_OF", "2026-01-02T21:00:00Z").strip() or "2026-01-02T21:00:00Z"


def mode_default_synthetic_ratio(mode: str) -> float:
    if mode == "demo":
        return 1.0
    if mode == "sandbox":
        return 0.75
    return 0.0


def build_data_mode_payload(
    *,
    mode: str,
    as_of: str,
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    copy = DATA_MODE_COPY.get(mode, DATA_MODE_COPY["demo"])
    overrides = []
    if mode == "demo":
        overrides = ["synthetic", "fixed_demo"]
    elif mode == "sandbox":
        overrides = ["synthetic", "sandbox"]
    return {
        "mode": mode,
        **copy,
        "allowedModes": ["demo", "sandbox", "real"],
        "sourceMeta": build_source_meta(
            provider=f"investment_research_{mode}_mode",
            as_of=demo_as_of() if mode == "demo" else as_of,
            overrides=overrides,
            synthetic_ratio=mode_default_synthetic_ratio(mode),
            mode=mode,
        ),
    }


def build_synthetic_market_snapshot(
    symbol: str,
    market: str,
    *,
    mode: str,
    build_source_meta: Callable[..., dict[str, Any]],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
) -> dict[str, Any]:
    seed = sum(ord(char) for char in f"{symbol.upper()}:{market}:{mode}")
    base = 42 + (seed % 240)
    wave = ((seed % 17) - 8) / 100
    close = round(base * (1 + wave), 2)
    day_change = round(((seed % 900) - 450) / 100, 2)
    as_of = demo_as_of() if mode == "demo" else iso(now_utc())
    provider = "synthetic_demo_market_snapshot" if mode == "demo" else "synthetic_sandbox_market_snapshot"
    overrides = ["synthetic", "fixed_demo"] if mode == "demo" else ["synthetic", "sandbox"]
    return {
        "ok": True,
        "marketValueHint": close,
        "dayChange": day_change,
        "sourceName": provider,
        "observedAt": as_of,
        "sourceMeta": build_source_meta(
            provider=provider,
            as_of=as_of,
            overrides=overrides,
            synthetic_ratio=1.0,
            mode=mode,
        ),
    }
