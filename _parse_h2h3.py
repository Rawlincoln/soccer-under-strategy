import re
import requests

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text
print("len", len(text))

for title in re.findall(r"<h[234][^>]*>([^<]+)</h[234]>", text):
    tl = title.lower()
    if any(k in tl for k in ("stat", "h2h", "head", "team", "goal", "form", "overall")):
        print("HEADING:", title)

# all label/value pairs in page
pairs = re.findall(
    r"<td[^>]*>([^<]{3,120})</td>\s*<td[^>]*class=\"?\"?>([^<]*)</td>",
    text,
    re.I,
)
print("pairs", len(pairs))
for label, val in pairs:
    ll = label.lower()
    if any(k in ll for k in ("goal", "under", "over", "half", "btts", "clean", "match", "scored", "draw")):
        print(f"  {label.strip()}: {val.strip()}")

# h2h history results
results = re.findall(r'title="([^"]+\d+\s*-\s*\d+)"', text)
print("form results", results[:15])