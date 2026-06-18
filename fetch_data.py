"""Fetch soccer data and compute first-half under baselines."""
import json
import requests

BASE = "https://www.thesportsdb.com/api/v1/json/3"


def fetch_wc_fh_stats():
    r = requests.get(f"{BASE}/eventsseason.php", params={"id": 4429, "s": 2026}, timeout=30)
    events = r.json().get("events", [])
    fh_stats = []
    for e in events:
        if e.get("strStatus") != "FT":
            continue
        tr = requests.get(f"{BASE}/lookuptimeline.php", params={"id": e["idEvent"]}, timeout=30)
        goals = [t for t in tr.json().get("timeline", []) if t.get("strTimeline") == "Goal"]
        fh_goals = sum(1 for g in goals if int(g.get("intTime", 99)) <= 45)
        fh_stats.append({"match": e["strEvent"], "fh_goals": fh_goals})
    return fh_stats


def fetch_today_soccer():
    r = requests.get(
        f"{BASE}/eventsday.php", params={"d": "2026-06-18", "s": "Soccer"}, timeout=30
    )
    return r.json().get("events", [])


if __name__ == "__main__":
    fh = fetch_wc_fh_stats()
    today = fetch_today_soccer()
    n = len(fh)
    print(f"WC finished: {n}, today soccer: {len(today)}")
    if n:
        print(f"Avg FH goals: {sum(s['fh_goals'] for s in fh)/n:.2f}")
        print(f"Under 1.5 FH: {sum(1 for s in fh if s['fh_goals']<=1)/n*100:.1f}%")
    for s in fh:
        print(f"  {s['match']}: {s['fh_goals']} FH goals")
    for e in today:
        print(f"  {e['strStatus']} {e['strTime']} {e['strEvent']}")