#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

npm run build
python3 -m py_compile backend/app.py
python3 -c "import backend.app; print('database initialized')"
python3 -m compileall -q ml
python3 -m ml.tests.test_point_in_time
python3 -m ml.tests.test_feature_store
python3 -m ml.tests.test_splits
python3 -m ml.tests.test_labels
python3 -m ml.tests.test_real_only_filter
python3 -m ml.tests.test_deep_candidate_audit
python3 -m ml.tests.test_event_ingest_quality
python3 -m ml.tests.test_risk_distribution
python3 -m ml.tests.test_validation_metrics
python3 -m ml.tests.test_token_compression
python3 -m ml.tests.test_inference_contract
python3 -m ml.tests.test_pipelines

python3 - <<'PY'
from fastapi.testclient import TestClient
import json
import backend.app as app_module
from backend.app import STANDARD_TOOLS, app, health
import time

assert health()["ok"] is True
client = TestClient(app)

assert client.get("/api/portfolio").status_code == 401

weak = client.post("/api/auth/register", json={"email": "weak@example.com", "password": "research123"})
assert weak.status_code == 400

email = f"verify-{int(time.time() * 1000)}@investment-research.local"
registered = client.post("/api/auth/register", json={"email": email, "password": "Verify123!"})
assert registered.status_code == 200, registered.text
token = registered.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

assert client.get("/api/auth/me", headers=headers).json()["profile"]["onboardingCompleted"] is False

key_result = client.post("/api/api-keys", headers=headers, json={"provider": "openai", "apiKey": "sk-verify-123456"})
assert key_result.status_code == 200, key_result.text
assert key_result.json()["apiKeys"][0]["maskedKey"].startswith("sk-v")


def fake_market_snapshot(symbol: str, market: str):
    return {
        "ok": True,
        "marketValueHint": 205.0,
        "dayChange": 1.25,
        "sourceName": "verify market provider",
        "observedAt": app_module.iso(app_module.now_utc()),
    }


def fake_news_events(symbol: str, market: str):
    return {
        "ok": True,
        "sourceName": "verify news provider",
        "count": 1,
        "articles": [
            {
                "title": f"{symbol} verify news event",
                "url": "https://example.com/verify-news",
                "publisher": "Verify News",
                "publishedAt": app_module.iso(app_module.now_utc()),
            }
        ],
    }


def fake_disclosures(symbol: str, market: str):
    return {
        "ok": True,
        "sourceName": "SEC EDGAR submissions",
        "cik": "0001045810",
        "companyName": "NVIDIA CORP",
        "count": 1,
        "filings": [
            {
                "form": "10-Q",
                "filingDate": "2026-05-01",
                "reportDate": "2026-03-28",
                "accessionNumber": "0001045810-26-verify",
                "primaryDocument": "nvda-verify.htm",
                "url": "https://www.sec.gov/Archives/edgar/data/1045810/verify/nvda-verify.htm",
            }
        ],
    }


def make_minimal_text_pdf(lines: list[str]) -> bytes:
    content_lines = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if index:
            content_lines.append("T*")
        content_lines.append(f"({safe}) Tj")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode())
    return bytes(pdf)


app_module.try_fetch_market_snapshot = fake_market_snapshot
app_module.try_fetch_news_events = fake_news_events
app_module.try_fetch_disclosures = fake_disclosures

onboarding = client.post(
    "/api/onboarding",
    headers=headers,
    json={
        "preference": "growth",
        "riskAnswers": {"horizon": "3-12个月", "drawdownTolerance": "10%-20%", "reportFrequency": "weekly"},
        "holdings": [{"symbol": "NVDA", "name": "NVIDIA", "market": "us", "shares": 2, "costPrice": 120, "sector": "AI 算力"}],
    },
)
assert onboarding.status_code == 200, onboarding.text
assert onboarding.json()["profile"]["onboardingCompleted"] is True

portfolio = client.get("/api/portfolio?preference=growth", headers=headers)
assert portfolio.status_code == 200, portfolio.text
assert len(portfolio.json()["holdings"]) == 1

missing_symbol = client.get("/api/research/NOTREAL?preference=growth", headers=headers)
assert missing_symbol.status_code == 404, missing_symbol.text

dataset_response = client.post(
    "/api/ml/datasets/build",
    headers=headers,
    json={"symbols": ["NVDA"], "allowSynthetic": True, "smoke": True},
)
assert dataset_response.status_code == 200, dataset_response.text
dataset_payload = dataset_response.json()
assert dataset_payload["ok"] is True, dataset_payload
assert dataset_payload["sampleCount"] > 0, dataset_payload

train_response = client.post(
    "/api/ml/train",
    headers=headers,
    json={"modelType": "tabular_baseline", "datasetPath": dataset_payload["datasetPath"], "modelId": "verify_tabular_smoke"},
)
assert train_response.status_code == 200, train_response.text
train_payload = train_response.json()
assert train_payload["ok"] is True, train_payload
assert train_payload["modelId"] == "verify_tabular_smoke"

infer_response = client.post(
    "/api/ml/infer/NVDA",
    headers=headers,
    json={"allowSynthetic": True, "modelId": "verify_tabular_smoke"},
)
assert infer_response.status_code == 200, infer_response.text
infer_payload = infer_response.json()
assert infer_payload["prediction"]["modelId"] == "verify_tabular_smoke", infer_payload
assert infer_payload["mlRiskSummary"]["modelId"] == "verify_tabular_smoke", infer_payload

models_response = client.get("/api/ml/models", headers=headers)
assert models_response.status_code == 200, models_response.text
assert any(item["modelId"] == "verify_tabular_smoke" for item in models_response.json()["models"])

refresh = client.post("/api/refresh/daily", headers=headers)
assert refresh.status_code == 200, refresh.text
refresh_payload = refresh.json()
assert refresh_payload["ok"] is True, refresh_payload
assert refresh_payload["count"] == 1, refresh_payload
refresh_item = refresh_payload["items"][0]
assert refresh_item["disclosure"]["ok"] is True, refresh_item
assert len(refresh_item["evidenceChanges"]["newEvidenceIds"]) == 5, refresh_item["evidenceChanges"]
assert refresh_item["evidenceChanges"]["supersededFinancialEvidence"], refresh_item["evidenceChanges"]

csv_bytes = b"period,revenue,gross_margin,free_cash_flow\n2026Q1,26440,77.0,14900\n2026Q2,30040,76.5,16020\n"
upload = client.post(
    "/api/documents/NVDA/analyze",
    headers=headers,
    files={"file": ("nvda_metrics.csv", csv_bytes, "text/csv")},
)
assert upload.status_code == 200, upload.text
assert upload.json()["documentAnalysis"]["sourceType"] == "uploaded_report"

txt_result = app_module.analyze_document_content(
    "VERIFYTXT",
    "verify_report.txt",
    (
        "This long management discussion paragraph describes the operating context and reporting assumptions for verification.\n"
        "revenue, gross margin, free cash flow, 26440, 77.0, 14900\n"
        "Figure 1 growth trend chart shows revenue growth over time.\n"
        "footnote: revenue recognition depends on shipment timing and customer acceptance.\n"
    ).encode("utf-8"),
)
txt_block_types = {item["block_type"] for item in txt_result["blockPreviews"]}
assert {"text", "table", "chart", "footnote"}.issubset(txt_block_types), txt_result["blockPreviews"]

pdf_result = app_module.analyze_document_content(
    "VERIFYPDF",
    "verify_report.pdf",
    make_minimal_text_pdf(
        [
            "This long management discussion paragraph describes operating context and reporting assumptions for verification.",
            "revenue, gross margin, free cash flow, 26440, 77.0, 14900",
            "Figure 1 growth trend chart shows revenue growth over time.",
            "footnote: revenue recognition depends on shipment timing and customer acceptance.",
        ]
    ),
)
pdf_block_types = {item["block_type"] for item in pdf_result["blockPreviews"]}
assert {"text", "table", "chart", "footnote"}.issubset(pdf_block_types), pdf_result["blockPreviews"]

research = client.get("/api/research/NVDA?preference=growth", headers=headers)
assert research.status_code == 200, research.text
payload = research.json()
assert payload["documentAnalysis"]
assert payload["documentAnalysis"]["sourceType"] == "uploaded_report"
assert any(block["block_type"] == "table" for block in payload["documentAnalysis"]["blockPreviews"])
assert payload["evidenceAudit"]["score"] >= 0
assert payload["evidenceAudit"]["judgeVersion"] == "v2"
assert payload["evidenceAudit"]["scope"].startswith("Research Quality Judge")
dimension_labels = {item["label"] for item in payload["evidenceAudit"]["dimensions"]}
assert {
    "证据是否充分",
    "信息是否过期",
    "财务指标是否有来源",
    "是否核验权威公告/披露",
    "策略回测是否有样本外风险提示",
    "结论是否混淆事实和推断",
    "是否缺少反方观点",
    "是否出现个性化荐股越界",
    "结论是否有 claim 级证据图谱",
    "时序模型是否样本外验证与校准",
    "是否通过 Point-in-Time Feature Store 检查",
    "是否输出风险分布而非涨跌预测",
    "是否完成校准与回测验证",
    "是否量化 Agent token 压缩",
    "Judge v2 是否检查引用来源",
    "Judge v2 是否禁止确定性预测表达",
}.issubset(dimension_labels)
dimensions = {item["key"]: item for item in payload["evidenceAudit"]["dimensions"]}
assert dimensions["financial_metric_sources"]["passed"] is True, dimensions["financial_metric_sources"]
assert dimensions["authority_disclosure"]["passed"] is True, dimensions["authority_disclosure"]
assert dimensions["personalized_advice_boundary"]["passed"] is True, dimensions["personalized_advice_boundary"]
assert dimensions["pit_feature_store"]["passed"] is True, dimensions["pit_feature_store"]
assert dimensions["risk_distribution_engine"]["passed"] is True, dimensions["risk_distribution_engine"]
assert dimensions["calibration_backtest_validator"]["passed"] is True, dimensions["calibration_backtest_validator"]
assert dimensions["token_compression_report"]["passed"] is True, dimensions["token_compression_report"]
assert payload["evidenceAudit"]["v2Checks"]["noFutureData"] is True
assert payload["evidenceAudit"]["v2Checks"]["outOfSampleValidation"] is True
workflow_roles = {item["role"] for item in payload["agentWorkflow"]}
expected_workflow_roles = {
    "行情与资讯收集 Agent",
    "财务数据分析 Skill",
    "策略回测 Skill",
    "Time-Series Feature Builder Skill",
    "CNN Local Signal Skill",
    "Transformer Scenario Encoder Skill",
    "Calibration Validator Skill",
    "观察池管理 Agent",
    "信号提醒 Agent",
    "研究报告生成 Agent",
    "LLM Judge 审稿 Agent",
}
assert expected_workflow_roles.issubset(workflow_roles), sorted(expected_workflow_roles - workflow_roles)
assert payload["mlRiskSummary"]["modelId"] == "verify_tabular_smoke", payload["mlRiskSummary"]
assert payload["mlRiskSummary"]["calibrationStatus"] in {"valid", "stale", "failed"}, payload["mlRiskSummary"]
assert payload["mlRiskSummary"]["similarScenarios"], payload["mlRiskSummary"]
assert payload["mlRiskSummary"]["featureStoreAudit"]["ok"] is True, payload["mlRiskSummary"]["featureStoreAudit"]
assert payload["mlRiskSummary"]["featureStoreAudit"]["futureLeakageCount"] == 0, payload["mlRiskSummary"]["featureStoreAudit"]
assert "drawdownQuantiles1w" in payload["mlRiskSummary"]["riskDistribution"], payload["mlRiskSummary"]["riskDistribution"]
assert "drawdownQuantiles1m" in payload["mlRiskSummary"]["riskDistribution"], payload["mlRiskSummary"]["riskDistribution"]
assert payload["mlRiskSummary"]["riskDistribution"]["varBreach"]["threshold"] < 0, payload["mlRiskSummary"]["riskDistribution"]
assert "pinball_loss" in payload["mlRiskSummary"]["validationMetrics"], payload["mlRiskSummary"]["validationMetrics"]
assert "crps" in payload["mlRiskSummary"]["validationMetrics"], payload["mlRiskSummary"]["validationMetrics"]
assert "var_breach_rate" in payload["mlRiskSummary"]["validationMetrics"], payload["mlRiskSummary"]["validationMetrics"]
assert payload["mlRiskSummary"]["validationMetrics"]["walk_forward"]["windowCount"] >= 1, payload["mlRiskSummary"]["validationMetrics"]
assert payload["mlRiskSummary"]["validationMetrics"]["purged_cv"]["foldCount"] >= 1, payload["mlRiskSummary"]["validationMetrics"]
assert payload["tokenCompressionReport"]["rawTokenEstimate"] > payload["tokenCompressionReport"]["structuredTokenEstimate"], payload["tokenCompressionReport"]
assert payload["tokenCompressionReport"]["tokenReductionPercent"] > 0, payload["tokenCompressionReport"]
compression_response = client.get("/api/ml/token-compression/NVDA", headers=headers)
assert compression_response.status_code == 200, compression_response.text
assert compression_response.json()["report"]["conclusionConsistency"] >= 0.66, compression_response.json()
assert payload["conditionAlignment"]["factors"]
assert payload["debate"]["bull"]
assert payload["observationChecklist"]
claim_by_id = {item["id"]: item for item in payload["evidenceGraph"]["claims"]}
assert claim_by_id["financial_quality"]["status"] == "supported", claim_by_id["financial_quality"]
assert claim_by_id["authority_disclosure_check"]["status"] == "supported", claim_by_id["authority_disclosure_check"]
assert payload["evidenceGraph"]["edges"], payload["evidenceGraph"]
assert payload["reportRevisionLoop"]["finalStatus"] in {"approved_research_note", "data_insufficient"}
expired_evidence = [dict(item) for item in payload["evidence"]]
expired_evidence[0]["isExpired"] = True
expired_graph = app_module.build_evidence_graph(
    expired_evidence,
    portfolio.json()["holdings"][0],
    payload["documentAnalysis"],
    payload["historicalAnalogies"],
    {"score": 92, "verdict": "verify high score"},
)
expired_report_claim = {item["id"]: item for item in expired_graph["claims"]}["report_conclusion_boundary"]
assert expired_report_claim["status"] == "contested", expired_report_claim
assert expired_evidence[0]["id"] in expired_report_claim["dependsOnExpiredEvidenceIds"], expired_report_claim

tool_ids = {call["toolId"] for call in payload["toolCalls"]}
standard_tool_ids = {tool["toolId"] for tool in STANDARD_TOOLS}
assert standard_tool_ids <= tool_ids, sorted(standard_tool_ids - tool_ids)
for call in payload["toolCalls"]:
    assert call["input"] is not None
    assert call["outputSummary"]
    assert call["sourceName"]
    assert call["observedAt"]
    assert call["status"] in {"success", "degraded", "failed"}
    assert call["evidenceId"] is not None, call
assert any(call["toolId"] == "announcement_search" and call["status"] == "success" and call["evidenceId"] for call in payload["toolCalls"])
assert any(call["toolId"] == "financial_report_parser" and call["status"] == "success" and call["evidenceId"] for call in payload["toolCalls"])
assert any(call["toolId"] == "metric_calculator" and call["status"] == "success" and call["evidenceId"] for call in payload["toolCalls"])

report_response = client.get("/api/reports/NVDA.md?preference=growth", headers=headers)
assert report_response.status_code == 200, report_response.text
report = report_response.text
assert "Research Quality Judge" in report
assert "Agent / Skill 工作流" in report
assert "证据是否充分" in report
assert "是否核验权威公告/披露" in report
assert "是否出现个性化荐股越界" in report
assert "策略回测是否有样本外风险提示" in report
assert "时序模型风险分布" in report
assert "Agent Token Compression Report" in report
assert "Point-in-Time Feature Store" in report
assert "VaR breach probability" in report
assert "verify_tabular_smoke" in report
assert "Bull / Bear" in report
assert "观察清单" in report

from ml.common import connect
from ml.training.registry import approval_status

with connect() as conn:
    conn.execute("update model_registry set status = 'candidate' where model_id like 'verify_%' or model_id like 'test_%'")
    conn.execute("update model_registry set status = 'candidate' where model_type != 'tabular_baseline'")
    for row in conn.execute("select model_id, model_type, metrics_json from model_registry where model_id in ('risk_tabular_scale_v1', 'risk_tabular_real_v1')").fetchall():
        status = approval_status(json.loads(row["metrics_json"]), row["model_type"])
        conn.execute("update model_registry set status = ? where model_id = ?", (status, row["model_id"]))
    conn.commit()

print("verify ok")
PY
