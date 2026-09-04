#!/usr/bin/env python3
"""MOM walk-forward validation + multi-universe confirmation (frozen knobs).

Validation only — knobs frozen a priori from ``mom_baseline_liquid_20260829``.
No retune / no fold-based selection. Research candidate ≠ gold ≠ DailyRun.

Usage:
  python tools/mom_walkforward_multiuniv.py
  python tools/mom_walkforward_multiuniv.py --end 2026-08-28
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
_TOOLS = _REPO / "tools"
for _p in (_PE, _TOOLS, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import DEFAULT_INITIAL_ACCOUNT, is_excluded_html_compare_label  # noqa: E402
from mom_clenow_ab import (  # noqa: E402
    INDEX_SYM,
    IS_CUT,
    SORT_JS,
    SORTABLE_TH_CSS,
    _fmt_metric,
    _sortable_th,
    equity_slice_metrics,
    load_panel,
    load_universe,
    pack_metrics,
    run_backtest,
    trade_metrics,
    write_stamp,
)

STAMP = "mom_walkforward_multiuniv_20260829"
OUT_DIR = _PE / STAMP
DEFAULT_DB = _REPO / "data" / "ohlcv.duckdb"

UNIV_ADV2M = _REPO / "drive" / "universes" / "MOM_universe.csv"
UNIV_ADV5M = _REPO / "drive" / "universes" / "MOM_universe_adv5m.csv"
UNIV_PT = _REPO / "drive" / "universes" / "PaulTwenty_universe.csv"

# Validation WF folds (biennial test windows). Knobs frozen — no train/select.
# 2010–2013 = warm-up / book build before first reported fold.
WF_FOLDS: list[tuple[str, date, date]] = [
    ("2014-15", date(2014, 1, 1), date(2015, 12, 31)),
    ("2016-17", date(2016, 1, 1), date(2017, 12, 31)),
    ("2018-19", date(2018, 1, 1), date(2019, 12, 31)),
    ("2020-21", date(2020, 1, 1), date(2021, 12, 31)),
    ("2022-23", date(2022, 1, 1), date(2023, 12, 31)),
    ("2024-26", date(2024, 1, 1), date(2026, 12, 31)),  # clipped to data end in slice
]


def _fold_metrics(result: dict[str, Any], fold_label: str, start: date, end: date) -> dict[str, Any]:
    """OOS-style metrics on a continuous frozen-knob book for one calendar fold."""
    trades = result["trades"]
    eq_df = pd.DataFrame(result["equity"])
    eq_df["d"] = pd.to_datetime(eq_df["date"]).dt.date
    data_end = eq_df["d"].iloc[-1]
    fold_end = min(end, data_end)
    eq_m = equity_slice_metrics(eq_df, start, fold_end, fold_label)
    fold_trades = [t for t in trades if start <= t.entry_date <= fold_end]
    tm = trade_metrics(fold_trades)
    return {
        "fold": fold_label,
        "start": start.isoformat(),
        "end": fold_end.isoformat(),
        "ann_ror": eq_m.get("ann_ror"),
        "max_dd": eq_m.get("max_dd"),
        "total_ret_pct": eq_m.get("total_ret_pct"),
        "sharpe": eq_m.get("sharpe"),
        "calmar": eq_m.get("calmar"),
        "n_days": eq_m.get("n_days"),
        "n": tm.get("n"),
        "win_rate": tm.get("win_rate"),
        "avg_pnl_pct": tm.get("avg_pnl_pct"),
        "avg_days": tm.get("avg_days"),
        "profit_factor": tm.get("profit_factor"),
    }


def _arm_row(label: str, note: str, univ_n: int, pack: dict[str, Any], path: str) -> dict[str, Any]:
    return {
        "label": label,
        "note": note,
        "path": path,
        "n_univ": univ_n,
        "full_ann_ror": pack["full_m"].get("ann_ror"),
        "full_max_dd": pack["full_m"].get("max_dd"),
        "full_calmar": pack["full_m"].get("calmar"),
        "full_sharpe": pack["full_m"].get("sharpe"),
        "full_n": pack["tm_all"].get("n"),
        "full_wr": pack["tm_all"].get("win_rate"),
        "full_avg_pnl": pack["tm_all"].get("avg_pnl_pct"),
        "full_pf": pack["tm_all"].get("profit_factor"),
        "full_avg_days": pack["tm_all"].get("avg_days"),
        "is_ann_ror": pack["is_m"].get("ann_ror"),
        "is_max_dd": pack["is_m"].get("max_dd"),
        "is_n": pack["tm_is"].get("n"),
        "is_wr": pack["tm_is"].get("win_rate"),
        "is_avg_pnl": pack["tm_is"].get("avg_pnl_pct"),
        "is_pf": pack["tm_is"].get("profit_factor"),
        "oos_ann_ror": pack["oos_m"].get("ann_ror"),
        "oos_max_dd": pack["oos_m"].get("max_dd"),
        "oos_n": pack["tm_oos"].get("n"),
        "oos_wr": pack["tm_oos"].get("win_rate"),
        "oos_avg_pnl": pack["tm_oos"].get("avg_pnl_pct"),
        "oos_pf": pack["tm_oos"].get("profit_factor"),
    }


def _verdict(arms: list[dict[str, Any]], folds: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Honest research verdict — never gold. No fold used to pick knobs."""
    notes: list[str] = []
    ctrl = next((a for a in arms if a["label"] == "ADV$2m"), None)
    adv5 = next((a for a in arms if a["label"] == "ADV$5m"), None)
    pt = next((a for a in arms if a["label"] == "PaulTwenty"), None)

    if not ctrl:
        return "HOLD", ["Missing control arm."]

    # WF robustness: count folds with positive Ann ROR and Avg PnL%
    finite_folds = [f for f in folds if np.isfinite(float(f.get("ann_ror") or float("nan")))]
    pos_ror = sum(1 for f in finite_folds if float(f["ann_ror"]) > 0)
    pos_pnl = sum(
        1
        for f in finite_folds
        if np.isfinite(float(f.get("avg_pnl_pct") or float("nan"))) and float(f["avg_pnl_pct"]) > 0
    )
    notes.append(
        f"WF (continuous path): {pos_ror}/{len(finite_folds)} folds Ann ROR>0; "
        f"{pos_pnl}/{len(finite_folds)} folds Avg PnL%>0."
    )

    # Soft folds (negative Ann ROR or Avg PnL)
    soft = [
        f["fold"]
        for f in finite_folds
        if float(f["ann_ror"]) <= 0
        or (
            np.isfinite(float(f.get("avg_pnl_pct") or float("nan")))
            and float(f["avg_pnl_pct"]) <= 0
        )
    ]
    if soft:
        notes.append(f"Soft / weak folds: {', '.join(soft)}.")

    # Multi-univ: ADV$5m should not collapse quality vs control
    if adv5:
        is_ok = float(adv5["is_ann_ror"] or float("nan")) >= float(ctrl["is_ann_ror"] or 0) * 0.85
        oos_ok = float(adv5["oos_ann_ror"] or float("nan")) >= float(ctrl["oos_ann_ror"] or 0) * 0.85
        notes.append(
            f"ADV$5m vs control: IS Ann ROR {_fmt_metric(adv5['is_ann_ror'])} vs "
            f"{_fmt_metric(ctrl['is_ann_ror'])}; OOS {_fmt_metric(adv5['oos_ann_ror'])} vs "
            f"{_fmt_metric(ctrl['oos_ann_ror'])} "
            f"({'similar' if is_ok and oos_ok else 'diverges'})."
        )

    if pt:
        notes.append(
            f"PaulTwenty sensitivity only (N={pt['n_univ']} mega-caps; wrong shape for Clenow top-20% "
            f"rank book): full Ann ROR {_fmt_metric(pt['full_ann_ror'])}, "
            f"Avg PnL% {_fmt_metric(pt['full_avg_pnl'])}."
        )

    notes.append(
        "Blocker unchanged: static liquid tape — not point-in-time (PIT) S&P 500 membership "
        "(survivorship / membership bias vs classic Clenow)."
    )
    notes.append("No fold or universe arm used to retune knobs (validation only).")

    # Verdict ladder
    wf_ok = len(finite_folds) >= 4 and pos_ror >= max(3, len(finite_folds) - 2)
    oos_ctrl = float(ctrl["oos_ann_ror"] or float("nan"))
    is_ctrl = float(ctrl["is_ann_ror"] or float("nan"))
    oos_holds = np.isfinite(oos_ctrl) and oos_ctrl > 0
    multi_ok = True
    if adv5:
        multi_ok = (
            np.isfinite(float(adv5["is_ann_ror"] or float("nan")))
            and float(adv5["is_ann_ror"]) > 0
            and np.isfinite(float(adv5["oos_ann_ror"] or float("nan")))
            and float(adv5["oos_ann_ror"]) > 0
        )

    if soft and len(soft) >= 3:
        verdict = "HOLD — needs PIT S&P / more evidence"
        notes.append("Multiple weak folds → not closer to gold; HOLD.")
    elif wf_ok and oos_holds and multi_ok and np.isfinite(is_ctrl) and is_ctrl > 0:
        verdict = "LEAN KEEP research"
        notes.append(
            "Closer to gold bar than baseline alone (WF + multi-univ positive), "
            "but still research-only — PIT S&P / walk-forward gold bar not met."
        )
    elif oos_holds and wf_ok:
        verdict = "LEAN KEEP research"
        notes.append("WF mostly positive and OOS holds; multi-univ / PIT still gate gold.")
    else:
        verdict = "HOLD — needs PIT S&P / more evidence"
        notes.append("Robustness incomplete → HOLD vs stronger claim.")

    return verdict, notes


def write_report(
    out: Path,
    *,
    folds: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    verdict: str,
    verdict_notes: list[str],
    control_result: dict[str, Any],
    end: Optional[date],
) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    stamp = out.name

    # Persist fold + arm tables
    folds_path = out / "wf_folds.csv"
    pd.DataFrame(folds).to_csv(folds_path, index=False)
    written.append(folds_path)
    arms_path = out / "multiuniv_arms.csv"
    pd.DataFrame(arms).to_csv(arms_path, index=False)
    written.append(arms_path)

    meta = {
        "stamp": stamp,
        "kind": "validation_wf_plus_multiuniv",
        "knobs_frozen": True,
        "selection_bias": "none — no fold/univ used to pick knobs",
        "is_cut": IS_CUT.isoformat(),
        "end": end.isoformat() if end else None,
        "verdict": verdict,
        "verdict_notes": verdict_notes,
        "folds": folds,
        "arms": arms,
        "control_calendar": {
            "start": str(control_result.get("calendar_start")),
            "end": str(control_result.get("calendar_end")),
            "n_reviews": control_result.get("n_reviews"),
            "n_trades": len(control_result.get("trades") or []),
        },
    }
    mj = out / "metrics.json"
    mj.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    written.append(mj)

    fold_md = "\n".join(
        f"| {f['fold']} | {f['start']} | {f['end']} | {_fmt_metric(f['ann_ror'])} | "
        f"{_fmt_metric(f['max_dd'])} | {_fmt_metric(f['avg_pnl_pct'])} | "
        f"{_fmt_metric(f['profit_factor'])} | {f['n']} | {_fmt_metric(f['win_rate'])} |"
        for f in folds
    )
    arm_md = "\n".join(
        f"| {a['label']} | {a['n_univ']} | {_fmt_metric(a['is_ann_ror'])} | "
        f"{_fmt_metric(a['is_avg_pnl'])} | {_fmt_metric(a['is_pf'])} | {a['is_n']} | "
        f"{_fmt_metric(a['oos_ann_ror'])} | {_fmt_metric(a['oos_avg_pnl'])} | "
        f"{_fmt_metric(a['oos_pf'])} | {a['oos_n']} | {a['note']} |"
        for a in arms
    )

    baseline = f"""# BASELINE — `{stamp}`

**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.**

**Parent freeze:** `mom_baseline_liquid_20260829` — MOM (Momentum) Clenow knobs **frozen a priori**.
This stamp is a **validation** walk-forward + multi-universe confirmation. **No retune.**

## Knob freeze (do not change)

Inherited from `tools/mom_clenow_ab.py` / liquid baseline:

- Momentum lookback 90d · stock SMA100 entry/exit · SPY SMA200 regime · ATR20 · risk 0.001
- Gap filter 15% / 90d · top 20% · Wednesday review · resize every other review · 10 bps slip
- IS/OOS cut default: entry/equity `< 2024-01-01` vs `≥ 2024-01-01` (report-only)

## Part A — Walk-forward design (validation, not selection)

- **Method:** one continuous ADV$2m book with frozen knobs; report equity + trade metrics on successive **test windows**.
- **No train/select step** — knobs already frozen; folds are robustness checks only.
- **If any fold were used to pick knobs/exits → selection bias** — we did **not**.
- **Warm-up:** 2010 through ~2013 builds indicators / book before first reported fold (2014–15).
- **Alternative considered:** annual OOS slices after warm-up — biennial windows preferred for Clenow weekly turnover (~2y ≈ meaningful regime sample without over-fragmenting N).
- **Independent fold restarts** (cash reset each window) not primary — would discard path-dependent sizing; continuous-path slices match live book continuity.

### Suggested folds (used)

| Fold | Start | End |
|------|-------|-----|
| 2014-15 | 2014-01-01 | 2015-12-31 |
| 2016-17 | 2016-01-01 | 2017-12-31 |
| 2018-19 | 2018-01-01 | 2019-12-31 |
| 2020-21 | 2020-01-01 | 2021-12-31 |
| 2022-23 | 2022-01-01 | 2023-12-31 |
| 2024-26 | 2024-01-01 | data end |

## Part B — Multi-universe (one knob = universe)

| Arm | File | Role |
|-----|------|------|
| ADV$2m | `drive/universes/MOM_universe.csv` | Control (VZ tradable ADV$2m liquid) |
| ADV$5m | `drive/universes/MOM_universe_adv5m.csv` | Honest liquid lift (same methodology, higher ADV$) |
| PaulTwenty | `drive/universes/PaulTwenty_universe.csv` | **Sensitivity only** — tiny mega-cap book; wrong shape for Clenow top-20% rank |

**Not used as primary:** `RL_universe.csv` (59) — wrong-shape / production RL sleeve; would add noise without Clenow-relevant breadth.

**Survivorship:** all arms are **static membership** lists (as-of liquid cuts / curated lists), **not** point-in-time S&P 500. Documented blocker vs classic Clenow.

## How to re-run

```bash
python tools/mom_walkforward_multiuniv.py --out drive/paul_experiments/{stamp} --end 2026-08-28
```

## Promotion

Research candidate ≠ gold ≠ DailyRun. WF + multi-univ help the gold **bar** but do **not** by themselves promote.
"""
    bp = out / "BASELINE.md"
    bp.write_text(baseline, encoding="utf-8")
    written.append(bp)

    notes_md = "\n".join(f"- {n}" for n in verdict_notes)
    summary = f"""# SUMMARY — `{stamp}`

**MOM (Momentum)** frozen-knob **validation walk-forward** + **multi-universe** confirmation.
Research only — **not gold / not DailyRun**.

## Verdict

**{verdict}**

{notes_md}

## Part A — Walk-forward folds (ADV$2m continuous path)

Equity Ann ROR / Max DD from daily MTM in-window; trades by `entry_date` in fold.
Clickable HTML in `compare.html`. Knobs frozen — **no selection**.

| Fold | Start | End | Ann ROR % | Max DD % | Avg PnL % | PF | N | Win% |
|------|-------|-----|-----------|----------|-----------|-----|---|------|
{fold_md}

## Part B — Multi-universe (same freeze)

| Arm | N univ | IS Ann ROR | IS AvgPnL% | IS PF | IS N | OOS Ann ROR | OOS AvgPnL% | OOS PF | OOS N | Note |
|-----|--------|------------|------------|-------|------|-------------|-------------|--------|-------|------|
{arm_md}

## Artifacts

- `compare.html` — sortable WF + multi-univ tables (no Sheet/Total PnL $)
- `wf_folds.csv` / `multiuniv_arms.csv` / `metrics.json`
- `control_adv2m/` — full single-arm stamp copy of control run
- `BASELINE.md` / `SUMMARY.md`
"""
    sp = out / "SUMMARY.md"
    sp.write_text(summary, encoding="utf-8")
    written.append(sp)

    html_path = write_html(out, stamp=stamp, folds=folds, arms=arms, verdict=verdict, notes=verdict_notes)
    written.append(html_path)
    return written


def write_html(
    out: Path,
    *,
    stamp: str,
    folds: list[dict[str, Any]],
    arms: list[dict[str, Any]],
    verdict: str,
    notes: list[str],
) -> Path:
    def fmt(x: Any) -> str:
        return _fmt_metric(x)

    wf_cols = [
        ("Fold", "fold", "text"),
        ("Start", "start", "date"),
        ("End", "end", "date"),
        ("Ann ROR %", "ann_ror", "num"),
        ("Max DD %", "max_dd", "num"),
        ("Total ret %", "total_ret_pct", "num"),
        ("Sharpe", "sharpe", "num"),
        ("Calmar", "calmar", "num"),
        ("Avg PnL %", "avg_pnl_pct", "num"),
        ("PF", "profit_factor", "num"),
        ("N", "n", "num"),
        ("Win %", "win_rate", "num"),
        ("Avg days", "avg_days", "num"),
    ]
    wf_head = "".join(_sortable_th(c[0], c[2]) for c in wf_cols)
    wf_body = ""
    for f in folds:
        cells = []
        for _, key, typ in wf_cols:
            v = f.get(key)
            if typ == "num":
                cells.append(fmt(v))
            else:
                cells.append(html_mod.escape(str(v if v is not None else "—")))
        wf_body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    mu_metric_defs = [
        ("Arm", "label", "text"),
        ("Note", "note", "text"),
        ("N univ", "n_univ", "num"),
        ("Full Ann ROR %", "full_ann_ror", "num"),
        ("Full Max DD %", "full_max_dd", "num"),
        ("Full Calmar", "full_calmar", "num"),
        ("Full Sharpe", "full_sharpe", "num"),
        ("Full N", "full_n", "num"),
        ("Full Win %", "full_wr", "num"),
        ("Full Avg PnL %", "full_avg_pnl", "num"),
        ("Full PF", "full_pf", "num"),
        ("Full Avg days", "full_avg_days", "num"),
        ("IS Ann ROR %", "is_ann_ror", "num"),
        ("IS Max DD %", "is_max_dd", "num"),
        ("IS N", "is_n", "num"),
        ("IS Win %", "is_wr", "num"),
        ("IS Avg PnL %", "is_avg_pnl", "num"),
        ("IS PF", "is_pf", "num"),
        ("OOS Ann ROR %", "oos_ann_ror", "num"),
        ("OOS Max DD %", "oos_max_dd", "num"),
        ("OOS N", "oos_n", "num"),
        ("OOS Win %", "oos_wr", "num"),
        ("OOS Avg PnL %", "oos_avg_pnl", "num"),
        ("OOS PF", "oos_pf", "num"),
    ]
    mu_metric_defs = [c for c in mu_metric_defs if not is_excluded_html_compare_label(c[0])]
    mu_head = "".join(_sortable_th(c[0], c[2]) for c in mu_metric_defs)
    mu_body = ""
    for a in arms:
        cells = []
        for _, key, typ in mu_metric_defs:
            v = a.get(key)
            if typ == "num" and key != "n_univ" and key not in {"full_n", "is_n", "oos_n"}:
                cells.append(fmt(v))
            elif typ == "num":
                cells.append(str(int(v)) if v is not None and np.isfinite(float(v)) else "—")
            else:
                cells.append(html_mod.escape(str(v if v is not None else "—")))
        mu_body += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    notes_html = "".join(f"<li>{html_mod.escape(n)}</li>" for n in notes)
    badge_cls = "badge-ok" if "LEAN KEEP" in verdict else "badge-warn"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
<title>MOM WF + multi-univ — {html_mod.escape(stamp)}</title>
<style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --accent: #2a4a5c; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea; --ok: #2d6a4f; --ok-bg: #e8f2ec;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1200px; margin: 0 auto; padding: 36px 24px 64px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{ font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent); font-weight: 650; margin: 0 0 6px; }}
  h1 {{ font-size: 1.55rem; margin: 0 0 6px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 1.12rem; margin: 26px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  .lede {{ margin: 0; color: var(--muted); max-width: 76ch; }}
  .badge {{ display: inline-block; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.04em; padding: 2px 8px; margin: 10px 4px 0 0; }}
  .badge-warn {{ background: var(--warn-bg); color: var(--warn); }}
  .badge-bad {{ background: var(--bad-bg); color: var(--bad); }}
  .badge-ok {{ background: var(--ok-bg); color: var(--ok); }}
  .callout {{ background: var(--warn-bg); border-left: 4px solid var(--warn); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.bad {{ background: var(--bad-bg); border-left-color: var(--bad); }}
  .table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
  table.sortable {{ border-collapse: collapse; width: 100%; font-size: 12.5px; }}
  th, td {{ border: 1px solid var(--line); padding: 6px 7px; text-align: left; }}
  thead th {{ background: var(--fill); }}
  {SORTABLE_TH_CSS}
  caption {{ text-align: left; font-size: 0.82rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }}
  footer {{ margin-top: 28px; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }}
  code {{ font-family: Consolas, monospace; font-size: 0.86em; background: var(--fill); padding: 0.08em 0.3em; }}
  ul {{ padding-left: 1.25rem; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Paul experiments · validation WF + multi-univ</p>
    <h1>MOM (Momentum) — walk-forward &amp; multi-universe confirmation</h1>
    <p class="lede">Frozen Clenow knobs from <code>mom_baseline_liquid_20260829</code>.
    Stamp <code>{html_mod.escape(stamp)}</code>. Validation only — no retune, no fold selection.</p>
    <span class="badge badge-bad">NOT GOLD</span>
    <span class="badge badge-warn">NOT DailyRun</span>
    <span class="badge {badge_cls}">{html_mod.escape(verdict)}</span>
  </header>

  <div class="callout bad">
    <strong>Research candidate only.</strong> Knobs frozen a priori.
    Walk-forward folds are robustness checks — <em>not</em> used to pick parameters.
    Static liquid tape (not PIT S&amp;P 500). Sheet/Total PnL $ omitted.
  </div>

  <h2>Verdict notes</h2>
  <ul>{notes_html}</ul>

  <h2>Part A — Walk-forward folds (click headers to sort)</h2>
  <div class="table-wrap">
  <table class="sortable">
    <caption>Continuous ADV$2m book; per-fold equity + trades by entry_date. Click column headers to sort.</caption>
    <thead><tr>{wf_head}</tr></thead>
    <tbody>{wf_body}</tbody>
  </table>
  </div>

  <h2>Part B — Multi-universe (click headers to sort)</h2>
  <div class="table-wrap">
  <table class="sortable">
    <caption>Same MOM freeze; only universe changes. PaulTwenty = sensitivity. Click column headers to sort.</caption>
    <thead><tr>{mu_head}</tr></thead>
    <tbody>{mu_body}</tbody>
  </table>
  </div>

  <div class="callout">
    Re-run: <code>python tools/mom_walkforward_multiuniv.py --out drive/paul_experiments/{html_mod.escape(stamp)}</code>
  </div>

  <footer>drive/paul_experiments/{html_mod.escape(stamp)}/compare.html · {datetime.now().strftime("%Y-%m-%d %H:%M")}</footer>
</div>
{SORT_JS}
</body>
</html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="MOM validation WF + multi-univ confirmation")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--start", type=str, default="2010-01-04")
    ap.add_argument("--end", type=str, default="2026-08-28")
    ap.add_argument("--capital", type=float, default=DEFAULT_INITIAL_ACCOUNT)
    ap.add_argument("--limit", type=int, default=0, help="Smoke: limit ADV$2m univ size")
    args = ap.parse_args()

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    univ_2 = load_universe(UNIV_ADV2M)
    univ_5 = load_universe(UNIV_ADV5M)
    univ_pt = load_universe(UNIV_PT)
    if args.limit and args.limit > 0:
        univ_2 = univ_2[: args.limit]
        univ_5 = [s for s in univ_5 if s in set(univ_2)]
        print(f"[MOM-WF] smoke limit ADV$2m -> {len(univ_2)}")

    union = sorted(set(univ_2) | set(univ_5) | set(univ_pt) | {INDEX_SYM})
    print(f"[MOM-WF] Loading union panel N={len(union)} from {args.db} ...")
    panel = load_panel(args.db, [s for s in union if s != INDEX_SYM], start=start, end=end)
    loaded_2 = [s for s in univ_2 if s in panel]
    loaded_5 = [s for s in univ_5 if s in panel]
    loaded_pt = [s for s in univ_pt if s in panel]
    print(
        f"[MOM-WF] Loaded ADV$2m={len(loaded_2)}/{len(univ_2)} "
        f"ADV$5m={len(loaded_5)}/{len(univ_5)} PaulTwenty={len(loaded_pt)}/{len(univ_pt)} "
        f"SPY={'yes' if INDEX_SYM in panel else 'NO'}"
    )

    print("[MOM-WF] Running control ADV$2m ...")
    ctrl = run_backtest(panel, loaded_2, initial_capital=args.capital, bt_start=start, bt_end=end)
    print(f"[MOM-WF] Control trades={len(ctrl['trades'])} final_eq={ctrl['final_equity']:.2f}")

    print("[MOM-WF] Running ADV$5m ...")
    arm5 = run_backtest(panel, loaded_5, initial_capital=args.capital, bt_start=start, bt_end=end)
    print(f"[MOM-WF] ADV$5m trades={len(arm5['trades'])} final_eq={arm5['final_equity']:.2f}")

    print("[MOM-WF] Running PaulTwenty (sensitivity) ...")
    arm_pt = run_backtest(panel, loaded_pt, initial_capital=args.capital, bt_start=start, bt_end=end)
    print(f"[MOM-WF] PaulTwenty trades={len(arm_pt['trades'])} final_eq={arm_pt['final_equity']:.2f}")

    # Part A — WF folds on control continuous path
    folds = [_fold_metrics(ctrl, lab, a, b) for lab, a, b in WF_FOLDS]
    print("[MOM-WF] Fold summary:")
    for f in folds:
        print(
            f"  {f['fold']}: AnnROR={_fmt_metric(f['ann_ror'])} "
            f"MaxDD={_fmt_metric(f['max_dd'])} AvgPnL%={_fmt_metric(f['avg_pnl_pct'])} "
            f"PF={_fmt_metric(f['profit_factor'])} N={f['n']}"
        )

    # Part B — multi-univ packs
    p2, p5, ppt = pack_metrics(ctrl), pack_metrics(arm5), pack_metrics(arm_pt)
    arms = [
        _arm_row(
            "ADV$2m",
            "control · VZ liquid ADV$2m",
            len(univ_2),
            p2,
            UNIV_ADV2M.as_posix(),
        ),
        _arm_row(
            "ADV$5m",
            "same methodology · ADV$≥$5m",
            len(univ_5),
            p5,
            UNIV_ADV5M.as_posix(),
        ),
        _arm_row(
            "PaulTwenty",
            "sensitivity only · wrong shape for Clenow",
            len(univ_pt),
            ppt,
            UNIV_PT.as_posix(),
        ),
    ]

    verdict, notes = _verdict(arms, folds)
    print(f"[MOM-WF] Verdict: {verdict}")

    args.out.mkdir(parents=True, exist_ok=True)
    # Full control stamp under subfolder for audit trail
    ctrl_dir = args.out / "control_adv2m"
    write_stamp(
        ctrl,
        univ_2,
        UNIV_ADV2M,
        ctrl_dir,
        stamp=f"{args.out.name}__control",
        title="MOM control ADV$2m (WF parent run)",
    )

    # Also dump equity/trades for other arms (lightweight CSVs via write_stamp)
    write_stamp(
        arm5,
        univ_5,
        UNIV_ADV5M,
        args.out / "arm_adv5m",
        stamp=f"{args.out.name}__adv5m",
        title="MOM ADV$5m multi-univ arm",
        univ_note=(
            f"- File: `{UNIV_ADV5M.as_posix()}`\n"
            f"- **N = {len(univ_5)}**\n"
            "- VZ tradable ADV$≥$5m as-of 2023-12-29; not PIT S&P 500"
        ),
    )
    write_stamp(
        arm_pt,
        univ_pt,
        UNIV_PT,
        args.out / "arm_paultwenty",
        stamp=f"{args.out.name}__paultwenty",
        title="MOM PaulTwenty sensitivity (wrong shape)",
        univ_note=(
            f"- File: `{UNIV_PT.as_posix()}`\n"
            f"- **N = {len(univ_pt)}** mega-caps — sensitivity only\n"
            "- Wrong shape for Clenow top-20% weekly rank book"
        ),
    )

    written = write_report(
        args.out,
        folds=folds,
        arms=arms,
        verdict=verdict,
        verdict_notes=notes,
        control_result=ctrl,
        end=end,
    )
    print(f"[MOM-WF] Wrote stamp {args.out}")
    for p in written:
        try:
            print(f"  {p.relative_to(_REPO)}")
        except ValueError:
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
