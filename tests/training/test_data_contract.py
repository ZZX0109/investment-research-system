from datetime import date, datetime, timezone

import pytest

from investment_research.training.data_contract import (
    CanonicalDataRecord,
    EventCoverage,
    MissingReason,
    PITEventRecord,
    PITFinancialRecord,
    PITFinancingRecord,
    PITMarketBreadthRecord,
    PITSecurityMasterRecord,
    PITTradingStatusRecord,
    QualityStatus,
)


def _base(**updates):
    value = dict(
        symbol="000001",
        trade_date=date(2026, 8, 1),
        revision_id="rev-1",
        collected_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        provider="test",
        raw_hash="a" * 64,
        quality_status=QualityStatus.COMPLETE,
    )
    value.update(updates)
    return value


def test_complete_record_requires_a_business_date() -> None:
    with pytest.raises(ValueError, match="trade_date or effective_date"):
        CanonicalDataRecord(**_base(trade_date=None))


def test_missing_semantics_are_not_encoded_as_complete_zero() -> None:
    record = CanonicalDataRecord(
        **_base(
            quality_status=QualityStatus.UNAVAILABLE,
            missing_reason=MissingReason.PROVIDER_NOT_COVERED,
        )
    )
    assert record.missing_reason == MissingReason.PROVIDER_NOT_COVERED


def test_availability_can_precede_local_collection_time() -> None:
    record = CanonicalDataRecord(
        **_base(
            published_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            available_at=datetime(2026, 8, 1, 12, tzinfo=timezone.utc),
            collected_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
    )
    assert record.available_at < record.collected_at


def test_complete_record_requires_pit_timestamps() -> None:
    with pytest.raises(ValueError, match="published_at and available_at"):
        CanonicalDataRecord(**_base(published_at=None, available_at=None))


def test_pit_timestamps_require_explicit_timezone() -> None:
    with pytest.raises(ValueError, match="published_at requires an explicit timezone"):
        CanonicalDataRecord(**_base(published_at=datetime(2026, 8, 1)))


def test_financial_contract_retains_period_scope_and_units() -> None:
    record = PITFinancialRecord(
        **_base(effective_date=date(2026, 5, 1)),
        report_period_start=date(2026, 1, 1),
        report_period_end=date(2026, 3, 31),
        filing_kind="quarterly",
        statement_scope="single_quarter",
        unit="CNY_million",
        value=10.0,
    )
    assert record.statement_scope == "single_quarter"


def test_financial_contract_rejects_ambiguous_statement_scope() -> None:
    with pytest.raises(ValueError):
        PITFinancialRecord(
            **_base(effective_date=date(2026, 5, 1)),
            report_period_start=date(2026, 1, 1),
            report_period_end=date(2026, 3, 31),
            filing_kind="quarterly",
            statement_scope="annual_total",
            unit="CNY_million",
            value=10.0,
        )


def test_event_provider_gap_requires_explicit_reason() -> None:
    with pytest.raises(ValueError, match="requires missing_reason"):
        PITEventRecord(
            **_base(quality_status=QualityStatus.DEGRADED),
            event_type="announcement",
            event_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
            coverage=EventCoverage.PROVIDER_NOT_COVERED,
        )


def test_security_master_contract_retains_lifecycle_fields() -> None:
    record = PITSecurityMasterRecord(
        **_base(
            effective_date=date(2020, 1, 1),
            quality_status=QualityStatus.DEGRADED,
            missing_reason=MissingReason.PROVIDER_NOT_COVERED,
        ),
        instrument_type="equity",
        valid_from=date(2020, 1, 1),
        industry_key="bank",
    )
    assert record.instrument_type == "equity"


def test_status_financing_and_breadth_contracts_are_explicit() -> None:
    status = PITTradingStatusRecord(**_base(), is_tradeable=False, is_suspended=True)
    financing = PITFinancingRecord(**_base(), market="sh", balance=10.0, publication_lag_seconds=86400)
    breadth = PITMarketBreadthRecord(**_base(), historical_universe_version="u1", member_count=2, return_observation_count=2, advance_ratio=0.5)
    assert status.is_suspended and financing.market == "sh" and breadth.member_count == 2


def test_financing_lag_must_match_source_timestamps() -> None:
    with pytest.raises(ValueError, match="publication_lag_seconds"):
        PITFinancingRecord(**_base(), market="sh", balance=10.0, publication_lag_seconds=1)


def test_breadth_cannot_claim_more_returns_than_members() -> None:
    with pytest.raises(ValueError, match="return_observation_count"):
        PITMarketBreadthRecord(
            **_base(),
            historical_universe_version="u1",
            member_count=1,
            return_observation_count=2,
        )
