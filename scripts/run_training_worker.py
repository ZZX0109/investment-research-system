#!/usr/bin/env python3
"""Run the dedicated long-running research training worker."""

from __future__ import annotations

import argparse
import fcntl
from pathlib import Path
import signal
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_research.workers.training import ResearchTrainingWorker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--lock", type=Path, default=ROOT / "var" / "research-training-worker.lock")
    args = parser.parse_args()
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("another training worker already owns the lock")
        worker = ResearchTrainingWorker(ROOT)
        stopping = False

        def stop(*_args) -> None:
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        while not stopping:
            worker.tick(limit=1)
            if args.once:
                break
            time.sleep(max(1.0, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
