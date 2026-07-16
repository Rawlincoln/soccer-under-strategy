"""
Wheatcroft (2020) GAP pressure model for Over/Under forecasting.

Based on: "A Profitable Model For Predicting the Over/Under Market in Football"
(LSE / International Journal of Forecasting) and the BetAngel methodology video.

Uses shots-on-target + corners (not goals) as pressure inputs, logistic regression
to estimate Over 2.5 probability, then blends with market implied odds to find value.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Logistic: y_hat = alpha + beta_gap * gap_sum + beta_market * r_market
# p_over = sigmoid(y_hat); fair_odds = 1 / p
LOGISTIC_ALPHA = -0.15
LOGISTIC_BETA_GAP = 0.055
LOGISTIC_BETA_MARKET = 0.70

MODEL_WEIGHT = 0.60
MARKET_WEIGHT = 0.40

LEAGUE_AVG_PRESSURE_PER_TEAM = 7.5
BASELINE_MATCH_PRESSURE = 15.0
BASELINE_MATCH_GOALS = 2.7

PERIOD_GOAL_SHARE = {"fh": 0.44, "sh": 0.56, "full": 1.0}
PERIOD_LENGTH = {"fh": 45, "sh": 45, "full": 90}


def _sigmoid(x: float) -> float:
    x = max(min(x, 20.0), -20.0)
    return 1.0 / (1.0 + math.exp(-x))


def _fair_odds(prob_pct: float) -> float:
    if prob_pct <= 0.5:
        return 0.0
    return round(100.0 / prob_pct, 2)


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def team_pressure_per_match(sot: float, corners: float, window: int) -> float:
    """Attacking pressure = shots on target + corners per match (GAP proxy)."""
    if window <= 0:
        return LEAGUE_AVG_PRESSURE_PER_TEAM
    return (sot + corners) / window


def gap_ratings_from_form(prophit: dict[str, Any]) -> dict[str, float]:
    """
    Build four GAP-style ratings from ProphitBet rolling form.
    Home attack / away attack from venue-specific SOT+corners;
    defensive ratings proxy opponent attacking pressure at that venue.
    """
    home = prophit.get("home") or {}
    away = prophit.get("away") or {}
    window = max(int(prophit.get("form_window", 3) or 3), 1)

    h_attack = team_pressure_per_match(
        float(home.get("shots_on_target", 0) or 0),
        float(home.get("corners", 0) or 0),
        window,
    )
    a_attack = team_pressure_per_match(
        float(away.get("shots_on_target", 0) or 0),
        float(away.get("corners", 0) or 0),
        window,
    )
    h_defense = a_attack
    a_defense = h_attack
    gap_sum = h_attack + h_defense + a_attack + a_defense

    return {
        "home_attack": round(h_attack, 2),
        "home_defense": round(h_defense, 2),
        "away_attack": round(a_attack, 2),
        "away_defense": round(a_defense, 2),
        "gap_sum": round(gap_sum, 2),
        "expected_match_pressure": round(gap_sum / 2, 2),
    }


def p_over_25_logistic(
    gap_sum: float,
    market_over_implied_pct: Optional[float] = None,
) -> float:
    """Wheatcroft eq. (3): logistic Over 2.5 probability (%)."""
    r = (market_over_implied_pct / 100.0) if market_over_implied_pct else 0.52
    y = LOGISTIC_ALPHA + LOGISTIC_BETA_GAP * gap_sum + LOGISTIC_BETA_MARKET * r
    return round(_sigmoid(y) * 100.0, 1)


def blend_model_market(
    model_prob_pct: float,
    market_prob_pct: Optional[float],
    model_weight: float = MODEL_WEIGHT,
) -> float:
    """Blend model forecast with market implied probability (video method)."""
    if not market_prob_pct or market_prob_pct <= 0:
        return model_prob_pct
    w = max(min(model_weight, 0.95), 0.05)
    return round(w * model_prob_pct + (1 - w) * market_prob_pct, 1)


def pressure_to_lambda(pressure: float, half: str = "full") -> float:
    """Map combined match pressure to expected period goals (Poisson lambda)."""
    ratio = pressure / BASELINE_MATCH_PRESSURE if BASELINE_MATCH_PRESSURE else 1.0
    share = PERIOD_GOAL_SHARE.get(half, 1.0)
    return max(0.12, BASELINE_MATCH_GOALS * ratio * share)


def poisson_under_prob(
    line: float,
    lam: float,
    goals_already: int = 0,
) -> float:
    """P(remaining period goals keep total at or under line)."""
    max_remaining = int(line) - goals_already
    if max_remaining < 0:
        return 0.0
    p = sum(_poisson_pmf(k, lam) for k in range(max_remaining + 1))
    return round(min(p * 100.0, 99.0), 1)


def live_pressure_adjust(
    match_pressure: float,
    live_shots: int,
    live_corners: int,
    elapsed: int,
    half: str = "fh",
    live_weight: float = 0.45,
) -> tuple[float, bool]:
    """Blend historical pressure with live shots+corners pace."""
    period_len = PERIOD_LENGTH.get(half, 45)
    hist_period = match_pressure * PERIOD_GOAL_SHARE.get(half, 0.44)

    if elapsed < 5 or (live_shots + live_corners) == 0:
        return round(hist_period, 2), False

    live_pm = (live_shots + live_corners) / elapsed
    projected = live_pm * period_len
    blended = (1 - live_weight) * hist_period + live_weight * projected
    return round(blended, 2), True


def market_edge(
    model_prob_pct: float,
    market_odds: float,
) -> float:
    """Edge in percentage points: model prob minus market implied prob."""
    if market_odds <= 1.0:
        return 0.0
    market_imp = 100.0 / market_odds
    return round(model_prob_pct - market_imp, 1)


@dataclass
class PressureOUResult:
    gap_sum: float = 0.0
    home_attack: float = 0.0
    away_attack: float = 0.0
    match_pressure: float = 0.0
    period_pressure: float = 0.0
    p_over_25: float = 50.0
    p_under_25: float = 50.0
    p_under_15: float = 50.0
    p_under_05: float = 50.0
    fair_over_odds: float = 0.0
    fair_under_odds: float = 0.0
    over_edge_pct: float = 0.0
    under_edge_pct: float = 0.0
    value_side: str = "none"
    profile: str = "balanced"
    live_adjusted: bool = False
    score: float = 0.0
    signals: list[str] = field(default_factory=list)


def analyze_pressure_ou(
    prophit_stats: Optional[dict[str, Any]],
    live_stats: Any = None,
    half: str = "fh",
    period_goals: int = 0,
    market_odds: Optional[dict[str, Any]] = None,
    minute: int = 0,
) -> PressureOUResult:
    """
    Full pressure O/U analysis for a live period.
    Returns probabilities, fair odds, market edge, and fusion score.
    """
    signals: list[str] = []
    result = PressureOUResult()

    if prophit_stats and not prophit_stats.get("partial"):
        gap = gap_ratings_from_form(prophit_stats)
        result.gap_sum = gap["gap_sum"]
        result.home_attack = gap["home_attack"]
        result.away_attack = gap["away_attack"]
        result.match_pressure = gap["expected_match_pressure"]
    else:
        result.match_pressure = BASELINE_MATCH_PRESSURE / 2
        result.gap_sum = BASELINE_MATCH_PRESSURE * 2
        signals.append("GAP: no ProphitBet form — using league-average pressure")

    elapsed = max(minute - (0 if half == "fh" else 45), 1) if minute else 1
    live_shots = int(getattr(live_stats, "total_shots", 0) or 0) if live_stats else 0
    live_corners = int(getattr(live_stats, "corners", 0) or 0) if live_stats else 0

    period_pressure, live_adj = live_pressure_adjust(
        result.match_pressure, live_shots, live_corners, elapsed, half,
    )
    result.period_pressure = period_pressure
    result.live_adjusted = live_adj

    mkt = market_odds or {}
    over_imp = None
    if mkt.get("over_25_odds"):
        over_imp = 100.0 / mkt["over_25_odds"]
    elif mkt.get("over_15_odds"):
        over_imp = 100.0 / mkt["over_15_odds"]

    p_over_model = p_over_25_logistic(result.gap_sum, over_imp)
    p_over_blend = blend_model_market(p_over_model, over_imp)
    result.p_over_25 = p_over_blend
    result.p_under_25 = round(100.0 - p_over_blend, 1)
    result.fair_over_odds = _fair_odds(p_over_blend)
    result.fair_under_odds = _fair_odds(result.p_under_25)

    lam = pressure_to_lambda(period_pressure, half)
    result.p_under_15 = poisson_under_prob(1.5, lam, period_goals)
    result.p_under_05 = poisson_under_prob(0.5, lam, period_goals)

    if live_adj:
        signals.append(
            f"GAP live: {period_pressure:.1f} pressure "
            f"({live_shots} shots + {live_corners} ck in {elapsed}')"
        )
    else:
        signals.append(
            f"GAP form: {result.home_attack:.1f}/{result.away_attack:.1f} "
            f"attack pressure (sum {result.gap_sum:.1f})"
        )

    signals.append(
        f"Pressure model: {result.p_under_25:.0f}% U2.5 "
        f"(fair {result.fair_under_odds or '—'})"
    )

    u15_odds = mkt.get("under_15_odds") or 0
    u25_odds = mkt.get("under_25_odds") or 0
    o25_odds = mkt.get("over_25_odds") or 0

    if u15_odds > 1:
        result.under_edge_pct = market_edge(result.p_under_15, u15_odds)
    if u25_odds > 1:
        edge_u25 = market_edge(result.p_under_25, u25_odds)
        if abs(edge_u25) > abs(result.under_edge_pct):
            result.under_edge_pct = edge_u25
    if o25_odds > 1:
        result.over_edge_pct = market_edge(result.p_over_25, o25_odds)

    if result.under_edge_pct >= 4:
        result.value_side = "under"
        signals.append(
            f"VALUE Under: model {result.p_under_15:.0f}% vs market "
            f"{100/u15_odds:.0f}% (+{result.under_edge_pct:.0f}pp edge)"
            if u15_odds > 1
            else f"VALUE Under: +{result.under_edge_pct:.0f}pp edge on U2.5"
        )
    elif result.over_edge_pct >= 4:
        result.value_side = "over"
        signals.append(f"VALUE Over: +{result.over_edge_pct:.0f}pp edge — avoid unders")
    elif result.under_edge_pct <= -5:
        result.value_side = "over"
        signals.append("Market prices under below model — caution on unders")

    if result.gap_sum < 24:
        result.profile = "low_pressure"
    elif result.gap_sum > 34:
        result.profile = "high_pressure"
    else:
        result.profile = "balanced"

    score = 0.0
    if result.profile == "low_pressure":
        score += 8
        signals.append("Low shots+corners form — supports unders (GAP)")
    elif result.profile == "high_pressure":
        score -= 8
        signals.append("High shots+corners form — over risk (GAP)")

    if result.p_under_15 >= 72:
        score += 6
    elif result.p_under_15 >= 62:
        score += 3
    elif result.p_under_15 <= 42:
        score -= 6

    if result.value_side == "under" and result.under_edge_pct >= 4:
        score += 5
    elif result.value_side == "over":
        score -= 6

    if live_adj and period_pressure < result.match_pressure * 0.7:
        score += 4
        signals.append("Live tempo below form pressure — under lean")

    result.score = round(max(min(score, 18.0), -12.0), 1)
    result.signals = signals
    return result


def pressure_ou_score(
    prophit_stats: Optional[dict[str, Any]],
    live_stats: Any = None,
    half: str = "fh",
    period_goals: int = 0,
    market_odds: Optional[dict[str, Any]] = None,
    minute: int = 0,
) -> tuple[float, list[str], dict[str, Any]]:
    """Fusion hook: returns (score, signals, summary dict)."""
    r = analyze_pressure_ou(
        prophit_stats, live_stats, half, period_goals, market_odds, minute,
    )
    return r.score, r.signals, asdict(r)


def pressure_confidence_adjust(
    base_conf: float,
    pressure: PressureOUResult,
    market_key: str = "under_15",
) -> float:
    """Nudge period-under confidence using pressure model probabilities."""
    prob_map = {
        "under_05": pressure.p_under_05,
        "under_15": pressure.p_under_15,
        "under_25": pressure.p_under_25,
    }
    target = prob_map.get(market_key, pressure.p_under_15)
    delta = (target - 58.0) * 0.35
    if pressure.value_side == "under":
        delta += min(pressure.under_edge_pct * 0.4, 6.0)
    elif pressure.value_side == "over":
        delta -= 8.0
    return round(min(max(base_conf + delta, 1.0), 96.0), 1)