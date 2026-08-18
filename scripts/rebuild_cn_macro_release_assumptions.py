#!/usr/bin/env python3
"""Rebuild the macro release-link layer from already downloaded NBS pages."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

from fetch_cn_macro_release_calendar_nbs import (  # noqa: E402
    OUTPUT,
    _build_macro_assumptions,
    _persist_assumptions,
    _write,
)


def main() -> int:
    calendar_path = OUTPUT / "nbs_release_calendar.json"
    records = json.loads(calendar_path.read_text(encoding="utf-8"))
    for record in records:
        planned = datetime.fromisoformat(str(record["planned_published_at"]).replace("Z", "+00:00"))
        if planned.hour >= 17:
            record["planned_published_at"] = (planned - timedelta(hours=8)).isoformat()
        if record.get("series") != "cpi_monthly":
            continue
        release = datetime.fromisoformat(str(record["planned_published_at"]).replace("Z", "+00:00")).date()
        previous = release.replace(day=1) - timedelta(days=1)
        record["data_period"] = f"{previous.year:04d}-{previous.month:02d}"
    _write(calendar_path, records)
    assumptions = _build_macro_assumptions(records)
    _persist_assumptions(assumptions)
    _write(OUTPUT / "macro_release_assumptions.json", assumptions)
    report_path = OUTPUT / "latest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["row_count"] = len(records)
    report["assumption_row_count"] = len(assumptions)
    report["assumption_coverage"] = {
        series: {
            "rows": sum(row.get("series") == series for row in assumptions),
            "planned_release_matched": sum(row.get("series") == series and bool(row.get("planned_published_at")) for row in assumptions),
            "coverage": (
                sum(row.get("series") == series and bool(row.get("planned_published_at")) for row in assumptions)
                / max(1, sum(row.get("series") == series for row in assumptions))
            ),
        }
        for series in sorted({row.get("series") for row in assumptions})
    }
    report["generated_at"] = datetime.now().astimezone().isoformat()
    _write(report_path, report)
    print(json.dumps({"status": report.get("status"), "assumption_row_count": len(assumptions), "assumption_coverage": report["assumption_coverage"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
