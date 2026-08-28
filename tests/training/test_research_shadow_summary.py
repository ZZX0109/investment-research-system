from datetime import date, datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from uuid import uuid4

from investment_research.domain.pit import EventCoverageStatus
from investment_research.service.research_shadow import FileResearchShadowStore, ResearchShadowSession


def _load_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "build_research_shadow_summary.py"
    spec = importlib.util.spec_from_file_location("build_research_shadow_summary", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _freeze(store: FileResearchShadowStore, trade_date: date) -> None:
    store.freeze(ResearchShadowSession(
        id=uuid4(), market="cn", decision_context="close_confirmed", cohort="cn_equity_core",
        task="direction_1d", symbol="600000", trade_date=trade_date,
        frozen_at=datetime.combine(trade_date, datetime.min.time(), timezone.utc),
        market_snapshot_id=f"snapshot-{trade_date.isoformat()}",
        market_snapshot_hash="a" * 64, data_tier="research_pit",
        coverage_ratio=1.0, event_coverage_status=EventCoverageStatus.CONFIRMED_NONE,
        provider_chain=["test"], model_artifact_hashes={"model": "b" * 64},
        frozen_prediction={"score": 0.1}, evidence_valid=True,
    ))


def test_summary_counts_independent_dates_not_wide_single_day_batches(tmp_path: Path) -> None:
    module = _load_script()
    first = FileResearchShadowStore(tmp_path / "runs" / "run-1")
    second = FileResearchShadowStore(tmp_path / "runs" / "run-2")
    _freeze(first, date(2026, 1, 2))
    _freeze(first, date(2026, 1, 5))
    _freeze(second, date(2026, 1, 5))
    payload = module.build_summary(
        tmp_path, market="cn", decision_context="close_confirmed", minimum_trade_dates=60,
    )
    assert payload["session_count"] == 3
    assert payload["valid_trade_date_count"] == 2
    assert payload["status"] == "blocked"
    assert payload["minimum_required_trade_dates"] == 60
    assert payload["real_prediction_trade_date_count"] == 2
    assert payload["empty_prediction_trade_date_count"] == 0
    assert payload["prediction_trade_date_coverage"] == 1.0
    assert payload["prediction_state_counts"] == {
        "real_prediction": 3,
        "placeholder_abstain": 0,
        "gated_abstain": 0,
        "invalid_evidence": 0,
    }
    assert payload["abstain_reason_counts"] == {}
