#!/usr/bin/env python3
"""Stamp RSI DailyRun adopt: atr=2.93, min_dist off (preference, not gold)."""
from __future__ import annotations

import html as html_mod
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from rsi_mindist52_718_ab_20260916 import (  # noqa: E402
    SLICE_HEADERS,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    _delta_pct,
    _fmt_pct,
    arm_row,
    exit_table,
    full_canonical_rows,
    load_closed,
    load_equity_meta,
    load_report,
    load_summary,
    pack,
    slc,
    sortable_th,
    summary_pack,
)

STAMP = "rsi_atr293_dailyrun_20260916"
OUT_DIR = REPO / "drive" / "paul_experiments" / STAMP
DRIVE = REPO / "drive"
CTRL_DIR = DRIVE / "paul_experiments" / "rsi_mindist52_718_20260916" / "control"
CTRL_TS = "260916115932"
PRIOR_DIST_DIR = DRIVE / "paul_experiments" / "rsi_mindist52_718_20260916" / "candidate"
PRIOR_DIST_TS = "260916115932"

ORIGINAL_REQUEST = (
    "let's go with atr 2.93. i like that number of trades and although the numbers "
    "are worse, it gives us more trades and is still very profitable. let's adopt "
    "it and wire it into DailyRun please."
)
PLAIN_ENGLISH = (
    "Relative Strength Index (RSI) buys after a name was hot, then cooled off, "
    "but only if the stock is still swinging enough. That swing floor is Average "
    "True Range percent (ATR%): how large a typical day is versus price. House "
    "used to require ATR% of at least 5, which left about 428 trades and a higher "
    "average gain. You asked to loosen that floor to 2.93% so more setups qualify "
    "(about 876 trades on the 149-name book). Distance-to-52-week-high stays off "
    "so we do not also require price to sit 7.18% below the high — that combo "
    "would cut the book back toward ~770. Average gain drops (about 12.2% to 6.5%) "
    "but the book is still profitable. This is a more-trades preference, not a "
    "quality win."
)


def _read_pin() -> str:
    return (DRIVE / "RSI_house_last_run_ts.txt").read_text(encoding="utf-8").strip().splitlines()[0]


def _copy_house_into_stamp(ts: str) -> None:
    dest = OUT_DIR / "house"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        f"RSI_Closed_{ts}.csv",
        f"RSI_Open_{ts}.csv",
        f"RSI_Watchlist_{ts}.csv",
        f"RSI_Summary_{ts}.csv",
        f"RSI_Report_{ts}.csv",
        f"RSI_EquityCurve_{ts}.csv",
        f"RSI_EquityMeta_{ts}.csv",
        f"RSI_house_last_run_ts.txt",
    ):
        src = DRIVE / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    pin = dest / "RSI_house_last_run_ts.txt"
    if not pin.is_file():
        pin.write_text(ts + "\n", encoding="utf-8")


def _slice_table(ctrl: dict, adopted: dict, sl: str, note: str) -> str:
    title = {
        "IS": "IS (entry &lt; 2024-01-01) — 2.93 was shopped on the full tape / overlay hunt",
        "OOS": "OOS (entry ≥ 2024-01-01) — report-only; do not retune",
        "FULL": "FULL (all history) — overlay $10k/fill on $500k seed for Closed slices",
    }[sl]
    th = "".join(sortable_th(h, t) for h, t in SLICE_HEADERS)
    return (
        f"<h3>{title}</h3>"
        f'<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted.</p>'
        f'<table class="sortable"><thead><tr>{th}</tr></thead><tbody>'
        f"{arm_row('BEFORE (DailyRun atr=5, dist=off)', 'atr=5, dist=off', ctrl, ctrl, sl, '')}"
        f"{arm_row('AFTER (adopted atr=2.93, dist=off)', 'atr=2.93, dist=off', adopted, ctrl, sl, note)}"
        f"</tbody></table>"
    )


def main() -> int:
    house_ts = _read_pin()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _copy_house_into_stamp(house_ts)

    ctrl_all = load_closed(CTRL_DIR, CTRL_TS)
    house_all = load_closed(DRIVE, house_ts)
    if not house_all:
        raise SystemExit(f"no Closed rows for house pin {house_ts}")

    packs = {
        sl: (pack(slc(ctrl_all, sl)), pack(slc(house_all, sl)))
        for sl in ("IS", "OOS", "FULL")
    }
    c_full, a_full = packs["FULL"]
    c_oos, a_oos = packs["OOS"]
    c_is, a_is = packs["IS"]

    prior = None
    if (PRIOR_DIST_DIR / f"RSI_Closed_{PRIOR_DIST_TS}.csv").is_file():
        prior = pack(load_closed(PRIOR_DIST_DIR, PRIOR_DIST_TS))

    c_rep = load_report(CTRL_DIR, CTRL_TS)
    a_rep = load_report(DRIVE, house_ts)
    c_eq = load_equity_meta(CTRL_DIR, CTRL_TS)
    a_eq = load_equity_meta(DRIVE, house_ts)
    c_sum = summary_pack(load_summary(CTRL_DIR, CTRL_TS))
    a_sum = summary_pack(load_summary(DRIVE, house_ts))
    canon = full_canonical_rows(
        c_rep,
        a_rep,
        c_eq,
        a_eq,
        c_sum,
        a_sum,
        c_full.get("avg_wo_max"),
        a_full.get("avg_wo_max"),
    )
    c_ex = Counter(c_full.get("exits") or {})
    a_ex = Counter(a_full.get("exits") or {})

    research = (
        "DISMISS on quality (FULL Avg% 12.22 → 6.49 on the overlay; live house "
        f"Avg% {a_full.get('avg_pnl_pct'):.2f} on N={a_full.get('n')})."
    )
    wired = (
        "DailyRun wired by preference / not gold from metrics. Paul asked for "
        "more trades that are still profitable. min_dist stays off (0). "
        "Not walk-forward gold."
    )

    prior_line = ""
    if prior:
        prior_line = (
            f"- Brief 7.18 + atr=5 DailyRun wire (`{PRIOR_DIST_TS}`) FULL N={prior['n']} "
            f"Avg%={prior['avg_pnl_pct']:.2f} — **reverted**. Do not combine 7.18 with atr=2.93 "
            "(that book is ~770, not ~876).\n"
        )

    baseline = f"""# BASELINE — {STAMP}

**Status:** DailyRun official TBN sleeve — **preference adopt of ATR% ≥ 2.93, min_dist off**.
**Wired by preference / not gold from metrics. Not walk-forward gold.**

Research on `rsi_mindist52_718_20260916` labeled **ATR_2.93_NO_DIST DISMISS** vs control
(Avg% 12.22 → 6.49). Adopt anyway: more trades, still profitable.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

{PLAIN_ENGLISH}

## Honesty / selection

- Source compare arm: **ATR_2.93_NO_DIST** on `rsi_mindist52_718_20260916` (Closed overlay
  on atr=0 / no-dist book, keep if `ATR_PCT_AT_TRIGGER` ≥ 2.93). Overlay FULL N=876 Avg%=6.49.
- Research verdict vs control (atr=5, dist=off): **DISMISS** on quality.
- Adopt is **Paul preference** (trade count). Same pattern as atr6→atr5.
- **min_dist stays off** (`RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER=0`). Do not pass 7.18.
  Combining 7.18 + atr 2.93 is a different book (~770), not this adopt.
{prior_line}- One change vs prior house freeze (atr=5, dist=off): `rsi_min_atr_pct` 5 → **2.93**.
- Freeze otherwise: ob=70 / os=30 / exit=70 / max_trigger=60 / ts=20 / next_open /
  house `rsi_universe.csv` 149 / full history (no `entry_end_date`). Not RSIN_PaulScore5_IS.
- 2.93 was picked after seeing the ~875 hunt — **in-sample selection**. OOS report-only.
  Do not retune on OOS.
- Live house re-run is the DailyRun identity (not the overlay). Overlay ≠ live if a
  skipped quiet fill would have freed the name for a later louder fill.

## Frozen knobs (DailyRun now)

| Knob | Value |
|------|-------|
| Universe | `drive/universes/rsi_universe.csv` (N=149 High-FIT / IS-good) |
| rsi_ob | 70 |
| rsi_os | 30 |
| rsi_exit | 70 |
| rsi_max_trigger | 60 |
| **rsi_min_atr_pct** | **2.93** (was 5) |
| **rsi_min_dist_to_52w_high_pct_at_trigger** | **0 (off)** — 7.18 reverted |
| rsi_time_stop_days | 20 calendar |
| rsi_entry_on | next_open |
| rsi_sheet_notional | 10000 |

## Chronologic split

- IS = `entry_date < 2024-01-01` (reported; quality DISMISS vs atr5)
- OOS = `entry_date >= 2024-01-01` — **report-only**. Do not retune.

### BEFORE — control / prior house (atr=5, dist=off) `{CTRL_TS}`
- **IS** N={c_is['n']} WR={c_is['win_pct']:.2f}% Avg%={c_is['avg_pnl_pct']:.2f} MaxDD={c_is['max_dd']:.2f}
- **OOS** N={c_oos['n']} WR={c_oos['win_pct']:.2f}% Avg%={c_oos['avg_pnl_pct']:.2f} MaxDD={c_oos['max_dd']:.2f}
- **FULL** N={c_full['n']} WR={c_full['win_pct']:.2f}% Avg%={c_full['avg_pnl_pct']:.2f} MaxDD={c_full['max_dd']:.2f}

### AFTER — adopted house (atr=2.93, dist=off) `{house_ts}`
- **IS** N={a_is['n']} WR={a_is['win_pct']:.2f}% Avg%={a_is['avg_pnl_pct']:.2f} MaxDD={a_is['max_dd']:.2f}
- **OOS** N={a_oos['n']} WR={a_oos['win_pct']:.2f}% Avg%={a_oos['avg_pnl_pct']:.2f} MaxDD={a_oos['max_dd']:.2f}
- **FULL** N={a_full['n']} WR={a_full['win_pct']:.2f}% Avg%={a_full['avg_pnl_pct']:.2f} MaxDD={a_full['max_dd']:.2f}

- **Research verdict:** {research}
- **DailyRun:** {wired}
- **OOS Δ Avg%:** {float(a_oos['avg_pnl_pct']) - float(c_oos['avg_pnl_pct']):+.2f} (report-only)

## House pin / wiring

- Engine: `stock_analysis/rocket_rsi.py` via `run_rsi.bat` / DailyRun `[10c/13]`
- Defaults: `RsiConfig.rsi_min_atr_pct=2.93`, `BRTConfig.rsi_min_atr_pct=2.93`,
  `RSI_MIN_ATR_PCT=2.93`, `RSI_MIN_DIST_TO_52W_HIGH_PCT_AT_TRIGGER=0`
- House pin: `drive/RSI_house_last_run_ts.txt` = **`{house_ts}`**
- LatestRun Closed N=**{a_full['n']}** Avg PnL% **{a_full['avg_pnl_pct']:.2f}**
- Expected overlay N ~876. Live N may differ slightly (fill-order vs overlay).
- Not RS (Relative Strength vs SPY). Not RSIN_PaulScore5_IS.
"""
    (OUT_DIR / "BASELINE.md").write_text(baseline, encoding="utf-8")

    canon_th = "".join(
        sortable_th(h, t)
        for h, t in [
            ("Metric", "text"),
            ("BEFORE (atr=5, dist=off)", "num"),
            ("AFTER (atr=2.93, dist=off)", "num"),
            ("Δ after−before", "num"),
        ]
    )
    canon_body = "".join(
        "<tr>" + "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in row) + "</tr>"
        for row in canon
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP}</title>
<style>
{SORTABLE_TH_CSS}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 78rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; }}
table.sortable th {{ background: #f1f5f9; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
.caveat {{ color: #9a3412; font-size: .9rem; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; }}
</style></head><body>
<h1>RSI DailyRun adopt ATR% ≥ 2.93 (min distance off)</h1>
<p class="badge">Wired by preference / not gold from metrics · not walk-forward gold · OOS report-only</p>
<p class="meta">Stamp <code>{STAMP}</code> · 2026-09-16 · house pin <code>{html_mod.escape(house_ts)}</code> · click column headers to sort</p>
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN_ENGLISH)}</p>
</div>
<div class="insight">
<p><strong>Research verdict:</strong> {html_mod.escape(research)}</p>
<p><strong>DailyRun:</strong> {html_mod.escape(wired)}</p>
<p class="caveat"><strong>Selection honesty:</strong> 2.93 was picked after seeing the ~875-trade
hunt on the full tape (in-sample selection). Research labeled DISMISS because average gain
fell (12.22% → 6.49% on the overlay). You still wanted more trades that stay profitable.
Out-of-sample (2024+) is a check only — we did not retune on it. Distance-to-52-week-high
stays <strong>off</strong> so this matches the ATR_2.93_NO_DIST arm (~876), not 7.18+atr2.93 (~770).</p>
<p class="meta">BEFORE control <code>{CTRL_TS}</code> (atr=5, dist=off, isolated stamp) ·
AFTER house pin <code>{html_mod.escape(house_ts)}</code> (live <code>run_rsi.bat</code>,
149-name <code>rsi_universe.csv</code>, full history). Not RSIN_PaulScore5_IS.</p>
</div>
<h2>IS / OOS / FULL (Closed)</h2>
{_slice_table(c_is, a_is, "IS", "in-sample selection")}
{_slice_table(c_oos, a_oos, "OOS", "report-only")}
{_slice_table(c_full, a_full, "FULL", "preference adopt; research DISMISS")}
<h2>FULL host Report / EquityMeta / Summary (canonical set)</h2>
<p class="meta">Click column headers to sort. Sheet $ / Total PnL $ omitted per compare rule.</p>
<table class="sortable"><thead><tr>{canon_th}</tr></thead><tbody>{canon_body}</tbody></table>
<h2>Exit mix (FULL Closed)</h2>
{exit_table(c_ex, a_ex, int(c_full["n"]), int(a_full["n"]))}
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body></html>
"""
    html_path = OUT_DIR / "compare.html"
    html_path.write_text(html, encoding="utf-8")
    (OUT_DIR / "summary.json").write_text(
        json.dumps(
            {
                "house_ts": house_ts,
                "ctrl_ts": CTRL_TS,
                "research_verdict": research,
                "dailyrun": wired,
                "latest_n": a_full.get("n"),
                "latest_avg_pct": a_full.get("avg_pnl_pct"),
                "knobs": {
                    "rsi_min_atr_pct": 2.93,
                    "rsi_min_dist_to_52w_high_pct_at_trigger": 0,
                    "rsi_ob": 70,
                    "rsi_os": 30,
                    "rsi_exit": 70,
                    "rsi_max_trigger": 60,
                    "rsi_time_stop_days": 20,
                    "rsi_entry_on": "next_open",
                },
                "slices": {k: {"before": v[0], "after": v[1]} for k, v in packs.items()},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[rsi atr293] wrote {html_path}")
    print(
        f"  BEFORE {CTRL_TS} FULL N={c_full['n']} Avg%={c_full['avg_pnl_pct']:.2f}"
    )
    print(
        f"  AFTER  {house_ts} FULL N={a_full['n']} Avg%={a_full['avg_pnl_pct']:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
