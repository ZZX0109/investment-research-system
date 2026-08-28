#!/usr/bin/env python3
"""Rebuild financial coverage and project completion after the fai fetch.
Run this after fetch_financial_analysis_indicator.py completes.
"""
import subprocess, sys, json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

def main() -> int:
    # 1. Check fai record count
    import sqlite3
    c = sqlite3.connect(PROJECT / "var/cn-research/catalog.db")
    r = c.execute(
        "SELECT COUNT(*) FROM raw_data_batches WHERE dataset='cn_financial_analysis_indicator_research'"
    ).fetchone()
    print(f"[rebuild] fai records: {r[0]}")

    # Count by family
    from collections import Counter
    fams = Counter()
    for (pj,) in c.execute(
        "SELECT payload_json FROM raw_data_batches WHERE dataset='cn_financial_analysis_indicator_research'"
    ).fetchall():
        p = json.loads(pj)
        ref = p.get("payload_ref", "").replace("file-object://", "")
        fpath = PROJECT / "var/cn-research/raw" / ref
        if fpath.is_file():
            d = json.loads(fpath.read_text())
            fams[d.get("feature_family", "?")] += 1
    c.close()
    print(f"[rebuild] families: {dict(fams)}")

    # 2. Rebuild financial coverage
    print("[rebuild] running audit_cn_financial_coverage.py...")
    r = subprocess.run(
        [sys.executable, str(PROJECT / "scripts/audit_cn_financial_coverage.py")],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        print(f"[rebuild] financial coverage FAILED: {r.stderr[:200]}")
    else:
        # Check new coverage
        fc = json.loads((PROJECT / "artifacts/cn_financial_coverage/latest.json").read_text())
        fields = fc.get("fields", {})
        for k in ["balance.quickRatio", "balance.cashRatio", "growth.YOYAsset"]:
            f = fields.get(k, {})
            print(f"  {k}: coverage={f.get('coverage', 0):.4f}")
        print(f"  overall: {fc.get('coverage')}")

    # 3. Rebuild project completion
    print("[rebuild] running audit_project_completion.py...")
    r = subprocess.run(
        [sys.executable, str(PROJECT / "scripts/audit_project_completion.py")],
        capture_output=True, text=True, timeout=120,
    )
    d = json.loads((PROJECT / "artifacts/project_completion/latest.json").read_text())
    p = sum(1 for r in d.get("requirements", []) if r.get("status") == "passed")
    print(f"[rebuild] audit: {p}/17 passed")
    for r in d.get("requirements", []):
        if r.get("status") != "passed":
    print(f"  {r.get('id')}: {r.get('observed')}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
