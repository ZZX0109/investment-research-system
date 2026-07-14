from __future__ import annotations

from uuid import uuid4

import pytest

from investment_research.domain.base import Provenance, utc_now
from investment_research.domain.enums import (
    AssetType,
    DataMode,
    DataSourceType,
    EvidenceType,
    JudgeVerdict,
)
from investment_research.domain.long_term_models import Claim
from investment_research.domain.models import AnalysisRun, Asset, Evidence, User
from investment_research.repository.postgres_compat import _translate_sql
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.outbox import OutboxService


def _provenance() -> Provenance:
    return Provenance(
        data_mode=DataMode.REAL,
        source_type=DataSourceType.REAL,
        source_name="test-source",
        observed_at=utc_now(),
    )


def _user(email: str) -> User:
    return User(email=email, display_name=email.split("@")[0], auth_subject=f"user:{uuid4()}", provenance=_provenance())


def _asset() -> Asset:
    return Asset(ticker="AAPL", name="Apple", asset_type=AssetType.EQUITY, provenance=_provenance())


def test_claim_chain_is_deduplicated_and_viewer_is_read_only(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "domain.db")
    owner = _user("owner@example.com")
    viewer = _user("viewer@example.com")
    uow.users.add(owner, password_hash="x")
    uow.users.add(viewer, password_hash="x")
    asset = uow.assets.add(_asset())
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=owner.id)
    evidence = Evidence(
        asset_id=asset.id,
        evidence_type=EvidenceType.FILING,
        title="10-Q",
        summary="Revenue increased.",
        source_url="https://www.sec.gov/example",
        collected_at=utc_now(),
        published_at=utc_now(),
        normalized_hash="a" * 64,
        raw_hash="b" * 64,
        provenance=_provenance(),
    )
    uow.evidence.add(evidence)
    first_id = uow.domain.register_evidence(evidence=evidence, owner=owner)
    second_id = uow.domain.register_evidence(evidence=evidence, owner=owner)
    claim = Claim(
        id=uuid4(),
        asset_id=asset.id,
        owner_user_id=owner.id,
        statement="Revenue trend improved.",
        direction="positive",
        confidence=0.8,
        evidence_ids=[evidence.id],
    )
    uow.domain.submit_claim(claim, owner=owner)
    uow.domain.create_share(resource_type="asset", resource_id=asset.id, viewer=viewer, owner=owner)

    assert first_id == second_id
    assert uow.connection.execute("SELECT COUNT(*) FROM source_revisions").fetchone()[0] == 1
    assert [item.id for item in uow.domain.list_claims(asset_id=str(asset.id), user=viewer)] == [claim.id]
    with pytest.raises(ValueError, match="Resource not found"):
        uow.domain.assert_access(resource_type="asset", resource_id=str(asset.id), user_id=viewer.id, write=True)
    uow.close()


def test_completed_research_run_is_immutable_and_gate_is_outboxed(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "runs.db")
    owner = _user("owner@example.com")
    uow.users.add(owner, password_hash="x")
    asset = uow.assets.add(_asset())
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=owner.id)
    run = AnalysisRun(
        asset_id=asset.id,
        triggered_by=owner.auth_subject,
        input_snapshot_ref="snapshot://run",
        input_snapshot_hash="c" * 64,
        as_of=utc_now(),
        provenance=_provenance(),
    )
    uow.analysis_runs.add(run)
    uow.domain.record_research_run(run=run, owner=owner, correlation_id=str(run.id))
    uow.domain.record_gate_evaluation(
        run=run,
        owner=owner,
        verdict=JudgeVerdict.HOLD,
        score=0.6,
        reasons=["Evidence is stale"],
        correlation_id=str(run.id),
    )
    changed = run.model_copy(update={"input_snapshot_hash": "d" * 64})

    with pytest.raises(ValueError, match="immutable"):
        uow.domain.record_research_run(run=changed, owner=owner, correlation_id=str(run.id))
    assert uow.connection.execute("SELECT COUNT(*) FROM gate_findings").fetchone()[0] == 1
    assert uow.connection.execute("SELECT COUNT(*) FROM outbox_events WHERE state='pending'").fetchone()[0] >= 2
    uow.close()


def test_outbox_delivery_is_bounded_and_idempotent(tmp_path) -> None:
    uow = SQLiteUnitOfWork(tmp_path / "outbox.db")
    owner = _user("owner@example.com")
    uow.users.add(owner, password_hash="x")
    asset = uow.assets.add(_asset())
    uow.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=owner.id)

    uow.connection.execute(
        "INSERT INTO outbox_events (id,aggregate_type,aggregate_id,event_type,correlation_id,payload_json,state,attempts,occurred_at,processed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid4()), "asset", str(asset.id), "asset.refreshed", str(asset.id), "{}", "pending", 0, utc_now().isoformat(), None),
    )
    uow.connection.commit()

    assert OutboxService(uow).drain(limit=1) == {"delivered": 1, "failed": 0, "pending": 0}
    assert OutboxService(uow).drain(limit=1) == {"delivered": 0, "failed": 0, "pending": 0}
    assert uow.connection.execute("SELECT state FROM outbox_events").fetchone()[0] == "delivered"
    uow.close()


def test_postgres_sql_translation_preserves_repository_upsert_intent() -> None:
    translated = _translate_sql(
        "INSERT OR REPLACE INTO resource_shares (id,resource_id,role) VALUES (?,?,?)"
    )
    assert translated == (
        "INSERT INTO resource_shares (id,resource_id,role) VALUES (%s,%s,%s) "
        "ON CONFLICT (id) DO UPDATE SET resource_id=EXCLUDED.resource_id, role=EXCLUDED.role"
    )
    assert _translate_sql("INSERT OR IGNORE INTO research_run_evidence (run_id,evidence_id) VALUES (?,?)") == (
        "INSERT INTO research_run_evidence (run_id,evidence_id) VALUES (%s,%s) ON CONFLICT DO NOTHING"
    )
    assert _translate_sql("INSERT OR REPLACE INTO llm_cache_entries (cache_key,response_json) VALUES (?,?)") == (
        "INSERT INTO llm_cache_entries (cache_key,response_json) VALUES (%s,%s) "
        "ON CONFLICT (cache_key) DO UPDATE SET response_json=EXCLUDED.response_json"
    )
