"""
Live basketball Q3 totals engine.
Uses Q1+Q2+Q3 quarter scoring stats blended with historical league curves.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from basketball_filters import is_excluded_basketball_raw
from bet_assistant import effective_onexbet_android_package, effective_onexbet_site
from onexbet_basketball import OneXBetBasketballClient, OneXBetBasketballMatch

REFRESH_SECONDS = 30
MIN_DEFINITE_PCT = 70.0
CLIENT = OneXBetBasketballClient()

# Historical quarter distributions (combined pts per quarter) + cumulative game shares
LEAGUE_PROFILES: dict[str, dict[str, Any]] = {
    "nba": {
        "avg_game": 220.0,
        "game_std": 13.0,
        "quarters": [55.0, 55.0, 54.0, 56.0],
        "cumulative_share": [0.25, 0.50, 0.745, 1.0],
        "q4_vs_h1_avg": 1.02,
    },
    "wnba": {
        "avg_game": 168.0,
        "game_std": 11.0,
        "quarters": [42.0, 42.0, 41.0, 43.0],
        "cumulative_share": [0.25, 0.50, 0.744, 1.0],
        "q4_vs_h1_avg": 1.01,
    },
    "nbl": {
        "avg_game": 160.0,
        "game_std": 10.5,
        "quarters": [40.0, 40.0, 39.0, 41.0],
        "cumulative_share": [0.25, 0.50, 0.744, 1.0],
        "q4_vs_h1_avg": 1.0,
    },
    "ibl": {
        "avg_game": 152.0,
        "game_std": 10.0,
        "quarters": [38.0, 38.0, 37.0, 39.0],
        "cumulative_share": [0.25, 0.50, 0.743, 1.0],
        "q4_vs_h1_avg": 0.98,
    },
    "euroleague": {
        "avg_game": 164.0,
        "game_std": 11.0,
        "quarters": [41.0, 41.0, 40.0, 42.0],
        "cumulative_share": [0.25, 0.50, 0.744, 1.0],
        "q4_vs_h1_avg": 1.01,
    },
    "philippines": {
        "avg_game": 175.0,
        "game_std": 11.5,
        "quarters": [44.0, 44.0, 43.0, 44.0],
        "cumulative_share": [0.251, 0.503, 0.749, 1.0],
        "q4_vs_h1_avg": 0.99,
    },
    "default": {
        "avg_game": 160.0,
        "game_std": 10.5,
        "quarters": [40.0, 40.0, 39.0, 41.0],
        "cumulative_share": [0.25, 0.50, 0.744, 1.0],
        "q4_vs_h1_avg": 0.99,
    },
}


def _league_profile(league: str) -> dict[str, Any]:
    ll = league.lower()
    for key, profile in LEAGUE_PROFILES.items():
        if key != "default" and key in ll:
            return profile
    return LEAGUE_PROFILES["default"]


@dataclass
class TotalPrediction:
    market: str
    line: float
    pick: str
    confidence: float
    projected: float
    edge: float
    recommendation: str
    label: str = ""
    is_definite: bool = False
    signals: list[str] = field(default_factory=list)


@dataclass
class BasketballCard:
    event_id: str
    home_team: str
    away_team: str
    league: str
    score: str
    total_points: int
    period_name: str
    q3_clock: str
    quarters: dict[str, Any]
    quarter_stats: dict[str, Any]
    pace: dict[str, float]
    history: dict[str, float]
    predictions: list[dict]
    game_odds: dict[str, Any]
    q3_odds: dict[str, Any]
    best_pick: str = ""
    best_confidence: float = 0.0
    definite_pick: Optional[dict[str, Any]] = None
    definite_picks: list[dict[str, Any]] = field(default_factory=list)
    league_id: int = 0


def _interp_cumulative_share(game_pct: float, shares: list[float]) -> float:
    """Linear interpolation on cumulative quarter shares (0..1 game progress)."""
    game_pct = max(0.0, min(game_pct, 1.0))
    breakpoints = [0.0, 0.25, 0.50, 0.75, 1.0]
    values = [0.0] + list(shares)
    for i in range(len(breakpoints) - 1):
        if breakpoints[i] <= game_pct <= breakpoints[i + 1]:
            span = breakpoints[i + 1] - breakpoints[i]
            if span <= 0:
                return values[i + 1]
            t = (game_pct - breakpoints[i]) / span
            return values[i] + t * (values[i + 1] - values[i])
    return shares[-1]


def compute_quarter_stats(match: OneXBetBasketballMatch, profile: dict[str, Any]) -> dict[str, Any]:
    """Build scoring stats from Q1, Q2, and in-progress Q3."""
    q_len = match.quarter_minutes
    hist_q = profile["quarters"]
    q1 = match.q1_total
    q2 = match.q2_total
    q3 = match.q3_total
    h1 = q1 + q2
    three_q = h1 + q3

    q3_elapsed = max(match.q3_elapsed_min, 0.5)
    minutes_played = 2 * q_len + q3_elapsed
    total_game_min = 4 * q_len
    game_pct = minutes_played / total_game_min

    q3_pace_to_full = q3 + (q3 / q3_elapsed) * max(q_len - q3_elapsed, 0)
    three_q_at_q3_end = q1 + q2 + q3_pace_to_full

    h1_ppm = h1 / (2 * q_len)
    q3_ppm = q3 / q3_elapsed
    three_q_ppm = three_q / minutes_played

    q1_vs_hist = q1 - hist_q[0]
    q2_vs_hist = q2 - hist_q[1]
    q3_vs_hist_pace = q3_pace_to_full - hist_q[2]
    h1_vs_hist = h1 - (hist_q[0] + hist_q[1])
    three_q_vs_hist = three_q - _interp_cumulative_share(game_pct, profile["cumulative_share"]) * profile["avg_game"]

    q2_delta = q2 - q1
    q3_delta = q3_pace_to_full - q2
    trend = q3_delta - q2_delta

    if trend >= 4:
        trajectory = "accelerating"
    elif trend <= -4:
        trajectory = "decelerating"
    else:
        trajectory = "stable"

    quarters_below_hist = sum([
        q1 < hist_q[0] - 2,
        q2 < hist_q[1] - 2,
        q3_pace_to_full < hist_q[2] - 2,
    ])
    quarters_above_hist = sum([
        q1 > hist_q[0] + 2,
        q2 > hist_q[1] + 2,
        q3_pace_to_full > hist_q[2] + 2,
    ])

    return {
        "q1": q1,
        "q2": q2,
        "q3_so_far": q3,
        "h1_total": h1,
        "three_q_total": three_q,
        "three_q_at_q3_end": round(three_q_at_q3_end, 1),
        "game_pct": round(game_pct * 100, 1),
        "minutes_played": round(minutes_played, 1),
        "q1_vs_hist": round(q1_vs_hist, 1),
        "q2_vs_hist": round(q2_vs_hist, 1),
        "q3_vs_hist": round(q3_vs_hist_pace, 1),
        "h1_vs_hist": round(h1_vs_hist, 1),
        "three_q_vs_hist": round(three_q_vs_hist, 1),
        "q2_delta": round(q2_delta, 1),
        "q3_delta": round(q3_delta, 1),
        "trend": round(trend, 1),
        "trajectory": trajectory,
        "quarters_below_hist": quarters_below_hist,
        "quarters_above_hist": quarters_above_hist,
        "h1_ppm": round(h1_ppm, 2),
        "q3_ppm": round(q3_ppm, 2),
        "three_q_ppm": round(three_q_ppm, 2),
        "q3_pace_to_full": round(q3_pace_to_full, 1),
    }


def compute_historical_benchmark(
    match: OneXBetBasketballMatch,
    profile: dict[str, Any],
    qstats: dict[str, Any],
) -> dict[str, float]:
    hist_q = profile["quarters"]
    game_pct = qstats["game_pct"] / 100.0
    avg_game = profile["avg_game"]

    expected_now = _interp_cumulative_share(game_pct, profile["cumulative_share"]) * avg_game
    expected_q3_end = sum(hist_q[:3])
    expected_q4 = hist_q[3]

    h1_avg_q = (hist_q[0] + hist_q[1]) / 2
    hist_q4_from_pattern = h1_avg_q * profile["q4_vs_h1_avg"]

    live_vs_hist_ratio = qstats["three_q_total"] / max(expected_now, 1.0)
    hist_scaled_final = avg_game * live_vs_hist_ratio

    hist_from_q3_end = qstats["three_q_at_q3_end"] + hist_q4_from_pattern

    return {
        "hist_game_avg": avg_game,
        "hist_q1": hist_q[0],
        "hist_q2": hist_q[1],
        "hist_q3": hist_q[2],
        "hist_q4": hist_q[3],
        "hist_expected_now": round(expected_now, 1),
        "hist_expected_q3_end": round(expected_q3_end, 1),
        "hist_expected_q4": round(hist_q4_from_pattern, 1),
        "hist_scaled_final": round(hist_scaled_final, 1),
        "hist_from_q3_pattern": round(hist_from_q3_end, 1),
        "live_vs_hist_ratio": round(live_vs_hist_ratio, 3),
    }


def project_game_total(
    match: OneXBetBasketballMatch,
    profile: dict[str, Any],
    qstats: dict[str, Any],
    hist: dict[str, float],
) -> dict[str, float]:
    q_len = match.quarter_minutes
    q3_elapsed = max(match.q3_elapsed_min, 0.5)
    minutes_played = qstats["minutes_played"]
    remaining_min = max(4 * q_len - minutes_played, 0.5)

    # Method A: 3-quarter live pace extrapolation
    pace_proj = qstats["three_q_total"] + qstats["three_q_ppm"] * remaining_min

    # Method B: Q1+Q2+Q3 projected finish + historical Q4
    quarter_sum_proj = qstats["three_q_at_q3_end"] + hist["hist_expected_q4"]

    # Method C: Historical curve scaled by live Q1-Q2-Q3 performance
    hist_scaled = hist["hist_scaled_final"]

    # Method D: Trend-adjusted Q4 (decelerating teams score less in Q4)
    trend_adj = 0.0
    if qstats["trajectory"] == "decelerating":
        trend_adj = -3.0
    elif qstats["trajectory"] == "accelerating":
        trend_adj = 2.0
    trend_proj = quarter_sum_proj + trend_adj

    weights = {
        "pace": 0.30,
        "quarters": 0.30,
        "historical": 0.25,
        "trend": 0.15,
    }
    blended = (
        weights["pace"] * pace_proj
        + weights["quarters"] * quarter_sum_proj
        + weights["historical"] * hist_scaled
        + weights["trend"] * trend_proj
    )

    return {
        "proj_pace": round(pace_proj, 1),
        "proj_quarters": round(quarter_sum_proj, 1),
        "proj_historical": round(hist_scaled, 1),
        "proj_trend": round(trend_proj, 1),
        "proj_final": round(blended, 1),
        "proj_q3": round(qstats["q3_pace_to_full"], 1),
        "proj_q4": round(hist["hist_expected_q4"] + trend_adj, 1),
        "h1_pace": qstats["h1_ppm"],
        "q3_pace": qstats["q3_ppm"],
        "three_q_ppm": qstats["three_q_ppm"],
        "pace_ratio": round(qstats["q3_ppm"] / max(qstats["h1_ppm"], 0.1), 2),
    }


def _normal_cdf(value: float, mu: float, sigma: float) -> float:
    if sigma <= 0:
        return 1.0 if value >= mu else 0.0
    z = (value - mu) / sigma
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _estimate_sigma(
    match: OneXBetBasketballMatch,
    profile: dict[str, Any],
    qstats: dict[str, Any],
    hist_bias: str,
) -> float:
    q_len = match.quarter_minutes
    minutes_played = qstats["minutes_played"]
    remaining_frac = max((4 * q_len - minutes_played) / (4 * q_len), 0.08)
    sigma = profile.get("game_std", 10.5) * math.sqrt(remaining_frac)

    q_spread = max(qstats["q1"], qstats["q2"], qstats["q3_pace_to_full"]) - min(
        qstats["q1"], qstats["q2"], qstats["q3_pace_to_full"],
    )
    if q_spread > 14:
        sigma *= 1.1
    if qstats["trajectory"] == "stable":
        sigma *= 0.92
    if hist_bias in ("OVER", "UNDER"):
        sigma *= 0.9
    return max(sigma, 4.0)


def _format_line(line: float) -> str:
    if abs(line * 2 - round(line * 2)) < 0.01:
        half = round(line * 2)
        if half % 2 == 0:
            return str(half // 2)
        return f"{half // 2}.5"
    return f"{line:.1f}"


def _format_pick_label(pick: str, line: float, prob: float) -> str:
    return f"{pick} {_format_line(line)} · {prob:.0f}%"


def _find_definite_picks(
    mu: float,
    sigma: float,
    odds: dict[str, Any],
    hist_bias: str,
    qstats: dict[str, Any],
    hist: dict[str, float],
    pace: dict[str, float],
) -> list[dict[str, Any]]:
    """Scan all total lines; return picks with >=70% model probability."""
    lines_map: dict[float, dict[str, float]] = {}
    for row in odds.get("game_all_lines") or []:
        line = float(row["line"])
        lines_map[line] = {
            "under_prob_pct": row.get("under_prob_pct", 0),
            "over_prob_pct": row.get("over_prob_pct", 0),
            "on_market": True,
        }

    base = int(round(mu))
    for whole in range(base - 28, base + 29):
        for half in (0.0, 0.5):
            lines_map.setdefault(float(whole) + half, {"on_market": False})

    candidates: list[dict[str, Any]] = []
    for line, meta in lines_map.items():
        model_p_under = _normal_cdf(line, mu, sigma) * 100.0
        model_p_over = (1.0 - _normal_cdf(line, mu, sigma)) * 100.0

        if meta.get("under_prob_pct"):
            p_under = 0.68 * model_p_under + 0.32 * meta["under_prob_pct"]
        else:
            p_under = model_p_under
        if meta.get("over_prob_pct"):
            p_over = 0.68 * model_p_over + 0.32 * meta["over_prob_pct"]
        else:
            p_over = model_p_over

        if hist_bias == "UNDER":
            p_under = min(p_under + 2.5, 97.0)
            p_over = max(p_over - 2.0, 3.0)
        elif hist_bias == "OVER":
            p_over = min(p_over + 2.5, 97.0)
            p_under = max(p_under - 2.0, 3.0)

        cushion_under = line - mu
        cushion_over = mu - line

        if p_under >= MIN_DEFINITE_PCT and cushion_under >= 2:
            candidates.append({
                "pick": "UNDER",
                "line": line,
                "probability": round(p_under, 1),
                "cushion": round(cushion_under, 1),
                "on_market": meta.get("on_market", False),
                "projected": round(mu, 1),
                "sigma": round(sigma, 1),
            })
        if p_over >= MIN_DEFINITE_PCT and cushion_over >= 2:
            candidates.append({
                "pick": "OVER",
                "line": line,
                "probability": round(p_over, 1),
                "cushion": round(cushion_over, 1),
                "on_market": meta.get("on_market", False),
                "projected": round(mu, 1),
                "sigma": round(sigma, 1),
            })

    market_pool = [c for c in candidates if c.get("on_market")]
    pick_pool = market_pool if market_pool else candidates

    def _line_quality(c: dict[str, Any]) -> float:
        """Lower is better: favour ~73% on-market half-point lines."""
        prob = c["probability"]
        target = abs(prob - 73.0)
        if not c.get("on_market"):
            target += 12.0
        if prob > 86:
            target += (prob - 86) * 1.0
        return target

    def _best_pick(side: str) -> Optional[dict[str, Any]]:
        pool = [c for c in pick_pool if c["pick"] == side]
        if not pool:
            return None
        band = [c for c in pool if 70.0 <= c["probability"] <= 84.0]
        chosen = min(band or pool, key=_line_quality)
        chosen["label"] = _format_pick_label(side, chosen["line"], chosen["probability"])
        return chosen

    definite: list[dict[str, Any]] = []
    best_u = _best_pick("UNDER")
    best_o = _best_pick("OVER")
    if best_u:
        definite.append(best_u)
    if best_o:
        definite.append(best_o)

    definite.sort(key=lambda x: -x["probability"])
    return definite[:2]


def _historical_pick_bias(qstats: dict[str, Any], hist: dict[str, float]) -> tuple[str, float, list[str]]:
    """Under/over lean from Q1-Q2-Q3 stats vs historical benchmarks."""
    signals: list[str] = []
    score = 0.0

    if qstats["three_q_vs_hist"] <= -6:
        score -= 8
        signals.append(
            f"Q1+Q2+Q3 ({qstats['three_q_total']}) {qstats['three_q_vs_hist']:+.0f} vs "
            f"historical pace ({hist['hist_expected_now']:.0f}) — under lean"
        )
    elif qstats["three_q_vs_hist"] >= 6:
        score += 8
        signals.append(
            f"Q1+Q2+Q3 ({qstats['three_q_total']}) {qstats['three_q_vs_hist']:+.0f} vs "
            f"historical pace ({hist['hist_expected_now']:.0f}) — over lean"
        )
    else:
        signals.append(
            f"Q1+Q2+Q3 {qstats['three_q_total']} pts in line with historical "
            f"benchmark {hist['hist_expected_now']:.0f}"
        )

    if qstats["quarters_below_hist"] >= 2:
        score -= 5
        signals.append(f"{qstats['quarters_below_hist']}/3 quarters below historical avg — under pattern")
    elif qstats["quarters_above_hist"] >= 2:
        score += 5
        signals.append(f"{qstats['quarters_above_hist']}/3 quarters above historical avg — over pattern")

    if qstats["trajectory"] == "decelerating":
        score -= 4
        signals.append(f"Scoring decelerating (Q trend {qstats['trend']:+.0f}) — Q4 likely slower")
    elif qstats["trajectory"] == "accelerating":
        score += 4
        signals.append(f"Scoring accelerating (Q trend {qstats['trend']:+.0f}) — Q4 likely faster")

    if hist["live_vs_hist_ratio"] < 0.96:
        score -= 3
    elif hist["live_vs_hist_ratio"] > 1.04:
        score += 3

    if score <= -6:
        return "UNDER", abs(score), signals
    if score >= 6:
        return "OVER", abs(score), signals
    return "NEUTRAL", abs(score), signals


def analyze_q3_match(
    match: OneXBetBasketballMatch,
    odds: dict[str, Any],
) -> tuple[list[TotalPrediction], dict[str, float], dict[str, float], dict[str, Any]]:
    profile = _league_profile(match.league)
    qstats = compute_quarter_stats(match, profile)
    hist = compute_historical_benchmark(match, profile, qstats)
    pace = project_game_total(match, profile, qstats, hist)
    hist_bias, hist_strength, hist_signals = _historical_pick_bias(qstats, hist)

    history_summary = {
        **hist,
        "q1_total": float(qstats["q1"]),
        "q2_total": float(qstats["q2"]),
        "q3_so_far": float(qstats["q3_so_far"]),
        "h1_total": float(qstats["h1_total"]),
        "three_q_total": float(qstats["three_q_total"]),
        "hist_bias": hist_bias,
        "hist_strength": hist_strength,
    }

    predictions: list[TotalPrediction] = []
    proj_final = pace["proj_final"]
    sigma = _estimate_sigma(match, profile, qstats, hist_bias)

    signals_base: list[str] = [
        f"Q1 {qstats['q1']} · Q2 {qstats['q2']} · Q3 {qstats['q3_so_far']} "
        f"({qstats['three_q_total']} through 3Q)",
        f"3Q pace {qstats['three_q_ppm']:.2f} ppm · historical expected now {hist['hist_expected_now']:.0f}",
        f"Projected final {proj_final:.0f} ±{sigma:.1f} pts from Q1-Q2-Q3 + history",
    ] + hist_signals

    definite_picks = _find_definite_picks(
        proj_final, sigma, odds, hist_bias, qstats, hist, pace,
    )

    for dp in definite_picks:
        edge = dp["cushion"] if dp["pick"] == "OVER" else dp["cushion"]
        prob = dp["probability"]
        rec = "BET" if prob >= 75 else "BET"
        predictions.append(TotalPrediction(
            market="Game Total",
            line=dp["line"],
            pick=dp["pick"],
            confidence=prob,
            projected=proj_final,
            edge=edge,
            recommendation=rec,
            label=dp["label"],
            is_definite=True,
            signals=signals_base + [
                dp["label"],
                f"{dp['pick']} needs final below {dp['line']}" if dp["pick"] == "UNDER"
                else f"{dp['pick']} needs final above {dp['line']}",
                f"Cushion {dp['cushion']:+.1f} pts vs projection {proj_final:.0f}",
                "On 1xBet board" if dp.get("on_market") else "Model line (check 1xBet)",
            ],
        ))

    if not definite_picks:
        game_odds = odds.get("game") or {}
        game_line = game_odds.get("line")
        if game_line:
            p_under = _normal_cdf(game_line, proj_final, sigma) * 100
            p_over = 100 - p_under
            if p_under >= p_over:
                pick, prob = "UNDER", p_under
                edge = game_line - proj_final
            else:
                pick, prob = "OVER", p_over
                edge = proj_final - game_line
            predictions.append(TotalPrediction(
                market="Game Total",
                line=game_line,
                pick=pick,
                confidence=round(prob, 1),
                projected=proj_final,
                edge=round(edge, 1),
                recommendation="WAIT",
                label=_format_pick_label(pick, game_line, prob),
                is_definite=False,
                signals=signals_base + [
                    f"No {MIN_DEFINITE_PCT:.0f}%+ line found — best {pick} {game_line} at {prob:.0f}%",
                ],
            ))

    q3_odds = odds.get("q3_quarter") or {}
    q3_line = q3_odds.get("line")
    if q3_line:
        proj_q3 = pace["proj_q3"]
        q3_edge = proj_q3 - q3_line
        if q3_edge >= 3:
            pick, rec = "OVER", "BET"
            conf = min(90.0, 56 + q3_edge * 3)
        elif q3_edge <= -3:
            pick, rec = "UNDER", "BET"
            conf = min(90.0, 56 + abs(q3_edge) * 3)
        elif q3_edge >= 1.5:
            pick, rec = "OVER", "WATCH"
            conf = 50 + q3_edge * 2.5
        elif q3_edge <= -1.5:
            pick, rec = "UNDER", "WATCH"
            conf = 50 + abs(q3_edge) * 2.5
        else:
            pick, rec = "NEAR LINE", "WAIT"
            conf = 42.0

        predictions.append(TotalPrediction(
            market="Q3 Quarter Total",
            line=q3_line,
            pick=pick,
            confidence=round(conf, 1),
            projected=round(proj_q3, 1),
            edge=round(q3_edge, 1),
            recommendation=rec,
            signals=[
                f"Q3 projected {proj_q3:.0f} from Q1-Q2-Q3 pace vs line {q3_line}",
                f"Historical Q3 avg {hist['hist_q3']:.0f} · live Q3 {qstats['q3_so_far']} in {match.q3_elapsed_min:.0f} min",
                f"Q3 vs hist pace {qstats['q3_vs_hist']:+.0f}",
            ],
        ))

    return predictions, pace, history_summary, qstats, definite_picks, sigma


def _q3_clock_label(match: OneXBetBasketballMatch) -> str:
    if match.q3_elapsed_min <= 0:
        return "Q3 start"
    return f"Q3 {match.q3_elapsed_min:.0f}'"


def _quarters_display(match: OneXBetBasketballMatch) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, q in sorted(match.quarters.items()):
        out[f"Q{k}"] = f"{q.home}-{q.away} ({q.total})"
    return out


def build_basketball_payload() -> dict[str, Any]:
    raw_live = CLIENT.fetch_live_basketball()
    total_live = len(raw_live)
    excluded = 0
    q3_excluded_period = 0
    cards: list[BasketballCard] = []

    for raw in raw_live:
        if is_excluded_basketball_raw(raw):
            excluded += 1
            continue

        match = CLIENT.parse_match(raw)
        if not match.is_third_quarter:
            q3_excluded_period += 1
            continue

        try:
            odds = CLIENT.fetch_match_odds(match)
        except Exception:
            odds = {"game": {}, "q3_quarter": {}}

        preds, pace, history, qstats, definite_picks, sigma = analyze_q3_match(match, odds)
        if not preds:
            continue

        pred_dicts = [asdict(p) for p in preds]
        definite_only = [p for p in preds if p.is_definite]
        best = max(definite_only or preds, key=lambda p: p.confidence)
        primary_definite = definite_picks[0] if definite_picks else None

        cards.append(BasketballCard(
            event_id=str(match.game_id),
            home_team=match.home_team,
            away_team=match.away_team,
            league=match.league,
            league_id=match.league_id,
            score=f"{match.home_score} - {match.away_score}",
            total_points=match.total_points,
            period_name=match.period_name,
            q3_clock=_q3_clock_label(match),
            quarters=_quarters_display(match),
            quarter_stats={**qstats, "proj_sigma": round(sigma, 1)},
            pace=pace,
            history=history,
            predictions=pred_dicts,
            game_odds=odds.get("game") or {},
            q3_odds=odds.get("q3_quarter") or {},
            best_pick=best.label or f"{best.pick} {best.line}",
            best_confidence=best.confidence,
            definite_pick=primary_definite,
            definite_picks=definite_picks,
        ))

    cards.sort(key=lambda c: (
        0 if c.definite_pick else 1,
        -c.best_confidence,
        -c.total_points,
    ))

    bet_signals = []
    for card in cards:
        for p in card.predictions:
            if p.get("is_definite") and p["confidence"] >= MIN_DEFINITE_PCT:
                bet_signals.append({
                    "match": f"{card.home_team} vs {card.away_team}",
                    "event_id": card.event_id,
                    "league_id": card.league_id,
                    "market": p["market"],
                    "pick": p["pick"],
                    "line": p["line"],
                    "label": p.get("label") or f"{p['pick']} {p['line']} · {p['confidence']:.0f}%",
                    "confidence": p["confidence"],
                    "recommendation": p["recommendation"],
                    "signals": p["signals"][:4],
                    "league": card.league,
                    "score": card.score,
                    "q3_clock": card.q3_clock,
                    "game_odds": card.game_odds,
                    "q3_odds": card.q3_odds,
                })

    site = effective_onexbet_site()
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_seconds": REFRESH_SECONDS,
        "source": "1xbet",
        "onexbet_site": site,
        "onexbet_android_package": effective_onexbet_android_package(),
        "sport": "basketball",
        "filter": f"3rd quarter · definite picks ≥{MIN_DEFINITE_PCT:.0f}%",
        "min_definite_pct": MIN_DEFINITE_PCT,
        "definite_count": sum(1 for c in cards if c.definite_pick),
        "total_live": total_live,
        "excluded_count": excluded,
        "non_q3_count": q3_excluded_period,
        "match_count": len(cards),
        "bet_signal_count": len(bet_signals),
        "matches": [asdict(c) for c in cards],
        "bet_signals": bet_signals,
        "error": None,
    }


class BasketballCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"matches": [], "error": None}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            self.refresh()
            time.sleep(REFRESH_SECONDS)

    def refresh(self):
        try:
            payload = build_basketball_payload()
            with self._lock:
                self._data = payload
        except Exception as exc:
            with self._lock:
                self._data["error"] = str(exc)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)