"""Pro Punter — live under-goals web dashboard."""

import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from engine import REFRESH_SECONDS, DataCache

app = Flask(__name__, static_folder="static")
cache = DataCache()
_cache_started = False


def _ensure_cache():
    global _cache_started
    if not _cache_started:
        cache.start()
        _cache_started = True

STATIC = Path(__file__).parent / "static"


@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/accumulator")
def accumulator_page():
    return send_from_directory(STATIC, "accumulator.html")


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
    return send_from_directory(STATIC, filename)


@app.route("/api/predictions")
def api_predictions():
    _ensure_cache()
    return jsonify(cache.get())


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    cache.refresh()
    return jsonify({"ok": True, "updated_at": cache.get().get("updated_at")})


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