#!/usr/bin/env python3
"""Generate MARKTEN_SC_FULL_MISMATCH_INVENTORY.md from inventory JSON + NFLX findings."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

BASE = Path(r"C:\Users\songg\Downloads\stockresearch\drive\wpbr_sheet_reconcile")
inv = json.loads((BASE / "_tmp_markten_mismatch_inv.json").read_text(encoding="utf-8"))

lines: list[str] = []
A = lines.append

A("# MarkTen SC-on — full mismatch inventory (identity grade)")
A("")
A("**Stamp:** `260722145252` — `_markten_variantC_SC_2016_20260722145207/`")
A("**Settings:** variant C, `retest_mode=stop_looking`, `start_date=2016-01-01`, `target_pct=1.22`, engine `stop_pct=0.89`, SC on.")
A("**Ground truth:** WPBR sheet trade ledger (pastes under `drive/wpbr_sheet_reconcile/<TICKER>/`).")
A("**Policy:** engine exits earlier / later than sheet are **mismatches**, not footnotes. No silent code change in this pass.")
A("")
A("---")
A("")
A("## Parent-ready summary")
A("")
A("1. **NFLX Aug-2023 exit:** Sheet LOSS **2023-10-12 @ 36.24**; engine STOP **2023-10-13 @ 35.44**. Not gap priority, not exit-on-close, not `stop_looking`. **Stop level differs:** sheet exit prices across MarkTen LOSS trades fit **`signal_low × 0.91`** (9% below signal low); engine uses **`signal_low × 0.89`** (run log). On 10/12 Low=35.905 touches sheet stop ~36.23/36.24 but **not** eng stop 35.44; eng first touch is 10/13.")
A("2. **That exit fork causes the SC re-entry lag:** sheet frees the slot on 10/12 → rocket 10/13 → fill **10/16**; eng still open until 10/13 STOP → fill **10/17**.")
A("3. **Systemic, not NFLX-only:** **39/39** matched entry-date exit-date forks are **sheet earlier** than engine, and sheet exit px **above** eng `STOP_PRICE`. Plus **11** same-day exit-price mismatches (sheet stop px > eng stop px).")
A("4. **Zones/retests/rockets** are already aligned on this stamp (per `VARIANT_C_SC_2016_MARKTEN_STATUS.md`). Residuals are almost entirely **trade ledger / stop / occupancy cascade**.")
A("5. **#1 fix for identity:** confirm sheet stop cell/formula; if ledger is truth, re-run engine with **`stop_pct=0.91`** (or change sheet to 0.89). Do not chase SC fill dates until stops match.")
A("")
A("---")
A("")
A("## 1. NFLX Aug-2023 exit — precise")
A("")
A("### Trade fields")
A("")
A("| | Entry Date | Entry Price | Exit Date | Exit Price | Result / type |")
A("|---|---|---:|---|---:|---|")
A("| **Sheet** | 2023-08-21 | 40.22 | **2023-10-12** | **36.24** | LOSS (−9.91%) |")
A("| **Engine** | 2023-08-21 | 40.22 | **2023-10-13** | **35.44** | STOP_LOSS (−11.90%) |")
A("")
A("- Zone: `2022-04-01|39.0600|40.2400` (sheet band 39.05–40.24).")
A("- Signal / close-above: **2023-08-18** (engine `CLOSE_ABOVE_DATE`).")
A("- Yahoo signal Low: **39.815** → eng stop `39.815 × 0.89 = 35.44` (matches `STOP_PRICE`).")
A("- Sheet exit 36.24 ≈ `39.82 × 0.91` (or `39.815 × 0.91 = 36.23` with 1¢ GF/rounding).")
A("")
A("### Bar walk (engine OHLC)")
A("")
A("| Date | O | H | L | C | vs eng stop 35.44 | vs sheet stop ~36.24 |")
A("|---|---:|---:|---:|---:|---|---|")
A("| 2023-10-11 | 37.278 | 37.781 | 36.534 | 36.593 | no touch | no touch |")
A("| **2023-10-12** | 36.648 | 36.883 | **35.905** | 36.120 | L still **+0.47** above stop → **hold** | L **≤ 36.24** → **STOP @ 36.24** |")
A("| **2023-10-13** | 35.564 | 35.893 | **35.205** | 35.568 | L ≤ 35.44 → **STOP @ 35.44** (not gap: O>35.44) | already flat |")
A("")
A("### Rule checklist")
A("")
A("| Hypothesis | Verdict |")
A("|---|---|")
A("| `stop_pct` level (0.89 vs 0.91 on signal low) | **YES — root cause** |")
A("| Gap-down vs intraday stop priority | No — 10/13 is intraday STOP (O=35.56 > 35.44) |")
A("| Same-day stop-before-target | N/A (no target that day) |")
A("| `exit_at_close_when_stopped` | No — eng exits at stop px 35.44, not close 35.57 |")
A("| `stop_looking` / retest abandon | N/A (exit path, not retest scan) |")
A("| Entry×0.89 stop | No — entry×0.89=35.80; 10/12 L=35.905 still above; would gap 10/13 @ open |")
A("| OHLC paste / wrong ticker | No — entry open matches; unique NFLX path |")
A("")
A("### Which side matches sheet formula ground truth?")
A("")
A("- **Trade ledger behavior** (all MarkTen LOSS exits tested): **`stop = signal_low × 0.91`**, exit at that stop when Low touches — **sheet side**.")
A("- **Engine run + docs/status** assumed **`stop_pct=0.89`** — **engine is consistent with its own config**, but **not** with the pasted ledger.")
A("- **Recommendation:** treat sheet ledger as identity ground truth → set engine `-v stop_pct=0.91` and re-stamp; **or** if product policy is truly 11% (`0.89`), fix the sheet stop cell/formula to 0.89 and re-paste. **Do not** patch gap/close logic for this NFLX case.")
A("")
A("### Downstream SC fork (consequence, not separate root)")
A("")
A("| | Sheet | Engine (SC on) |")
A("|---|---|---|")
A("| Prior Aug exit | 10/12 | 10/13 |")
A("| SC rocket on 34.45–35.50 | 10/13 | blocked (still in Aug trade) |")
A("| SC fill | **2023-10-16 @ 35.62** | **2023-10-17 @ 36.11** |")
A("| SC exit | 2023-11-03 @ 43.46 TARGET | 2023-11-10 @ 44.05 TARGET |")
A("")
A("Fixing the Aug stop alignment is the prerequisite; the 10/16 vs 10/17 fill should collapse with it.")
A("")
A("---")
A("")
A("## 2. Full residual table (all 10 MarkTen)")
A("")
A("Perfect entry+exit date+price matches are omitted. Every row below is a **non-identity** residual.")
A("")
A("| Ticker | Mismatch type | Sheet | Engine | Suspected cause | Severity |")
A("|---|---|---|---|---|---|")

for m in inv["all_mismatches"]:
    sh = str(m["sheet"]).replace("|", "/")
    en = str(m["engine"]).replace("|", "/")
    cause = str(m["cause"]).replace("|", "/")
    A(f"| {m['ticker']} | {m['type']} | {sh} | {en} | {cause} | {m['severity']} |")

A("")
A("### Per-ticker scoreboard (this stamp)")
A("")
A("| Ticker | Sheet trades | Eng closed(+open) | Perfect matches | Residual rows |")
A("|---|---:|---:|---:|---:|")
for s in inv["per_symbol"]:
    A(f"| {s['ticker']} | {s['sheet_n']} | {s['eng_n']} | {s['perfect']} | {s['mismatch_n']} |")

A("")
A("Structure (pivots/zones/retest/rocket-where-sheet-fires) remains **matched** per status file; not re-listed as residuals here.")
A("")
A("---")
A("")
A("## 3. Root-cause clusters")
A("")

# Reclassify for clearer product clusters
cluster = Counter()
for m in inv["all_mismatches"]:
    t = m["type"]
    c = m["cause"]
    if t in ("exit_date_mismatch", "exit_price_mismatch") or "NFLX-class" in c or "gap vs" in c or "exit price" in c:
        if "TARGET" in str(m.get("engine", "")) and "LOSS" in str(m.get("sheet", "")):
            cluster["A. stop_pct 0.91 vs 0.89 (sheet early STOP; eng later continues to TARGET/GAP_UP)"] += 1
        elif "gap" in c.lower() or "GAP" in str(m.get("engine", "")):
            cluster["A. stop_pct 0.91 vs 0.89 (sheet early; eng later GAP/STOP) — includes gap-day presentation"] += 1
        else:
            cluster["A. stop_pct 0.91 vs 0.89 (sheet stop higher / earlier or same-day higher exit px)"] += 1
    elif t == "entry_date_off_by_session" or t == "exit_date_mismatch_on_near_pair":
        cluster["B. SC / occupancy fill lag secondary to prior exit fork"] += 1
    elif t == "sheet_only_trade":
        cluster["C. Sheet-only trades (SC/occupancy after divergent exits, or eng never filled)"] += 1
    elif t == "engine_only_trade":
        cluster["D. Engine-only trades (eng-only rockets, open trades, or cascade from stop fork)"] += 1
    else:
        cluster["E. Other"] += 1

A("| Cluster | Count (residual rows) | Notes |")
A("|---|---:|---|")
for k, v in cluster.most_common():
    A(f"| {k} | {v} | |")

A("")
A("### Evidence for cluster A (stop multiplier)")
A("")
A("- Among matched trades with exit-date mismatch: **39/39 sheet earlier**; **39/39** sheet exit px > eng `STOP_PRICE`.")
A("- Fit of sheet LOSS exit price to `signal_low × 0.91`: **46/50** within 3¢ (median abs err **0.002**); `×0.89` fits **0/50**.")
A("- Engine log explicitly: `stop_pct=0.89`.")
A("- Same-day STOP exits with sheet px > eng stop (META/NVDA/TSLA/AMD/NFLX examples) are the same level bug without a date shift.")
A("")
A("### Type counts (raw)")
A("")
A("| Type | Count |")
A("|---|---:|")
for k, v in sorted(inv["type_counts"].items(), key=lambda x: -x[1]):
    A(f"| {k} | {v} |")

A("")
A("---")
A("")
A("## 4. Ranked fixes for identity")
A("")
A("1. **Stop multiplier parity (blocks almost everything else)** — Confirm sheet stop parameter. If sheet is 0.91 multiplier on signal/trigger low → re-run MarkTen SC stamp with `-v stop_pct=0.91`. If policy is 0.89 → fix sheet and re-paste. Reconcile LOSS exits first.")
A("2. **Re-check NFLX Aug → SC 10/16** — After stop parity, expect sheet 10/12 and eng 10/12 (or both 10/13 if sheet moves to 0.89), and SC fill dates to align.")
A("3. **Cascade clean-up** — Re-inventory sheet-only / eng-only after (1); many are occupancy consequences of early sheet stops (or eng holding into TARGET).")
A("4. **Eng-only rockets / early window** — Remaining eng-only after stop fix (AAPL 2016–2018 rockets, open trades) need a separate pass (sheet paste coverage vs eng-only signal).")
A("5. **Do not** change gap/stop priority or `exit_at_close_when_stopped` for the NFLX Aug case — bar walk shows standard Low≤stop → exit at stop.")
A("")
A("---")
A("")
A("## Artifacts")
A("")
A("- Status: `VARIANT_C_SC_2016_MARKTEN_STATUS.md`")
A("- Prior NFLX SC deepdive: `NFLX/NFLX_trade_mismatch_deepdive.md` (SC lineage; exit fork left open — closed here)")
A("- Machine inventory: `_tmp_markten_mismatch_inv.json`")
A("- Helper scripts (ephemeral): `_tmp_markten_full_inv.py`, `_tmp_nflx_exit_walk.py`, `_tmp_stop_formula_rev.py`")
A("")
A("*Generated for identity reconcile vs stamp `260722145252`. No engine code changed.*")

out = BASE / "MARKTEN_SC_FULL_MISMATCH_INVENTORY.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote {out} ({len(lines)} lines)")
