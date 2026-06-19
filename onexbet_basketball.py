"""1xBet live basketball feed parser (quarters, totals odds)."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import requests

from onexbet_client import OneXBetClient

BASKETBALL_SPORT_ID = 3
BASE_URL = "https://1xbet.com/web-api/LiveFeed"


@dataclass
class QuarterScore:
    home: int = 0
    away: int = 0

    @property
    def total(self) -> int:
        return self.home + self.away


@dataclass
class OneXBetBasketballMatch:
    game_id: int
    home_team: str
    away_team: str
    league: str
    country: str
    period: int
    period_name: str
    timer_sec: int
    home_score: int
    away_score: int
    quarters: dict[int, QuarterScore] = field(default_factory=dict)
    quarter_minutes: int = 10
    q3_elapsed_min: float = 0.0
    game_elapsed_min: float = 0.0
    is_third_quarter: bool = False
    is_q3_break: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def total_points(self) -> int:
        return self.home_score + self.away_score

    @property
    def q1_total(self) -> int:
        return self.quarters.get(1, QuarterScore()).total

    @property
    def q2_total(self) -> int:
        return self.quarters.get(2, QuarterScore()).total

    @property
    def q3_total(self) -> int:
        return self.quarters.get(3, QuarterScore()).total

    @property
    def h1_total(self) -> int:
        return self.q1_total + self.q2_total


def parse_quarter_scores(ps: list[dict]) -> dict[int, QuarterScore]:
    quarters: dict[int, QuarterScore] = {}
    for item in ps or []:
        key = int(item.get("Key") or 0)
        val = item.get("Value") or {}
        nf = (val.get("NF") or "").lower()
        if "quarter" not in nf and "period" not in nf:
            continue
        quarters[key] = QuarterScore(
            home=int(val.get("S1") or 0),
            away=int(val.get("S2") or 0),
        )
    return quarters


def infer_quarter_minutes(league: str) -> int:
    ll = league.lower()
    if "nba" in ll and "cyber" not in ll and "2k" not in ll:
        return 12
    if "ncaa" in ll or "college" in ll:
        return 20
    if "wnba" in ll:
        return 10
    return 10


def is_active_third_quarter(period: int, period_name: str, quarters: dict[int, QuarterScore]) -> bool:
    pn = (period_name or "").lower().strip()
    if period != 3:
        return False
    if "break" in pn:
        return False
    if "3rd" in pn:
        return True
    return 3 in quarters and quarters[3].total > 0


def parse_basketball_clock(
    period: int,
    period_name: str,
    timer_sec: int,
    quarter_minutes: int,
    quarters: dict[int, QuarterScore],
) -> tuple[float, float]:
    """Return (game_elapsed_min, q3_elapsed_min)."""
    elapsed = max(int(timer_sec or 0), 0) / 60.0
    pn = (period_name or "").lower()

    if period < 3:
        return elapsed, 0.0

    if period == 3:
        if "break" in pn:
            return elapsed, 0.0
        q3_elapsed = max(elapsed - 2 * quarter_minutes, 0.0)
        if 3 in quarters and quarters[3].total > 0 and q3_elapsed < 0.5:
            q3_elapsed = max(quarters[3].total / 4.0, 0.5)
        return elapsed, q3_elapsed

    return elapsed, float(quarter_minutes)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def extract_totals_lines(ge: list[dict], group_id: int = 4) -> dict[float, dict[int, float]]:
    lines: dict[float, dict[int, float]] = {}
    for group in ge or []:
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


def pick_main_line(lines: dict[float, dict[int, float]]) -> Optional[float]:
    if not lines:
        return None
    best_line = None
    best_gap = 999.0
    for line, sides in lines.items():
        over = sides.get(9, 0)
        under = sides.get(10, 0)
        if over <= 1.0 or under <= 1.0:
            continue
        gap = abs(over - under)
        if gap < best_gap:
            best_gap = gap
            best_line = line
    return best_line


def snapshot_all_lines(lines: dict[float, dict[int, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in sorted(lines.keys()):
        sides = lines[line]
        over = sides.get(9, 0.0)
        under = sides.get(10, 0.0)
        over_imp = round(100 / over, 1) if over > 1 else 0.0
        under_imp = round(100 / under, 1) if under > 1 else 0.0
        total_imp = over_imp + under_imp
        rows.append({
            "line": line,
            "over_odds": round(over, 3) if over else 0.0,
            "under_odds": round(under, 3) if under else 0.0,
            "over_implied_pct": over_imp,
            "under_implied_pct": under_imp,
            "under_prob_pct": round(under_imp / total_imp * 100, 1) if total_imp > 0 else 0.0,
            "over_prob_pct": round(over_imp / total_imp * 100, 1) if total_imp > 0 else 0.0,
        })
    return rows


def snapshot_odds(lines: dict[float, dict[int, float]], main_line: Optional[float]) -> dict[str, Any]:
    if main_line is None:
        return {}
    sides = lines.get(main_line, {})
    over = sides.get(9, 0.0)
    under = sides.get(10, 0.0)
    over_imp = round(100 / over, 1) if over > 1 else 0.0
    under_imp = round(100 / under, 1) if under > 1 else 0.0
    lean = "neutral"
    if over_imp and under_imp:
        if under_imp - over_imp >= 8:
            lean = "under"
        elif over_imp - under_imp >= 8:
            lean = "over"
    return {
        "line": main_line,
        "over_odds": round(over, 3) if over else 0.0,
        "under_odds": round(under, 3) if under else 0.0,
        "over_implied_pct": over_imp,
        "under_implied_pct": under_imp,
        "market_lean": lean,
    }


class OneXBetBasketballClient:
    def __init__(self):
        self._football_client = OneXBetClient(base_url=BASE_URL)
        self.session = self._football_client.session
        self.session.headers["Referer"] = "https://1xbet.com/en/live/basketball"

    def fetch_live_basketball(self, count: int = 500) -> list[dict]:
        data = self._football_client._get("Get1x2_VZip", {
            "sports": BASKETBALL_SPORT_ID,
            "count": count,
            "lng": "en",
            "mode": 4,
            "country": 1,
            "getEmpty": "true",
        })
        return data.get("Value") or []

    def fetch_game_detail(self, game_id: int) -> dict:
        return self._football_client.fetch_game_detail(game_id)

    def parse_match(self, raw: dict, detail: Optional[dict] = None) -> OneXBetBasketballMatch:
        sc = raw.get("SC") or {}
        if detail:
            sc = detail.get("SC") or sc

        fs = sc.get("FS") or {}
        home_score = int(fs.get("S1") or 0)
        away_score = int(fs.get("S2") or 0)
        quarters = parse_quarter_scores(sc.get("PS") or [])

        league = raw.get("L", "")
        quarter_minutes = infer_quarter_minutes(league)
        period = int(sc.get("CP") or 0)
        period_name = sc.get("CPS") or ""
        timer_sec = int(sc.get("TS") or 0)
        game_elapsed, q3_elapsed = parse_basketball_clock(
            period, period_name, timer_sec, quarter_minutes, quarters,
        )

        pn_lower = period_name.lower()
        return OneXBetBasketballMatch(
            game_id=int(raw["I"]),
            home_team=raw.get("O1", ""),
            away_team=raw.get("O2", ""),
            league=league,
            country=raw.get("CN", ""),
            period=period,
            period_name=period_name,
            timer_sec=timer_sec,
            home_score=home_score,
            away_score=away_score,
            quarters=quarters,
            quarter_minutes=quarter_minutes,
            q3_elapsed_min=round(q3_elapsed, 1),
            game_elapsed_min=round(game_elapsed, 1),
            is_third_quarter=is_active_third_quarter(period, period_name, quarters),
            is_q3_break=period == 3 and "break" in pn_lower,
            raw=raw,
        )

    def fetch_match_odds(self, match: OneXBetBasketballMatch) -> dict[str, Any]:
        detail = self.fetch_game_detail(match.game_id)
        game_lines = extract_totals_lines(detail.get("GE") or [])
        game_line = pick_main_line(game_lines)

        q3_lines: dict[float, dict[int, float]] = {}
        for sg in detail.get("SG") or []:
            pn = (sg.get("PN") or "").lower()
            if pn != "3rd quarter":
                continue
            sub = self.fetch_game_detail(int(sg["I"]))
            candidate = extract_totals_lines(sub.get("GE") or [])
            if candidate and max(candidate) >= 20:
                q3_lines = candidate
                break

        return {
            "game": snapshot_odds(game_lines, game_line),
            "game_all_lines": snapshot_all_lines(game_lines),
            "q3_quarter": snapshot_odds(q3_lines, pick_main_line(q3_lines)),
            "q3_all_lines": snapshot_all_lines(q3_lines),
        }

    def match_to_dict(self, match: OneXBetBasketballMatch) -> dict[str, Any]:
        data = asdict(match)
        data["quarters"] = {str(k): asdict(v) for k, v in match.quarters.items()}
        return data