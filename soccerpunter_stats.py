"""
SoccerPunter.com stats — live feed index + H2H / team goal-trend parsing.
Complements 1xBet live tempo and ProphitBet rolling form.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "soccerpunter"
BASE_URL = "https://www.soccerpunter.com"
FEED_URL = f"{BASE_URL}/ls_feed.php"
TODAY_URL = f"{BASE_URL}/soccer-statistics/matches_today"
FEED_TTL_SECONDS = 60
INDEX_TTL_SECONDS = 6 * 3600
H2H_CACHE_TTL_SECONDS = 12 * 3600
REQUEST_TIMEOUT = 25
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ProPunter/1.0; +https://github.com/Rawlincoln/soccer-under-strategy)",
    "Accept": "text/html,application/json",
}


def _normalize_team(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"\b(fc|cf|sc|ac|fk|cd|ud|sv|vfb|vfl|rb|tsg|1\.)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _slugify(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name.strip())
    return name or "team"


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or val == "":
            return default
        return int(float(str(val).strip()))
    except (TypeError, ValueError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(str(val).strip().replace("%", ""))
    except (TypeError, ValueError):
        return default


def _pair_key(home: str, away: str) -> str:
    return f"{_normalize_team(home)}|{_normalize_team(away)}"


@dataclass
class MatchSoccerPunterStats:
    home_team: str = ""
    away_team: str = ""
    home_id: str = ""
    away_id: str = ""
    match_id: str = ""
    league: str = ""
    h2h_home_wins: int = 0
    h2h_draws: int = 0
    h2h_away_wins: int = 0
    h2h_meetings: int = 0
    h2h_avg_total_goals: float = 0.0
    h2h_under_25_pct: float = 0.0
    home_played: int = 0
    away_played: int = 0
    home_goals_scored_avg: float = 0.0
    away_goals_scored_avg: float = 0.0
    home_goals_allowed_avg: float = 0.0
    away_goals_allowed_avg: float = 0.0
    home_under_225: int = 0
    away_under_225: int = 0
    home_over_225: int = 0
    away_over_225: int = 0
    home_fh_under_05: int = 0
    away_fh_under_05: int = 0
    home_fh_over_05: int = 0
    away_fh_over_05: int = 0
    home_clean_sheets: int = 0
    away_clean_sheets: int = 0
    combined_under_225_pct: float = 0.0
    combined_fh_under_05_pct: float = 0.0
    combined_goals_avg: float = 0.0
    recent_h2h_results: list[str] = field(default_factory=list)
    source: str = "soccerpunter.com"
    partial: bool = False


def _parse_h2h_pie(html: str) -> tuple[int, int, int]:
    m = re.search(r"data\.addRows\(\[\s*(.*?)\s*\]\)", html, re.S)
    if not m:
        return 0, 0, 0
    block = m.group(1)
    rows = re.findall(r"\['([^']+)',\s*(\d+)\]", block)
    home_wins = draws = away_wins = 0
    for label, val in rows:
        n = _safe_int(val)
        low = label.lower()
        if low == "draw":
            draws = n
        elif home_wins == 0:
            home_wins = n
        else:
            away_wins = n
    return home_wins, draws, away_wins


def _parse_h2h_sum(html: str) -> dict[str, Any]:
    m = re.search(r'<table id="h2hSum".*?</table>', html, re.S)
    if not m:
        return {}
    table = m.group(0)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)
    data: dict[str, list[str]] = {}
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(clean) >= 3:
            data[clean[0].lower()] = clean[1:]

    def _avg(row_key: str, idx: int) -> float:
        row = data.get(row_key, [])
        if len(row) <= idx:
            return 0.0
        return _safe_float(re.sub(r"<[^>]+>", "", row[idx]))

    return {
        "home_played": _safe_int((data.get("played") or ["0"])[0]),
        "away_played": _safe_int((data.get("played") or ["0", "0"])[1]),
        "home_goals_scored_avg": _avg("goals scored", 0),
        "away_goals_scored_avg": _avg("goals scored", 1),
        "home_goals_allowed_avg": _avg("goals allowed", 0),
        "away_goals_allowed_avg": _avg("goals allowed", 1),
    }


def _parse_team_comparison(html: str) -> dict[str, int | float]:
    stats: dict[str, int | float] = {}
    pattern = re.compile(
        r"<tr[^>]*>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d+)</td>",
        re.I,
    )
    label_map = {
        "matches under 2.25 goals": ("home_under_225", "away_under_225"),
        "matches over 2.25 goals": ("home_over_225", "away_over_225"),
        "matches first half under 0.5": ("home_fh_under_05", "away_fh_under_05"),
        "matches first half over 0.5": ("home_fh_over_05", "away_fh_over_05"),
        "clean sheets": ("home_clean_sheets", "away_clean_sheets"),
        "average goals scored": ("home_avg_goals_scored_raw", "away_avg_goals_scored_raw"),
    }
    for home_v, label, away_v in pattern.findall(html):
        key = label.strip().lower()
        if key not in label_map:
            continue
        hk, ak = label_map[key]
        stats[hk] = _safe_int(home_v)
        stats[ak] = _safe_int(away_v)
    return stats


def _parse_h2h_recent_scores(html: str, home: str, away: str) -> list[tuple[int, int]]:
    home_n = _normalize_team(home)
    away_n = _normalize_team(away)
    scores: list[tuple[int, int]] = []
    for title in re.findall(r'title="([^"]+)"', html):
        if not re.search(r"\d+\s*-\s*\d+", title):
            continue
        parts = re.split(r"\s*-\s*", title)
        if len(parts) < 3:
            continue
        t1, score_a, score_b = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not (score_a.isdigit() and score_b.isdigit()):
            continue
        n1 = _normalize_team(t1)
        if home_n in n1 or n1 in home_n:
            scores.append((_safe_int(score_a), _safe_int(score_b)))
        elif away_n in n1 or n1 in away_n:
            scores.append((_safe_int(score_b), _safe_int(score_a)))
    deduped: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for s in scores:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped[:12]


def _parse_h2h_page(html: str, home: str, away: str) -> dict[str, Any]:
    hw, dr, aw = _parse_h2h_pie(html)
    summary = _parse_h2h_sum(html)
    comp = _parse_team_comparison(html)
    h2h_scores = _parse_h2h_recent_scores(html, home, away)

    totals = [h + a for h, a in h2h_scores]
    under_25 = sum(1 for t in totals if t <= 2) / max(len(totals), 1) * 100 if totals else 0.0
    avg_total = sum(totals) / len(totals) if totals else 0.0

    home_played = summary.get("home_played", 0) or 1
    away_played = summary.get("away_played", 0) or 1
    hu = _safe_int(comp.get("home_under_225", 0))
    au = _safe_int(comp.get("away_under_225", 0))
    ho = _safe_int(comp.get("home_over_225", 0))
    ao = _safe_int(comp.get("away_over_225", 0))
    total_uo = hu + au + ho + ao
    under_pct = (hu + au) / max(total_uo, 1) * 100

    hfu = _safe_int(comp.get("home_fh_under_05", 0))
    afu = _safe_int(comp.get("away_fh_under_05", 0))
    hfo = _safe_int(comp.get("home_fh_over_05", 0))
    afo = _safe_int(comp.get("away_fh_over_05", 0))
    fh_total = hfu + afu + hfo + afo
    fh_under_pct = (hfu + afu) / max(fh_total, 1) * 100

    h_gs = summary.get("home_goals_scored_avg", 0.0)
    a_gs = summary.get("away_goals_scored_avg", 0.0)
    h_ga = summary.get("home_goals_allowed_avg", 0.0)
    a_ga = summary.get("away_goals_allowed_avg", 0.0)
    combined_goals = (h_gs + a_gs + h_ga + a_ga) / 2

    recent_str = [f"{home} {h}-{a} {away}" for h, a in h2h_scores[:6]]

    return {
        "h2h_home_wins": hw,
        "h2h_draws": dr,
        "h2h_away_wins": aw,
        "h2h_meetings": hw + dr + aw,
        "h2h_avg_total_goals": round(avg_total, 2),
        "h2h_under_25_pct": round(under_25, 1),
        "home_played": home_played,
        "away_played": away_played,
        "home_goals_scored_avg": h_gs,
        "away_goals_scored_avg": a_gs,
        "home_goals_allowed_avg": h_ga,
        "away_goals_allowed_avg": a_ga,
        "home_under_225": hu,
        "away_under_225": au,
        "home_over_225": ho,
        "away_over_225": ao,
        "home_fh_under_05": hfu,
        "away_fh_under_05": afu,
        "home_fh_over_05": hfo,
        "away_fh_over_05": afo,
        "home_clean_sheets": _safe_int(comp.get("home_clean_sheets", 0)),
        "away_clean_sheets": _safe_int(comp.get("away_clean_sheets", 0)),
        "combined_under_225_pct": round(under_pct, 1),
        "combined_fh_under_05_pct": round(fh_under_pct, 1),
        "combined_goals_avg": round(combined_goals, 2),
        "recent_h2h_results": recent_str,
    }


class SoccerPunterStatsProvider:
    """Live feed + H2H page stats from soccerpunter.com."""

    _instance: Optional["SoccerPunterStatsProvider"] = None

    def __init__(self):
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.headers.update(HEADERS)
        self._pair_index: dict[str, dict[str, str]] = {}
        self._feed_index: dict[str, dict[str, Any]] = {}
        self._h2h_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._index_loaded_at: float = 0.0
        self._feed_loaded_at: float = 0.0
        self._loading_index = False
        self._loading_feed = False
        self._error: Optional[str] = None
        self._feed_matches = 0
        self._index_pairs = 0
        self._h2h_fetches = 0

    @classmethod
    def get(cls) -> "SoccerPunterStatsProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        return {
            "feed_matches": self._feed_matches,
            "index_pairs": self._index_pairs,
            "h2h_cache_size": len(self._h2h_cache),
            "h2h_fetches": self._h2h_fetches,
            "feed_age_seconds": round(time.time() - self._feed_loaded_at, 1) if self._feed_loaded_at else None,
            "index_age_seconds": round(time.time() - self._index_loaded_at, 1) if self._index_loaded_at else None,
            "loading_feed": self._loading_feed,
            "loading_index": self._loading_index,
            "error": self._error,
            "source": "soccerpunter.com (ls_feed + H2H)",
        }

    def ensure_loaded(self, background: bool = True) -> None:
        if background:
            if time.time() - self._feed_loaded_at > FEED_TTL_SECONDS and not self._loading_feed:
                threading.Thread(target=self._load_feed, daemon=True).start()
            if time.time() - self._index_loaded_at > INDEX_TTL_SECONDS and not self._loading_index:
                threading.Thread(target=self._load_index, daemon=True).start()
        else:
            self._load_feed()
            self._load_index()

    def _load_feed(self) -> None:
        with self._lock:
            if self._loading_feed:
                return
            self._loading_feed = True
        try:
            r = self._session.get(FEED_URL, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            matches = payload.get("matches", {}).get("full", [])
            index: dict[str, dict[str, Any]] = {}
            for m in matches:
                home = m.get("ta_name", "")
                away = m.get("tb_name", "")
                if not home or not away:
                    continue
                entry = {
                    "home_id": str(m.get("team_A_id", "")),
                    "away_id": str(m.get("team_B_id", "")),
                    "match_id": str(m.get("match_id", m.get("id", ""))),
                    "home_team": home,
                    "away_team": away,
                    "league": m.get("leagueName", ""),
                    "slug": f"{_slugify(home)}-vs-{_slugify(away)}",
                }
                index[_pair_key(home, away)] = entry
                index[_pair_key(away, home)] = {**entry, "swapped": True}
            with self._lock:
                self._feed_index = index
                self._feed_matches = len(matches)
                self._feed_loaded_at = time.time()
                self._error = None
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._loading_feed = False

    def _load_index(self) -> None:
        with self._lock:
            if self._loading_index:
                return
            self._loading_index = True
        try:
            r = self._session.get(TODAY_URL, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            html = r.text
            pairs: dict[str, dict[str, str]] = {}
            for slug, hid, aid in re.findall(r"/h2h/([^/]+)/(\d+)/(\d+)/", html):
                parts = slug.split("-vs-")
                if len(parts) != 2:
                    continue
                home_slug, away_slug = parts
                home_guess = home_slug.replace("-", " ")
                away_guess = away_slug.replace("-", " ")
                entry = {
                    "home_id": hid,
                    "away_id": aid,
                    "slug": slug,
                    "home_team": home_guess,
                    "away_team": away_guess,
                }
                pairs[_pair_key(home_guess, away_guess)] = entry
            with self._lock:
                self._pair_index = pairs
                self._index_pairs = len(pairs)
                self._index_loaded_at = time.time()
                self._error = None
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._loading_index = False

    def _resolve_pair(self, home: str, away: str) -> Optional[dict[str, str]]:
        key = _pair_key(home, away)
        with self._lock:
            if key in self._feed_index:
                e = self._feed_index[key]
                if e.get("swapped"):
                    return {
                        "home_id": e["away_id"],
                        "away_id": e["home_id"],
                        "match_id": e.get("match_id", ""),
                        "slug": f"{_slugify(home)}-vs-{_slugify(away)}",
                        "league": e.get("league", ""),
                    }
                return {
                    "home_id": e["home_id"],
                    "away_id": e["away_id"],
                    "match_id": e.get("match_id", ""),
                    "slug": e.get("slug", f"{_slugify(home)}-vs-{_slugify(away)}"),
                    "league": e.get("league", ""),
                }
            if key in self._pair_index:
                return dict(self._pair_index[key])

        best = None
        best_score = 0.0
        with self._lock:
            candidates = list(self._pair_index.items()) + [
                (k, v) for k, v in self._feed_index.items() if not v.get("swapped")
            ]
        for cand_key, entry in candidates:
            if "|" not in cand_key:
                continue
            h_norm, a_norm = cand_key.split("|", 1)
            h_score = SequenceMatcher(None, _normalize_team(home), h_norm).ratio()
            a_score = SequenceMatcher(None, _normalize_team(away), a_norm).ratio()
            combo = (h_score + a_score) / 2
            if combo > best_score:
                best_score = combo
                best = entry
        if best and best_score >= 0.78:
            return {
                "home_id": best["home_id"],
                "away_id": best["away_id"],
                "match_id": best.get("match_id", ""),
                "slug": best.get("slug", f"{_slugify(home)}-vs-{_slugify(away)}"),
                "league": best.get("league", ""),
            }
        return None

    def _fetch_h2h_html(self, slug: str, home_id: str, away_id: str) -> Optional[str]:
        url = f"{BASE_URL}/h2h/{slug}/{home_id}/{away_id}/"
        try:
            r = self._session.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            with self._lock:
                self._h2h_fetches += 1
            return r.text
        except requests.RequestException:
            return None

    def _get_cached_h2h(self, home_id: str, away_id: str) -> Optional[dict[str, Any]]:
        cache_key = f"{home_id}:{away_id}"
        with self._lock:
            cached = self._h2h_cache.get(cache_key)
            if cached and time.time() - cached[0] < H2H_CACHE_TTL_SECONDS:
                return cached[1]
        return None

    def _store_h2h_cache(self, home_id: str, away_id: str, data: dict[str, Any]) -> None:
        cache_key = f"{home_id}:{away_id}"
        with self._lock:
            self._h2h_cache[cache_key] = (time.time(), data)
            if len(self._h2h_cache) > 400:
                oldest = sorted(self._h2h_cache.items(), key=lambda x: x[1][0])[:100]
                for k, _ in oldest:
                    self._h2h_cache.pop(k, None)

    def lookup_match(self, home: str, away: str) -> Optional[dict[str, Any]]:
        self.ensure_loaded(background=True)

        pair = self._resolve_pair(home, away)
        if not pair:
            return None

        home_id = pair["home_id"]
        away_id = pair["away_id"]
        slug = pair.get("slug") or f"{_slugify(home)}-vs-{_slugify(away)}"

        cached = self._get_cached_h2h(home_id, away_id)
        if cached:
            stats = MatchSoccerPunterStats(
                home_team=home,
                away_team=away,
                home_id=home_id,
                away_id=away_id,
                match_id=pair.get("match_id", ""),
                league=pair.get("league", cached.get("league", "")),
                **{k: v for k, v in cached.items() if k in MatchSoccerPunterStats.__dataclass_fields__},
            )
            return asdict(stats)

        html = self._fetch_h2h_html(slug, home_id, away_id)
        if not html:
            if cached:
                return asdict(MatchSoccerPunterStats(home_team=home, away_team=away, partial=True))
            return None

        parsed = _parse_h2h_page(html, home, away)
        parsed["league"] = pair.get("league", "")
        self._store_h2h_cache(home_id, away_id, parsed)

        stats = MatchSoccerPunterStats(
            home_team=home,
            away_team=away,
            home_id=home_id,
            away_id=away_id,
            match_id=pair.get("match_id", ""),
            **{k: v for k, v in parsed.items() if k in MatchSoccerPunterStats.__dataclass_fields__},
        )
        return asdict(stats)


def soccerpunter_scoring_boost(stats: Optional[dict[str, Any]], half: str = "fh") -> tuple[float, list[str]]:
    """Translate SoccerPunter H2H/form into up to 12 confidence points."""
    if not stats:
        return 0.0, []

    boost = 0.0
    signals: list[str] = []

    combined_avg = stats.get("combined_goals_avg", 0)
    if combined_avg > 0:
        if combined_avg <= 1.6:
            boost += 5
            signals.append(f"SoccerPunter: low combined goal avg ({combined_avg:.2f})")
        elif combined_avg <= 2.2:
            boost += 2
        elif combined_avg >= 3.0:
            boost -= 4
            signals.append(f"SoccerPunter: high scoring teams ({combined_avg:.2f} avg)")

    u225 = stats.get("combined_under_225_pct", 0)
    if u225 >= 65:
        boost += 4
        signals.append(f"SoccerPunter: {u225:.0f}% under 2.25 in competition form")
    elif u225 >= 50:
        boost += 2

    if half == "fh":
        fh_u = stats.get("combined_fh_under_05_pct", 0)
        if fh_u >= 55:
            boost += 4
            signals.append(f"SoccerPunter: {fh_u:.0f}% FH under 0.5 trend")
        elif fh_u >= 40:
            boost += 2

    h2h_avg = stats.get("h2h_avg_total_goals", 0)
    if h2h_avg > 0:
        if h2h_avg <= 2.0:
            boost += 3
            signals.append(f"SoccerPunter: H2H avg {h2h_avg:.1f} goals — low scoring")
        elif h2h_avg >= 3.5:
            boost -= 3

    h2h_u25 = stats.get("h2h_under_25_pct", 0)
    if h2h_u25 >= 70:
        boost += 3
        signals.append(f"SoccerPunter: {h2h_u25:.0f}% H2H under 2.5")

    meetings = stats.get("h2h_meetings", 0)
    if meetings >= 3 and stats.get("h2h_draws", 0) >= meetings * 0.4:
        boost += 2
        signals.append("SoccerPunter: high H2H draw rate — tight games")

    return min(max(boost, -6), 12.0), signals


SOCCERPUNTER_PROVIDER = SoccerPunterStatsProvider.get()