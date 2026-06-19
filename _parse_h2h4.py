import re
import requests

url = "https://www.soccerpunter.com/h2h/Ba-vs-Nadroga/18396/30793/"
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
text = r.text

idx = text.find("Head to Head Summary")
print("idx", idx)
print(text[idx : idx + 5000].replace("\n", " ")[:5000])