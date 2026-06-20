"""
Build accumulator (parlay) slips from live FH/SH under predictions.
Rules: 3–10 legs per acca; min 60% confidence; multiple accas if >10 picks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

MIN_LEGS = 3
MAX_LEGS = 10
MIN_CONFIDENCE = 60


@dataclass
class AccaLeg:
    event_id: str
    league_id: int = 0
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


def _confidence_to_odds(confidence: float) -> float:
    return round(max(1.04, min(4.0, 100 / max(confidence, 40))), 2)


def _period_goals(card: dict) -> int:
    return card.get("period_goals", card.get("fh_goals", 0))


def _leg_score(pick: dict, card: dict) -> float:
    rec = pick.get("recommendation", "")
    conf = pick.get("confidence", 0)
    bonus = 0
    if rec == "BET":
        bonus = 25
    elif rec == "WATCH" and conf >= 65:
        bonus = 10
    elif rec == "WATCH":
        bonus = 3
    if card.get("scored_filter"):
        bonus += 5
    if card.get("in_entry_window"):
        bonus += 8
    fusion = card.get("combined_analysis") or {}
    if fusion.get("agreement") == "CONFIRMED":
        bonus += 8
    elif fusion.get("agreement") == "ALIGNED":
        bonus += 4
    elif fusion.get("agreement") == "CONFLICT":
        bonus -= 12
    if fusion.get("verdict") == "STRONG BET":
        bonus += 6
    pb = card.get("prophit_stats") or {}
    if pb.get("combined_under_15_fh_pct", 0) >= 65:
        bonus += 3
    sp = card.get("soccerpunter_stats") or {}
    if sp.get("combined_under_225_pct", 0) >= 60:
        bonus += 2
    if sp.get("h2h_under_25_pct", 0) >= 70:
        bonus += 2
    if (fusion.get("sp_profile") or "") in ("defensive", "low_scoring"):
        bonus += 2
    if (fusion.get("fotmob_profile") or "") in ("very_slow", "slow"):
        bonus += 2
    fm = card.get("fotmob_stats") or {}
    if fm.get("total_xg", 99) <= 0.5:
        bonus += 2
    bd = fusion.get("breakdown") or {}
    if (bd.get("external_verify") or 0) >= 6:
        bonus += 3
    elif (bd.get("external_verify") or 0) >= 3:
        bonus += 1
    if (bd.get("market_odds") or 0) >= 6:
        bonus += 3
    elif (bd.get("market_odds") or 0) >= 3:
        bonus += 1
    mkt = card.get("market_odds") or fusion.get("market_odds_summary") or {}
    if mkt.get("under_15_implied_pct", 0) >= 68:
        bonus += 2
    elif mkt.get("under_05_implied_pct", 0) >= 65:
        bonus += 1
    if mkt.get("market_lean") == "strong_under":
        bonus += 2
    sd = card.get("sportsdb_stats") or {}
    if sd.get("total_shots"):
        bonus += 1
    return conf + bonus


def _market_alive(market: str, period_goals: int) -> bool:
    if "Under 0.5" in market and period_goals > 0:
        return False
    if "Under 1.5" in market and period_goals > 1:
        return False
    if "Under 2.5" in market and period_goals > 2:
        return False
    return True


def _best_pick_per_match(matches: list[dict]) -> list[dict]:
    legs: list[dict] = []

    for card in matches:
        best = None
        best_score = 0
        period_goals = _period_goals(card)

        for pick in card.get("predictions") or []:
            market = pick.get("market", "")
            conf = pick.get("confidence", 0)
            rec = pick.get("recommendation", "SKIP")

            if rec == "SKIP" or conf < MIN_CONFIDENCE:
                continue
            if not _market_alive(market, period_goals):
                continue
            if rec not in ("BET", "WATCH"):
                continue

            score = _leg_score(pick, card)
            if score > best_score:
                best_score = score
                best = {"card": card, "pick": pick}

        if best:
            legs.append(best)

    legs.sort(key=lambda x: -_leg_score(x["pick"], x["card"]))
    return legs


def _all_qualified_picks(matches: list[dict]) -> list[dict]:
    """Every pick at or above MIN_CONFIDENCE, sorted by confidence."""
    picks: list[dict] = []
    for card in matches:
        period_goals = _period_goals(card)
        for pick in card.get("predictions") or []:
            conf = pick.get("confidence", 0)
            rec = pick.get("recommendation", "SKIP")
            market = pick.get("market", "")
            if conf < MIN_CONFIDENCE or rec == "SKIP":
                continue
            if not _market_alive(market, period_goals):
                continue
            if rec not in ("BET", "WATCH"):
                continue
            picks.append({
                "card": card,
                "pick": pick,
                "confidence": conf,
                "recommendation": rec,
                "market": market,
                "match": f"{card['home_team']} vs {card['away_team']}",
                "half": card.get("half", "fh"),
                "minute": card.get("minute", 0),
                "period_minute": card.get("period_minute", 0),
                "period_score": card.get("period_score", card.get("fh_score", "0-0")),
                "fusion_verdict": (card.get("combined_analysis") or {}).get("verdict", ""),
                "is_half_time": card.get("is_half_time", False),
            })
    picks.sort(key=lambda x: -x["confidence"])
    return picks


def _split_into_slips(legs: list[dict]) -> list[list[dict]]:
    if not legs:
        return []

    if len(legs) <= MAX_LEGS:
        return [legs] if len(legs) >= MIN_LEGS else []

    slips: list[list[dict]] = []
    pool = list(legs)

    while pool:
        if len(pool) <= MAX_LEGS:
            if len(pool) >= MIN_LEGS:
                slips.append(pool)
            elif slips:
                need = MIN_LEGS - len(pool)
                last = slips[-1]
                if len(last) > MIN_LEGS and len(last) - need >= MIN_LEGS:
                    tail = last[-need:]
                    slips[-1] = last[:-need]
                    slips.append(tail + pool)
                elif len(last) + len(pool) <= MAX_LEGS:
                    slips[-1] = last + pool
                else:
                    slips.append(pool)
            break

        slips.append(pool[:MAX_LEGS])
        pool = pool[MAX_LEGS:]

    return slips


def _make_leg(entry: dict) -> AccaLeg:
    card = entry["card"]
    pick = entry["pick"]
    conf = pick["confidence"]
    half = card.get("half", "fh")
    market_short = pick["market"].replace("First Half Goals", "FH").replace("Second Half Goals", "SH")

    pb = card.get("prophit_stats") or {}
    fusion = card.get("combined_analysis") or {}
    return AccaLeg(
        event_id=card.get("event_id", ""),
        league_id=int(card.get("league_id") or 0),
        match=f"{card['home_team']} vs {card['away_team']}",
        home_team=card["home_team"],
        away_team=card["away_team"],
        league=card.get("league", ""),
        market=pick["market"],
        selection=market_short,
        fh_score=card.get("period_score", card.get("fh_score", "0-0")),
        minute=card.get("minute", 0),
        period_minute=card.get("period_minute", 0),
        confidence=round(conf, 1),
        recommendation=pick.get("recommendation", ""),
        estimated_odds=_confidence_to_odds(conf),
        signals=(pick.get("signals") or [])[:3],
        half=half,
        period_score=card.get("period_score", card.get("fh_score", "0-0")),
        full_score=card.get("full_score", "0-0"),
        prophit_under_15_fh_pct=pb.get("combined_under_15_fh_pct", 0),
        prophit_goals_form=pb.get("combined_goals_last_n", 0),
        fusion_verdict=fusion.get("verdict", ""),
        fusion_agreement=fusion.get("agreement", ""),
        is_half_time=card.get("is_half_time", False),
    )


def _risk_level(avg_conf: float, legs: int) -> str:
    if avg_conf >= 75 and legs <= 5:
        return "LOW"
    if avg_conf >= 65 and legs <= 7:
        return "MEDIUM"
    return "HIGH"


def build_accumulators(matches: list[dict]) -> dict[str, Any]:
    qualified = _best_pick_per_match(matches)
    all_60 = _all_qualified_picks(matches)
    slips_raw = _split_into_slips(qualified)

    accumulators: list[Accumulator] = []
    for i, slip in enumerate(slips_raw, start=1):
        acca_legs = [_make_leg(e) for e in slip]
        odds_list = [leg.estimated_odds for leg in acca_legs]
        prob_list = [leg.confidence / 100 for leg in acca_legs]

        combined_odds = round(_product(odds_list), 2)
        combined_prob = round(_product(prob_list) * 100, 1)
        avg_conf = round(sum(leg.confidence for leg in acca_legs) / len(acca_legs), 1)

        accumulators.append(Accumulator(
            id=i,
            name=f"Acca #{i}",
            legs=acca_legs,
            leg_count=len(acca_legs),
            combined_odds=combined_odds,
            combined_probability=combined_prob,
            avg_confidence=avg_conf,
            potential_return_10=round(10 * combined_odds, 2),
            risk_level=_risk_level(avg_conf, len(acca_legs)),
        ))

    return {
        "qualified_picks": len(qualified),
        "qualified_picks_60": all_60,
        "qualified_picks_60_count": len(all_60),
        "min_confidence": MIN_CONFIDENCE,
        "accumulator_count": len(accumulators),
        "min_legs": MIN_LEGS,
        "max_legs": MAX_LEGS,
        "accumulators": [asdict(a) for a in accumulators],
        "insufficient_picks": len(qualified) > 0 and len(qualified) < MIN_LEGS,
    }


def _product(values: list[float]) -> float:
    result = 1.0
    for v in values:
        result *= v
    return result