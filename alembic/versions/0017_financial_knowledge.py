"""Add point-in-time financial knowledge catalog."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0017_financial_knowledge"
down_revision = "0016_research_data_qualification"
branch_labels = None
depends_on = None


SEED_DOCUMENTS = (
    (
        "A股公开披露来源",
        "上市公司公告应优先从交易所和法定信息披露平台获取。公告发布时间与事件发生时间必须分别保存，研究只能使用决策时点前已公开的信息。",
        "巨潮资讯网",
        "https://www.cninfo.com.cn/",
        "disclosure_rule",
    ),
    (
        "A股研究结果解释边界",
        "方向概率、收益区间和回撤风险是研究结果，不是买入、卖出或保证收益的指令。数据缺失、模型分歧或输入漂移时应降低可信度或拒绝结论。",
        "A股量化研究平台",
        "https://www.sse.com.cn/",
        "platform_policy",
    ),
    (
        "交易所公告与上市状态",
        "上市、终止上市、停牌和公司公告属于证券状态与事件证据。历史研究必须按照当时已公开的状态解释，不得用当前状态覆盖历史样本。",
        "深圳证券交易所",
        "https://www.szse.cn/disclosure/notice/company/index.html",
        "market_rule",
    ),
    (
        "监管规则来源",
        "证券市场监管规则、行政处罚和监管措施应优先引用中国证监会及交易所公开文件，并记录生效日期、修订版本和来源链接。",
        "中国证监会",
        "https://www.csrc.gov.cn/",
        "regulation",
    ),
)


def upgrade() -> None:
    table = op.create_table(
        "financial_knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("document_type", sa.String(48), nullable=False),
        sa.Column("published_at", sa.String(48), nullable=False),
        sa.Column("available_at", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.UniqueConstraint("content_hash", name="uq_financial_knowledge_content_hash"),
    )
    op.create_index("ix_financial_knowledge_scope", "financial_knowledge_documents", ["market", "symbol", "available_at"])
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    rows = []
    for title, content, source, url, document_type in SEED_DOCUMENTS:
        content_hash = hashlib.sha256(f"{title}|{content}|{url}".encode()).hexdigest()
        payload = {
            "id": str(uuid4()), "title": title, "content": content,
            "source_name": source, "source_url": url, "market": "CN", "symbol": None,
            "document_type": document_type, "published_at": now.isoformat(),
            "effective_from": now.isoformat(), "effective_to": None,
            "collected_at": now.isoformat(), "available_at": now.isoformat(),
            "revision": 1, "content_hash": content_hash, "data_tier": "research_pit", "status": "active",
        }
        rows.append({
            "id": payload["id"], "market": "CN", "symbol": None,
            "document_type": document_type, "published_at": now.isoformat(),
            "available_at": now.isoformat(), "status": "active",
            "content_hash": content_hash,
            "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        })
    op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_index("ix_financial_knowledge_scope", table_name="financial_knowledge_documents")
    op.drop_table("financial_knowledge_documents")
