from __future__ import annotations

from ml.data.splits import apply_embargo, temporal_split


def run() -> None:
    assert temporal_split("2022-06-01") == "train"
    assert temporal_split("2023-06-01") == "validation"
    assert temporal_split("2024-06-01") == "test"
    assert temporal_split("2026-06-01") == "shadow"
    embargo = apply_embargo(["2022-12-20", "2023-05-01"], embargo_days=30)
    assert embargo["2022-12-20"] == "embargo"
    assert "2023-05-01" not in embargo


if __name__ == "__main__":
    run()
    print("test_splits ok")

