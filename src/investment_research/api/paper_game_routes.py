from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator

from investment_research.config import get_app_settings
from investment_research.auth.security import AuthSettings
from investment_research.auth.service import AuthenticationError, AuthService
from investment_research.repository.sqlite import SQLiteUnitOfWork, create_unit_of_work
from investment_research.service.paper_game import PaperGameError, PaperGameService

router = APIRouter(prefix="/api/v1/paper-game", tags=["paper-game"])
COOKIE_NAME = "paper_game_visitor"


def get_uow():
    uow = create_unit_of_work()
    try:
        yield uow
    finally:
        uow.close()


class PaperAccountCreate(BaseModel):
    persona_code: str | None = Field(default=None, max_length=24)


class PaperOrderCreate(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    side: Literal["buy", "sell"]
    quantity: int | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)
    idempotency_key: str = Field(min_length=8, max_length=80)

    @model_validator(mode="after")
    def quantity_or_amount(self):
        if (self.quantity is None) == (self.amount is None):
            raise ValueError("quantity 和 amount 必须且只能提供一个")
        if self.side == "sell" and self.quantity is None:
            raise ValueError("卖出委托必须指定 quantity")
        return self


class PaperInitialPosition(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    quantity: int = Field(gt=0)


class PaperOnboardingConfirm(BaseModel):
    positions: list[PaperInitialPosition] = Field(min_length=1, max_length=30)
    idempotency_key: str = Field(min_length=8, max_length=80)


def _token(request: Request) -> str:
    value = request.cookies.get(COOKIE_NAME)
    if not value:
        raise HTTPException(status_code=401, detail="请先创建模拟账户")
    return value


def _call(fn):
    try:
        return fn()
    except PaperGameError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _optional_user_id(request: Request) -> str | None:
    settings = AuthSettings()
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        return None
    try:
        return str(AuthService(create_unit_of_work(), settings=settings).get_current_user(token).id)
    except AuthenticationError:
        return None


@router.get("/today")
def today(uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).today())


@router.post("/accounts", status_code=201)
def create_account(payload: PaperAccountCreate, request: Request, response: Response, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    token, account = _call(lambda: PaperGameService(uow).create_or_restore_account(request.cookies.get(COOKIE_NAME), payload.persona_code, _optional_user_id(request)))
    settings = get_app_settings()
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=settings.environment.value == "production",
        samesite="lax", max_age=60 * 60 * 24 * 365, path="/",
    )
    return account


@router.get("/account")
def account(request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).account(_token(request)))


@router.get("/onboarding")
def onboarding(request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).onboarding(_token(request)))


@router.post("/onboarding/confirm")
def confirm_onboarding(payload: PaperOnboardingConfirm, request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).confirm_onboarding(
        _token(request), [item.model_dump() for item in payload.positions], payload.idempotency_key,
    ))


@router.post("/orders", status_code=201)
def create_order(payload: PaperOrderCreate, request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).place_order(
        _token(request), symbol=payload.symbol, side=payload.side, quantity=payload.quantity,
        amount=payload.amount, idempotency_key=payload.idempotency_key,
    ))


@router.delete("/orders/{order_id}")
def cancel_order(order_id: str, request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).cancel(_token(request), order_id))


@router.get("/leaderboard")
def leaderboard(request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).leaderboard(_token(request)))


@router.get("/equity-curve")
def equity_curve(request: Request, uow: SQLiteUnitOfWork = Depends(get_uow)) -> dict:
    return _call(lambda: PaperGameService(uow).equity_curve(_token(request)))
