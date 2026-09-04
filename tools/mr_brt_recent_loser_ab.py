#!/usr/bin/env python3
"""MR AB #2 — BRT “recent loser” entry overlay (research-only).

Control: production BRT LatestRun Closed (`drive/BRT_LatestRun_Closed.csv`).
Single knob (report pick-one): require 21-day return < 0 on last daily bar before entry.
Frozen: all BRT DailyRun knobs from `run_brt.bat` (overlay only — no engine change).

Usage:
  python tools/mr_brt_recent_loser_ab.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mr_ab_common import (  # noqa: E402
    BRT_CASH,
    BRT_LATEST_CLOSED,
    PARENT_OUT,
    PARENT_STAMP,
    OhlcCache,
    load_trades,
    overall_verdict,
    pack_overlay_arm,
    ret_nd,
    write_stamp_html,
    write_summary_md,
)

CHILD = "02_brt_recent_loser"
OUT = PARENT_OUT / CHILD
RET_N = 21  # one knob: 21d return < 0


def main() -> int:
    if not BRT_LATEST_CLOSED.is_file():
        raise SystemExit(f"Missing BRT Closed: {BRT_LATEST_CLOSED}")
    OUT.mkdir(parents=True, exist_ok=True)

    all_trades = load_trades(BRT_LATEST_CLOSED)
    cache = OhlcCache()
    kept: list[dict] = []
    dropped = 0
    missing = 0
    gate_rows: list[dict[str, str]] = []

    for t in all_trades:
        sym, opened = t["sym"], t["opened"]
        i = cache.signal_idx(sym, opened)
        b = cache.bars(sym)
        r = float("nan")
        if b is not None and i is not None:
            r = ret_nd(b["close"], i, RET_N)
        pass_gate = r == r and r < 0.0
        gate_rows.append(
            {
                "SYMBOL": sym,
                "DATE_OPENED": opened.isoformat(),
                "RET_21D": f"{r:.6f}" if r == r else "",
                "PASS": "1" if pass_gate else "0",
            }
        )
        if b is None or i is None or r != r:
            missing += 1
            continue
        if pass_gate:
            kept.append(t)
        else:
            dropped += 1

    control = pack_overlay_arm("control", "control (full BRT LatestRun)", all_trades, BRT_CASH)
    control["cash"] = BRT_CASH
    cand = pack_overlay_arm(
        "ret21_lt_0",
        "21d return < 0 at signal bar",
        kept,
        BRT_CASH,
        extra={"n_dropped": dropped, "n_missing": missing},
    )
    arms = [control, cand]
    verdicts = {cand["id"]: overall_verdict(cand, control)}

    with (OUT / "gate_values.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["SYMBOL", "DATE_OPENED", "RET_21D", "PASS"])
        w.writeheader()
        w.writerows(gate_rows)

    baseline = f"""# BASELINE — `{PARENT_STAMP}/{CHILD}`

**Status:** RESEARCH overlay — not gold / not DailyRun.

## Hypothesis

BRT zone retest stays intact; requiring a **recent loser** (negative 21-day return) at the
signal bar adds short-term reversal flavor and avoids buying already-extended names.

## Single knob (picked from report menu)

| Knob | Control | Candidate |
|------|---------|-----------|
| Recent-loser gate | none | **21-day close-to-close return < 0** on last daily bar before `DATE_OPENED` |

Not tested here (explicitly deferred): Close z vs SMA20 < −1; RSI14 < 40.

## Frozen control identity (BRT DailyRun / `run_brt.bat`)

| Knob | Value |
|------|-------|
| Source Closed | `{BRT_LATEST_CLOSED.as_posix()}` |
| `stop_pct` | 0.934 |
| `target_pct` | 1.21 |
| `too_high_multiplier` | 0 |
| `band_pct` | 0.0154 |
| strong pre/post pivot | 0.1 / 0.1 · bars 7 / 7 |
| `breakout_bars` | 100 |
| tight range | thr 0.35 · lookback 105 |
| `brt_sheet_touch` | true |
| `sheet_red_to_green_entry_enabled` | true |
| `growth_filter_enabled` | true |
| `brt_zones` | true |
| Cash model | $47,500 |
| Split | IS entry < 2024-01-01; OOS report-only |

## Method honesty

- Overlay on realized Closed — not a live engine gate.
- One knob only. OOS report-only; no retune on OOS.

## Verdict

See `SUMMARY.md` / `compare.html`.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    write_stamp_html(
        OUT,
        title="MR AB #2 — BRT recent-loser (21d return < 0)",
        meta=f"Stamp <code>{PARENT_STAMP}/{CHILD}</code> · ENTRY overlay · research-only",
        warn=(
            "<strong>Research only.</strong> One knob: 21d return &lt; 0. "
            "Control = BRT LatestRun / DailyRun freeze. OOS report-only."
        ),
        baseline_md_link="BASELINE.md",
        arms=arms,
        control=control,
        verdicts=verdicts,
        extra_html=(
            f'<div class="info">Gate pass N={len(kept)} / {len(all_trades)} '
            f"(dropped={dropped}, missing={missing}). Detail: <code>gate_values.csv</code>.</div>"
        ),
    )
    write_summary_md(
        OUT,
        stamp=f"{PARENT_STAMP}/{CHILD}",
        hypothesis="Require 21d return < 0 at BRT signal bar to improve entry quality.",
        knob="21-day return < 0 (signal bar before entry)",
        control_id="BRT_LatestRun_Closed.csv (DailyRun freeze)",
        arms=arms,
        verdicts=verdicts,
    )
    tag = verdicts[cand["id"]][0]
    print(f"[mr_brt_ret21] done -> {OUT} overall={tag} kept={len(kept)}/{len(all_trades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
