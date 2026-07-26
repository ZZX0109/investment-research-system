"""Start the same-origin, public read-only Workbench service."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
SOURCE = str(ROOT / "src")
if SOURCE not in sys.path:
    sys.path.insert(0, SOURCE)


if __name__ == "__main__":
    uvicorn.run(
        "investment_research.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
