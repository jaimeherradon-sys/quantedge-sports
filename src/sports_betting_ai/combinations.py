"""Same-game joint bets: only empirically aligned historical outcomes accepted."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from sports_betting_ai.value import expected_value


@dataclass(frozen=True)
class Combination:
    probability: float
    odds: float
    ev: float
    n_joint_observations: int
    method: str


def empirical_combination(outcomes: np.ndarray, individual_odds: list[float],
                          *, min_joint_samples=200) -> Combination:
    """outcomes: historical 2D [same event-context rows, selection columns].

    No positional joining of unrelated athletes/dates; calling code must supply
    verified aligned joint event samples. All entries must be observed outcomes.
    """
    arr = np.asarray(outcomes)
    if arr.ndim != 2 or arr.shape[1] != len(individual_odds):
        raise ValueError("Aligned outcomes matrix required")
    if arr.shape[0] < min_joint_samples:
        raise ValueError("NO BET: insufficient joint historical samples")
    if not np.isin(arr, [0, 1]).all() or np.isnan(arr.astype(float)).any():
        raise ValueError("Historical outcomes must be binary and complete")
    if len(individual_odds) < 2 or len(individual_odds) > 6:
        raise ValueError("Use 2-6 legs")
    price = float(np.prod(individual_odds))
    p = float(np.all(arr == 1, axis=1).mean())
    return Combination(p, price, expected_value(p, price), len(arr), "observed-aligned-joint")


def bootstrap_joint_probability(outcomes: np.ndarray, individual_odds: list[float],
                                *, simulations: int = 100_000, seed: int = 42):
    """Optional 100k Monte Carlo resamples aligned real joint historical outcomes.

    A correlated, non-parametric bootstrap estimates sampling uncertainty for the
    empirical joint rate; it is NOT a new predictive model or independent-leg
    multiplier. Validity requires comparable, honestly aligned historical contexts.
    """
    base = empirical_combination(outcomes, individual_odds)
    if not 100 <= simulations <= 100_000:
        raise ValueError("simulations must be 100..100000")
    wins = np.all(np.asarray(outcomes, dtype=int) == 1, axis=1).astype(float)
    rng = np.random.default_rng(seed)
    # Quantify uncertainty in joint event probability by bootstrap of observed rows.
    # Avoid huge [n_bootstrap, n_original] allocations on large samples.
    reps = min(simulations // len(wins), 2_000)
    if reps < 100:
        reps = 100
    sampled = []
    for _ in range(reps):
        sampled.append(float(rng.choice(wins, size=len(wins), replace=True).mean()))
    low, high = np.quantile(sampled, [.025, .975])
    return {"joint_p": base.probability, "joint_p_low": float(low),
            "joint_p_high": float(high), "decimal_odds": base.odds,
            "ev": base.ev, "ev_lower":expected_value(float(low), base.odds),
            "observed_matched_events":len(wins),"bootstrap_replicates":reps,
            "method":"aligned-joint-event-bootstrap; not independent legs"}
