#!/usr/bin/env python3
"""RL target vs entry extension — Paul mental-model check.

Target = prior-day SMA50 × rl_target_pct (1.20), recomputed daily in hold.
cut_the_losers = prior-bar High vs prior-bar SMA50 (not entry price).

Usage:
  python tools/rl_target_vs_extension_check.py
"""
from __future__ import annotations

import csv
import html as html_mod
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402

STAMP = "20260831"
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"rl_target_vs_extension_check_{STAMP}"
CLOSED = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "rl_tradable_2010_adv2m_20260828"
    / "runs"
    / "tradable"
    / "RL_Closed_260828112205.csv"
)
DATA_DIR = ROOT / "data" / "newdata" / "data"
SMA50 = 50
CUT = 0.25
NEAR_LO = 0.20
TARGET_MULT = 1.20


def _parse_d(s: Any) -> Optional[date]:
    s = str(s or "").strip()
    if not s:
        return None
    for cand, fmt in ((s[:10], "%Y-%m-%d"), (s.replace("-", "")[:8], "%Y%m%d")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _f(row: dict, *keys: str) -> float:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return float(str(v).replace(",", "").replace("%", ""))
    return 0.0


def cur_hi_pct_at_entry(sym: str, entry: date) -> Optional[tuple[float, float]]:
    """Prior-bar high vs prior-bar SMA50 at signal (matches rocket_rl.py)."""
    path = DATA_DIR / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    cols = {str(c).lower(): c for c in df.columns}
    need = {"date", "open", "high", "low", "close"}
    if not need.issubset(cols):
        return None
    df = df.rename(
        columns={
            cols["date"]: "Date",
            cols["open"]: "Open",
            cols["high"]: "High",
            cols["low"]: "Low",
            cols["close"]: "Close",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    df = df.sort_values("Date")
    dates = list(df["Date"])
    if entry not in dates:
        return None
    fill_i = dates.index(entry)
    if fill_i < 2:
        return None
    sub = df.iloc[:fill_i]
    sma = sub["Close"].rolling(SMA50, min_periods=SMA50).mean()
    prior_i = fill_i - 2
    y_sma = float(sma.iloc[prior_i])
    if not np.isfinite(y_sma) or y_sma <= 0:
        return None
    hi = float(sub["High"].iloc[prior_i])
    return (hi - y_sma) / y_sma, y_sma


def bucket(pct: float) -> str:
    if pct >= CUT:
        return "ge_25"
    if pct >= NEAR_LO:
        return "20_24.99"
    return "lt_20"


def load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with CLOSED.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            sym = str(raw.get("SYMBOL") or "").strip().upper()
            opened = _parse_d(raw.get("DATE OPENED"))
            if not sym or opened is None:
                continue
            entry = _f(raw, "ENTRY PRICE")
            sma50_e = _f(raw, "SMA50")
            orig_tgt = _f(raw, "ORIGINAL TARGET")
            if entry <= 0 or sma50_e <= 0 or orig_tgt <= 0:
                continue
            ch = cur_hi_pct_at_entry(sym, opened)
            if ch is None:
                continue
            cur_hi, sig_sma = ch
            entry_vs_sma = (entry - sma50_e) / sma50_e
            entry_vs_sig = (entry - sig_sma) / sig_sma
            upside_orig = (orig_tgt - entry) / entry
            rows.append(
                {
                    "sym": sym,
                    "opened": opened,
                    "entry": entry,
                    "sma50_e": sma50_e,
                    "sig_sma": sig_sma,
                    "orig_tgt": orig_tgt,
                    "cur_hi_pct": cur_hi,
                    "entry_vs_sma50": entry_vs_sma,
                    "entry_vs_sig_sma": entry_vs_sig,
                    "upside_orig": upside_orig,
                    "hi_entry_gap": cur_hi - entry_vs_sma,
                    "bucket": bucket(cur_hi),
                    "exit": str(raw.get("EXIT TYPE") or "").strip(),
                    "pnl": str(raw.get("PNL %") or "").strip(),
                    "exit_price": _f(raw, "EXIT PRICE"),
                }
            )
    return rows


def agg(sub: list[dict[str, Any]]) -> dict[str, float]:
    if not sub:
        return {"n": 0}
    return {
        "n": len(sub),
        "cur_hi_avg": 100 * np.mean([r["cur_hi_pct"] for r in sub]),
        "entry_sma_avg": 100 * np.mean([r["entry_vs_sma50"] for r in sub]),
        "entry_sma_med": 100 * np.median([r["entry_vs_sma50"] for r in sub]),
        "upside_avg": 100 * np.mean([r["upside_orig"] for r in sub]),
        "upside_med": 100 * np.median([r["upside_orig"] for r in sub]),
        "gap_avg": 100 * np.mean([r["hi_entry_gap"] for r in sub]),
    }


def pick_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    near = [r for r in rows if r["bucket"] == "20_24.99"]
    picks: list[dict[str, Any]] = []

    def pnl_val(r: dict) -> float:
        try:
            return float(str(r["pnl"]).replace("%", "").replace(",", ""))
        except ValueError:
            return -999.0

    for r in sorted(near, key=pnl_val, reverse=True)[:2]:
        picks.append({**r, "why": "Near-ceiling TARGET winner"})
    # Typical near band with moderate entry extension
    for r in sorted(near, key=lambda x: abs(x["entry_vs_sma50"] - 0.10)):
        if r not in picks:
            picks.append({**r, "why": "Near-ceiling ~10% above SMA50 at fill"})
            break
    return picks[:3]


def write_summary(
    full: dict[str, float],
    near: dict[str, float],
    examples: list[dict[str, Any]],
    closed_n: int,
) -> None:
    ex_lines = []
    for r in examples:
        ex_lines.append(
            f"- **{r['sym']}** ({r['opened']}): prior-bar high **{r['cur_hi_pct']*100:.1f}%** above SMA50; "
            f"fill **{r['entry_vs_sma50']*100:.1f}%** above entry-day SMA50 @ {r['entry']:.2f}; "
            f"ORIGINAL TARGET **{r['orig_tgt']:.2f}** ({r['upside_orig']*100:.1f}% above fill); "
            f"→ {r['exit']} **{r['pnl']}**"
        )

    text = f"""# RL target vs extension — {STAMP}

## Plain English (Paul)

**Paul's question:** Target is 20% above SMA50, but `cut_the_losers` allows entries when the prior bar's high is up to 25% above SMA50. If we're already extended, how is there room to make money?

**Short answer:** The concern mixes two different prices. **`cut_the_losers` measures the prior bar's HIGH** (the rally peak), **not your fill price**. RL enters on a **dip**: signal-day low must sit in the SMA50 band (±5.5% with house `rl_dip_pct=1.055`), then you **buy the next open**. By fill, price is usually **much closer to SMA50** than the prior high was.

**Target is not "20% above entry."** It is **`prior-day SMA50 × 1.20`**, recomputed each day while the trade is open (AWK/Python agree). At entry the CSV snapshots that as **ORIGINAL TARGET** = signal-prior SMA50 × 1.20. As SMA50 trends up during the hold, the live target **drifts higher** too.

**If entry were 10% above SMA50 and target is 20% above the same SMA50**, the snapshot upside is ~**9%** from fill to ORIGINAL TARGET — not zero. Near-ceiling trades (prior high 20–24.99% above SMA50) still show **~{near.get('upside_med', 0):.1f}% median** snapshot upside at fill because fills average only **~{near.get('entry_sma_med', 0):.1f}%** above SMA50.

**Verdict:** Partially valid intuition **if** you assumed entry happens at the prior-high extension level. **Not valid** for actual RL mechanics — dip entry + SMA50-anchored target are decoupled from the cut filter.

## Key formulas (code)

| Piece | Formula |
|-------|---------|
| Target (daily, in hold) | `rl_target = sma50[yesterday] × rl_target_pct` (default **1.20**) |
| ORIGINAL TARGET (at entry) | `sma50[signal_yesterday] × rl_target_pct` — frozen snapshot in Closed CSV |
| cut_the_losers | `(prior_bar_high - prior_bar_sma50) / prior_bar_sma50 < 0.25` |
| Dip gate | signal low in `[y_sma×(2-rl_dip_pct), y_sma×rl_dip_pct]` ≈ ±5.5% band |
| Fill | **next-day open** after signal |

Sources: `stock_analysis/rocket_rl.py` (lines ~919, ~1273–1274, ~1401), `stock_analysis/portfolio_audit.awk` (lines ~741, ~964, ~1317, ~1474).

## Closed book stats (`RL_Closed_260828112205`, N={closed_n:,} labeled)

| Cohort | N | Avg prior-hi vs SMA50 | Avg fill vs SMA50 | Med fill vs SMA50 | Med upside to ORIGINAL TARGET |
|--------|---|----------------------|-------------------|-------------------|-------------------------------|
| Full book | {full['n']} | {full['cur_hi_avg']:.1f}% | {full['entry_sma_avg']:.1f}% | {full['entry_sma_med']:.1f}% | {full['upside_med']:.1f}% |
| 20–24.99% cut band (allowed) | {near['n']} | {near['cur_hi_avg']:.1f}% | {near['entry_sma_avg']:.1f}% | {near['entry_sma_med']:.1f}% | {near['upside_med']:.1f}% |

Avg **gap** (prior-hi extension minus fill extension) in the near band: **{near.get('gap_avg', 0):.1f}%** — the dip pulls you off the prior high.

## Worked examples (near-ceiling band)

{chr(10).join(ex_lines)}

## Note on HIST_HIGH_PCT in Closed CSV

That column is **lifetime peak** high-vs-SMA50 for the symbol, **not** the `cut_the_losers` reading at entry. Use recomputed `cur_hi_pct` (prior bar at signal) for the filter.

See `report.html` and `trade_extension.csv` for sortable detail.
"""
    (OUT_DIR / "SUMMARY.md").write_text(text, encoding="utf-8")


def write_html(examples: list[dict[str, Any]], summary_rows: list[dict], trade_rows: list[dict]) -> Path:
    th = "".join(
        sortable_th(lbl, typ)
        for lbl, typ in [
            ("Cohort", "text"),
            ("N", "num"),
            ("Avg prior-hi%", "num"),
            ("Avg fill vs SMA50%", "num"),
            ("Med fill vs SMA50%", "num"),
            ("Med upside to orig tgt%", "num"),
        ]
    )
    sum_body = "".join(
        f"<tr><td>{html_mod.escape(r['cohort'])}</td><td>{r['n']}</td>"
        f"<td>{r['cur_hi_avg']:.2f}</td><td>{r['entry_sma_avg']:.2f}</td>"
        f"<td>{r['entry_sma_med']:.2f}</td><td>{r['upside_med']:.2f}</td></tr>"
        for r in summary_rows
    )
    ex_th = "".join(
        sortable_th(lbl, typ)
        for lbl, typ in [
            ("Symbol", "text"),
            ("Entry", "date"),
            ("Prior-hi%", "num"),
            ("Fill vs SMA50%", "num"),
            ("Entry", "num"),
            ("Orig target", "num"),
            ("Upside%", "num"),
            ("Exit", "text"),
            ("PnL%", "text"),
        ]
    )
    ex_body = "".join(
        f"<tr><td>{r['sym']}</td><td>{r['opened']}</td>"
        f"<td>{100*r['cur_hi_pct']:.2f}</td><td>{100*r['entry_vs_sma50']:.2f}</td>"
        f"<td>{r['entry']:.2f}</td><td>{r['orig_tgt']:.2f}</td>"
        f"<td>{100*r['upside_orig']:.2f}</td><td>{html_mod.escape(r['exit'])}</td>"
        f"<td>{html_mod.escape(r['pnl'])}</td></tr>"
        for r in examples
    )
    tr_th = "".join(
        sortable_th(lbl, typ)
        for lbl, typ in [
            ("Symbol", "text"),
            ("Entry", "date"),
            ("Prior-hi%", "num"),
            ("Fill vs SMA50%", "num"),
            ("Upside orig%", "num"),
            ("Bucket", "text"),
            ("Exit", "text"),
            ("PnL%", "text"),
        ]
    )
    tr_body = "".join(
        f"<tr><td>{r['sym']}</td><td>{r['opened']}</td>"
        f"<td>{100*r['cur_hi_pct']:.2f}</td><td>{100*r['entry_vs_sma50']:.2f}</td>"
        f"<td>{100*r['upside_orig']:.2f}</td><td>{r['bucket']}</td>"
        f"<td>{html_mod.escape(r['exit'])}</td><td>{html_mod.escape(r['pnl'])}</td></tr>"
        for r in trade_rows[:400]
    )
    path = OUT_DIR / "report.html"
    path.write_text(
        f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>RL target vs extension {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 1100px; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: right; }}
th {{ background: #f4f4f4; }}
td:first-child, th:first-child {{ text-align: left; }}
.muted {{ color: #555; }}
{SORTABLE_TH_CSS}
</style></head><body>
<h1>RL target vs entry extension</h1>
<p class="muted">Target = prior-day SMA50 × 1.20 (not entry × 1.20). cut_the_losers = prior-bar HIGH vs SMA50.
Closed: RL_Closed_260828112205. Click column headers to sort.</p>

<h2>Summary</h2>
<table class="sortable"><thead><tr>{th}</tr></thead><tbody>{sum_body}</tbody></table>

<h2>Examples (20–24.99% prior-hi band)</h2>
<table class="sortable"><thead><tr>{ex_th}</tr></thead><tbody>{ex_body}</tbody></table>

<h2>All trades (sample)</h2>
<table class="sortable"><thead><tr>{tr_th}</tr></thead><tbody>{tr_body}</tbody></table>
{SORTABLE_TABLE_SCRIPT}
</body></html>""",
        encoding="utf-8",
    )
    return path


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not CLOSED.is_file():
        print(f"Missing {CLOSED}", file=sys.stderr)
        return 1

    rows = load_rows()
    closed_n = sum(1 for _ in csv.DictReader(CLOSED.open(encoding="utf-8-sig")))
    full_a = agg(rows)
    near_a = agg([r for r in rows if r["bucket"] == "20_24.99"])
    examples = pick_examples(rows)

    summary_rows = [
        {"cohort": "Full book", **full_a},
        {"cohort": "20–24.99% cut band", **near_a},
    ]

    trade_csv = OUT_DIR / "trade_extension.csv"
    with trade_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sym",
                "opened",
                "cur_hi_pct",
                "entry_vs_sma50",
                "entry_vs_sig_sma",
                "upside_orig",
                "bucket",
                "exit",
                "pnl",
                "entry",
                "sma50_e",
                "orig_tgt",
            ],
        )
        w.writeheader()
        for r in sorted(rows, key=lambda x: (-x["cur_hi_pct"], x["sym"])):
            w.writerow({k: r.get(k, "") for k in w.fieldnames})

    write_summary(full_a, near_a, examples, closed_n)
    html_path = write_html(examples, summary_rows, rows)
    print(f"Wrote {OUT_DIR}")

    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ntfy_job_done.py"), "--path", str(html_path)],
        check=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
