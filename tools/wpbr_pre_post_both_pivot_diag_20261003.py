#!/usr/bin/env python3
"""WPBR diagnostic: classify frozen 22/15/8/D40 trades by 10%/3-bar pre vs post pivot.

Scoring only. Does not change trades, knobs, or DailyRun.
PRE ONLY / POST ONLY / BOTH from Closed WPBR_PRE_RISE_PCT / WPBR_POST_RISE_PCT
vs the live 10% thresholds (same windows as strong_pre/post_pivot_bars=3).
"""
from __future__ import annotations

import csv
import html as html_mod
import math
import statistics
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from _gen_too_high_diff import SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    ann_ror_from_closed,
    calmar_ratio,
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

IS_CUT = "20240101"
IS_DATE = date(2024, 1, 1)
PRE_PCT = 0.10
POST_PCT = 0.10
THR = PRE_PCT - 1e-12

CLOSED = ROOT / "tmp_wpbr_d40_target15_ab_20261003" / "test" / "WPBR_Closed_261003124834.csv"
REPORT = ROOT / "tmp_wpbr_d40_target15_ab_20261003" / "test" / "WPBR_Report_261003124834.csv"
OUT = ROOT / "drive" / "mark_experiments" / "wpbr_pre_post_both_pivot_diag_20261003"
PY = sys.executable

PRE = "PRE ONLY"
POST = "POST ONLY"
BOTH = "BOTH"
NEITHER = "NEITHER"
ALL = "ALL"

REQUEST_QUOTE = (
    "Test the existing 10% strong-pivot qualification by splitting qualifying WPBR trades "
    "into three mutually exclusive groups based on the current pivot logic: PRE ONLY — "
    "qualifies for the existing 10% pre-pivot strength requirement, but not the post-pivot "
    "requirement. POST ONLY — qualifies for the existing 10% post-pivot rejection "
    "requirement, but not the pre-pivot requirement. BOTH — qualifies on both the "
    "pre-pivot and post-pivot 10% requirements. Keep the current 10% magnitude and 3-bar "
    "windows exactly unchanged. Do not test any other pivot percentages or windows. Keep "
    "the frozen WPBR architecture unchanged: 22% overhead / +15% target / 8% stop / "
    "Day-40 below-entry. Report IS (2010–2023), OOS (2024+), and FULL separately for "
    "PRE ONLY, POST ONLY, and BOTH. For each group report: trade count, win rate, Avg "
    "P&L %, profit factor, max drawdown, annualized ROR, average days held, median days "
    "held, capital days, PPCD, average winner %, and average loser %. This is a "
    "diagnostic classification only. Do not optimize, recommend parameter changes, or "
    "test additional variants."
)

METRIC_SPECS: list[tuple[str, str, str]] = [
    ("Closed trades", "n", "n"),
    ("% of slice", "pct_of_slice", "pct"),
    ("Win rate (WR)", "wr", "pct"),
    ("Avg P&L %", "avg", "pct2"),
    ("Profit factor (PF)", "pf", "num2"),
    ("Expectancy %", "avg", "pct2"),
    ("Avg winner %", "avg_win", "pct2"),
    ("Avg loser %", "avg_loss", "pct2"),
    ("Max DD %", "max_dd", "pct2"),
    ("Ann ROR %", "ann_ror", "pct2"),
    ("Calmar", "calmar", "num2"),
    ("Sharpe", "sharpe", "num2"),
    ("Avg days held", "avg_days", "num1"),
    ("Median days held", "med_days", "num1"),
    ("Capital days", "capital_days", "num0"),
    ("PPCD $", "ppcd", "money"),
    ("Trades / year", "tpy", "num2"),
]


def _f(raw: Any, default: float = float("nan")) -> float:
    if raw is None or raw == "":
        return default
    try:
        v = float(str(raw).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _ymd(raw: str) -> str:
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _to_date(ymd: str) -> date | None:
    raw = _ymd(ymd)
    if len(raw) != 8:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError:
        return None


def _classify(pre: float, post: float) -> str:
    pre_ok = math.isfinite(pre) and pre >= THR
    post_ok = math.isfinite(post) and post >= THR
    if pre_ok and post_ok:
        return BOTH
    if pre_ok:
        return PRE
    if post_ok:
        return POST
    return NEITHER


def load_report() -> tuple[float, float]:
    with REPORT.open(newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f), {})
    cash = _f(row.get("capacity_brt_cash"))
    init = _f(row.get("initial_capital"), DEFAULT_INITIAL_ACCOUNT)
    if not (math.isfinite(cash) and cash > 0):
        raise RuntimeError(f"missing capacity_brt_cash in {REPORT}")
    if not (math.isfinite(init) and init > 0):
        init = float(DEFAULT_INITIAL_ACCOUNT)
    return cash, init


def load_trades() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with CLOSED.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened_s = _ymd(str(raw.get("DATE_OPENED") or ""))
            if not opened_s:
                continue
            opened = _to_date(opened_s)
            closed = _to_date(str(raw.get("DATE_CLOSED") or opened_s))
            pre = _f(raw.get("WPBR_PRE_RISE_PCT"))
            post = _f(raw.get("WPBR_POST_RISE_PCT"))
            group = _classify(pre, post)
            sl = "IS" if opened_s < IS_CUT else "OOS"
            rows.append({
                "symbol": str(raw.get("SYMBOL") or "").strip().upper(),
                "opened_s": opened_s,
                "opened": opened,
                "closed": closed,
                "pnl": _f(raw.get("PNL_PCT")),
                "pnl_d": _f(raw.get("PNL_DOLLARS")),
                "days": _f(raw.get("DAYS_HELD")),
                "exit": str(raw.get("EXIT_TYPE") or "").strip(),
                "pre": pre,
                "post": post,
                "group": group,
                "slice": sl,
            })
    return rows


def _metrics(
    trades: list[dict[str, Any]],
    *,
    cash: float,
    initial_account: float,
    pct_base: int,
) -> dict[str, Any]:
    n = len(trades)
    empty: dict[str, Any] = {
        "n": 0, "pct_of_slice": 0.0, "wr": float("nan"), "avg": float("nan"),
        "pf": float("nan"), "avg_win": float("nan"), "avg_loss": float("nan"),
        "max_dd": float("nan"), "ann_ror": float("nan"), "calmar": float("nan"),
        "sharpe": float("nan"), "avg_days": float("nan"), "med_days": float("nan"),
        "capital_days": 0.0, "ppcd": float("nan"), "tpy": float("nan"),
        "sharpe_source": "",
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades if math.isfinite(t["pnl"])]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    dols = [t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"])]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(d for d in dols if d > 0)
    gl = abs(sum(d for d in dols if d < 0))
    if gl > 0:
        pf = gp / gl
    elif gp > 0:
        pf = float("inf")
    else:
        pf = float("nan")
    avg_days = (sum(days) / len(days)) if days else 0.0
    capital_days = float(sum(days)) if days else 0.0
    total_d = sum(dols) if len(dols) == n else sum(p / 100.0 * cash for p in pnls)
    ppcd = (total_d / capital_days) if capital_days > 0 else float("nan")
    ov = overlay_ann_ror_max_dd(
        trades,
        cash=cash,
        initial_account=initial_account,
        equity_curve_path=None,
        pnl_d_key="pnl_d",
        days_key="days",
        closed_key="closed",
        opened_key="opened",
        pnl_pct_key="pnl",
    )
    house = ann_ror_from_closed(
        total_pnl=total_d, n_trades=n, avg_days_held=avg_days, brt_cash=cash,
    )
    opens = [t["opened"] for t in trades if t.get("opened")]
    closes = [t["closed"] for t in trades if t.get("closed")]
    span = 0.0
    if opens and closes:
        span = (max(closes) - min(opens)).days / 365.25
    ann = float(house) if house is not None else float(ov.get("ann_ror") or float("nan"))
    max_dd = ov.get("max_dd")
    cal = calmar_ratio(ann, max_dd) if max_dd is not None else None
    return {
        "n": n,
        "pct_of_slice": (100.0 * n / pct_base) if pct_base else 0.0,
        "wr": 100.0 * len(wins) / n,
        "avg": (sum(pnls) / n) if pnls else float("nan"),
        "pf": pf,
        "avg_win": (sum(wins) / len(wins)) if wins else float("nan"),
        "avg_loss": (sum(losses) / len(losses)) if losses else float("nan"),
        "max_dd": float(max_dd) if max_dd is not None else float("nan"),
        "ann_ror": ann,
        "calmar": float(cal) if cal is not None else float("nan"),
        "sharpe": float(ov.get("sharpe") or float("nan")),
        "avg_days": avg_days,
        "med_days": float(statistics.median(days)) if days else float("nan"),
        "capital_days": capital_days,
        "ppcd": ppcd,
        "tpy": (n / span) if span > 0.25 else float("nan"),
        "sharpe_source": str(ov.get("sharpe_source") or ""),
    }


def _fmt(v: Any, kind: str) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if kind == "n":
        return str(int(v))
    if kind == "pct":
        return f"{float(v):.1f}%"
    if kind == "pct2":
        return f"{float(v):.2f}%"
    if kind == "num0":
        return f"{float(v):,.0f}"
    if kind == "num1":
        return f"{float(v):.1f}"
    if kind == "num2":
        return f"{float(v):.2f}"
    if kind == "money":
        return f"${float(v):,.2f}"
    return str(v)


def _table(title: str, cols: list[tuple[str, dict[str, Any]]]) -> str:
    heads = sortable_th("Metric", "text") + "".join(sortable_th(name, "num") for name, _ in cols)
    body = []
    for label, key, kind in METRIC_SPECS:
        tds = "".join(f"<td>{_fmt(m.get(key), kind)}</td>" for _, m in cols)
        body.append(f"<tr><td>{html_mod.escape(label)}</td>{tds}</tr>")
    return f"""
<h2>{html_mod.escape(title)}</h2>
<p class="note">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{heads}</tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
"""


def _headline(blocks: dict[str, dict[str, dict[str, Any]]]) -> str:
    heads = "".join([
        sortable_th("Group", "text"), sortable_th("Slice", "text"),
        sortable_th("N", "num"), sortable_th("% of slice", "num"),
        sortable_th("WR", "num"), sortable_th("Avg P&L %", "num"),
        sortable_th("PF", "num"), sortable_th("Max DD %", "num"),
        sortable_th("Ann ROR %", "num"), sortable_th("Avg days", "num"),
        sortable_th("Median days", "num"), sortable_th("Capital days", "num"),
        sortable_th("PPCD $", "num"), sortable_th("Avg winner %", "num"),
        sortable_th("Avg loser %", "num"),
    ])
    rows = []
    for sl in ("FULL", "IS", "OOS"):
        for g in (PRE, POST, BOTH, ALL):
            m = blocks[g][sl]
            rows.append(
                "<tr>"
                f"<td>{html_mod.escape(g)}</td><td>{sl}</td>"
                f"<td>{_fmt(m['n'], 'n')}</td>"
                f"<td>{_fmt(m['pct_of_slice'], 'pct')}</td>"
                f"<td>{_fmt(m['wr'], 'pct')}</td>"
                f"<td>{_fmt(m['avg'], 'pct2')}</td>"
                f"<td>{_fmt(m['pf'], 'num2')}</td>"
                f"<td>{_fmt(m['max_dd'], 'pct2')}</td>"
                f"<td>{_fmt(m['ann_ror'], 'pct2')}</td>"
                f"<td>{_fmt(m['avg_days'], 'num1')}</td>"
                f"<td>{_fmt(m['med_days'], 'num1')}</td>"
                f"<td>{_fmt(m['capital_days'], 'num0')}</td>"
                f"<td>{_fmt(m['ppcd'], 'money')}</td>"
                f"<td>{_fmt(m['avg_win'], 'pct2')}</td>"
                f"<td>{_fmt(m['avg_loss'], 'pct2')}</td>"
                "</tr>"
            )
    return f"""
<h2>Headline (FULL / IS / OOS)</h2>
<p class="note">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
"""


def _recon_table(title: str, counts: dict[str, int], total: int) -> str:
    heads = sortable_th("Group", "text") + sortable_th("N", "num") + sortable_th("% of slice", "num")
    rows = []
    for g in (PRE, POST, BOTH, NEITHER):
        n = counts.get(g, 0)
        pct = (100.0 * n / total) if total else 0.0
        rows.append(f"<tr><td>{html_mod.escape(g)}</td><td>{n}</td><td>{pct:.1f}%</td></tr>")
    s = sum(counts.get(g, 0) for g in (PRE, POST, BOTH, NEITHER))
    rows.append(
        f'<tr class="total-row"><td>Sum (must equal closed N)</td><td>{s}</td>'
        f"<td>{(100.0 * s / total) if total else 0.0:.1f}%</td></tr>"
    )
    return f"""
<h2>{html_mod.escape(title)}</h2>
<p class="note">Click column headers to sort. {SWIPE_NOTE_HTML}</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
"""


def _md_table(cols: list[tuple[str, dict[str, Any]]]) -> list[str]:
    names = ["Metric"] + [n for n, _ in cols]
    lines = ["| " + " | ".join(names) + " |", "| " + " | ".join(["---"] * len(names)) + " |"]
    for label, key, kind in METRIC_SPECS:
        cells = [_fmt(m.get(key), kind) for _, m in cols]
        lines.append("| " + " | ".join([label] + cells) + " |")
    return lines


def write_baseline(blocks: dict[str, dict[str, dict[str, Any]]], cash: float, init: float, n: int) -> None:
    lines = [
        "# WPBR PRE / POST / BOTH 10% pivot diagnostic",
        "",
        "Classification only. Same frozen Closed book. No new parameter tests. Research only. Not DailyRun.",
        "",
        "## What you asked",
        "",
        f"> {REQUEST_QUOTE}",
        "",
        "## In plain English",
        "",
        "Pivot Break and Retest (WPBR) already requires a weekly pivot that is 'strong' by at least "
        "one of two 10% tests over three weekly bars: the run into the pivot (pre) or the rejection "
        "after it (post). This page does not change buys or sells. It only splits the existing "
        "qualifying trades into three buckets: pre-only, post-only, or both. In-sample is entries "
        "before 2024. 2024 onward is out-of-sample, for reading only.",
        "",
        "## Freeze",
        "",
        "- Closed stamp **261003124834** (`tmp_wpbr_d40_target15_ab_20261003/test`).",
        "- Architecture: `wpbr_overhead_band_pct=0.22`, `target_pct=1.15`, `stop_pct=0.92`, "
        "`wpbr_underwater_time_stop_bars=40`.",
        "- Pivot: `strong_pivot_mode=either`, `strong_pre_pivot_bars=3`, `strong_post_pivot_bars=3`, "
        "`strong_pre_pivot_pct=0.10`, `strong_post_pivot_pct=0.10`. No other % or window tested.",
        "- Groups from Closed `WPBR_PRE_RISE_PCT` / `WPBR_POST_RISE_PCT` vs 10% (engine epsilon 1e-12). "
        "Those columns use the same 3-bar weekly high/low windows as live qualification.",
        f"- Slot cash for Ann ROR / PPCD: capacity_brt_cash ${cash:,.2f}. Overlay Max DD / Sharpe "
        f"seeded at initial_capital ${init:,.0f} (exit-date equity; not the full-book EquityCurve).",
        "- IS = `DATE_OPENED < 2024-01-01`. OOS report-only. No KEEP/DISMISS. Not gold. Not DailyRun.",
        f"- Closed N = {n}.",
        "",
        "## Headline",
        "",
    ]
    for sl, title in (
        ("FULL", "Full book"),
        ("IS", "In-sample (entry before 2024-01-01)"),
        ("OOS", "Out-of-sample (entry on or after 2024-01-01) — report only"),
    ):
        lines.append(f"### {title}")
        lines.append("")
        lines.extend(_md_table([(g, blocks[g][sl]) for g in (PRE, POST, BOTH, ALL)]))
        lines.append("")
    (OUT / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")


def write_html(blocks: dict[str, dict[str, dict[str, Any]]], cash: float, init: float, n: int,
               recon: dict[str, dict[str, int]]) -> Path:
    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR PRE / POST / BOTH 10% pivot diagnostic</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1c1917; max-width: 1200px; }}
h1 {{ font-size: 1.5rem; }}
.callout {{ background: #f5f5f0; border: 1px solid #d6d3d1; padding: 12px 16px; margin: 12px 0 18px; }}
blockquote {{ margin: 8px 0; }}
td, th {{ padding: 4px 8px; border-bottom: 1px solid #e7e5e4; }}
td {{ text-align: right; }}
td:first-child, th:first-child {{ text-align: left; }}
.note {{ font-size: 0.95rem; color: #44403c; }}
{SORTABLE_TH_CSS}
{RESPONSIVE_TABLE_CSS}
</style>
</head><body>
{FORCE_RELOAD_SCRIPT}
<h1>Pivot Break and Retest — 10% pre / post / both diagnostic</h1>
<p class="note">Classification only. Frozen 22% overhead / +15% target / 8% stop / Day-40 below-entry. Stamp 261003124834. Not gold. Not DailyRun. Click column headers to sort.</p>
<div class="callout">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(REQUEST_QUOTE)}</blockquote>
<h2>In plain English</h2>
<p>Weekly Pivot Break and Retest (WPBR) already requires a strong weekly pivot. “Strong” means at least one of two 10% moves over three weekly bars: the drop into the pivot (pre) or the bounce/rejection after it (post). This page does not change those trades. It only labels each already-taken trade as pre-only, post-only, or both, then shows whether win rate, average P&amp;L, and annualized rate of return (Ann ROR) differ. Buys before 2024 are in-sample. 2024 onward is for reading only. No new percentages or windows were tested.</p>
</div>
<p class="note">Closed N = {n}. Slot cash ${cash:,.2f} (Report <code>capacity_brt_cash</code>). Ann ROR uses the house formula. Max DD and Sharpe are group overlays from closed exit dates (account ${init:,.0f}), not the full-book EquityCurve. PPCD $ = closed P&amp;L dollars / capital days. Diagnostic only — no KEEP/DISMISS, no parameter recommendation.</p>
{_headline(blocks)}
{_table("Full book", [(g, blocks[g]["FULL"]) for g in (PRE, POST, BOTH, ALL)])}
{_table("In-sample (entry before 2024-01-01)", [(g, blocks[g]["IS"]) for g in (PRE, POST, BOTH, ALL)])}
{_table("Out-of-sample (entry on or after 2024-01-01) — report only", [(g, blocks[g]["OOS"]) for g in (PRE, POST, BOTH, ALL)])}
{_recon_table("Reconciliation — FULL", recon["FULL"], recon["FULL"][ALL])}
{_recon_table("Reconciliation — IS", recon["IS"], recon["IS"][ALL])}
{_recon_table("Reconciliation — OOS", recon["OOS"], recon["OOS"][ALL])}
<p class="note">Picking a favorite group after this table is in-sample selection. Not a live change.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT / "compare.html"
    path.write_text(inject_report_page_extras(page), encoding="utf-8")
    return path


def write_csv(trades: list[dict[str, Any]], blocks: dict[str, dict[str, dict[str, Any]]]) -> None:
    with (OUT / "classified_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["symbol", "DATE_OPENED", "DATE_CLOSED", "slice", "group",
                        "WPBR_PRE_RISE_PCT", "WPBR_POST_RISE_PCT", "PNL_PCT", "PNL_DOLLARS",
                        "DAYS_HELD", "EXIT_TYPE"],
        )
        w.writeheader()
        for t in trades:
            w.writerow({
                "symbol": t["symbol"],
                "DATE_OPENED": t["opened_s"],
                "DATE_CLOSED": t["closed"].strftime("%Y%m%d") if t.get("closed") else "",
                "slice": t["slice"],
                "group": t["group"],
                "WPBR_PRE_RISE_PCT": t["pre"],
                "WPBR_POST_RISE_PCT": t["post"],
                "PNL_PCT": t["pnl"],
                "PNL_DOLLARS": t["pnl_d"],
                "DAYS_HELD": t["days"],
                "EXIT_TYPE": t["exit"],
            })
    fields = [
        "group", "slice", "n", "pct_of_slice", "wr", "avg", "pf", "avg_win", "avg_loss",
        "max_dd", "ann_ror", "calmar", "sharpe", "avg_days", "med_days", "capital_days",
        "ppcd", "tpy",
    ]
    with (OUT / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for g in (PRE, POST, BOTH, ALL):
            for sl in ("FULL", "IS", "OOS"):
                row = {"group": g, "slice": sl, **blocks[g][sl]}
                w.writerow({k: row.get(k) for k in fields})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not CLOSED.is_file():
        raise FileNotFoundError(CLOSED)
    cash, init = load_report()
    trades = load_trades()
    n = len(trades)
    print(f"closed={n} cash={cash} init={init}", flush=True)

    def pick(sl: str, group: str | None) -> list[dict[str, Any]]:
        rows = trades if sl == "FULL" else [t for t in trades if t["slice"] == sl]
        if group and group != ALL:
            rows = [t for t in rows if t["group"] == group]
        return rows

    recon: dict[str, dict[str, int]] = {}
    blocks: dict[str, dict[str, dict[str, Any]]] = {}
    for sl in ("FULL", "IS", "OOS"):
        base = pick(sl, ALL)
        recon[sl] = {g: len(pick(sl, g)) for g in (PRE, POST, BOTH, NEITHER, ALL)}
        print(f"{sl} recon { {k: recon[sl][k] for k in (PRE, POST, BOTH, NEITHER, ALL)} }", flush=True)
    for g in (PRE, POST, BOTH, ALL):
        blocks[g] = {}
        for sl in ("FULL", "IS", "OOS"):
            rows = pick(sl, g)
            blocks[g][sl] = _metrics(rows, cash=cash, initial_account=init, pct_base=recon[sl][ALL])

    write_csv(trades, blocks)
    write_baseline(blocks, cash, init, n)
    html_path = write_html(blocks, cash, init, n, recon)
    print(f"wrote {html_path}", flush=True)
    subprocess.run(
        [PY, str(ROOT / "tools" / "ntfy_job_done.py"), "--path", str(html_path),
         "-t", "WPBR PRE/POST/BOTH 10% pivot diagnostic"],
        cwd=str(ROOT),
        check=False,
    )


if __name__ == "__main__":
    main()
