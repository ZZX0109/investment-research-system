"""§1 step 6 price-path projection regression tests.

``build_price_path_projection`` turns the existing long-term model's
q10/q50/q90 horizon-end quantiles into a forward price path + q10–q90 band,
so the predicted-vs-actual chart shows a real fan (kittenCN temporal port
still pending). These pin the projection + the degrade paths.
"""
from __future__ import annotations

from datetime import datetime, timezone

from investment_research.agent.evaluation import build_price_path_projection

AS_OF = datetime(2026, 8, 14, tzinfo=timezone.utc)


def test_build_price_path_projection_real_fan() -> None:
    readings = {
        "excess_return_240d": {
            "q10": -0.174, "q50": 0.022, "q90": 0.327, "horizon_days": 240,
        }
    }
    proj = build_price_path_projection(readings, 1341.99, AS_OF, realized_mae=0.2585)
    assert proj["status"] == "ok"
    assert proj["horizon_days"] == 240
    assert proj["mean_abs_error_pct"] == 0.2585
    assert "excess_return_240d" in proj["model"]
    pts = proj["points"]
    assert len(pts) >= 2
    # Anchor at as_of: actual == base, predicted == base (t=0).
    first = pts[0]
    assert first["actual"] == 1341.99
    assert first["predicted"] == 1341.99
    assert first["q10"] == 1341.99 and first["q90"] == 1341.99
    # End point: projected, actual null, fan opens to q10<q50<q90.
    last = pts[-1]
    assert last["actual"] is None
    assert last["q10"] < last["predicted"] < last["q90"]
    assert abs(last["predicted"] - 1341.99 * (1 + 0.022)) < 0.5
    assert abs(last["q10"] - 1341.99 * (1 - 0.174)) < 0.5
    assert abs(last["q90"] - 1341.99 * (1 + 0.327)) < 0.5


def test_build_price_path_projection_degrades_without_reading() -> None:
    proj = build_price_path_projection({}, 100.0, AS_OF)
    assert proj["status"] == "unavailable"
    assert proj["reason"] == "no_model_reading"
    assert proj["points"] == []


def test_build_price_path_projection_degrades_without_close() -> None:
    readings = {"excess_return_240d": {"q10": -0.1, "q50": 0.0, "q90": 0.1, "horizon_days": 120}}
    proj = build_price_path_projection(readings, None, AS_OF)
    assert proj["status"] == "unavailable"
    assert proj["reason"] == "no_latest_close"


def test_build_price_path_projection_degrades_without_quantiles() -> None:
    readings = {"excess_return_240d": {"horizon_days": 240}}  # no q10/q50/q90
    proj = build_price_path_projection(readings, 100.0, AS_OF)
    assert proj["status"] == "unavailable"
    assert proj["reason"] == "quantiles_missing"
