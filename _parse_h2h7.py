import re
import requests

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

for label in ["Matches under 2.25", "Matches First Half Under 0.5", "Clean sheets", "Average goals scored"]:
    idx = text.find(label)
    if idx < 0:
        continue
    print("===", label, "===")
    print(text[idx - 800 : idx + 400].replace("\n", " "))
    print()