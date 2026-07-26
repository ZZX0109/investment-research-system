from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import raises

from investment_research.bootstrap.application import _attach_static_workbench
from investment_research.public_demo import require_private_research_workspace


def test_static_workbench_serves_assets_and_spa_fallback(monkeypatch, tmp_path) -> None:
    static_dir = tmp_path / "dist-workbench"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<div>research workbench</div>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ready')", encoding="utf-8")
    monkeypatch.setenv("INVESTMENT_RESEARCH_STATIC_DIR", str(static_dir))

    app = FastAPI()
    app.get("/health")(lambda: {"status": "ok"})
    _attach_static_workbench(app)
    client = TestClient(app)

    assert client.get("/").text == "<div>research workbench</div>"
    assert client.get("/research/600519").text == "<div>research workbench</div>"
    assert client.get("/assets/app.js").text == "console.log('ready')"
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/unknown").status_code == 404


def test_public_demo_rejects_shared_key_or_llm_operations(monkeypatch) -> None:
    monkeypatch.setenv("INVESTMENT_RESEARCH_PUBLIC_DEMO", "true")
    with raises(Exception) as raised:
        require_private_research_workspace()
    assert getattr(raised.value, "status_code", None) == 403
