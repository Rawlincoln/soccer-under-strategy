import re
import requests
from html.parser import HTMLParser

url = "https://www.soccerpunter.com/h2h/United-States-vs-Australia/18571/18730/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

# Extract table rows with under/over context
for section in re.findall(r"(?is)(under|over).{0,200}?</table>", text):
    if "goal" in section.lower():
        print(section[:500])
        print("---")

# Find percentage stats in H2H
for pat in [
    r"(\d+(?:\.\d+)?%?)\s*(?:of\s+)?(?:matches|games|times).*?(?:under|over)",
    r"(Under|Over)\s*([\d.]+)\s*Goals?.*?</td>\s*<td[^>]*>([^<]+)",
    r"<td[^>]*>([^<]*under[^<]*)</td>",
    r"<td[^>]*>([^<]*over[^<]*)</td>",
]:
    ms = re.findall(pat, text, re.I)
    if ms:
        print("PATTERN", pat[:50], "matches", len(ms))
        for m in ms[:10]:
            print(" ", m)

# headings
for h in re.findall(r"<h[234][^>]*>([^<]+)</h[234]>", text):
    hl = h.strip().lower()
    if any(k in hl for k in ("h2h", "under", "over", "goal", "stat", "form", "total")):
        print("HEADING:", h.strip())

# save snippet around over 2.25
idx = text.lower().find("over 2.25")
if idx >= 0:
    print("CONTEXT:", text[idx - 400 : idx + 400].replace("\n", " "))