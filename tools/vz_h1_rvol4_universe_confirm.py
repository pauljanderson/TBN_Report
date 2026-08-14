#!/usr/bin/env python3
"""H1 origin rvol>=4 broader-universe confirmation — research only (not gold).

Frozen rule (do not retune):
  RESEARCH_CANDIDATE_V2 (HL, first_retest, mt>=1, rw=126)
  + house next_open + zone_atr05_ts40
  + H1 filter origin_rvol >= 4.0 (20d SMA, origin max-vol bar)

Universes:
  DualPaul78     — original cluster
  PaulTwenty     — if drive/universes/PaulTwenty_universe.csv exists
  SPX500         — current S&P 500 constituents (broader tradable set)
  SPX_ex_DP78    — SPX500 minus DualPaul78 (clustering check)

Local DailyRun FullOHLC dump is not in this environment; SPX500 is the
broader-universe proxy. Do not retune 4.0 on OOS.

  python tools/vz_h1_rvol4_universe_confirm.py
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
    _closed_signal_rows,
    _fmt_num,
    _fmt_pct,
    atr14,
    build_zones,
    enrich_signal_rows,
    load_ohlcv,
    load_universe_symbols,
    run_symbol_with_params,
    sortable_th,
    summarize_signal_dicts,
)
from vz_oc_overlap_vol_strength import DUAL_PAUL78, YF_ALTS, rvol20  # noqa: E402
from vz_playbook_strength_ab import (  # noqa: E402
    _arm_table_html,
    _filter,
    _finite,
    _metrics_row,
    attach_playbook_fields,
)

STAMP_DEFAULT = "vz_h1_rvol4_univ_20260814"
SPX_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
PAUL_TWENTY_PATH = REPO / "drive" / "universes" / "PaulTwenty_universe.csv"
RVOL_GATE = 4.0


def yf_ticker(sym: str) -> str:
    alts = YF_ALTS.get(sym.upper(), [sym])
    return str(alts[0]).replace(".", "-")


def load_spx500() -> list[str]:
    df = pd.read_csv(SPX_CSV)
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    out: list[str] = []
    seen: set[str] = set()
    for raw in df[col].astype(str):
        s = raw.strip().upper().replace(".", "-")
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def load_paultwenty() -> list[str]:
    if PAUL_TWENTY_PATH.is_file():
        return load_universe_symbols(PAUL_TWENTY_PATH)
    return []


def ensure_ohlcv(symbols: list[str], data_dir: Path, chunk: int = 40) -> tuple[list[str], list[str]]:
    """Download missing CSVs via yfinance into house OHLCV shape."""
    import yfinance as yf

    data_dir.mkdir(parents=True, exist_ok=True)
    have: list[str] = []
    need: list[str] = []
    for s in symbols:
        p = data_dir / f"{s}.csv"
        if p.is_file() and p.stat().st_size > 200:
            have.append(s)
        else:
            need.append(s)
    if not need:
        return have, []
    print(f"[VZ-h1-univ] downloading {len(need)} missing symbols via yfinance", flush=True)
    failed: list[str] = []
    for i in range(0, len(need), chunk):
        batch = need[i : i + chunk]
        yf_map = {yf_ticker(s): s for s in batch}
        print(f"  yf batch {i // chunk + 1}/{(len(need) + chunk - 1) // chunk} n={len(batch)}", flush=True)
        try:
            raw = yf.download(
                list(yf_map),
                start="2005-01-01",
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
                timeout=60,
            )
        except Exception as e:
            print(f"  batch failed: {e}; falling back one-by-one", flush=True)
            raw = None
        for yf_sym, house in yf_map.items():
            saved = False
            if raw is not None:
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        lvl0 = set(raw.columns.get_level_values(0))
                        if yf_sym in lvl0:
                            sub = raw[yf_sym].copy()
                        else:
                            sub = raw.xs(yf_sym, axis=1, level=1).copy()
                    else:
                        sub = raw.copy()
                    sub = sub.rename(columns=str.title)
                    if {"Open", "High", "Low", "Close", "Volume"}.issubset(set(sub.columns)):
                        sub = sub.dropna(subset=["Open", "High", "Low", "Close"])
                        if len(sub) >= 200:
                            out = sub.reset_index()
                            date_col = "Date" if "Date" in out.columns else out.columns[0]
                            out = out.rename(columns={date_col: "Date"})
                            out["Date"] = pd.to_datetime(out["Date"]).dt.tz_localize(None)
                            out = out[["Date", "Open", "High", "Low", "Close", "Volume"]]
                            out.to_csv(data_dir / f"{house}.csv", index=False)
                            have.append(house)
                            saved = True
                except Exception:
                    saved = False
            if not saved:
                failed.append(house)
        time.sleep(0.4)
    still: list[str] = []
    for s in failed:
        ok = False
        for alt in YF_ALTS.get(s, [yf_ticker(s)]):
            try:
                hist = yf.Ticker(alt).history(start="2005-01-01", auto_adjust=True, timeout=60)
                if hist is None or hist.empty or len(hist) < 200:
                    continue
                hist = hist.rename(columns=str.title).reset_index()
                date_col = "Date" if "Date" in hist.columns else hist.columns[0]
                hist = hist.rename(columns={date_col: "Date"})
                hist["Date"] = pd.to_datetime(hist["Date"]).dt.tz_localize(None)
                hist = hist[["Date", "Open", "High", "Low", "Close", "Volume"]]
                hist.to_csv(data_dir / f"{s}.csv", index=False)
                have.append(s)
                ok = True
                break
            except Exception:
                continue
        if not ok:
            still.append(s)
    print(f"[VZ-h1-univ] have={len(have)} failed={len(still)}", flush=True)
    return have, still


def process_symbol(sym: str, data_dir: Path) -> dict:
    csv_path = data_dir / f"{sym}.csv"
    if not csv_path.is_file():
        return {"symbol": sym, "status": "missing", "rows": [], "note": "no csv"}
    try:
        df = load_ohlcv(csv_path)
        params = replace(RESEARCH_CANDIDATE_V2, entry_on="next_open")
        if len(df) <= params.lookback_days + 20:
            return {"symbol": sym, "status": "short", "rows": [], "note": f"n={len(df)}"}
        atr = atr14(df)
        zones = build_zones(df, params.lookback_days)
        zone_by_id = {z.zone_id: z for z in zones}
        rvol = rvol20(df["Volume"].to_numpy(dtype=np.float64))
        sigs, _, _ = run_symbol_with_params(sym, df, zones, atr, params)
        rows = enrich_signal_rows(sym, df, sigs, params, atr=atr, exit_spec=PRIMARY_EXIT)
        attach_playbook_fields(rows, sigs, df, zone_by_id, rvol, atr)
        return {"symbol": sym, "status": "ok", "rows": rows, "note": ""}
    except Exception as e:
        return {"symbol": sym, "status": "error", "rows": [], "note": str(e)[:200]}


def _worker(args: tuple[str, str]) -> dict:
    return process_symbol(args[0], Path(args[1]))


def _h1(rows: list[dict]) -> list[dict]:
    return _filter(
        rows,
        lambda r: _finite(r, "origin_rvol") and float(r["origin_rvol"]) >= RVOL_GATE,
    )


def _in_univ(rows: list[dict], symbols: set[str]) -> list[dict]:
    return [r for r in rows if str(r.get("symbol", "")).upper() in symbols]


def judge(ctrl: dict, arm: dict) -> str:
    """Pass/fail vs the DualPaul78 DD-gap bar. Not an adopt. Frozen 4.0."""
    if arm["n"] < 80 or arm["is_n"] < 50:
        return "FAIL (N too small)"
    dd_gap = float(ctrl["max_dd"]) - float(arm["max_dd"])
    wr_ok = float(arm["wr"]) >= float(ctrl["wr"]) - 0.03
    r_ok = float(arm["avg_r"]) >= float(ctrl["avg_r"]) - 0.05
    oos_hurt = float(arm["oos_avg_pnl"]) <= float(ctrl["oos_avg_pnl"]) - 0.75 or (
        int(arm["oos_n"]) >= 40 and float(arm["oos_wr"]) + 0.03 < float(ctrl["oos_wr"])
    )
    if dd_gap >= 12 and wr_ok and r_ok and not oos_hurt:
        return "PASS — DD gap survives"
    if dd_gap >= 6 and wr_ok and not oos_hurt:
        return "HOLD — calmer, gap shrinks"
    if dd_gap < 6:
        return "FAIL — DD gap gone (clustering)"
    return "FAIL — quality or OOS veto"


def _md_row(r: dict) -> str:
    return (
        f"| {r['universe']} | {r['arm']} | {r.get('lean', '')} | {int(r['n'])} | "
        f"{_fmt_pct(float(r['wr']))}% | {_fmt_num(float(r['avg_pnl']))} | "
        f"{_fmt_num(float(r['avg_r']))} | {_fmt_num(float(r['ann_ror']))} | "
        f"{_fmt_num(float(r['max_dd']))} | {_fmt_num(float(r['calmar']))} | "
        f"{int(r['is_n'])} | {_fmt_num(float(r['is_max_dd']))} | "
        f"{int(r['oos_n'])} | {_fmt_pct(float(r['oos_wr']))}% | "
        f"{_fmt_num(float(r['oos_avg_pnl']))} | {_fmt_num(float(r['oos_max_dd']))} |"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="H1 rvol>=4 broader-universe confirmation")
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 4))
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--symbols", default="", help="Optional comma list (overrides universe union)")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir) / args.stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    dp78 = [s.upper() for s in DUAL_PAUL78]
    pt = load_paultwenty()
    spx = load_spx500()
    print(f"[VZ-h1-univ] DualPaul78={len(dp78)} PaulTwenty={len(pt)} SPX={len(spx)}", flush=True)

    if args.symbols.strip():
        wanted = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        wanted = []
        seen: set[str] = set()
        for s in dp78 + pt + spx:
            if s not in seen:
                seen.add(s)
                wanted.append(s)

    if args.skip_download:
        have = [s for s in wanted if (data_dir / f"{s}.csv").is_file()]
        failed = [s for s in wanted if s not in have]
    else:
        have, failed = ensure_ohlcv(wanted, data_dir)
        have_set = set(have)
        have = [s for s in wanted if s in have_set]
    print(f"[VZ-h1-univ] runnable={len(have)} failed_download={len(failed)}", flush=True)

    t0 = time.time()
    rows: list[dict] = []
    status: list[dict] = []
    n_w = max(1, int(args.workers))
    jobs = [(s, str(data_dir)) for s in have]
    if n_w == 1:
        results = [_worker(j) for j in jobs]
        for i, res in enumerate(results, 1):
            print(f"  [{i}/{len(jobs)}] {res['symbol']} {res['status']} n={len(res['rows'])}", flush=True)
    else:
        results = []
        with ProcessPoolExecutor(max_workers=n_w) as ex:
            futs = [ex.submit(_worker, j) for j in jobs]
            for i, fut in enumerate(as_completed(futs), 1):
                res = fut.result()
                results.append(res)
                print(
                    f"  [{i}/{len(jobs)}] {res['symbol']} {res['status']} n={len(res['rows'])}",
                    flush=True,
                )
    for res in results:
        status.append(
            {
                "symbol": res["symbol"],
                "status": res["status"],
                "n": len(res["rows"]),
                "note": res.get("note", ""),
            }
        )
        rows.extend(res["rows"])
    rows = _closed_signal_rows(rows)
    print(f"[VZ-h1-univ] closed trades={len(rows)} in {time.time()-t0:.0f}s", flush=True)

    dp78_set = set(dp78)
    pt_set = set(pt)
    spx_set = set(spx) & set(have)
    universes: list[tuple[str, set[str], str]] = [
        ("DualPaul78", dp78_set, "original cluster (83 names)"),
        ("SPX500", spx_set, "current S&P 500 constituents (broader proxy for FullOHLC)"),
        ("SPX_ex_DP78", spx_set - dp78_set, "SPX500 minus DualPaul78 — clustering check"),
        ("DP78_in_SPX", dp78_set & spx_set, "DualPaul78 names that are also in SPX500"),
    ]
    if pt:
        universes.insert(1, ("PaulTwenty", pt_set, "drive/universes/PaulTwenty_universe.csv"))

    table: list[dict] = []
    verdicts: list[str] = []
    for uname, uset, note in universes:
        urows = _in_univ(rows, uset)
        ctrl = _metrics_row(f"{uname} CONTROL rw126", urows)
        h1 = _metrics_row(f"{uname} H1 rvol>=4", _h1(urows))
        lean = "control"
        h1_lean = judge(ctrl, h1) if ctrl["n"] else "FAIL (empty control)"
        for m, arm_lean, knob in (
            (ctrl, lean, f"rw126 control · {note}"),
            (h1, h1_lean, f"origin_rvol >= {RVOL_GATE} · {note}"),
        ):
            m = dict(m)
            m["universe"] = uname
            m["knob"] = knob
            m["lean"] = arm_lean
            table.append(m)
        n_ratio = 100.0 * h1["n"] / max(ctrl["n"], 1)
        dd_gap = float(ctrl["max_dd"]) - float(h1["max_dd"])
        line = (
            f"**{uname}:** {h1_lean} — control N={int(ctrl['n'])} Max DD {_fmt_num(float(ctrl['max_dd']))}% "
            f"vs H1 N={int(h1['n'])} ({_fmt_num(n_ratio, 0)}%) Max DD {_fmt_num(float(h1['max_dd']))}% "
            f"(gap {_fmt_num(dd_gap)} pp) Calmar {_fmt_num(float(h1['calmar']))} vs {_fmt_num(float(ctrl['calmar']))} "
            f"OOS N={int(h1['oos_n'])} PnL {_fmt_num(float(h1['oos_avg_pnl']))}%."
        )
        verdicts.append(line)
        print(
            f"  {uname:14s} CTRL N={ctrl['n']:5d} DD={ctrl['max_dd']:5.1f}  "
            f"H1 N={h1['n']:5d} DD={h1['max_dd']:5.1f} gap={dd_gap:5.1f}  {h1_lean}",
            flush=True,
        )

    pd.DataFrame(table).to_csv(out_dir / "compare_metrics.csv", index=False)
    pd.DataFrame(rows).to_csv(out_dir / "trades_rw126.csv", index=False)
    pd.DataFrame(status).to_csv(out_dir / "per_symbol_status.csv", index=False)
    (out_dir / "failed_download.txt").write_text("\n".join(failed) + ("\n" if failed else ""), encoding="utf-8")
    (out_dir / "SPX500_universe.csv").write_text("\n".join(spx) + "\n", encoding="utf-8")

    pt_note = (
        f"PaulTwenty loaded ({len(pt)} names)."
        if pt
        else "PaulTwenty_universe.csv is not in this environment (gitignored); skipped."
    )
    overall = "FAIL"
    spx_h1 = next((r for r in table if r["universe"] == "SPX500" and "H1" in r["arm"]), None)
    if spx_h1 and str(spx_h1["lean"]).startswith("PASS"):
        overall = "PASS"
    elif spx_h1 and str(spx_h1["lean"]).startswith("HOLD"):
        overall = "HOLD"
    ex_h1 = next((r for r in table if r["universe"] == "SPX_ex_DP78" and "H1" in r["arm"]), None)
    # Clustering veto only when the ex-DP78 sleeve is large enough to judge.
    if (
        ex_h1
        and int(ex_h1["n"]) >= 80
        and str(ex_h1["lean"]).startswith("FAIL")
    ):
        overall = "FAIL — gap does not survive outside DualPaul78"

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>H1 rvol≥4 universe confirm — {html_mod.escape(args.stamp)}</title>
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
<h1>H1 origin rvol ≥4 — broader-universe confirmation</h1>
<p class="muted">Research only · {html_mod.escape(args.stamp)} · frozen gate origin_rvol ≥ {RVOL_GATE} · rw126 · next_open · zone_atr05_ts40</p>
<div class="callout warn">
<strong>Not gold. Not DailyRun. Do not retune 4.0 on OOS.</strong>
Overall: <strong>{html_mod.escape(overall)}</strong>. {html_mod.escape(pt_note)}
Local FullOHLC / DailyRun dump is not in this environment; SPX500 is the broader proxy.
</div>
<ul>{"".join(f"<li>{html_mod.escape(v.replace('**',''))}</li>" for v in verdicts)}</ul>
<h2>Results</h2>
{_arm_table_html(table, "Control vs H1 rvol≥4 on each universe. Lean on H1 rows is the confirmation judge.")}
<p class="muted">Max DD is the house passive book path (fixed notional, PnL at exit, no OHLC MTM).
PASS requires ≥12pp Max DD gap vs that universe's control, WR/Avg R not collapsing, OOS not reversing.</p>
<footer class="muted">Twin Beacon Networks · VZ research · {html_mod.escape(args.stamp)}</footer>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    (out_dir / "VZ_H1_Rvol4_Universe_Confirm.html").write_text(html, encoding="utf-8")

    md = [
        "# H1 origin rvol ≥4 — broader-universe confirmation",
        "",
        "Research only. Frozen rule: `RESEARCH_CANDIDATE_V2` rw126, next_open, `zone_atr05_ts40`, "
        f"`origin_rvol >= {RVOL_GATE}`. **Do not retune 4.0 on OOS.**",
        "",
        f"## Verdict: {overall}",
        "",
        pt_note,
        "Local FullOHLC / DailyRun dump is not in this environment; **SPX500** is the broader-universe proxy.",
        "",
        *verdicts,
        "",
        "PASS bar: H1 Max DD at least **12pp** below that universe's rw126 control, WR/Avg R not collapsing, "
        "OOS not reversing. DualPaul78's gap was ~21pp (38.5% → 17.7%). A shrink to ~3pp is a fail.",
        "",
        "## Setup",
        "",
        f"Runnable symbols={len(have)} · failed download={len(failed)} · closed trades={len(rows)}.",
        "",
        "| Universe | Arm | Lean | N | WR% | Avg PnL% | Avg R | Book Ann ROR% | Max DD% | Calmar | IS N | IS Max DD% | OOS N | OOS WR% | OOS Avg PnL% | OOS Max DD% |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    md.extend(_md_row(r) for r in table)
    md += [
        "",
        "## Reproduce",
        "",
        "```",
        "python tools/vz_h1_rvol4_universe_confirm.py",
        "```",
        "",
        "Not gold. Not DailyRun. Do not retune on OOS.",
        "",
    ]
    text = "\n".join(md)
    (out_dir / "README.md").write_text(text, encoding="utf-8")
    docs = REPO / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "vz_h1_rvol4_universe_confirm.md").write_text(text, encoding="utf-8")
    (docs / "vz_h1_rvol4_universe_confirm.html").write_text(html, encoding="utf-8")
    pd.DataFrame(table).to_csv(docs / "vz_h1_rvol4_universe_confirm.csv", index=False)
    print(f"[VZ-h1-univ] overall={overall} wrote {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
