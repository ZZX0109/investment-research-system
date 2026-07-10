from __future__ import annotations

from ml.data.point_in_time import assert_point_in_time


def run() -> None:
    assert_point_in_time("2025-01-10", ["2025-01-01", "2025-01-10"])
    try:
        assert_point_in_time("2025-01-10", ["2025-01-11"])
    except AssertionError:
        return
    raise AssertionError("future leakage was not detected")


if __name__ == "__main__":
    run()
    print("test_point_in_time ok")

