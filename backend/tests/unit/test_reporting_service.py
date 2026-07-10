from __future__ import annotations

from backend.reporting_service import attach_report_snapshot, report_snapshot_path


def test_report_snapshot_path_is_run_bound():
    assert report_snapshot_path("NVDA", "NVDA-balanced-run") == "/api/reports/NVDA.md?run_id=NVDA-balanced-run"


def test_attach_report_snapshot_stores_markdown_and_binds_paths():
    stored = {}
    payload = {
        "symbol": "UNIT",
        "run": {
            "runId": "UNIT-balanced-current",
            "reportVersion": "report-20260707090000",
            "summary": "fixed run summary",
        },
        "reportVersions": {
            "current": {},
            "delta": {"hasPrevious": True},
            "recentRuns": [
                {"runId": "UNIT-balanced-previous", "summary": "previous run"},
            ],
        },
    }

    def store_report_snapshot(run_id, symbol, preference, report_version, markdown):
        stored.update(
            {
                "run_id": run_id,
                "symbol": symbol,
                "preference": preference,
                "report_version": report_version,
                "markdown": markdown,
            }
        )

    result = attach_report_snapshot(
        payload=payload,
        preference="balanced",
        user_id=99,
        store_report_snapshot=store_report_snapshot,
        markdown_builder=lambda **kwargs: f"# {kwargs['symbol']} report\nRun ID: {payload['run']['runId']}",
    )

    assert stored == {
        "run_id": "UNIT-balanced-current",
        "symbol": "UNIT",
        "preference": "balanced",
        "report_version": "report-20260707090000",
        "markdown": "# UNIT report\nRun ID: UNIT-balanced-current",
    }
    assert result["run"]["reportPath"] == "/api/reports/UNIT.md?run_id=UNIT-balanced-current"
    assert result["reportVersions"]["current"]["runId"] == "UNIT-balanced-current"
    assert result["reportVersions"]["recentRuns"][0]["reportPath"] == "/api/reports/UNIT.md?run_id=UNIT-balanced-previous"
