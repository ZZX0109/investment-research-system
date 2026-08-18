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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_research.service.scheduling import LocalResearchScheduler


def main() -> int:
    scheduler = LocalResearchScheduler()
    scheduler.start()
    if scheduler.scheduler is None:
        raise SystemExit("APScheduler is not installed; cannot start research worker")
    stopping = False

    def stop(*_args) -> None:
        nonlocal stopping
        stopping = True
        scheduler.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
