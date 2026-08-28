from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from investment_research.api.paper_game_routes import router
from investment_research.repository.sqlite import SQLiteUnitOfWork


def test_anonymous_cookie_restores_account_and_endpoints(tmp_path: Path) -> None:
    database = tmp_path / "paper-api.db"

    def override_uow():
        uow = SQLiteUnitOfWork(database)
        try:
            yield uow
        finally:
            uow.close()

    app = FastAPI()
    app.include_router(router)
    # The route dependency function is module-local, so replace it by finding
    # the dependency callable used by the first paper-game route.
    from investment_research.api.paper_game_routes import get_uow
    app.dependency_overrides[get_uow] = override_uow

    with TestClient(app) as client:
        today = client.get("/api/v1/paper-game/today")
        assert today.status_code == 200
        assert {asset["category"] for asset in today.json()["assets"]} == {"股票", "基金", "黄金"}

        created = client.post("/api/v1/paper-game/accounts", json={"persona_code": "OWL"})
        assert created.status_code == 201
        assert created.json()["cash"] == 100_000
        assert client.cookies.get("paper_game_visitor")

        restored = client.get("/api/v1/paper-game/account")
        assert restored.status_code == 200
        assert restored.json()["id"] == created.json()["id"]
        assert len(client.get("/api/v1/paper-game/leaderboard").json()["entries"]) == 13
        assert client.get("/api/v1/paper-game/equity-curve").status_code == 200
