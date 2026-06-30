"""Probe jackpot sources."""
import re
import requests

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
    "Accept": "text/html,application/json",
})

r = s.get("https://www.betika.com/en-ke/jackpot", timeout=25)
print("betika", r.status_code, len(r.text))
if "__NEXT_DATA__" in r.text:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if m:
        import json
        data = json.loads(m.group(1))
        print("next keys", data.get("props", {}).keys())
        print(str(data)[:2000])

r2 = s.get("https://www.mozzartbet.co.ke/jackpot", timeout=25)
print("mozzart", r2.status_code, len(r2.text))
for pat in ["jackpot", "Jackpot", "fixture", "homeTeam"]:
    if pat in r2.text:
        print("  has", pat)

r3 = s.get("https://betwinner360.com/sportpesa-mega-jackpot-predictions/", timeout=25)
# extract table rows with team names from HTML
teams = re.findall(r'class="[^"]*team[^"]*"[^>]*>([^<]+)', r3.text, re.I)
print("betwinner teams sample", teams[:20])