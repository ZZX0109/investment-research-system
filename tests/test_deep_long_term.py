import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest

from investment_research.service.deep_long_term import (
    DeepLongTermArtifactError,
    DeepLongTermInferenceService,
    LONG_TERM_TASKS,
    build_deep_long_term_artifact_manifest,
    load_deep_long_term_registry_summary,
    write_long_term_model_readings,
)
from investment_research.training.sequence_dataset import SequenceExample
from investment_research.training.sequence_models import SequenceModelConfig, SequenceTaskRunner


def _semantic_hash(value, *, sort_keys=False):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":")).encode()).hexdigest()


def _example(symbol: str, *, snapshot: str = "snapshot-1", target: float = 0.1) -> SequenceExample:
    width, window = 2, 20
    values = np.asarray([[0.01 * (index + 1), 0.02] for index in range(window)], dtype=np.float32)
    missing = np.zeros((window, width), dtype=bool)
    quality = np.asarray([[1.0, 1.0, 0.0] for _ in range(window)], dtype=np.float32)
    events = np.asarray([[0.0, 1.0] for _ in range(window)], dtype=np.float32)
    providers = np.ones(window, dtype=np.int64)
    delays = np.zeros(window, dtype=np.float32)
    return SequenceExample(
        symbol=symbol,
        market="cn",
        decision_context="close_confirmed",
        decision_time="2026-08-14T07:00:00+00:00",
        feature_cutoff="2026-08-14T07:00:00+00:00",
        window_sessions=window,
        feature_order=["feature_a", "feature_b"],
        values=values,
        data_quality_mask=quality,
        event_missing_mask=events,
        provider_ids=providers,
        revision_ids=[None] * window,
        source_delay_seconds=delays,
        cache_states=["fresh"] * window,
        missing_mask=missing,
        target=target,
        market_snapshot_id=snapshot,
        market_snapshot_hash="hash-1",
        sequence_hash="sequence-1",
    )


def _write_fixture_roster(tmp_path: Path) -> Path:
    runner = SequenceTaskRunner(
        SequenceModelConfig(
            architecture="deep_mlp", task="excess_return_120d", window_sessions=20,
            hidden_size=4, layers=1, batch_size=2, max_epochs=1, patience=1,
        ),
        seed=42,
    ).fit([_example("600000", target=0.1), _example("000001", target=-0.1)])
    model = tmp_path / "model.pt"
    model_hash = runner.save(model)
    feature_order = list(runner.feature_order)
    normalizer = {key: list(value) for key, value in runner.stats.items()}
    feature_path = tmp_path / "feature_order.json"
    normalizer_path = tmp_path / "normalizer.json"
    evaluation_path = tmp_path / "evaluation.json"
    feature_path.write_text(json.dumps(feature_order), encoding="utf-8")
    normalizer_path.write_text(json.dumps(normalizer, sort_keys=True), encoding="utf-8")
    evaluation_path.write_text(json.dumps({
        "schema_version": "cn-sequence-evaluation-v1",
        "status": "research_only",
        "deployment_ready": False,
        "task": "excess_return_120d",
        "architecture": "deep_mlp",
        "variant": "fixture",
        "result": {"fold_hash": "a" * 64},
    }), encoding="utf-8")
    registry = {
        "schema_version": "long-term-deep-model-roster-v1",
        "status": "research_only",
        "deployment_ready": False,
        "models": {
            "excess_return_120d": {
                "architecture": "deep_mlp", "variant": "fixture",
                "model_ref": "model.pt", "evaluation_ref": "evaluation.json",
                "feature_order_ref": "feature_order.json", "normalizer_ref": "normalizer.json",
                "model_hash": model_hash,
                "report_hash": sha256(evaluation_path.read_bytes()).hexdigest(),
                "fold_hash": "a" * 64,
                "feature_order_hash": _semantic_hash(feature_order),
                "normalizer_hash": _semantic_hash(normalizer, sort_keys=True),
                "snapshot_id": "snapshot-1", "dataset_hash": "dataset-1",
                "window_sessions": 20,
                "feature_contract_version": "fixture-v1",
                "status": "research_only", "deployment_ready": False,
            },
        },
    }
    registry_path = tmp_path / "roster.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return registry_path


def test_registry_loads_and_predicts_all_quantiles(tmp_path):
    registry = _write_fixture_roster(tmp_path)
    service = DeepLongTermInferenceService(tmp_path, registry_path=registry)
    readings = service.predict("excess_return_120d", [_example("600000")])

    assert len(readings) == 1
    assert set(("q10", "q50", "q90", "prediction_interval_width")) <= readings[0].keys()
    assert readings[0]["snapshot_hash"] == "hash-1"
    assert readings[0]["feature_contract_version"] == "fixture-v1"
    assert readings[0]["status"] == "research_only"
    assert readings[0]["deployment_ready"] is False


def test_aggregate_prediction_rejects_partial_four_task_bundle(tmp_path):
    registry = _write_fixture_roster(tmp_path)
    service = DeepLongTermInferenceService(tmp_path, registry_path=registry)
    with np.testing.assert_raises(DeepLongTermArtifactError):
        service.predict_all({"excess_return_120d": [_example("600000")]})


def test_predict_rejects_mixed_snapshots(tmp_path):
    registry = _write_fixture_roster(tmp_path)
    service = DeepLongTermInferenceService(tmp_path, registry_path=registry)
    with np.testing.assert_raises(DeepLongTermArtifactError):
        service.predict("excess_return_120d", [_example("600000"), _example("000001", snapshot="other")])


def test_predict_rejects_non_pit_or_unusable_sequence_input(tmp_path):
    registry = _write_fixture_roster(tmp_path)
    service = DeepLongTermInferenceService(tmp_path, registry_path=registry)

    future_cutoff = _example("600000")
    future_cutoff.feature_cutoff = "2026-08-15T07:00:00+00:00"
    with np.testing.assert_raises(DeepLongTermArtifactError):
        service.predict("excess_return_120d", [future_cutoff])

    wrong_order = _example("600000")
    wrong_order.feature_order = ["feature_b", "feature_a"]
    with np.testing.assert_raises(DeepLongTermArtifactError):
        service.predict("excess_return_120d", [wrong_order])

    no_features = _example("600000")
    no_features.missing_mask = np.ones((20, 2), dtype=bool)
    with np.testing.assert_raises(DeepLongTermArtifactError):
        service.predict("excess_return_120d", [no_features])


def test_runner_rejects_sidecar_normalizer_that_differs_from_checkpoint(tmp_path):
    registry = _write_fixture_roster(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    normalizer_path = tmp_path / "normalizer.json"
    normalizer = json.loads(normalizer_path.read_text(encoding="utf-8"))
    normalizer["feature_a"][0] = float(normalizer["feature_a"][0]) + 1.0
    normalizer_path.write_text(json.dumps(normalizer, sort_keys=True), encoding="utf-8")
    payload["models"]["excess_return_120d"]["normalizer_hash"] = _semantic_hash(normalizer, sort_keys=True)
    registry.write_text(json.dumps(payload), encoding="utf-8")
    service = DeepLongTermInferenceService(tmp_path, registry_path=registry)
    with np.testing.assert_raises(DeepLongTermArtifactError):
        service.predict("excess_return_120d", [_example("600000")])


def test_registry_contract_lists_four_long_term_tasks_in_project():
    from investment_research.service.deep_long_term import load_deep_long_term_registry

    project_root = Path(__file__).resolve().parents[1]
    try:
        specs = load_deep_long_term_registry(project_root=project_root)
    except DeepLongTermArtifactError as exc:
        if "missing" in str(exc):
            pytest.skip(f"downloaded research artifacts are not present: {exc}")
        raise
    assert set(specs) == set(LONG_TERM_TASKS)
    assert all(len(spec.fold_hash) == 64 for spec in specs.values())


def test_registry_summary_exposes_training_and_holdout_details_without_loading_models():
    project_root = Path(__file__).resolve().parents[1]
    summary = load_deep_long_term_registry_summary(project_root=project_root)
    if summary["status"] != "available":
        pytest.skip(f"downloaded evaluation artifacts are not present: {summary['blocking_reasons']}")
    assert len(summary["models"]) == 4
    assert {item["task"] for item in summary["models"]} == set(LONG_TERM_TASKS)
    assert all(item["training_symbol_count"] == 162 for item in summary["models"])
    assert all(item["training_date_count"] in {1260, 1500} for item in summary["models"])
    assert all(item["snapshot_hash"] for item in summary["models"])
    assert all("training_date_range" in item for item in summary["models"])
    assert all("evaluation_metric_status" in item for item in summary["models"])
    assert all(len(item["fold_hash"]) == 64 for item in summary["models"])
    assert all(item["capacity_status"] for item in summary["models"])
    assert all({"rank_ic", "risk_rank_ic"}.intersection(item["holdout_metrics"]) for item in summary["models"])
    assert summary["candidate_count"] >= 4
    assert {"deep_mlp", "itransformer"}.issubset(set(summary["candidate_architectures"]))
    assert any(item["is_primary"] for item in summary["candidate_models"])
    assert summary["artifact_registration_status"] == "registered_research_only"
    assert summary["artifact_registration_ref"]


def test_compact_evaluation_metrics_preserves_risk_contract_fields():
    from investment_research.service.deep_long_term import _compact_evaluation_metrics

    compact = _compact_evaluation_metrics({
        "risk_max_drawdown_after_cost": -0.25,
        "risk_turnover": 0.40,
        "risk_capacity_estimate": 123.0,
        "risk_regime_metrics": {"bull": {"rank_ic": 0.02}},
        "risk_data_completeness_rank_ic": {"coverage_at_least_98%": 0.03},
    })
    assert compact["risk_max_drawdown_after_cost"] == -0.25
    assert compact["risk_turnover"] == 0.40
    assert compact["risk_capacity_estimate"] == 123.0
    assert set(compact["risk_regime_metrics"]) == {"bull"}


def test_evaluation_metric_status_does_not_treat_null_or_empty_fields_as_recorded():
    from investment_research.service.deep_long_term import _evaluation_metric_status

    status = _evaluation_metric_status(
        "excess_return_120d",
        {"result": {"holdout_metrics": {
            "pinball_loss": 0.1,
            "p50_mae": 0.2,
            "interval_coverage": 0.8,
            "rank_ic": 0.03,
            "rank_icir": 0.4,
            "top_k_mean_excess_return_after_cost": 0.01,
            "top_bottom_spread_after_cost": 0.02,
            "max_drawdown_after_cost": -0.1,
            "turnover": None,
            "capacity_estimate": None,
            "year_rank_ic": {},
            "industry_rank_ic": {"banks": 0.02},
            "regime_metrics": {},
            "data_completeness_rank_ic": {"coverage_at_least_98%": 0.01},
        }}}
    )
    assert status["fields"]["turnover"]["status"] == "not_recorded"
    assert status["fields"]["capacity_estimate"]["status"] == "not_recorded"
    assert status["fields"]["year_rank_ic"]["status"] == "not_recorded"
    assert status["fields"]["industry_rank_ic"]["status"] == "recorded"


def test_artifact_registration_is_reference_only_and_records_missing_training_range_explicitly():
    project_root = Path(__file__).resolve().parents[1]
    try:
        manifest = build_deep_long_term_artifact_manifest(project_root=project_root)
    except DeepLongTermArtifactError as exc:
        pytest.skip(f"downloaded research artifacts are not present: {exc}")
    assert manifest["registration_status"] == "registered_research_only"
    assert manifest["reference_only"] is True
    assert manifest["production_copy_created"] is False
    assert set(manifest["tasks"]) == set(LONG_TERM_TASKS)
    for entry in manifest["models"]:
        assert entry["status"] == "research_only"
        assert entry["deployment_ready"] is False
        assert len(entry["model_sha256"]) == 64
        assert len(entry["evaluation_sha256"]) == 64
        assert entry["window_sessions"] == 20
        assert entry["training_date_range"]["status"] in {"recorded", "not_recorded"}


def _reading(task: str, symbol: str = "600000") -> dict:
    horizon = int(task.rsplit("_", 1)[-1][:-1])
    return {
        "task": task,
        "symbol": symbol,
        "horizon_days": horizon,
        "q10": -0.12,
        "q50": 0.03,
        "q90": 0.18,
        "prediction_interval_width": 0.30,
        "model": "deep_mlp",
        "model_version": f"{task}:deep_mlp:fixture",
        "data_as_of": "2026-08-14T07:00:00+00:00",
        "snapshot_id": "snapshot-1",
        "snapshot_hash": "hash-1",
        "dataset_hash": "dataset-1",
        "feature_contract_version": "fixture-v1",
        "label_version": "labels-v1",
        "artifact_hash": "a" * 64,
        "status": "research_only",
        "deployment_ready": False,
    }


def test_model_readings_are_grouped_and_written_atomically(tmp_path):
    readings = {task: [_reading(task)] for task in LONG_TERM_TASKS}
    target = write_long_term_model_readings(tmp_path, readings)

    assert target == tmp_path / "artifacts" / "long_term_model_readings" / "latest.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "long-term-model-readings-v1"
    assert payload["deployment_ready"] is False
    assert payload["symbol_count"] == 1
    assert payload["label_version"] == "labels-v1"
    assert set(payload["readings"][0]["tasks"]) == set(LONG_TERM_TASKS)


def test_model_readings_writer_rejects_partial_or_mixed_context(tmp_path):
    partial = {task: [_reading(task)] for task in LONG_TERM_TASKS[:-1]}
    with np.testing.assert_raises(DeepLongTermArtifactError):
        write_long_term_model_readings(tmp_path, partial)

    mixed = {task: [_reading(task)] for task in LONG_TERM_TASKS}
    mixed["excess_return_240d"][0]["snapshot_id"] = "snapshot-2"
    with np.testing.assert_raises(DeepLongTermArtifactError):
        write_long_term_model_readings(tmp_path, mixed)

    mixed = {task: [_reading(task)] for task in LONG_TERM_TASKS}
    mixed["excess_return_240d"][0]["label_version"] = "labels-v2"
    with np.testing.assert_raises(DeepLongTermArtifactError):
        write_long_term_model_readings(tmp_path, mixed)

    with np.testing.assert_raises(DeepLongTermArtifactError):
        write_long_term_model_readings(tmp_path, {task: [_reading(task)] for task in LONG_TERM_TASKS}, output_path=tmp_path / "active" / "latest.json")
