"""
Shots-volume heuristic for Under 1.5 / Under 2.5.

Reference profile (full match):
  - Combined total shots: 18–28 (both teams)
  - Leading side: often 10–14 shots
  - Trailing side: often 6–10 shots

Low, balanced volume supports unders; high volume or one-sided barrage leans over.
Live games: project to 90' from elapsed time; period markets also check half-scaled bands.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Full-match under-friendly bands
COMBINED_MIN = 18
COMBINED_MAX = 28
LEADER_MIN = 10
LEADER_MAX = 14
TRAILER_MIN = 6
TRAILER_MAX = 10

# Period-scaled (~half of full-match bands)
PERIOD_COMBINED_MIN = 9
PERIOD_COMBINED_MAX = 14
PERIOD_LEADER_MIN = 5
PERIOD_LEADER_MAX = 7
PERIOD_TRAILER_MIN = 3
PERIOD_TRAILER_MAX = 5


@dataclass
class ShotsVolumeResult:
    home_shots: int = 0
    away_shots: int = 0
    combined: int = 0
    projected_90: float = 0.0
    projected_leader: float = 0.0
    projected_trailer: float = 0.0
    in_combined_band: bool = False
    in_split_band: bool = False
    period_combined_band: bool = False
    period_split_band: bool = False
    under_15_boost: float = 0.0
    under_25_boost: float = 0.0
    score: float = 0.0
    profile: str = "unknown"
    preferred_market: str = ""
    signals: list[str] = field(default_factory=list)


def _split_shots(stats: Any) -> tuple[int, int, int]:
    home = int(getattr(stats, "home_shots", 0) or 0)
    away = int(getattr(stats, "away_shots", 0) or 0)
    total = int(getattr(stats, "total_shots", 0) or 0)
    if home + away <= 0 and total > 0:
        # No split available — treat as even for projection only
        return 0, 0, total
    if total <= 0:
        total = home + away
    return home, away, total


def _project(value: float, elapsed_full: int) -> float:
    if elapsed_full < 1:
        return 0.0
    return value * (90.0 / elapsed_full)


def analyze_shots_volume(
    live_stats: Any,
    minute: int = 0,
    half: str = "fh",
    period_goals: int = 0,
) -> ShotsVolumeResult:
    result = ShotsVolumeResult()
    home, away, combined = _split_shots(live_stats)
    result.home_shots = home
    result.away_shots = away
    result.combined = combined

    elapsed_full = max(int(minute or 0), 1)
    period_start = 0 if half == "fh" else 45
    elapsed_period = max(elapsed_full - period_start, 1)

    if combined <= 0 and elapsed_full < 8:
        result.profile = "too_early"
        result.signals.append("Shots volume: waiting for sample (need more minutes)")
        return result

    proj_total = _project(combined, elapsed_full)
    result.projected_90 = round(proj_total, 1)

    if home + away > 0:
        hi = max(home, away)
        lo = min(home, away)
        result.projected_leader = round(_project(hi, elapsed_full), 1)
        result.projected_trailer = round(_project(lo, elapsed_full), 1)
    else:
        result.projected_leader = 0.0
        result.projected_trailer = 0.0

    score = 0.0
    u15 = 0.0
    u25 = 0.0
    signals: list[str] = []

    # --- Full-match projected combined band (18–28) ---
    if 18 <= proj_total <= 28:
        result.in_combined_band = True
        score += 10
        u15 += 4
        u25 += 7
        signals.append(
            f"Shots volume: ~{proj_total:.0f} proj/90 in under band (18–28 combined)"
        )
    elif proj_total < 18 and elapsed_full >= 12:
        result.in_combined_band = True
        score += 12
        u15 += 8
        u25 += 6
        signals.append(
            f"Shots volume: low ~{proj_total:.0f} proj/90 (<18) — strong under lean"
        )
    elif 28 < proj_total <= 34:
        score += 2
        u15 -= 2
        u25 += 3
        signals.append(
            f"Shots volume: ~{proj_total:.0f} proj/90 slightly high — prefer U2.5 over U1.5"
        )
    elif proj_total > 34:
        score -= 10
        u15 -= 8
        u25 -= 6
        signals.append(
            f"Shots volume: high ~{proj_total:.0f} proj/90 (>34) — over risk"
        )

    # --- Leader/trailer split (10–14 vs 6–10) ---
    if result.projected_leader > 0:
        lead = result.projected_leader
        trail = result.projected_trailer
        if LEADER_MIN <= lead <= LEADER_MAX and TRAILER_MIN <= trail <= TRAILER_MAX:
            result.in_split_band = True
            score += 8
            u15 += 5
            u25 += 6
            signals.append(
                f"Classic under split: ~{lead:.0f}–{trail:.0f} "
                f"(leader 10–14, trailer 6–10)"
            )
        elif lead <= LEADER_MAX and trail <= TRAILER_MAX and (lead + trail) <= COMBINED_MAX:
            result.in_split_band = True
            score += 4
            u15 += 2
            u25 += 3
            signals.append(
                f"Balanced low split: ~{lead:.0f}–{trail:.0f} (under-friendly)"
            )
        elif lead >= 18 and trail <= 6:
            score -= 4
            u15 -= 3
            signals.append(
                f"One-sided barrage: ~{lead:.0f}–{trail:.0f} — cautious on U1.5"
            )
        elif lead >= 16:
            score -= 3
            u15 -= 2
            signals.append(f"High leader volume: ~{lead:.0f} shots proj — goal threat")

    # --- Period-level bands (scaled half of full-match rules) ---
    period_total = combined  # period stats when engine feeds period subgame
    if home + away > 0:
        p_hi, p_lo = max(home, away), min(home, away)
    else:
        p_hi = p_lo = 0

    # Scale period totals to full half (45') for fair band check
    period_proj = period_total * (45.0 / elapsed_period) if elapsed_period else period_total
    if PERIOD_COMBINED_MIN <= period_proj <= PERIOD_COMBINED_MAX:
        result.period_combined_band = True
        score += 4
        u15 += 3
        u25 += 4
        signals.append(
            f"Period shots: ~{period_proj:.0f}/45' in under band "
            f"({PERIOD_COMBINED_MIN}–{PERIOD_COMBINED_MAX})"
        )
    elif period_proj > PERIOD_COMBINED_MAX + 4 and elapsed_period >= 12:
        score -= 4
        u15 -= 3
        signals.append(f"Period shots hot: ~{period_proj:.0f}/45' — pressure building")

    if p_hi > 0:
        p_hi_proj = p_hi * (45.0 / elapsed_period)
        p_lo_proj = p_lo * (45.0 / elapsed_period)
        if (
            PERIOD_LEADER_MIN <= p_hi_proj <= PERIOD_LEADER_MAX
            and PERIOD_TRAILER_MIN <= p_lo_proj <= PERIOD_TRAILER_MAX
        ):
            result.period_split_band = True
            score += 3
            u15 += 2
            u25 += 3
            signals.append(
                f"Period split under-style: ~{p_hi_proj:.0f}–{p_lo_proj:.0f} "
                f"({PERIOD_LEADER_MIN}–{PERIOD_LEADER_MAX} vs "
                f"{PERIOD_TRAILER_MIN}–{PERIOD_TRAILER_MAX})"
            )

    # Prefer market: tighter volume → U1.5; mid band → U2.5
    if period_goals >= 2:
        preferred = "under_25" if period_goals == 2 else ""
    elif result.in_combined_band and proj_total < 22 and period_goals <= 1:
        preferred = "under_15"
    elif result.in_combined_band or result.period_combined_band:
        preferred = "under_25" if period_goals >= 1 else "under_15"
    elif proj_total > 34:
        preferred = ""
    else:
        preferred = "under_25" if u25 > u15 else ("under_15" if u15 > 0 else "")

    result.preferred_market = preferred
    result.under_15_boost = round(max(min(u15, 12.0), -10.0), 1)
    result.under_25_boost = round(max(min(u25, 12.0), -10.0), 1)
    result.score = round(max(min(score, 18.0), -12.0), 1)

    if score >= 12:
        result.profile = "under_band"
    elif score >= 5:
        result.profile = "mild_under"
    elif score <= -6:
        result.profile = "over_risk"
    else:
        result.profile = "neutral"

    if home + away > 0:
        signals.insert(
            0,
            f"Live shots {home}-{away} (combined {combined}"
            f"{f', ~{proj_total:.0f}/90' if elapsed_full >= 8 else ''})",
        )
    elif combined > 0:
        signals.insert(0, f"Live shots combined {combined} (~{proj_total:.0f}/90)")

    result.signals = signals
    return result


def shots_volume_score(
    live_stats: Any,
    minute: int = 0,
    half: str = "fh",
    period_goals: int = 0,
) -> tuple[float, list[str], dict[str, Any]]:
    r = analyze_shots_volume(live_stats, minute, half, period_goals)
    return r.score, r.signals, asdict(r)


def shots_confidence_adjust(
    base_conf: float,
    volume: Optional[dict[str, Any] | ShotsVolumeResult],
    market_key: str = "under_15",
) -> float:
    """Nudge U1.5 / U2.5 confidence from shots-volume bands."""
    if not volume:
        return base_conf
    if isinstance(volume, ShotsVolumeResult):
        boost_15 = volume.under_15_boost
        boost_25 = volume.under_25_boost
    else:
        boost_15 = float(volume.get("under_15_boost") or 0)
        boost_25 = float(volume.get("under_25_boost") or 0)

    if market_key == "under_15":
        delta = boost_15
    elif market_key == "under_25":
        delta = boost_25
    else:
        delta = min(boost_15, boost_25) * 0.5

    return round(min(max(base_conf + delta, 1.0), 96.0), 1)
