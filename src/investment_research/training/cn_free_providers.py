"""Zero-budget A-share research providers and cross-source reconciliation.

The adapters return source bytes only.  They deliberately do not make either
AKShare or Baostock a formal market-data authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from hashlib import sha256
import json
from typing import Any


ETF_RESEARCH_SYMBOLS = ("510050", "510300", "510500", "159915", "512100")


@dataclass(frozen=True)
class PublicDailyPayload:
    provider: str
    symbol: str
    payload: bytes
    row_count: int
    requested_start: date | None
    requested_end: date
    adjustment_mode: str = "raw"


@dataclass(frozen=True)
class ProviderComparison:
    status: str
    shared_dates: int
    close_conflicts: int
    volume_conflicts: int
    missing_dates: int
    maximum_close_difference_ratio: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def severe(self) -> bool:
        return self.status == "conflict"


class AkshareDailyResearchProvider:
    name = "akshare"

    def enumerate_symbols(self) -> list[str]:
        import akshare as ak

        frame = ak.stock_info_a_code_name()
        column = "code" if "code" in frame.columns else "代码"
        return sorted({str(value).zfill(6) for value in frame[column].tolist() if value})

    def fetch(self, symbol: str, *, start: date | None, end: date, adjustment_mode: str = "raw") -> PublicDailyPayload:
        import akshare as ak

        if symbol in ETF_RESEARCH_SYMBOLS:
            exchange_symbol = ("sh" if symbol.startswith("5") else "sz") + symbol
            frame = ak.fund_etf_hist_sina(symbol=exchange_symbol)
            date_column = "date" if "date" in frame.columns else "日期"
            dates = frame[date_column].map(lambda value: date.fromisoformat(str(value)[:10]))
            lower = start or date(1990, 1, 1)
            frame = frame[(dates >= lower) & (dates <= end)]
        else:
            frame = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=(start or date(1990, 1, 1)).strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="" if adjustment_mode == "raw" else adjustment_mode,
            )
        if frame.empty:
            raise RuntimeError("akshare returned no daily rows")
        payload = frame.to_json(orient="records", force_ascii=False, date_format="iso").encode()
        return PublicDailyPayload(self.name, symbol, payload, len(frame), start, end, adjustment_mode)


class BaostockDailyResearchProvider:
    name = "baostock"

    def __enter__(self) -> "BaostockDailyResearchProvider":
        import baostock as bs

        result = bs.login()
        if result.error_code != "0":
            raise RuntimeError(f"baostock login failed:{result.error_code}:{result.error_msg}")
        self._bs = bs
        return self

    def __exit__(self, *_args) -> None:
        if hasattr(self, "_bs"):
            self._bs.logout()

    def enumerate_symbols(self, *, as_of: date) -> list[str]:
        errors: list[str] = []
        for offset in range(10):
            candidate = as_of - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            result = self._bs.query_all_stock(day=candidate.isoformat())
            if result.error_code != "0":
                errors.append(f"{candidate}:{result.error_code}")
                continue
            symbols: list[str] = []
            while result.next():
                row = dict(zip(result.fields, result.get_row_data()))
                code = row.get("code", "")
                if code.startswith(("sh.6", "sz.0", "sz.3", "bj.")):
                    symbols.append(code.split(".", 1)[1])
            if symbols:
                return sorted(set(symbols))
            errors.append(f"{candidate}:empty")
        raise RuntimeError("baostock universe unavailable:" + ",".join(errors))

    def enumerate_liquid_candidates(self) -> list[str]:
        """Return the public CSI 300 constituent buffer for fixed-pool ranking."""
        result = self._bs.query_hs300_stocks()
        if result.error_code != "0":
            raise RuntimeError(
                f"baostock hs300 universe failed:{result.error_code}:{result.error_msg}"
            )
        symbols: list[str] = []
        while result.next():
            row = dict(zip(result.fields, result.get_row_data()))
            code = row.get("code", "")
            if code.startswith(("sh.6", "sz.0", "sz.3")):
                symbols.append(code.split(".", 1)[1])
        if not symbols:
            raise RuntimeError("baostock hs300 universe is empty")
        return sorted(set(symbols))

    def fetch(self, symbol: str, *, start: date | None, end: date, adjustment_mode: str = "raw") -> PublicDailyPayload:
        code = _baostock_code(symbol)
        result = self._bs.query_history_k_data_plus(
            code,
            "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
            start_date=(start or date(1990, 1, 1)).isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag={"raw": "3", "qfq": "2", "hfq": "1"}[adjustment_mode],
        )
        if result.error_code != "0":
            raise RuntimeError(f"baostock daily failed:{result.error_code}:{result.error_msg}")
        rows: list[dict[str, Any]] = []
        while result.next():
            source = dict(zip(result.fields, result.get_row_data()))
            if not source.get("close"):
                continue
            rows.append({
                "日期": source["date"], "代码": source["code"],
                "开盘": _float(source.get("open")), "最高": _float(source.get("high")),
                "最低": _float(source.get("low")), "收盘": _float(source.get("close")),
                "成交量": _float(source.get("volume"), 0.0),
                "成交额": _float(source.get("amount"), 0.0),
                "换手率": _float(source.get("turn")),
                "交易状态": source.get("tradestatus"), "是否ST": source.get("isST"),
            })
        if not rows:
            raise RuntimeError("baostock returned no daily rows")
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
        return PublicDailyPayload(self.name, symbol, payload, len(rows), start, end, adjustment_mode)




def deterministic_cross_check(symbol: str, trade_date: date, *, ratio: float) -> bool:
    if ratio <= 0:
        return False
    if ratio >= 1:
        return True
    digest = sha256(f"{trade_date.isoformat()}:{symbol}".encode()).digest()
    bucket = int.from_bytes(digest[:4], "big") / (2**32 - 1)
    return bucket < ratio


def compare_public_daily_payloads(
    primary: bytes,
    backup: bytes,
    *,
    close_tolerance: float = 0.002,
    volume_tolerance: float = 0.02,
) -> ProviderComparison:
    left = _rows_by_date(primary)
    right = _rows_by_date(backup)
    shared = sorted(set(left) & set(right))
    close_conflicts = 0
    volume_conflicts = 0
    maximum = 0.0
    for key in shared:
        left_close = left[key]["close"]
        right_close = right[key]["close"]
        close_ratio = abs(left_close - right_close) / max(abs(left_close), abs(right_close), 1e-12)
        maximum = max(maximum, close_ratio)
        close_conflicts += close_ratio > close_tolerance
        left_volume, right_volume = left[key]["volume"], right[key]["volume"]
        volume_ratio = abs(left_volume - right_volume) / max(abs(left_volume), abs(right_volume), 1.0)
        volume_conflicts += volume_ratio > volume_tolerance
    missing = len(set(left) ^ set(right))
    reasons: list[str] = []
    if close_conflicts:
        reasons.append("raw_close_difference_exceeds_0_2pct")
    if volume_conflicts:
        reasons.append("raw_volume_difference_exceeds_2pct")
    if missing:
        reasons.append("provider_trade_date_set_differs")
    status = "conflict" if close_conflicts or volume_conflicts else "partial" if missing else "matched"
    return ProviderComparison(
        status=status, shared_dates=len(shared),
        close_conflicts=close_conflicts, volume_conflicts=volume_conflicts,
        missing_dates=missing, maximum_close_difference_ratio=maximum, reasons=reasons,
    )


def _rows_by_date(payload: bytes) -> dict[str, dict[str, float]]:
    rows = json.loads(payload)
    output: dict[str, dict[str, float]] = {}
    for row in rows:
        key = _value(row, "date", "日期")
        close = _value(row, "close", "收盘")
        if key is None or close in (None, ""):
            continue
        output[str(key)[:10]] = {
            "close": float(close),
            "volume": float(_value(row, "volume", "成交量") or 0.0),
        }
    return output


def _value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    for key, value in row.items():
        lowered = str(key).lower()
        if any(name.lower() in lowered for name in names):
            return value
    return None


def _baostock_code(symbol: str) -> str:
    if symbol.startswith(("4", "8", "9")):
        return f"bj.{symbol}"
    return f"sh.{symbol}" if symbol.startswith(("5", "6")) else f"sz.{symbol}"


def _float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(value)
