import requests
from soccerpunter_stats import _parse_h2h_page, _parse_h2h_pie, _parse_team_comparison, _parse_h2h_sum

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
html = r.text
print("pie", _parse_h2h_pie(html))
print("sum", _parse_h2h_sum(html))
print("comp", _parse_team_comparison(html))
print("full", _parse_h2h_page(html, "Ba", "Nadroga"))

# feed debug
r2 = requests.get("https://www.soccerpunter.com/ls_feed.php", timeout=20, headers={"User-Agent": "Mozilla/5.0"})
print("feed status", r2.status_code, "ctype", r2.headers.get("content-type"), "start", r2.text[:80])