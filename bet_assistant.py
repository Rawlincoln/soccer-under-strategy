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

from onexbet_client import get_onexbet_site, onexbet_live_url, onexbet_match_url

DATA_DIR = Path(__file__).parent / "data"
STATE_PATH = DATA_DIR / "assistant_state.json"
CONFIG_PATH = DATA_DIR / "assistant_config.json"
ALERTS_PATH = DATA_DIR / "assistant_alerts.json"

DAILY_TARGET = 100_000
STAKE_PER_SLIP = 5_000
MAX_LOSS_STREAK = 5

WAVE_WINDOWS = {
    "wave1": {"half": "fh", "start": 15, "end": 20, "label": "Wave 1 · 1H anchor"},
    "wave2": {"half": "sh", "start": 60, "end": 65, "label": "Wave 2 · 2H booster"},
    "wave3": {"half": "any", "start": 0, "end": 999, "label": "Wave 3 · Closer / Goal Lock"},
}

def effective_onexbet_site(config: Optional[dict] = None) -> str:
    cfg = config or STORE.load_config()
    return get_onexbet_site(cfg.get("onexbet_site") or None)


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
    onexbet_url: str = ""
    export_text: str = ""


@dataclass
class WorkflowState:
    date: str
    losses: int = 0
    wins: int = 0
    slips_placed: int = 0
    profit_recorded: float = 0.0
    loss_streak: int = 0
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
        raw = self._read_json(STATE_PATH, {})
        if not raw:
            return WorkflowState(date=_today())
        return WorkflowState(
            date=raw.get("date", _today()),
            losses=int(raw.get("losses", 0)),
            wins=int(raw.get("wins", 0)),
            slips_placed=int(raw.get("slips_placed", 0)),
            profit_recorded=float(raw.get("profit_recorded", 0)),
            loss_streak=int(raw.get("loss_streak", 0)),
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
            "onexbet_site": "",
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
                "onexbet_site",
            }
            for key, val in updates.items():
                if key not in allowed:
                    continue
                if key in ("telegram_bot_token", "telegram_chat_id") and not str(val).strip():
                    continue
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


def _leg_match_url(
    event_id: str,
    league_id: int = 0,
    config: Optional[dict] = None,
) -> str:
    site = effective_onexbet_site(config)
    if event_id and str(event_id).isdigit():
        return onexbet_match_url(event_id, league_id or None, site=site)
    return onexbet_live_url(site)


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
            league = leg.league or "Football"
            pm = leg.period_minute
            clock = (
                f"{leg.minute}' · {leg.minutes_left}' to {leg.closing_target}"
                if leg.minutes_left
                else (f"{half} {leg.minute}'" if leg.half == "fh" else f"{leg.minute}' · 2H {pm or max(0, leg.minute - 45)}'")
            )
            lines.append(
                f"{i}. {leg.match} ({league}) — {leg.selection} — {leg.confidence:.0f}% "
                f"— {clock} — {half} {leg.period_score} · FT {leg.full_score}"
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
        onexbet_url=legs[0].onexbet_url if legs else onexbet_live_url(effective_onexbet_site()),
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

    return {
        "date": state.date,
        "daily_target": target,
        "stake_per_slip": stake,
        "max_loss_streak": MAX_LOSS_STREAK,
        "losses": state.losses,
        "wins": state.wins,
        "loss_streak": state.loss_streak,
        "slips_placed": state.slips_placed,
        "profit_recorded": state.profit_recorded,
        "gap_to_target": gap,
        "target_reached": state.profit_recorded >= target,
        "can_place": True,
        "waves": waves,
        "active_wave": active_wave,
        "recommendations": recommendations,
        "placed_slips": state.placed_slips,
    }


def record_slip_placed(slip_id: str, slip_type: str, stake: float, title: str) -> dict[str, Any]:
    state = STORE.load_state()
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
    config = STORE.load_config()
    target = float(config.get("daily_target", DAILY_TARGET))
    entry = next((s for s in state.placed_slips if s["id"] == slip_id and s.get("result") is None), None)
    if not entry:
        return {"ok": False, "error": "Slip not found or already settled"}

    entry["result"] = "won" if won else "lost"
    entry["settled_at"] = datetime.now(timezone.utc).isoformat()
    if won:
        state.wins += 1
        state.profit_recorded += profit
        state.loss_streak = 0
    else:
        state.losses += 1
        state.loss_streak += 1

    reset_reason = None
    if state.profit_recorded >= target:
        reset_reason = "target_reached"
    elif state.loss_streak >= MAX_LOSS_STREAK:
        reset_reason = "loss_streak"

    if reset_reason:
        previous = asdict(state)
        state = WorkflowState(date=_today())
        STORE.save_state(state)
        return {
            "ok": True,
            "state": asdict(state),
            "session_reset": True,
            "reset_reason": reset_reason,
            "previous_session": previous,
        }

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

    loss_streak = int(workflow.get("loss_streak") or 0)
    max_streak = int(workflow.get("max_loss_streak") or MAX_LOSS_STREAK)
    if loss_streak >= max(1, max_streak - 1):
        aid = _alert_id("streak", str(loss_streak))
        if aid not in seen:
            new_alerts.append({
                "id": aid,
                "type": "loss_streak",
                "priority": "critical" if loss_streak >= max_streak else "high",
                "title": f"{loss_streak}-loss streak",
                "message": (
                    f"{loss_streak} losses in a row — session resets after {max_streak}"
                    if loss_streak < max_streak
                    else f"{max_streak} losses in a row — session reset, fresh target started"
                ),
                "created_at": now,
            })
            seen.add(aid)

    existing = STORE.load_alerts()
    combined = new_alerts + existing
    STORE.save_alerts(combined, list(seen))
    return new_alerts


def _telegram_post(token: str, method: str, payload: dict) -> tuple[bool, str, Optional[dict]]:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            timeout=15,
        )
        data = r.json() if r.content else {}
        if r.ok and data.get("ok"):
            return True, "ok", data.get("result")
        err = data.get("description") or r.text or f"HTTP {r.status_code}"
        return False, str(err), None
    except requests.RequestException as exc:
        return False, str(exc), None


def discover_telegram_chats(token: str) -> dict[str, Any]:
    """Return chat IDs from recent messages to the bot (user must /start bot first)."""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "Bot token required"}

    ok, err, result = _telegram_post(token, "getUpdates", {"limit": 20, "timeout": 0})
    if not ok:
        return {"ok": False, "error": err}

    chats: dict[str, dict] = {}
    for item in result or []:
        msg = item.get("message") or item.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        key = str(cid)
        chats[key] = {
            "chat_id": key,
            "type": chat.get("type", ""),
            "title": chat.get("title") or chat.get("username") or "",
            "name": " ".join(
                x for x in [chat.get("first_name"), chat.get("last_name")] if x
            ).strip() or chat.get("username", ""),
            "username": chat.get("username", ""),
        }

    chat_list = list(chats.values())
    if not chat_list:
        return {
            "ok": False,
            "error": "No messages found. Open your bot in Telegram, tap Start, send any message, then try again.",
            "chats": [],
        }
    return {"ok": True, "chats": chat_list}


def send_telegram_message(
    text: str,
    *,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    config: Optional[dict] = None,
) -> tuple[bool, str]:
    config = config or STORE.load_config()
    token = (token or config.get("telegram_bot_token") or "").strip()
    chat_id = str(chat_id or config.get("telegram_chat_id") or "").strip()
    if not token:
        return False, "Bot token missing — add it below or set TELEGRAM_BOT_TOKEN"
    if not chat_id:
        return False, "Chat ID missing — discover it below or set TELEGRAM_CHAT_ID"
    ok, err, _ = _telegram_post(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    })
    return ok, err if not ok else "sent"


def send_telegram_alert(text: str, config: Optional[dict] = None) -> bool:
    config = config or STORE.load_config()
    if not config.get("telegram_enabled"):
        return False
    ok, _ = send_telegram_message(text, config=config)
    return ok


def test_telegram(config: Optional[dict] = None) -> dict[str, Any]:
    config = config or STORE.load_config()
    msg = (
        "✅ Pro Punter Telegram alerts are working!\n\n"
        "You will receive notifications for:\n"
        "• Goal Lock picks (95%+)\n"
        "• Wave 1 / Wave 2 acca signals\n"
        "• Stop-loss warnings"
    )
    ok, detail = send_telegram_message(msg, config=config)
    return {
        "ok": ok,
        "error": None if ok else detail,
        "telegram_configured": config.get("telegram_configured", False),
        "telegram_enabled": config.get("telegram_enabled", False),
    }


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
        "onexbet_site": effective_onexbet_site(config),
        "onexbet_live_url": onexbet_live_url(effective_onexbet_site(config)),
    }