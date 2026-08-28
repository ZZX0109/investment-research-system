"""Round 33 — async intraday-spot capture worker (out-of-process).

Runs as a standalone process (``nohup ... &``) so a flaky/slow akshare call
never blocks the API.  Loops: every ``interval`` seconds (default 300 = 5m),
if inside a CN trading session, capture market+index spot with retries and
persist; off-hours the loop sleeps and retries the check.  Never exits on
fetch failure — logs and retries next tick.

Usage::

    NODE_ENV=development nohup python3 -m scripts.run_intraday_spot_worker \\
        --interval 300 > /tmp/intraday-spot-worker.log 2>&1 &
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from investment_research.integrations.xystock.quote_fetcher import is_cn_trading_session
from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.service.intraday_spot import capture_now
from investment_research.service.paper_game import PaperGameService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("intraday_spot_worker")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=300, help="seconds between ticks (default 300 = 5m)")
    parser.add_argument("--once", action="store_true", help="capture once and exit (for testing)")
    parser.add_argument("--force", action="store_true", help="capture even off-hours")
    args = parser.parse_args()

    uow = SQLiteUnitOfWork(get_default_database_path())
    log.info("intraday spot worker started: interval=%ds db=%s", args.interval, get_default_database_path())

    def tick() -> None:
        in_session = is_cn_trading_session()
        log.info("tick: trading_session=%s", in_session)
        if not in_session and not args.force:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            if now.weekday() < 5 and (now.hour, now.minute) >= (15, 5):
                try:
                    closes = PaperGameService(uow).capture_close_snapshots()
                    log.info("paper-game close snapshots: %s", closes)
                except Exception as exc:
                    log.exception("paper-game close snapshot failed (worker continues): %s", exc)
            log.info("off-hours — skipping capture")
            return
        try:
            summary = capture_now(uow)
            mk, ix = summary["market"], summary["index"]
            log.info(
                "capture: market=%s n=%d err=%s | index=%s n=%d err=%s",
                mk["status"], mk["n_persisted"], mk["error"],
                ix["status"], ix["n_persisted"], ix["error"],
            )
            game = PaperGameService(uow).run_automation()
            log.info("paper-game automation: %s", game)
        except Exception as exc:  # never crash the loop
            log.exception("capture_now raised (worker continues next tick): %s", exc)

    if args.once:
        tick()
        return 0

    while True:
        tick()
        log.info("sleeping %ds", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
