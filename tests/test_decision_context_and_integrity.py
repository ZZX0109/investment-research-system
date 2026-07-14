from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import pytest

from investment_research.domain.decision_context import (
    DecisionContextType,
    build_decision_context,
)
from investment_research.pipeline.artifact_integrity import (
    ArtifactIntegrityError,
    verify_artifact_set,
)


def test_close_and_pre_open_are_distinct_pit_contracts() -> None:
    trading_dates = [date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14)]
    close = build_decision_context(
        date(2026, 7, 10),
        DecisionContextType.CLOSE_CONFIRMED,
        trading_dates=trading_dates,
    )
    pre_open = build_decision_context(
        date(2026, 7, 10),
        DecisionContextType.PRE_OPEN,
        trading_dates=trading_dates,
    )
    overnight = datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc)

    assert close.decision_time.isoformat() == "2026-07-10T15:10:00+08:00"
    assert pre_open.decision_time.isoformat() == "2026-07-13T09:10:00+08:00"
    assert close.prediction_start_date == date(2026, 7, 13)
    assert not close.permits(overnight)
    assert pre_open.permits(overnight)


def test_artifact_set_fails_closed_after_tampering(tmp_path) -> None:
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(b"approved bytes")
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = {"artifact_hashes": {"model.pkl": expected}}

    verify_artifact_set(tmp_path, manifest)
    artifact.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        verify_artifact_set(tmp_path, manifest)
