"""Fetch 1xBet Toto & jackpot pools from toto-api-v2."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from bet_assistant import effective_onexbet_site
from onexbet_client import onexbet_toto_url

ROOT = Path(__file__).parent
DATA_FILE = ROOT / "data" / "onexbet_toto.json"
DEFAULT_TYPE_ID = 1
DEFAULT_CURRENCY = "KES"
CACHE_TTL_HOURS = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}

# Active 1xBet Toto products (TotoTypeId → metadata)
PRODUCTS: dict[int, dict[str, Any]] = {
    1: {"label": "Toto 15", "slug": "fifteen", "market": "1x2", "icon": "⚽"},
    2: {"label": "Correct Score", "slug": "score", "market": "score", "icon": "🎯"},
    6: {"label": "Cyber Football", "slug": "cyber-football", "market": "1x2", "icon": "🎮"},
    7: {"label": "Toto Football", "slug": "football", "market": "1x2", "icon": "⚽"},
    9: {"label": "Cyber Sport", "slug": "cyber", "market": "1x2", "icon": "🎮"},
    11: {"label": "Cricket", "slug": "cricket", "market": "1x2", "icon": "🏏"},
    12: {"label": "Basketball", "slug": "basketball", "market": "1x2", "icon": "🏀"},
}

OUTCOME_WDL = {1: "W", 2: "D", 3: "L"}


@dataclass
class TotoMatch:
    num: int
    home_team: str
    away_team: str
    league: str = ""
    country: str = ""
    kickoff: str = ""
    status: str = "scheduled"
    game_id: int = 0
    is_cyber: bool = False
    market_wdl: dict[str, float] = field(default_factory=dict)


@dataclass
class TotoJackpot:
    source: str
    type_id: int
    product_label: str
    title: str
    draw_number: int
    prize_kes: int
    pool_kes: int
    stake_min_kes: float
    stake_max_kes: float
    match_count: int
    fetched_at: str
    matches: list[TotoMatch]
    closes_at: str = ""
    error: Optional[str] = None


def product_info(type_id: int) -> dict[str, Any]:
    info = PRODUCTS.get(int(type_id), {})
    label = info.get("label") or f"Toto {type_id}"
    return {
        "type_id": int(type_id),
        "label": label,
        "slug": info.get("slug") or "fifteen",
        "market": info.get("market") or "1x2",
        "icon": info.get("icon") or "🎰",
        "toto_url": onexbet_toto_url(effective_onexbet_site(), variant=info.get("slug") or "fifteen"),
    }


def _session(site: str) -> requests.Session:
    sess = requests.Session()
    sess.headers.update(HEADERS)
    sess.headers["Referer"] = f"{site.rstrip('/')}/en/toto/fifteen"
    return sess


def _api_base(site: str) -> str:
    return site.rstrip("/")


def _parse_market_wdl(bets_percents: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for bp in bets_percents or []:
        key = OUTCOME_WDL.get(int(bp.get("Outcome") or 0))
        if key:
            out[key] = float(bp.get("BukPercentage") or 0)
    return out


def _parse_kickoff(ts: Any) -> str:
    try:
        sec = int(ts or 0)
        if sec <= 0:
            return ""
        return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _flatten_games(draw: dict) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for champ in draw.get("ChampsWithGames") or []:
        league = str(champ.get("ChampName") or champ.get("ChampNameEng") or "").strip()
        for game in champ.get("GamesList") or []:
            rows.append((league, game))
    rows.sort(key=lambda x: int(x[1].get("GameNumber") or 0))
    return rows


def _draw_to_jackpot(
    draw: dict,
    *,
    type_id: int,
    site: str,
    fetched_at: str,
) -> TotoJackpot:
    pinfo = product_info(type_id)
    label = pinfo["label"]
    matches: list[TotoMatch] = []

    for league, g in _flatten_games(draw):
        home = str(g.get("Opponent1Name") or "").strip()
        away = str(g.get("Opponent2Name") or "").strip()
        if not home or not away:
            continue
        matches.append(
            TotoMatch(
                num=int(g.get("GameNumber") or len(matches) + 1),
                home_team=home,
                away_team=away,
                league=league,
                kickoff=_parse_kickoff(g.get("StartDate")),
                game_id=int(g.get("BukGameId") or 0),
                is_cyber=bool(g.get("IsCyber")),
                market_wdl=_parse_market_wdl(g.get("BetsPercents") or []),
            )
        )

    prize = int(draw.get("Jackpot") or 0)
    pool = int(draw.get("Pool") or 0)
    draw_no = int(draw.get("TiragNumber") or 0)

    return TotoJackpot(
        source=site,
        type_id=type_id,
        product_label=label,
        title=f"1xBet {label}",
        draw_number=draw_no,
        prize_kes=prize,
        pool_kes=pool,
        stake_min_kes=float(draw.get("MinBetSum") or 0),
        stake_max_kes=float(draw.get("MaxBetSum") or 0),
        match_count=len(matches),
        fetched_at=fetched_at,
        matches=matches,
        closes_at=_parse_kickoff(draw.get("EndReceiptDate")),
        error=None if matches else "No active games in this pool",
    )


def _load_cache() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return {"types": {}}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"types": {}}


def _save_cache(type_id: int, jackpot: TotoJackpot) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_cache()
    types = cache.setdefault("types", {})
    types[str(type_id)] = jackpot_to_dict(jackpot)
    DATA_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _load_local(type_id: int) -> Optional[TotoJackpot]:
    raw = (_load_cache().get("types") or {}).get(str(type_id))
    if not raw:
        return None
    try:
        matches = [
            TotoMatch(
                num=int(m.get("num", i + 1)),
                home_team=m.get("home_team", m.get("home", "")),
                away_team=m.get("away_team", m.get("away", "")),
                league=m.get("league", ""),
                country=m.get("country", ""),
                kickoff=m.get("kickoff", ""),
                status=m.get("status", "scheduled"),
                game_id=int(m.get("game_id") or 0),
                is_cyber=bool(m.get("is_cyber")),
                market_wdl=dict(m.get("market_wdl") or {}),
            )
            for i, m in enumerate(raw.get("matches") or [])
        ]
        return TotoJackpot(
            source=raw.get("source", "1xbet"),
            type_id=int(raw.get("type_id") or type_id),
            product_label=raw.get("product_label") or product_info(type_id)["label"],
            title=raw.get("title") or f"1xBet {product_info(type_id)['label']}",
            draw_number=int(raw.get("draw_number") or 0),
            prize_kes=int(raw.get("prize_kes") or 0),
            pool_kes=int(raw.get("pool_kes") or 0),
            stake_min_kes=float(raw.get("stake_min_kes") or 0),
            stake_max_kes=float(raw.get("stake_max_kes") or 0),
            match_count=len(matches),
            fetched_at=raw.get("fetched_at", ""),
            matches=matches,
            closes_at=raw.get("closes_at", ""),
        )
    except (TypeError, ValueError):
        return None


def fetch_jackpots_list(
    *,
    site: Optional[str] = None,
    currency: str = DEFAULT_CURRENCY,
) -> list[dict[str, Any]]:
    """Return all jackpot pools with live game counts."""
    site = effective_onexbet_site() if not site else site.rstrip("/")
    if site and not site.startswith("http"):
        site = f"https://{site}"
    base = _api_base(site)
    sess = _session(site)

    try:
        r = sess.get(
            f"{base}/toto-api-v2/web/v1/jackpots",
            params={"curISO": currency, "lng": "en"},
            timeout=25,
        )
        r.raise_for_status()
        items = r.json().get("JackpotsList") or []
    except requests.RequestException:
        return []

    products: list[dict[str, Any]] = []
    for item in items:
        tid = int(item.get("TotoTypeId") or 0)
        if tid not in PRODUCTS:
            continue
        pinfo = product_info(tid)
        entry = {
            **pinfo,
            "jackpot_kes": int(item.get("Jackpot") or 0),
            "active": False,
            "game_count": 0,
            "draw_number": 0,
        }
        try:
            dr = sess.get(
                f"{base}/toto-api-v2/web/v1/toto/{tid}/draws/active",
                params={"lng": "en", "curISO": currency},
                timeout=20,
            )
            if dr.status_code != 200:
                continue
            draw = dr.json()
            games = sum(
                len(c.get("GamesList") or [])
                for c in draw.get("ChampsWithGames") or []
            )
            if games > 0:
                entry["active"] = True
                entry["game_count"] = games
                entry["draw_number"] = int(draw.get("TiragNumber") or 0)
                entry["pool_kes"] = int(draw.get("Pool") or 0)
                entry["jackpot_kes"] = int(draw.get("Jackpot") or entry["jackpot_kes"])
        except requests.RequestException:
            pass
        products.append(entry)
    return products


def fetch_active_draw(
    type_id: int = DEFAULT_TYPE_ID,
    *,
    site: Optional[str] = None,
    currency: str = DEFAULT_CURRENCY,
) -> TotoJackpot:
    """Fetch the active draw for a 1xBet Toto product."""
    type_id = int(type_id)
    site = effective_onexbet_site() if not site else site.rstrip("/")
    if site and not site.startswith("http"):
        site = f"https://{site}"
    base = _api_base(site)
    now = datetime.now(timezone.utc).isoformat()
    sess = _session(site)

    try:
        r = sess.get(
            f"{base}/toto-api-v2/web/v1/toto/{type_id}/draws/active",
            params={"lng": "en", "curISO": currency},
            timeout=25,
        )
        if r.status_code == 400:
            return TotoJackpot(
                source=site,
                type_id=type_id,
                product_label=product_info(type_id)["label"],
                title=f"1xBet {product_info(type_id)['label']}",
                draw_number=0,
                prize_kes=0,
                pool_kes=0,
                stake_min_kes=0,
                stake_max_kes=0,
                match_count=0,
                fetched_at=now,
                matches=[],
                error="No active draw for this product",
            )
        r.raise_for_status()
        draw = r.json()
    except requests.RequestException as exc:
        local = _load_local(type_id)
        if local and local.matches:
            local.error = f"Fetch failed ({exc}); showing saved list"
            return local
        return TotoJackpot(
            source=site,
            type_id=type_id,
            product_label=product_info(type_id)["label"],
            title=f"1xBet {product_info(type_id)['label']}",
            draw_number=0,
            prize_kes=0,
            pool_kes=0,
            stake_min_kes=0,
            stake_max_kes=0,
            match_count=0,
            fetched_at=now,
            matches=[],
            error=str(exc),
        )

    jackpot = _draw_to_jackpot(draw, type_id=type_id, site=site, fetched_at=now)
    if jackpot.matches:
        _save_cache(type_id, jackpot)
    return jackpot


def get_jackpot(
    *,
    type_id: int = DEFAULT_TYPE_ID,
    force_refresh: bool = False,
    site: Optional[str] = None,
) -> TotoJackpot:
    type_id = int(type_id)
    if not force_refresh:
        local = _load_local(type_id)
        if local and local.matches:
            try:
                age_h = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(local.fetched_at.replace("Z", "+00:00"))
                ).total_seconds() / 3600
                if age_h < CACHE_TTL_HOURS:
                    return local
            except ValueError:
                return local
    return fetch_active_draw(type_id, site=site)


def jackpot_to_dict(jackpot: TotoJackpot) -> dict[str, Any]:
    return {
        "source": jackpot.source,
        "type_id": jackpot.type_id,
        "product_label": jackpot.product_label,
        "title": jackpot.title,
        "draw_number": jackpot.draw_number,
        "prize_kes": jackpot.prize_kes,
        "pool_kes": jackpot.pool_kes,
        "stake_min_kes": jackpot.stake_min_kes,
        "stake_max_kes": jackpot.stake_max_kes,
        "stake_kes": jackpot.stake_min_kes,
        "match_count": jackpot.match_count,
        "fetched_at": jackpot.fetched_at,
        "closes_at": jackpot.closes_at,
        "error": jackpot.error,
        "matches": [asdict(m) for m in jackpot.matches],
    }