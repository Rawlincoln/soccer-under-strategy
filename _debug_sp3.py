import re
import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
})

home = session.get("https://www.soccerpunter.com/", timeout=20)
print("home", home.status_code, len(home.text))

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = session.get(url, timeout=20, headers={"Referer": "https://www.soccerpunter.com/"})
html = r.text
print("h2h", r.status_code, len(html), "Nadroga" in html, "h2hSum" in html)
if "h2hSum" in html:
    m = re.search(r'<table id="h2hSum".*?</table>', html, re.S)
    print(m.group(0)[:400] if m else "no table")