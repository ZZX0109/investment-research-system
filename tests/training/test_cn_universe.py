from __future__ import annotations

import json
from pathlib import Path

import pytest

from investment_research.service.cn_universe import ETF_SYMBOLS, load_cn_symbols, normalize_cn_symbols


def test_normalize_cn_symbols_accepts_exchange_codes_and_excludes_etfs() -> None:
    assert normalize_cn_symbols(["sh.600519", {"code": "000001"}, "510300"], exclude_etf=True) == ["000001", "600519"]
    assert "510300" in ETF_SYMBOLS


@pytest.mark.parametrize("payload, expected", [
    (["000001", {"code": "600519"}], ["000001", "600519"]),
    ({"cn": ["000001", "600519"]}, ["000001", "600519"]),
    ({"symbols": [{"code": "000001"}]}, ["000001"]),
])
def test_load_cn_symbols_supports_current_and_legacy_shapes(tmp_path: Path, payload, expected) -> None:
    path = tmp_path / "symbols.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_cn_symbols(path) == expected


def test_load_cn_symbols_fails_closed_on_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"cn": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_cn_symbols(path)
