"""Small, dependency-light resource guard for long-running training jobs.

The guard does not promise a constant utilisation percentage.  It makes the
resource policy explicit, records what the process actually used, and keeps a
run diagnosable when a backend falls back from GPU to CPU or the host becomes
memory constrained.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any


@dataclass(frozen=True)
class ResourceProfile:
    cpu_count: int
    thread_count: int
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    gpu: list[dict[str, Any]]
    policy: dict[str, str]


def recommended_threads(*, reserve_cores: int = 2, maximum: int = 16) -> int:
    """Return a conservative all-core setting while leaving the OS responsive."""
    count = os.cpu_count() or 1
    return max(1, min(maximum, count - max(0, reserve_cores)))


def probe_resources() -> ResourceProfile:
    memory_total = None
    memory_available = None
    try:
        import psutil

        virtual = psutil.virtual_memory()
        memory_total = int(virtual.total)
        memory_available = int(virtual.available)
    except ImportError:
        pass
    return ResourceProfile(
        cpu_count=os.cpu_count() or 1,
        thread_count=recommended_threads(),
        memory_total_bytes=memory_total,
        memory_available_bytes=memory_available,
        gpu=_query_gpus(),
        policy={
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
            "INVESTMENT_RESEARCH_USE_GPU": os.environ.get("INVESTMENT_RESEARCH_USE_GPU", "0"),
            "INVESTMENT_RESEARCH_TORCH_DEVICE": os.environ.get("INVESTMENT_RESEARCH_TORCH_DEVICE", "cpu"),
        },
    )


class ResourceMonitor:
    """Write periodic host/process/GPU samples to JSONL while a task runs."""

    def __init__(self, output: Path, *, interval_seconds: float = 5.0, pid: int | None = None):
        self.output = output
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.pid = pid or os.getpid()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_proc_cpu_ticks: int | None = None
        self._last_proc_wall: float | None = None

    def start(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        profile_path = self.output.with_name("resource-profile.json")
        _atomic_json(profile_path, asdict(probe_resources()))
        self._thread = threading.Thread(target=self._run, name="resource-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds + 1.0))

    def _run(self) -> None:
        with self.output.open("a", encoding="utf-8") as handle:
            while not self._stop.is_set():
                handle.write(json.dumps(self.sample(), ensure_ascii=False) + "\n")
                handle.flush()
                self._stop.wait(self.interval_seconds)

    def sample(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pid": self.pid,
            "disk_free_bytes": _disk_free(self.output.parent),
            "gpu": _query_gpus(),
        }
        try:
            import psutil

            process = psutil.Process(self.pid)
            row["process"] = {
                "cpu_percent": process.cpu_percent(interval=None),
                "rss_bytes": int(process.memory_info().rss),
                "memory_percent": process.memory_percent(),
                "threads": process.num_threads(),
            }
            virtual = psutil.virtual_memory()
            row["host_memory"] = {
                "available_bytes": int(virtual.available),
                "used_percent": float(virtual.percent),
            }
        except ImportError:
            row["process"] = _proc_metrics(self)
            row["host_memory"] = _proc_memory()
        except Exception:
            row["process"] = {"unavailable": True}
        return row


def _query_gpus() -> list[dict[str, Any]]:
    if shutil.which("nvidia-smi") is None:
        return []
    command = [
        "nvidia-smi",
        "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 5:
            continue
        try:
            rows.append({
                "index": int(values[0]),
                "utilization_percent": float(values[1]),
                "memory_used_mib": float(values[2]),
                "memory_total_mib": float(values[3]),
                "temperature_c": float(values[4]),
            })
        except ValueError:
            continue
    return rows


def _disk_free(path: Path) -> int | None:
    try:
        return int(shutil.disk_usage(path).free)
    except OSError:
        return None


def _proc_metrics(monitor: ResourceMonitor) -> dict[str, Any]:
    """Linux fallback used on minimal training images without psutil."""
    try:
        stat = Path(f"/proc/{monitor.pid}/stat").read_text(encoding="utf-8")
        after_comm = stat.rsplit(")", 1)[1].split()
        cpu_ticks = int(after_comm[11]) + int(after_comm[12])
        now = time.monotonic()
        cpu_percent = None
        if monitor._last_proc_cpu_ticks is not None and monitor._last_proc_wall is not None:
            elapsed = max(1e-6, now - monitor._last_proc_wall)
            tick_rate = float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
            cpu_percent = ((cpu_ticks - monitor._last_proc_cpu_ticks) / tick_rate) / elapsed * 100.0 / max(1, os.cpu_count() or 1)
        monitor._last_proc_cpu_ticks = cpu_ticks
        monitor._last_proc_wall = now
        rss_bytes = 0
        threads = None
        for line in Path(f"/proc/{monitor.pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss_bytes = int(line.split()[1]) * 1024
            elif line.startswith("Threads:"):
                threads = int(line.split()[1])
        return {"cpu_percent": cpu_percent, "rss_bytes": rss_bytes, "threads": threads, "source": "procfs"}
    except (OSError, IndexError, ValueError, KeyError):
        return {"unavailable": True}


def _proc_memory() -> dict[str, Any]:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.split()[0]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable")
        used_percent = ((total - available) / total * 100.0) if total and available is not None else None
        return {"available_bytes": available, "used_percent": used_percent, "source": "procfs"}
    except (OSError, IndexError, ValueError):
        return {"unavailable": True}


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
