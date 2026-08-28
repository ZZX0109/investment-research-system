from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fetch_cn_macro_actual_release_nbs.py"
    spec = importlib.util.spec_from_file_location("macro_release_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_pubdate_accepts_rendered_nbs_article_timestamp() -> None:
    module = _module()
    html = "<html><head><title>2021年9月份居民消费价格</title></head><body>2021/10/14 09:30 | 字体</body></html>"
    assert module._parse_pubdate(html) == "2021-10-14T09:30:00+08:00"


def test_incremental_merge_keeps_verified_timestamp_when_refresh_is_unresolved() -> None:
    module = _module()
    previous = [{
        "series": "pmi_monthly", "observation_period": "2022-05",
        "published_at": "2022-05-31T09:00:00+08:00", "source_url": "old",
    }]
    fresh = [{
        "series": "pmi_monthly", "observation_period": "2022-05",
        "published_at": None, "source_url": "new",
    }]
    merged = module._merge_previous_records(previous, fresh)
    assert merged[0]["published_at"] == "2022-05-31T09:00:00+08:00"
    assert merged[0]["source_url"] == "old"
