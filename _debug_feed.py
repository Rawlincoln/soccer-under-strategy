import json
import requests

r = requests.get("https://www.soccerpunter.com/ls_feed.php", timeout=20, headers={"User-Agent": "Mozilla/5.0"})
data = r.json()
m = data["matches"]["full"][0]
print("keys", sorted(m.keys()))
print(json.dumps(m, indent=2)[:2000])

# any match with stats?
for match in data["matches"]["full"][:50]:
    if match.get("hts_A") is not None:
        print("sample live", match.get("ta_name"), "vs", match.get("tb_name"), match.get("status"), match.get("hts_A"), match.get("score_A"))
        break