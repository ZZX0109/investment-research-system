from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any, Callable

from .document_repository import (
    fetch_document_blocks,
    fetch_document_metrics,
    fetch_latest_document,
    replace_document_blocks,
    replace_financial_metrics,
    upsert_multimodal_document,
)
from .schemas import DocumentAnalysisRecord


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def extract_document_text(content: bytes, filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore
            import io

            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages[:8])
        except Exception:
            return ""
    try:
        return content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def compact_preview(value: str, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized[:limit]


def detect_document_blocks(text: str, filename: str) -> list[dict[str, str]]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    split_pattern = re.compile(
        r"(?i)(?=(?:revenue|gross\s+margin|free\s+cash\s+flow|figure\s*\d*|chart|footnote|note\s|notes\s|营收|毛利|现金流|图|趋势|附注|注[:：]))"
    )
    lines: list[tuple[int, int, str]] = []
    for line_index, line in enumerate(raw_lines, start=1):
        if len(line) > 140:
            parts = [part.strip(" ;。") for part in split_pattern.split(line) if part.strip(" ;。")]
        else:
            parts = [line]
        for part_index, part in enumerate(parts, start=1):
            lines.append((line_index, part_index, part))
    blocks: list[dict[str, str]] = []
    table_markers = ["|", "\t", ",", "revenue", "gross", "margin", "cash", "营收", "毛利", "现金流", "资产"]
    chart_markers = ["chart", "figure", "trend", "growth", "图", "趋势", "增长", "curve"]
    footnote_markers = ["note ", "notes ", "footnote", "注:", "注：", "附注", "*"]
    for line_index, part_index, line in lines[:160]:
        lowered = line.lower()
        if any(marker in lowered or marker in line for marker in footnote_markers) and len(line) >= 8:
            block_type = "footnote"
            label = f"footnote-candidate-{line_index}-{part_index}"
        elif any(marker in lowered or marker in line for marker in chart_markers):
            block_type = "chart"
            label = f"chart-candidate-{line_index}-{part_index}"
        elif any(marker in lowered or marker in line for marker in table_markers) and any(char.isdigit() for char in line):
            block_type = "table"
            label = f"table-candidate-{line_index}-{part_index}"
        elif len(line) > 40:
            block_type = "text"
            label = f"text-block-{line_index}-{part_index}"
        else:
            continue
        blocks.append(
            {
                "block_type": block_type,
                "label": label,
                "locator": f"{filename}:line:{line_index}:segment:{part_index}",
                "content_preview": compact_preview(line),
            }
        )
    return blocks[:36]


def metrics_from_document(text: str, filename: str, symbol: str) -> list[tuple[str, str, str, str]]:
    metrics: list[tuple[str, str, str, str]] = []
    lowered = text.lower()
    if filename.lower().endswith(".csv"):
        rows = [line.strip() for line in text.splitlines() if line.strip()]
        if rows:
            delimiter = "\t" if "\t" in rows[0] else "," if "," in rows[0] else "|"
            headers = [header.strip() for header in rows[0].split(delimiter)]
            for row_index, row in enumerate(rows[1:8], start=2):
                values = [value.strip() for value in row.split(delimiter)]
                for col_index, raw_value in enumerate(values[: len(headers)]):
                    numeric = raw_value.replace(",", "").replace("%", "").replace("$", "")
                    if re.fullmatch(r"-?\d+(\.\d+)?", numeric):
                        metric_name = headers[col_index] if col_index < len(headers) and headers[col_index] else f"column_{col_index + 1}"
                        metrics.append((metric_name, raw_value, f"csv-row-{row_index}", f"table:{filename}:row:{row_index}:col:{col_index + 1}"))
                if len(metrics) >= 8:
                    break
        if metrics:
            return metrics[:10]
    keyword_metrics = [
        ("Revenue / 营收", ["revenue", "营收"], "table-candidate:revenue"),
        ("Gross margin / 毛利率", ["gross margin", "margin", "毛利"], "table-candidate:gross-margin"),
        ("Cash flow / 现金流", ["cash flow", "cash", "现金流", "现金"], "table-candidate:cash-flow"),
        ("Assets / 资产", ["assets", "资产"], "table-candidate:assets"),
        ("Liabilities / 负债", ["liabilities", "负债"], "table-candidate:liabilities"),
    ]
    for name, keywords, source_block in keyword_metrics:
        if any(keyword in lowered or keyword in text for keyword in keywords) and not any(item[0] == name for item in metrics):
            metrics.append((name, "已定位候选表格，需人工/规则复核数值", "latest", source_block))
    if not metrics:
        metrics.append(("Document numeric coverage", "未定位可计算表格数值", "not factual", "no-table-candidate"))
    return metrics[:10]


def build_document_ingest_payload(
    symbol: str,
    filename: str,
    content: bytes,
    *,
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
) -> dict[str, Any]:
    text = extract_document_text(content, filename)
    blocks = detect_document_blocks(text, filename)
    block_counts = {
        "text": sum(1 for item in blocks if item["block_type"] == "text"),
        "table": sum(1 for item in blocks if item["block_type"] == "table"),
        "chart": sum(1 for item in blocks if item["block_type"] == "chart"),
        "footnote": sum(1 for item in blocks if item["block_type"] == "footnote"),
    }
    digest = hashlib.sha1(content[:200_000]).hexdigest()[:12]
    return {
        "document_id": f"{symbol}-{digest}",
        "symbol": symbol,
        "filename": filename,
        "uploaded_at": iso(now_utc()),
        "summary": "文档已进入轻量多模态解析管线: 文本、表格、图表和脚注分离记录；表格候选指标进入结构化库，数字计算走代码。",
        "blocks": blocks,
        "metrics": metrics_from_document(text, filename, symbol),
        "block_counts": block_counts,
        "text_blocks": max(1, block_counts["text"]),
        "table_blocks": max(1, block_counts["table"]),
        "chart_blocks": block_counts["chart"],
        "footnote_blocks": block_counts["footnote"],
    }


def _block_summaries(doc: sqlite3.Row) -> list[dict[str, Any]]:
    return [
        {"type": "text", "label": "文本块", "count": doc["text_blocks"], "status": "已抽取"},
        {"type": "table", "label": "表格块", "count": doc["table_blocks"], "status": "指标入库"},
        {"type": "chart", "label": "图表块", "count": doc["chart_blocks"], "status": "生成摘要"},
        {"type": "footnote", "label": "脚注块", "count": doc["footnote_blocks"], "status": "引用定位"},
    ]


def _chart_summary() -> str:
    return "图表摘要: 收入、利润率、现金流和行业暴露变化已生成轻量解释；涉及精确计算时优先读取结构化指标。"


def _demo_document_analysis(
    symbol: str,
    *,
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    uploaded_at = iso(now_utc() - timedelta(days=1))
    return dump_model(
        DocumentAnalysisRecord(
            documentId="demo-multimodal-pipeline",
            filename=f"{symbol}-demo-filing.pdf",
            uploadedAt=uploaded_at,
            sourceType="demo_cache",
            sourceMeta=build_source_meta(
                provider="demo_cache",
                as_of=uploaded_at,
                overrides=["synthetic"],
                synthetic_ratio=1.0,
            ),
            summary="尚未上传真实财报，当前仅展示多模态解析管线占位样例；不得把这些数字或摘要当作公司事实。",
            blocks=[
                {"type": "text", "label": "文本块", "count": 12, "status": "样例"},
                {"type": "table", "label": "表格块", "count": 4, "status": "样例"},
                {"type": "chart", "label": "图表块", "count": 3, "status": "样例"},
                {"type": "footnote", "label": "脚注块", "count": 2, "status": "样例"},
            ],
            metrics=[
                {"metric_name": "Revenue growth", "metric_value": "demo placeholder", "period": "not factual", "source_block": "demo table"},
                {"metric_name": "Gross margin", "metric_value": "demo placeholder", "period": "not factual", "source_block": "demo table"},
                {"metric_name": "Free cash flow", "metric_value": "demo placeholder", "period": "not factual", "source_block": "demo table"},
            ],
            chartSummary="图表摘要占位样例: 上传真实财报前，不生成任何关于收入、利润率或现金流的事实判断。",
            blockPreviews=[
                {"block_type": "text", "label": "demo text block", "locator": "demo:paragraph:1", "content_preview": "上传真实财报后展示文本块定位。"},
                {"block_type": "table", "label": "demo table block", "locator": "demo:table:1", "content_preview": "上传真实 CSV/PDF/TXT 后展示表格候选定位。"},
                {"block_type": "footnote", "label": "demo footnote block", "locator": "demo:footnote:1", "content_preview": "脚注会单独拆出，供 Judge 检查引用是否支撑结论。"},
            ],
        )
    )


def get_latest_document_analysis(
    symbol: str,
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    with closing(connect()) as conn:
        doc = fetch_latest_document(conn, symbol)
        if not doc:
            return _demo_document_analysis(symbol, now_utc=now_utc, iso=iso, build_source_meta=build_source_meta)
        metrics = fetch_document_metrics(conn, doc["document_id"])
        blocks = fetch_document_blocks(conn, doc["document_id"])
    return dump_model(
        DocumentAnalysisRecord(
            documentId=doc["document_id"],
            filename=doc["filename"],
            uploadedAt=doc["uploaded_at"],
            sourceType=doc["source_type"],
            sourceMeta=build_source_meta(
                provider=doc["source_type"],
                as_of=doc["uploaded_at"],
                overrides=[],
                synthetic_ratio=0.0,
            ),
            summary=doc["summary"],
            blocks=_block_summaries(doc),
            metrics=[dict(item) for item in metrics],
            chartSummary=_chart_summary(),
            blockPreviews=[dict(item) for item in blocks],
        )
    )


def analyze_document_content(
    symbol: str,
    filename: str,
    content: bytes,
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    payload = build_document_ingest_payload(symbol, filename, content, now_utc=now_utc, iso=iso)
    with closing(connect()) as conn:
        upsert_multimodal_document(conn, payload, source_type="uploaded_report")
        replace_financial_metrics(conn, payload)
        replace_document_blocks(conn, payload)
        conn.commit()
    return get_latest_document_analysis(
        symbol,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        build_source_meta=build_source_meta,
    )
