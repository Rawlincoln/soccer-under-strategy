"""Probe live match URL shape on 1xbet.co.ke."""
import re
import requests

API = "https://1xbet.com/web-api/LiveFeed/Get1x2_VZip"
headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/131 Mobile Safari/537.36",
    "Referer": "https://1xbet.co.ke/en/live/football",
}
r = requests.get(API, params={"sports": 1, "count": 5, "lng": "en", "mode": 4, "country": 1}, headers=headers, timeout=25)
data = r.json()
for raw in (data.get("Value") or [])[:3]:
    gid = raw["I"]
    lid = raw.get("LI", 0)
    home = raw.get("O1", "")
    away = raw.get("O2", "")
    for path in [
        f"https://1xbet.co.ke/en/live/football/{lid}/{gid}",
        f"https://1xbet.co.ke/en/live/football/{gid}",
        f"https://1xbet.co.ke/en/line/football/{lid}/{gid}",
        f"https://1xbet.co.ke/en/mobile/live/football/{lid}/{gid}",
    ]:
        try:
            resp = requests.get(
                path,
                headers=headers,
                timeout=20,
                allow_redirects=True,
            )
            final = resp.url
            ok = resp.status_code == 200
            print(f"{home} vs {away}")
            print(f"  try {path}")
            print(f"  -> {resp.status_code} final={final} len={len(resp.text)}")
            if ok:
                for pat in [r"canonical\" href=\"([^\"]+)\"", r"og:url\" content=\"([^\"]+)\""]:
                    m = re.search(pat, resp.text)
                    if m:
                        print(f"  meta {m.group(1)}")
        except Exception as e:
            print(path, e)
    print()