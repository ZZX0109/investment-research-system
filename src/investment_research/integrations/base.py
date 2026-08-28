"""Graceful-degradation primitives shared by all integration adapters.

A live data fetch (akshare/baostock) can fail in three ways that must NOT
crash a research run: (1) the host is network-gated, (2) the symbol has no
data, (3) the provider schema drifted.  ``safe_fetch`` collapses these into a
typed ``FetchResult`` so callers (``market_observation`` fillers, agent tool
handlers) can branch on ``status`` instead of try/except-ing every call.

Network-error detection is conservative: only well-known network signal
words map to ``network_unavailable``; anything else is ``error`` (still
degraded, still non-fatal, but surfaced for diagnosis).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

_NETWORK_SIGNALS = (
    "timeout", "timed out", "connection", "resolve", "unreachable",
    "network", "ssl", "handshake", "refused", "reset",
)


@dataclass
class FetchResult:
    """Typed outcome of one adapter fetch."""

    ok: bool
    status: str  # "ok" | "network_unavailable" | "no_data" | "error"
    provider: str
    data: Any = None
    error: str | None = None
    degraded: bool = False

    @property
    def available(self) -> bool:
        return self.ok and self.status == "ok"


def safe_fetch(
    provider: str,
    fetch: Callable[[], Any],
    *,
    empty_ok: bool = True,
) -> FetchResult:
    """Run ``fetch``; degrade gracefully on network/error/empty results."""
    try:
        data = fetch()
    except Exception as exc:  # noqa: BLE001 - adapter boundary, must not crash
        message = str(exc).lower()
        if any(sig in message for sig in _NETWORK_SIGNALS):
            return FetchResult(
                ok=False, status="network_unavailable", provider=provider,
                error=type(exc).__name__, degraded=True,
            )
        return FetchResult(
            ok=False, status="error", provider=provider,
            error=f"{type(exc).__name__}: {exc!s:.200}", degraded=True,
        )
    if data is None:
        return FetchResult(
            ok=empty_ok, status="no_data", provider=provider, degraded=True,
        )
    try:
        length = len(data)
    except TypeError:
        length = 1
    if length == 0:
        return FetchResult(
            ok=empty_ok, status="no_data", provider=provider, data=data,
            degraded=True,
        )
    return FetchResult(ok=True, status="ok", provider=provider, data=data)


def sh_or_sz(symbol: str) -> str:
    """Return ``'sse'``/``'szse'`` for a 6-digit A-share symbol."""
    return "sse" if symbol.startswith(("6", "5")) else "szse"
