"""Full-universe WPBR Control with research-only retest-vs-zone columns.

Does not change eligibility, entries, exits, retest search, or production knobs.
The columns read the qualifying retest bar and weekly zone already chosen for
that trade.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from wpbr_zones import retest_position_vs_zone  # noqa: E402

STAMP = "20260929"
OUT = ROOT / "drive" / "paul_experiments" / f"wpbr_retest_vs_zone_{STAMP}"
TAG = f"wpbr_retest_vs_zone_{STAMP}"

# Printed columns use 10 decimal places. Operand rounding versus the stored
# percent stays far inside this bound when the formula is the one we wrote.
ARITH_TOL = 1e-9
# WPBR_ZONE_ID stores each bound with 4 decimal places.
ZONE_ID_TOL = 5e-5

REQUEST = """Add research-only columns to the WPBR closed-trade report to measure the qualifying retest's position relative to the weekly WPBR zone.
For each closed WPBR trade, use the exact weekly zone associated with that trade and the exact qualifying retest day already used by production WPBR logic.
Add these raw columns:
RETEST_LOW = daily LOW on the qualifying retest day.
RETEST_CLOSE = daily CLOSE on the qualifying retest day.
RETEST_LOW_VS_ZONE_TOP_PCT = (RETEST_LOW / ZONE_TOP) - 1
RETEST_LOW_VS_ZONE_BOTTOM_PCT = (RETEST_LOW / ZONE_BOTTOM) - 1
RETEST_CLOSE_VS_ZONE_TOP_PCT = (RETEST_CLOSE / ZONE_TOP) - 1
RETEST_CLOSE_VS_ZONE_BOTTOM_PCT = (RETEST_CLOSE / ZONE_BOTTOM) - 1
Use the existing WPBR zone top, zone bottom, and qualifying retest day already determined by the production engine. Do not independently reconstruct or redefine the retest.
Run this on the full-universe WPBR Control, with current production settings and no 3-year growth filter.
These columns are descriptive only. Do not change trade eligibility, entries, exits, retest logic, or production settings. Do not apply any thresholds or filters.
Include arithmetic validation that each percentage column exactly matches its stated formula, and report any missing values or failed checks.
Research only. Not gold. Not DailyRun."""

LAYMAN = (
    "We did not change which Pivot Break and Retest (WPBR) trades are bought or sold. "
    "We only added columns to the closed-trade list that say where the retest day’s low and close sat compared with that trade’s weekly zone. "
    "The zone is the weekly price band that trade already used. "
    "The retest day is the day the production system already counted as the qualifying retest for that trade. "
    "We did not go looking for a different day. "
    "Each percent is the price divided by one edge of the zone, then minus 1, on the same scale as the other WPBR percent columns. "
    "0.02 means the price was 2% above that edge. A negative number means it was below that edge. "
    "Nothing is filtered on these numbers."
)

FORMULAS = (
    ("RETEST_LOW_VS_ZONE_TOP_PCT", "RETEST_LOW", "ZONE_TOP"),
    ("RETEST_LOW_VS_ZONE_BOTTOM_PCT", "RETEST_LOW", "ZONE_BOTTOM"),
    ("RETEST_CLOSE_VS_ZONE_TOP_PCT", "RETEST_CLOSE", "ZONE_TOP"),
    ("RETEST_CLOSE_VS_ZONE_BOTTOM_PCT", "RETEST_CLOSE", "ZONE_BOTTOM"),
)

NEEDED = (
    "RETEST_DATE",
    "ZONE_TOP",
    "ZONE_BOTTOM",
    "RETEST_LOW",
    "RETEST_CLOSE",
    "RETEST_LOW_VS_ZONE_TOP_PCT",
    "RETEST_LOW_VS_ZONE_BOTTOM_PCT",
    "RETEST_CLOSE_VS_ZONE_TOP_PCT",
    "RETEST_CLOSE_VS_ZONE_BOTTOM_PCT",
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
    cmd = [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR retest vs zone"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def _latest_closed() -> Path:
    hits = sorted(OUT.glob("WPBR_Closed_*.csv"), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise FileNotFoundError(f"no closed CSV in {OUT}")
    return hits[-1]


def _num(text: str) -> float | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _zone_id_bounds(zone_id: str) -> tuple[float, float] | None:
    parts = str(zone_id or "").split("|")
    if len(parts) < 3:
        return None
    try:
        bottom = float(parts[-2])
        top = float(parts[-1])
    except ValueError:
        return None
    if not (math.isfinite(bottom) and math.isfinite(top) and bottom > 0.0 and top > 0.0):
        return None
    return bottom, top


def _self_check_formula() -> None:
    low = np.array([1.0, 95.5, 80.0], dtype=np.float64)
    close = np.array([1.0, 101.25, 70.0], dtype=np.float64)
    out = retest_position_vs_zone(low, close, retest_bar=1, zone_lower=90.0, zone_upper=100.0)
    expect = {
        "retest_low": 95.5,
        "retest_close": 101.25,
        "retest_zone_bottom": 90.0,
        "retest_zone_top": 100.0,
        "retest_low_vs_zone_top_pct": (95.5 / 100.0) - 1.0,
        "retest_low_vs_zone_bottom_pct": (95.5 / 90.0) - 1.0,
        "retest_close_vs_zone_top_pct": (101.25 / 100.0) - 1.0,
        "retest_close_vs_zone_bottom_pct": (101.25 / 90.0) - 1.0,
    }
    for key, value in expect.items():
        if abs(float(out[key]) - value) > 0.0:
            raise AssertionError(f"formula self-check {key}: {out[key]} != {value}")
    # A bad bar must stay blank. Neighboring bars must not be substituted.
    blank = retest_position_vs_zone(low, close, retest_bar=-1, zone_lower=90.0, zone_upper=100.0)
    if any(math.isfinite(float(v)) for v in blank.values()):
        raise AssertionError(f"missing retest bar should be blank, got {blank}")
    zero = retest_position_vs_zone(low, close, retest_bar=1, zone_lower=0.0, zone_upper=100.0)
    if any(math.isfinite(float(v)) for v in zero.values()):
        raise AssertionError("zero zone bottom should be blank")


def _validate(rows: list[dict[str, str]]) -> dict:
    missing = []
    arith_fail = []
    zone_fail = []
    filled = 0
    max_err = 0.0
    for row in rows:
        blanks = [name for name in NEEDED if not str(row.get(name) or "").strip()]
        if blanks:
            missing.append(
                {
                    "symbol": row.get("SYMBOL") or "",
                    "opened": row.get("DATE_OPENED") or "",
                    "zone": row.get("WPBR_ZONE_ID") or "",
                    "blank": ", ".join(blanks),
                }
            )
            continue
        filled += 1
        top = _num(row["ZONE_TOP"])
        bottom = _num(row["ZONE_BOTTOM"])
        ident = _zone_id_bounds(row.get("WPBR_ZONE_ID") or "")
        if top is None or bottom is None or top <= 0.0 or bottom <= 0.0 or ident is None:
            zone_fail.append(
                {
                    "symbol": row.get("SYMBOL") or "",
                    "opened": row.get("DATE_OPENED") or "",
                    "zone": row.get("WPBR_ZONE_ID") or "",
                    "detail": "zone top, zone bottom, or zone id could not be read",
                }
            )
            continue
        id_bottom, id_top = ident
        if abs(bottom - id_bottom) > ZONE_ID_TOL or abs(top - id_top) > ZONE_ID_TOL:
            zone_fail.append(
                {
                    "symbol": row.get("SYMBOL") or "",
                    "opened": row.get("DATE_OPENED") or "",
                    "zone": row.get("WPBR_ZONE_ID") or "",
                    "detail": (
                        f"ZONE_BOTTOM {bottom:.10f} vs id {id_bottom:.4f}; "
                        f"ZONE_TOP {top:.10f} vs id {id_top:.4f}"
                    ),
                }
            )
        for pct_name, price_name, bound_name in FORMULAS:
            price = _num(row[price_name])
            bound = _num(row[bound_name])
            stored = _num(row[pct_name])
            if price is None or bound is None or stored is None or bound == 0.0:
                arith_fail.append(
                    {
                        "symbol": row.get("SYMBOL") or "",
                        "opened": row.get("DATE_OPENED") or "",
                        "column": pct_name,
                        "stored": row.get(pct_name) or "",
                        "expected": "",
                        "error": "unreadable",
                    }
                )
                continue
            expected = (price / bound) - 1.0
            err = abs(expected - stored)
            if err > max_err:
                max_err = err
            if err > ARITH_TOL:
                arith_fail.append(
                    {
                        "symbol": row.get("SYMBOL") or "",
                        "opened": row.get("DATE_OPENED") or "",
                        "column": pct_name,
                        "stored": f"{stored:.12g}",
                        "expected": f"{expected:.12g}",
                        "error": f"{err:.3e}",
                    }
                )
    return {
        "n": len(rows),
        "filled": filled,
        "missing": missing,
        "arith_fail": arith_fail,
        "zone_fail": zone_fail,
        "max_err": max_err,
    }


def _rows_html(rows: list[dict], columns: list[tuple[str, str, str]]) -> str:
    esc = html_mod.escape
    body = []
    for row in rows:
        cells = "".join(f"<td>{esc(str(row.get(key) or ''))}</td>" for _label, key, _kind in columns)
        body.append(f"<tr>{cells}</tr>")
    head = "".join(sortable_th(label, kind) for label, _key, kind in columns)
    empty = '<tr><td colspan="8">None</td></tr>'
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        f"{head}</tr></thead><tbody>{''.join(body) or empty}"
        "</tbody></table></div>"
    )


def write_note(closed: Path, verdict: dict) -> Path:
    rows = list(csv.DictReader(closed.open(encoding="utf-8-sig", newline="")))
    sample_cols = [
        ("Symbol", "SYMBOL", "text"),
        ("Opened", "DATE_OPENED", "date"),
        ("Retest day", "RETEST_DATE", "date"),
        ("Zone id", "WPBR_ZONE_ID", "text"),
        ("Zone top", "ZONE_TOP", "num"),
        ("Zone bottom", "ZONE_BOTTOM", "num"),
        ("Retest low", "RETEST_LOW", "num"),
        ("Retest close", "RETEST_CLOSE", "num"),
        ("Low vs top", "RETEST_LOW_VS_ZONE_TOP_PCT", "num"),
        ("Low vs bottom", "RETEST_LOW_VS_ZONE_BOTTOM_PCT", "num"),
        ("Close vs top", "RETEST_CLOSE_VS_ZONE_TOP_PCT", "num"),
        ("Close vs bottom", "RETEST_CLOSE_VS_ZONE_BOTTOM_PCT", "num"),
    ]
    sample = [r for r in rows if str(r.get("RETEST_LOW") or "").strip()][:12]
    miss_rows = [
        {
            "SYMBOL": m["symbol"],
            "DATE_OPENED": m["opened"],
            "WPBR_ZONE_ID": m["zone"],
            "BLANK": m["blank"],
        }
        for m in verdict["missing"][:40]
    ]
    fail_rows = verdict["arith_fail"][:40]
    zone_rows = [
        {
            "SYMBOL": z["symbol"],
            "DATE_OPENED": z["opened"],
            "DETAIL": z["detail"],
        }
        for z in verdict["zone_fail"][:40]
    ]
    esc = html_mod.escape
    max_err = verdict["max_err"]
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR retest vs weekly zone</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:1280px;margin:0 auto;padding:1rem}}
h1{{font-size:1.3rem}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap}}
.muted{{color:var(--muted)}}
table{{border-collapse:collapse;width:100%;font-size:.82rem}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child,th:nth-child(4),td:nth-child(4){{text-align:left}}
.table-wrap{{overflow-x:auto}}
{SORTABLE_TH_CSS}
</style></head><body>
<header><h1>WPBR retest day versus the weekly zone</h1>
<p class="muted">Research columns on the production Control book. Not a filter. Not gold. Not DailyRun. Click column headers to sort.</p></header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p></div>
<section><h2>Arithmetic check</h2>
<p>{verdict['n']:,} closed trades. {verdict['filled']:,} have the retest day, both zone edges, both prices, and all four percent columns. {len(verdict['missing']):,} are missing one or more of those values. Percent checks outside {ARITH_TOL:.0e}: {len(verdict['arith_fail']):,}. Zone-id mismatches: {len(verdict['zone_fail']):,}. Largest absolute gap between a stored percent and its formula: {max_err:.3e}.</p>
<p class="muted">Each stored percent is checked as (price / zone edge) − 1, using the ZONE_TOP and ZONE_BOTTOM written on that same row. Those two edges are the weekly zone bounds production already attached to the trade. RETEST_DATE is the qualifying retest day production already chose. A check fails when the absolute difference is greater than {ARITH_TOL:.0e}. The zone-id check asks that those bounds still match the last two numbers in WPBR_ZONE_ID within {ZONE_ID_TOL:.0e}, which is the 4-decimal rounding already stored in the zone id.</p>
<h3>Failed formula checks</h3>
{_rows_html(fail_rows, [("Symbol", "symbol", "text"), ("Opened", "opened", "date"), ("Column", "column", "text"), ("Stored", "stored", "num"), ("Formula", "expected", "num"), ("Abs error", "error", "num")])}
<h3>Missing values</h3>
{_rows_html(miss_rows, [("Symbol", "SYMBOL", "text"), ("Opened", "DATE_OPENED", "date"), ("Zone id", "WPBR_ZONE_ID", "text"), ("Blank columns", "BLANK", "text")])}
<p class="muted">Showing up to 40 missing rows. Total missing: {len(verdict['missing']):,}.</p>
<h3>Zone id versus the bounds used in the formula</h3>
{_rows_html(zone_rows, [("Symbol", "SYMBOL", "text"), ("Opened", "DATE_OPENED", "date"), ("Detail", "DETAIL", "text")])}
</section>
<section><h2>Closed book sample</h2>
<p>The full file is <code>{esc(closed.name)}</code> in this folder. First 12 closed rows that have a retest low.</p>
{_rows_html(sample, sample_cols)}
</section>
<section><h2>Freeze</h2>
<ul>
<li>Current WPBR production knobs from run_wpbr.bat. Growth filter off. No 3-year growth requirement. No extra history cutoff.</li>
<li>Full universe: every CSV under data/newdata/data.</li>
<li>RETEST_LOW, RETEST_CLOSE, and the four percent columns are descriptive. ZONE_TOP, ZONE_BOTTOM, and RETEST_DATE are the production inputs those formulas use, written on the row so the arithmetic can be checked. They do not block or change a trade.</li>
<li>The retest day is the bar production already stored on that entry. The zone edges are the weekly bounds already stored on that entry. This job does not search for another retest.</li>
<li>Research only. Not gold. Not DailyRun.</li>
</ul>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT / "compare.html"
    path.write_text(page, encoding="utf-8")
    (OUT / "BASELINE.md").write_text(
        "\n".join(
            [
                "# WPBR retest versus weekly zone",
                "",
                "## What you asked",
                "",
                REQUEST.strip(),
                "",
                "## In plain English",
                "",
                LAYMAN,
                "",
                f"Closed file: `{closed.name}`.",
                f"Trades {verdict['n']}. Filled {verdict['filled']}. Missing {len(verdict['missing'])}.",
                f"Formula failures {len(verdict['arith_fail'])}. Zone-id mismatches {len(verdict['zone_fail'])}.",
                f"Largest absolute formula gap {max_err:.3e} (fail if greater than {ARITH_TOL:.0e}).",
                "",
                "Control freeze: run_wpbr.bat production knobs, growth_filter_enabled=false, full data/newdata/data universe.",
                "Columns are descriptive. No threshold. No change to eligibility, entries, exits, or retest search.",
                "",
                "Research only. Not gold. Not DailyRun.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def write_failure(message: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "compare.html"
    path.write_text(
        "<!DOCTYPE html><html><body><h1>WPBR retest vs weekly zone</h1>"
        f"<h2>What you asked</h2><pre>{html_mod.escape(REQUEST.strip())}</pre>"
        f"<p><strong>In plain English.</strong> {html_mod.escape(LAYMAN)}</p>"
        f"<pre>{html_mod.escape(message)}</pre></body></html>",
        encoding="utf-8",
    )
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "stock_analysis" / "rocket_tbn.py"),
        str(ROOT / "data" / "newdata" / "data"),
        "-o",
        str(OUT),
        "-w",
        "16",
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    for knob in KNOBS:
        cmd.extend(["-v", knob])
    log = OUT / "run.log"
    print(f"[{TAG}] start log={log}", flush=True)
    try:
        _self_check_formula()
        with log.open("w", encoding="utf-8", errors="replace") as f:
            proc = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            raise RuntimeError(f"rocket exited {proc.returncode}. See {log}")
        closed = _latest_closed()
        rows = list(csv.DictReader(closed.open(encoding="utf-8-sig", newline="")))
        missing_headers = [name for name in NEEDED if name not in (rows[0].keys() if rows else {})]
        if not rows:
            header = closed.read_text(encoding="utf-8-sig").splitlines()[:1]
            raise RuntimeError(f"closed CSV has no trades. header={header}")
        if missing_headers:
            raise RuntimeError(f"closed CSV missing columns: {missing_headers}")
        verdict = _validate(rows)
        html = write_note(closed, verdict)
        htmls = sorted(OUT.glob("*.html"))
        msg = (
            f"WPBR Control retest-vs-zone columns. "
            f"Trades {verdict['n']}. Filled {verdict['filled']}. "
            f"Missing {len(verdict['missing'])}. "
            f"Formula failures {len(verdict['arith_fail'])}. "
            f"Zone-id mismatches {len(verdict['zone_fail'])}. "
            f"Max abs error {verdict['max_err']:.3e}."
        )
        print(f"[{TAG}] {msg}", flush=True)
        _notify(htmls or [html], msg)
        if verdict["arith_fail"] or verdict["zone_fail"]:
            return 2
        return 0
    except Exception:
        err = traceback.format_exc()
        print(err, flush=True)
        path = write_failure(err)
        _notify([path], "WPBR retest vs zone run failed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
