"""
FotMob live match statistics — xG, shots, possession, period splits.
Unofficial public API used for cross-validation of 1xBet live tempo.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Optional

import requests

from team_aliases import apply_team_alias, league_context_score

BASE_URL = "https://www.fotmob.com/api/data"
FUZZY_TEAM_THRESHOLD = 0.78
FUZZY_LEAGUE_MIN_SCORE = 0.35
MATCHES_TTL_SECONDS = 120
DETAIL_TTL_SECONDS = 90
DETAIL_MIN_INTERVAL = 1.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _normalize_team(name: str) -> str:
    name = apply_team_alias(name)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"\b(fc|cf|sc|ac|fk|cd|ud|sv|vfb|vfl|rb|tsg|1\.)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _pair_key(home: str, away: str) -> str:
    return f"{_normalize_team(home)}|{_normalize_team(away)}"


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(str(val).strip().replace("%", ""))
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or val == "":
            return default
        if isinstance(val, str) and "(" in val:
            val = val.split("(", 1)[0].strip()
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _period_key(half: str) -> str:
    return "FirstHalf" if half == "fh" else "SecondHalf"


def _extract_stat(period_stats: dict[str, Any], key: str) -> tuple[int, int]:
    for group in period_stats.get("stats", []):
        for item in group.get("stats", []):
            if item.get("key") == key:
                vals = item.get("stats") or [0, 0]
                return _safe_int(vals[0]), _safe_int(vals[1])
    return 0, 0


def _extract_float_stat(period_stats: dict[str, Any], key: str) -> tuple[float, float]:
    for group in period_stats.get("stats", []):
        for item in group.get("stats", []):
            if item.get("key") == key:
                vals = item.get("stats") or [0, 0]
                return _safe_float(vals[0]), _safe_float(vals[1])
    return 0.0, 0.0


@dataclass
class FotMobMatchStats:
    match_id: int = 0
    home_team: str = ""
    away_team: str = ""
    league: str = ""
    half: str = "fh"
    home_goals: int = 0
    away_goals: int = 0
    total_shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    home_possession: float = 50.0
    away_possession: float = 50.0
    home_xg: float = 0.0
    away_xg: float = 0.0
    total_xg: float = 0.0
    big_chances: int = 0
    home_red_cards: int = 0
    away_red_cards: int = 0
    is_live: bool = False
    is_finished: bool = False
    source: str = "fotmob.com"


def _parse_period_stats(
    detail: dict[str, Any],
    half: str,
    home: str,
    away: str,
) -> Optional[FotMobMatchStats]:
    content = detail.get("content") or {}
    general = detail.get("general") or content.get("general") or {}
    header = detail.get("header") or {}
    status = header.get("status") or {}

    periods = (content.get("stats") or {}).get("Periods") or {}
    period_stats = periods.get(_period_key(half)) or periods.get("All")
    if not period_stats:
        return None

    h_shots, a_shots = _extract_stat(period_stats, "total_shots")
    h_sot, a_sot = _extract_stat(period_stats, "ShotsOnTarget")
    h_corners, a_corners = _extract_stat(period_stats, "corners")
    h_poss, a_poss = _extract_stat(period_stats, "BallPossesion")
    h_xg, a_xg = _extract_float_stat(period_stats, "expected_goals")
    h_bc, a_bc = _extract_stat(period_stats, "big_chance")

    teams = header.get("teams") or []
    home_goals = _safe_int(teams[0].get("score")) if len(teams) > 0 else 0
    away_goals = _safe_int(teams[1].get("score")) if len(teams) > 1 else 0

    if half == "fh" and status.get("halfs", {}).get("firstHalfEnded"):
        pass
    elif half == "sh" and not status.get("halfs", {}).get("secondHalfStarted"):
        return None

    return FotMobMatchStats(
        match_id=_safe_int(general.get("matchId")),
        home_team=home,
        away_team=away,
        league=general.get("leagueName", ""),
        half=half,
        home_goals=home_goals,
        away_goals=away_goals,
        total_shots=h_shots + a_shots,
        shots_on_target=h_sot + a_sot,
        corners=h_corners + a_corners,
        home_possession=float(h_poss or 50),
        away_possession=float(a_poss or 50),
        home_xg=h_xg,
        away_xg=a_xg,
        total_xg=round(h_xg + a_xg, 2),
        big_chances=h_bc + a_bc,
        home_red_cards=_safe_int(status.get("numberOfHomeRedCards")),
        away_red_cards=_safe_int(status.get("numberOfAwayRedCards")),
        is_live=bool(status.get("started") and not status.get("finished")),
        is_finished=bool(status.get("finished")),
    )


class FotMobStatsProvider:
    """FotMob matches index + per-match detail cache."""

    _instance: Optional["FotMobStatsProvider"] = None

    def __init__(self):
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._match_index: dict[str, dict[str, Any]] = {}
        self._detail_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._index_loaded_at: float = 0.0
        self._last_detail_fetch: float = 0.0
        self._loading = False
        self._error: Optional[str] = None
        self._index_count = 0
        self._detail_fetches = 0

    @classmethod
    def get(cls) -> "FotMobStatsProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        return {
            "index_matches": self._index_count,
            "detail_cache": len(self._detail_cache),
            "detail_fetches": self._detail_fetches,
            "index_age_seconds": round(time.time() - self._index_loaded_at, 1) if self._index_loaded_at else None,
            "loading": self._loading,
            "error": self._error,
            "source": "fotmob.com (xG + period stats)",
        }

    def ensure_loaded(self, background: bool = True) -> None:
        if time.time() - self._index_loaded_at < MATCHES_TTL_SECONDS:
            return
        if background:
            if not self._loading:
                threading.Thread(target=self._load_index, daemon=True).start()
        else:
            self._load_index()

    def _load_index(self) -> None:
        with self._lock:
            if self._loading:
                return
            self._loading = True
        try:
            today = datetime.now(timezone.utc).date()
            index: dict[str, dict[str, Any]] = {}
            for offset in (-1, 0, 1):
                d = (today + timedelta(days=offset)).strftime("%Y%m%d")
                r = self._session.get(f"{BASE_URL}/matches?date={d}", timeout=25)
                r.raise_for_status()
                for league in r.json().get("leagues", []):
                    league_name = league.get("name", "")
                    league_ccode = league.get("ccode", "") or ""
                    parent_name = league.get("parentLeagueName", "") or ""
                    for m in league.get("matches", []):
                        home = (m.get("home") or {}).get("name", "")
                        away = (m.get("away") or {}).get("name", "")
                        mid = m.get("id")
                        if not home or not away or not mid:
                            continue
                        entry = {
                            "match_id": int(mid),
                            "home_team": home,
                            "away_team": away,
                            "league": league_name,
                            "ccode": league_ccode,
                            "parent_league": parent_name,
                            "status": m.get("status", {}),
                        }
                        index[_pair_key(home, away)] = entry
            with self._lock:
                self._match_index = index
                self._index_count = len(index)
                self._index_loaded_at = time.time()
                self._error = None
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._loading = False

    def _resolve_match(
        self,
        home: str,
        away: str,
        league: str = "",
        country: str = "",
    ) -> Optional[dict[str, Any]]:
        home_alias = apply_team_alias(home)
        away_alias = apply_team_alias(away)
        key = _pair_key(home_alias, away_alias)
        with self._lock:
            if key in self._match_index:
                entry = self._match_index[key]
                if self._league_ok(league, country, entry):
                    return entry

        best_key = None
        best_combined = 0.0
        with self._lock:
            entries = list(self._match_index.items())
        hn, an = _normalize_team(home_alias), _normalize_team(away_alias)
        for cand_key, entry in entries:
            if "|" not in cand_key:
                continue
            ch, ca = cand_key.split("|", 1)
            team_score = (
                SequenceMatcher(None, hn, ch).ratio()
                + SequenceMatcher(None, an, ca).ratio()
            ) / 2
            if team_score < FUZZY_TEAM_THRESHOLD:
                continue
            ctx_score = league_context_score(
                league,
                country,
                entry.get("league", ""),
                entry.get("ccode", ""),
            )
            if ctx_score < FUZZY_LEAGUE_MIN_SCORE:
                continue
            combined = team_score * 0.65 + ctx_score * 0.35
            if combined > best_combined:
                best_combined = combined
                best_key = cand_key
        if best_key:
            with self._lock:
                return self._match_index.get(best_key)
        return None

    @staticmethod
    def _league_ok(league: str, country: str, entry: dict[str, Any]) -> bool:
        if not league and not country:
            return True
        return league_context_score(
            league,
            country,
            entry.get("league", ""),
            entry.get("ccode", ""),
        ) >= FUZZY_LEAGUE_MIN_SCORE

    def _fetch_detail(self, match_id: int) -> Optional[dict[str, Any]]:
        cache_key = str(match_id)
        with self._lock:
            cached = self._detail_cache.get(cache_key)
            if cached and time.time() - cached[0] < DETAIL_TTL_SECONDS:
                return cached[1]

        elapsed = time.time() - self._last_detail_fetch
        if elapsed < DETAIL_MIN_INTERVAL:
            time.sleep(DETAIL_MIN_INTERVAL - elapsed)

        try:
            r = self._session.get(f"{BASE_URL}/matchDetails?matchId={match_id}", timeout=25)
            r.raise_for_status()
            data = r.json()
            with self._lock:
                self._detail_cache[cache_key] = (time.time(), data)
                self._detail_fetches += 1
                self._last_detail_fetch = time.time()
                if len(self._detail_cache) > 200:
                    oldest = sorted(self._detail_cache.items(), key=lambda x: x[1][0])[:50]
                    for k, _ in oldest:
                        self._detail_cache.pop(k, None)
            return data
        except requests.RequestException:
            with self._lock:
                cached = self._detail_cache.get(cache_key)
            return cached[1] if cached else None

    def lookup_match(
        self,
        home: str,
        away: str,
        half: str = "fh",
        league: str = "",
        country: str = "",
    ) -> Optional[dict[str, Any]]:
        self.ensure_loaded(background=True)
        if self._index_loaded_at == 0:
            self._load_index()

        resolved = self._resolve_match(home, away, league=league, country=country)
        if not resolved:
            return None

        detail = self._fetch_detail(resolved["match_id"])
        if not detail:
            return None

        stats = _parse_period_stats(detail, half, home, away)
        if not stats:
            return None
        return asdict(stats)


def fotmob_tempo_profile(stats: Optional[dict[str, Any]], minute: int, half: str) -> tuple[float, str, dict[str, Any]]:
    """Score FotMob period tempo up to 12 pts (xG + shots/min)."""
    if not stats:
        return 0.0, "unknown", {}

    elapsed = max(minute - (0 if half == "fh" else 45), 1)
    shots_pm = stats.get("total_shots", 0) / elapsed
    sot_pm = stats.get("shots_on_target", 0) / elapsed
    xg = stats.get("total_xg", 0.0)
    xg_pm = xg / elapsed
    corners_pm = stats.get("corners", 0) / elapsed

    score = 0.0
    if xg_pm < 0.04:
        score += 5
    elif xg_pm < 0.07:
        score += 3
    elif xg_pm > 0.15:
        score -= 4

    if shots_pm < 0.35:
        score += 4
    elif shots_pm < 0.55:
        score += 2
    elif shots_pm > 0.85:
        score -= 3

    if sot_pm < 0.12:
        score += 2
    if corners_pm < 0.2:
        score += 1

    score = max(0.0, min(score, 12.0))
    if score >= 9:
        profile = "very_slow"
    elif score >= 6:
        profile = "slow"
    elif score >= 3:
        profile = "average"
    else:
        profile = "fast"

    return score, profile, {
        "total_xg": stats.get("total_xg", 0),
        "xg_per_min": round(xg_pm, 3),
        "shots": stats.get("total_shots", 0),
        "shots_per_min": round(shots_pm, 2),
        "sot": stats.get("shots_on_target", 0),
        "corners": stats.get("corners", 0),
        "big_chances": stats.get("big_chances", 0),
        "possession": round(stats.get("home_possession", 50), 0),
    }


def fotmob_live_agreement(live_profile: str, fotmob_profile: str) -> tuple[float, list[str]]:
    signals: list[str] = []
    if live_profile == "unknown" or fotmob_profile == "unknown":
        return 0.0, signals
    slow = {"very_slow", "slow"}
    fast = {"fast"}
    if live_profile in slow and fotmob_profile in slow:
        signals.append(f"FotMob xG confirms 1xBet slow tempo ({live_profile}/{fotmob_profile})")
        return 6.0, signals
    if live_profile in fast and fotmob_profile in fast:
        signals.append("FotMob and 1xBet both show high tempo — under risk")
        return -6.0, signals
    if live_profile in slow and fotmob_profile in fast:
        signals.append("FotMob hotter than 1xBet live — verify before betting under")
        return -4.0, signals
    if live_profile in fast and fotmob_profile in slow:
        signals.append("1xBet fast but FotMob xG low — possible false tempo reading")
        return -2.0, signals
    return 1.0, signals


FOTMOB_PROVIDER = FotMobStatsProvider.get()