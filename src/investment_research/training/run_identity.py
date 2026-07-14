from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


class TrainingRunIdentity(BaseModel):
    schema_version: str = "training-run-identity-v1"
    training_run_id: str
    created_at: datetime
    mode: str
    config_hash: str
    code_commit: str
    dependency_versions: dict[str, str]
    random_seeds: list[int]
    raw_data_hash: str | None = None
    sample_data_hash: str | None = None
    feature_contract_version: str
    label_policy_version: str
    status: str = "created"
    completed_steps: list[str] = Field(default_factory=list)
    failure_reason: str | None = None

    @classmethod
    def create(cls, *, mode: str, config_hash: str, random_seeds: list[int], feature_contract_version: str, label_policy_version: str) -> "TrainingRunIdentity":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return cls(
            training_run_id=f"{stamp}-{mode}-{uuid4().hex[:10]}",
            created_at=datetime.now(timezone.utc),
            mode=mode,
            config_hash=config_hash,
            code_commit=resolve_code_commit(),
            dependency_versions=dependency_versions(),
            random_seeds=random_seeds,
            feature_contract_version=feature_contract_version,
            label_policy_version=label_policy_version,
        )


def resolve_code_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unversioned-worktree"


def dependency_versions() -> dict[str, str]:
    names = ("pydantic", "numpy", "pandas", "scikit-learn", "joblib", "lightgbm", "xgboost", "torch")
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in paths if item.is_file()), key=lambda item: str(item)):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_identity(path: Path, identity: TrainingRunIdentity) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(identity.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
