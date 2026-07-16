"""
Fuse 1xBet live stats with ProphitBet historical form into one unified analysis.
Supports first half (FH) and second half (SH).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from fotmob_stats import fotmob_live_agreement, fotmob_tempo_profile
from market_odds import market_odds_score
from pressure_ou_model import pressure_ou_score
from thesportsdb_stats import sportsdb_live_agreement

HALF_CONFIG = {
    "fh": {
        "label": "FH",
        "entry_start": 15,
        "entry_end": 20,
        "period_minute_start": 0,
        "period_length": 45,
        "under_15_baseline": 67.0,
    },
    "sh": {
        "label": "SH",
        "entry_start": 60,
        "entry_end": 65,
        "period_minute_start": 45,
        "period_length": 45,
        "under_15_baseline": 62.0,
    },
}


@dataclass
class ScoreBreakdown:
    historical: float = 0.0
    soccer_punter: float = 0.0
    fotmob_verify: float = 0.0
    external_verify: float = 0.0
    market_odds: float = 0.0
    pressure_model: float = 0.0
    live_tempo: float = 0.0
    time_context: float = 0.0
    agreement: float = 0.0
    total: float = 0.0


@dataclass
class CombinedAnalysis:
    verdict: str
    confidence: float
    agreement: str
    best_market: str
    best_recommendation: str
    breakdown: ScoreBreakdown
    live_profile: str
    form_profile: str
    sp_profile: str = "unknown"
    fotmob_profile: str = "unknown"
    half: str = "fh"
    period_minute: int = 0
    fusion_signals: list[str] = field(default_factory=list)
    live_summary: dict[str, Any] = field(default_factory=dict)
    form_summary: dict[str, Any] = field(default_factory=dict)
    sp_summary: dict[str, Any] = field(default_factory=dict)
    fotmob_summary: dict[str, Any] = field(default_factory=dict)
    sportsdb_summary: dict[str, Any] = field(default_factory=dict)
    market_odds_summary: dict[str, Any] = field(default_factory=dict)
    pressure_summary: dict[str, Any] = field(default_factory=dict)


def _period_elapsed(minute: int, half: str) -> int:
    cfg = HALF_CONFIG[half]
    return max(minute - cfg["period_minute_start"], 1)


def _live_tempo_profile(
    stats: Any, minute: int, half: str = "fh"
) -> tuple[float, str, dict[str, Any]]:
    elapsed = _period_elapsed(minute, half)
    shots_pm = stats.total_shots / elapsed
    sot_pm = stats.shots_on_target / elapsed
    corners_pm = stats.corners / elapsed
    danger_pm = (stats.dangerous_attacks or 0) / elapsed

    score = 0.0
    if shots_pm < 0.40:
        score += 13
    elif shots_pm < 0.58:
        score += 8
    elif shots_pm < 0.75:
        score += 3
    else:
        score -= 5

    if sot_pm < 0.12:
        score += 11
    elif sot_pm < 0.22:
        score += 6
    elif sot_pm < 0.32:
        score += 2
    else:
        score -= 4

    if corners_pm < 0.22:
        score += 8
    elif corners_pm < 0.32:
        score += 4

    if 38 <= stats.home_possession <= 62:
        score += 5

    if danger_pm < 0.45:
        score += 4
    elif danger_pm > 1.0:
        score -= 5

    score = max(0.0, min(score, 35.0))

    if score >= 28:
        profile = "very_slow"
    elif score >= 20:
        profile = "slow"
    elif score >= 12:
        profile = "average"
    else:
        profile = "fast"

    return score, profile, {
        "shots": stats.total_shots,
        "shots_per_min": round(shots_pm, 2),
        "sot": stats.shots_on_target,
        "corners": stats.corners,
        "dangerous_attacks": stats.dangerous_attacks or 0,
        "possession": round(stats.home_possession, 0),
        "minute": minute,
        "period_minute": elapsed,
        "half": half,
    }


def _form_profile(prophit: Optional[dict[str, Any]], half: str = "fh") -> tuple[float, str, dict[str, Any]]:
    if not prophit:
        return 12.0, "unknown", {}

    score = 0.0
    window = prophit.get("form_window", 3)
    u15 = prophit.get("combined_under_15_fh_pct", 0) or 0
    u25 = prophit.get("combined_under_25_pct", 0) or 0
    goals = prophit.get("combined_goals_last_n", 0) or 0
    sot = prophit.get("combined_sot_last_n", 0) or 0
    corners = prophit.get("combined_corners_last_n", 0) or 0

    if half == "sh":
        u15 = max(u15 - 5, u25)
        score += min(u25 / 100 * 12, 12)
    else:
        score += min(u15 / 100 * 14, 14)
        score += min(u25 / 100 * 8, 8)

    if goals <= 4:
        score += 6
    elif goals <= 6:
        score += 3
    elif goals >= 10:
        score -= 5

    if sot <= 8:
        score += 4
    elif sot >= 16:
        score -= 3

    if corners <= 10:
        score += 3

    home = prophit.get("home") or {}
    away = prophit.get("away") or {}
    avg_fh = ((home.get("avg_fh_goals", 0) or 0) + (away.get("avg_fh_goals", 0) or 0)) / 2
    if 0 < avg_fh <= 0.8:
        score += 4
    if half == "sh" and avg_fh > 1.2:
        score -= 3

    score = max(0.0, min(score, 35.0))

    if score >= 28:
        profile = "defensive"
    elif score >= 20:
        profile = "low_scoring"
    elif score >= 12:
        profile = "balanced"
    else:
        profile = "high_scoring"

    return score, profile, {
        "under_15_fh_pct": round(u15, 1),
        "under_25_pct": round(u25, 1),
        "goals_last_n": goals,
        "sot_last_n": sot,
        "corners_last_n": corners,
        "avg_fh_goals": round(avg_fh, 2),
        "window": window,
        "home_matched": home.get("matched_name") or home.get("team"),
        "away_matched": away.get("matched_name") or away.get("team"),
    }


def _sp_profile(sp: Optional[dict[str, Any]], half: str = "fh") -> tuple[float, str, dict[str, Any]]:
    if not sp:
        return 0.0, "unknown", {}

    has_signal = any(
        (sp.get(k) or 0) > 0
        for k in (
            "combined_goals_avg", "combined_under_225_pct", "combined_fh_under_05_pct",
            "h2h_avg_total_goals", "h2h_meetings",
        )
    )
    if not has_signal:
        return 0.0, "unknown", {}

    score = 0.0
    combined_avg = sp.get("combined_goals_avg", 0) or 0
    u225 = sp.get("combined_under_225_pct", 0) or 0
    fh_u05 = sp.get("combined_fh_under_05_pct", 0) or 0
    h2h_avg = sp.get("h2h_avg_total_goals", 0) or 0
    h2h_u25 = sp.get("h2h_under_25_pct", 0) or 0

    if combined_avg > 0:
        if combined_avg <= 1.6:
            score += 8
        elif combined_avg <= 2.2:
            score += 5
        elif combined_avg >= 3.0:
            score -= 5

    if u225 >= 65:
        score += 6
    elif u225 >= 50:
        score += 3
    elif u225 <= 30 and u225 > 0:
        score -= 3

    if half == "fh":
        if fh_u05 >= 55:
            score += 5
        elif fh_u05 >= 40:
            score += 2
        elif fh_u05 <= 25 and fh_u05 > 0:
            score -= 2
    elif u225 >= 55:
        score += 4

    if h2h_avg > 0:
        if h2h_avg <= 2.0:
            score += 4
        elif h2h_avg >= 3.5:
            score -= 4

    if h2h_u25 >= 70:
        score += 3

    score = max(0.0, min(score, 20.0))

    if score >= 15:
        profile = "defensive"
    elif score >= 10:
        profile = "low_scoring"
    elif score >= 5:
        profile = "balanced"
    else:
        profile = "high_scoring"

    return score, profile, {
        "combined_goals_avg": round(combined_avg, 2),
        "under_225_pct": round(u225, 1),
        "fh_under_05_pct": round(fh_u05, 1),
        "h2h_avg_goals": round(h2h_avg, 2),
        "h2h_under_25_pct": round(h2h_u25, 1),
        "h2h_meetings": sp.get("h2h_meetings", 0),
        "home_gs_avg": round(sp.get("home_goals_scored_avg", 0) or 0, 2),
        "away_gs_avg": round(sp.get("away_goals_scored_avg", 0) or 0, 2),
    }


def _agreement_score(
    live_profile: str,
    form_profile: str,
    sp_profile: str = "unknown",
) -> tuple[float, str, list[str]]:
    signals: list[str] = []
    slow_live = live_profile in ("very_slow", "slow")
    fast_live = live_profile == "fast"
    low_form = form_profile in ("defensive", "low_scoring")
    high_form = form_profile == "high_scoring"
    low_sp = sp_profile in ("defensive", "low_scoring")
    high_sp = sp_profile == "high_scoring"
    low_all = low_form or low_sp
    high_all = high_form or high_sp

    if slow_live and low_form and low_sp:
        signals.append("1xBet tempo + ProphitBet + SoccerPunter all lean under — triple fusion")
        return 12.0, "CONFIRMED", signals
    if slow_live and low_all:
        signals.append("Live tempo confirms low-scoring historical data — strong fusion")
        return 10.0, "CONFIRMED", signals
    if slow_live and form_profile == "balanced" and sp_profile in ("balanced", "low_scoring", "defensive"):
        signals.append("Quiet live match supports moderate under lean")
        return 5.0, "ALIGNED", signals
    if fast_live and high_all:
        signals.append("Fast live tempo matches high-scoring form — avoid unders")
        return -10.0, "CONFLICT", signals
    if fast_live and low_all:
        signals.append("Live tempo hotter than form/H2H suggests — caution on unders")
        return -8.0, "CONFLICT", signals
    if high_sp and slow_live:
        signals.append("SoccerPunter H2H trends higher scoring than live tempo — mixed signals")
        return -4.0, "CAUTION_MIXED", signals
    if live_profile == "average" and low_all:
        signals.append("Average tempo but defensive trends — slight under edge")
        return 3.0, "LEAN_UNDER", signals
    if sp_profile != "unknown" and low_sp and form_profile == "unknown":
        signals.append("SoccerPunter H2H supports unders — partial fusion (no ProphitBet)")
        return 2.0, "LEAN_UNDER", signals
    if form_profile == "unknown" and sp_profile == "unknown":
        signals.append("No historical form — relying on live 1xBet stats only")
        return 0.0, "LIVE_ONLY", signals
    return 0.0, "NEUTRAL", signals


def _time_context_score(total_goals: int, minute: int, half: str) -> tuple[float, list[str]]:
    cfg = HALF_CONFIG[half]
    label = cfg["label"]
    elapsed = minute - cfg["period_minute_start"]
    signals: list[str] = []

    if total_goals == 0 and elapsed >= 15:
        score = 18.0 if half == "fh" else 16.0
        signals.append(f"0-0 in {label} at {minute}' — under 1.5 {label} supported")
        return score, signals
    if total_goals == 0 and elapsed >= 10:
        return 12.0, [f"0-0 in {label} at {minute}' — building under case"]
    if total_goals == 1 and elapsed >= 25:
        signals.append(f"1 goal in {label} at {minute}' — under 1.5 still viable")
        return 15.0, signals
    if total_goals == 1 and elapsed >= 15:
        return 11.0, signals
    if total_goals == 2 and elapsed >= 30:
        return 9.0, signals
    return 0.0, signals


def _market_suffix(half: str) -> str:
    return "First Half Goals" if half == "fh" else "Second Half Goals"


def _pick_best_market(
    total_goals: int, confidence: float, minute: int, half: str
) -> tuple[str, str]:
    sfx = _market_suffix(half)
    if total_goals >= 3:
        return f"Under 2.5 {half.upper()}", "SKIP"
    if total_goals == 2:
        return f"Under 2.5 {half.upper()}", "BET" if confidence >= 68 else "WATCH"
    if total_goals == 1:
        return f"Under 1.5 {half.upper()}", "BET" if confidence >= 66 else "WATCH"
    u05_rec = "BET" if confidence >= 70 and minute >= (58 if half == "sh" else 18) else "WATCH"
    u15_rec = "BET" if confidence >= 64 else "WATCH"
    if u05_rec == "BET" and confidence >= 74:
        return f"Under 0.5 {half.upper()}", u05_rec
    return f"Under 1.5 {half.upper()}", u15_rec


def _verdict(confidence: float, agreement: str, recommendation: str) -> str:
    if recommendation == "SKIP":
        return "SKIP"
    if agreement == "CONFLICT":
        return "CAUTION"
    if confidence >= 76 and agreement in ("CONFIRMED", "ALIGNED"):
        return "STRONG BET"
    if confidence >= 66 and recommendation == "BET":
        return "BET"
    if confidence >= 60:
        return "WATCH"
    return "WAIT"


def build_combined_analysis(
    live_stats: Any,
    prophit_stats: Optional[dict[str, Any]],
    total_goals: int,
    minute: int,
    league_baseline_under_15: float = 67.0,
    half: str = "fh",
    soccer_punter_stats: Optional[dict[str, Any]] = None,
    fotmob_stats: Optional[dict[str, Any]] = None,
    sportsdb_stats: Optional[dict[str, Any]] = None,
    market_odds: Optional[dict[str, Any]] = None,
) -> CombinedAnalysis:
    live_score, live_profile, live_summary = _live_tempo_profile(live_stats, minute, half)
    form_score, form_profile, form_summary = _form_profile(prophit_stats, half)
    sp_score, sp_prof, sp_summary = _sp_profile(soccer_punter_stats, half)
    fm_score, fm_prof, fm_summary = fotmob_tempo_profile(fotmob_stats, minute, half)
    fm_agree, fm_signals = fotmob_live_agreement(live_profile, fm_prof)
    sd_agree, sd_signals = sportsdb_live_agreement(
        live_stats.total_shots, live_stats.shots_on_target, sportsdb_stats,
    )
    mkt_score, mkt_signals = market_odds_score(market_odds, half, total_goals)
    prs_score, prs_signals, prs_summary = pressure_ou_score(
        prophit_stats, live_stats, half, total_goals, market_odds, minute,
    )
    time_score, time_signals = _time_context_score(total_goals, minute, half)
    agree_score, agreement, agree_signals = _agreement_score(live_profile, form_profile, sp_prof)

    hist_score = form_score if prophit_stats else league_baseline_under_15 / 100 * 25
    fotmob_total = round(fm_score + fm_agree, 1)
    external_total = round(min(sd_agree, 12.0), 1)

    breakdown = ScoreBreakdown(
        historical=round(hist_score, 1),
        soccer_punter=round(sp_score, 1),
        fotmob_verify=round(fotmob_total, 1),
        external_verify=external_total,
        market_odds=round(mkt_score, 1),
        pressure_model=round(prs_score, 1),
        live_tempo=round(live_score, 1),
        time_context=round(time_score, 1),
        agreement=round(agree_score, 1),
        total=round(
            hist_score + sp_score + fotmob_total + external_total + mkt_score
            + prs_score + live_score + time_score + agree_score,
            1,
        ),
    )

    confidence = round(min(max(breakdown.total, 5), 96), 1)
    if agreement == "CONFLICT":
        confidence = round(max(confidence - 12, 20), 1)
    if fm_agree <= -4:
        confidence = round(max(confidence - 8, 20), 1)
    if mkt_score <= -4:
        confidence = round(max(confidence - 10, 20), 1)
    if prs_score <= -6:
        confidence = round(max(confidence - 8, 20), 1)
    elif prs_score >= 10:
        confidence = round(min(confidence + 4, 96), 1)

    best_market, best_rec = _pick_best_market(total_goals, confidence, minute, half)
    if agreement == "CONFLICT" and best_rec == "BET":
        best_rec = "WATCH"

    fusion_signals = (
        list(agree_signals) + list(fm_signals) + list(sd_signals)
        + list(mkt_signals) + list(prs_signals) + list(time_signals)
    )
    elapsed = _period_elapsed(minute, half)
    if live_profile in ("very_slow", "slow"):
        fusion_signals.append(
            f"1xBet {half.upper()}: {live_profile.replace('_', ' ')} tempo "
            f"({live_summary.get('shots', 0)} shots in {elapsed}')"
        )
    elif live_profile == "fast":
        fusion_signals.append(
            f"1xBet {half.upper()}: high tempo "
            f"({live_summary.get('shots', 0)} shots, {live_summary.get('dangerous_attacks', 0)} danger)"
        )
    if form_profile != "unknown":
        fusion_signals.append(
            f"ProphitBet: {form_profile.replace('_', ' ')} "
            f"(U1.5 FH {form_summary.get('under_15_fh_pct', '—')}%)"
        )
    if sp_prof != "unknown":
        fusion_signals.append(
            f"SoccerPunter: {sp_prof.replace('_', ' ')} "
            f"(H2H avg {sp_summary.get('h2h_avg_goals', '—')} gl, "
            f"U2.25 {sp_summary.get('under_225_pct', '—')}%)"
        )
    if fm_prof != "unknown":
        fusion_signals.append(
            f"FotMob: {fm_prof.replace('_', ' ')} xG tempo "
            f"({fm_summary.get('total_xg', '—')} xG, {fm_summary.get('shots', '—')} shots)"
        )
    if sportsdb_stats and sportsdb_stats.get("total_shots"):
        fusion_signals.append(
            f"TheSportsDB: {sportsdb_stats.get('total_shots')} shots "
            f"({sportsdb_stats.get('shots_on_target')} SoT) cross-check"
        )
    if market_odds and market_odds.get("under_15_implied_pct"):
        fusion_signals.append(
            f"Market: {market_odds.get('under_15_implied_pct')}% implied U1.5 "
            f"@ {market_odds.get('under_15_odds', '—')} ({market_odds.get('source', '1xbet')})"
        )
    if prs_summary.get("p_under_15"):
        fusion_signals.append(
            f"GAP pressure: {prs_summary.get('p_under_15')}% U1.5 "
            f"({prs_summary.get('profile', 'balanced').replace('_', ' ')}, "
            f"fair U {prs_summary.get('fair_under_odds') or '—'})"
        )

    return CombinedAnalysis(
        verdict=_verdict(confidence, agreement, best_rec),
        confidence=confidence,
        agreement=agreement,
        best_market=best_market,
        best_recommendation=best_rec,
        breakdown=breakdown,
        live_profile=live_profile,
        form_profile=form_profile,
        sp_profile=sp_prof,
        fotmob_profile=fm_prof,
        half=half,
        period_minute=elapsed,
        fusion_signals=fusion_signals,
        live_summary=live_summary,
        form_summary=form_summary,
        sp_summary=sp_summary,
        fotmob_summary=fm_summary,
        sportsdb_summary=sportsdb_stats or {},
        market_odds_summary=market_odds or {},
        pressure_summary=prs_summary,
    )


def combined_to_dict(analysis: CombinedAnalysis) -> dict[str, Any]:
    return asdict(analysis)