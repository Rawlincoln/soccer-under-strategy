import json
import re
from pathlib import Path

text = Path(__file__).resolve().parent.parent / "data" / "betwinner_sample.html"
html = text.read_text(encoding="utf-8")
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
if not m:
    print("no __NEXT_DATA__")
    raise SystemExit(1)

data = json.loads(m.group(1))


def find_lists(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and len(v) >= 10:
                sample = v[0] if v else None
                print(f"LIST {path}{k} n={len(v)} sample_keys={list(sample.keys()) if isinstance(sample, dict) else type(sample)}")
            find_lists(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, x in enumerate(obj[:2]):
            find_lists(x, f"{path}[{i}].")


find_lists(data)

# dump pageProps if exists
props = data.get("props", {}).get("pageProps", {})
print("pageProps keys:", list(props.keys())[:20])
Path(__file__).resolve().parent.parent.joinpath("data", "betwinner_pageprops.json").write_text(
    json.dumps(props, indent=2)[:200000], encoding="utf-8",
)
print("wrote pageprops")