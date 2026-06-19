import re
import requests

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
html = r.text

print("has h2hSum", "h2hSum" in html)
print("has addRows", "addRows" in html)
print("has under 2.25", "under 2.25" in html.lower())

m = re.search(r'<table id="h2hSum".*?</table>', html, re.S)
print("h2hSum match", bool(m))
if m:
    print(m.group(0)[:600])

pie = re.search(r"addRows\(\[(.*?)\]\)", html, re.S)
print("pie match", bool(pie))
if pie:
    print(pie.group(1)[:300])

# try looser team comparison
for label in ["Matches under 2.25 goals", "Matches First Half Under 0.5"]:
    idx = html.find(label)
    print(label, "idx", idx)
    if idx >= 0:
        print(html[idx-120:idx+80])