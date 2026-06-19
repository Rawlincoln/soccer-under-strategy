import re
import requests

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

# Find blocks with team names as headers
for m in re.finditer(r"Team Statistics in ([^<]+)</h2>(.*?)(?=<h2|<h3|$)", text, re.S):
    league = m.group(1)
    body = m.group(2)
    print("LEAGUE", league)
    # two team columns?
    headers = re.findall(r"<h3[^>]*>([^<]+)</h3>", body)
    print(" h3", headers)
    for table in re.findall(r"<table[^>]*class=\"competitionRanking\"[^>]*>(.*?)</table>", body, re.S):
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
            clean = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]
            if len(clean) >= 2 and any(k in clean[0].lower() for k in ("goal", "under", "over", "half", "match", "clean")):
                print("  ", clean)

# direct h2h meetings goals - past results
idx = text.find("Past H2H Results")
if idx >= 0:
    chunk = text[idx : idx + 8000]
    scores = re.findall(r'title="([^"]*\d+\s*-\s*\d+)"', chunk)
    h2h_only = [s for s in scores if "Ba" in s and "Nadroga" in s]
    print("H2H meetings", h2h_only[:10])