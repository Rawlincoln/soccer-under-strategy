"""1xBet live football data client (web-api/LiveFeed)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests

BASE_URL = "https://1xbet.com/web-api/LiveFeed"
FOOTBALL_SPORT_ID = 1
DEFAULT_ONEXBET_SITE = "https://1xbet.co.ke"
DEFAULT_ANDROID_PACKAGE = "org.xbet.client.ke_ps"


def get_onexbet_site(override: Optional[str] = None) -> str:
    """User-facing 1xBet domain (regional site opens the mobile app)."""
    site = (override or os.environ.get("ONEXBET_SITE") or DEFAULT_ONEXBET_SITE).strip().rstrip("/")
    if site and not site.startswith("http"):
        site = f"https://{site}"
    return site or DEFAULT_ONEXBET_SITE


ONEXBET_SITE = get_onexbet_site()


def onexbet_live_url(site: Optional[str] = None) -> str:
    return f"{get_onexbet_site(site)}/en/live/football"


def onexbet_match_url(
    game_id: int | str,
    league_id: Optional[int] = None,
    site: Optional[str] = None,
    sport: str = "football",
) -> str:
    """Deep link to a live match on 1xBet."""
    base = get_onexbet_site(site)
    gid = int(game_id)
    if league_id:
        return f"{base}/en/live/{sport}/{int(league_id)}/{gid}"
    return f"{base}/en/live/{sport}/{gid}"


def onexbet_basketball_match_url(
    game_id: int | str,
    league_id: Optional[int] = None,
    site: Optional[str] = None,
) -> str:
    return onexbet_match_url(game_id, league_id, site=site, sport="basketball")


# Regional Android app packages (Play Store). Used for intent:// deep links.
ANDROID_PACKAGES: dict[str, str] = {
    "1xbet.co.ke": "org.xbet.client.ke_ps",
    "1xbet.ng": "org.xbet.client.ng_ps",
    "1xbet.com.zm": "org.xbet.client.zm_ps",
    "1xbet.com.gh": "com.xbet.betafrica.gh",
    "1xbet.ug": "org.xbet.client.ug_ps",
    "1xbet.co.tz": "org.xbet.client.tz_ps",
    "1xbet.co.mz": "org.xbet.client.mz_ps",
    "1xbet.com": "org.xbet.client1",
}


def site_hostname(site: Optional[str] = None) -> str:
    host = urlparse(get_onexbet_site(site)).hostname or ""
    return host.lower()


def android_package_for_site(
    site: Optional[str] = None,
    override: Optional[str] = None,
) -> str:
    """Guess Play Store package for the regional 1xBet app."""
    pkg = (override or os.environ.get("ONEXBET_ANDROID_PACKAGE") or "").strip()
    if pkg:
        return pkg
    host = site_hostname(site)
    if host in ANDROID_PACKAGES:
        return ANDROID_PACKAGES[host]
    if host.endswith(".co.ke"):
        return "org.xbet.client.ke_ps"
    if host.endswith(".co.tz"):
        return "org.xbet.client.tz_ps"
    if host.endswith(".co.mz"):
        return "org.xbet.client.mz_ps"
    if host == "1xbet.ng" or host.endswith(".ng"):
        return "org.xbet.client.ng_ps"
    if host.endswith(".com.zm"):
        return "org.xbet.client.zm_ps"
    if host.endswith(".com.gh"):
        return "com.xbet.betafrica.gh"
    if host.endswith(".ug"):
        return "org.xbet.client.ug_ps"
    return ""


def app_base_url() -> str:
    """Public URL of this Pro Punter deployment (for Telegram deep-link redirects)."""
    base = (
        os.environ.get("APP_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or "https://soccer-under-strategy.onrender.com"
    )
    return str(base).strip().rstrip("/")


def onexbet_telegram_open_url(
    game_id: int | str = "",
    league_id: Optional[int] = None,
    *,
    site: Optional[str] = None,
    sport: str = "football",
    base_url: Optional[str] = None,
) -> str:
    """Link for Telegram/messaging apps → /open/1xbet redirect → native app."""
    base = (base_url or app_base_url()).rstrip("/")
    gid = str(game_id).strip()
    if gid and gid.isdigit():
        params = f"game_id={int(gid)}"
        if league_id:
            params += f"&league_id={int(league_id)}"
        if sport and sport != "football":
            params += f"&sport={sport}"
        return f"{base}/open/1xbet?{params}"
    return f"{base}/open/1xbet"


def onexbet_android_intent_url(
    https_url: str,
    site: Optional[str] = None,
    package: Optional[str] = None,
    *,
    force_package: bool = False,
    browser_fallback: Optional[str] = None,
) -> str:
    """Chrome Android intent URL — opens the app that handles 1xbet.co.ke links.

    Do NOT set force_package=True on Kenya — Chrome sends users to Play Store when the
    package cannot handle the exact deep link, even if the app is already installed.
    """
    parsed = urlparse(https_url)
    if not parsed.scheme.startswith("http"):
        return https_url
    path = f"{parsed.netloc}{parsed.path or ''}{parsed.query and '?' + parsed.query or ''}"
    intent = f"intent://{path}#Intent;scheme=https;"
    pkg = android_package_for_site(site, package)
    if force_package and pkg:
        intent += f"package={pkg};"
    intent += "action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;"
    if browser_fallback:
        intent += f"S.browser_fallback_url={quote(browser_fallback, safe='')};"
    return f"{intent}end"


def onexbet_android_app_url(
    https_url: str,
    site: Optional[str] = None,
    package: Optional[str] = None,
) -> str:
    """android-app:// URI — alternate deep-link format for WebView taps."""
    pkg = android_package_for_site(site, package)
    if not pkg:
        return https_url
    parsed = urlparse(https_url)
    if not parsed.scheme.startswith("http"):
        return https_url
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return f"android-app://{pkg}/https/{parsed.hostname}{path}"


def onexbet_play_store_url(site: Optional[str] = None, package: Optional[str] = None) -> str:
    pkg = android_package_for_site(site, package)
    return f"market://details?id={pkg}" if pkg else ""


def onexbet_open_payload(
    https_url: str,
    site: Optional[str] = None,
    package: Optional[str] = None,
) -> dict[str, str]:
    """All URLs/strategies for opening the regional 1xBet Android app."""
    pkg = android_package_for_site(site, package)
    return {
        "https": https_url,
        "package": pkg,
    }


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
    league_id: int = 0
    home_possession: float = 50.0
    sh_home: int = 0
    sh_away: int = 0
    sh_goals: int = 0
    fh_subgame_id: Optional[int] = None
    sh_subgame_id: Optional[int] = None
    is_first_half: bool = False
    is_second_half: bool = False
    is_half_time: bool = False
    period_minute: int = 0
    raw: dict = field(default_factory=dict)


HALF_TIME_SECONDS = 45 * 60


def parse_match_clock(
    period: int,
    is_half_time: bool,
    timer_sec: int,
    period_name: str = "",
) -> tuple[int, int]:
    """
    Return (match_minute, period_minute).
    match_minute: standard match clock (0-45 HT, 46-90+ in 2H).
    period_minute: minutes elapsed in the current half.

    1xBet TS semantics:
    - 1st half (CP=1): seconds elapsed in the half.
    - 2nd half (CP=2): usually total match seconds (>= 45 min). Sometimes
      only 2nd-half elapsed (< 45 min) on short/esoccer feeds.
    """
    if is_half_time:
        return 45, 45

    elapsed_sec = max(int(timer_sec or 0), 0)

    if period == 1:
        match_min = elapsed_sec // 60
        return match_min, match_min

    if period == 2:
        pn = (period_name or "").lower()
        if elapsed_sec >= HALF_TIME_SECONDS:
            # Total match clock (e.g. TS=3396 -> 56', not 45+56=101')
            match_min = elapsed_sec // 60
        elif "2nd" in pn:
            match_min = 45 + elapsed_sec // 60
        else:
            match_min = elapsed_sec // 60
        return match_min, max(0, match_min - 45)

    return 0, 0


def detect_half_time(period: int, period_name: str) -> bool:
    """Return True when the match is at half-time (break between halves)."""
    pn = (period_name or "").lower().strip()
    if pn in ("half-time", "halftime", "ht", "half time", "break"):
        return True
    if ("half-time" in pn or "halftime" in pn) and "1st" not in pn and "2nd" not in pn:
        return True
    return False


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
        period_name = sc.get("CPS") or ""
        is_half_time = detect_half_time(period, period_name)

        if sh_home == 0 and sh_away == 0 and period == 2 and not is_half_time:
            sh_home = max(home_score - fh_home, 0)
            sh_away = max(away_score - fh_away, 0)

        timer_sec = int(sc.get("TS") or 0)
        minute, period_minute = parse_match_clock(
            period, is_half_time, timer_sec, period_name,
        )

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
            league_id=int(raw.get("LI") or (detail or {}).get("LI") or 0),
            home_team=raw.get("O1", ""),
            away_team=raw.get("O2", ""),
            league=raw.get("L", ""),
            country=raw.get("CN", ""),
            period=period,
            period_name=period_name,
            minute=minute,
            period_minute=period_minute,
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
            is_first_half=not is_half_time and (period == 1 or "1st" in period_name.lower()),
            is_second_half=not is_half_time and (period == 2 or "2nd" in period_name.lower()),
            is_half_time=is_half_time,
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