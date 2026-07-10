from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel


class WatchlistRequest(BaseModel):
    symbol: str
    market: str = "us"
    name: str | None = None


class ReportSettingsRequest(BaseModel):
    frequency: str = "weekly"


class OnboardingRequest(BaseModel):
    preference: str
    riskAnswers: dict[str, Any] = {}
    holdings: list[dict[str, Any]]


class ApiKeyRequest(BaseModel):
    provider: str
    apiKey: str


def build_portfolio_router(
    *,
    get_current_user: Callable[..., sqlite3.Row],
    get_user_profile: Callable[[int], dict[str, Any]],
    public_user: Callable[[sqlite3.Row], dict[str, Any]],
    portfolio_payload: Callable[[str, int | None], dict[str, Any]],
    save_onboarding_portfolio: Callable[[int, str, dict[str, Any], list[dict[str, Any]]], None],
    add_watchlist_holding: Callable[[int, str, str, str | None], dict[str, Any]],
    report_settings: Callable[[], dict[str, Any]],
    save_report_settings: Callable[[str], dict[str, Any]],
    user_api_key_summary: Callable[[int], list[dict[str, Any]]],
    upsert_user_api_key: Callable[[int, str, str], None],
    delete_user_api_key: Callable[[int, str], None],
    data_mode_status: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["portfolio"])

    def with_source_meta(payload: dict[str, Any]) -> dict[str, Any]:
        mode = data_mode_status()
        return {**payload, "dataMode": mode, "sourceMeta": mode["sourceMeta"]}

    @router.post("/api/onboarding")
    def save_onboarding(request: OnboardingRequest, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        user_id = int(user["id"])
        try:
            save_onboarding_portfolio(user_id, request.preference, request.riskAnswers, request.holdings)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        profile = get_user_profile(user_id)
        return {
            "ok": True,
            "preference": profile["preference"],
            "onboardingCompleted": profile["onboardingCompleted"],
            "user": public_user(user),
            "profile": profile,
            "portfolio": {**portfolio_payload(request.preference, user_id), "dataMode": data_mode_status()},
            "dataMode": data_mode_status(),
            "sourceMeta": data_mode_status()["sourceMeta"],
        }

    @router.get("/api/api-keys")
    def list_api_keys(user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        return with_source_meta({"apiKeys": user_api_key_summary(int(user["id"]))})

    @router.post("/api/api-keys")
    def upsert_api_key(request: ApiKeyRequest, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        provider = request.provider.strip().lower()
        api_key = request.apiKey.strip()
        if not provider or len(api_key) < 6:
            raise HTTPException(status_code=400, detail="Provider and API key are required.")
        upsert_user_api_key(int(user["id"]), provider, api_key)
        return with_source_meta({"ok": True, "apiKeys": user_api_key_summary(int(user["id"]))})

    @router.delete("/api/api-keys/{provider}")
    def delete_api_key(provider: str, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        delete_user_api_key(int(user["id"]), provider.strip().lower())
        return with_source_meta({"ok": True, "apiKeys": user_api_key_summary(int(user["id"]))})

    @router.get("/api/portfolio")
    def portfolio(preference: str = Query(default="balanced"), user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        profile = get_user_profile(int(user["id"]))
        selected_preference = preference or profile["preference"]
        payload = portfolio_payload(selected_preference, int(user["id"]))
        return {**payload, "dataMode": data_mode_status()}

    @router.get("/api/settings/report")
    def get_report_settings(user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        return with_source_meta(report_settings())

    @router.post("/api/settings/report")
    def update_report_settings(request: ReportSettingsRequest, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        return with_source_meta(save_report_settings(request.frequency))

    @router.post("/api/watchlist")
    def add_watchlist(request: WatchlistRequest, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        user_id = int(user["id"])
        try:
            result = add_watchlist_holding(user_id, request.symbol, request.market, request.name)
        except LookupError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        holding = result["holding"]
        snapshot = result["snapshot"]
        return {
            "symbol": holding["symbol"],
            "name": holding["name"],
            "market": holding["market"],
            "sector": holding["sector"],
            "shares": holding["shares"],
            "sourceMeta": snapshot.get("sourceMeta") or data_mode_status()["sourceMeta"],
            "dataMode": data_mode_status(),
        }

    return router
