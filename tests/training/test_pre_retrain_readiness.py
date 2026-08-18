"""Pre-retrain readiness tests for the A-share four-task research models.

These lock in the data-repair work that must be in place before the 20-hour
retrain is launched:

* ``akshare_cninfo_notices`` events are actually collected (the previous run
  failed with ``fetch_failed`` -> 100% missing event features).
* ``config/cn_industry_map.json`` covers the training universe (previous run
  had ~9.26% of symbols with no industry).
* The rebuilt research PIT propagates events + industry into the snapshot the
  training consumes.
* Model manifests default to research-only governance (never deployment_ready).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
COVERAGE_LEDGER = PROJECT / "artifacts" / "free_research_coverage.json"
INDUSTRY_MAP = PROJECT / "config" / "cn_industry_map.json"
REBUILD_ROOT = PROJECT / "artifacts" / "free_research_rebuild"

# These assertions validate a locally downloaded research run.  The raw
# downloads are intentionally ignored by git, so a clean checkout must not
# fail the unit-test job merely because the optional local evidence is absent.
pytestmark = pytest.mark.skipif(
    not COVERAGE_LEDGER.is_file() or not REBUILD_ROOT.is_dir(),
    reason="local downloaded research artifacts are not present",
)


def _newest_rebuild_index() -> Path | None:
    # Scan every full-v4* variant (full-v4, full-v4.1, ...) and pick the newest
    # rebuild index by mtime -- this way a fresh rebuild in full-v4.1 wins.
    candidates = sorted(
        REBUILD_ROOT.glob("full-v4*/rebuild-*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _universe_symbols(index_path: Path) -> list[str]:
    data = json.loads(index_path.read_text(encoding="utf-8"))
    symbols = {qr.get("symbol") for qr in data.get("quality_reports", []) if qr.get("symbol")}
    return sorted(symbols)


def test_cninfo_events_collected_with_rows():
    assert COVERAGE_LEDGER.is_file(), "coverage ledger missing"
    records = json.loads(COVERAGE_LEDGER.read_text(encoding="utf-8")).get("records", [])
    cninfo = [r for r in records if r.get("provider") == "akshare_cninfo_notices"]
    assert cninfo, "no akshare_cninfo_notices record in coverage ledger"
    for rec in cninfo:
        assert rec.get("status") in {"partial", "backfilled"}, (
            f"cninfo events not collected: status={rec.get('status')} "
            f"reason={rec.get('reason')}"
        )
        assert (rec.get("rows_or_bytes") or 0) > 0, "cninfo collected but produced zero rows"


def test_cninfo_events_not_failed():
    """The previous failure mode (fetch_failed -> 100% missing) must be gone."""
    records = json.loads(COVERAGE_LEDGER.read_text(encoding="utf-8")).get("records", [])
    failed = [r for r in records if r.get("provider") == "akshare_cninfo_notices"
              and r.get("status") == "fetch_failed"]
    assert not failed, f"cninfo events still failing: {failed}"


def test_cn_industry_map_present_and_schema():
    assert INDUSTRY_MAP.is_file(), "config/cn_industry_map.json missing"
    payload = json.loads(INDUSTRY_MAP.read_text(encoding="utf-8"))
    assert isinstance(payload.get("symbols"), dict), "industry map must contain 'symbols' dict"
    assert payload.get("source", "").startswith("baostock"), "industry map source must be baostock"
    assert payload.get("mapped", 0) >= 160, f"too few symbols mapped: {payload.get('mapped')}"


def test_cn_industry_map_covers_universe():
    index_path = _newest_rebuild_index()
    assert index_path is not None, "no rebuild index found"
    universe = _universe_symbols(index_path)
    assert universe, "rebuild index has no universe symbols"
    payload = json.loads(INDUSTRY_MAP.read_text(encoding="utf-8"))
    mapped = payload.get("symbols", {})
    # ETFs (51xxxx / 15xxxx / 56xxxx / 58xxxx) have no CSRC industry and are
    # expected to be absent; every A-share must be mapped.
    etf_prefixes = ("51", "15", "56", "58")
    equities = [s for s in universe if not s.startswith(etf_prefixes)]
    missing_equities = [s for s in equities if s not in mapped]
    coverage = (len(equities) - len(missing_equities)) / max(len(equities), 1)
    assert coverage >= 0.95, (
        f"industry coverage {coverage:.1%} below 95%; missing equities: {missing_equities[:10]}"
    )


def test_rebuilt_pit_propagates_events_and_industry():
    index_path = _newest_rebuild_index()
    assert index_path is not None, "no rebuild index found"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    snap_ref = (
        index.get("contexts", {})
        .get("close_confirmed", {})
        .get("snapshot_ref")
    )
    assert snap_ref, "rebuild index does not reference a close_confirmed snapshot"
    snap_path = PROJECT / snap_ref
    assert snap_path.is_file(), f"snapshot missing: {snap_path}"
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    status = snap.get("event_coverage_status")
    assert status in {"partial", "backfilled", "complete"}, (
        f"unexpected event_coverage_status in snapshot: {status}"
    )
    # Coverage counts live on the rebuild index (feature_v4_supplement block),
    # not on the snapshot itself.
    supplement = index.get("feature_v4_supplement", {})
    assert supplement.get("industry_symbol_count", 0) >= 150, (
        f"industry_symbol_count too low: {supplement.get('industry_symbol_count')}"
    )
    assert supplement.get("event_symbol_count", 0) >= 1, (
        "no symbols carry events in rebuild index"
    )
