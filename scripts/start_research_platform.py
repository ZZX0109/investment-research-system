#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the A-share research API, scheduler, and Vite workbench."
    )
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=5173)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "development")
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["WORKBENCH_API_ORIGIN"] = f"http://127.0.0.1:{args.api_port}"
    required = [
        ROOT / "output" / "models" / "model_manifest.json",
        *[
            ROOT / "output" / f"bundle_{market}.pkl"
            for market in ("us", "cn", "hk", "jp")
        ],
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        print("Preflight warning: missing " + ", ".join(missing), flush=True)

    subprocess.run(
        [
            sys.executable,
            "-c",
            "from investment_research.repository.sqlite import create_unit_of_work; create_unit_of_work().close()",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "investment_research.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.api_port),
            ],
            cwd=ROOT,
            env=env,
        ),
        subprocess.Popen(
            [
                "npm",
                "run",
                "dev:workbench",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.web_port),
            ],
            cwd=ROOT,
            env=env,
        ),
    ]
    print(f"Research API: http://127.0.0.1:{args.api_port}", flush=True)
    print(f"Research web: http://127.0.0.1:{args.web_port}", flush=True)

    def stop(*_args) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
    finally:
        stop()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    return next(
        (process.returncode or 1 for process in processes if process.returncode), 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
