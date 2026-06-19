import re
import requests

url = "https://www.soccerpunter.com/soccer-statistics/matches_today"
r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

# h2h links: /h2h/Home-vs-Away/home_id/away_id/
links = re.findall(r'/h2h/([^/]+)/(\d+)/(\d+)/', text)
print("h2h links", len(links))
for link in links[:5]:
    print(link)

# match links with ids
matches = re.findall(r'/match/(\d+)/([^"/]+)', text)
print("match links", len(set(matches)))
for m in list(set(matches))[:5]:
    print(m)