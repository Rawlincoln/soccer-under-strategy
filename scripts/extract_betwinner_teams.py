import re
from pathlib import Path

html = Path(__file__).resolve().parent.parent / "data" / "betwinner_sample.html"
text = html.read_text(encoding="utf-8")

# Team names in jackpot rows: <span class="font-bold">Home</span> or <span class="">Home</span>
team_spans = re.findall(
    r'<div class="flex flex-1 justify-between[^"]*"><span class="(?:font-bold)?">([^<]+)</span>',
    text,
)
print("teams found", len(team_spans))
for i in range(0, min(len(team_spans), 34), 2):
    if i + 1 < len(team_spans):
        print(i // 2 + 1, team_spans[i], "vs", team_spans[i + 1])

# League codes near rows
leagues = re.findall(r'<span class="[^"]*text-\[10px\][^"]*">([A-Z0-9]{2,6})</span>', text)
print("leagues", leagues[:20])