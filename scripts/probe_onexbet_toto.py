import json
import requests

site = "https://1xbet.co.ke"
headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": f"{site}/en/toto/fifteen",
}

jackpots = requests.get(
    f"{site}/toto-api-v2/web/v1/jackpots",
    headers=headers,
    params={"curISO": "KES", "lng": "en"},
    timeout=20,
).json()
print("jackpots", json.dumps(jackpots, indent=2))

for item in jackpots.get("JackpotsList", []):
    tid = item["TotoTypeId"]
    r = requests.get(
        f"{site}/toto-api-v2/web/v1/toto/{tid}/draws/active",
        headers=headers,
        params={"lng": "en", "curISO": "KES"},
        timeout=20,
    )
    if r.status_code != 200:
        print("type", tid, r.status_code)
        continue
    data = r.json()
    games = sum(len(c.get("GamesList") or []) for c in data.get("ChampsWithGames") or [])
    print(f"type {tid}: draw {data.get('TiragNumber')} games {games} pool {data.get('Pool')} jp {data.get('Jackpot')}")
    if games:
        g = (data["ChampsWithGames"][0]["GamesList"] or [])[0]
        print("  sample", g.get("Opponent1Name"), "vs", g.get("Opponent2Name"), g.get("BetsPercents"))