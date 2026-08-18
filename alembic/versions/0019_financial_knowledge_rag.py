"""Add revisioned, chunked and auditable financial knowledge retrieval."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision = "0019_financial_knowledge_rag"
down_revision = "0018_workbuddy_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("financial_knowledge_documents", sa.Column("owner_user_id", sa.String(36), nullable=True))
    op.add_column("financial_knowledge_documents", sa.Column("access_scope", sa.String(16), nullable=False, server_default="public"))
    op.add_column("financial_knowledge_documents", sa.Column("source_name", sa.String(160), nullable=True))
    op.add_column("financial_knowledge_documents", sa.Column("first_observed_at", sa.String(48), nullable=True))
    op.create_index("ix_financial_knowledge_access", "financial_knowledge_documents", ["access_scope", "owner_user_id"])
    op.create_table(
        "financial_knowledge_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("base_url", sa.String(2000), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("authority_level", sa.Integer, nullable=False),
        sa.Column("content_policy", sa.String(32), nullable=False),
        sa.Column("update_frequency", sa.String(24), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_table(
        "knowledge_fetch_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.String(48), nullable=False),
        sa.Column("finished_at", sa.String(48), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["financial_knowledge_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_knowledge_fetch_provider_time", "knowledge_fetch_runs", ["provider", "started_at"])
    op.create_table(
        "knowledge_document_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("previous_revision_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("available_at", sa.String(48), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload_ref", sa.String(2000), nullable=True),
        sa.Column("raw_payload_hash", sa.String(64), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["financial_knowledge_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "revision", name="uq_knowledge_document_revision"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("section", sa.String(300), nullable=True),
        sa.Column("page_start", sa.Integer, nullable=True),
        sa.Column("page_end", sa.Integer, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=True),
        sa.Column("access_scope", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["financial_knowledge_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "revision", "chunk_index", name="uq_knowledge_chunk_position"),
    )
    op.create_index("ix_knowledge_chunks_document", "knowledge_chunks", ["document_id", "revision"])
    op.create_index("ix_knowledge_chunks_owner", "knowledge_chunks", ["owner_user_id", "access_scope"])
    op.create_table(
        "knowledge_embeddings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("model_revision", sa.String(80), nullable=False),
        sa.Column("dimension", sa.Integer, nullable=False),
        sa.Column("vector_hash", sa.String(64), nullable=False),
        sa.Column("shard_key", sa.String(160), nullable=False),
        sa.Column("vector_blob", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("chunk_id", "model_name", "model_revision", name="uq_knowledge_chunk_embedding"),
    )
    op.create_table(
        "knowledge_coverage_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=True),
        sa.Column("dataset", sa.String(80), nullable=False),
        sa.Column("metadata_status", sa.String(24), nullable=False),
        sa.Column("full_text_status", sa.String(24), nullable=False),
        sa.Column("checked_at", sa.String(48), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_knowledge_coverage_scope", "knowledge_coverage_ledger", ["market", "symbol", "dataset", "checked_at"])
    op.create_table(
        "knowledge_retrieval_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.String(36), nullable=True),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("as_of", sa.String(48), nullable=False),
        sa.Column("retrieval_mode", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
    )
    op.create_index("ix_knowledge_retrieval_owner_time", "knowledge_retrieval_snapshots", ["owner_user_id", "created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5("
            "chunk_id UNINDEXED, document_id UNINDEXED, title, symbol, section, content, tokenize='unicode61')"
        ))
    _seed_sources(bind)
    _backfill_existing_documents(bind)


def _seed_sources(bind) -> None:
    sources = (
        ("cninfo", "巨潮资讯网", "https://www.cninfo.com.cn/", 5, "full_text", "daily"),
        ("sse", "上海证券交易所", "https://www.sse.com.cn/", 5, "full_text", "daily"),
        ("szse", "深圳证券交易所", "https://www.szse.cn/", 5, "full_text", "daily"),
        ("bse", "北京证券交易所", "https://www.bse.cn/", 5, "full_text", "daily"),
        ("csrc", "中国证券监督管理委员会", "https://www.csrc.gov.cn/", 5, "full_text", "weekly"),
        ("pbc", "中国人民银行", "https://www.pbc.gov.cn/", 5, "full_text", "weekly"),
        ("stats", "国家统计局", "https://www.stats.gov.cn/", 5, "full_text", "monthly"),
        ("mof", "中华人民共和国财政部", "https://www.mof.gov.cn/", 5, "full_text", "weekly"),
    )
    table = sa.table(
        "financial_knowledge_sources",
        sa.column("id"), sa.column("provider"), sa.column("name"), sa.column("base_url"),
        sa.column("source_kind"), sa.column("authority_level"), sa.column("content_policy"),
        sa.column("update_frequency"), sa.column("enabled"), sa.column("payload_json"),
    )
    rows = []
    for provider, name, url, authority, policy, frequency in sources:
        payload = {
            "id": str(uuid4()), "provider": provider, "name": name, "base_url": url,
            "source_kind": "official_public", "authority_level": authority,
            "content_policy": policy, "update_frequency": frequency, "enabled": True,
        }
        rows.append({**payload, "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))})
    bind.execute(sa.insert(table), rows)


def _backfill_existing_documents(bind) -> None:
    rows = bind.execute(sa.text(
        "SELECT id,content_hash,payload_json FROM financial_knowledge_documents"
    )).fetchall()
    revision_table = sa.table(
        "knowledge_document_revisions", sa.column("id"), sa.column("document_id"),
        sa.column("previous_revision_id"), sa.column("revision"), sa.column("available_at"),
        sa.column("content_hash"), sa.column("raw_payload_ref"), sa.column("raw_payload_hash"),
        sa.column("payload_json"),
    )
    chunk_table = sa.table(
        "knowledge_chunks", sa.column("id"), sa.column("document_id"), sa.column("revision"),
        sa.column("chunk_index"), sa.column("content"), sa.column("section"), sa.column("page_start"),
        sa.column("page_end"), sa.column("content_hash"), sa.column("owner_user_id"),
        sa.column("access_scope"), sa.column("payload_json"),
    )
    for row in rows:
        payload = json.loads(row[2])
        document_id = str(row[0])
        available_at = str(payload.get("available_at") or datetime.now(timezone.utc).isoformat())
        source_name = str(payload.get("source_name") or "平台研究说明")
        first_observed_at = str(payload.get("first_observed_at") or payload.get("collected_at") or available_at)
        bind.execute(sa.text(
            "UPDATE financial_knowledge_documents SET source_name=:source_name,first_observed_at=:first_observed_at "
            "WHERE id=:document_id"
        ), {"source_name": source_name, "first_observed_at": first_observed_at, "document_id": document_id})
        revision_id = str(uuid4())
        bind.execute(sa.insert(revision_table), [{
            "id": revision_id, "document_id": document_id, "previous_revision_id": None,
            "revision": int(payload.get("revision", 1)), "available_at": available_at,
            "content_hash": str(row[1]), "raw_payload_ref": payload.get("raw_payload_ref"),
            "raw_payload_hash": payload.get("raw_payload_hash"), "payload_json": json.dumps(payload, ensure_ascii=False),
        }])
        content = str(payload.get("content") or "")
        chunk_hash = hashlib.sha256(content.encode()).hexdigest()
        chunk_id = str(uuid4())
        chunk_payload = {
            "id": chunk_id, "document_id": document_id, "revision": int(payload.get("revision", 1)),
            "chunk_index": 0, "content": content, "section": payload.get("title"),
            "page_start": None, "page_end": None, "token_estimate": max(1, len(content) // 2),
            "content_hash": chunk_hash, "owner_user_id": payload.get("owner_user_id"),
            "access_scope": payload.get("access_scope", "public"),
        }
        bind.execute(sa.insert(chunk_table), [{**chunk_payload, "payload_json": json.dumps(chunk_payload, ensure_ascii=False)}])
        if bind.dialect.name == "sqlite":
            bind.execute(sa.text(
                "INSERT INTO knowledge_chunks_fts(chunk_id,document_id,title,symbol,section,content) "
                "VALUES (:chunk_id,:document_id,:title,:symbol,:section,:content)"
            ), {"chunk_id": chunk_id, "document_id": document_id, "title": payload.get("title", ""),
                "symbol": payload.get("symbol") or "", "section": payload.get("title", ""), "content": content})


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text("DROP TABLE IF EXISTS knowledge_chunks_fts"))
    op.drop_index("ix_knowledge_retrieval_owner_time", table_name="knowledge_retrieval_snapshots")
    op.drop_table("knowledge_retrieval_snapshots")
    op.drop_index("ix_knowledge_coverage_scope", table_name="knowledge_coverage_ledger")
    op.drop_table("knowledge_coverage_ledger")
    op.drop_table("knowledge_embeddings")
    op.drop_index("ix_knowledge_chunks_owner", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_revisions")
    op.drop_index("ix_knowledge_fetch_provider_time", table_name="knowledge_fetch_runs")
    op.drop_table("knowledge_fetch_runs")
    op.drop_table("financial_knowledge_sources")
    op.drop_index("ix_financial_knowledge_access", table_name="financial_knowledge_documents")
    op.drop_column("financial_knowledge_documents", "first_observed_at")
    op.drop_column("financial_knowledge_documents", "source_name")
    op.drop_column("financial_knowledge_documents", "access_scope")
    op.drop_column("financial_knowledge_documents", "owner_user_id")
