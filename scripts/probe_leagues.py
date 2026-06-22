"""Probe football-data.co.uk league CSV availability."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
cfg = json.loads((ROOT / "data" / "leagues.json").read_text(encoding="utf-8"))

ok, fail = [], []
for lg in cfg["leagues"]:
    lid = lg["id"]
    if lg["category"] == "main":
        url = lg["url"].format("2425")
    else:
        url = lg["url"]
    try:
        df = pd.read_csv(url, on_bad_lines="skip", nrows=5)
        rows = len(df)
        cols = "HomeTeam" in df.columns or "Home" in df.columns
        if rows and cols:
            ok.append((lid, rows, url))
        else:
            fail.append((lid, "empty/bad cols", url))
    except Exception as e:
        fail.append((lid, str(e)[:60], url))

print(f"OK: {len(ok)}  FAIL: {len(fail)}")
for x in fail:
    print("FAIL", x[0], x[1])
for x in ok[:5]:
    print("OK", x[0])