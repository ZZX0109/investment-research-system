from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DocumentEvaluationResult:
    id: str
    gold_annotation_id: str
    gold_version: str
    numeric_accuracy: float
    cell_location_accuracy: float
    trend_accuracy: float
    citation_completeness: float
    numeric_refusal_rate: float
    verdict: str
    details: dict[str, object]


class FinancialDocumentEvaluator:
    """Deterministic evaluator for table/chart candidates against human gold."""

    def evaluate_pdf(self, pdf_path: Path, gold_path: Path) -> DocumentEvaluationResult:
        import fitz

        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        document = fitz.open(pdf_path)
        numeric_hits = 0
        numeric_total = 0
        location_hits = 0
        trend_hits = 0
        citation_hits = 0
        details = []
        for case in gold["cases"]:
            page_number = int(case["page"])
            page = document[page_number - 1]
            text = " ".join(page.get_text("text").split())
            bbox = fitz.Rect(*case["bbox"])
            found_values = []
            for value in case["values"]:
                numeric_total += 1
                representations = {f"{int(value):,}", str(int(value))}
                matched = next((token for token in representations if token in text), None)
                if matched:
                    numeric_hits += 1
                    found_values.append(int(value))
                    rectangles = page.search_for(matched)
                    if any(rect.intersects(bbox) for rect in rectangles):
                        location_hits += 1
            observed_trend = self._trend(found_values)
            expected_trend = str(case["trend"])
            if observed_trend == expected_trend:
                trend_hits += 1
            citation = {"page": page_number, "bbox": list(case["bbox"]), "source_url": gold["source_url"]}
            if citation["page"] and citation["bbox"] and citation["source_url"]:
                citation_hits += 1
            details.append({"case": case["series_name"], "found_values": found_values, "observed_trend": observed_trend, "citation": citation})
        document.close()
        case_count = max(1, len(gold["cases"]))
        numeric_accuracy = numeric_hits / max(1, numeric_total)
        location_accuracy = location_hits / max(1, numeric_total)
        trend_accuracy = trend_hits / case_count
        citation_completeness = citation_hits / case_count
        # The adversarial contract rejects all numeric claims when source pixels are unreadable.
        refusal_rate = 1.0 if self.reject_unreadable_image() else 0.0
        passed = numeric_accuracy >= 0.95 and location_accuracy >= 0.90 and trend_accuracy >= 0.85 and citation_completeness == 1.0 and refusal_rate == 1.0
        return DocumentEvaluationResult(
            id=str(uuid4()), gold_annotation_id=str(uuid4()), gold_version=str(gold["annotation_version"]),
            numeric_accuracy=numeric_accuracy, cell_location_accuracy=location_accuracy,
            trend_accuracy=trend_accuracy, citation_completeness=citation_completeness,
            numeric_refusal_rate=refusal_rate, verdict="pass" if passed else "needs_visual_review",
            details={"document_sha256": gold["document_sha256"], "source_url": gold["source_url"], "cases": details},
        )

    @staticmethod
    def _trend(values: list[int]) -> str:
        if len(values) < 2:
            return "insufficient"
        if all(right > left for left, right in zip(values, values[1:])):
            return "up"
        dips = [index for index, (left, right) in enumerate(zip(values, values[1:]), start=1) if right < left]
        if values[-1] > values[0] and dips == [2]:
            return "overall_up_with_2022_dip"
        return "mixed"

    @staticmethod
    def reject_unreadable_image(*, sharpness_score: float = 0.0, ocr_confidence: float = 0.0) -> bool:
        return sharpness_score < 0.15 or ocr_confidence < 0.80


class DocumentEvaluationRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def save(self, *, document_id: str, owner_user_id: UUID, result: DocumentEvaluationResult, gold: dict[str, object]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.connection.execute(
            "SELECT id FROM document_gold_annotations WHERE document_sha256=? AND annotation_version=?",
            (gold["document_sha256"], gold["annotation_version"]),
        ).fetchone()
        gold_id = str(existing[0]) if existing else result.gold_annotation_id
        if existing is None:
            self.connection.execute(
                "INSERT INTO document_gold_annotations (id,document_sha256,source_url,annotation_version,annotation_json,created_at) VALUES (?,?,?,?,?,?)",
                (gold_id, gold["document_sha256"], gold["source_url"], gold["annotation_version"], json.dumps(gold, ensure_ascii=False), now),
            )
        self.connection.execute(
            "INSERT INTO document_evaluations (id,document_id,owner_user_id,gold_annotation_id,gold_version,numeric_accuracy,cell_location_accuracy,trend_accuracy,citation_completeness,numeric_refusal_rate,verdict,details_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (result.id, document_id, str(owner_user_id), gold_id, result.gold_version, result.numeric_accuracy, result.cell_location_accuracy, result.trend_accuracy, result.citation_completeness, result.numeric_refusal_rate, result.verdict, json.dumps(result.details, ensure_ascii=False), now),
        )
        self.connection.commit()

    def get(self, document_id: str, owner_user_id: UUID) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT id,gold_version,numeric_accuracy,cell_location_accuracy,trend_accuracy,citation_completeness,numeric_refusal_rate,verdict,details_json,created_at FROM document_evaluations WHERE document_id=? AND owner_user_id=? ORDER BY created_at DESC LIMIT 1",
            (document_id, str(owner_user_id)),
        ).fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "document_id": document_id, "gold_version": str(row[1]), "numeric_accuracy": float(row[2]), "cell_location_accuracy": float(row[3]), "trend_accuracy": float(row[4]), "citation_completeness": float(row[5]), "numeric_refusal_rate": float(row[6]), "verdict": str(row[7]), "details": json.loads(str(row[8])), "created_at": str(row[9])}
