from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from investment_research.training.models import CoverageGroup, CoveragePreset, DataProvider, InstrumentType, Market


TARGET_MARKET_TYPE_COUNTS: dict[Market, dict[InstrumentType, int]] = {
    Market.US: {
        InstrumentType.EQUITY: 28,
        InstrumentType.ETF: 12,
        InstrumentType.INDEX: 8,
    },
    Market.CN: {
        InstrumentType.EQUITY: 28,
        InstrumentType.ETF: 12,
        InstrumentType.INDEX: 8,
    },
    Market.HK: {
        InstrumentType.EQUITY: 8,
        InstrumentType.ETF: 4,
        InstrumentType.INDEX: 4,
    },
    Market.JP: {
        InstrumentType.EQUITY: 8,
        InstrumentType.ETF: 4,
        InstrumentType.INDEX: 4,
    },
}

TARGET_MARKET_TOTALS: dict[Market, int] = {
    market: sum(counts.values()) for market, counts in TARGET_MARKET_TYPE_COUNTS.items()
}

TARGET_COVERAGE_GROUP_COUNTS: dict[Market, dict[CoverageGroup, int]] = {
    Market.US: {
        CoverageGroup.US_CORE: 18,
        CoverageGroup.CHINA_ADR: 10,
        CoverageGroup.ETF: 12,
        CoverageGroup.INDEX: 8,
    },
    Market.CN: {
        CoverageGroup.CN_A_SHARE: 28,
        CoverageGroup.ETF: 12,
        CoverageGroup.INDEX: 8,
    },
    Market.HK: {
        CoverageGroup.HK_PROXY: 8,
        CoverageGroup.ETF: 4,
        CoverageGroup.INDEX: 4,
    },
    Market.JP: {
        CoverageGroup.JP_PROXY: 8,
        CoverageGroup.ETF: 4,
        CoverageGroup.INDEX: 4,
    },
}


def _preset(
    symbol: str,
    *,
    market: Market,
    instrument_type: InstrumentType,
    name: str,
    currency: str,
    exchange: str,
    industry_key: str,
    benchmark_symbol: str,
    sector_reference_symbol: str,
    style_reference_symbol: str,
    primary_provider: DataProvider,
    coverage_group: CoverageGroup,
    aliases: Iterable[str] = (),
) -> CoveragePreset:
    return CoveragePreset(
        symbol=symbol,
        market=market,
        instrument_type=instrument_type,
        coverage_group=coverage_group,
        name=name,
        currency=currency,
        exchange=exchange,
        industry_key=industry_key,
        benchmark_symbol=benchmark_symbol,
        sector_reference_symbol=sector_reference_symbol,
        style_reference_symbol=style_reference_symbol,
        primary_provider=primary_provider,
        aliases=list(aliases),
    )


def _us_presets() -> list[CoveragePreset]:
    equities = [
        ("AAPL", "Apple", "technology"),
        ("MSFT", "Microsoft", "technology"),
        ("NVDA", "NVIDIA", "semiconductors"),
        ("AMZN", "Amazon", "consumer_internet"),
        ("GOOGL", "Alphabet", "communication_services"),
        ("META", "Meta Platforms", "communication_services"),
        ("TSLA", "Tesla", "autos"),
        ("JPM", "JPMorgan Chase", "financials"),
        ("BAC", "Bank of America", "financials"),
        ("XOM", "Exxon Mobil", "energy"),
        ("CVX", "Chevron", "energy"),
        ("UNH", "UnitedHealth", "healthcare"),
        ("JNJ", "Johnson & Johnson", "healthcare"),
        ("PFE", "Pfizer", "healthcare"),
        ("WMT", "Walmart", "consumer_defensive"),
        ("COST", "Costco", "consumer_defensive"),
        ("HD", "Home Depot", "consumer_cyclical"),
        ("CRM", "Salesforce", "software"),
    ]
    presets = [
        _preset(
            symbol,
            market=Market.US,
            instrument_type=InstrumentType.EQUITY,
            name=name,
            currency="USD",
            exchange="XNYS" if symbol in {"JPM", "BAC", "XOM", "CVX", "UNH", "JNJ", "PFE", "WMT", "HD", "CRM", "ORCL", "IBM"} else "XNAS",
            industry_key=industry,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="XLK" if industry in {"technology", "semiconductors", "software"} else "SPY",
            style_reference_symbol="QQQ",
            primary_provider=DataProvider.YFINANCE,
            coverage_group=CoverageGroup.US_CORE,
        )
        for symbol, name, industry in equities
    ]
    china_adrs = [
        ("BABA", "Alibaba ADR", "china_internet", "XNYS"),
        ("JD", "JD.com ADR", "china_internet", "XNAS"),
        ("PDD", "PDD Holdings ADR", "china_internet", "XNAS"),
        ("BIDU", "Baidu ADR", "china_internet", "XNAS"),
        ("NTES", "NetEase ADR", "china_internet", "XNAS"),
        ("TME", "Tencent Music ADR", "china_media", "XNYS"),
        ("LI", "Li Auto ADR", "china_ev", "XNAS"),
        ("NIO", "NIO ADR", "china_ev", "XNYS"),
        ("XPEV", "XPeng ADR", "china_ev", "XNYS"),
        ("BEKE", "KE Holdings ADR", "china_real_estate", "XNYS"),
    ]
    presets.extend(
        _preset(
            symbol,
            market=Market.US,
            instrument_type=InstrumentType.EQUITY,
            name=name,
            currency="USD",
            exchange=exchange,
            industry_key=industry,
            benchmark_symbol="^GSPC",
            sector_reference_symbol="KWEB",
            style_reference_symbol="QQQ",
            primary_provider=DataProvider.YFINANCE,
            coverage_group=CoverageGroup.CHINA_ADR,
        )
        for symbol, name, industry, exchange in china_adrs
    )
    presets.extend(
        [
            _preset("SPY", market=Market.US, instrument_type=InstrumentType.ETF, name="SPDR S&P 500 ETF", currency="USD", exchange="ARCX", industry_key="broad_market", benchmark_symbol="^GSPC", sector_reference_symbol="SPY", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("QQQ", market=Market.US, instrument_type=InstrumentType.ETF, name="Invesco QQQ Trust", currency="USD", exchange="XNAS", industry_key="growth_style", benchmark_symbol="^NDX", sector_reference_symbol="QQQ", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("XLK", market=Market.US, instrument_type=InstrumentType.ETF, name="Technology Select Sector SPDR", currency="USD", exchange="ARCX", industry_key="technology", benchmark_symbol="^GSPC", sector_reference_symbol="XLK", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("SOXX", market=Market.US, instrument_type=InstrumentType.ETF, name="iShares Semiconductor ETF", currency="USD", exchange="XNAS", industry_key="semiconductors", benchmark_symbol="^NDX", sector_reference_symbol="SOXX", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("XLE", market=Market.US, instrument_type=InstrumentType.ETF, name="Energy Select Sector SPDR", currency="USD", exchange="ARCX", industry_key="energy", benchmark_symbol="^GSPC", sector_reference_symbol="XLE", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("XLF", market=Market.US, instrument_type=InstrumentType.ETF, name="Financial Select Sector SPDR", currency="USD", exchange="ARCX", industry_key="financials", benchmark_symbol="^GSPC", sector_reference_symbol="XLF", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("XLV", market=Market.US, instrument_type=InstrumentType.ETF, name="Health Care Select Sector SPDR", currency="USD", exchange="ARCX", industry_key="healthcare", benchmark_symbol="^GSPC", sector_reference_symbol="XLV", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("XLY", market=Market.US, instrument_type=InstrumentType.ETF, name="Consumer Discretionary Select Sector SPDR", currency="USD", exchange="ARCX", industry_key="consumer_cyclical", benchmark_symbol="^GSPC", sector_reference_symbol="XLY", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("XLP", market=Market.US, instrument_type=InstrumentType.ETF, name="Consumer Staples Select Sector SPDR", currency="USD", exchange="ARCX", industry_key="consumer_defensive", benchmark_symbol="^GSPC", sector_reference_symbol="XLP", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("IWM", market=Market.US, instrument_type=InstrumentType.ETF, name="iShares Russell 2000 ETF", currency="USD", exchange="ARCX", industry_key="small_cap", benchmark_symbol="^RUT", sector_reference_symbol="IWM", style_reference_symbol="IWM", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("KWEB", market=Market.US, instrument_type=InstrumentType.ETF, name="KraneShares CSI China Internet ETF", currency="USD", exchange="ARCX", industry_key="china_internet", benchmark_symbol="^GSPC", sector_reference_symbol="KWEB", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("VEA", market=Market.US, instrument_type=InstrumentType.ETF, name="Vanguard Developed Markets ETF", currency="USD", exchange="ARCX", industry_key="developed_ex_us", benchmark_symbol="^GSPC", sector_reference_symbol="VEA", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.ETF),
            _preset("^GSPC", market=Market.US, instrument_type=InstrumentType.INDEX, name="S&P 500", currency="USD", exchange="INDEX", industry_key="broad_market", benchmark_symbol="^GSPC", sector_reference_symbol="SPY", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^NDX", market=Market.US, instrument_type=InstrumentType.INDEX, name="NASDAQ 100", currency="USD", exchange="INDEX", industry_key="growth_style", benchmark_symbol="^NDX", sector_reference_symbol="QQQ", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^IXIC", market=Market.US, instrument_type=InstrumentType.INDEX, name="NASDAQ Composite", currency="USD", exchange="INDEX", industry_key="growth_style", benchmark_symbol="^IXIC", sector_reference_symbol="QQQ", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^RUT", market=Market.US, instrument_type=InstrumentType.INDEX, name="Russell 2000", currency="USD", exchange="INDEX", industry_key="small_cap", benchmark_symbol="^RUT", sector_reference_symbol="SPY", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^DJI", market=Market.US, instrument_type=InstrumentType.INDEX, name="Dow Jones Industrial Average", currency="USD", exchange="INDEX", industry_key="large_value", benchmark_symbol="^DJI", sector_reference_symbol="SPY", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^NYA", market=Market.US, instrument_type=InstrumentType.INDEX, name="NYSE Composite", currency="USD", exchange="INDEX", industry_key="broad_market", benchmark_symbol="^NYA", sector_reference_symbol="SPY", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^SOX", market=Market.US, instrument_type=InstrumentType.INDEX, name="PHLX Semiconductor", currency="USD", exchange="INDEX", industry_key="semiconductors", benchmark_symbol="^SOX", sector_reference_symbol="SOXX", style_reference_symbol="QQQ", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
            _preset("^VIX", market=Market.US, instrument_type=InstrumentType.INDEX, name="CBOE Volatility Index", currency="USD", exchange="INDEX", industry_key="volatility", benchmark_symbol="^VIX", sector_reference_symbol="SPY", style_reference_symbol="SPY", primary_provider=DataProvider.YFINANCE, coverage_group=CoverageGroup.INDEX),
        ]
    )
    return presets


def _cn_presets() -> list[CoveragePreset]:
    equities = [
        "600519.SH", "601318.SH", "600036.SH", "600900.SH", "600276.SH", "601888.SH",
        "000001.SZ", "000002.SZ", "000333.SZ", "000651.SZ", "002415.SZ", "002594.SZ",
        "300750.SZ", "300760.SZ", "600030.SH", "600031.SH", "600309.SH", "600436.SH",
        "600887.SH", "601012.SH", "601398.SH", "601857.SH", "601988.SH", "603288.SH",
        "000858.SZ", "002475.SZ", "300059.SZ", "601899.SH",
    ]
    presets = [
        _preset(
            symbol,
            market=Market.CN,
            instrument_type=InstrumentType.EQUITY,
            name=f"CN Equity {symbol}",
            currency="CNY",
            exchange="XSHG" if symbol.endswith(".SH") else "XSHE",
            industry_key="cn_large_cap",
            benchmark_symbol="000300.SH",
            sector_reference_symbol="510300.SH",
            style_reference_symbol="399006.SZ",
            primary_provider=DataProvider.AKSHARE,
            coverage_group=CoverageGroup.CN_A_SHARE,
            aliases=(f"SH{symbol[:6]}",) if symbol.endswith(".SH") else (f"SZ{symbol[:6]}",),
        )
        for symbol in equities
    ]
    presets.extend(
        [
            _preset("510300.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="CSI 300 ETF", currency="CNY", exchange="XSHG", industry_key="cn_broad_market", benchmark_symbol="000300.SH", sector_reference_symbol="510300.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("510050.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="SSE 50 ETF", currency="CNY", exchange="XSHG", industry_key="cn_large_cap", benchmark_symbol="000300.SH", sector_reference_symbol="510050.SH", style_reference_symbol="000001.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("159919.SZ", market=Market.CN, instrument_type=InstrumentType.ETF, name="CSI 300 ETF SZ", currency="CNY", exchange="XSHE", industry_key="cn_large_cap", benchmark_symbol="000300.SH", sector_reference_symbol="159919.SZ", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("512100.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="CSI 1000 ETF", currency="CNY", exchange="XSHG", industry_key="cn_small_cap", benchmark_symbol="000905.SH", sector_reference_symbol="512100.SH", style_reference_symbol="000905.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("159915.SZ", market=Market.CN, instrument_type=InstrumentType.ETF, name="ChiNext ETF", currency="CNY", exchange="XSHE", industry_key="cn_growth", benchmark_symbol="399006.SZ", sector_reference_symbol="159915.SZ", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("510500.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="CSI 500 ETF", currency="CNY", exchange="XSHG", industry_key="cn_mid_cap", benchmark_symbol="000905.SH", sector_reference_symbol="510500.SH", style_reference_symbol="000905.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("588000.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="STAR 50 ETF", currency="CNY", exchange="XSHG", industry_key="cn_star", benchmark_symbol="000688.SH", sector_reference_symbol="588000.SH", style_reference_symbol="000688.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("512880.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="Securities ETF", currency="CNY", exchange="XSHG", industry_key="cn_financials", benchmark_symbol="000300.SH", sector_reference_symbol="512880.SH", style_reference_symbol="510300.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("512800.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="Bank ETF", currency="CNY", exchange="XSHG", industry_key="cn_banks", benchmark_symbol="000300.SH", sector_reference_symbol="512800.SH", style_reference_symbol="510300.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("512010.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="Pharmaceutical ETF", currency="CNY", exchange="XSHG", industry_key="cn_healthcare", benchmark_symbol="000300.SH", sector_reference_symbol="512010.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("515790.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="Photovoltaic ETF", currency="CNY", exchange="XSHG", industry_key="cn_new_energy", benchmark_symbol="399006.SZ", sector_reference_symbol="515790.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("515030.SH", market=Market.CN, instrument_type=InstrumentType.ETF, name="New Energy Vehicle ETF", currency="CNY", exchange="XSHG", industry_key="cn_ev", benchmark_symbol="399006.SZ", sector_reference_symbol="515030.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.ETF),
            _preset("000300.SH", market=Market.CN, instrument_type=InstrumentType.INDEX, name="CSI 300", currency="CNY", exchange="XSHG", industry_key="cn_broad_market", benchmark_symbol="000300.SH", sector_reference_symbol="510300.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
            _preset("000905.SH", market=Market.CN, instrument_type=InstrumentType.INDEX, name="CSI 500", currency="CNY", exchange="XSHG", industry_key="cn_mid_cap", benchmark_symbol="000905.SH", sector_reference_symbol="512100.SH", style_reference_symbol="000905.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
            _preset("000001.SH", market=Market.CN, instrument_type=InstrumentType.INDEX, name="SSE Composite", currency="CNY", exchange="XSHG", industry_key="cn_broad_market", benchmark_symbol="000001.SH", sector_reference_symbol="510050.SH", style_reference_symbol="000300.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
            _preset("399006.SZ", market=Market.CN, instrument_type=InstrumentType.INDEX, name="ChiNext Index", currency="CNY", exchange="XSHE", industry_key="cn_growth", benchmark_symbol="399006.SZ", sector_reference_symbol="159919.SZ", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX, aliases=("CHINEXT",)),
            _preset("000688.SH", market=Market.CN, instrument_type=InstrumentType.INDEX, name="STAR 50", currency="CNY", exchange="XSHG", industry_key="cn_star", benchmark_symbol="000688.SH", sector_reference_symbol="588000.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
            _preset("000016.SH", market=Market.CN, instrument_type=InstrumentType.INDEX, name="SSE 50", currency="CNY", exchange="XSHG", industry_key="cn_large_cap", benchmark_symbol="000016.SH", sector_reference_symbol="510050.SH", style_reference_symbol="000300.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
            _preset("399001.SZ", market=Market.CN, instrument_type=InstrumentType.INDEX, name="SZSE Component", currency="CNY", exchange="XSHE", industry_key="cn_broad_market", benchmark_symbol="399001.SZ", sector_reference_symbol="510300.SH", style_reference_symbol="399006.SZ", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
            _preset("399905.SZ", market=Market.CN, instrument_type=InstrumentType.INDEX, name="CSI 500 SZ", currency="CNY", exchange="XSHE", industry_key="cn_mid_cap", benchmark_symbol="399905.SZ", sector_reference_symbol="510500.SH", style_reference_symbol="000905.SH", primary_provider=DataProvider.AKSHARE, coverage_group=CoverageGroup.INDEX),
        ]
    )
    return presets


def _proxy_presets(market: Market, *, symbols: list[str], etfs: list[str], indices: list[str], currency: str, exchange: str, coverage_group: CoverageGroup, benchmark: str, provider: DataProvider) -> list[CoveragePreset]:
    presets = [
        _preset(
            symbol,
            market=market,
            instrument_type=InstrumentType.EQUITY,
            name=f"{market.value.upper()} Equity {symbol}",
            currency=currency,
            exchange=exchange,
            industry_key=f"{market.value}_large_cap",
            benchmark_symbol=benchmark,
            sector_reference_symbol=etfs[0],
            style_reference_symbol=etfs[1],
            primary_provider=provider,
            coverage_group=coverage_group,
        )
        for symbol in symbols
    ]
    presets.extend(
        _preset(symbol, market=market, instrument_type=InstrumentType.ETF, name=f"{market.value.upper()} ETF {symbol}", currency=currency, exchange=exchange, industry_key=f"{market.value}_etf", benchmark_symbol=benchmark, sector_reference_symbol=symbol, style_reference_symbol=etfs[1], primary_provider=provider, coverage_group=CoverageGroup.ETF)
        for symbol in etfs
    )
    presets.extend(
        _preset(symbol, market=market, instrument_type=InstrumentType.INDEX, name=f"{market.value.upper()} Index {symbol}", currency=currency, exchange="INDEX", industry_key=f"{market.value}_index", benchmark_symbol=symbol, sector_reference_symbol=etfs[0], style_reference_symbol=etfs[1], primary_provider=provider, coverage_group=CoverageGroup.INDEX)
        for symbol in indices
    )
    return presets


def _build_universe() -> dict[str, CoveragePreset]:
    hk_symbols = [
        "0700.HK", "9988.HK", "3690.HK", "9618.HK", "0941.HK", "1299.HK", "0939.HK", "1398.HK",
    ]
    jp_symbols = [
        "7203.T", "6758.T", "9984.T", "6861.T", "8306.T", "9432.T", "6501.T", "8035.T",
    ]
    presets = [
        *_us_presets(),
        *_cn_presets(),
        *_proxy_presets(
            Market.HK,
            symbols=hk_symbols,
            etfs=["2800.HK", "2828.HK", "3033.HK", "3067.HK"],
            indices=["^HSI", "^HSCE", "^HSCC", "2833.HK"],
            currency="HKD",
            exchange="XHKG",
            coverage_group=CoverageGroup.HK_PROXY,
            benchmark="^HSI",
            provider=DataProvider.YFINANCE,
        ),
        *_proxy_presets(
            Market.JP,
            symbols=jp_symbols,
            etfs=["1306.T", "1321.T", "1346.T", "1475.T"],
            indices=["^N225", "1591.T", "1592.T", "1348.T"],
            currency="JPY",
            exchange="XTKS",
            coverage_group=CoverageGroup.JP_PROXY,
            benchmark="^N225",
            provider=DataProvider.YFINANCE,
        ),
    ]
    return {preset.symbol: preset for preset in presets}


UNIVERSE_PRESETS: dict[str, CoveragePreset] = _build_universe()


def _coerce_market(market: Market | str) -> Market:
    return market if isinstance(market, Market) else Market(str(market).lower())


def iter_market_presets(market: Market | str | None = None) -> list[CoveragePreset]:
    if market is None:
        return list(UNIVERSE_PRESETS.values())
    resolved = _coerce_market(market)
    return [preset for preset in UNIVERSE_PRESETS.values() if preset.market == resolved]


def market_symbols(market: Market | str) -> list[str]:
    return [preset.symbol for preset in iter_market_presets(market)]


def market_distribution() -> dict[str, dict[str, int]]:
    distribution: dict[str, Counter[str]] = defaultdict(Counter)
    for preset in UNIVERSE_PRESETS.values():
        distribution[preset.market.value][preset.instrument_type.value] += 1
    return {market: dict(counts) for market, counts in distribution.items()}


def validate_universe_distribution() -> list[str]:
    issues: list[str] = []
    if len(UNIVERSE_PRESETS) != 128:
        issues.append(f"Expected 128 presets, found {len(UNIVERSE_PRESETS)}")
    distribution = market_distribution()
    for market, expected_counts in TARGET_MARKET_TYPE_COUNTS.items():
        expected_total = TARGET_MARKET_TOTALS[market]
        if len(market_symbols(market)) != expected_total:
            issues.append(f"{market.value} expected {expected_total} symbols")
        for instrument_type, expected in expected_counts.items():
            actual = distribution.get(market.value, {}).get(instrument_type.value, 0)
            if actual != expected:
                issues.append(f"{market.value}/{instrument_type.value} expected {expected}, found {actual}")
        actual_groups = Counter(preset.coverage_group for preset in iter_market_presets(market))
        for coverage_group, expected in TARGET_COVERAGE_GROUP_COUNTS[market].items():
            actual = actual_groups.get(coverage_group, 0)
            if actual != expected:
                issues.append(f"{market.value}/{coverage_group.value} expected {expected}, found {actual}")
    for preset in UNIVERSE_PRESETS.values():
        required = {
            "industry_key": preset.industry_key,
            "benchmark_symbol": preset.benchmark_symbol,
            "sector_reference_symbol": preset.sector_reference_symbol,
            "style_reference_symbol": preset.style_reference_symbol,
            "primary_provider": preset.primary_provider,
        }
        missing = [field for field, value in required.items() if not value]
        if missing:
            issues.append(f"{preset.symbol} missing required metadata: {','.join(missing)}")
    return issues


def benchmark_reference_symbols() -> list[str]:
    symbols: set[str] = set()
    for preset in UNIVERSE_PRESETS.values():
        symbols.update(
            symbol
            for symbol in [preset.benchmark_symbol, preset.sector_reference_symbol, preset.style_reference_symbol]
            if symbol
        )
    return sorted(symbols)
