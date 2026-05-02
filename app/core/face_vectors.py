from __future__ import annotations

import math
from typing import Sequence


def normalize_embedding(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if not norm:
        return []
    return [float(value) / norm for value in values]


def mean_embedding(vectors: Sequence[Sequence[float]]) -> list[float]:
    usable = [vector for vector in vectors if vector]
    if not usable:
        return []
    size = min(len(vector) for vector in usable)
    if size <= 0:
        return []
    return normalize_embedding(
        [
            sum(float(vector[index]) for vector in usable) / len(usable)
            for index in range(size)
        ]
    )


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    size = min(len(left), len(right))
    if size <= 0:
        return 0.0
    dot = sum(float(left[i]) * float(right[i]) for i in range(size))
    left_norm = math.sqrt(sum(float(left[i]) * float(left[i]) for i in range(size)))
    right_norm = math.sqrt(sum(float(right[i]) * float(right[i]) for i in range(size)))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))
