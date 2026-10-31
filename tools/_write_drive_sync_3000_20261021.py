"""One-shot: why Google Drive queued ~3000 files this morning. No orders."""
from __future__ import annotations

import html as html_lib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from prediction_paths import DRIVE_STAMP, RAW_DIR
from report_page_extras import CACHE_META, SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML

PAGE = DRIVE_STAMP / "drive_sync_3000_20261021.html"
ASKED = (
    "Google Drive is now trying to sync over 3000 files. Why? Check whether we moved "
    "prediction raw off Drive and Drive is still deleting or restoring copies, whether "
    "drive/.tmp.driveupload temps exploded, whether live in-match tick collection is "
    "writing thousands of JSON under drive/ instead of local/, whether HTML copies "
    "pulled a whole tree, or whether Python pycache leaked onto Drive."
)
PLAIN = (
    "This is not the 3 GB prediction tape coming back, and it is not live game ticks "
    "spilling onto Drive. The 10:30 morning stock run (DailyRun) wrote about 2,650 "
    "per-ticker zone spreadsheets onto the Drive folder plus about 600 Thinkorswim "
    "trendline study files. Google Drive stages each of those as a numbered temp in "
    ".tmp.driveupload while it uploads. That temp pile is what looks like 3000 files "
    "syncing. Live quote history stays on this PC only. We did not stop the stock run "
    "or the live game watchers."
)


def esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" aria-sort="none">'
        f"{esc(label)}<span class=\"sort-ind\"></span></th>"
    )


def td_row(cells: list[tuple[str, bool]]) -> str:
    parts = ["<tr>"]
    for text, _num in cells:
        parts.append(f"<td>{esc(text)}</td>")
    parts.append("</tr>")
    return "".join(parts)


def main() -> Path:
    folder_head = "".join(
        [
            th("Folder", "text"),
            th("Files", "num"),
            th("Size", "text"),
            th("Types", "text"),
            th("When (ET 2026-10-21)", "text"),
            th("Verdict", "text"),
        ]
    )
    folder_rows = [
        [
            ("drive/.tmp.driveupload", False),
            ("3333 after cleanup (peaked ~3549)", True),
            ("~379 MB", False),
            ("numbered temps; most 1–20 KB ToS studies and WPBR/BRT CSVs", False),
            ("10:39–11:01; 10:43–10:44 = ~1629 WPBR CSVs; 10:54–11:00 = trendlines", False),
            ("THE burst. Google Drive upload scratch for DailyRun, not unique data.", False),
        ],
        [
            ("drive/ (folder root)", False),
            ("2650 new/modified since 10:00", True),
            ("DailyRun reports", False),
            ("2234 WPBR_ZONES*.csv, 84 BRT_ZONES*.csv, plus RL/RSI/SB/WRL html/csv", False),
            ("10:40–10:45 from DailyRun_20261021_103000", False),
            ("Real files Drive is uploading. Normal morning stock run.", False),
        ],
        [
            ("drive/paul_studies/trendlines_tos_20261021", False),
            ("599", True),
            ("10.1 MB", False),
            (".ts Thinkorswim studies + index.html + segments.json", False),
            ("10:54–11:00 (DailyRun step 13d)", False),
            ("Second wave. Same job every weekday; not prediction ticks.", False),
        ],
        [
            ("drive/.../prediction_market_arb_exhaustive_20261017/raw", False),
            ("1 (README only after cleanup)", True),
            ("tiny", False),
            ("README.md pointer; empty live_* / pycache dirs removed", False),
            ("Move ~09:28; leftover error log 09:36–10:12 then stopped", False),
            ("NOT the 3000. No restored price_memory. No per-tick JSON on Drive.", False),
        ],
        [
            ("local/.../prediction_market_arb_exhaustive_20261017/raw", False),
            ("994", True),
            ("2.97 GB", False),
            ("price_memory.jsonl (~1.78 GB), live_state, live_health, logs", False),
            ("Live writes now (pollers + overnight_scan)", False),
            ("Collection is here via tools/prediction_paths.py RAW_DIR. Left running.", False),
        ],
        [
            ("G:\\My Drive\\paul_experiments\\...20261017", False),
            ("24", True),
            ("2.1 MB", False),
            ("HTML reports only; no raw/", False),
            ("HTML copies, not a tree copy of raw", False),
            ("Not a whole-tree copy. Different Drive mount than repo drive/.", False),
        ],
    ]
    cause_head = "".join(
        [
            th("Suspected cause", "text"),
            th("Result", "text"),
            th("Evidence", "text"),
        ]
    )
    cause_rows = [
        [
            ("1. Drive still deleting/restoring moved raw (~977 files / 3 GB)", False),
            ("No", False),
            ("Drive raw has README only. No price_memory or price_memory (1).jsonl. Local still has the 1.78 GB tape.", False),
        ],
        [
            ("2. drive/.tmp.driveupload temps", False),
            ("Yes — upload queue of DailyRun", False),
            ("3156 temps in the 10:00 hour; contents are WPBR/BRT CSVs and {SYM}_trendlines_mwd_Study.ts, not jsonl ticks.", False),
        ],
        [
            ("3. Live tick job writing thousands of JSON under drive/", False),
            ("No leak now", False),
            ("live_game_pollers.py and overnight_scan.py import RAW_DIR = local. Newest live_state/price_memory are under local/. Overnight leftover live_state temps (33 files, ~480 bytes each) were stuck in tmp from before 10:00; deleted. Did not stop pollers or leftover watch.", False),
        ],
        [
            ("4. HTML copy of a whole tree including raw", False),
            ("No", False),
            ("G: stamp is 24 HTML files, 2.1 MB, no raw. Repo stamp HTML updates are a handful of pages.", False),
        ],
        [
            ("5. __pycache__ / PYTHONDONTWRITEBYTECODE on Drive", False),
            ("No", False),
            ("Zero pycache files on Drive. Empty leftover raw/__pycache__ dir removed.", False),
        ],
    ]

    def body(rows):
        return "".join(td_row(r) for r in rows)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{CACHE_META}
<title>Why Drive queued 3000 files — 2026-10-21</title>
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
<h1>Why Google Drive queued ~3000 files</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{esc(ASKED)}</p>
<h2>In plain English</h2>
<p>{esc(PLAIN)}</p>
</div>
<h2>One-sentence cause</h2>
<p>Google Drive is uploading this morning's 10:30 DailyRun dump — about 2,650 per-ticker zone CSVs at the Drive root plus about 600 Thinkorswim trendline studies — and <code>.tmp.driveupload</code> is the in-flight copy of those files, not a restored prediction-market tape.</p>
<h2>What we did / did not do</h2>
<p>Deleted 33 leftover overnight <code>.tmp.driveupload</code> files from before 10:00 (stuck live_state JSON and old scratch). Left today's DailyRun temps alone so the real upload can finish. Removed empty Drive <code>raw/live_*</code> and <code>raw/__pycache__</code> dirs plus leftover stub logs. Drive <code>raw/</code> is README only. Did not stop pollers, leftover watch, or the orders latch. Did not send live orders. Did not clear <code>orders_stopped.json</code>. Did not flip Novig orders.</p>
<p>Expect Drive to keep syncing for a while until those DailyRun CSVs and <code>.ts</code> studies finish uploading; the temp count should fall on its own (it already dropped from ~3549 toward ~3333 while this note was written). We did not halt a leak, because there was no live-tick leak onto Drive.</p>
<p>Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{folder_head}</tr></thead>
<tbody>
{body(folder_rows)}
</tbody>
</table>
</div>
<h2>Likely causes checked</h2>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{cause_head}</tr></thead>
<tbody>
{body(cause_rows)}
</tbody>
</table>
</div>
<p>HTML reports stay at <code>{esc(DRIVE_STAMP)}</code>. Live raw stays at <code>{esc(RAW_DIR)}</code>.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    PAGE.write_text(page, encoding="utf-8")
    print(PAGE)
    return PAGE


if __name__ == "__main__":
    main()
