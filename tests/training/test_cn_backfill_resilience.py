from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import requests
import pytest


def _cninfo_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_cn_financial_disclosures_cninfo.py"
    spec = importlib.util.spec_from_file_location("cninfo_backfill_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ratios_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_cn_financial_ratios_akshare.py"
    spec = importlib.util.spec_from_file_location("financial_ratios_backfill_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _eastmoney_reports_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_cn_financial_reports_eastmoney.py"
    spec = importlib.util.spec_from_file_location("eastmoney_financial_reports_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _eastmoney_audit_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit_cn_financial_reports_eastmoney.py"
    spec = importlib.util.spec_from_file_location("eastmoney_financial_audit_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _eastmoney_import_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "import_cn_financial_eastmoney_landing.py"
    spec = importlib.util.spec_from_file_location("eastmoney_financial_import_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cninfo_backfill_checkpoints_each_symbol(tmp_path: Path) -> None:
    module = _cninfo_module()
    progress_path = tmp_path / "progress.json"
    progress = {"symbols": {}}

    class Service:
        def persist(self, **_kwargs):
            return SimpleNamespace(payload_hash="a" * 64, id="batch-1")

    module._persist_result(
        Service(),
        progress,
        progress_path,
        "000001",
        {"status": "complete", "rows": [{"published_at": "2026-08-21T00:00:00+00:00"}]},
        start_date="2010-01-01",
        end_date="2026-08-21",
    )

    persisted = json.loads(progress_path.read_text(encoding="utf-8"))
    assert persisted["symbols"]["000001"]["status"] == "complete"
    assert persisted["symbols"]["000001"]["published_at_count"] == 1
    assert persisted["symbols"]["000001"]["payload_hash"] == "a" * 64


@pytest.mark.parametrize("loader", [_cninfo_module, _ratios_module])
def test_checkpoint_write_is_valid_json_and_leaves_no_temporary_file(tmp_path: Path, loader) -> None:
    module = loader()
    path = tmp_path / "progress.json"

    module._write(path, {"symbols": {"000001": {"status": "complete"}}})

    assert json.loads(path.read_text(encoding="utf-8"))["symbols"]["000001"]["status"] == "complete"
    assert not list(tmp_path.glob(".progress.json.*.tmp"))


def test_cninfo_post_retries_rate_limit_with_exponential_backoff(monkeypatch) -> None:
    module = _cninfo_module()
    sleeps: list[float] = []
    module._configure_request_pacing(0)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.headers = {"Retry-After": "3"} if status_code == 429 else {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"{self.status_code}")

        def json(self):
            return {"announcements": []}

    class Session:
        def __init__(self) -> None:
            self.responses = [Response(429), Response(200)]

        def post(self, *_args, **_kwargs):
            return self.responses.pop(0)

    assert module._post(Session(), {"pageNum": "1"}) == {"announcements": []}
    assert sleeps == [3.0]


def test_financial_ratio_fetch_retries_and_keeps_a_checkpoint_safe_result(monkeypatch) -> None:
    module = _ratios_module()
    sleeps: list[float] = []
    module._configure_request_pacing(0)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    class Frame:
        empty = False
        columns: list[str] = []

        def iterrows(self):
            return iter(())

    calls = {"count": 0}

    def fetch(*, symbol: str):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary_provider_failure")
        return Frame()

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(stock_financial_abstract=fetch))
    result = module._fetch_symbol("000001")

    assert result == {"status": "complete", "rows": [], "metric_count": 0}
    assert sleeps == [1.0]


def test_financial_ratio_http_wrapper_applies_hard_timeout() -> None:
    module = _ratios_module()
    calls = []

    def original(*args, **kwargs):
        calls.append(kwargs)
        return "ok"

    module._configure_request_timeout(7.5)
    wrapped = module._get_with_timeout(original)
    assert wrapped("https://example.test") == "ok"
    assert calls == [{"timeout": 7.5}]


def test_financial_ratio_fetch_maps_core_and_extended_contract_fields(monkeypatch) -> None:
    module = _ratios_module()
    module._configure_request_pacing(0)

    class Frame:
        empty = False
        columns = ["选项", "指标", "20251231", "20241231"]

        def iterrows(self):
            return iter(enumerate([
                {"指标": "毛利率", "20251231": "30.0", "20241231": "28.0"},
                {"指标": "净资产收益率_平均", "20251231": "10.0", "20241231": "9.0"},
                {"指标": "基本每股收益", "20251231": "1.5", "20241231": "1.25"},
                {"指标": "净利润", "20251231": "4.0", "20241231": str(10 / 3)},
                {"指标": "总资产周转率", "20251231": "0.4", "20241231": "0.3"},
                {"指标": "资产负债率", "20251231": "50.0", "20241231": "52.0"},
                {"指标": "权益乘数", "20251231": "2.0", "20241231": "2.1"},
            ]))

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_financial_abstract=lambda *, symbol: Frame()),
    )
    result = module._fetch_symbol("000001")
    values = {
        (row["feature_family"], next(key for key in row if key in {
            "gpMargin", "roeAvg", "epsTTM", "YOYEPSBasic", "YOYNI",
            "AssetTurnRatio", "liabilityToAsset", "dupontROE",
            "dupontAssetTurn", "dupontAssetStoEquity",
        })): row
        for row in result["rows"]
    }

    assert result["status"] == "complete"
    assert values[("profit", "gpMargin")]["gpMargin"] == 0.3
    assert values[("profit", "roeAvg")]["roeAvg"] == 0.1
    assert values[("dupont", "dupontROE")]["dupontROE"] == 0.1
    assert values[("growth", "YOYEPSBasic")]["YOYEPSBasic"] == pytest.approx(0.2)
    assert values[("growth", "YOYNI")]["YOYNI"] == pytest.approx(0.2)
    assert values[("balance", "liabilityToAsset")]["liabilityToAsset"] == 0.5
    assert values[("dupont", "dupontAssetStoEquity")]["dupontAssetStoEquity"] == 2.0
    assert module._current_contract_complete({"status": "complete"}) is False
    assert module._current_contract_complete({
        "status": "complete", "metric_contract_version": module.METRIC_CONTRACT_VERSION,
    }) is True


def test_financial_ratio_throttle_uses_semantic_indicator_fallback(monkeypatch) -> None:
    module = _ratios_module()
    module._configure_request_pacing(0)

    class Frame:
        empty = False
        columns = ["日期", "销售净利率(%)", "流动比率", "资产负债率(%)", "股东权益比率(%)"]

        def to_dict(self, *, orient: str):
            assert orient == "records"
            return [{
                "日期": "2024-12-31",
                "销售净利率(%)": 12.0,
                "流动比率": 1.5,
                "资产负债率(%)": 40.0,
                "股东权益比率(%)": 60.0,
            }]

    def abstract(*, symbol: str):
        raise module._ProviderThrottled("http_status_456")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_financial_abstract=abstract,
            stock_financial_analysis_indicator=lambda **_kwargs: Frame(),
        ),
    )
    result = module._fetch_symbol("601228")
    by_field = {key: row for row in result["rows"] for key in row if key in {"npMargin", "currentRatio", "liabilityToAsset", "dupontAssetStoEquity"}}
    assert result["status"] == "complete"
    assert result["source_mode"] == "analysis_indicator_fallback"
    assert by_field["npMargin"]["npMargin"] == pytest.approx(0.12)
    assert by_field["currentRatio"]["currentRatio"] == pytest.approx(1.5)
    assert by_field["liabilityToAsset"]["liabilityToAsset"] == pytest.approx(0.4)
    assert by_field["dupontAssetStoEquity"]["dupontAssetStoEquity"] == pytest.approx(1 / 0.6)


def test_eastmoney_bulk_financial_reports_keep_period_and_publication_provenance() -> None:
    module = _eastmoney_reports_module()
    payload = {
        "result": {
            "pages": 1,
            "data": [{
                "SECURITY_CODE": "1", "REPORTDATE": "2024-12-31 00:00:00",
                "NOTICE_DATE": "2025-04-28 00:00:00", "UPDATE_DATE": "2025-04-28 00:00:00",
                "BASIC_EPS": 1.2, "TOTAL_OPERATE_INCOME": 100.0,
                "PARENT_NETPROFIT": 20.0, "WEIGHTAVG_ROE": 10.0, "XSMLL": 30.0,
            }],
        },
    }

    envelope = module._envelope("20241231", 1, payload)

    row = envelope["normalized_records"][0]
    assert row["symbol"] == "000001"
    assert row["report_period"] == "2024-12-31"
    assert row["published_at"] == "2025-04-28"
    assert row["metrics"]["BASIC_EPS"] == 1.2
    assert len(envelope["raw_payload_sha256"]) == 64
    assert module._report_periods(2024, "20240930") == ["20240331", "20240630", "20240930"]


def test_eastmoney_statement_family_uses_report_date_and_keeps_statement_fields() -> None:
    module = _eastmoney_reports_module()
    payload = {
        "result": {
            "pages": 1,
            "data": [{
                "SECURITY_CODE": "600519", "REPORT_DATE": "2024-12-31 00:00:00",
                "NOTICE_DATE": "2025-03-29 00:00:00", "TOTAL_ASSETS": 1_000.0,
                "TOTAL_LIABILITIES": 200.0, "CURRENT_RATIO": 2.0,
            }],
        },
    }

    envelope = module._envelope("20241231", 1, payload, "balance")
    row = envelope["normalized_records"][0]

    assert envelope["dataset"] == "quarterly_balance_reports"
    assert row["report_family"] == "balance"
    assert row["symbol"] == "600519"
    assert row["report_period"] == "2024-12-31"
    assert row["metrics"] == {
        "TOTAL_ASSETS": 1_000.0, "TOTAL_LIABILITIES": 200.0, "TOTAL_EQUITY": None,
        "MONETARYFUNDS": None, "ACCOUNTS_RECE": None, "INVENTORY": None,
        "ACCOUNTS_PAYABLE": None, "CURRENT_RATIO": 2.0, "DEBT_ASSET_RATIO": None,
        "SHORT_LOAN": None,
    }


def test_eastmoney_landing_audit_checks_hash_and_normalized_identity(tmp_path: Path) -> None:
    module = _eastmoney_audit_module()
    root = tmp_path / "financial"
    page = root / "landing" / "eastmoney-performance-20240331-20240331" / "20240331" / "page-0001.json"
    page.parent.mkdir(parents=True)
    payload = {"result": {"data": [{"SECURITY_CODE": "000001"}]}}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    page.write_text(json.dumps({
        "report_family": "performance", "report_period": "20240331", "payload": payload,
        "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "normalized_records": [{"symbol": "000001", "report_period": "2024-03-31", "published_at": "2024-04-30"}],
    }), encoding="utf-8")
    manifest = page.parents[1] / "manifest.json"
    manifest.write_text(json.dumps({
        "run_id": "eastmoney-performance-20240331-20240331", "status": "complete",
        "periods": {"20240331": {"status": "complete", "expected_pages": 1}},
    }), encoding="utf-8")

    report = module.audit(root, "performance")

    assert report["status"] == "complete"
    assert report["record_count"] == 1
    assert report["published_at_coverage"] == 1.0
    page_payload = json.loads(page.read_text(encoding="utf-8"))
    page_payload["raw_payload_sha256"] = "x" * 64
    page.write_text(json.dumps(page_payload), encoding="utf-8")
    assert module.audit(root, "performance")["invalid_page_count"] == 1


def test_eastmoney_import_uses_cninfo_time_and_does_not_substitute_fetch_time() -> None:
    module = _eastmoney_import_module()
    evidence = {"published_at": "2025-03-29T00:00:00+08:00", "announcement_id": "a1", "title": "2024 年年度报告"}
    record = {
        "symbol": "600519", "report_period": "2024-12-31", "source_uri": "https://example.test/source",
        "metrics": {"BASIC_EPS": 10.0, "WEIGHTAVG_ROE": 30.0, "XSMLL": 90.0, "SJLTZ": 20.0},
    }

    rows = module._canonical_rows(record, "performance", evidence, {"raw_payload_sha256": "a" * 64})

    values = {(row["feature_family"], next(key for key in row if key in {"epsTTM", "roeAvg", "dupontROE", "gpMargin", "YOYNI", "YOYPNI"})): row for row in rows}
    assert values[("profit", "epsTTM")]["epsTTM"] == 10.0
    assert values[("profit", "roeAvg")]["roeAvg"] == 0.3
    assert values[("profit", "gpMargin")]["gpMargin"] == 0.9
    assert values[("growth", "YOYNI")]["YOYNI"] == 0.2
    assert all(row["pubDate"] == evidence["published_at"] for row in rows)
    assert all(row["available_at"] is None for row in rows)


def test_eastmoney_import_landing_progress_is_family_specific(tmp_path: Path) -> None:
    module = _eastmoney_import_module()
    root = tmp_path / "financial"
    for family, statuses in {
        "performance": ["complete", "partial"],
        "income": ["complete", "complete"],
    }.items():
        manifest_dir = root / "landing" / f"eastmoney-{family}-20100331-20100630"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.json").write_text(json.dumps({
            "periods": {str(i): {"status": status} for i, status in enumerate(statuses)},
        }), encoding="utf-8")
    progress = module._landing_progress(root, ("performance", "income", "cashflow"))
    assert progress["performance"] == {"target_period_count": 2, "completed_period_count": 1}
    assert progress["income"] == {"target_period_count": 2, "completed_period_count": 2}
    assert progress["cashflow"] == {"target_period_count": 0, "completed_period_count": 0}
