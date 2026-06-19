"""
Live First-Half Under Goals — prediction engine.
Used by CLI (predictor.py) and web app (app.py).
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from accumulator import MIN_CONFIDENCE, build_accumulators
from combined_analysis import build_combined_analysis, combined_to_dict
from filters import has_red_cards, is_excluded_match, is_excluded_raw
from onexbet_client import OneXBetClient, OneXBetMatch
from prophitbet_stats import PROPHIT_PROVIDER

SPORTSDB = "https://www.thesportsdb.com/api/v1/json/3"
REFRESH_SECONDS = 30
ONEXBET_CLIENT = OneXBetClient()

LEAGUE_BASELINES = {
    "FIFA World Cup": {
        "avg_fh_goals": 1.05,
        "under_05_fh_pct": 32,
        "under_15_fh_pct": 72,
        "under_25_fh_pct": 88,
        "avg_corners_fh": 4.8,
        "avg_shots_fh": 9.5,
        "avg_sot_fh": 3.2,
    },
    "default": {
        "avg_fh_goals": 1.15,
        "under_05_fh_pct": 30,
        "under_15_fh_pct": 67,
        "under_25_fh_pct": 85,
        "avg_corners_fh": 5.2,
        "avg_shots_fh": 10.5,
        "avg_sot_fh": 3.5,
        "under_05_sh_pct": 28,
        "under_15_sh_pct": 62,
        "under_25_sh_pct": 82,
    },
}

HALF_BASELINES = {
    "fh": ("under_15_fh_pct", 15, 20),
    "sh": ("under_15_sh_pct", 60, 65),
}

TIME_DECAY_0_0 = {
    15: {"over_05_fh": 55, "over_15_fh": 22},
    20: {"over_05_fh": 48, "over_15_fh": 19},
    30: {"over_05_fh": 35, "over_15_fh": 12},
}

WC_2026_OBSERVED = {
    "matches": 5,
    "avg_fh_goals": 1.40,
    "under_05_pct": 20,
    "under_15_pct": 60,
    "under_25_pct": 80,
}

TEAM_PROFILES = {
    "Switzerland": {"fh_scored_avg": 0.5, "fh_conceded_avg": 0.3, "fh_under_15_pct": 75, "style": "defensive"},
    "Bosnia-Herzegovina": {"fh_scored_avg": 0.5, "fh_conceded_avg": 0.5, "fh_under_15_pct": 70, "style": "balanced"},
    "Canada": {"fh_scored_avg": 0.5, "fh_conceded_avg": 0.5, "fh_under_15_pct": 65, "style": "attacking"},
    "Qatar": {"fh_scored_avg": 0.3, "fh_conceded_avg": 0.8, "fh_under_15_pct": 55, "style": "defensive_low"},
    "Colombia": {"fh_scored_avg": 0.8, "fh_conceded_avg": 0.3, "fh_under_15_pct": 60, "style": "patient_attack"},
    "Uzbekistan": {"fh_scored_avg": 0.2, "fh_conceded_avg": 0.5, "fh_under_15_pct": 70, "style": "defensive"},
}

LIVE_STATUSES = {"1H", "HT", "2H", "LIVE", "IN_PLAY", "PAUSED"}
UPCOMING_STATUSES = {"NS", "TBD", "SCHEDULED"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}


@dataclass
class LiveStats:
    minute: int
    home_goals: int
    away_goals: int
    period_minute: int = 0
    total_shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    home_possession: float = 50.0
    away_possession: float = 50.0
    fouls: int = 0
    home_shots: int = 0
    away_shots: int = 0
    dangerous_attacks: int = 0
    attacks: int = 0


@dataclass
class Prediction:
    match: str
    league: str
    kickoff: str
    status: str
    market: str
    confidence: float
    score: float
    signals: list[str] = field(default_factory=list)
    live_stats: Optional[LiveStats] = None
    recommendation: str = "WAIT"
    event_id: str = ""
    home_team: str = ""
    away_team: str = ""
    prophit_stats: Optional[dict] = None
    combined_analysis: Optional[dict] = None


@dataclass
class MatchCard:
    event_id: str
    home_team: str
    away_team: str
    league: str
    kickoff: str
    status: str
    score: str
    minute: int
    live_stats: Optional[dict]
    predictions: list[dict]
    home_badge: str = ""
    away_badge: str = ""
    in_entry_window: bool = False
    fh_goals: int = 0
    fh_score: str = "0-0"
    source: str = "1xbet"
    under_15_alive: bool = False
    under_25_alive: bool = False
    scored_filter: bool = False
    prophit_stats: Optional[dict] = None
    combined_analysis: Optional[dict] = None
    half: str = "fh"
    period_goals: int = 0
    period_score: str = "0-0"
    full_score: str = "0-0"
    is_half_time: bool = False
    period_name: str = ""
    period_minute: int = 0


class DataCache:
    """Thread-safe cache refreshed in the background."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "updated_at": None,
            "matches": [],
            "bet_signals": [],
            "baselines": {},
            "error": None,
        }
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self.refresh()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(REFRESH_SECONDS)
            self.refresh()

    def refresh(self):
        try:
            payload = build_dashboard_payload()
            with self._lock:
                self._data = payload
        except Exception as exc:
            with self._lock:
                self._data["error"] = str(exc)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


def _parse_kickoff(event: dict) -> Optional[datetime]:
    ts = event.get("strTimestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    date_str = event.get("dateEvent", "")
    time_str = event.get("strTime", "00:00:00")
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def estimate_minute(event: dict) -> int:
    status = event.get("strStatus", "NS")
    if status == "HT":
        return 45
    if status == "2H":
        kickoff = _parse_kickoff(event)
        if kickoff:
            elapsed = int((datetime.now(timezone.utc) - kickoff).total_seconds() / 60)
            return max(46, min(elapsed, 90))
        return 60
    if status in LIVE_STATUSES or status == "1H":
        kickoff = _parse_kickoff(event)
        if kickoff:
            elapsed = int((datetime.now(timezone.utc) - kickoff).total_seconds() / 60)
            return max(1, min(elapsed, 45))
    return 0


def fetch_matches() -> list[dict]:
    """Fetch today's soccer fixtures plus nearby dates and WC extras."""
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=d)).isoformat() for d in (-1, 0, 1)]
    seen: set[str] = set()
    matches: list[dict] = []

    for d in dates:
        try:
            r = requests.get(f"{SPORTSDB}/eventsday.php", params={"d": d, "s": "Soccer"}, timeout=20)
            for e in r.json().get("events") or []:
                eid = e.get("idEvent")
                if eid and eid not in seen:
                    seen.add(eid)
                    matches.append(e)
        except requests.RequestException:
            continue

    try:
        r = requests.get(f"{SPORTSDB}/eventsnextleague.php", params={"id": 4429}, timeout=20)
        for e in r.json().get("events") or []:
            eid = e.get("idEvent")
            if eid and eid not in seen:
                seen.add(eid)
                matches.append(e)
    except requests.RequestException:
        pass

    return matches


def fetch_live_stats(event_id: str) -> Optional[LiveStats]:
    try:
        r = requests.get(f"{SPORTSDB}/lookupeventstats.php", params={"id": event_id}, timeout=20)
        stats = r.json().get("eventstats")
    except requests.RequestException:
        return None

    if not stats:
        return None

    parsed: dict[str, tuple[int, int]] = {}
    for s in stats:
        key = s["strStat"].lower()
        parsed[key] = (int(s.get("intHome", 0) or 0), int(s.get("intAway", 0) or 0))

    home_shots, away_shots = parsed.get("total shots", (0, 0))
    home_sot, away_sot = parsed.get("shots on goal", (0, 0))
    home_corners, away_corners = parsed.get("corner kicks", parsed.get("corners", (0, 0)))
    home_poss, away_poss = parsed.get("ball possession", (0, 0))
    home_fouls, away_fouls = parsed.get("fouls", (0, 0))

    if home_poss == 0 and away_poss == 0:
        home_poss, away_poss = 50, 50
    elif home_poss > 0 and away_poss == 0:
        away_poss = 100 - home_poss

    return LiveStats(
        minute=0,
        home_goals=0,
        away_goals=0,
        total_shots=home_shots + away_shots,
        shots_on_target=home_sot + away_sot,
        corners=home_corners + away_corners,
        home_possession=float(home_poss),
        away_possession=float(away_poss),
        fouls=home_fouls + away_fouls,
        home_shots=home_shots,
        away_shots=away_shots,
    )


def score_period_under(
    stats: LiveStats,
    home: str,
    away: str,
    league: str,
    half: str = "fh",
    prophit_stats: Optional[dict] = None,
    combined: Optional[dict] = None,
) -> dict[str, Prediction]:
    baseline = LEAGUE_BASELINES.get(league, LEAGUE_BASELINES["default"])
    bl_key, entry_start, entry_end = HALF_BASELINES[half]
    total_goals = stats.home_goals + stats.away_goals
    minute = stats.minute
    half_label = half.upper()
    period_name = "First Half" if half == "fh" else "Second Half"
    elapsed = max(minute - (0 if half == "fh" else 45), 1)

    if combined is None:
        combined = combined_to_dict(build_combined_analysis(
            stats, prophit_stats, total_goals, minute, baseline[bl_key], half=half,
        ))

    signals: list[str] = list(combined.get("fusion_signals") or [])
    total_score = combined["breakdown"]["total"]
    base_conf = combined["confidence"]
    conflict = combined.get("agreement") == "CONFLICT"
    sot_pm = stats.shots_on_target / elapsed
    shots_pm = stats.total_shots / elapsed

    if minute < entry_start:
        signals.append(f"Before {half_label} entry window — wait until {entry_start}'")

    def _conf(value: float) -> float:
        return round(min(max(value, 1), 96), 1)

    def _rec(conf: float, bet_at: float, min_minute: int) -> str:
        if conflict:
            return "WATCH" if conf >= bet_at - 5 else "WAIT"
        if conf >= bet_at and minute >= min_minute:
            return "BET"
        return "WATCH" if conf >= bet_at - 8 else "WAIT"

    results: dict[str, Prediction] = {}
    u05_key = f"Under 0.5 {half_label}"
    u15_key = f"Under 1.5 {half_label}"
    u25_key = f"Under 2.5 {half_label}"

    if total_goals == 0:
        u05_conf = _conf(base_conf + (9 if half == "fh" else 7))
        u05_rec = _rec(u05_conf, 68, entry_end - 2)
        results[u05_key] = Prediction(
            match=f"{home} vs {away}", league=league, kickoff="", status="LIVE",
            market=f"Under 0.5 {period_name} Goals", confidence=u05_conf, score=total_score,
            signals=signals.copy(), live_stats=stats, recommendation=u05_rec,
            home_team=home, away_team=away, prophit_stats=prophit_stats, combined_analysis=combined,
        )
    else:
        results[u05_key] = Prediction(
            match=f"{home} vs {away}", league=league, kickoff="", status="LIVE",
            market=f"Under 0.5 {period_name} Goals", confidence=5, score=0,
            signals=[f"1+ {half_label} goals — under 0.5 dead"], recommendation="SKIP",
            home_team=home, away_team=away, prophit_stats=prophit_stats, combined_analysis=combined,
        )

    if total_goals == 0:
        u15_conf = _conf(base_conf)
        u15_rec = _rec(u15_conf, 64, entry_start)
    elif total_goals == 1:
        u15_conf = _conf(base_conf + 11)
        if shots_pm < 0.52 and sot_pm < 0.22:
            u15_conf = _conf(u15_conf + 5)
            signals.append(f"1 {half_label} goal but tempo still low — under 1.5 holds")
        late_min = 78 if half == "sh" else 35
        if minute >= late_min:
            u15_conf = _conf(u15_conf + 7)
        u15_rec = _rec(u15_conf, 66, entry_start - 5)
        signals.append(f"1 {half_label} goal — under 1.5 still alive")
    else:
        u15_conf, u15_rec = 5, "SKIP"
        signals.append(f"{total_goals} {half_label} goals — under 1.5 dead")

    results[u15_key] = Prediction(
        match=f"{home} vs {away}", league=league, kickoff="", status="LIVE",
        market=f"Under 1.5 {period_name} Goals", confidence=u15_conf, score=total_score,
        signals=signals.copy(), live_stats=stats, recommendation=u15_rec,
        home_team=home, away_team=away, prophit_stats=prophit_stats, combined_analysis=combined,
    )

    if total_goals <= 1:
        u25_conf = _conf(base_conf + (17 if half == "fh" else 14))
        u25_rec = _rec(u25_conf, 70, entry_start)
    elif total_goals == 2:
        u25_conf = _conf(base_conf + 7)
        slow_min = 72 if half == "sh" else 30
        if shots_pm < 0.52 and minute >= slow_min:
            u25_conf = _conf(u25_conf + 9)
            signals.append(f"2 {half_label} goals but tempo slowing — under 2.5 viable")
        u25_rec = _rec(u25_conf, 68, entry_start - 5)
        signals.append(f"2 {half_label} goals — under 2.5 still alive")
    else:
        u25_conf, u25_rec = 5, "SKIP"
        signals.append(f"{total_goals} {half_label} goals — under 2.5 dead")

    results[u25_key] = Prediction(
        match=f"{home} vs {away}", league=league, kickoff="", status="LIVE",
        market=f"Under 2.5 {period_name} Goals", confidence=u25_conf, score=total_score,
        signals=signals.copy(), live_stats=stats, recommendation=u25_rec,
        home_team=home, away_team=away, prophit_stats=prophit_stats, combined_analysis=combined,
    )

    return results


def score_live_under(*args, **kwargs) -> dict[str, Prediction]:
    """Backward-compatible alias for first-half scoring."""
    kwargs.setdefault("half", "fh")
    return score_period_under(*args, **kwargs)


def score_prematch_under(home: str, away: str, league: str, kickoff: str) -> Prediction:
    baseline = LEAGUE_BASELINES.get(league, LEAGUE_BASELINES["default"])
    home_prof = TEAM_PROFILES.get(home, {})
    away_prof = TEAM_PROFILES.get(away, {})
    signals: list[str] = []

    combined_under_15 = (
        home_prof.get("fh_under_15_pct", baseline["under_15_fh_pct"])
        + away_prof.get("fh_under_15_pct", baseline["under_15_fh_pct"])
    ) / 2

    league_rate = baseline["under_15_fh_pct"]
    blended = combined_under_15 * 0.5 + league_rate * 0.5
    score = blended * 0.85

    styles = [home_prof.get("style", ""), away_prof.get("style", "")]
    if any("defensive" in s for s in styles):
        score += 7
        signals.append("Defensive team profile detected")
    if home_prof.get("style") == "defensive_low" or away_prof.get("style") == "defensive_low":
        score += 6
        signals.append("Low-scoring team in tournament")

    combined_fh_avg = home_prof.get("fh_scored_avg", 0.5) + away_prof.get("fh_conceded_avg", 0.5)
    combined_fh_avg += away_prof.get("fh_scored_avg", 0.5) + home_prof.get("fh_conceded_avg", 0.5)
    if combined_fh_avg < 1.6:
        score += 6
        signals.append(f"Low combined FH goal expectation ({combined_fh_avg:.1f})")

    if league == "FIFA World Cup":
        score += 4
        signals.append("World Cup — 72% historical under 1.5 FH rate")

    if {home, away} == {"Canada", "Qatar"}:
        score += 5
        signals.append("Qatar rarely scores early; Canada controls but slow starters")
    if {home, away} == {"Switzerland", "Bosnia-Herzegovina"}:
        score += 4
        signals.append("Both teams profile as FH under teams; Bosnia drew 1-1 R1")

    conf = min(score, 88)
    rec = "PRE-MATCH CANDIDATE" if conf >= 62 else "LOW PRIORITY"

    return Prediction(
        match=f"{home} vs {away}", league=league, kickoff=kickoff, status="NS",
        market="Under 1.5 First Half Goals", confidence=conf, score=score,
        signals=signals, recommendation=rec, home_team=home, away_team=away,
    )


def _stats_to_dict(stats: Optional[LiveStats]) -> Optional[dict]:
    return asdict(stats) if stats else None


def _pred_to_dict(p: Prediction) -> dict:
    d = asdict(p)
    d["live_stats"] = _stats_to_dict(p.live_stats)
    return d


def analyze_match(event: dict) -> tuple[list[Prediction], int, Optional[LiveStats]]:
    home = event["strHomeTeam"]
    away = event["strAwayTeam"]
    league = event.get("strLeague", "default")
    kickoff = f"{event.get('dateEvent', '')} {event.get('strTime', '')}"
    status = event.get("strStatus", "NS")
    minute = estimate_minute(event)
    preds: list[Prediction] = []
    live_stats: Optional[LiveStats] = None

    if status in UPCOMING_STATUSES:
        p = score_prematch_under(home, away, league, kickoff)
        p.event_id = event.get("idEvent", "")
        preds.append(p)
        return preds, minute, None

    if status in LIVE_STATUSES or status in {"1H", "HT", "2H"}:
        live_stats = fetch_live_stats(event["idEvent"])
        if live_stats:
            live_stats.minute = minute
            live_stats.home_goals = int(event.get("intHomeScore") or 0)
            live_stats.away_goals = int(event.get("intAwayScore") or 0)
            for p in score_live_under(live_stats, home, away, league).values():
                p.kickoff = kickoff
                p.event_id = event.get("idEvent", "")
                preds.append(p)
        else:
            # Live but no stats yet — use score only
            live_stats = LiveStats(
                minute=minute,
                home_goals=int(event.get("intHomeScore") or 0),
                away_goals=int(event.get("intAwayScore") or 0),
            )
            for p in score_live_under(live_stats, home, away, league).values():
                p.kickoff = kickoff
                p.event_id = event.get("idEvent", "")
                preds.append(p)
        return preds, minute, live_stats

    return preds, minute, None


def _onexbet_to_live_stats(m: OneXBetMatch, half: str = "fh", period_stats: Optional[dict] = None) -> LiveStats:
    s = period_stats or m.stats
    if half == "fh":
        home_goals, away_goals = m.fh_home, m.fh_away
    else:
        home_goals, away_goals = m.sh_home, m.sh_away
    return LiveStats(
        minute=m.minute,
        period_minute=m.period_minute,
        home_goals=home_goals,
        away_goals=away_goals,
        total_shots=s.get("total_shots", 0),
        shots_on_target=s.get("shots_on_target", 0),
        corners=s.get("corners", 0),
        home_possession=m.home_possession,
        away_possession=100 - m.home_possession,
        fouls=s.get("fouls", 0),
        home_shots=s.get("shots_on_target_home", 0) + s.get("shots_off_target_home", 0),
        away_shots=s.get("shots_on_target_away", 0) + s.get("shots_off_target_away", 0),
        dangerous_attacks=s.get("dangerous_attacks", 0),
        attacks=s.get("attacks", 0),
    )


def analyze_onexbet_match(
    m: OneXBetMatch,
    half: str = "fh",
    prophit_stats: Optional[dict] = None,
    period_stats: Optional[dict] = None,
) -> tuple[list[Prediction], dict]:
    live = _onexbet_to_live_stats(m, half=half, period_stats=period_stats)
    baseline = LEAGUE_BASELINES.get(m.league, LEAGUE_BASELINES["default"])
    bl_key = HALF_BASELINES[half][0]
    period_goals = m.fh_goals if half == "fh" else m.sh_goals
    combined = combined_to_dict(build_combined_analysis(
        live, prophit_stats, period_goals, m.minute, baseline[bl_key], half=half,
    ))
    preds = list(score_period_under(
        live, m.home_team, m.away_team, m.league, half=half,
        prophit_stats=prophit_stats, combined=combined,
    ).values())
    for p in preds:
        p.event_id = str(m.game_id)
        p.kickoff = m.period_name
        p.status = "1H" if half == "fh" else "2H"
    return preds, combined


def _qualifies_60(p: Prediction) -> bool:
    return p.confidence >= MIN_CONFIDENCE and p.recommendation != "SKIP"


def _filter_preds_60(preds: list[Prediction]) -> list[Prediction]:
    return [p for p in preds if _qualifies_60(p)]


def _build_match_card(
    m: OneXBetMatch,
    half: str,
    prophit_stats: Optional[dict],
    preds: list[Prediction],
    combined: dict,
    live_stats: LiveStats,
) -> MatchCard:
    _, entry_start, entry_end = HALF_BASELINES[half]
    if half == "fh":
        p_home, p_away, p_goals = m.fh_home, m.fh_away, m.fh_goals
        status = "1H"
    else:
        p_home, p_away, p_goals = m.sh_home, m.sh_away, m.sh_goals
        status = "2H"

    under_15_alive = p_goals <= 1
    under_25_alive = p_goals <= 2
    scored = p_goals >= 1
    qualified_preds = _filter_preds_60(preds)

    return MatchCard(
        event_id=str(m.game_id),
        home_team=m.home_team,
        away_team=m.away_team,
        league=m.league,
        kickoff=m.period_name,
        status=status,
        score=f"{p_home} - {p_away}",
        minute=m.minute,
        period_minute=m.period_minute,
        live_stats=_stats_to_dict(live_stats),
        predictions=[_pred_to_dict(p) for p in qualified_preds],
        in_entry_window=entry_start <= m.minute <= entry_end,
        fh_goals=p_goals,
        fh_score=f"{p_home}-{p_away}",
        source="1xbet",
        under_15_alive=under_15_alive,
        under_25_alive=under_25_alive,
        scored_filter=scored and (under_15_alive or under_25_alive),
        prophit_stats=prophit_stats,
        combined_analysis=combined,
        half=half,
        period_goals=p_goals,
        period_score=f"{p_home}-{p_away}",
        full_score=f"{m.home_score}-{m.away_score}",
        is_half_time=m.is_half_time,
        period_name=m.period_name,
    )


def _build_half_time_card(m: OneXBetMatch, prophit_stats: Optional[dict]) -> MatchCard:
    return MatchCard(
        event_id=str(m.game_id),
        home_team=m.home_team,
        away_team=m.away_team,
        league=m.league,
        kickoff=m.period_name or "Half-time",
        status="HT",
        score=f"{m.fh_home} - {m.fh_away}",
        minute=45,
        period_minute=45,
        live_stats=_stats_to_dict(_onexbet_to_live_stats(m, half="fh")),
        predictions=[],
        fh_goals=m.fh_goals,
        fh_score=f"{m.fh_home}-{m.fh_away}",
        source="1xbet",
        under_15_alive=m.fh_goals <= 1,
        under_25_alive=m.fh_goals <= 2,
        scored_filter=m.fh_goals >= 1,
        prophit_stats=prophit_stats,
        combined_analysis=None,
        half="ht",
        period_goals=m.fh_goals,
        period_score=f"{m.fh_home}-{m.fh_away}",
        full_score=f"{m.home_score}-{m.away_score}",
        is_half_time=True,
        period_name=m.period_name or "Half-time",
    )


def build_dashboard_payload() -> dict[str, Any]:
    cards: list[MatchCard] = []
    bet_signals: list[dict] = []
    scored_under_15: list[dict] = []
    scored_under_25: list[dict] = []

    PROPHIT_PROVIDER.ensure_loaded(background=True)

    raw_live = ONEXBET_CLIENT.fetch_live_football()
    total_live = len(raw_live)
    excluded_count = 0
    fh_count = 0
    sh_count = 0
    ht_count = 0

    for raw in raw_live:
        if is_excluded_raw(raw):
            excluded_count += 1
            continue

        m = ONEXBET_CLIENT.parse_match(raw)
        if is_excluded_match(m.home_team, m.away_team, m.league, m.country):
            excluded_count += 1
            continue

        if has_red_cards(m.stats):
            excluded_count += 1
            continue

        prophit_stats = PROPHIT_PROVIDER.lookup_match(m.home_team, m.away_team)

        if m.is_half_time:
            cards.append(_build_half_time_card(m, prophit_stats))
            ht_count += 1
            continue

        if not m.is_first_half and not m.is_second_half:
            continue
        halves: list[str] = []
        if m.is_first_half:
            halves.append("fh")
        if m.is_second_half:
            halves.append("sh")

        for half in halves:
            period_stats = ONEXBET_CLIENT.fetch_period_subgame_stats(m, half)
            if has_red_cards(period_stats):
                continue
            preds, combined = analyze_onexbet_match(
                m, half=half, prophit_stats=prophit_stats, period_stats=period_stats,
            )
            if not preds:
                continue

            live_stats = _onexbet_to_live_stats(m, half=half, period_stats=period_stats)
            card = _build_match_card(m, half, prophit_stats, preds, combined, live_stats)
            if not card.predictions:
                continue
            cards.append(card)
            if half == "fh":
                fh_count += 1
            else:
                sh_count += 1

            card_dict = asdict(card)
            p_goals = card.period_goals
            scored = p_goals >= 1
            for p in preds:
                if not _qualifies_60(p):
                    continue
                pd = _pred_to_dict(p)
                pd["minute"] = card.minute
                pd["half"] = card.half
                pd["period_score"] = card.period_score
                pd["full_score"] = card.full_score
                pd["is_half_time"] = card.is_half_time
                pd["period_minute"] = card.period_minute
                if p.recommendation in ("BET", "WATCH"):
                    bet_signals.append(pd)

                if scored and p.recommendation in ("BET", "WATCH"):
                    if "Under 1.5" in p.market and card.under_15_alive:
                        scored_under_15.append({**card_dict, "pick": pd})
                    if "Under 2.5" in p.market and card.under_25_alive:
                        scored_under_25.append({**card_dict, "pick": pd})

    cards.sort(key=lambda c: (
        0 if (c.combined_analysis or {}).get("verdict") == "STRONG BET" else 1,
        0 if c.scored_filter else 1,
        0 if c.in_entry_window else 1,
        -(c.combined_analysis or {}).get("confidence", 0),
        -max((p["confidence"] for p in c.predictions), default=0),
    ))

    scored_under_15.sort(key=lambda x: -x["pick"]["confidence"])
    scored_under_25.sort(key=lambda x: -x["pick"]["confidence"])

    match_dicts = [asdict(c) for c in cards]
    accumulators = build_accumulators(match_dicts)

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_seconds": REFRESH_SECONDS,
        "source": "1xbet",
        "total_live_football": total_live,
        "excluded_count": excluded_count,
        "first_half_count": fh_count,
        "second_half_count": sh_count,
        "half_time_count": ht_count,
        "match_count": len(cards),
        "bet_signal_count": len(bet_signals),
        "scored_filter_count": sum(1 for c in cards if c.scored_filter),
        "matches": match_dicts,
        "bet_signals": bet_signals,
        "scored_under_15": scored_under_15,
        "scored_under_25": scored_under_25,
        "accumulators": accumulators,
        "baselines": {
            "wc_under_15_pct": LEAGUE_BASELINES["default"]["under_15_fh_pct"],
            "wc_avg_fh_goals": LEAGUE_BASELINES["default"]["avg_fh_goals"],
            "wc_2026_observed": WC_2026_OBSERVED,
            "time_decay_20_under_15": 100 - TIME_DECAY_0_0[20]["over_15_fh"],
        },
        "prophitbet": PROPHIT_PROVIDER.status(),
        "min_confidence": MIN_CONFIDENCE,
        "error": None,
    }