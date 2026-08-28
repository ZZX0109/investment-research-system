"""Tests for the plain-language answer formatter.

These guard the product rules a competition judge cares about:

* no q10/q50/q90 quantiles reach the user-facing answer
* the four readings are translated into neutral observation wording
* the answer never contains buy/sell/position/target-price/guaranteed-return
* conflicts and missing evidence are stated explicitly
* every answer ends with a sources + data-date section
"""
from __future__ import annotations

from investment_research.agent.plain_answer import PlainAnswerBuilder


def _builder() -> PlainAnswerBuilder:
    return PlainAnswerBuilder()


def _full_readings() -> dict[str, dict[str, object]]:
    return {
        "excess_return_120d": {
            "q10": -0.08, "q50": 0.06, "q90": 0.18,
            "horizon_days": 120, "data_as_of": "2026-08-15",
            "artifact_hash": "a" * 64,
        },
        "excess_return_240d": {
            "q10": -0.10, "q50": -0.05, "q90": 0.12,
            "horizon_days": 240, "data_as_of": "2026-08-15",
            "artifact_hash": "b" * 64,
        },
        "future_max_drawdown_120d": {
            "q10": -0.20, "q50": -0.14, "q90": -0.05,
            "horizon_days": 120, "data_as_of": "2026-08-15",
            "artifact_hash": "c" * 64,
        },
        "future_max_drawdown_240d": {
            "q10": -0.30, "q50": -0.18, "q90": -0.06,
            "horizon_days": 240, "data_as_of": "2026-08-15",
            "artifact_hash": "d" * 64,
        },
    }


def _full_scorecard() -> dict[str, object]:
    return {
        "long_term_quality": 72.0,
        "growth_stability": 60.0,
        "valuation_position": 58.0,
        "shareholder_return": 65.0,
        "long_term_risk": 40.0,
        "evidence_completeness": 82.0,
        "as_of_date": "2026-08-15",
    }


def test_translates_four_readings_without_quantiles() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营怎么样",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts={"latest_close": 1680.0, "trade_date": "2026-08-15"},
        data_as_of="2026-08-15",
    )
    labels = {item.label for item in answer.long_term_observations}
    assert "相对基准的长期表现观察" in labels
    assert "潜在下跌幅度观察" in labels
    # The neutral observation wording must be present.
    text = _all_text(answer)
    assert "相对基准的长期表现观察" in text
    assert "潜在下跌幅度观察" in text
    # Quantiles must NEVER appear in the user-facing answer.
    for forbidden in ("q10", "q50", "q90", "P10", "P50", "P90", "低位", "中位", "高位"):
        assert forbidden not in text, forbidden


def test_no_trade_instructions_in_any_section() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="能不能买入",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    assert answer.compliance_allowed is True
    text = _all_text(answer)
    for forbidden in ("买入", "卖出", "加仓", "减仓", "目标价", "保证收益", "稳赚", "必涨"):
        assert forbidden not in text, forbidden


def test_missing_readings_produce_insufficient_evidence_status() -> None:
    readings = _full_readings()
    del readings["future_max_drawdown_240d"]
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    assert answer.result_status == "insufficient_evidence"
    assert "尚未生成" in answer.missing_evidence
    assert any(not item.available for item in answer.long_term_observations)


def test_conflict_between_knowledge_and_web_is_detected() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营变化",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=[{"snippet": "公司净利润同比增长，盈利改善", "document": {"title": "季报", "source_name": "知识库", "source_url": "https://kb.example/1", "published_at": "2026-06-30"}, "citation_id": "kb:1"}],
        web_results=[{"title": "行业承压", "source": "新闻", "url": "https://news.example/1", "published_at": "2026-08-10", "snippet": "公司利润下滑，行业承压"}],
        price_facts=None, data_as_of="2026-08-15",
    )
    assert answer.result_status == "conflict_present"
    assert any(item.classification == "conflict" for item in answer.evidence)


def test_sources_section_lists_materials_and_data_date() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="风险",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=[{"snippet": "分红稳定", "document": {"title": "公司资料", "source_name": "知识库", "source_url": "https://kb.example/2", "published_at": "2026-06-30"}, "citation_id": "kb:2"}],
        web_results=[{"title": "最新公告", "source": "交易所", "url": "https://exchange.example/1", "published_at": "2026-08-12", "snippet": "发布中期报告"}],
        price_facts=None, data_as_of="2026-08-15",
    )
    assert "数据截至 2026-08-15" in answer.sources_summary
    assert answer.sources
    assert any(item.kind == "news" for item in answer.sources)
    assert any(item.kind == "knowledge" for item in answer.sources)
    assert all(item.url for item in answer.sources)


def test_no_scorecard_does_not_fabricate_business_conclusion() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营情况",
        scorecard=None, model_readings=None,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of=None,
    )
    assert answer.result_status == "insufficient_evidence"
    assert "缺少" in answer.business_condition or "尚未" in answer.business_condition
    assert "不强行下结论" in answer.business_condition


def test_drawdown_described_as_observation_not_prediction() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="风险",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    text = _all_text(answer)
    assert "潜在下跌幅度观察" in text
    # Must not be sold as a fall prediction or sell signal.
    assert "卖出信号" not in text
    assert "必跌" not in text


def test_portfolio_note_is_explanation_not_rebalance() -> None:
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="组合影响",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        portfolio_note={"concentration": "组合集中在消费与新能源", "possible_impact": "可能受行业景气度影响", "missing_info": "需补充持仓明细"},
    )
    assert answer.portfolio_note is not None
    assert "消费" in answer.portfolio_note.concentration
    text = _all_text(answer)
    assert "调仓" not in text and "仓位指令" not in text


def _all_text(answer) -> str:
    return " ".join([
        answer.business_condition,
        answer.long_term_changes,
        answer.possible_risks,
        answer.missing_evidence,
        answer.sources_summary,
        " ".join(item.text for item in answer.evidence),
        " ".join(item.interpretation for item in answer.long_term_observations),
    ])


def test_walk_forward_and_fundamental_coverage_surface_in_missing_evidence() -> None:
    """§1 step7 / §3 readouts reach the user-facing answer (§2 piece 3):
    the per-asset directional-accuracy + data-gap lines must appear in the
    missing-evidence section, grounded in real archived numbers, and stay
    compliance-safe (no buy/sell/target/quantile leak)."""
    walk_forward_daily = {
        "status": "ok",
        "decision_count": 24,
        "directional_accuracy": 0.625,
        "mean_abs_error": 0.2585,
        "mean_signed_error": 0.2309,
        "dates": [],
    }
    fundamental_coverage = {
        "status": "ok",
        "expected_count": 6,
        "present": ["revenue", "net_profit", "gross_margin"],
        "missing": ["operating_profit", "roe", "roa"],
        "coverage_pct": 50.0,
    }
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营怎么样",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        walk_forward_daily=walk_forward_daily,
        fundamental_coverage=fundamental_coverage,
    )
    assert answer.compliance_allowed is True
    missing = answer.missing_evidence
    # Walk-forward readout (grounded, per-asset).
    assert "历史方向命中62%" in missing
    assert "平均误差25.9%" in missing
    assert "系统性高估23.1%" in missing
    assert "仅作研究参考" in missing
    # Fundamental-coverage gap (which pillars are missing).
    assert "基本面覆盖50%" in missing
    assert "operating_profit" in missing and "roe" in missing and "roa" in missing
    # Compliance: no trade/target/quantile leak from the new readouts.
    text = _all_text(answer)
    for forbidden in ("买入", "卖出", "加仓", "减仓", "目标价", "保证收益", "q10", "q50", "q90"):
        assert forbidden not in text, forbidden


def test_missing_evidence_unchanged_when_new_fields_absent() -> None:
    """Passing None for the new fields leaves the legacy missing-evidence
    behavior intact (no regression)."""
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="经营怎么样",
        scorecard=_full_scorecard(), model_readings=_full_readings(),
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
    )
    assert answer.compliance_allowed is True
    assert "历史方向命中" not in answer.missing_evidence
    assert "基本面覆盖" not in answer.missing_evidence


def test_catboost_readout_surfaced_in_missing_evidence() -> None:
    """§1 row-2 / §2 three-piece: the CatBoost research-model direction + its
    real OOF accuracy are rendered in the missing-evidence section
    (训练说清楚) — a compliance-safe research readout, never buy/sell."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        catboost_direction={"direction": 1, "probability": 0.756, "features": {}},
        catboost_accuracy={
            "status": "ok", "n_holdout": 3489, "directional_accuracy": 0.6306,
            "majority_base_rate": 0.5913, "edge_over_base": 0.0393,
        },
    )
    txt = answer.missing_evidence
    assert "CatBoost 研究模型" in txt
    assert "偏强" in txt  # direction == 1
    assert "置信76%" in txt
    assert "OOF 方向命中63.1%" in txt
    assert "较基线高3.9个百分点" in txt
    assert "仅作研究参考" in txt
    # Compliance: never a buy/sell/target instruction.
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_catboost_readout_down_direction() -> None:
    """Direction == 0 renders as 偏弱 (not a sell instruction)."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        catboost_direction={"direction": 0, "probability": 0.62, "features": {}},
        catboost_accuracy=None,  # degrade: accuracy absent, direction still shown
    )
    txt = answer.missing_evidence
    assert "CatBoost 研究模型" in txt
    assert "偏弱" in txt
    assert "置信62%" in txt
    assert "OOF" not in txt  # accuracy absent → not rendered


def test_catboost_readout_absent_without_direction() -> None:
    """No catboost_direction → no CatBoost readout (degrade, no fabrication)."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        catboost_direction=None,
        catboost_accuracy={"status": "ok", "directional_accuracy": 0.63},
    )
    assert "CatBoost" not in answer.missing_evidence


def test_catboost_readout_names_top_feature_driver() -> None:
    """§1 row-2 / 训练说清楚: the plain answer names the top feature driver
    (explainability) when catboost_feature_importance is supplied."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        catboost_direction={"direction": 1, "probability": 0.756, "features": {}},
        catboost_accuracy={
            "status": "ok", "directional_accuracy": 0.6306,
            "majority_base_rate": 0.5913, "edge_over_base": 0.0393,
        },
        catboost_feature_importance={
            "status": "ok",
            "features": [
                {"feature": "industry_key", "importance_pct": 39.91},
                {"feature": "score", "importance_pct": 22.01},
            ],
        },
    )
    txt = answer.missing_evidence
    assert "CatBoost 研究模型" in txt
    assert "主要由行业驱动" in txt  # industry_key → 行业, top driver
    assert "40%" in txt  # 39.91 → ~40
    assert "仅作研究参考" in txt
    # Compliance: never a buy/sell/target instruction.
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_catboost_readout_surfaces_best_regime() -> None:
    """§1 row-2 / 训练说清楚: the plain answer surfaces the best regime's
    accuracy when it notably beats the global (WHERE the model works)."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        catboost_direction={"direction": 1, "probability": 0.756, "features": {}},
        catboost_accuracy={
            "status": "ok", "directional_accuracy": 0.6306,
            "majority_base_rate": 0.5913, "edge_over_base": 0.0393,
            "by_regime": {
                "bull": {"n": 187, "directional_accuracy": 0.7647},
                "range": {"n": 2474, "directional_accuracy": 0.6221},
            },
        },
    )
    txt = answer.missing_evidence
    assert "牛市命中率更高" in txt  # bull 76% vs global 63% → +13pts, notable
    assert "76%" in txt
    assert "仅作研究参考" in txt
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_catboost_readout_omits_best_regime_when_not_notable() -> None:
    """If no regime notably beats global, omit the best-regime clause (no
    fabrication / no over-stuffing)."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        catboost_direction={"direction": 1, "probability": 0.6, "features": {}},
        catboost_accuracy={
            "status": "ok", "directional_accuracy": 0.63,
            "by_regime": {"range": {"n": 100, "directional_accuracy": 0.64}},  # +1pt, not notable
        },
    )
    assert "命中率更高" not in answer.missing_evidence


def test_long_term_directional_by_regime_surfaced() -> None:
    """§3 / 训练说清楚 WHERE (long-term): the plain answer surfaces the
    long-term model's global directional accuracy by regime as a system-level
    reliability caveat."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="长期风险",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None,
        data_as_of="2026-08-15",
        long_term_directional_by_regime={
            "status": "ok", "directional_accuracy": 0.5564, "n": 17444,
            "by_regime": {
                "bull": {"n": 896, "directional_accuracy": 0.6406},
                "range": {"n": 12481, "directional_accuracy": 0.5478},
            },
        },
    )
    txt = answer.missing_evidence
    assert "长期模型整体表现" in txt
    assert "整体方向命中55.6%" in txt
    assert "牛市命中率更高（64%）" in txt  # best regime
    assert "仅作研究参考" in txt
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_catboost_short_term_horizons_surfaced() -> None:
    """§1 row-2 (round 27) / §2 three-piece: the price-based 1/5/20d CatBoost
    horizon forecasts + their REAL holdout directional accuracy are rendered in
    the missing-evidence section (训练说清楚) — compliance-safe, never buy/sell."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="短期方向",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None, data_as_of="2026-08-15",
        catboost_short_term_horizons={
            "status": "ok", "as_of": "2024-12-31", "latest_close": 1435.7,
            "horizons": {
                "1d": {"direction": "down", "probability": 0.5787, "directional_accuracy": 0.5405, "edge": 0.0106},
                "5d": {"direction": "down", "probability": 0.5245, "directional_accuracy": 0.5489, "edge": 0.0283},
                "20d": {"direction": "down", "probability": 0.6235, "directional_accuracy": 0.5874, "edge": 0.0874},
            },
        },
    )
    txt = answer.missing_evidence
    assert "短期 CatBoost 方向读数" in txt
    assert "1d方向看跌" in txt and "5d方向看跌" in txt and "20d方向看跌" in txt
    assert "历史命中54%" in txt  # 1d accuracy surfaced
    assert "历史命中59%" in txt  # 20d accuracy surfaced
    assert "仅作研究参考" in txt
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_catboost_horizon_walk_forward_daily_surfaced() -> None:
    """§1 row-3 (round 28) / 训练说清楚 WHERE per-asset (short-term): the
    1/5/20d model's REALIZED directional accuracy on this stock's history is
    rendered in the missing-evidence section — compliance-safe, never buy/sell."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="短期方向",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None, data_as_of="2026-08-15",
        catboost_horizon_walk_forward_daily={
            "status": "ok", "symbol": "600519", "n_bars": 1212,
            "horizons": {
                "1d": {"status": "ok", "decision_count": 1172, "directional_accuracy": 0.5316, "mean_confidence": 0.5464},
                "5d": {"status": "ok", "decision_count": 1172, "directional_accuracy": 0.5401, "mean_confidence": 0.5281},
                "20d": {"status": "ok", "decision_count": 1172, "directional_accuracy": 0.5759, "mean_confidence": 0.5493},
            },
        },
    )
    txt = answer.missing_evidence
    assert "短期模型在该标的的历史表现" in txt
    assert "1d命中53%" in txt and "5d命中54%" in txt and "20d命中58%" in txt
    assert "1172次" in txt
    assert "仅作研究参考" in txt
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_temporal_price_path_forecast_surfaced() -> None:
    """§1 row-5 (round 30) / §2 three-piece: the temporal price-path forecast
    (trained kittenCN price-only LSTM) + its honest directional accuracy are
    rendered in the missing-evidence section — compliance-safe, never a target
    price (explicitly framed as 路径为模型推演，不构成投资建议)."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="价格路径",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None, data_as_of="2026-08-15",
        price_path_forecast={
            "status": "ok", "model": "temporal_lstm (kittenCN price-only)",
            "horizon_days": 20, "endpoint_q50": 1477.78, "endpoint_q10": 1277.34,
            "endpoint_q90": 1678.22, "directional_accuracy": 0.4666,
            "architecture": "LSTM(1,32)->Linear(32,1), price-only, window=20",
        },
    )
    txt = answer.missing_evidence
    assert "时序 LSTM（kittenCN 价格路径）" in txt
    assert "未来20日中位路径约1477.78" in txt
    assert "区间1277.34~1678.22" in txt
    assert "历史方向命中47%" in txt
    assert "仅作研究参考" in txt
    assert "路径为模型推演，不构成投资建议" in txt  # explicit non-target framing
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_temporal_vendored_hybrid_forecast_surfaced() -> None:
    """§1 row-5 round 31: the VENDORED TemporalHybridNet (the named
    temporal_hybrid model) forecast + accuracy surface in the plain answer with
    the hybrid tag — compliance-safe, never a target price."""
    readings = _full_readings()
    answer = _builder().build(
        symbol="600519", asset_name="示例公司", task_text="价格路径",
        scorecard=_full_scorecard(), model_readings=readings,
        knowledge_results=None, web_results=None, price_facts=None, data_as_of="2026-08-15",
        price_path_forecast={
            "status": "ok", "model": "temporal_hybrid (vendored kittenCN, price-only)",
            "horizon_days": 20, "endpoint_q50": 1461.19, "endpoint_q10": 1264.38,
            "endpoint_q90": 1658.01, "directional_accuracy": 0.4963,
            "architecture": "TemporalHybridNet (vendored kittenCN temporal_hybrid)",
        },
    )
    txt = answer.missing_evidence
    assert "时序混合网络（kittenCN 价格路径）" in txt  # hybrid tag (not LSTM)
    assert "未来20日中位路径约1461" in txt
    assert "区间1264.38~1658.01" in txt
    assert "历史方向命中50%" in txt
    assert "仅作研究参考" in txt
    for bad in ("买入", "卖出", "加仓", "减仓", "目标价"):
        assert bad not in txt


def test_intraday_quote_surfaced_in_business_condition():
    """Round 34 — same-day intraday quote (盘中实时) surfaces in the business
    condition section, marked as a snapshot (not the confirmed close)."""
    b = PlainAnswerBuilder()
    ans = b.build(
        symbol="600519", asset_name="贵州茅台", task_text="x",
        scorecard=None, model_readings=None, knowledge_results=None,
        web_results=None, price_facts={"latest_close": 1290.0},
        data_as_of="2026-08-19",
        intraday_quote={"latest_price": 1294.56, "change_pct": -1.018},
    )
    assert "盘中价" in ans.business_condition
    assert "1294.56" in ans.business_condition
    assert "-1.02%" in ans.business_condition
    assert "非收盘确认" in ans.business_condition


def test_market_news_surfaced_in_long_term_changes():
    """Round 34 — per-asset news + notices surface in long-term changes."""
    b = PlainAnswerBuilder()
    ans = b.build(
        symbol="600519", asset_name="贵州茅台", task_text="x",
        scorecard=None, model_readings=None, knowledge_results=None,
        web_results=None, price_facts=None, data_as_of="2026-08-19",
        market_news=[
            {"kind": "news", "title": "贵州茅台中报净利润445亿元", "published_at": "2026-08-15 10:11"},
            {"kind": "notice", "title": "关于2025年度权益分派", "date": "2026-08-10"},
        ],
    )
    assert "新闻与公告" in ans.long_term_changes
    assert "中报净利润445" in ans.long_term_changes
