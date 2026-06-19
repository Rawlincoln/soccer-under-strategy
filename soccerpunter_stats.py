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
H2H_MIN_INTERVAL_SECONDS = 2.5
FEED_FORM_WINDOW = 8
REQUEST_TIMEOUT = 25
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
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


def _is_registration_wall(html: str) -> bool:
    if len(html) < 90000:
        return True
    if "Member Registration" in html:
        return True
    return "h2hSum" not in html and "Head to Head Summary" not in html


def _parse_h2h_pie(html: str) -> tuple[int, int, int]:
    m = re.search(r"addRows\s*\(\s*\[\s*(.*?)\s*\]\s*\)", html, re.S)
    if not m:
        return 0, 0, 0
    block = m.group(1)
    rows = re.findall(r"\[\s*'([^']+)'\s*,\s*(\d+)\s*\]", block)
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
        r"<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*([^<]+?)\s*</td>\s*<td[^>]*>\s*(\d+)\s*</td>",
        re.I | re.S,
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


def _team_form_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {}
    n = len(results)
    goals_for = sum(r["gf"] for r in results)
    goals_against = sum(r["ga"] for r in results)
    under_225 = sum(1 for r in results if r["gf"] + r["ga"] <= 2)
    fh_under_05 = sum(1 for r in results if r.get("ht_total", 0) <= 0)
    fh_over_05 = sum(1 for r in results if r.get("ht_total", 0) >= 1)
    return {
        "played": n,
        "goals_scored_avg": round(goals_for / n, 2),
        "goals_allowed_avg": round(goals_against / n, 2),
        "under_225": under_225,
        "over_225": n - under_225,
        "fh_under_05": fh_under_05,
        "fh_over_05": fh_over_05,
        "under_225_pct": round(under_225 / n * 100, 1),
        "fh_under_05_pct": round(fh_under_05 / n * 100, 1),
    }


def _build_feed_aggregates(matches: list[dict[str, Any]]) -> tuple[dict[str, list], dict[str, list]]:
    """Rolling finished-match form keyed by team id and normalized name."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    finished = [m for m in matches if m.get("status") in ("FT", "AET", "PEN")]

    for m in finished:
        ht_a = m.get("hts_A")
        ht_b = m.get("hts_B")
        ht_a_i = _safe_int(ht_a, -1) if ht_a is not None else -1
        ht_b_i = _safe_int(ht_b, -1) if ht_b is not None else -1

        for team_id, team_name, gf, ga, ht_gf, ht_ga in (
            (str(m.get("team_A_id", "")), m.get("ta_name", ""), _safe_int(m.get("score_A")), _safe_int(m.get("score_B")), ht_a_i, ht_b_i),
            (str(m.get("team_B_id", "")), m.get("tb_name", ""), _safe_int(m.get("score_B")), _safe_int(m.get("score_A")), ht_b_i, ht_a_i),
        ):
            if not team_id or not team_name:
                continue
            row = {
                "gf": gf,
                "ga": ga,
                "ht_total": ht_gf + ht_ga if ht_gf >= 0 and ht_ga >= 0 else -1,
                "opponent_id": str(m.get("team_B_id" if team_id == str(m.get("team_A_id")) else "team_A_id", "")),
            }
            by_id.setdefault(team_id, []).append(row)
            by_name.setdefault(_normalize_team(team_name), []).append(row)

    for bucket in (by_id, by_name):
        for key in bucket:
            bucket[key] = bucket[key][-FEED_FORM_WINDOW:]

    return by_id, by_name


def _pair_h2h_from_feed(matches: list[dict[str, Any]], home_id: str, away_id: str) -> list[tuple[int, int]]:
    scores: list[tuple[int, int]] = []
    for m in matches:
        if m.get("status") not in ("FT", "AET", "PEN"):
            continue
        a_id = str(m.get("team_A_id", ""))
        b_id = str(m.get("team_B_id", ""))
        if {a_id, b_id} != {home_id, away_id}:
            continue
        sa = _safe_int(m.get("score_A"))
        sb = _safe_int(m.get("score_B"))
        if a_id == home_id:
            scores.append((sa, sb))
        else:
            scores.append((sb, sa))
    return scores[-8:]


def _compose_feed_fallback(
    home: str,
    away: str,
    home_id: str,
    away_id: str,
    league: str,
    by_id: dict[str, list],
    by_name: dict[str, list],
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    home_rows = by_id.get(home_id) or by_name.get(_normalize_team(home), [])
    away_rows = by_id.get(away_id) or by_name.get(_normalize_team(away), [])
    home_form = _team_form_from_results(home_rows)
    away_form = _team_form_from_results(away_rows)
    h2h_scores = _pair_h2h_from_feed(matches, home_id, away_id)

    totals = [h + a for h, a in h2h_scores]
    h2h_avg = sum(totals) / len(totals) if totals else 0.0
    h2h_u25 = sum(1 for t in totals if t <= 2) / max(len(totals), 1) * 100 if totals else 0.0

    hu = home_form.get("under_225", 0)
    au = away_form.get("under_225", 0)
    ho = home_form.get("over_225", 0)
    ao = away_form.get("over_225", 0)
    uo_total = hu + au + ho + ao
    under_pct = (hu + au) / max(uo_total, 1) * 100

    hfu = home_form.get("fh_under_05", 0)
    afu = away_form.get("fh_under_05", 0)
    hfo = home_form.get("fh_over_05", 0)
    afo = away_form.get("fh_over_05", 0)
    fh_total = hfu + afu + hfo + afo
    fh_under_pct = (hfu + afu) / max(fh_total, 1) * 100

    h_gs = home_form.get("goals_scored_avg", 0.0)
    a_gs = away_form.get("goals_scored_avg", 0.0)
    h_ga = home_form.get("goals_allowed_avg", 0.0)
    a_ga = away_form.get("goals_allowed_avg", 0.0)
    combined_goals = (h_gs + a_gs + h_ga + a_ga) / 2 if home_form or away_form else 0.0

    return {
        "h2h_home_wins": 0,
        "h2h_draws": 0,
        "h2h_away_wins": 0,
        "h2h_meetings": len(h2h_scores),
        "h2h_avg_total_goals": round(h2h_avg, 2),
        "h2h_under_25_pct": round(h2h_u25, 1),
        "home_played": home_form.get("played", 0),
        "away_played": away_form.get("played", 0),
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
        "home_clean_sheets": sum(1 for r in home_rows if r["ga"] == 0),
        "away_clean_sheets": sum(1 for r in away_rows if r["ga"] == 0),
        "combined_under_225_pct": round(under_pct, 1),
        "combined_fh_under_05_pct": round(fh_under_pct, 1),
        "combined_goals_avg": round(combined_goals, 2),
        "recent_h2h_results": [f"{home} {h}-{a} {away}" for h, a in h2h_scores[-4:]],
        "league": league,
        "source_mode": "feed_form",
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
        self._feed_raw: list[dict[str, Any]] = []
        self._team_by_id: dict[str, list] = {}
        self._team_by_name: dict[str, list] = {}
        self._h2h_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._index_loaded_at: float = 0.0
        self._feed_loaded_at: float = 0.0
        self._last_h2h_fetch_at: float = 0.0
        self._loading_index = False
        self._loading_feed = False
        self._error: Optional[str] = None
        self._feed_matches = 0
        self._index_pairs = 0
        self._h2h_fetches = 0
        self._h2h_blocked = 0

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
            "h2h_blocked": self._h2h_blocked,
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
            by_id, by_name = _build_feed_aggregates(matches)
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
                self._feed_raw = matches
                self._team_by_id = by_id
                self._team_by_name = by_name
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
        elapsed = time.time() - self._last_h2h_fetch_at
        if elapsed < H2H_MIN_INTERVAL_SECONDS:
            time.sleep(H2H_MIN_INTERVAL_SECONDS - elapsed)

        url = f"{BASE_URL}/h2h/{slug}/{home_id}/{away_id}/"
        try:
            r = self._session.get(url, timeout=REQUEST_TIMEOUT, headers={"Referer": f"{BASE_URL}/"})
            r.raise_for_status()
            html = r.text
            with self._lock:
                self._h2h_fetches += 1
                self._last_h2h_fetch_at = time.time()
            if _is_registration_wall(html):
                with self._lock:
                    self._h2h_blocked += 1
                return None
            return html
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

    def _feed_fallback(
        self, home: str, away: str, home_id: str, away_id: str, league: str,
    ) -> dict[str, Any]:
        with self._lock:
            return _compose_feed_fallback(
                home, away, home_id, away_id, league,
                self._team_by_id, self._team_by_name, self._feed_raw,
            )

    def _build_stats_dict(
        self,
        home: str,
        away: str,
        pair: dict[str, str],
        parsed: dict[str, Any],
        partial: bool = False,
    ) -> dict[str, Any]:
        stats = MatchSoccerPunterStats(
            home_team=home,
            away_team=away,
            home_id=pair["home_id"],
            away_id=pair["away_id"],
            match_id=pair.get("match_id", ""),
            league=pair.get("league", parsed.get("league", "")),
            partial=partial,
            **{k: v for k, v in parsed.items() if k in MatchSoccerPunterStats.__dataclass_fields__},
        )
        return asdict(stats)

    def lookup_match(self, home: str, away: str) -> Optional[dict[str, Any]]:
        self.ensure_loaded(background=True)
        if self._feed_loaded_at == 0:
            self._load_feed()

        pair = self._resolve_pair(home, away)
        if not pair:
            return None

        home_id = pair["home_id"]
        away_id = pair["away_id"]
        slug = pair.get("slug") or f"{_slugify(home)}-vs-{_slugify(away)}"
        league = pair.get("league", "")

        cached = self._get_cached_h2h(home_id, away_id)
        if cached and (
            cached.get("h2h_meetings", 0) > 0 or cached.get("combined_goals_avg", 0) > 0
        ):
            return self._build_stats_dict(home, away, pair, cached)

        html = self._fetch_h2h_html(slug, home_id, away_id)
        parsed: dict[str, Any]
        partial = False

        if html:
            parsed = _parse_h2h_page(html, home, away)
            parsed["league"] = league
            parsed["source_mode"] = "h2h_page"
            if parsed.get("h2h_meetings", 0) == 0 and parsed.get("combined_goals_avg", 0) == 0:
                feed_data = self._feed_fallback(home, away, home_id, away_id, league)
                parsed = {**feed_data, **{k: v for k, v in parsed.items() if v}}
                partial = True
            self._store_h2h_cache(home_id, away_id, parsed)
            return self._build_stats_dict(home, away, pair, parsed, partial=partial)

        with self._lock:
            stale = self._h2h_cache.get(f"{home_id}:{away_id}")
        if stale:
            return self._build_stats_dict(home, away, pair, stale[1], partial=True)

        parsed = self._feed_fallback(home, away, home_id, away_id, league)
        if parsed.get("home_played", 0) == 0 and parsed.get("away_played", 0) == 0 and parsed.get("h2h_meetings", 0) == 0:
            parsed["partial"] = True
        self._store_h2h_cache(home_id, away_id, parsed)
        return self._build_stats_dict(home, away, pair, parsed, partial=True)


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