#!/usr/bin/env python3
"""Compare live books to high-water-trail reruns that can take the next signal.

Research only. Reads drive/*_LatestRun_Closed.csv as the control and the
stamp run folders as the research arm. Does not retune.
"""
from __future__ import annotations

import csv
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))
sys.path.insert(0, str(REPO))

import compare_format as cf  # noqa: E402
import report_page_extras as rpe  # noqa: E402

STAMP = REPO / "drive" / "paul_experiments" / "hwm_stop_rerun_signals_20261015"
RUNS = STAMP / "runs"
DRIVE = REPO / "drive"
IS_CUT = datetime(2024, 1, 1)

QUOTE = (
    "can you add these variables to each system? i don't want them moved to dailyrun, "
    "or gold, but i want to be able to run them through each system for real. when we do so, "
    "i expect we will have more signals than we have if we are holding stocks for longer periods "
    "of time (the current control) so i want to run these variables through ( the new trailing stops "
    "and accompanying stop losses) and compare each to the standard gold system."
)

# Rocket Launcher closed rows are percent-only. Live slot is rl_cash.
KNOWN_SLOT = {"RL": 47_500.0}

SYSTEMS = [
    {
        "key": "BRT",
        "name": "Break and ReTest (BRT)",
        "gold": True,
        "knob": "Base stop 13.6% under the trigger-day low (low × 0.864). Trail on after a 6% gain, keep 70%. Live control is trigger low × 0.934 and no trail.",
    },
    {
        "key": "RL",
        "name": "Rocket Launcher (RL)",
        "gold": True,
        "knob": "Base stop 0.65% under the signal-day low (low × 0.9935). Trail on after a 6% gain, keep 80%. The live 80%-at-+20% / leftover-stop-at-entry / leftover-+40% ladder stays on the control only.",
    },
    {
        "key": "YH",
        "name": "Year High (YH)",
        "gold": True,
        "knob": "Base stop 0.95% under the trigger-day low (low × 0.9905). Trail on after a 2% gain, keep 70%. Live control is trigger low × 0.934 and no trail.",
    },
    {
        "key": "MTS",
        "name": "Magic Touch (MTS)",
        "gold": True,
        "knob": "Base stop 2.56% under the trigger-day low (low × 0.9744). Trail on after a 4% gain, keep 60%. Live control is trigger low × 0.934 and no trail.",
    },
    {
        "key": "WPBR",
        "name": "Weekly Pivot Break and Retest (WPBR)",
        "gold": True,
        "knob": "Base stop 3.03% under the trigger-day low (low × 0.9697). Trail on after a 2% gain, keep 80%. Live control is trigger low × 0.92 and no trail.",
    },
    {
        "key": "RS",
        "name": "Relative Strength vs SPY (RS)",
        "gold": True,
        "knob": "Live base stays entry × 0.85. Trail on after a 10% gain, keep 80%. The 252-bar time stop and the live target stay unless the trail or the base stop hits first.",
    },
    {
        "key": "RSI",
        "name": "Relative Strength Index (RSI)",
        "gold": False,
        "knob": "No new price base. Trail on after a 6% gain, keep 80%. The 8-point drop from the in-trade RSI high, RSI back at 70, and the 20-calendar-day stop still apply if the trail has not sold. RSI is wired in DailyRun and is not walk-forward gold.",
    },
]


def _pick(row: dict, *names: str):
    lookup = {k.strip().upper().replace(" ", "_"): v for k, v in row.items()}
    for n in names:
        key = n.upper().replace(" ", "_")
        if key in lookup and str(lookup[key]).strip() != "":
            return lookup[key]
    return ""


def _parse_date(raw) -> datetime | None:
    s = str(raw or "").strip().replace("-", "").replace("/", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def load_closed(path: Path, cash_if_no_dollars: float | None = None) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for row in rows:
        opened = _parse_date(_pick(row, "DATE_OPENED", "DATE OPENED", "ENTRY_DATE"))
        closed = _parse_date(_pick(row, "DATE_CLOSED", "DATE CLOSED", "EXIT_DATE"))
        pct = cf.parse_number(_pick(row, "PNL_PCT", "PNL %", "PNL_PERCENT"))
        dol = cf.parse_number(_pick(row, "PNL_DOLLARS"))
        days = cf.parse_number(_pick(row, "DAYS_HELD", "DAYS HELD"))
        if opened is None or pct is None:
            continue
        pnl_d = float(dol) if dol is not None else None
        if pnl_d is None and cash_if_no_dollars:
            pnl_d = float(pct) / 100.0 * float(cash_if_no_dollars)
        out.append(
            {
                "symbol": str(_pick(row, "SYMBOL") or "").upper(),
                "opened": opened,
                "closed": closed,
                "pnl": float(pct),
                "pnl_d": pnl_d,
                "days": float(days) if days is not None else None,
                "exit": str(_pick(row, "EXIT_TYPE", "EXIT TYPE") or ""),
            }
        )
    return out


def newest_closed(folder: Path, prefix: str) -> Path | None:
    hits = sorted(folder.glob(f"{prefix}_Closed_*.csv"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def slot_cash(trades: list[dict], report_cash: float | None) -> tuple[float | None, str]:
    notions = []
    for t in trades:
        if t["pnl_d"] is None or abs(t["pnl"]) < 0.05:
            continue
        notions.append(abs(t["pnl_d"] / (t["pnl"] / 100.0)))
    med = statistics.median(notions) if notions else None
    if med and report_cash and med > 0 and abs(report_cash - med) / med <= 0.25:
        return float(report_cash), "Report capacity is within 25% of the Closed median implied notional"
    if med:
        return float(med), "Closed median implied notional (trade dollars ÷ return)"
    if report_cash:
        return float(report_cash), "Report capacity (no usable Closed notionals)"
    return None, "slot cash missing"


def report_cash(folder: Path, prefix: str) -> float | None:
    hits = sorted(folder.glob(f"{prefix}_Report_*.csv"), key=lambda p: p.stat().st_mtime)
    path = hits[-1] if hits else (folder / f"{prefix}_LatestRun_Report.csv")
    if not path.is_file():
        # Control reports often sit beside LatestRun_Closed.
        alt = DRIVE / f"{prefix}_LatestRun_Report.csv"
        path = alt if alt.is_file() else path
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    row = rows[0]
    for k, v in row.items():
        if k and k.strip().lower() in ("brt_cash", "cash", "slot_cash"):
            num = cf.parse_number(v)
            if num and num > 0:
                return float(num)
    return None


def _pctile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return s[i]


def book_metrics(trades: list[dict], cash: float | None) -> dict:
    n = len(trades)
    pcts = [t["pnl"] for t in trades]
    wins = [x for x in pcts if x > 0]
    losses = [x for x in pcts if x <= 0]
    days = [t["days"] for t in trades if t["days"] is not None and t["days"] > 0]
    dols = [t["pnl_d"] for t in trades if t["pnl_d"] is not None]
    avg = statistics.fmean(pcts) if pcts else None
    wo = None
    if len(pcts) >= 2:
        drop = max(pcts)
        rest = [x for x in pcts if x != drop]
        # drop one max only
        rest = pcts.copy()
        rest.remove(drop)
        wo = statistics.fmean(rest) if rest else None
    sum_win_d = sum(x for x in dols if x > 0)
    sum_loss_d = abs(sum(x for x in dols if x < 0))
    pf = (sum_win_d / sum_loss_d) if sum_loss_d > 0 else None
    exp_d = statistics.fmean(dols) if dols else None
    exp_pct = avg
    avg_days = statistics.fmean(days) if days else None
    total_d = sum(dols) if dols else None
    ann = None
    if cash and total_d is not None and avg_days and n:
        ann = cf.ann_ror_from_closed(
            total_pnl=total_d, n_trades=n, avg_days_held=avg_days, brt_cash=cash
        )
    overlay = {}
    if cash:
        overlay = cf.overlay_ann_ror_max_dd(
            trades,
            cash=cash,
            initial_account=500_000.0,
        )
    streak = 0
    worst = 0
    for x in pcts:
        if x <= 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    by_sym: dict[str, float] = {}
    for t in trades:
        if t["pnl_d"] is None:
            continue
        by_sym[t["symbol"]] = by_sym.get(t["symbol"], 0.0) + t["pnl_d"]
    sym_vals = sorted(by_sym.values(), reverse=True)
    gross = sum(x for x in sym_vals if x > 0)
    max_sym = (sym_vals[0] / gross * 100.0) if gross and sym_vals else None
    top10 = (sum(sym_vals[:10]) / gross * 100.0) if gross else None
    bot = sorted(by_sym.values())
    bot10 = (sum(bot[:10]) / sum(dols) * 100.0) if dols and sum(dols) else None
    max_trade = None
    if dols and sum(x for x in dols if x > 0):
        max_trade = max(dols) / sum(x for x in dols if x > 0) * 100.0
    exits: dict[str, int] = {}
    for t in trades:
        exits[t["exit"] or "(blank)"] = exits.get(t["exit"] or "(blank)", 0) + 1
    cap_days = sum(days) if days else None
    return {
        "N": n,
        "Wins": len(wins),
        "Losses": len(losses),
        "Win %": (100.0 * len(wins) / n) if n else None,
        "Avg PnL %": avg,
        "Book AVG_PNL_PCT_WO_MAX": wo,
        "Expectancy $": exp_d,
        "Expectancy %": exp_pct,
        "Avg win %": statistics.fmean(wins) if wins else None,
        "Avg loss %": statistics.fmean(losses) if losses else None,
        "Win/Loss ratio (count)": (len(wins) / len(losses)) if losses else None,
        "Win/Loss ratio $": (sum_win_d / sum_loss_d) if sum_loss_d else None,
        "Profit factor": pf,
        "Ann ROR %": ann if ann is not None else overlay.get("ann_ror"),
        "Max DD %": overlay.get("max_dd"),
        "Calmar": overlay.get("calmar"),
        "Sharpe": overlay.get("sharpe"),
        "Profit per capital day": (total_d / cap_days) if total_d is not None and cap_days else None,
        "Capital days": cap_days,
        "Avg days held": avg_days,
        "Median days held": statistics.median(days) if days else None,
        "P90 days held": _pctile(days, 0.90),
        "Losing streak": worst if n else None,
        "Pct PnL max symbol": max_sym,
        "Pct PnL max trade": max_trade,
        "Pct PnL top10": top10,
        "Pct PnL bottom10": bot10,
        "Total PnL $": total_d,
        "_exits": exits,
        "_note": overlay.get("note") or "",
    }


NUM_KEYS = {
    "N",
    "Wins",
    "Losses",
    "Win %",
    "Avg PnL %",
    "Book AVG_PNL_PCT_WO_MAX",
    "Expectancy $",
    "Expectancy %",
    "Avg win %",
    "Avg loss %",
    "Win/Loss ratio (count)",
    "Win/Loss ratio $",
    "Profit factor",
    "Ann ROR %",
    "Max DD %",
    "Calmar",
    "Sharpe",
    "Profit per capital day",
    "Capital days",
    "Avg days held",
    "Median days held",
    "P90 days held",
    "Losing streak",
    "Pct PnL max symbol",
    "Pct PnL max trade",
    "Pct PnL top10",
    "Pct PnL bottom10",
}

SHOW = [
    "N",
    "Wins",
    "Losses",
    "Win %",
    "Avg PnL %",
    "Book AVG_PNL_PCT_WO_MAX",
    "Expectancy $",
    "Expectancy %",
    "Avg win %",
    "Avg loss %",
    "Win/Loss ratio (count)",
    "Win/Loss ratio $",
    "Profit factor",
    "Ann ROR %",
    "Max DD %",
    "Calmar",
    "Sharpe",
    "Profit per capital day",
    "Capital days",
    "Avg days held",
    "Median days held",
    "P90 days held",
    "Losing streak",
    "Pct PnL max symbol",
    "Pct PnL max trade",
    "Pct PnL top10",
    "Pct PnL bottom10",
]


def fmt(key: str, val) -> str:
    if val is None or (isinstance(val, float) and not math.isfinite(val)):
        return "—"
    if key in ("Expectancy $", "Profit per capital day"):
        return cf.format_money(val)
    if key in ("N", "Wins", "Losses", "Losing streak"):
        return f"{int(round(val)):,}"
    if key == "Capital days":
        return f"{val:,.0f}"
    return f"{val:,.2f}"


def delta(key: str, a, b) -> str:
    if a is None or b is None:
        return "—"
    if isinstance(a, float) and (not math.isfinite(a) or not math.isfinite(b)):
        return "—"
    d = b - a
    if key in ("Expectancy $", "Profit per capital day"):
        return cf.format_money_delta(d)
    if key in ("N", "Wins", "Losses", "Losing streak", "Capital days"):
        return f"{d:+,.0f}"
    return f"{d:+,.2f}"


def slice_of(trades: list[dict], which: str) -> list[dict]:
    if which == "full":
        return trades
    if which == "is":
        return [t for t in trades if t["opened"] < IS_CUT]
    return [t for t in trades if t["opened"] >= IS_CUT]


def th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{label}<span class="sort-ind"></span></th>'
    )


def system_table(control: dict, research: dict) -> str:
    slices = ("full", "is", "oos")
    heads = "".join(
        th(f"{arm} {sl}", "num")
        for sl in ("full", "IS", "OOS")
        for arm in ("Control", "Research", "Δ")
    )
    body = []
    for key in SHOW:
        cells = []
        for sl in slices:
            a = control[sl].get(key)
            b = research[sl].get(key)
            cells.append(f"<td>{fmt(key, a)}</td><td>{fmt(key, b)}</td><td>{delta(key, a, b)}</td>")
        body.append(f"<tr><td>{key}</td>{''.join(cells)}</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th("Metric", "text")
        + heads
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def exit_line(m: dict) -> str:
    exits = m.get("_exits") or {}
    n = m.get("N") or 0
    parts = []
    for name, count in sorted(exits.items(), key=lambda kv: -kv[1])[:8]:
        pct = (100.0 * count / n) if n else 0
        parts.append(f"{name} {count} ({pct:.0f}%)")
    return ", ".join(parts) if parts else "—"


def judge(ctrl_is: dict, res_is: dict) -> str:
    a = ctrl_is.get("Avg PnL %")
    b = res_is.get("Avg PnL %")
    na = ctrl_is.get("N") or 0
    nb = res_is.get("N") or 0
    if a is None or b is None:
        return "In-sample average return could not be computed."
    extra = nb - na
    if b < a - 1e-9:
        bit = "The extra signals lowered in-sample average return"
        if extra > 0:
            bit += f" ({extra:+.0f} trades). The added trades diluted the book"
        elif extra < 0:
            bit += f". Research has {extra:.0f} trades versus the control"
        else:
            bit += ". Trade count did not rise"
        wr_a = ctrl_is.get("Win %")
        wr_b = res_is.get("Win %")
        if wr_b is not None and wr_a is not None and wr_b > wr_a:
            bit += " even though the in-sample win rate is higher"
        bit += "."
        return bit
    if b > a + 1e-9:
        if extra > 0:
            return (
                f"The extra signals raised in-sample average return "
                f"({extra:+.0f} trades). The added trades helped the book."
            )
        return "In-sample average return is higher. Trade count did not rise, so this is not an extra-signal lift."
    return "In-sample average return is flat versus the control."


def main() -> int:
    sections = []
    baseline_rows = []
    missing = []
    for spec in SYSTEMS:
        key = spec["key"]
        ctrl_path = DRIVE / f"{key}_LatestRun_Closed.csv"
        res_path = newest_closed(RUNS / key, key)
        if not ctrl_path.is_file() or res_path is None:
            missing.append(f"{key}: control={ctrl_path.is_file()} research={res_path}")
            continue
        known = KNOWN_SLOT.get(key)
        ctrl = load_closed(ctrl_path, known)
        res = load_closed(res_path, known)
        c_cash, c_note = slot_cash(ctrl, known or report_cash(DRIVE, key))
        r_cash, r_note = slot_cash(res, known or report_cash(RUNS / key, key))
        # Same formula on both arms. Use each arm's own slot so Ann ROR matches its dollars.
        c_m = {sl: book_metrics(slice_of(ctrl, sl), c_cash) for sl in ("full", "is", "oos")}
        r_m = {sl: book_metrics(slice_of(res, sl), r_cash) for sl in ("full", "is", "oos")}
        label = "live gold book (what DailyRun runs today)" if spec["gold"] else "live book, not walk-forward gold"
        verdict = judge(c_m["is"], r_m["is"])
        sections.append(
            f"<h2>{spec['name']}</h2>"
            f"<p>Control is the {label}. {spec['knob']}</p>"
            f"<p><strong>In-sample call.</strong> {verdict} "
            f"Full-book N {fmt('N', c_m['full']['N'])} control vs {fmt('N', r_m['full']['N'])} research. "
            f"In-sample average return {fmt('Avg PnL %', c_m['is']['Avg PnL %'])}% control vs "
            f"{fmt('Avg PnL %', r_m['is']['Avg PnL %'])}% research. "
            f"Full-book win rate {fmt('Win %', c_m['full']['Win %'])}% vs {fmt('Win %', r_m['full']['Win %'])}%. "
            f"Full-book annualized rate of return {fmt('Ann ROR %', c_m['full']['Ann ROR %'])}% vs "
            f"{fmt('Ann ROR %', r_m['full']['Ann ROR %'])}%.</p>"
            f"<p>Slot cash control ${c_cash:,.0f} ({c_note}). Research ${r_cash:,.0f} ({r_note}). "
            f"Annualized rate of return uses <code>compare_format.ann_ror_from_closed</code>.</p>"
            f"<p>Control exits: {exit_line(c_m['full'])}. Research exits: {exit_line(r_m['full'])}.</p>"
            + system_table(c_m, r_m)
        )
        baseline_rows.append((spec, c_m, r_m, c_cash, r_cash, verdict, ctrl_path, res_path))

    if missing:
        raise SystemExit("Missing books:\n" + "\n".join(missing))

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>High-water stop rerun — more signals</title>
{rpe.CACHE_META}
<style>
body {{ font-family: Georgia, serif; margin: 1.25rem; color: #1e293b; line-height: 1.45; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0.8rem 0 1.2rem; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ margin-top: 2rem; }}
{rpe.SORTABLE_TH_CSS}
</style>
</head><body>
<h1>High-water trailing stop, rerun so later signals can fire</h1>
<div class="callout">
<h2>What you asked</h2>
<p>{QUOTE}</p>
<h2>In plain English</h2>
<p>Each system was run again with a tighter or restated starting stop and a trailing stop that only wakes up after the stock has risen a set amount. The trail keeps a fraction of the gain from the buy to the highest high so far, and it never sits below the starting stop. Because these exits are often sooner than the current book, a symbol can take another buy after the first trade is sold. The control is the book DailyRun produces today. The research arm is not gold and is not wired into DailyRun. Out-of-sample (entry on or after 2024-01-01) is shown and was not used to change the stops.</p>
<p>Break and ReTest (BRT), Rocket Launcher (RL), Year High (YH), Magic Touch (MTS), Weekly Pivot Break and Retest (WPBR), Relative Strength vs SPY (RS), and Relative Strength Index (RSI). One position per symbol at a time, the same rule the engines already use. No extra portfolio-wide slot limit.</p>
</div>
<p><strong>Selection bias.</strong> These stop percents and trail settings were chosen after earlier tables (activation grid, Paul's picks, and the tighter-base page). That is in-sample selection on this same history. This page does not retune from out-of-sample, and it does not name a winner from out-of-sample. Judge on in-sample average return.</p>
<p>In-sample means entry before 2024-01-01. Out-of-sample means entry on or after 2024-01-01. Annualized rate of return (Ann ROR after this) is the house formula <code>((1 + total PnL / (slot cash × trades)) ** (365 / average days held) − 1) × 100</code>. Max drawdown and Sharpe use the closed-trade replay in <code>compare_format.overlay_ann_ror_max_dd</code> (exit-date equity, $500,000 start). Click column headers to sort. {rpe.SWIPE_NOTE_HTML}</p>
{''.join(sections)}
<p>Research only. Not gold. Not DailyRun. Engine flags <code>hwm_act_pct</code> and <code>hwm_keep</code> default to off, so the normal bats keep today's exits.</p>
{rpe.SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    # SWIPE_NOTE already includes a <p>. Don't nest. I included it inside a <p>. Fix.
    html = html.replace(
        f"Click column headers to sort. {rpe.SWIPE_NOTE_HTML}</p>",
        "Click column headers to sort.</p>\n" + rpe.SWIPE_NOTE_HTML,
    )
    out = STAMP / "compare.html"
    out.write_text(html, encoding="utf-8")

    lines = [
        "# High-water stop rerun — later signals",
        "",
        "## What you asked",
        "",
        f"> {QUOTE}",
        "",
        "## In plain English",
        "",
        "Each system was rerun with the locked starting stop and trailing stop so a symbol can take a new signal after the prior trade exits. The control is today's DailyRun book. Research is not gold and is not DailyRun. Out-of-sample is report-only.",
        "",
        "Selection bias: these settings were chosen after earlier high-water tables on this same history. No retune from out-of-sample.",
        "",
        "In-sample: entry_date < 2024-01-01. Out-of-sample: entry_date >= 2024-01-01.",
        "Annualized rate of return uses compare_format.ann_ror_from_closed.",
        "",
        "| System | Control label | Full N ctrl | Full N res | Full win% ctrl | Full win% res | Full avg% ctrl | Full avg% res | Full Ann ROR ctrl | Full Ann ROR res | IS N ctrl | IS N res | IS win% ctrl | IS win% res | IS avg% ctrl | IS avg% res | IS Ann ROR ctrl | IS Ann ROR res | IS average return |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for spec, c_m, r_m, c_cash, r_cash, verdict, ctrl_path, res_path in baseline_rows:
        label = "live gold" if spec["gold"] else "live, not gold"
        def g(m, sl, k):
            v = m[sl].get(k)
            return "—" if v is None else f"{v:.2f}"
        lines.append(
            f"| {spec['name']} | {label} | {c_m['full']['N']:.0f} | {r_m['full']['N']:.0f} | "
            f"{g(c_m,'full','Win %')} | {g(r_m,'full','Win %')} | {g(c_m,'full','Avg PnL %')} | {g(r_m,'full','Avg PnL %')} | "
            f"{g(c_m,'full','Ann ROR %')} | {g(r_m,'full','Ann ROR %')} | "
            f"{c_m['is']['N']:.0f} | {r_m['is']['N']:.0f} | {g(c_m,'is','Win %')} | {g(r_m,'is','Win %')} | "
            f"{g(c_m,'is','Avg PnL %')} | {g(r_m,'is','Avg PnL %')} | {g(c_m,'is','Ann ROR %')} | {g(r_m,'is','Ann ROR %')} | {verdict} |"
        )
        lines += [
            "",
            f"### {spec['name']}",
            "",
            spec["knob"],
            f"Control file: `{ctrl_path}`. Research file: `{res_path}`.",
            f"Slot cash control {c_cash:.0f}. Research {r_cash:.0f}.",
            verdict,
            "",
        ]
    lines += [
        "## Freeze",
        "",
        "- Not gold. Not DailyRun. `DailyRun.bat` does not call `run_hwm_stop_research.bat`.",
        "- Flags `hwm_act_pct` and `hwm_keep` default to 0 (live behavior) when absent.",
        "- Research env `HWM_ACT_PCT`, `HWM_KEEP`, `HWM_STOP_PCT`, `HWM_RL_STOP_PCT`, `HWM_RL_SCALE_LADDER`, `HWM_RESEARCH_OUT` is set only by the research bat.",
        "- One position per symbol. No new portfolio slot cap.",
        "- Stop on day T uses the high through day T−1. Entry day cannot sell. Open through the stop fills at the open; a low through the stop fills at the stop. The system's price target still applies if neither stop hits.",
        "- Rocket Launcher research turns the scale ladder off. The control ladder is unchanged.",
        "",
    ]
    (STAMP / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
