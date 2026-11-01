"""One-shot: note that bulky raw data moved off Google Drive. No orders."""
from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, LOCAL_STAMP, ONE_LEG_WATCH, ORDERS_STOP, RAW_DIR
from report_page_extras import CACHE_META, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML

PAGE = DRIVE_STAMP / "local_data_path_20261021.html"
ASKED = (
    "Google Drive is struggling with all the files. Paul does not need raw or pycache on Drive. "
    "Create local/paul_experiments/prediction_market_arb_exhaustive_20261017 and MOVE raw and "
    "pycache there. Wire processes to the new location. Wait until in-match vol/hedge report is "
    "done (it is done: inmatch_vol_hedge_20261021.html). Then wire and restart. HTML reports MUST "
    "stay under drive/ so ntfy and G: copies still work. Leave a tiny README in drive/.../raw/. "
    "Do not turn orders on."
)
PLAIN = (
    "The bulky quote history, order logs, snapshots, balances, leftover-watch files, and Python "
    "cache were filling Google Drive and making it slow. Those files now live only on this PC. "
    "The web pages you actually open (job status, orders, opportunities, research reports) still "
    "sit in the Drive folder, so they still sync and still ping the phone. The programs that watch "
    "live games were pointed at the new folder and restarted. New pair orders were not turned on."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def main() -> Path:
    if ORDERS_STOP.exists():
        latch_note = str(ORDERS_STOP)
        latch_count = "1 file"
        latch_size = f"{ORDERS_STOP.stat().st_size / 1048576:.4f}".rstrip("0").rstrip(".")
    else:
        latch_note = f"{ORDERS_STOP} (not present; latch is off)"
        latch_count = "absent"
        latch_size = ""
    rows = [
        (
            "raw/ folder (price memory, orders, snapshots, balances, logs, locks)",
            "977 files",
            "2994.8",
            str(RAW_DIR),
        ),
        ("price_memory.jsonl", "1 file", "1753.1", str(RAW_DIR / "price_memory.jsonl")),
        ("live_supervisor.log + overnight_scan.log", "2 files", "35.7", str(RAW_DIR)),
        ("orders.jsonl + order_io.jsonl", "2 files", "2.9", str(RAW_DIR)),
        (
            "stamp __pycache__ (overnight_scan / build_scan)",
            "3 files",
            "0.2",
            str(LOCAL_STAMP / "__pycache__"),
        ),
        ("one_leg_watch.json (leftover watch)", "1 file", "0.0008", str(ONE_LEG_WATCH)),
        ("orders_stopped.json (order-stop latch)", latch_count, latch_size, latch_note),
    ]
    head = "".join(
        [
            th("What moved", "text"),
            th("Count", "text"),
            th("Size (MB)", "num"),
            th("Now lives at", "text"),
        ]
    )
    body = []
    for item, count, size, where in rows:
        body.append(
            "<tr>"
            + f"<td>{esc(item)}</td>"
            + f"<td>{esc(count)}</td>"
            + f"<td>{esc(size)}</td>"
            + f"<td>{esc(where)}</td>"
            + "</tr>"
        )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Raw data moved off Google Drive</title>
<style>
body {{ margin: 0; padding: 16px 16px 48px; font: 16px/1.45 system-ui, Segoe UI, sans-serif; color: #0f172a; background: #fff; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 1.4rem 0 0.4rem; }}
p {{ margin: 0.4rem 0 0.7rem; }}
.callout {{ border-left: 4px solid #1d4ed8; background: #f8fafc; padding: 10px 12px; margin: 0 0 12px; }}
.callout h2 {{ margin: 0 0 6px; font-size: 1rem; }}
code {{ font-size: 0.92em; word-break: break-all; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Raw data moved off Google Drive</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<p>HTML reports stay here: <code>{esc(DRIVE_STAMP)}</code>.</p>
<p>Raw data now lives here: <code>{esc(RAW_DIR)}</code>.</p>
<p>Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
</div>
<h2>Latch and leftover watch</h2>
<p>The leftover-watch file is <code>{esc(ONE_LEG_WATCH)}</code>.</p>
<p>The leftover watch resumed from the moved <code>one_leg_watch.json</code>. After restart it wrote the order-stop latch at 09:31:25 Eastern Time (reason: one leg filled and the other missed). New pair orders stay off. This job did not run the orders-on bat.</p>
<h2>What stayed on Drive</h2>
<p>Every <code>.html</code> page in this stamp, including <code>job_status.html</code>. The old <code>raw/</code> folder now has a short README pointing at the local path. If Google Drive puts a tiny leftover file back into <code>drive/.../raw</code>, that is a cloud restore stub, not the live tape. The live tape is the local copy.</p>
<p>See also <a href="job_status.html">job_status.html</a>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    print(PAGE)
    return PAGE


if __name__ == "__main__":
    main()
