import re
import requests

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

urls = [
    "https://www.soccerpunter.com/match/19712911/Ba-vs-Nadroga",
    "https://www.soccerpunter.com/head-to-head-stats/home/27323/18396/30793/Ba-vs-Nadroga-in-Fiji-FA-Cup-2026",
    "https://www.soccerpunter.com/live-odds/19712911/Ba-vs-Nadroga",
    "https://www.soccerpunter.com/h2h/Bohemians-vs-Dundalk/374/1311/",
]

for url in urls:
    r = requests.get(url, timeout=20, headers=headers)
    title_m = re.search(r"<title>([^<]+)</title>", r.text)
    title = title_m.group(1) if title_m else "?"
    print(url.split("/")[-2] + "/" + url.split("/")[-1], r.status_code, len(r.text), title[:60])
    for kw in ["h2hSum", "under 2.25", "Goals Scored", "addRows"]:
        if kw.lower() in r.text.lower():
            print("  has", kw)