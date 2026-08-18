from pathlib import Path

from investment_research.training.resource_guard import ResourceMonitor, probe_resources, recommended_threads


def test_recommended_threads_leaves_a_small_reserve(monkeypatch) -> None:
    monkeypatch.setattr("os.cpu_count", lambda: 20)
    assert recommended_threads() == 16


def test_resource_profile_is_serializable() -> None:
    profile = probe_resources()
    assert profile.cpu_count >= 1
    assert profile.thread_count >= 1
    assert isinstance(profile.gpu, list)


def test_monitor_writes_profile_and_sample(tmp_path: Path) -> None:
    monitor = ResourceMonitor(tmp_path / "monitor.jsonl", interval_seconds=1)
    monitor.start()
    monitor.sample()
    monitor.stop()
    assert (tmp_path / "resource-profile.json").is_file()
    assert (tmp_path / "monitor.jsonl").is_file()
