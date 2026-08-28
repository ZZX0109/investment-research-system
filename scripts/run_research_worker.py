#!/usr/bin/env python3
"""Run the research scheduler as a separate worker process.

The API does not own this process. Long-running collection, retraining and
audit subprocesses therefore cannot block API request handling or restart the
web server unexpectedly.
"""
from __future__ import annotations

import signal
import sys
import time
import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_research.service.scheduling import LocalResearchScheduler


def _write_heartbeat(path: Path, *, started_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "research-worker-heartbeat-v1",
        "pid": os.getpid(),
        "started_at": started_at.isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "role": "research_scheduler",
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--heartbeat", type=Path,
        default=ROOT / "artifacts/research_lifecycle/research-worker-heartbeat.json",
    )
    options = parser.parse_args()
    scheduler = LocalResearchScheduler()
    scheduler.start()
    if scheduler.scheduler is None:
        raise SystemExit("APScheduler is not installed; cannot start research worker")
    stopping = False
    started_at = datetime.now(timezone.utc)

    def stop(*_args) -> None:
        nonlocal stopping
        stopping = True
        scheduler.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        _write_heartbeat(options.heartbeat, started_at=started_at)
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
