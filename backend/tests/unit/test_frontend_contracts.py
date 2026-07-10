"""
前端契约测试：确保 demo fixture 不回流到真实 API 主流程。
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = ROOT / "frontend" / "src"


def test_sample_data_is_not_imported_by_main_app():
    offenders: list[Path] = []
    for path in FRONTEND_SRC.rglob("*.ts*"):
        if path.name == "sampleData.ts":
            continue
        text = path.read_text(encoding="utf-8")
        if "sampleData" in text and "from \"./sampleData\"" in text:
            offenders.append(path)
        if "sampleData" in text and "from \"../sampleData\"" in text:
            offenders.append(path)
    assert offenders == [], f"真实前端流程仍引用 demo fixture: {offenders}"


def test_sample_data_declares_demo_only_intent():
    text = (FRONTEND_SRC / "sampleData.ts").read_text(encoding="utf-8")
    assert "Demo-only fixture" in text


def test_main_entry_stays_thin_after_workbench_split():
    text = (FRONTEND_SRC / "main.tsx").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 40
    assert "WorkbenchPage" not in text
    assert "QueryClientProvider" in text


def test_direct_fetch_is_centralized_in_api_client():
    offenders: list[Path] = []
    for path in FRONTEND_SRC.rglob("*.ts*"):
        if path.as_posix().endswith("src/lib/apiClient.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        if "fetch(" in text:
            offenders.append(path)
    assert offenders == [], f"前端仍绕过统一 API client: {offenders}"
