"""Curated competition-demo knowledge base seed content.

Research-demonstration data: clearly labeled, public-shaped excerpts and
sourced fact cards for the three demo companies.  This is NOT validated
financial data and is never presented as live research — it exists so the
long-term investment AI assistant has a non-empty, citable knowledge base to
demonstrate deep analysis when the real ingestion pipeline (akshare/cninfo)
is network-gated.

Conventions:
* ``source_url`` always https (domain model requirement).
* news/analyst items are ``metadata_excerpt`` only (no copyrighted full text).
* documents carry finance-aware section structure so ``KnowledgeChunker``
  splits by 第X章/一、二、 for precise retrieval.
"""
from __future__ import annotations

from datetime import datetime, timezone

# All demo timestamps share one frozen research date so PIT filtering is
# deterministic and obviously research-only.
AS_OF = "2026-08-15T08:00:00+00:00"
PUBLISHED_AT = "2026-06-30T08:00:00+00:00"  # interim report window
ANNOUNCEMENT_AT = "2026-08-12T08:00:00+00:00"

# authority_level: 5 = exchange/regulator filing, 4 = audited annual report,
# 3 = official interim, 2 = research note metadata, 1 = news metadata.

_LINE_ITEMS: dict[str, list[dict]] = {
    "600519": [
        {"period": "2025FY", "metric": "revenue", "metric_label": "营业总收入", "value": 1743.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 9.5, "authority_level": 4,
         "source_url": "https://example-exchange.com/600519-annual-2025"},
        {"period": "2025FY", "metric": "net_profit", "metric_label": "归母净利润", "value": 892.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 8.0, "authority_level": 4,
         "source_url": "https://example-exchange.com/600519-annual-2025"},
        {"period": "2025FY", "metric": "gross_margin", "metric_label": "毛利率", "value": 91.5,
         "unit": "%", "scale": 1.0, "yoy_pct": 0.3, "authority_level": 4,
         "source_url": "https://example-exchange.com/600519-annual-2025"},
        {"period": "2026H1", "metric": "revenue", "metric_label": "营业总收入", "value": 905.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 8.2, "authority_level": 3,
         "source_url": "https://example-exchange.com/600519-interim-2026"},
        {"period": "2026H1", "metric": "net_profit", "metric_label": "归母净利润", "value": 466.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 7.1, "authority_level": 3,
         "source_url": "https://example-exchange.com/600519-interim-2026"},
    ],
    "300750": [
        {"period": "2025FY", "metric": "revenue", "metric_label": "营业总收入", "value": 3654.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 6.2, "authority_level": 4,
         "source_url": "https://example-exchange.com/300750-annual-2025"},
        {"period": "2025FY", "metric": "net_profit", "metric_label": "归母净利润", "value": 410.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 4.5, "authority_level": 4,
         "source_url": "https://example-exchange.com/300750-annual-2025"},
        {"period": "2025FY", "metric": "gross_margin", "metric_label": "毛利率", "value": 23.0,
         "unit": "%", "scale": 1.0, "yoy_pct": -1.5, "authority_level": 4,
         "source_url": "https://example-exchange.com/300750-annual-2025"},
    ],
    "000858": [
        {"period": "2025FY", "metric": "revenue", "metric_label": "营业总收入", "value": 920.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 5.1, "authority_level": 4,
         "source_url": "https://example-exchange.com/000858-annual-2025"},
        {"period": "2025FY", "metric": "net_profit", "metric_label": "归母净利润", "value": 332.0,
         "unit": "亿元", "scale": 1.0, "yoy_pct": 3.2, "authority_level": 4,
         "source_url": "https://example-exchange.com/000858-annual-2025"},
    ],
}


COMPANIES: list[dict] = [
    {
        "symbol": "600519",
        "name": "示例白酒",
        "industry": "消费",
        "line_items": _LINE_ITEMS["600519"],
        "documents": [
            {
                "title": "示例白酒 2025 年年度报告（节选）",
                "source_name": "交易所公告",
                "source_url": "https://example-exchange.com/600519-annual-2025",
                "document_type": "annual_report_excerpt",
                "report_period": "2025FY",
                "authority_level": 4,
                "content": (
                    "一、经营情况讨论与分析\n"
                    "2025 年公司实现营业总收入约 1743 亿元，同比增长约 9.5%；"
                    "归属于上市公司股东的净利润约 892 亿元，同比增长约 8.0%。"
                    "毛利率维持在 91% 以上，高端产品占比提升，经营质量保持稳定。\n"
                    "二、风险因素\n"
                    "主要风险包括：宏观经济波动影响高端消费需求；行业竞争加剧可能压缩份额；"
                    "原材料与包材成本上行；渠道库存波动。公司强调通过品牌力与产品结构对冲。\n"
                    "三、股东回报\n"
                    "公司延续稳定分红政策，2025 年度拟现金分红比例不低于 51%，并持续强化投资者关系。"
                ),
            },
            {
                "title": "示例白酒 2026 年中期报告（节选）",
                "source_name": "交易所公告",
                "source_url": "https://example-exchange.com/600519-interim-2026",
                "document_type": "interim_report_excerpt",
                "report_period": "2026H1",
                "authority_level": 3,
                "content": (
                    "一、经营情况\n"
                    "2026 年上半年营业总收入约 905 亿元，同比增长约 8.2%；"
                    "净利润约 466 亿元，同比增长约 7.1%。盈利能力保持稳定，分红政策延续。\n"
                    "二、行业环境\n"
                    "高端消费需求平稳，但部分子行业承压，估值位置偏高需要持续关注。"
                ),
            },
        ],
        "fact_cards": [
            {"fact_key": "operations.growth", "topic": "经营", "stance": "supporting",
             "claim": "2025 年营业总收入同比增长约 9.5%，净利润同比增长约 8.0%，毛利率维持 91% 以上，经营质量保持稳定。",
             "confidence": 0.92, "authority_level": 4},
            {"fact_key": "shareholder.dividend", "topic": "股东回报", "stance": "supporting",
             "claim": "2025 年度拟现金分红比例不低于 51%，延续稳定分红政策。",
             "confidence": 0.88, "authority_level": 4},
            {"fact_key": "valuation.high", "topic": "估值", "stance": "contrary",
             "claim": "估值位置偏高，若高端消费需求或行业景气度走弱，估值可能面临消化压力。",
             "confidence": 0.6, "authority_level": 3},
            {"fact_key": "industry.pressure", "topic": "行业", "stance": "uncertain",
             "claim": "高端消费需求平稳但部分子行业承压，行业景气度存在分歧，需持续观察。",
             "confidence": 0.5, "authority_level": 2},
        ],
    },
    {
        "symbol": "300750",
        "name": "示例电池",
        "industry": "新能源",
        "line_items": _LINE_ITEMS["300750"],
        "documents": [
            {
                "title": "示例电池 2025 年年度报告（节选）",
                "source_name": "交易所公告",
                "source_url": "https://example-exchange.com/300750-annual-2025",
                "document_type": "annual_report_excerpt",
                "report_period": "2025FY",
                "authority_level": 4,
                "content": (
                    "一、经营情况\n"
                    "2025 年营业总收入约 3654 亿元，同比增长约 6.2%；净利润约 410 亿元，"
                    "同比增长约 4.5%。毛利率约 23%，较上年回落，行业产能扩张导致价格承压。\n"
                    "二、风险因素\n"
                    "主要风险：行业产能扩张、上游材料价格波动、海外贸易政策变化、技术路线迭代。"
                    "盈利稳定性下降，长期风险读数偏高。\n"
                    "三、股东回报\n"
                    "公司保持一定分红，但因扩产资金需求，分红比例相对稳健。"
                ),
            },
            {
                "title": "示例电池 定增与海外产能规划公告",
                "source_name": "交易所公告",
                "source_url": "https://example-exchange.com/300750-issue-2026",
                "document_type": "announcement_metadata",
                "announcement_category": "再融资",
                "authority_level": 5,
                "content": (
                    "公司披露定增方案与海外产能规划：短期摊薄盈利，长期扩张方向明确。"
                    "市场对行业景气度存在分歧，部分研究认为产能过剩将持续压制盈利。"
                ),
            },
        ],
        "fact_cards": [
            {"fact_key": "operations.decline", "topic": "经营", "stance": "contrary",
             "claim": "2025 年毛利率较上年回落，行业产能扩张导致价格承压，盈利稳定性下降。",
             "confidence": 0.82, "authority_level": 4},
            {"fact_key": "industry.conflict", "topic": "行业", "stance": "uncertain",
             "claim": "行业产能扩张、价格承压、部分企业盈利下滑，但海外产能规划指向长期扩张，景气度存在分歧。",
             "confidence": 0.6, "authority_level": 3},
            {"fact_key": "risk.high", "topic": "风险", "stance": "contrary",
             "claim": "上游材料价格波动、海外贸易政策变化、技术路线迭代使长期风险读数偏高。",
             "confidence": 0.7, "authority_level": 4},
            {"fact_key": "expansion.longterm", "topic": "经营", "stance": "supporting",
             "claim": "海外产能规划指向长期扩张方向，但短期摊薄盈利。",
             "confidence": 0.55, "authority_level": 5},
        ],
    },
    {
        "symbol": "000858",
        "name": "示例食饮",
        "industry": "消费",
        "line_items": _LINE_ITEMS["000858"],
        "documents": [
            {
                "title": "示例食饮 2025 年年度报告（节选）",
                "source_name": "交易所公告",
                "source_url": "https://example-exchange.com/000858-annual-2025",
                "document_type": "annual_report_excerpt",
                "report_period": "2025FY",
                "authority_level": 4,
                "content": (
                    "一、经营情况\n"
                    "2025 年营业总收入约 920 亿元，同比增长约 5.1%；净利润约 332 亿元，"
                    "同比增长约 3.2%。经营质量尚可，但增速放缓，渠道动销平稳。\n"
                    "二、风险因素\n"
                    "行业竞争加剧、消费场景修复不及预期、原材料成本波动。"
                    "240 日相对表现读数偏弱，需关注行业竞争与成本。\n"
                    "三、股东回报\n"
                    "分红政策稳定，股东回报保持。"
                ),
            },
            {
                "title": "示例食饮 渠道动销跟踪（研究资讯摘要）",
                "source_name": "研究资讯",
                "source_url": "https://example-news.com/000858-channel-2026",
                "document_type": "news_metadata",
                "authority_level": 2,
                "content": (
                    "公司渠道动销平稳，但 240 日相对表现读数偏弱，需关注行业竞争与成本。"
                    "高端化推进但有阻力，估值位置中等。"
                ),
            },
        ],
        "fact_cards": [
            {"fact_key": "operations.stable", "topic": "经营", "stance": "supporting",
             "claim": "2025 年营业总收入同比增长约 5.1%，净利润同比增长约 3.2%，经营质量尚可但增速放缓。",
             "confidence": 0.78, "authority_level": 4},
            {"fact_key": "horizon.soft", "topic": "估值", "stance": "contrary",
             "claim": "240 日相对表现读数偏弱，与经营质量尚可形成分歧，需关注行业竞争与成本。",
             "confidence": 0.62, "authority_level": 3},
            {"fact_key": "competition.risk", "topic": "风险", "stance": "contrary",
             "claim": "行业竞争加剧、消费场景修复不及预期、原材料成本波动构成主要风险。",
             "confidence": 0.66, "authority_level": 4},
        ],
        "line_items": _LINE_ITEMS["000858"],
    },
]


def seed_payload(*, generated_at: datetime) -> dict:
    return {
        "schema_version": "competition-knowledge-seed-v1",
        "data_tier": "research_demo",
        "validation_status": "research_demonstration_not_validated",
        "note": "比赛演示用知识库种子；公开形态摘要与研究展示事实卡，非验证数据；news 类仅 metadata_excerpt。",
        "generated_at": generated_at.isoformat(),
        "as_of": AS_OF,
        "companies": COMPANIES,
    }
