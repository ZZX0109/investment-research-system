from __future__ import annotations

import importlib.util
import json
import pickle
import sys
from datetime import date, timedelta
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from investment_research.training.models import (
    CanonicalPriceBar,
    EventType,
    InstrumentType,
    LabelSet,
    Market,
    PointInTimeEvent,
    PreparedPriceBar,
    TrainingSample,
)
from investment_research.training.sources import build_instrument_from_symbol


PROJECT = Path(__file__).resolve().parents[2]


def _load_script(module_name: str, relative_path: str):
    script_path = PROJECT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authoritative_run_requires_real_full() -> None:
    module = _load_script("run_retraining_test", "scripts/run_retraining.py")

    assert module._authoritative_run(data_source="real", profile="full") is True
    assert module._authoritative_run(data_source="real", profile="quick") is False
    assert module._authoritative_run(data_source="synthetic", profile="full") is False


def test_retraining_results_include_reproducible_framework_identity() -> None:
    module = _load_script("run_retraining_framework_test", "scripts/run_retraining.py")
    assert module.TRUST_FRAMEWORK_VERSION == "trusted-risk-gate-v1"


def test_market_eligibility_excludes_zero_event_market(tmp_path, monkeypatch) -> None:
    module = _load_script("run_retraining_test_eligibility", "scripts/run_retraining.py")
    monkeypatch.setattr(module, "TEMP", tmp_path)
    monkeypatch.setattr(module, "MARKET_SYMBOLS", {"us": [f"S{i}" for i in range(32)]})
    (tmp_path / "fetch_validation.json").write_text(
        json.dumps({"us": {"fetched_symbols": 32, "missing_symbols": []}}),
        encoding="utf-8",
    )
    (tmp_path / "fetch_events_validation.json").write_text(
        json.dumps({"us": {"event_type_counts": {"news": 0, "filing": 0, "announcement": 0, "earnings": 0}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "load_pickle", lambda path: {"events": []})

    report = module.assess_market_eligibility(bundles={"us": Path("bundle_us.pkl")}, data_source="real")

    assert report["us"]["included"] is False
    assert "event coverage is zero" in report["us"]["reason"]


def test_load_real_bundles_allows_partial_market_coverage(tmp_path, monkeypatch) -> None:
    module = _load_script("run_retraining_test_partial", "scripts/run_retraining.py")
    monkeypatch.setattr(module, "OUTPUT", tmp_path)
    monkeypatch.setattr(module, "MARKET_SYMBOLS", {"us": ["AAPL", "MSFT"]})

    bar = CanonicalPriceBar(
        symbol="AAPL",
        trade_date=date(2026, 1, 30),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        adjusted_close=10.5,
        volume=1000.0,
        currency="USD",
        published_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
    )
    with open(tmp_path / "bundle_us.pkl", "wb") as f:
        pickle.dump(
            {
                "source": "real:yfinance",
                "instruments": [build_instrument_from_symbol("AAPL")],
                "price_bars": [bar],
                "events": [],
            },
            f,
        )

    bundles = module._load_real_bundles(strict=True)

    assert bundles["us"] == tmp_path / "bundle_us.pkl"


def test_fetch_real_data_checkpoint_ignores_stale_symbols(tmp_path, monkeypatch) -> None:
    module = _load_script("fetch_real_data_test_checkpoint", "scripts/fetch_real_data.py")
    monkeypatch.setattr(module, "INTERMEDIATE", tmp_path)
    (tmp_path / "market_cn.csv").write_text(
        "symbol,trade_date,open,high,low,close,adj_close,volume\n"
        "000858.SZ,2026-01-01,1,2,0.5,1.5,1.5,100\n"
        "600519.SH,2026-01-01,10,11,9,10.5,10.5,200\n",
        encoding="utf-8",
    )

    data, completed = module.load_checkpoint("cn", ["600519.SH"])

    assert list(data) == ["600519.SH"]
    assert completed == {"600519.SH"}


def test_invest_config_keeps_champion_and_marks_zero_approved_challengers(tmp_path) -> None:
    module = _load_script("run_retraining_test_config", "scripts/run_retraining.py")
    results_data = {
        "target_name": "future_max_drawdown_20d",
        "models": [
            {
                "model_id": "baseline-1",
                "trainer_name": "linear-baseline",
                "algorithm_family": "linear_baseline",
                "folds": [{}],
                "eligible_for_approval": True,
            },
            {
                "model_id": "lgbm-1",
                "trainer_name": "lightgbm",
                "algorithm_family": "lightgbm",
                "folds": [{}],
                "eligible_for_approval": False,
            },
        ],
    }

    module._write_invest_config(results_data, artifact_root=tmp_path)
    config = json.loads((tmp_path / "invest_agent_models.json").read_text(encoding="utf-8"))

    assert config["champion_model"]["trainer_name"] == "linear-baseline"
    assert config["primary_model"]["trainer_name"] == "linear-baseline"
    assert config["champion_fallback"]["trainer_name"] == "linear-baseline"
    assert config["approval_summary"]["approved_challenger_count"] == 0
    assert config["approval_summary"]["message"] == "0 approved challengers"


def test_invest_config_uses_random_forest_as_primary_when_guardrails_clear(tmp_path) -> None:
    module = _load_script("run_retraining_test_primary_rf", "scripts/run_retraining.py")
    results_data = {
        "target_name": "future_max_drawdown_20d",
        "reference_risk_flag": False,
        "regime_breakdown": {"bull": {}, "bear": {}, "range": {}, "high_vol": {}},
        "models": [
            {
                "model_id": "baseline-1",
                "trainer_name": "linear-baseline",
                "algorithm_family": "linear_baseline",
                "folds": [{}],
                "eligible_for_approval": True,
            },
            {
                "model_id": "rf-1",
                "trainer_name": "random-forest",
                "algorithm_family": "random_forest",
                "folds": [{}],
                "eligible_for_approval": True,
            },
        ],
    }

    module._write_invest_config(results_data, artifact_root=tmp_path)
    config = json.loads((tmp_path / "invest_agent_models.json").read_text(encoding="utf-8"))

    assert config["primary_model"]["trainer_name"] == "random-forest"
    assert config["champion_fallback"]["trainer_name"] == "linear-baseline"
    assert config["approval_summary"]["primary_challenger_allowed"] is True
    assert [model["trainer_name"] for model in config["approved_challengers"]] == ["random-forest"]
    assert [model["trainer_name"] for model in config["approved_models"]] == ["linear-baseline", "random-forest"]
    assert config["conditional_models"] == []


def test_training_summary_exposes_feature_contract_and_deployment_roles() -> None:
    module = _load_script("run_retraining_test_summary_contract", "scripts/run_retraining.py")
    results_data = {
        "target_name": "future_max_drawdown_20d",
        "data_source": "real",
        "training_profile": "full",
        "feature_contract_version": module.FEATURE_CONTRACT_VERSION,
        "label_set_version": "multitask-v2",
        "reference_risk_flag": False,
        "regime_breakdown": {"bull": {}, "bear": {}, "range": {}, "high_vol": {}},
        "models": [
            {
                "model_id": "baseline-1",
                "trainer_name": "linear-baseline",
                "algorithm_family": "linear_baseline",
                "folds": [],
                "eligible_for_approval": True,
            },
            {
                "model_id": "rf-1",
                "trainer_name": "random-forest",
                "algorithm_family": "random_forest",
                "folds": [],
                "eligible_for_approval": True,
            },
        ],
    }

    roles = module._deployment_roles_for_results(results_data)
    results_data["deployment_roles"] = roles
    evaluation = module._compute_evaluation(results_data)

    assert roles["primary_model"] == "random-forest"
    assert roles["champion_fallback"] == "linear-baseline"
    assert evaluation["feature_contract_version"] == module.FEATURE_CONTRACT_VERSION
    assert evaluation["deployment_roles"] == roles


def test_invest_config_keeps_champion_primary_when_reference_risk_flagged(tmp_path) -> None:
    module = _load_script("run_retraining_test_primary_risk", "scripts/run_retraining.py")
    results_data = {
        "target_name": "future_max_drawdown_20d",
        "reference_risk_flag": True,
        "regime_breakdown": {"bull": {}, "bear": {}, "range": {}, "high_vol": {}},
        "models": [
            {
                "model_id": "baseline-1",
                "trainer_name": "linear-baseline",
                "algorithm_family": "linear_baseline",
                "folds": [{}],
                "eligible_for_approval": True,
            },
            {
                "model_id": "rf-1",
                "trainer_name": "random-forest",
                "algorithm_family": "random_forest",
                "folds": [{}],
                "eligible_for_approval": True,
            },
        ],
    }

    module._write_invest_config(results_data, artifact_root=tmp_path)
    config = json.loads((tmp_path / "invest_agent_models.json").read_text(encoding="utf-8"))

    assert config["primary_model"]["trainer_name"] == "linear-baseline"
    assert config["approval_summary"]["primary_challenger_allowed"] is False
    assert config["approved_challengers"] == []
    assert [model["trainer_name"] for model in config["approved_models"]] == ["linear-baseline"]
    assert config["conditional_models"][0]["trainer_name"] == "random-forest"
    assert config["conditional_models"][0]["status"] == "conditional"


def test_reference_resolution_falls_back_to_market_default_reference() -> None:
    module = _load_script("run_retraining_test_reference_fallback", "scripts/run_retraining.py")
    instrument = build_instrument_from_symbol("AAPL")
    bars = [
        PreparedPriceBar(
            symbol="SPY",
            trade_date=date(2026, 1, 1) + timedelta(days=index),
            close_native=100.0 + index,
            close_normalized=100.0 + index,
            volume=1000.0,
            currency="USD",
            target_currency="USD",
            is_halted=False,
            is_suspended=False,
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        for index in range(25)
    ]
    stats = module._empty_reference_stats()

    resolved = module._resolve_reference_bars(
        instrument=instrument,
        reference_type="benchmark",
        prepared_by_symbol={"SPY": bars},
        reference_stats=stats,
    )

    assert resolved == bars
    assert stats["benchmark"]["fallback_count"] == 1
    assert stats["benchmark"]["fallback_pairs"]["^GSPC->SPY"] == 1


def test_fetch_market_events_records_provider_counts(monkeypatch) -> None:
    module = _load_script("fetch_real_events_test", "scripts/fetch_real_events.py")

    def _event(symbol: str, event_type: EventType, suffix: str) -> PointInTimeEvent:
        ts = datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc)
        return PointInTimeEvent(
            symbol=symbol,
            event_type=event_type,
            event_time=ts,
            published_at=ts,
            source_name="test",
            source_url=f"https://example.com/{suffix}",
            payload_ref=suffix,
        )

    monkeypatch.setattr(module, "fetch_sec_filings", lambda symbol, failures: [_event(symbol, EventType.FILING, "f1")])
    monkeypatch.setattr(module, "fetch_earnings", lambda symbol, failures: [_event(symbol, EventType.EARNINGS, "e1")])
    monkeypatch.setattr(module, "fetch_news", lambda symbol, failures: [_event(symbol, EventType.NEWS, "n1")])
    monkeypatch.setattr(module, "time", type("FakeTime", (), {"sleep": staticmethod(lambda *_args, **_kwargs: None)}))

    events, report = module.fetch_market_events("us", ["AAPL"])

    assert len(events) == 3
    assert report["provider_counts"]["sec_filings"] == 1
    assert report["provider_counts"]["earnings_yfinance"] == 1
    assert report["provider_counts"]["news_yfinance"] == 1
    assert report["event_type_counts"]["filing"] == 1
    assert report["event_type_counts"]["earnings"] == 1
    assert report["event_type_counts"]["news"] == 1


def test_fetch_news_skips_items_without_publish_time(monkeypatch) -> None:
    module = _load_script("fetch_real_events_test_news_skip", "scripts/fetch_real_events.py")

    class FakeTicker:
        news = [
            {"title": "missing time", "link": "https://example.com/missing"},
            {
                "title": "valid news",
                "providerPublishTime": 1783526400,
                "uuid": "n1",
                "link": "https://example.com/valid",
            },
        ]

        def __init__(self, symbol: str):
            self.symbol = symbol

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))
    failures: list[dict] = []

    events = module.fetch_news("AAPL", failures)

    assert len(events) == 1
    assert events[0].headline == "valid news"
    assert failures[0]["provider"] == "news_yfinance_skipped"
    assert "skipped 1" in failures[0]["error"]


def test_fetch_hk_announcements_reads_hkex_json(monkeypatch) -> None:
    module = _load_script("fetch_real_events_test_hkex", "scripts/fetch_real_events.py")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "newsInfoLst": [
                    {
                        "newsId": 12238525,
                        "title": "DISCLOSEABLE TRANSACTION",
                        "webPath": "/listedco/listconews/sehk/2026/0708/test.pdf",
                        "stock": [{"sc": "00700", "sn": "TENCENT"}],
                        "relTime": "08/07/2026 22:52",
                    }
                ]
            }

    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: FakeResponse())
    failures: list[dict] = []

    events = module.fetch_hk_announcements("0700.HK", failures)

    assert len(events) == 1
    assert events[0].symbol == "0700.HK"
    assert events[0].provider == "hkex_announcements"
    assert events[0].source_url == "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0708/test.pdf"
    assert not failures


def test_run_audits_writes_new_outputs_and_legacy_aliases(tmp_path, monkeypatch) -> None:
    module = _load_script("run_audits_test", "scripts/run_audits.py")
    monkeypatch.setattr(module, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(module, "AUDITS", tmp_path / "audits")
    monkeypatch.setattr(module, "TEMP", tmp_path / "temp")
    monkeypatch.setattr(module, "RUNS", tmp_path / "runs")
    module.OUTPUT.mkdir(parents=True)
    module.AUDITS.mkdir(parents=True)
    module.TEMP.mkdir(parents=True)
    module.RUNS.mkdir(parents=True)

    sample = TrainingSample(
        symbol="AAPL",
        market=Market.US,
        instrument_type=InstrumentType.EQUITY,
        as_of_date=date(2026, 1, 30),
        as_of_time=datetime(2026, 1, 30, tzinfo=timezone.utc),
        feature_cutoff=datetime(2026, 1, 30, 23, tzinfo=timezone.utc),
        feature_version="f-v2",
        data_version="bundle_us",
        features={"event_score_1d": 1.0, "event_score_7d": 1.0, "ret_20d": 0.1},
        feature_coverage=0.9,
        missing_features=["benchmark_ret_20d"],
        labels=LabelSet(symbol="AAPL", as_of_date=date(2026, 1, 30), future_max_drawdown_20d=-0.1),
        point_in_time_event_count=2,
        provider="yfinance",
        published_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
        as_of=datetime(2026, 1, 30, 23, tzinfo=timezone.utc),
        raw_hash="raw",
        normalized_hash="norm",
    )
    with open(module.TEMP / "all_samples.pkl", "wb") as f:
        pickle.dump({"samples": [sample], "raw_samples": [sample]}, f)
    (module.OUTPUT / "results.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-08T00:00:00+00:00",
                "included_markets": ["us"],
                "excluded_markets": ["hk", "jp"],
                "excluded_market_reasons": {"hk": ["event coverage is zero"]},
                "coverage_group_distribution": {"us_core": 1},
                "regime_breakdown": {"bull": {"fold_count": 1}},
                "recent_window_breakdown": {"linear-baseline": [{"fold_id": "wf-1"}]},
                "reference_preflight": {
                    "threshold_checks": {
                        "benchmark_ret_20d": {
                            "missing_ratio": 0.0,
                            "max_missing_ratio": 0.02,
                            "status": "passed",
                        }
                    },
                    "risk_flag": False,
                },
                "reference_risk_flag": False,
                "task_matrix": {
                    "future_max_drawdown_20d": {
                        "regime_breakdown": {"bull": {"fold_count": 1}},
                        "recent_window_breakdown": {"linear-baseline": [{"fold_id": "wf-1"}]},
                    }
                },
                "models": [{"trainer_name": "linear-baseline", "folds": []}],
            }
        ),
        encoding="utf-8",
    )
    (module.OUTPUT / "labels.csv").write_text(
        "symbol,market,instrument_type,as_of_date,training_weight,selected_for_training,future_max_drawdown_20d\n"
        "AAPL,us,equity,2026-01-30,1.0,1,-0.1\n",
        encoding="utf-8",
    )
    bar = CanonicalPriceBar(
        symbol="AAPL",
        trade_date=date(2026, 1, 30),
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        adjusted_close=10.5,
        volume=1000.0,
        currency="USD",
        published_at=datetime(2026, 1, 30, tzinfo=timezone.utc),
        provider="yfinance",
        as_of=datetime(2026, 1, 30, tzinfo=timezone.utc),
        raw_hash="raw",
        normalized_hash="norm",
        data_version="bundle_us",
    )
    event = PointInTimeEvent(
        symbol="AAPL",
        event_type=EventType.NEWS,
        event_time=datetime(2026, 1, 29, tzinfo=timezone.utc),
        published_at=datetime(2026, 1, 29, tzinfo=timezone.utc),
        source_name="wire",
        provider="newswire",
        as_of=datetime(2026, 1, 29, tzinfo=timezone.utc),
        raw_hash="event-raw",
        normalized_hash="event-norm",
        data_version="events_us",
    )
    with open(module.OUTPUT / "bundle_us.pkl", "wb") as f:
        pickle.dump({"price_bars": [bar], "events": [event]}, f)
    (module.TEMP / "fetch_validation.json").write_text(
        json.dumps({"us": {"provider_usage": {"yfinance": 1}}}),
        encoding="utf-8",
    )
    (module.TEMP / "fetch_events_validation.json").write_text(
        json.dumps({"us": {"provider_counts": {"news_yfinance": 1}, "event_type_counts": {"news": 1}}}),
        encoding="utf-8",
    )
    (module.RUNS / "training-status.json").write_text(json.dumps({"state": "ok"}), encoding="utf-8")

    assert module.main() == 0
    assert (module.AUDITS / "data_coverage.json").exists()
    data_coverage = json.loads((module.AUDITS / "data_coverage.json").read_text(encoding="utf-8"))
    assert data_coverage["training_status"]["state"] == "ok"
    assert data_coverage["global_summary"]["training_status"]["state"] == "ok"
    assert (module.AUDITS / "label_coverage.json").exists()
    assert (module.AUDITS / "event_feature_coverage.json").exists()
    assert (module.AUDITS / "reference_coverage.json").exists()
    assert (module.AUDITS / "event_semantic_coverage.json").exists()
    assert (module.AUDITS / "regime_breakdown.json").exists()
    assert (module.AUDITS / "regime_balance.json").exists()
    assert (module.AUDITS / "recent_window_breakdown.json").exists()
    assert (module.AUDITS / "approval_report_random_forest.json").exists()
    assert (module.AUDITS / "approval_report_random_forest.md").exists()
    assert (module.AUDITS / "audit_data.json").exists()
    assert (module.AUDITS / "label_audit.json").exists()
    assert (module.AUDITS / "feature_audit.json").exists()


def test_serialize_models_writes_only_approved_trainers(tmp_path, monkeypatch) -> None:
    module = _load_script("serialize_models_test", "scripts/serialize_models.py")
    samples_path = tmp_path / "all_samples.pkl"
    results_path = tmp_path / "results.json"
    invest_config_path = tmp_path / "invest_agent_models.json"
    output_dir = tmp_path / "models"
    output_dir.mkdir(parents=True)
    (output_dir / "random-forest_model.pkl").write_bytes(b"stale")

    samples = []
    for index in range(30):
        sample_date = date(2026, 1, 1) + timedelta(days=index)
        samples.append(
            TrainingSample(
                symbol=f"S{index}",
                market=Market.US,
                instrument_type=InstrumentType.EQUITY,
                as_of_date=sample_date,
                as_of_time=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc),
                feature_cutoff=datetime.combine(sample_date, datetime.min.time(), tzinfo=timezone.utc),
                feature_version="f-v2",
                data_version="bundle_us",
                features={"ret_20d": float(index) / 100.0, "vol_20d": 0.1 + (index / 1000.0)},
                labels=LabelSet(
                    symbol=f"S{index}",
                    as_of_date=sample_date,
                    future_max_drawdown_20d=-0.1 if index % 3 == 0 else -0.02,
                ),
            )
        )
    with open(samples_path, "wb") as f:
        pickle.dump({"samples": samples}, f)
    results_path.write_text(
        json.dumps(
            {
                "data_source": "real",
                "training_profile": "full",
                "generated_at": "2026-07-08T00:00:00+00:00",
                "target_name": "future_max_drawdown_20d",
            }
        ),
        encoding="utf-8",
    )
    invest_config_path.write_text(
        json.dumps(
            {
                "primary_model": {"trainer_name": "linear-baseline", "model_id": "baseline-1"},
                "champion_fallback": {"trainer_name": "linear-baseline", "model_id": "baseline-1"},
                "approved_models": [
                    {"trainer_name": "linear-baseline"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(
            report=tmp_path / "unused.pkl",
            results=results_path,
            invest_config=invest_config_path,
            samples=samples_path,
            output_dir=output_dir,
        ),
    )

    assert module.main() == 0
    manifest = json.loads((output_dir / "model_manifest.json").read_text(encoding="utf-8"))
    assert manifest["approved_trainers"] == ["linear-baseline"]
    assert manifest["primary_model"]["trainer_name"] == "linear-baseline"
    assert manifest["champion_fallback"]["trainer_name"] == "linear-baseline"
    assert set(manifest["models"]) == {"linear-baseline"}
    assert manifest["models"]["linear-baseline"]["path"] == "linear-baseline_model.pkl"
    assert "random-forest" not in manifest["models"]
    assert not (output_dir / "random-forest_model.pkl").exists()
    archived = list((output_dir / "archive").glob("stale_models_*/random-forest_model.pkl"))
    assert archived


def test_training_job_syncs_final_status_into_audit_aliases(tmp_path, monkeypatch) -> None:
    module = _load_script("run_training_job_test_status_sync", "scripts/run_training_job.py")
    monkeypatch.setattr(module, "AUDITS", tmp_path / "audits")
    module.AUDITS.mkdir(parents=True)
    for name in ("data_coverage.json", "audit_data.json"):
        (module.AUDITS / name).write_text(
            json.dumps({"global_summary": {"training_status": {"state": "running"}}}),
            encoding="utf-8",
        )

    module.sync_audit_training_status({"state": "succeeded", "run_id": "job-1"})

    for name in ("data_coverage.json", "audit_data.json"):
        payload = json.loads((module.AUDITS / name).read_text(encoding="utf-8"))
        assert payload["training_status"]["state"] == "succeeded"
        assert payload["training_status"]["run_id"] == "job-1"
        assert payload["global_summary"]["training_status"]["state"] == "succeeded"
        assert payload["global_summary"]["training_status"]["run_id"] == "job-1"
