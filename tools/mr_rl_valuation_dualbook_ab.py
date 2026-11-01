#!/usr/bin/env python3
"""MR AB #3 — Fund Valuation ≥60 dual-book on RL (research-only).

Control: full RL 40_30d Closed (tradable 764).
Single knob: keep symbols with fund scorecard Valuation pillar ≥ 60.
Scores = industry-peer stamp snapshot (contaminated / look-ahead labeled).

Usage:
  python tools/mr_rl_valuation_dualbook_ab.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from mr_ab_common import (  # noqa: E402
    PARENT_OUT,
    PARENT_STAMP,
    RL_40_30D_CLOSED,
    RL_CASH,
    SCORES_FALLBACK,
    SCORES_INDUSTRY,
    load_trades,
    overall_verdict,
    pack_overlay_arm,
    write_stamp_html,
    write_summary_md,
)

CHILD = "03_rl_valuation_dualbook"
OUT = PARENT_OUT / CHILD
THR = 60.0  # one threshold (report: ≥60 or ≥70 — pick one)


def load_scores() -> tuple[pd.DataFrame, Path]:
    path = SCORES_INDUSTRY if SCORES_INDUSTRY.is_file() else SCORES_FALLBACK
    if not path.is_file():
        raise SystemExit("Missing fund scorecard scores.csv")
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    return df.set_index("symbol", drop=False), path


def main() -> int:
    if not RL_40_30D_CLOSED.is_file():
        raise SystemExit(f"Missing RL Closed: {RL_40_30D_CLOSED}")
    OUT.mkdir(parents=True, exist_ok=True)

    scores, scores_path = load_scores()
    all_trades = load_trades(RL_40_30D_CLOSED)
    traded = {t["sym"] for t in all_trades}

    keep: set[str] = set()
    n_fail = n_miss = n_norow = 0
    for sym in traded:
        if sym not in scores.index:
            n_norow += 1
            continue
        val = scores.at[sym, "score_valuation"] if "score_valuation" in scores.columns else float("nan")
        try:
            v = float(val)
        except (TypeError, ValueError):
            v = float("nan")
        if not math.isfinite(v):
            n_miss += 1
            continue
        if v >= THR:
            keep.add(sym)
        else:
            n_fail += 1

    kept_trades = [t for t in all_trades if t["sym"] in keep]
    control = pack_overlay_arm("control", "control (full RL 40_30d)", all_trades, RL_CASH)
    control["cash"] = RL_CASH
    cand = pack_overlay_arm(
        "valuation_ge_60",
        f"Valuation ≥ {THR:.0f}",
        kept_trades,
        RL_CASH,
        extra={
            "n_keep_sym": len(keep),
            "n_fail": n_fail,
            "n_miss": n_miss,
            "n_norow": n_norow,
        },
    )
    # contamination ceiling: downgrade KEEP → LEAN KEEP
    tag, is_v, oos_v, note = overall_verdict(cand, control)
    if tag == "KEEP":
        tag = "LEAN KEEP"
        note += " (contamination ceiling — snapshot scores)"
    verdicts = {cand["id"]: (tag, is_v, oos_v, note)}
    arms = [control, cand]

    baseline = f"""# BASELINE — `{PARENT_STAMP}/{CHILD}`

**Status:** RESEARCH dual-book — not gold / not DailyRun.

## Hypothesis

Fundamental mean reversion (Valuation pillar) complements RL price-dip selection.
Restricting the book to Valuation ≥ {THR:.0f} improves quality vs the full RL book.

## Single knob

| Knob | Control | Candidate |
|------|---------|-----------|
| Valuation gate | none (full book) | keep symbols with **score_valuation ≥ {THR:.0f}** |

## Frozen control identity

| Knob | Value |
|------|-------|
| Source Closed | `{RL_40_30D_CLOSED.as_posix()}` |
| Exit freeze | `rl_exit_percent=0.40`, `rl_exit_days=30`, `rl_cut_the_losers=1000` |
| Entry freeze | dip 1.055 / expansion 1.163 / stop 0.934 / target 1.20 / too_high 0 |
| Scores | `{scores_path.as_posix()}` (point-in-time **snapshot** — contaminated overlay) |
| Cash | $47,500 |
| Split | IS entry < 2024-01-01; OOS report-only |

## Method honesty

- Snapshot scores applied to historical entries = **look-ahead / contaminated ceiling**.
- Missing Valuation → fail gate. OOS report-only; no retune. Max verdict LEAN KEEP.

## Coverage

- traded symbols: {len(traded)}
- pass ≥{THR:.0f}: {len(keep)}
- fail score: {n_fail}; missing score: {n_miss}; no score row: {n_norow}

## Verdict

See `SUMMARY.md` / `compare.html`.
"""
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    write_stamp_html(
        OUT,
        title="MR AB #3 — RL Fund Valuation ≥60 dual-book",
        meta=f"Stamp <code>{PARENT_STAMP}/{CHILD}</code> · dual-book · research-only",
        warn=(
            "<strong>Contaminated snapshot overlay.</strong> Valuation scores are a "
            "point-in-time stamp — treat as research upper-bound. OOS report-only. "
            "Not DailyRun."
        ),
        baseline_md_link="BASELINE.md",
        arms=arms,
        control=control,
        verdicts=verdicts,
        extra_html=(
            f'<div class="info">Symbols pass={len(keep)} / traded={len(traded)}; '
            f"trades kept={len(kept_trades)} / {len(all_trades)}. "
            f"Scores: <code>{scores_path.as_posix()}</code>.</div>"
        ),
    )
    write_summary_md(
        OUT,
        stamp=f"{PARENT_STAMP}/{CHILD}",
        hypothesis="Valuation≥60 dual-book improves RL quality vs full 40_30d book.",
        knob=f"score_valuation ≥ {THR:.0f}",
        control_id="RL 40_30d Closed 260831203843 (tradable 764)",
        arms=arms,
        verdicts=verdicts,
    )
    print(
        f"[mr_rl_val] done -> {OUT} overall={tag} "
        f"sym_pass={len(keep)}/{len(traded)} trades={len(kept_trades)}/{len(all_trades)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
