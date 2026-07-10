from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import APIRouter, Depends


def build_refresh_router(
    *,
    get_current_user: Callable[..., sqlite3.Row],
    refresh_user_data: Callable[[int], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["refresh"])

    @router.post("/api/refresh/daily")
    def refresh_daily_endpoint(user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        return refresh_user_data(int(user["id"]))

    return router
