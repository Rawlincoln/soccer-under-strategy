"""1xBet live football data client (web-api/LiveFeed)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

BASE_URL = "https://1xbet.com/web-api/LiveFeed"
FOOTBALL_SPORT_ID = 1

STAT_MAP = {
    "attacks": 45,
    "dangerous_attacks": 58,
    "possession": 29,
    "shots_on_target": 59,
    "shots_off_target": 60,
    "corners": 70,
    "yellow_cards": 26,
    "red_cards": 71,
    "fouls": 62,
}


@dataclass
class OneXBetMatch:
    game_id: int
    home_team: str
    away_team: str
    league: str
    country: str
    period: int
    period_name: str
    minute: int
    home_score: int
    away_score: int
    fh_home: int
    fh_away: int
    fh_goals: int
    stats: dict[str, int] = field(default_factory=dict)
    home_possession: float = 50.0
    sh_home: int = 0
    sh_away: int = 0
    sh_goals: int = 0
    fh_subgame_id: Optional[int] = None
    sh_subgame_id: Optional[int] = None
    is_first_half: bool = False
    is_second_half: bool = False
    raw: dict = field(default_factory=dict)


def parse_match_stats(st: Any) -> dict[str, int]:
    """Parse 1xBet SC.ST block into home/away/total stat counters."""
    result: dict[str, int] = {}
    if not st:
        return result

    entries = st[0].get("Value", []) if isinstance(st, list) and st else []
    id_to_key = {v: k for k, v in STAT_MAP.items()}

    for item in entries:
        stat_id = item.get("ID")
        key = id_to_key.get(stat_id)
        if not key:
            continue
        s1 = int(item.get("S1") or 0)
        s2 = int(item.get("S2") or 0)
        result[f"{key}_home"] = s1
        result[f"{key}_away"] = s2
        if key == "possession":
            result["possession_home"] = s1
            result["possession_away"] = s2
        else:
            result[key] = s1 + s2

    result["total_shots"] = result.get("shots_on_target", 0) + result.get("shots_off_target", 0)
    return result


class OneXBetClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://1xbet.com/en/live/football",
        })

    def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{self.base_url}/{endpoint}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=25)
                r.raise_for_status()
                data = r.json()
                if not data.get("Success", True) and data.get("Error"):
                    raise RuntimeError(data.get("Error"))
                return data
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(1.5)
        return {}

    def fetch_live_football(self, count: int = 500) -> list[dict]:
        data = self._get("Get1x2_VZip", {
            "sports": FOOTBALL_SPORT_ID,
            "count": count,
            "lng": "en",
            "mode": 4,
            "country": 1,
            "getEmpty": "true",
        })
        return data.get("Value") or []

    def fetch_game_detail(self, game_id: int) -> dict:
        data = self._get("GetGameZip", {
            "id": game_id,
            "lng": "en",
            "cfview": 0,
            "isSubGames": "true",
            "GroupEvents": "true",
            "countevents": 500,
            "grMode": 2,
        })
        return data.get("Value") or {}

    def parse_match(self, raw: dict, detail: Optional[dict] = None) -> OneXBetMatch:
        sc = raw.get("SC") or {}
        if detail:
            sc = detail.get("SC") or sc

        fs = sc.get("FS") or {}
        home_score = int(fs.get("S1") or 0)
        away_score = int(fs.get("S2") or 0)

        fh_home, fh_away = 0, 0
        sh_home, sh_away = 0, 0
        for period in sc.get("PS") or []:
            val = period.get("Value") or {}
            nf = (val.get("NF") or "").lower()
            if period.get("Key") == 1 or "1st" in nf:
                fh_home = int(val.get("S1") or 0)
                fh_away = int(val.get("S2") or 0)
            elif period.get("Key") == 2 or "2nd" in nf:
                sh_home = int(val.get("S1") or 0)
                sh_away = int(val.get("S2") or 0)

        period = int(sc.get("CP") or 0)

        if sh_home == 0 and sh_away == 0 and period == 2:
            sh_home = max(home_score - fh_home, 0)
            sh_away = max(away_score - fh_away, 0)
        period_name = sc.get("CPS") or ""
        timer_sec = int(sc.get("TS") or 0)
        minute = timer_sec // 60 if period == 1 else 0
        if period == 2:
            minute = 45 + timer_sec // 60

        stats = self._parse_stats(sc.get("ST"))
        home_poss = float(stats.get("possession_home", 50))

        fh_subgame_id = None
        sh_subgame_id = None
        src = detail or raw
        for sg in src.get("SG") or []:
            pn = (sg.get("PN") or "").lower()
            if pn == "1st half":
                fh_subgame_id = sg.get("I")
            elif pn == "2nd half":
                sh_subgame_id = sg.get("I")

        return OneXBetMatch(
            game_id=int(raw["I"]),
            home_team=raw.get("O1", ""),
            away_team=raw.get("O2", ""),
            league=raw.get("L", ""),
            country=raw.get("CN", ""),
            period=period,
            period_name=period_name,
            minute=minute,
            home_score=home_score,
            away_score=away_score,
            fh_home=fh_home,
            fh_away=fh_away,
            fh_goals=fh_home + fh_away,
            sh_home=sh_home,
            sh_away=sh_away,
            sh_goals=sh_home + sh_away,
            stats=stats,
            home_possession=home_poss,
            fh_subgame_id=fh_subgame_id,
            sh_subgame_id=sh_subgame_id,
            is_first_half=period == 1 or "1st" in period_name.lower(),
            is_second_half=period == 2 or "2nd" in period_name.lower(),
            raw=raw,
        )

    def _parse_stats(self, st: Any) -> dict[str, int]:
        return parse_match_stats(st)

    def fetch_period_subgame_stats(self, match: OneXBetMatch, half: str) -> dict[str, int]:
        subgame_id = match.fh_subgame_id if half == "fh" else match.sh_subgame_id
        if not subgame_id:
            return match.stats
        try:
            detail = self.fetch_game_detail(subgame_id)
            sc = detail.get("SC") or {}
            parsed = self._parse_stats(sc.get("ST"))
            return parsed if parsed else match.stats
        except Exception:
            return match.stats

    def fetch_fh_subgame_stats(self, match: OneXBetMatch) -> dict[str, int]:
        return self.fetch_period_subgame_stats(match, "fh")

    def fetch_all_live_parsed(self, first_half_only: bool = False) -> list[OneXBetMatch]:
        raw_matches = self.fetch_live_football()
        parsed: list[OneXBetMatch] = []
        for raw in raw_matches:
            m = self.parse_match(raw)
            if first_half_only and not m.is_first_half:
                continue
            parsed.append(m)
        return parsed