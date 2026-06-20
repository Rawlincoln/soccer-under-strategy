"""
Betting assistant — workflow, slip export, alerts (Telegram + browser feed).
Does NOT place bets; prepares slips and tracks the 100K daily plan manually.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
import requests

from onexbet_client import ONEXBET_SITE, onexbet_match_url

DATA_DIR = Path(__file__).parent / "data"
STATE_PATH = DATA_DIR / "assistant_state.json"
CONFIG_PATH = DATA_DIR / "assistant_config.json"
ALERTS_PATH = DATA_DIR / "assistant_alerts.json"

DAILY_TARGET = 100_000
STAKE_PER_SLIP = 5_000
MAX_SLIPS = 5
MAX_LOSSES = 2

WAVE_WINDOWS = {
    "wave1": {"half": "fh", "start": 15, "end": 20, "label": "Wave 1 · 1H anchor"},
    "wave2": {"half": "sh", "start": 60, "end": 65, "label": "Wave 2 · 2H booster"},
    "wave3": {"half": "any", "start": 0, "end": 999, "label": "Wave 3 · Closer / Goal Lock"},
}

ONEXBET_LIVE_URL = f"{ONEXBET_SITE}/en/live/football"


@dataclass
class SlipLeg:
    match: str
    home_team: str
    away_team: str
    league: str
    market: str
    selection: str
    minute: int
    period_score: str
    full_score: str
    confidence: float
    estimated_odds: float
    half: str = "fh"
    period_minute: int = 0
    minutes_left: int = 0
    closing_target: str = ""
    event_id: str = ""
    league_id: int = 0
    onexbet_url: str = ""
    recommendation: str = ""


@dataclass
class BetSlip:
    id: str
    slip_type: str
    title: str
    stake: float
    combined_odds: float
    potential_return: float
    potential_profit: float
    legs: list[SlipLeg] = field(default_factory=list)
    wave: str = ""
    risk_level: str = ""
    avg_confidence: float = 0.0
    lock_pct: float = 0.0
    checklist: list[str] = field(default_factory=list)
    onexbet_url: str = ONEXBET_LIVE_URL
    export_text: str = ""


@dataclass
class WorkflowState:
    date: str
    losses: int = 0
    wins: int = 0
    slips_placed: int = 0
    profit_recorded: float = 0.0
    stop_loss_hit: bool = False
    placed_slips: list[dict] = field(default_factory=list)


class AssistantStore:
    """Thread-safe persistence for workflow + alerts."""

    def __init__(self):
        self._lock = threading.Lock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path, default: dict) -> dict:
        if not path.exists():
            return dict(default)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return dict(default)

    def _write_json(self, path: Path, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_state(self) -> WorkflowState:
        today = date.today().isoformat()
        raw = self._read_json(STATE_PATH, {})
        if raw.get("date") != today:
            return WorkflowState(date=today)
        return WorkflowState(
            date=today,
            losses=int(raw.get("losses", 0)),
            wins=int(raw.get("wins", 0)),
            slips_placed=int(raw.get("slips_placed", 0)),
            profit_recorded=float(raw.get("profit_recorded", 0)),
            stop_loss_hit=bool(raw.get("stop_loss_hit", False)),
            placed_slips=list(raw.get("placed_slips", [])),
        )

    def save_state(self, state: WorkflowState) -> None:
        with self._lock:
            self._write_json(STATE_PATH, asdict(state))

    def load_config(self) -> dict[str, Any]:
        cfg = self._read_json(CONFIG_PATH, {
            "stake_per_slip": STAKE_PER_SLIP,
            "daily_target": DAILY_TARGET,
            "browser_alerts": True,
            "telegram_enabled": False,
        })
        token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("telegram_chat_id", "")
        cfg["telegram_bot_token"] = token
        cfg["telegram_chat_id"] = chat_id
        cfg["telegram_configured"] = bool(token and chat_id)
        cfg["telegram_enabled"] = bool(cfg.get("telegram_enabled") and token and chat_id)
        return cfg

    def save_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            cfg = self._read_json(CONFIG_PATH, {})
            allowed = {
                "stake_per_slip", "daily_target", "browser_alerts",
                "telegram_enabled", "telegram_bot_token", "telegram_chat_id",
            }
            for key, val in updates.items():
                if key in allowed:
                    cfg[key] = val
            self._write_json(CONFIG_PATH, cfg)
        return self.load_config()

    def load_alerts(self) -> list[dict]:
        raw = self._read_json(ALERTS_PATH, {"alerts": [], "seen_ids": []})
        return list(raw.get("alerts", []))

    def save_alerts(self, alerts: list[dict], seen_ids: list[str]) -> None:
        with self._lock:
            trimmed = alerts[-50:]
            self._write_json(ALERTS_PATH, {"alerts": trimmed, "seen_ids": seen_ids[-200:]})

    def get_seen_ids(self) -> set[str]:
        raw = self._read_json(ALERTS_PATH, {"seen_ids": []})
        return set(raw.get("seen_ids", []))


STORE = AssistantStore()


def _today() -> str:
    return date.today().isoformat()


def _profit(stake: float, odds: float) -> float:
    return round(stake * (odds - 1), 2)


def _leg_match_url(event_id: str, league_id: int = 0) -> str:
    if event_id and str(event_id).isdigit():
        return onexbet_match_url(event_id, league_id or None)
    return ONEXBET_LIVE_URL


def _default_checklist(stake: float) -> list[str]:
    return [
        "Open 1xBet Live Football",
        "Find each match and add the market to your bet slip",
        "Confirm odds have not dropped significantly",
        f"Enter stake: {stake:,.0f}",
        "Review all legs one more time",
        "Place bet manually on 1xBet",
    ]


def _format_export(slip: BetSlip) -> str:
    lines = [
        "═" * 42,
        "PRO PUNTER · MANUAL BET SLIP",
        "═" * 42,
        f"Type: {slip.title}",
        f"Stake: {slip.stake:,.0f}",
        f"Combined odds: {slip.combined_odds:.2f}",
        f"Potential return: {slip.potential_return:,.2f}",
        f"Potential profit: {slip.potential_profit:,.2f}",
        "",
    ]
    if slip.lock_pct:
        lines.append(f"Lock probability: {slip.lock_pct:.0f}%")
        lines.append("")
    if slip.legs:
        lines.append("LEGS:")
        for i, leg in enumerate(slip.legs, 1):
            half = "2H" if leg.half == "sh" else "1H"
            lines.append(
                f"{i}. {leg.match} — {leg.selection} — {leg.confidence:.0f}% "
                f"— {half} {leg.minute}' — {leg.period_score}"
            )
            if leg.onexbet_url:
                lines.append(f"   1xBet: {leg.onexbet_url}")
        lines.append("")
    lines.append("CHECKLIST:")
    for step in slip.checklist:
        lines.append(f"☐ {step}")
    lines.append("")
    lines.append(f"1xBet: {slip.onexbet_url}")
    lines.append("═" * 42)
    return "\n".join(lines)


def acca_to_slip(acca: dict, stake: float, wave: str = "") -> BetSlip:
    legs = []
    for leg in acca.get("legs", []):
        eid = str(leg.get("event_id", ""))
        lid = int(leg.get("league_id") or 0)
        legs.append(SlipLeg(
            match=leg["match"],
            home_team=leg["home_team"],
            away_team=leg["away_team"],
            league=leg.get("league", ""),
            market=leg.get("market", ""),
            selection=leg.get("selection", leg.get("market", "")),
            minute=int(leg.get("minute", 0)),
            period_score=leg.get("period_score", leg.get("fh_score", "0-0")),
            full_score=leg.get("full_score", "0-0"),
            confidence=float(leg.get("confidence", 0)),
            estimated_odds=float(leg.get("estimated_odds", 1.5)),
            half=leg.get("half", "fh"),
            period_minute=int(leg.get("period_minute") or 0),
            event_id=eid,
            league_id=lid,
            onexbet_url=_leg_match_url(eid, lid),
            recommendation=leg.get("recommendation", ""),
        ))
    odds = float(acca.get("combined_odds", 1.0))
    slip_id = f"acca-{acca.get('id', 0)}"
    slip = BetSlip(
        id=slip_id,
        slip_type="accumulator",
        title=acca.get("name", "Accumulator"),
        stake=stake,
        combined_odds=odds,
        potential_return=round(stake * odds, 2),
        potential_profit=_profit(stake, odds),
        legs=legs,
        wave=wave,
        risk_level=acca.get("risk_level", ""),
        avg_confidence=float(acca.get("avg_confidence", 0)),
        checklist=_default_checklist(stake),
        onexbet_url=legs[0].onexbet_url if legs else ONEXBET_LIVE_URL,
    )
    slip.export_text = _format_export(slip)
    return slip


def lock_to_slip(match: dict, stake: float) -> BetSlip:
    eid = str(match.get("event_id", ""))
    lid = int(match.get("league_id") or 0)
    match_url = _leg_match_url(eid, lid)
    leg = SlipLeg(
        match=f"{match['home_team']} vs {match['away_team']}",
        home_team=match["home_team"],
        away_team=match["away_team"],
        league=match.get("league", ""),
        market=match.get("lock_market", "No more goals"),
        selection=match.get("lock_label", "NO MORE GOALS"),
        minute=int(match.get("minute", 0)),
        period_score=match.get("period_score", "0-0"),
        full_score=match.get("full_score", "0-0"),
        confidence=float(match.get("lock_pct", 0)),
        estimated_odds=1.05,
        half=match.get("half", "fh"),
        period_minute=int(match.get("period_minute") or 0),
        minutes_left=int(match.get("minutes_left") or 0),
        closing_target=match.get("closing_target", ""),
        event_id=eid,
        league_id=lid,
        onexbet_url=match_url,
        recommendation="LOCK",
    )
    slip_id = f"lock-{match.get('event_id')}-{match.get('half')}"
    slip = BetSlip(
        id=slip_id,
        slip_type="goal_lock",
        title=f"Goal Lock · {leg.match}",
        stake=stake,
        combined_odds=1.05,
        potential_return=round(stake * 1.05, 2),
        potential_profit=_profit(stake, 1.05),
        legs=[leg],
        wave="wave3",
        lock_pct=float(match.get("lock_pct", 0)),
        checklist=_default_checklist(stake) + [
            f"Market: {match.get('lock_market', '')}",
            f"{match.get('minutes_left', '?')}' left to {match.get('closing_target', 'HT/FT')}",
        ],
        onexbet_url=match_url,
    )
    slip.export_text = _format_export(slip)
    return slip


def _in_entry_window(minute: int, half: str) -> Optional[str]:
    if half == "fh" and WAVE_WINDOWS["wave1"]["start"] <= minute <= WAVE_WINDOWS["wave1"]["end"]:
        return "wave1"
    if half == "sh" and WAVE_WINDOWS["wave2"]["start"] <= minute <= WAVE_WINDOWS["wave2"]["end"]:
        return "wave2"
    return None


def _acca_matches_wave(acca: dict, wave: str) -> bool:
    legs = acca.get("legs") or []
    if not legs:
        return False
    if wave == "wave1":
        return all(leg.get("half") == "fh" for leg in legs)
    if wave == "wave2":
        return all(leg.get("half") == "sh" for leg in legs)
    return True


def _active_waves(matches: list[dict], closing_matches: list[dict]) -> list[dict]:
    waves: list[dict] = []
    fh_window = any(
        _in_entry_window(int(m.get("minute", 0)), "fh")
        for m in matches if m.get("half") == "fh"
    )
    sh_window = any(
        _in_entry_window(int(m.get("minute", 0)), "sh")
        for m in matches if m.get("half") == "sh"
    )
    if fh_window:
        waves.append({
            "id": "wave1",
            **WAVE_WINDOWS["wave1"],
            "status": "ACTIVE",
            "action": "Place 1× anchor acca (4–6 legs, FH unders, 5,000 stake)",
        })
    else:
        waves.append({
            "id": "wave1",
            **WAVE_WINDOWS["wave1"],
            "status": "WAITING",
            "action": "Wait for 1H matches to hit 15′–20′ entry window",
        })

    if sh_window:
        waves.append({
            "id": "wave2",
            **WAVE_WINDOWS["wave2"],
            "status": "ACTIVE",
            "action": "Place 1–2× 2H under accas when BET signals align",
        })
    else:
        waves.append({
            "id": "wave2",
            **WAVE_WINDOWS["wave2"],
            "status": "WAITING",
            "action": "Wait for 2H matches to hit 60′–65′ entry window",
        })

    lock_count = len(closing_matches)
    waves.append({
        "id": "wave3",
        **WAVE_WINDOWS["wave3"],
        "status": "ACTIVE" if lock_count else "STANDBY",
        "action": f"{lock_count} goal lock(s) ready" if lock_count else "Use late accas or goal locks if short of target",
        "lock_count": lock_count,
    })
    return waves


def build_workflow(
    main_payload: dict[str, Any],
    closing_payload: dict[str, Any],
    state: Optional[WorkflowState] = None,
    config: Optional[dict] = None,
) -> dict[str, Any]:
    state = state or STORE.load_state()
    config = config or STORE.load_config()
    stake = float(config.get("stake_per_slip", STAKE_PER_SLIP))
    target = float(config.get("daily_target", DAILY_TARGET))

    matches = main_payload.get("matches") or []
    accas = (main_payload.get("accumulators") or {}).get("accumulators") or []
    closing = closing_payload.get("matches") or []

    waves = _active_waves(matches, closing)
    active_wave = next((w for w in waves if w["status"] == "ACTIVE"), None)

    recommendations: list[dict] = []
    if not state.stop_loss_hit and state.slips_placed < MAX_SLIPS:
        if active_wave and active_wave["id"] in ("wave1", "wave2"):
            wave_accas = [a for a in accas if _acca_matches_wave(a, active_wave["id"])]
            for acca in wave_accas[:2]:
                slip = acca_to_slip(acca, stake, wave=active_wave["id"])
                recommendations.append({
                    "priority": "high" if active_wave["id"] == "wave1" else "medium",
                    "reason": f"{active_wave['label']} — entry window open",
                    "slip": asdict(slip),
                })
        for m in closing[:3]:
            slip = lock_to_slip(m, stake)
            recommendations.append({
                "priority": "high",
                "reason": f"Goal Lock {m.get('lock_pct', 0):.0f}% — {m.get('minutes_left')}′ to {m.get('closing_target')}",
                "slip": asdict(slip),
            })
        if not recommendations and accas:
            slip = acca_to_slip(accas[0], stake, wave="wave3")
            recommendations.append({
                "priority": "low",
                "reason": "Best available acca (no active wave window)",
                "slip": asdict(slip),
            })

    gap = max(0, target - state.profit_recorded)
    slips_remaining = max(0, MAX_SLIPS - state.slips_placed)

    return {
        "date": state.date,
        "daily_target": target,
        "stake_per_slip": stake,
        "max_slips": MAX_SLIPS,
        "max_losses": MAX_LOSSES,
        "losses": state.losses,
        "wins": state.wins,
        "slips_placed": state.slips_placed,
        "slips_remaining": slips_remaining,
        "profit_recorded": state.profit_recorded,
        "gap_to_target": gap,
        "stop_loss_hit": state.stop_loss_hit,
        "can_place": not state.stop_loss_hit and slips_remaining > 0,
        "waves": waves,
        "active_wave": active_wave,
        "recommendations": recommendations,
        "placed_slips": state.placed_slips,
    }


def record_slip_placed(slip_id: str, slip_type: str, stake: float, title: str) -> dict[str, Any]:
    state = STORE.load_state()
    if state.stop_loss_hit:
        return {"ok": False, "error": "Stop-loss active — max 2 losses reached"}
    if state.slips_placed >= MAX_SLIPS:
        return {"ok": False, "error": f"Max {MAX_SLIPS} slips per day reached"}
    state.slips_placed += 1
    state.placed_slips.append({
        "id": slip_id,
        "type": slip_type,
        "stake": stake,
        "title": title,
        "placed_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
    })
    STORE.save_state(state)
    return {"ok": True, "state": asdict(state)}


def record_slip_result(slip_id: str, won: bool, profit: float = 0.0) -> dict[str, Any]:
    state = STORE.load_state()
    entry = next((s for s in state.placed_slips if s["id"] == slip_id and s.get("result") is None), None)
    if not entry:
        return {"ok": False, "error": "Slip not found or already settled"}

    entry["result"] = "won" if won else "lost"
    entry["settled_at"] = datetime.now(timezone.utc).isoformat()
    if won:
        state.wins += 1
        state.profit_recorded += profit
    else:
        state.losses += 1
        if state.losses >= MAX_LOSSES:
            state.stop_loss_hit = True
    STORE.save_state(state)
    return {"ok": True, "state": asdict(state)}


def reset_workflow() -> dict[str, Any]:
    state = WorkflowState(date=_today())
    STORE.save_state(state)
    return {"ok": True, "state": asdict(state)}


def _alert_id(kind: str, key: str) -> str:
    return f"{kind}:{key}:{_today()}"


def detect_alerts(
    main_payload: dict[str, Any],
    closing_payload: dict[str, Any],
    workflow: dict[str, Any],
) -> list[dict]:
    seen = STORE.get_seen_ids()
    new_alerts: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()

    for m in closing_payload.get("matches") or []:
        aid = _alert_id("lock", f"{m.get('event_id')}-{m.get('half')}")
        if aid in seen:
            continue
        new_alerts.append({
            "id": aid,
            "type": "goal_lock",
            "priority": "high",
            "title": f"Goal Lock {m.get('lock_pct', 0):.0f}%",
            "message": f"{m['home_team']} vs {m['away_team']} — {m.get('lock_label')} — {m.get('minute')}'",
            "created_at": now,
            "slip_hint": "goal_lock",
            "event_id": m.get("event_id"),
        })
        seen.add(aid)

    accas = (main_payload.get("accumulators") or {}).get("accumulators") or []
    active = workflow.get("active_wave")
    if active and active.get("id") in ("wave1", "wave2"):
        for acca in accas[:2]:
            if not _acca_matches_wave(acca, active["id"]):
                continue
            aid = _alert_id("wave", f"{active['id']}-acca-{acca.get('id')}")
            if aid in seen:
                continue
            new_alerts.append({
                "id": aid,
                "type": "wave_acca",
                "priority": "high",
                "title": f"{active['label']} ready",
                "message": f"{acca.get('name')} — {acca.get('leg_count')} legs @ {acca.get('combined_odds', 0):.2f}",
                "created_at": now,
                "slip_hint": "accumulator",
                "acca_id": acca.get("id"),
            })
            seen.add(aid)

    if workflow.get("stop_loss_hit"):
        aid = _alert_id("stop", "loss")
        if aid not in seen:
            new_alerts.append({
                "id": aid,
                "type": "stop_loss",
                "priority": "critical",
                "title": "Stop-loss hit",
                "message": "2 slips lost today — stop placing bets for the rest of the day",
                "created_at": now,
            })
            seen.add(aid)

    existing = STORE.load_alerts()
    combined = new_alerts + existing
    STORE.save_alerts(combined, list(seen))
    return new_alerts


def send_telegram_alert(text: str, config: Optional[dict] = None) -> bool:
    config = config or STORE.load_config()
    if not config.get("telegram_enabled"):
        return False
    token = config.get("telegram_bot_token", "")
    chat_id = config.get("telegram_chat_id", "")
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        return r.ok
    except requests.RequestException:
        return False


def dispatch_new_alerts(alerts: list[dict], config: Optional[dict] = None) -> int:
    config = config or STORE.load_config()
    sent = 0
    for alert in alerts:
        body = f"🔔 {alert['title']}\n{alert['message']}\n\nOpen Pro Punter → Betting Assistant"
        if send_telegram_alert(body, config):
            sent += 1
    return sent


def build_assistant_payload(
    main_payload: dict[str, Any],
    closing_payload: dict[str, Any],
) -> dict[str, Any]:
    config = STORE.load_config()
    workflow = build_workflow(main_payload, closing_payload)
    new_alerts = detect_alerts(main_payload, closing_payload, workflow)
    if new_alerts:
        dispatch_new_alerts(new_alerts, config)

    all_alerts = STORE.load_alerts()
    safe_config = {k: v for k, v in config.items() if k != "telegram_bot_token"}
    safe_config["telegram_configured"] = config.get("telegram_configured", False)

    accas = (main_payload.get("accumulators") or {}).get("accumulators") or []
    stake = float(config.get("stake_per_slip", STAKE_PER_SLIP))
    export_slips = [asdict(acca_to_slip(a, stake)) for a in accas[:5]]
    for m in (closing_payload.get("matches") or [])[:5]:
        export_slips.append(asdict(lock_to_slip(m, stake)))

    return {
        "updated_at": main_payload.get("updated_at"),
        "workflow": workflow,
        "alerts": all_alerts[:20],
        "new_alerts": new_alerts,
        "config": safe_config,
        "export_slips": export_slips,
        "onexbet_live_url": ONEXBET_LIVE_URL,
    }