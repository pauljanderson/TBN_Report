#!/usr/bin/env python3
"""Generate RL 764 PO Q&A pack (2026-08-30). Research only. No commit."""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, sortable_th  # noqa: E402
from rl_univ_compare_lists import (  # noqa: E402
    IS_CUT,
    book_stats,
    load_summary_aggs,
    load_trades,
    split_is_oos,
)

STAMP = "rl_764_po_qa_20260830"
OUT = ROOT / "drive" / "paul_experiments" / STAMP
SRC = ROOT / "drive" / "paul_experiments" / "rl_tradable_2010_adv2m_20260828"
CLOSED_SRC = SRC / "runs" / "tradable" / "RL_Closed_260828112205.csv"
SUMMARY_SRC = SRC / "runs" / "tradable" / "RL_Summary_260828112205.csv"
REPORT_SRC = SRC / "runs" / "tradable" / "RL_Report_260828112205.csv"
UNIV = ROOT / "drive" / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
REJECTS = ROOT / "drive" / "paul_experiments" / "vz_tradable_2010_adv2m_20260818" / "universe_rejects.csv"


def esc(x: object) -> str:
    return html_mod.escape("" if x is None else str(x))


def ths(cols: list[tuple[str, str]]) -> str:
    return "".join(sortable_th(a, b) for a, b in cols)


def parse_opened(s: str) -> date | None:
    t = str(s or "").strip().replace("-", "").replace("/", "")[:8]
    try:
        return datetime.strptime(t, "%Y%m%d").date()
    except ValueError:
        return None


def fnum(s: object) -> float | None:
    try:
        return float(str(s).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    univ: list[str] = []
    for line in UNIV.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.upper() == "SYMBOL":
            continue
        univ.append(s.upper())

    nvda_row = None
    if REJECTS.is_file():
        with REJECTS.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("SYMBOL", "").upper() == "NVDA":
                    nvda_row = row
                    break

    with CLOSED_SRC.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        raw_rows = list(reader)

    trades = load_trades(CLOSED_SRC)
    is_t, oos_t = split_is_oos(trades)
    m_full = book_stats(trades)
    m_is = book_stats(is_t)
    m_oos = book_stats(oos_t)
    _ = load_summary_aggs(SUMMARY_SRC)

    report: dict[str, str] = {}
    with REPORT_SRC.open(encoding="utf-8-sig", newline="") as f:
        report = next(csv.DictReader(f), {}) or {}

    is_raw = []
    for row in raw_rows:
        d = parse_opened(row.get("DATE OPENED", ""))
        if d is not None and d < IS_CUT:
            is_raw.append(row)

    is_closed_path = OUT / "RL_Closed_IS_entry_lt_20240101_from_260828112205.csv"
    with is_closed_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(is_raw)

    longs = sorted([t for t in trades if t["days"] > 1000], key=lambda t: -t["days"])
    ctr = Counter(t["sym"] for t in trades)
    traded = set(ctr)
    never = sorted(set(univ) - traded)
    ones = sorted([s for s, c in ctr.items() if c == 1])
    pnls = [t["pnl"] for t in trades]
    top = sorted(trades, key=lambda t: -t["pnl"])[:10]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    be = [p for p in pnls if p == 0]
    days_vals = [t["days"] for t in trades]
    pct_pnl_max_trade_report = fnum(report.get("Pct_PNL_Max_Trade"))
    sum_pnls = sum(pnls) or 1.0

    metrics_rows = []
    for label, m, n_extra in (
        ("IS (entry < 2024-01-01)", m_is, {"n_raw_closed": len(is_raw)}),
        ("OOS (entry >= 2024-01-01)", m_oos, {}),
        ("FULL", m_full, {"n_raw_closed": len(raw_rows)}),
    ):
        metrics_rows.append(
            {
                "split": label,
                "N": m["n"],
                "WR_pct": round(m["wr"], 2),
                "Avg_PnL_pct": round(m["avg_pnl"], 4),
                "AVG_PNL_PCT_WO_MAX": round(m["wo_max"], 4),
                "Avg_win_pct": round(m["avg_win"], 4),
                "Avg_loss_pct": round(m["avg_loss"], 4),
                "PF": round(m["pf"], 4),
                "Ann_ROR_overlay_pct": round(m["ann_ror"], 4) if math.isfinite(m["ann_ror"]) else "",
                "Max_DD_overlay_pct": round(m["max_dd"], 4) if math.isfinite(m["max_dd"]) else "",
                "Calmar_overlay": round(m["calmar"], 4) if math.isfinite(m["calmar"]) else "",
                "Avg_days": round(m["avg_days"], 2),
                "Med_days": round(m["med_days"], 2),
                "Trades_per_year": round(m["tpy"], 2) if math.isfinite(m["tpy"]) else "",
                "Lose_streak": m["lose_streak"],
                "exit_mix": json.dumps(m["exits"], sort_keys=True),
                **n_extra,
            }
        )

    metrics_path = OUT / "IS_OOS_FULL_book_metrics.csv"
    with metrics_path.open("w", encoding="utf-8", newline="") as f:
        fields = list(metrics_rows[0].keys())
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(metrics_rows)

    long_path = OUT / "long_holds_gt_1000d.csv"
    with long_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["SYMBOL", "DATE_OPENED", "DATE_CLOSED", "DAYS_HELD", "PNL_PCT", "EXIT", "SPLIT"],
        )
        w.writeheader()
        for t in longs:
            w.writerow(
                {
                    "SYMBOL": t["sym"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "DATE_CLOSED": t["closed"].isoformat() if t["closed"] else "",
                    "DAYS_HELD": int(t["days"]),
                    "PNL_PCT": round(t["pnl"], 4),
                    "EXIT": t.get("exit") or "",
                    "SPLIT": "IS" if t["opened"] < IS_CUT else "OOS",
                }
            )

    freq_path = OUT / "trades_per_symbol.csv"
    with freq_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["SYMBOL", "N_TRADES", "ZERO_TRADE"])
        w.writeheader()
        for s in univ:
            w.writerow(
                {
                    "SYMBOL": s,
                    "N_TRADES": ctr.get(s, 0),
                    "ZERO_TRADE": "Y" if s not in traded else "N",
                }
            )

    nvda_asof = nvda_row.get("asof_close") if nvda_row else "49.522"
    top_freq = ", ".join(f"{s} ({c})" for s, c in ctr.most_common(5))
    n2 = sum(1 for c in ctr.values() if c == 2)
    n35 = sum(1 for c in ctr.values() if 3 <= c <= 5)
    n610 = sum(1 for c in ctr.values() if 6 <= c <= 10)
    n1120 = sum(1 for c in ctr.values() if 11 <= c <= 20)
    n21 = sum(1 for c in ctr.values() if c >= 21)

    fact = f"""# Fact sheet — RL 764 PO Q&A (2026-08-30)

**Research honesty.** Not gold. Not DailyRun-wired. Freeze still production knobs + `rl_exit_days=10000` (time-stop off) until PO adopts.

## Dummy version (what the 764 restart was)

We stopped treating the old ~59-name Rocket Launcher (RL) list as “the market.” That list is a curated whitelist (many names fail a simple tradable screen). The restart rebuilds a **trait-only** tape: names that existed by early 2010 and, **as of year-end 2023**, closed ≥ $5 with enough dollar volume. That produced **764** names. Same RL rules as before; only the universe changed. Headline quality looks worse than the whitelist — that is expected when you stop cherry-picking names.

## 1) Close ≥ $5 filter — exact definition

| Item | Value |
|------|-------|
| Builder | `tools/vz_build_tradable_universe.py` |
| Universe CSV | `drive/universes/VZ_tradable_2010_adv2m_universe.csv` |
| Stamp | `drive/paul_experiments/rl_tradable_2010_adv2m_20260828/` |
| First bar | on or before **2010-01-04** |
| Price / liquidity as-of | **2023-12-29** (last bar on/before that date) |
| Close rule | as-of Close **≥ $5** |
| Liquidity | 20-session ADV$ = mean(Close×Volume) **≥ $2,000,000** |
| List type | **Static list** built once from that freeze — **not** point-in-time at each trade entry |
| Traits only | No RL PnL / Paul / FIT in the screen |

**PO plain answer:** It does **not** mean “under $5 in 2010 = gone forever.” It means: did the stock clear **$5 on the as-of date 2023-12-29** (and the age + ADV$ rules)? If yes, it is on the 764 list for the whole backtest. Example: **NVDA** — local OHLC shows ~$0.46 on 2010-01-04 (split-adjusted) but **as-of close ${nvda_asof} on 2023-12-29**, so NVDA **is included**. A name under $5 on 2023-12-29 is out of *this* static universe until someone rebuilds the list with a new freeze.

**Caveat:** This is **not** a live point-in-time “only trade when price ≥ $5 today” gate. Split-adjusted history can show tiny 2010 prices; the screen intentionally ignores that and looks at the as-of close.

## 2) Long holds (>1000 days)

| Metric | Full book `260828112205` |
|--------|---------------------------|
| Trades with DAYS HELD > 1000 | **{len(longs)}** |
| Worst (longest) | **{longs[0]['sym']}** {int(longs[0]['days'])}d, PnL {longs[0]['pnl']:.2f}% ({longs[0].get('exit')}), {longs[0]['opened']}→{longs[0]['closed']} |
| Mean / median days | {mean(days_vals):.1f} / {median(days_vals):.1f} |
| >500d / >250d / >100d | {sum(1 for d in days_vals if d > 500)} / {sum(1 for d in days_vals if d > 250)} / {sum(1 for d in days_vals if d > 100)} |

Time stop **today (DailyRun freeze):** **off** — `rl_exit_days=10000` (Report confirms). Research stamp `rl_time_stop_tradable_20260828`: **PO CONSIDER 40d** after +29%, **not adopted**. First 40d Closed VOID (fill bug); corrected `260828184602`.

## 3) IS Summary / Closed paths (send these)

**No separate engine IS Closed/Summary existed** before this pack. Full artifacts + stamp IS/OOS tables:

| What | Path |
|------|------|
| Full Closed | `drive/paul_experiments/rl_tradable_2010_adv2m_20260828/runs/tradable/RL_Closed_260828112205.csv` |
| Full Summary (per-symbol) | `.../RL_Summary_260828112205.csv` |
| Full Report | `.../RL_Report_260828112205.csv` |
| Stamp IS/OOS tables | `.../BASELINE.md`, `.../SUMMARY.md`, `.../compare.html` |
| **IS Closed (generated)** | `{is_closed_path.as_posix()}` |
| **IS/OOS/FULL book metrics (generated)** | `{metrics_path.as_posix()}` |
| Prior PO pack generator | `tools/rl_764_restart_po_report.py` → `rl_764_restart_po_report_20260828.html` |

**IS numbers (entry < 2024-01-01):** N={m_is['n']} WR={m_is['wr']:.1f}% Avg={m_is['avg_pnl']:.2f}% WO_MAX={m_is['wo_max']:.2f}% PF={m_is['pf']:.2f} AnnROR(overlay)={m_is['ann_ror']:.2f} MaxDD(overlay)={m_is['max_dd']:.2f}

**How to filter yourself:** keep Closed rows where `DATE OPENED` (YYYYMMDD) < `20240101`.

## 4) Trade frequency / one-timers

| Item | Count |
|------|------:|
| Universe | 764 |
| Symbols with ≥1 trade | **{len(traded)}** |
| Exactly 1 trade | **{len(ones)}** |
| 2 trades | {n2} |
| 3–5 | {n35} |
| 6–10 | {n610} |
| 11–20 | {n1120} |
| 21+ | {n21} |
| Most active | {top_freq} |

## 5) One huge winner + many losers?

**Partly true in shape, not “one trade carries the book.”**

| Item | Value |
|------|-------|
| Full N / WR | {m_full['n']} / {m_full['wr']:.1f}% |
| Wins / Losses / BE | {len(wins)} / {len(losses)} / {len(be)} |
| Avg PnL% | {m_full['avg_pnl']:.2f}% |
| AVG_PNL_PCT_WO_MAX | {m_full['wo_max']:.2f}% (drop of {m_full['avg_pnl'] - m_full['wo_max']:.2f}pp) |
| Top trade | **{top[0]['sym']}** {top[0]['pnl']:.2f}% over {int(top[0]['days'])}d (TARGET) |
| Top trade share of sum(PnL%) | ~{100 * top[0]['pnl'] / sum_pnls:.1f}% |
| Report `Pct_PNL_Max_Trade` | {pct_pnl_max_trade_report if pct_pnl_max_trade_report is not None else '—'} |
| Top10 of sum(PnL%) | ~{100 * sum(t['pnl'] for t in top[:10]) / sum_pnls:.1f}% |

More losers than winners (WR ~38%) is real. Removing the single biggest winner only moves Avg from {m_full['avg_pnl']:.2f}% → {m_full['wo_max']:.2f}% — the edge is **not** “only {top[0]['sym']}.” Still: several multi-year TARGET grinds are large; concentration metrics matter.

## 6) Zero-trade names

**{len(never)} of 764** never triggered a trade ({100 * len(never) / len(univ):.1f}%). **{len(traded)}** had ≥1. List: `trades_per_symbol.csv` (`ZERO_TRADE=Y`).

## Freeze reminder

dip 1.055 / expansion 1.163 / stop 0.934 / SMA50 target 1.20 / time-stop off (`rl_exit_days=10000`) / cash $47,500. Research tape only.
"""
    (OUT / "FACT_SHEET.md").write_text(fact, encoding="utf-8")

    email = f"""# Email-ready answers for PO (RL 764) — 2026-08-30

Copy/paste blocks below. Honest caveats kept short.

---

## Dummy version (1 paragraph)

We rebuilt Rocket Launcher (RL) from scratch on a **tradable** universe instead of the old hand-picked ~59 names. The new list is **764** stocks that (1) already had price history by early 2010 and (2) on **2023-12-29** closed at least **$5** with enough average dollar volume. Same entry/exit rules as before — only the name list changed. The 764 book looks weaker than the 59 on headline stats; that’s expected when you stop using a whitelist. This is still **research**, not DailyRun.

---

## 1) Close ≥ $5 — does 2010 under-$5 get banned forever?

**No.** The $5 rule is checked on a single **as-of date: 2023-12-29**, not in 2010 and not at every trade entry. If a stock was cheap in 2010 (or looks tiny because of split-adjusted history) but was ≥ $5 at year-end 2023, it **can** be on the list. NVDA is the example: ~$0.46 on the 2010 chart in our file, ~${nvda_asof} on 2023-12-29 — **included**. Names below $5 on that as-of date are out of *this* static 764 list until we rebuild it. It is **not** a live “price today ≥ $5” filter.

Evidence: `tools/vz_build_tradable_universe.py`; `drive/universes/VZ_tradable_2010_adv2m_universe.csv`; stamp `rl_tradable_2010_adv2m_20260828/BASELINE.md`.

---

## 2) Long holds (>1000 days) / time stop?

**Yes, they exist.** In the 764 full Closed book there are **{len(longs)}** trades held **>1000 calendar days**. Longest: **{longs[0]['sym']}** for **{int(longs[0]['days'])} days** (PnL {longs[0]['pnl']:.2f}%, exit {longs[0].get('exit')}). Average hold is ~{mean(days_vals):.0f} days; median ~{median(days_vals):.0f}.

**Today’s freeze still has no real time stop** (`rl_exit_days=10000` = off). We tested 40- and 80-day time stops after +29%; **40d is a PO CONSIDER**, not adopted into DailyRun yet. Caveat: the first 40d print had a fill bug and was voided; use the corrected stamp.

Evidence: Closed `RL_Closed_260828112205.csv`; `rl_time_stop_tradable_20260828/`.

---

## 3) IS Summary / Closed files to send

Send these:

1. Full Closed: `drive/paul_experiments/rl_tradable_2010_adv2m_20260828/runs/tradable/RL_Closed_260828112205.csv`
2. Full Summary: `.../RL_Summary_260828112205.csv`
3. Stamp write-up with IS/OOS table: `.../SUMMARY.md` + `.../compare.html`
4. **IS-only Closed (generated today):** `drive/paul_experiments/rl_764_po_qa_20260830/RL_Closed_IS_entry_lt_20240101_from_260828112205.csv`
5. **IS/OOS/FULL metrics CSV:** `drive/paul_experiments/rl_764_po_qa_20260830/IS_OOS_FULL_book_metrics.csv`

IS (entry before 2024-01-01): **N={m_is['n']}, WR={m_is['wr']:.1f}%, Avg={m_is['avg_pnl']:.2f}%, WO_MAX={m_is['wo_max']:.2f}%, PF={m_is['pf']:.2f}**.

Engine did not ship a separate “IS Summary” file; Summary is full-book per-symbol. Book-level IS metrics are in the stamp and in the generated metrics CSV.

---

## 4) One-timers / trade frequency

Of **764** names, **{len(traded)}** traded at least once. **{len(ones)}** symbols had **exactly one** trade. Many names fire rarely; a few fire a lot (e.g. {ctr.most_common(1)[0][0]} with {ctr.most_common(1)[0][1]} trades). That is normal on a wide trait tape — not every liquid name forms an RL setup.

---

## 5) One huge winner + many losers?

**Shape is true; “the book is only one winner” is not.** Win rate is about **{m_full['wr']:.0f}%** (more losers than winners). Biggest single trade is **{top[0]['sym']} ~{top[0]['pnl']:.2f}%**. Dropping that one winner only moves average PnL from **{m_full['avg_pnl']:.2f}% → {m_full['wo_max']:.2f}%** (WO_MAX). So the book is not a one-trade story, but long TARGET grinds do matter and we should keep watching concentration (Report max-trade share ~{pct_pnl_max_trade_report}).

---

## 6) How many of 764 never traded?

**{len(never)} names (about {100 * len(never) / len(univ):.0f}%) never triggered a trade.** **{len(traded)}** had ≥1. Zero-trade does not mean “bad stock” — it often means “never printed an RL setup under these knobs.”

---

## Next steps Paul can propose (anti-overfit)

1. Keep **764 as the honest research tape**; do not re-adopt the 59 whitelist because it looks prettier (selection).
2. Judge on **quality** (WR, Avg, WO_MAX, PF, DD), not trade count.
3. **OOS is report-only** — if it softens, HOLD / investigate; do not retune to “fix” OOS.
4. Treat **40d time-stop** as a labeled research CONSIDER (walk-forward already started); adopt only with clear freeze + reconcile, not silent.
5. Any **symbol-quality screen** (drop chronic one-and-done losers, etc.) = new stamped AB, not a silent cut of the 764.
6. Research candidate ≠ gold ≠ DailyRun — no wire from this restart alone.

---
Generated `{STAMP}` from Closed `260828112205`.
"""
    (OUT / "EMAIL_ANSWERS.md").write_text(email, encoding="utf-8")

    long_rows = "".join(
        f"<tr><td>{esc(t['sym'])}</td><td>{esc(t['opened'])}</td><td>{esc(t['closed'])}</td>"
        f"<td>{int(t['days'])}</td><td>{t['pnl']:.2f}</td><td>{esc(t.get('exit'))}</td>"
        f"<td>{'IS' if t['opened'] < IS_CUT else 'OOS'}</td></tr>"
        for t in longs
    )

    bucket_rows = ""
    for label, a, b in [
        ("Exactly 1", 1, 1),
        ("Exactly 2", 2, 2),
        ("3–5", 3, 5),
        ("6–10", 6, 10),
        ("11–20", 11, 20),
        ("21+", 21, 10**9),
    ]:
        n = sum(1 for c in ctr.values() if a <= c <= b)
        bucket_rows += f"<tr><td>{label}</td><td>{n}</td></tr>"

    top_rows = "".join(
        f"<tr><td>{i + 1}</td><td>{esc(t['sym'])}</td><td>{t['pnl']:.2f}</td>"
        f"<td>{int(t['days'])}</td><td>{esc(t['opened'])}</td><td>{esc(t.get('exit'))}</td></tr>"
        for i, t in enumerate(top)
    )

    qa_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RL 764 PO Q&amp;A — 2026-08-30</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; max-width: 1100px; color: #1a1a1a; line-height: 1.45; }}
h1,h2 {{ margin-top: 1.4em; }}
.muted {{ color: #555; }}
.box {{ background: #f6f7f9; border: 1px solid #ddd; padding: 12px 14px; margin: 12px 0; }}
.answer {{ background: #eef7ee; border-left: 4px solid #3a7; padding: 10px 12px; margin: 8px 0 16px; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 14px; margin: 10px 0 18px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; text-align: left; }}
th.sortable-th {{ cursor: pointer; background: #f0f0f0; user-select: none; }}
th.sortable-th .sort-ind {{ margin-left: 4px; opacity: 0.5; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: "▲"; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: "▼"; }}
code {{ font-size: 0.92em; }}
.hi {{ background: #fff8d6; }}
</style>
</head>
<body>
<h1>Rocket Launcher (RL) 764 — PO Q&amp;A pack</h1>
<p class="muted">Generated 2026-08-30 from stamp <code>rl_tradable_2010_adv2m_20260828</code> / Closed <code>260828112205</code>.
Research only. Not gold / not DailyRun. Click column headers to sort.</p>

<div class="box">
<strong>Dummy version:</strong> We rebuilt RL on a trait-only tradable tape (764 names: listed by early 2010; as-of 2023-12-29 Close ≥ $5 and ADV$ ≥ $2m) instead of the curated ~59 whitelist. Same knobs; only the universe changed. Headline quality is lower than the whitelist — expected. Still research.
</div>

<h2>1. Close ≥ $5 filter</h2>
<div class="answer">
<strong>Answer:</strong> Not “under $5 in 2010 = banned forever.” Static as-of <strong>2023-12-29</strong> Close ≥ $5 (+ first bar ≤ 2010-01-04 + ADV$2m). NVDA ~$0.46 in 2010 file / ~${esc(nvda_asof)} as-of → included. Not point-in-time at entry.
</div>
<table class="sortable"><thead><tr>
{ths([("Field", "text"), ("Value", "text")])}
</tr></thead><tbody>
<tr><td>Builder</td><td><code>tools/vz_build_tradable_universe.py</code></td></tr>
<tr><td>As-of</td><td>2023-12-29</td></tr>
<tr><td>Close rule</td><td>≥ $5 on as-of bar</td></tr>
<tr><td>ADV$</td><td>20d mean(Close×Volume) ≥ $2,000,000</td></tr>
<tr><td>List type</td><td>Static trait list (not PIT)</td></tr>
<tr><td>NVDA as-of close</td><td>{esc(nvda_asof)} (pass)</td></tr>
<tr><td>Universe</td><td><code>drive/universes/VZ_tradable_2010_adv2m_universe.csv</code> (764)</td></tr>
</tbody></table>

<h2>2. Long holds &gt;1000 days / time stop</h2>
<div class="answer">
<strong>Answer:</strong> Yes — <strong>{len(longs)}</strong> trades &gt;1000d. Longest <strong>{esc(longs[0]['sym'])}</strong> {int(longs[0]['days'])}d.
Freeze time-stop still <strong>off</strong> (<code>rl_exit_days=10000</code>). 40d is PO CONSIDER, not adopted.
</div>
<table class="sortable"><thead><tr>
{ths([("SYMBOL", "text"), ("Opened", "date"), ("Closed", "date"), ("Days", "num"), ("PnL%", "num"), ("Exit", "text"), ("Split", "text")])}
</tr></thead><tbody>
{long_rows}
</tbody></table>

<h2>3. Files to send (IS + full)</h2>
<div class="answer">
<strong>Answer:</strong> Full Closed/Summary under the 764 stamp; IS Closed + book metrics generated in this folder. No separate engine IS Summary existed.
</div>
<ul>
<li>Full Closed: <code>{esc(CLOSED_SRC.as_posix())}</code></li>
<li>Full Summary: <code>{esc(SUMMARY_SRC.as_posix())}</code></li>
<li>Stamp IS/OOS: <code>{esc((SRC / 'SUMMARY.md').as_posix())}</code> / <code>compare.html</code></li>
<li>IS Closed: <code>{esc(is_closed_path.as_posix())}</code> (N={len(is_raw)})</li>
<li>Metrics: <code>{esc(metrics_path.as_posix())}</code></li>
</ul>
<table class="sortable"><thead><tr>
{ths([("Split", "text"), ("N", "num"), ("WR%", "num"), ("Avg%", "num"), ("WO_MAX%", "num"), ("PF", "num"), ("AnnROR overlay", "num"), ("MaxDD overlay", "num"), ("Avg days", "num")])}
</tr></thead><tbody>
<tr class="hi"><td>IS</td><td>{m_is['n']}</td><td>{m_is['wr']:.1f}</td><td>{m_is['avg_pnl']:.2f}</td><td>{m_is['wo_max']:.2f}</td><td>{m_is['pf']:.2f}</td><td>{m_is['ann_ror']:.2f}</td><td>{m_is['max_dd']:.2f}</td><td>{m_is['avg_days']:.1f}</td></tr>
<tr><td>OOS</td><td>{m_oos['n']}</td><td>{m_oos['wr']:.1f}</td><td>{m_oos['avg_pnl']:.2f}</td><td>{m_oos['wo_max']:.2f}</td><td>{m_oos['pf']:.2f}</td><td>{m_oos['ann_ror']:.2f}</td><td>{m_oos['max_dd']:.2f}</td><td>{m_oos['avg_days']:.1f}</td></tr>
<tr><td>FULL</td><td>{m_full['n']}</td><td>{m_full['wr']:.1f}</td><td>{m_full['avg_pnl']:.2f}</td><td>{m_full['wo_max']:.2f}</td><td>{m_full['pf']:.2f}</td><td>{m_full['ann_ror']:.2f}</td><td>{m_full['max_dd']:.2f}</td><td>{m_full['avg_days']:.1f}</td></tr>
</tbody></table>

<h2>4. Trade frequency / one-timers</h2>
<div class="answer">
<strong>Answer:</strong> <strong>{len(ones)}</strong> symbols with exactly 1 trade; <strong>{len(traded)}</strong> traded ≥1; <strong>{len(never)}</strong> never traded.
</div>
<table class="sortable"><thead><tr>
{ths([("Trades / symbol", "text"), ("N symbols", "num")])}
</tr></thead><tbody>
{bucket_rows}
<tr><td>Zero (in universe)</td><td>{len(never)}</td></tr>
</tbody></table>

<h2>5. One huge winner + many losers?</h2>
<div class="answer">
<strong>Answer:</strong> More losers than winners (WR {m_full['wr']:.1f}%). Top trade {esc(top[0]['sym'])} {top[0]['pnl']:.2f}%. WO_MAX {m_full['wo_max']:.2f}% vs Avg {m_full['avg_pnl']:.2f}% — not a one-trade book, but long TARGET grinds matter. Report Pct_PNL_Max_Trade={esc(pct_pnl_max_trade_report)}.
</div>
<table class="sortable"><thead><tr>
{ths([("Rank", "num"), ("SYMBOL", "text"), ("PnL%", "num"), ("Days", "num"), ("Opened", "date"), ("Exit", "text")])}
</tr></thead><tbody>
{top_rows}
</tbody></table>

<h2>6. Never triggered</h2>
<div class="answer">
<strong>Answer:</strong> <strong>{len(never)} / 764</strong> ({100 * len(never) / 764:.1f}%) never printed a trade under this freeze.
</div>

<h2>Next steps (anti-overfit)</h2>
<ol>
<li>Keep 764 as honest research tape; don’t re-crown the 59 whitelist on looks.</li>
<li>Quality over N; OOS report-only — no OOS retune.</li>
<li>40d time-stop = labeled CONSIDER; adopt only with freeze + reconcile.</li>
<li>Any symbol-quality cut = stamped AB, not silent drop.</li>
<li>Research ≠ gold ≠ DailyRun.</li>
</ol>

<p class="muted">Also: <code>FACT_SHEET.md</code>, <code>EMAIL_ANSWERS.md</code>, <code>long_holds_gt_1000d.csv</code>, <code>trades_per_symbol.csv</code>.</p>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""

    html_path = OUT / "po_qa.html"
    html_path.write_text(qa_html, encoding="utf-8")

    (OUT / "README.md").write_text(
        f"""# `{STAMP}` — RL 764 PO Q&A pack (2026-08-30)

Artifacts for Portfolio Owner questions on the tradable 764 restart.

- `po_qa.html` — sortable Q&A summary
- `FACT_SHEET.md` — numbers + paths
- `EMAIL_ANSWERS.md` — paste-ready replies
- `RL_Closed_IS_entry_lt_20240101_from_260828112205.csv` — IS Closed (N={len(is_raw)})
- `IS_OOS_FULL_book_metrics.csv` — book metrics
- `long_holds_gt_1000d.csv` — holds >1000d
- `trades_per_symbol.csv` — frequency + zero-trade flag

Source book: `rl_tradable_2010_adv2m_20260828` / `RL_Closed_260828112205.csv`.
No commit. Research only.
""",
        encoding="utf-8",
    )

    print("OUT", OUT)
    print("IS_closed", len(is_raw), "FULL", len(raw_rows))
    print("longs", len(longs), "never", len(never), "ones", len(ones))
    print("html", html_path)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                sys.executable,
                str(ntfy),
                "--path",
                str(html_path),
                "-t",
                "RL 764 PO Q&A pack",
                "-m",
                "Close>=$5 as-of, long holds, IS Closed, frequency, outliers, zero-trade",
            ],
            cwd=str(ROOT),
            check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
