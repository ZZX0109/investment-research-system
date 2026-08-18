"""Generate competition-demo research fixtures.

These fixtures are explicitly RESEARCH DEMONSTRATION data: research_only,
deployment_ready=false, validation_status=research_demonstration_not_validated.
They let the competition demo run end-to-end (question -> tools -> plain
answer) when the real long_term_training artifact is still blocked, WITHOUT
overwriting the active ``artifacts/long_term_training/latest.json``.

Run: ``python3 scripts/build_competition_demo_fixtures.py``
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "artifacts" / "competition_demo"

# Three demo companies chosen to exercise the three required demo cases:
#  - 600519 示例白酒: high business quality, modest long-term readings
#  - 300750 示例电池: readings that conflict across horizons (industry cycle)
#  - 000858 示例食饮: fundamentals look fine but 240d observation is softer
COMPANIES = [
    {
        "symbol": "600519", "name": "示例白酒", "industry": "消费",
        "as_of_date": "2026-08-15",
        "scorecard": {
            "long_term_quality": 78.0, "growth_stability": 66.0,
            "valuation_position": 74.0, "shareholder_return": 72.0,
            "long_term_risk": 38.0, "evidence_completeness": 85.0,
            "composite_score": 70.0, "score_type": "research_demonstration",
            "evidence": ["财报覆盖较完整", "估值位置偏高需要持续关注"],
        },
        "readings": {
            "excess_return_120d": (-0.04, 0.05, 0.16),
            "excess_return_240d": (-0.06, 0.02, 0.12),
            "future_max_drawdown_120d": (-0.18, -0.10, -0.04),
            "future_max_drawdown_240d": (-0.24, -0.14, -0.06),
        },
    },
    {
        "symbol": "300750", "name": "示例电池", "industry": "新能源",
        "as_of_date": "2026-08-15",
        "scorecard": {
            "long_term_quality": 58.0, "growth_stability": 44.0,
            "valuation_position": 62.0, "shareholder_return": 50.0,
            "long_term_risk": 58.0, "evidence_completeness": 70.0,
            "composite_score": 52.0, "score_type": "research_demonstration",
            "evidence": ["盈利波动较大", "行业景气度存在分歧"],
        },
        # Conflict case: 120d相对表现偏强但240d偏弱，drawdown 240d偏大
        "readings": {
            "excess_return_120d": (-0.05, 0.07, 0.18),
            "excess_return_240d": (-0.16, -0.08, 0.04),
            "future_max_drawdown_120d": (-0.20, -0.12, -0.05),
            "future_max_drawdown_240d": (-0.34, -0.22, -0.08),
        },
    },
    {
        "symbol": "000858", "name": "示例食饮", "industry": "消费",
        "as_of_date": "2026-08-15",
        "scorecard": {
            "long_term_quality": 70.0, "growth_stability": 60.0,
            "valuation_position": 50.0, "shareholder_return": 64.0,
            "long_term_risk": 42.0, "evidence_completeness": 78.0,
            "composite_score": 62.0, "score_type": "research_demonstration",
            "evidence": ["经营质量尚可", "240日观察偏弱需关注"],
        },
        # Different-horizon inconsistency case: 120d偏强但240d偏弱
        "readings": {
            "excess_return_120d": (-0.03, 0.06, 0.15),
            "excess_return_240d": (-0.14, -0.07, 0.03),
            "future_max_drawdown_120d": (-0.16, -0.09, -0.04),
            "future_max_drawdown_240d": (-0.26, -0.16, -0.06),
        },
    },
]

HORIZON_DAYS = {
    "excess_return_120d": 120, "excess_return_240d": 240,
    "future_max_drawdown_120d": 120, "future_max_drawdown_240d": 240,
}

WEB_INDEX = [
    {"title": "示例白酒发布2026年中期报告", "source": "交易所公告", "url": "https://example-exchange.com/600519-mid-2026",
     "published_at": "2026-08-12", "snippet": "公司2026年上半年净利润同比增长，盈利能力保持稳定，分红政策延续。",
     "tags": ["600519", "示例白酒"], "kind": "announcement", "verified": True},
    {"title": "消费板块景气度跟踪", "source": "研究资讯", "url": "https://example-news.com/consumer-2026",
     "published_at": "2026-08-10", "snippet": "高端消费需求平稳，但部分子行业承压，估值位置偏高需要关注。",
     "tags": ["600519", "000858", "消费"], "kind": "news"},
    {"title": "示例电池行业产能与价格跟踪", "source": "行业研究", "url": "https://example-news.com/battery-2026",
     "published_at": "2026-08-09", "snippet": "新能源行业产能扩张，价格承压，部分企业盈利下滑，景气度存在分歧。",
     "tags": ["300750", "示例电池", "新能源"], "kind": "news"},
    {"title": "示例电池公司公告：定增与产能规划", "source": "交易所公告", "url": "https://example-exchange.com/300750-issue-2026",
     "published_at": "2026-08-05", "snippet": "公司披露定增方案与海外产能规划，短期摊薄盈利，长期扩张方向明确。",
     "tags": ["300750", "示例电池"], "kind": "announcement", "verified": True},
    {"title": "示例食饮渠道与动销跟踪", "source": "研究资讯", "url": "https://example-news.com/food-2026",
     "published_at": "2026-08-08", "snippet": "公司渠道动销平稳，但240日相对表现读数偏弱，需关注行业竞争与成本。",
     "tags": ["000858", "示例食饮", "消费"], "kind": "news"},
    {"title": "分红与股东回报政策更新", "source": "交易所公告", "url": "https://example-exchange.com/dividend-2026",
     "published_at": "2026-07-20", "snippet": "多家公司更新分红政策，强调稳定回报与投资者关系。",
     "tags": ["600519", "000858", "股东回报"], "kind": "announcement", "verified": True},
    {"title": "监管更新：披露与公司治理要求", "source": "监管动态", "url": "https://example-regulator.com/disclosure-2026",
     "published_at": "2026-07-05", "snippet": "提高定期报告披露要求，强化关联交易与ESG披露。",
     "tags": ["监管", "披露"], "kind": "news"},
]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _build_readings(company: dict) -> dict[str, dict[str, object]]:
    symbol = company["symbol"]
    as_of = company["as_of_date"]
    snapshot_id = f"snap-{_hash(symbol + as_of)[:12]}"
    snapshot_hash = _hash(symbol + as_of + "snapshot")
    out: dict[str, dict[str, object]] = {}
    for task, (q10, q50, q90) in company["readings"].items():
        artifact_hash = _hash(f"{symbol}:{task}:{as_of}")
        out[task] = {
            "symbol": symbol,
            "data_as_of": as_of,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
            "model": "research-demonstration",
            "model_version": f"{task}:demo:v1",
            "artifact_hash": artifact_hash,
            "status": "research_only",
            "deployment_ready": False,
            "horizon_days": HORIZON_DAYS[task],
            "horizon": f"{HORIZON_DAYS[task]}d",
            "q10": q10, "q50": q50, "q90": q90,
            "prediction_interval_width": round(q90 - q10, 6),
            "quantile_projection": "monotone_sort",
            "dataset_hash": _hash(symbol + "dataset"),
            "label_version": "research-demonstration-v1",
        }
    return out


def build_scorecard_fixture() -> dict:
    scorecards = []
    for company in COMPANIES:
        card = dict(company["scorecard"])
        card["symbol"] = company["symbol"]
        card["name"] = company["name"]
        card["industry"] = company["industry"]
        card["as_of_date"] = company["as_of_date"]
        card["long_term_model_readings"] = _build_readings(company)
        scorecards.append(card)
    return {
        "schema_version": "long-term-scorecard-response-v1",
        "data_tier": "research_demo",
        "deployment_ready": False,
        "status": "research_only",
        "validation_status": "research_demonstration_not_validated",
        "note": "比赛演示用研究展示数据，非验证预测结果；普通用户界面只展示通俗长期观察，不展示分位数与模型名称。",
        "generated_at": date.today().isoformat(),
        "scorecards": scorecards,
    }


def build_web_index_fixture() -> dict:
    return {
        "schema_version": "web-search-index-v1",
        "data_tier": "research_demo",
        "validation_status": "research_demonstration_not_validated",
        "note": "比赛演示用联网搜索索引，非实时新闻抓取结果；每条均保留来源、标题、发布日期与链接。",
        "results": WEB_INDEX,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scorecard_path = OUT_DIR / "long_term_research_demo.json"
    web_path = OUT_DIR / "web_search_index.json"
    scorecard_path.write_text(json.dumps(build_scorecard_fixture(), ensure_ascii=False, indent=2), encoding="utf-8")
    web_path.write_text(json.dumps(build_web_index_fixture(), ensure_ascii=False, indent=2), encoding="utf-8")
    # Validate every reading against the same rules the real loader uses.
    from investment_research.service.deep_long_term import _validate_reading
    fixture = json.loads(scorecard_path.read_text(encoding="utf-8"))
    for card in fixture["scorecards"]:
        for task, reading in card["long_term_model_readings"].items():
            _validate_reading(task, reading)
    print(f"wrote {scorecard_path.relative_to(ROOT)} ({len(fixture['scorecards'])} companies)")
    print(f"wrote {web_path.relative_to(ROOT)} ({len(WEB_INDEX)} entries)")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    main()
