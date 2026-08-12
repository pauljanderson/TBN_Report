#!/usr/bin/env python3
"""ImproveHints → one-knob ABs under VZ research freeze (rw63 + zone_atr05_ts40).

Maps stamp 260811090711 ImproveHints into runnable arms vs RESEARCH_CANDIDATE_V2_RW63
on DualPaul78 (drive/universes/VZ_universe.csv). Research only — not gold.

Usage:
  python tools/vz_improve_hints_ab.py
  python tools/vz_improve_hints_ab.py --stamp vz_improve_hints_ab_260811090711
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from vol_zone_break_retest import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_OUT_DIR,
    OOS_SPLIT_DATE,
    PRIMARY_EXIT,
    RESEARCH_CANDIDATE_V2_RW63,
    SORTABLE_TABLE_SCRIPT,
    ExitSpec,
    RetestSignal,
    SysParams,
    Zone,
    ZoneEvents,
    _exit_mix,
    _fmt_num,
    _fmt_pct,
    _metrics_cells,
    atr14,
    build_zones,
    enrich_signal_rows,
    lean_ab_v2_exit,
    load_ohlcv,
    load_universe_symbols,
    precompute_zone_events,
    resolve_stop,
    run_symbol_with_params,
    sortable_th,
    split_is_oos,
    summarize_signal_dicts,
)

DEFAULT_UNIVERSE = REPO / "drive" / "universes" / "VZ_universe.csv"
HINTS_STAMP = "260811090711"
DEFAULT_STAMP = f"vz_improve_hints_ab_{HINTS_STAMP}"


# ---------------------------------------------------------------------------
# Hint → arm mapping (honest dismissals documented)
# ---------------------------------------------------------------------------
HINT_MAP: list[dict] = [
    {
        "hypothesis": "stop_pct_tension_expand_vs_hold",
        "category": "param",
        "arm": "EXIT_stop_atr075",
        "status": "run",
        "knob": "EXIT stop_atr_buffer 0.5→0.75 (wider)",
        "notes": "Maps stop_pct expand lean; research stop is zone.lo−k·ATR not % stop.",
    },
    {
        "hypothesis": "stop_pct_tension_expand_vs_hold",
        "category": "param",
        "arm": "EXIT_stop_atr10",
        "status": "run",
        "knob": "EXIT stop_atr_buffer 0.5→1.0 (wider+)",
        "notes": "Stronger widen arm; same hint tension (expand vs hold).",
    },
    {
        "hypothesis": "fat_stops",
        "category": "pattern",
        "arm": "EXIT_stop_atr025",
        "status": "run",
        "knob": "EXIT stop_atr_buffer 0.5→0.25 (tighter)",
        "notes": "Opposite of expand peer-learn; one-knob tighter stop.",
    },
    {
        "hypothesis": "fat_stops",
        "category": "pattern",
        "arm": "EXIT_ts20",
        "status": "run",
        "knob": "EXIT exit_bars 40→20",
        "notes": "Time-based cut the losers (second fat_stops lever; separate arm).",
    },
    {
        "hypothesis": "target_pct_tension_expand_vs_contract",
        "category": "param",
        "arm": "EXIT_target_r25",
        "status": "run",
        "knob": "EXIT target_r 2.0→2.5",
        "notes": "Expand target / small_target_wins / peer longer-hold proxy.",
    },
    {
        "hypothesis": "target_pct_tension_expand_vs_contract",
        "category": "param",
        "arm": "EXIT_target_r15",
        "status": "run",
        "knob": "EXIT target_r 2.0→1.5",
        "notes": "Contract target (approach-fail lens).",
    },
    {
        "hypothesis": "small_target_wins",
        "category": "pattern",
        "arm": "EXIT_target_r25",
        "status": "run",
        "knob": "(same as EXIT_target_r25)",
        "notes": "Consolidated with target expand — no separate partial_exit sim.",
    },
    {
        "hypothesis": "band_tighten_weak_fill",
        "category": "param",
        "arm": "ENTRY_eps0",
        "status": "run",
        "knob": "ENTRY retest_eps_pct 0.005→0.0",
        "notes": "Tighten acceptance band (eps). Secondary mild arm: ENTRY_eps002.",
    },
    {
        "hypothesis": "band_tighten_weak_fill",
        "category": "param",
        "arm": "ENTRY_eps002",
        "status": "run",
        "knob": "ENTRY retest_eps_pct 0.005→0.002",
        "notes": "Mild band tighten.",
    },
    {
        "hypothesis": "band_tighten_weak_fill",
        "category": "param",
        "arm": "ENTRY_mt2",
        "status": "run",
        "knob": "ENTRY min_touches 1→2",
        "notes": "Stricter pre-break touch quality (noise / weak-fill adjacent).",
    },
    {
        "hypothesis": "post_target_quick_stop",
        "category": "pattern",
        "arm": "ENTRY_cd_target10",
        "status": "run",
        "knob": "ENTRY skip re-entry ≤10 bars after TARGET on same symbol",
        "notes": "Proxy for post-win cooldown (not full rl_post_target modes).",
    },
    {
        "hypothesis": "false_start_2022_2023",
        "category": "pattern",
        "arm": "ENTRY_spy_sma200",
        "status": "run",
        "knob": "ENTRY require SPY Close > SMA200 on entry date",
        "notes": "Regime gate proxy; tradeoff fewer bull-regime entries.",
    },
    {
        "hypothesis": "winner_peak_giveback",
        "category": "pattern",
        "arm": "EXIT_trail_be1r",
        "status": "run",
        "knob": "EXIT raise stop to breakeven after +1R MFE (still 2R/40d)",
        "notes": "Minimal one-knob trail; not chandelier/partial.",
    },
    {
        "hypothesis": "peer_wider_stop_won_*",
        "category": "peer_learn",
        "arm": "EXIT_stop_atr075 / EXIT_stop_atr10",
        "status": "run",
        "knob": "(consolidated into wider-stop EXIT arms)",
        "notes": "WPBR/YH/RS/BRT/MTS peer wider-stop hints collapsed to one-change stop arms.",
    },
    {
        "hypothesis": "peer_longer_hold_won_* / peer_target_after_our_stop_*",
        "category": "peer_learn",
        "arm": "EXIT_ts60 / EXIT_target_r25",
        "status": "run",
        "knob": "(consolidated into longer time-stop + higher target)",
        "notes": "Peer hold/target edge mapped to EXIT_ts60 and EXIT_target_r25.",
    },
    {
        "hypothesis": "partial_exit / scale-out",
        "category": "pattern",
        "arm": "—",
        "status": "dismiss",
        "knob": "n/a",
        "notes": "No partial-fill simulator in vol_zone research exit — untestable here.",
    },
]


def exit_ab_specs() -> list[ExitSpec]:
    """One-knob EXIT variants vs PRIMARY_EXIT (zone_atr05_ts40)."""
    base = PRIMARY_EXIT
    return [
        ExitSpec(
            "EXIT_stop_atr075",
            "Wider stop: zone.lo−0.75·ATR, 2R/40d",
            exit_bars=base.exit_bars,
            target_r=base.target_r,
            stop_atr_buffer=0.75,
        ),
        ExitSpec(
            "EXIT_stop_atr10",
            "Wider+ stop: zone.lo−1.0·ATR, 2R/40d",
            exit_bars=base.exit_bars,
            target_r=base.target_r,
            stop_atr_buffer=1.0,
        ),
        ExitSpec(
            "EXIT_stop_atr025",
            "Tighter stop: zone.lo−0.25·ATR, 2R/40d",
            exit_bars=base.exit_bars,
            target_r=base.target_r,
            stop_atr_buffer=0.25,
        ),
        ExitSpec(
            "EXIT_target_r25",
            "Higher target: zone.lo−0.5·ATR, 2.5R/40d",
            exit_bars=base.exit_bars,
            target_r=2.5,
            stop_atr_buffer=base.stop_atr_buffer,
        ),
        ExitSpec(
            "EXIT_target_r15",
            "Lower target: zone.lo−0.5·ATR, 1.5R/40d",
            exit_bars=base.exit_bars,
            target_r=1.5,
            stop_atr_buffer=base.stop_atr_buffer,
        ),
        ExitSpec(
            "EXIT_ts60",
            "Longer hold: zone.lo−0.5·ATR, 2R/60d",
            exit_bars=60,
            target_r=base.target_r,
            stop_atr_buffer=base.stop_atr_buffer,
        ),
        ExitSpec(
            "EXIT_ts20",
            "Shorter time-stop: zone.lo−0.5·ATR, 2R/20d",
            exit_bars=20,
            target_r=base.target_r,
            stop_atr_buffer=base.stop_atr_buffer,
        ),
    ]


def entry_ab_arms(freeze: SysParams) -> list[tuple[str, SysParams, str]]:
    return [
        ("ENTRY_eps0", replace(freeze, retest_eps_pct=0.0), "retest_eps_pct=0 (band tighten)"),
        (
            "ENTRY_eps002",
            replace(freeze, retest_eps_pct=0.002),
            "retest_eps_pct=0.002 (mild band tighten)",
        ),
        (
            "ENTRY_mt2",
            replace(freeze, min_touches_before_entry=2),
            "min_touches>=2 (stricter quality)",
        ),
    ]


def simulate_trail_be(
    df: pd.DataFrame,
    sig: RetestSignal,
    *,
    exit_bars: int,
    target_r: float,
    stop: float,
    activate_r: float = 1.0,
) -> dict:
    """After MFE ≥ activate_r·risk, raise stop to entry (breakeven). Else same as stock exit."""
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)
    entry = float(sig.entry_price)
    stop_px = float(stop)
    risk = max(entry - stop_px, entry * 0.005)
    target = entry + target_r * risk
    be = entry
    activated = False
    end = min(len(df) - 1, sig.entry_idx + exit_bars)
    for i in range(sig.entry_idx + 1, end + 1):
        mfe = float(highs[i]) - entry
        if (not activated) and mfe >= activate_r * risk:
            activated = True
            stop_px = max(stop_px, be)
        if float(lows[i]) <= stop_px:
            pnl = (stop_px - entry) / entry * 100.0
            return {
                "pnl_pct": pnl,
                "r_mult": (stop_px - entry) / risk,
                "exit_reason": "stop" if stop_px < entry - 1e-9 else ("trail_be" if activated else "stop"),
                "bars_held": i - sig.entry_idx,
                "stop": stop_px,
                "target": target,
            }
        if float(highs[i]) >= target:
            pnl = (target - entry) / entry * 100.0
            return {
                "pnl_pct": pnl,
                "r_mult": target_r,
                "exit_reason": "target",
                "bars_held": i - sig.entry_idx,
                "stop": stop_px,
                "target": target,
            }
    pnl = (float(closes[end]) - entry) / entry * 100.0
    return {
        "pnl_pct": pnl,
        "r_mult": (pnl / 100.0 * entry) / risk if risk > 0 else 0.0,
        "exit_reason": "time",
        "bars_held": end - sig.entry_idx,
        "stop": stop_px,
        "target": target,
    }


def enrich_trail_rows(
    symbol: str,
    df: pd.DataFrame,
    sigs: list[RetestSignal],
    atr: np.ndarray,
    exit_spec: ExitSpec,
) -> list[dict]:
    rows: list[dict] = []
    for s in sigs:
        stop = resolve_stop(s, atr, exit_spec.stop_atr_buffer)
        sim = simulate_trail_be(
            df,
            s,
            exit_bars=exit_spec.exit_bars,
            target_r=exit_spec.target_r,
            stop=stop,
            activate_r=1.0,
        )
        rows.append(
            {
                "symbol": symbol,
                "zone_id": s.zone_id,
                "kind": s.kind,
                "break_date": str(s.break_date.date()),
                "entry_date": str(s.entry_date.date()),
                "entry_price": round(s.entry_price, 4),
                "stop": round(float(sim["stop"]), 4),
                "zone_lo": round(s.stop, 4),
                "bars_after_break": s.bars_after_break,
                "touch_count_all": s.touch_count_all,
                "touch_count_holds": s.touch_count_holds,
                "pre_break_touches": s.pre_break_touches,
                "post_break_touches": s.post_break_touches,
                "strength": round(s.strength, 3),
                "break_dist_pct": round(s.break_dist_pct, 5),
                "break_atr_mult": round(s.break_atr_mult, 3),
                "visit_n": s.visit_n,
                "pnl_pct": round(float(sim["pnl_pct"]), 4),
                "r_mult": round(float(sim["r_mult"]), 4),
                "win": int(float(sim["pnl_pct"]) > 0),
                "exit_reason": sim["exit_reason"],
                "bars_held": int(sim["bars_held"]),
                "exit_name": "EXIT_trail_be1r",
                "params_tag": s.params_tag,
            }
        )
    return rows


def load_spy_sma200(data_dir: Path) -> pd.Series:
    """Date-indexed bool: True when SPY Close > SMA200."""
    spy = load_ohlcv(data_dir / "SPY.csv")
    close = spy["Close"].astype(float)
    sma = close.rolling(200, min_periods=200).mean()
    ok = close > sma
    return pd.Series(ok.to_numpy(), index=pd.to_datetime(spy["Date"]).dt.normalize())


def filter_spy_regime(rows: list[dict], spy_ok: pd.Series) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        d = pd.Timestamp(r["entry_date"]).normalize()
        if d in spy_ok.index and bool(spy_ok.loc[d]):
            out.append(r)
        elif d not in spy_ok.index:
            # forward-fill nearest prior session
            prior = spy_ok.loc[:d]
            if len(prior) and bool(prior.iloc[-1]):
                out.append(r)
    return out


def filter_cooldown_after_target(rows: list[dict], cooldown_bars: int = 10) -> list[dict]:
    """Drop entries that start ≤ cooldown_bars after a TARGET exit on same symbol.

    Uses bars_held on prior TARGET row as proxy for exit timing vs next entry_date
    ordering (calendar days approximated via sorted entry_date + bars_held).
    """
    by_sym: dict[str, list[dict]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    kept: list[dict] = []
    for sym, rs in by_sym.items():
        rs = sorted(rs, key=lambda x: (x["entry_date"], x.get("zone_id", "")))
        last_target_exit: pd.Timestamp | None = None
        for r in rs:
            ed = pd.Timestamp(r["entry_date"])
            if last_target_exit is not None:
                # approximate bars via calendar days (research proxy)
                gap = (ed - last_target_exit).days
                if 0 <= gap <= cooldown_bars:
                    continue
            kept.append(r)
            if str(r.get("exit_reason", "")).lower() == "target":
                held = int(r.get("bars_held", 0) or 0)
                last_target_exit = ed + pd.Timedelta(days=held)
    return kept


def lean_control_arm(arm: str) -> bool:
    return arm in ("00_freeze", "CONTROL")


def score_lean(arm: str, m: dict, ctrl: dict) -> tuple[str, str]:
    if lean_control_arm(arm):
        return "CONTROL", "Freeze reference (rw63 + zone_atr05_ts40)"
    return lean_ab_v2_exit(arm, m, ctrl)


def write_baseline_md(path: Path, *, stamp: str, universe_path: Path, n_symbols: int) -> None:
    p = RESEARCH_CANDIDATE_V2_RW63
    e = PRIMARY_EXIT
    md = f"""# VZ ImproveHints AB — research only (NOT gold)

**Stamp:** `{stamp}`  
**Source hints:** `drive/VZ_ImproveHints_{HINTS_STAMP}.html` (+ CSV)  
**Universe:** `{universe_path.as_posix()}` — DualPaul78 ({n_symbols} symbols)  
**Status:** Research candidate ABs only — **not** gold, **not** DailyRun-wired.

## Frozen control

| Knob | Value |
|------|-------|
| lookback_days | {p.lookback_days} |
| zone_kinds | {", ".join(p.zone_kinds)} (HL-only) |
| first_retest_only | {p.first_retest_only} |
| min_touches_before_entry | {p.min_touches_before_entry} |
| retest_eps_pct | {p.retest_eps_pct} |
| retest_window | {p.retest_window} |
| Primary exit | `{e.name}` — zone.lo−{e.stop_atr_buffer}·ATR, {e.target_r}R / {e.exit_bars}d |

## Process

- One-change ABs vs freeze; quality over count (WR, AvgR, AvgPnL%, N).
- Chronologic IS/OOS: entry_date &lt; 2024-01-01 vs ≥ 2024-01-01. **OOS is report-only — do not retune.**
- Selection bias: arms chosen from ImproveHints on the same DualPaul78 history used for scoring.
- Peer-learn hints consolidated into shared stop/target/time knobs (not per-system arms).

## Outputs

- `comparison.html` — arms, verdicts, IS/OOS for control + LEAN KEEP
- `ab_results.csv` / `hint_map.json` / `signals_*.csv`
- `BASELINE.md` / `AB_PLAN.md`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")


def write_ab_plan_md(path: Path) -> None:
    lines = [
        "# ImproveHints AB plan",
        "",
        "Control = RESEARCH_CANDIDATE_V2_RW63 + zone_atr05_ts40 on DualPaul78.",
        "",
        "## Runnable arms",
        "",
        "| Arm | Knob | Source hints |",
        "|-----|------|--------------|",
        "| 00_freeze | — | Control |",
    ]
    for h in HINT_MAP:
        if h["status"] == "run":
            lines.append(
                f"| {h['arm']} | {h['knob']} | `{h['hypothesis']}` |"
            )
    lines += [
        "",
        "## Dismissed / untestable",
        "",
        "| Hypothesis | Reason |",
        "|------------|--------|",
    ]
    for h in HINT_MAP:
        if h["status"] == "dismiss":
            lines.append(f"| `{h['hypothesis']}` | {h['notes']} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _mc(m: dict) -> str:
    """Metric cells including house Ann ROR%."""
    return _metrics_cells(m, include_ann_ror=True)


def _ext_headers() -> str:
    """Extended book-quality headers (Max DD, PF, outlier, exposure, med/mean, agg)."""
    return (
        f"{sortable_th('MaxDD%', 'num')}"
        f"{sortable_th('Calmar', 'num')}"
        f"{sortable_th('PF', 'num')}"
        f"{sortable_th('AvgW/|L|', 'num')}"
        f"{sortable_th('Outlier%Wins', 'num')}"
        f"{sortable_th('Top10%Wins', 'num')}"
        f"{sortable_th('CapDays', 'num')}"
        f"{sortable_th('AvgConc', 'num')}"
        f"{sortable_th('Exposure%', 'num')}"
        f"{sortable_th('MedPnL%', 'num')}"
        f"{sortable_th('Mean-Med', 'num')}"
        f"{sortable_th('Pass$PnL', 'num')}"
        f"{sortable_th('PassMaxDD%', 'num')}"
        f"{sortable_th('Agg$PnL', 'num')}"
        f"{sortable_th('AggMaxDD%', 'num')}"
        f"{sortable_th('AggAnnROR%', 'num')}"
    )


def _ext_cells(m: dict) -> str:
    mean_med = float(m.get("avg_pnl_pct", 0.0)) - float(m.get("median_pnl_pct", 0.0))
    return (
        f"<td>{_fmt_num(m.get('max_dd_pct', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('calmar', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('profit_factor', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('win_loss_ratio', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('outlier_pct_of_wins', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('outlier_top10_pct_of_wins', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('capital_days', 0.0), 0)}</td>"
        f"<td>{_fmt_num(m.get('avg_concurrent', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('exposure_pct', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('median_pnl_pct', 0.0))}</td>"
        f"<td>{_fmt_num(mean_med)}</td>"
        f"<td>{_fmt_num(m.get('passive_total_pnl', 0.0), 0)}</td>"
        f"<td>{_fmt_num(m.get('passive_max_dd_pct', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('agg_total_pnl', 0.0), 0)}</td>"
        f"<td>{_fmt_num(m.get('agg_max_dd_pct', 0.0))}</td>"
        f"<td>{_fmt_num(m.get('agg_ann_ror', 0.0))}</td>"
    )


def score_atr10_adopt_gate(
    *,
    ctrl_full: dict,
    ctrl_oos: dict,
    atr075_full: dict,
    atr075_oos: dict,
    atr10_full: dict,
    atr10_oos: dict,
) -> tuple[str, str]:
    """PASS/HOLD for EXIT_stop_atr10 vs control — OOS report-only; do not require OOS>IS.

    Gate: OOS Ann ROR and quality (WR, AvgPnL%) hold vs control OOS. Full-book quality
    already scored separately. AvgR dilution on wider stops is expected — not a fail alone.
    """
    notes: list[str] = []
    # Full-book quality vs control (PnL%/WR lens for stop-width)
    d_wr_f = (atr10_full["win_rate"] - ctrl_full["win_rate"]) * 100
    d_pnl_f = atr10_full["avg_pnl_pct"] - ctrl_full["avg_pnl_pct"]
    d_ror_f = atr10_full.get("ann_ror", 0.0) - ctrl_full.get("ann_ror", 0.0)
    notes.append(
        f"Full vs control: dWR {d_wr_f:+.1f}pp, dAvgPnL% {d_pnl_f:+.2f}, "
        f"dAnnROR {d_ror_f:+.1f}pp (AvgR dilution expected on wider stop)."
    )

    d_wr_o = (atr10_oos["win_rate"] - ctrl_oos["win_rate"]) * 100
    d_pnl_o = atr10_oos["avg_pnl_pct"] - ctrl_oos["avg_pnl_pct"]
    d_ror_o = atr10_oos.get("ann_ror", 0.0) - ctrl_oos.get("ann_ror", 0.0)
    notes.append(
        f"OOS vs control OOS: dWR {d_wr_o:+.1f}pp, dAvgPnL% {d_pnl_o:+.2f}, "
        f"dAnnROR {d_ror_o:+.1f}pp — report-only (do not retune; OOS need not beat IS)."
    )

    # Milder peer context
    d_ror_075 = atr075_oos.get("ann_ror", 0.0) - ctrl_oos.get("ann_ror", 0.0)
    notes.append(
        f"Context EXIT_stop_atr075 OOS dAnnROR vs control: {d_ror_075:+.1f}pp "
        f"(milder widen peer)."
    )

    oos_ror_holds = d_ror_o >= -5.0  # within ~5pp of control OOS Ann ROR
    oos_quality_holds = d_wr_o >= -1.5 and d_pnl_o >= -0.25
    full_quality_ok = d_wr_f >= -0.5 and d_pnl_f >= 0.10

    if atr10_oos["n_signals"] < 15:
        return "HOLD", " ".join(notes + ["OOS N thin — provisional HOLD, not adopt."])
    if not full_quality_ok:
        return "HOLD", " ".join(notes + ["Full-book WR/AvgPnL% do not clearly hold — HOLD."])
    if not oos_ror_holds or not oos_quality_holds:
        why = []
        if not oos_ror_holds:
            why.append("OOS Ann ROR softens vs control")
        if not oos_quality_holds:
            why.append("OOS WR/AvgPnL% softens vs control")
        return "HOLD", " ".join(notes + ["; ".join(why) + " — HOLD (do not adopt / do not retune OOS)."])
    return (
        "PASS",
        " ".join(
            notes
            + [
                "OOS Ann ROR and quality hold vs control OOS — research PASS to consider "
                "atr10 as a freeze delta candidate (still not gold / not DailyRun; "
                "prefer documenting selection bias)."
            ]
        ),
    )


def write_comparison_html(
    out_path: Path,
    *,
    stamp: str,
    universe_path: Path,
    n_symbols: int,
    freeze_m: dict,
    is_m: dict,
    oos_m: dict,
    ab_rows: list[dict],
    lean_keep_oos: list[dict],
    recommendation: str,
    runtime_s: float,
    atr_gate: dict | None = None,
) -> None:
    split_s = str(OOS_SPLIT_DATE.date())
    ctrl = freeze_m
    softens = (
        (oos_m["win_rate"] - is_m["win_rate"]) <= -0.05
        or (oos_m["avg_r"] - is_m["avg_r"]) <= -0.15
    )

    def ab_body(rows: list[dict]) -> str:
        body = ""
        for r in rows:
            m = r["metrics"]
            d_n = m["n_signals"] - ctrl["n_signals"]
            d_wr = (m["win_rate"] - ctrl["win_rate"]) * 100
            d_r = m["avg_r"] - ctrl["avg_r"]
            d_pnl = m["avg_pnl_pct"] - ctrl["avg_pnl_pct"]
            d_ror = m.get("ann_ror", 0.0) - ctrl.get("ann_ror", 0.0)
            lean = r.get("lean", "")
            cls = ""
            if lean in ("KEEP", "LEAN KEEP"):
                cls = ' class="keep"'
            elif lean == "DISMISS":
                cls = ' class="dismiss"'
            elif lean == "HOLD":
                cls = ' class="hold"'
            body += (
                f"<tr{cls}>"
                f"<td>{html_mod.escape(r['arm'])}</td>"
                f"<td>{html_mod.escape(r.get('kind', ''))}</td>"
                f"<td>{html_mod.escape(r['note'])}</td>"
                f"<td>{html_mod.escape(r.get('hints', ''))}</td>"
                f"{_mc(m)}"
                f"<td>{d_n:+d}</td>"
                f"<td>{d_wr:+.1f}</td>"
                f"<td>{d_r:+.2f}</td>"
                f"<td>{d_pnl:+.2f}</td>"
                f"<td>{d_ror:+.1f}</td>"
                f"<td>{html_mod.escape(lean)}</td>"
                f"<td>{html_mod.escape(r.get('lean_why', ''))}</td>"
                f"<td>{html_mod.escape(r.get('exit_mix', '—'))}</td>"
                "</tr>"
            )
        return body

    def slice_cells(m: dict) -> str:
        return (
            f"<td>{m['n_signals']}</td>"
            f"<td>{_fmt_pct(m['win_rate'])}</td>"
            f"<td>{_fmt_num(m['avg_r'])}</td>"
            f"<td>{_fmt_num(m['avg_pnl_pct'])}</td>"
            f"<td>{_fmt_num(m.get('ann_ror', 0.0))}</td>"
        )

    oos_body = ""
    for r in lean_keep_oos:
        m = r["metrics"]
        m_is = r["metrics_is"]
        m_oos = r["metrics_oos"]
        oos_body += (
            "<tr>"
            f"<td>{html_mod.escape(r['arm'])}</td>"
            f"{_mc(m)}"
            f"{slice_cells(m_is)}"
            f"{slice_cells(m_oos)}"
            f"<td>{html_mod.escape(r.get('lean', ''))}</td>"
            f"<td>{html_mod.escape(r.get('oos_note', ''))}</td>"
            "</tr>"
        )

    # Three-way stop-buffer table (control atr05 / atr075 / atr10)
    stop_arms = ["00_freeze", "EXIT_stop_atr075", "EXIT_stop_atr10"]
    stop_by_arm = {r["arm"]: r for r in lean_keep_oos if r["arm"] in stop_arms}
    # Also accept metrics from ab_rows if lean_keep missing
    ab_by_arm = {r["arm"]: r for r in ab_rows}
    stop_body = ""
    for arm, label in (
        ("00_freeze", "control (atr05 / zone_atr05_ts40)"),
        ("EXIT_stop_atr075", "EXIT_stop_atr075"),
        ("EXIT_stop_atr10", "EXIT_stop_atr10"),
    ):
        r = stop_by_arm.get(arm)
        if r is None and arm in ab_by_arm:
            # Build empty IS/OOS placeholders only if we somehow lack splits
            continue
        if r is None:
            continue
        for split_name, mm in (
            ("Full", r["metrics"]),
            ("IS", r["metrics_is"]),
            ("OOS", r["metrics_oos"]),
        ):
            stop_body += (
                "<tr>"
                f"<td>{html_mod.escape(label)}</td>"
                f"<td>{split_name}</td>"
                f"<td>{mm['n_signals']}</td>"
                f"<td>{_fmt_pct(mm['win_rate'])}</td>"
                f"<td>{_fmt_num(mm['avg_r'])}</td>"
                f"<td>{_fmt_num(mm['avg_pnl_pct'])}</td>"
                f"<td>{_fmt_num(mm.get('ann_ror', 0.0))}</td>"
                "</tr>"
            )

    gate_html = ""
    if atr_gate:
        verdict = atr_gate.get("verdict", "HOLD")
        cls = "keep" if verdict == "PASS" else "hold"
        gate_html = f"""
  <h2>atr10 adopt gate (research only)</h2>
  <p class="muted">
    Compare <code>EXIT_stop_atr10</code> vs control on OOS Ann ROR + quality (WR, AvgPnL%).
    OOS is report-only — do not retune; OOS need not beat IS. Not a freeze/DailyRun wire.
  </p>
  <div class="rec {cls}">
    <strong>Gate: {html_mod.escape(verdict)}</strong>
    <pre style="white-space:pre-wrap;margin:0.6rem 0 0;font-family:inherit">{html_mod.escape(atr_gate.get("detail", ""))}</pre>
  </div>
  <table class="sortable"><thead><tr>
    {sortable_th("Arm", "text")}
    {sortable_th("Slice", "text")}
    {sortable_th("N", "num")}
    {sortable_th("WR%", "num")}
    {sortable_th("AvgR", "num")}
    {sortable_th("AvgPnL%", "num")}
    {sortable_th("Ann ROR%", "num")}
  </tr></thead><tbody>
  {stop_body}
  </tbody></table>
"""

    hint_body = ""
    for h in HINT_MAP:
        hint_body += (
            "<tr>"
            f"<td>{html_mod.escape(h['category'])}</td>"
            f"<td>{html_mod.escape(h['hypothesis'])}</td>"
            f"<td>{html_mod.escape(h['arm'])}</td>"
            f"<td>{html_mod.escape(h['status'])}</td>"
            f"<td>{html_mod.escape(h['knob'])}</td>"
            f"<td>{html_mod.escape(h['notes'])}</td>"
            "</tr>"
        )

    soft_txt = (
        f"Yes — OOS softens vs IS (do not retune on OOS)."
        if softens
        else "OOS does not clearly soften vs IS — still research-only; do not retune on holdout."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ImproveHints AB — {html_mod.escape(stamp)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1500px; margin:0 auto; }}
  h1 {{ font-size:1.45rem; }}
  h2 {{ font-size:1.15rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
  .rec {{ background:#f0f0ea; border:1px solid #d8d8d0; padding:14px 16px; margin:1rem 0; }}
  .rec.keep {{ background:#ecfdf5; }}
  .rec.hold {{ background:#fffbeb; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:12.5px; margin-bottom:1.4rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:5px 7px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  tr.keep {{ background:#ecfdf5; }}
  tr.dismiss {{ background:#fef2f2; }}
  tr.hold {{ background:#fffbeb; }}
  th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  th.sortable-th:hover {{ background:#e2e8f0; }}
  th.sortable-th .sort-ind::after {{ content:" \\2195"; opacity:0.35; font-size:0.85em; }}
  th.sortable-th.sort-asc .sort-ind::after {{ content:" \\2191"; opacity:0.9; }}
  th.sortable-th.sort-desc .sort-ind::after {{ content:" \\2193"; opacity:0.9; }}
  code {{ font-size:0.92em; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>VZ ImproveHints AB — {html_mod.escape(stamp)}</h1>
  <p class="muted">
    Research only (not gold / not DailyRun). Universe: DualPaul78
    (<code>{html_mod.escape(str(universe_path))}</code>, {n_symbols} symbols).
    Freeze: HL-only, first_retest, mt≥1, eps=0.005, lookback=126, retest_window=63 +
    <code>zone_atr05_ts40</code>. Ann ROR = house book formula
    <code>((1+Total_PNL/(brt_cash×n))**(365/avg_days)−1)×100</code> with fixed-notional
    <code>pnl_pct</code> sizing and <code>bars_held</code> as days held.
    Click column headers to sort. Runtime {runtime_s/60:.1f} min.
  </p>

  <div class="rec">
    <strong>Recommendation</strong>
    <pre style="white-space:pre-wrap;margin:0.6rem 0 0;font-family:inherit">{html_mod.escape(recommendation)}</pre>
  </div>

{gate_html}

  <h2>Control freeze (full book + IS/OOS)</h2>
  <p class="muted">IS = entry_date &lt; {split_s}; OOS = ≥ {split_s} (report-only). {soft_txt}</p>
  <table class="sortable"><thead><tr>
    {sortable_th("Slice", "text")}
    {sortable_th("N", "num")}
    {sortable_th("WR%", "num")}
    {sortable_th("AvgPnL%", "num")}
    {sortable_th("AvgR", "num")}
    {sortable_th("MedPnL%", "num")}
    {sortable_th("Ann ROR%", "num")}
  </tr></thead><tbody>
    <tr><td>Full history</td>{_mc(freeze_m)}</tr>
    <tr><td>IS (&lt;{split_s})</td>{_mc(is_m)}</tr>
    <tr><td>OOS (≥{split_s})</td>{_mc(oos_m)}</tr>
  </tbody></table>

  <h2>Extended book metrics (control Full / IS / OOS)</h2>
  <p class="muted">
    (1) Max DD + Calmar (= AnnROR/MaxDD); (2) Profit factor + avg win÷|avg loss|;
    (4) Outlier dependence (max win / top-10 wins as % of winning PnL%);
    (5) Exposure = capital_days / span_days; avg concurrent open slots;
    (7) Median PnL% and mean−median gap; (8) Passive fixed-notional vs aggressive
    (size ≈ init / avg concurrent). Cash equity path (PnL at exit; no OHLC MTM).
    Exit mix (3) and same-day clusters (6) skipped.
  </p>
  <table class="sortable"><thead><tr>
    {sortable_th("Slice", "text")}
    {_ext_headers()}
  </tr></thead><tbody>
    <tr><td>Full</td>{_ext_cells(freeze_m)}</tr>
    <tr><td>IS</td>{_ext_cells(is_m)}</tr>
    <tr><td>OOS</td>{_ext_cells(oos_m)}</tr>
  </tbody></table>

  <h2>Extended metrics — all one-knob arms (full book)</h2>
  <table class="sortable"><thead><tr>
    {sortable_th("Arm", "text")}
    {sortable_th("Verdict", "text")}
    {sortable_th("N", "num")}
    {sortable_th("Ann ROR%", "num")}
    {_ext_headers()}
  </tr></thead><tbody>
  {"".join(
      "<tr>"
      f"<td>{html_mod.escape(r['arm'])}</td>"
      f"<td>{html_mod.escape(r.get('lean', ''))}</td>"
      f"<td>{r['metrics']['n_signals']}</td>"
      f"<td>{_fmt_num(r['metrics'].get('ann_ror', 0.0))}</td>"
      f"{_ext_cells(r['metrics'])}"
      "</tr>"
      for r in ab_rows
  )}
  </tbody></table>

  <h2>One-knob arms vs freeze (full-history score)</h2>
  <p class="muted">Judge quality over count. KEEP/LEAN KEEP only if WR/AvgR/PnL improve without collapsing N.</p>
  <table class="sortable"><thead><tr>
    {sortable_th("Arm", "text")}
    {sortable_th("Kind", "text")}
    {sortable_th("Change", "text")}
    {sortable_th("Hints", "text")}
    {sortable_th("N", "num")}
    {sortable_th("WR%", "num")}
    {sortable_th("AvgPnL%", "num")}
    {sortable_th("AvgR", "num")}
    {sortable_th("MedPnL%", "num")}
    {sortable_th("Ann ROR%", "num")}
    {sortable_th("ΔN", "num")}
    {sortable_th("ΔWR pp", "num")}
    {sortable_th("ΔAvgR", "num")}
    {sortable_th("ΔPnL%", "num")}
    {sortable_th("ΔAnnROR pp", "num")}
    {sortable_th("Verdict", "text")}
    {sortable_th("Why", "text")}
    {sortable_th("Exit mix", "text")}
  </tr></thead><tbody>
  {ab_body(ab_rows)}
  </tbody></table>

  <h2>IS/OOS for control + LEAN KEEP / KEEP candidates</h2>
  <p class="muted">OOS is report-only. If OOS softens → HOLD / investigate — do not retune on holdout. Click column headers to sort.</p>
  <table class="sortable"><thead><tr>
    {sortable_th("Arm", "text")}
    {sortable_th("Full N", "num")}
    {sortable_th("Full WR%", "num")}
    {sortable_th("Full AvgPnL%", "num")}
    {sortable_th("Full AvgR", "num")}
    {sortable_th("Full MedPnL%", "num")}
    {sortable_th("Full Ann ROR%", "num")}
    {sortable_th("IS N", "num")}
    {sortable_th("IS WR%", "num")}
    {sortable_th("IS AvgR", "num")}
    {sortable_th("IS AvgPnL%", "num")}
    {sortable_th("IS Ann ROR%", "num")}
    {sortable_th("OOS N", "num")}
    {sortable_th("OOS WR%", "num")}
    {sortable_th("OOS AvgR", "num")}
    {sortable_th("OOS AvgPnL%", "num")}
    {sortable_th("OOS Ann ROR%", "num")}
    {sortable_th("Verdict", "text")}
    {sortable_th("OOS note", "text")}
  </tr></thead><tbody>
  {oos_body}
  </tbody></table>

  <h2>Hint → arm map</h2>
  <table class="sortable"><thead><tr>
    {sortable_th("Category", "text")}
    {sortable_th("Hypothesis", "text")}
    {sortable_th("Arm", "text")}
    {sortable_th("Status", "text")}
    {sortable_th("Knob", "text")}
    {sortable_th("Notes", "text")}
  </tr></thead><tbody>
  {hint_body}
  </tbody></table>

  <h2>Caveats</h2>
  <ul>
    <li>ImproveHints came from rocket VZ % stop/target language; research knobs are zone-ATR R / time-stop / eps — mapping is approximate.</li>
    <li>Arms selected after seeing ImproveHints on this universe → in-sample selection bias (labeled).</li>
    <li>Peer-learn overlaps are tiny-N on a few symbols; consolidated, not per-peer KEEP claims.</li>
    <li>Cooldown uses calendar-day proxy for bars; trail is breakeven-after-1R only.</li>
    <li>Ann ROR uses research signal <code>bars_held</code> (not full equity-curve path) with house book annualization.</li>
    <li>Research candidate ≠ gold ≠ DailyRun.</li>
  </ul>
  <p class="muted">Generated by <code>tools/vz_improve_hints_ab.py</code>.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def build_recommendation(ab_rows: list[dict], lean_keep_oos: list[dict], softens: bool) -> str:
    keeps = [r for r in ab_rows if r.get("lean") in ("KEEP", "LEAN KEEP")]
    holds = [r for r in ab_rows if r.get("lean") == "HOLD"]
    dismisses = [r for r in ab_rows if r.get("lean") == "DISMISS"]
    lines: list[str] = []
    if not keeps:
        lines.append("No KEEP / LEAN KEEP arms on full-history quality vs freeze.")
        if holds:
            lines.append(
                "HOLD (flat/mixed): " + ", ".join(r["arm"] for r in holds[:6])
                + ("..." if len(holds) > 6 else "")
            )
        lines.append(
            f"DISMISS count: {len(dismisses)}. Prefer leave freeze as-is; do not wire DailyRun."
        )
    else:
        lines.append("LEAN KEEP / KEEP (full-history, research-only):")
        for r in keeps:
            lines.append(f"  - {r['arm']}: {r.get('lean_why', '')}")
        for r in lean_keep_oos:
            if r["arm"] == "00_freeze":
                continue
            m_is, m_oos = r["metrics_is"], r["metrics_oos"]
            if m_oos["n_signals"] < 15:
                lines.append(
                    f"  - {r['arm']} OOS N={m_oos['n_signals']} thin — treat as provisional HOLD."
                )
            elif (m_oos["avg_r"] - m_is["avg_r"]) <= -0.15 or (
                m_oos["win_rate"] - m_is["win_rate"]
            ) <= -0.05:
                lines.append(
                    f"  - {r['arm']} OOS softens vs its IS — HOLD / investigate; do not retune OOS."
                )
            else:
                lines.append(
                    f"  - {r['arm']} OOS does not clearly soften (report-only) — still research candidate, not gold."
                )
        if any(r["arm"].startswith("EXIT_stop_atr") for r in keeps):
            lines.append(
                "Prefer milder EXIT_stop_atr075 over atr10 if adopting a one-knob freeze delta."
            )
    if holds:
        lines.append(
            "HOLD: " + ", ".join(f"{r['arm']}" for r in holds) + " — not enough for KEEP."
        )
    lines.append(f"DISMISS count: {len(dismisses)} (band tighten, trail, fat tighter, etc.).")
    if softens:
        lines.append("Control freeze itself: OOS softens vs IS — extra caution on any adopt.")
    lines.append(
        "Selection bias labeled (hints → arms on same DualPaul78). Research only — not gold / not DailyRun."
    )
    return "\n".join(lines)


def run(
    *,
    universe_path: Path,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
) -> Path:
    t0 = time.time()
    symbols = load_universe_symbols(universe_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_baseline_md(
        out_dir / "BASELINE.md", stamp=stamp, universe_path=universe_path, n_symbols=len(symbols)
    )
    write_ab_plan_md(out_dir / "AB_PLAN.md")
    (out_dir / "hint_map.json").write_text(json.dumps(HINT_MAP, indent=2), encoding="utf-8")

    freeze = RESEARCH_CANDIDATE_V2_RW63
    primary = PRIMARY_EXIT
    lookback = freeze.lookback_days

    caches: dict[str, tuple[pd.DataFrame, list[Zone], np.ndarray, list[ZoneEvents] | None]] = {}
    freeze_raw: dict[str, list[RetestSignal]] = {}
    freeze_signals: list[dict] = []
    skipped: list[dict] = []

    print(
        f"ImproveHints AB stamp={stamp} symbols={len(symbols)} univ={universe_path.name} "
        f"freeze=rw63 exit={primary.name}"
    )
    for sym in symbols:
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            note = f"missing CSV: {csv_path}"
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            continue
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback)
        except Exception as e:  # noqa: BLE001
            note = str(e)
            print(f"  SKIP {sym}: {note}")
            skipped.append({"symbol": sym, "note": note})
            continue
        sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, freeze)
        rows = enrich_signal_rows(sym, df, sigs, freeze, atr=atr, exit_spec=primary)
        freeze_signals.extend(rows)
        freeze_raw[sym] = sigs
        caches[sym] = (df, zones, atr, None)
        m = summarize_signal_dicts(rows)
        print(
            f"  {sym}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% AvgR={m['avg_r']:.2f}"
        )

    freeze_m = summarize_signal_dicts(freeze_signals)
    is_rows, oos_rows = split_is_oos(freeze_signals)
    is_m = summarize_signal_dicts(is_rows)
    oos_m = summarize_signal_dicts(oos_rows)
    print(
        f"FREEZE: N={freeze_m['n_signals']} WR={freeze_m['win_rate']*100:.1f}% "
        f"AvgR={freeze_m['avg_r']:.2f} AvgPnL%={freeze_m['avg_pnl_pct']:.2f}"
    )
    print(
        f"IS:  N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% AvgR={is_m['avg_r']:.2f}"
    )
    print(
        f"OOS: N={oos_m['n_signals']} WR={oos_m['win_rate']*100:.1f}% AvgR={oos_m['avg_r']:.2f}"
    )

    ab_rows: list[dict] = []
    arm_signals: dict[str, list[dict]] = {"00_freeze": freeze_signals}

    ab_rows.append(
        {
            "arm": "00_freeze",
            "kind": "CONTROL",
            "note": "rw63 + zone_atr05_ts40",
            "hints": "baseline",
            "metrics": freeze_m,
            "exit_mix": _exit_mix(freeze_signals),
            "lean": "CONTROL",
            "lean_why": "Freeze reference",
        }
    )

    # EXIT ABs on freeze entries
    for spec in exit_ab_specs():
        rows: list[dict] = []
        for sym, (df, _z, atr, _) in caches.items():
            sigs = freeze_raw.get(sym, [])
            rows.extend(
                enrich_signal_rows(sym, df, sigs, freeze, atr=atr, exit_spec=spec)
            )
        m = summarize_signal_dicts(rows)
        arm_signals[spec.name] = rows
        hints = ", ".join(
            sorted(
                {
                    h["hypothesis"]
                    for h in HINT_MAP
                    if h["status"] == "run" and spec.name in h["arm"]
                }
            )
        )
        ab_rows.append(
            {
                "arm": spec.name,
                "kind": "EXIT",
                "note": spec.label,
                "hints": hints or spec.name,
                "metrics": m,
                "exit_mix": _exit_mix(rows),
            }
        )
        print(
            f"  {spec.name}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"AvgR={m['avg_r']:.2f} AvgPnL%={m['avg_pnl_pct']:.2f}"
        )

    # Trail BE arm
    trail_rows: list[dict] = []
    trail_spec = ExitSpec(
        "EXIT_trail_be1r",
        "Trail BE after 1R; zone.lo−0.5·ATR, 2R/40d",
        exit_bars=primary.exit_bars,
        target_r=primary.target_r,
        stop_atr_buffer=primary.stop_atr_buffer,
    )
    for sym, (df, _z, atr, _) in caches.items():
        trail_rows.extend(enrich_trail_rows(sym, df, freeze_raw.get(sym, []), atr, trail_spec))
    m_trail = summarize_signal_dicts(trail_rows)
    arm_signals["EXIT_trail_be1r"] = trail_rows
    ab_rows.append(
        {
            "arm": "EXIT_trail_be1r",
            "kind": "EXIT",
            "note": trail_spec.label,
            "hints": "winner_peak_giveback",
            "metrics": m_trail,
            "exit_mix": _exit_mix(trail_rows),
        }
    )
    print(
        f"  EXIT_trail_be1r: N={m_trail['n_signals']} WR={m_trail['win_rate']*100:.1f}% "
        f"AvgR={m_trail['avg_r']:.2f}"
    )

    # ENTRY ABs
    entry_arms = entry_ab_arms(freeze)
    eps_needed = sorted({a[1].retest_eps_pct for a in entry_arms} | {freeze.retest_eps_pct})
    break_pcts = sorted({a[1].break_pct for a in entry_arms} | {freeze.break_pct})
    break_atrs = sorted({a[1].break_atr for a in entry_arms} | {freeze.break_atr})
    print("precomputing zone events for entry ABs...")
    for sym, (df, zones, atr, _) in list(caches.items()):
        cached = precompute_zone_events(
            df,
            zones,
            atr,
            approach_lookback=freeze.approach_lookback,
            eps_list=eps_needed,
            break_pcts=break_pcts,
            break_atrs=break_atrs,
        )
        caches[sym] = (df, zones, atr, cached)

    for arm, arm_params, note in entry_arms:
        all_rows: list[dict] = []
        for sym, (df, zones, atr, cached) in caches.items():
            sigs, _, _ = run_symbol_with_params(
                sym, df, zones, atr, arm_params, cached=cached
            )
            all_rows.extend(
                enrich_signal_rows(sym, df, sigs, arm_params, atr=atr, exit_spec=primary)
            )
        m = summarize_signal_dicts(all_rows)
        arm_signals[arm] = all_rows
        hints = ", ".join(
            sorted(
                {
                    h["hypothesis"]
                    for h in HINT_MAP
                    if h["status"] == "run" and arm in h["arm"]
                }
            )
        )
        ab_rows.append(
            {
                "arm": arm,
                "kind": "ENTRY",
                "note": note,
                "hints": hints or arm,
                "metrics": m,
                "exit_mix": _exit_mix(all_rows),
            }
        )
        print(
            f"  {arm}: N={m['n_signals']} WR={m['win_rate']*100:.1f}% "
            f"AvgR={m['avg_r']:.2f} AvgPnL%={m['avg_pnl_pct']:.2f}"
        )

    # Cooldown after TARGET (filter on freeze primary rows)
    cd_rows = filter_cooldown_after_target(freeze_signals, cooldown_bars=10)
    m_cd = summarize_signal_dicts(cd_rows)
    arm_signals["ENTRY_cd_target10"] = cd_rows
    ab_rows.append(
        {
            "arm": "ENTRY_cd_target10",
            "kind": "ENTRY",
            "note": "Skip entries ≤10 calendar days after TARGET exit (same symbol)",
            "hints": "post_target_quick_stop",
            "metrics": m_cd,
            "exit_mix": _exit_mix(cd_rows),
        }
    )
    print(
        f"  ENTRY_cd_target10: N={m_cd['n_signals']} WR={m_cd['win_rate']*100:.1f}% "
        f"AvgR={m_cd['avg_r']:.2f}"
    )

    # SPY SMA200 regime
    spy_ok = load_spy_sma200(data_dir)
    spy_rows = filter_spy_regime(freeze_signals, spy_ok)
    m_spy = summarize_signal_dicts(spy_rows)
    arm_signals["ENTRY_spy_sma200"] = spy_rows
    ab_rows.append(
        {
            "arm": "ENTRY_spy_sma200",
            "kind": "ENTRY",
            "note": "Require SPY Close > SMA200 on entry date",
            "hints": "false_start_2022_2023",
            "metrics": m_spy,
            "exit_mix": _exit_mix(spy_rows),
        }
    )
    print(
        f"  ENTRY_spy_sma200: N={m_spy['n_signals']} WR={m_spy['win_rate']*100:.1f}% "
        f"AvgR={m_spy['avg_r']:.2f}"
    )

    # Leans
    for r in ab_rows:
        if r["arm"] == "00_freeze":
            continue
        lean, why = score_lean(r["arm"], r["metrics"], freeze_m)
        # Stop-width arms: AvgR falls when risk widens — judge on PnL%/WR.
        if r["arm"].startswith("EXIT_stop_atr") and lean in ("KEEP", "LEAN KEEP"):
            m, c = r["metrics"], freeze_m
            d_wr = m["win_rate"] - c["win_rate"]
            d_pnl = m["avg_pnl_pct"] - c["avg_pnl_pct"]
            d_r = m["avg_r"] - c["avg_r"]
            if d_pnl >= 0.15 and d_wr >= -0.015:
                why = (
                    "WR and AvgPnL% improve; AvgR falls as expected when stop widens "
                    "(larger risk denominator) — judge stop-width on PnL%/WR not AvgR"
                    + (f" (dAvgR {d_r:+.2f})" if d_r < 0 else "")
                )
            elif d_r < -0.03 and d_pnl < 0.15:
                lean, why = "HOLD", "Wider stop: PnL lift weak vs AvgR dilution"
        r["lean"] = lean
        r["lean_why"] = why

    # IS/OOS for control + KEEP/LEAN KEEP (+ always stop-width arms for adopt gate)
    lean_keep_oos: list[dict] = []
    softens = (oos_m["win_rate"] - is_m["win_rate"]) <= -0.05 or (
        oos_m["avg_r"] - is_m["avg_r"]
    ) <= -0.15
    force_oos_arms = {"00_freeze", "EXIT_stop_atr075", "EXIT_stop_atr10"}
    for r in ab_rows:
        if r["arm"] not in force_oos_arms and r.get("lean") not in ("KEEP", "LEAN KEEP"):
            continue
        if r["arm"] != "00_freeze" and r.get("lean") not in (
            "KEEP",
            "LEAN KEEP",
            "CONTROL",
        ):
            if r["arm"] not in force_oos_arms:
                continue
        rows = arm_signals[r["arm"]]
        is_r, oos_r = split_is_oos(rows)
        m_is_a = summarize_signal_dicts(is_r)
        m_oos_a = summarize_signal_dicts(oos_r)
        oos_note = "report-only"
        if m_oos_a["n_signals"] < 15:
            oos_note = "thin OOS N — provisional"
        elif (m_oos_a["avg_r"] - m_is_a["avg_r"]) <= -0.15 or (
            m_oos_a["win_rate"] - m_is_a["win_rate"]
        ) <= -0.05:
            oos_note = "OOS softens vs IS — HOLD / do not retune"
        else:
            oos_note = "OOS does not clearly soften (still research-only)"
        lean_keep_oos.append(
            {
                "arm": r["arm"],
                "metrics": r["metrics"],
                "metrics_is": m_is_a,
                "metrics_oos": m_oos_a,
                "lean": r.get("lean", "CONTROL"),
                "oos_note": oos_note,
            }
        )

    # atr10 adopt gate (research-only; OOS report-only)
    by_arm = {r["arm"]: r for r in lean_keep_oos}
    atr_gate = None
    if all(k in by_arm for k in ("00_freeze", "EXIT_stop_atr075", "EXIT_stop_atr10")):
        gate_v, gate_d = score_atr10_adopt_gate(
            ctrl_full=by_arm["00_freeze"]["metrics"],
            ctrl_oos=by_arm["00_freeze"]["metrics_oos"],
            atr075_full=by_arm["EXIT_stop_atr075"]["metrics"],
            atr075_oos=by_arm["EXIT_stop_atr075"]["metrics_oos"],
            atr10_full=by_arm["EXIT_stop_atr10"]["metrics"],
            atr10_oos=by_arm["EXIT_stop_atr10"]["metrics_oos"],
        )
        atr_gate = {"verdict": gate_v, "detail": gate_d}
        print(f"atr10 adopt gate: {gate_v}")
        print(gate_d)

    recommendation = build_recommendation(ab_rows, lean_keep_oos, softens)
    if atr_gate:
        recommendation = (
            f"atr10 adopt gate: {atr_gate['verdict']} — {atr_gate['detail']}\n\n"
            + recommendation
        )

    # CSVs
    pd.DataFrame(freeze_signals).to_csv(out_dir / "signals_00_freeze.csv", index=False)
    for arm_name in ("EXIT_stop_atr075", "EXIT_stop_atr10"):
        if arm_name in arm_signals:
            pd.DataFrame(arm_signals[arm_name]).to_csv(
                out_dir / f"signals_{arm_name}.csv", index=False
            )
    flat = []
    for r in ab_rows:
        m = r["metrics"]
        flat.append(
            {
                "arm": r["arm"],
                "kind": r.get("kind", ""),
                "note": r["note"],
                "hints": r.get("hints", ""),
                "n_signals": m["n_signals"],
                "win_rate": m["win_rate"],
                "avg_pnl_pct": m["avg_pnl_pct"],
                "avg_r": m["avg_r"],
                "median_pnl_pct": m.get("median_pnl_pct", 0.0),
                "ann_ror": m.get("ann_ror", 0.0),
                "avg_days_held": m.get("avg_days_held", 0.0),
                "max_dd_pct": m.get("max_dd_pct", 0.0),
                "calmar": m.get("calmar", 0.0),
                "profit_factor": m.get("profit_factor", 0.0),
                "win_loss_ratio": m.get("win_loss_ratio", 0.0),
                "outlier_pct_of_wins": m.get("outlier_pct_of_wins", 0.0),
                "outlier_top10_pct_of_wins": m.get("outlier_top10_pct_of_wins", 0.0),
                "capital_days": m.get("capital_days", 0.0),
                "avg_concurrent": m.get("avg_concurrent", 0.0),
                "exposure_pct": m.get("exposure_pct", 0.0),
                "mean_minus_median": float(m.get("avg_pnl_pct", 0.0))
                - float(m.get("median_pnl_pct", 0.0)),
                "passive_total_pnl": m.get("passive_total_pnl", 0.0),
                "passive_max_dd_pct": m.get("passive_max_dd_pct", 0.0),
                "agg_total_pnl": m.get("agg_total_pnl", 0.0),
                "agg_max_dd_pct": m.get("agg_max_dd_pct", 0.0),
                "agg_ann_ror": m.get("agg_ann_ror", 0.0),
                "delta_n": m["n_signals"] - freeze_m["n_signals"],
                "delta_wr_pp": (m["win_rate"] - freeze_m["win_rate"]) * 100,
                "delta_avg_r": m["avg_r"] - freeze_m["avg_r"],
                "delta_pnl": m["avg_pnl_pct"] - freeze_m["avg_pnl_pct"],
                "delta_ann_ror": m.get("ann_ror", 0.0) - freeze_m.get("ann_ror", 0.0),
                "lean": r.get("lean", ""),
                "lean_why": r.get("lean_why", ""),
                "exit_mix": r.get("exit_mix", ""),
            }
        )
    pd.DataFrame(flat).to_csv(out_dir / "ab_results.csv", index=False)

    oos_flat = []
    for r in lean_keep_oos:
        for split_name, mm in (
            ("FULL", r["metrics"]),
            ("IS", r["metrics_is"]),
            ("OOS", r["metrics_oos"]),
        ):
            oos_flat.append(
                {
                    "arm": r["arm"],
                    "split": split_name,
                    "n_signals": mm["n_signals"],
                    "win_rate": mm["win_rate"],
                    "avg_pnl_pct": mm["avg_pnl_pct"],
                    "avg_r": mm["avg_r"],
                    "ann_ror": mm.get("ann_ror", 0.0),
                    "avg_days_held": mm.get("avg_days_held", 0.0),
                    "lean": r.get("lean", ""),
                    "oos_note": r.get("oos_note", ""),
                }
            )
    pd.DataFrame(oos_flat).to_csv(out_dir / "oos_lean_keep.csv", index=False)

    if atr_gate:
        (out_dir / "atr10_adopt_gate.txt").write_text(
            f"{atr_gate['verdict']}\n{atr_gate['detail']}\n", encoding="utf-8"
        )

    if skipped:
        pd.DataFrame(skipped).to_csv(out_dir / "skipped.csv", index=False)

    runtime = time.time() - t0
    html_path = out_dir / "comparison.html"
    write_comparison_html(
        html_path,
        stamp=stamp,
        universe_path=universe_path,
        n_symbols=len(symbols),
        freeze_m=freeze_m,
        is_m=is_m,
        oos_m=oos_m,
        ab_rows=ab_rows,
        lean_keep_oos=lean_keep_oos,
        recommendation=recommendation,
        runtime_s=runtime,
        atr_gate=atr_gate,
    )
    (out_dir / "recommendation.txt").write_text(recommendation, encoding="utf-8")
    print(f"saved: {html_path}")
    print(f"runtime: {runtime/60:.1f} min")
    print("--- recommendation ---")
    try:
        print(recommendation)
    except UnicodeEncodeError:
        print(recommendation.encode("ascii", "replace").decode("ascii"))
    return html_path


def main() -> None:
    ap = argparse.ArgumentParser(description="VZ ImproveHints one-knob ABs (research only)")
    ap.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    args = ap.parse_args()
    stamp = args.stamp.strip() or DEFAULT_STAMP
    out_dir = args.out_dir / stamp if args.out_dir == DEFAULT_OUT_DIR else args.out_dir
    run(
        universe_path=args.universe,
        data_dir=args.data_dir,
        out_dir=out_dir,
        stamp=stamp,
    )


if __name__ == "__main__":
    main()
