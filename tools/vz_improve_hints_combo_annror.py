#!/usr/bin/env python3
"""Combinatorial Ann ROR search over ImproveHints AB knobs (research only).

Search/rank on **IS Ann ROR**; OOS Ann ROR is report-only holdout.
Combo search is high selection-bias risk — labeled clearly in outputs.

Axes (orthogonal; peers collapsed to one level each where possible):
  stop_atr_buffer ∈ {0.5, 0.75, 1.0}   # control + LEAN KEEP wideners
  exit_bars       ∈ {40, 20, 60}
  target_r        ∈ {2.0, 2.5, 1.5}
  trail_be1r      ∈ {0, 1}
  cd_target10     ∈ {0, 1}
  spy_sma200      ∈ {0, 1}

Full factorial = 3×3×3×2×2×2 = 216 combos (includes control).
Excluded: partial_exit (untestable); ENTRY eps/mt (large solo Ann ROR damage;
same-axis peers already covered by milder/lean alternatives).

Usage:
  python tools/vz_improve_hints_combo_annror.py
  python tools/vz_improve_hints_combo_annror.py --workers 8
"""
from __future__ import annotations

import argparse
import html as html_mod
import itertools
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    atr14,
    build_zones,
    enrich_signal_rows,
    load_ohlcv,
    load_universe_symbols,
    run_symbol_with_params,
    sortable_th,
    split_is_oos,
    summarize_signal_dicts,
    _fmt_num,
    _fmt_pct,
)
from vz_improve_hints_ab import (  # noqa: E402
    _ext_cells,
    _ext_headers,
    enrich_trail_rows,
    filter_cooldown_after_target,
    filter_spy_regime,
    load_spy_sma200,
)

DEFAULT_UNIVERSE = REPO / "drive" / "universes" / "VZ_universe.csv"
HINTS_STAMP = "260811090711"
DEFAULT_STAMP = f"vz_improve_hints_combo_annror_{HINTS_STAMP}"

STOPS = (0.5, 0.75, 1.0)
EXIT_BARS = (40, 20, 60)
TARGETS = (2.0, 2.5, 1.5)
TRAILS = (False, True)
CDS = (False, True)
SPYS = (False, True)


def combo_id(
    stop: float,
    bars: int,
    target: float,
    trail: bool,
    cd: bool,
    spy: bool,
) -> str:
    parts = [
        f"stop{stop:g}",
        f"ts{bars}",
        f"r{target:g}",
        "trail" if trail else "notrail",
        "cd10" if cd else "nocd",
        "spy" if spy else "nospy",
    ]
    return "_".join(parts)


def is_control(stop: float, bars: int, target: float, trail: bool, cd: bool, spy: bool) -> bool:
    return (
        abs(stop - 0.5) < 1e-9
        and bars == 40
        and abs(target - 2.0) < 1e-9
        and (not trail)
        and (not cd)
        and (not spy)
    )


def enumerate_combos() -> list[dict]:
    out: list[dict] = []
    for stop, bars, target, trail, cd, spy in itertools.product(
        STOPS, EXIT_BARS, TARGETS, TRAILS, CDS, SPYS
    ):
        out.append(
            {
                "combo": combo_id(stop, bars, target, trail, cd, spy),
                "stop_atr_buffer": float(stop),
                "exit_bars": int(bars),
                "target_r": float(target),
                "trail_be1r": bool(trail),
                "cd_target10": bool(cd),
                "spy_sma200": bool(spy),
                "is_control": is_control(stop, bars, target, trail, cd, spy),
            }
        )
    return out


def _exit_key(stop: float, bars: int, target: float, trail: bool) -> str:
    return f"stop{stop:g}_ts{bars}_r{target:g}_{'trail' if trail else 'notrail'}"


def build_exit_book(
    *,
    caches: dict[str, tuple[pd.DataFrame, list, np.ndarray]],
    freeze_raw: dict[str, list[RetestSignal]],
    freeze: object,
    stop: float,
    bars: int,
    target: float,
    trail: bool,
) -> list[dict]:
    spec = ExitSpec(
        name=_exit_key(stop, bars, target, trail),
        label=spec_label(stop, bars, target, trail),
        exit_bars=bars,
        target_r=target,
        stop_atr_buffer=stop,
    )
    rows: list[dict] = []
    for sym, (df, _z, atr) in caches.items():
        sigs = freeze_raw.get(sym, [])
        if trail:
            rows.extend(enrich_trail_rows(sym, df, sigs, atr, spec))
        else:
            rows.extend(
                enrich_signal_rows(sym, df, sigs, freeze, atr=atr, exit_spec=spec)
            )
    return rows


def spec_label(stop: float, bars: int, target: float, trail: bool) -> str:
    t = " trailBE@1R" if trail else ""
    return f"zone.lo−{stop:g}·ATR, {target:g}R/{bars}d{t}"


def apply_entry_filters(
    rows: list[dict],
    *,
    cd: bool,
    spy: bool,
    spy_ok: pd.Series | None,
) -> list[dict]:
    out = rows
    if cd:
        out = filter_cooldown_after_target(out, cooldown_bars=10)
    if spy:
        assert spy_ok is not None
        out = filter_spy_regime(out, spy_ok)
    return out


def metrics_bundle(rows: list[dict]) -> dict:
    full = summarize_signal_dicts(rows)
    is_r, oos_r = split_is_oos(rows)
    return {
        "metrics": full,
        "metrics_is": summarize_signal_dicts(is_r),
        "metrics_oos": summarize_signal_dicts(oos_r),
    }


def write_baseline(path: Path, *, stamp: str, universe: Path, n_symbols: int, n_combos: int) -> None:
    p = RESEARCH_CANDIDATE_V2_RW63
    e = PRIMARY_EXIT
    md = f"""# VZ ImproveHints combo Ann ROR search — research only (NOT gold)

**Stamp:** `{stamp}`  
**Universe:** `{universe.as_posix()}` — DualPaul78 ({n_symbols} symbols)  
**Status:** Research combinatorial search — **not** gold, **not** DailyRun-wired.

## Frozen entry (all combos)

| Knob | Value |
|------|-------|
| lookback_days | {p.lookback_days} |
| zone_kinds | HL-only |
| first_retest_only | {p.first_retest_only} |
| min_touches_before_entry | {p.min_touches_before_entry} |
| retest_eps_pct | {p.retest_eps_pct} |
| retest_window | {p.retest_window} |

## Control exit

`{e.name}` — zone.lo−{e.stop_atr_buffer}·ATR, {e.target_r}R / {e.exit_bars}d

## Combo axes ({n_combos} configs)

| Axis | Levels |
|------|--------|
| stop_atr_buffer | {list(STOPS)} |
| exit_bars | {list(EXIT_BARS)} |
| target_r | {list(TARGETS)} |
| trail_be1r | {list(TRAILS)} |
| cd_target10 | {list(CDS)} |
| spy_sma200 | {list(SPYS)} |

Excluded: `partial_exit` (untestable); ENTRY eps / mt2 (large solo Ann ROR damage).

## Selection bias / IS-OOS

- **Primary sort key: IS Ann ROR** (entry_date &lt; 2024-01-01).
- OOS Ann ROR is **holdout / report-only** — do not choose or retune on OOS.
- Full-factorial combo fishing on the same DualPaul78 history used for ImproveHints
  → **high multiple-testing / selection-bias risk**. Any beat of control is a
  research LEAN KEEP candidate at best, not gold.
"""
    path.write_text(md, encoding="utf-8")


def write_html(
    path: Path,
    *,
    stamp: str,
    universe: Path,
    n_symbols: int,
    rows: list[dict],
    control: dict,
    top_n: int,
    recommendation: str,
    runtime_s: float,
) -> None:
    split_s = str(OOS_SPLIT_DATE.date())
    ctrl_is = control["metrics_is"]["ann_ror"]
    # Rank by IS Ann ROR desc
    ranked = sorted(rows, key=lambda r: r["metrics_is"]["ann_ror"], reverse=True)
    beats = [r for r in ranked if (not r["is_control"]) and r["metrics_is"]["ann_ror"] > ctrl_is + 1e-9]
    top = ranked[:top_n]
    # Always include control + best IS + any beaters in detail table
    detail_ids = {control["combo"], ranked[0]["combo"]} | {r["combo"] for r in beats[:10]}
    detail = [r for r in ranked if r["combo"] in detail_ids]
    # de-dupe preserve order
    seen: set[str] = set()
    detail_u: list[dict] = []
    for r in detail + top:
        if r["combo"] in seen:
            continue
        seen.add(r["combo"])
        detail_u.append(r)

    def row_html(r: dict) -> str:
        m, mi, mo = r["metrics"], r["metrics_is"], r["metrics_oos"]
        d_is = mi["ann_ror"] - ctrl_is
        d_full = m["ann_ror"] - control["metrics"]["ann_ror"]
        d_oos = mo["ann_ror"] - control["metrics_oos"]["ann_ror"]
        cls = ' class="ctrl"' if r["is_control"] else (' class="beat"' if d_is > 0 else "")
        return (
            f"<tr{cls}>"
            f"<td>{html_mod.escape(r['combo'])}</td>"
            f"<td>{'CONTROL' if r['is_control'] else ''}</td>"
            f"<td>{r['stop_atr_buffer']:g}</td>"
            f"<td>{r['exit_bars']}</td>"
            f"<td>{r['target_r']:g}</td>"
            f"<td>{int(r['trail_be1r'])}</td>"
            f"<td>{int(r['cd_target10'])}</td>"
            f"<td>{int(r['spy_sma200'])}</td>"
            f"<td>{mi['n_signals']}</td>"
            f"<td>{_fmt_num(mi['ann_ror'])}</td>"
            f"<td>{d_is:+.2f}</td>"
            f"<td>{_fmt_num(m['ann_ror'])}</td>"
            f"<td>{d_full:+.2f}</td>"
            f"<td>{mo['n_signals']}</td>"
            f"<td>{_fmt_num(mo['ann_ror'])}</td>"
            f"<td>{d_oos:+.2f}</td>"
            f"<td>{_fmt_pct(mi['win_rate'])}</td>"
            f"<td>{_fmt_num(mi['avg_pnl_pct'])}</td>"
            f"<td>{_fmt_num(mi['avg_days_held'])}</td>"
            "</tr>"
        )

    def ext_row(r: dict, split: str, mm: dict) -> str:
        return (
            "<tr>"
            f"<td>{html_mod.escape(r['combo'])}</td>"
            f"<td>{split}</td>"
            f"<td>{mm['n_signals']}</td>"
            f"<td>{_fmt_num(mm.get('ann_ror', 0.0))}</td>"
            f"{_ext_cells(mm)}"
            "</tr>"
        )

    ext_body = ""
    for r in detail_u[:12]:
        ext_body += ext_row(r, "Full", r["metrics"])
        ext_body += ext_row(r, "IS", r["metrics_is"])
        ext_body += ext_row(r, "OOS", r["metrics_oos"])

    beat_txt = (
        f"{len(beats)} combo(s) beat control IS Ann ROR ({ctrl_is:.2f}%)."
        if beats
        else f"No combo beats control IS Ann ROR ({ctrl_is:.2f}%)."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ImproveHints combo Ann ROR — {html_mod.escape(stamp)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1600px; margin:0 auto; }}
  h1 {{ font-size:1.45rem; }}
  h2 {{ font-size:1.15rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
  .rec {{ background:#fffbeb; border:1px solid #d8d8d0; padding:14px 16px; margin:1rem 0; }}
  .rec.keep {{ background:#ecfdf5; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:12px; margin-bottom:1.4rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:4px 6px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  tr.ctrl {{ background:#eef2ff; }}
  tr.beat {{ background:#ecfdf5; }}
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
  <h1>VZ ImproveHints combo Ann ROR — {html_mod.escape(stamp)}</h1>
  <p class="muted">
    Research only (not gold / not DailyRun). Universe DualPaul78
    (<code>{html_mod.escape(str(universe))}</code>, {n_symbols} symbols).
    Freeze entry: HL-only, first_retest, mt≥1, eps=0.005, lb=126, rw=63.
    <strong>Combo search ranked on IS Ann ROR; OOS is holdout (do not retune).</strong>
    High multiple-testing / selection-bias risk. {len(rows)} combos.
    Click column headers to sort. Runtime {runtime_s/60:.1f} min.
  </p>

  <div class="rec {'keep' if beats else ''}">
    <strong>Recommendation</strong>
    <pre style="white-space:pre-wrap;margin:0.6rem 0 0;font-family:inherit">{html_mod.escape(recommendation)}</pre>
  </div>

  <h2>Leaderboard (sorted by IS Ann ROR) — top {top_n}</h2>
  <p class="muted">{beat_txt} Control IS Ann ROR = {_fmt_num(ctrl_is)}%. Green = beats control on IS.</p>
  <table class="sortable"><thead><tr>
    {sortable_th("Combo", "text")}
    {sortable_th("Tag", "text")}
    {sortable_th("StopATR", "num")}
    {sortable_th("TS", "num")}
    {sortable_th("TargetR", "num")}
    {sortable_th("Trail", "num")}
    {sortable_th("CD10", "num")}
    {sortable_th("SPY", "num")}
    {sortable_th("IS N", "num")}
    {sortable_th("IS AnnROR%", "num")}
    {sortable_th("ΔIS vs ctrl", "num")}
    {sortable_th("Full AnnROR%", "num")}
    {sortable_th("ΔFull", "num")}
    {sortable_th("OOS N", "num")}
    {sortable_th("OOS AnnROR%", "num")}
    {sortable_th("ΔOOS", "num")}
    {sortable_th("IS WR%", "num")}
    {sortable_th("IS AvgPnL%", "num")}
    {sortable_th("IS AvgDays", "num")}
  </tr></thead><tbody>
  {"".join(row_html(r) for r in top)}
  </tbody></table>

  <h2>Extended metrics — control + top / beaters</h2>
  <p class="muted">
    (1) Max DD + Calmar; (2) PF + avgW/|L|; (4) outlier % of wins / top10;
    (5) exposure / concurrent; (7) median vs mean; (8) passive vs aggressive.
    Skip exit-mix / same-day clusters.
  </p>
  <table class="sortable"><thead><tr>
    {sortable_th("Combo", "text")}
    {sortable_th("Slice", "text")}
    {sortable_th("N", "num")}
    {sortable_th("Ann ROR%", "num")}
    {_ext_headers()}
  </tr></thead><tbody>
  {ext_body}
  </tbody></table>

  <h2>Caveats</h2>
  <ul>
    <li>Full factorial over ImproveHints-derived knobs on the same history = combo fishing.</li>
    <li>IS rank ≠ OOS truth. Soft OOS → HOLD; do not retune holdout.</li>
    <li>Max DD / aggressive metrics use cash equity path (PnL at exit), not full OHLC MTM.</li>
    <li>Research candidate ≠ gold ≠ DailyRun.</li>
  </ul>
  <p class="muted">Generated by <code>tools/vz_improve_hints_combo_annror.py</code>. Split date {split_s}.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def build_recommendation(rows: list[dict], control: dict) -> str:
    ctrl_is = control["metrics_is"]["ann_ror"]
    ctrl_oos = control["metrics_oos"]["ann_ror"]
    ctrl_full = control["metrics"]["ann_ror"]
    ranked = sorted(rows, key=lambda r: r["metrics_is"]["ann_ror"], reverse=True)
    beats = [
        r
        for r in ranked
        if (not r["is_control"]) and r["metrics_is"]["ann_ror"] > ctrl_is + 1e-9
    ]
    lines: list[str] = []
    lines.append(
        "COMBO SEARCH — ranked on IS Ann ROR; OOS is holdout (do not retune). "
        "High selection-bias / multiple-testing risk."
    )
    lines.append(
        f"Control: IS AnnROR={ctrl_is:.2f}% Full={ctrl_full:.2f}% OOS={ctrl_oos:.2f}% "
        f"(N_is={control['metrics_is']['n_signals']}, N_oos={control['metrics_oos']['n_signals']})."
    )
    if not beats:
        best = ranked[0]
        lines.append(
            f"No combo beats control IS Ann ROR. Best IS is {best['combo']} "
            f"at {best['metrics_is']['ann_ror']:.2f}% "
            f"(ΔIS {best['metrics_is']['ann_ror'] - ctrl_is:+.2f}pp; "
            f"OOS {best['metrics_oos']['ann_ror']:.2f}% report-only)."
        )
        lines.append(
            "Recommendation: HOLD control exit/filters for Ann ROR. "
            "One-knob LEAN KEEPs (wider stops) remain quality-only research candidates — "
            "they do not lift Ann ROR alone or in this factorial."
        )
    else:
        lines.append(f"{len(beats)} combo(s) beat control on IS Ann ROR (research LEAN KEEP only if OOS does not collapse):")
        for r in beats[:8]:
            mi, mo, m = r["metrics_is"], r["metrics_oos"], r["metrics"]
            oos_note = "OOS ok-ish"
            if mo["n_signals"] < 15:
                oos_note = "thin OOS N"
            elif mo["ann_ror"] < ctrl_oos - 5.0:
                oos_note = "OOS AnnROR softens vs control OOS — HOLD / do not retune"
            lines.append(
                f"  - {r['combo']}: IS {mi['ann_ror']:.2f}% (Δ{mi['ann_ror'] - ctrl_is:+.2f}) "
                f"Full {m['ann_ror']:.2f}% OOS {mo['ann_ror']:.2f}% (ΔOOS {mo['ann_ror'] - ctrl_oos:+.2f}) "
                f"— {oos_note}"
            )
        # Lean keep only those that don't collapse OOS
        lean = [
            r
            for r in beats
            if r["metrics_oos"]["n_signals"] >= 15
            and r["metrics_oos"]["ann_ror"] >= ctrl_oos - 5.0
        ]
        if lean:
            lines.append(
                "LEAN KEEP (research): "
                + ", ".join(r["combo"] for r in lean[:5])
                + " — beats IS Ann ROR without collapsing OOS vs control; still not gold."
            )
        else:
            lines.append(
                "No combo both beats IS Ann ROR and holds OOS within ~5pp of control — "
                "treat IS winners as selection-biased HOLD."
            )
    lines.append(
        "Excluded from factorial: partial_exit; ENTRY eps/mt2. "
        "Not gold / not DailyRun."
    )
    return "\n".join(lines)


def run(
    *,
    universe_path: Path,
    data_dir: Path,
    out_dir: Path,
    stamp: str,
    workers: int,
    top_n: int,
) -> Path:
    t0 = time.time()
    symbols = load_universe_symbols(universe_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    combos = enumerate_combos()
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        universe=universe_path,
        n_symbols=len(symbols),
        n_combos=len(combos),
    )
    (out_dir / "AB_PLAN.md").write_text(
        "# Combo Ann ROR plan\n\n"
        f"Full factorial of ImproveHints-derived orthogonal knobs = **{len(combos)}** "
        "configs including control.\n\n"
        "Rank on **IS Ann ROR**; report Full + OOS without choosing on OOS.\n",
        encoding="utf-8",
    )

    freeze = RESEARCH_CANDIDATE_V2_RW63
    lookback = freeze.lookback_days
    caches: dict[str, tuple[pd.DataFrame, list, np.ndarray]] = {}
    freeze_raw: dict[str, list[RetestSignal]] = {}

    print(
        f"combo AnnROR stamp={stamp} symbols={len(symbols)} combos={len(combos)} "
        f"workers={workers}"
    )

    def load_one(sym: str):
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.is_file():
            return sym, None, f"missing CSV: {csv_path}"
        try:
            df = load_ohlcv(csv_path)
            atr = atr14(df)
            zones = build_zones(df, lookback)
            sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, freeze)
            return sym, (df, zones, atr, sigs), None
        except Exception as e:  # noqa: BLE001
            return sym, None, str(e)

    skipped: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(load_one, sym) for sym in symbols]
        for fut in as_completed(futs):
            sym, payload, err = fut.result()
            if err or payload is None:
                print(f"  SKIP {sym}: {err}")
                skipped.append({"symbol": sym, "note": err or "fail"})
                continue
            df, zones, atr, sigs = payload
            caches[sym] = (df, zones, atr)
            freeze_raw[sym] = sigs
            print(f"  loaded {sym}: N_entry={len(sigs)}")

    spy_ok = load_spy_sma200(data_dir)

    # Unique exit books (before cd/spy filters)
    exit_cfgs = list(
        itertools.product(STOPS, EXIT_BARS, TARGETS, TRAILS)
    )
    print(f"building {len(exit_cfgs)} exit books...")
    exit_books: dict[str, list[dict]] = {}

    def build_one(cfg):
        stop, bars, target, trail = cfg
        key = _exit_key(stop, bars, target, trail)
        rows = build_exit_book(
            caches=caches,
            freeze_raw=freeze_raw,
            freeze=freeze,
            stop=stop,
            bars=bars,
            target=target,
            trail=trail,
        )
        return key, rows

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(exit_cfgs)))) as ex:
        futs = [ex.submit(build_one, cfg) for cfg in exit_cfgs]
        for i, fut in enumerate(as_completed(futs), 1):
            key, rows = fut.result()
            exit_books[key] = rows
            if i % 5 == 0 or i == len(exit_cfgs):
                print(f"  exit books {i}/{len(exit_cfgs)}")

    # Apply filters + metrics for each combo
    print(f"scoring {len(combos)} combos...")
    results: list[dict] = []
    control_row: dict | None = None
    for i, c in enumerate(combos, 1):
        key = _exit_key(
            c["stop_atr_buffer"], c["exit_bars"], c["target_r"], c["trail_be1r"]
        )
        base_rows = exit_books[key]
        rows = apply_entry_filters(
            base_rows,
            cd=c["cd_target10"],
            spy=c["spy_sma200"],
            spy_ok=spy_ok,
        )
        bundle = metrics_bundle(rows)
        rec = {**c, **bundle}
        results.append(rec)
        if c["is_control"]:
            control_row = rec
        if i % 20 == 0 or i == len(combos):
            print(
                f"  scored {i}/{len(combos)} last={c['combo']} "
                f"IS_AnnROR={bundle['metrics_is']['ann_ror']:.2f}"
            )

    assert control_row is not None, "control combo missing from factorial"
    recommendation = build_recommendation(results, control_row)

    # CSV
    flat = []
    for r in results:
        m, mi, mo = r["metrics"], r["metrics_is"], r["metrics_oos"]
        flat.append(
            {
                "combo": r["combo"],
                "is_control": r["is_control"],
                "stop_atr_buffer": r["stop_atr_buffer"],
                "exit_bars": r["exit_bars"],
                "target_r": r["target_r"],
                "trail_be1r": r["trail_be1r"],
                "cd_target10": r["cd_target10"],
                "spy_sma200": r["spy_sma200"],
                "n_full": m["n_signals"],
                "ann_ror_full": m["ann_ror"],
                "ann_ror_is": mi["ann_ror"],
                "ann_ror_oos": mo["ann_ror"],
                "delta_ann_ror_is": mi["ann_ror"] - control_row["metrics_is"]["ann_ror"],
                "delta_ann_ror_full": m["ann_ror"] - control_row["metrics"]["ann_ror"],
                "delta_ann_ror_oos": mo["ann_ror"] - control_row["metrics_oos"]["ann_ror"],
                "n_is": mi["n_signals"],
                "n_oos": mo["n_signals"],
                "wr_is": mi["win_rate"],
                "avg_pnl_is": mi["avg_pnl_pct"],
                "avg_days_is": mi["avg_days_held"],
                "max_dd_full": m.get("max_dd_pct", 0.0),
                "calmar_full": m.get("calmar", 0.0),
                "pf_full": m.get("profit_factor", 0.0),
                "wl_ratio_full": m.get("win_loss_ratio", 0.0),
                "outlier_wins_full": m.get("outlier_pct_of_wins", 0.0),
                "exposure_full": m.get("exposure_pct", 0.0),
                "median_pnl_full": m.get("median_pnl_pct", 0.0),
                "agg_ann_ror_full": m.get("agg_ann_ror", 0.0),
                "agg_max_dd_full": m.get("agg_max_dd_pct", 0.0),
            }
        )
    flat_sorted = sorted(flat, key=lambda x: x["ann_ror_is"], reverse=True)
    pd.DataFrame(flat_sorted).to_csv(out_dir / "combo_results.csv", index=False)
    (out_dir / "recommendation.txt").write_text(recommendation, encoding="utf-8")
    (out_dir / "combo_axes.json").write_text(
        json.dumps(
            {
                "stops": list(STOPS),
                "exit_bars": list(EXIT_BARS),
                "targets": list(TARGETS),
                "trails": list(TRAILS),
                "cds": list(CDS),
                "spys": list(SPYS),
                "n_combos": len(combos),
                "rank_key": "ann_ror_is",
                "oos_policy": "report-only holdout; do not retune",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if skipped:
        pd.DataFrame(skipped).to_csv(out_dir / "skipped.csv", index=False)

    runtime = time.time() - t0
    html_path = out_dir / "comparison.html"
    write_html(
        html_path,
        stamp=stamp,
        universe=universe_path,
        n_symbols=len(symbols),
        rows=results,
        control=control_row,
        top_n=top_n,
        recommendation=recommendation,
        runtime_s=runtime,
    )
    print(f"saved: {html_path}")
    print(f"runtime: {runtime/60:.1f} min")
    print("--- recommendation ---")
    try:
        print(recommendation)
    except UnicodeEncodeError:
        print(recommendation.encode("ascii", "replace").decode("ascii"))
    return html_path


def main() -> None:
    ap = argparse.ArgumentParser(description="VZ ImproveHints combo Ann ROR search")
    ap.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--top-n", type=int, default=40)
    args = ap.parse_args()
    stamp = args.stamp.strip() or DEFAULT_STAMP
    out_dir = args.out_dir / stamp if args.out_dir == DEFAULT_OUT_DIR else args.out_dir
    run(
        universe_path=args.universe,
        data_dir=args.data_dir,
        out_dir=out_dir,
        stamp=stamp,
        workers=max(1, int(args.workers)),
        top_n=max(10, int(args.top_n)),
    )


if __name__ == "__main__":
    main()
