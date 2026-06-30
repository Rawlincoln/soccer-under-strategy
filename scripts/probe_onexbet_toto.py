import json
import requests

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://1xbet.co.ke/en/toto/fifteen",
    "X-Requested-With": "XMLHttpRequest",
})

site = "https://1xbet.co.ke"
page = session.get(f"{site}/en/toto/fifteen", timeout=25)
print("page", page.status_code, "cookies", list(session.cookies.keys()))

for path in ["/web-api/toto15", "/web-api/toto/fifteen", "/web-api/toto/active"]:
    for method in ["get", "post"]:
        url = site + path
        fn = getattr(session, method)
        for payload in [None, {"lng": "en"}, {"lng": "en", "country": 1}, {"type": 15}]:
            r = fn(url, json=payload, timeout=20) if method == "post" else fn(url, params=payload, timeout=20)
            if r.status_code not in (204, 404) or (r.text and len(r.text) > 5):
                print(method.upper(), path, payload, r.status_code, len(r.text), r.text[:250])