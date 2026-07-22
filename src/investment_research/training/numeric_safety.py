"""Narrow numerical guard for third-party estimator matrix operations."""
from __future__ import annotations

from contextlib import contextmanager
import warnings


@contextmanager
def guarded_model_math():
    """Silence only BLAS matmul warnings, then require finite outputs.

    Apple's accelerated BLAS can emit divide/overflow/invalid matmul warnings
    for finite, bounded sklearn inputs even when the resulting probabilities
    are finite.  Callers must validate every output with ``require_finite``;
    this is not a general warning suppression boundary.
    """
    import numpy as np

    with warnings.catch_warnings(), np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        warnings.filterwarnings(
            "ignore",
            message=r".*encountered in matmul",
            category=RuntimeWarning,
        )
        yield


def require_finite(values, *, stage: str):
    import numpy as np

    resolved = np.asarray(values, dtype=float)
    if not np.isfinite(resolved).all():
        raise ValueError(f"non_finite_model_output:{stage}")
    return values
