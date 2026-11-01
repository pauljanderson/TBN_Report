"""Full-universe WPBR production run with a research-only expansion column.

Does not change eligibility, entries, or exits. Writes the closed book under
drive/paul_experiments and a short HTML note.
"""
from __future__ import annotations

import csv
import html as html_mod
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402

STAMP = "20260929"
OUT = ROOT / "drive" / "paul_experiments" / f"wpbr_max_pre_retest_expansion_{STAMP}"
TAG = f"wpbr_max_pre_retest_expansion_{STAMP}"

REQUEST = """Add a research-only column to the WPBR closed-trade report called MAX_PRE_RETEST_EXPANSION_PCT.
For each WPBR trade, identify the weekly zone top used by that trade. Starting after the qualifying breakout and ending immediately before the qualifying retest, find the maximum daily HIGH reached during that interval.
Calculate:
MAX_PRE_RETEST_EXPANSION_PCT = (maximum daily HIGH before retest / zone top) - 1
Store it as a percentage.
This is descriptive only. Do not change WPBR eligibility, entries, exits, or any production logic. Do not apply any threshold or filter.
Also add MAX_PRE_RETEST_HIGH so the underlying price used in the calculation is visible for validation.
And run the full-universe control with this column."""

LAYMAN = (
    "We did not change which Pivot Break and Retest (WPBR) trades are bought or sold. "
    "We only added two columns to the closed-trade list so you can see how far price ran up before it came back to retest the weekly zone. "
    "The zone top is the top of the weekly zone that trade used. "
    "The high is the highest daily high after that zone’s weekly breakout week finished, and before the retest day that qualified the trade. "
    "The breakout day itself and the retest day are not included. "
    "If there is no day strictly between them, the columns are left blank. "
    "The percent column is (that high divided by the zone top) minus 1, the same scale as the other WPBR percent columns. "
    "0.20 means the high was 20% above the zone top. Nothing is filtered on this number."
)

KNOBS = [
    "wpbr_zones=true",
    "brt_zones=false",
    "yh_zones=false",
    "vec_zones=false",
    "band_pct=0.015",
    "strong_pre_pivot_bars=3",
    "strong_pre_pivot_pct=0.10",
    "strong_post_pivot_bars=3",
    "strong_post_pivot_pct=0.10",
    "strong_pivot_mode=either",
    "wpbr_breakout_confirmation=0.03",
    "wpbr_max_days_after_retest=2",
    "wpbr_second_chance_after_win=true",
    "growth_filter_enabled=false",
    "min_spy_compare_1y_at_trigger=-1000",
    "ind_score_weights_path=",
    "too_high_multiplier=0",
    "target_pct=1.22",
    "stop_pct=0.91",
    "sheet_no_entry_same_bar_after_exit=false",
    "use_indicators=true",
    "max_market_cap=0",
    "min_market_cap=0",
]


def _notify(paths: list[Path], message: str) -> None:
    cmd = [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR pre-retest expansion"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest_closed() -> Path:
    hits = sorted(OUT.glob("WPBR_Closed_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no closed CSV in {OUT}")
    return hits[-1]


def _zone_top(zone_id: str) -> float | None:
    parts = str(zone_id or "").split("|")
    if len(parts) < 3:
        return None
    try:
        return float(parts[-1])
    except ValueError:
        return None


def write_note(closed: Path) -> Path:
    rows = list(csv.DictReader(closed.open(encoding="utf-8-sig", newline="")))
    filled = blank = bad = 0
    sample = []
    for row in rows:
        hi = str(row.get("MAX_PRE_RETEST_HIGH") or "").strip()
        pct = str(row.get("MAX_PRE_RETEST_EXPANSION_PCT") or "").strip()
        if not hi or not pct:
            blank += 1
            continue
        filled += 1
        top = _zone_top(str(row.get("WPBR_ZONE_ID") or ""))
        try:
            calc = (float(hi) / top) - 1.0 if top else None
        except (TypeError, ValueError, ZeroDivisionError):
            calc = None
        if calc is None or abs(calc - float(pct)) > 1e-4:
            bad += 1
        if len(sample) < 12:
            sample.append(row)
    esc = html_mod.escape
    body = []
    for row in sample:
        top = _zone_top(str(row.get("WPBR_ZONE_ID") or ""))
        hi = row.get("MAX_PRE_RETEST_HIGH") or ""
        pct = row.get("MAX_PRE_RETEST_EXPANSION_PCT") or ""
        body.append(
            "<tr>"
            f"<td>{esc(row.get('SYMBOL') or '')}</td>"
            f"<td>{esc(row.get('DATE_OPENED') or '')}</td>"
            f"<td>{esc(row.get('WPBR_ZONE_ID') or '')}</td>"
            f"<td>{esc(f'{top:.4f}' if top is not None else '')}</td>"
            f"<td>{esc(hi)}</td>"
            f"<td>{esc(pct)}</td>"
            "</tr>"
        )
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR pre-retest expansion</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1200px;margin:0 auto;padding:1rem}}
h1{{font-size:1.3rem}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap}}
.muted{{color:var(--muted)}}
table{{border-collapse:collapse;width:100%;font-size:.82rem}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(3),td:nth-child(3){{text-align:left}}
{SORTABLE_TH_CSS}
</style></head><body>
<header><h1>WPBR max high before the retest</h1>
<p class="muted">Research column on the production book. Not a filter. Not gold. Not DailyRun. Click column headers to sort.</p></header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p></div>
<section><h2>Closed book</h2>
<p>{len(rows):,} closed trades. {filled:,} have both columns. {blank:,} are blank because no daily bar sits strictly between the breakout week and that trade’s retest. Arithmetic checks that failed: {bad}.</p>
<p>The full file is <code>{esc(closed.name)}</code> in this folder. Zone top is the last number in <code>WPBR_ZONE_ID</code>.</p>
<p class="muted">Check: MAX_PRE_RETEST_EXPANSION_PCT = MAX_PRE_RETEST_HIGH / zone top − 1.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Symbol", "text")}{sortable_th("Opened", "date")}{sortable_th("Zone id", "text")}{sortable_th("Zone top", "num")}{sortable_th("Max high", "num")}{sortable_th("Expansion", "num")}
</tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p class="muted">First 12 closed rows, for a visual check. The window is daily highs after the last session of the qualifying weekly breakout (weekly close above the zone top) and before the retest day used by that trade.</p>
</section>
<section><h2>Freeze</h2>
<ul>
<li>Current WPBR production knobs from run_wpbr.bat. No growth filter. No history cutoff beyond what production already does.</li>
<li>MAX_PRE_RETEST_HIGH and MAX_PRE_RETEST_EXPANSION_PCT are descriptive. They do not block or change a trade.</li>
<li>Full universe: every CSV under data/newdata/data.</li>
</ul>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT / "compare.html"
    path.write_text(page, encoding="utf-8")
    (OUT / "BASELINE.md").write_text(
        "\n".join([
            "# WPBR pre-retest expansion column",
            "",
            "## What you asked",
            "",
            REQUEST.strip(),
            "",
            "## In plain English",
            "",
            LAYMAN,
            "",
            f"Closed file: `{closed.name}`. Trades {len(rows)}. Filled {filled}. Blank {blank}. Arithmetic mismatches {bad}.",
            "",
            "Research only. Not a filter. Not gold. Not DailyRun.",
            "",
        ]),
        encoding="utf-8",
    )
    return path


def write_failure(message: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "compare.html"
    path.write_text(
        "<!DOCTYPE html><html><body><h1>WPBR pre-retest expansion</h1>"
        f"<h2>What you asked</h2><pre>{html_mod.escape(REQUEST.strip())}</pre>"
        f"<p><strong>In plain English.</strong> {html_mod.escape(LAYMAN)}</p>"
        f"<pre>{html_mod.escape(message)}</pre></body></html>",
        encoding="utf-8",
    )
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-u", str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o", str(OUT), "-w", "16", "--aggressive", "--use-duckdb", "--no-regression",
    ]
    for knob in KNOBS:
        cmd.extend(["-v", knob])
    log = OUT / "run.log"
    print(f"[{TAG}] start log={log}", flush=True)
    try:
        with log.open("w", encoding="utf-8", errors="replace") as f:
            proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            raise RuntimeError(f"rocket exited {proc.returncode}. See {log}")
        closed = _latest_closed()
        html = write_note(closed)
        msg = f"WPBR production book with pre-retest expansion column: {closed.name}"
        print(f"[{TAG}] {msg}", flush=True)
        _notify([html, closed], msg)
        return 0
    except Exception:
        err = traceback.format_exc()
        print(err, flush=True)
        path = write_failure(err)
        _notify([path], "WPBR pre-retest expansion run failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
