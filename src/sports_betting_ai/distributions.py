"""Count distributions; overdispersion estimated from training residuals only."""
from __future__ import annotations
from math import floor
import numpy as np
from scipy.stats import nbinom, poisson


def fit_alpha(y: np.ndarray, predicted_train: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    m = np.clip(np.asarray(predicted_train, dtype=float), 0.001, None)
    extra = float(np.mean((y - m) ** 2 - m) / np.mean(m * m))
    return float(np.clip(extra, 0, 3))


def over_probability(mean: float, line: float, alpha: float = 0.0) -> float:
    if mean < 0 or alpha < 0 or line < 0:
        raise ValueError("Non-negative count parameters and threshold required")
    k = floor(line)
    if alpha < 1e-8:
        return float(poisson.sf(k, mean))
    shape = 1 / alpha
    return float(nbinom.sf(k, shape, shape / (shape + mean)))


def confidence_range(mean: float, line: float, alpha: float, recent_counts,
                     n_boot: int = 1500, seed: int = 42) -> tuple[float, float]:
    """Heuristic bootstrap for forecast-mean uncertainty; NOT a calibrated confidence bound.

    Samples the recent observed counts; rescales the model mean by relative bootstrap
    means. This does not adjust for injury or role changes; gating must handle those.
    """
    vals = np.asarray(recent_counts, dtype=float)
    if len(vals) < 20 or not np.isfinite(vals).all() or np.mean(vals) <= 0:
        return 0.0, 1.0
    rng = np.random.default_rng(seed)
    sampled = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    mu = np.maximum(0.0, mean * sampled / vals.mean())
    if alpha < 1e-8:
        p = poisson.sf(floor(line), mu)
    else:
        shape = 1 / alpha
        p = nbinom.sf(floor(line), shape, shape / (shape + mu))
    lo, hi = np.quantile(p, [0.025, 0.975])
    return float(lo), float(hi)
