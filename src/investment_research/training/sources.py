from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Iterable, Mapping

from investment_research.training.catalog import UNIVERSE_PRESETS
from investment_research.training.models import (
    CanonicalDatasetBundle,
    CanonicalInstrument,
    CanonicalPriceBar,
    CoveragePreset,
    DataProvider,
    EventDirection,
    EventIntensity,
    EventSourceTier,
    EventType,
    GuidanceBucket,
    PointInTimeEvent,
    SurpriseBucket,
)
from investment_research.training.source_rows import (
    AksharePriceRow,
    CnAnnouncementRow,
    JsonValue,
    NewsRow,
    SecFilingRow,
    YFinancePriceRow,
)


def resolve_coverage_preset(symbol: str) -> CoveragePreset:
    normalized = _normalize_symbol(symbol)
    preset = UNIVERSE_PRESETS.get(normalized)
    if preset is not None:
        return preset
    for candidate in UNIVERSE_PRESETS.values():
        if normalized in {_normalize_symbol(alias) for alias in candidate.aliases}:
            return candidate
    raise ValueError(f"Unsupported symbol coverage preset: {symbol}")


def build_instrument_from_symbol(symbol: str) -> CanonicalInstrument:
    preset = resolve_coverage_preset(symbol)
    return CanonicalInstrument(
        symbol=preset.symbol,
        market=preset.market,
        instrument_type=preset.instrument_type,
        coverage_group=preset.coverage_group,
        name=preset.name,
        currency=preset.currency,
        exchange=preset.exchange,
        industry_key=preset.industry_key,
        benchmark_symbol=preset.benchmark_symbol,
        sector_reference_symbol=preset.sector_reference_symbol,
        style_reference_symbol=preset.style_reference_symbol,
    )


def normalize_yfinance_rows(
    symbol: str,
    rows: Iterable[YFinancePriceRow | Mapping[str, JsonValue]],
) -> CanonicalDatasetBundle:
    preset = resolve_coverage_preset(symbol)
    instrument = build_instrument_from_symbol(symbol)
    typed_rows = [_as_yfinance_row(row) for row in rows]
    bars = [
        _build_price_bar(
            symbol=instrument.symbol,
            row=row,
            currency=preset.currency,
            calendar_code=preset.exchange or "XNYS",
            provider=DataProvider.YFINANCE,
            adjusted_close=row.adj_close,
            fx_rate_to_usd=None,
        )
        for row in typed_rows
    ]
    return CanonicalDatasetBundle(
        instrument=instrument,
        provider=DataProvider.YFINANCE,
        price_bars=bars,
        coverage_notes=[f"Normalized {len(bars)} yfinance rows for {instrument.symbol}."],
    )


def normalize_akshare_rows(
    symbol: str,
    rows: Iterable[AksharePriceRow | Mapping[str, JsonValue]],
) -> CanonicalDatasetBundle:
    preset = resolve_coverage_preset(symbol)
    instrument = build_instrument_from_symbol(symbol)
    typed_rows = [_as_akshare_row(row) for row in rows]
    bars = [
        _build_price_bar(
            symbol=instrument.symbol,
            row=row,
            currency=preset.currency,
            calendar_code=preset.exchange or "XSHG",
            provider=DataProvider.AKSHARE,
            adjusted_close=row.adjusted_close,
            fx_rate_to_usd=row.fx_rate_to_usd,
        )
        for row in typed_rows
    ]
    return CanonicalDatasetBundle(
        instrument=instrument,
        provider=DataProvider.AKSHARE,
        price_bars=bars,
        coverage_notes=[f"Normalized {len(bars)} akshare rows for {instrument.symbol}."],
    )


def normalize_sec_filings(symbol: str, filings: Iterable[SecFilingRow | Mapping[str, JsonValue]]) -> list[PointInTimeEvent]:
    instrument = build_instrument_from_symbol(symbol)
    events: list[PointInTimeEvent] = []
    for filing_input in filings:
        filing = _as_sec_filing_row(filing_input)
        published_at = _coerce_datetime(filing.acceptance_datetime or filing.published_at or filing.filed_at)
        events.append(
            PointInTimeEvent(
                symbol=instrument.symbol,
                event_type=EventType.FILING,
                event_time=_coerce_datetime(filing.event_time or filing.filed_at or published_at),
                published_at=published_at,
                source_name="sec",
                source_url=filing.url,
                headline=None if filing.form is None else f"SEC {filing.form}",
                payload_ref=filing.accession_number,
                event_direction=EventDirection.UNKNOWN,
                event_intensity=infer_event_intensity(filing.form or ""),
                source_tier=EventSourceTier.REGULATORY,
                surprise_bucket=SurpriseBucket.UNKNOWN,
                guidance_bucket=GuidanceBucket.UNKNOWN,
                filing_subtype=(filing.form or "").upper() or None,
                provider=DataProvider.SEC.value,
                as_of=published_at,
                raw_hash=_hash_payload(filing.model_dump(mode="json")),
                normalized_hash=_hash_payload(
                    {
                        "symbol": instrument.symbol,
                        "event_type": EventType.FILING.value,
                        "published_at": published_at.isoformat(),
                        "payload_ref": filing.accession_number,
                        "filing_subtype": (filing.form or "").upper() or None,
                    }
                ),
                data_version=f"{DataProvider.SEC.value}:{published_at.date().isoformat()}",
            )
        )
    return events


def normalize_cn_announcements(
    symbol: str,
    announcements: Iterable[CnAnnouncementRow | Mapping[str, JsonValue]],
) -> list[PointInTimeEvent]:
    instrument = build_instrument_from_symbol(symbol)
    events: list[PointInTimeEvent] = []
    for announcement_input in announcements:
        announcement = _as_cn_announcement_row(announcement_input)
        published_at = _coerce_datetime(announcement.published_at)
        title = announcement.title or ""
        event_type = infer_event_type(title or "公告")
        events.append(
            PointInTimeEvent(
                symbol=instrument.symbol,
                event_type=event_type,
                event_time=_coerce_datetime(announcement.event_time or published_at),
                published_at=published_at,
                source_name="cninfo",
                source_url=announcement.url,
                headline=announcement.title,
                payload_ref=announcement.id,
                event_direction=infer_event_direction(title),
                event_intensity=infer_event_intensity(title),
                source_tier=EventSourceTier.EXCHANGE,
                surprise_bucket=infer_surprise_bucket(title),
                guidance_bucket=infer_guidance_bucket(title),
                provider=DataProvider.CNINFO.value,
                as_of=published_at,
                raw_hash=_hash_payload(announcement.model_dump(mode="json")),
                normalized_hash=_hash_payload(
                    {
                        "symbol": instrument.symbol,
                        "event_type": event_type.value,
                        "published_at": published_at.isoformat(),
                        "payload_ref": announcement.id,
                        "headline": announcement.title,
                    }
                ),
                data_version=f"{DataProvider.CNINFO.value}:{published_at.date().isoformat()}",
            )
        )
    return events


def normalize_news_rows(
    symbol: str,
    rows: Iterable[NewsRow | Mapping[str, JsonValue]],
    *,
    provider: DataProvider = DataProvider.NEWSWIRE,
) -> list[PointInTimeEvent]:
    instrument = build_instrument_from_symbol(symbol)
    events: list[PointInTimeEvent] = []
    for row_input in rows:
        row = _as_news_row(row_input)
        published_at = _coerce_datetime(row.published_at)
        events.append(
            PointInTimeEvent(
                symbol=instrument.symbol,
                event_type=infer_event_type(row.headline or ""),
                event_time=_coerce_datetime(row.event_time or published_at),
                published_at=published_at,
                source_name=provider.value,
                source_url=row.url,
                headline=row.headline,
                payload_ref=row.id,
                event_direction=infer_event_direction(row.headline or ""),
                event_intensity=infer_event_intensity(row.headline or ""),
                source_tier=_provider_source_tier(provider),
                surprise_bucket=infer_surprise_bucket(row.headline or ""),
                guidance_bucket=infer_guidance_bucket(row.headline or ""),
                provider=provider.value,
                as_of=published_at,
                raw_hash=_hash_payload(row.model_dump(mode="json")),
                normalized_hash=_hash_payload(
                    {
                        "symbol": instrument.symbol,
                        "event_type": infer_event_type(row.headline or "").value,
                        "published_at": published_at.isoformat(),
                        "payload_ref": row.id,
                        "headline": row.headline,
                    }
                ),
                data_version=f"{provider.value}:{published_at.date().isoformat()}",
            )
        )
    return events


def _build_price_bar(
    *,
    symbol: str,
    row,
    currency: str,
    calendar_code: str,
    provider: DataProvider,
    adjusted_close: float | None,
    fx_rate_to_usd: float | None,
) -> CanonicalPriceBar:
    trade_date = _coerce_date(row.trade_date)
    published_at = _coerce_datetime(row.published_at or row.trade_date)
    open_price = float(row.open)
    close_price = float(row.close)
    high_price = max(float(row.high), open_price, close_price)
    low_price = min(float(row.low), open_price, close_price)
    adjusted_close_value = float(adjusted_close) if adjusted_close is not None else close_price
    volume_value = float(row.volume) if row.volume is not None else 0.0
    raw_payload = row.model_dump(mode="json")
    normalized_payload = {
        "symbol": symbol,
        "trade_date": trade_date.isoformat(),
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "adjusted_close": adjusted_close_value,
        "volume": volume_value,
        "currency": currency,
        "calendar_code": calendar_code,
        "provider": provider.value,
    }
    return CanonicalPriceBar(
        symbol=symbol,
        trade_date=trade_date,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        adjusted_close=adjusted_close_value,
        volume=volume_value,
        currency=currency,
        calendar_code=calendar_code,
        fx_rate_to_usd=fx_rate_to_usd,
        published_at=published_at,
        provider=provider.value,
        as_of=published_at,
        raw_hash=_hash_payload(raw_payload),
        normalized_hash=_hash_payload(normalized_payload),
        data_version=f"{provider.value}:{trade_date.isoformat()}",
    )


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def infer_event_type(text: str) -> EventType:
    normalized = text.lower()
    if any(keyword in normalized for keyword in (
        "earnings", "财报", "业绩", "results", "guidance", "outlook", "profit warning",
        "profit alert", "positive profit alert", "annual result", "interim result", "quarterly result",
        "preliminary results", "earnings preview", "eps", "revenue", "margin pressure",
        "业绩预告", "业绩快报", "年度报告", "中期业绩", "季度报告", "盈利警告", "盈利预警",
        "一季报", "半年报", "三季报", "年报", "净利润", "营收", "利润分配",
    )):
        return EventType.EARNINGS
    if any(keyword in normalized for keyword in (
        "merger", "acquisition", "m&a", "takeover", "discloseable transaction", "connected transaction",
        "joint venture", "asset disposal", "strategic investment", "privatization", "spin-off",
        "tender offer", "buyout", "收购", "并购", "兼并", "重组", "重大资产", "股权转让",
        "资产出售", "资产购买", "吸收合并", "定向增发", "控制权变更", "要约收购",
    )):
        return EventType.MNA
    if any(keyword in normalized for keyword in (
        "lawsuit", "litigation", "class action", "court", "trial", "settlement", "诉讼",
        "仲裁", "起诉", "判决", "裁定", "和解", "索赔",
    )):
        return EventType.LITIGATION
    if any(keyword in normalized for keyword in (
        "regulator", "regulatory", "sec probe", "investigation", "probe", "fine", "penalty",
        "antitrust", "sanction", "delisting risk", "wells notice", "subpoena", "compliance",
        "监管", "调查", "立案", "处罚", "罚款", "问询函", "监管函", "警示函", "关注函",
        "纪律处分", "行政处罚", "反垄断", "退市风险", "被查", "违规",
    )):
        return EventType.REGULATION
    if any(keyword in normalized for keyword in (
        "policy", "tariff", "stimulus", "rate cut", "rate hike", "export control", "subsidy",
        "restriction", "ban", "quota", "政策", "关税", "降息", "加息", "补贴", "出口管制",
        "产业政策", "监管政策", "限购", "禁令", "配额",
    )):
        return EventType.POLICY
    if any(keyword in normalized for keyword in ("filing", "10-k", "10-q", "8-k", "prospectus")):
        return EventType.FILING
    if any(keyword in normalized for keyword in ("announcement", "公告")):
        return EventType.ANNOUNCEMENT
    return EventType.NEWS


def infer_event_direction(text: str) -> EventDirection:
    normalized = text.lower()
    positive = (
        "beat", "beats", "tops", "above estimates", "raise", "raises", "raised", "surge", "record",
        "approval", "approved", "growth", "upgrade", "outperform", "buyback", "repurchase",
        "dividend increase", "positive profit alert", "profit alert", "contract win", "获批",
        "超预期", "大超预期", "上调", "上修", "增长", "预增", "扭亏", "增持", "回购",
        "中标", "创新高", "改善", "盈利能力提升", "订单增长", "突破",
    )
    negative = (
        "miss", "misses", "below estimates", "cut", "cuts", "lowered", "drop", "plunge", "downgrade",
        "underperform", "investigation", "probe", "lawsuit", "litigation", "recall", "layoff",
        "profit warning", "loss warning", "fine", "penalty", "sanction", "default", "bankruptcy",
        "slump", "weak demand", "margin pressure", "guidance lowered", "guidance cut", "delisting risk",
        "fraud", "restatement", "impairment", "short seller", "resignation",
        "不及预期", "大幅不及预期", "下调", "下修", "预减", "预亏", "亏损", "处罚", "罚款",
        "调查", "立案", "诉讼", "仲裁", "减持", "暴跌", "违约", "退市风险", "计提减值",
        "商誉减值", "业绩承压", "需求疲软", "毛利率下降", "停产", "召回", "辞任",
    )
    if any(keyword in normalized for keyword in negative):
        return EventDirection.NEGATIVE
    if any(keyword in normalized for keyword in positive):
        return EventDirection.POSITIVE
    return EventDirection.NEUTRAL if normalized else EventDirection.UNKNOWN


def infer_event_intensity(text: str) -> EventIntensity:
    normalized = text.lower()
    if any(keyword in normalized for keyword in (
        "8-k", "merger", "acquisition", "discloseable transaction", "connected transaction",
        "investigation", "bankruptcy", "default", "profit warning", "major", "重大", "重组",
        "并购", "诉讼", "处罚", "立案", "问询函", "警示函", "退市风险", "控制权变更",
        "重大合同", "重大诉讼", "行政处罚", "wells notice", "delisting risk",
    )):
        return EventIntensity.MAJOR
    if any(keyword in normalized for keyword in ("update", "commentary", "preview", "rumor", "传闻", "快讯")):
        return EventIntensity.LOW
    return EventIntensity.NORMAL


def infer_guidance_bucket(text: str) -> GuidanceBucket:
    normalized = text.lower()
    if any(keyword in normalized for keyword in (
        "guidance raise", "raises guidance", "raised guidance", "outlook raised", "raises outlook",
        "positive profit alert", "profit alert", "guidance above", "raises forecast",
        "上调指引", "上修", "预增", "扭亏", "盈利预喜", "上调业绩预告", "业绩预告上修",
    )):
        return GuidanceBucket.RAISE
    if any(keyword in normalized for keyword in (
        "guidance cut", "cuts guidance", "cut guidance", "outlook lowered", "lowers outlook",
        "guidance below", "lowers forecast", "profit warning", "loss warning", "margin warning",
        "下调指引", "下修", "预减", "预亏", "盈利警告", "盈利预警", "业绩预告下修",
        "下调业绩预告", "业绩承压",
    )):
        return GuidanceBucket.CUT
    if "guidance" in normalized or "指引" in normalized or "outlook" in normalized:
        return GuidanceBucket.MAINTAIN
    return GuidanceBucket.UNKNOWN


def infer_surprise_bucket(text: str) -> SurpriseBucket:
    normalized = text.lower()
    if any(keyword in normalized for keyword in ("big beat", "crushes", "far above", "大超预期", "大幅超预期", "大幅预增")):
        return SurpriseBucket.BIG_BEAT
    if any(keyword in normalized for keyword in ("beat", "beats", "tops estimates", "above estimates", "超预期", "预增", "盈利预喜", "扭亏")):
        return SurpriseBucket.BEAT
    if any(keyword in normalized for keyword in ("big miss", "far below", "大幅不及预期", "大幅预减", "大幅预亏", "大幅亏损")):
        return SurpriseBucket.BIG_MISS
    if any(keyword in normalized for keyword in ("miss", "misses", "below estimates", "profit warning", "不及预期", "预减", "预亏", "盈利警告", "盈利预警")):
        return SurpriseBucket.MISS
    if any(keyword in normalized for keyword in ("inline", "in line", "符合预期")):
        return SurpriseBucket.INLINE
    return SurpriseBucket.UNKNOWN


def _provider_source_tier(provider: DataProvider) -> EventSourceTier:
    if provider == DataProvider.SEC:
        return EventSourceTier.REGULATORY
    if provider == DataProvider.CNINFO:
        return EventSourceTier.EXCHANGE
    if provider == DataProvider.YFINANCE:
        return EventSourceTier.AGGREGATOR
    return EventSourceTier.MAINSTREAM_NEWS if provider == DataProvider.NEWSWIRE else EventSourceTier.AGGREGATOR


def _coerce_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise ValueError(f"Unsupported date value: {value!r}")


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _as_yfinance_row(row: YFinancePriceRow | Mapping[str, JsonValue]) -> YFinancePriceRow:
    return row if isinstance(row, YFinancePriceRow) else YFinancePriceRow.model_validate(row)


def _as_akshare_row(row: AksharePriceRow | Mapping[str, JsonValue]) -> AksharePriceRow:
    return row if isinstance(row, AksharePriceRow) else AksharePriceRow.model_validate(row)


def _as_sec_filing_row(row: SecFilingRow | Mapping[str, JsonValue]) -> SecFilingRow:
    return row if isinstance(row, SecFilingRow) else SecFilingRow.model_validate(row)


def _as_cn_announcement_row(row: CnAnnouncementRow | Mapping[str, JsonValue]) -> CnAnnouncementRow:
    return row if isinstance(row, CnAnnouncementRow) else CnAnnouncementRow.model_validate(row)


def _as_news_row(row: NewsRow | Mapping[str, JsonValue]) -> NewsRow:
    return row if isinstance(row, NewsRow) else NewsRow.model_validate(row)


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()
