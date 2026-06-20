"""Pro Punter — live under-goals web dashboard."""

import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from basketball_engine import REFRESH_SECONDS as BB_REFRESH_SECONDS, BasketballCache
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


@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/accumulator")
def accumulator_page():
    return send_from_directory(STATIC, "accumulator.html")


@app.route("/strategy")
def strategy_page():
    return send_from_directory(STATIC, "strategy.html")


@app.route("/basketball")
def basketball_page():
    return send_from_directory(STATIC, "basketball.html")


@app.route("/closing")
def closing_page():
    return send_from_directory(STATIC, "closing.html")


@app.route("/api/accumulators")
def api_accumulators():
    _ensure_cache()
    data = cache.get()
    return jsonify({
        "updated_at": data.get("updated_at"),
        "refresh_seconds": data.get("refresh_seconds", REFRESH_SECONDS),
        **data.get("accumulators", {}),
    })


@app.route("/static/<path:filename>")
def static_files(filename):
    resp = send_from_directory(STATIC, filename)
    if filename.endswith((".js", ".html", ".css")):
        resp.headers["Cache-Control"] = "no-cache"
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