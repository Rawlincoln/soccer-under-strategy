import re
import requests

url = "https://www.soccerpunter.com/h2h/United-States-vs-Australia/18571/18730/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

# Parse stat rows: label in td followed by value td
rows = re.findall(
    r"<tr[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*class=\"?\"?>([^<]*)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*class=\"?\"?>([^<]*)</td>",
    text,
    re.I,
)
print("paired rows", len(rows))
for row in rows[:30]:
    print(row)

# Simpler: find stat label + next value
stats = {}
for m in re.finditer(
    r"<td[^>]*>([^<]{3,80})</td>\s*<td[^>]*class=\"?\"?>(\d+)</td>",
    text,
):
    label, val = m.group(1).strip(), m.group(2)
    if any(k in label.lower() for k in ("goal", "under", "over", "half", "btts", "clean", "score", "match")):
        stats[label] = int(val)

print("\nSTATS:")
for k, v in stats.items():
    print(f"  {k}: {v}")

# team ids from url
print("\nhome_id=18571 away_id=18730 match links:")
for m in re.findall(r"/match/(\d+)/([^\"]+)", text):
    if "United-States" in m[1] or "Australia" in m[1]:
        print(m)