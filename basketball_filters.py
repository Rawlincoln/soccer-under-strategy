"""Exclude cyber / esports basketball from live predictions."""

from __future__ import annotations

import re

EXCLUDED_KEYWORDS = (
    "cyber",
    "(cyber)",
    "nba 2k",
    "2k26",
    "2k25",
    "2k24",
    "esport",
    "e-sport",
    "e-basket",
    "ebasket",
    "virtual",
    "frostball",
    "ipbl",
    "bskt cup",
    "simulator",
    "electronic",
)

_TEAM_CYBER_RE = re.compile(r"\(cyber\)", re.IGNORECASE)


def is_excluded_basketball(
    home_team: str,
    away_team: str,
    league: str,
    country: str = "",
) -> bool:
    combined = f"{league} {country} {home_team} {away_team}".lower()
    if any(kw in combined for kw in EXCLUDED_KEYWORDS):
        return True
    for team in (home_team, away_team):
        if _TEAM_CYBER_RE.search(team):
            return True
    return False


def is_excluded_basketball_raw(raw: dict) -> bool:
    return is_excluded_basketball(
        home_team=raw.get("O1", ""),
        away_team=raw.get("O2", ""),
        league=raw.get("L", ""),
        country=raw.get("CN", ""),
    )