"""
Live basketball Q3 totals engine — arithmetic pace + historical quarter baselines.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from basketball_filters import is_excluded_basketball_raw
from onexbet_basketball import OneXBetBasketballClient, OneXBetBasketballMatch

REFRESH_SECONDS = 30
CLIENT = OneXBetBasketballClient()

# Historical quarter/game scoring profiles (pts per quarter combined)
LEAGUE_PROFILES: dict[str, dict[str, float]] = {
    "nba": {"avg_quarter": 55.0, "avg_game": 220.0, "q3_vs_h1": 0.98, "q4_vs_h1": 1.02},
    "wnba": {"avg_quarter": 42.0, "avg_game": 168.0, "q3_vs_h1": 0.97, "q4_vs_h1": 1.0},
    "nbl": {"avg_quarter": 40.0, "avg_game": 160.0, "q3_vs_h1": 0.96, "q4_vs_h1": 1.0},
    "ibl": {"avg_quarter": 38.0, "avg_game": 152.0, "q3_vs_h1": 0.95, "q4_vs_h1": 0.98},
    "euroleague": {"avg_quarter": 41.0, "avg_game": 164.0, "q3_vs_h1": 0.97, "q4_vs_h1": 1.01},
    "default": {"avg_quarter": 40.0, "avg_game": 160.0, "q3_vs_h1": 0.96, "q4_vs_h1": 0.99},
}


def _league_profile(league: str) -> dict[str, float]:
    ll = league.lower()
    for key, profile in LEAGUE_PROFILES.items():
        if key != "default" and key in ll:
            return profile
    return LEAGUE_PROFILES["default"]


@dataclass
class TotalPrediction:
    market: str
    line: float
    pick: str
    confidence: float
    projected: float
    edge: float
    recommendation: str
    signals: list[str] = field(default_factory=list)


@dataclass
class BasketballCard:
    event_id: str
    home_team: str
    away_team: str
    league: str
    score: str
    total_points: int
    period_name: str
    q3_clock: str
    quarters: dict[str, Any]
    pace: dict[str, float]
    history: dict[str, float]
    predictions: list[dict]
    game_odds: dict[str, Any]
    q3_odds: dict[str, Any]
    best_pick: str = ""
    best_confidence: float = 0.0


def _pace_pts_per_min(points: float, minutes: float) -> float:
    return points / max(minutes, 0.5)


def _project_quarter(
    current_pts: float,
    elapsed_min: float,
    quarter_len: float,
    hist_expected: float,
) -> float:
    remaining = max(quarter_len - elapsed_min, 0.0)
    live_pace = _pace_pts_per_min(current_pts, elapsed_min)
    live_proj = current_pts + live_pace * remaining
    if elapsed_min < 3.0:
        weight = elapsed_min / 3.0
        return weight * live_proj + (1.0 - weight) * hist_expected
    return live_proj


def analyze_q3_match(
    match: OneXBetBasketballMatch,
    odds: dict[str, Any],
) -> tuple[list[TotalPrediction], dict[str, float], dict[str, float]]:
    profile = _league_profile(match.league)
    q_len = match.quarter_minutes
    q1, q2, q3 = match.q1_total, match.q2_total, match.q3_total
    h1 = q1 + q2
    current = match.total_points

    h1_minutes = 2 * q_len
    h1_pace = _pace_pts_per_min(h1, h1_minutes)
    q3_elapsed = max(match.q3_elapsed_min, 0.5)
    q3_pace = _pace_pts_per_min(q3, q3_elapsed)

    hist_q_avg = (q1 + q2) / 2 if q1 and q2 else profile["avg_quarter"]
    hist_q3 = hist_q_avg * profile["q3_vs_h1"]
    hist_q4 = hist_q_avg * profile["q4_vs_h1"]

    proj_q3 = _project_quarter(q3, q3_elapsed, q_len, hist_q3)
    blended_q4_pace = 0.55 * h1_pace + 0.45 * q3_pace
    proj_q4 = blended_q4_pace * q_len
    proj_final = q1 + q2 + proj_q3 + proj_q4

    pace_delta = q3_pace - h1_pace
    pace_ratio = q3_pace / max(h1_pace, 0.1)

    pace_summary = {
        "h1_pace": round(h1_pace, 2),
        "q3_pace": round(q3_pace, 2),
        "pace_delta": round(pace_delta, 2),
        "pace_ratio": round(pace_ratio, 2),
        "proj_q3": round(proj_q3, 1),
        "proj_q4": round(proj_q4, 1),
        "proj_final": round(proj_final, 1),
    }
    history_summary = {
        "hist_q3": round(hist_q3, 1),
        "hist_q4": round(hist_q4, 1),
        "hist_game": round(profile["avg_game"], 1),
        "q1_total": float(q1),
        "q2_total": float(q2),
        "h1_total": float(h1),
    }

    predictions: list[TotalPrediction] = []
    signals_base: list[str] = [
        f"H1 pace {h1_pace:.1f} ppm · Q3 pace {q3_pace:.1f} ppm",
        f"Projected final {proj_final:.0f} (current {current})",
    ]

    if pace_ratio < 0.88:
        signals_base.append("Q3 tempo slower than H1 — historical under pattern")
    elif pace_ratio > 1.12:
        signals_base.append("Q3 tempo faster than H1 — historical over pattern")
    else:
        signals_base.append("Q3 tempo in line with H1 scoring history")

    game_odds = odds.get("game") or {}
    game_line = game_odds.get("line")
    if game_line:
        edge = proj_final - game_line
        if edge >= 4:
            pick, rec = "OVER", "BET"
            conf = min(92.0, 58 + edge * 2.5)
        elif edge <= -4:
            pick, rec = "UNDER", "BET"
            conf = min(92.0, 58 + abs(edge) * 2.5)
        elif edge >= 2:
            pick, rec = "OVER", "WATCH"
            conf = 52 + edge * 2
        elif edge <= -2:
            pick, rec = "UNDER", "WATCH"
            conf = 52 + abs(edge) * 2
        else:
            pick, rec = "NEAR LINE", "WAIT"
            conf = 45.0

        if game_odds.get("market_lean") == "under" and pick == "UNDER":
            conf += 4
        if game_odds.get("market_lean") == "over" and pick == "OVER":
            conf += 4

        predictions.append(TotalPrediction(
            market="Game Total",
            line=game_line,
            pick=pick,
            confidence=round(conf, 1),
            projected=round(proj_final, 1),
            edge=round(edge, 1),
            recommendation=rec,
            signals=signals_base + [
                f"Market line {game_line} · model edge {edge:+.1f}",
                f"Book lean: {game_odds.get('market_lean', 'neutral')}",
            ],
        ))

    q3_odds = odds.get("q3_quarter") or {}
    q3_line = q3_odds.get("line")
    if q3_line:
        q3_edge = proj_q3 - q3_line
        if q3_edge >= 3:
            pick, rec = "OVER", "BET"
            conf = min(90.0, 56 + q3_edge * 3)
        elif q3_edge <= -3:
            pick, rec = "UNDER", "BET"
            conf = min(90.0, 56 + abs(q3_edge) * 3)
        elif q3_edge >= 1.5:
            pick, rec = "OVER", "WATCH"
            conf = 50 + q3_edge * 2.5
        elif q3_edge <= -1.5:
            pick, rec = "UNDER", "WATCH"
            conf = 50 + abs(q3_edge) * 2.5
        else:
            pick, rec = "NEAR LINE", "WAIT"
            conf = 42.0

        predictions.append(TotalPrediction(
            market="Q3 Quarter Total",
            line=q3_line,
            pick=pick,
            confidence=round(conf, 1),
            projected=round(proj_q3, 1),
            edge=round(q3_edge, 1),
            recommendation=rec,
            signals=[
                f"Q3 projected {proj_q3:.0f} vs line {q3_line} ({q3_edge:+.1f})",
                f"Historical Q3 avg from H1: {hist_q3:.0f}",
                f"Q3 elapsed {q3_elapsed:.1f} min · {q3} pts so far",
            ],
        ))

    return predictions, pace_summary, history_summary


def _q3_clock_label(match: OneXBetBasketballMatch) -> str:
    if match.q3_elapsed_min <= 0:
        return "Q3 start"
    return f"Q3 {match.q3_elapsed_min:.0f}'"


def _quarters_display(match: OneXBetBasketballMatch) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, q in sorted(match.quarters.items()):
        out[f"Q{k}"] = f"{q.home}-{q.away} ({q.total})"
    return out


def build_basketball_payload() -> dict[str, Any]:
    raw_live = CLIENT.fetch_live_basketball()
    total_live = len(raw_live)
    excluded = 0
    q3_excluded_period = 0
    cards: list[BasketballCard] = []

    for raw in raw_live:
        if is_excluded_basketball_raw(raw):
            excluded += 1
            continue

        match = CLIENT.parse_match(raw)
        if not match.is_third_quarter:
            q3_excluded_period += 1
            continue

        try:
            odds = CLIENT.fetch_match_odds(match)
        except Exception:
            odds = {"game": {}, "q3_quarter": {}}

        preds, pace, history = analyze_q3_match(match, odds)
        if not preds:
            continue

        pred_dicts = [asdict(p) for p in preds]
        best = max(preds, key=lambda p: p.confidence)

        cards.append(BasketballCard(
            event_id=str(match.game_id),
            home_team=match.home_team,
            away_team=match.away_team,
            league=match.league,
            score=f"{match.home_score} - {match.away_score}",
            total_points=match.total_points,
            period_name=match.period_name,
            q3_clock=_q3_clock_label(match),
            quarters=_quarters_display(match),
            pace=pace,
            history=history,
            predictions=pred_dicts,
            game_odds=odds.get("game") or {},
            q3_odds=odds.get("q3_quarter") or {},
            best_pick=f"{best.pick} {best.line}" if best.line else best.pick,
            best_confidence=best.confidence,
        ))

    cards.sort(key=lambda c: (-c.best_confidence, -c.total_points))

    bet_signals = []
    for card in cards:
        for p in card.predictions:
            if p["recommendation"] in ("BET", "WATCH") and p["confidence"] >= 52:
                bet_signals.append({
                    "match": f"{card.home_team} vs {card.away_team}",
                    "market": p["market"],
                    "pick": p["pick"],
                    "line": p["line"],
                    "confidence": p["confidence"],
                    "recommendation": p["recommendation"],
                    "signals": p["signals"][:3],
                    "league": card.league,
                    "score": card.score,
                    "q3_clock": card.q3_clock,
                })

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_seconds": REFRESH_SECONDS,
        "source": "1xbet",
        "sport": "basketball",
        "filter": "3rd quarter live · no cyber/esports",
        "total_live": total_live,
        "excluded_count": excluded,
        "non_q3_count": q3_excluded_period,
        "match_count": len(cards),
        "bet_signal_count": len(bet_signals),
        "matches": [asdict(c) for c in cards],
        "bet_signals": bet_signals,
        "error": None,
    }


class BasketballCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"matches": [], "error": None}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self.refresh()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            time.sleep(REFRESH_SECONDS)
            self.refresh()

    def refresh(self):
        try:
            payload = build_basketball_payload()
            with self._lock:
                self._data = payload
        except Exception as exc:
            with self._lock:
                self._data["error"] = str(exc)

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)