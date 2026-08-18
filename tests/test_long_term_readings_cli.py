import json
from pathlib import Path

import pytest

from scripts.run_long_term_model_readings import _guard_input_path, _load_examples
from investment_research.service.deep_long_term import DeepLongTermArtifactError, LONG_TERM_TASKS


def _row():
    return {
        "symbol": "600000",
        "market": "cn",
        "decision_context": "close_confirmed",
        "decision_time": "2026-08-14T07:00:00+00:00",
        "feature_cutoff": "2026-08-14T07:00:00+00:00",
        "window_sessions": 1,
        "feature_order": ["feature_a"],
        "values": [[1.0]],
        "data_quality_mask": [[1.0]],
        "event_missing_mask": [[0.0]],
        "provider_ids": [1],
        "revision_ids": [None],
        "source_delay_seconds": [0.0],
        "cache_states": ["fresh"],
        "missing_mask": [[False]],
        "target": 0.1,
        "market_snapshot_id": "snapshot-1",
        "market_snapshot_hash": "hash-1",
        "sequence_hash": "sequence-1",
    }


def test_input_loader_requires_explicit_four_task_json(tmp_path: Path):
    input_path = tmp_path / "artifacts" / "frozen.json"
    input_path.parent.mkdir()
    input_path.write_text(json.dumps({
        "schema_version": "long-term-sequence-input-v1",
        "examples_by_task": {task: [_row()] for task in LONG_TERM_TASKS},
    }), encoding="utf-8")
    groups = _load_examples(tmp_path, input_path)
    assert set(groups) == set(LONG_TERM_TASKS)
    assert groups[LONG_TERM_TASKS[0]][0].symbol == "600000"


@pytest.mark.parametrize("name", ["landing/run/input.json", "raw/input.json", "active/input.json"])
def test_input_loader_rejects_download_and_active_paths(tmp_path: Path, name: str):
    path = tmp_path / "artifacts" / name
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(DeepLongTermArtifactError):
        _guard_input_path(tmp_path, path)


def test_input_loader_rejects_pickle_or_non_artifact(tmp_path: Path):
    outside = tmp_path / "sequence.pkl"
    outside.write_bytes(b"not input")
    with pytest.raises(DeepLongTermArtifactError):
        _guard_input_path(tmp_path, outside)
