from datetime import date, datetime, timezone
from types import SimpleNamespace

from investment_research.training.pit_join import PITJoinService


def test_join_uses_effective_and_available_time_and_preserves_target_order() -> None:
    t1 = (date(2026, 8, 2), datetime(2026, 8, 2, 10, tzinfo=timezone.utc))
    t2 = (date(2026, 8, 1), datetime(2026, 8, 1, 10, tzinfo=timezone.utc))
    references = [
        {"effective_date": "2026-08-01", "available_at": "2026-08-02T12:00:00+00:00", "revision_id": "late", "value": 2},
        {"effective_date": "2026-07-31", "available_at": "2026-08-01T09:00:00+00:00", "revision_id": "early", "value": 1},
    ]
    result = PITJoinService().join([t1, t2], references)
    assert [item.target_index for item in result] == [0, 1]
    assert result[0].value == 1
    assert result[1].value == 1


def test_join_distinguishes_unavailable_from_zero() -> None:
    target = [(date(2026, 8, 1), datetime(2026, 8, 1, tzinfo=timezone.utc))]
    result = PITJoinService().join(target, [{"effective_date": "2026-08-01", "value": 0}])
    assert result[0].value is None
    assert result[0].missing_reason == "available_at_unproven_or_not_visible"


def test_latest_visible_uses_decision_time_for_domain_records() -> None:
    service = PITJoinService()
    records = [
        SimpleNamespace(
            as_of_date=date(2026, 8, 1),
            as_of_time=datetime(2026, 8, 2, tzinfo=timezone.utc),
            revision_id="r1",
        ),
        SimpleNamespace(
            as_of_date=date(2026, 8, 2),
            as_of_time=datetime(2026, 8, 5, tzinfo=timezone.utc),
            revision_id="r2",
        ),
    ]
    selected = service.latest_visible(records, datetime(2026, 8, 3, tzinfo=timezone.utc))
    assert selected is records[0]


def test_join_rejects_naive_decision_and_available_timestamps() -> None:
    service = PITJoinService()
    target = [(date(2026, 8, 1), datetime(2026, 8, 1, 10))]
    result = service.join(
        target,
        [{"effective_date": "2026-08-01", "available_at": "2026-08-01T09:00:00", "value": 1}],
    )
    assert result[0].value is None
    assert result[0].missing_reason == "decision_time_invalid"

    aware_target = [(date(2026, 8, 1), datetime(2026, 8, 1, 10, tzinfo=timezone.utc))]
    result = service.join(
        aware_target,
        [{"effective_date": "2026-08-01", "available_at": "2026-08-01T09:00:00", "value": 1}],
    )
    assert result[0].value is None
    assert result[0].missing_reason == "available_at_unproven_or_not_visible"
