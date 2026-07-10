from __future__ import annotations

from ml.data.feature_store import build_feature_metadata, validate_feature_metadata
from ml.features.market import FEATURE_NAMES


def run() -> None:
    dates = [f"2024-01-{day:02d}" for day in range(1, 6)]
    metadata = build_feature_metadata(
        as_of_date="2024-01-05",
        source="unit-test",
        dates=dates,
        sources=["unit-test" for _ in dates],
        tabular_field_count=len(FEATURE_NAMES),
        windows={"window60": 5},
    )
    audit = validate_feature_metadata(metadata)
    assert audit["ok"] is True
    broken = dict(metadata)
    broken["tabular.return_1d"] = {**broken["tabular.return_1d"], "availableAt": "2024-01-06"}
    failed = validate_feature_metadata(broken)
    assert failed["ok"] is False
    assert failed["futureLeakageCount"] == 1


if __name__ == "__main__":
    run()
    print("test_feature_store ok")
