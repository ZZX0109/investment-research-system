from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


class ArtifactIntegrityError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact_set(model_dir: Path, manifest: dict[str, Any]) -> None:
    hashes = manifest.get("artifact_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ArtifactIntegrityError("Deployment manifest has no artifact hashes")
    for relative_name, expected in sorted(hashes.items()):
        path = model_dir / str(relative_name)
        if not path.is_file():
            raise ArtifactIntegrityError(f"Required artifact is missing: {relative_name}")
        actual = sha256_file(path)
        if actual != str(expected):
            raise ArtifactIntegrityError(
                f"Artifact hash mismatch for {relative_name}"
            )
