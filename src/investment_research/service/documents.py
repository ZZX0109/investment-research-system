from __future__ import annotations

import hashlib
import io
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from investment_research.domain.models import DocumentArtifact, User
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.advanced_research import _real_provenance
from investment_research.service.vision import VisionProvider, build_vision_provider
from investment_research.service.object_store import ObjectStore, build_object_store


MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_PAGES = 100
DEFAULT_SOURCE_ALLOWLIST = (
    "sec.gov",
    "cninfo.com.cn",
    "hkexnews.hk",
    "sse.com.cn",
    "szse.cn",
)


class DocumentService:
    def __init__(
        self,
        uow: SQLiteUnitOfWork,
        *,
        root: Path | None = None,
        vision_provider: VisionProvider | None = None,
        object_store: ObjectStore | None = None,
    ) -> None:
        self.uow = uow
        self.root = root or Path.cwd() / "var" / "documents"
        self.root.mkdir(parents=True, exist_ok=True)
        self.vision_provider = vision_provider or build_vision_provider()
        self.object_store = object_store or build_object_store()

    def create(
        self,
        *,
        user: User,
        filename: str,
        content_type: str,
        data: bytes,
        asset_id: str | None = None,
        source_url: str | None = None,
    ) -> DocumentArtifact:
        if content_type != "application/pdf" or not filename.lower().endswith(".pdf"):
            raise ValueError("Only PDF documents are accepted")
        if not data or len(data) > MAX_DOCUMENT_BYTES:
            raise ValueError("PDF is empty or exceeds 20 MB")
        self._validate_page_count(data)
        self._validate_source_url(source_url)
        sha = hashlib.sha256(data).hexdigest()
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
        object_key = f"documents/{sha}/{safe}"
        storage_path = self.object_store.put(object_key, data, content_type=content_type)
        work_path = self.root / f"{sha[:16]}-{safe}"
        work_path.write_bytes(data)
        artifact = DocumentArtifact(
            user_id=user.id,
            asset_id=None if asset_id is None else UUID(asset_id),
            filename=safe,
            content_type=content_type,
            storage_path=storage_path,
            source_url=source_url,
            sha256=sha,
            provenance=_real_provenance("document-upload"),
        )
        artifact = self._parse(artifact, data, work_path=work_path)
        return self.uow.document_artifacts.add(artifact)

    def get_for_user(self, document_id: str, *, user: User) -> DocumentArtifact | None:
        item = self.uow.document_artifacts.get(document_id)
        return item if item and item.user_id == user.id else None

    def list_for_user(self, *, user: User) -> list[DocumentArtifact]:
        return self.uow.document_artifacts.list_for_user(str(user.id))

    def _parse(self, artifact: DocumentArtifact, data: bytes, *, work_path: Path) -> DocumentArtifact:
        text = []
        tables = []
        figures = []
        failures = []
        page_count = 0
        try:
            import fitz

            document = fitz.open(stream=data, filetype="pdf")
            page_count = len(document)
            if page_count > MAX_DOCUMENT_PAGES:
                raise ValueError("PDF exceeds 100 pages")
            figure_root = work_path.with_suffix("")
            figure_root.mkdir(parents=True, exist_ok=True)
            for index, page in enumerate(document):
                page_text = page.get_text("text").strip()
                if not page_text:
                    try:
                        import pytesseract
                        from PIL import Image

                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        page_text = pytesseract.image_to_string(
                            Image.open(io.BytesIO(pix.tobytes("png")))
                        ).strip()
                    except Exception as exc:
                        failures.append(f"ocr-page-{index + 1}:{exc}")
                if page_text:
                    text.append(f"[page {index + 1}] {page_text}")
                for image_index, image in enumerate(page.get_images(full=True)[:8]):
                    try:
                        extracted = document.extract_image(image[0])
                        image_data = extracted["image"]
                        image_hash = hashlib.sha256(image_data).hexdigest()
                        image_path = (
                            figure_root
                            / f"page-{index + 1}-figure-{image_index + 1}.{extracted.get('ext', 'png')}"
                        )
                        image_path.write_bytes(image_data)
                        figure_key = f"documents/{artifact.sha256}/figures/{image_path.name}"
                        figure_object = self.object_store.put(
                            figure_key,
                            image_data,
                            content_type=f"image/{extracted.get('ext', 'png')}",
                        )
                        visual = self.vision_provider.inspect(image_path)
                        figures.append(
                            {
                                "page": index + 1,
                                "index": image_index,
                                "xref": image[0],
                                "object_key": figure_object,
                                "sha256": image_hash,
                                "status": "model_interpretation"
                                if visual
                                else "needs_visual_review",
                                "visual_analysis": visual,
                            }
                        )
                    except Exception as exc:
                        failures.append(
                            f"figure-page-{index + 1}-{image_index + 1}:{exc}"
                        )
            document.close()
        except Exception as exc:
            failures.append(f"pymupdf:{exc}")
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                page_count = page_count or len(pdf.pages)
                for page_index, page in enumerate(pdf.pages):
                    for table_index, table in enumerate(page.find_tables() or []):
                        rows = table.extract() or []
                        tables.append(
                            {
                                "page": page_index + 1,
                                "index": table_index,
                                "bbox": list(table.bbox),
                                "cells": [list(cell) for cell in table.cells],
                                "rows": rows[:100],
                                "row_count": len(rows),
                            }
                        )
        except Exception as exc:
            failures.append(f"pdfplumber:{exc}")
        status = (
            "parsed"
            if text or tables
            else "needs_visual_review"
            if figures
            else "failed"
        )
        return artifact.model_copy(
            update={
                "page_count": page_count,
                "parse_status": status,
                "text_summary": "\n".join(text)[:6000] or None,
                "tables": tables,
                "figures": figures,
                "failure_reasons": failures,
            }
        )

    def _validate_page_count(self, data: bytes) -> None:
        try:
            import fitz

            document = fitz.open(stream=data, filetype="pdf")
            count = len(document)
            document.close()
        except Exception as exc:
            raise ValueError(f"Invalid PDF: {exc}") from exc
        if count > MAX_DOCUMENT_PAGES:
            raise ValueError("PDF exceeds 100 pages")

    def _validate_source_url(self, source_url: str | None) -> None:
        if not source_url:
            return
        parsed = urlparse(source_url)
        host = (parsed.hostname or "").lower()
        allowed = tuple(
            item.strip().lower()
            for item in os.getenv(
                "WORKBUDDY_DOCUMENT_SOURCE_ALLOWLIST",
                ",".join(DEFAULT_SOURCE_ALLOWLIST),
            ).split(",")
            if item.strip()
        )
        if (
            parsed.scheme != "https"
            or not host
            or not any(
                host == domain or host.endswith(f".{domain}") for domain in allowed
            )
        ):
            raise ValueError("Document source URL is not allowlisted")
