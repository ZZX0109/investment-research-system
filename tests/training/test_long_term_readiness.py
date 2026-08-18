from __future__ import annotations

import json

from scripts.audit_long_term_readiness import build_audit


def test_readiness_audit_fails_closed_when_active_and_pit_evidence_are_missing(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    (artifacts / "download_manifests").mkdir(parents=True)
    (artifacts / "cn_financial_coverage").mkdir(parents=True)
    (artifacts / "cn_security_master").mkdir(parents=True)
    (artifacts / "cn_trading_status").mkdir(parents=True)
    (artifacts / "cn_research_auxiliary").mkdir(parents=True)
    (artifacts / "long_term_training").mkdir(parents=True)
    (artifacts / "download_manifests/latest.json").write_text(
        json.dumps({"status": "blocked", "ready_for_landing": False, "blocked_datasets": ["market_breadth:blocked"]}),
        encoding="utf-8",
    )
    (artifacts / "cn_financial_coverage/latest.json").write_text(
        json.dumps({"quality_status": "degraded", "coverage": 0.97, "pit_verified": False, "low_coverage_fields": ["profit.gpMargin"]}),
        encoding="utf-8",
    )
    for relative in (
        "cn_security_master/latest.json",
        "cn_trading_status/latest.json",
        "cn_research_auxiliary/macro_pit_latest.json",
        "long_term_training/latest.json",
    ):
        (artifacts / relative).write_text(json.dumps({"status": "blocked", "deployment_ready": False}), encoding="utf-8")

    audit = build_audit(tmp_path)

    assert audit["status"] == "blocked"
    assert audit["deployment_ready"] is False
    assert "active snapshot pointer is missing" in " ".join(audit["blocking_reasons"])
    assert "macro_publication_time_not_proven" in audit["blocking_reasons"]
    assert any(check["name"] == "training_prediction_parquet" and check["status"] == "blocked" for check in audit["checks"])
    assert any(check["name"] == "long_term_model_evaluation_contract" and check["status"] == "blocked" for check in audit["checks"])


def test_prediction_artifact_check_accepts_project_relative_parquet_hash(tmp_path) -> None:
    from scripts.audit_long_term_readiness import build_audit

    artifacts = tmp_path / "artifacts"
    for relative in (
        "download_manifests/latest.json",
        "cn_financial_coverage/latest.json",
        "cn_security_master/latest.json",
        "cn_trading_status/latest.json",
        "cn_research_auxiliary/macro_pit_latest.json",
        "long_term_training/latest.json",
    ):
        (artifacts / relative).parent.mkdir(parents=True, exist_ok=True)
    prediction = artifacts / "long_term_training" / "predictions.parquet"
    prediction.write_bytes(b"PAR1-test")
    import hashlib

    digest = hashlib.sha256(prediction.read_bytes()).hexdigest()
    (artifacts / "long_term_training/latest.json").write_text(
        json.dumps({"status": "blocked", "predictions_ref": str(prediction.relative_to(tmp_path)), "predictions_sha256": digest}),
        encoding="utf-8",
    )
    from scripts.audit_long_term_readiness import _prediction_artifact_check

    passed, evidence, reasons = _prediction_artifact_check(tmp_path, json.loads((artifacts / "long_term_training/latest.json").read_text()))
    assert passed is True
    assert evidence["observed_sha256"] == digest
    assert reasons == []


def test_event_semantics_rejects_unqualified_no_event_claim() -> None:
    from scripts.audit_long_term_readiness import _event_semantics_check

    passed, evidence, reasons = _event_semantics_check({
        "records": [{"category": "events", "dataset": "events", "quality_status": "degraded", "missing_reason": "no events"}],
    })
    assert passed is False
    assert evidence["event_record_count"] == 1
    assert "event_missing_semantics_invalid:unqualified_no_event_statement" in reasons

    passed, _, reasons = _event_semantics_check({
        "records": [{"category": "events", "dataset": "events", "quality_status": "degraded", "missing_reason": "provider has no historical coverage", "missing_reason_code": "provider_not_covered"}],
    })
    assert passed is True
    assert reasons == []
