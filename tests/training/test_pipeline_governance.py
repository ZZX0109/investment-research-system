from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from investment_research.training.pipeline_config import (
    PipelineMode,
    ProviderConfig,
    TrainingPipelineConfig,
)
from investment_research.training.publisher import (
    PublicationBlocked,
    attach_approval_evidence,
    validate_publishable_manifest,
)


def _config(**updates) -> TrainingPipelineConfig:
    payload = {
        "mode": PipelineMode.FORMAL,
        "markets": ["cn"],
        "start_date": date(2020, 1, 1),
        "end_date": date(2026, 1, 1),
        "targets": ["future_max_drawdown_20d"],
        "embargo_days": 20,
        "providers": {"cn": ProviderConfig(primary="licensed", authorized=True)},
        "allow_synthetic": False,
    }
    payload.update(updates)
    return TrainingPipelineConfig.model_validate(payload)


def test_formal_config_forbids_synthetic_and_short_embargo() -> None:
    with pytest.raises(ValueError, match="cannot allow synthetic"):
        _config(allow_synthetic=True)
    with pytest.raises(ValueError, match="longest target horizon"):
        _config(embargo_days=19)


def test_run_directories_are_isolated_by_mode_and_id() -> None:
    formal = _config()
    research = formal.model_copy(update={"mode": PipelineMode.RESEARCH})
    assert formal.run_root("run-1") != research.run_root("run-1")
    assert formal.run_root("run-1") != formal.run_root("run-2")


def test_manifest_is_single_publish_fact_source(tmp_path) -> None:
    model_dir = tmp_path / "models"
    audit_dir = tmp_path / "audits"
    model_dir.mkdir()
    audit_dir.mkdir()
    artifact = model_dir / "model.pkl"
    artifact.write_bytes(b"model")
    artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "model-artifact-set-v3",
        "deployment_ready": True,
        "legacy_cutoff_semantics": False,
        "data_source": "real",
        "training_run_id": "run-1",
        "config_hash": "config-1",
        "feature_contract_version": "investment-risk-features-v2",
        "decision_context": "close_confirmed",
        "artifact_hashes": {"model.pkl": artifact_hash},
    }
    (model_dir / "model_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    approval = audit_dir / "approval_report.json"
    approval.write_text('{"eligible": true}', encoding="utf-8")

    attach_approval_evidence(
        model_dir, training_run_id="run-1", evidence_paths=[approval]
    )
    validated = validate_publishable_manifest(
        model_dir,
        expected_training_run_id="run-1",
        expected_config_hash="config-1",
        expected_feature_contract="investment-risk-features-v2",
    )
    assert validated["approval_evidence_complete"] is True

    with pytest.raises(PublicationBlocked, match="config_hash"):
        validate_publishable_manifest(
            model_dir,
            expected_training_run_id="run-1",
            expected_config_hash="different",
            expected_feature_contract="investment-risk-features-v2",
        )
