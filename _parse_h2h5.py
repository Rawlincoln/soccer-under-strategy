import re
import requests

for slug, hid, aid in [
    ("Ba-vs-Nadroga", "18396", "30793"),
    ("United-States-vs-Australia", "18571", "18730"),
]:
    url = f"https://www.soccerpunter.com/h2h/{slug}/{hid}/{aid}/"
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    text = r.text

    print("===", slug, "===")
    # h2hSum table
    m = re.search(r'<table id="h2hSum".*?</table>', text, re.S)
    if m:
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S)
        for row in rows:
            cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if clean:
                print(" ", clean)

    # pie wins
    pie = re.search(r"data\.addRows\(\[\s*(.*?)\s*\]\)", text, re.S)
    if pie:
        print(" pie:", pie.group(1).replace("\n", " ")[:200])

    # team stat blocks - find tables after Team Statistics
    idx = text.find("Team Statistics")
    if idx >= 0:
        chunk = text[idx : idx + 12000]
        tables = re.findall(r"<table[^>]*>(.*?)</table>", chunk, re.S)
        for ti, table in enumerate(tables[:3]):
            print(f" team table {ti}")
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)[:15]:
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                if len(cells) >= 2:
                    label = re.sub(r"<[^>]+>", "", cells[0]).strip()
                    vals = [re.sub(r"<[^>]+>", "", c).strip() for c in cells[1:]]
                    if label and any(k in label.lower() for k in ("goal", "under", "over", "half", "match", "clean", "scored")):
                        print(f"   {label}: {vals}")
    print()