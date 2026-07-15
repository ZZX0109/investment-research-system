from pathlib import Path

from investment_research.service.legacy_inventory import build_inventory


def test_legacy_inventory_is_portable_and_blocks_cn_training(tmp_path: Path) -> None:
    raw = tmp_path / "data/free_research_raw/yfinance"
    standard = tmp_path / "data/free_research_standard/CN"
    raw.mkdir(parents=True)
    standard.mkdir(parents=True)
    (raw / "payload.json").write_bytes(b'{"close": 1}')
    (standard / "bars.json").write_bytes(b"[]")

    inventory = build_inventory(
        tmp_path,
        [tmp_path / "data/free_research_raw", tmp_path / "data/free_research_standard"],
    )

    assert inventory["classification"] == "legacy_four_market_public_data"
    assert inventory["eligible_for_cn_training"] is False
    assert inventory["entry_count"] == 2
    assert all(not item["path"].startswith(str(tmp_path)) for item in inventory["entries"])
    assert all(item["eligible_for_cn_training"] is False for item in inventory["entries"])
    assert inventory["content_manifest_sha256"]
