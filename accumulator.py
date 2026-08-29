"""
Build 6–12 Over/Under accumulator slips from live FH / SH / FT picks.
Legs must be ≥80% and the under/over line must still be alive.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from acca_ou_picks import MIN_ACCA_PCT, all_ou_picks
from team_aliases import format_match_location

MIN_LEGS = 3
MAX_LEGS = 5
MIN_ACCAS = 6
MAX_ACCAS = 12
# Live soccer page still imports this for the 60% card filter.
MIN_CONFIDENCE = 60


@dataclass
class AccaLeg:
    event_id: str
    match: str
    home_team: str
    away_team: str
    league: str
    market: str
    selection: str
    fh_score: str
    minute: int
    confidence: float
    recommendation: str
    estimated_odds: float
    signals: list[str]
    half: str = "fh"
    period_minute: int = 0
    period_score: str = "0-0"
    full_score: str = "0-0"
    prophit_under_15_fh_pct: float = 0.0
    prophit_goals_form: float = 0.0
    fusion_verdict: str = ""
    fusion_agreement: str = ""
    is_half_time: bool = False
    league_id: int = 0
    onexbet_url: str = ""
    side: str = ""
    line: float = 0.0
    scope: str = ""
    tempo: str = ""
    remaining_xg: float = 0.0
    country: str = ""
    location: str = ""


@dataclass
class Accumulator:
    id: int
    name: str
    legs: list[AccaLeg]
    leg_count: int
    combined_odds: float
    combined_probability: float
    avg_confidence: float
    potential_return_10: float
    risk_level: str
    theme: str = ""


def _confidence_to_odds(confidence: float) -> float:
    return round(max(1.04, min(4.0, 100 / max(confidence, 40))), 2)


def _product(values: list[float]) -> float:
    result = 1.0
    for v in values:
        result *= v
    return result


def _unique_events(picks: list[dict], n: int) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for p in picks:
        eid = str(p.get("event_id") or "")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        out.append(p)
        if len(out) >= n:
            break
    return out


def _signature(legs: list[dict]) -> tuple[str, ...]:
    return tuple(sorted(
        f"{p.get('event_id')}|{p.get('selection')}" for p in legs
    ))


def _build_themes(picks: list[dict]) -> list[tuple[str, list[dict]]]:
    themes: list[tuple[str, callable, int]] = [
        ("Safest 3-fold", lambda p: True, 3),
        ("Safest 4-fold", lambda p: True, 4),
        ("Banker 5-fold", lambda p: True, 5),
        ("Under 3-fold", lambda p: p.get("side") == "UNDER", 3),
        ("Under 4-fold", lambda p: p.get("side") == "UNDER", 4),
        ("Over 3-fold", lambda p: p.get("side") == "OVER", 3),
        ("1H 3-fold", lambda p: p.get("scope") == "fh", 3),
        ("2H 3-fold", lambda p: p.get("scope") == "sh", 3),
        ("FT 3-fold", lambda p: p.get("scope") == "ft", 3),
        ("FT 4-fold", lambda p: p.get("scope") == "ft", 4),
        ("Slow unders", lambda p: p.get("side") == "UNDER" and p.get("tempo") == "slow", 3),
        ("Fast overs", lambda p: p.get("side") == "OVER" and p.get("tempo") == "fast", 3),
        ("U2.5+ unders", lambda p: p.get("side") == "UNDER" and float(p.get("line") or 0) >= 2.5, 3),
        ("U3.5 / U4.5", lambda p: p.get("side") == "UNDER" and float(p.get("line") or 0) >= 3.5, 3),
        ("O1.5 / O2.5", lambda p: p.get("side") == "OVER" and float(p.get("line") or 0) <= 2.5, 3),
    ]

    slips: list[tuple[str, list[dict]]] = []
    used_sigs: set[tuple[str, ...]] = set()

    for name, pred, n_legs in themes:
        pool = [p for p in picks if pred(p)]
        legs = _unique_events(pool, n_legs)
        if len(legs) < MIN_LEGS:
            continue
        sig = _signature(legs)
        if sig in used_sigs:
            continue
        used_sigs.add(sig)
        slips.append((name, legs))
        if len(slips) >= MAX_ACCAS:
            return slips

    # Extra staggered 3-folds from the ranked list so we can reach 6–12
    ranked = _unique_events(picks, 40)
    for start in range(0, max(0, len(ranked) - MIN_LEGS + 1), 2):
        if len(slips) >= MAX_ACCAS:
            break
        chunk = ranked[start:start + MIN_LEGS]
        if len(chunk) < MIN_LEGS:
            break
        sig = _signature(chunk)
        if sig in used_sigs:
            continue
        used_sigs.add(sig)
        slips.append((f"Mix {len(slips) + 1}", chunk))

    return slips[:MAX_ACCAS]


def _make_leg(entry: dict) -> AccaLeg:
    card = entry.get("card") or {}
    fusion = card.get("combined_analysis") or {}
    pb = card.get("prophit_stats") or {}
    conf = float(entry.get("confidence") or 0)
    return AccaLeg(
        event_id=str(entry.get("event_id") or ""),
        league_id=int(entry.get("league_id") or 0),
        match=entry.get("match") or "",
        home_team=entry.get("home_team") or card.get("home_team") or "",
        away_team=entry.get("away_team") or card.get("away_team") or "",
        league=entry.get("league") or card.get("league") or "",
        market=entry.get("market") or "",
        selection=entry.get("selection") or "",
        fh_score=entry.get("period_score") or card.get("fh_score") or "0-0",
        minute=int(entry.get("minute") or 0),
        period_minute=int(entry.get("period_minute") or 0),
        confidence=round(conf, 1),
        recommendation=entry.get("recommendation") or "BET",
        estimated_odds=round(float(entry.get("estimated_odds") or _confidence_to_odds(conf)), 2),
        signals=(entry.get("signals") or [])[:3],
        half=entry.get("half") or card.get("half") or "fh",
        period_score=entry.get("period_score") or "0-0",
        full_score=entry.get("full_score") or "0-0",
        prophit_under_15_fh_pct=pb.get("combined_under_15_fh_pct", 0) or 0,
        prophit_goals_form=pb.get("combined_goals_last_n", 0) or 0,
        fusion_verdict=fusion.get("verdict") or "",
        fusion_agreement=fusion.get("agreement") or "",
        is_half_time=bool(entry.get("is_half_time")),
        onexbet_url=entry.get("onexbet_url") or "",
        side=entry.get("side") or "",
        line=float(entry.get("line") or 0),
        scope=entry.get("scope") or "",
        tempo=entry.get("tempo") or "",
        remaining_xg=float(entry.get("remaining_xg") or 0),
        country=entry.get("country") or card.get("country") or "",
        location=entry.get("location")
        or card.get("location")
        or format_match_location(
            entry.get("country") or card.get("country") or "",
            entry.get("league") or card.get("league") or "",
        ),
    )


def _risk_level(avg_conf: float, legs: int) -> str:
    if avg_conf >= 86 and legs <= 3:
        return "LOW"
    if avg_conf >= 82 and legs <= 4:
        return "MEDIUM"
    return "HIGH"


def build_accumulators(matches: list[dict]) -> dict[str, Any]:
    picks = all_ou_picks(matches)
    themed = _build_themes(picks)

    accumulators: list[Accumulator] = []
    for i, (name, slip) in enumerate(themed, start=1):
        acca_legs = [_make_leg(e) for e in slip]
        odds_list = [leg.estimated_odds for leg in acca_legs]
        prob_list = [leg.confidence / 100 for leg in acca_legs]
        combined_odds = round(_product(odds_list), 2)
        combined_prob = round(_product(prob_list) * 100, 1)
        avg_conf = round(sum(leg.confidence for leg in acca_legs) / len(acca_legs), 1)
        accumulators.append(Accumulator(
            id=i,
            name=name,
            theme=name,
            legs=acca_legs,
            leg_count=len(acca_legs),
            combined_odds=combined_odds,
            combined_probability=combined_prob,
            avg_confidence=avg_conf,
            potential_return_10=round(10 * combined_odds, 2),
            risk_level=_risk_level(avg_conf, len(acca_legs)),
        ))

    return {
        "qualified_picks": len({(p["event_id"], p["scope"]) for p in picks}),
        "qualified_picks_60": picks,
        "qualified_picks_60_count": len(picks),
        "min_confidence": MIN_ACCA_PCT,
        "min_odds": 1.30,
        "max_odds": 2.50,
        "accumulator_count": len(accumulators),
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "min_accas": MIN_ACCAS,
        "max_accas": MAX_ACCAS,
        "accumulators": [asdict(a) for a in accumulators],
        "insufficient_picks": len(picks) > 0 and len(picks) < MIN_LEGS,
    }
