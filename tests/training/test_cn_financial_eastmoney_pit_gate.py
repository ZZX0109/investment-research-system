from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from investment_research.service.object_store import LocalObjectStore


def _rebuild_module():
    project = Path(__file__).resolve().parents[2]
    path = project / "scripts/rebuild_cn_research_pit.py"
    spec = importlib.util.spec_from_file_location("rebuild_cn_research_pit_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eastmoney_statement_rows_require_explicit_research_visibility(tmp_path: Path) -> None:
    module = _rebuild_module()
    payload = json.dumps([
        {
            "code": "sh.600000",
            "statDate": "2024-12-31",
            "pubDate": "2025-03-28",
            "feature_family": "profit",
            "epsTTM": 1.2,
        }
    ], separators=(",", ":")).encode()
    store = LocalObjectStore(tmp_path / "raw")
    reference = store.put("eastmoney/600000.json", payload, content_type="application/json")
    batch = SimpleNamespace(
        id="eastmoney-fixture",
        dataset="cn_financial_eastmoney_research",
        symbol="600000",
        payload_ref=reference,
        payload_hash=sha256(payload).hexdigest(),
        fetched_at=datetime(2025, 3, 29, tzinfo=timezone.utc),
        available_at=datetime(2025, 3, 29, tzinfo=timezone.utc),
    )
    bars = {
        "600000": [
            SimpleNamespace(
                trade_date=date(2025, 4, 1),
                published_at=datetime(2025, 4, 1, 8, tzinfo=timezone.utc),
            )
        ]
    }

    assert module._load_financial_features(store, [batch], bars) == {}
    admitted = module._load_financial_features(
        store, [batch], bars, allow_unproven_available_at=True
    )
    assert admitted["600000"][date(2025, 4, 1)]["fundamental_eps_ttm"] == 1.2
