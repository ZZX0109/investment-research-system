from __future__ import annotations

from fastapi.testclient import TestClient


def test_document_analyze_endpoint_returns_uploaded_source_meta(client: TestClient, onboarded_user):
    resp = client.post(
        "/api/documents/NVDA/analyze",
        files={"file": ("nvda-report.csv", b"Revenue,Gross margin\n123,45%\n", "text/csv")},
        headers=onboarded_user,
    )

    assert resp.status_code == 200
    data = resp.json()
    analysis = data["documentAnalysis"]
    assert data["ok"] is True
    assert analysis["sourceType"] == "uploaded_report"
    assert analysis["sourceMeta"]["provider"] == "uploaded_report"
    assert analysis["sourceMeta"]["synthetic_ratio"] == 0.0
    assert any(item["metric_name"] == "Revenue" for item in analysis["metrics"])
