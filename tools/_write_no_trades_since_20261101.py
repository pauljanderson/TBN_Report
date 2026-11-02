"""Why no kitchen trades since 2026-11-01 ~08:20 ET.

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
OUT = STAMP / "no_trades_since_20261101.html"

PAUL = (
    "it looks like we haven't made any trades since yesterday at 8AM? "
    "can you investigate as to what is going on?"
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
<title>No trades since 2026-11-01 08:20 ET</title>
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
th, td {{ border: 1px solid #d8dee9; padding: 6px 8px; }}
thead th {{ background: #f8fafc; }}
</style>
</head>
<body>
<h1>No trades since yesterday ~8 AM ET</h1>
<p class="tiny">Written {esc(now)}. Stamp prediction_market_arb_exhaustive_20261017.
Did not sell. Did not start a second B. Did not leftover-GTC. Live reload still needed on the kitchen PC after this code lands.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{esc(PAUL)}</p>
<h2>In plain English</h2>
<p>Last kitchen fill on the dashboard tape is <strong>2026-11-01 08:20:24 ET</strong>
(Gima vs Peniston, Lock A). Bots are still running — dashboard refreshed
{esc(now.split(' ')[0])} morning — but Lock A has been refusing every new pair because
the send gate thinks it already has <strong>331 open locks</strong> while max is 10.
Positions / Open now A is <strong>0</strong> (Kalshi and Polymarket positions GETs are empty).
Those 331 are house-tape ghosts from the GTC-merge stub that stopped counting venue qty.
B/E/F/G are on; today (Nov 2 ET) scoreboard is still 0 sent. B last action stuck at
Nov 1 09:22 (“no trusted clock”); E last action Nov 1 03:01 — reload those after A.</p>
</div>

<div class="bad">
<h2>Root cause (Lock A)</h2>
<ul>
<li>Last skip: <code>Already have 331 open lock pair(s); max_open_locks=10.</code> (2026-11-02 09:43 ET)</li>
<li>Open now / Positions overlay: <strong>0</strong> games, $0 at risk</li>
<li>summary.json ~10:05 ET: Kalshi positions n=0 HTTP 200; Poly n=0 HTTP 200</li>
<li>Mechanism: after the GTC second-leg merge, <code>open_lock_keys()</code> counted filled/one_leg
rows on <code>orders.jsonl</code> forever and <strong>ignored</strong> the venue overlay. Settled tickets never
cleared the cap. Same class bug as <a href="lock_ghost_open_cap_20261025.html">lock_ghost_open_cap_20261025</a>.</li>
</ul>
</div>

<div class="warn">
<h2>Why B / E also quiet</h2>
<ul>
<li>Last fills: E ~03:01 ET Nov 1; B ~01:43 ET Nov 1; then A at 08:20; nothing after.</li>
<li>Nov 2 Today scoreboard: all systems 0 sent / 0 filled.</li>
<li>F and G last_action update this morning (alive). B last_action frozen ~25h; E ~31h — treat as hung/stale watches; reload B and E on the kitchen PC after pulling this fix.</li>
<li>C is intentionally off. D last_action still Oct 24 — also stale; reload if you want D live.</li>
</ul>
</div>

<div class="ok">
<h2>Fix shipping</h2>
<ol>
<li>Restore venue-overlay send cap in <code>live_lock_orders.open_lock_keys</code> (default overlay=True).</li>
<li>House tape still available via <code>overlay=False</code> for diagnostics.</li>
<li>Unit tests: 331 house ghosts + empty venue books → send allowed; only venue-held qty counts.</li>
<li>job_status open line shows venue / cap and notes house-tape ghosts when they diverge.</li>
</ol>
</div>

<div class="callout">
<h2>Prevention (class-level)</h2>
<ul>
<li>Send cap must match Positions / Open now A (venue qty), never raw filled rows.</li>
<li>Regression test locks the Nov 2 shape (house≫venue → send allowed).</li>
<li>After deploy on the kitchen PC: <code>python tools/prediction_job_control.py reload-lock</code>,
then restart B/E (and D if wanted). Confirm last skip is not “Already have N open…”
while Open now A is 0.</li>
</ul>
</div>

<p class="tiny">Sources: dashboard.html / orders_performance.html / summary.json (Drive, ~2026-11-02 10:05 ET).</p>
</body>
</html>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
