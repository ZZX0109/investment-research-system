"""Leakage-safe tabular matrix and preprocessing helpers.

Missing observations remain NaN in the matrix.  Every imputer is embedded in
the estimator pipeline, so ``fit`` sees training rows only and validation,
holdout and online rows can never contribute preprocessing statistics.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def sample_matrix(samples, feature_order: list[str]) -> pd.DataFrame:
    values: list[list[float]] = []
    for sample in samples:
        row: list[float] = []
        for name in feature_order:
            raw = sample.features.get(name)
            if raw is None:
                row.append(float("nan"))
                continue
            value = float(raw)
            if not np.isfinite(value):
                raise ValueError(f"non_finite_feature:{sample.symbol}:{sample.as_of_date}:{name}")
            row.append(value)
        values.append(row)
    return pd.DataFrame(np.asarray(values, dtype=float), columns=feature_order)


def estimator_pipeline(estimator, *, scale: bool = False):
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline

    steps = [SimpleImputer(strategy="median", keep_empty_features=True)]
    if scale:
        from sklearn.preprocessing import StandardScaler

        steps.append(StandardScaler())
    steps.append(estimator)
    return make_pipeline(*steps)


def finite_feature_bounds(matrix: pd.DataFrame) -> dict[str, list[float | None]]:
    output: dict[str, list[float | None]] = {}
    for name in matrix.columns:
        values = matrix[name].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        output[str(name)] = (
            [float(finite.min()), float(finite.max())]
            if finite.size
            else [None, None]
        )
    return output


def add_missing_indicators(
    feature_values: dict[str, float], missing_features: Iterable[str]
) -> dict[str, float]:
    output = dict(feature_values)
    missing = set(missing_features)
    for name in sorted(set(output) | missing):
        output[f"missing__{name}"] = 1.0 if name in missing else 0.0
    return output
