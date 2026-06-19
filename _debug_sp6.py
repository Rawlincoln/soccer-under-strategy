import re
import requests

headers = {"User-Agent": "Mozilla/5.0"}
for url in [
    "https://www.soccerpunter.com/team/Ba/18396/",
    "https://www.soccerpunter.com/team/United-States/18571/",
    "https://www.soccerpunter.com/soccer-statistics/matches_today",
]:
    r = requests.get(url, timeout=30, headers=headers)
    title = re.search(r"<title>([^<]+)</title>", r.text)
    print(url.split("/")[-2] or url[-20:], len(r.text), (title.group(1) if title else "")[:50])
    if "matches_today" in url:
        # find predict links with stats
        blocks = re.findall(r"Bohemians.*?Dundalk.*?</tr>", r.text, re.S | re.I)
        print(" bohemians blocks", len(blocks))
        idx = r.text.find("Bohemians")
        if idx >= 0:
            print(r.text[idx:idx+800].replace("\n", " ")[:800])