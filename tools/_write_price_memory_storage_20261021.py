"""Note: split price_memory.jsonl into dated sport shards. No orders."""
from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, RAW_DIR
from price_memory import (
    CSV_DIR,
    CUTOFF_PATH,
    HISTORY,
    HISTORY_DIR,
    load_cutoff,
    list_tick_files,
)
from report_page_extras import CACHE_META, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML

PAGE = DRIVE_STAMP / "price_memory_storage_20261021.html"
ET = ZoneInfo("America/New_York")
ASKED = (
    "Change-ticks for every live game will grow price_memory.jsonl. Might we need to split "
    "the memory file up? Or store in a database? Or a CSV or different format for easier reading?"
)
PLAIN = (
    "The live price tape was one 1.87 GB text file. Every later look-up of a single match "
    "had to walk the whole file. New quotes now go into a small file per Eastern calendar "
    "day and sport on this PC only, not Google Drive. The old 1.87 GB file is frozen and "
    "kept as history. Excel can open a last-two-day CSV, or a one-match CSV dump. "
    "Same-price repeats are still stored only after 20 seconds. This does not send orders."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def mb(n: int | float) -> str:
    return f"{n / 1_000_000:.2f}"


def gb(n: int | float) -> str:
    return f"{n / 1_000_000_000:.3f}"


def main() -> Path:
    now = datetime.now(ET)
    now_text = now.strftime("%Y-%m-%d %I:%M:%S %p") + " Eastern Time"
    archive_bytes = HISTORY.stat().st_size if HISTORY.is_file() else 0
    cutoff = load_cutoff()
    files = list_tick_files()
    shard_bytes = sum(int(row["bytes"]) for row in files if row.get("kind") == "shard jsonl")
    csv_bytes = sum(
        int(row["bytes"]) for row in files if str(row.get("kind") or "").endswith("csv")
    )
    head = "".join(
        [
            th("Kind", "text"),
            th("Path", "text"),
            th("MB", "num"),
            th("Bytes", "num"),
            th("Written (ET)", "text"),
        ]
    )
    body = "".join(
        "<tr>"
        f"<td>{esc(row.get('kind'))}</td>"
        f"<td>{esc(row.get('path'))}</td>"
        f"<td>{esc(mb(int(row.get('bytes') or 0)))}</td>"
        f"<td>{esc(int(row.get('bytes') or 0))}</td>"
        f"<td>{esc(row.get('mtime_et'))}</td>"
        "</tr>"
        for row in files
    )
    if not body:
        body = "<tr><td>No tick files found.</td><td></td><td></td><td></td><td></td></tr>"
    today = now.strftime("%Y-%m-%d")
    cutoff_et = cutoff.get("cutoff_et") or "(written on first new tick after the split)"
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>price_memory storage</title>
{CACHE_META}
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: none; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
.later {{ background: #fffbeb; border: 1px solid #f59e0b; padding: 0.8rem 1rem; margin: 1rem 0; }}
h1 {{ margin-top: 0; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Price-memory storage split</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<h2>Growth</h2>
<p>Measured on the one-file tape <code>price_memory.jsonl</code> just before the split, after the all-sports live collection restart at about 11:22 AM ET on 2026-10-21:</p>
<ul>
<li>Size: <strong>{esc(gb(archive_bytes))} GB</strong> ({esc(f"{archive_bytes:,}")} bytes).</li>
<li>Lines: <strong>3,561,197</strong> (newline count at 11:32 AM ET; about 527 bytes per line).</li>
<li>First quote on the archive: 2026-10-17 8:55 PM ET. Last quote on the archive is frozen at the cutoff below.</li>
<li>Since 11:22 AM ET (all-sports restart) through 11:32 AM ET: <strong>9,313</strong> new lines, <strong>5.04 MB</strong> in 0.167 hours → about <strong>30.2 MB/hour</strong> and <strong>55,700 lines/hour</strong>.</li>
<li>If that rate holds: about <strong>0.72 GB/day</strong>. The old single file would have been several more gigabytes within a week.</li>
<li>Those 10 minutes were mostly tennis (8,867) plus college football (446). Venues: Polymarket 5,624, Kalshi 2,201, Novig 1,488. Gemini had no change-ticks in that window.</li>
</ul>
<p>Live shards now: {esc(mb(shard_bytes))} MB jsonl. Last-two-day / match CSV: {esc(mb(csv_bytes))} MB. Drive stays HTML-only.</p>
<h2>Format chosen</h2>
<p><strong>Dated sport jsonl shards</strong> under <code>{esc(HISTORY_DIR)}</code>, for example <code>2026-10-21/tennis.jsonl</code>. Optional Excel copies for the last two Eastern days: <code>{esc(CSV_DIR / "YYYY-MM-DD_sport.csv")}</code>.</p>
<ul>
<li><strong>Why not keep one jsonl:</strong> append is cheap, but one match still reads 1.87 GB and growing.</li>
<li><strong>Why not CSV as the live tape:</strong> game names need quoting, and a busy tennis day can pass Excel’s 1,048,576-row cap. CSV is a sidecar for the last two days plus one-match dumps.</li>
<li><strong>Why not SQLite:</strong> stdlib <code>sqlite3</code> would index one match well, but the live path already appends jsonl under a file lock. A DB is an extra tool to open the tape. We can load a day’s jsonl into SQLite later if needed.</li>
<li><strong>Why not Parquet / DuckDB:</strong> the repo uses DuckDB for stock bars. Parquet is a poor crash-safe live append (rewrite, not tail-write).</li>
</ul>
<p>Change-ticks only, same as today: a repeat of the same pay-price is stored again only after 20 seconds.</p>
<h2>How Paul opens a match</h2>
<p>A live tennis match from after the split (opens only today’s tennis shard, not the 1.87 GB archive):</p>
<pre>python tools/price_memory.py export-match --game Goffin --sport tennis --day {esc(today)}</pre>
<p>Older match still on the frozen archive (slow; walks 1.87 GB once). Wawrinka vs Landaluce is on that archive. Add <code>--archive</code> with <code>--day</code> if you also want this morning’s pre-split ticks:</p>
<pre>python tools/price_memory.py export-match --game Wawrinka --sport tennis</pre>
<p>Open the printed <code>.csv</code> in Excel. List files:</p>
<pre>python tools/price_memory.py files</pre>
<p>Research scripts should call <code>price_memory.iter_tick_lines(sport=..., game=..., day=...)</code> or <code>iter_ticks(...)</code> instead of opening the giant file.</p>
<div class="later">
<h2>Archive vs live</h2>
<p>Old file <code>{esc(HISTORY)}</code> is <strong>read-only archive</strong>. Writers no longer append to it. Cutoff: {esc(cutoff_et)}. First shard write also stores <code>{esc(CUTOFF_PATH)}</code>.</p>
<p>Latch <code>orders_stopped.json</code> was not cleared. Leftover watch was left in place. Novig orders stay off (<code>NOVIG_ORDERS_ENABLED = False</code>). No live orders were sent. Ticks stay on this PC; Google Drive only gets this HTML.</p>
</div>
<h2>Files</h2>
<p>Click column headers to sort. Swipe sideways to see more columns.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>
{body}
</tbody>
</table>
</div>
<p class="note">Written {esc(now_text)}. Research only. Not gold. Not DailyRun. This page does not place an order. ATP is Association of Tennis Professionals. NFL is National Football League.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PAGE.with_suffix(".html.tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(PAGE)
    print(PAGE)
    print(json.dumps({
        "archive_bytes": archive_bytes,
        "shard_bytes": shard_bytes,
        "csv_bytes": csv_bytes,
        "n_files": len(files),
        "cutoff": cutoff,
    }, indent=2))
    return PAGE


if __name__ == "__main__":
    main()
