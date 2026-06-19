"""
Live betting-market implied probabilities from 1xBet (+ API-Football odds fallback).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from api_football_stats import APIFOOTBALL_PROVIDER
from onexbet_client import OneXBetClient


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def implied_probability(odds: float) -> float:
    if odds <= 1.0:
        return 0.0
    return round(min(100.0 / odds, 98.0), 1)


@dataclass
class MarketOddsSnapshot:
    source: str = "1xbet"
    half: str = "fh"
    under_05_odds: float = 0.0
    under_15_odds: float = 0.0
    under_25_odds: float = 0.0
    over_15_odds: float = 0.0
    under_05_implied_pct: float = 0.0
    under_15_implied_pct: float = 0.0
    under_25_implied_pct: float = 0.0
    market_lean: str = "neutral"
    best_under_market: str = ""


def _extract_ge_totals(ge: list[dict], group_id: int = 4) -> dict[float, dict[int, float]]:
    """Map line (P) -> {T: odds} for totals group."""
    lines: dict[float, dict[int, float]] = {}
    for group in ge:
        if group.get("G") != group_id:
            continue
        for row in group.get("E") or []:
            for cell in row:
                line = cell.get("P")
                t = cell.get("T")
                if line is None or t is None:
                    continue
                odds = _safe_float(cell.get("CV") or cell.get("C"))
                if odds <= 1.0:
                    continue
                lines.setdefault(float(line), {})[int(t)] = odds
        break
    return lines


def extract_onexbet_period_odds(
    client: OneXBetClient,
    game_id: int,
    half: str = "fh",
    cached_detail: Optional[dict] = None,
) -> Optional[MarketOddsSnapshot]:
    detail = cached_detail or client.fetch_game_detail(game_id)
    period_label = "1st half" if half == "fh" else "2nd half"
    sub_id = None
    for sg in detail.get("SG") or []:
        if period_label in (sg.get("PN") or "").lower():
            sub_id = sg.get("I")
            break

    target = client.fetch_game_detail(int(sub_id)) if sub_id else detail
    lines = _extract_ge_totals(target.get("GE") or [])

    def _under(line: float) -> float:
        return lines.get(line, {}).get(10, 0.0)

    def _over(line: float) -> float:
        return lines.get(line, {}).get(9, 0.0)

    u05, u15, u25 = _under(0.5), _under(1.5), _under(2.5)
    o15 = _over(1.5)
    if not any((u05, u15, u25)):
        return None

    u15_imp = implied_probability(u15) if u15 else 0.0
    lean = "neutral"
    if u15_imp >= 72:
        lean = "strong_under"
    elif u15_imp >= 62:
        lean = "under"
    elif u15_imp > 0 and u15_imp < 48:
        lean = "over"

    best = ""
    if u05 and (not u15 or u05 <= u15):
        best = f"Under 0.5 {half.upper()}"
    elif u15:
        best = f"Under 1.5 {half.upper()}"
    elif u25:
        best = f"Under 2.5 {half.upper()}"

    return MarketOddsSnapshot(
        source="1xbet",
        half=half,
        under_05_odds=round(u05, 3) if u05 else 0.0,
        under_15_odds=round(u15, 3) if u15 else 0.0,
        under_25_odds=round(u25, 3) if u25 else 0.0,
        over_15_odds=round(o15, 3) if o15 else 0.0,
        under_05_implied_pct=implied_probability(u05) if u05 else 0.0,
        under_15_implied_pct=u15_imp,
        under_25_implied_pct=implied_probability(u25) if u25 else 0.0,
        market_lean=lean,
        best_under_market=best,
    )


def _apifootball_odds_fallback(fixture_id: int, half: str) -> Optional[MarketOddsSnapshot]:
    if not APIFOOTBALL_PROVIDER.enabled:
        return None
    data = APIFOOTBALL_PROVIDER._request("odds/live", {"fixture": fixture_id})  # noqa: SLF001
    if not data:
        return None
    for block in data.get("response") or []:
        for bookmaker in block.get("bookmakers") or []:
            for bet in bookmaker.get("bets") or []:
                name = (bet.get("name") or "").lower()
                if "first half" not in name and half == "fh":
                    continue
                if "second half" not in name and half == "sh":
                    continue
                if "goals" not in name:
                    continue
                u15 = 0.0
                for val in bet.get("values") or []:
                    v = (val.get("value") or "").lower()
                    if "under 1.5" in v:
                        u15 = _safe_float(val.get("odd"))
                if u15:
                    imp = implied_probability(u15)
                    return MarketOddsSnapshot(
                        source="api-football",
                        half=half,
                        under_15_odds=round(u15, 3),
                        under_15_implied_pct=imp,
                        market_lean="strong_under" if imp >= 72 else "under" if imp >= 62 else "neutral",
                        best_under_market=f"Under 1.5 {half.upper()}",
                    )
    return None


def lookup_market_odds(
    client: OneXBetClient,
    game_id: int,
    half: str = "fh",
    apifb_fixture_id: Optional[int] = None,
    cached_detail: Optional[dict] = None,
) -> Optional[dict[str, Any]]:
    snap = extract_onexbet_period_odds(client, game_id, half, cached_detail=cached_detail)
    if not snap and apifb_fixture_id:
        snap = _apifootball_odds_fallback(apifb_fixture_id, half)
    return asdict(snap) if snap else None


def market_odds_score(
    odds: Optional[dict[str, Any]],
    half: str,
    period_goals: int,
) -> tuple[float, list[str]]:
    if not odds:
        return 0.0, []

    score = 0.0
    signals: list[str] = []
    u15_imp = odds.get("under_15_implied_pct", 0) or 0
    u05_imp = odds.get("under_05_implied_pct", 0) or 0
    u25_imp = odds.get("under_25_implied_pct", 0) or 0
    lean = odds.get("market_lean", "neutral")
    src = odds.get("source", "market")

    if period_goals == 0 and u05_imp >= 65:
        score += 6
        signals.append(f"Market ({src}): {u05_imp:.0f}% implied U0.5 {half.upper()} @ {odds.get('under_05_odds')}")
    if period_goals <= 1 and u15_imp >= 68:
        score += 8
        signals.append(f"Market ({src}): {u15_imp:.0f}% implied U1.5 {half.upper()} @ {odds.get('under_15_odds')}")
    elif period_goals <= 1 and u15_imp >= 58:
        score += 4
        signals.append(f"Market ({src}): {u15_imp:.0f}% implied U1.5 {half.upper()}")
    elif u15_imp > 0 and u15_imp < 45:
        score -= 6
        signals.append(f"Market ({src}): only {u15_imp:.0f}% implied U1.5 — bookies expect goals")

    if period_goals <= 2 and u25_imp >= 70:
        score += 3

    if lean == "over" and period_goals == 0:
        score -= 4
        signals.append("Market pricing leans over despite 0 goals")

    return max(min(score, 12.0), -8.0), signals