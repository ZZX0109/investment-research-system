from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError


class RunBundleFileStore:
    """Path-safe JSON/model access for persisted run bundles."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root.resolve()

    def read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def read_json_value(self, value: str | None, fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    def read_model_json(self, path: Path, model_class: type[Any]) -> Any:
        try:
            return TypeAdapter(model_class).validate_python(self.read_json(path))
        except ValidationError as exc:
            raise ValueError(f"Invalid structured JSON in {path}") from exc

    def safe_run_root(self, run_id: str) -> Path:
        candidate = (self.runs_root / run_id).resolve()
        try:
            candidate.relative_to(self.runs_root)
        except ValueError as exc:
            raise FileNotFoundError(f"Run path escaped runs root: {run_id}") from exc
        return candidate

    def resolve_run_path(self, run_id: str, candidate_path: str) -> Path:
        candidate = Path(candidate_path)
        if not candidate.is_absolute():
            candidate = self.safe_run_root(run_id) / candidate
        resolved = candidate.resolve()
        run_root = self.safe_run_root(run_id)
        if run_root != resolved and run_root not in resolved.parents:
            raise FileNotFoundError(f"Run file escaped run root: {candidate_path}")
        return resolved

    def safe_run_file(self, run_id: str, candidate_path: str) -> Path:
        resolved = self.resolve_run_path(run_id, candidate_path)
        if not resolved.is_file():
            raise FileNotFoundError(f"Run file not found for {run_id}: {candidate_path}")
        return resolved

    @staticmethod
    def parse_timestamp(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
