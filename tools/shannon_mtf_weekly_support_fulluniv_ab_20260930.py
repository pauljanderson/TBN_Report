#!/usr/bin/env python3
"""One-knob A/B on the frozen full-universe weekly rising support book.

Control is the published weekly arm in
drive/paul_experiments/shannon_mtf_weekly_support_fulluniv_20260930/.
Does not overwrite that folder or the earlier Shannon stamps.
Research only. Not gold. Not DailyRun.

  python tools/shannon_mtf_weekly_support_fulluniv_ab_20260930.py
  python tools/shannon_mtf_weekly_support_fulluniv_ab_20260930.py --workers 8
"""
from __future__ import annotations

import csv
import html as html_mod
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import shannon_mtf_lines_20260930 as sh  # noqa: E402
import shannon_mtf_lines_post_ab_20260930 as post  # noqa: E402
import shannon_mtf_weekly_support_fulluniv_20260930 as uni  # noqa: E402
from compare_format import format_money, format_money_delta  # noqa: E402

PRIOR_DIR = ROOT / "drive" / "paul_experiments" / "shannon_mtf_weekly_support_fulluniv_20260930"
OUT_DIR = ROOT / "drive" / "paul_experiments" / "shannon_mtf_weekly_support_fulluniv_ab_20260930"
PRIOR_TRADES = PRIOR_DIR / "trades.csv"
IS_CUT = sh.IS_CUT
SHEET = sh.SHEET
BIG_WIN = post.BIG_WIN
PUBLISHED_N = 14582
TOL_N = 50

ORIGINAL_REQUEST = (
    "run the weekly rising support against the full universe and then run "
    "post analysis and wire and run AB tests. tell me what you find."
)

PACK_KEYS = (
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
    "tgt_tf",
    "risk_pct",
    "stop_slope_pct_day",
)

_WEEKLY = next(a for a in post.ARMS if a.key == "entry_weekly_support")
_REQ = next(a for a in post.ARMS if a.key == "entry_require_target")
_SKIP = next(a for a in post.ARMS if a.key == "entry_only_no_target")
_PCT = next(a for a in post.ARMS if a.key == "exit_pct20_if_no_line")
_TIME = next(a for a in post.ARMS if a.key == "exit_time_63")
_GIVE = next(a for a in post.ARMS if a.key == "exit_giveback_half")

CONTROL = replace(
    _WEEKLY,
    key="control",
    label="Full-universe weekly rising support",
    kind="CONTROL",
    bias="frozen",
    rule=(
        "The published full-warehouse weekly rising support book. A Shannon buy is taken "
        "only when a rising weekly support line exists and the signal close is strictly above it. "
        "Exits stay the frozen Shannon exits. This rule is the control."
    ),
)
ENTRY_REQUIRE = replace(
    _REQ,
    require_weekly_support=True,
    label="Require a line target",
    rule=(
        "Buy only when a falling resistance line is still above the entry, and the weekly "
        "rising support rule already holds. Same exits. A skipped signal does not lock the symbol."
    ),
)
ENTRY_NO_TARGET = replace(
    _SKIP,
    require_weekly_support=True,
    label="Only entries with no target",
    bias="selection",
    rule=(
        "Skip buys that have a falling resistance line overhead. The weekly rising support "
        "rule already holds. Same exits. Labeled in-sample selection because the PaulTwenty "
        "winners had no target. A skipped signal does not lock the symbol."
    ),
)
EXIT_PCT = replace(
    _PCT,
    label="20% target when the target cell is blank",
    rule=(
        "Same entries as the full-universe weekly control. When the Shannon target cell would "
        "be blank, also sell at +20% from the entry (gap at the open, or the high touches it). "
        "Trades that already have a line target keep that line. Stop and higher-timeframe exits unchanged."
    ),
)
EXIT_TIME = replace(
    _TIME,
    label="63-calendar-day time stop",
    rule=(
        "Same entries as the full-universe weekly control. If the trade is still open 63 calendar "
        "days after the entry, sell at that close. Stop, line target, and higher-timeframe exits "
        "are checked first on that bar. 63 days is one pre-set quarter, not a search over day counts."
    ),
)
EXIT_GIVE = replace(
    _GIVE,
    label="Half giveback after +10%",
    rule=(
        "Same entries as the full-universe weekly control. Once a prior bar's high is at least 10% "
        "above the entry, a giveback price is halfway from the highest high since entry back down "
        "to the entry. From the next day, a gap through that price sells at the open; a close through "
        "it sells at the close. Stop and higher-timeframe exits are checked first."
    ),
)
PAUL_REF = post.Arm(
    key="paul20_weekly",
    label="PaulTwenty weekly rising support",
    kind="REFERENCE",
    bias="published",
    rule=(
        "The same weekly rising support rule on drive/universes/PaulTwenty_universe.csv (20 names). "
        "Repeated from the published page so the universe gap stays visible. Not an arm in this test."
    ),
)

TESTED = [CONTROL, ENTRY_REQUIRE, ENTRY_NO_TARGET, EXIT_PCT, EXIT_TIME, EXIT_GIVE]
DISPLAY = [CONTROL, PAUL_REF, ENTRY_REQUIRE, ENTRY_NO_TARGET, EXIT_PCT, EXIT_TIME, EXIT_GIVE]
EXIT_ARMS = [EXIT_PCT, EXIT_TIME, EXIT_GIVE]


def pack_trade(t: dict) -> dict:
    out = {}
    for k in PACK_KEYS:
        out[k] = t.get(k, "" if k == "tgt_tf" else float("nan"))
    return out


def run_symbol(sym: str) -> tuple:
    try:
        df = sh.load_ohlc(sym)
        if df is None:
            return sym, "missing", {}, {}
        if len(df) < sh.MIN_DAILY_BARS:
            return sym, "short", {}, {}
        piv_d = sh.confirmed_pivots_daily(df, sh.PIVOT_K["daily"])
        piv_w = sh.confirmed_pivots_htf(df, sh.WEEK_FREQ, sh.PIVOT_K["weekly"])
        arrays, ctx = post.prepare(sym, df)
        base = post.simulate_entries(sym, df, piv_d, piv_w, arrays, CONTROL)
        books = {
            CONTROL.key: [pack_trade(t) for t in base],
            ENTRY_REQUIRE.key: [pack_trade(t) for t in post.simulate_entries(sym, df, piv_d, piv_w, arrays, ENTRY_REQUIRE)],
            ENTRY_NO_TARGET.key: [pack_trade(t) for t in post.simulate_entries(sym, df, piv_d, piv_w, arrays, ENTRY_NO_TARGET)],
        }
        exits = {
            arm.key: [pack_trade(post.replay_exit(ctx, t, arm)) for t in base]
            for arm in EXIT_ARMS
        }
        return sym, "ok", books, exits
    except Exception as exc:
        return sym, f"error:{type(exc).__name__}:{exc}", {}, {}


def _iso(v) -> str:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:10]


def ident(t: dict) -> tuple:
    had = t["had_target"]
    if isinstance(had, str):
        had = had == "True"
    return (
        t["sym"],
        _iso(t["signal"]),
        _iso(t["opened"]),
        t["exit"],
        round(float(t["pnl"]), 6),
        bool(had),
    )


def load_prior(book: str, universe: str) -> list[dict]:
    rows = []
    with PRIOR_TRADES.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["universe"] != universe or r["book"] != book:
                continue
            rows.append({
                "sym": r["sym"],
                "signal": date.fromisoformat(r["signal"]),
                "opened": date.fromisoformat(r["opened"]),
                "closed": date.fromisoformat(r["closed"]),
                "entry": float(r["entry"]),
                "exit": r["exit"],
                "pnl": float(r["pnl"]),
                "r": float(r["r"]),
                "days": float(r["days"]),
                "pnl_d": float(r["pnl_d"]),
                "had_target": r["had_target"] == "True",
                "wsup_under": r["wsup_under"] == "True",
                "tgt_tf": "",
                "risk_pct": float("nan"),
                "stop_slope_pct_day": float("nan"),
            })
    rows.sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    return rows


def match_control(got: list[dict], frozen: list[dict]) -> tuple[bool, str]:
    g = sorted(got, key=lambda t: (t["opened"], t["sym"], t["signal"]))
    f = frozen
    n_gap = abs(len(g) - len(f))
    gi = [ident(t) for t in g]
    fi = [ident(t) for t in f]
    mismatches = []
    for i, (a, b) in enumerate(zip(fi, gi)):
        if a != b:
            mismatches.append((i, a, b))
            if len(mismatches) >= 5:
                break
    extra = abs(len(fi) - len(gi))
    ok = n_gap <= TOL_N and len(mismatches) == 0 and extra <= TOL_N and len(g) == PUBLISHED_N
    # Exact identity on the overlapping prefix, and published count, is the bar.
    # A handful of trailing extras would still be a mismatch when lengths differ.
    if len(g) != len(f) or mismatches:
        ok = False
    lines = [
        f"Resim N={len(g)} published N={len(f)} (expected {PUBLISHED_N}).",
        f"Identity mismatches in the overlapping prefix: {len(mismatches)} shown, length gap {n_gap}.",
    ]
    for i, a, b in mismatches:
        lines.append(f"  row {i}: published {a} vs resim {b}")
    if len(g) == len(f) and not mismatches:
        lines.append("Control matches the published 14,582-trade weekly book trade for trade.")
        ok = True
    return ok, "\n".join(lines)


def slice_stats(trades: list[dict]) -> dict:
    out = {}
    for sl in ("full", "IS", "OOS"):
        out[sl] = uni.pack(post.slice_trades(trades, sl))
    return out


def arm_verdict(arm: post.Arm, stats: dict) -> tuple[str, str]:
    if arm.kind == "REFERENCE":
        return (
            "REFERENCE",
            "Same weekly rule on the 20-name Paul list. Shown so the universe gap stays visible. "
            "This row is not a knob on the full-universe book.",
        )
    if arm.kind == "CONTROL":
        return (
            "CONTROL",
            "Published full-universe weekly rising support book. The other arms are judged against this row.",
        )
    v, why = post.judge(
        arm,
        stats[CONTROL.key]["IS"],
        stats[arm.key]["IS"],
        stats[CONTROL.key]["OOS"],
        stats[arm.key]["OOS"],
    )
    if arm.key == ENTRY_REQUIRE.key:
        why += (
            " In-sample average percent is lower. In-sample annualized rate of return is higher "
            "because these trades last about three days. Out-of-sample average is about zero and "
            "out-of-sample annualized rate of return is about zero. Out-of-sample is report-only. Not retuned."
        )
    if arm.key == EXIT_TIME.key and v == "HOLD":
        why += (
            " In-sample average percent and profit factor barely move. In-sample annualized rate of return "
            "is a little higher, and out-of-sample annualized rate of return did not soften. That lift does not "
            "clear the keep bar. Out-of-sample is report-only. Not retuned."
        )
    if arm.key == ENTRY_NO_TARGET.key:
        why += (
            " Chosen because the PaulTwenty trades at or above +20% had a blank target. "
            "On this full-universe control every trade at or above +20% also has a blank target, "
            "so a keep based on that tail would be in-sample selection."
        )
    return v, why


def describe_winners(big: list[dict], control: list[dict]) -> str:
    if not big:
        return "No control trade reached the cutoff."
    days = [float(t["days"]) for t in big]
    rest = [float(t["days"]) for t in control if float(t["pnl"]) < BIG_WIN]
    exits = Counter(t["exit"] for t in big)
    syms = Counter(t["sym"] for t in big)
    had = sum(1 for t in big if t["had_target"])
    exit_s = ", ".join(f"{k} {v}" for k, v in exits.most_common())
    top_syms = ", ".join(f"{s} ({c})" for s, c in syms.most_common(8))
    return (
        f"{len(big)} control trades gained {BIG_WIN:.0f}% or more. "
        f"{had} of them had a line target. "
        f"Exit reasons: {exit_s}. "
        f"Median hold {post.quantile(days, 0.5):.0f} calendar days "
        f"(other trades median {post.quantile(rest, 0.5):.0f} calendar days). "
        f"Names that show up most: {top_syms}. "
        f"This is a description of the control. A filter is not adopted because it would have kept these trades."
    )


def write_trades(books: dict[str, list[dict]]) -> None:
    path = OUT_DIR / "trades.csv"
    cols = ["arm", *PACK_KEYS]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for arm in DISPLAY:
            for t in books[arm.key]:
                w.writerow([
                    arm.key,
                    t["sym"],
                    _iso(t["signal"]),
                    _iso(t["opened"]),
                    _iso(t["closed"]),
                    f"{float(t['entry']):.6f}",
                    t["exit"],
                    f"{float(t['pnl']):.6f}",
                    f"{float(t['r']):.6f}",
                    f"{float(t['days']):.0f}",
                    f"{float(t['pnl_d']):.4f}",
                    t["had_target"],
                    t["wsup_under"],
                    t.get("tgt_tf") or "",
                    "" if not post.finite(t.get("risk_pct")) else f"{float(t['risk_pct']):.4f}",
                    "" if not post.finite(t.get("stop_slope_pct_day")) else f"{float(t['stop_slope_pct_day']):.6f}",
                ])


def write_summary(stats: dict, verdicts: dict) -> None:
    path = OUT_DIR / "summary.csv"
    fields = [
        "arm", "label", "kind", "bias", "slice", "verdict",
        "n", "wins", "losses", "wr", "avg", "median", "wo_max", "avg_win", "avg_loss",
        "wl_count", "pf", "ann_ror", "max_dd", "calmar", "sharpe", "exp_d", "ppcd",
        "cap_days", "avg_days", "med_days", "p90_days", "tpy", "streak",
        "avg_pos", "med_pos", "max_pos", "pct_max_trade", "pct_max_sym", "pct_top10",
        "pct_bot10", "with_target", "syms",
        "d_n", "d_wr", "d_avg", "d_median", "d_wo_max", "d_pf", "d_ann_ror", "d_max_dd",
        "d_calmar", "d_sharpe", "d_exp_d", "d_avg_days", "d_tpy", "exits",
    ]
    delta_keys = [
        "n", "wr", "avg", "median", "wo_max", "pf", "ann_ror", "max_dd",
        "calmar", "sharpe", "exp_d", "avg_days", "tpy",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for arm in DISPLAY:
            v, _why = verdicts[arm.key]
            for sl in ("full", "IS", "OOS"):
                st = stats[arm.key][sl]
                base = stats[CONTROL.key][sl]
                row = {k: st.get(k, "") for k in fields}
                row.update({
                    "arm": arm.key,
                    "label": arm.label,
                    "kind": arm.kind,
                    "bias": arm.bias,
                    "slice": sl,
                    "verdict": v if sl == "full" else "",
                    "exits": post.exit_mix_text(st.get("exits") or {}, int(st.get("n") or 0)),
                })
                for k in delta_keys:
                    row[f"d_{k}"] = "" if arm.key == CONTROL.key else post.delta(st.get(k), base.get(k))
                w.writerow(row)


def fmt_cell(st: dict, key: str, kind: str) -> str:
    return uni.fmt_cell(st, key, kind)


def delta_cell(st: dict, base: dict, key: str, kind: str, is_control: bool) -> str:
    if is_control:
        return "—"
    return uni.fmt_d(st, base, key, kind)


METRIC_COLS = [
    ("N", "n", "int"),
    ("Win %", "wr", "pct1"),
    ("Avg %", "avg", "pct2"),
    ("Median %", "median", "pct2"),
    ("Avg % w/o largest", "wo_max", "pct2"),
    ("Avg win %", "avg_win", "pct2"),
    ("Avg loss %", "avg_loss", "pct2"),
    ("Win/loss count", "wl_count", "n2"),
    ("Profit factor", "pf", "n2"),
    ("Ann ROR %", "ann_ror", "pct1"),
    ("Max DD %", "max_dd", "pct1"),
    ("Calmar", "calmar", "n2"),
    ("Sharpe", "sharpe", "n2"),
    ("Expectancy $", "exp_d", "money"),
    ("$ / capital day", "ppcd", "money"),
    ("Capital days", "cap_days", "n0"),
    ("Avg days", "avg_days", "n1"),
    ("Median days", "med_days", "n1"),
    ("P90 days", "p90_days", "n1"),
    ("Trades/year", "tpy", "n1"),
    ("Losing streak", "streak", "int"),
    ("Avg positions", "avg_pos", "n2"),
    ("Median positions", "med_pos", "n1"),
    ("Max positions", "max_pos", "int"),
    ("% PnL largest trade", "pct_max_trade", "pct1"),
    ("% PnL largest symbol", "pct_max_sym", "pct1"),
    ("% PnL top 10 symbols", "pct_top10", "pct1"),
    ("% PnL bottom 10 symbols", "pct_bot10", "pct1"),
    ("With line target", "with_target", "int"),
    ("Symbols traded", "syms", "int"),
]
DELTA_COLS = [
    ("Δ N", "n", "int"),
    ("Δ Win %", "wr", "pct1"),
    ("Δ Avg %", "avg", "pct2"),
    ("Δ Median %", "median", "pct2"),
    ("Δ Avg % w/o largest", "wo_max", "pct2"),
    ("Δ Profit factor", "pf", "n2"),
    ("Δ Ann ROR", "ann_ror", "pct1"),
    ("Δ Max DD", "max_dd", "pct1"),
    ("Δ Calmar", "calmar", "n2"),
    ("Δ Sharpe", "sharpe", "n2"),
    ("Δ Expectancy $", "exp_d", "money"),
    ("Δ Avg days", "avg_days", "n1"),
    ("Δ Trades/year", "tpy", "n1"),
]


def write_baseline(info: dict, verdicts: dict, stats: dict, match_text: str) -> None:
    lines = [
        "# shannon_mtf_weekly_support_fulluniv_ab_20260930",
        "",
        "Research only. Not gold. Not DailyRun. No arm is wired into production, getTarget, or the daily run.",
        "The folders `shannon_mtf_lines_20260930`, `shannon_mtf_lines_post_ab_20260930`, and "
        "`shannon_mtf_weekly_support_fulluniv_20260930` were not overwritten.",
        "",
        "## What you asked",
        "",
        ORIGINAL_REQUEST,
        "",
        "## In plain English",
        "",
        "We already ran the weekly rising support rule on every stock. This page starts from that book "
        "and tries one extra rule at a time, things like a time limit or a profit target, to see if the "
        "full-universe results get better. It also sets those numbers next to the same weekly rule on the "
        "20-name Paul list. Annualized rate of return (Ann ROR) is spelled out the first time below and "
        "uses the same house formula as the earlier Shannon page.",
        "",
        "Multi-Timeframe (MTF) means the month, the week, and the day.",
        "",
        "## Control match",
        "",
        match_text,
        "",
        f"Published full-universe weekly arm reused as the control: N={PUBLISHED_N}, "
        "win rate 37.2%, average 0.33%, Ann ROR 5.8%, max drawdown 30.3%. "
        f"In-sample (entry before {IS_CUT.isoformat()}): 11,471 / 37.9% / 0.33% / 5.9% / 30.3%. "
        f"Out-of-sample (entry on or after {IS_CUT.isoformat()}): 3,111 / 34.4% / 0.29% / 5.6% / 42.7%. "
        "Out-of-sample is report-only. Nothing was retuned on it.",
        "",
        "The weekly rising support rule is the control. It is not an arm on this page.",
        "",
        "## Exit and entry identity",
        "",
        "Exits on the control match `drive/paul_experiments/shannon_mtf_lines_post_ab_20260930/BASELINE.md`. "
        "Stop is the frozen trigger daily support line. Target is frozen falling resistance, daily if overhead, "
        "else weekly. Same-bar stop and target: the stop is filled. A week or month that is no longer up exits "
        "at the next open. Costs 0. Sheet notional $45,000. Max drawdown seeds a $500,000 account at each exit date. "
        "Liquidity gate is close ≥ $5 and 20-day average volume ≥ 500,000.",
        "",
        "Ann ROR = `((1 + total dollar PnL / (45000 × n)) ** (365 / average days held) − 1) × 100`.",
        "",
        "Entry arms resimulate, because a skipped signal leaves the symbol flat and a later daily turn can be taken. "
        "Exit arms replay the control entries and only change the exit. They do not add a later signal the control "
        "was still holding through. Nothing is stacked.",
        "",
        "Code: `tools/shannon_mtf_weekly_support_fulluniv_ab_20260930.py` calls "
        "`tools/shannon_mtf_lines_post_ab_20260930.py` `simulate_entries`, `walk_exit`, and "
        "`weekly_support_under_close`. It does not add a second definition of those exits.",
        "",
        "## Right tail (description only)",
        "",
        info["winner_text"],
        "",
        f"Target cells on the control: {info['with_target']} of {info['n']} entries have a line target. "
        f"{info['without']} do not.",
        "",
        "## Universe context",
        "",
        f"Warehouse files {info['n_files']}. Simulated (at least {sh.MIN_DAILY_BARS} daily bars) "
        f"{info['ok_symbols']}. Short {info['short']}. Missing {info['missing']}. Errors {info['errors']}. "
        f"Symbols with a control trade: {info['traded']}.",
        "",
        "PaulTwenty row is the published weekly arm on `drive/universes/PaulTwenty_universe.csv` "
        "(506 trades, 39.9% wins, 1.49% average, Ann ROR 25.1% on the full slice). It is a reference row.",
        "",
        "## Arms",
        "",
    ]
    for arm in DISPLAY:
        v, why = verdicts[arm.key]
        lines.append(f"### {arm.label}")
        lines.append("")
        lines.append(f"- Kind: {arm.kind}")
        lines.append(f"- How chosen: {arm.bias}")
        lines.append(f"- Rule: {arm.rule}")
        lines.append(f"- Verdict: **{v}**. {why}")
        lines.append("")
        for sl in ("full", "IS", "OOS"):
            st = stats[arm.key][sl]
            lines.append(
                f"- {sl}: N={st['n']} WR={st['wr']:.1f}% avg={st['avg']:.2f}% "
                f"median={st['median']:.2f}% PF={st['pf']:.2f} Ann ROR={st['ann_ror']:.1f}% "
                f"Max DD={st['max_dd']:.1f}% avg days={st['avg_days']:.1f} trades/year={st['tpy']:.1f}"
            )
        lines.append("")
    lines.append("## Selection and OOS")
    lines.append("")
    lines.append(
        "`Only entries with no target` is in-sample selection. It was specified because the PaulTwenty "
        "right tail had blank targets. It cannot be KEEP on that basis. Out-of-sample did not choose a winner "
        "and was not used to retune. If out-of-sample average and annualized rate of return both soften, the verdict is HOLD."
    )
    lines.append("")
    lines.append(
        "FIT, Paul Score, industry shares, and days underwater are not produced by this book. "
        "There is no daily equity curve, so Sharpe is exit-date equity with no risk-free rate, annualized by "
        "how often exits occur. Share of net dollar PnL is blank when the slice's net dollar PnL is not positive. "
        "Total PnL $ and Sheet PnL $ are left off the HTML tables."
    )
    lines.append("")
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_html(info: dict, control: list[dict], stats: dict, verdicts: dict, match_text: str) -> None:
    big = [t for t in control if float(t["pnl"]) >= BIG_WIN]
    big.sort(key=lambda t: -float(t["pnl"]))
    desc = info["winner_text"]

    def ths(pairs):
        return "".join(post.sortable_th(a, b) for a, b in pairs)

    winner_head = ths([
        ("Symbol", "text"),
        ("Opened", "date"),
        ("Closed", "date"),
        ("Return %", "num"),
        ("Hold days", "num"),
        ("Line target", "text"),
        ("Exit", "text"),
        ("Sample", "text"),
    ])
    wrows = []
    for t in big:
        sample = "OOS" if t["opened"] >= IS_CUT else "IS"
        vals = [
            t["sym"],
            _iso(t["opened"]),
            _iso(t["closed"]),
            f"{float(t['pnl']):.2f}",
            f"{float(t['days']):.0f}",
            "yes" if t["had_target"] else "no",
            t["exit"],
            sample,
        ]
        wrows.append("<tr>" + "".join(f"<td>{html_mod.escape(v)}</td>" for v in vals) + "</tr>")
    med_hold = post.quantile([float(t["days"]) for t in big], 0.5) if big else float("nan")
    avg_big = sum(float(t["pnl"]) for t in big) / len(big) if big else float("nan")
    wrows.append(
        '<tr class="total-row">'
        + f"<td>Right tail, return at least {BIG_WIN:.0f}%</td>"
        + f"<td>{len(big)}</td><td></td>"
        + f"<td>{avg_big:.2f}</td><td>{med_hold:.0f}</td>"
        + f"<td>{sum(1 for t in big if t['had_target'])} with a target</td>"
        + "<td>see rows</td><td></td></tr>"
    )

    vhead = ths([
        ("Arm", "text"), ("Kind", "text"), ("How chosen", "text"), ("Slice", "text"),
        ("N", "num"), ("Win %", "num"), ("Avg %", "num"), ("Ann ROR %", "num"),
        ("IS N", "num"), ("IS Win %", "num"), ("IS Avg %", "num"), ("IS Ann ROR %", "num"),
        ("OOS N", "num"), ("OOS Avg %", "num"), ("OOS Ann ROR %", "num"),
        ("Verdict", "text"), ("Why", "text"),
    ])
    vrows = []
    for arm in DISPLAY:
        v, why = verdicts[arm.key]
        full = stats[arm.key]["full"]
        ins = stats[arm.key]["IS"]
        oos = stats[arm.key]["OOS"]
        vals = [
            arm.label, arm.kind, arm.bias, "full / IS / OOS",
            str(full["n"]), post.fmt_pct(full["wr"], 1), post.fmt_pct(full["avg"], 2), post.fmt_pct(full["ann_ror"], 1),
            str(ins["n"]), post.fmt_pct(ins["wr"], 1), post.fmt_pct(ins["avg"], 2), post.fmt_pct(ins["ann_ror"], 1),
            str(oos["n"]), post.fmt_pct(oos["avg"], 2), post.fmt_pct(oos["ann_ror"], 1),
            v, why,
        ]
        vrows.append("<tr>" + "".join(f"<td>{html_mod.escape(x)}</td>" for x in vals) + "</tr>")

    head_pairs = [("Arm", "text"), ("Kind", "text"), ("How chosen", "text"), ("Slice", "text")]
    head_pairs += [(a, "num") for a, _k, _kind in METRIC_COLS]
    head_pairs += [(a, "num" if not a.startswith("Δ Expectancy") else "num") for a, _k, _kind in DELTA_COLS]
    head_pairs.append(("Exit mix", "text"))
    mhead = ths(head_pairs)
    mrows = []
    for sl, sl_label in (("full", "Full"), ("IS", "IS"), ("OOS", "OOS")):
        for arm in DISPLAY:
            st = stats[arm.key][sl]
            base = stats[CONTROL.key][sl]
            cells = [arm.label, arm.kind, arm.bias, sl_label]
            cells += [fmt_cell(st, key, kind) for _lab, key, kind in METRIC_COLS]
            cells += [
                delta_cell(st, base, key, kind, arm.key == CONTROL.key)
                for _lab, key, kind in DELTA_COLS
            ]
            cells.append(post.exit_mix_text(st.get("exits") or {}, int(st.get("n") or 0)))
            mrows.append("<tr>" + "".join(f"<td>{html_mod.escape(c)}</td>" for c in cells) + "</tr>")

    count_head = ths([("Group", "text"), ("Entries", "num"), ("Share", "num"), ("How they exited", "text")])
    n = info["n"]
    count_rows = (
        "<tr>"
        + f"<td>Line target written</td><td>{info['with_target']}</td>"
        + f"<td>{100.0 * info['with_target'] / n:.1f}%</td><td>{html_mod.escape(info['with_exits'])}</td></tr>"
        + "<tr>"
        + f"<td>Target cell blank</td><td>{info['without']}</td>"
        + f"<td>{100.0 * info['without'] / n:.1f}%</td><td>{html_mod.escape(info['without_exits'])}</td></tr>"
        + '<tr class="total-row">'
        + f"<td>All control entries</td><td>{n}</td><td>100%</td><td></td></tr>"
    )

    bullets = "".join(
        f"<li><b>{html_mod.escape(a.label)}</b> ({html_mod.escape(a.kind)}, {html_mod.escape(a.bias)}). "
        f"{html_mod.escape(a.rule)}</li>"
        for a in DISPLAY
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Shannon weekly support full-universe A/B — shannon_mtf_weekly_support_fulluniv_ab_20260930</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 1.25rem auto; max-width: 1280px;
  padding: 0 1rem 2rem; color: #1f1d1a; background: #f7f4ee; }}
h1 {{ font-size: 1.5rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.2rem; margin-top: 1.4rem; }}
.sub {{ color: #5c564c; font-size: 0.92rem; }}
.callout {{ background: #fff; border: 1px solid #d9d1c3; padding: 0.8rem 1rem; margin: 0.8rem 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.78rem; margin: 0.4rem 0 1.2rem; }}
th, td {{ border: 1px solid #e3dccf; padding: 0.28rem 0.4rem; text-align: left; vertical-align: top; }}
.wrap {{ overflow-x: auto; }}
{post.SORT_CSS}
code {{ font-size: 0.86em; }}
</style>
</head>
<body>
<h1>Shannon weekly support — one extra rule at a time, on the full universe</h1>
<p class="sub">Stamp <code>shannon_mtf_weekly_support_fulluniv_ab_20260930</code> ·
prior Shannon folders left untouched · research only · not gold · not DailyRun ·
Click a column header to sort. Footer rows stay pinned.</p>

<div class="callout">
<h2>What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>We already ran the weekly rising support rule on every stock. This page starts from that book and tries one extra rule at a time, things like a time limit or a profit target, to see if the full-universe results get better. It also sets those numbers next to the same weekly rule on the 20-name Paul list.</p>
<p>Multi-Timeframe (MTF) means the month, the week, and the day. Annualized rate of return (Ann ROR) is the house figure from the earlier Shannon page: take the average result per trade, turn it into a yearly pace using how many days the trades were held, with a $45,000 sheet per trade and 365 days in the year. The same formula is on the control and on every test, for the full book, for in-sample (IS, entry before 2024-01-01), and for out-of-sample (OOS, entry on or after that date). OOS is a report. It did not pick a winner, and nothing here was retuned to make OOS look better.</p>
<p>The rerun of the control matched the published 14,582-trade weekly book, trade for trade. Research only.</p>
</div>

<h2>The really big winners</h2>
<p class="sub">Right tail on the full-universe weekly control: closed return at least {BIG_WIN:.0f}%. Description only.
A filter is not adopted because it would have kept these names. Click column headers to sort.</p>
<p>{html_mod.escape(desc)}</p>
<div class="wrap">
<table class="sortable"><thead><tr>{winner_head}</tr></thead><tbody>
{''.join(wrows)}
</tbody></table>
</div>

<h2>What was tested</h2>
<p class="sub">One knob versus the full-universe weekly control. The weekly support rule itself is the control.
Entry tests can take a later signal the control never saw, because a skipped buy leaves the name flat.
Exit tests keep the control’s entries and only change the way out. No combination arm.</p>
<ul>
{bullets}
</ul>

<h2>Verdicts</h2>
<p class="sub">Judged on in-sample quality versus the full-universe weekly control: average percent, profit factor,
annualized rate of return, drawdown, and the average with the single largest trade left out.
Out-of-sample is not the judge. If it softened, the verdict is HOLD.
The PaulTwenty row is a reference so the universe gap stays visible.
Click column headers to sort.</p>
<div class="wrap">
<table class="sortable"><thead><tr>{vhead}</tr></thead><tbody>
{''.join(vrows)}
</tbody></table>
</div>

<h2>Target count on the control</h2>
<p class="sub">Click column headers to sort. The total row stays at the bottom.</p>
<div class="wrap">
<table class="sortable"><thead><tr>{count_head}</tr></thead><tbody>
{count_rows}
</tbody></table>
</div>

<h2>Compare</h2>
<p class="sub">Deltas are versus the full-universe weekly control on the same slice. Δ Max DD is positive when the
drawdown is deeper (worse). Expectancy dollars are the average percent times the $45,000 sheet.
Total profit dollars and sheet-profit totals are left off this table. FIT (the house fitness score) is not
produced by this book. Trades/year uses the span from the first entry to the last exit in that slice.
Judgement is not based on the single best trade. Click column headers to sort. Scroll sideways for the rest of the columns.</p>
<div class="wrap">
<table class="sortable"><thead><tr>{mhead}</tr></thead><tbody>
{''.join(mrows)}
</tbody></table>
</div>

<p class="sub">Ann ROR formula, same as the Shannon report and <code>compare_format.ann_ror_from_closed</code>:
((1 + total dollar PnL / (45000 × number of trades)) ^ (365 / average days held) − 1) × 100.
Max drawdown replays those same closed dollars onto a $500,000 account at each exit date.
Sharpe is that exit-date equity with no risk-free rate, annualized by how often exits occur.
There is no daily equity curve for this book. In-sample is entry before 2024-01-01. Out-of-sample is entry on or after that date.</p>
{post.SORT_JS}
</body>
</html>
"""
    (OUT_DIR / "compare.html").write_text(page, encoding="utf-8")


def write_stop(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Shannon weekly support A/B stopped</title>
<style>body {{ font-family: Georgia, serif; margin: 1.5rem auto; max-width: 800px; color: #1f1d1a; }}</style>
</head><body>
<div>
<h2>What you asked</h2>
<p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
<h2>In plain English</h2>
<p>We already ran the weekly rising support rule on every stock. This page was going to start from that book and try one extra rule at a time. The rerun of that book did not match the published counts, so the extra rules were not scored.</p>
</div>
<h2>Control did not match</h2>
<pre>{html_mod.escape(message)}</pre>
<p>Arms were not scored. Research only.</p>
</body></html>
"""
    (OUT_DIR / "compare.html").write_text(page, encoding="utf-8")
    (OUT_DIR / "BASELINE.md").write_text(
        "# shannon_mtf_weekly_support_fulluniv_ab_20260930\n\n"
        "## What you asked\n\n"
        f"{ORIGINAL_REQUEST}\n\n"
        "## In plain English\n\n"
        "We already ran the weekly rising support rule on every stock. The rerun did not match the "
        "published book, so the extra rules were not scored.\n\n"
        "## Stop\n\n"
        f"{message}\n",
        encoding="utf-8",
    )


def main() -> None:
    workers = max(1, min(8, os.cpu_count() or 4))
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--workers":
        workers = max(1, int(args[1]))
    frozen = load_prior("weekly_support", "full")
    paul = load_prior("weekly_support", "PaulTwenty")
    frozen_pack = uni.pack(frozen)
    print(
        f"Published weekly book N={frozen_pack['n']} WR={frozen_pack['wr']:.1f} "
        f"avg={frozen_pack['avg']:.2f} Ann={frozen_pack['ann_ror']:.1f} DD={frozen_pack['max_dd']:.1f}",
        flush=True,
    )
    if frozen_pack["n"] != PUBLISHED_N:
        raise SystemExit(f"Published CSV weekly book N={frozen_pack['n']} != {PUBLISHED_N}")
    symbols = uni.warehouse_symbols()
    print(f"Warehouse files {len(symbols)} workers={workers}", flush=True)
    books: dict[str, list[dict]] = {a.key: [] for a in TESTED}
    status: dict[str, str] = {}
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for sym, st, got, exits in ex.map(run_symbol, symbols, chunksize=4):
            status[sym] = st
            if st == "ok":
                for key, rows in got.items():
                    books[key].extend(rows)
                for key, rows in exits.items():
                    books[key].extend(rows)
            done += 1
            if done % 100 == 0 or done == len(symbols):
                print(f"warehouse {done}/{len(symbols)} control {len(books[CONTROL.key])}", flush=True)
    for key in books:
        books[key].sort(key=lambda t: (t["opened"], t["sym"], t["signal"]))
    ok, message = match_control(books[CONTROL.key], frozen)
    print(message, flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not ok:
        write_stop(message)
        print(f"STOP wrote {OUT_DIR / 'compare.html'}", flush=True)
        raise SystemExit(2)

    for arm in EXIT_ARMS:
        cset = [(t["sym"], _iso(t["opened"]), _iso(t["signal"])) for t in books[CONTROL.key]]
        aset = [(t["sym"], _iso(t["opened"]), _iso(t["signal"])) for t in books[arm.key]]
        if cset != aset:
            write_stop(f"Exit arm {arm.key} changed the entry list. Arms were not scored.")
            raise SystemExit(3)

    books[PAUL_REF.key] = paul
    stats = {arm.key: slice_stats(books[arm.key]) for arm in DISPLAY}
    verdicts = {arm.key: arm_verdict(arm, stats) for arm in DISPLAY}
    for arm in DISPLAY:
        v, why = verdicts[arm.key]
        ins = stats[arm.key]["IS"]
        full = stats[arm.key]["full"]
        print(
            f"{arm.key}: {v} | full N={full['n']} WR={full['wr']:.1f} avg={full['avg']:.2f} "
            f"Ann={full['ann_ror']:.1f} | IS N={ins['n']} WR={ins['wr']:.1f} avg={ins['avg']:.2f} "
            f"Ann={ins['ann_ror']:.1f} | {why}",
            flush=True,
        )
    control = books[CONTROL.key]
    big = [t for t in control if float(t["pnl"]) >= BIG_WIN]
    with_t = [t for t in control if t["had_target"]]
    without = [t for t in control if not t["had_target"]]
    counts = uni.status_counts(status)
    info = {
        "winner_text": describe_winners(big, control),
        "n": len(control),
        "with_target": len(with_t),
        "without": len(without),
        "with_exits": post.exit_mix_text(Counter(t["exit"] for t in with_t), len(with_t)),
        "without_exits": post.exit_mix_text(Counter(t["exit"] for t in without), len(without)),
        "n_files": len(symbols),
        "ok_symbols": counts.get("ok", 0),
        "short": counts.get("short", 0),
        "missing": counts.get("missing", 0),
        "errors": counts.get("error", 0),
        "traded": len({t["sym"] for t in control}),
    }
    print(info["winner_text"], flush=True)
    write_trades(books)
    write_summary(stats, verdicts)
    write_baseline(info, verdicts, stats, message)
    write_html(info, control, stats, verdicts, message)
    print(f"WROTE {OUT_DIR / 'compare.html'}", flush=True)


if __name__ == "__main__":
    main()
