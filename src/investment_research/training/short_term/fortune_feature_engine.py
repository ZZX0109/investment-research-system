"""Causal feature engine for the Fortune-inspired short-horizon candidates.

The original Fortune project gets much of its signal from volatility, market
regime and cross-sectional structure.  This module implements those families
without treating an API's *current* value as historical training data:

* technical trend/range features (BB width, support/resistance, MACD, KDJ);
* per-symbol, rolling GARCH(1,1) conditional-volatility features;
* a causal Gaussian HMM of the market return/volatility state;
* rolling correlation-network community and cohesion features; and
* as-of aligned LPR/SHIBOR and optional northbound-holding features.

All functions consume only observations at or before a row's date.  The panel
is intentionally separate from the deployed lightweight CatBoost runner: it is
a candidate-training input, not a silent replacement for an existing model.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import logging
from math import exp, log, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np


FORTUNE_ENHANCED_FEATURES = [
    "ret_1d", "ret_5d", "ret_20d", "vol_20d", "volume_ratio_5d",
    "ma_5_ratio", "ma_20_ratio", "range_20d", "symbol",
    "volatility_30d", "volatility_30pct", "volatility_70pct",
    "ma250_slope", "bb_width_20", "bb_width_ma60",
    "distance_support_120d", "distance_resistance_120d",
    "macd", "macd_signal", "macd_histogram", "kdj_k", "kdj_d", "kdj_j",
    "calendar_weekday", "calendar_month",
    "garch_conditional_vol", "garch_vol_ratio_20", "garch_persistence",
    "garch_alpha", "garch_beta",
    "lstm_garch_residual_vol",
    "hmm_bear_probability", "hmm_range_probability", "hmm_bull_probability",
    "hmm_regime", "hmm_regime_duration",
    "network_cohesion", "network_degree", "network_betweenness",
    "network_community_size", "network_regime_interaction",
    "network_garch_interaction",
    "lpr_1y", "lpr_5y", "shibor_overnight", "shibor_3m", "shibor_term_spread",
    "northbound_holding_pct", "northbound_holding_change_5d",
    "northbound_value_change_1d", "northbound_value_change_5d",
]

_FEATURE_CACHE_SCHEMA = "fortune-feature-cache-v3"

FORTUNE_CATEGORICAL_FEATURES = ["symbol"]


def _nan() -> float:
    return float("nan")


def _finite(value: object, default: float | None = None) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _nan() if default is None else default
    return parsed if np.isfinite(parsed) else (_nan() if default is None else default)


def _returns(closes: list[float]) -> np.ndarray:
    if len(closes) < 2:
        return np.array([], dtype=float)
    values = np.asarray(closes, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = values[1:] / values[:-1] - 1.0
    return out[np.isfinite(out)]


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2.0 / (span + 1.0)
    result = np.empty(len(values), dtype=float)
    result[0] = values[0]
    for index in range(1, len(values)):
        result[index] = alpha * values[index] + (1.0 - alpha) * result[index - 1]
    return result


@dataclass(frozen=True)
class GarchParameters:
    omega: float
    alpha: float
    beta: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta


def fit_garch11(returns: Iterable[float]) -> GarchParameters | None:
    """Fit a compact GARCH(1,1) by Gaussian quasi maximum likelihood.

    ``arch`` is excellent for offline research, but this deterministic scipy
    implementation keeps candidate construction runnable in the base training
    environment as well.  The parameterisation enforces alpha + beta < 0.999.
    """
    values = np.asarray(list(returns), dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 30:
        return None
    variance = max(float(np.var(values)), 1e-10)
    # Use the standard ``arch`` implementation when the training extra is
    # installed.  The compact optimizer below is a deterministic fallback for
    # local/demo environments where optional scientific packages are absent.
    try:
        from arch import arch_model

        fitted = arch_model(values * 100.0, mean="Zero", vol="GARCH", p=1, q=1, rescale=False).fit(disp="off", show_warning=False)
        params = fitted.params
        omega = float(params.get("omega", _nan())) / 10_000.0
        alpha = float(params.get("alpha[1]", _nan()))
        beta = float(params.get("beta[1]", _nan()))
        if np.isfinite(omega) and np.isfinite(alpha) and np.isfinite(beta) and omega > 0 and alpha >= 0 and beta >= 0 and alpha + beta < 1.0:
            return GarchParameters(omega, alpha, beta)
    except (ImportError, ArithmeticError, ValueError, OverflowError):
        pass
    try:
        from scipy.optimize import minimize
    except ImportError:  # pragma: no cover - scipy is a project dependency
        return GarchParameters(variance * 0.05, 0.06, 0.89)

    def unpack(raw: np.ndarray) -> GarchParameters:
        omega = exp(float(raw[0]))
        alpha = 0.45 / (1.0 + exp(-float(raw[1])))
        beta = (0.999 - alpha) / (1.0 + exp(-float(raw[2])))
        return GarchParameters(omega=omega, alpha=alpha, beta=beta)

    def objective(raw: np.ndarray) -> float:
        params = unpack(raw)
        conditional = variance
        total = 0.0
        for value in values:
            conditional = max(
                params.omega + params.alpha * value * value + params.beta * conditional,
                1e-12,
            )
            total += log(conditional) + (value * value / conditional)
        return total / len(values)

    initial = np.array([log(variance * 0.05), -1.8, 2.7], dtype=float)
    try:
        result = minimize(objective, initial, method="L-BFGS-B", options={"maxiter": 80})
        return unpack(result.x if result.success and np.all(np.isfinite(result.x)) else initial)
    except (ArithmeticError, ValueError, OverflowError):
        return GarchParameters(variance * 0.05, 0.06, 0.89)


def symbol_feature_rows(
    symbol: str,
    dates: list[date],
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    *,
    garch_lookback: int = 252,
    garch_refit_interval: int = 20,
) -> dict[date, dict[str, float | str]]:
    """Build features for each date using only that date's and prior bars."""
    if not (len(dates) == len(closes) == len(highs) == len(lows) == len(volumes)):
        raise ValueError("symbol feature inputs must have aligned lengths")
    rows: dict[date, dict[str, float | str]] = {}
    active_garch: GarchParameters | None = None
    conditional_var: float | None = None
    for index, current_date in enumerate(dates):
        prefix_close = closes[: index + 1]
        prefix_high = highs[: index + 1]
        prefix_low = lows[: index + 1]
        prefix_volume = volumes[: index + 1]
        returns = _returns(prefix_close)
        if len(returns) >= 30 and (active_garch is None or index % garch_refit_interval == 0):
            active_garch = fit_garch11(returns[-garch_lookback:])
            conditional_var = float(np.var(returns[-min(len(returns), 20):]))
        latest_return = float(returns[-1]) if len(returns) else 0.0
        if active_garch is not None:
            conditional_var = max(
                active_garch.omega + active_garch.alpha * latest_return * latest_return
                + active_garch.beta * (conditional_var or latest_return * latest_return),
                1e-12,
            )
        row = _technical_features(symbol, current_date, prefix_close, prefix_high, prefix_low, prefix_volume)
        recent_returns = returns[-20:]
        realized_vol = float(np.std(recent_returns, ddof=0)) if len(recent_returns) >= 2 else _nan()
        conditional_vol = sqrt(conditional_var) if conditional_var is not None else _nan()
        row.update({
            "garch_conditional_vol": conditional_vol,
            "garch_vol_ratio_20": conditional_vol / realized_vol if np.isfinite(conditional_vol) and realized_vol > 0 else _nan(),
            "garch_persistence": active_garch.persistence if active_garch else _nan(),
            "garch_alpha": active_garch.alpha if active_garch else _nan(),
            "garch_beta": active_garch.beta if active_garch else _nan(),
        })
        rows[current_date] = row
    return rows


def _technical_features(
    symbol: str,
    current_date: date,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
) -> dict[str, float | str]:
    count = len(closes)
    close = closes[-1]

    def ret(back: int) -> float:
        return close / closes[-1 - back] - 1.0 if count > back and closes[-1 - back] else _nan()

    returns = _returns(closes)
    vol = lambda window: float(np.std(returns[-window:], ddof=0)) if len(returns) >= 2 else _nan()
    ma = lambda window: float(np.mean(closes[-window:])) if count >= window else _nan()
    ma5, ma20 = ma(5), ma(20)
    ma250 = ma(250)
    ma250_old = float(np.mean(closes[-270:-20])) if count >= 270 else _nan()
    mid20 = ma20
    std20 = float(np.std(closes[-20:], ddof=0)) if count >= 20 else _nan()
    bb_width = (4.0 * std20 / mid20) if np.isfinite(std20) and mid20 else _nan()
    widths = []
    if count >= 79:
        for end in range(count - 59, count + 1):
            window = closes[end - 20:end]
            mid = float(np.mean(window))
            widths.append(4.0 * float(np.std(window, ddof=0)) / mid if mid else _nan())
    bb_width_ma60 = float(np.nanmean(widths)) if widths else _nan()
    support = min(lows[-120:]) if count >= 120 else _nan()
    resistance = max(highs[-120:]) if count >= 120 else _nan()
    ema12 = _ema(np.asarray(closes, dtype=float), 12)
    ema26 = _ema(np.asarray(closes, dtype=float), 26)
    macd_line = float(ema12[-1] - ema26[-1]) if count >= 26 else _nan()
    macd_series = ema12 - ema26
    signal = float(_ema(macd_series, 9)[-1]) if count >= 35 else _nan()
    high9 = max(highs[-9:]) if count >= 9 else _nan()
    low9 = min(lows[-9:]) if count >= 9 else _nan()
    rsv = 100.0 * (close - low9) / (high9 - low9) if np.isfinite(high9) and high9 > low9 else _nan()
    k = rsv if np.isfinite(rsv) else _nan()
    d = k if np.isfinite(k) else _nan()
    if count >= 11:
        k, d = 50.0, 50.0
        for offset in range(max(8, count - 20), count):
            h, l, c = max(highs[offset - 8:offset + 1]), min(lows[offset - 8:offset + 1]), closes[offset]
            observed = 100.0 * (c - l) / (h - l) if h > l else 50.0
            k = (2.0 * k + observed) / 3.0
            d = (2.0 * d + k) / 3.0
    volume_mean = float(np.mean(volumes[-5:])) if count >= 5 else _nan()
    return {
        "symbol": symbol,
        "ret_1d": ret(1), "ret_5d": ret(5), "ret_20d": ret(20),
        "vol_20d": vol(20), "volume_ratio_5d": volumes[-1] / volume_mean if volume_mean else _nan(),
        "ma_5_ratio": close / ma5 if np.isfinite(ma5) and ma5 else _nan(),
        "ma_20_ratio": close / ma20 if np.isfinite(ma20) and ma20 else _nan(),
        "range_20d": (max(highs[-20:]) - min(lows[-20:])) / close if count >= 20 and close else _nan(),
        "volatility_30d": vol(30),
        "volatility_30pct": float(np.percentile(np.abs(returns[-30:]), 30)) if len(returns) >= 30 else _nan(),
        "volatility_70pct": float(np.percentile(np.abs(returns[-30:]), 70)) if len(returns) >= 30 else _nan(),
        "ma250_slope": ma250 / ma250_old - 1.0 if np.isfinite(ma250) and np.isfinite(ma250_old) and ma250_old else _nan(),
        "bb_width_20": bb_width, "bb_width_ma60": bb_width_ma60,
        "distance_support_120d": close / support - 1.0 if np.isfinite(support) and support else _nan(),
        "distance_resistance_120d": close / resistance - 1.0 if np.isfinite(resistance) and resistance else _nan(),
        "macd": macd_line, "macd_signal": signal,
        "macd_histogram": macd_line - signal if np.isfinite(macd_line) and np.isfinite(signal) else _nan(),
        "kdj_k": k, "kdj_d": d, "kdj_j": 3.0 * k - 2.0 * d if np.isfinite(k) and np.isfinite(d) else _nan(),
        "calendar_weekday": float(current_date.weekday()), "calendar_month": float(current_date.month),
    }


class CausalMarketContext:
    """Compute HMM and correlation-network features without looking ahead."""

    def __init__(self, *, hmm_lookback: int = 252, network_lookback: int = 60, refresh_interval: int = 20) -> None:
        self.hmm_lookback = hmm_lookback
        self.network_lookback = network_lookback
        self.refresh_interval = refresh_interval

    def build(self, prices: Mapping[str, Mapping[date, float]]) -> dict[tuple[str, date], dict[str, float]]:
        dates = sorted({day for values in prices.values() for day in values})
        if not dates:
            return {}
        symbols = sorted(prices)
        matrix = np.full((len(dates), len(symbols)), np.nan)
        index_by_date = {day: index for index, day in enumerate(dates)}
        for col, symbol in enumerate(symbols):
            for day, close in prices[symbol].items():
                matrix[index_by_date[day], col] = close
        returns = np.full_like(matrix, np.nan)
        with np.errstate(divide="ignore", invalid="ignore"):
            returns[1:] = matrix[1:] / matrix[:-1] - 1.0
        observed = np.sum(np.isfinite(returns), axis=1)
        market_returns = np.divide(
            np.nansum(returns, axis=1), observed,
            out=np.zeros(len(dates), dtype=float), where=observed > 0,
        )
        hmm = self._hmm_features(dates, market_returns)
        network = self._network_features(dates, symbols, returns)
        result: dict[tuple[str, date], dict[str, float]] = {}
        for row, day in enumerate(dates):
            for col, symbol in enumerate(symbols):
                values = {**hmm[row], **network.get((symbol, day), {})}
                result[(symbol, day)] = values
        return result

    def _hmm_features(self, dates: list[date], market_returns: np.ndarray) -> list[dict[str, float]]:
        output: list[dict[str, float]] = []
        last = {"hmm_bear_probability": _nan(), "hmm_range_probability": _nan(), "hmm_bull_probability": _nan(), "hmm_regime": _nan(), "hmm_regime_duration": 0.0}
        prior_regime: int | None = None
        duration = 0
        for index in range(len(dates)):
            if index >= 60 and index % self.refresh_interval == 0:
                window = market_returns[max(0, index - self.hmm_lookback + 1):index + 1]
                fitted = _fit_and_filter_hmm(window)
                if fitted is not None:
                    probs, state_means = fitted
                    ordered = _order_regime_probabilities(probs, state_means)
                    regime = int(np.argmax(ordered))
                    duration = duration + 1 if regime == prior_regime else 1
                    prior_regime = regime
                    last = {
                        "hmm_bear_probability": float(ordered[0]),
                        "hmm_range_probability": float(ordered[1]),
                        "hmm_bull_probability": float(ordered[2]),
                        "hmm_regime": float(regime - 1),
                        "hmm_regime_duration": float(duration),
                    }
            elif prior_regime is not None:
                # The state is inferred at a fixed causal refresh cadence, but
                # its duration is measured in sessions, not in refit counts.
                duration += 1
                last["hmm_regime_duration"] = float(duration)
            output.append(dict(last))
        return output

    def _network_features(self, dates: list[date], symbols: list[str], returns: np.ndarray) -> dict[tuple[str, date], dict[str, float]]:
        try:
            import networkx as nx
        except ImportError:  # pragma: no cover - declared train dependency
            return {}
        output: dict[tuple[str, date], dict[str, float]] = {}
        latest: dict[str, dict[str, float]] = {}
        for index, day in enumerate(dates):
            if index >= self.network_lookback and index % self.refresh_interval == 0:
                window = returns[index - self.network_lookback + 1:index + 1]
                filled = np.nan_to_num(window, nan=0.0)
                # A newly listed/suspended symbol can have an all-zero return
                # window.  It has no meaningful correlations and must not
                # trigger NumPy divide-by-zero warnings or fabricated edges.
                active = np.std(filled, axis=0) > 1e-12
                corr = np.zeros((len(symbols), len(symbols)), dtype=float)
                if int(np.sum(active)) >= 2:
                    with np.errstate(invalid="ignore", divide="ignore"):
                        corr[np.ix_(active, active)] = np.corrcoef(filled[:, active], rowvar=False)
                graph = nx.Graph()
                graph.add_nodes_from(symbols)
                for left in range(len(symbols)):
                    for right in range(left + 1, len(symbols)):
                        weight = float(corr[left, right]) if np.isfinite(corr[left, right]) else 0.0
                        if weight >= 0.35:
                            graph.add_edge(symbols[left], symbols[right], weight=weight, distance=1.0 / max(weight, 1e-6))
                if graph.number_of_edges():
                    try:
                        communities = list(nx.community.louvain_communities(graph, weight="weight", seed=42))
                    except AttributeError:
                        communities = list(nx.community.greedy_modularity_communities(graph, weight="weight"))
                    communities = sorted((sorted(group) for group in communities), key=lambda group: group[0])
                    community_by_symbol = {symbol: (idx, len(group)) for idx, group in enumerate(communities) for symbol in group}
                    betweenness = nx.betweenness_centrality(graph, k=min(32, len(symbols)), weight="distance", seed=42)
                else:
                    community_by_symbol, betweenness = {}, {}
                latest = {}
                for symbol in symbols:
                    degree = graph.degree(symbol, weight="weight") if graph.has_node(symbol) else 0.0
                    community_id, community_size = community_by_symbol.get(symbol, (-1, 1))
                    latest[symbol] = {
                        "network_cohesion": float(degree) / max(1, len(symbols) - 1),
                        "network_degree": float(graph.degree(symbol)) / max(1, len(symbols) - 1),
                        "network_betweenness": float(betweenness.get(symbol, 0.0)),
                        "network_community_size": float(community_size),
                    }
            for symbol, values in latest.items():
                output[(symbol, day)] = dict(values)
        return output


def _fit_and_filter_hmm(returns: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Small diagonal Gaussian HMM with an EM fit; returns last-state posterior."""
    values = returns[np.isfinite(returns)]
    if len(values) < 60:
        return None
    volatility = np.array([np.std(values[max(0, i - 19):i + 1]) for i in range(len(values))])
    x = np.column_stack((values, volatility))
    states = 3
    try:
        from hmmlearn.hmm import GaussianHMM

        model = GaussianHMM(n_components=states, covariance_type="diag", n_iter=100, random_state=42, min_covar=1e-8)
        # Rolling windows can be nearly singular.  ``hmmlearn`` warns but still
        # returns probabilities in that case; those probabilities must not be
        # treated as a valid regime signal.  Fall through to the deterministic
        # local EM implementation instead.
        logger = logging.getLogger("hmmlearn.base")
        was_disabled = logger.disabled
        logger.disabled = True
        try:
            model.fit(x)
        finally:
            logger.disabled = was_disabled
        history = [float(value) for value in model.monitor_.history]
        if (
            not model.monitor_.converged
            or len(history) < 2
            or any(current + 1e-6 < previous for previous, current in zip(history, history[1:]))
            or not np.all(np.isfinite(model.means_))
        ):
            raise ValueError("non-converged rolling HMM")
        posterior = model.predict_proba(x)[-1]
        if not np.all(np.isfinite(posterior)):
            raise ValueError("invalid rolling HMM posterior")
        return posterior, model.means_[:, 0]
    except (ImportError, ValueError, ArithmeticError):
        pass
    ranked = np.argsort(x[:, 0])
    means = np.vstack([np.mean(x[group], axis=0) for group in np.array_split(ranked, states)])
    variances = np.vstack([np.maximum(np.var(x[group], axis=0), 1e-8) for group in np.array_split(ranked, states)])
    transition = np.full((states, states), 0.025)
    np.fill_diagonal(transition, 0.95)
    start = np.full(states, 1.0 / states)
    for _ in range(12):
        emission = _gaussian_emission(x, means, variances)
        alpha, scales = _forward(emission, transition, start)
        beta = _backward(emission, transition, scales)
        gamma = alpha * beta
        gamma /= np.maximum(gamma.sum(axis=1, keepdims=True), 1e-12)
        xi_sum = np.zeros_like(transition)
        for i in range(len(x) - 1):
            xi = alpha[i, :, None] * transition * emission[i + 1, None, :] * beta[i + 1, None, :]
            xi_sum += xi / max(float(xi.sum()), 1e-12)
        start = np.maximum(gamma[0], 1e-8)
        start /= start.sum()
        transition = xi_sum + 1e-6
        transition /= transition.sum(axis=1, keepdims=True)
        weights = np.maximum(gamma.sum(axis=0), 1e-8)
        means = (gamma.T @ x) / weights[:, None]
        for state in range(states):
            centered = x - means[state]
            variances[state] = np.maximum((gamma[:, state, None] * centered * centered).sum(axis=0) / weights[state], 1e-8)
    return gamma[-1], means[:, 0]


def _gaussian_emission(x: np.ndarray, means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    diff = x[:, None, :] - means[None, :, :]
    log_density = -0.5 * (np.log(2.0 * np.pi * variances)[None, :, :] + diff * diff / variances[None, :, :]).sum(axis=2)
    log_density -= np.max(log_density, axis=1, keepdims=True)
    density = np.exp(log_density)
    return density / np.maximum(density.sum(axis=1, keepdims=True), 1e-12)


def _forward(emission: np.ndarray, transition: np.ndarray, start: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    alpha = np.zeros_like(emission)
    scales = np.ones(len(emission))
    alpha[0] = start * emission[0]
    scales[0] = max(float(alpha[0].sum()), 1e-12)
    alpha[0] /= scales[0]
    for index in range(1, len(emission)):
        alpha[index] = (alpha[index - 1] @ transition) * emission[index]
        scales[index] = max(float(alpha[index].sum()), 1e-12)
        alpha[index] /= scales[index]
    return alpha, scales


def _backward(emission: np.ndarray, transition: np.ndarray, scales: np.ndarray) -> np.ndarray:
    beta = np.ones_like(emission)
    for index in range(len(emission) - 2, -1, -1):
        beta[index] = transition @ (emission[index + 1] * beta[index + 1])
        beta[index] /= max(scales[index + 1], 1e-12)
    return beta


def _order_regime_probabilities(probabilities: np.ndarray, state_means: np.ndarray) -> np.ndarray:
    """Order arbitrary HMM state IDs by fitted mean return: bear/range/bull."""
    if len(probabilities) != 3:
        return probabilities
    order = np.argsort(state_means)
    return probabilities[order]


@dataclass(frozen=True)
class RateObservation:
    observed_on: date
    lpr_1y: float = _nan()
    lpr_5y: float = _nan()
    shibor_overnight: float = _nan()
    shibor_3m: float = _nan()


def load_local_rate_observations(project_root: Path) -> list[RateObservation]:
    """Load optional, local rate history. Missing rate files remain missing."""
    observations: dict[date, RateObservation] = {}
    for path, kind in (
        (project_root / "artifacts/cn_research_auxiliary/macro_lpr.json", "lpr"),
        (project_root / "artifacts/cn_research_auxiliary/macro_shibor.json", "shibor"),
    ):
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for row in rows if isinstance(rows, list) else []:
            raw_date = row.get("TRADE_DATE") or row.get("日期")
            try:
                day = date.fromisoformat(str(raw_date)[:10])
            except (TypeError, ValueError):
                continue
            prior = observations.get(day, RateObservation(day))
            if kind == "lpr":
                observations[day] = RateObservation(day, _finite(row.get("LPR1Y") or row.get("RATE_1")), _finite(row.get("LPR5Y") or row.get("RATE_2")), prior.shibor_overnight, prior.shibor_3m)
            else:
                observations[day] = RateObservation(day, prior.lpr_1y, prior.lpr_5y, _finite(row.get("O/N-定价")), _finite(row.get("3M-定价")))
    return sorted(observations.values(), key=lambda item: item.observed_on)


def rate_features_asof(observations: list[RateObservation], day: date) -> dict[str, float]:
    if not observations:
        return {name: _nan() for name in ("lpr_1y", "lpr_5y", "shibor_overnight", "shibor_3m", "shibor_term_spread")}
    dates = [item.observed_on for item in observations]
    index = bisect_right(dates, day) - 1
    if index < 0:
        return {name: _nan() for name in ("lpr_1y", "lpr_5y", "shibor_overnight", "shibor_3m", "shibor_term_spread")}
    item = observations[index]
    spread = item.shibor_3m - item.shibor_overnight if np.isfinite(item.shibor_3m) and np.isfinite(item.shibor_overnight) else _nan()
    return {"lpr_1y": item.lpr_1y, "lpr_5y": item.lpr_5y, "shibor_overnight": item.shibor_overnight, "shibor_3m": item.shibor_3m, "shibor_term_spread": spread}


@dataclass(frozen=True)
class NorthboundObservation:
    symbol: str
    observed_on: date
    holding_pct: float = _nan()
    holding_shares: float = _nan()
    value_change_1d: float = _nan()
    value_change_5d: float = _nan()


def load_local_northbound_history(project_root: Path) -> dict[str, list[NorthboundObservation]]:
    """Load dated northbound holdings downloaded by the companion collector.

    The data is optional.  An absent file deliberately yields missing values;
    it must never be replaced with the latest live holding during training.
    """
    path = project_root / "artifacts/cn_research_auxiliary/northbound_holdings.jsonl"
    grouped: dict[str, list[NorthboundObservation]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return grouped
    for line in lines:
        try:
            row = json.loads(line)
            symbol = str(row["symbol"]).zfill(6)
            observed_on = date.fromisoformat(str(row["trade_date"])[:10])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        grouped.setdefault(symbol, []).append(NorthboundObservation(
            symbol=symbol, observed_on=observed_on,
            holding_pct=_finite(row.get("holding_pct")), holding_shares=_finite(row.get("holding_shares")),
            value_change_1d=_finite(row.get("northbound_value_change_1d")),
            value_change_5d=_finite(row.get("northbound_value_change_5d")),
        ))
    for values in grouped.values():
        values.sort(key=lambda item: item.observed_on)
    return grouped


def northbound_features_asof(observations: list[NorthboundObservation], day: date) -> dict[str, float]:
    missing = {
        "northbound_holding_pct": _nan(), "northbound_holding_change_5d": _nan(),
        "northbound_value_change_1d": _nan(), "northbound_value_change_5d": _nan(),
    }
    if not observations:
        return missing
    dates = [item.observed_on for item in observations]
    index = bisect_right(dates, day) - 1
    if index < 0:
        return missing
    latest = observations[index]
    prior_index = max(0, index - 5)
    prior = observations[prior_index]
    change = latest.holding_pct - prior.holding_pct if np.isfinite(latest.holding_pct) and np.isfinite(prior.holding_pct) else _nan()
    return {
        "northbound_holding_pct": latest.holding_pct, "northbound_holding_change_5d": change,
        "northbound_value_change_1d": latest.value_change_1d,
        "northbound_value_change_5d": latest.value_change_5d,
    }


class FortuneFeatureCache:
    """Content-addressed JSON cache for expensive causal feature panels."""

    def __init__(self, root: Path) -> None:
        self.root = root / "artifacts" / "feature_cache"

    def key(self, bars: Mapping[str, Mapping[date, float]]) -> str:
        material = [_FEATURE_CACHE_SCHEMA] + [f"{symbol}:{day.isoformat()}:{close:.8f}" for symbol, values in sorted(bars.items()) for day, close in sorted(values.items())]
        return hashlib.sha256("|".join(material).encode()).hexdigest()[:20]

    def path_for(self, key: str) -> Path:
        return self.root / f"fortune_context_{key}.json"

    def load(self, key: str) -> dict[tuple[str, date], dict[str, float]] | None:
        try:
            payload = json.loads(self.path_for(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if payload.get("schema") != _FEATURE_CACHE_SCHEMA:
            return None
        output: dict[tuple[str, date], dict[str, float]] = {}
        for item in payload.get("rows", []):
            try:
                output[(str(item["symbol"]), date.fromisoformat(item["date"]))] = {str(k): _finite(v) for k, v in item["features"].items()}
            except (KeyError, TypeError, ValueError):
                return None
        return output

    def save(self, key: str, values: Mapping[tuple[str, date], Mapping[str, float]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        rows = [{"symbol": symbol, "date": day.isoformat(), "features": dict(features)} for (symbol, day), features in sorted(values.items())]
        self.path_for(key).write_text(json.dumps({"schema": _FEATURE_CACHE_SCHEMA, "rows": rows}, allow_nan=True, separators=(",", ":")), encoding="utf-8")
