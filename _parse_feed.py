import json
import requests

headers = {"User-Agent": "Mozilla/5.0"}
r = requests.get("https://www.soccerpunter.com/ls_feed.php", timeout=20, headers=headers)
data = r.json()
live_status = {"1H", "2H", "HT", "LIVE", "IN_PLAY", "ET", "P"}
matches = data.get("matches", {}).get("full", [])
live = [m for m in matches if m.get("status") in live_status]
print("total", len(matches), "live-ish", len(live))
for m in live[:12]:
    print(
        m["ta_name"],
        "vs",
        m["tb_name"],
        m["status"],
        m.get("minute"),
        f"HT {m.get('hts_A')}-{m.get('hts_B')}",
        f"FT {m.get('score_A')}-{m.get('score_B')}",
        m.get("leagueName"),
        m.get("match_id"),
        m.get("team_A_id"),
        m.get("team_B_id"),
    )