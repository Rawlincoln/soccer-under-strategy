"""Fetch SportPesa Mega Jackpot (Toto 17) match lists."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "toto_jackpot.json"
BETWINNER_URL = "https://betwinner360.com/sportpesa-mega-jackpot-predictions/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class TotoMatch:
    num: int
    home_team: str
    away_team: str
    league: str = ""
    country: str = ""
    kickoff: str = ""
    status: str = "scheduled"


@dataclass
class TotoJackpot:
    source: str
    title: str
    prize_kes: int
    stake_kes: int
    match_count: int
    fetched_at: str
    matches: list[TotoMatch]
    error: Optional[str] = None


def _load_local() -> Optional[TotoJackpot]:
    if not DATA_FILE.exists():
        return None
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        matches = [
            TotoMatch(
                num=int(m.get("num", i + 1)),
                home_team=m.get("home_team", m.get("home", "")),
                away_team=m.get("away_team", m.get("away", "")),
                league=m.get("league", ""),
                country=m.get("country", ""),
                kickoff=m.get("kickoff", ""),
                status=m.get("status", "scheduled"),
            )
            for i, m in enumerate(raw.get("matches") or [])
        ]
        return TotoJackpot(
            source=raw.get("source", "local"),
            title=raw.get("title", "SportPesa Mega Jackpot Pro 17"),
            prize_kes=int(raw.get("prize_kes") or 0),
            stake_kes=int(raw.get("stake_kes") or 99),
            match_count=len(matches),
            fetched_at=raw.get("fetched_at", ""),
            matches=matches,
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _save_local(jackpot: TotoJackpot) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": jackpot.source,
        "title": jackpot.title,
        "prize_kes": jackpot.prize_kes,
        "stake_kes": jackpot.stake_kes,
        "fetched_at": jackpot.fetched_at,
        "matches": [asdict(m) for m in jackpot.matches],
    }
    DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_prize(text: str) -> int:
    m = re.search(r"Win Amount:\s*([\d,.]+)\s*M", text, re.I)
    if m:
        return int(float(m.group(1).replace(",", "")) * 1_000_000)
    m = re.search(r"Ksh\s*([\d,.]+)\s*M", text, re.I)
    if m:
        return int(float(m.group(1).replace(",", "")) * 1_000_000)
    return 0


def fetch_from_betwinner() -> TotoJackpot:
    """Scrape current SportPesa 17-game list from Betwinner360 (public fixture table)."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        r = requests.get(BETWINNER_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        html = r.text
    except requests.RequestException as exc:
        local = _load_local()
        if local:
            local.error = f"Fetch failed ({exc}); showing saved list"
            return local
        return TotoJackpot(
            source="betwinner360",
            title="SportPesa Mega Jackpot Pro 17",
            prize_kes=0,
            stake_kes=99,
            match_count=0,
            fetched_at=now,
            matches=[],
            error=str(exc),
        )

    teams = re.findall(
        r'<div class="flex flex-1 justify-between[^"]*"><span class="(?:font-bold)?">([^<]+)</span>',
        html,
    )
    pairs: list[tuple[str, str]] = []
    for i in range(0, len(teams) - 1, 2):
        home, away = teams[i].strip(), teams[i + 1].strip()
        if home and away:
            pairs.append((home, away))

    # Dedupe while preserving order (page lists current + results tables)
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for pair in pairs:
        key = (pair[0].lower(), pair[1].lower())
        if key not in seen:
            seen.add(key)
            unique.append(pair)

    matches = [
        TotoMatch(num=i + 1, home_team=h, away_team=a)
        for i, (h, a) in enumerate(unique[:17])
    ]

    jackpot = TotoJackpot(
        source="betwinner360",
        title="SportPesa Mega Jackpot Pro 17",
        prize_kes=_parse_prize(html),
        stake_kes=99,
        match_count=len(matches),
        fetched_at=now,
        matches=matches,
        error=None if len(matches) >= 13 else "Fewer than 13 jackpot games parsed",
    )
    if matches:
        _save_local(jackpot)
    return jackpot


def get_jackpot(*, force_refresh: bool = False) -> TotoJackpot:
    if not force_refresh:
        local = _load_local()
        if local and local.matches:
            try:
                age_h = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(local.fetched_at.replace("Z", "+00:00"))
                ).total_seconds() / 3600
                if age_h < 12:
                    return local
            except ValueError:
                return local
    return fetch_from_betwinner()


def jackpot_to_dict(jackpot: TotoJackpot) -> dict[str, Any]:
    return {
        "source": jackpot.source,
        "title": jackpot.title,
        "prize_kes": jackpot.prize_kes,
        "stake_kes": jackpot.stake_kes,
        "match_count": jackpot.match_count,
        "fetched_at": jackpot.fetched_at,
        "error": jackpot.error,
        "matches": [asdict(m) for m in jackpot.matches],
    }