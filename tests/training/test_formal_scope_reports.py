from __future__ import annotations

from types import SimpleNamespace

from investment_research.training.approval_reports import REQUIRED_SCOPE_REPORTS
from investment_research.training.formal_scope_reports import build_formal_scope_reports


def _manifest() -> dict[str, object]:
    return {
        "dataset_hash": "a" * 64,
        "leakage_report_hash": "b" * 64,
        "market": "cn",
    }


def _sample() -> SimpleNamespace:
    return SimpleNamespace(
        feature_coverage=0.95,
        core_feature_coverage=0.98,
        data_issues=["event_coverage_partial"],
        event_coverage_status="partial",
    )


def test_formal_scope_reports_use_evaluated_or_explicit_blocked_statuses() -> None:
    reports = build_formal_scope_reports(
        dataset_manifest=_manifest(),
        plan={"scope": "cn:close_confirmed:drawdown_20d", "embargo_sessions": 20},
        result={
            "fold_hash": "c" * 64,
            "selected_candidate": "logistic-regression",
            "candidates": [{
                "name": "logistic-regression", "calibration_method": "platt",
                "brier": 0.2, "regime_metrics": {"range": {"sample_count": 16}},
            }],
            "holdout_scores": [0.2, 0.8], "holdout_labels": [0, 1],
            "stress_scores": [0.4], "stress_labels": [0],
        },
        samples=[_sample()],
    )

    assert set(reports) == set(REQUIRED_SCOPE_REPORTS)
    assert reports["holdout_12m"]["status"] == "evaluated_once"
    assert reports["stress_6m"]["status"] == "evaluated_once"
    assert reports["ablation"]["status"] == "blocked"
    assert reports["cost_liquidity"]["status"] == "blocked"
    assert all(
        not str(report.get("status", "")).startswith("pending")
        for report in reports.values()
    )


def test_direction_report_includes_final_holdout_metrics() -> None:
    reports = build_formal_scope_reports(
        dataset_manifest=_manifest(),
        plan={"scope": "cn:pre_open:direction_1d", "embargo_sessions": 1},
        result={
            "fold_hash": "c" * 64,
            "selected_candidate": "momentum",
            "candidates": [{"name": "momentum", "regime_metrics": {}}],
            "holdout_probabilities": [{"up": 0.8, "down": 0.1, "flat": 0.1}],
            "holdout_labels": ["up"],
            "stress_probabilities": [{"up": 0.1, "down": 0.8, "flat": 0.1}],
            "stress_labels": ["down"],
        },
        samples=[_sample()],
    )

    assert reports["holdout_12m"]["metrics"]["accuracy"] == 1.0
    assert reports["stress_6m"]["metrics"]["class_counts"] == {"down": 1}


def test_industry_report_uses_published_candidate_metrics() -> None:
    reports = build_formal_scope_reports(
        dataset_manifest=_manifest(),
        plan={"scope": "cn:close_confirmed:excess_return_120d", "embargo_sessions": 120},
        result={
            "fold_hash": "c" * 64,
            "selected_candidate": "ridge",
            "candidates": [{
                "name": "ridge",
                "industry_rank_ic": {"banks": 0.08, "technology": 0.03},
            }],
            "holdout_quantiles": [[-0.1, 0.0, 0.1]],
            "holdout_targets": [0.02],
            "stress_quantiles": [[-0.1, 0.0, 0.1]],
            "stress_targets": [-0.01],
        },
        samples=[_sample()],
    )
    assert reports["market_industry_regime"]["status"] == "evaluated"
    assert reports["market_industry_regime"]["industry_rank_ic"]["banks"] == 0.08
    assert reports["holdout_12m"]["metrics"]["pinball_loss"] is not None
    assert reports["holdout_12m"]["metrics"]["mae"] is not None
