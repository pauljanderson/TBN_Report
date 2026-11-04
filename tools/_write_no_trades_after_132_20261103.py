"""Why no kitchen trades after 2026-11-03 01:32 ET.

Display / autopsy only. Does not place orders. Does not start a second B.
Does not sell. Does not clear orders.jsonl.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
try:
    from prediction_paths import DRIVE_STAMP as STAMP
except Exception:
    STAMP = ROOT / "drive" / "paul_experiments" / "prediction_market_arb_exhaustive_20261017"

ET = ZoneInfo("America/New_York")
OUT = STAMP / "no_trades_after_132_20261103.html"

PAUL = (
    "there were NO trades at all after 1:32 AM this morning. "
    "can you do a deep dive and find out why? I know one thing we changed recently "
    "was gemini calls. i can't imagine that had anything to do with it, but I would "
    "like to know why NO tennis crossovers happened. were they all above the cap of "
    "1.05? why did we not buy any Tennis T0 dogs? or any tennis spreads? "
    "0 soccer total bets. 0 T0 spreads (on except football) why?"
)


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def main() -> None:
    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    STAMP.mkdir(parents=True, exist_ok=True)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>No trades after 2026-11-03 01:32 ET</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px 16px 64px; line-height: 1.45; color: #1a1a1a; max-width: 980px; }}
h1, h2 {{ font-family: system-ui, sans-serif; }}
.callout {{ background: #f4f7fb; border: 1px solid #d8dee9; padding: 12px 16px; margin: 16px 0; }}
.bad {{ background: #fdecec; border: 1px solid #e8b4b4; padding: 12px 16px; margin: 16px 0; }}
.ok {{ background: #ecfdf3; border: 1px solid #86efac; padding: 12px 16px; margin: 16px 0; }}
.warn {{ background: #fff7ed; border: 1px solid #fdba74; padding: 12px 16px; margin: 16px 0; }}
code {{ font-size: 0.92em; }}
.tiny {{ color: #64748b; font-size: 0.9rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #d8dee9; padding: 6px 8px; text-align: left; }}
thead th {{ background: #f8fafc; }}
</style>
</head>
<body>
<h1>No trades after 1:32 AM ET</h1>
<p class="tiny">Written {esc(now)}. Stamp prediction_market_arb_exhaustive_20261017.
Did not sell. Did not start a second B. Live reload still needed on the kitchen PC
after this code lands (supervisor will then auto-reload STALE watches).</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(PAUL)}</p>
<h2>In plain English</h2>
<p>Last <strong>filled</strong> tickets today were Lock A at
<strong>2026-11-03 01:32:15 ET</strong> (Gibson vs Oliynykova). After that: zero
fills on A–G. Today scoreboard at ~21:13 ET: A sent/filled 6/−$0.60; B/C/D/E/F/G
all 0. Gemini quote-only did <em>not</em> cause this — those A fills were
Kalshi + Polymarket after Gemini was soft-disabled.</p>
</div>

<div class="bad">
<h2>1. How did this happen?</h2>
<table>
<thead><tr><th>System</th><th>What the tape / job_status show</th><th>Root mechanism</th></tr></thead>
<tbody>
<tr>
<td>A Lock gap</td>
<td>Last fills 01:15 / 01:28 / 01:32 ET. Then Yastremska vs Sonmez claim+skips at 01:33–01:39. Last skip line still Nov 2 23:25 same-direction.</td>
<td>Still probing after 01:32; no more under-cap locks posted. Not a full bot death.</td>
</tr>
<tr>
<td>B Tennis crossover</td>
<td>State updated frozen <strong>01:40:37 ET</strong>. Last log
<code>01:09:22 strategy b loop PermissionError</code>. Last skip:
<em>no trusted clock</em> (Sara Yoshida vs Xi Luo) — <strong>not</strong>
<code>t0_allin_c_over_105</code>. PID 55936 still “UP”.</td>
<td>Zombie: PID alive, watch heartbeat dead after PermissionError / hung tick.
Not “all above 1.05.”</td>
</tr>
<tr>
<td>E Tennis T0 dog</td>
<td>Last fill / last_send <strong>Nov 1 03:01</strong>. job_status showed that
stamp all day (preferred last_send over updated_at).</td>
<td>Display hid heartbeat; E was never proven live after the Nov 1
ORDERS_STOP AttributeError incident. Treat as hung/stale until reload.</td>
</tr>
<tr>
<td>D T0 spreads</td>
<td>Last action <strong>Oct 24</strong>. NFL intentionally skipped; CFB/others
should still send — they did not.</td>
<td>Same zombie / never-reloaded class. Not “except football” working.</td>
</tr>
<tr>
<td>F Tennis spread</td>
<td>Alive (updated_at ticking). 340 Nov 3 rows, <strong>all</strong>
never posted (claim+skip). Live note: no Yes in [0.20, 0.50).</td>
<td>Process up; band / recheck / size skips — zero posts inception on this tape.</td>
</tr>
<tr>
<td>G Soccer total</td>
<td>Alive; 0 clusters ever on ledger/clusters.</td>
<td>No soccer Points Total T0 in band hit the claim path today.</td>
</tr>
<tr>
<td>C CFB favorite</td>
<td>Off.</td>
<td>Intentional.</td>
</tr>
</tbody>
</table>
</div>

<div class="warn">
<h2>Gemini?</h2>
<p>Soft-disable (quote-only) landed Nov 2 morning UTC. It only blocks Gemini as a
<strong>send</strong> venue; Kalshi / Polymarket / Novig (when enabled) still send.
Today’s A fills prove the kitchen was still wiring non-Gemini legs after that change.
Gemini was not the reason B/E/D went quiet.</p>
</div>

<div class="ok">
<h2>2. What we are fixing</h2>
<ol>
<li><strong>Heartbeat truth:</strong> job_status Last action uses watch
<code>updated_at</code>, not a days-old <code>last_send</code>.</li>
<li><strong>STALE badge + supervisor reload:</strong> on + PID up +
<code>updated_at</code> &gt; 5 minutes → mark STALE and
<code>reload_system</code> (never a second B).</li>
<li><strong>PermissionError retries</strong> on atomic watch JSON replace for B and C–G.</li>
<li>Louder loop logs: <code>PermissionError: …</code> not bare type name.</li>
</ol>
<p>On the kitchen PC after pull: confirm job_status no longer shows B frozen at 01:40;
if supervisor has not looped yet,
<code>python tools/prediction_job_control.py systems</code> / reload B D E.</p>
</div>

<div class="callout">
<h2>3. So this (and anything like it) never happens again</h2>
<ul>
<li>Class bug = <strong>PID-up / brain-dead</strong> on any live bot (B/C/D/E/F/G), not
Kalshi-only.</li>
<li>Guard: stale <code>updated_at</code> while PID listed → auto-reload.</li>
<li>Tests: heartbeat prefers <code>updated_at</code>; stale reload hook;
JSON dump retries PermissionError.</li>
<li>job_status paints STALE in red so a frozen 01:40 cannot look “UP and fine.”</li>
</ul>
</div>

<p class="tiny">Sources: Drive dashboard.html / job_status.html / clusters.json /
summary.json (~2026-11-03 21:13–21:33 ET).</p>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
