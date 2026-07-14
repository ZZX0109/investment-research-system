from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen


class VisionProvider(Protocol):
    name: str

    def inspect(self, image_path: Path) -> dict[str, object] | None: ...


class DisabledVisionProvider:
    name = "disabled"

    def inspect(self, image_path: Path) -> dict[str, object] | None:
        del image_path
        return None


class HttpVisionProvider:
    def __init__(
        self,
        *,
        name: str,
        endpoint: str,
        model: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.name = name
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    def inspect(self, image_path: Path) -> dict[str, object] | None:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = "Describe the chart structure, axes, legend, and visible trends. Do not invent unreadable numbers."
        payload = {"prompt": prompt, "image_base64": encoded, "model": self.model}
        if self.name == "ollama":
            payload = {
                "model": self.model or "llava",
                "prompt": prompt,
                "images": [encoded],
                "stream": False,
            }
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - endpoint is explicit operator config
            body = json.loads(response.read().decode("utf-8"))
        analysis = (
            body.get("response") if self.name == "ollama" else body.get("analysis")
        )
        if not analysis:
            return None
        return {
            "provider": self.name,
            "model": self.model,
            "analysis": str(analysis),
            "confidence": float(body.get("confidence", 0.5)),
            "is_model_inferred": True,
            "numeric_claims_trusted": False,
        }


def build_vision_provider() -> VisionProvider:
    mode = os.getenv("WORKBUDDY_VISION_PROVIDER", "disabled").strip().lower()
    if mode == "ollama":
        return HttpVisionProvider(
            name="ollama",
            endpoint=os.getenv(
                "WORKBUDDY_OLLAMA_VISION_ENDPOINT",
                "http://127.0.0.1:11434/api/generate",
            ),
            model=os.getenv("WORKBUDDY_OLLAMA_VISION_MODEL", "llava"),
        )
    if mode == "generic_http":
        endpoint = os.getenv("WORKBUDDY_VISION_ENDPOINT")
        if endpoint:
            return HttpVisionProvider(
                name="generic_http",
                endpoint=endpoint,
                model=os.getenv("WORKBUDDY_VISION_MODEL"),
            )
    return DisabledVisionProvider()
