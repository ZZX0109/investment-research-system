from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from investment_research.domain.pit import PITDataQualityStatus, PITDatasetManifest
from investment_research.training.approval_reports import (
    REQUIRED_SCOPE_REPORTS,
    FormalApprovalReportWriter,
)
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.training.catalog_adapter import PITCatalogAdapter
from investment_research.training.parquet_store import PITParquetStore


def test_scope_approval_writer_requires_all_reports_and_drafts_not_ready_manifest(tmp_path) -> None:
    writer = FormalApprovalReportWriter(tmp_path)
    reports = {name: {"name": name} for name in REQUIRED_SCOPE_REPORTS}
    uow = SQLiteUnitOfWork(tmp_path / "catalog.db")
    hashes = writer.write(
        training_run_id="run-1", market="cn", decision_context="close_confirmed",
        task="drawdown_20d", reports=reports, catalog=uow.pit_catalog,
        artifact_ref_prefix="file-object://approval/run-1/cn/close_confirmed/drawdown_20d",
    )
    assert len(hashes) == len(REQUIRED_SCOPE_REPORTS)
    adapter = PITCatalogAdapter(
        uow.pit_catalog, PITParquetStore(LocalObjectStore(tmp_path / "objects"))
    )
    evidence = adapter.verify_approval_evidence(
        training_run_id="run-1", market="cn", decision_context="close_confirmed",
        task="drawdown_20d", expected_hashes=hashes,
    )
    assert [item.evidence_type for item in evidence] == sorted(REQUIRED_SCOPE_REPORTS)
    dataset = PITDatasetManifest(
        id=uuid4(), training_run_id="run-1", market="cn", decision_context="close_confirmed",
        task="drawdown_20d", parquet_refs=["file-object://sample.parquet"], row_count=1,
        dataset_hash=sha256(b"dataset").hexdigest(), schema_hash=sha256(b"schema").hexdigest(),
        feature_version="investment-risk-features-v2", label_version="four-market-tradeable-label-v1",
        historical_universe_version="v1", leakage_report_hash=sha256(b"leakage").hexdigest(),
        quality_status=PITDataQualityStatus.PASSED, created_at=datetime.now(timezone.utc),
    )
    manifest = writer.draft_manifest(
        dataset=dataset, report_hashes=hashes, model_name="risk", model_version="v1",
        baseline_name="baseline", artifact_hashes={"risk.pkl": sha256(b"model").hexdigest()},
        calibration_method="platt", critical_data_coverage=0.99,
        formal_synthetic_output_count=0,
        metrics_passed={
            "pit_leakage": True, "calibration": True, "holdout_12m": True,
            "stress_6m": True, "market_regime": True, "cost_liquidity": True,
        },
    )
    assert manifest.status == "approved"
    assert not manifest.deployment_ready
    assert manifest.approval_evidence_hashes == hashes
    uow.close()


def test_scope_approval_writer_rejects_pending_report_placeholders(tmp_path) -> None:
    reports = {name: {"status": "evaluated"} for name in REQUIRED_SCOPE_REPORTS}
    reports["ablation"] = {"status": "pending_formal_feature_group_execution"}

    with pytest.raises(ValueError, match="pending placeholders"):
        FormalApprovalReportWriter(tmp_path).write(
            training_run_id="run-1", market="cn", decision_context="close_confirmed",
            task="drawdown_20d", reports=reports,
        )
