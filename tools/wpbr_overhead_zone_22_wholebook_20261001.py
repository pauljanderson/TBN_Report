"""Whole-book count of earlier WPBR zones sitting within 22% above the entry zone.

Adopted 3-year positive-growth book only. Compares the frozen bad-performer
cohort with every other closed trade. Measurement only. No filter.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

STAMP = "20261001"
CLOSED = ROOT / "tmp_wpbr_growth_min_pct_ab_20261001" / "control" / "WPBR_Closed_261001155729.csv"
FROZEN = ROOT / "drive" / "paul_experiments" / "wpbr_bad_performer_structure_20261001" / "symbols.csv"
DATA = ROOT / "data" / "newdata" / "data"
OUT = ROOT / "drive" / "paul_experiments" / f"wpbr_overhead_zone_22_wholebook_{STAMP}"
BAND = 0.22

REQUEST_PROMPT = """Run a whole-book WPBR measurement on the adopted 3-year-growth book. For every closed trade, count all earlier WPBR zones whose lower edge is above the active entry-zone upper edge and within +22% of that edge. Compare the frozen bad-performer cohort (40 symbols, 335 trades) against all remaining trades. Report the percentage with ≥1 qualifying prior zone, median zone count, percentage with nearest zone within 5%, 10%, and 15%, and percentage with ≥1 qualifying zone still above the trigger-day close. Measurement only—do not build or optimize a filter."""

LAYMAN = (
    "This is a count, not a new buy rule. "
    "We used the Pivot Break and Retest (WPBR) research book that already requires the stock to be higher than it was 756 trading sessions earlier. "
    "For every closed trade we looked backward and counted older WPBR zones whose bottom sits above the top of the zone being bought, and no more than 22% above that top. "
    "We then compared two groups that were already frozen: the 40 symbols that had at least 5 trades and a win rate under 20%, and every other trade in the same book. "
    "The page says how often each group had at least one of those zones, how many it usually had, how close the nearest one was, and how often one of them was still above the price on the day before the buy."
)


def _f(raw: Any) -> float:
    if raw is None:
        return float("nan")
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _notify(paths: list[Path], message: str) -> None:
    cmd = [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "-t", "WPBR 22% zone count"]
    for p in paths:
        cmd.extend(["--path", str(p)])
    cmd.extend(["-m", message])
    subprocess.run(cmd, cwd=str(ROOT), check=False)


def load_trades(bad: set[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    with CLOSED.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(raw.get("DATE_OPENED") or "")
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            if not opened or not sym:
                continue
            grouped.setdefault(sym, []).append({
                "symbol": sym,
                "opened": opened,
                "zone_id": str(raw.get("WPBR_ZONE_ID") or "").strip(),
                "zone_top": _f(raw.get("ZONE_TOP")),
                "cohort": "bad" if sym in bad else "rest",
            })
    return grouped


def measure_symbol(sym: str, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path = DATA / f"{sym}.csv"
    if not path.is_file():
        return [{
            "symbol": t["symbol"], "opened": t["opened"], "cohort": t["cohort"],
            "measured": 0, "zone_matched": 0, "n_band": "", "n_still": "", "nearest": "",
        } for t in trades]
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")
    for col in ("Open", "High", "Low", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0)
    else:
        df["Volume"] = 0.0
    df = df.set_index("Date")
    close = df["Close"].to_numpy(dtype=np.float64)
    dates = df.index.strftime("%Y%m%d").to_numpy()
    stream = compute_wpbr_touch_stream(
        df,
        band_pct=0.015,
        strong_pre_pivot_bars=3,
        strong_pre_pivot_pct=0.10,
        strong_post_pivot_bars=3,
        strong_post_pivot_pct=0.10,
        strong_pivot_mode="either",
        breakout_confirmation=0.03,
        max_days_after_retest=2,
        retest_mode="stop_looking",
        zone_price_round_decimals=2,
        merge_overlapping_zones=False,
    )
    events = list(stream.get("wpbr_zone_events") or [])
    by_id = {str(ev.get("wpbr_zone_id") or ""): ev for ev in events}
    born = np.array([int(ev.get("activation_bar") if ev.get("activation_bar") is not None else -1) for ev in events], dtype=np.int32)
    lowers = np.array([float(ev.get("zone_lower") or np.nan) for ev in events], dtype=np.float64)
    ids = [str(ev.get("wpbr_zone_id") or "") for ev in events]
    out = []
    for trade in trades:
        hits = np.flatnonzero(dates < trade["opened"])
        if hits.size == 0 or not events:
            out.append({
                "symbol": sym, "opened": trade["opened"], "cohort": trade["cohort"],
                "measured": 0, "zone_matched": 0, "n_band": "", "n_still": "", "nearest": "",
            })
            continue
        i = int(hits[-1])
        px = float(close[i])
        ev = by_id.get(trade["zone_id"])
        active_upper = float(ev["zone_upper"]) if ev else trade["zone_top"]
        if not (math.isfinite(active_upper) and active_upper > 0):
            out.append({
                "symbol": sym, "opened": trade["opened"], "cohort": trade["cohort"],
                "measured": 0, "zone_matched": int(ev is not None), "n_band": "", "n_still": "", "nearest": "",
            })
            continue
        own = np.fromiter((z == trade["zone_id"] for z in ids), dtype=bool, count=len(ids))
        ok = (~own) & (born >= 0) & (born < i) & np.isfinite(lowers) & (lowers > active_upper)
        gap = (lowers - active_upper) / active_upper
        qual = ok & (gap <= BAND)
        n_band = int(np.count_nonzero(qual))
        n_still = int(np.count_nonzero(qual & np.isfinite(px) & (lowers > px))) if math.isfinite(px) else 0
        nearest = float(np.min(gap[qual])) if n_band else float("nan")
        out.append({
            "symbol": sym,
            "opened": trade["opened"],
            "cohort": trade["cohort"],
            "measured": 1,
            "zone_matched": int(ev is not None),
            "n_band": n_band,
            "n_still": n_still,
            "nearest": "" if not math.isfinite(nearest) else f"{nearest:.8f}",
        })
    return out


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    meas = [r for r in rows if int(r["measured"]) == 1]
    n = len(meas)
    counts = np.array([int(r["n_band"]) for r in meas], dtype=np.float64)
    still = np.array([int(r["n_still"]) > 0 for r in meas], dtype=bool)
    nearest = np.array([
        float(r["nearest"]) if str(r["nearest"]) != "" else np.nan
        for r in meas
    ], dtype=np.float64)

    def pct(mask: np.ndarray) -> float:
        return 100.0 * float(np.count_nonzero(mask)) / n if n else float("nan")

    return {
        "trades": len(rows),
        "measured": n,
        "symbols": len({r["symbol"] for r in rows}),
        "matched": sum(int(r["zone_matched"]) for r in meas),
        "ge1": pct(counts >= 1),
        "ge1_n": int(np.count_nonzero(counts >= 1)) if n else 0,
        "median": float(np.median(counts)) if n else float("nan"),
        "p5": pct(np.isfinite(nearest) & (nearest <= 0.05)),
        "p5_n": int(np.count_nonzero(np.isfinite(nearest) & (nearest <= 0.05))) if n else 0,
        "p10": pct(np.isfinite(nearest) & (nearest <= 0.10)),
        "p10_n": int(np.count_nonzero(np.isfinite(nearest) & (nearest <= 0.10))) if n else 0,
        "p15": pct(np.isfinite(nearest) & (nearest <= 0.15)),
        "p15_n": int(np.count_nonzero(np.isfinite(nearest) & (nearest <= 0.15))) if n else 0,
        "still": pct(still),
        "still_n": int(np.count_nonzero(still)) if n else 0,
    }


def _pct(v: float) -> str:
    return "—" if not math.isfinite(v) else f"{v:.1f}%"


def _num(v: float) -> str:
    return "—" if not math.isfinite(v) else f"{v:.1f}"


def _delta(a: float, b: float, suffix: str = "") -> str:
    if not (math.isfinite(a) and math.isfinite(b)):
        return "—"
    d = a - b
    sign = "+" if d > 0 else ""
    return f"{sign}{d:.1f}{suffix}"


def write_page(bad: dict[str, Any], rest: dict[str, Any], book: dict[str, Any], missing: int) -> tuple[Path, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    esc = html_mod.escape
    rows_spec = [
        ("Trades in the book", "trades", "count"),
        ("Trades measured", "measured", "count"),
        ("Symbols", "symbols", "count"),
        ("At least one qualifying prior zone", "ge1", "pct"),
        ("Median count of qualifying zones", "median", "num"),
        ("Nearest qualifying zone within 5%", "p5", "pct"),
        ("Nearest qualifying zone within 10%", "p10", "pct"),
        ("Nearest qualifying zone within 15%", "p15", "pct"),
        ("At least one qualifying zone still above the trigger close", "still", "pct"),
    ]
    body = []
    for label, key, kind in rows_spec:
        bv, rv = bad[key], rest[key]
        if kind == "pct":
            cells = (_pct(bv), _pct(rv), _delta(bv, rv, "%"))
        elif kind == "num":
            cells = (_num(bv), _num(rv), _delta(bv, rv))
        else:
            cells = (str(int(bv)), str(int(rv)), str(int(bv) - int(rv)))
        body.append(
            "<tr>"
            f"<td>{esc(label)}</td><td>{esc(cells[0])}</td><td>{esc(cells[1])}</td><td>{esc(cells[2])}</td>"
            "</tr>"
        )
    head = (
        sortable_th("Measure", "text")
        + sortable_th("Bad cohort", "num")
        + sortable_th("Remaining trades", "num")
        + sortable_th("Bad minus remaining", "num")
    )
    counts = (
        f"At least one zone: bad {bad['ge1_n']} / {bad['measured']}, remaining {rest['ge1_n']} / {rest['measured']}. "
        f"Nearest within 5% / 10% / 15%: bad {bad['p5_n']} / {bad['p10_n']} / {bad['p15_n']}; "
        f"remaining {rest['p5_n']} / {rest['p10_n']} / {rest['p15_n']}. "
        f"Still above the trigger close: bad {bad['still_n']} / {bad['measured']}, remaining {rest['still_n']} / {rest['measured']}."
    )
    freeze = [
        "Book: control arm of wpbr_overhead, the adopted 3-year positive-growth filter. Closed file WPBR_Closed_261001155729.csv. growth_filter_enabled=true, growth_filter_strict_gt=true, growth_bars=756, growth_min_pct=0, min_history_bars=756. Trigger close must be greater than the close exactly 756 sessions earlier.",
        "Bad cohort: the frozen symbol list in wpbr_bad_performer_structure_20261001/symbols.csv. That list is the 40 symbols with at least 5 closed trades and a win rate under 20% in this book. Every closed trade on those symbols is in the cohort. Remaining trades are every other closed trade in the same book.",
        "A qualifying zone is an earlier WPBR zone. Its pivot week starts before the trigger bar. It is not this trade's zone. Its lower edge is strictly above the active entry zone's upper edge, and (lower edge − upper edge) / upper edge is 22% or less.",
        "The active upper edge is the recomputed zone upper bound when the trade's zone id matches. Otherwise it is ZONE_TOP from the closed trade.",
        "The trigger bar is the last daily bar dated strictly before DATE_OPENED. A zone is still above the trigger close when its lower edge is above that close.",
        "Nearest within 5%, 10%, or 15% uses every measured trade as the denominator. A trade with no qualifying zone is not counted in those percentages.",
        "Median zone count includes zeros.",
        "Zone knobs match production WPBR: band 1.5%, strong pivot either side 3 bars and 10%, breakout confirmation 3%, retest window 2 days, zones not merged.",
        f"Zone id matched on {book['matched']} of {book['measured']} measured trades. Trades with no daily bar before the entry, or no readable price file, are not measured ({missing} unmeasured).",
        "Measurement only. The percentages were not used to choose a cutoff or a buy rule. Research only. Not gold. Not DailyRun.",
    ]
    # Fix the awkward freeze line I started with the wrong name.
    freeze[0] = (
        "Book: control arm of wpbr_growth_min_pct_3y_ab_20261001, the adopted 3-year positive-growth filter. "
        "Closed file WPBR_Closed_261001155729.csv. growth_filter_enabled=true, growth_filter_strict_gt=true, "
        "growth_bars=756, growth_min_pct=0, min_history_bars=756. "
        "Trigger close must be greater than the close exactly 756 sessions earlier."
    )
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WPBR 22% overhead zone count</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header,main{{max-width:980px;margin:0 auto;padding:1rem}}
h1{{font-size:1.35rem;margin:0 0 .4rem}}
h2{{font-size:1.05rem;margin:0 0 .5rem}}
.muted{{color:var(--muted)}}
.callout,section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.9rem 1rem;margin:1rem 0}}
pre{{white-space:pre-wrap;font-size:.9rem}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .45rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
@media (max-width: 800px) {{
  table.sortable > thead > tr > th.sortable-th:first-child,
  table.sortable > tbody > tr > td:first-child {{ background:#1a2332; color:#e7ecf3; }}
}}
</style></head><body>
<header>
<h1>WPBR zones within 22% above the entry zone</h1>
<p class="muted">Pivot Break and Retest (WPBR). Whole adopted 3-year-growth book. Measurement only. No new filter. Click a column header to sort. Swipe sideways to see more columns.</p>
</header>
<main>
<div class="callout"><h2>What you asked</h2>
<pre>{esc(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English.</strong> {esc(LAYMAN)}</p>
</div>
<section><h2>Bad cohort versus the rest of the book</h2>
<p class="muted">The bad cohort is the frozen 40 symbols. Remaining is every other closed trade. A percentage uses measured trades. The difference is the bad cohort minus the remaining trades. It is a comparison of counts, not a decision to keep a rule.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap"><table class="sortable"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p class="muted">{esc(counts)} The whole measured book is {book['measured']} trades across {book['symbols']} symbols.</p>
</section>
<section><h2>How a zone qualified</h2>
<p>An earlier zone qualifies when its lower edge is above the active entry zone's upper edge and that gap is 22% or less of the upper edge. The nearest-zone percentages ask whether the closest qualifying zone is within 5%, 10%, or 15%. A trade with none is outside all three. A zone is still overhead when its lower edge is also above the close on the day before the buy.</p>
</section>
<section><h2>Freeze</h2><ul>{''.join(f'<li>{esc(line)}</li>' for line in freeze)}</ul></section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    html_path = OUT / "compare.html"
    html_path.write_text(page, encoding="utf-8")
    md = [
        "# WPBR zones within 22% above the entry zone",
        "",
        "Pivot Break and Retest (WPBR). Measurement only. No new filter.",
        "",
        "## What you asked",
        "",
        REQUEST_PROMPT.strip(),
        "",
        "## In plain English",
        "",
        LAYMAN,
        "",
        "## Bad cohort versus remaining trades",
        "",
        "| Measure | Bad cohort | Remaining trades | Bad minus remaining |",
        "| --- | --- | --- | --- |",
    ]
    for label, key, kind in rows_spec:
        bv, rv = bad[key], rest[key]
        if kind == "pct":
            cells = (_pct(bv), _pct(rv), _delta(bv, rv, "%"))
        elif kind == "num":
            cells = (_num(bv), _num(rv), _delta(bv, rv))
        else:
            cells = (str(int(bv)), str(int(rv)), str(int(bv) - int(rv)))
        md.append(f"| {label} | {cells[0]} | {cells[1]} | {cells[2]} |")
    md.extend(["", counts, "", "## Freeze", ""])
    md.extend(f"- {line}" for line in freeze)
    md_path = OUT / "BASELINE.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return html_path, md_path


def main() -> int:
    with FROZEN.open(newline="", encoding="utf-8-sig") as f:
        bad_syms = {str(r["SYMBOL"]).strip().upper() for r in csv.DictReader(f)}
    if len(bad_syms) != 40:
        raise SystemExit(f"frozen list has {len(bad_syms)} symbols, expected 40")
    grouped = load_trades(bad_syms)
    bad_n = sum(len(v) for sym, v in grouped.items() if sym in bad_syms)
    if bad_n != 335:
        raise SystemExit(f"frozen cohort has {bad_n} trades, expected 335")
    rows: list[dict[str, Any]] = []
    symbols = list(grouped.items())
    for i, (sym, trades) in enumerate(symbols, start=1):
        rows.extend(measure_symbol(sym, trades))
        if i % 100 == 0 or i == len(symbols):
            print(f"[zones] {i}/{len(symbols)}", flush=True)
    bad_rows = [r for r in rows if r["cohort"] == "bad"]
    rest_rows = [r for r in rows if r["cohort"] == "rest"]
    bad, rest, book = _stats(bad_rows), _stats(rest_rows), _stats(rows)
    missing = book["trades"] - book["measured"]
    OUT.mkdir(parents=True, exist_ok=True)
    feat = OUT / "trade_zone_counts.csv"
    with feat.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["symbol", "opened", "cohort", "measured", "zone_matched", "n_band", "n_still", "nearest"])
        w.writeheader()
        w.writerows(rows)
    html_path, md_path = write_page(bad, rest, book, missing)
    msg = (
        f"Bad cohort >=1 zone {_pct(bad['ge1'])}, median {_num(bad['median'])}. "
        f"Rest >=1 zone {_pct(rest['ge1'])}, median {_num(rest['median'])}."
    )
    print(f"[zones] {msg}", flush=True)
    print(f"[zones] wrote {html_path}", flush=True)
    _notify([html_path, md_path], msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
