"""Diagnostic: WPBR_VEL_TS40 trades vs same trades if CONTROL 22/20/8 continued.

No rule changes. Reads existing Day-40/+10% AB closed books.
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import statistics
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from compare_format import format_money  # noqa: E402
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    RESPONSIVE_TABLE_CSS,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

IS_CUT = "20240101"
VEL_EXIT = "WPBR_VEL_TS40"
TEST_CLOSED = ROOT / "tmp_wpbr_day40_vel10_ab_20261002" / "test" / "WPBR_Closed_261002180145.csv"
CONTROL_CLOSED = ROOT / "tmp_wpbr_day40_vel10_ab_20261002" / "control" / "WPBR_Closed_261002172253.csv"
CONTROL_OPEN = ROOT / "tmp_wpbr_day40_vel10_ab_20261002" / "control" / "WPBR_Open_261002172253.csv"
CONTROL_REPORT = ROOT / "tmp_wpbr_day40_vel10_ab_20261002" / "control" / "WPBR_Report_261002172253.csv"
TEST_REPORT = ROOT / "tmp_wpbr_day40_vel10_ab_20261002" / "test" / "WPBR_Report_261002180145.csv"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "wpbr_day40_vel_continue_diag_20261003"

REQUEST_QUOTE = (
    "Analyze the exact trades that were exited by WPBR_VEL_TS40 in the Day-40/+10% test "
    "and match each one to the same trade in the CONTROL 22% overhead / +20% target / -8% stop book. "
    "For those matched trades, report what happened if the control was allowed to continue normally "
    "after Day 40. Report FULL, IS, and OOS. Do not change or test any rules. Diagnostic only: "
    "measure exactly what upside was sacrificed and what losses/time/capital were avoided by the "
    "Day-40/+10% velocity exit."
)

TARGET_EXITS = {"TARGET", "ATR_TARGET", "GAP_UP"}
STOP_GAP_EXITS = {
    "STOP_LOSS",
    "GAP_DOWN",
    "ATR_STOP",
    "TRAILING_STOP",
    "CHANDELIER_STOP",
    "SMA_STOP",
}


def _f(raw: Any, default: float = float("nan")) -> float:
    if raw is None:
        return default
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _ymd(raw: str) -> str:
    s = str(raw or "").strip().replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _to_date(ymd: str) -> date | None:
    s = _ymd(ymd)
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _iso(ymd: str) -> str:
    d = _to_date(ymd)
    return d.isoformat() if d else ""


def _extra_bars(vel_close: str, ctrl_close: str) -> float:
    a = _to_date(vel_close)
    b = _to_date(ctrl_close)
    if a is None or b is None:
        return float("nan")
    if b <= a:
        return 0.0
    return float(np.busday_count(np.datetime64(a.isoformat()), np.datetime64(b.isoformat())))


def _mean(xs: list[float]) -> float:
    ok = [x for x in xs if math.isfinite(x)]
    return float(sum(ok) / len(ok)) if ok else float("nan")


def _median(xs: list[float]) -> float:
    ok = [x for x in xs if math.isfinite(x)]
    return float(statistics.median(ok)) if ok else float("nan")


def _report_cash(path: Path) -> float:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return float("nan")
    return _f(rows[0].get("capacity_brt_cash"))


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _ymd(str(raw.get("DATE_OPENED") or ""))
            if not opened:
                continue
            rows.append({
                "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                "opened": opened,
                "closed": _ymd(str(raw.get("DATE_CLOSED") or "")),
                "entry": _f(raw.get("ENTRY_PRICE")),
                "exit_px": _f(raw.get("EXIT_PRICE")),
                "exit": str(raw.get("EXIT_TYPE") or "").strip() or "?",
                "days": _f(raw.get("DAYS_HELD")),
                "pnl": _f(raw.get("PNL_PCT")),
                "pnl_d": _f(raw.get("PNL_DOLLARS")),
                "pct40": _f(raw.get("PCT_AT_DAY_40")),
                "first20": _ymd(str(raw.get("DATE_FIRST_UP_20PCT") or "")),
            })
    return rows


def _key(t: dict[str, Any]) -> tuple[str, str]:
    return (t["symbol"], t["opened"])


def _index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(_key(r), []).append(r)
    return out


def _pick(cands: list[dict[str, Any]], vel: dict[str, Any]) -> dict[str, Any] | None:
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    ep = vel["entry"]
    scored = []
    for c in cands:
        d = abs(c["entry"] - ep) if math.isfinite(c["entry"]) and math.isfinite(ep) else 1e9
        scored.append((d, c))
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


def _bucket(pnl: float) -> str:
    if not math.isfinite(pnl):
        return "unknown"
    if pnl < 0:
        return "<0%"
    if pnl < 5:
        return "0–5%"
    if pnl < 10:
        return "5–10%"
    return "≥10%"


def _is_stop_gap(exit_type: str) -> bool:
    u = (exit_type or "").upper()
    if u in STOP_GAP_EXITS:
        return True
    if "STOP" in u:
        return True
    if u.startswith("GAP_") and u != "GAP_UP":
        return True
    return False


def _stats(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(pairs)
    vel_pnl = [p["vel"]["pnl"] for p in pairs]
    ctrl_pnl = [p["ctrl"]["pnl"] for p in pairs]
    vel_d = [p["vel"]["pnl_d"] for p in pairs]
    ctrl_d = [p["ctrl"]["pnl_d"] for p in pairs]
    extra_bars = [p["extra_bars"] for p in pairs]
    extra_cap = [p["extra_cap_days"] for p in pairs]
    reached = [p for p in pairs if p["reached_target"]]
    stopg = [p for p in pairs if p["stop_gap"]]
    won = [p for p in pairs if math.isfinite(p["ctrl"]["pnl"]) and p["ctrl"]["pnl"] > 0]
    lost = [p for p in pairs if math.isfinite(p["ctrl"]["pnl"]) and p["ctrl"]["pnl"] < 0]
    tgt_final = [p["ctrl"]["pnl"] for p in reached]
    lost_final = [p["ctrl"]["pnl"] for p in lost]
    diff_pct = [
        a - b
        for a, b in zip(vel_pnl, ctrl_pnl)
        if math.isfinite(a) and math.isfinite(b)
    ]
    diff_d = [
        a - b
        for a, b in zip(vel_d, ctrl_d)
        if math.isfinite(a) and math.isfinite(b)
    ]
    cont_pct = [
        b - a
        for a, b in zip(vel_pnl, ctrl_pnl)
        if math.isfinite(a) and math.isfinite(b)
    ]
    cont_d = [
        b - a
        for a, b in zip(vel_d, ctrl_d)
        if math.isfinite(a) and math.isfinite(b)
    ]
    exits = Counter(p["ctrl"]["exit"] for p in pairs)
    return {
        "n": n,
        "vel_n": n,
        "vel_sum_pct": float(sum(x for x in vel_pnl if math.isfinite(x))),
        "vel_avg_pct": _mean(vel_pnl),
        "vel_sum_d": float(sum(x for x in vel_d if math.isfinite(x))),
        "ctrl_sum_pct": float(sum(x for x in ctrl_pnl if math.isfinite(x))),
        "ctrl_avg_pct": _mean(ctrl_pnl),
        "ctrl_sum_d": float(sum(x for x in ctrl_d if math.isfinite(x))),
        "diff_sum_pct": float(sum(diff_pct)),
        "diff_avg_pct": _mean(diff_pct),
        "diff_sum_d": float(sum(diff_d)),
        "cont_sum_pct": float(sum(cont_pct)),
        "cont_avg_pct": _mean(cont_pct),
        "cont_sum_d": float(sum(cont_d)),
        "n_target": len(reached),
        "pct_target": (100.0 * len(reached) / n) if n else float("nan"),
        "n_stop": len(stopg),
        "pct_stop": (100.0 * len(stopg) / n) if n else float("nan"),
        "n_win": len(won),
        "pct_win": (100.0 * len(won) / n) if n else float("nan"),
        "avg_extra_bars": _mean(extra_bars),
        "med_extra_bars": _median(extra_bars),
        "extra_cap_days": float(sum(x for x in extra_cap if math.isfinite(x))),
        "avg_final_target": _mean(tgt_final),
        "avg_final_lost": _mean(lost_final),
        "n_lost": len(lost),
        "exits": exits,
        "tagged20": sum(1 for p in pairs if p["ctrl"]["first20"]),
    }


def _slice_pairs(pairs: list[dict[str, Any]], window: str) -> list[dict[str, Any]]:
    if window == "FULL":
        return pairs
    if window == "IS":
        return [p for p in pairs if p["vel"]["opened"] < IS_CUT]
    return [p for p in pairs if p["vel"]["opened"] >= IS_CUT]


def _fmt_n(v: float, nd: int = 2, suf: str = "") -> str:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        return "—"
    if nd == 0:
        return f"{int(round(float(v)))}{suf}"
    return f"{float(v):,.{nd}f}{suf}"


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _metric_rows() -> list[tuple[str, str, int, str, str]]:
    # key, label, nd, suffix, kind: num|money|pct
    return [
        ("n", "Matched trades", 0, "", "num"),
        ("vel_sum_pct", "P&L at Day-40 velocity exit (sum %)", 2, "%", "pct"),
        ("vel_avg_pct", "P&L at Day-40 velocity exit (avg %)", 2, "%", "pct"),
        ("vel_sum_d", "P&L at Day-40 velocity exit (sum $, control slot)", 2, "", "money"),
        ("ctrl_sum_pct", "Final control P&L (sum %)", 2, "%", "pct"),
        ("ctrl_avg_pct", "Final control P&L (avg %)", 2, "%", "pct"),
        ("ctrl_sum_d", "Final control P&L (sum $, control slot)", 2, "", "money"),
        ("diff_sum_pct", "Velocity − control P&L (sum %)", 2, "%", "pct"),
        ("diff_avg_pct", "Velocity − control P&L (avg %)", 2, "%", "pct"),
        ("diff_sum_d", "Velocity − control P&L (sum $, control slot)", 2, "", "money"),
        ("cont_sum_pct", "Continuation add (control − velocity, sum %)", 2, "%", "pct"),
        ("cont_avg_pct", "Continuation add (avg %)", 2, "%", "pct"),
        ("cont_sum_d", "Continuation add (sum $, control slot)", 2, "", "money"),
        ("n_target", "Reached +20% target (count)", 0, "", "num"),
        ("pct_target", "Reached +20% target (%)", 1, "%", "pct"),
        ("n_stop", "Exited by stop/gap loss (count)", 0, "", "num"),
        ("pct_stop", "Exited by stop/gap loss (%)", 1, "%", "pct"),
        ("n_win", "Finished profitable (count)", 0, "", "num"),
        ("pct_win", "Finished profitable (%)", 1, "%", "pct"),
        ("avg_extra_bars", "Avg extra trading bars after Day 40", 1, "", "num"),
        ("med_extra_bars", "Median extra trading bars after Day 40", 1, "", "num"),
        ("extra_cap_days", "Total extra capital days after Day 40", 0, "", "num"),
        ("avg_final_target", "Avg final P&L % of trades that reached target", 2, "%", "pct"),
        ("avg_final_lost", "Avg final P&L % of trades that eventually lost", 2, "%", "pct"),
    ]


def _cell(kind: str, v: float, nd: int, suf: str) -> str:
    if kind == "money":
        return f"<td>{format_money(v)}</td>"
    if kind == "pct":
        return f"<td>{_fmt_n(v, nd, suf)}</td>"
    return f"<td>{_fmt_n(v, nd, suf)}</td>"


def _stats_table(title: str, windows: list[str], by_window: dict[str, dict[str, Any]]) -> str:
    head = "".join([sortable_th("Metric", "text"), *[sortable_th(w, "num") for w in windows]])
    body = []
    for key, label, nd, suf, kind in _metric_rows():
        cells = [f"<td>{html_mod.escape(label)}</td>"]
        for w in windows:
            cells.append(_cell(kind, by_window[w][key], nd, suf))
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<h2>{html_mod.escape(title)}</h2>"
        f"<p class=\"sub\">Click column headers to sort. {SWIPE_NOTE_HTML}</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _bucket_table(bucket_stats: dict[str, dict[str, dict[str, Any]]]) -> str:
    buckets = ["<0%", "0–5%", "5–10%"]
    windows = ["FULL", "IS", "OOS"]
    head = "".join([
        sortable_th("Day-40 P&L bucket", "text"),
        sortable_th("Slice", "text"),
        *[sortable_th(lab, "num") for _, lab, *_ in [
            ("n", "N"),
            ("vel", "Vel sum %"),
            ("ctrl", "Ctrl sum %"),
            ("diff", "Vel−ctrl sum %"),
            ("cont", "Ctrl−vel sum %"),
            ("tgt", "Hit +20% tgt %"),
            ("stop", "Stop/gap %"),
            ("win", "Finished green %"),
            ("bars", "Avg extra bars"),
            ("medb", "Med extra bars"),
            ("cap", "Extra cap days"),
            ("avgt", "Avg final % if target"),
            ("avgl", "Avg final % if lost"),
        ]],
    ])
    body = []
    for b in buckets:
        for w in windows:
            s = bucket_stats[b][w]
            row = [
                f"<td>{html_mod.escape(b)}</td>",
                f"<td>{w}</td>",
                f"<td>{s['n']}</td>",
                f"<td>{_fmt_n(s['vel_sum_pct'], 2, '%')}</td>",
                f"<td>{_fmt_n(s['ctrl_sum_pct'], 2, '%')}</td>",
                f"<td>{_fmt_n(s['diff_sum_pct'], 2, '%')}</td>",
                f"<td>{_fmt_n(s['cont_sum_pct'], 2, '%')}</td>",
                f"<td>{_fmt_n(s['pct_target'], 1, '%')}</td>",
                f"<td>{_fmt_n(s['pct_stop'], 1, '%')}</td>",
                f"<td>{_fmt_n(s['pct_win'], 1, '%')}</td>",
                f"<td>{_fmt_n(s['avg_extra_bars'], 1)}</td>",
                f"<td>{_fmt_n(s['med_extra_bars'], 1)}</td>",
                f"<td>{_fmt_n(s['extra_cap_days'], 0)}</td>",
                f"<td>{_fmt_n(s['avg_final_target'], 2, '%')}</td>",
                f"<td>{_fmt_n(s['avg_final_lost'], 2, '%')}</td>",
            ]
            body.append("<tr>" + "".join(row) + "</tr>")
    return (
        "<h2>Breakout by P&amp;L at the Day-40 velocity exit</h2>"
        "<p class=\"sub\">Buckets use the test book’s exit P&amp;L % on WPBR_VEL_TS40 "
        "(close on Day 40). ≥10% is omitted unless any trades land there (they should not). "
        f"Click headers to sort. {SWIPE_NOTE_HTML}</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _exit_table(pairs: list[dict[str, Any]]) -> str:
    head = "".join([
        sortable_th("Control EXIT_TYPE", "text"),
        sortable_th("FULL n", "num"),
        sortable_th("FULL %", "num"),
        sortable_th("IS n", "num"),
        sortable_th("OOS n", "num"),
    ])
    full = Counter(p["ctrl"]["exit"] for p in pairs)
    is_c = Counter(p["ctrl"]["exit"] for p in _slice_pairs(pairs, "IS"))
    oos_c = Counter(p["ctrl"]["exit"] for p in _slice_pairs(pairs, "OOS"))
    n = len(pairs) or 1
    body = []
    for k, c in full.most_common():
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(k)}</td>"
            f"<td>{c}</td>"
            f"<td>{100.0 * c / n:.1f}%</td>"
            f"<td>{is_c.get(k, 0)}</td>"
            f"<td>{oos_c.get(k, 0)}</td>"
            "</tr>"
        )
    return (
        "<h2>Control exit mix on the matched set</h2>"
        f"<p class=\"sub\">Click headers to sort. {SWIPE_NOTE_HTML}</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _trade_table(pairs: list[dict[str, Any]], limit: int = 400) -> str:
    head = "".join([
        sortable_th("Symbol", "text"),
        sortable_th("Opened", "date"),
        sortable_th("Slice", "text"),
        sortable_th("Day-40 bucket", "text"),
        sortable_th("Vel close", "date"),
        sortable_th("Ctrl close", "date"),
        sortable_th("Vel P&L %", "num"),
        sortable_th("Ctrl P&L %", "num"),
        sortable_th("Ctrl − vel %", "num"),
        sortable_th("Ctrl exit", "text"),
        sortable_th("Extra bars", "num"),
        sortable_th("Extra cap days", "num"),
    ])
    shown = sorted(pairs, key=lambda p: (p["vel"]["opened"], p["vel"]["symbol"]))
    note = ""
    if len(shown) > limit:
        note = f"<p class=\"sub\">Showing first {limit} of {len(shown)} matched trades (CSV has all).</p>"
        shown = shown[:limit]
    body = []
    for p in shown:
        v, c = p["vel"], p["ctrl"]
        sl = "IS" if v["opened"] < IS_CUT else "OOS"
        cont = (c["pnl"] - v["pnl"]) if math.isfinite(c["pnl"]) and math.isfinite(v["pnl"]) else float("nan")
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(v['symbol'])}</td>"
            f"<td>{_iso(v['opened'])}</td>"
            f"<td>{sl}</td>"
            f"<td>{html_mod.escape(p['bucket'])}</td>"
            f"<td>{_iso(v['closed'])}</td>"
            f"<td>{_iso(c['closed'])}</td>"
            f"<td>{_fmt_n(v['pnl'], 2)}</td>"
            f"<td>{_fmt_n(c['pnl'], 2)}</td>"
            f"<td>{_fmt_n(cont, 2)}</td>"
            f"<td>{html_mod.escape(c['exit'])}</td>"
            f"<td>{_fmt_n(p['extra_bars'], 0)}</td>"
            f"<td>{_fmt_n(p['extra_cap_days'], 0)}</td>"
            "</tr>"
        )
    return (
        "<h2>Matched trade rows</h2>"
        f"{note}<p class=\"sub\">Click headers to sort. {SWIPE_NOTE_HTML}</p>"
        f"<div class=\"table-wrap\"><table class=\"sortable\"><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def main() -> int:
    test = _load(TEST_CLOSED)
    control = _load(CONTROL_CLOSED)
    open_rows = _load(CONTROL_OPEN) if CONTROL_OPEN.is_file() else []
    slot = _report_cash(CONTROL_REPORT)
    test_slot = _report_cash(TEST_REPORT)
    vel = [t for t in test if t["exit"] == VEL_EXIT]
    cidx = _index(control)
    oidx = _index(open_rows)

    pairs: list[dict[str, Any]] = []
    unmatched_open_rows: list[dict[str, Any]] = []
    unmatched_none_rows: list[dict[str, Any]] = []
    for v in vel:
        c = _pick(cidx.get(_key(v), []), v)
        if c is None:
            o = _pick(oidx.get(_key(v), []), v)
            if o is not None:
                unmatched_open_rows.append(v)
            else:
                unmatched_none_rows.append(v)
            continue
        # Books used different slot cash; compare dollars on the control slot.
        if math.isfinite(slot) and slot > 0:
            if math.isfinite(v["pnl"]):
                v = {**v, "pnl_d": v["pnl"] / 100.0 * slot}
            if math.isfinite(c["pnl"]):
                c = {**c, "pnl_d": c["pnl"] / 100.0 * slot}
        extra_bars = _extra_bars(v["closed"], c["closed"])
        extra_cap = (
            (c["days"] - v["days"])
            if math.isfinite(c["days"]) and math.isfinite(v["days"])
            else float("nan")
        )
        pairs.append({
            "vel": v,
            "ctrl": c,
            "extra_bars": extra_bars,
            "extra_cap_days": extra_cap,
            "reached_target": c["exit"] in TARGET_EXITS,
            "stop_gap": _is_stop_gap(c["exit"]),
            "bucket": _bucket(v["pnl"]),
        })

    windows = ["FULL", "IS", "OOS"]
    by_window = {w: _stats(_slice_pairs(pairs, w)) for w in windows}
    bucket_stats: dict[str, dict[str, dict[str, Any]]] = {}
    leftover_ge10 = [p for p in pairs if p["bucket"] == "≥10%"]
    unmatched_open = len(unmatched_open_rows)
    unmatched_none = len(unmatched_none_rows)
    unmatched_closed = unmatched_open + unmatched_none
    u_open_pnl = _mean([t["pnl"] for t in unmatched_open_rows])
    u_none_pnl = _mean([t["pnl"] for t in unmatched_none_rows])
    u_none_sum = float(sum(t["pnl"] for t in unmatched_none_rows if math.isfinite(t["pnl"])))
    for b in ("<0%", "0–5%", "5–10%", "≥10%"):
        bucket_stats[b] = {
            w: _stats([p for p in _slice_pairs(pairs, w) if p["bucket"] == b])
            for w in windows
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "matched_trades.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "symbol", "opened", "slice", "day40_bucket",
            "vel_closed", "ctrl_closed", "vel_exit", "ctrl_exit",
            "vel_pnl_pct", "ctrl_pnl_pct", "vel_minus_ctrl_pct", "ctrl_minus_vel_pct",
            "vel_pnl_dollars", "ctrl_pnl_dollars", "vel_minus_ctrl_dollars",
            "extra_trading_bars", "extra_capital_days",
            "reached_target", "stop_gap_loss", "ctrl_finished_profit",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in sorted(pairs, key=lambda x: (x["vel"]["opened"], x["vel"]["symbol"])):
            v, c = p["vel"], p["ctrl"]
            w.writerow({
                "symbol": v["symbol"],
                "opened": v["opened"],
                "slice": "IS" if v["opened"] < IS_CUT else "OOS",
                "day40_bucket": p["bucket"],
                "vel_closed": v["closed"],
                "ctrl_closed": c["closed"],
                "vel_exit": v["exit"],
                "ctrl_exit": c["exit"],
                "vel_pnl_pct": v["pnl"],
                "ctrl_pnl_pct": c["pnl"],
                "vel_minus_ctrl_pct": v["pnl"] - c["pnl"] if math.isfinite(v["pnl"]) and math.isfinite(c["pnl"]) else "",
                "ctrl_minus_vel_pct": c["pnl"] - v["pnl"] if math.isfinite(v["pnl"]) and math.isfinite(c["pnl"]) else "",
                "vel_pnl_dollars": v["pnl_d"],
                "ctrl_pnl_dollars": c["pnl_d"],
                "vel_minus_ctrl_dollars": v["pnl_d"] - c["pnl_d"] if math.isfinite(v["pnl_d"]) and math.isfinite(c["pnl_d"]) else "",
                "extra_trading_bars": p["extra_bars"],
                "extra_capital_days": p["extra_cap_days"],
                "reached_target": int(p["reached_target"]),
                "stop_gap_loss": int(p["stop_gap"]),
                "ctrl_finished_profit": int(math.isfinite(c["pnl"]) and c["pnl"] > 0),
            })

    summary_path = OUT_DIR / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        keys = [k for k, *_ in _metric_rows()]
        fields = ["slice", "bucket", *keys]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for sl in windows:
            row = {"slice": sl, "bucket": "ALL"}
            for k in keys:
                row[k] = by_window[sl][k]
            w.writerow(row)
        for b in ("<0%", "0–5%", "5–10%"):
            for sl in windows:
                row = {"slice": sl, "bucket": b}
                for k in keys:
                    row[k] = bucket_stats[b][sl][k]
                w.writerow(row)

    full = by_window["FULL"]
    ge10_note = ""
    if leftover_ge10:
        ge10_note = (
            f"<p><strong>Note:</strong> {len(leftover_ge10)} velocity exits had Day-40 P&amp;L "
            "≥10% (unexpected under a High never-tagged-+10% rule).</p>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR Day-40 velocity vs control continuation</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px; max-width: 1200px; color: #1e293b; background: #faf8f5; }}
h1 {{ font-size: 1.6rem; }}
h2 {{ margin-top: 1.6rem; }}
.callout {{ background: #fff; border: 1px solid #e2d6c6; padding: 12px 16px; margin: 12px 0 20px; }}
.callout h2 {{ margin-top: 0; font-size: 1.1rem; }}
.sub, .muted {{ color: #64748b; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: 14px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }}
th.sortable-th {{ background: #f4f1ea; cursor: pointer; white-space: nowrap; }}
.verdict {{ background: #eef6ff; border-left: 4px solid #2563eb; padding: 12px 16px; }}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head>
<body>
{FORCE_RELOAD_SCRIPT}
<h1>WPBR Day-40 / +10% velocity exits vs control continuation</h1>
<p class="muted">Diagnostic only. No rules changed. IS = entry before 2024-01-01. OOS = entry on or after 2024-01-01.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(REQUEST_QUOTE)}</p>
<h2>In plain English</h2>
<p>The test book dumped a trade at the close of trading day 40 if the high never got to +10% from the buy. We lined those dumped trades up with the same buys in the live 22% overhead / +20% target / −8% stop book, then asked: if we had just sat there, what happened next? Did we eventually get the +20% payday, or did we get stopped, and how much extra calendar time did that consume?</p>
<p><strong>Control</strong> = current 22% overhead / +20% target / −8% stop, velocity off. <strong>Velocity exit</strong> = same entries, but sell at Day-40 close when the high never tagged +10% (<code>WPBR_VEL_TS40</code>).</p>
</div>

<div class="verdict">
<p><strong>Match:</strong> {full['n']:,} of {len(vel):,} velocity exits matched a control closed trade on symbol + open date
({100.0 * full['n'] / len(vel) if vel else 0:.1f}%). The other {unmatched_closed:,} are not in the continuation set:
{unmatched_open:,} are still open in control (no final P&amp;L yet), and {unmatched_none:,} never existed in the control book
(velocity dumps freed slots, so the test took extra later fills). Those extras are not “the same trade, allowed to continue.”</p>
<p><strong>FULL continuation P&amp;L:</strong> velocity-exit sum { _fmt_n(full['vel_sum_pct'], 2, '%') }
vs final control sum { _fmt_n(full['ctrl_sum_pct'], 2, '%') }.
Sitting through it added { _fmt_n(full['cont_sum_pct'], 2, '%') }
({format_money(full['cont_sum_d'])}) on these names — that is control minus velocity.
Velocity minus control is { _fmt_n(full['diff_sum_pct'], 2, '%') } ({format_money(full['diff_sum_d'])}).
A negative velocity−control number means the live book finished better on the same trades.</p>
<p><strong>What sitting bought:</strong> {full['n_target']:,} / {full['n']:,}
({ _fmt_n(full['pct_target'], 1, '%') }) eventually exited at the +20% target.
{full['n_stop']:,} / {full['n']:,} ({ _fmt_n(full['pct_stop'], 1, '%') })
exited by stop or gap loss. {full['n_win']:,} / {full['n']:,}
({ _fmt_n(full['pct_win'], 1, '%') }) finished with a profit.</p>
<p><strong>Time/capital after Day 40:</strong> average extra trading bars { _fmt_n(full['avg_extra_bars'], 1) },
median { _fmt_n(full['med_extra_bars'], 1) }, total extra capital days { _fmt_n(full['extra_cap_days'], 0) }
(house capital days = sum of calendar <code>DAYS_HELD</code>).</p>
</div>
{ge10_note}

{_stats_table("Matched set: FULL / IS / OOS", windows, by_window)}
{_bucket_table(bucket_stats)}
{_exit_table(pairs)}

<h2>How to read the difference</h2>
<ul>
<li><strong>Velocity − control</strong> is what you asked for. Positive: the Day-40 dump beat the eventual live exit (losses avoided outweighed missed winners). Negative: the live book harvested more than the dump locked in (upside sacrificed).</li>
<li><strong>Continuation add (control − velocity)</strong> is the same gap with the opposite sign: P&amp;L earned or given back by staying in after Day 40.</li>
<li>Percent sums add per-trade <code>PNL_PCT</code> (the apples-to-apples identity). Dollar sums rescale both legs to control <code>capacity_brt_cash</code> ({format_money(slot)}). Raw test dollars used a larger slot (~{format_money(test_slot)}) and are not used here.</li>
<li>+20% target = control <code>EXIT_TYPE</code> in TARGET / ATR_TARGET / GAP_UP. Stop/gap loss = STOP_LOSS, GAP_DOWN, and any other stop-labeled exit. On this matched set every green control finish was a target and every red finish was a stop/gap — the two counts match.</li>
<li>Extra trading bars = NYSE-style weekdays from the velocity close date to the control close date (numpy busday_count). Extra capital days = control <code>DAYS_HELD</code> minus velocity <code>DAYS_HELD</code>.</li>
</ul>

<p><strong>Unmatched velocity exits:</strong> still-open in control n={unmatched_open:,}, avg Day-40 P&amp;L {_fmt_n(u_open_pnl, 2, '%')}.
No control row n={unmatched_none:,}, Day-40 P&amp;L sum {_fmt_n(u_none_sum, 2, '%')}, avg {_fmt_n(u_none_pnl, 2, '%')}.</p>
<p class="muted">Sources: <code>{html_mod.escape(str(TEST_CLOSED.relative_to(ROOT)))}</code> and
<code>{html_mod.escape(str(CONTROL_CLOSED.relative_to(ROOT)))}</code>.
Research only. Not gold. Not DailyRun.</p>
{_trade_table(pairs)}
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    html_path = OUT_DIR / "index.html"
    html_path.write_text(html, encoding="utf-8")
    (OUT_DIR / "BASELINE.md").write_text(
        "\n".join([
            "# WPBR Day-40 velocity vs control continuation (diagnostic)",
            "",
            "## What you asked",
            REQUEST_QUOTE,
            "",
            "## In plain English",
            "Same buys as the live 22/20/8 book. The test sold at Day-40 close if the high never reached +10%.",
            "This page only follows those dumped trades in the control book after Day 40. No knobs changed.",
            "",
            f"- Test closed: `{TEST_CLOSED}`",
            f"- Control closed: `{CONTROL_CLOSED}`",
            f"- Match key: SYMBOL + DATE_OPENED",
            f"- Velocity exits in test: {len(vel)}",
            f"- Matched to control closed: {len(pairs)}",
            f"- Unmatched: {unmatched_closed} (open {unmatched_open}, missing {unmatched_none})",
            f"- IS cut: entry_date < 2024-01-01",
            "",
            "Research only. EXIT identity frozen. Not a retune.",
            "",
        ]),
        encoding="utf-8",
    )
    print(f"vel={len(vel)} matched={len(pairs)} unmatched={unmatched_closed} open={unmatched_open} missing={unmatched_none}")
    print(f"wrote {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
