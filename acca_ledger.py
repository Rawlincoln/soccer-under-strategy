"""
Persist accumulator predictions and settle them against final 1xBet scores.

A snapshot is the bet you *would* have placed at that moment: legs, odds,
combined odds, and the live score when the call was made.
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from onexbet_client import OneXBetClient, is_match_finished

ROOT = Path(__file__).parent
LEDGER_PATH = ROOT / "data" / "acca_ledger.json"
MAX_SNAPSHOTS = 250
DEDUP_SECONDS = 4 * 3600
ASSUMED_STAKE = 10.0

_lock = threading.Lock()
_client = OneXBetClient()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _load() -> dict[str, Any]:
    if not LEDGER_PATH.exists():
        return {"snapshots": [], "score_cache": {}}
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"snapshots": [], "score_cache": {}}


def _save(data: dict[str, Any]) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    snaps = data.get("snapshots") or []
    if len(snaps) > MAX_SNAPSHOTS:
        data["snapshots"] = snaps[-MAX_SNAPSHOTS:]
    LEDGER_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _signature(band: str, acca: dict[str, Any]) -> str:
    parts = [band, acca.get("name") or ""]
    for leg in acca.get("legs") or []:
        parts.append(f"{leg.get('event_id')}|{leg.get('selection')}|{leg.get('estimated_odds')}")
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _flatten_accas(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for key, band in (
        ("accumulators", "core"),
        ("short_accumulators", "short"),
        ("long_accumulators", "long"),
    ):
        for acca in payload.get(key) or []:
            if (acca.get("legs") or []) and (acca.get("combined_odds") or 0) > 1:
                out.append((band, acca))
    return out


def snapshot_accumulators(payload: dict[str, Any]) -> int:
    """Record new acca slips from a live scan. Returns how many were added."""
    items = _flatten_accas(payload)
    if not items:
        return 0
    added = 0
    now = _now()
    now_ts = datetime.now(timezone.utc).timestamp()
    with _lock:
        data = _load()
        snaps = data.setdefault("snapshots", [])
        recent = {
            s.get("signature")
            for s in snaps
            if now_ts - _parse_ts(s.get("created_at") or "") < DEDUP_SECONDS
        }
        for band, acca in items:
            sig = _signature(band, acca)
            if sig in recent:
                continue
            legs = []
            for leg in acca.get("legs") or []:
                legs.append({
                    "event_id": str(leg.get("event_id") or ""),
                    "match": leg.get("match") or f"{leg.get('home_team')} vs {leg.get('away_team')}",
                    "home_team": leg.get("home_team") or "",
                    "away_team": leg.get("away_team") or "",
                    "location": leg.get("location") or leg.get("league") or "",
                    "league": leg.get("league") or "",
                    "country": leg.get("country") or "",
                    "selection": leg.get("selection") or "",
                    "market": leg.get("market") or "",
                    "side": (leg.get("side") or "").upper(),
                    "line": float(leg.get("line") or 0),
                    "scope": leg.get("scope") or "ft",
                    "odds": float(leg.get("estimated_odds") or 0),
                    "confidence": float(leg.get("confidence") or 0),
                    "score_at_call": leg.get("period_score") or "",
                    "full_score_at_call": leg.get("full_score") or "",
                    "minute": int(leg.get("minute") or 0),
                    "half": leg.get("half") or "fh",
                    "result": None,
                    "final_fh": "",
                    "final_ft": "",
                    "goals_used": None,
                })
            if len(legs) < 2:
                continue
            snaps.append({
                "id": f"acca-{sig}-{int(now_ts)}",
                "signature": sig,
                "created_at": now,
                "band": band,
                "name": acca.get("name") or "Acca",
                "combined_odds": float(acca.get("combined_odds") or 0),
                "combined_probability": float(acca.get("combined_probability") or 0),
                "avg_confidence": float(acca.get("avg_confidence") or 0),
                "leg_count": len(legs),
                "stake": ASSUMED_STAKE,
                "legs": legs,
                "status": "pending",
                "settled_at": None,
                "payout": 0.0,
                "profit": 0.0,
            })
            recent.add(sig)
            added += 1
        if added:
            _save(data)
    return added


def _grade_leg(leg: dict[str, Any], score: dict[str, Any]) -> Optional[bool]:
    side = (leg.get("side") or "").upper()
    line = float(leg.get("line") or 0)
    scope = (leg.get("scope") or "ft").lower()
    if line <= 0 or side not in ("UNDER", "OVER"):
        return None

    finished = bool(score.get("finished"))
    ht_or_later = bool(score.get("ht_or_later"))
    if scope == "fh":
        if not ht_or_later:
            return None
        goals = int(score.get("fh_goals") or 0)
    elif scope == "sh":
        if not finished:
            return None
        goals = int(score.get("sh_goals") or 0)
    else:
        if not finished:
            return None
        goals = int(score.get("ft_goals") or 0)

    leg["goals_used"] = goals
    leg["final_fh"] = score.get("fh_score") or ""
    leg["final_ft"] = score.get("ft_score") or ""
    if side == "UNDER":
        return goals < line
    return goals > line


def fetch_score(game_id: str) -> dict[str, Any]:
    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return {}
    try:
        detail = _client.fetch_game_detail(gid, timeout=8, retries=1)
    except Exception:
        return {}
    if not detail:
        return {}
    raw = dict(detail)
    raw.setdefault("I", gid)
    raw.setdefault("O1", detail.get("O1") or "")
    raw.setdefault("O2", detail.get("O2") or "")
    try:
        m = _client.parse_match(raw, detail)
    except Exception:
        return {}
    finished = is_match_finished(m.period, m.period_name, m.minute)
    ht_or_later = finished or m.is_half_time or m.is_second_half or m.period >= 2
    return {
        "fh_goals": m.fh_goals,
        "sh_goals": m.sh_goals,
        "ft_goals": m.home_score + m.away_score,
        "fh_score": f"{m.fh_home}-{m.fh_away}",
        "ft_score": f"{m.home_score}-{m.away_score}",
        "finished": finished,
        "ht_or_later": ht_or_later,
        "period_name": m.period_name,
        "fetched_at": _now(),
    }


def settle_pending(limit: int = 20) -> int:
    """Settle pending snapshots that have finished (or FH-complete) scores."""
    with _lock:
        data = _load()
        snaps = data.get("snapshots") or []
        cache = data.setdefault("score_cache", {})
        pending = [s for s in snaps if s.get("status") == "pending"][-limit:]
        event_ids = []
        for s in pending:
            for leg in s.get("legs") or []:
                eid = str(leg.get("event_id") or "")
                if eid and eid not in cache:
                    event_ids.append(eid)
        unique = list(dict.fromkeys(event_ids))

    scores: dict[str, dict] = {}
    if unique:
        workers = min(8, max(1, len(unique)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for eid, score in zip(unique, pool.map(fetch_score, unique)):
                if score:
                    scores[eid] = score

    settled = 0
    with _lock:
        data = _load()
        cache = data.setdefault("score_cache", {})
        cache.update(scores)
        for snap in data.get("snapshots") or []:
            if snap.get("status") != "pending":
                continue
            legs = snap.get("legs") or []
            if not legs:
                continue
            results: list[Optional[bool]] = []
            for leg in legs:
                eid = str(leg.get("event_id") or "")
                score = cache.get(eid) or {}
                if not score:
                    results.append(None)
                    continue
                won = _grade_leg(leg, score)
                if won is None:
                    results.append(None)
                    continue
                leg["result"] = "won" if won else "lost"
                results.append(won)
            if any(r is None for r in results):
                continue
            won_slip = all(results)
            snap["status"] = "won" if won_slip else "lost"
            snap["settled_at"] = _now()
            stake = float(snap.get("stake") or ASSUMED_STAKE)
            odds = float(snap.get("combined_odds") or 0)
            snap["payout"] = round(stake * odds, 2) if won_slip else 0.0
            snap["profit"] = round(snap["payout"] - stake, 2)
            settled += 1
        if settled or scores:
            _save(data)
    return settled


def ledger_payload() -> dict[str, Any]:
    try:
        settle_pending()
    except Exception:
        pass
    with _lock:
        data = _load()
    snaps = list(reversed(data.get("snapshots") or []))
    won = [s for s in snaps if s.get("status") == "won"]
    lost = [s for s in snaps if s.get("status") == "lost"]
    pending = [s for s in snaps if s.get("status") == "pending"]
    stake_total = round(sum(float(s.get("stake") or 0) for s in won + lost), 2)
    profit = round(sum(float(s.get("profit") or 0) for s in won + lost), 2)
    settled_n = len(won) + len(lost)
    return {
        "snapshots": snaps,
        "pending_count": len(pending),
        "won_count": len(won),
        "lost_count": len(lost),
        "settled_count": settled_n,
        "win_rate": round(100.0 * len(won) / settled_n, 1) if settled_n else 0.0,
        "stake_total": stake_total,
        "profit": profit,
        "roi_pct": round(100.0 * profit / stake_total, 1) if stake_total else 0.0,
        "assumed_stake": ASSUMED_STAKE,
    }



