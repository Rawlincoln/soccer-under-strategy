"""
Calibrated P(under) from remaining-time Poisson goals.

Live shot/SoT pace is shrunk toward a league prior until enough minutes
have elapsed — 0 shots in the 1st minute is not evidence of a slow match.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

GOALS_PER_SHOT = 0.095
GOALS_PER_SOT = 0.30
PRIOR_STRENGTH_MIN = 18.0  # minutes of prior vs live
STOPPAGE = {"fh": 2.0, "sh": 4.0}
PERIOD_LENGTH = {"fh": 45.0, "sh": 45.0}
PRIOR_PERIOD_GOALS = {"fh": 1.15, "sh": 1.20}
MIN_SAMPLE_ELAPSED = 12


def _poisson_cdf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    if lam <= 0:
        return 1.0
    lam = min(lam, 20.0)
    p = 0.0
    for i in range(k + 1):
        p += (lam ** i) * math.exp(-lam) / math.factorial(i)
    return min(max(p, 0.0), 1.0)


def sample_weight(elapsed: float) -> float:
    """0 at kickoff → ~1 after ~35' of the period."""
    return elapsed / (elapsed + PRIOR_STRENGTH_MIN) if elapsed > 0 else 0.0


@dataclass
class GoalProbResult:
    elapsed: int = 0
    minutes_left: float = 45.0
    sample_quality: float = 0.0
    remaining_xg: float = 0.0
    p_under_05: float = 50.0
    p_under_15: float = 50.0
    p_under_25: float = 50.0
    prior_p_under_15: float = 67.0
    live_gpm: float = 0.0
    thin_sample: bool = True
    signals: list[str] = field(default_factory=list)


def remaining_lambda(
    shots: int,
    sot: int,
    elapsed: int,
    half: str,
    fotmob_xg: float = 0.0,
    danger_pm: float = 0.0,
) -> tuple[float, float, float]:
    """Return (lambda_remaining, live_goals_per_min, sample_quality)."""
    period_len = PERIOD_LENGTH.get(half, 45.0)
    elapsed_f = float(max(elapsed, 0))
    minutes_left = max(period_len - elapsed_f, 0.0) + STOPPAGE.get(half, 2.0)
    prior_gpm = PRIOR_PERIOD_GOALS.get(half, 1.15) / period_len
    prior_rem = prior_gpm * minutes_left

    shots_pm = shots / max(elapsed_f, 1.0)
    sot_pm = sot / max(elapsed_f, 1.0)
    live_gpm = 0.55 * sot_pm * GOALS_PER_SOT + 0.45 * shots_pm * GOALS_PER_SHOT
    if fotmob_xg > 0 and elapsed_f >= 8:
        xg_pm = fotmob_xg / elapsed_f
        live_gpm = 0.55 * xg_pm + 0.45 * live_gpm
    if danger_pm > 1.0:
        live_gpm *= 1.12
    elif danger_pm > 0 and danger_pm < 0.35 and elapsed_f >= 12:
        live_gpm *= 0.92

    w = sample_weight(elapsed_f)
    lam = (1.0 - w) * prior_rem + w * (live_gpm * minutes_left)
    return max(lam, 0.05), live_gpm, w


def calibrate_p(p_model: float, sample_q: float, p_market: Optional[float] = None) -> float:
    """
    Shrink toward 50% until the period has a real sample.
    Optionally nudge with market implied (capped so bookies don't dominate).
    """
    p_model = min(max(p_model, 0.02), 0.98)
    p = sample_q * p_model + (1.0 - sample_q) * 0.50
    if p_market and p_market > 0:
        m = min(max(p_market, 0.05), 0.95)
        # Market only counts once we have some live evidence
        mw = 0.22 * sample_q
        p = (1.0 - mw) * p + mw * m
    return min(max(p, 0.02), 0.96)


def analyze_goal_probs(
    live_stats: Any,
    minute: int,
    half: str,
    period_goals: int,
    market_odds: Optional[dict[str, Any]] = None,
    fotmob_stats: Optional[dict[str, Any]] = None,
) -> GoalProbResult:
    period_start = 0 if half == "fh" else 45
    elapsed = max(int(minute) - period_start, 0)
    shots = int(getattr(live_stats, "total_shots", 0) or 0)
    sot = int(getattr(live_stats, "shots_on_target", 0) or 0)
    danger = float(getattr(live_stats, "dangerous_attacks", 0) or 0)
    danger_pm = danger / max(elapsed, 1)
    fotmob_xg = float((fotmob_stats or {}).get("total_xg") or 0)

    lam, live_gpm, w = remaining_lambda(
        shots, sot, elapsed, half, fotmob_xg=fotmob_xg, danger_pm=danger_pm,
    )
    minutes_left = max(PERIOD_LENGTH[half] - elapsed, 0.0) + STOPPAGE.get(half, 2.0)

    # P(period total <= line) = P(remaining <= line - already)
    p05_raw = _poisson_cdf(0 - period_goals, lam) if period_goals <= 0 else 0.0
    p15_raw = _poisson_cdf(1 - period_goals, lam) if period_goals <= 1 else 0.0
    p25_raw = _poisson_cdf(2 - period_goals, lam) if period_goals <= 2 else 0.0

    mkt = market_odds or {}
    m05 = (mkt.get("under_05_implied_pct") or 0) / 100.0
    m15 = (mkt.get("under_15_implied_pct") or 0) / 100.0
    m25 = (mkt.get("under_25_implied_pct") or 0) / 100.0

    prior_u15 = 67.0 if half == "fh" else 62.0
    result = GoalProbResult(
        elapsed=elapsed,
        minutes_left=round(minutes_left, 1),
        sample_quality=round(w, 3),
        remaining_xg=round(lam, 2),
        prior_p_under_15=prior_u15,
        live_gpm=round(live_gpm, 3),
        thin_sample=elapsed < MIN_SAMPLE_ELAPSED,
    )
    result.p_under_05 = round(calibrate_p(p05_raw, w, m05 or None) * 100.0, 1)
    result.p_under_15 = round(calibrate_p(p15_raw, w, m15 or None) * 100.0, 1)
    result.p_under_25 = round(calibrate_p(p25_raw, w, m25 or None) * 100.0, 1)

    signals: list[str] = []
    if result.thin_sample:
        signals.append(
            f"Thin sample ({elapsed}' elapsed) — P(under) shrunk toward 50% "
            f"until {MIN_SAMPLE_ELAPSED}'"
        )
    else:
        q = "solid" if w >= 0.55 else "building"
        signals.append(
            f"Calibrated remaining xG {lam:.2f} in {minutes_left:.0f}' left "
            f"({q} sample, live {live_gpm:.2f} gl/min)"
        )
        signals.append(
            f"Model P(U1.5) {result.p_under_15:.0f}% · P(U2.5) {result.p_under_25:.0f}%"
        )
    result.signals = signals
    return result


def goal_prob_score(
    live_stats: Any,
    minute: int,
    half: str,
    period_goals: int,
    market_odds: Optional[dict[str, Any]] = None,
    fotmob_stats: Optional[dict[str, Any]] = None,
) -> tuple[float, list[str], dict[str, Any]]:
    """Fusion hook: score is 0 (probs replace additive confidence)."""
    r = analyze_goal_probs(
        live_stats, minute, half, period_goals, market_odds, fotmob_stats,
    )
    return 0.0, r.signals, asdict(r)
