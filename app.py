"""Pro Punter — live under-goals web dashboard."""

import json
import os
from dataclasses import asdict
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from basketball_engine import REFRESH_SECONDS as BB_REFRESH_SECONDS, BasketballCache
from bet_assistant import (
    STORE,
    acca_to_slip,
    discover_telegram_chats,
    effective_onexbet_android_package,
    effective_onexbet_site,
    lock_to_slip,
    log_bet_result,
    record_slip_outcome,
    record_slip_placed,
    record_slip_result,
    reset_workflow,
    test_telegram,
)
from onexbet_client import (
    onexbet_app_open_url,
    onexbet_live_url,
    onexbet_match_url,
)
from engine import REFRESH_SECONDS, DataCache

app = Flask(__name__, static_folder="static")
cache = DataCache()
basketball_cache = BasketballCache()
_cache_started = False
_bb_cache_started = False


def _ensure_cache():
    global _cache_started
    if not _cache_started:
        cache.start()
        _cache_started = True


def _ensure_basketball_cache():
    global _bb_cache_started
    if not _bb_cache_started:
        basketball_cache.start()
        _bb_cache_started = True

STATIC = Path(__file__).parent / "static"
ASSET_VERSION = os.environ.get("ASSET_VERSION", "22")


def _no_cache(resp: Response) -> Response:
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def _serve_html(filename: str) -> Response:
    path = STATIC / filename
    html = path.read_text(encoding="utf-8")
    html = html.replace("{{ASSET_VERSION}}", ASSET_VERSION)
    return _no_cache(Response(html, mimetype="text/html; charset=utf-8"))


@app.route("/")
def index():
    return _serve_html("index.html")


@app.route("/accumulator")
def accumulator_page():
    return _serve_html("accumulator.html")


@app.route("/strategy")
def strategy_page():
    return _serve_html("strategy.html")


@app.route("/basketball")
def basketball_page():
    return _serve_html("basketball.html")


@app.route("/closing")
def closing_page():
    return _serve_html("closing.html")


@app.route("/assistant")
def assistant_page():
    return _serve_html("assistant.html")


@app.route("/open/1xbet")
def open_onexbet_match():
    """Landing page: tap → 1xBet Kenya app (Android intent). Works from Telegram after Open in Chrome."""
    game_id = request.args.get("game_id", "").strip()
    league_id = request.args.get("league_id", "").strip()
    sport = request.args.get("sport", "football").strip() or "football"
    config = STORE.load_config()
    site = effective_onexbet_site(config)
    pkg = effective_onexbet_android_package(config)
    if game_id.isdigit():
        lid = int(league_id) if league_id.isdigit() else None
        match_url = onexbet_match_url(game_id, lid, site=site, sport=sport)
    else:
        match_url = onexbet_live_url(site)
    https_url = onexbet_app_open_url(site)
    payload = {"https": https_url, "match": match_url, "package": pkg}
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Open 1xBet</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0d1117; color: #e6edf3;
      display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }}
    .box {{ text-align: center; max-width: 360px; width: 100%; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 8px; }}
    p {{ color: #8b949e; font-size: 0.9rem; line-height: 1.45; margin: 0 0 16px; }}
    .btn {{ display: block; width: 100%; box-sizing: border-box; margin: 10px 0; padding: 14px 16px;
      border: none; border-radius: 10px; font-size: 1rem; font-weight: 700; cursor: pointer; text-decoration: none; }}
    .btn-primary {{ background: #238636; color: #fff; }}
    .btn-secondary {{ background: #21262d; color: #e6edf3; border: 1px solid #30363d; }}
    .hint {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 12px; margin-bottom: 16px;
      font-size: 0.85rem; color: #c9d1d9; text-align: left; }}
    .pkg {{ font-size: 0.75rem; color: #6e7681; margin-top: 12px; word-break: break-all; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>Open in 1xBet app</h1>
    <p>Tap the green button — opens the <strong>1xBet app</strong> via <strong>1xbet.co.ke/en/mobile</strong>.</p>
    <p style="font-size:0.8rem;color:#8b949e;margin-top:-8px">Match link (in app → Live Football): <a href="{match_url}" style="color:#3fb950">{match_url}</a></p>
    <div id="inapp-hint" class="hint" hidden>
      <strong>Using Telegram?</strong> Tap <strong>⋮</strong> (top right) → <strong>Open in Chrome</strong>,
      then tap the green button below.
    </div>
    <div id="settings-hint" class="hint" hidden>
      <strong>One-time setup (required):</strong><br>
      1. <strong>Settings → Apps → 1xBet</strong> (Sport Betting &amp; Casino)<br>
      2. Tap <strong>Open by default</strong> → turn ON <strong>Open supported links</strong><br>
      3. Add / enable <strong>1xbet.co.ke</strong><br>
      Then links open the app instead of Play Store or browser.
    </div>
    <button type="button" id="open-app" class="btn btn-primary">Open 1xBet app</button>
    <button type="button" id="open-chrome" class="btn btn-secondary" hidden>Open in Chrome first</button>
    <a id="open-web" class="btn btn-secondary" href="{match_url}">Open match in browser</a>
    <p class="pkg">Package: {pkg or "org.xbet.client.ke_ps"}</p>
  </div>
  <script>window.ONEXBET_OPEN = {json.dumps(payload)};</script>
  <script src="/static/open-1xbet.js?v={ASSET_VERSION}"></script>
</body>
</html>"""
    return _no_cache(Response(html, mimetype="text/html; charset=utf-8"))


@app.route("/api/accumulators")
def api_accumulators():
    _ensure_cache()
    data = cache.get()
    return jsonify({
        "updated_at": data.get("updated_at"),
        "refresh_seconds": data.get("refresh_seconds", REFRESH_SECONDS),
        "onexbet_site": data.get("onexbet_site"),
        "onexbet_live_url": data.get("onexbet_live_url"),
        "onexbet_android_package": data.get("onexbet_android_package"),
        **data.get("accumulators", {}),
    })


@app.route("/static/<path:filename>")
def static_files(filename):
    resp = send_from_directory(STATIC, filename)
    if filename.endswith((".js", ".html", ".css")):
        return _no_cache(resp)
    return resp


@app.route("/api/predictions")
def api_predictions():
    _ensure_cache()
    return jsonify(cache.get())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    cache.refresh()
    return jsonify({"ok": True, "updated_at": cache.get().get("updated_at")})


@app.route("/api/basketball")
def api_basketball():
    _ensure_basketball_cache()
    return jsonify(basketball_cache.get())


@app.route("/api/basketball/refresh", methods=["POST"])
def api_basketball_refresh():
    basketball_cache.refresh()
    return jsonify({"ok": True, "updated_at": basketball_cache.get().get("updated_at")})


@app.route("/api/closing")
def api_closing():
    _ensure_cache()
    return jsonify(cache.get_closing())


@app.route("/api/closing/refresh", methods=["POST"])
def api_closing_refresh():
    cache.refresh()
    return jsonify({"ok": True, "updated_at": cache.get_closing().get("updated_at")})


@app.route("/api/assistant")
def api_assistant():
    _ensure_cache()
    return jsonify(cache.get_assistant())


@app.route("/api/assistant/config", methods=["GET", "POST"])
def api_assistant_config():
    if request.method == "GET":
        cfg = STORE.load_config()
        safe = {k: v for k, v in cfg.items() if k != "telegram_bot_token"}
        safe["telegram_token_set"] = bool(cfg.get("telegram_bot_token"))
        return jsonify(safe)
    body = request.get_json(silent=True) or {}
    cfg = STORE.save_config(body)
    safe = {k: v for k, v in cfg.items() if k != "telegram_bot_token"}
    safe["telegram_token_set"] = bool(cfg.get("telegram_bot_token"))
    return jsonify({"ok": True, "config": safe})


@app.route("/api/assistant/telegram/test", methods=["POST"])
def api_telegram_test():
    body = request.get_json(silent=True) or {}
    cfg = STORE.load_config()
    if body.get("telegram_bot_token"):
        cfg = {**cfg, "telegram_bot_token": body["telegram_bot_token"]}
    if body.get("telegram_chat_id"):
        cfg = {**cfg, "telegram_chat_id": str(body["telegram_chat_id"])}
    if body.get("telegram_enabled") is not None:
        cfg = {**cfg, "telegram_enabled": bool(body["telegram_enabled"])}
    elif not cfg.get("telegram_enabled"):
        cfg = {**cfg, "telegram_enabled": True}
    return jsonify(test_telegram(cfg))


@app.route("/api/assistant/telegram/discover", methods=["POST"])
def api_telegram_discover():
    body = request.get_json(silent=True) or {}
    token = body.get("telegram_bot_token") or STORE.load_config().get("telegram_bot_token", "")
    return jsonify(discover_telegram_chats(token))


@app.route("/api/assistant/workflow/placed", methods=["POST"])
def api_assistant_placed():
    body = request.get_json(silent=True) or {}
    result = record_slip_placed(
        slip_id=str(body.get("slip_id", "")),
        slip_type=str(body.get("slip_type", "accumulator")),
        stake=float(body.get("stake", 5000)),
        title=str(body.get("title", "Bet slip")),
        wave=str(body.get("wave", "")),
        potential_profit=float(body.get("potential_profit", 0)),
        combined_odds=float(body.get("combined_odds", 0)),
    )
    if result.get("ok"):
        cache.refresh()
    return jsonify(result)


@app.route("/api/assistant/workflow/result", methods=["POST"])
def api_assistant_result():
    body = request.get_json(silent=True) or {}
    slip_meta = body.get("slip_meta") or {}
    leg_event_id = str(body.get("leg_event_id") or "")
    if slip_meta and not leg_event_id:
        result = record_slip_outcome(
            slip_id=str(body.get("slip_id", "")),
            won=bool(body.get("won")),
            profit=float(body.get("profit", 0)),
            slip_meta=slip_meta,
        )
    elif leg_event_id:
        result = record_slip_outcome(
            slip_id=str(body.get("slip_id", "")),
            won=bool(body.get("won")),
            profit=float(body.get("profit", 0)),
            leg_event_id=leg_event_id,
            slip_meta=slip_meta,
        )
    else:
        result = record_slip_result(
            slip_id=str(body.get("slip_id", "")),
            won=bool(body.get("won")),
            profit=float(body.get("profit", 0)),
        )
    if result.get("ok"):
        cache.refresh()
    return jsonify(result)


@app.route("/api/assistant/workflow/log", methods=["POST"])
def api_assistant_log():
    body = request.get_json(silent=True) or {}
    result = log_bet_result(
        title=str(body.get("title", "Manual bet")),
        stake=float(body.get("stake", 5000)),
        won=bool(body.get("won")),
        profit=float(body.get("profit", 0)),
        slip_type=str(body.get("slip_type", "manual")),
    )
    if result.get("ok"):
        cache.refresh()
    return jsonify(result)


@app.route("/api/assistant/workflow/reset", methods=["POST"])
def api_assistant_reset():
    result = reset_workflow()
    cache.refresh()
    return jsonify(result)


@app.route("/api/assistant/export/acca/<int:acca_id>")
def api_export_acca(acca_id: int):
    _ensure_cache()
    data = cache.get()
    stake = float(request.args.get("stake", STORE.load_config().get("stake_per_slip", 5000)))
    accas = (data.get("accumulators") or {}).get("accumulators") or []
    acca = next((a for a in accas if a.get("id") == acca_id), None)
    if not acca:
        return jsonify({"error": "Acca not found"}), 404
    slip = acca_to_slip(acca, stake)
    return jsonify(asdict(slip))


@app.route("/api/assistant/export/lock")
def api_export_lock():
    _ensure_cache()
    closing = cache.get_closing()
    event_id = request.args.get("event_id", "")
    half = request.args.get("half", "fh")
    stake = float(request.args.get("stake", STORE.load_config().get("stake_per_slip", 5000)))
    match = next(
        (m for m in (closing.get("matches") or [])
         if str(m.get("event_id")) == event_id and m.get("half") == half),
        None,
    )
    if not match:
        return jsonify({"error": "Lock not found"}), 404
    slip = lock_to_slip(match, stake)
    return jsonify(asdict(slip))


@app.route("/health")
def health():
    return jsonify({"ok": True})


if __name__ == "__main__":
    _ensure_cache()
    port = int(os.environ.get("PORT", 5050))
    print("=" * 60)
    print("  Pro Punter")
    print(f"  Open: http://localhost:{port}")
    print(f"  Auto-refresh: every {REFRESH_SECONDS}s")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)