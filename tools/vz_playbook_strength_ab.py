#!/usr/bin/env python3
"""VZ playbook strength ABs — research only (not gold).

Three one-knob hypotheses from volume-zone prior art, tested on the rw126
DualPaul78 freeze (prior to the rw63 trade-count cut):

  H1  Origin-bar climatic rvol gate (vs 20d SMA)
  H2  Drop min_touches / keep only naked first retests
  H3  Wyckoff secondary test: lighter volume on the retest bar than origin

Control = RESEARCH_CANDIDATE_V2 (HL, first_retest, mt>=1, rw=126) +
house next_open + zone_atr05_ts40.

  python tools/vz_playbook_strength_ab.py
"""
from __future__ import annotations

import argparse
import html as html_mod
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from vol_zone_break_retest import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_OUT_DIR,
    PRIMARY_EXIT,
    RESEARCH_CANDIDATE_V2,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SysParams,
    _closed_signal_rows,
    _fmt_num,
    _fmt_pct,
    atr14,
    build_zones,
    enrich_signal_rows,
    load_ohlcv,
    run_symbol_with_params,
    sortable_th,
    split_is_oos,
    summarize_signal_dicts,
)
from vz_oc_overlap_vol_strength import DUAL_PAUL78, rvol20  # noqa: E402

STAMP_DEFAULT = "vz_playbook_strength_ab_20260813"


def attach_playbook_fields(
    rows: list[dict],
    sigs: list,
    df: pd.DataFrame,
    zone_by_id: dict,
    rvol: np.ndarray,
    atr: np.ndarray,
) -> None:
    vols = df["Volume"].to_numpy(dtype=np.float64)
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    for row, sig in zip(rows, sigs):
        z = zone_by_id.get(sig.zone_id)
        asof = int(sig.signal_idx) if int(getattr(sig, "signal_idx", -1)) >= 0 else int(sig.entry_idx)
        asof = max(0, min(asof, len(vols) - 1))
        row["signal_idx"] = asof
        row["signal_vol"] = float(vols[asof])
        row["signal_rvol"] = float(rvol[asof]) if np.isfinite(rvol[asof]) else float("nan")
        days = max(int(row.get("bars_held") or 0), 1)
        row["ann_ror_pct"] = float(row["pnl_pct"]) * (365.25 / float(days))
        if z is None:
            row["origin_vol"] = float("nan")
            row["origin_rvol"] = float("nan")
            row["origin_range_atr"] = float("nan")
            row["retest_vs_origin"] = float("nan")
            continue
        oi = int(z.max_vol_idx)
        row["origin_vol"] = float(z.volume)
        row["origin_rvol"] = float(rvol[oi]) if 0 <= oi < len(rvol) and np.isfinite(rvol[oi]) else float("nan")
        rng = float(highs[oi] - lows[oi]) if 0 <= oi < len(highs) else float("nan")
        a = float(atr[oi]) if 0 <= oi < len(atr) and np.isfinite(atr[oi]) else float("nan")
        row["origin_range_atr"] = (rng / a) if a and a > 0 and np.isfinite(rng) else float("nan")
        ov = float(z.volume) if z.volume else float("nan")
        row["retest_vs_origin"] = (float(vols[asof]) / ov) if ov and ov > 0 else float("nan")
        row["zone_hi"] = float(z.hi)
        row["zone_lo"] = float(z.lo)


def process_symbol_both(sym: str, data_dir: Path) -> dict:
    csv_path = data_dir / f"{sym}.csv"
    if not csv_path.is_file():
        return {"symbol": sym, "status": "missing", "mt1": [], "mt0": [], "note": "no csv"}
    try:
        df = load_ohlcv(csv_path)
        base = replace(RESEARCH_CANDIDATE_V2, entry_on="next_open")
        if len(df) <= base.lookback_days + 20:
            return {"symbol": sym, "status": "short", "mt1": [], "mt0": [], "note": f"n={len(df)}"}
        atr = atr14(df)
        zones = build_zones(df, base.lookback_days)
        zone_by_id = {z.zone_id: z for z in zones}
        rvol = rvol20(df["Volume"].to_numpy(dtype=np.float64))
        out: dict[str, list] = {}
        for tag, mt in (("mt1", 1), ("mt0", 0)):
            params = replace(base, min_touches_before_entry=mt)
            sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, params)
            rows = enrich_signal_rows(sym, df, sigs, params, atr=atr, exit_spec=PRIMARY_EXIT)
            attach_playbook_fields(rows, sigs, df, zone_by_id, rvol, atr)
            out[tag] = rows
        return {"symbol": sym, "status": "ok", "mt1": out["mt1"], "mt0": out["mt0"], "note": ""}
    except Exception as e:
        return {"symbol": sym, "status": "error", "mt1": [], "mt0": [], "note": str(e)[:200]}


def _worker(args: tuple[str, str]) -> dict:
    sym, data_dir = args
    return process_symbol_both(sym, Path(data_dir))


def _metrics_row(label: str, rows: list[dict]) -> dict:
    closed = _closed_signal_rows(rows)
    is_r, oos_r = split_is_oos(closed)
    full = summarize_signal_dicts(closed)
    iso = summarize_signal_dicts(is_r)
    oos = summarize_signal_dicts(oos_r)
    return {
        "arm": label,
        "n": full["n_signals"],
        "wr": full["win_rate"],
        "avg_pnl": full["avg_pnl_pct"],
        "med_pnl": full["median_pnl_pct"],
        "avg_r": full["avg_r"],
        "ann_ror": full["ann_ror"],
        "avg_days": full["avg_days_held"],
        "is_n": iso["n_signals"],
        "is_wr": iso["win_rate"],
        "is_avg_pnl": iso["avg_pnl_pct"],
        "is_avg_r": iso["avg_r"],
        "is_ann_ror": iso["ann_ror"],
        "oos_n": oos["n_signals"],
        "oos_wr": oos["win_rate"],
        "oos_avg_pnl": oos["avg_pnl_pct"],
        "oos_avg_r": oos["avg_r"],
        "oos_ann_ror": oos["ann_ror"],
        "max_dd": full["max_dd_pct"],
        "calmar": full["calmar"],
        "avg_conc": full["avg_concurrent"],
        "is_max_dd": iso["max_dd_pct"],
        "is_calmar": iso["calmar"],
        "oos_max_dd": oos["max_dd_pct"],
        "oos_calmar": oos["calmar"],
    }


def _filter(rows: list[dict], pred) -> list[dict]:
    return [r for r in rows if pred(r)]


def _finite(row: dict, key: str) -> bool:
    v = row.get(key)
    try:
        return v is not None and np.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def lean(ctrl: dict, arm: dict) -> str:
    """Quality-over-count lean on IS, with OOS as a holdout check. Not an adopt."""
    if arm["n"] < 80 or arm["is_n"] < 50:
        return "DISMISS (N too small)"
    n_ratio = arm["n"] / max(ctrl["n"], 1)
    is_pnl = arm["is_avg_pnl"] - ctrl["is_avg_pnl"]
    is_wr = arm["is_wr"] - ctrl["is_wr"]
    is_r = arm["is_avg_r"] - ctrl["is_avg_r"]
    is_ann = arm["is_ann_ror"] - ctrl["is_ann_ror"]
    oos_pnl = arm["oos_avg_pnl"] - ctrl["oos_avg_pnl"]
    quality_up = (is_pnl >= 0.25 and is_r >= 0.02) or (is_wr >= 0.015 and is_ann >= 5.0)
    quality_down = is_pnl <= -0.25 and is_r <= -0.02
    oos_hurt = oos_pnl <= -0.75 or (arm["oos_n"] >= 40 and arm["oos_wr"] + 0.03 < ctrl["oos_wr"])
    if quality_down:
        return "DISMISS"
    if quality_up and not oos_hurt:
        if n_ratio < 0.35:
            return "LEAN KEEP (thin N)"
        return "LEAN KEEP"
    if quality_up and oos_hurt:
        return "HOLD (IS up, OOS soft)"
    if abs(is_pnl) < 0.25 and abs(is_wr) < 0.015 and n_ratio > 0.85:
        return "DISMISS (no change)"
    if is_pnl > 0 and oos_pnl > 0 and n_ratio < 0.9:
        return "HOLD (weak)"
    return "DISMISS"


def _arm_table_html(rows: list[dict], caption: str) -> str:
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['arm'])}</td>"
            f"<td>{html_mod.escape(r.get('knob', ''))}</td>"
            f"<td>{html_mod.escape(r.get('lean', ''))}</td>"
            f"<td>{int(r['n'])}</td>"
            f"<td>{_fmt_pct(float(r['wr']))}%</td>"
            f"<td>{_fmt_num(float(r['avg_pnl']))}</td>"
            f"<td>{_fmt_num(float(r['avg_r']))}</td>"
            f"<td>{_fmt_num(float(r['med_pnl']))}</td>"
            f"<td>{_fmt_num(float(r['ann_ror']))}</td>"
            f"<td>{_fmt_num(float(r['max_dd']))}</td>"
            f"<td>{_fmt_num(float(r['calmar']))}</td>"
            f"<td>{int(r['is_n'])}</td>"
            f"<td>{_fmt_pct(float(r['is_wr']))}%</td>"
            f"<td>{_fmt_num(float(r['is_avg_pnl']))}</td>"
            f"<td>{_fmt_num(float(r['is_ann_ror']))}</td>"
            f"<td>{_fmt_num(float(r['is_max_dd']))}</td>"
            f"<td>{int(r['oos_n'])}</td>"
            f"<td>{_fmt_pct(float(r['oos_wr']))}%</td>"
            f"<td>{_fmt_num(float(r['oos_avg_pnl']))}</td>"
            f"<td>{_fmt_num(float(r['oos_ann_ror']))}</td>"
            f"<td>{_fmt_num(float(r['oos_max_dd']))}</td>"
            "</tr>"
        )
    heads = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("Knob", "text"),
            sortable_th("Lean", "text"),
            sortable_th("N", "num"),
            sortable_th("WR%", "num"),
            sortable_th("Avg PnL%", "num"),
            sortable_th("Avg R", "num"),
            sortable_th("Med PnL%", "num"),
            sortable_th("Book Ann ROR%", "num"),
            sortable_th("Max DD%", "num"),
            sortable_th("Calmar", "num"),
            sortable_th("IS N", "num"),
            sortable_th("IS WR%", "num"),
            sortable_th("IS Avg PnL%", "num"),
            sortable_th("IS Ann ROR%", "num"),
            sortable_th("IS Max DD%", "num"),
            sortable_th("OOS N", "num"),
            sortable_th("OOS WR%", "num"),
            sortable_th("OOS Avg PnL%", "num"),
            sortable_th("OOS Ann ROR%", "num"),
            sortable_th("OOS Max DD%", "num"),
        ]
    )
    return (
        f"<div class='table-wrap'><table class='sortable'><caption>{html_mod.escape(caption)}</caption>"
        f"<thead><tr>{heads}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="VZ playbook strength one-knob ABs")
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    ap.add_argument("--symbols", default="")
    ap.add_argument(
        "--replay",
        action="store_true",
        help="Rescore Max DD / Calmar from existing trades_mt1.csv + trades_mt0.csv (no engine).",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir) / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if args.replay:
        mt1_path = out_dir / "trades_mt1.csv"
        mt0_path = out_dir / "trades_mt0.csv"
        if not mt1_path.is_file() or not mt0_path.is_file():
            print(f"[VZ-playbook] --replay needs {mt1_path} and {mt0_path}", flush=True)
            return 1
        mt1 = _closed_signal_rows(pd.read_csv(mt1_path).to_dict("records"))
        mt0 = _closed_signal_rows(pd.read_csv(mt0_path).to_dict("records"))
        print(
            f"[VZ-playbook] replay closed mt1={len(mt1)} mt0={len(mt0)} from {out_dir}",
            flush=True,
        )
    else:
        data_dir = Path(args.data_dir)
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(DUAL_PAUL78)
        symbols = [s for s in symbols if (data_dir / f"{s}.csv").is_file()]
        print(f"[VZ-playbook] symbols={len(symbols)} workers={args.workers} stamp={args.stamp}", flush=True)

        mt1 = []
        mt0 = []
        n_w = max(1, int(args.workers))
        jobs = [(s, str(data_dir)) for s in symbols]
        if n_w == 1:
            results = [_worker(j) for j in jobs]
        else:
            results = []
            with ProcessPoolExecutor(max_workers=n_w) as ex:
                futs = [ex.submit(_worker, j) for j in jobs]
                for i, fut in enumerate(as_completed(futs), 1):
                    res = fut.result()
                    results.append(res)
                    print(
                        f"  [{i}/{len(symbols)}] {res['symbol']} {res['status']} "
                        f"mt1={len(res['mt1'])} mt0={len(res['mt0'])}",
                        flush=True,
                    )
        if n_w == 1:
            for i, res in enumerate(results, 1):
                print(
                    f"  [{i}/{len(symbols)}] {res['symbol']} {res['status']} "
                    f"mt1={len(res['mt1'])} mt0={len(res['mt0'])}",
                    flush=True,
                )
        for res in results:
            mt1.extend(res["mt1"])
            mt0.extend(res["mt0"])
        mt1 = _closed_signal_rows(mt1)
        mt0 = _closed_signal_rows(mt0)
        print(f"[VZ-playbook] closed mt1={len(mt1)} mt0={len(mt0)} in {time.time()-t0:.0f}s", flush=True)

    ctrl = _metrics_row("CONTROL mt>=1", mt1)
    arms_meta = [
        ("CONTROL mt>=1", "none (rw126 v2)", mt1, "control"),
        (
            "H1 ORIGIN_RVOL>=2.5",
            "origin_rvol >= 2.5",
            _filter(mt1, lambda r: _finite(r, "origin_rvol") and float(r["origin_rvol"]) >= 2.5),
            "H1",
        ),
        (
            "H1 ORIGIN_RVOL>=4.0",
            "origin_rvol >= 4.0",
            _filter(mt1, lambda r: _finite(r, "origin_rvol") and float(r["origin_rvol"]) >= 4.0),
            "H1",
        ),
        ("H2 MT0 drop prior-touch", "min_touches 1→0", mt0, "H2"),
        (
            "H2 NAKED only",
            "mt=0 and touch_count_all==0",
            _filter(mt0, lambda r: int(r.get("touch_count_all") or 0) == 0),
            "H2",
        ),
        (
            "H3 RETEST/ORIGIN<=0.5",
            "signal_vol / origin_vol <= 0.5",
            _filter(mt1, lambda r: _finite(r, "retest_vs_origin") and float(r["retest_vs_origin"]) <= 0.5),
            "H3",
        ),
        (
            "H3 SIGNAL_RVOL<1",
            "signal_rvol < 1.0",
            _filter(mt1, lambda r: _finite(r, "signal_rvol") and float(r["signal_rvol"]) < 1.0),
            "H3",
        ),
    ]

    table = []
    for name, knob, rows, hyp in arms_meta:
        m = _metrics_row(name, rows)
        m["knob"] = knob
        m["hyp"] = hyp
        m["lean"] = "control" if hyp == "control" else lean(ctrl, m)
        table.append(m)
        print(
            f"  {name:28s} N={m['n']:5d} WR={m['wr']*100:5.1f}% "
            f"PnL={m['avg_pnl']:+6.2f} Ann={m['ann_ror']:7.1f} "
            f"MaxDD={m['max_dd']:5.1f} Calmar={m['calmar']:4.2f} "
            f"OOS_N={m['oos_n']:4d} OOS_PnL={m['oos_avg_pnl']:+6.2f} "
            f"OOS_DD={m['oos_max_dd']:5.1f}  {m['lean']}",
            flush=True,
        )

    pd.DataFrame(table).to_csv(out_dir / "ab_metrics.csv", index=False)
    if not args.replay:
        pd.DataFrame(mt1).to_csv(out_dir / "trades_mt1.csv", index=False)
        pd.DataFrame(mt0).to_csv(out_dir / "trades_mt0.csv", index=False)

    # Coverage of features on control
    c = pd.DataFrame(mt1)
    cov_lines = []
    if not c.empty:
        cov_lines.append(
            f"Control origin_rvol median={c['origin_rvol'].median():.2f} "
            f"p10={c['origin_rvol'].quantile(0.1):.2f} "
            f"p90={c['origin_rvol'].quantile(0.9):.2f}."
        )
        cov_lines.append(
            f"Control retest/origin median={c['retest_vs_origin'].median():.2f} "
            f"signal_rvol median={c['signal_rvol'].median():.2f}."
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>VZ playbook strength AB — {html_mod.escape(args.stamp)}</title>
<style>
  body {{ font-family: Segoe UI, Helvetica, sans-serif; margin: 24px; color: #1c1b19; background: #f7f6f2; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.05rem; border-bottom: 1px solid #d4d0c4; padding-bottom: 4px; }}
  .muted {{ color: #5a574f; }}
  .callout {{ background: #e8eef2; border-left: 4px solid #2a4a5c; padding: 10px 12px; margin: 12px 0; }}
  .callout.warn {{ background: #f7efe0; border-left-color: #8a5a12; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }}
  th, td {{ border: 1px solid #d4d0c4; padding: 6px 8px; text-align: left; }}
  thead th {{ background: #f0eee6; }}
  {SORTABLE_TH_CSS}
  code {{ background: #f0eee6; padding: 0.05em 0.3em; }}
</style></head><body>
<h1>VZ playbook strength — one-knob ABs</h1>
<p class="muted">Research only · {html_mod.escape(args.stamp)} · DualPaul78 · freeze rw126 v2 + next_open + zone_atr05_ts40</p>
<div class="callout warn">
<strong>Not gold. Not DailyRun.</strong> Leans are research labels on IS with OOS as a check.
Do not retune on OOS. One hypothesis per pair of alternatives vs CONTROL.
</div>
<p>{" ".join(html_mod.escape(x) for x in cov_lines)}</p>
<p>Max DD is the house passive book path (fixed notional, PnL at exit, no OHLC MTM). Init capital is sized to average concurrent slots.</p>
<h2>1. Hypotheses</h2>
<ol>
<li><strong>H1 climatic origin.</strong> Only keep zones whose max-vol day is a real spike vs the 20-day average (rvol ≥ 2.5 / ≥ 4.0). Quiet-window “max” bars are noise.</li>
<li><strong>H2 naked / first retest.</strong> Market Profile prefers untested nodes. Drop <code>min_touches≥1</code>, or keep only <code>touch_count_all==0</code>.</li>
<li><strong>H3 Wyckoff secondary test.</strong> Retest bar should show less effort than the origin climax (vol ratio ≤ 0.5, or signal rvol &lt; 1).</li>
</ol>
<h2>2. Results</h2>
{_arm_table_html(table, "Click headers to sort. Lean is not an adopt.")}
<h2>3. How to read</h2>
<ul>
<li>Judge quality (WR / Avg R / Avg PnL / book Ann ROR / Max DD), not max profit. OOS is 2024+.</li>
<li>Max DD is the house passive book path (fixed notional, PnL at exit, no OHLC MTM). Calmar = book Ann ROR / Max DD.</li>
<li>LEAN KEEP = IS quality up and OOS not soft. HOLD = mixed. DISMISS = no edge or worse.</li>
<li>H2 changes the entry set (engine re-run). H1/H3 are filters on CONTROL trades.</li>
</ul>
<footer class="muted">Twin Beacon Networks · VZ research · {html_mod.escape(args.stamp)}</footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    (out_dir / "VZ_Playbook_Strength_AB.html").write_text(html, encoding="utf-8")

    def md_row(r: dict) -> str:
        return (
            f"| {r['arm']} | {r['knob']} | {r['lean']} | {int(r['n'])} | "
            f"{_fmt_pct(float(r['wr']))}% | {_fmt_num(float(r['avg_pnl']))} | "
            f"{_fmt_num(float(r['avg_r']))} | {_fmt_num(float(r['ann_ror']))} | "
            f"{_fmt_num(float(r['max_dd']))} | {_fmt_num(float(r['calmar']))} | "
            f"{int(r['is_n'])} | {_fmt_pct(float(r['is_wr']))}% | {_fmt_num(float(r['is_avg_pnl']))} | "
            f"{_fmt_num(float(r['is_max_dd']))} | "
            f"{int(r['oos_n'])} | {_fmt_pct(float(r['oos_wr']))}% | {_fmt_num(float(r['oos_avg_pnl']))} | "
            f"{_fmt_num(float(r['oos_max_dd']))} |"
        )

    ctrl_m = table[0]
    by_arm = {r["arm"]: r for r in table}
    h1_hi = by_arm["H1 ORIGIN_RVOL>=4.0"]
    h2_naked = by_arm["H2 NAKED only"]
    md = [
        "# VZ playbook strength ABs",
        "",
        "Research only. Control = `RESEARCH_CANDIDATE_V2` rw126, DualPaul78, next_open, `zone_atr05_ts40`.",
        "",
        "## Verdict",
        "",
        "**Do not adopt any of these three playbook gates.** They do not beat control on quality-over-count. "
        "`min_touches≥1` is doing real work; naked/first-touch lore is the wrong direction for this sleeve.",
        "",
        f"Control: N={int(ctrl_m['n'])}, WR {_fmt_pct(float(ctrl_m['wr']))}%, avg PnL {_fmt_num(float(ctrl_m['avg_pnl']))}%, "
        f"book Ann ROR {_fmt_num(float(ctrl_m['ann_ror']))}%, Max DD {_fmt_num(float(ctrl_m['max_dd']))}% "
        f"(OOS N={int(ctrl_m['oos_n'])}, PnL {_fmt_num(float(ctrl_m['oos_avg_pnl']))}%, Max DD {_fmt_num(float(ctrl_m['oos_max_dd']))}%). "
        "Max DD is the house passive book path (fixed notional, PnL at exit, no OHLC MTM). "
        "Init capital is sized to average concurrent slots, so thinner sleeves are not automatically calmer.",
        "",
        "H1 origin rvol ≥4.0 is the only arm with a clearly smaller book Max DD "
        f"({_fmt_num(float(h1_hi['max_dd']))}% vs {_fmt_num(float(ctrl_m['max_dd']))}%) and higher Calmar. "
        "That sleeve is ~31% of control N; do not treat the DD cut as a free lunch. "
        f"H2 naked is worse on DD ({_fmt_num(float(h2_naked['max_dd']))}%).",
        "",
    ]
    for hyp, title in (("H1", "H1 origin climatic rvol"), ("H2", "H2 naked / drop min_touches"), ("H3", "H3 lighter retest volume")):
        md.append(f"### {title}")
        md.append("")
        for r in table:
            if r["hyp"] == hyp:
                md.append(
                    f"- **{r['arm']}**: {r['lean']} — FULL N={int(r['n'])} WR {_fmt_pct(float(r['wr']))}% "
                    f"avg PnL {_fmt_num(float(r['avg_pnl']))}% Ann ROR {_fmt_num(float(r['ann_ror']))}% "
                    f"Max DD {_fmt_num(float(r['max_dd']))}% "
                    f"(OOS N={int(r['oos_n'])} PnL {_fmt_num(float(r['oos_avg_pnl']))}% "
                    f"Max DD {_fmt_num(float(r['oos_max_dd']))}%)"
                )
        md.append("")
    md += [
        "## Setup",
        "",
        *cov_lines,
        "",
        "| Arm | Knob | Lean | N | WR% | Avg PnL% | Avg R | Book Ann ROR% | Max DD% | Calmar | IS N | IS WR% | IS Avg PnL% | IS Max DD% | OOS N | OOS WR% | OOS Avg PnL% | OOS Max DD% |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    md.extend(md_row(r) for r in table)
    md += [
        "",
        "## Reproduce",
        "",
        "```",
        "python tools/vz_playbook_strength_ab.py",
        "python tools/vz_playbook_strength_ab.py --replay   # rescore Max DD from saved trades",
        "```",
        "",
        "Not gold. Not DailyRun. Do not retune on OOS.",
        "",
    ]
    text = "\n".join(md)
    (out_dir / "README.md").write_text(text, encoding="utf-8")
    docs = REPO / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "vz_playbook_strength_ab.md").write_text(text, encoding="utf-8")
    (docs / "vz_playbook_strength_ab.html").write_text(html, encoding="utf-8")
    pd.DataFrame(table).to_csv(docs / "vz_playbook_strength_ab.csv", index=False)
    print(f"[VZ-playbook] wrote {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
