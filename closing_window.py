"""
Late-period goal-lock scoring for matches approaching HT or FT.
FH from 36', SH from 81' — only surfaces picks with >=95% no-more-goals probability.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from combined_analysis import HALF_CONFIG

CLOSING_START = {"fh": 36, "sh": 81}
MIN_LOCK_PCT = 95.0


def is_closing_window(minute: int, half: str) -> bool:
    return half in CLOSING_START and minute >= CLOSING_START[half]


def minutes_left_in_period(minute: int, half: str) -> int:
    cfg = HALF_CONFIG[half]
    end = cfg["period_minute_start"] + cfg["period_length"]
    return max(end - minute, 0)


def closing_target(half: str) -> str:
    return "HT" if half == "fh" else "FT"


@dataclass
class ClosingCard:
    event_id: str
    home_team: str
    away_team: str
    league: str
    score: str
    minute: int
    period_minute: int
    half: str
    period_goals: int
    period_score: str
    full_score: str
    minutes_left: int
    closing_target: str
    lock_pct: float
    lock_label: str
    lock_market: str
    signals: list[str] = field(default_factory=list)
    live_stats: Optional[dict] = None
    prophit_stats: Optional[dict] = None
    soccerpunter_stats: Optional[dict] = None
    fotmob_stats: Optional[dict] = None
    sportsdb_stats: Optional[dict] = None
    market_odds: Optional[dict] = None
    combined_analysis: Optional[dict] = None
    kickoff: str = ""
    status: str = ""
    league_id: int = 0


def _time_base_lock(period_goals: int, mins_left: int) -> float:
    g = min(period_goals, 3)
    if mins_left <= 2:
        table = {0: 94.0, 1: 96.5, 2: 97.5, 3: 98.0}
    elif mins_left <= 4:
        table = {0: 88.0, 1: 93.0, 2: 95.5, 3: 96.5}
    elif mins_left <= 7:
        table = {0: 80.0, 1: 88.0, 2: 92.0, 3: 94.0}
    else:
        table = {0: 72.0, 1: 82.0, 2: 88.0, 3: 91.0}
    return table.get(g, 85.0)


def _tempo_lock_score(
    shots_pm: float,
    sot_pm: float,
    danger_pm: float,
    live_profile: str,
) -> tuple[float, list[str]]:
    signals: list[str] = []
    if live_profile == "very_slow" or (shots_pm < 0.40 and sot_pm < 0.14):
        signals.append(f"Very slow tempo ({shots_pm:.2f} shots/min, {sot_pm:.2f} SoT/min)")
        return 96.0, signals
    if live_profile == "slow" or shots_pm < 0.55:
        signals.append(f"Slow tempo ({shots_pm:.2f} shots/min)")
        return 90.0, signals
    if shots_pm < 0.72:
        return 82.0, signals
    if shots_pm >= 0.90 or danger_pm >= 1.25:
        signals.append(f"High tempo ({shots_pm:.2f} shots/min, {danger_pm:.2f} danger/min)")
        return 58.0, signals
    signals.append(f"Average-fast tempo ({shots_pm:.2f} shots/min)")
    return 70.0, signals


def _history_lock_score(
    prophit_stats: Optional[dict],
    soccerpunter_stats: Optional[dict],
    half: str,
) -> tuple[float, list[str]]:
    signals: list[str] = []
    score = 78.0
    if prophit_stats:
        u15 = float(prophit_stats.get("combined_under_15_fh_pct") or 0)
        u25 = float(prophit_stats.get("combined_under_25_pct") or 0)
        goals = float(prophit_stats.get("combined_goals_last_n") or 0)
        if half == "sh":
            u15 = max(u15 - 4, u25)
        if u25 >= 75 or u15 >= 72:
            score = 93.0
            signals.append(f"ProphitBet: strong under form (U1.5 {u15:.0f}%, U2.5 {u25:.0f}%)")
        elif u25 >= 65 or u15 >= 65:
            score = 86.0
            signals.append(f"ProphitBet: under-leaning form (U1.5 {u15:.0f}%)")
        elif goals <= 4:
            score = 84.0
            signals.append(f"ProphitBet: low recent goals ({goals:.0f} in window)")
    if soccerpunter_stats:
        u225 = float(soccerpunter_stats.get("combined_under_225_pct") or soccerpunter_stats.get("under_225_pct") or 0)
        h2h = float(soccerpunter_stats.get("h2h_avg_total_goals") or soccerpunter_stats.get("h2h_avg_goals") or 0)
        if u225 >= 70 or h2h <= 2.2:
            score = max(score, 90.0)
            signals.append(f"SoccerPunter H2H: low scoring (avg {h2h:.1f}, U2.25 {u225:.0f}%)")
        elif h2h >= 3.2:
            score = min(score, 72.0)
            signals.append(f"SoccerPunter H2H: higher scoring trend (avg {h2h:.1f})")
    return score, signals


def _market_lock_implied(market_odds: Optional[dict], period_goals: int) -> tuple[float, list[str]]:
    if not market_odds:
        return 0.0, []
    key_map = {0: "under_05_implied_pct", 1: "under_15_implied_pct", 2: "under_25_implied_pct"}
    key = key_map.get(min(period_goals, 2), "under_25_implied_pct")
    implied = float(market_odds.get(key) or 0)
    if implied <= 0:
        return 0.0, []
    line = period_goals + 0.5
    return implied, [f"1xBet market: Under {line} implied {implied:.0f}%"]


def compute_lock_probability(
    live_stats: Any,
    period_goals: int,
    minute: int,
    half: str,
    prophit_stats: Optional[dict] = None,
    soccerpunter_stats: Optional[dict] = None,
    market_odds: Optional[dict] = None,
    combined: Optional[dict] = None,
) -> tuple[float, list[str], str, str]:
    """
    Probability (%) that no further goals are scored before HT/FT in this period.
    Returns (lock_pct, signals, lock_label, lock_market).
    """
    cfg = HALF_CONFIG[half]
    elapsed = max(minute - cfg["period_minute_start"], 1)
    mins_left = minutes_left_in_period(minute, half)
    shots_pm = live_stats.total_shots / elapsed
    sot_pm = live_stats.shots_on_target / elapsed
    danger_pm = (live_stats.dangerous_attacks or 0) / elapsed

    live_profile = (combined or {}).get("live_profile", "average")
    agreement = (combined or {}).get("agreement", "NEUTRAL")

    signals: list[str] = []
    time_score = _time_base_lock(period_goals, mins_left)
    tempo_score, tempo_signals = _tempo_lock_score(shots_pm, sot_pm, danger_pm, live_profile)
    hist_score, hist_signals = _history_lock_score(prophit_stats, soccerpunter_stats, half)
    market_score, market_signals = _market_lock_implied(market_odds, period_goals)

    signals.extend(tempo_signals)
    signals.extend(hist_signals)
    signals.extend(market_signals)
    signals.append(f"{mins_left}' left to {closing_target(half)} · {period_goals} {cfg['label']} goal(s)")

    weights = {"time": 0.38, "tempo": 0.28, "hist": 0.14, "market": 0.20}
    if market_score <= 0:
        weights = {"time": 0.42, "tempo": 0.32, "hist": 0.26, "market": 0.0}

    lock_pct = (
        time_score * weights["time"]
        + tempo_score * weights["tempo"]
        + hist_score * weights["hist"]
        + market_score * weights["market"]
    )

    if mins_left <= 3:
        lock_pct += 4.0
        signals.append(f"Under {mins_left}' — clock strongly favours lock")
    elif mins_left <= 5:
        lock_pct += 2.0

    if agreement == "CONFIRMED":
        lock_pct += 3.0
        signals.append("Fusion sources confirm low-scoring profile")
    elif agreement == "CONFLICT":
        lock_pct -= 14.0
        signals.append("Conflicting fusion signals — lock downgraded")

    if live_profile == "fast":
        lock_pct -= 10.0
    elif live_profile == "very_slow":
        lock_pct += 4.0

    if shots_pm >= 0.85:
        lock_pct -= 8.0
    if sot_pm >= 0.35:
        lock_pct -= 6.0
    if danger_pm >= 1.1:
        lock_pct -= 5.0

    fm_prof = (combined or {}).get("fotmob_profile", "unknown")
    if fm_prof in ("very_slow", "slow"):
        lock_pct += 2.0
    elif fm_prof == "fast":
        lock_pct -= 4.0

    lock_pct = round(min(max(lock_pct, 5.0), 99.0), 1)

    lock_market = f"Under {period_goals + 0.5} {cfg['label']}"
    lock_label = f"NO MORE GOALS · {lock_pct:.0f}%"
    return lock_pct, signals, lock_label, lock_market


def qualifies_lock(lock_pct: float) -> bool:
    return lock_pct >= MIN_LOCK_PCT


def build_closing_card(
    *,
    event_id: str,
    league_id: int,
    home_team: str,
    away_team: str,
    league: str,
    score: str,
    minute: int,
    period_minute: int,
    half: str,
    period_goals: int,
    period_score: str,
    full_score: str,
    live_stats: Any,
    prophit_stats: Optional[dict],
    soccerpunter_stats: Optional[dict],
    fotmob_stats: Optional[dict],
    sportsdb_stats: Optional[dict],
    market_odds: Optional[dict],
    combined: Optional[dict],
    kickoff: str,
    status: str,
) -> Optional[ClosingCard]:
    if not is_closing_window(minute, half):
        return None

    lock_pct, signals, lock_label, lock_market = compute_lock_probability(
        live_stats,
        period_goals,
        minute,
        half,
        prophit_stats=prophit_stats,
        soccerpunter_stats=soccerpunter_stats,
        market_odds=market_odds,
        combined=combined,
    )
    if not qualifies_lock(lock_pct):
        return None

    return ClosingCard(
        event_id=event_id,
        league_id=league_id,
        home_team=home_team,
        away_team=away_team,
        league=league,
        score=score,
        minute=minute,
        period_minute=period_minute,
        half=half,
        period_goals=period_goals,
        period_score=period_score,
        full_score=full_score,
        minutes_left=minutes_left_in_period(minute, half),
        closing_target=closing_target(half),
        lock_pct=lock_pct,
        lock_label=lock_label,
        lock_market=lock_market,
        signals=signals,
        live_stats=asdict(live_stats) if hasattr(live_stats, "__dataclass_fields__") else live_stats,
        prophit_stats=prophit_stats,
        soccerpunter_stats=soccerpunter_stats,
        fotmob_stats=fotmob_stats,
        sportsdb_stats=sportsdb_stats,
        market_odds=market_odds,
        combined_analysis=combined,
        kickoff=kickoff,
        status=status,
    )


def closing_card_to_dict(card: ClosingCard) -> dict[str, Any]:
    return asdict(card)