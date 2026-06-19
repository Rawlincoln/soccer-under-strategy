import re
import requests

url = "https://www.soccerpunter.com/h2h/United-States-vs-Australia/18571/18730/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

# Section blocks by heading
sections = re.split(r"<h[234][^>]*>", text)
for i, sec in enumerate(sections):
    title_m = re.match(r"([^<]+)</h[234]>", sec)
    if not title_m:
        continue
    title = title_m.group(1).strip()
    if not any(k in title.lower() for k in ("stat", "h2h", "head", "team", "goal", "form")):
        continue
    body = sec[title_m.end() : title_m.end() + 3000]
    stats = re.findall(
        r"<td[^>]*>([^<]{3,100})</td>\s*<td[^>]*class=\"?\"?>([^<]*)</td>",
        body,
        re.I,
    )
    if stats:
        print("===", title, "===")
        for label, val in stats[:20]:
            print(f"  {label.strip()}: {val.strip()}")
        print()