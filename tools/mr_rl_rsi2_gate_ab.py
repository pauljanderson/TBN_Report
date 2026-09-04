#!/usr/bin/env python3
"""MR AB #1 — RL + RSI(2) oversold entry overlay (research-only).

Control: RL tradable 764 Closed under adopted prod freeze 40%+30d
  (`rl_entry_exit_ab_20260831/runs/40_30d`).
Single knob: keep trade if Wilder RSI(2) on last daily bar before DATE_OPENED < 10.
No engine rerun. Overlay timing = no look-ahead vs next-open fill.

Usage:
  python tools/mr_rl_rsi2_gate_ab.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mr_ab_common import (  # noqa: E402
    PARENT_OUT,
    PARENT_STAMP,
    RL_40_30D_CLOSED,
    RL_CASH,
    OhlcCache,
    load_trades,
    overall_verdict,
    pack_overlay_arm,
    write_stamp_html,
    write_summary_md,
)

CHILD = "01_rl_rsi2_gate"
OUT = PARENT_OUT / CHILD
RSI_K = 10.0  # one pre-agreed k (report: e.g. 10 or 5 — not a grid)


def main() -> int:
    if not RL_40_30D_CLOSED.is_file():
        raise SystemExit(f"Missing control Closed: {RL_40_30D_CLOSED}")
    OUT.mkdir(parents=True, exist_ok=True)

    all_trades = load_trades(RL_40_30D_CLOSED)
    cache = OhlcCache()
    kept: list[dict] = []
    dropped = 0
    missing = 0
    gate_rows: list[dict[str, str]] = []

    for t in all_trades:
        sym, opened = t["sym"], t["opened"]
        i = cache.signal_idx(sym, opened)
        b = cache.bars(sym)
        rsi = float("nan")
        if b is not None and i is not None and i >= 0:
            rsi = float(b["rsi2"][i])
        pass_gate = rsi == rsi and rsi < RSI_K  # finite and < k
        gate_rows.append(
            {
                "SYMBOL": sym,
                "DATE_OPENED": opened.isoformat(),
                "RSI2": f"{rsi:.4f}" if rsi == rsi else "",
                "PASS": "1" if pass_gate else "0",
            }
        )
        if b is None or i is None:
            missing += 1
            continue
        if pass_gate:
            kept.append(t)
        else:
            dropped += 1

    control = pack_overlay_arm("control", "control (full RL 40_30d book)", all_trades, RL_CASH)
    control["cash"] = RL_CASH
    cand = pack_overlay_arm(
        "rsi2_lt_10",
        f"RSI(2) < {RSI_K:.0f} at signal bar",
        kept,
        RL_CASH,
        extra={"n_dropped": dropped, "n_missing_ohlc": missing},
    )
    arms = [control, cand]
    verdicts = {cand["id"]: overall_verdict(cand, control)}

    with (OUT / "gate_values.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["SYMBOL", "DATE_OPENED", "RSI2", "PASS"])
        w.writeheader()
        w.writerows(gate_rows)

    baseline = f"""# BASELINE — `{PARENT_STAMP}/{CHILD}`

**Status:** RESEARCH overlay — not gold / not DailyRun.

## Hypothesis

RL is already MR-in-trend (SMA50 dip). Adding a Connors-style Relative Strength Index (RSI)(2)
oversold gate improves entry quality without changing stop/target/timed-exit identity.

## Single knob

| Knob | Control | Candidate |
|------|---------|-----------|
| RSI(2) gate | none (full book) | require Wilder RSI(2) **< {RSI_K:.0f}** on last daily bar **before** `DATE_OPENED` |

## Frozen control identity (prod RL as of 2026-09-03)

| Knob | Value |
|------|-------|
| Source Closed | `{RL_40_30D_CLOSED.as_posix()}` |
| Universe | tradable 764 (same Closed) |
| `rl_dip_pct` | 1.055 |
| `rl_expansion` | 1.163 |
| `rl_stop_pct` | 0.934 |
| `rl_target_pct` | 1.20 |
| `rl_too_high` | 0 (off) |
| `rl_cut_the_losers` | 1000 (OFF) |
| `rl_exit_percent` | **0.40** |
| `rl_exit_days` | **30** |
| Cash model | $47,500 |
| Split | IS entry < 2024-01-01; OOS report-only |

## Method honesty

- Overlay on realized Closed — **not** a live engine gate (capacity / sequencing unchanged for kept trades).
- RSI(2) = Wilder period 2 on daily closes; signal = last bar strictly before entry.
- One pre-agreed k=10 (report allowed 10 or 5 — **not** a grid). OOS report-only; no retune.

## Verdict

See `SUMMARY.md` / `compare.html`.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    write_stamp_html(
        OUT,
        title="MR AB #1 — RL + RSI(2)<10 oversold gate",
        meta=f"Stamp <code>{PARENT_STAMP}/{CHILD}</code> · ENTRY overlay · research-only",
        warn=(
            "<strong>Research only.</strong> One knob RSI(2)&lt;10 on signal bar. "
            "Control = prod RL freeze 40%+30d / cut OFF. OOS report-only — do not retune."
        ),
        baseline_md_link="BASELINE.md",
        arms=arms,
        control=control,
        verdicts=verdicts,
        extra_html=(
            f'<div class="info">Gate pass N={len(kept)} / {len(all_trades)} '
            f"(dropped={dropped}, missing OHLC/idx={missing}). "
            f'Detail: <code>gate_values.csv</code>.</div>'
        ),
    )
    write_summary_md(
        OUT,
        stamp=f"{PARENT_STAMP}/{CHILD}",
        hypothesis="RSI(2)<10 oversold gate improves RL entry quality vs full 40_30d book.",
        knob=f"RSI(2) < {RSI_K:.0f} on signal bar (Wilder)",
        control_id="RL 40_30d Closed 260831203843 (tradable 764)",
        arms=arms,
        verdicts=verdicts,
    )
    tag = verdicts[cand["id"]][0]
    print(f"[mr_rl_rsi2] done -> {OUT} overall={tag} kept={len(kept)}/{len(all_trades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
