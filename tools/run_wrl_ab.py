#!/usr/bin/env python3
"""WRL one-knob A/B vs house control (scale 50/50, stop at swing low).

Arms match ``optimizer_systems.WRL_PLAN`` (one knob at a time; controls frozen).
Research only — does not change ``run_wrl.bat`` defaults.

Usage:
  python tools/run_wrl_ab.py
  python tools/run_wrl_ab.py --smoke
  python tools/run_wrl_ab.py --symbols AAPL,MSFT,NVDA
  python tools/run_wrl_ab.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "stock_analysis"))

from rocket_wrl import (  # noqa: E402
    WrlConfig,
    _run_wrl_symbol_tasks,
    _wrl_cfg_dict,
    brt_config_from_wrl,
    write_wrl_outputs,
)
from tbn_host_sizing import HostSizingConfig, apply_host_dollar_scale  # noqa: E402

MAG10 = ["AAPL", "AMD", "AMZN", "AU", "GOOGL", "META", "MSFT", "NFLX", "NVDA", "TSLA"]
DATA_DIR = REPO / "data" / "newdata" / "data"
OUT_ROOT = REPO / "drive" / "paul_experiments" / "wrl" / "ab_levers"
DOCS_COPY = REPO / "docs" / "systems" / "wrl_ab.html"

CONTROL = "00_control"
ARMS: list[tuple[str, dict[str, Any], str]] = [
    (CONTROL, {}, "House: scale 50/50, stop at swing low, min-zone off"),
    ("01_target_range", {"wrl_target_mode": "range"}, "Full size out at range high"),
    ("02_target_swing", {"wrl_target_mode": "swing"}, "Full size out at swing high"),
    ("03_scale_033", {"wrl_scale_frac": 0.33}, "Scale: 33% at range high, rest to swing high"),
    ("04_scale_067", {"wrl_scale_frac": 0.67}, "Scale: 67% at range high, rest to swing high"),
    ("05_stop_098", {"stop_pct": 0.98}, "Stop = 98% of swing low (tighter)"),
    ("06_stop_099", {"stop_pct": 0.99}, "Stop = 99% of swing low (slightly tighter)"),
    ("07_minzone_01", {"wrl_min_zone_pct": 0.01}, "Require demand zone ≥ 1% wide"),
    ("08_minzone_02", {"wrl_min_zone_pct": 0.02}, "Require demand zone ≥ 2% wide"),
]


def _ensure_ohlcv(symbols: list[str], data_dir: Path) -> list[str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    missing = [s for s in symbols if not (data_dir / f"{s}.csv").is_file()]
    if not missing:
        return symbols
    print(f"[WRL-AB] Downloading {len(missing)} symbols via yfinance: {','.join(missing)}", flush=True)
    import yfinance as yf

    kept: list[str] = []
    for sym in symbols:
        dest = data_dir / f"{sym}.csv"
        if dest.is_file():
            kept.append(sym)
            continue
        try:
            raw = yf.download(sym, period="max", auto_adjust=False, progress=False, threads=False)
        except Exception as e:
            print(f"[WRL-AB] skip {sym}: download failed ({e})", flush=True)
            continue
        if raw is None or raw.empty:
            print(f"[WRL-AB] skip {sym}: empty download", flush=True)
            continue
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [str(c[0]).strip() for c in raw.columns]
        raw = raw.reset_index()
        colmap = {str(c).strip().title(): c for c in raw.columns}
        date_col = colmap.get("Date") or colmap.get("Datetime") or raw.columns[0]
        out = pd.DataFrame(
            {
                "Date": pd.to_datetime(raw[date_col]).dt.strftime("%Y-%m-%d"),
                "Open": pd.to_numeric(raw[colmap.get("Open", "Open")], errors="coerce"),
                "High": pd.to_numeric(raw[colmap.get("High", "High")], errors="coerce"),
                "Low": pd.to_numeric(raw[colmap.get("Low", "Low")], errors="coerce"),
                "Close": pd.to_numeric(raw[colmap.get("Close", "Close")], errors="coerce"),
            }
        )
        vol_key = colmap.get("Volume")
        if vol_key is not None:
            out["Volume"] = pd.to_numeric(raw[vol_key], errors="coerce")
        out = out.dropna(subset=["Open", "High", "Low", "Close"])
        if len(out) < 40:
            print(f"[WRL-AB] skip {sym}: only {len(out)} bars", flush=True)
            continue
        out.to_csv(dest, index=False)
        print(f"[WRL-AB] wrote {dest} ({len(out)} bars)", flush=True)
        kept.append(sym)
    return kept


def _load_symbol(sym: str, data_dir: Path) -> Optional[pd.DataFrame]:
    path = data_dir / f"{sym}.csv"
    if not path.is_file():
        return None
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    for c in ("Open", "High", "Low", "Close"):
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Volume" in df.columns:
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df if len(df) >= 40 else None


def _host_cfg() -> HostSizingConfig:
    return HostSizingConfig(
        brt_cash=47_500.0,
        initial_capital=500_000.0,
        aggressive_max_multiple=2.0,
        margin_utilization=0.6,
        max_positions=0,
        aggressive=False,
        aggressive_margin_interest=0.10,
        aggressive_avg_positions=0.0,
        aggressive_sizing_equity_cap=10.0,
        aggressive_sell="false",
        equity_fast_aggressive=True,
    )


def _run_arm(
    arm: str,
    overrides: dict[str, Any],
    symbols: list[str],
    frames: dict[str, pd.DataFrame],
    workers: int,
) -> Path:
    arm_dir = OUT_ROOT / arm
    if arm_dir.exists():
        shutil.rmtree(arm_dir)
    arm_dir.mkdir(parents=True, exist_ok=True)
    cfg = WrlConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    tasks = [(sym, frames[sym], _wrl_cfg_dict(cfg)) for sym in symbols if sym in frames]
    t0 = time.time()
    results = _run_wrl_symbol_tasks(tasks, workers)
    closed, opens, watch, scanner = [], [], [], []
    for res in results:
        closed.extend(res.closed)
        opens.extend(res.open_rows)
        watch.extend(res.watch)
        scanner.extend(res.scanner)
    closed.sort(key=lambda r: (r.date_opened, r.symbol))
    hcfg = _host_cfg()
    host_meta: dict[str, Any] = {}
    if closed:
        adj, scale, max_pos = apply_host_dollar_scale(closed, opens, hcfg)
        cfg.brt_cash = adj
        host_meta = {
            "host_max_positions": max_pos,
            "host_brt_cash": adj,
            "host_pnl_scale": scale,
        }
    ts = time.strftime("%y%m%d%H%M%S")
    write_wrl_outputs(
        arm_dir,
        ts,
        closed,
        opens,
        watch,
        scanner,
        cfg,
        host_meta=host_meta,
        tickers=frames,
        host_cfg=hcfg,
        tbn_cfg=brt_config_from_wrl(cfg, None),
        no_yfinance=True,
    )
    (arm_dir / "STAMP.txt").write_text(
        f"stamp={ts}\narm={arm}\noverrides={overrides}\nsymbols={','.join(symbols)}\n"
        f"elapsed_s={time.time() - t0:.1f}\n",
        encoding="utf-8",
    )
    print(
        f"[WRL-AB] {arm}: {len(closed)} closed / {len(opens)} open  ({time.time() - t0:.1f}s) -> {arm_dir}",
        flush=True,
    )
    return arm_dir


def _safe_num(x: Any) -> float:
    if x is None or x == "" or str(x).strip().upper() == "N/A":
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _latest(arm_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(arm_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _arm_metrics(arm_dir: Path) -> dict[str, Any]:
    note = next((n for a, _, n in ARMS if a == arm_dir.name), "")
    out: dict[str, Any] = {
        "arm": arm_dir.name,
        "note": note,
        "stamp": "",
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "pnl": 0.0,
        "pf": 0.0,
        "exp": 0.0,
        "avg_pnl_pct": 0.0,
        "avg_days": 0.0,
        "ann_ror": 0.0,
        "max_dd": 0.0,
        "ok": False,
    }
    stamp_p = arm_dir / "STAMP.txt"
    if stamp_p.exists():
        for line in stamp_p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("stamp="):
                out["stamp"] = line.split("=", 1)[1].strip()
    aud = _latest(arm_dir, "WRL_Audit_Report_*.csv")
    if not aud:
        return out
    with aud.open(newline="", encoding="utf-8-sig", errors="replace") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return out
    out["ok"] = True
    out["trades"] = int(_safe_num(row.get("Total_Trades")))
    out["wins"] = int(_safe_num(row.get("Wins")))
    out["losses"] = int(_safe_num(row.get("Losses")))
    tot = out["wins"] + out["losses"] + int(_safe_num(row.get("BE")))
    out["wr"] = (100.0 * out["wins"] / tot) if tot else _safe_num(row.get("Pct_Wins"))
    out["pnl"] = _safe_num(row.get("Total_PNL"))
    out["pf"] = _safe_num(row.get("Profit_Factor"))
    out["exp"] = _safe_num(row.get("Expectancy"))
    out["avg_pnl_pct"] = _safe_num(row.get("Avg_PNL_Pct"))
    out["avg_days"] = _safe_num(row.get("Avg_Days_Held"))
    out["ann_ror"] = _safe_num(row.get("Ann_ROR"))
    out["max_dd"] = _safe_num(row.get("Max_DD"))
    if not out["stamp"]:
        out["stamp"] = aud.stem.split("_")[-1]
    return out


def summarize(root: Path = OUT_ROOT) -> Path:
    rows = []
    for arm, _, _ in ARMS:
        d = root / arm
        if d.is_dir():
            rows.append(_arm_metrics(d))
    ctrl = next((r for r in rows if r["arm"] == CONTROL), None)

    def delta(r: dict[str, Any], key: str) -> float:
        if not (ctrl and ctrl["ok"] and r["ok"]):
            return 0.0
        return float(r[key]) - float(ctrl[key])

    hdr = (
        f"{'arm':18} {'trades':>7} {'WR%':>6} {'PnL$':>12} {'PF':>6} "
        f"{'Exp$':>8} {'avg%':>7} {'AnnROR':>8} {'MaxDD':>7} {'dPnL$':>12}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['arm']:18} {r['trades']:7d} {r['wr']:6.1f} {r['pnl']:12.0f} {r['pf']:6.2f} "
            f"{r['exp']:8.0f} {r['avg_pnl_pct']:7.2f} {r['ann_ror']:8.1f} {r['max_dd']:7.2f} "
            f"{delta(r, 'pnl'):12.0f}"
        )

    md = [
        "# WRL A/B — one-knob levers vs house control",
        "",
        "Universe: Mag10 (`AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA`).",
        "Control: `wrl_target_mode=scale`, `wrl_scale_frac=0.50`, `stop_pct=1.0`, `wrl_min_zone_pct=0`.",
        "Host cash scaled like `run_wrl.bat` (500k × 2.0 × 0.6). Aggressive equity off for the A/B.",
        "Research only — `run_wrl.bat` defaults unchanged.",
        "",
        "| Arm | What changed | Trades | WR% | Total PnL $ | PF | Expectancy $ | Avg PnL% | Ann ROR | Max DD | Δ PnL $ | Δ Trades |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md.append(
            f"| `{r['arm']}` | {r['note']} | {r['trades']} | {r['wr']:.1f} | "
            f"{r['pnl']:.0f} | {r['pf']:.2f} | {r['exp']:.0f} | {r['avg_pnl_pct']:.2f} | "
            f"{r['ann_ror']:.1f} | {r['max_dd']:.2f} | {delta(r, 'pnl'):+.0f} | "
            f"{delta(r, 'trades'):+.0f} |"
        )

    winner = None
    if ctrl and ctrl["ok"]:
        cands = [r for r in rows if r["ok"] and r["arm"] != CONTROL]
        if cands:
            winner = max(cands, key=lambda r: r["pnl"])
            beat = winner["pnl"] > ctrl["pnl"]
            dd_note = ""
            if winner["max_dd"] > ctrl["max_dd"] + 5:
                dd_note = (
                    f" **Max DD is worse** ({winner['max_dd']:.1f} vs control {ctrl['max_dd']:.1f}) "
                    "— do not adopt on PnL alone."
                )
            md.extend(
                [
                    "",
                    "## Verdict",
                    "",
                    f"- Control PnL: **{ctrl['pnl']:.0f}** ({ctrl['trades']} trades, WR {ctrl['wr']:.1f}%, PF {ctrl['pf']:.2f}, Max DD {ctrl['max_dd']:.1f}).",
                    f"- Best arm by Total PnL: **`{winner['arm']}`** ({winner['pnl']:.0f}, Δ {winner['pnl'] - ctrl['pnl']:+.0f}).",
                    (
                        f"- **`{winner['arm']}` beat control on Total PnL.** Still research — Mag10 only, no walk-forward.{dd_note}"
                        if beat
                        else f"- **No arm beat control on Total PnL.** Keep house `{CONTROL}`."
                    ),
                ]
            )

    (root / "README.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    def th(label: str, sort: str) -> str:
        return (
            f'<th class="sortable-th" data-sort="{sort}" tabindex="0">'
            f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
        )

    body_rows = []
    for r in rows:
        cls = "ctrl" if r["arm"] == CONTROL else ""
        body_rows.append(
            f"<tr class='{cls}'>"
            f"<td><code>{html.escape(r['arm'])}</code></td>"
            f"<td>{html.escape(r['note'])}</td>"
            f"<td>{r['trades']}</td><td>{r['wr']:.1f}</td>"
            f"<td>{r['pnl']:.0f}</td><td>{r['pf']:.2f}</td><td>{r['exp']:.0f}</td>"
            f"<td>{r['avg_pnl_pct']:.2f}</td><td>{r['ann_ror']:.1f}</td><td>{r['max_dd']:.2f}</td>"
            f"<td>{delta(r, 'pnl'):+.0f}</td><td>{delta(r, 'trades'):+.0f}</td>"
            "</tr>"
        )
    verdict_html = ""
    if ctrl and winner:
        beat = winner["pnl"] > ctrl["pnl"]
        dd_bit = ""
        if winner["max_dd"] > ctrl["max_dd"] + 5:
            dd_bit = (
                f" Max DD is worse ({winner['max_dd']:.1f} vs {ctrl['max_dd']:.1f}) — do not adopt on PnL alone."
            )
        verdict_html = (
            f"<div class='callout {'ok' if beat else 'warn'}'>"
            f"<strong>Verdict:</strong> control PnL {ctrl['pnl']:.0f} (Max DD {ctrl['max_dd']:.1f}). "
            f"Best arm <code>{html.escape(winner['arm'])}</code> at {winner['pnl']:.0f} "
            f"(Δ {winner['pnl'] - ctrl['pnl']:+.0f}). "
            f"{'Beat control on Total PnL — still research (Mag10, no walk-forward).' if beat else 'No arm beat control on Total PnL.'}"
            f"{html.escape(dd_bit)}"
            "</div>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>WRL A/B — one-knob levers</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px;max-width:1100px;color:#1a1a1a}}
h1{{font-size:1.4rem;margin:0 0 .4em}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}
th,td{{border:1px solid #cbd5e1;padding:6px 8px;text-align:left}}
thead{{background:#f1f5f9}}
tr.ctrl{{background:#ecfdf5}}
.callout{{padding:10px 14px;margin:14px 0;border-left:4px solid #3b82f6;background:#eff6ff}}
.callout.ok{{border-left-color:#10b981;background:#ecfdf5}}
.callout.warn{{border-left-color:#f97316;background:#fff7ed}}
.muted{{color:#64748b;font-size:13px}}
code{{background:#f4f4f5;padding:1px 5px}}
th.sortable-th{{cursor:pointer}}
</style>
</head><body>
<p class="muted"><a href="wrl.html">&larr; WRL system description</a></p>
<h1>WRL A/B — one-knob levers vs house control</h1>
<p class="muted">Mag10 · control = scale 50/50, stop at swing low, min-zone off. Research only.</p>
{verdict_html}
<table class="sortable">
<thead><tr>
{th("Arm","text")}{th("What changed","text")}{th("Trades","num")}{th("WR%","num")}
{th("Total PnL $","num")}{th("PF","num")}{th("Expectancy $","num")}{th("Avg PnL%","num")}
{th("Ann ROR","num")}{th("Max DD","num")}{th("Δ PnL $","num")}{th("Δ Trades","num")}
</tr></thead>
<tbody>
{"".join(body_rows)}
</tbody></table>
<p class="muted">Generated by <code>tools/run_wrl_ab.py</code>. Local copies under
<code>drive/paul_experiments/wrl/ab_levers/</code>.</p>
<script>
(function(){{
  function parseCell(td,type){{
    var t=(td.textContent||"").trim().replace(/[$,%+]/g,"").replace(/,/g,"");
    if(type==="num"){{var n=parseFloat(t); return isNaN(n)?null:n;}}
    return t.toLowerCase();
  }}
  document.querySelectorAll("table.sortable").forEach(function(table){{
    table.querySelectorAll("th.sortable-th").forEach(function(th, colIdx){{
      th.addEventListener("click", function(){{
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        table.querySelectorAll("th.sortable-th").forEach(function(x){{x.classList.remove("sort-asc","sort-desc");}});
        th.classList.add(asc?"sort-asc":"sort-desc");
        var tbody=table.tBodies[0];
        var rows=[].slice.call(tbody.querySelectorAll("tr"));
        rows.sort(function(a,b){{
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        }});
        rows.forEach(function(r){{tbody.appendChild(r);}});
      }});
    }});
  }});
}})();
</script>
</body></html>
"""
    html_path = root / "comparison.html"
    html_path.write_text(page, encoding="utf-8")
    DOCS_COPY.parent.mkdir(parents=True, exist_ok=True)
    DOCS_COPY.write_text(page, encoding="utf-8")
    print(f"[WRL-AB] Wrote {html_path}", flush=True)
    print(f"[WRL-AB] Pages copy {DOCS_COPY}", flush=True)
    return html_path


def main() -> int:
    ap = argparse.ArgumentParser(description="WRL one-knob A/B vs house control")
    ap.add_argument("--symbols", default="", help="Comma list (default Mag10)")
    ap.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 4)))
    ap.add_argument("--smoke", action="store_true", help="Control arm only")
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    args = ap.parse_args()
    if args.summarize_only:
        summarize()
        return 0
    symbols = [s.strip().upper() for s in (args.symbols or ",".join(MAG10)).split(",") if s.strip()]
    data_dir = Path(args.data_dir)
    symbols = _ensure_ohlcv(symbols, data_dir)
    frames: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = _load_symbol(sym, data_dir)
        if df is None:
            print(f"[WRL-AB] skip {sym}: could not load", flush=True)
            continue
        frames[sym] = df
    if not frames:
        print("[WRL-AB] no symbol data — abort", flush=True)
        return 1
    print(f"[WRL-AB] {len(frames)} symbols, {args.workers} workers", flush=True)
    arms = ARMS[:1] if args.smoke else ARMS
    for arm, overrides, _note in arms:
        _run_arm(arm, overrides, list(frames), frames, int(args.workers))
    summarize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
