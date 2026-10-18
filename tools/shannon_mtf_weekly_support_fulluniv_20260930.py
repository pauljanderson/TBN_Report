#!/usr/bin/env python3
"""Weekly rising support on PaulTwenty and the full daily CSV warehouse.

One entry arm from shannon_mtf_lines_post_ab_20260930. Exit is the frozen
Shannon book. Does not overwrite the earlier Shannon folders.

  python tools/shannon_mtf_weekly_support_fulluniv_20260930.py
"""
from __future__ import annotations

import csv
import html as html_mod
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import shannon_mtf_lines_20260930 as sh  # noqa: E402
import shannon_mtf_lines_post_ab_20260930 as post  # noqa: E402
from compare_format import format_money, format_money_delta  # noqa: E402

OUT_DIR = ROOT / "drive" / "paul_experiments" / "shannon_mtf_weekly_support_fulluniv_20260930"
POST_TRADES = ROOT / "drive" / "paul_experiments" / "shannon_mtf_lines_post_ab_20260930" / "trades.csv"
IS_CUT = sh.IS_CUT
SHEET = sh.SHEET

ORIGINAL_REQUEST = (
    "let's implement this arm: Require weekly rising support and let's run it "
    "through the entire universe and compare to this Paul20"
)

CONTROL = next(a for a in post.ARMS if a.key == "control")
WEEKLY = next(a for a in post.ARMS if a.key == "entry_weekly_support")

SLIM_KEYS = (
    "sym",
    "signal",
    "opened",
    "closed",
    "entry",
    "exit",
    "pnl",
    "r",
    "days",
    "pnl_d",
    "had_target",
    "wsup_under",
)

PREDICATE = (
    "Take the control buy only when a rising weekly support line also exists and "
    "the signal close is above it. In code that is weekly_support_under_close: "
    "shannon_line on weekly lows with rising=True (last two confirmed swing lows, "
    "later low strictly higher, both confirmed on or before the signal date), and "
    "the signal close strictly greater than that line's price on the signal date. "
    "Same exits. A skipped signal does not hold the symbol, so a later daily turn "
    "can be taken."
)


def slim(trades: list[dict]) -> list[dict]:
    out = []
    for t in trades:
        out.append({k: t[k] for k in SLIM_KEYS})
    return out


def run_one(sym: str) -> tuple:
    try:
        df = sh.load_ohlc(sym)
        if df is None:
            return sym, "missing", [], []
        if len(df) < sh.MIN_DAILY_BARS:
            return sym, "short", [], []
        piv_d = sh.confirmed_pivots_daily(df, sh.PIVOT_K["daily"])
        piv_w = sh.confirmed_pivots_htf(df, sh.WEEK_FREQ, sh.PIVOT_K["weekly"])
        arrays, _ctx = post.prepare(sym, df)
        ctrl = post.simulate_entries(sym, df, piv_d, piv_w, arrays, CONTROL)
        arm = post.simulate_entries(sym, df, piv_d, piv_w, arrays, WEEKLY)
        return sym, "ok", slim(ctrl), slim(arm)
    except Exception as exc:  # one bad file must not kill the book
        return sym, f"error:{type(exc).__name__}:{exc}", [], []


def run_serial(symbols: list[str]) -> tuple[list[dict], list[dict], dict]:
    ctrl: list[dict] = []
    arm: list[dict] = []
    status: dict[str, str] = {}
    for i, sym in enumerate(symbols, 1):
        sym, st, c, a = run_one(sym)
        status[sym] = st
        ctrl.extend(c)
        arm.extend(a)
        print(f"paul20 {i}/{len(symbols)} {sym} {st} control {len(c)} arm {len(a)}", flush=True)
    ctrl.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    arm.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    return ctrl, arm, status


def run_pool(symbols: list[str], workers: int) -> tuple[list[dict], list[dict], dict]:
    ctrl: list[dict] = []
    arm: list[dict] = []
    status: dict[str, str] = {}
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for sym, st, c, a in ex.map(run_one, symbols, chunksize=4):
            status[sym] = st
            ctrl.extend(c)
            arm.extend(a)
            done += 1
            if done % 50 == 0 or done == len(symbols):
                print(
                    f"warehouse {done}/{len(symbols)} trades control {len(ctrl)} arm {len(arm)}",
                    flush=True,
                )
    ctrl.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    arm.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    return ctrl, arm, status


def _ident(t: dict) -> tuple:
    opened = t["opened"].isoformat() if isinstance(t["opened"], date) else str(t["opened"])[:10]
    return (t["sym"], opened, t["exit"], round(float(t["pnl"]), 6), bool(t["had_target"]))


def assert_weekly_matches(trades: list[dict]) -> None:
    frozen = [r for r in csv.DictReader(POST_TRADES.open(encoding="utf-8")) if r["arm"] == WEEKLY.key]
    got = sorted(trades, key=lambda t: (t["opened"], t["sym"], t["signal"]))
    if len(got) != len(frozen):
        raise SystemExit(
            f"Paul20 weekly arm N {len(got)} != published post-analysis CSV {len(frozen)}. "
            "Full-universe numbers were not scored."
        )
    for i, (a, b) in enumerate(zip(frozen, got)):
        if a["sym"] != b["sym"] or a["opened"] != b["opened"].isoformat() or a["exit"] != b["exit"]:
            raise SystemExit(
                f"Weekly arm mismatch row {i}: csv {a['sym']} {a['opened']} {a['exit']} "
                f"vs {b['sym']} {b['opened']} {b['exit']}. Full-universe numbers were not scored."
            )
        if abs(float(a["pnl"]) - b["pnl"]) > 1e-6:
            raise SystemExit(
                f"Weekly arm PnL mismatch {b['sym']} {b['opened']}: {a['pnl']} vs {b['pnl']}. "
                "Full-universe numbers were not scored."
            )
    print(f"Paul20 weekly arm matches published post-analysis CSV N={len(got)}", flush=True)


def verify_paul20(ctrl: list[dict], arm: list[dict]) -> None:
    try:
        post.assert_control_matches(ctrl)
    except SystemExit as exc:
        raise SystemExit(
            f"Paul20 control did not match the frozen 714-trade book ({exc}). "
            "Full-universe numbers were not scored."
        ) from exc
    assert_weekly_matches(arm)
    st = post.book_stats(ctrl)
    wa = post.book_stats(arm)
    print(
        f"Paul20 control N={st['n']} WR={st['wr']:.1f} avg={st['avg']:.2f} Ann={st['ann_ror']:.1f}",
        flush=True,
    )
    print(
        f"Paul20 arm N={wa['n']} WR={wa['wr']:.1f} avg={wa['avg']:.2f} Ann={wa['ann_ror']:.1f}",
        flush=True,
    )
    # Published page rounds WR to 0.1 and avg to 0.01. Same trades already passed.
    if st["n"] != 714 or abs(st["wr"] - 41.9) > 0.15 or abs(st["avg"] - 1.33) > 0.02:
        raise SystemExit(
            f"Paul20 control stats {st['n']} / {st['wr']:.2f}% / {st['avg']:.4f}% "
            "are outside the published 714 / 41.9% / 1.33% rounding. "
            "Full-universe numbers were not scored."
        )
    if wa["n"] != 506 or abs(wa["wr"] - 39.9) > 0.15 or abs(wa["avg"] - 1.49) > 0.02:
        raise SystemExit(
            f"Paul20 arm stats {wa['n']} / {wa['wr']:.2f}% / {wa['avg']:.4f}% "
            "are outside the published 506 / 39.9% / 1.49% rounding. "
            "Full-universe numbers were not scored."
        )


def position_stats(trades: list[dict]) -> tuple[float, float, int]:
    """Calendar occupancy. A trade counts for `days` held, open date inclusive."""
    if not trades:
        return float("nan"), float("nan"), 0
    start = min(t["opened"] for t in trades)
    span = (max(t["closed"] for t in trades) - start).days + 2
    diff = [0] * (span + 1)
    for t in trades:
        a = (t["opened"] - start).days
        hold = int(t["days"]) if t["days"] else 1
        b = a + max(hold, 1)
        if 0 <= a < len(diff):
            diff[a] += 1
        if 0 <= b < len(diff):
            diff[b] -= 1
    cur = 0
    levels = []
    for i in range(span):
        cur += diff[i]
        levels.append(cur)
    return sum(levels) / len(levels), post.quantile(levels, 0.5), int(max(levels))


def share_stats(trades: list[dict]) -> dict:
    empty = {
        "pct_max_trade": float("nan"),
        "pct_max_sym": float("nan"),
        "pct_top10": float("nan"),
        "pct_bot10": float("nan"),
        "net_pnl_d": 0.0,
    }
    if not trades:
        return empty
    net = sum(t["pnl_d"] for t in trades)
    empty["net_pnl_d"] = net
    if net <= 0:
        return empty
    by_sym: dict[str, float] = {}
    for t in trades:
        by_sym[t["sym"]] = by_sym.get(t["sym"], 0.0) + t["pnl_d"]
    ranked = sorted(by_sym.values(), reverse=True)
    bot = sorted(by_sym.values())
    empty["pct_max_trade"] = 100.0 * max(t["pnl_d"] for t in trades) / net
    empty["pct_max_sym"] = 100.0 * max(ranked) / net
    empty["pct_top10"] = 100.0 * sum(ranked[:10]) / net
    empty["pct_bot10"] = 100.0 * sum(bot[:10]) / net
    return empty


def slice_of(trades: list[dict], which: str) -> list[dict]:
    return post.slice_trades(trades, which)


def pack(trades: list[dict]) -> dict:
    st = post.book_stats(trades)
    avg_pos, med_pos, max_pos = position_stats(trades)
    st["avg_pos"] = avg_pos
    st["med_pos"] = med_pos
    st["max_pos"] = max_pos
    st.update(share_stats(trades))
    st["exp_d"] = (st["avg"] / 100.0 * SHEET) if post.finite(st["avg"]) else float("nan")
    return st


def judge_universe(is_b: dict, is_a: dict, oos_b: dict, oos_a: dict) -> tuple[str, str]:
    """Full-universe arm versus the PaulTwenty arm. Same quality gates as the prior page.

    Trade count is not a reason to dismiss a wider book. OOS is report-only.
    """
    if is_a["n"] == 0:
        return "DISMISS", "In-sample full-universe arm is empty."
    avg_d = post.delta(is_a["avg"], is_b["avg"])
    ann_d = post.delta(is_a["ann_ror"], is_b["ann_ror"])
    pf_d = post.delta(is_a["pf"], is_b["pf"])
    dd_d = post.delta(is_a["max_dd"], is_b["max_dd"])
    wo_d = post.delta(is_a["wo_max"], is_b["wo_max"])
    med_d = post.delta(is_a["median"], is_b["median"])
    worse_core = post.finite(avg_d) and post.finite(ann_d) and avg_d < -0.05 and ann_d < -0.5
    better_core = post.finite(avg_d) and post.finite(ann_d) and avg_d > 0.05 and ann_d > 0.5
    pf_ok = post.finite(pf_d) and pf_d >= -0.02
    pf_better = post.finite(pf_d) and pf_d > 0.02
    dd_ok = (not post.finite(dd_d)) or dd_d <= 2.0
    wo_ok = post.finite(wo_d) and wo_d >= -0.15
    tail_only = post.finite(avg_d) and avg_d > 0.05 and post.finite(wo_d) and wo_d < -0.15
    oos_avg = post.delta(oos_a["avg"], oos_b["avg"])
    oos_ann = post.delta(oos_a["ann_ror"], oos_b["ann_ror"])
    oos_soft = post.finite(oos_avg) and post.finite(oos_ann) and oos_avg < -0.05 and oos_ann < -0.5
    stack = (
        " Max drawdown replays every closed trade onto one $500,000 account, so a wider "
        "list can print a deeper drawdown when more losses land on the same day."
    )

    if worse_core or (post.finite(avg_d) and avg_d < -0.15 and post.finite(ann_d) and ann_d < 0):
        verdict, why = (
            "DISMISS",
            "In-sample average percent and annualized rate of return on the full-universe arm "
            "are worse than the PaulTwenty arm.",
        )
    elif tail_only:
        verdict, why = (
            "HOLD",
            "The in-sample average lift does not survive after the single largest trade is left out.",
        )
    elif better_core and not dd_ok:
        verdict, why = (
            "HOLD",
            "In-sample average percent and annualized rate of return are better than the PaulTwenty arm, "
            "but max drawdown on the stacked account is worse by more than 2 points." + stack,
        )
    elif better_core and pf_better and dd_ok and wo_ok:
        verdict, why = (
            "KEEP",
            "In-sample average percent, profit factor, and annualized rate of return are better than "
            "the PaulTwenty arm, and the gain is not only the single largest trade.",
        )
    elif better_core and pf_ok and dd_ok and (wo_ok or (post.finite(med_d) and med_d >= 0)):
        verdict, why = (
            "LEAN KEEP",
            "In-sample average and annualized rate of return improve versus the PaulTwenty arm, "
            "with profit factor and drawdown not worse in a material way.",
        )
    else:
        verdict, why = (
            "HOLD",
            "In-sample quality is mixed versus the PaulTwenty arm. No knob is adopted.",
        )

    if verdict in ("KEEP", "LEAN KEEP") and oos_soft:
        verdict = "HOLD"
        why = (
            "In-sample looked better, but out-of-sample average and annualized rate of return "
            "both softened versus the PaulTwenty arm. Out-of-sample is report-only. Not retuned."
        )
    elif verdict == "HOLD" and oos_soft and better_core:
        why += " Out-of-sample average and annualized rate of return also softened. Not retuned."
    why += " Research only. Not gold. Not DailyRun."
    return verdict, why


def warehouse_symbols() -> list[str]:
    """Every CSV the Shannon loader can read. The generator does not drop SPY."""
    by: dict[str, Path] = {}
    for path in sh.DATA_DIR.glob("*.csv"):
        if not path.is_file():
            continue
        sym = path.stem.upper()
        if sym not in by or path.name == f"{sym}.csv":
            by[sym] = path
    return sorted(by)


def status_counts(status: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for st in status.values():
        key = st if st in ("ok", "short", "missing") else "error"
        out[key] = out.get(key, 0) + 1
    return out


HEAD_METRICS = [
    ("N", "n", "num", "int"),
    ("Wins", "wins", "num", "int"),
    ("Losses", "losses", "num", "int"),
    ("Win %", "wr", "num", "pct1"),
    ("Avg %", "avg", "num", "pct2"),
    ("Median %", "median", "num", "pct2"),
    ("Avg % w/o largest", "wo_max", "num", "pct2"),
    ("Profit factor", "pf", "num", "n2"),
    ("Ann ROR %", "ann_ror", "num", "pct1"),
    ("Max DD %", "max_dd", "num", "pct1"),
    ("Avg days", "avg_days", "num", "n1"),
    ("Trades/year", "tpy", "num", "n1"),
]

CANON_METRICS = [
    ("Universe listed", "listed", "num", "int"),
    ("Symbols with a trade", "syms", "num", "int"),
    ("N", "n", "num", "int"),
    ("Wins", "wins", "num", "int"),
    ("Losses", "losses", "num", "int"),
    ("Win %", "wr", "num", "pct1"),
    ("Avg %", "avg", "num", "pct2"),
    ("Median %", "median", "num", "pct2"),
    ("Avg % w/o largest", "wo_max", "num", "pct2"),
    ("Avg win %", "avg_win", "num", "pct2"),
    ("Avg loss %", "avg_loss", "num", "pct2"),
    ("Win/loss count", "wl_count", "num", "n2"),
    ("Profit factor", "pf", "num", "n2"),
    ("Ann ROR %", "ann_ror", "num", "pct1"),
    ("Max DD %", "max_dd", "num", "pct1"),
    ("Calmar", "calmar", "num", "n2"),
    ("Sharpe", "sharpe", "num", "n2"),
    ("Expectancy %", "avg", "num", "pct2"),
    ("Expectancy $", "exp_d", "num", "money"),
    ("$ / capital day", "ppcd", "num", "money"),
    ("Capital days", "cap_days", "num", "n0"),
    ("Avg days", "avg_days", "num", "n1"),
    ("Median days", "med_days", "num", "n1"),
    ("P90 days", "p90_days", "num", "n1"),
    ("Trades/year", "tpy", "num", "n1"),
    ("Losing streak", "streak", "num", "int"),
    ("Avg positions", "avg_pos", "num", "n2"),
    ("Median positions", "med_pos", "num", "n1"),
    ("Max positions", "max_pos", "num", "int"),
    ("% PnL largest trade", "pct_max_trade", "num", "pct1"),
    ("% PnL largest symbol", "pct_max_sym", "num", "pct1"),
    ("% PnL top 10 symbols", "pct_top10", "num", "pct1"),
    ("% PnL bottom 10 symbols", "pct_bot10", "num", "pct1"),
    ("With line target", "with_target", "num", "int"),
    ("Exit mix", "exits", "text", "exits"),
]

DELTA_KEYS = [
    ("Δ N", "n", "int"),
    ("Δ Win %", "wr", "pct1"),
    ("Δ Avg %", "avg", "pct2"),
    ("Δ Median %", "median", "pct2"),
    ("Δ Avg % w/o largest", "wo_max", "pct2"),
    ("Δ Profit factor", "pf", "n2"),
    ("Δ Ann ROR pp", "ann_ror", "n1"),
    ("Δ Max DD pp", "max_dd", "n1"),
    ("Δ Calmar", "calmar", "n2"),
    ("Δ Sharpe", "sharpe", "n2"),
    ("Δ Expectancy $", "exp_d", "money"),
    ("Δ Avg days", "avg_days", "n1"),
    ("Δ Trades/year", "tpy", "n1"),
]


def fmt_cell(st: dict, key: str, kind: str, n: int | None = None) -> str:
    if kind == "exits":
        return post.exit_mix_text(st.get("exits") or {}, int(st.get("n") or 0))
    val = st.get(key)
    if kind == "int":
        if not post.finite(val):
            return "—"
        return str(int(val))
    if kind == "pct1":
        return post.fmt_pct(val, 1)
    if kind == "pct2":
        return post.fmt_pct(val, 2)
    if kind == "n2":
        return post.fmt_num(val, 2)
    if kind == "n1":
        return post.fmt_num(val, 1)
    if kind == "n0":
        return post.fmt_num(val, 0)
    if kind == "money":
        return format_money(val) if post.finite(val) else "—"
    return "—"


def fmt_d(a: dict, b: dict, key: str, kind: str) -> str:
    if kind == "money":
        return format_money_delta(post.delta(a.get(key), b.get(key)))
    d = post.delta(a.get(key), b.get(key))
    if kind == "int":
        if not post.finite(d):
            return "—"
        v = int(round(d))
        sign = "+" if v > 0 else ""
        return f"{sign}{v}"
    if kind == "pct1":
        return post.fmt_delta(d, 1, " pp")
    if kind == "pct2":
        return post.fmt_delta(d, 2, " pp")
    if kind == "n2":
        return post.fmt_delta(d, 2, "")
    if kind == "n1":
        return post.fmt_delta(d, 1, "")
    return "—"


def th_row(cols: list[tuple[str, str]]) -> str:
    return "".join(post.sortable_th(label, kind) for label, kind in cols)


def tr(cells: list[str], total: bool = False) -> str:
    cls = ' class="total-row"' if total else ""
    return f"<tr{cls}>" + "".join(f"<td>{html_mod.escape(c)}</td>" for c in cells) + "</tr>"


def write_summary(rows: list[dict]) -> None:
    path = OUT_DIR / "summary.csv"
    fields = [
        "universe", "book", "slice", "listed", "ok_symbols", "verdict_role",
        "n", "wins", "losses", "wr", "avg", "median", "wo_max", "avg_win", "avg_loss",
        "wl_count", "pf", "ann_ror", "max_dd", "calmar", "sharpe", "exp_d", "ppcd",
        "cap_days", "avg_days", "med_days", "p90_days", "tpy", "streak",
        "avg_pos", "med_pos", "max_pos", "pct_max_trade", "pct_max_sym", "pct_top10",
        "pct_bot10", "with_target", "syms", "exits", "net_pnl_d",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            out = dict(row)
            out["exits"] = post.exit_mix_text(row.get("exits") or {}, int(row.get("n") or 0))
            w.writerow(out)


def write_trades(books: dict[tuple[str, str], list[dict]]) -> None:
    path = OUT_DIR / "trades.csv"
    cols = ["universe", "book", *SLIM_KEYS]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for (universe, book), trades in books.items():
            for t in trades:
                w.writerow([
                    universe,
                    book,
                    t["sym"],
                    t["signal"].isoformat(),
                    t["opened"].isoformat(),
                    t["closed"].isoformat(),
                    f"{t['entry']:.6f}",
                    t["exit"],
                    f"{t['pnl']:.6f}",
                    f"{t['r']:.6f}",
                    f"{t['days']:.0f}",
                    f"{t['pnl_d']:.4f}",
                    t["had_target"],
                    t["wsup_under"],
                ])


def line_stats(label: str, st: dict) -> str:
    return (
        f"{label}: N={st['n']} WR={st['wr']:.1f}% avg={st['avg']:.2f}% "
        f"median={st['median']:.2f}% PF={st['pf']:.2f} Ann ROR={st['ann_ror']:.1f}% "
        f"Max DD={st['max_dd']:.1f}% avg days={st['avg_days']:.1f}"
    )


def write_baseline(ctx: dict) -> None:
    p20 = ", ".join(ctx["paul20"])
    fc = ctx["counts_full"]
    err = ctx["errors"]
    err_txt = ", ".join(err[:12]) if err else "none"
    lines = [
        "# shannon_mtf_weekly_support_fulluniv_20260930",
        "",
        "Research only. Not gold. Not DailyRun. The arm is not wired into production, getTarget, or the daily run.",
        "The folders `shannon_mtf_lines_20260930` and `shannon_mtf_lines_post_ab_20260930` were not overwritten.",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        "The Shannon lines book buys pullbacks to rising lines. This test keeps a buy only when the weekly "
        "support line under the stock is rising. We run that on every stock we have prices for, and set it "
        "next to the same rule on the PaulTwenty list.",
        "",
        "Multi-Timeframe (MTF) means the month, the week, and the day. Annualized rate of return (Ann ROR) "
        "uses the house formula on this page and on the earlier Shannon page.",
        "",
        "## Frozen arm",
        "",
        PREDICATE,
        "",
        "Code: `tools/shannon_mtf_lines_post_ab_20260930.py` `weekly_support_under_close` and "
        "`Arm.require_weekly_support` on `entry_weekly_support`. This stamp imports that function. "
        "It does not add a second definition.",
        "",
        "## Universes",
        "",
        f"| Item | Choice |",
        f"|---|---|",
        f"| PaulTwenty | `{sh.PAULTWENTY.relative_to(ROOT).as_posix()}` — {len(ctx['paul20'])} symbols. "
        f"This is the list on the frozen Shannon stamp. There is not a second Paul20 file. |",
        f"| PaulTwenty names | {p20} |",
        f"| Full warehouse | Every `*.csv` under `{sh.DATA_DIR.relative_to(ROOT).as_posix()}`. "
        f"The Shannon generator reads those files and does not drop SPY, so SPY stays in. |",
        f"| Files | {ctx['n_files']} |",
        f"| Simulated (at least {sh.MIN_DAILY_BARS} daily bars) | {fc.get('ok', 0)} |",
        f"| Short history, skipped | {fc.get('short', 0)} |",
        f"| Unreadable | {fc.get('missing', 0)} |",
        f"| Errors | {fc.get('error', 0)} ({err_txt}) |",
        f"| SPY in the file list | {'yes' if ctx['spy'] else 'no'} |",
        "",
        "## Exit, unchanged",
        "",
        "Same as `drive/paul_experiments/shannon_mtf_lines_20260930/BASELINE.md`.",
        "Stop is the frozen trigger daily support line, projected each day. Target is frozen falling "
        "resistance, daily if overhead, else weekly. Same-bar stop and target: stop is filled. "
        "A week or month that is no longer up exits at the next open. No time stop. No 63-day clock. "
        "No percent target. No giveback. Costs 0. Sheet notional $45,000. Max drawdown seeds a "
        "$500,000 account at each exit date. Liquidity gate is still close ≥ $5 and 20-day average "
        "volume ≥ 500,000, applied inside the entry bar, not as a symbol drop.",
        "",
        "Ann ROR = `((1 + total dollar PnL / (45000 × n)) ** (365 / average days held) − 1) × 100`. "
        "That is an average-trade pace. A longer symbol list does not raise it by itself.",
        "",
        "## IS / OOS",
        "",
        "In-sample: entry date (`opened`) before 2024-01-01. Out-of-sample: entry date on or after "
        "2024-01-01. OOS is report-only. Knobs were not picked from OOS and were not retuned.",
        "",
        "## Paul20 match",
        "",
        "Paul20 control was resimulated on this code path and matched the frozen `trades.csv` "
        f"trade for trade (symbol, entry date, exit, percent). Published page: 714 trades, 41.9% wins, "
        f"1.33% average. Recomputed here: N={ctx['p20_ctrl']['full']['n']}, "
        f"WR={ctx['p20_ctrl']['full']['wr']:.1f}%, avg={ctx['p20_ctrl']['full']['avg']:.2f}%, "
        f"Ann ROR={ctx['p20_ctrl']['full']['ann_ror']:.1f}%.",
        "",
        "Paul20 weekly arm matched the post-analysis `trades.csv` rows for `entry_weekly_support`. "
        f"Published page: 506 trades, 39.9% wins, 1.49% average, 25.1% Ann ROR. "
        f"Recomputed here: N={ctx['p20_arm']['full']['n']}, WR={ctx['p20_arm']['full']['wr']:.1f}%, "
        f"avg={ctx['p20_arm']['full']['avg']:.2f}%, Ann ROR={ctx['p20_arm']['full']['ann_ror']:.1f}%.",
        "",
        "## Headline",
        "",
        "Compare the full-universe weekly arm with the PaulTwenty weekly arm. "
        "Both controls are on the page so a longer list is not read as the filter.",
        "",
        f"Filter vs its own control, PaulTwenty: **{ctx['filter_p20'][0]}**. {ctx['filter_p20'][1]}",
        "",
        f"Filter vs its own control, full warehouse: **{ctx['filter_full'][0]}**. {ctx['filter_full'][1]}",
        "",
        f"Full-universe arm vs PaulTwenty arm: **{ctx['verdict'][0]}**. {ctx['verdict'][1]}",
        "",
        "## Not produced",
        "",
        "No daily equity curve, so days underwater and EquityMeta Sharpe (square root of 252) are not shown. "
        "Sharpe here is exit-date equity, no risk-free rate, annualized by how often exits occur. "
        "Paul Score, FIT, and industry shares are not produced by this book. "
        "Share of net dollar PnL is blank when the slice's net dollar PnL is not positive. "
        "Total PnL $ and Sheet PnL $ are left off the HTML tables.",
        "",
        "## Books",
        "",
    ]
    for title, block in (
        ("PaulTwenty control", ctx["p20_ctrl"]),
        ("PaulTwenty weekly arm", ctx["p20_arm"]),
        ("Full warehouse control", ctx["full_ctrl"]),
        ("Full warehouse weekly arm", ctx["full_arm"]),
    ):
        lines.append(f"### {title}")
        lines.append("")
        for sl in ("full", "IS", "OOS"):
            lines.append(f"- {line_stats(sl, block[sl])}")
        lines.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(ctx: dict) -> None:
    slices = ("full", "IS", "OOS")
    books = [
        ("PaulTwenty", "Control", ctx["p20_ctrl"], ctx["listed_p20"]),
        ("PaulTwenty", "Weekly rising support", ctx["p20_arm"], ctx["listed_p20"]),
        ("Full warehouse", "Control", ctx["full_ctrl"], ctx["listed_full"]),
        ("Full warehouse", "Weekly rising support", ctx["full_arm"], ctx["listed_full"]),
    ]

    head_cols = [("Universe", "text"), ("Book", "text"), ("Slice", "text")] + [
        (a, c) for a, _k, c, _f in HEAD_METRICS
    ]
    head_rows = []
    for universe, book, block, _listed in books:
        for sl in slices:
            st = block[sl]
            cells = [universe, book, sl]
            cells += [fmt_cell(st, key, kind) for _a, key, _c, kind in HEAD_METRICS]
            head_rows.append(tr(cells))

    def delta_rows(left_name: str, right_name: str, left: dict, right: dict) -> list[str]:
        rows = []
        for sl in slices:
            cells = [f"{left_name} − {right_name}", sl]
            cells += [fmt_d(left[sl], right[sl], key, kind) for _a, key, kind in DELTA_KEYS]
            rows.append(tr(cells))
        return rows

    dcols = [("Compare", "text"), ("Slice", "text")] + [(a, "num") for a, _k, _f in DELTA_KEYS]
    headline_delta = delta_rows(
        "Full weekly arm", "PaulTwenty weekly arm", ctx["full_arm"], ctx["p20_arm"]
    )
    filter_delta = delta_rows(
        "PaulTwenty arm", "PaulTwenty control", ctx["p20_arm"], ctx["p20_ctrl"]
    ) + delta_rows(
        "Full arm", "Full control", ctx["full_arm"], ctx["full_ctrl"]
    )

    canon_cols = [("Universe", "text"), ("Book", "text"), ("Slice", "text")] + [
        (a, c) for a, _k, c, _f in CANON_METRICS
    ]
    canon_rows = []
    for universe, book, block, listed in books:
        for sl in slices:
            st = dict(block[sl])
            st["listed"] = listed
            cells = [universe, book, sl]
            cells += [fmt_cell(st, key, kind) for _a, key, _c, kind in CANON_METRICS]
            canon_rows.append(tr(cells))

    v, why = ctx["verdict"]
    fp_v, fp_why = ctx["filter_p20"]
    ff_v, ff_why = ctx["filter_full"]
    fc = ctx["counts_full"]
    err = ctx["errors"]
    err_txt = ", ".join(html_mod.escape(e) for e in err[:12]) if err else "none"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Shannon weekly rising support — full warehouse vs PaulTwenty</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 1.25rem auto; max-width: 1280px;
  padding: 0 1rem 2rem; color: #1f1d1a; background: #f7f4ee; }}
h1 {{ font-size: 1.45rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.4rem; }}
.sub {{ color: #5c564c; font-size: 0.92rem; }}
.callout {{ background: #fff; border: 1px solid #d9d1c3; padding: 0.8rem 1rem; margin: 0.8rem 0; }}
.callout.verdict {{ border-color: #8d6a2f; background: #fffaf0; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.78rem; margin: 0.4rem 0 1.2rem; }}
th, td {{ border: 1px solid #e3dccf; padding: 0.28rem 0.4rem; text-align: left; vertical-align: top; }}
.wrap {{ overflow-x: auto; }}
{post.SORT_CSS}
code {{ font-size: 0.86em; }}
</style>
</head>
<body>
<h1>Shannon weekly rising support, full warehouse next to PaulTwenty</h1>
<p class="sub">Stamp <code>shannon_mtf_weekly_support_fulluniv_20260930</code> ·
earlier Shannon folders left untouched · research only · not gold · not DailyRun</p>

<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>The Shannon lines book buys pullbacks to rising lines. This test keeps a buy only when the weekly
support line under the stock is rising. We run that on every stock we have prices for, and set it
next to the same rule on the PaulTwenty list.</p>
<p>Multi-Timeframe (MTF) here means the month, the week, and the day already have to agree before
the daily buy, the same way the frozen book works. This test adds one check on top: a rising weekly
support line, with the signal close above that line. The way out of the trade does not change.
Annualized rate of return (Ann ROR) is the house pace for an average trade: combine the trades'
dollar result with a $45,000 sheet per trade and how many days they were held, using 365 days in
the year. A longer stock list does not raise that pace by itself. In-sample (IS) is an entry before
2024-01-01. Out-of-sample (OOS) is an entry on or after that date. OOS is a report. It did not pick
a setting, and nothing was retuned.</p>
</div>

<div class="callout verdict">
<h2>Verdict</h2>
<p>Headline: full-warehouse weekly arm versus the PaulTwenty weekly arm.
<b>{html_mod.escape(v)}</b>. {html_mod.escape(why)}</p>
<p>The filter against its own control, same exits, PaulTwenty:
<b>{html_mod.escape(fp_v)}</b>. {html_mod.escape(fp_why)}</p>
<p>The filter against its own control, same exits, full warehouse:
<b>{html_mod.escape(ff_v)}</b>. {html_mod.escape(ff_why)}</p>
<p>PaulTwenty control on this run matched the frozen book trade for trade
(N={ctx['p20_ctrl']['full']['n']}, win rate {ctx['p20_ctrl']['full']['wr']:.1f}%,
average {ctx['p20_ctrl']['full']['avg']:.2f}%). The published page was 714 / 41.9% / 1.33%.
Research only. Not gold. Not DailyRun.</p>
</div>

<h2>Symbol counts</h2>
<p class="sub">PaulTwenty is <code>drive/universes/PaulTwenty_universe.csv</code>,
{ctx['listed_p20']} names: {html_mod.escape(', '.join(ctx['paul20']))}.
That is the Shannon stamp list. The full warehouse is every CSV under
<code>data/newdata/data</code>, {ctx['n_files']} files. The Shannon loader does not drop the
index, so SPY {'is' if ctx['spy'] else 'is not'} in that list.
{fc.get('ok', 0)} files had at least {sh.MIN_DAILY_BARS} daily bars and were simulated.
{fc.get('short', 0)} were shorter and were skipped. Unreadable: {fc.get('missing', 0)}.
Errors: {fc.get('error', 0)} ({err_txt}).</p>

<h2>The rule, frozen</h2>
<p>{html_mod.escape(PREDICATE)}</p>
<p class="sub">Entry fill, stop, target, and the higher-timeframe exit are the frozen Shannon book.
No 63-day time stop. Click column headers to sort.</p>

<h2>Headline books</h2>
<p class="sub">Click column headers to sort. Ann ROR is annualized rate of return.
Max DD is max drawdown on the stacked $500,000 exit-date account.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{th_row(head_cols)}</tr></thead>
<tbody>
{''.join(head_rows)}
</tbody>
</table>
</div>

<h2>Full-universe arm minus PaulTwenty arm</h2>
<p class="sub">This is the compare you asked for. Each number is the full-warehouse weekly arm
minus the PaulTwenty weekly arm, same slice. A positive max-drawdown delta is a deeper drawdown.
Click column headers to sort.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{th_row(dcols)}</tr></thead>
<tbody>
{''.join(headline_delta)}
</tbody>
</table>
</div>

<h2>Filter minus control, same universe</h2>
<p class="sub">These rows are the weekly-support check by itself. They are not the universe change.
Click column headers to sort.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{th_row(dcols)}</tr></thead>
<tbody>
{''.join(filter_delta)}
</tbody>
</table>
</div>

<h2>Canonical compare metrics</h2>
<p class="sub">Absolute values. Dollar cells use thousands separators and two decimals.
Share-of-PnL cells stay blank when the slice's net dollar result is not positive.
Sharpe is exit-date equity, no risk-free rate. Positions count calendar days in the book span,
one per day the trade's held-day count covers. Click column headers to sort.
FIT, Paul Score, industry, and days underwater are not on this book.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{th_row(canon_cols)}</tr></thead>
<tbody>
{''.join(canon_rows)}
</tbody>
</table>
</div>

<p class="sub">Ann ROR formula, same as the Shannon report and <code>compare_format.ann_ror_from_closed</code>:
((1 + total dollar PnL / (45000 × number of trades)) ^ (365 / average days held) − 1) × 100.
Max drawdown replays those closed dollars onto a $500,000 account at each exit date.</p>
{post.SORT_JS}
</body>
</html>
"""
    (OUT_DIR / "compare.html").write_text(page, encoding="utf-8")


def main() -> None:
    workers = 8
    if len(sys.argv) >= 3 and sys.argv[1] == "--workers":
        workers = max(1, int(sys.argv[2]))
    paul20 = sh.load_universe(sh.PAULTWENTY)
    print(f"PaulTwenty listed {len(paul20)}: {' '.join(paul20)}", flush=True)
    p20_ctrl, p20_arm, _p20_status = run_serial(paul20)
    verify_paul20(p20_ctrl, p20_arm)

    symbols = warehouse_symbols()
    spy = "SPY" in symbols
    print(f"Warehouse files {len(symbols)} SPY={spy} workers={workers}", flush=True)
    full_ctrl, full_arm, status = run_pool(symbols, workers)
    # Same code path: the pool's PaulTwenty names must match the serial check.
    pool_ctrl = [t for t in full_ctrl if t["sym"] in set(paul20)]
    pool_arm = [t for t in full_arm if t["sym"] in set(paul20)]
    pool_ctrl.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    pool_arm.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    if [_ident(t) for t in pool_ctrl] != [_ident(t) for t in p20_ctrl]:
        raise SystemExit("Pool PaulTwenty control diverged from the serial match. Full book not trusted.")
    if [_ident(t) for t in pool_arm] != [_ident(t) for t in p20_arm]:
        raise SystemExit("Pool PaulTwenty arm diverged from the serial match. Full book not trusted.")
    print("Pool PaulTwenty subset matches the serial 714 / 506 books.", flush=True)

    def blocks(trades: list[dict]) -> dict:
        return {sl: pack(slice_of(trades, sl)) for sl in ("full", "IS", "OOS")}

    p20_c = blocks(p20_ctrl)
    p20_a = blocks(p20_arm)
    full_c = blocks(full_ctrl)
    full_a = blocks(full_arm)
    filter_p20 = post.judge(WEEKLY, p20_c["IS"], p20_a["IS"], p20_c["OOS"], p20_a["OOS"])
    filter_full = post.judge(WEEKLY, full_c["IS"], full_a["IS"], full_c["OOS"], full_a["OOS"])
    verdict = judge_universe(p20_a["IS"], full_a["IS"], p20_a["OOS"], full_a["OOS"])
    print(f"FILTER Paul20 {filter_p20[0]}: {filter_p20[1]}", flush=True)
    print(f"FILTER full {filter_full[0]}: {filter_full[1]}", flush=True)
    print(f"UNIVERSE {verdict[0]}: {verdict[1]}", flush=True)
    for name, block in (
        ("P20 control", p20_c),
        ("P20 arm", p20_a),
        ("FULL control", full_c),
        ("FULL arm", full_a),
    ):
        for sl in ("full", "IS", "OOS"):
            print(line_stats(f"{name} {sl}", block[sl]), flush=True)

    counts = status_counts(status)
    errors = [f"{sym} {st}" for sym, st in sorted(status.items()) if st.startswith("error")]
    ctx = {
        "paul20": paul20,
        "n_files": len(symbols),
        "spy": spy,
        "counts_full": counts,
        "errors": errors,
        "listed_p20": len(paul20),
        "listed_full": len(symbols),
        "p20_ctrl": p20_c,
        "p20_arm": p20_a,
        "full_ctrl": full_c,
        "full_arm": full_a,
        "filter_p20": filter_p20,
        "filter_full": filter_full,
        "verdict": verdict,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    role = {
        ("PaulTwenty", "Control"): "",
        ("PaulTwenty", "Weekly rising support"): filter_p20[0],
        ("Full warehouse", "Control"): "",
        ("Full warehouse", "Weekly rising support"): verdict[0],
    }
    for universe, book, block, listed, ok_n in (
        ("PaulTwenty", "Control", p20_c, len(paul20), sum(1 for s in paul20 if status.get(s) == "ok")),
        ("PaulTwenty", "Weekly rising support", p20_a, len(paul20), sum(1 for s in paul20 if status.get(s) == "ok")),
        ("Full warehouse", "Control", full_c, len(symbols), counts.get("ok", 0)),
        ("Full warehouse", "Weekly rising support", full_a, len(symbols), counts.get("ok", 0)),
    ):
        for sl, st in block.items():
            row = dict(st)
            row.update({
                "universe": universe,
                "book": book,
                "slice": sl,
                "listed": listed,
                "ok_symbols": ok_n,
                "verdict_role": role[(universe, book)] if sl == "full" else "",
            })
            summary_rows.append(row)
    write_summary(summary_rows)
    write_trades({
        ("PaulTwenty", "control"): p20_ctrl,
        ("PaulTwenty", "weekly_support"): p20_arm,
        ("full", "control"): full_ctrl,
        ("full", "weekly_support"): full_arm,
    })
    write_baseline(ctx)
    write_html(ctx)
    print(f"WROTE {OUT_DIR / 'compare.html'}", flush=True)


if __name__ == "__main__":
    main()
