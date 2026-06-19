import requests

url = "https://www.soccerpunter.com/h2h/United-States-vs-Australia/18571/18730/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
html = r.text
print("len", len(html))
for kw in ["United States", "h2hSum", "addRows", "under 2.25", "Access Denied", "captcha", "robot"]:
    print(kw, kw.lower() in html.lower() if kw != "United States" else "United States" in html)

# save snippet around title
idx = html.lower().find("<title>")
print("title", html[idx:idx+200] if idx >= 0 else "no title")