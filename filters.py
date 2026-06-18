"""Exclude virtual, esoccer, small-sided, and MLS matches from predictions."""

from __future__ import annotations

import re

# League / competition keywords (case-insensitive substring match)
EXCLUDED_LEAGUE_KEYWORDS = (
    "4x4",
    "5x5",
    "2x2",
    "3x3",
    "fifa",
    "esoccer",
    "e-soccer",
    "esports",
    "e-sports",
    "virtual",
    "mls",
    "short football",
    "volta",
    "daily league",  # FIFA amateur/volta leagues
    "lfl 5x5",
    "division 4x4",
    "budnesliga lfl",
    "student league",
    "15 min student",
    "15 minute student",
    "15 minutes student",
)

# Team-name patterns common in esoccer / small-sided
EXCLUDED_TEAM_PATTERNS = (
    r"\(2x2\)",
    r"\(3x3\)",
    r"\(4x4\)",
    r"\(5x5\)",
    r"\(amateur\)",
    r"\(quezzy\)",
    r"\(mick\)",
    r"\(gambit\)",
    r"\(raven\)",
)

_TEAM_RE = re.compile("|".join(EXCLUDED_TEAM_PATTERNS), re.IGNORECASE)


def _contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def is_excluded_match(
    home_team: str,
    away_team: str,
    league: str,
    country: str = "",
) -> bool:
    """Return True if match should be excluded from predictions."""
    combined = f"{league} {country} {home_team} {away_team}"

    if _contains_keyword(league, EXCLUDED_LEAGUE_KEYWORDS):
        return True

    if _contains_keyword(country, EXCLUDED_LEAGUE_KEYWORDS):
        return True

    # MLS variants: "MLS+", "MLS ", "Major League Soccer"
    league_lower = league.lower()
    if "mls" in league_lower or "major league soccer" in league_lower:
        return True

    if _contains_keyword(combined, ("esoccer", "e-soccer", "esports", "virtual")):
        return True

    for team in (home_team, away_team):
        if _TEAM_RE.search(team):
            return True
        if _contains_keyword(team, ("4x4", "5x5", "2x2", "3x3")):
            return True

    return False


def is_excluded_raw(raw: dict) -> bool:
    """Check exclusion on a 1xBet raw match dict."""
    return is_excluded_match(
        home_team=raw.get("O1", ""),
        away_team=raw.get("O2", ""),
        league=raw.get("L", ""),
        country=raw.get("CN", ""),
    )