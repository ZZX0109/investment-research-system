#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "var/documents/tencent-2024/tencent-2024-annual-report.pdf"
GOLD = ROOT / "data/multimodal/tencent-2024-annual-report-gold.json"
OUTPUT = ROOT / "artifacts/document_evaluation.json"
IMAGE_ROOT = ROOT / "artifacts/multimodal"


def main() -> None:
    import fitz
    from PIL import Image, ImageDraw
    from investment_research.service.document_evaluation import FinancialDocumentEvaluator

    if not PDF.exists():
        raise SystemExit(f"Missing fixed official report: {PDF}")
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    import hashlib
    actual_hash = hashlib.sha256(PDF.read_bytes()).hexdigest()
    if actual_hash != gold["document_sha256"]:
        raise SystemExit("Tencent report SHA256 does not match gold annotation")
    result = FinancialDocumentEvaluator().evaluate_pdf(PDF, GOLD)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result.__dict__, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    document = fitz.open(PDF)
    for case in gold["cases"]:
        page = document[int(case["page"]) - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        draw = ImageDraw.Draw(image)
        scale = 1.5
        draw.rectangle(tuple(float(value) * scale for value in case["bbox"]), outline="#e11d48", width=4)
        image.save(IMAGE_ROOT / f"tencent-2024-page-{case['page']}-annotated.png")
    document.close()
    print(json.dumps({"verdict": result.verdict, "numeric_accuracy": result.numeric_accuracy, "cell_location_accuracy": result.cell_location_accuracy, "trend_accuracy": result.trend_accuracy, "citation_completeness": result.citation_completeness, "numeric_refusal_rate": result.numeric_refusal_rate}, ensure_ascii=False))


if __name__ == "__main__":
    main()
