#!/usr/bin/env python3
"""WPBR structural diagnostic: prior price vs qualifying overhead zones.

Classification / reporting only. Does not change entries, exits, or DailyRun.
Reuses the Day-40 A/B control closed book (stamp 261002172253).
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    format_money,
    overlay_ann_ror_max_dd,
)
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SWIPE_NOTE_HTML,
    inject_report_page_extras,
)
from _gen_too_high_diff import SORTABLE_TH_CSS, sortable_th  # noqa: E402
from wpbr_zones import compute_wpbr_touch_stream  # noqa: E402

CLOSED = (
    ROOT
    / "tmp_wpbr_day40_vel10_ab_20261002"
    / "control"
    / "WPBR_Closed_261002172253.csv"
)
REPORT = (
    ROOT
    / "tmp_wpbr_day40_vel10_ab_20261002"
    / "control"
    / "WPBR_Report_261002172253.csv"
)
DB = ROOT / "data" / "ohlcv.duckdb"
OUT = ROOT / "drive" / "paul_experiments" / "wpbr_structure_prior_overhead_diag_20261003"
IS_CUT = date(2024, 1, 1)

REQUEST_QUOTE = (
    "Run a WPBR structural diagnostic on the current research system. Do not change any "
    "entry, exit, overhead, target, stop, sizing, or execution logic. This is "
    "classification/reporting only.\n"
    "For every WPBR trade, use the pivot bar that created the active WPBR entry zone as "
    "the historical cutoff. Only price history strictly before that pivot bar may be used "
    "for this diagnostic.\n"
    "Classify every trade into exactly one mutually exclusive group:\n"
    "GROUP 1 — NO PRIOR PRICE ABOVE: No historical HIGH before the active-zone pivot bar "
    "exceeded the active WPBR zone upper edge.\n"
    "GROUP 2 — PRIOR PRICE ABOVE / NO QUALIFYING OVERHEAD ZONE: At least one historical "
    "HIGH before the active-zone pivot bar exceeded the active zone upper edge, but no "
    "qualifying prior WPBR overhead zone exists above the active zone under the existing "
    "WPBR zone definition.\n"
    "GROUP 3 — PRIOR PRICE ABOVE / QUALIFYING OVERHEAD ZONE: At least one historical HIGH "
    "before the active-zone pivot bar exceeded the active zone upper edge, and at least "
    "one qualifying prior WPBR overhead zone exists above the active zone under the "
    "existing WPBR zone definition.\n"
    "Do not add a distance threshold for this diagnostic. Group 3 means any qualifying "
    "overhead WPBR zone above the active zone, regardless of distance.\n"
    "Report IS / OOS / FULL separately for each group: N, % of trades, WR, Avg P&L %, PF, "
    "expectancy, Avg Winner %, Avg Loser %, Max DD, corrected Ann ROR, Calmar, Sharpe, "
    "Avg Days Held, Median Days Held, Capital Days, PPCD, and Trades/Year.\n"
    "Also report a reconciliation showing Group 1 + Group 2 + Group 3 = all classified trades.\n"
    "Do not optimize anything and do not create a new filter. The purpose is only to "
    "determine whether WPBR performance differs between true price discovery, historical "
    "price overhead without a qualifying resistance zone, and historical price overhead "
    "with a qualifying WPBR resistance zone."
)

WPBR_KW = dict(
    band_pct=0.015,
    band_pct_atr=0.0,
    strong_pre_pivot_bars=3,
    strong_pre_pivot_pct=0.10,
    strong_pre_pivot_pct_atr=0.0,
    strong_post_pivot_bars=3,
    strong_post_pivot_pct=0.10,
    strong_post_pivot_pct_atr=0.0,
    strong_pivot_mode="either",
    breakout_confirmation=0.03,
    max_days_after_retest=2,
    retest_mode="stop_looking",
    merge_overlapping_zones=False,
)

G1 = "GROUP 1"
G2 = "GROUP 2"
G3 = "GROUP 3"
UNCL = "UNCLASSIFIED"
GROUP_LABELS = {
    G1: "GROUP 1 — NO PRIOR PRICE ABOVE",
    G2: "GROUP 2 — PRIOR PRICE ABOVE / NO QUALIFYING OVERHEAD ZONE",
    G3: "GROUP 3 — PRIOR PRICE ABOVE / QUALIFYING OVERHEAD ZONE",
    UNCL: "UNCLASSIFIED",
}


def _f(raw: Any, default: float = float("nan")) -> float:
    if raw is None:
        return default
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null", ""}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _ymd_date(raw: Any) -> date | None:
    s = str(raw or "").strip().replace("-", "").replace("/", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def parse_zone_id(zid: str) -> tuple[date | None, float, float]:
    parts = str(zid or "").strip().split("|")
    if len(parts) < 3:
        return None, float("nan"), float("nan")
    try:
        pivot = datetime.strptime(parts[0][:10], "%Y-%m-%d").date()
    except ValueError:
        pivot = None
    return pivot, _f(parts[1]), _f(parts[2])


def pivot_monday_from_friday(fri: date) -> date:
    return fri - timedelta(days=4)


def load_report_cash(path: Path) -> tuple[float, float]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    cap = _f(row.get("capacity_brt_cash"))
    init = _f(row.get("initial_capital"), DEFAULT_INITIAL_ACCOUNT)
    if not math.isfinite(init) or init <= 0:
        init = DEFAULT_INITIAL_ACCOUNT
    return cap, init


def load_closed(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        opened = _ymd_date(r.get("DATE_OPENED"))
        closed = _ymd_date(r.get("DATE_CLOSED"))
        zid = str(r.get("WPBR_ZONE_ID") or "").strip()
        pivot_id, lo_id, hi_id = parse_zone_id(zid)
        out.append(
            {
                "idx": i,
                "symbol": str(r.get("SYMBOL") or "").strip().upper(),
                "opened": opened,
                "closed": closed,
                "exit": str(r.get("EXIT_TYPE") or "").strip(),
                "pnl_pct": _f(r.get("PNL_PCT")),
                "pnl_d": _f(r.get("PNL_DOLLARS")),
                "days": _f(r.get("DAYS_HELD")),
                "zone_top": _f(r.get("ZONE_TOP"), hi_id),
                "zone_bottom": _f(r.get("ZONE_BOTTOM"), lo_id),
                "wpbr_zone_id": zid,
                "pivot_week_end": pivot_id,
            }
        )
    return out


def load_prices(symbols: list[str]) -> dict[str, pd.DataFrame]:
    import duckdb

    con = duckdb.connect(str(DB), read_only=True)
    try:
        con.register("syms", pd.DataFrame({"symbol": symbols}))
        raw = con.execute(
            """
            SELECT
                symbol,
                date AS Date,
                open AS Open,
                high AS High,
                low AS Low,
                close AS Close,
                volume AS Volume
            FROM prices
            WHERE symbol IN (SELECT symbol FROM syms)
            ORDER BY symbol, date
            """
        ).fetchdf()
    finally:
        con.close()
    if raw.empty:
        return {}
    raw["Date"] = pd.to_datetime(raw["Date"])
    for col in ("Open", "High", "Low", "Close"):
        raw[col] = raw[col].astype("float64").round(6)
    out: dict[str, pd.DataFrame] = {}
    for sym, g in raw.groupby("symbol", sort=False):
        df = g.drop(columns=["symbol"]).set_index("Date")
        out[str(sym).upper()] = df
    return out


def build_zone_inventory(prices: dict[str, pd.DataFrame]) -> dict[str, list[dict[str, Any]]]:
    inv: dict[str, list[dict[str, Any]]] = {}
    n = len(prices)
    t0 = time.perf_counter()
    for i, (sym, df) in enumerate(sorted(prices.items()), start=1):
        if df is None or df.empty:
            inv[sym] = []
            continue
        stream = compute_wpbr_touch_stream(df, **WPBR_KW)
        events = []
        for ev in stream.get("wpbr_zone_events") or []:
            zid = str(ev.get("wpbr_zone_id") or "")
            pwe = str(ev.get("pivot_week_end") or "")[:10]
            pm = str(ev.get("pivot_monday") or "")[:10]
            try:
                pwe_d = datetime.strptime(pwe, "%Y-%m-%d").date() if pwe else None
            except ValueError:
                pwe_d = None
            try:
                pm_d = datetime.strptime(pm, "%Y-%m-%d").date() if pm else None
            except ValueError:
                pm_d = None
            events.append(
                {
                    "wpbr_zone_id": zid,
                    "pivot_week_end": pwe_d,
                    "pivot_monday": pm_d,
                    "zone_lower": float(ev.get("zone_lower") or ev.get("zone_lower_f") or np.nan),
                    "zone_upper": float(ev.get("zone_upper") or ev.get("zone_upper_f") or np.nan),
                }
            )
        inv[sym] = events
        if i % 50 == 0 or i == n:
            dt = time.perf_counter() - t0
            print(f"  zones {i}/{n} symbols  {dt:.1f}s", flush=True)
    return inv


def prior_max_high(df: pd.DataFrame, cutoff: date) -> float:
    if df is None or df.empty or cutoff is None:
        return float("nan")
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return float("nan")
    cut = np.datetime64(cutoff.isoformat())
    dates = idx.values.astype("datetime64[D]")
    mask = dates < cut
    if not np.any(mask):
        return float("nan")
    hi = df["High"].to_numpy(dtype=np.float64)[mask]
    hi = hi[np.isfinite(hi)]
    if hi.size == 0:
        return float("nan")
    return float(np.max(hi))


def count_overhead(
    events: list[dict[str, Any]],
    *,
    active_id: str,
    active_upper: float,
    active_pivot: date,
) -> int:
    if not events or active_pivot is None or not np.isfinite(active_upper):
        return 0
    n = 0
    for ev in events:
        zid = ev.get("wpbr_zone_id") or ""
        if zid and zid == active_id:
            continue
        pwe = ev.get("pivot_week_end")
        if pwe is None or pwe >= active_pivot:
            continue
        lo = ev.get("zone_lower")
        try:
            lo_f = float(lo)
        except (TypeError, ValueError):
            continue
        if np.isfinite(lo_f) and lo_f > active_upper:
            n += 1
    return n


def classify_trade(
    t: dict[str, Any],
    prices: dict[str, pd.DataFrame],
    inventory: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    reason = ""
    group = UNCL
    prior_hi = float("nan")
    n_oh = 0
    pivot_week = t.get("pivot_week_end")
    pivot_mon = pivot_monday_from_friday(pivot_week) if pivot_week else None
    zid = t.get("wpbr_zone_id") or ""
    upper = t.get("zone_top")
    sym = t.get("symbol") or ""
    events = inventory.get(sym) or []

    matched = None
    if zid:
        for ev in events:
            if ev.get("wpbr_zone_id") == zid:
                matched = ev
                break
    if matched is None and pivot_week is not None and np.isfinite(upper):
        for ev in events:
            if ev.get("pivot_week_end") == pivot_week and np.isfinite(ev.get("zone_upper", np.nan)):
                if abs(float(ev["zone_upper"]) - float(upper)) <= 1e-4:
                    matched = ev
                    break
    if matched is not None:
        if matched.get("pivot_week_end"):
            pivot_week = matched["pivot_week_end"]
        if matched.get("pivot_monday"):
            pivot_mon = matched["pivot_monday"]
        if np.isfinite(matched.get("zone_upper", np.nan)) and not np.isfinite(upper):
            upper = float(matched["zone_upper"])

    if not zid and (pivot_week is None or not np.isfinite(upper)):
        reason = "missing_zone"
    elif pivot_week is None or pivot_mon is None:
        reason = "missing_pivot"
    elif not np.isfinite(upper) or upper <= 0:
        reason = "missing_zone_top"
    elif sym not in prices or prices[sym] is None or prices[sym].empty:
        reason = "missing_bars"
    else:
        df = prices[sym]
        # Need at least some history in the warehouse (not necessarily pre-pivot).
        prior_hi = prior_max_high(df, pivot_mon)
        n_oh = count_overhead(
            events, active_id=zid, active_upper=float(upper), active_pivot=pivot_week
        )
        # Empty pre-pivot history = no prior high above (true discovery / IPO-like).
        if not np.isfinite(prior_hi):
            prior_price_above = False
        else:
            prior_price_above = prior_hi > float(upper)
        if not prior_price_above:
            group = G1
        elif n_oh <= 0:
            group = G2
        else:
            group = G3
        reason = ""

    opened = t.get("opened")
    slice_name = "OOS" if opened is not None and opened >= IS_CUT else "IS"
    if opened is None:
        slice_name = "UNDATED"
        if group != UNCL:
            group = UNCL
            reason = "missing_open_date"

    return {
        **t,
        "group": group,
        "unclassified_reason": reason,
        "pivot_week_end": pivot_week,
        "pivot_monday": pivot_mon,
        "prior_max_high": prior_hi,
        "n_overhead_zones": n_oh,
        "slice": slice_name,
        "active_upper": upper,
    }


def slice_years(trades: list[dict[str, Any]]) -> float:
    opens = [t["opened"] for t in trades if t.get("opened")]
    if len(opens) < 2:
        return float("nan")
    span = (max(opens) - min(opens)).days / 365.25
    return span if span > 0 else float("nan")


def metrics_for(
    trades: list[dict[str, Any]],
    *,
    brt_cash: float,
    initial_account: float,
    pct_base: int,
    slice_span_years: float,
) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n": 0,
        "pct_of_slice": 0.0,
        "wr": float("nan"),
        "avg_pnl_pct": float("nan"),
        "pf": float("nan"),
        "expectancy": float("nan"),
        "avg_win_pct": float("nan"),
        "avg_loss_pct": float("nan"),
        "max_dd": float("nan"),
        "ann_ror": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "avg_days": float("nan"),
        "median_days": float("nan"),
        "capital_days": 0.0,
        "ppcd": float("nan"),
        "trades_per_year": float("nan"),
        "sharpe_source": "",
        "overlay_note": "no trades",
    }
    if n <= 0:
        return empty
    pnls = [float(t["pnl_pct"]) for t in trades if np.isfinite(t.get("pnl_pct", np.nan))]
    days = [float(t["days"]) for t in trades if np.isfinite(t.get("days", np.nan))]
    dol = [float(t["pnl_d"]) for t in trades if np.isfinite(t.get("pnl_d", np.nan))]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    wr = (100.0 * len(wins) / n) if n else float("nan")
    avg = float(np.mean(pnls)) if pnls else float("nan")
    avg_w = float(np.mean(wins)) if wins else float("nan")
    avg_l = float(np.mean(losses)) if losses else float("nan")
    win_d = sum(x for x in dol if x > 0)
    loss_d = abs(sum(x for x in dol if x < 0))
    if loss_d > 0:
        pf = win_d / loss_d
    else:
        pf = win_d if win_d > 0 else 0.0
    cap_days = float(sum(d for d in days if d > 0))
    avg_days = float(np.mean(days)) if days else float("nan")
    med_days = float(np.median(days)) if days else float("nan")
    total_d = float(sum(dol)) if dol else 0.0
    ppcd = (total_d / cap_days) if cap_days > 0 else float("nan")
    overlay_rows = [
        {
            "pnl_d": t.get("pnl_d"),
            "days": t.get("days"),
            "closed": t.get("closed"),
            "opened": t.get("opened"),
            "pnl": t.get("pnl_pct"),
        }
        for t in trades
    ]
    ov = overlay_ann_ror_max_dd(
        overlay_rows,
        cash=brt_cash,
        initial_account=initial_account,
        equity_curve_path=None,
    )
    tpy = float("nan")
    if np.isfinite(slice_span_years) and slice_span_years > 0:
        tpy = n / slice_span_years
    pct = (100.0 * n / pct_base) if pct_base else 0.0
    house_ann = ann_ror_from_closed(
        total_pnl=total_d,
        n_trades=n,
        avg_days_held=avg_days if np.isfinite(avg_days) else 0.0,
        brt_cash=brt_cash,
    )
    return {
        "n": n,
        "pct_of_slice": pct,
        "wr": wr,
        "avg_pnl_pct": avg,
        "pf": pf,
        "expectancy": avg,
        "avg_win_pct": avg_w,
        "avg_loss_pct": avg_l,
        "max_dd": ov.get("max_dd"),
        "ann_ror": house_ann if house_ann is not None else ov.get("ann_ror"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "avg_days": avg_days,
        "median_days": med_days,
        "capital_days": cap_days,
        "ppcd": ppcd,
        "trades_per_year": tpy,
        "sharpe_source": ov.get("sharpe_source") or "",
        "overlay_note": ov.get("note") or "",
    }


def fmt_n(v: Any) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    return f"{int(v)}"


def fmt_num(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    return f"{x:.{nd}f}"


def fmt_pct(v: Any, nd: int = 2) -> str:
    s = fmt_num(v, nd)
    return "—" if s == "—" else f"{s}%"


def write_classified_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    cols = [
        "symbol",
        "opened",
        "group",
        "slice",
        "pnl",
        "exit",
        "zone_top",
        "pivot_date",
        "prior_max_high",
        "n_overhead_zones",
        "unclassified_reason",
        "wpbr_zone_id",
        "pivot_monday",
        "pnl_dollars",
        "days_held",
        "closed",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in rows:
            w.writerow(
                {
                    "symbol": t.get("symbol"),
                    "opened": _iso(t.get("opened")),
                    "group": t.get("group"),
                    "slice": t.get("slice"),
                    "pnl": t.get("pnl_pct"),
                    "exit": t.get("exit"),
                    "zone_top": t.get("active_upper") if t.get("active_upper") is not None else t.get("zone_top"),
                    "pivot_date": _iso(t.get("pivot_week_end")),
                    "prior_max_high": t.get("prior_max_high"),
                    "n_overhead_zones": t.get("n_overhead_zones"),
                    "unclassified_reason": t.get("unclassified_reason"),
                    "wpbr_zone_id": t.get("wpbr_zone_id"),
                    "pivot_monday": _iso(t.get("pivot_monday")),
                    "pnl_dollars": t.get("pnl_d"),
                    "days_held": t.get("days"),
                    "closed": _iso(t.get("closed")),
                }
            )


METRIC_SPECS = [
    ("N", "n", "num", "n"),
    ("% of classified trades", "pct_of_slice", "num", "pct"),
    ("WR", "wr", "num", "pct"),
    ("Avg P&L %", "avg_pnl_pct", "num", "pct"),
    ("PF", "pf", "num", "num2"),
    ("Expectancy (Avg P&L %)", "expectancy", "num", "pct"),
    ("Avg Winner %", "avg_win_pct", "num", "pct"),
    ("Avg Loser %", "avg_loss_pct", "num", "pct"),
    ("Max DD", "max_dd", "num", "pct"),
    ("Ann ROR", "ann_ror", "num", "pct"),
    ("Calmar", "calmar", "num", "num2"),
    ("Sharpe", "sharpe", "num", "num2"),
    ("Avg Days Held", "avg_days", "num", "num1"),
    ("Median Days Held", "median_days", "num", "num1"),
    ("Capital Days", "capital_days", "num", "n"),
    ("PPCD", "ppcd", "num", "money"),
    ("Trades/Year", "trades_per_year", "num", "num2"),
]


def cell(m: dict[str, Any], key: str, kind: str) -> str:
    v = m.get(key)
    if kind == "n":
        return fmt_n(v)
    if kind == "pct":
        return fmt_pct(v)
    if kind == "num1":
        return fmt_num(v, 1)
    if kind == "num2":
        return fmt_num(v, 2)
    if kind == "money":
        return format_money(v)
    return fmt_num(v)


def table_metrics(title: str, cols: list[tuple[str, dict[str, Any]]]) -> str:
    heads = sortable_th("Metric", "text") + "".join(
        sortable_th(name, "num") for name, _ in cols
    )
    body = []
    for label, key, sort, kind in METRIC_SPECS:
        tds = "".join(f"<td>{cell(m, key, kind)}</td>" for _, m in cols)
        body.append(f"<tr><td>{html_mod.escape(label)}</td>{tds}</tr>")
    return f"""
<h2>{html_mod.escape(title)}</h2>
<p class="sub">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{heads}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
</div>
"""


def table_recon(title: str, rows: list[tuple[str, int, int]]) -> str:
    heads = (
        sortable_th("Bucket", "text")
        + sortable_th("N", "num")
        + sortable_th("% of slice closed book", "num")
    )
    body = []
    for i, (name, n, total) in enumerate(rows):
        pct = (100.0 * n / total) if total else 0.0
        cls = ' class="total-row"' if i == len(rows) - 1 else ""
        body.append(
            f"<tr{cls}><td>{html_mod.escape(name)}</td><td>{n}</td><td>{fmt_pct(pct)}</td></tr>"
        )
    return f"""
<h2>{html_mod.escape(title)}</h2>
<p class="sub">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{heads}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
</div>
"""


def table_headline(blocks: dict[str, dict[str, dict[str, Any]]]) -> str:
    heads = "".join(
        [
            sortable_th("Group", "text"),
            sortable_th("Slice", "text"),
            sortable_th("N", "num"),
            sortable_th("% of classified", "num"),
            sortable_th("WR", "num"),
            sortable_th("Avg P&L %", "num"),
            sortable_th("PF", "num"),
            sortable_th("Ann ROR", "num"),
            sortable_th("Max DD", "num"),
            sortable_th("Calmar", "num"),
            sortable_th("Sharpe", "num"),
            sortable_th("Avg Days", "num"),
            sortable_th("PPCD", "num"),
            sortable_th("Trades/Year", "num"),
        ]
    )
    body = []
    for g in (G1, G2, G3):
        for sl in ("FULL", "IS", "OOS"):
            m = blocks[g][sl]
            body.append(
                "<tr>"
                f"<td>{html_mod.escape(GROUP_LABELS[g])}</td>"
                f"<td>{sl}</td>"
                f"<td>{fmt_n(m['n'])}</td>"
                f"<td>{fmt_pct(m['pct_of_slice'])}</td>"
                f"<td>{fmt_pct(m['wr'])}</td>"
                f"<td>{fmt_pct(m['avg_pnl_pct'])}</td>"
                f"<td>{fmt_num(m['pf'])}</td>"
                f"<td>{fmt_pct(m['ann_ror'])}</td>"
                f"<td>{fmt_pct(m['max_dd'])}</td>"
                f"<td>{fmt_num(m['calmar'])}</td>"
                f"<td>{fmt_num(m['sharpe'])}</td>"
                f"<td>{fmt_num(m['avg_days'], 1)}</td>"
                f"<td>{format_money(m['ppcd'])}</td>"
                f"<td>{fmt_num(m['trades_per_year'])}</td>"
                "</tr>"
            )
    return f"""
<h2>Headline — group × slice</h2>
<p class="sub">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{heads}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
</div>
"""


def write_summary_csv(path: Path, blocks: dict[str, dict[str, dict[str, Any]]]) -> None:
    fields = ["group", "slice"] + [k for _, k, _, _ in METRIC_SPECS] + ["sharpe_source", "overlay_note"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for g in (G1, G2, G3, UNCL, "ALL_CLASSIFIED", "ALL_CLOSED"):
            if g not in blocks:
                continue
            for sl in ("FULL", "IS", "OOS"):
                if sl not in blocks[g]:
                    continue
                m = dict(blocks[g][sl])
                m["group"] = g
                m["slice"] = sl
                w.writerow({k: m.get(k, "") for k in fields})


def write_baseline(
    path: Path,
    *,
    n_closed: int,
    n_uncl: int,
    reasons: dict[str, int],
    recon_ok: bool,
    brt_cash: float,
    initial_account: float,
) -> None:
    path.write_text(
        f"""# WPBR structure / prior-overhead diagnostic — freeze

Date: 2026-10-03
Status: **classification / reporting only**. No entry, exit, overhead, target, stop, sizing, or execution change. Not a filter. Not gold. Not DailyRun.

## Book

- Closed: `tmp_wpbr_day40_vel10_ab_20261002/control/WPBR_Closed_261002172253.csv`
- Report: `tmp_wpbr_day40_vel10_ab_20261002/control/WPBR_Report_261002172253.csv`
- Stamp: `261002172253`
- Same control used in the Day-40 A/Bs.
- Closed trades reused; `rocket_tbn` was **not** rerun.

## Research freeze (identity only)

- Pivot Break and Retest (WPBR), weekly pivot zones
- `wpbr_overhead_band_pct=0.22` (22% overhead skip) — **this diagnostic does not apply that cap**
- `target_pct=1.20` (+20% target)
- `stop_pct=0.92` (−8% of trigger-day low; `stop_loss_based=trigger_low`, `stop_pct_is_multiplier=true`)
- `growth_filter_enabled=false`
- `wpbr_velocity_time_stop_bars=0` / no velocity exit
- `wpbr_underwater_time_stop_bars=0` / no Day-40 underwater exit
- Zone knobs: `band_pct=0.015`, strong pivot either 3/10% pre or post, `wpbr_breakout_confirmation=0.03`, `wpbr_max_days_after_retest=2`, `wpbr_retest_mode=stop_looking`, `wpbr_merge_overlapping_zones=false`

## Classification rules

Active zone = the WPBR zone on the closed trade (`WPBR_ZONE_ID`, `ZONE_TOP`).
Active-zone pivot bar = weekly pivot that created that zone (`pivot_week_end` in the zone id / `wpbr_zone_events`). Daily cutoff is **strictly before** that week’s Monday (`pivot_monday` / `activation_bar` in `wpbr_zones.py`). The pivot week itself is excluded so the weekly pivot bar’s highs are not used as “prior” price.

Prior price above: `max(High)` on DuckDB `data/ohlcv.duckdb` `prices` with `date < pivot_monday` **>** active `ZONE_TOP`.

Qualifying prior WPBR overhead zone (existing WPBR zone definition, **no distance cap**):
- earlier zone from `compute_wpbr_touch_stream` / `wpbr_zone_events` (same knobs as freeze)
- creating pivot week strictly before the active-zone pivot week
- `prior_zone_lower > active_zone_upper`
- **do not** require `(lower-upper)/upper <= 0.22`

Groups (mutually exclusive):
1. NOT prior_price_above
2. prior_price_above AND no qualifying overhead zone
3. prior_price_above AND at least one qualifying overhead zone

Live DailyRun still skips entries with a qualifying overhead zone inside 22%. This closed book already passed that gate, so Group 3 here is historical overhead with a WPBR zone **above** the active band at **any** distance (typically >22%).

## Metrics

- IS = `DATE_OPENED < 2024-01-01`; OOS = `DATE_OPENED >= 2024-01-01`; plus FULL.
- `% of trades` = share of that slice’s **classified** N.
- Expectancy = average closed `PNL_PCT` (same as Avg P&L %).
- PPCD = sum `PNL_DOLLARS` / Capital Days; Capital Days = sum `DAYS_HELD`.
- Annualized rate of return (Ann ROR) = house `compare_format.ann_ror_from_closed` with Report `capacity_brt_cash` = {brt_cash:.9f} as `brt_cash`.
- Max DD / Sharpe / Calmar: closed-trade overlay (`overlay_ann_ror_max_dd` / `resolve_overlay_sharpe` / `sharpe_from_closed_pnl_by_date`). Exit-date equity seeded at Initial_capital / $500k (`{initial_account:.0f}`). Sharpe is **not** √252 daily EquityCurve (full-book EquityCurve is invalid on a group subset). Method tag: `closed_exit_date_equity:rf0:obs_per_year`.
- Trades/Year = group N / calendar years of **that slice’s closed-book** first-to-last `DATE_OPENED` (same denominator across groups in a slice).

## Unclassified

- Closed trades: {n_closed}
- Unclassified: {n_uncl}
- Reasons: {reasons or "{}"}
- Group1+Group2+Group3+unclassified = closed book: **{"YES" if recon_ok else "NO"}**

## Not done

No optimization. No new trade filter. `run_wpbr.bat` / DailyRun untouched.
""",
        encoding="utf-8",
    )


def write_html(
    path: Path,
    *,
    blocks: dict[str, dict[str, dict[str, Any]]],
    n_closed: int,
    n_uncl: int,
    reasons: dict[str, int],
    recon: dict[str, dict[str, int]],
    recon_ok: bool,
    brt_cash: float,
) -> None:
    reason_txt = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "none"
    css = SORTABLE_TH_CSS + RESPONSIVE_TABLE_CSS
    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR structure / prior overhead diagnostic</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 16px; color: #1e293b; background: #f8fafc; }}
h1 {{ font-size: 22px; margin: 0 0 8px; }}
h2 {{ font-size: 16px; margin: 22px 0 8px; }}
.sub {{ color: #64748b; font-size: 13px; }}
.callout {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; margin: 12px 0 18px; }}
.callout h2 {{ margin-top: 0; }}
.callout pre {{ white-space: pre-wrap; font-family: Georgia, serif; font-size: 13px; }}
.mono {{ font-family: ui-monospace, Consolas, monospace; font-size: 12px; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 13px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 5px 8px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
tr.total-row {{ font-weight: 700; background: #f1f5f9; }}
{css}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<h1>Pivot Break and Retest (WPBR) structure diagnostic — prior price vs overhead zone</h1>
<p class="sub">Stamp 261002172253 control book. Classification only. Not a filter. Not DailyRun.</p>

<div class="callout">
<h2>What you asked</h2>
<pre>{html_mod.escape(REQUEST_QUOTE)}</pre>
</div>

<div class="callout">
<h2>In plain English</h2>
<p>Weekly Pivot Break and Retest (WPBR) buys a stock after it breaks a weekly pivot band and comes back to retest it. This page does <strong>not</strong> change those buys or sells. It only labels each already-taken trade by what the chart looked like <em>before</em> that pivot week existed.</p>
<p><strong>Group 1</strong> is true price discovery: before that pivot week, the stock had never printed a high above this zone’s ceiling. <strong>Group 2</strong> had traded higher in the past, but the WPBR recipe never drew an older resistance band sitting cleanly above this one. <strong>Group 3</strong> had both: old highs above the ceiling, and at least one older WPBR band whose floor sits above this zone’s ceiling — at any distance (the live 22% skip is <em>not</em> used here).</p>
<p>We then show whether win rate, average P&amp;L, and annualized rate of return (Ann ROR) differ across those three stories, on the full book, before 2024 (in-sample, IS), and from 2024 on (out-of-sample, OOS).</p>
</div>

<div class="callout">
<p><span class="mono">Closed N = {n_closed}</span>. Unclassified = {n_uncl} ({html_mod.escape(reason_txt)}). Group1+2+3+unclassified matches the closed book: <strong>{"YES" if recon_ok else "NO"}</strong>.</p>
<p>Ann ROR uses house <span class="mono">ann_ror_from_closed</span> with Report <span class="mono">capacity_brt_cash={brt_cash:.6f}</span>. Max DD / Sharpe are group-only overlay curves from closed exit dates (rf=0, annualize by observed exit frequency — not the full-book EquityCurve, not √252). PPCD is formatted as dollars. Total PnL $ / Sheet PnL $ are omitted.</p>
</div>

{table_headline(blocks)}
{table_metrics("FULL book by group", [(GROUP_LABELS[g], blocks[g]["FULL"]) for g in (G1, G2, G3)] + [("All classified", blocks["ALL_CLASSIFIED"]["FULL"])])}
{table_metrics("IS (DATE_OPENED &lt; 2024-01-01)", [(GROUP_LABELS[g], blocks[g]["IS"]) for g in (G1, G2, G3)] + [("All classified", blocks["ALL_CLASSIFIED"]["IS"])])}
{table_metrics("OOS (DATE_OPENED ≥ 2024-01-01)", [(GROUP_LABELS[g], blocks[g]["OOS"]) for g in (G1, G2, G3)] + [("All classified", blocks["ALL_CLASSIFIED"]["OOS"])])}
{table_recon("Reconciliation — FULL", [
    (GROUP_LABELS[G1], recon["FULL"][G1], n_closed),
    (GROUP_LABELS[G2], recon["FULL"][G2], n_closed),
    (GROUP_LABELS[G3], recon["FULL"][G3], n_closed),
    (GROUP_LABELS[UNCL], recon["FULL"][UNCL], n_closed),
    ("Sum (must equal closed book)", recon["FULL"]["SUM"], n_closed),
])}
{table_recon("Reconciliation — IS", [
    (GROUP_LABELS[G1], recon["IS"][G1], recon["IS"]["ALL"]),
    (GROUP_LABELS[G2], recon["IS"][G2], recon["IS"]["ALL"]),
    (GROUP_LABELS[G3], recon["IS"][G3], recon["IS"]["ALL"]),
    (GROUP_LABELS[UNCL], recon["IS"][UNCL], recon["IS"]["ALL"]),
    ("Sum (must equal IS closed)", recon["IS"]["SUM"], recon["IS"]["ALL"]),
])}
{table_recon("Reconciliation — OOS", [
    (GROUP_LABELS[G1], recon["OOS"][G1], recon["OOS"]["ALL"]),
    (GROUP_LABELS[G2], recon["OOS"][G2], recon["OOS"]["ALL"]),
    (GROUP_LABELS[G3], recon["OOS"][G3], recon["OOS"]["ALL"]),
    (GROUP_LABELS[UNCL], recon["OOS"][UNCL], recon["OOS"]["ALL"]),
    ("Sum (must equal OOS closed)", recon["OOS"]["SUM"], recon["OOS"]["ALL"]),
])}

<p class="sub">Artifacts: BASELINE.md, summary.csv, classified_trades.csv. Freeze path: {html_mod.escape(str(CLOSED.relative_to(ROOT)))}</p>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(inject_report_page_extras(body), encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading closed + report", flush=True)
    trades = load_closed(CLOSED)
    brt_cash, initial_account = load_report_cash(REPORT)
    n_closed = len(trades)
    print(f"closed={n_closed} capacity_brt_cash={brt_cash} initial_capital={initial_account}", flush=True)
    symbols = sorted({t["symbol"] for t in trades if t["symbol"]})
    print(f"symbols={len(symbols)} loading duckdb", flush=True)
    t0 = time.perf_counter()
    prices = load_prices(symbols)
    print(f"prices loaded {len(prices)}/{len(symbols)} in {time.perf_counter()-t0:.1f}s", flush=True)
    print("rebuilding WPBR zone inventories (same knobs as freeze)", flush=True)
    inventory = build_zone_inventory(prices)
    print("classifying", flush=True)
    classified = [classify_trade(t, prices, inventory) for t in trades]

    def pick(sl: str | None, group: str | None, classified_only: bool = False) -> list[dict[str, Any]]:
        rows = classified
        if sl and sl != "FULL":
            rows = [t for t in rows if t.get("slice") == sl]
        if classified_only:
            rows = [t for t in rows if t.get("group") in (G1, G2, G3)]
        if group:
            rows = [t for t in rows if t.get("group") == group]
        return rows

    years = {
        "FULL": slice_years(classified),
        "IS": slice_years([t for t in classified if t.get("slice") == "IS"]),
        "OOS": slice_years([t for t in classified if t.get("slice") == "OOS"]),
    }
    blocks: dict[str, dict[str, dict[str, Any]]] = {}
    for g in (G1, G2, G3, UNCL, "ALL_CLASSIFIED", "ALL_CLOSED"):
        blocks[g] = {}
        for sl in ("FULL", "IS", "OOS"):
            if g == "ALL_CLOSED":
                rows = pick(sl if sl != "FULL" else None, None, False)
                if sl == "FULL":
                    rows = classified
                base = len(rows) or 1
            elif g == "ALL_CLASSIFIED":
                rows = pick(sl if sl != "FULL" else None, None, True)
                if sl == "FULL":
                    rows = pick(None, None, True)
                base = len(rows) or 1
            else:
                classified_slice = pick(sl if sl != "FULL" else None, None, True)
                if sl == "FULL":
                    classified_slice = pick(None, None, True)
                base = len(classified_slice)
                rows = pick(sl if sl != "FULL" else None, g, False)
                if sl == "FULL":
                    rows = pick(None, g, False)
            blocks[g][sl] = metrics_for(
                rows,
                brt_cash=brt_cash,
                initial_account=initial_account,
                pct_base=base,
                slice_span_years=years[sl],
            )

    recon: dict[str, dict[str, int]] = {}
    for sl in ("FULL", "IS", "OOS"):
        if sl == "FULL":
            bucket = classified
        else:
            bucket = [t for t in classified if t.get("slice") == sl]
        counts = defaultdict(int)
        for t in bucket:
            counts[t["group"]] += 1
        recon[sl] = {
            G1: counts[G1],
            G2: counts[G2],
            G3: counts[G3],
            UNCL: counts[UNCL],
            "SUM": counts[G1] + counts[G2] + counts[G3] + counts[UNCL],
            "ALL": len(bucket),
        }
    recon_ok = recon["FULL"]["SUM"] == n_closed
    n_uncl = recon["FULL"][UNCL]
    reasons: dict[str, int] = defaultdict(int)
    for t in classified:
        if t["group"] == UNCL:
            reasons[t.get("unclassified_reason") or "unknown"] += 1

    write_classified_csv(OUT / "classified_trades.csv", classified)
    write_summary_csv(OUT / "summary.csv", blocks)
    write_baseline(
        OUT / "BASELINE.md",
        n_closed=n_closed,
        n_uncl=n_uncl,
        reasons=dict(reasons),
        recon_ok=recon_ok,
        brt_cash=brt_cash,
        initial_account=initial_account,
    )
    write_html(
        OUT / "compare.html",
        blocks=blocks,
        n_closed=n_closed,
        n_uncl=n_uncl,
        reasons=dict(reasons),
        recon=recon,
        recon_ok=recon_ok,
        brt_cash=brt_cash,
    )

    print("DONE", flush=True)
    print(f"html={OUT / 'compare.html'}", flush=True)
    print(f"unclassified={n_uncl} reasons={dict(reasons)}", flush=True)
    print(f"recon_ok={recon_ok} closed={n_closed} sum={recon['FULL']['SUM']}", flush=True)
    for g in (G1, G2, G3):
        m = blocks[g]["FULL"]
        print(
            f"{g} FULL N={m['n']} WR={m['wr']:.2f} Avg={m['avg_pnl_pct']:.2f} AnnROR={m['ann_ror']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
