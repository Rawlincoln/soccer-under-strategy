"""
High-confidence Over/Under 1.5–4.5 picks for FH, SH, and FT accumulators.

A line is dead when one more goal would settle it the wrong way:
  Under 1.5 → already 1+ goals
  Under 2.5 → already 2+ goals
  Over is skipped once it has already landed (no value).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from goal_probability import (
    PERIOD_LENGTH,
    STOPPAGE,
    _poisson_cdf,
    remaining_lambda,
    sample_weight,
)

LINES = (1.5, 2.5, 3.5, 4.5)
MIN_ACCA_PCT = 80.0
MIN_ELAPSED = 12


def _stat(live: Any, key: str, default: float = 0.0) -> float:
    if live is None:
        return default
    if isinstance(live, dict):
        return float(live.get(key) or default)
    return float(getattr(live, key, default) or default)


def _parse_goals(score: str) -> int:
    try:
        a, b = str(score).replace(" ", "").split("-")
        return int(a) + int(b)
    except (ValueError, AttributeError):
        return 0


def _scope_goals(card: dict, scope: str) -> int:
    if scope == "ft":
        return _parse_goals(card.get("full_score") or "0-0")
    if scope == "fh":
        if card.get("half") == "fh":
            return int(card.get("period_goals") or 0)
        return _parse_goals(card.get("fh_score") or "0-0")
    if card.get("half") == "sh":
        return int(card.get("period_goals") or 0)
    return 0


def _under_alive(line: float, goals: int) -> bool:
    """Need a cushion: U1.5 only at 0-0, U2.5 only at 0 or 1, etc."""
    return goals < int(line)


def _over_alive(line: float, goals: int) -> bool:
    """Still to land — skip if already won."""
    return goals <= int(line)


def _tempo_mult(live: Any, elapsed: int) -> tuple[float, str, list[str]]:
    """Fast vs slow game from shots, corners, attacks, dangerous attacks."""
    elapsed = max(elapsed, 1)
    shots_pm = _stat(live, "total_shots") / elapsed
    sot_pm = _stat(live, "shots_on_target") / elapsed
    corners_pm = _stat(live, "corners") / elapsed
    danger_pm = _stat(live, "dangerous_attacks") / elapsed
    attacks_pm = _stat(live, "attacks") / elapsed

    mult = 1.0
    signals: list[str] = []
    score = 0

    if shots_pm >= 0.70:
        mult *= 1.16
        score += 2
        signals.append(f"Fast shot rate {shots_pm:.2f}/min")
    elif shots_pm <= 0.35:
        mult *= 0.86
        score -= 2
        signals.append(f"Slow shot rate {shots_pm:.2f}/min")

    if sot_pm >= 0.28:
        mult *= 1.10
        score += 1
        signals.append(f"Hot SoT {sot_pm:.2f}/min")
    elif sot_pm <= 0.10:
        mult *= 0.90
        score -= 1

    if corners_pm >= 0.28:
        mult *= 1.08
        score += 1
        signals.append(f"Corner pressure {corners_pm:.2f}/min")
    elif corners_pm <= 0.12:
        mult *= 0.94
        score -= 1
        signals.append(f"Few corners {corners_pm:.2f}/min")

    if danger_pm >= 1.0:
        mult *= 1.14
        score += 2
        signals.append(f"Dangerous attacks {danger_pm:.2f}/min")
    elif danger_pm <= 0.35:
        mult *= 0.90
        score -= 2
        signals.append(f"Quiet danger {danger_pm:.2f}/min")

    if attacks_pm >= 1.4:
        mult *= 1.06
        score += 1
        signals.append(f"High attack count {attacks_pm:.2f}/min")
    elif 0 < attacks_pm <= 0.55:
        mult *= 0.95
        score -= 1

    if score >= 3:
        profile = "fast"
    elif score <= -3:
        profile = "slow"
    else:
        profile = "average"
    return max(min(mult, 1.45), 0.70), profile, signals


def _minutes_left(minute: int, half: str, scope: str) -> float:
    if scope == "fh":
        elapsed = max(minute, 0)
        return max(PERIOD_LENGTH["fh"] - elapsed, 0) + STOPPAGE["fh"]
    if scope == "sh":
        elapsed = max(minute - 45, 0)
        return max(PERIOD_LENGTH["sh"] - elapsed, 0) + STOPPAGE["sh"]
    # FT
    if half == "sh":
        elapsed = max(minute - 45, 0)
        return max(PERIOD_LENGTH["sh"] - elapsed, 0) + STOPPAGE["sh"]
    if half == "ht" or minute >= 45:
        return PERIOD_LENGTH["sh"] + STOPPAGE["sh"]
    elapsed = max(minute, 0)
    left_fh = max(PERIOD_LENGTH["fh"] - elapsed, 0) + STOPPAGE["fh"]
    return left_fh + PERIOD_LENGTH["sh"] + STOPPAGE["sh"]


def _remaining_goals(
    live: Any,
    minute: int,
    half: str,
    scope: str,
    fotmob_xg: float,
) -> tuple[float, float, int]:
    """(lambda remaining, sample weight, period elapsed)."""
    if scope == "fh":
        elapsed = max(minute, 0)
        danger_pm = _stat(live, "dangerous_attacks") / max(elapsed, 1)
        lam, gpm, w = remaining_lambda(
            int(_stat(live, "total_shots")),
            int(_stat(live, "shots_on_target")),
            elapsed,
            "fh",
            fotmob_xg=fotmob_xg,
            danger_pm=danger_pm,
        )
        return lam, w, elapsed
    if scope == "sh":
        elapsed = max(minute - 45, 0)
        danger_pm = _stat(live, "dangerous_attacks") / max(elapsed, 1)
        lam, gpm, w = remaining_lambda(
            int(_stat(live, "total_shots")),
            int(_stat(live, "shots_on_target")),
            elapsed,
            "sh",
            fotmob_xg=fotmob_xg,
            danger_pm=danger_pm,
        )
        return lam, w, elapsed

    # FT: current period remaining + unused half
    if half == "sh":
        elapsed = max(minute - 45, 0)
        danger_pm = _stat(live, "dangerous_attacks") / max(elapsed, 1)
        lam, _, w = remaining_lambda(
            int(_stat(live, "total_shots")),
            int(_stat(live, "shots_on_target")),
            elapsed,
            "sh",
            fotmob_xg=fotmob_xg,
            danger_pm=danger_pm,
        )
        return lam, w, elapsed

    elapsed = max(minute, 0) if half != "ht" else 45
    danger_pm = _stat(live, "dangerous_attacks") / max(elapsed, 1)
    lam_fh, gpm, w = remaining_lambda(
        int(_stat(live, "total_shots")),
        int(_stat(live, "shots_on_target")),
        min(elapsed, 45),
        "fh",
        fotmob_xg=fotmob_xg,
        danger_pm=danger_pm,
    )
    sh_left = PERIOD_LENGTH["sh"] + STOPPAGE["sh"]
    lam_sh = (1.0 - w) * 1.20 + w * (gpm * sh_left)
    return lam_fh + max(lam_sh, 0.15), w, elapsed


def _fusion_nudge(card: dict, side: str) -> float:
    """pp adjustment from fusion / form / market."""
    fusion = card.get("combined_analysis") or {}
    gp = fusion.get("goal_prob_summary") or {}
    prs = fusion.get("pressure_summary") or {}
    sv = fusion.get("shots_volume_summary") or {}
    mkt = card.get("market_odds") or fusion.get("market_odds_summary") or {}
    pb = card.get("prophit_stats") or {}
    sp = card.get("soccerpunter_stats") or {}
    fm = card.get("fotmob_stats") or {}
    nudge = 0.0

    live_prof = fusion.get("live_profile") or ""
    if side == "UNDER":
        if live_prof in ("very_slow", "slow"):
            nudge += 3
        elif live_prof == "fast":
            nudge -= 5
        if fusion.get("agreement") in ("CONFIRMED", "ALIGNED"):
            nudge += 2
        elif fusion.get("agreement") == "CONFLICT":
            nudge -= 6
        if (prs.get("p_under_15") or 0) >= 70:
            nudge += 2
        if sv.get("in_combined_band") or sv.get("in_split_band"):
            nudge += 2
        if pb.get("combined_under_15_fh_pct", 0) >= 65:
            nudge += 1
        if sp.get("h2h_under_25_pct", 0) >= 70:
            nudge += 1
        if mkt.get("market_lean") in ("strong_under", "under"):
            nudge += 1
        if (fm.get("total_xg") or 99) <= 0.45:
            nudge += 1
    else:
        if live_prof == "fast":
            nudge += 4
        elif live_prof in ("very_slow", "slow"):
            nudge -= 4
        if fusion.get("agreement") == "CONFLICT":
            nudge += 2
        if (gp.get("remaining_xg") or 0) >= 1.1:
            nudge += 2
        if mkt.get("market_lean") == "over":
            nudge += 2
        if pb.get("combined_goals_last_n", 0) >= 10:
            nudge += 1
    return nudge


@dataclass
class OuPick:
    event_id: str
    match: str
    home_team: str
    away_team: str
    league: str
    league_id: int
    scope: str
    side: str
    line: float
    market: str
    selection: str
    confidence: float
    remaining_xg: float
    tempo: str
    minute: int
    half: str
    period_score: str
    full_score: str
    period_minute: int
    is_half_time: bool
    onexbet_url: str
    signals: list[str]
    recommendation: str = "BET"


def extract_ou_picks(card: dict) -> list[OuPick]:
    if card.get("is_half_time"):
        half = "ht"
    else:
        half = card.get("half") or "fh"
    minute = int(card.get("minute") or 0)
    live = card.get("live_stats") or {}
    fusion = card.get("combined_analysis") or {}
    fm = card.get("fotmob_stats") or fusion.get("fotmob_summary") or {}
    fotmob_xg = float(fm.get("total_xg") or 0)

    scopes: list[str] = []
    if half == "fh":
        scopes = ["fh", "ft"]
    elif half == "sh":
        scopes = ["sh", "ft"]
    else:
        scopes = ["ft"]

    picks: list[OuPick] = []
    home = card.get("home_team") or ""
    away = card.get("away_team") or ""

    for scope in scopes:
        elapsed = minute if scope == "fh" or (scope == "ft" and half != "sh") else max(minute - 45, 0)
        if scope == "ft" and half == "ht":
            elapsed = 45
        if elapsed < MIN_ELAPSED and half != "ht":
            continue
        if sample_weight(float(elapsed if half != "ht" else 25)) < 0.32 and half != "ht":
            continue

        goals = _scope_goals(card, scope)
        lam0, w, _ = _remaining_goals(live, minute, half if half != "ht" else "fh", scope, fotmob_xg)
        tempo_mult, tempo, tempo_signals = _tempo_mult(
            live, max(elapsed if half != "ht" else 45, 1),
        )
        lam = max(lam0 * tempo_mult, 0.05)
        nudge = _fusion_nudge(card, "UNDER")

        for line in LINES:
            # Under
            if _under_alive(line, goals):
                room = int(line) - goals
                p_raw = _poisson_cdf(room, lam)
                p = min(max(p_raw * 100.0 + nudge, 1.0), 96.0)
                if w < 0.45:
                    p = min(p, 78.0)
                if p >= MIN_ACCA_PCT:
                    label = {"fh": "FH", "sh": "SH", "ft": "FT"}[scope]
                    picks.append(_make_pick(
                        card, home, away, scope, "UNDER", line, p, lam, tempo,
                        tempo_signals, label, half, minute,
                    ))

            # Over
            if _over_alive(line, goals):
                room = int(line) - goals
                p_under = _poisson_cdf(room, lam)
                p_raw = 1.0 - p_under
                over_nudge = _fusion_nudge(card, "OVER")
                p = min(max(p_raw * 100.0 + over_nudge, 1.0), 96.0)
                if w < 0.45:
                    p = min(p, 78.0)
                if p >= MIN_ACCA_PCT:
                    label = {"fh": "FH", "sh": "SH", "ft": "FT"}[scope]
                    picks.append(_make_pick(
                        card, home, away, scope, "OVER", line, p, lam, tempo,
                        tempo_signals, label, half, minute,
                    ))

    # One pick per match+scope (highest confidence) to keep slips clean
    best: dict[tuple[str, str], OuPick] = {}
    for p in picks:
        key = (p.event_id, p.scope)
        if key not in best or p.confidence > best[key].confidence:
            best[key] = p
    return list(best.values())


def _make_pick(
    card: dict,
    home: str,
    away: str,
    scope: str,
    side: str,
    line: float,
    conf: float,
    lam: float,
    tempo: str,
    tempo_signals: list[str],
    label: str,
    half: str,
    minute: int,
) -> OuPick:
    selection = f"{side.title()} {line:g} {label}"
    market = f"{side.title()} {line:g} {'First Half' if scope == 'fh' else 'Second Half' if scope == 'sh' else 'Full Time'} Goals"
    signals = [
        f"{selection} · rem xG {lam:.2f} · {tempo} tempo",
        *tempo_signals[:2],
    ]
    return OuPick(
        event_id=str(card.get("event_id") or ""),
        match=f"{home} vs {away}",
        home_team=home,
        away_team=away,
        league=card.get("league") or "",
        league_id=int(card.get("league_id") or 0),
        scope=scope,
        side=side,
        line=line,
        market=market,
        selection=selection,
        confidence=round(conf, 1),
        remaining_xg=round(lam, 2),
        tempo=tempo,
        minute=minute,
        half=card.get("half") or "fh",
        period_score=card.get("period_score") or card.get("fh_score") or "0-0",
        full_score=card.get("full_score") or "0-0",
        period_minute=int(card.get("period_minute") or 0),
        is_half_time=bool(card.get("is_half_time")),
        onexbet_url=card.get("onexbet_url") or "",
        signals=signals,
        recommendation="BET",
    )


def all_ou_picks(matches: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in matches:
        for pick in extract_ou_picks(card):
            row = asdict(pick)
            row["card"] = card
            row["pick"] = {
                "market": pick.market,
                "confidence": pick.confidence,
                "recommendation": "BET",
                "signals": pick.signals,
            }
            out.append(row)
    out.sort(key=lambda x: -x["confidence"])
    return out
