"""Shared team-name aliases and league/country context for cross-provider matching."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

# 1xBet / bookmaker label -> canonical name used by FotMob / football-data
TEAM_ALIASES: dict[str, str] = {
    "bohemian dublin": "Bohemians",
    "bohemians dublin": "Bohemians",
    "qadsia": "Al-Qadsia",
    "al qadsia": "Al-Qadsia",
    "knattspyrnufelag reykjavikur": "KR",
    "kr reykjavik": "KR",
    "ia akranes": "ÍA",
    "stjarnan women": "Stjarnan",
    "fram reykjavik women": "Fram",
    # SportPesa Toto / Nordic & China bookmaker labels
    "turku ps": "Inter Turku",
    "afc malmo": "Malmo FF",
    "jonkopings sodra": "Jonkopings",
    "dalian zhixing": "Dalian Yingbo",
    "qingdao youth island": "Qingdao West Coast",
    "fh hafnarfjordur": "FH",
    "ibv vestmannaeyjar": "IBV",

    "ff jaro": "Jaro",
    "hjk helsinki": "HJK",
    "hangzhou greentown": "Hangzhou Greentown",
    "zhejiang greentown": "Hangzhou Greentown",
}

# National sides in Toto jackpots — skip club-form providers (ProphitBet etc.)
NATIONAL_TEAMS: frozenset[str] = frozenset({
    "algeria", "austria", "england", "france", "germany", "spain", "italy",
    "portugal", "netherlands", "belgium", "brazil", "argentina", "mexico",
    "usa", "japan", "south korea", "morocco", "nigeria", "senegal", "egypt",
    "cameroon", "ghana", "kenya", "uganda", "tanzania", "south africa",
})

# 1xBet country label -> FotMob ccode
COUNTRY_TO_CCODE: dict[str, str] = {
    "kuwait": "KUW",
    "ireland": "IRL",
    "iceland": "ISL",
    "northern ireland": "NIR",
    "england": "ENG",
    "scotland": "SCO",
    "wales": "WAL",
    "spain": "ESP",
    "italy": "ITA",
    "germany": "GER",
    "france": "FRA",
    "netherlands": "NED",
    "portugal": "POR",
    "belgium": "BEL",
    "turkey": "TUR",
    "greece": "GRE",
    "usa": "USA",
    "united states": "USA",
    "brazil": "BRA",
    "argentina": "ARG",
    "mexico": "MEX",
    "japan": "JPN",
    "china": "CHN",
    "denmark": "DEN",
    "norway": "NOR",
    "sweden": "SWE",
    "finland": "FIN",
    "poland": "POL",
    "romania": "ROU",
    "russia": "RUS",
    "switzerland": "SUI",
    "austria": "AUT",
}

# League keyword hints when country alone is insufficient
LEAGUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "IRL": ("premier", "division"),
    "ISL": ("urvalsdeild", "besta", "deild"),
    "KUW": ("premier",),
    "ENG": ("premier", "championship", "league one", "league two"),
}


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalize_team_key(name: str) -> str:
    """Compact key for alias lookup."""
    name = _strip_accents(name).lower().strip()
    name = re.sub(r"\s*\(women\)\s*", " women ", name, flags=re.I)
    name = re.sub(r"\b(fc|cf|sc|ac|fk|cd|ud|sv|vfb|vfl|rb|tsg|1\.)\b", "", name)
    name = re.sub(r"[^a-z0-9 ]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def apply_team_alias(name: str) -> str:
    """Return canonical team label when a known alias exists."""
    if not name:
        return name
    key = normalize_team_key(name)
    if key in TEAM_ALIASES:
        return TEAM_ALIASES[key]
    # Strip trailing city suffixes bookmakers add (e.g. "Bohemian Dublin")
    for suffix in (" dublin", " reykjavik", " london", " city"):
        if key.endswith(suffix):
            trimmed = key[: -len(suffix)].strip()
            if trimmed in TEAM_ALIASES:
                return TEAM_ALIASES[trimmed]
    return name


def parse_onexbet_context(league: str, country: str = "") -> tuple[str, str, Optional[str]]:
    """
    Extract country hint, league hint, and FotMob ccode from 1xBet labels.
    League format is often "Country. Competition Name".
    """
    league = (league or "").strip()
    country = (country or "").strip()

    country_hint = _strip_accents(country).lower()
    league_hint = ""

    if "." in league:
        parts = [p.strip() for p in league.split(".", 1)]
        if not country_hint and parts[0]:
            country_hint = _strip_accents(parts[0]).lower()
        if len(parts) > 1:
            league_hint = _strip_accents(parts[1]).lower()
    elif league:
        league_hint = _strip_accents(league).lower()

    ccode: Optional[str] = None
    if country_hint:
        ccode = COUNTRY_TO_CCODE.get(country_hint)
        if not ccode:
            for label, code in COUNTRY_TO_CCODE.items():
                if label in country_hint or country_hint in label:
                    ccode = code
                    break

    return country_hint, league_hint, ccode


def _normalize_league_text(text: str) -> str:
    text = _strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def league_context_score(
    onexbet_league: str,
    onexbet_country: str,
    fotmob_league: str,
    fotmob_ccode: str = "",
) -> float:
    """
    Score how well a FotMob league entry matches 1xBet context (0–1).
    Used to reject cross-country false positives (e.g. Kuwait vs Scottish PL).
    """
    country_hint, league_hint, expected_ccode = parse_onexbet_context(onexbet_league, onexbet_country)
    fm_ccode = (fotmob_ccode or "").upper()
    fm_league = _normalize_league_text(fotmob_league)

    if not country_hint and not league_hint:
        return 0.5

    score = 0.0

    if expected_ccode and fm_ccode:
        if fm_ccode == expected_ccode:
            score += 0.55
        elif fm_ccode in ("INT", "WORLD"):
            score += 0.1
        else:
            return 0.0

    if league_hint and fm_league:
        ratio = SequenceMatcher(None, league_hint, fm_league).ratio()
        score += ratio * 0.35
        # Shared significant tokens (premier, division, etc.)
        hint_tokens = set(league_hint.split())
        fm_tokens = set(fm_league.split())
        overlap = hint_tokens & fm_tokens
        if overlap:
            score += min(0.2, 0.05 * len(overlap))

    if expected_ccode and expected_ccode in LEAGUE_KEYWORDS and fm_league:
        keywords = LEAGUE_KEYWORDS[expected_ccode]
        if any(kw in fm_league for kw in keywords):
            score += 0.15

    if country_hint and not expected_ccode and fm_league:
        if country_hint in fm_league:
            score += 0.25

    return min(score, 1.0)


def is_national_team(name: str) -> bool:
    """True when the label is a country/national side (not a club)."""
    if not name:
        return False
    return normalize_team_key(name) in NATIONAL_TEAMS


def team_match_quality(query: str, matched: str) -> float:
    """0–1 confidence that a provider matched the intended team name."""
    if not query or not matched:
        return 0.0
    q = normalize_team_key(query)
    m = normalize_team_key(matched)
    if q == m:
        return 1.0
    if is_national_team(query):
        return 1.0 if m == q else 0.0
    if q in m or m in q:
        return 0.92
    return SequenceMatcher(None, q, m).ratio()


def is_virtual_esoccer_team(name: str) -> bool:
    """Detect 1xBet virtual/esoccer team suffixes like 'Galaxy+' or 'Rapids +'."""
    if not name:
        return False
    stripped = name.strip()
    if stripped.endswith("+") or stripped.endswith(" +"):
        return True
    if re.search(r"\+\s*$", stripped):
        return True
    return False