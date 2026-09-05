"""Small count-distribution helpers shared by threshold scoring components."""
from __future__ import annotations

import math


def probability_at_least(mean: float, dispersion: float, threshold: int) -> float:
    """Negative-binomial tail; dispersion zero is the Poisson limit."""
    if mean <= 0:
        return 0.0
    if dispersion <= 0:
        term = math.exp(-mean)
        cumulative = term
        for count in range(1, threshold):
            term *= mean / count
            cumulative += term
        return min(max(1 - cumulative, 0.0), 1.0)
    size = 1.0 / dispersion
    probability = size / (size + mean)
    term = probability**size
    cumulative = term
    for count in range(1, threshold):
        term *= (count - 1 + size) / count * (1 - probability)
        cumulative += term
    return min(max(1 - cumulative, 0.0), 1.0)


def expected_points_at_intervals(
    mean: float, dispersion: float, interval: int, max_count: int = 60,
) -> tuple[float, dict[int, float]]:
    """E[floor(count/interval)] via the tail-sum identity."""
    tails = {
        threshold: probability_at_least(mean, dispersion, threshold)
        for threshold in range(interval, max_count + 1, interval)
    }
    return sum(tails.values()), tails
