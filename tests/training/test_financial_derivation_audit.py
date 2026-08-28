from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts/derive_cn_financial_ratios_from_landing.py"
    spec = importlib.util.spec_from_file_location("financial_derivation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_derivation_audit_distinguishes_available_and_missing_inputs() -> None:
    module = _module()
    index = {
        "performance": {},
        "income": {},
        "cashflow": {},
        "balance": {
            ("000001", "2024-12-31"): {"metrics": {
                "MONETARYFUNDS": 100.0,
                "INVENTORY": 20.0,
            }},
            ("000002", "2024-12-31"): {"metrics": {
                "MONETARYFUNDS": 200.0,
                "INVENTORY": None,
            }},
        },
    }
    result = module._field_availability(index)
    assert result["MONETARYFUNDS"]["available_count"] == 2
    assert result["INVENTORY"]["available_count"] == 1
    assert result["CURRENT_ASSETS"]["available_count"] == 0
    assert result["CURRENT_LIABILITIES"]["coverage"] == 0.0
