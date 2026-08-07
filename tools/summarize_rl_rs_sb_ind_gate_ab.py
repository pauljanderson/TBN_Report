#!/usr/bin/env python3
"""RL / RS / SB × IND-style gate A/B (post-filter + optional live-arm folders).

Primary path: post-hoc filter Closed books by trade-aligned IND_DIFF (and a couple
of easy IND-style companions). RS Closed already stamps IND_DIFF when
use_indicators=true; RL/SB get IND_DIFF attached from OHLCV + brt_entry_indicators
cache at the trigger bar (session before DATE_OPENED / DATE OPENED).

This does **not** re-simulate portfolio concurrency / host sizing — metrics are
trade-book aggregates (count, win rate, sum/avg PNL%) vs each system's control.

Usage:
  python tools/summarize_rl_rs_sb_ind_gate_ab.py
  python tools/summarize_rl_rs_sb_ind_gate_ab.py --postfilter-only
  python tools/summarize_rl_rs_sb_ind_gate_ab.py --rl-closed drive/RL_Closed_….csv \\
      --rs-closed drive/RS_Closed_….csv --sb-closed drive/SB_Closed_….csv
  python tools/summarize_rl_rs_sb_ind_gate_ab.py --root drive/paul_experiments/rl_rs_sb_ind_gate_ab
"""
from __future__ import annotations

import argparse
import csv
import html
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stock_analysis"))

DEFAULT_OUT = ROOT / "drive" / "paul_experiments" / "rl_rs_sb_ind_gate_ab"
DATA_DIR = ROOT / "data" / "newdata" / "data"
CACHE_DIR = DATA_DIR / ".brt_indicator_cache"

# IND production uses indicator_diff=7; RS Closed IND_DIFF med≈14 / mean≈13.
IND_DIFF_THRESHOLDS = (0, 5, 7, 10, 12)

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORTABLE_TABLE_SCRIPT = """
(function(){
  function parseCell(td, type){
    var t=(td.textContent||"").trim().replace(/[$,%]/g,"").replace(/,/g,"");
    if(type==="num"){var n=parseFloat(t); return isNaN(n)?null:n;}
    if(type==="date"||type==="month"){return t;}
    return t.toLowerCase();
  }
  function bind(table){
    var ths=table.querySelectorAll("th.sortable-th");
    ths.forEach(function(th, colIdx){
      th.addEventListener("click", function(){
        var type=th.getAttribute("data-sort")||"text";
        var asc=!th.classList.contains("sort-asc");
        ths.forEach(function(x){x.classList.remove("sort-asc","sort-desc"); x.setAttribute("aria-sort","none");});
        th.classList.add(asc?"sort-asc":"sort-desc");
        th.setAttribute("aria-sort", asc?"ascending":"descending");
        var tbody=table.tBodies[0]; if(!tbody) return;
        var rows=[].slice.call(tbody.querySelectorAll("tr")).filter(function(r){return !r.classList.contains("total-row");});
        rows.sort(function(a,b){
          var av=parseCell(a.children[colIdx], type), bv=parseCell(b.children[colIdx], type);
          if(av==null&&bv==null) return 0;
          if(av==null) return 1; if(bv==null) return -1;
          if(av<bv) return asc?-1:1; if(av>bv) return asc?1:-1; return 0;
        });
        rows.forEach(function(r){tbody.appendChild(r);});
      });
      th.addEventListener("keydown", function(e){
        if(e.key==="Enter"||e.key===" "){e.preventDefault(); th.click();}
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


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


def _ymd8(v: Any) -> str:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())
    return s[:8] if len(s) >= 8 else ""


def _latest(drive: Path, pattern: str) -> Optional[Path]:
    files = sorted(drive.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _col(row: dict[str, str], *names: str) -> str:
    lower = {str(k).strip().lower(): k for k in row.keys()}
    for n in names:
        k = lower.get(n.lower())
        if k is not None:
            return str(row.get(k, "") or "")
    return ""


def _pnl_pct(row: dict[str, str]) -> float:
    return _safe_num(_col(row, "PNL_PCT", "PNL %", "PNL%"))


def _pnl_dollars(row: dict[str, str]) -> Optional[float]:
    raw = _col(row, "PNL_DOLLARS", "PNL_DOLLARS".lower(), "PNL")
    if not raw.strip():
        return None
    return _safe_num(raw)


def _symbol(row: dict[str, str]) -> str:
    return _col(row, "SYMBOL", "Symbol").strip().upper()


def _date_opened(row: dict[str, str]) -> str:
    return _ymd8(_col(row, "DATE_OPENED", "DATE OPENED", "Date Opened"))


def _load_closed(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    n = len(rows)
    pnls = [_pnl_pct(r) for r in rows]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    wr = (100.0 * wins / n) if n else 0.0
    avg = (sum(pnls) / n) if n else 0.0
    sum_pct = sum(pnls)
    dollar_vals = [_pnl_dollars(r) for r in rows]
    dollars_ok = [d for d in dollar_vals if d is not None]
    sum_dollars = sum(dollars_ok) if len(dollars_ok) == n and n else None
    ind_vals = []
    for r in rows:
        raw = _col(r, "IND_DIFF").strip()
        if raw:
            try:
                ind_vals.append(float(raw))
            except ValueError:
                pass
    return {
        "trades": n,
        "wins": wins,
        "losses": losses,
        "wr": wr,
        "avg_pnl_pct": avg,
        "sum_pnl_pct": sum_pct,
        "sum_pnl_dollars": sum_dollars,
        "ind_diff_n": len(ind_vals),
        "ind_diff_mean": (sum(ind_vals) / len(ind_vals)) if ind_vals else None,
        "ind_diff_med": (
            sorted(ind_vals)[len(ind_vals) // 2] if ind_vals else None
        ),
    }


def _attach_ind_diff(
    rows: list[dict[str, str]],
    *,
    data_dir: Path,
    cache_dir: Path,
    workers: int = 4,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Ensure each row has IND_DIFF (and IND_ENTRY_NEUTRAL_N / IND_SCORE when computable)."""
    already = sum(1 for r in rows if _col(r, "IND_DIFF").strip() != "")
    if already == len(rows) and rows:
        return rows, {"mode": "column_present", "attached": 0, "missing": 0}

    try:
        from brt_entry_indicators import (  # type: ignore
            aligned_bull_bear_diff,
            build_entry_indicator_precompute,
            entry_neutral_n,
            snapshot_for_entry,
        )
        from rocket_tbn import load_csv  # type: ignore
    except ImportError:
        from stock_analysis.brt_entry_indicators import (  # type: ignore
            aligned_bull_bear_diff,
            build_entry_indicator_precompute,
            entry_neutral_n,
            snapshot_for_entry,
        )
        from stock_analysis.rocket_tbn import load_csv  # type: ignore

    by_sym: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_sym[_symbol(r)].append(r)

    attached = 0
    missing = 0
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _enrich_sym(sym: str, tlist: list[dict[str, str]]) -> tuple[int, int]:
        ok = miss = 0
        if not sym or sym == "SPY":
            return 0, len(tlist)
        csv_path = data_dir / f"{sym}.csv"
        if not csv_path.exists():
            return 0, len(tlist)
        try:
            df = load_csv(str(csv_path))
        except Exception:
            return 0, len(tlist)
        pre = build_entry_indicator_precompute(
            df, symbol=sym, cache_dir=cache_dir, use_cache=True
        )
        if pre is None:
            return 0, len(tlist)
        # Map YYYYMMDD -> bar index
        date_to_i: dict[str, int] = {}
        pre_dates = getattr(pre, "dates", None)
        if pre_dates is not None:
            for i, d in enumerate(pre_dates):
                try:
                    ds = str(int(d)) if not isinstance(d, str) else _ymd8(d)
                except (TypeError, ValueError):
                    ds = _ymd8(d)
                if len(ds) >= 8:
                    date_to_i[ds[:8]] = i
        # Also from df index
        try:
            for i, ts in enumerate(df.index):
                ymd = ts.strftime("%Y%m%d") if hasattr(ts, "strftime") else _ymd8(ts)
                if ymd:
                    date_to_i[ymd] = i
        except Exception:
            pass

        for r in tlist:
            if _col(r, "IND_DIFF").strip():
                ok += 1
                continue
            entry = _date_opened(r)
            if not entry or entry not in date_to_i:
                miss += 1
                continue
            entry_i = date_to_i[entry]
            trig_i = entry_i - 1
            if trig_i < 0:
                miss += 1
                continue
            side = (_col(r, "SIDE", "side") or "LONG").strip().upper() or "LONG"
            diff = aligned_bull_bear_diff(pre, trig_i, side)
            if diff is None:
                miss += 1
                continue
            r["IND_DIFF"] = str(int(diff))
            neut = entry_neutral_n(pre, trig_i, side)
            if neut is not None and not _col(r, "IND_ENTRY_NEUTRAL_N").strip():
                r["IND_ENTRY_NEUTRAL_N"] = str(int(neut))
            if not _col(r, "IND_SCORE").strip():
                snap = snapshot_for_entry(pre, trig_i, side)
                if snap.get("IND_SCORE"):
                    r["IND_SCORE"] = snap["IND_SCORE"]
            ok += 1
        return ok, miss

    # Serial is fine (disk cache); optional thread pool for many symbols
    from concurrent.futures import ThreadPoolExecutor, as_completed

    syms = [(s, lst) for s, lst in by_sym.items() if s]
    n_workers = max(1, min(int(workers or 1), 8, len(syms) or 1))
    if n_workers > 1 and len(syms) > 1:
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(_enrich_sym, s, lst) for s, lst in syms]
            for fut in as_completed(futs):
                a, m = fut.result()
                attached += a
                missing += m
    else:
        for s, lst in syms:
            a, m = _enrich_sym(s, lst)
            attached += a
            missing += m

    return rows, {
        "mode": "enriched",
        "attached": attached,
        "missing": missing,
        "symbols": len(syms),
    }


def _passes(row: dict[str, str], gate: str) -> bool:
    if gate == "control":
        return True
    if gate.startswith("ind_diff_ge_"):
        thr = float(gate.split("_")[-1])
        raw = _col(row, "IND_DIFF").strip()
        if not raw:
            return False
        return float(raw) >= thr
    if gate == "ind_neutral_le_30":
        raw = _col(row, "IND_ENTRY_NEUTRAL_N").strip()
        if not raw:
            return False
        return float(raw) <= 30
    if gate == "spy_ind_diff_ge_0":
        raw = _col(row, "SPY_IND_DIFF").strip()
        if not raw:
            return False
        return float(raw) >= 0
    return False


def _gate_defs() -> list[tuple[str, str]]:
    out = [("control", "No IND overlay (full Closed book)")]
    for x in IND_DIFF_THRESHOLDS:
        out.append(
            (
                f"ind_diff_ge_{x}",
                f"Trade-aligned IND_DIFF >= {x} at trigger bar "
                f"(IND production uses indicator_diff=7)",
            )
        )
    out.append(
        (
            "ind_neutral_le_30",
            "IND_ENTRY_NEUTRAL_N <= 30 (IND max_ind_entry_neutral_n); "
            "skipped when column unavailable after enrich",
        )
    )
    out.append(
        (
            "spy_ind_diff_ge_0",
            "SPY_IND_DIFF >= 0 on entry (market-aligned count); "
            "skipped when column empty",
        )
    )
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def build_report(
    systems: dict[str, tuple[Path, list[dict[str, str]], dict[str, Any]]],
    out_dir: Path,
) -> Path:
    gate_defs = _gate_defs()
    cmp_rows: list[dict[str, Any]] = []

    for sys_name, (src, rows, enrich_meta) in systems.items():
        ctrl = [r for r in rows if _passes(r, "control")]
        ctrl_m = _metrics(ctrl)
        for gate, desc in gate_defs:
            filtered = [r for r in rows if _passes(r, gate)]
            # Skip companion gates that never fire (no data)
            if gate != "control" and not filtered and gate in (
                "ind_neutral_le_30",
                "spy_ind_diff_ge_0",
            ):
                # still record skipped
                cmp_rows.append(
                    {
                        "system": sys_name,
                        "gate": gate,
                        "gate_desc": desc,
                        "source": str(src),
                        "enrich_mode": enrich_meta.get("mode", ""),
                        "trades": 0,
                        "wr": "",
                        "avg_pnl_pct": "",
                        "sum_pnl_pct": "",
                        "sum_pnl_dollars": "",
                        "d_trades_vs_ctrl": "",
                        "d_wr_vs_ctrl": "",
                        "d_avg_pnl_pct_vs_ctrl": "",
                        "d_sum_pnl_pct_vs_ctrl": "",
                        "beats_ctrl_avg_pnl": "",
                        "skipped": "no_column_or_no_pass",
                        "ind_diff_mean": "",
                        "ind_diff_med": "",
                    }
                )
                continue
            m = _metrics(filtered)
            d_tr = m["trades"] - ctrl_m["trades"]
            d_wr = m["wr"] - ctrl_m["wr"]
            d_avg = m["avg_pnl_pct"] - ctrl_m["avg_pnl_pct"]
            d_sum = m["sum_pnl_pct"] - ctrl_m["sum_pnl_pct"]
            beats = ""
            if gate != "control" and m["trades"] > 0:
                beats = "yes" if m["avg_pnl_pct"] > ctrl_m["avg_pnl_pct"] else "no"
            cmp_rows.append(
                {
                    "system": sys_name,
                    "gate": gate,
                    "gate_desc": desc,
                    "source": str(src),
                    "enrich_mode": enrich_meta.get("mode", ""),
                    "trades": m["trades"],
                    "wr": round(m["wr"], 2),
                    "avg_pnl_pct": round(m["avg_pnl_pct"], 3),
                    "sum_pnl_pct": round(m["sum_pnl_pct"], 2),
                    "sum_pnl_dollars": (
                        round(m["sum_pnl_dollars"], 2)
                        if m["sum_pnl_dollars"] is not None
                        else ""
                    ),
                    "d_trades_vs_ctrl": d_tr if gate != "control" else 0,
                    "d_wr_vs_ctrl": round(d_wr, 2) if gate != "control" else 0,
                    "d_avg_pnl_pct_vs_ctrl": round(d_avg, 3) if gate != "control" else 0,
                    "d_sum_pnl_pct_vs_ctrl": round(d_sum, 2) if gate != "control" else 0,
                    "beats_ctrl_avg_pnl": beats,
                    "skipped": "",
                    "ind_diff_mean": _fmt(m["ind_diff_mean"]),
                    "ind_diff_med": _fmt(m["ind_diff_med"]),
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "comparison.csv"
    fields = [
        "system",
        "gate",
        "gate_desc",
        "trades",
        "wr",
        "avg_pnl_pct",
        "sum_pnl_pct",
        "sum_pnl_dollars",
        "d_trades_vs_ctrl",
        "d_wr_vs_ctrl",
        "d_avg_pnl_pct_vs_ctrl",
        "d_sum_pnl_pct_vs_ctrl",
        "beats_ctrl_avg_pnl",
        "ind_diff_mean",
        "ind_diff_med",
        "enrich_mode",
        "source",
        "skipped",
    ]
    _write_csv(csv_path, cmp_rows, fields)

    # Verdicts per system (best avg PNL% among IND_DIFF gates with trades)
    verdict_lines: list[str] = []
    for sys_name in ("RL", "RS", "SB"):
        sys_rows = [r for r in cmp_rows if r["system"] == sys_name and not r.get("skipped")]
        ctrl = next((r for r in sys_rows if r["gate"] == "control"), None)
        diff_rows = [
            r
            for r in sys_rows
            if str(r["gate"]).startswith("ind_diff_ge_") and int(r["trades"] or 0) > 0
        ]
        if not ctrl:
            verdict_lines.append(f"<li><strong>{sys_name}</strong>: no Closed book loaded.</li>")
            continue
        if not diff_rows:
            verdict_lines.append(
                f"<li><strong>{sys_name}</strong>: no IND_DIFF-gated trades "
                f"(enrich missing?).</li>"
            )
            continue
        best = max(diff_rows, key=lambda r: float(r["avg_pnl_pct"]))
        helped = [
            r
            for r in diff_rows
            if float(r["avg_pnl_pct"]) > float(ctrl["avg_pnl_pct"])
        ]
        if helped:
            top = max(helped, key=lambda r: float(r["avg_pnl_pct"]) - float(ctrl["avg_pnl_pct"]))
            verdict_lines.append(
                f"<li><strong>{sys_name}</strong>: IND_DIFF helped — best "
                f"<code>{html.escape(str(top['gate']))}</code> avg PNL% "
                f"{top['avg_pnl_pct']} vs control {ctrl['avg_pnl_pct']} "
                f"(Δ {float(top['avg_pnl_pct']) - float(ctrl['avg_pnl_pct']):+.3f}); "
                f"trades {top['trades']} vs {ctrl['trades']}.</li>"
            )
        else:
            verdict_lines.append(
                f"<li><strong>{sys_name}</strong>: IND_DIFF did <em>not</em> raise avg PNL% "
                f"vs control (control {ctrl['avg_pnl_pct']}; best gated "
                f"<code>{html.escape(str(best['gate']))}</code> = {best['avg_pnl_pct']}).</li>"
            )

    body = []
    for r in cmp_rows:
        skip = str(r.get("skipped") or "")
        cls = " skipped" if skip else ""
        body.append(
            f"<tr class='{cls}'>"
            f"<td>{html.escape(str(r['system']))}</td>"
            f"<td><code>{html.escape(str(r['gate']))}</code></td>"
            f"<td class='num'>{r['trades']}</td>"
            f"<td class='num'>{r['wr']}</td>"
            f"<td class='num'>{r['avg_pnl_pct']}</td>"
            f"<td class='num'>{r['sum_pnl_pct']}</td>"
            f"<td class='num'>{r['sum_pnl_dollars']}</td>"
            f"<td class='num'>{r['d_trades_vs_ctrl']}</td>"
            f"<td class='num'>{r['d_avg_pnl_pct_vs_ctrl']}</td>"
            f"<td>{html.escape(str(r['beats_ctrl_avg_pnl']))}</td>"
            f"<td class='num'>{r['ind_diff_med']}</td>"
            f"<td>{html.escape(skip)}</td>"
            "</tr>"
        )

    enrich_notes = []
    for sys_name, (src, _rows, meta) in systems.items():
        enrich_notes.append(
            f"<li><strong>{html.escape(sys_name)}</strong>: "
            f"<code>{html.escape(str(src))}</code> — enrich "
            f"{html.escape(str(meta))}</li>"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>RL / RS / SB × IND gate A/B</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;line-height:1.45;color:#1a1a1a;max-width:1200px}}
h1{{font-size:1.45rem}} h2{{font-size:1.1rem;margin-top:1.6rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}}
th,td{{border:1px solid #ccc;padding:.35rem .5rem;text-align:left}}
th{{background:#f3f3f3}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
tr.skipped{{opacity:.55}}
.note{{color:#444;max-width:58rem}}
.def{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;margin:12px 0;font-size:.92rem}}
code{{background:#f5f5f5;padding:.1em .3em;border-radius:3px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>RL / RS / SB × Indicators (IND) gate A/B</h1>
<p class="note">Post-hoc filter on Closed books. Does <strong>not</strong> re-run
portfolio concurrency / host cash. Click column headers to sort.
<code>IND_DIFF</code> = trade-aligned bull−bear indicator count at the
<strong>trigger</strong> bar (session before fill).</p>
<div class="def">
<strong>Gates tried:</strong> control; IND_DIFF ≥ {", ".join(str(x) for x in IND_DIFF_THRESHOLDS)}
(IND production <code>indicator_diff=7</code>); optional
<code>IND_ENTRY_NEUTRAL_N ≤ 30</code>; optional <code>SPY_IND_DIFF ≥ 0</code>.<br>
<strong>Skipped:</strong> <code>min_ind_score</code> (IND sets −2 but the engine only
activates the filter when threshold &gt; 0 — effectively off); <code>use_average_ind</code>
(needs a universe average pre-pass); ATR target/stop (exit schedule, not an entry DIFF gate).
</div>
<h2>Verdict (avg PNL% vs control)</h2>
<ul>
{"".join(verdict_lines)}
</ul>
<h2>Sources</h2>
<ul class="note">{"".join(enrich_notes)}</ul>
<h2>Comparison</h2>
<p class="note">Primary quality signal: <em>avg PNL%</em> (and win rate) on kept trades.
Sum PNL% / dollars grow with trade count — do not treat raw sum as “better” after a wide gate.</p>
<table class="sortable">
<thead><tr>
{sortable_th("System", "text")}
{sortable_th("Gate", "text")}
{sortable_th("Trades", "num")}
{sortable_th("Win%", "num")}
{sortable_th("Avg PNL%", "num")}
{sortable_th("Sum PNL%", "num")}
{sortable_th("Sum $", "num")}
{sortable_th("Δ trades", "num")}
{sortable_th("Δ avg PNL%", "num")}
{sortable_th("Beats ctrl avg?", "text")}
{sortable_th("IND_DIFF med", "num")}
{sortable_th("Skipped", "text")}
</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>
<script>{SORTABLE_TABLE_SCRIPT}</script>
</body>
</html>
"""
    html_path = out_dir / "comparison.html"
    html_path.write_text(html_doc, encoding="utf-8")

    md = [
        "# RL / RS / SB × IND gate A/B",
        "",
        "Post-hoc Closed filter (not a full portfolio re-sim).",
        "",
        "## Verdict",
        "",
    ]
    for line in verdict_lines:
        # strip tags lightly
        t = (
            line.replace("<li>", "- ")
            .replace("</li>", "")
            .replace("<strong>", "**")
            .replace("</strong>", "**")
            .replace("<code>", "`")
            .replace("</code>", "`")
            .replace("<em>", "")
            .replace("</em>", "")
        )
        md.append(t)
    md.extend(["", f"CSV: `{csv_path.as_posix()}`", f"HTML: `{html_path.as_posix()}`", ""])
    (out_dir / "README.md").write_text("\n".join(md), encoding="utf-8")
    return html_path


def _resolve_closed(
    explicit: Optional[Path], drive: Path, patterns: list[str]
) -> Optional[Path]:
    if explicit is not None:
        return explicit if explicit.exists() else None
    for pat in patterns:
        p = _latest(drive, pat)
        if p is not None:
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_OUT,
        help="Output folder for comparison.html / comparison.csv",
    )
    ap.add_argument("--drive", type=Path, default=ROOT / "drive")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument("--rl-closed", type=Path, default=None)
    ap.add_argument("--rs-closed", type=Path, default=None)
    ap.add_argument("--sb-closed", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--postfilter-only",
        action="store_true",
        help="Alias flag for callers; this script is always post-filter.",
    )
    ap.add_argument(
        "--write-enriched",
        action="store_true",
        help="Write enriched Closed copies under --root",
    )
    args = ap.parse_args()

    drive = args.drive
    specs = {
        "RL": (
            args.rl_closed,
            ["RL_Closed_*.csv"],
        ),
        "RS": (
            args.rs_closed,
            ["RS_Closed_*.csv"],
        ),
        "SB": (
            args.sb_closed,
            ["SB_Closed_*.csv"],
        ),
    }

    systems: dict[str, tuple[Path, list[dict[str, str]], dict[str, Any]]] = {}
    for name, (explicit, pats) in specs.items():
        # Prefer non-RL-prefixed BRT twin? Use plain SYS_Closed only.
        path = _resolve_closed(explicit, drive, pats)
        if path is None:
            print(f"[WARN] No {name} Closed found under {drive}", file=sys.stderr)
            continue
        # Skip BRT_Closed_RL_* if somehow matched — patterns are SYS-specific.
        rows = _load_closed(path)
        print(f"[{name}] loaded {len(rows)} trades from {path.name}")
        rows, meta = _attach_ind_diff(
            rows,
            data_dir=args.data_dir,
            cache_dir=args.cache_dir,
            workers=args.workers,
        )
        print(f"[{name}] IND_DIFF enrich: {meta}")
        if args.write_enriched:
            out_csv = args.root / f"{name}_control_enriched.csv"
            args.root.mkdir(parents=True, exist_ok=True)
            if rows:
                with out_csv.open("w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
                print(f"[{name}] wrote {out_csv}")
        systems[name] = (path, rows, meta)

    if not systems:
        print("ERROR: no Closed books to compare", file=sys.stderr)
        return 1

    html_path = build_report(systems, args.root)
    print(f"Wrote {html_path}")
    print(f"Wrote {args.root / 'comparison.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
