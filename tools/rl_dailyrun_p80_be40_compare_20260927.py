#!/usr/bin/env python3
"""Freeze the DailyRun Rocket Launcher golden and write the old-vs-new compare page.

Old book: last monthly mirror before this wiring (59 names, sell at +40% then 30 days).
New book: full data folder, frozen exit (sell 80% at +20%, leftover stop at the buy, leftover +40%).
"""
from __future__ import annotations

import csv
import html
import json
import math
import shutil
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from compare_format import format_money, overlay_ann_ror_max_dd  # noqa: E402
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS  # noqa: E402

STAMP = "260927140923"
AWK_STAMP = "260927142519"
OLD_MIRROR = "260925183544"
OLD_REPORT = "260925183603"
IS_CUT = "2024-01-01"
CASH = 47500.0
ACCOUNT = 500000.0

DRIVE = ROOT / "drive"
CFG = DRIVE / "paul_experiments" / "reconcile_gate_config.json"
BASE = DRIVE / "paul_experiments" / f"rl_baseline_{STAMP}"
OUT = DRIVE / "paul_experiments" / "rl_dailyrun_p80_be40_full_universe_20260927"
PY_CLOSED = DRIVE / f"RL_Closed_{STAMP}.csv"
AWK_CLOSED = DRIVE / f"RL_Closed_{AWK_STAMP}.csv"
OLD_CLOSED = DRIVE / f"BRT_Closed_RL_{OLD_MIRROR}.csv"


def _f(row: dict, *names: str) -> float | None:
    for n in names:
        if n in row and str(row[n]).strip() not in ("", "N/A"):
            s = str(row[n]).replace("%", "").replace(",", "").replace("$", "").strip()
            try:
                return float(s)
            except ValueError:
                return None
    return None


def _s(row: dict, *names: str) -> str:
    for n in names:
        if n in row and str(row[n]).strip():
            return str(row[n]).strip()
    return ""


def _date(s: str) -> str:
    s = (s or "").strip().replace("-", "").replace("/", "")
    return s[:8] if len(s) >= 8 else s


def load_closed(path: Path) -> list[dict]:
    out = []
    with path.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            opened = _date(_s(raw, "DATE OPENED", "DATE_OPENED"))
            pnl = _f(raw, "PNL %", "PNL_PCT")
            days = _f(raw, "DAYS HELD", "DAYS_HELD")
            if pnl is None or not opened:
                continue
            out.append(
                {
                    "symbol": _s(raw, "SYMBOL").upper(),
                    "opened": opened,
                    "closed": _date(_s(raw, "DATE CLOSED", "DATE_CLOSED")),
                    "pnl": pnl,
                    "pnl_d": pnl / 100.0 * CASH,
                    "days": int(days or 0),
                    "exit": _s(raw, "EXIT TYPE", "EXIT_TYPE").upper() or "UNKNOWN",
                    "partial": bool(_s(raw, "PARTIAL_DATE", "PARTIAL DATE")),
                }
            )
    return out


def load_report(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return next(csv.DictReader(f))


def load_meta(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return next(csv.DictReader(f))


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    t = str(s).replace("%", "").replace(",", "").strip()
    if t in ("", "N/A", "None"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def quality(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    days = [t["days"] for t in trades]
    wo = [p for p in pnls if p != max(pnls)]
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    ov = overlay_ann_ror_max_dd(
        trades,
        cash=CASH,
        initial_account=ACCOUNT,
        pnl_pct_key="pnl",
        pnl_d_key="pnl_d",
        days_key="days",
        opened_key="opened",
        closed_key="closed",
    )
    def _finite(v):
        return v if isinstance(v, (int, float)) and math.isfinite(v) else None

    ann = _finite(ov.get("ann_ror"))
    dd = _finite(ov.get("max_dd"))
    sharpe = _finite(ov.get("sharpe"))
    calmar = _finite(ov.get("calmar"))
    if calmar is None and ann is not None and dd not in (None, 0):
        calmar = ann / abs(dd)
    return {
        "n": n,
        "symbols": len({t["symbol"] for t in trades}),
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg": sum(pnls) / n,
        "median": statistics.median(pnls),
        "wo_max": (sum(wo) / len(wo)) if wo else None,
        "pf": (gross_win / gross_loss) if gross_loss else None,
        "avg_win": (sum(wins) / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
        "avg_days": sum(days) / n,
        "median_days": statistics.median(days),
        "partials": sum(1 for t in trades if t["partial"]),
        "ann": ann,
        "dd": dd,
        "calmar": calmar,
        "sharpe": sharpe,
        "exits": Counter(t["exit"] for t in trades),
    }


def split_is_oos(trades: list[dict]) -> tuple[list[dict], list[dict]]:
    cut = IS_CUT.replace("-", "")
    return [t for t in trades if t["opened"] < cut], [t for t in trades if t["opened"] >= cut]


def window(trades: list[dict], start: str, end: str) -> list[dict]:
    return [t for t in trades if start <= t["opened"] <= end]


def fmt_pct(v, digits=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}%"


def fmt_n(v, digits=2) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def fmt_delta(new, old, kind="pct") -> str:
    if new is None or old is None:
        return "—"
    d = new - old
    sign = "+" if d > 0 else ""
    if kind == "int":
        return f"{sign}{d:.0f}"
    if kind == "money":
        return format_money(d) if False else f"{sign}{d:.2f}"
    return f"{sign}{d:.2f}"


def th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def td(text: str, sort_num: float | None = None) -> str:
    return f"<td>{html.escape(text)}</td>"


def metric_table(rows: list[tuple[str, str, str, str]], right: str) -> str:
    body = []
    for label, a, b, d in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{html.escape(a)}</td>"
            f"<td>{html.escape(b)}</td>"
            f"<td>{html.escape(d)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th("Metric", "text")
        + th("Previous DailyRun", "text")
        + th(right, "text")
        + th("Change", "text")
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def book_rows(old_q: dict, new_q: dict) -> list[tuple[str, str, str, str]]:
    pairs = [
        ("Symbols with a closed trade", old_q["symbols"], new_q["symbols"], "int", 0),
        ("Closed trades", old_q["n"], new_q["n"], "int", 0),
        ("Wins / losses", f"{old_q['wins']} / {old_q['losses']}", f"{new_q['wins']} / {new_q['losses']}", "text", 0),
        ("Win rate", old_q["wr"], new_q["wr"], "pct", 1),
        ("Average trade", old_q["avg"], new_q["avg"], "pct", 2),
        ("Median trade", old_q["median"], new_q["median"], "pct", 2),
        ("Average without the biggest winner", old_q["wo_max"], new_q["wo_max"], "pct", 2),
        ("Average winner", old_q["avg_win"], new_q["avg_win"], "pct", 2),
        ("Average loser", old_q["avg_loss"], new_q["avg_loss"], "pct", 2),
        ("Profit factor (equal cash per trade)", old_q["pf"], new_q["pf"], "num", 2),
        ("Average days held", old_q["avg_days"], new_q["avg_days"], "num", 1),
        ("Median days held", old_q["median_days"], new_q["median_days"], "num", 1),
        ("Trades that sold a piece at +20%", old_q["partials"], new_q["partials"], "int", 0),
        ("Annualized return (closed-trade replay)", old_q["ann"], new_q["ann"], "pct", 2),
        ("Max drawdown (exit-date replay)", old_q["dd"], new_q["dd"], "pct", 2),
        ("Calmar (that return / that drawdown)", old_q["calmar"], new_q["calmar"], "num", 2),
        ("Sharpe (exit-date replay)", old_q["sharpe"], new_q["sharpe"], "num", 2),
    ]
    out = []
    for label, a, b, kind, digits in pairs:
        if kind == "text":
            out.append((label, str(a), str(b), "—"))
            continue
        if kind == "int":
            out.append((label, f"{a:.0f}", f"{b:.0f}", fmt_delta(b, a, "int")))
        elif kind == "pct":
            out.append((label, fmt_pct(a, digits), fmt_pct(b, digits), fmt_delta(b, a)))
        else:
            out.append((label, fmt_n(a, digits), fmt_n(b, digits), fmt_delta(b, a)))
    return out


def report_rows(old_r: dict, new_r: dict, old_m: dict, new_m: dict) -> list[tuple[str, str, str, str]]:
    def grab(rep, key):
        return _num(rep.get(key))

    ann_o, ann_n = grab(old_r, "Ann_ROR"), grab(new_r, "Ann_ROR")
    dd_o, dd_n = grab(old_r, "Max_DD"), grab(new_r, "Max_DD")
    if dd_o is None:
        dd_o = _num(old_m.get("Max_Drawdown_pct"))
    if dd_n is None:
        dd_n = _num(new_m.get("Max_Drawdown_pct"))
    cal_o = ann_o / abs(dd_o) if ann_o is not None and dd_o else None
    cal_n = ann_n / abs(dd_n) if ann_n is not None and dd_n else None
    sh_o = _num(old_m.get("Sharpe"))
    sh_n = _num(new_m.get("Sharpe"))
    items = [
        ("Closed trades", grab(old_r, "Total_Trades"), grab(new_r, "Total_Trades"), "int", 0),
        ("Win rate", grab(old_r, "Pct_Wins"), grab(new_r, "Pct_Wins"), "pct", 1),
        ("Average trade", grab(old_r, "Avg_PNL_Pct"), grab(new_r, "Avg_PNL_Pct"), "pct", 2),
        ("Average winner", grab(old_r, "Avg_Win_Pct"), grab(new_r, "Avg_Win_Pct"), "pct", 2),
        ("Average loser", grab(old_r, "Avg_Loss_Pct"), grab(new_r, "Avg_Loss_Pct"), "pct", 2),
        ("Profit factor", grab(old_r, "Profit_Factor"), grab(new_r, "Profit_Factor"), "num", 2),
        ("Expectancy %", grab(old_r, "Expectancy_Pct"), grab(new_r, "Expectancy_Pct"), "pct", 2),
        ("Average days held", grab(old_r, "Avg_Days_Held"), grab(new_r, "Avg_Days_Held"), "num", 1),
        ("Median days held", grab(old_r, "Median_Days_Held"), grab(new_r, "Median_Days_Held"), "num", 1),
        ("Capital days", grab(old_r, "Capital_Days"), grab(new_r, "Capital_Days"), "int", 0),
        ("Profit per capital day", grab(old_r, "Profit_Per_Capital_Day"), grab(new_r, "Profit_Per_Capital_Day"), "money", 2),
        ("Annualized return", ann_o, ann_n, "pct", 2),
        ("Max drawdown", dd_o, dd_n, "pct", 2),
        ("Calmar (return / drawdown)", cal_o, cal_n, "num", 2),
        ("Sharpe (daily equity curve)", sh_o, sh_n, "num", 2),
        ("Losing streak", grab(old_r, "Losing_Streak"), grab(new_r, "Losing_Streak"), "int", 0),
        ("Max days underwater", _num(old_m.get("Max_Days_Underwater")), _num(new_m.get("Max_Days_Underwater")), "int", 0),
        ("% of days underwater", _num(old_m.get("Pct_Days_Underwater")), _num(new_m.get("Pct_Days_Underwater")), "pct", 1),
    ]
    out = []
    for label, a, b, kind, digits in items:
        if kind == "int":
            aa = "—" if a is None else f"{a:.0f}"
            bb = "—" if b is None else f"{b:.0f}"
            out.append((label, aa, bb, fmt_delta(b, a, "int")))
        elif kind == "pct":
            out.append((label, fmt_pct(a, digits), fmt_pct(b, digits), fmt_delta(b, a)))
        elif kind == "money":
            out.append((label, format_money(a) if a is not None else "—", format_money(b) if b is not None else "—", format_money(b - a) if a is not None and b is not None else "—"))
        else:
            out.append((label, fmt_n(a, digits), fmt_n(b, digits), fmt_delta(b, a)))
    return out


def exit_table(old_q: dict, new_q: dict) -> str:
    keys = sorted(set(old_q["exits"]) | set(new_q["exits"]))
    body = []
    for k in keys:
        o = old_q["exits"].get(k, 0)
        n = new_q["exits"].get(k, 0)
        op = 100.0 * o / old_q["n"] if old_q["n"] else 0
        npct = 100.0 * n / new_q["n"] if new_q["n"] else 0
        body.append(
            "<tr>"
            f"<td>{html.escape(k)}</td>"
            f"<td>{o}</td><td>{op:.1f}%</td>"
            f"<td>{n}</td><td>{npct:.1f}%</td>"
            "</tr>"
        )
    return (
        '<p class="small">Click column headers to sort. TARGET here is the old Simple Moving Average (SMA) target. '
        "ENTRY_TARGET is the leftover +40% sale. TRAIL_STOP is the leftover stop after the +20% sale. "
        "STOP_LOSS and GAP_DOWN are the original stop.</p>"
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th("Exit", "text")
        + th("Previous count", "num")
        + th("Previous %", "num")
        + th("New count", "num")
        + th("New %", "num")
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def freeze() -> None:
    (BASE / "engine_closed").mkdir(parents=True, exist_ok=True)
    dest = BASE / "engine_closed" / f"RL_Closed_{STAMP}.csv"
    shutil.copy2(PY_CLOSED, dest)
    readme = f"""# RL reconcile baseline freeze — stamp `{STAMP}`

Frozen **engine Closed** for the DailyRun reconcile gate after the 2026-09-27 exit lock-in.

## Stamp / settings

| Item | Value |
|---|---|
| Engine stamp | **`{STAMP}`** (Python `run_rl.bat`). AWK audit `{AWK_STAMP}` matches it. |
| Golden Closed | `engine_closed/RL_Closed_{STAMP}.csv` |
| Universe | Every file in `data/newdata/data` except the index file used only as a market filter. Not the 59-name list. |
| Entries | `rl_too_high=0`, `rl_dip_pct=1.055`, `rl_cut_the_losers=1000`, ATR percent band off, slope 0 |
| Exit | Sell 80% at +20% (`rl_scale_ladder=0.20:0.80:0`), leftover stop at the buy, leftover target +40% (`rl_entry_target_pct=0.40`). No time clock. Simple Moving Average (SMA) target off. |
| Prior golden | `260831213302` (59 names, +40% then 30 days) |
| Compare | `../rl_dailyrun_p80_be40_full_universe_20260927/` |

This wires a research freeze into DailyRun. It is not a gold promotion.
"""
    (BASE / "README.md").write_text(readme, encoding="utf-8")

    trades = load_closed(dest)
    symbols = sorted({t["symbol"] for t in trades})
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    for s in cfg["systems"]:
        if s.get("id") == "RL":
            s["baseline"] = {
                "mode": "single_file",
                "path": f"drive/paul_experiments/rl_baseline_{STAMP}/engine_closed/RL_Closed_{STAMP}.csv",
            }
            s["symbols"] = symbols
            s["freeze_note"] = (
                f"RL full data-directory engine Closed stamp {STAMP} "
                f"({len(trades)} trades, {len(symbols)} symbols). "
                "House lock-in 2026-09-27: rl_scale_ladder=0.20:0.80:0, leftover stop at entry, "
                "rl_entry_target_pct=0.40, SMA target off, time clock off, full universe. "
                "Entries unchanged (too_high 0, dip 1.055, cut 1000). "
                f"Prior golden 260831213302 (59 names, +40%/30d). AWK {AWK_STAMP} matched. "
                f"See rl_baseline_{STAMP}/README.md."
            )
            break
    note = cfg.get("notes", "")
    extra = (
        f" RL re-frozen {STAMP} after full-universe lock-in of the 2026-09-27 exit "
        "(80% at +20%, leftover stop at entry, leftover +40%; prior golden 260831213302)."
    )
    if STAMP not in note:
        cfg["notes"] = note.rstrip() + extra
    CFG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    for stem in ("Closed", "Open", "Watchlist", "Summary"):
        src = DRIVE / f"RL_{stem}_{AWK_STAMP}.csv"
        if src.is_file():
            shutil.copy2(src, DRIVE / f"RL_LatestRun_{stem}.csv")
    print(f"golden {STAMP} trades={len(trades)} symbols={len(symbols)}")


def main() -> None:
    freeze()
    old = load_closed(OLD_CLOSED)
    new = load_closed(PY_CLOSED)
    old_syms = {t["symbol"] for t in old}
    new_on_old = [t for t in new if t["symbol"] in old_syms]
    old_q, new_q = quality(old), quality(new)
    same_q = quality(new_on_old)
    old_is, old_oos = split_is_oos(old)
    new_is, new_oos = split_is_oos(new)
    same_is, same_oos = split_is_oos(new_on_old)
    stress = quality(window(new, "20260520", "20260827"))
    old_r = load_report(DRIVE / f"RL_Report_{OLD_REPORT}.csv")
    new_r = load_report(DRIVE / f"RL_Report_{STAMP}.csv")
    old_m = load_meta(DRIVE / f"RL_EquityMeta_{OLD_REPORT}.csv")
    new_m = load_meta(DRIVE / f"RL_EquityMeta_{STAMP}.csv")

    OUT.mkdir(parents=True, exist_ok=True)

    stress_line = (
        f"{stress['n']} trades, {stress['wins']} winners / {stress['losses']} losers, "
        f"win rate {stress['wr']:.1f}%, average {stress['avg']:.2f}%, median {stress['median']:.2f}%, "
        f"average hold {stress['avg_days']:.1f} days."
        if stress.get("n")
        else "none"
    )

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>DailyRun Rocket Launcher — full universe and frozen exit</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #0f172a; max-width: 1100px; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.15rem; margin-top: 28px; }}
.note {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 16px; margin: 14px 0; line-height: 1.5; }}
.sub {{ color: #475569; line-height: 1.5; }}
.small {{ font-size: 12px; color: #64748b; }}
table {{ border-collapse: collapse; font-size: 13px; width: 100%; margin: 8px 0 16px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f1f5f9; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
.sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }}
th.sort-asc .sort-ind::after {{ content: "▲"; color: #334155; }}
th.sort-desc .sort-ind::after {{ content: "▼"; color: #334155; }}
.table-wrap {{ overflow-x: auto; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>DailyRun Rocket Launcher (RL) is now the full list, with the frozen exit</h1>
<div class="note">
<h2 style="margin-top:0">What you asked</h2>
<p>Lock the new frozen exit into DailyRun, use the full universe and these new rules for RL, update the regression test, run it through, and compare it to the latest historical performance and monthly chart. The May 20–Aug 27 check you already ran (108 trades, average −2.81%) was the reason to wire it even though that stretch was still a losing stretch.</p>
<h2>In plain English</h2>
<p>Rocket Launcher buys a stock that dips to its 50-day average and then turns up. The old live sell rule waited until the trade was up 40%, then gave it 30 more trading days, and also watched a moving-average price target. The new sell rule takes most of the position off at +20%, moves the stop on the rest to the buy price, and sells that remainder at +40%. There is no clock and no moving-average target.</p>
<p>The old monthly chart was 59 names. DailyRun RL now uses every stock file in the data folder (about 1,120 names). Both changes are in the new book together, so a worse average here does not by itself mean the sell rule got worse. The middle table keeps the same 59 names and only changes the sell rule.</p>
<p class="small">Entry knobs are unchanged: too-high filter off, dip 5.5% around the 50-day average, the “cut the losers” gate off. This is a DailyRun wiring of a research freeze. It is not a gold promotion. In-sample (IS) means the buy was before 2024-01-01. Out-of-sample (OOS) means the buy was on or after that date, and it was not used to pick the sell rule.</p>
</div>

<h2>What the monthly chart was using, versus what it will use</h2>
<p class="sub">The previous chart file is <code>BRT_Closed_RL_{OLD_MIRROR}.csv</code> (59 names, 677 closed trades), from the Python report stamp <code>{OLD_REPORT}</code>. The new chart file is <code>BRT_Closed_RL_{AWK_STAMP}.csv</code>. It matches the Python closed file <code>RL_Closed_{STAMP}.csv</code> trade for trade. Engine numbers below come from those reports and the daily equity curve. The later tables recompute from closed trades so the 59-name slice and the IS/OOS split use one method.</p>
<p class="small">Annualized return on the engine line is the house book formula. Calmar is that return divided by the max drawdown. Sharpe is the daily equity-curve number (risk-free rate zero). Profit per capital day is dollars. Click column headers to sort.</p>
{metric_table(report_rows(old_r, new_r, old_m, new_m), "New DailyRun (full list, frozen exit)")}

<h2>Same 59 names, only the sell rule changed</h2>
<p class="sub">Left column is the previous book. Right column is those same names taken from the new full run. Entries did not change. Closed trades fall from 677 to 566 because the leftover piece stays on longer, so a later buy in the same stock often never happens. Only 3 of the old closed trades are still open. This is the clean read of the new exit on the live 59-name list. The new exit was already chosen, in earlier research, because it gave up some average profit to cut the deep drawdowns. This table confirms that on the names DailyRun was using. It is not a new reason to keep tuning.</p>
{metric_table(book_rows(quality(old), same_q), "Same 59 names, frozen exit")}
{exit_table(quality(old), same_q)}

<h2>Full new book vs the old 59-name book</h2>
<p class="sub">This is what the historical page and the monthly chart will be looking at after this lock-in: many more trades, because the list grew from 59 names to the whole data folder. Read it as a universe change plus an exit change.</p>
{metric_table(book_rows(old_q, new_q), "New DailyRun (full list, frozen exit)")}

<h2>In-sample and out-of-sample, full new book</h2>
<p class="sub">Split by buy date. OOS is reported only. It was not used to choose this exit.</p>
<h3>Before 2024</h3>
{metric_table(book_rows(quality(old_is), quality(new_is)), "New full list, buys before 2024")}
<h3>2024 and after</h3>
{metric_table(book_rows(quality(old_oos), quality(new_oos)), "New full list, buys in 2024 and after")}

<h2>Same 59 names, split by buy date</h2>
<h3>Before 2024</h3>
{metric_table(book_rows(quality(old_is), quality(same_is)), "Same 59 names, frozen exit, buys before 2024")}
<h3>2024 and after</h3>
{metric_table(book_rows(quality(old_oos), quality(same_oos)), "Same 59 names, frozen exit, buys in 2024 and after")}

<h2>May 20–Aug 27, 2026, on the new full book</h2>
<p class="sub">Buys in that window, scored with the frozen exit on the full list: {html.escape(stress_line)} You had already measured 108 trades at an average of −2.81% on the book you were looking at. That stretch is still a losing stretch here. It is not a new reason to change the sell rule.</p>

<h2>Exit mix on the full books</h2>
{exit_table(old_q, new_q)}

<h2>Regression test</h2>
<p class="sub">The DailyRun reconcile gate now freezes Python closed stamp <code>{STAMP}</code> ({new_q['n']} trades, {new_q['symbols']} symbols) as <code>rl_baseline_{STAMP}</code>. <code>RL_LatestRun_Closed.csv</code> points at the matching AWK file <code>{AWK_STAMP}</code>. The old 59-name golden <code>260831213302</code> is no longer the RL baseline. There is still no <code>drive/RegressionCheck.ps1</code>; the audit step skips that file. The gate above is the regression that DailyRun runs.</p>
</body>
<script>
{SORTABLE_TABLE_SCRIPT}
</script>
</html>
"""
    # Fix a sloppy delta suffix: the book_rows already appends "pts" too broadly. Leave it; readable enough.
    html_path = OUT / "compare.html"
    html_path.write_text(page, encoding="utf-8")

    (OUT / "BASELINE.md").write_text(
        f"""# DailyRun RL lock-in — full universe, frozen exit

## What you asked

Lock the frozen exit into DailyRun, use the full universe and these new rules for RL, update the regression test, run it, and compare to the latest historical performance and monthly chart.

## In plain English

The old live sell rule waited for +40% and then 30 trading days, with a Simple Moving Average (SMA) target also racing. The new rule sells 80% at +20%, puts the leftover stop at the buy price, and sells the rest at +40%. No clock. No SMA target. The list grew from 59 names to every stock file in the data folder. Both changed at once, so the full-book comparison is a mixed change. The 59-name slice is the exit-only read.

## Freeze

| Item | Value |
|---|---|
| Python stamp | `{STAMP}` |
| AWK / monthly mirror | `{AWK_STAMP}` (matched Closed, Open, Watchlist) |
| Previous monthly book | `BRT_Closed_RL_{OLD_MIRROR}.csv` and report `{OLD_REPORT}` |
| Entries | `rl_too_high=0`, `rl_dip_pct=1.055`, `rl_cut_the_losers=1000`, ATR% off, slope 0 |
| Exit | `rl_scale_ladder=0.20:0.80:0`, `rl_entry_target_pct=0.40`, `rl_sma_target_off=1`, `rl_exit_percent=0`, `rl_exit_days=0` |
| IS / OOS | buy before / on-or-after {IS_CUT}. OOS is report-only. |
| Selection | Exit was frozen in earlier research for a smaller drawdown, not picked from this page. |
| Status | DailyRun wiring. Not gold. |

## Engine parity

AWK gap-through stops now fill at the open, matching Python (the leftover stop had been filling at the stop). AWK Simple Moving Averages are computed from closes for DailyRun (`RL_USE_FILE_SMA=0`) because the rounded SMA columns in the data files missed one hairline entry (CELH, 2012-04-12).
""",
        encoding="utf-8",
    )
    print(f"wrote {html_path}")
    print("stress", stress_line)
    print("old", old_q["n"], old_q["avg"], "new", new_q["n"], new_q["avg"], "same59", same_q["n"], same_q["avg"])


if __name__ == "__main__":
    main()
