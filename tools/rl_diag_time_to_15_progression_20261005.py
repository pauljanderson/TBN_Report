#!/usr/bin/env python3
"""RL diagnostic: time to +15% and forward progression on frozen DailyRun closed book.

Diagnostic only — does not change exits, targets, stops, filters, or trade logic.
Does not simulate a +15/+30 exit.

Usage:
  python tools/rl_diag_time_to_15_progression_20261005.py
"""
from __future__ import annotations

import html as html_mod
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from report_page_extras import SWIPE_NOTE_HTML  # noqa: E402

CLOSED_CSV = ROOT / "drive" / "RL_Closed_261005120747.csv"
STAMP = ROOT / "drive" / "paul_experiments" / "rl_diag_time_to_15_progression_20261005"
OUT_HTML = STAMP / "report.html"
OUT_CSV = STAMP / "per_trade_hit_timings.csv"
OUT_BASELINE = STAMP / "BASELINE.md"
DB_PATH = ROOT / "data" / "ohlcv.duckdb"
CSV_DIR = ROOT / "data" / "newdata" / "data"
IS_CUTOFF = "20240101"
LEVELS = (15, 20, 30, 40)

ORIGINAL_REQUEST = """RL DIAGNOSTIC ONLY — TIME TO +15% AND FORWARD PROGRESSION
Use the current frozen RL closed-trade population and current RL entry/exit architecture. Do not change any exits, targets, stops, filters, or trade logic. This is a diagnostic report only.
For every closed trade, calculate:
1. Did the trade ever reach +15% from entry?
2. If yes, number of trading bars and calendar days from entry to first +15%.
3. Of trades that reached +15%, did they subsequently reach +20%, +30%, and +40%?
4. For each subsequent level, report trading bars and calendar days from:
   - Entry → first +20%, +30%, +40%
   - First +15% → first +20%, +30%, +40%
5. For trades that reached +15% but never reached +30%, report:
   - Trade count
   - Final P&L
   - Exit reason
   - Total days held
6. Provide FULL / IS / OOS summaries.
7. For all timing measurements, provide count, average, median, and relevant percentile distribution.
Also provide conversion rates:
+15 → +20
+15 → +30
+15 → +40
The purpose is to determine whether +15% is reached materially earlier than the current +20% scale point and, once +15% is reached, how frequently and how quickly trades progress to +30%.
Do not simulate a +15/+30 exit structure yet. No optimization. Diagnostic only."""

LAYMAN = (
    "We are not changing how Rocket Launcher buys or sells. We only look at the finished trades "
    "and ask: how often does price get to +15% from the buy, how long does that take (market days "
    "and calendar days), and after that happens, how often / how fast does the same trade keep "
    "going to +20%, +30%, and +40% before it is already closed. The current book sells most of "
    "the position at +20% and aims leftovers at +40%; this page checks whether +15% shows up much "
    "earlier and whether +30% is a common next stop."
)


def days_diff(d1: str, d2: str) -> int:
    """Match rocket_rl / AWK days_diff (local midnight calendar days)."""

    def _epoch(d: str) -> int:
        t = time.struct_time((int(d[:4]), int(d[4:6]), int(d[6:8]), 0, 0, 0, 0, 0, -1))
        return int(time.mktime(t))

    return int((_epoch(d2) - _epoch(d1)) / 86400)


def _iso(d: Any) -> str:
    s = str(d).strip().replace("-", "").replace("/", "").replace(".0", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    raise ValueError(f"bad date: {d!r}")


def _parse_pnl_pct(v: Any) -> float:
    s = str(v).strip().replace("%", "").replace(",", "")
    if not s or s.lower() in {"nan", "none"}:
        return float("nan")
    return float(s)


def _pctiles(vals: list[float]) -> dict[str, float | int | None]:
    if not vals:
        return {
            "n": 0,
            "avg": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
        }
    a = np.asarray(vals, dtype=np.float64)
    qs = np.percentile(a, [10, 25, 50, 75, 90])
    return {
        "n": int(len(a)),
        "avg": float(np.mean(a)),
        "median": float(np.median(a)),
        "p10": float(qs[0]),
        "p25": float(qs[1]),
        "p50": float(qs[2]),
        "p75": float(qs[3]),
        "p90": float(qs[4]),
    }


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    if isinstance(v, (int, np.integer)):
        return f"{int(v)}"
    if isinstance(v, (float, np.floating)):
        if abs(v - round(v)) < 1e-9 and nd == 0:
            return f"{int(round(v))}"
        return f"{float(v):.{nd}f}"
    return str(v)


def _fmt_pct(v: Any, nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{100.0 * float(v):.{nd}f}%"


def _load_bars(symbols: list[str]) -> dict[str, tuple[list[str], np.ndarray]]:
    """Bulk High bars: prefer DuckDB, fill missing symbols from CSV."""
    out: dict[str, tuple[list[str], np.ndarray]] = {}
    syms = sorted({s.upper() for s in symbols if s})
    if DB_PATH.is_file():
        try:
            import duckdb

            con = duckdb.connect(str(DB_PATH), read_only=True)
            frame = con.execute(
                """
                SELECT upper(symbol) AS symbol, date, high
                FROM prices
                WHERE upper(symbol) IN (SELECT unnest(?))
                ORDER BY symbol, date
                """,
                [syms],
            ).df()
            con.close()
            if not frame.empty:
                frame["date"] = frame["date"].astype(str).str.replace("-", "", regex=False).str[:8]
                for sym, grp in frame.groupby("symbol", sort=False):
                    highs = grp["high"].to_numpy(dtype=np.float64)
                    out[str(sym)] = (grp["date"].tolist(), highs)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] DuckDB load failed ({exc}); falling back to CSV", flush=True)

    missing = [s for s in syms if s not in out]
    for sym in missing:
        path = CSV_DIR / f"{sym}.csv"
        if not path.is_file():
            matches = list(CSV_DIR.glob(f"{sym}.csv")) + list(CSV_DIR.glob(f"{sym.lower()}.csv"))
            path = matches[0] if matches else path
        if not path.is_file():
            continue
        df = pd.read_csv(path)
        dates = df["Date"].astype(str).str.replace("-", "", regex=False).str[:8].tolist()
        highs = df["High"].astype(float).to_numpy(dtype=np.float64)
        out[sym] = (dates, highs)
    return out


def _first_touch(
    dates: list[str],
    highs: np.ndarray,
    entry_iso: str,
    exit_iso: str,
    entry_px: float,
    pct: float,
    *,
    not_before_iso: str | None = None,
) -> tuple[str | None, int | None]:
    """First High >= entry*(1+pct/100) on [entry, exit], optionally not before not_before_iso.

    Returns (touch_ymd, absolute index in full series) or (None, None).
    """
    thr = entry_px * (1.0 + pct / 100.0)
    # Binary search bounds on sorted dates
    lo = 0
    hi = len(dates)
    # find first index with date >= entry
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] < entry_iso:
            lo = mid + 1
        else:
            hi = mid
    start = lo
    if start >= len(dates) or dates[start] < entry_iso:
        # linear fallback if unsorted-ish
        start = next((i for i, d in enumerate(dates) if d >= entry_iso), len(dates))
    if not_before_iso and not_before_iso > entry_iso:
        while start < len(dates) and dates[start] < not_before_iso:
            start += 1
    for i in range(start, len(dates)):
        d = dates[i]
        if d > exit_iso:
            break
        if highs[i] >= thr:
            return d, i
    return None, None


def _entry_idx(dates: list[str], entry_iso: str) -> int:
    try:
        return dates.index(entry_iso)
    except ValueError:
        for i, d in enumerate(dates):
            if d >= entry_iso:
                return i
        return -1


def analyze_trade(row: dict[str, Any], bars: dict[str, tuple[list[str], np.ndarray]]) -> dict[str, Any]:
    sym = str(row.get("SYMBOL") or "").strip().upper()
    entry_iso = _iso(row.get("DATE OPENED"))
    exit_iso = _iso(row.get("DATE CLOSED"))
    entry_px = float(str(row.get("ENTRY PRICE")).replace(",", ""))
    pnl = _parse_pnl_pct(row.get("PNL %"))
    try:
        days_held = int(float(row.get("DAYS HELD")))
    except (TypeError, ValueError):
        days_held = days_diff(entry_iso, exit_iso) + 1
    exit_type = str(row.get("EXIT TYPE") or "").strip()
    slice_tag = "IS" if entry_iso < IS_CUTOFF else "OOS"

    out: dict[str, Any] = {
        "SYMBOL": sym,
        "DATE_OPENED": entry_iso,
        "DATE_CLOSED": exit_iso,
        "ENTRY_PRICE": entry_px,
        "PNL_PCT": pnl,
        "DAYS_HELD": days_held,
        "EXIT_TYPE": exit_type,
        "SLICE": slice_tag,
        "HAS_BARS": 0,
        "HIT_15": 0,
        "HIT_20": 0,
        "HIT_30": 0,
        "HIT_40": 0,
        "DATE_15": "",
        "DATE_20": "",
        "DATE_30": "",
        "DATE_40": "",
        "BARS_ENTRY_15": "",
        "CAL_ENTRY_15": "",
        "BARS_ENTRY_20": "",
        "CAL_ENTRY_20": "",
        "BARS_ENTRY_30": "",
        "CAL_ENTRY_30": "",
        "BARS_ENTRY_40": "",
        "CAL_ENTRY_40": "",
        "BARS_15_20": "",
        "CAL_15_20": "",
        "BARS_15_30": "",
        "CAL_15_30": "",
        "BARS_15_40": "",
        "CAL_15_40": "",
        "BARS_15_THEN_20_EARLIER": "",
        "CAL_15_THEN_20_EARLIER": "",
    }

    pack = bars.get(sym)
    if pack is None:
        return out
    dates, highs = pack
    e_idx = _entry_idx(dates, entry_iso)
    if e_idx < 0:
        return out
    out["HAS_BARS"] = 1

    touches: dict[int, tuple[str | None, int | None]] = {}
    for lvl in LEVELS:
        touches[lvl] = _first_touch(dates, highs, entry_iso, exit_iso, entry_px, float(lvl))

    d15, i15 = touches[15]
    if d15 is not None and i15 is not None:
        out["HIT_15"] = 1
        out["DATE_15"] = d15
        out["BARS_ENTRY_15"] = (i15 - e_idx) + 1
        out["CAL_ENTRY_15"] = days_diff(entry_iso, d15) + 1

        # Subsequent levels must be on/after the +15 bar and on/before exit
        for lvl in (20, 30, 40):
            # Re-scan with not_before = d15 to enforce "on/after +15 bar"
            dX, iX = _first_touch(
                dates, highs, entry_iso, exit_iso, entry_px, float(lvl), not_before_iso=d15
            )
            # Also accept touch found without not_before if on/after d15
            d0, i0 = touches[lvl]
            if dX is None and d0 is not None and i0 is not None and d0 >= d15:
                dX, iX = d0, i0
            if dX is None or iX is None:
                continue
            out[f"HIT_{lvl}"] = 1
            out[f"DATE_{lvl}"] = dX
            out[f"BARS_ENTRY_{lvl}"] = (iX - e_idx) + 1
            out[f"CAL_ENTRY_{lvl}"] = days_diff(entry_iso, dX) + 1
            out[f"BARS_15_{lvl}"] = iX - i15  # 0 if same bar
            out[f"CAL_15_{lvl}"] = days_diff(d15, dX)  # 0 if same day

        if out["HIT_20"] == 1:
            out["BARS_15_THEN_20_EARLIER"] = out["BARS_15_20"]
            out["CAL_15_THEN_20_EARLIER"] = out["CAL_15_20"]
    else:
        # Still record absolute hits for +20/+30/+40 for reference (not used in conversion)
        for lvl in (20, 30, 40):
            dX, iX = touches[lvl]
            if dX is not None and iX is not None:
                out[f"HIT_{lvl}"] = 1
                out[f"DATE_{lvl}"] = dX
                out[f"BARS_ENTRY_{lvl}"] = (iX - e_idx) + 1
                out[f"CAL_ENTRY_{lvl}"] = days_diff(entry_iso, dX) + 1

    return out


def _slice_mask(df: pd.DataFrame, slice_name: str) -> pd.Series:
    if slice_name == "FULL":
        return pd.Series(True, index=df.index)
    if slice_name == "IS":
        return df["SLICE"] == "IS"
    if slice_name == "OOS":
        return df["SLICE"] == "OOS"
    raise ValueError(slice_name)


def summarize_slice(df: pd.DataFrame, slice_name: str) -> dict[str, Any]:
    m = _slice_mask(df, slice_name)
    sub = df.loc[m]
    n = len(sub)
    n_bars = int(sub["HAS_BARS"].sum())
    hit15 = sub[sub["HIT_15"] == 1]
    n15 = len(hit15)
    n20 = int((hit15["HIT_20"] == 1).sum())
    n30 = int((hit15["HIT_30"] == 1).sum())
    n40 = int((hit15["HIT_40"] == 1).sum())
    n15_not30 = int(((hit15["HIT_30"] != 1)).sum()) if n15 else 0

    def _col_stats(frame: pd.DataFrame, col: str) -> dict[str, float | int | None]:
        vals = [float(x) for x in frame[col].tolist() if str(x) not in {"", "nan", "None"}]
        return _pctiles(vals)

    both_15_20 = hit15[hit15["HIT_20"] == 1]

    return {
        "slice": slice_name,
        "n_trades": n,
        "n_with_bars": n_bars,
        "n_hit_15": n15,
        "pct_hit_15": (n15 / n) if n else None,
        "n_hit_20_among_15": n20,
        "n_hit_30_among_15": n30,
        "n_hit_40_among_15": n40,
        "conv_15_20": (n20 / n15) if n15 else None,
        "conv_15_30": (n30 / n15) if n15 else None,
        "conv_15_40": (n40 / n15) if n15 else None,
        "n_15_not_30": n15_not30,
        "bars_entry_15": _col_stats(hit15, "BARS_ENTRY_15"),
        "cal_entry_15": _col_stats(hit15, "CAL_ENTRY_15"),
        "bars_entry_20": _col_stats(both_15_20, "BARS_ENTRY_20"),
        "cal_entry_20": _col_stats(both_15_20, "CAL_ENTRY_20"),
        "bars_entry_30": _col_stats(hit15[hit15["HIT_30"] == 1], "BARS_ENTRY_30"),
        "cal_entry_30": _col_stats(hit15[hit15["HIT_30"] == 1], "CAL_ENTRY_30"),
        "bars_entry_40": _col_stats(hit15[hit15["HIT_40"] == 1], "BARS_ENTRY_40"),
        "cal_entry_40": _col_stats(hit15[hit15["HIT_40"] == 1], "CAL_ENTRY_40"),
        "bars_15_20": _col_stats(both_15_20, "BARS_15_20"),
        "cal_15_20": _col_stats(both_15_20, "CAL_15_20"),
        "bars_15_30": _col_stats(hit15[hit15["HIT_30"] == 1], "BARS_15_30"),
        "cal_15_30": _col_stats(hit15[hit15["HIT_30"] == 1], "CAL_15_30"),
        "bars_15_40": _col_stats(hit15[hit15["HIT_40"] == 1], "BARS_15_40"),
        "cal_15_40": _col_stats(hit15[hit15["HIT_40"] == 1], "CAL_15_40"),
        "exit_type_15_not_30": (
            hit15[hit15["HIT_30"] != 1]["EXIT_TYPE"].value_counts().to_dict() if n15_not30 else {}
        ),
        "pnl_15_not_30": _col_stats(hit15[hit15["HIT_30"] != 1], "PNL_PCT") if n15_not30 else _pctiles([]),
        "days_held_15_not_30": (
            _col_stats(hit15[hit15["HIT_30"] != 1], "DAYS_HELD") if n15_not30 else _pctiles([])
        ),
    }


def _stats_row(label: str, st: dict[str, float | int | None]) -> str:
    return (
        f"<tr><td>{html_mod.escape(label)}</td>"
        f"<td>{_fmt(st['n'], 0)}</td>"
        f"<td>{_fmt(st['avg'])}</td>"
        f"<td>{_fmt(st['median'])}</td>"
        f"<td>{_fmt(st['p10'])}</td>"
        f"<td>{_fmt(st['p25'])}</td>"
        f"<td>{_fmt(st['p50'])}</td>"
        f"<td>{_fmt(st['p75'])}</td>"
        f"<td>{_fmt(st['p90'])}</td></tr>"
    )


def _stats_headers() -> str:
    cols = [
        ("Measure", "text"),
        ("N", "num"),
        ("Avg", "num"),
        ("Median", "num"),
        ("P10", "num"),
        ("P25", "num"),
        ("P50", "num"),
        ("P75", "num"),
        ("P90", "num"),
    ]
    return "".join(sortable_th(a, b) for a, b in cols)


def build_html(summaries: dict[str, dict[str, Any]], detail: pd.DataFrame, missing_bars: int) -> str:
    conv_rows = []
    for name in ("FULL", "IS", "OOS"):
        s = summaries[name]
        conv_rows.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>{s['n_trades']}</td>"
            f"<td>{s['n_with_bars']}</td>"
            f"<td>{s['n_hit_15']}</td>"
            f"<td>{_fmt_pct(s['pct_hit_15'])}</td>"
            f"<td>{_fmt_pct(s['conv_15_20'])}</td>"
            f"<td>{_fmt_pct(s['conv_15_30'])}</td>"
            f"<td>{_fmt_pct(s['conv_15_40'])}</td>"
            f"<td>{s['n_15_not_30']}</td>"
            "</tr>"
        )
    conv_th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Slice", "text"),
            ("Trades", "num"),
            ("With bars", "num"),
            ("Hit +15%", "num"),
            ("% hit +15", "num"),
            ("+15→+20", "num"),
            ("+15→+30", "num"),
            ("+15→+40", "num"),
            ("+15 not +30", "num"),
        ]
    )

    timing_blocks = []
    for name in ("FULL", "IS", "OOS"):
        s = summaries[name]
        rows = [
            _stats_row("Trading bars entry→+15 (hitters)", s["bars_entry_15"]),
            _stats_row("Calendar days entry→+15 (hitters)", s["cal_entry_15"]),
            _stats_row("Trading bars entry→+20 (among +15 and +20)", s["bars_entry_20"]),
            _stats_row("Calendar days entry→+20 (among +15 and +20)", s["cal_entry_20"]),
            _stats_row("Trading bars entry→+30 (among converters)", s["bars_entry_30"]),
            _stats_row("Calendar days entry→+30 (among converters)", s["cal_entry_30"]),
            _stats_row("Trading bars entry→+40 (among converters)", s["bars_entry_40"]),
            _stats_row("Calendar days entry→+40 (among converters)", s["cal_entry_40"]),
            _stats_row("Trading bars +15→+20", s["bars_15_20"]),
            _stats_row("Calendar days +15→+20", s["cal_15_20"]),
            _stats_row("Trading bars +15→+30", s["bars_15_30"]),
            _stats_row("Calendar days +15→+30", s["cal_15_30"]),
            _stats_row("Trading bars +15→+40", s["bars_15_40"]),
            _stats_row("Calendar days +15→+40", s["cal_15_40"]),
        ]
        timing_blocks.append(
            f"<h3>{name} timing distributions</h3>"
            f"{SWIPE_NOTE_HTML}"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{_stats_headers()}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )

    # +15 not +30 exit-type breakdown (FULL)
    s_full = summaries["FULL"]
    exit_rows = []
    for et, cnt in sorted(s_full["exit_type_15_not_30"].items(), key=lambda kv: (-kv[1], kv[0])):
        exit_rows.append(f"<tr><td>{html_mod.escape(str(et))}</td><td>{cnt}</td></tr>")
    if not exit_rows:
        exit_rows = ["<tr><td>—</td><td>0</td></tr>"]
    exit_th = "".join(sortable_th(a, b) for a, b in [("EXIT TYPE", "text"), ("Count", "num")])

    subset_stats_rows = [
        _stats_row("Final PNL % (+15 not +30)", s_full["pnl_15_not_30"]),
        _stats_row("DAYS HELD (+15 not +30)", s_full["days_held_15_not_30"]),
    ]
    for name in ("IS", "OOS"):
        s = summaries[name]
        subset_stats_rows.append(
            _stats_row(f"Final PNL % (+15 not +30) {name}", s["pnl_15_not_30"])
        )
        subset_stats_rows.append(
            _stats_row(f"DAYS HELD (+15 not +30) {name}", s["days_held_15_not_30"])
        )

    # Detail table: +15 not +30 (cap for page size but keep sortable)
    not30 = detail[(detail["HIT_15"] == 1) & (detail["HIT_30"] != 1)].copy()
    not30 = not30.sort_values(["DATE_OPENED", "SYMBOL"])
    detail_th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("SYMBOL", "text"),
            ("DATE OPENED", "date"),
            ("DATE CLOSED", "date"),
            ("Slice", "text"),
            ("ENTRY", "num"),
            ("PNL %", "num"),
            ("DAYS HELD", "num"),
            ("EXIT TYPE", "text"),
            ("Cal entry→+15", "num"),
            ("Bars entry→+15", "num"),
            ("Hit +20", "text"),
            ("Hit +40", "text"),
            ("Cal entry→+20", "num"),
            ("Bars +15→+20", "num"),
        ]
    )
    detail_rows = []
    for _, r in not30.iterrows():
        detail_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['SYMBOL']))}</td>"
            f"<td>{r['DATE_OPENED'][:4]}-{r['DATE_OPENED'][4:6]}-{r['DATE_OPENED'][6:8]}</td>"
            f"<td>{r['DATE_CLOSED'][:4]}-{r['DATE_CLOSED'][4:6]}-{r['DATE_CLOSED'][6:8]}</td>"
            f"<td>{r['SLICE']}</td>"
            f"<td>{_fmt(r['ENTRY_PRICE'])}</td>"
            f"<td>{_fmt(r['PNL_PCT'])}</td>"
            f"<td>{_fmt(r['DAYS_HELD'], 0)}</td>"
            f"<td>{html_mod.escape(str(r['EXIT_TYPE']))}</td>"
            f"<td>{_fmt(r['CAL_ENTRY_15'], 0) if str(r['CAL_ENTRY_15']) != '' else '—'}</td>"
            f"<td>{_fmt(r['BARS_ENTRY_15'], 0) if str(r['BARS_ENTRY_15']) != '' else '—'}</td>"
            f"<td>{'Y' if r['HIT_20'] == 1 else 'N'}</td>"
            f"<td>{'Y' if r['HIT_40'] == 1 else 'N'}</td>"
            f"<td>{_fmt(r['CAL_ENTRY_20'], 0) if str(r['CAL_ENTRY_20']) != '' else '—'}</td>"
            f"<td>{_fmt(r['BARS_15_20'], 0) if str(r['BARS_15_20']) != '' else '—'}</td>"
            "</tr>"
        )

    both = detail[(detail["HIT_15"] == 1) & (detail["HIT_20"] == 1)]
    earlier_note = (
        f"Among trades that hit both +15% and +20% (FULL N={len(both)}): "
        f"median calendar days from +15→+20 = {_fmt(summaries['FULL']['cal_15_20']['median'])}; "
        f"median trading bars +15→+20 = {_fmt(summaries['FULL']['bars_15_20']['median'])}. "
        f"Median calendar entry→+15 = {_fmt(summaries['FULL']['cal_entry_15']['median'])} vs "
        f"entry→+20 = {_fmt(summaries['FULL']['cal_entry_20']['median'])}."
    )

    req_html = "<br/>".join(html_mod.escape(line) for line in ORIGINAL_REQUEST.splitlines())

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL diagnostic — time to +15% and forward progression</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:16px;color:#1c1b19;background:#faf9f7;line-height:1.45;max-width:1200px}}
h1{{font-size:1.45rem;margin:0 0 8px}}
h2{{font-size:1.15rem;margin:28px 0 8px;border-bottom:1px solid #ddd;padding-bottom:4px}}
h3{{font-size:1.02rem;margin:20px 0 6px}}
.callout{{background:#fff;border:1px solid #ddd;border-left:4px solid #3b6ea5;padding:12px 14px;margin:12px 0;border-radius:4px}}
.callout h2{{margin-top:0;border:0;font-size:1.05rem}}
.freeze{{background:#fff8e8;border:1px solid #e6d5a8;padding:12px 14px;margin:12px 0;border-radius:4px}}
.note{{color:#555;font-size:0.95rem}}
table.sortable{{border-collapse:collapse;background:#fff;font-size:13px}}
table.sortable th,table.sortable td{{border:1px solid #ddd;padding:6px 8px;text-align:left}}
table.sortable th{{background:#f0eee8}}
table.sortable td:nth-child(n+2){{text-align:right}}
{SORTABLE_TH_CSS}
code{{background:#f0eee8;padding:1px 4px;border-radius:3px}}
ul{{margin:6px 0 6px 1.2em}}
</style>
</head>
<body>
<h1>Rocket Launcher (RL) diagnostic — time to +15% and forward progression</h1>
<p class="note">Stamp <code>rl_diag_time_to_15_progression_20261005</code> · source
<code>drive/RL_Closed_261005120747.csv</code> · {summaries['FULL']['n_trades']} closed trades ·
diagnostic only (no exit / entry change)</p>

<div class="callout">
<h2>What you asked</h2>
<p>{req_html}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<div class="freeze">
<strong>Architecture freeze (document only — not altered)</strong>
<ul>
<li><strong>Exit</strong> (house freeze 2026-09-27 / partial exit strategy): sell 80% at +20% from entry
(<code>rl_scale_ladder=0.20:0.80:0</code>), leftover stop to entry (breakeven), leftover target +40%
(<code>rl_entry_target_pct=0.40</code>); Simple Moving Average (SMA) target off
(<code>rl_sma_target_off=1</code>); no time exit (<code>rl_exit_percent=0</code>,
<code>rl_exit_days=0</code>, <code>rl_exit_calendar_days=0</code>).</li>
<li><strong>Entries</strong>: current production RL dip book (document-only):
<code>rl_dip_pct=1.055</code>, expansion / stop / too-high as in DailyRun lock-in
(<code>rl_dailyrun_p80_be40_full_universe_20260927</code> / look-left control writeups). Not changed here.</li>
<li><strong>Universe</strong>: whatever symbols appear in the closed file above.</li>
<li><strong>Status</strong>: research diagnostic only. Not gold. Not a new exit. Do not simulate +15/+30 yet.</li>
</ul>
</div>

<h2>Method</h2>
<ul>
<li>For each closed trade, walk daily Open-High-Low-Close (OHLC) from DATE OPENED through DATE CLOSED (inclusive).</li>
<li>Reach +X% = first bar where <strong>High</strong> ≥ ENTRY PRICE × (1 + X/100). High, not Close.</li>
<li>Levels: 15, 20, 30, 40.</li>
<li>Calendar days entry→touch: <code>days_diff(entry, touch) + 1</code> (same inclusive convention as DAYS HELD / DAYS_TO_*).</li>
<li>Trading bars entry→touch: <code>(touch_idx − entry_idx) + 1</code>.</li>
<li>From first +15% → later level: calendar = <code>days_diff(d15, dX)</code> (0 if same day); bars = <code>idxX − idx15</code> (0 if same bar).</li>
<li>Subsequent hits only on/after the +15% bar and on/before DATE CLOSED (actual closed path; no look-past-exit).</li>
<li>Bars from DuckDB <code>data/ohlcv.duckdb</code> with CSV fallback under <code>data/newdata/data</code>.</li>
<li>In-sample (IS) = entry date &lt; 2024-01-01; out-of-sample (OOS) = entry date ≥ 2024-01-01. OOS is report-only.</li>
</ul>
<p class="note">Missing OHLC bars for {missing_bars} trade(s); those rows are excluded from hit timing but remain in trade counts.</p>
<p class="note">{html_mod.escape(earlier_note)}</p>

<h2>Conversion rates (among +15% hitters)</h2>
<p>Click column headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{conv_th}</tr></thead>
<tbody>{''.join(conv_rows)}</tbody>
</table>
</div>

<h2>Timing distributions</h2>
<p>Count, average, median, and P10/P25/P50/P75/P90 for every timing measure. Click headers to sort.</p>
{''.join(timing_blocks)}

<h2>Subset: reached +15% but never +30%</h2>
<p>FULL count = <strong>{s_full['n_15_not_30']}</strong>
(IS {summaries['IS']['n_15_not_30']}, OOS {summaries['OOS']['n_15_not_30']}).</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{_stats_headers()}</tr></thead>
<tbody>{''.join(subset_stats_rows)}</tbody>
</table>
</div>
<h3>EXIT TYPE breakdown (FULL, +15 not +30)</h3>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{exit_th}</tr></thead>
<tbody>{''.join(exit_rows)}</tbody>
</table>
</div>
<h3>Detail table (+15% hit, never +30% on the closed path)</h3>
<p>N={len(not30)}. Click headers to sort.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>{detail_th}</tr></thead>
<tbody>{''.join(detail_rows)}</tbody>
</table>
</div>

<p class="note">Per-trade hit timings CSV: <code>per_trade_hit_timings.csv</code> in this stamp folder.</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def write_baseline(summaries: dict[str, dict[str, Any]], n_trades: int, missing_bars: int) -> str:
    s = summaries["FULL"]
    return f"""# RL diagnostic — time to +15% and forward progression

Date: 2026-10-05
Status: **diagnostic / reporting only**. No entry, exit, target, stop, filter, or trade-logic change.
Not gold. Not DailyRun. Do **not** simulate a +15/+30 exit from this page.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Source population

| Item | Value |
|---|---|
| Closed book | `drive/RL_Closed_261005120747.csv` |
| Closed trades | {n_trades} |
| Missing OHLC | {missing_bars} |
| Universe | Symbols present in that closed file |

## Architecture freeze (document only)

| Item | Value |
|---|---|
| Exit (house freeze 2026-09-27 / partial exit strategy) | Sell 80% at +20% (`rl_scale_ladder=0.20:0.80:0`), leftover stop to entry (breakeven), leftover +40% (`rl_entry_target_pct=0.40`), SMA target off (`rl_sma_target_off=1`), no time exit |
| Entries | Current production RL dip book (DailyRun / look-left writeups): `rl_dip_pct=1.055`, etc. Not changed |
| SMA | Simple Moving Average |

## Method

Matches house milestone rules from `tools/enrich_rl_closed_days_to_25.py`:

1. Walk daily OHLC from DATE OPENED through DATE CLOSED (inclusive).
2. Reach +X% = first bar where High ≥ ENTRY × (1 + X/100). High, not Close.
3. Levels: 15, 20, 30, 40.
4. Prefer DuckDB `data/ohlcv.duckdb`; fallback CSV under `data/newdata/data`.
5. Calendar days entry→touch: `days_diff(entry, touch) + 1`.
6. Trading bars entry→touch: `(touch_idx - entry_idx) + 1`.
7. From +15 → later: calendar `days_diff(d15, dX)` (0 same day); bars `idxX - idx15` (0 same bar).
8. Subsequent hits only on/after the +15% bar and on/before DATE CLOSED.

## IS / OOS

- IS = `DATE OPENED` &lt; 2024-01-01
- OOS = `DATE OPENED` ≥ 2024-01-01 (report-only; no retune)

## FULL headline numbers

| Metric | Value |
|---|---|
| Hit +15% | {s['n_hit_15']} / {s['n_trades']} ({_fmt_pct(s['pct_hit_15'])}) |
| +15→+20 | {_fmt_pct(s['conv_15_20'])} |
| +15→+30 | {_fmt_pct(s['conv_15_30'])} |
| +15→+40 | {_fmt_pct(s['conv_15_40'])} |
| +15 not +30 | {s['n_15_not_30']} |
| Median cal days entry→+15 | {_fmt(s['cal_entry_15']['median'])} |
| Median bars entry→+15 | {_fmt(s['bars_entry_15']['median'])} |
| Median cal days entry→+20 (among +15∩+20) | {_fmt(s['cal_entry_20']['median'])} |
| Median bars entry→+20 (among +15∩+20) | {_fmt(s['bars_entry_20']['median'])} |
| Median cal +15→+30 (converters) | {_fmt(s['cal_15_30']['median'])} |
| Median bars +15→+30 (converters) | {_fmt(s['bars_15_30']['median'])} |

## Artifacts

- `report.html` — sortable phone-friendly report
- `per_trade_hit_timings.csv` — one row per closed trade
- `tools/rl_diag_time_to_15_progression_20261005.py` — generator
"""


def main() -> int:
    STAMP.mkdir(parents=True, exist_ok=True)
    if not CLOSED_CSV.is_file():
        print(f"Missing closed CSV: {CLOSED_CSV}", file=sys.stderr)
        return 1

    raw = pd.read_csv(CLOSED_CSV)
    print(f"Loaded {len(raw)} closed trades from {CLOSED_CSV.name}", flush=True)
    symbols = [str(s).strip().upper() for s in raw["SYMBOL"].tolist()]
    print(f"Loading OHLC for {len(set(symbols))} symbols…", flush=True)
    bars = _load_bars(symbols)
    print(f"Bars loaded for {len(bars)} symbols", flush=True)

    rows = []
    for i, rec in enumerate(raw.to_dict("records")):
        rows.append(analyze_trade(rec, bars))
        if (i + 1) % 500 == 0:
            print(f"  analyzed {i+1}/{len(raw)}", flush=True)
    detail = pd.DataFrame(rows)
    missing_bars = int((detail["HAS_BARS"] == 0).sum())
    print(f"Done. Missing bars: {missing_bars}", flush=True)

    detail.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}", flush=True)

    summaries = {name: summarize_slice(detail, name) for name in ("FULL", "IS", "OOS")}
    html = build_html(summaries, detail, missing_bars)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_HTML}", flush=True)

    OUT_BASELINE.write_text(write_baseline(summaries, len(detail), missing_bars), encoding="utf-8")
    print(f"Wrote {OUT_BASELINE}", flush=True)

    for name in ("FULL", "IS", "OOS"):
        s = summaries[name]
        print(
            f"{name}: N={s['n_trades']} hit15={s['n_hit_15']} "
            f"conv20={_fmt_pct(s['conv_15_20'])} conv30={_fmt_pct(s['conv_15_30'])} "
            f"conv40={_fmt_pct(s['conv_15_40'])} "
            f"med_cal_e15={_fmt(s['cal_entry_15']['median'])} "
            f"med_bars_e15={_fmt(s['bars_entry_15']['median'])} "
            f"med_cal_e20={_fmt(s['cal_entry_20']['median'])} "
            f"med_bars_15_30={_fmt(s['bars_15_30']['median'])} "
            f"n15_not30={s['n_15_not_30']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
