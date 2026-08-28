"""§1 row-5 kittenCN temporal adapter (the temporal-port hook).

Lazily bridges the price-path runner to the vendored kittenCN models
(``vendor/kittencn``) + torch + trained weights to produce a *daily temporal*
price path.  Returns ``None`` (degrade) when ANY prerequisite is missing —
vendored source absent, torch unavailable, or no trained weights — so the
runner falls back to the quantile projection.

This module owns NO kittenCN source (the vendor clone + training happen in a
dedicated round); it only bridges the runner to the vendored models when they
exist.  The three prerequisite checks below are deliberately explicit so the
degrade is auditable (``why is the chart showing the quantile fan not a daily
temporal path?`` → because one of these is missing).
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Mapping
from uuid import UUID

# Path to vendored kittenCN source (a future training round runs
# ``git clone https://github.com/KittenCN/stock_prediction vendor/kittencn``
# since this repo is not git-initialized).  Overridable via env for tests.
_VENDOR_ROOT = os.environ.get("KITTENCN_VENDOR_ROOT", "vendor/kittencn")
# Path to trained kittenCN weights (a future training round produces these).
_WEIGHTS_PATH = os.environ.get("KITTENCN_WEIGHTS_PATH", "")


def is_available() -> bool:
    """True iff every kittenCN temporal prerequisite is in place."""
    return bool(_vendored_source_present() and _torch_available() and _weights_present())


def prereq_status() -> dict[str, Any]:
    """Report each kittenCN temporal prerequisite individually so callers can
    cite "kittenCN 时序：源已备✓/torch✓/权重待训练✗" — the honest
    partial-availability state (训练说清楚).  Returns ``{vendored_source,
    torch, trained_weights, ready, blocking}`` where ``blocking`` names the
    missing prereqs (empty when ready)."""
    source_ok = _vendored_source_present()
    torch_ok = _torch_available()
    weights_ok = _weights_present()
    blocking = [
        name
        for name, ok in (
            ("vendored_source", source_ok),
            ("torch", torch_ok),
            ("trained_weights", weights_ok),
        )
        if not ok
    ]
    return {
        "vendored_source": source_ok,
        "torch": torch_ok,
        "trained_weights": weights_ok,
        "ready": bool(source_ok and torch_ok and weights_ok),
        "blocking": blocking,
    }


def forecast_temporal_path(
    symbol: str,
    model_readings: Mapping[str, Any] | None,
    latest_close: float | None,
    as_of: Any,
    realized_mae: float | None,
    task: str,
    *,
    asset_id: str | UUID | None = None,
    repo: Any = None,
    project_root: Any = None,
    anchor_close: float | None = None,
    anchor_date: Any = None,
) -> dict[str, Any] | None:
    """Produce a daily temporal price path.

    Round 31: prefer the VENDORED kittenCN ``TemporalHybridNet`` (the §1 row-5
    NAMED model, trained price-only on real daily bars in
    ``artifacts/price_path/temporal_hybrid.pt``) — the faithful port of the
    architecture the goal names.  Falls back to the round-29 self-contained
    price-only LSTM (``TemporalPricePathRunner``) when the vendored weights are
    absent; degrades to ``None`` (→ quantile fan) when neither is available.
    """
    # 0) Direct multi-horizon path.  It is deliberately an independent
    # artifact: only a complete, evaluated direct model can replace the legacy
    # recursive one-step paths below.
    if repo is not None and project_root is not None:
        try:
            from investment_research.training.price_path.direct_multihorizon_runner import (
                DirectMultiHorizonPricePathRunner,
            )

            direct = DirectMultiHorizonPricePathRunner(project_root)
            if direct.is_available():
                out = direct.forecast_path_for_symbol(repo, symbol, anchor_close=anchor_close, anchor_date=anchor_date)
                if out:
                    return out
        except Exception:
            pass
    # 1) vendored kittenCN TemporalHybridNet (round 31 — the named §1 row-5 model)
    if repo is not None and project_root is not None:
        try:
            from investment_research.training.price_path.temporal_vendored_runner import (
                TemporalVendoredRunner,
            )

            vr = TemporalVendoredRunner(project_root, model_kind="temporal_hybrid")
            if vr.is_available():
                out = vr.forecast_path_for_symbol(repo, symbol, anchor_close=anchor_close, anchor_date=anchor_date)
                if out:
                    return out
        except Exception:
            pass
    # 1b) vendored kittenCN PTFTVSSMEnsemble (round 31 — the OTHER named §1 row-5 model)
    if repo is not None and project_root is not None:
        try:
            from investment_research.training.price_path.temporal_vendored_runner import (
                TemporalVendoredRunner,
            )

            vr = TemporalVendoredRunner(project_root, model_kind="ptft_vssm")
            if vr.is_available():
                out = vr.forecast_path_for_symbol(repo, symbol, anchor_close=anchor_close, anchor_date=anchor_date)
                if out:
                    return out
        except Exception:
            pass
    # 2) self-contained price-only temporal LSTM (round 29 — the temporal CORE)
    if repo is not None and project_root is not None:
        try:
            from investment_research.training.price_path.temporal_runner import (
                TemporalPricePathRunner,
            )

            tr = TemporalPricePathRunner(project_root)
            if tr.is_available():
                return tr.forecast_path_for_symbol(repo, symbol, anchor_close=anchor_close, anchor_date=anchor_date)
        except Exception:
            pass
    # 3) full vendored kittenCN model with BERT (multi-hour — future round)
    if not is_available():
        return None
    try:
        module = importlib.import_module("vendor.kittencn.src.stock_prediction.models")
    except ImportError:
        return None
    _ = module
    return None


def _vendored_source_present() -> bool:
    if not os.path.isdir(_VENDOR_ROOT):
        return False
    # A loose signal the kittenCN source is actually vendored (not an empty
    # dir) — the models package path kittenCN ships.
    return os.path.exists(os.path.join(_VENDOR_ROOT, "src", "stock_prediction"))


def _torch_available() -> bool:
    try:
        importlib.import_module("torch")  # noqa: F401
        return True
    except ImportError:
        return False


def _weights_present() -> bool:
    return bool(_WEIGHTS_PATH) and os.path.exists(_WEIGHTS_PATH)
