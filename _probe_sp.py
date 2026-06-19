import re
import requests

headers = {"User-Agent": "Mozilla/5.0"}

for url in [
    "https://www.soccerpunter.com/h2h/United-States-vs-Australia/18571/18730/",
    "https://www.soccerpunter.com/livescore/",
    "https://www.soccerpunter.com/soccer-statistics/matches_today",
]:
    print("===", url)
    r = requests.get(url, timeout=20, headers=headers)
    text = r.text
    print("status", r.status_code, "len", len(text))

    for kw in ["Under 1.5", "Under 2.5", "Over/Under", "match_id", "fixture", "sportmonks", "api/"]:
        if kw.lower() in text.lower():
            print("  has:", kw)

    # table headers near under/over
    for m in re.finditer(r"(?i)(under|over).{0,40}goals", text):
        snippet = text[m.start() : m.start() + 80].replace("\n", " ")
        print("  snippet:", snippet[:80])

    apis = set(re.findall(r'["\'](/[^"\']{3,80})["\']', text))
    for a in sorted(apis):
        low = a.lower()
        if any(x in low for x in ("api", "ajax", "live", "score", "match", "feed")):
            print("  path:", a)

    urls = set(re.findall(r"https?://[a-zA-Z0-9./_?=&%-]+", text))
    for u in sorted(urls):
        low = u.lower()
        if any(x in low for x in ("api", "live", "score", "feed", "socket", "ajax")):
            print("  url:", u[:140])

    print()