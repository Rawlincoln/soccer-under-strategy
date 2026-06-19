"""
API-Football (api-sports.io) live fixtures + statistics.
Requires API_FOOTBALL_KEY environment variable (free tier ~100 req/day).
"""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

import requests

BASE_URL = "https://v3.football.api-sports.io"
LIVE_TTL_SECONDS = 90
STATS_TTL_SECONDS = 180
HEADERS_BASE = {"User-Agent": "ProPunter/1.0"}


def _normalize_team(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"\b(fc|cf|sc|ac|fk|cd|ud|sv|vfb|vfl|rb|tsg|1\.)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _pair_key(home: str, away: str) -> str:
    return f"{_normalize_team(home)}|{_normalize_team(away)}"


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return default


@dataclass
class APIFootballMatchStats:
    fixture_id: int = 0
    home_team: str = ""
    away_team: str = ""
    league: str = ""
    status: str = ""
    minute: int = 0
    total_shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    home_possession: float = 50.0
    away_possession: float = 50.0
    fouls: int = 0
    home_goals: int = 0
    away_goals: int = 0
    source: str = "api-football.com"


def _stat_value(team_stats: list[dict], stat_name: str) -> int:
    for item in team_stats:
        if (item.get("type") or "").lower() == stat_name.lower():
            raw = item.get("value")
            if raw is None:
                return 0
            if isinstance(raw, str) and "%" in raw:
                return _safe_int(raw.replace("%", ""))
            return _safe_int(raw)
    return 0


class APIFootballStatsProvider:
    _instance: Optional["APIFootballStatsProvider"] = None

    def __init__(self):
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(HEADERS_BASE)
        self._api_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
        self._live_index: dict[str, dict[str, Any]] = {}
        self._stats_cache: dict[str, tuple[float, APIFootballMatchStats]] = {}
        self._live_loaded_at: float = 0.0
        self._loading = False
        self._error: Optional[str] = None
        self._requests_today = 0
        self._rate_remaining: Optional[str] = None

    @classmethod
    def get(cls) -> "APIFootballStatsProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "live_fixtures": len(self._live_index),
            "stats_cache": len(self._stats_cache),
            "live_age_seconds": round(time.time() - self._live_loaded_at, 1) if self._live_loaded_at else None,
            "rate_remaining": self._rate_remaining,
            "loading": self._loading,
            "error": self._error,
            "source": "api-football.com",
        }

    def ensure_loaded(self, background: bool = True) -> None:
        if not self.enabled:
            return
        if time.time() - self._live_loaded_at < LIVE_TTL_SECONDS:
            return
        if background:
            if not self._loading:
                threading.Thread(target=self._load_live, daemon=True).start()
        else:
            self._load_live()

    def _request(self, path: str, params: dict[str, Any]) -> Optional[dict]:
        if not self.enabled:
            return None
        headers = {**HEADERS_BASE, "x-apisports-key": self._api_key}
        try:
            r = self._session.get(f"{BASE_URL}/{path}", params=params, headers=headers, timeout=25)
            self._rate_remaining = r.headers.get("x-ratelimit-remaining")
            if r.status_code == 429:
                self._error = "rate limit exceeded"
                return None
            r.raise_for_status()
            with self._lock:
                self._requests_today += 1
            return r.json()
        except requests.RequestException as exc:
            with self._lock:
                self._error = str(exc)
            return None

    def _load_live(self) -> None:
        with self._lock:
            if self._loading:
                return
            self._loading = True
        try:
            data = self._request("fixtures", {"live": "all"})
            if not data:
                return
            index: dict[str, dict[str, Any]] = {}
            for fx in data.get("response", []):
                home = fx.get("teams", {}).get("home", {}).get("name", "")
                away = fx.get("teams", {}).get("away", {}).get("name", "")
                fid = fx.get("fixture", {}).get("id")
                if not home or not away or not fid:
                    continue
                index[_pair_key(home, away)] = fx
            with self._lock:
                self._live_index = index
                self._live_loaded_at = time.time()
                self._error = None
        finally:
            with self._lock:
                self._loading = False

    def _fixture_by_id(self, fixture_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            for fx in self._live_index.values():
                if fx.get("fixture", {}).get("id") == fixture_id:
                    return fx
        return None

    def _resolve_fixture(self, home: str, away: str) -> Optional[dict[str, Any]]:
        key = _pair_key(home, away)
        with self._lock:
            if key in self._live_index:
                return self._live_index[key]
            candidates = list(self._live_index.items())
        best = None
        best_score = 0.0
        hn, an = _normalize_team(home), _normalize_team(away)
        for cand_key, fx in candidates:
            if "|" not in cand_key:
                continue
            ch, ca = cand_key.split("|", 1)
            score = (SequenceMatcher(None, hn, ch).ratio() + SequenceMatcher(None, an, ca).ratio()) / 2
            if score > best_score:
                best_score = score
                best = fx
        return best if best_score >= 0.78 else None

    def _fetch_statistics(
        self,
        fixture_id: int,
        fixture: Optional[dict[str, Any]] = None,
    ) -> Optional[APIFootballMatchStats]:
        cache_key = str(fixture_id)
        with self._lock:
            cached = self._stats_cache.get(cache_key)
            if cached and time.time() - cached[0] < STATS_TTL_SECONDS:
                return cached[1]

        data = self._request("fixtures/statistics", {"fixture": fixture_id})
        if not data:
            with self._lock:
                cached = self._stats_cache.get(cache_key)
            return cached[1] if cached else None

        response = data.get("response") or []
        if len(response) < 2:
            return None

        home_row = response[0].get("statistics") or []
        away_row = response[1].get("statistics") or []
        fx = fixture or self._fixture_by_id(fixture_id) or {}

        fixture_meta = fx.get("fixture") or {}
        goals = fx.get("goals") or {}
        league = fx.get("league") or {}

        home_shots = _stat_value(home_row, "Total Shots")
        away_shots = _stat_value(away_row, "Total Shots")
        home_sot = _stat_value(home_row, "Shots on Goal")
        away_sot = _stat_value(away_row, "Shots on Goal")
        home_corners = _stat_value(home_row, "Corner Kicks")
        away_corners = _stat_value(away_row, "Corner Kicks")
        home_poss = _stat_value(home_row, "Ball Possession")
        away_poss = _stat_value(away_row, "Ball Possession")
        home_fouls = _stat_value(home_row, "Fouls")
        away_fouls = _stat_value(away_row, "Fouls")

        if home_poss == 0 and away_poss == 0:
            home_poss, away_poss = 50, 50

        stats = APIFootballMatchStats(
            fixture_id=fixture_id,
            home_team=(response[0].get("team") or {}).get("name", ""),
            away_team=(response[1].get("team") or {}).get("name", ""),
            league=league.get("name", ""),
            status=(fixture_meta.get("status") or {}).get("short", ""),
            minute=_safe_int((fixture_meta.get("status") or {}).get("elapsed")),
            total_shots=home_shots + away_shots,
            shots_on_target=home_sot + away_sot,
            corners=home_corners + away_corners,
            home_possession=float(home_poss or 50),
            away_possession=float(away_poss or 50),
            fouls=home_fouls + away_fouls,
            home_goals=_safe_int(goals.get("home")),
            away_goals=_safe_int(goals.get("away")),
        )
        with self._lock:
            self._stats_cache[cache_key] = (time.time(), stats)
        return stats

    def lookup_match(self, home: str, away: str) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        self.ensure_loaded(background=True)
        if self._live_loaded_at == 0:
            self._load_live()

        fx = self._resolve_fixture(home, away)
        if not fx:
            return None

        fid = fx.get("fixture", {}).get("id")
        if not fid:
            return None

        stats = self._fetch_statistics(int(fid), fixture=fx)
        if not stats:
            return None
        return asdict(stats)


def apifootball_live_agreement(
    onexbet_shots: int,
    onexbet_sot: int,
    apifb: Optional[dict[str, Any]],
) -> tuple[float, list[str]]:
    if not apifb or not apifb.get("total_shots"):
        return 0.0, []

    db_shots = apifb.get("total_shots", 0)
    db_sot = apifb.get("shots_on_target", 0)
    signals: list[str] = []
    ratio = db_shots / max(onexbet_shots, 1)

    if 0.7 <= ratio <= 1.35:
        signals.append(f"API-Football confirms live tempo ({db_shots} shots)")
        boost = 5.0
        if db_sot and onexbet_sot and 0.75 <= db_sot / max(onexbet_sot, 1) <= 1.3:
            boost += 2.0
        return min(boost, 9.0), signals
    if ratio > 1.6:
        signals.append("API-Football shows higher shot volume than 1xBet")
        return -4.0, signals
    if ratio < 0.5:
        signals.append("API-Football shows lower shot volume than 1xBet")
        return -2.0, signals
    return 0.0, signals


APIFOOTBALL_PROVIDER = APIFootballStatsProvider.get()