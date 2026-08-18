from datetime import date, datetime, timezone

from investment_research.domain.trusted_market import SecurityMasterRecord, SecurityStateRecord
from investment_research.repository.sqlite import SQLiteUnitOfWork


def _time(day: int) -> datetime:
    return datetime(2026, 8, day, tzinfo=timezone.utc)


def test_security_as_of_uses_available_time_and_revision_visibility(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "market.db")
    security = SecurityMasterRecord(
        symbol="000001",
        exchange="XSHE",
        instrument_type="equity",
        name="fixture",
        listed_on=date(2020, 1, 1),
        currency="CNY",
        source_time=_time(1),
        ingest_time=_time(2),
        available_at=_time(2),
    )
    uow.trusted_market.add_security(security)
    early = SecurityStateRecord(
        security_id=security.id,
        effective_from=_time(1),
        is_st=True,
        source_time=_time(1),
        ingest_time=_time(2),
        available_at=_time(2),
    )
    late_revision = early.model_copy(update={"id": __import__("uuid").uuid4(), "is_st": False, "available_at": _time(5)})
    uow.trusted_market.add_security_state(early)
    uow.trusted_market.add_security_state(late_revision)

    assert uow.trusted_market.security_as_of("000001", _time(3))[1].is_st is True
    assert uow.trusted_market.security_as_of("000001", _time(1)) is None
    uow.close()
