"""Mathematically explicit prices, vigorish and fail-closed decisions."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite


def implied_probability(decimal_odds: float) -> float:
    if not isfinite(decimal_odds) or decimal_odds <= 1:
        raise ValueError("Decimal odds must exceed 1")
    return 1.0 / decimal_odds


def no_vig_two_way(over_odds: float, under_odds: float) -> tuple[float, float]:
    """Proportional overround removal (one bookmaker, same market/line/time)."""
    a, b = implied_probability(over_odds), implied_probability(under_odds)
    return a / (a + b), b / (a + b)


def expected_value(p: float, odds: float) -> float:
    if not isfinite(p) or p < 0 or p > 1:
        raise ValueError("Probability must be in [0,1]")
    return p * odds - 1 if implied_probability(odds) else 0


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str
    probability: float
    p_low: float
    p_high: float
    odds: float
    ev: float
    ev_lower: float
    implied: float


def decide(p: float, low: float, high: float, odds: float, *, market_fresh: bool,
           availability_verified: bool, model_validated: bool, min_lower_ev: float = 0.04,
           max_interval_width: float = 0.15) -> Decision:
    if not (0 <= low <= p <= high <= 1):
        raise ValueError("Malformed probability confidence interval")
    ev, lower = expected_value(p, odds), expected_value(low, odds)
    reason = "passes conservative research thresholds"
    if not model_validated:
        reason = "insufficient out-of-sample model validation"
    elif not market_fresh:
        reason = "missing or stale authorized odds"
    elif not availability_verified:
        reason = "player availability / minutes / injury evidence not verified"
    elif high - low > max_interval_width:
        reason = "probability interval too wide"
    elif lower <= min_lower_ev:
        reason = "uncertainty-adjusted EV below required margin"
    status = "CANDIDATE" if reason == "passes conservative research thresholds" else "NO BET"
    return Decision(status, reason, p, low, high, odds, ev, lower, implied_probability(odds))


def fractional_kelly(p: float, odds: float, fraction: float = 0.25,
                     max_bet_fraction: float = 0.005) -> float:
    """For paper-risk sizing only; caller must cap aggregate daily exposure."""
    expected_value(p, odds)
    if not (0 <= fraction <= 1 and 0 < max_bet_fraction <= 1):
        raise ValueError("Invalid Kelly configuration")
    edge = (p * odds - 1) / (odds - 1)
    return min(max_bet_fraction, max(0.0, fraction * edge))
