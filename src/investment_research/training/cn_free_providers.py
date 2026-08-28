"""Zero-budget A-share research providers and cross-source reconciliation.

The adapters return source bytes only.  They deliberately do not make either
AKShare or Baostock a formal market-data authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
    degraded_reason: str | None = None


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
        _validate_daily_frame(frame, symbol=symbol, adjustment_mode=adjustment_mode)
        payload = frame.to_json(orient="records", force_ascii=False, date_format="iso").encode()
        return PublicDailyPayload(self.name, symbol, payload, len(frame), start, end, adjustment_mode)


class SinaDailyResearchProvider:
    """Raw daily bars from Sina's public JSON endpoint.

    This is intentionally a research-tier adapter.  It is used as a backup
    for the AkShare/Eastmoney path because the two endpoints fail differently
    under public-rate limits.  The endpoint returns at most 5,000 rows, which
    is enough for the project's minimum historical-visibility check while
    retaining the exact provider payload in the append-only store.
    """

    name = "sina"
    endpoint = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )

    def __init__(self) -> None:
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",), raise_on_status=False,
        )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def fetch(self, symbol: str, *, start: date | None, end: date, adjustment_mode: str = "raw") -> PublicDailyPayload:
        if adjustment_mode != "raw":
            raise ValueError("sina provider only supplies raw daily bars")
        exchange_symbol = ("sh" if symbol.startswith(("5", "6")) else "sz") + symbol
        rows: Any = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._session.get(
                    self.endpoint,
                    params={"symbol": exchange_symbol, "scale": 240, "ma": 5, "datalen": 5000},
                    timeout=20,
                )
                response.raise_for_status()
                rows = response.json()
                if isinstance(rows, list) and rows:
                    break
                last_error = RuntimeError("sina returned an empty/non-list daily payload")
            except Exception as exc:  # retry transient public endpoint failures
                last_error = exc
            if attempt < 2:
                time.sleep(0.75 * (attempt + 1))
        if not isinstance(rows, list):
            raise RuntimeError("sina returned a non-list daily payload") from last_error
        lower = start or date(1990, 1, 1)
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_date = str(row.get("day") or "")[:10]
            try:
                observed = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if not (lower <= observed <= end):
                continue
            output.append({
                "日期": raw_date, "代码": symbol,
                "开盘": _float(row.get("open")), "最高": _float(row.get("high")),
                "最低": _float(row.get("low")), "收盘": _float(row.get("close")),
                "成交量": _float(row.get("volume"), 0.0),
            })
        if not output:
            raise RuntimeError("sina returned no daily rows")
        _validate_serialized_daily_rows(output, symbol=symbol, adjustment_mode=adjustment_mode)
        payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
        return PublicDailyPayload(self.name, symbol, payload, len(output), start, end, adjustment_mode)


class TencentDailyResearchProvider:
    """Forward-adjusted daily bars from Tencent's public endpoint."""

    name = "tencent"
    endpoint = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    def __init__(self) -> None:
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",), raise_on_status=False,
        )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def fetch(self, symbol: str, *, start: date | None, end: date, adjustment_mode: str = "qfq") -> PublicDailyPayload:
        if adjustment_mode != "qfq":
            raise ValueError("tencent provider only supplies qfq daily bars")
        exchange_symbol = ("sh" if symbol.startswith(("5", "6")) else "sz") + symbol
        lower = start or date(1990, 1, 1)
        # Tencent caps a single response at roughly 1,000 rows.  Four-year
        # windows avoid truncation and make the coverage boundaries explicit.
        windows: list[tuple[date, date]] = []
        cursor = lower
        while cursor <= end:
            window_end = min(date(cursor.year + 3, 12, 31), end)
            windows.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)
        output_by_date: dict[str, dict[str, Any]] = {}
        for window_start, window_end in windows:
            response = self._session.get(
                self.endpoint,
                params={
                    "param": (
                        f"{exchange_symbol},day,{window_start.isoformat()},"
                        f"{window_end.isoformat()},1000,qfq"
                    )
                },
                timeout=20,
            )
            response.raise_for_status()
            body = response.json()
            block = ((body.get("data") or {}).get(exchange_symbol) or {}) if isinstance(body, dict) else {}
            rows = block.get("qfqday") or []
            for row in rows:
                if not isinstance(row, list) or len(row) < 6:
                    continue
                raw_date = str(row[0])[:10]
                try:
                    observed = date.fromisoformat(raw_date)
                except ValueError:
                    continue
                if lower <= observed <= end:
                    output_by_date[raw_date] = {
                        "日期": raw_date, "代码": symbol,
                        "开盘": _float(row[1]), "收盘": _float(row[2]),
                        "最高": _float(row[3]), "最低": _float(row[4]),
                        "成交量": _float(row[5], 0.0),
                    }
        output = [output_by_date[key] for key in sorted(output_by_date)]
        if not output:
            raise RuntimeError("tencent returned no qfq daily rows")
        output, invalid_count = _clean_serialized_daily_rows(output)
        if not output:
            raise RuntimeError("tencent qfq rows were all invalid after OHLC validation")
        payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
        degraded_reason = f"invalid_ohlc_rows_filtered:{invalid_count}" if invalid_count else None
        return PublicDailyPayload(self.name, symbol, payload, len(output), start, end, adjustment_mode, degraded_reason)


class EastmoneyDailyResearchProvider:
    """Eastmoney's public historical K-line endpoint.

    It is specifically retained in the research provider chain because its
    forward-adjusted (``fqt=1``) history covers Beijing Exchange instruments
    that are absent from the Yahoo and Tencent endpoints.  The endpoint can
    intermittently reset public connections, so a bounded retry session and
    per-request timeout are part of the adapter rather than being left to the
    caller.
    """

    name = "eastmoney"
    endpoint = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        retry = Retry(
            # The process-level collector already retries a failed symbol in
            # later resumable passes.  Limit a single public request here so
            # one reset proxy cannot monopolise an entire worker.
            total=1, connect=1, read=1, backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",), raise_on_status=False,
        )
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        })
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def fetch(self, symbol: str, *, start: date | None, end: date, adjustment_mode: str = "qfq") -> PublicDailyPayload:
        if adjustment_mode not in {"raw", "qfq"}:
            raise ValueError(f"eastmoney unsupported adjustment mode:{adjustment_mode}")
        exchange = "1" if symbol.startswith(("5", "6")) else "0"
        lower = start or date(1990, 1, 1)
        response = self._session.get(
            self.endpoint,
            params={
                "secid": f"{exchange}.{symbol}", "klt": "101",
                "fqt": "0" if adjustment_mode == "raw" else "1",
                # Eastmoney's history service rejects/unstably closes some
                # qfq requests without its public client token.
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "beg": lower.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
                "lmt": "1000000", "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        block = body.get("data") if isinstance(body, dict) else None
        rows = block.get("klines") if isinstance(block, dict) else None
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("eastmoney returned no daily rows")
        output: list[dict[str, Any]] = []
        for row in rows:
            parts = str(row).split(",")
            if len(parts) < 7:
                continue
            try:
                observed = date.fromisoformat(parts[0][:10])
            except ValueError:
                continue
            if lower <= observed <= end:
                output.append({
                    "日期": observed.isoformat(), "代码": symbol,
                    "开盘": _float(parts[1]), "收盘": _float(parts[2]),
                    "最高": _float(parts[3]), "最低": _float(parts[4]),
                    "成交量": _float(parts[5], 0.0), "成交额": _float(parts[6], 0.0),
                })
        output, invalid_count = _clean_serialized_daily_rows(output)
        if not output:
            raise RuntimeError("eastmoney rows were all invalid after OHLC validation")
        payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
        degraded_reason = f"invalid_ohlc_rows_filtered:{invalid_count}" if invalid_count else None
        return PublicDailyPayload(self.name, symbol, payload, len(output), start, end, adjustment_mode, degraded_reason)


class YahooDailyResearchProvider:
    """Yahoo Finance chart fallback for A-share raw and adjusted OHLCV."""

    name = "yahoo"
    endpoint = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(self) -> None:
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",), raise_on_status=False,
        )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def fetch(self, symbol: str, *, start: date | None, end: date, adjustment_mode: str = "raw") -> PublicDailyPayload:
        if adjustment_mode not in {"raw", "qfq"}:
            raise ValueError(f"yahoo unsupported adjustment mode:{adjustment_mode}")
        suffix = "SS" if symbol.startswith(("5", "6")) else "SZ"
        yahoo_symbol = f"{symbol}.{suffix}"
        lower = start or date(1990, 1, 1)
        period1 = int(datetime.combine(lower, datetime.min.time(), timezone.utc).timestamp())
        period2 = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp())
        response = self._session.get(
            f"{self.endpoint}/{yahoo_symbol}",
            params={"period1": period1, "period2": period2, "interval": "1d", "events": "history"},
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
        result = ((body.get("chart") or {}).get("result") or [None])[0] if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("yahoo returned no chart result")
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [None])[0] or {}
        adjusted = ((result.get("indicators") or {}).get("adjclose") or [None])[0] or {}
        output: list[dict[str, Any]] = []
        for index, timestamp in enumerate(timestamps):
            try:
                observed = datetime.fromtimestamp(int(timestamp), timezone.utc).date()
                open_price = float((quote.get("open") or [])[index])
                high = float((quote.get("high") or [])[index])
                low = float((quote.get("low") or [])[index])
                close = float((quote.get("close") or [])[index])
                volume = float((quote.get("volume") or [])[index] or 0.0)
            except (IndexError, TypeError, ValueError, OverflowError):
                continue
            if not (lower <= observed <= end):
                continue
            if adjustment_mode == "qfq":
                try:
                    adjusted_close = float((adjusted.get("adjclose") or [])[index])
                    factor = adjusted_close / close if close > 0 and adjusted_close > 0 else 1.0
                except (IndexError, TypeError, ValueError, ZeroDivisionError):
                    factor = 1.0
                open_price, high, low, close = (
                    open_price * factor, high * factor, low * factor, close * factor,
                )
            output.append({
                "日期": observed.isoformat(), "代码": symbol,
                "开盘": open_price, "收盘": close, "最高": high, "最低": low,
                "成交量": volume,
            })
        output, invalid_count = _clean_serialized_daily_rows(output)
        if not output:
            raise RuntimeError("yahoo returned no valid daily rows")
        payload = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
        degraded_reason = f"invalid_ohlc_rows_filtered:{invalid_count}" if invalid_count else None
        return PublicDailyPayload(self.name, symbol, payload, len(output), start, end, adjustment_mode, degraded_reason)


class BaostockDailyResearchProvider:
    name = "baostock"

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def __enter__(self) -> "BaostockDailyResearchProvider":
        import baostock as bs

        result = bs.login()
        if result.error_code != "0":
            raise RuntimeError(f"baostock login failed:{result.error_code}:{result.error_msg}")
        self._bs = bs
        # Baostock keeps a module-global socket whose ``recv`` otherwise has
        # no deadline.  A provider that goes silent would block the whole
        # serial daily collector forever, so put the configured deadline on
        # the actual socket as well as the outer retry guard.
        try:
            from baostock.common import context

            default_socket = getattr(context, "default_socket", None)
            if default_socket is not None:
                default_socket.settimeout(self.timeout_seconds)
        except (AttributeError, OSError):
            # The next query will surface a normal provider error/retry.
            pass
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
            "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST",
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
                "昨收": _float(source.get("preclose")),
                "涨跌幅": _float(source.get("pctChg")),
                "市盈率TTM": _float(source.get("peTTM")),
                "市净率MRQ": _float(source.get("pbMRQ")),
                "市销率TTM": _float(source.get("psTTM")),
                "市现率TTM": _float(source.get("pcfNcfTTM")),
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


def _validate_daily_frame(frame: Any, *, symbol: str, adjustment_mode: str) -> None:
    """Reject provider rows that cannot be used as price observations.

    Public adjusted-price endpoints occasionally return negative historical
    values for old listings instead of a usable adjustment series.  Persisting
    those rows poisons the qfq PIT layer and only surfaces much later during a
    snapshot audit.  Fail this provider attempt early so the collector can use
    its configured backup and retain an explicit failure record.
    """
    aliases = {
        "open": ("open", "开盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        "close": ("close", "收盘"),
    }
    columns = set(getattr(frame, "columns", ()))
    selected: dict[str, str] = {}
    for canonical, names in aliases.items():
        column = next((name for name in names if name in columns), None)
        if column is None:
            raise RuntimeError(f"{adjustment_mode} price payload missing {canonical}:{symbol}")
        selected[canonical] = column
    try:
        numeric = frame[list(selected.values())].apply(lambda column: column.astype(float))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{adjustment_mode} price payload has non-numeric OHLC:{symbol}") from exc
    invalid = numeric.isna().any(axis=1) | (numeric <= 0).any(axis=1)
    invalid |= numeric[selected["high"]] < numeric[[selected["open"], selected["close"]]].max(axis=1)
    invalid |= numeric[selected["low"]] > numeric[[selected["open"], selected["close"]]].min(axis=1)
    if bool(invalid.any()):
        raise RuntimeError(f"{adjustment_mode} price payload failed OHLC validation:{symbol}:{int(invalid.sum())}")


def _validate_serialized_daily_rows(rows: list[dict[str, Any]], *, symbol: str, adjustment_mode: str) -> None:
    """Apply the same OHLC checks to non-DataFrame public-source adapters."""
    invalid = 0
    for row in rows:
        try:
            open_price = float(row["开盘"])
            high = float(row["最高"])
            low = float(row["最低"])
            close = float(row["收盘"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if min(open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close):
            invalid += 1
    if invalid:
        raise RuntimeError(f"{adjustment_mode} price payload failed OHLC validation:{symbol}:{invalid}")


def _clean_serialized_daily_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Drop malformed/negative adjusted rows instead of poisoning the PIT."""
    valid: list[dict[str, Any]] = []
    invalid = 0
    for row in rows:
        try:
            open_price = float(row["开盘"])
            high = float(row["最高"])
            low = float(row["最低"])
            close = float(row["收盘"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if min(open_price, high, low, close) <= 0 or high < max(open_price, close) or low > min(open_price, close):
            invalid += 1
            continue
        valid.append(row)
    return valid, invalid


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
