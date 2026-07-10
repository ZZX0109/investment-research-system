from __future__ import annotations

import math


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def scenario_embedding(window: list[list[float]], dim: int = 128) -> list[float]:
    if not window:
        return [0.0] * dim
    flat: list[float] = []
    cols = len(window[0])
    for col in range(cols):
        values = [row[col] for row in window]
        flat.extend([values[-1], sum(values) / len(values), max(values), min(values)])
    if len(flat) < dim:
        flat.extend([0.0] * (dim - len(flat)))
    return normalize(flat[:dim])


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))

