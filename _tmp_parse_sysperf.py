import re
from pathlib import Path

p = Path(r"C:\Users\songg\Downloads\stockresearch\docs\system_performance.html")
html = p.read_text(encoding="utf-8", errors="replace")

# Overview table rows
print("=== OVERVIEW TABLE ===")
m = re.search(r"<section id=\"systems\".*?</section>", html, re.S)
if m:
    rows = re.findall(
        r"<tr><td><a href='#(\w+)'>([^<]+)</a></td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>",
        m.group(0),
    )
    for r in rows:
        print(r)

print("\n=== SECTIONS ===")
for sec in re.finditer(
    r"<section id='([^']+)'><h2>([^<]+)</h2><p class='muted'>(.*?)</p>(.*?)</section>",
    html,
    re.S,
):
    sid, name, muted, body = sec.groups()
    avg = re.search(r"<th>Avg days</th>.*?<tr><td>[^<]*</td><td>[^<]*</td><td>[^<]*</td><td>[^<]*</td><td>[^<]*</td><td>([^<]*)</td>", body, re.S)
    ann = re.search(r"Annualized return</span><strong>([^<]+)</strong>", body)
    med = re.search(r"Median / P90 hold</span><strong>([^<]+)</strong>", body)
    trades = re.search(r"<th>Trades</th>.*?<tr><td>([^<]*)</td>", body, re.S)
    print(f"{sid}|{name}|ann={ann.group(1) if ann else '?'}|avg={avg.group(1) if avg else '?'}|med={med.group(1) if med else '?'}|trades={trades.group(1) if trades else '?'}|src={muted[:180]}")

print("\n=== SOURCES ===")
src = re.search(r"<details><summary>Exact sources.*?</details>", html, re.S)
if src:
    for li in re.findall(r"<li><strong>([^<]+):</strong>\s*(.*?)</li>", src.group(0)):
        print(li[0], "->", re.sub(r"<[^>]+>", "", li[1])[:250])
