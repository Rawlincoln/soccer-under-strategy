"""
TheSportsDB live event statistics — free cross-check for 1xBet tempo.
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

BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"
INDEX_TTL_SECONDS = 300
STATS_TTL_SECONDS = 120
HEADERS = {"User-Agent": "ProPunter/1.0"}


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
class SportsDBMatchStats:
    event_id: str = ""
    home_team: str = ""
    away_team: str = ""
    league: str = ""
    status: str = ""
    total_shots: int = 0
    shots_on_target: int = 0
    corners: int = 0
    home_possession: float = 50.0
    away_possession: float = 50.0
    fouls: int = 0
    api_football_id: str = ""
    source: str = "thesportsdb.com"


def _parse_event_stats(rows: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    parsed: dict[str, tuple[int, int]] = {}
    for row in rows:
        key = (row.get("strStat") or "").lower()
        parsed[key] = (_safe_int(row.get("intHome")), _safe_int(row.get("intAway")))
    return parsed


def _stats_from_rows(rows: list[dict[str, Any]], home: str, away: str, event: dict) -> SportsDBMatchStats:
    p = _parse_event_stats(rows)
    home_shots, away_shots = p.get("total shots", (0, 0))
    home_sot, away_sot = p.get("shots on goal", p.get("shots on target", (0, 0)))
    home_corners, away_corners = p.get("corner kicks", p.get("corners", (0, 0)))
    home_poss, away_poss = p.get("ball possession", (0, 0))
    home_fouls, away_fouls = p.get("fouls", (0, 0))
    if home_poss == 0 and away_poss == 0:
        home_poss, away_poss = 50, 50
    elif away_poss == 0 and home_poss > 0:
        away_poss = 100 - home_poss

    return SportsDBMatchStats(
        event_id=str(event.get("idEvent", "")),
        home_team=home,
        away_team=away,
        league=event.get("strLeague", ""),
        status=event.get("strStatus", ""),
        total_shots=home_shots + away_shots,
        shots_on_target=home_sot + away_sot,
        corners=home_corners + away_corners,
        home_possession=float(home_poss),
        away_possession=float(away_poss),
        fouls=home_fouls + away_fouls,
        api_football_id=str(event.get("idAPIfootball") or ""),
    )


class TheSportsDBStatsProvider:
    _instance: Optional["TheSportsDBStatsProvider"] = None

    def __init__(self):
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._event_index: dict[str, dict[str, Any]] = {}
        self._stats_cache: dict[str, tuple[float, SportsDBMatchStats]] = {}
        self._index_loaded_at: float = 0.0
        self._loading = False
        self._error: Optional[str] = None
        self._index_count = 0

    @classmethod
    def get(cls) -> "TheSportsDBStatsProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        return {
            "index_events": self._index_count,
            "stats_cache": len(self._stats_cache),
            "index_age_seconds": round(time.time() - self._index_loaded_at, 1) if self._index_loaded_at else None,
            "loading": self._loading,
            "error": self._error,
            "source": "thesportsdb.com",
        }

    def ensure_loaded(self, background: bool = True) -> None:
        if time.time() - self._index_loaded_at < INDEX_TTL_SECONDS:
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
                d = (today + timedelta(days=offset)).isoformat()
                r = self._session.get(f"{BASE_URL}/eventsday.php", params={"d": d, "s": "Soccer"}, timeout=25)
                r.raise_for_status()
                for event in r.json().get("events") or []:
                    home = event.get("strHomeTeam", "")
                    away = event.get("strAwayTeam", "")
                    if not home or not away:
                        continue
                    index[_pair_key(home, away)] = event
            with self._lock:
                self._event_index = index
                self._index_count = len(index)
                self._index_loaded_at = time.time()
                self._error = None
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._loading = False

    def _resolve_event(self, home: str, away: str) -> Optional[dict[str, Any]]:
        key = _pair_key(home, away)
        with self._lock:
            if key in self._event_index:
                return self._event_index[key]
            candidates = list(self._event_index.items())
        best = None
        best_score = 0.0
        hn, an = _normalize_team(home), _normalize_team(away)
        for cand_key, event in candidates:
            if "|" not in cand_key:
                continue
            ch, ca = cand_key.split("|", 1)
            score = (SequenceMatcher(None, hn, ch).ratio() + SequenceMatcher(None, an, ca).ratio()) / 2
            if score > best_score:
                best_score = score
                best = event
        return best if best_score >= 0.78 else None

    def lookup_match(self, home: str, away: str) -> Optional[dict[str, Any]]:
        self.ensure_loaded(background=True)
        if self._index_loaded_at == 0:
            self._load_index()

        event = self._resolve_event(home, away)
        if not event:
            return None

        eid = str(event.get("idEvent", ""))
        with self._lock:
            cached = self._stats_cache.get(eid)
            if cached and time.time() - cached[0] < STATS_TTL_SECONDS:
                return asdict(cached[1])

        try:
            r = self._session.get(f"{BASE_URL}/lookupeventstats.php", params={"id": eid}, timeout=20)
            r.raise_for_status()
            rows = r.json().get("eventstats") or []
        except requests.RequestException:
            return None

        if not rows:
            return None

        stats = _stats_from_rows(rows, home, away, event)
        with self._lock:
            self._stats_cache[eid] = (time.time(), stats)
        return asdict(stats)


def sportsdb_live_agreement(
    onexbet_shots: int,
    onexbet_sot: int,
    sportsdb: Optional[dict[str, Any]],
) -> tuple[float, list[str]]:
    if not sportsdb or not sportsdb.get("total_shots"):
        return 0.0, []

    db_shots = sportsdb.get("total_shots", 0)
    db_sot = sportsdb.get("shots_on_target", 0)
    signals: list[str] = []

    if onexbet_shots == 0:
        return 0.0, signals

    ratio = db_shots / max(onexbet_shots, 1)
    if 0.65 <= ratio <= 1.5:
        signals.append(f"TheSportsDB confirms tempo ({db_shots} shots vs 1xBet {onexbet_shots})")
        boost = 4.0
        if 0.8 <= ratio <= 1.25:
            boost = 6.0
        if db_sot and onexbet_sot:
            sot_ratio = db_sot / max(onexbet_sot, 1)
            if 0.7 <= sot_ratio <= 1.4:
                boost += 2.0
        return min(boost, 8.0), signals

    if ratio > 1.8:
        signals.append(f"TheSportsDB busier than 1xBet ({db_shots} vs {onexbet_shots} shots) — caution")
        return -3.0, signals
    if ratio < 0.45:
        signals.append(f"TheSportsDB quieter than 1xBet ({db_shots} vs {onexbet_shots} shots) — verify")
        return -2.0, signals
    return 1.0, signals


SPORTSDB_PROVIDER = TheSportsDBStatsProvider.get()