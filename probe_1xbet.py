import json
import requests

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://1xbet.com/en/live/football",
})
BASE = "https://1xbet.com/web-api/LiveFeed"

r = s.get(f"{BASE}/Get1x2_VZip", params={"sports": 1, "count": 100, "lng": "en", "mode": 4, "country": 1, "getEmpty": "true"}, timeout=20)
matches = [m for m in (r.json().get("Value") or []) if (m.get("SC") or {}).get("CP") == 1]

print(f"First half matches: {len(matches)}")
for m in matches[:8]:
    sc = m.get("SC") or {}
    ps = sc.get("PS") or []
    fh = next((p["Value"] for p in ps if p.get("Key") == 1 or "1st" in (p.get("Value", {}).get("NF") or "")), {})
    fh_g = int(fh.get("S1") or 0) + int(fh.get("S2") or 0)
    gid = m["I"]
    print(f"\n{m['O1']} vs {m['O2']} | FH goals={fh_g} | {m.get('L')}")
    r2 = s.get(f"{BASE}/GetGameZip", params={
        "id": gid, "lng": "en", "cfview": 0, "isSubGames": "true",
        "GroupEvents": "true", "countevents": 500, "grMode": 2,
    }, timeout=20)
    g = r2.json().get("Value") or {}
    # Sub-games for 1st half
    for sg in (g.get("SG") or [])[:5]:
        print("  SG:", sg.get("PN"), sg.get("TG"), sg.get("I"))
    for e in (g.get("E") or []):
        t, p, c, gn = e.get("T"), e.get("P"), e.get("C"), e.get("G")
        if t in (9, 10, 11, 12) or (p is not None and float(p) < 3):
            print(f"  E: T={t} P={p} C={c} G={gn}")
    for ge in (g.get("GE") or [])[:3]:
        print("  GE group:", ge.get("G"), ge.get("GS"))
        for row in (ge.get("E") or [])[:2]:
            for cell in (row or [])[:4]:
                print(f"    T={cell.get('T')} P={cell.get('P')} C={cell.get('C')} G={cell.get('G')}")