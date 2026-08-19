#!/usr/bin/env python3
"""Compare VZ tradable 2010/ADV$2m universe vs DualPaul78 vs ALL.

Trade quality for Tradable-slice is ALL Closed 260817214643 filtered to the
764-name universe (same freeze/fills). Overlay Ann ROR / Max DD need a live
run_vz.bat sleeve because aggressive capital path changes when other names
are absent.

NOT gold / NOT DailyRun. Screen is OHLC traits as-of 2023-12-29 (no VZ PnL/Paul).
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from vz_is_paul_universe_ab import (  # noqa: E402
    ALL_STAMP,
    DUAL_STAMP,
    DUAL_UNIV,
    DRIVE,
    SORT_JS,
    book_stats,
    fmt_money,
    fmt_n,
    load_closed,
    load_universe_symbols,
    sortable_th,
    split_is_oos,
)

OUT_DIR = DRIVE / "paul_experiments" / "vz_tradable_2010_adv2m_20260818"
UNIVERSE_CSV = DRIVE / "universes" / "VZ_tradable_2010_adv2m_universe.csv"
REJECT_CSV = OUT_DIR / "universe_rejects.csv"
HTML_PATH = OUT_DIR / "vz_tradable_vs_dual_all.html"
BASELINE_PATH = OUT_DIR / "BASELINE.md"
IS_CUT = date(2024, 1, 1)

KNOWN_CONTROL_STAMPS = {ALL_STAMP, DUAL_STAMP, "260817213118"}


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s in {"N/A", "n/a", "—"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def extend_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    s = book_stats(trades)
    pnls = [t["pnl"] for t in trades]
    n = len(pnls)
    if n >= 2:
        mx = max(pnls)
        s["avg_pnl_wo_max"] = (sum(pnls) - mx) / (n - 1)
    else:
        s["avg_pnl_wo_max"] = s.get("avg_pnl", 0.0)
    exits = Counter(str(t.get("exit") or "").strip() or "?" for t in trades)
    s["exit_counts"] = dict(exits)
    return s


def load_report(stamp: str) -> Optional[dict[str, Any]]:
    path = DRIVE / f"VZ_Report_{stamp}.csv"
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    r = rows[0]
    keys = [
        "Total_Trades",
        "Wins",
        "Losses",
        "Pct_Wins",
        "Avg_PNL_Pct",
        "Profit_Factor",
        "sheet_PnL",
        "Total_PNL",
        "Ann_ROR",
        "Max_DD",
        "Avg_Days_Held",
        "Median_Days_Held",
        "Capital_Days",
        "Profit_Per_Capital_Day",
        "Losing_Streak",
        "Max_Positions",
        "Avg_Positions",
        "Expectancy",
        "Expectancy_Pct",
        "Aggressive_Total_PNL",
        "Aggressive_Max_DD",
        "Pct_PNL_Top10",
        "Pct_PNL_Max_Trade",
        "Pct_PNL_Max_Symbol",
        "vz_exit_name",
        "vz_lookback_days",
        "vz_retest_window",
        "vz_entry_on",
        "vz_min_atr_pct_at_entry",
        "vz_stop_atr_buffer",
        "vz_target_r",
        "vz_exit_bars",
    ]
    return {k: r.get(k, "") for k in keys}


def detect_live_stamp(explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    ts_file = DRIVE / "VZ_last_run_ts.txt"
    if ts_file.is_file():
        ts = ts_file.read_text(encoding="utf-8").strip()
        closed = DRIVE / f"VZ_Closed_{ts}.csv"
        if ts and ts not in KNOWN_CONTROL_STAMPS and closed.is_file():
            return ts
    newest = ""
    newest_m = 0.0
    for p in DRIVE.glob("VZ_Closed_*.csv"):
        stem = p.stem.replace("VZ_Closed_", "")
        if not stem.isdigit() or len(stem) != 12:
            continue
        if stem in KNOWN_CONTROL_STAMPS:
            continue
        m = p.stat().st_mtime
        if m > newest_m:
            newest_m = m
            newest = stem
    return newest


def pack(name: str, trades: list[dict[str, Any]], overlay: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    is_t, oos_t = split_is_oos(trades)
    return {
        "name": name,
        "full": extend_stats(trades),
        "is": extend_stats(is_t),
        "oos": extend_stats(oos_t),
        "overlay": overlay,
        "n_trades_loaded": len(trades),
    }


def reject_counts(path: Path) -> Counter[str]:
    c: Counter[str] = Counter()
    if not path.is_file():
        return c
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if str(row.get("pass") or "").upper() == "Y":
                continue
            reason = str(row.get("reason") or "unknown")
            if reason.startswith("first_bar"):
                reason = "first_bar>2010-01-04"
            elif reason.startswith("close"):
                reason = "close<5"
            elif reason.startswith("adv20"):
                reason = "adv20<$2m"
            c[reason] += 1
    return c


def verdict_vs_all(trad_oos: dict[str, Any], all_oos: dict[str, Any], dual_oos: dict[str, Any]) -> tuple[str, str]:
    if trad_oos["n"] < 80:
        return "HOLD", "Tradable OOS N is thin; report only. Do not retune on OOS."
    d_wr = trad_oos["wr"] - all_oos["wr"]
    d_avg = trad_oos["avg_pnl"] - all_oos["avg_pnl"]
    d_r = trad_oos["avg_r"] - all_oos["avg_r"]
    d_pf = trad_oos["pf"] - all_oos["pf"]
    dual_wr_gap = abs(trad_oos["wr"] - dual_oos["wr"])
    all_wr_gap = abs(d_wr)
    closer_to_all = all_wr_gap + 1.5 < dual_wr_gap or (
        abs(trad_oos["avg_pnl"] - all_oos["avg_pnl"]) + 0.4
        < abs(trad_oos["avg_pnl"] - dual_oos["avg_pnl"])
    )
    worse = d_wr < -2.0 or d_avg < -0.40 or (d_pf < -0.12 and d_avg < 0)
    better = d_wr >= 2.0 and d_avg >= 0.30 and d_r >= -0.02
    flat = abs(d_wr) <= 2.0 and abs(d_avg) <= 0.40 and abs(d_r) <= 0.08
    closer_note = (
        "OOS quality sits closer to ALL than DualPaul78, as expected: DualPaul78 is an IS+OOS Paul winner-cut; "
        "this screen is the honest listing/liquidity tape (no VZ PnL/Paul)."
        if closer_to_all
        else "OOS quality is not clearly closer to ALL than DualPaul78 — treat Dual as still a selected book."
    )
    if worse:
        return (
            "DISMISS",
            f"Tradable OOS quality is worse than ALL (ΔWR {d_wr:+.1f}pp, ΔAvgPnL {d_avg:+.2f}pp, ΔPF {d_pf:+.2f}). "
            "Do not adopt as a quality upgrade. Screen may still be useful as a tape definition, but this AB fails vs ALL OOS.",
        )
    if better:
        return (
            "KEEP research tape",
            f"Tradable OOS quality beats ALL (ΔWR {d_wr:+.1f}pp, ΔAvgPnL {d_avg:+.2f}pp). Still research-only — "
            "not gold / not DailyRun. DualPaul78 remains a winner-cut, not the honest tape. " + closer_note,
        )
    if flat:
        return (
            "KEEP research tape",
            f"Tradable OOS quality is flat vs ALL (ΔWR {d_wr:+.1f}pp, ΔAvgPnL {d_avg:+.2f}pp, ΔAvgR {d_r:+.2f}) — "
            "no quality lift, no collapse. KEEP as the honest tradable screen vs DualPaul78 winner-cut. "
            "Not gold / not DailyRun; do not retune on OOS. " + closer_note,
        )
    return (
        "HOLD",
        f"Tradable OOS vs ALL is mixed (ΔWR {d_wr:+.1f}pp, ΔAvgPnL {d_avg:+.2f}pp, ΔAvgR {d_r:+.2f}, ΔPF {d_pf:+.2f}). "
        "Do not retune OOS. Research only. " + closer_note,
    )


def cell_for(key: str, stats: dict[str, Any], nd: int) -> str:
    v = stats.get(key, 0.0)
    if nd < 0:
        return fmt_money(v)
    return fmt_n(v, nd)


def overlay_cell(ov: Optional[dict[str, Any]], key: str, kind: str) -> str:
    if not ov:
        return "—"
    raw = ov.get(key, "")
    if raw in ("", None):
        return "—"
    if kind == "money":
        return fmt_money(_f(raw))
    if kind == "int":
        return fmt_n(_f(raw), 0)
    if kind == "pct1":
        return fmt_n(_f(raw), 1)
    return fmt_n(_f(raw), 2)


def write_html(
    packed: list[dict[str, Any]],
    verdict: str,
    why: str,
    trad_syms: set[str],
    dual_syms: set[str],
    all_syms: set[str],
    live_stamp: str,
    rejects: Counter[str],
    n_univ: int,
) -> None:
    specs = [
        ("Names traded", "syms", 0),
        ("Closed N", "n", 0),
        ("Wins", "wins", 0),
        ("Win %", "wr", 1),
        ("Avg PnL %", "avg_pnl", 2),
        ("Avg PnL % wo max", "avg_pnl_wo_max", 2),
        ("AvgR", "avg_r", 2),
        ("Profit factor", "pf", 2),
        ("Sheet PnL $", "sheet", -1),
        ("Avg days held", "avg_days", 1),
    ]
    splits = (
        ("full", "Full book (trade quality — same freeze)"),
        ("is", "IS (entry &lt; 2024-01-01)"),
        ("oos", "OOS (entry ≥ 2024-01-01) — verdict split"),
    )
    chunks: list[str] = []
    for sk, slabel in splits:
        body = ""
        for label, key, nd in specs:
            body += f"<tr><td>{html_mod.escape(label)}</td>"
            for p in packed:
                body += f'<td class="num">{cell_for(key, p[sk], nd)}</td>'
            if len(packed) >= 3:
                a = packed[1][sk][key]
                t = packed[2][sk][key]
                d = t - a
                if nd < 0:
                    dtxt = f"+${d:,.2f}" if d >= 0 else f"-${abs(d):,.2f}"
                elif key in {"syms", "n", "wins"}:
                    dtxt = f"{d:+,.0f}"
                else:
                    dtxt = f"{d:+.{nd}f}"
                body += f'<td class="num">{dtxt}</td>'
            body += "</tr>"
        head = sortable_th("Metric", "text") + "".join(sortable_th(p["name"], "num") for p in packed)
        head += sortable_th("Δ slice vs ALL", "num")
        chunks.append(
            f"<h2>{slabel}</h2>"
            f'<p class="small">Click column headers to sort.</p>'
            f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
        )

    ov_specs = [
        ("Ann ROR %", "Ann_ROR", "pct1"),
        ("Max DD %", "Max_DD", "pct1"),
        ("Aggressive Total PnL $", "Aggressive_Total_PNL", "money"),
        ("Aggressive Max DD %", "Aggressive_Max_DD", "pct1"),
        ("Report Total PnL $", "Total_PNL", "money"),
        ("Report sheet PnL $", "sheet_PnL", "money"),
        ("Capital days", "Capital_Days", "int"),
        ("Profit / capital day $", "Profit_Per_Capital_Day", "money"),
        ("Max positions", "Max_Positions", "int"),
        ("Avg positions", "Avg_Positions", "pct2"),
        ("Losing streak", "Losing_Streak", "int"),
        ("Expectancy $", "Expectancy", "money"),
        ("% PnL top 10", "Pct_PNL_Top10", "pct1"),
        ("% PnL max symbol", "Pct_PNL_Max_Symbol", "pct1"),
    ]
    ov_body = ""
    for label, key, kind in ov_specs:
        ov_body += f"<tr><td>{html_mod.escape(label)}</td>"
        for p in packed:
            ov_body += f'<td class="num">{overlay_cell(p.get("overlay"), key, kind)}</td>'
        ov_body += "</tr>"
    ov_head = sortable_th("Overlay (live Report)", "text") + "".join(
        sortable_th(p["name"], "num") for p in packed
    )
    overlay_note = (
        f"Tradable live stamp <code>{html_mod.escape(live_stamp)}</code>. "
        "Overlay Ann ROR / Max DD are capital-path (aggressive book), not the OOS-quality verdict. "
        "Live Closed N can differ from the ALL-slice by a couple of fills; trade quality still matches."
        if live_stamp
        else "Tradable live overlay pending — <code>run_vz.bat</code> still running or failed. "
        "Trade-quality answer is the ALL-slice column (same fills)."
    )

    # Exit mix on full book
    exit_keys: list[str] = []
    seen: set[str] = set()
    for p in packed:
        for k in p["full"].get("exit_counts", {}):
            if k not in seen:
                seen.add(k)
                exit_keys.append(k)
    exit_body = ""
    for ek in sorted(exit_keys):
        exit_body += f"<tr><td>{html_mod.escape(ek)}</td>"
        for p in packed:
            n = int(p["full"].get("exit_counts", {}).get(ek, 0))
            tot = max(int(p["full"]["n"]), 1)
            exit_body += f'<td class="num">{n:,} ({100.0 * n / tot:.1f}%)</td>'
        exit_body += "</tr>"
    exit_head = sortable_th("EXIT_TYPE (full)", "text") + "".join(
        sortable_th(p["name"], "num") for p in packed
    )

    rej_rows = "".join(
        f"<tr><td>{html_mod.escape(k)}</td><td class='num'>{v:,}</td></tr>"
        for k, v in rejects.most_common()
    )
    overlap = trad_syms & dual_syms
    dual_not_trad = dual_syms - trad_syms
    live_col_note = (
        f"Live Closed <code>VZ_Closed_{html_mod.escape(live_stamp)}.csv</code>."
        if live_stamp
        else "Live sleeve column omitted until stamp is ready."
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>VZ tradable 2010 / ADV$2m vs DualPaul78 vs ALL</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 24px; color: #1a1a1a; max-width: 1480px; }}
h1 {{ font-size: 1.35rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.1rem; margin: 28px 0 8px; }}
.sub, .small {{ color: #555; line-height: 1.45; }}
.card {{ background: #f7f8fa; border: 1px solid #e2e5ea; padding: 12px 14px; border-radius: 6px; margin: 12px 0; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 16px; }}
table.sortable th, table.sortable td {{ border-bottom: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; }}
table.sortable th {{ background: #f0f2f5; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e4e4dc; }}
.sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #94a3b8; font-size: 10px; }}
th.sort-asc .sort-ind::after {{ content: "▲"; color: #334155; }}
th.sort-desc .sort-ind::after {{ content: "▼"; color: #334155; }}
code {{ background: #eee; padding: 1px 4px; border-radius: 3px; }}
</style>
</head>
<body>
<h1>VZ tradable universe (2010 / ADV$2m) vs DualPaul78 vs ALL</h1>
<p class="sub">Frozen knobs = <code>EXIT_atr4_s025_r15</code>, min ATR 4%, stop 0.25 ATR, 1.5R, ts40, HL-only,
first_retest, mt≥1, eps 0.005, lookback 126, retest window 63, next_open — same as <code>run_vz.bat</code> defaults.
Screen (no VZ PnL / Paul / FIT): first bar ≤ 2010-01-04; as-of 2023-12-29 Close ≥ $5; 20d ADV$ ≥ $2,000,000.
IS = entry &lt; 2024-01-01; OOS = entry ≥ 2024-01-01 (report-only). Click column headers to sort.
<strong>Not gold / not DailyRun.</strong></p>
<div class="card">
<strong>Verdict: {html_mod.escape(verdict)}</strong>
<p>{html_mod.escape(why)}</p>
<p>Universe names: <strong>{n_univ}</strong>
&nbsp; DualPaul78: <strong>{len(dual_syms)}</strong>
&nbsp; ALL names traded: <strong>{len(all_syms)}</strong>
&nbsp; Dual ∩ tradable: <strong>{len(overlap)}</strong>
&nbsp; Dual not in tradable: <strong>{len(dual_not_trad)}</strong>
({html_mod.escape(", ".join(sorted(dual_not_trad)) or "none")})</p>
<p>{overlay_note} {live_col_note}</p>
</div>
<p>Tradable-slice = ALL Closed <code>VZ_Closed_{ALL_STAMP}.csv</code> filtered to the 764-name universe (same fills).
DualPaul78 = live Closed <code>VZ_Closed_{DUAL_STAMP}.csv</code> (83-name winner-cut).
Sleeve Ann ROR / Max DD are overlay-only — they change when other names are absent.</p>
<p>Universe: <code>drive/universes/VZ_tradable_2010_adv2m_universe.csv</code>
&nbsp; Freeze: <code>BASELINE.md</code></p>
{"".join(chunks)}
<h2>Live overlay (Ann ROR / Max DD from Report)</h2>
<p class="small">Slice column has no overlay by construction (it is a filter of ALL fills). Click headers to sort.</p>
<table class="sortable"><thead><tr>{ov_head}</tr></thead><tbody>{ov_body}</tbody></table>
<h2>Exit mix</h2>
<p class="small">Click column headers to sort.</p>
<table class="sortable"><thead><tr>{exit_head}</tr></thead><tbody>{exit_body}</tbody></table>
<h2>Screen rejects (OHLC traits, as-of 2023-12-29)</h2>
<p class="small">1119 scanned; 764 pass; 355 fail. Not VZ PnL-selected. Click headers to sort.</p>
<table class="sortable"><thead><tr>
{sortable_th("Reason", "text")}
{sortable_th("N fail", "num")}
</tr></thead><tbody>{rej_rows}</tbody></table>
{SORT_JS}
</body>
</html>
"""
    HTML_PATH.write_text(html, encoding="utf-8")


def write_baseline(
    packed: list[dict[str, Any]],
    verdict: str,
    why: str,
    trad_syms: set[str],
    dual_syms: set[str],
    live_stamp: str,
    rejects: Counter[str],
    n_univ: int,
) -> None:
    trad = packed[2]
    all_p = packed[1]
    dual = packed[0]
    live_line = (
        f"- Tradable live sleeve: `VZ_Closed_{live_stamp}.csv` / `VZ_Report_{live_stamp}.csv`"
        if live_stamp
        else "- Tradable live sleeve: **pending** (overlay Ann ROR / Max DD not yet in this freeze note)"
    )
    rej_md = "\n".join(f"  - `{k}`: {v}" for k, v in rejects.most_common())
    dual_not = ", ".join(sorted(dual_syms - trad_syms)) or "(none)"
    ov = packed[-1].get("overlay") if live_stamp and len(packed) > 3 else None
    ov_md = ""
    dual_ov = packed[0].get("overlay")
    all_ov = packed[1].get("overlay")
    if dual_ov and all_ov:
        ov_md += (
            f"- Dual overlay Ann ROR / Max DD: {_f(dual_ov.get('Ann_ROR')):.2f}% / {_f(dual_ov.get('Max_DD')):.2f}%\n"
            f"- ALL overlay Ann ROR / Max DD: {_f(all_ov.get('Ann_ROR')):.2f}% / {_f(all_ov.get('Max_DD')):.2f}%\n"
        )
    if ov:
        ov_md += (
            f"- Tradable live Ann ROR: {_f(ov.get('Ann_ROR')):.2f}%\n"
            f"- Tradable live Max DD: {_f(ov.get('Max_DD')):.2f}%\n"
            f"- Tradable live Aggressive Max DD: {_f(ov.get('Aggressive_Max_DD')):.2f}%\n"
        )
    md = f"""# BASELINE — VZ tradable 2010 / ADV$2m (2026-08-18)

**Status:** RESEARCH candidate only. **Not gold. Not DailyRun-wired.**

## Hypothesis (one knob)

Universe identity only. Same VZ freeze as `run_vz.bat` defaults. Compare DualPaul78 (83-name Paul winner-cut) vs ALL (~1110 names) vs a **tradable tape** (listing age + price + dollar volume). No VZ PnL, Paul, or FIT was used to pick names.

## Screen freeze (selection honesty)

Built by `tools/vz_build_tradable_universe.py` from local OHLC under `data/newdata/data`.

- First bar on or before **2010-01-04**
- As-of **2023-12-29** (last session on/before that date): Close ≥ **$5**; 20-session ADV$ = mean(Close × Volume) ≥ **$2,000,000**
- As-of is **calendar 2023 year-end**, not a VZ trade date and **not** OOS-tuned
- Scanned 1119 files; **pass={n_univ}**; fail=355
- Reject reasons:
{rej_md}

This is **not** an in-sample winner cut. DualPaul78 required Paul ≥ 7 on the dual (IS+OOS) score — that is a selected book. Tradable names can lose; they only had to exist and be liquid at the freeze date.

## Engine freeze (same as `run_vz.bat`)

- Exit identity: `EXIT_atr4_s025_r15`
- `min_atr_pct_at_entry=4.0`, `stop_atr_buffer=0.25`, `target_r=1.5`, `vz_exit_bars=40` (ts40)
- Zone: HL-only; `first_retest_only=true`; `min_touches>=1`; `retest_eps_pct=0.005`
- `lookback=126`; `retest_window=63`; `entry_on=next_open`
- Aggressive overlay: `--aggressive --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6`
- Sheet notional $45,000

Do not silently mutate this freeze. New stamp or explicit delta if knobs change.

## Compare stamps

- DualPaul78 live Closed: `drive/VZ_Closed_{DUAL_STAMP}.csv` ({len(dual_syms)} names)
- ALL live Closed: `drive/VZ_Closed_{ALL_STAMP}.csv`
- Tradable-slice: ALL Closed filtered to `drive/universes/VZ_tradable_2010_adv2m_universe.csv` ({n_univ} names)
{live_line}

IS / OOS split: entry_date < 2024-01-01 vs ≥ 2024-01-01. OOS is **report-only** — do not retune the screen or exits on OOS.

Dual ∩ tradable = {len(trad_syms & dual_syms)}. Dual names **not** in tradable: {dual_not}.

## Trade-quality snapshot (Closed)

| Split | DualPaul78 N / WR / AvgPnL / AvgR / PF | ALL N / WR / AvgPnL / AvgR / PF | Tradable-slice N / WR / AvgPnL / AvgR / PF |
|-------|----------------------------------------|----------------------------------|--------------------------------------------|
| Full | {dual['full']['n']} / {dual['full']['wr']:.1f}% / {dual['full']['avg_pnl']:.2f} / {dual['full']['avg_r']:.2f} / {dual['full']['pf']:.2f} | {all_p['full']['n']} / {all_p['full']['wr']:.1f}% / {all_p['full']['avg_pnl']:.2f} / {all_p['full']['avg_r']:.2f} / {all_p['full']['pf']:.2f} | {trad['full']['n']} / {trad['full']['wr']:.1f}% / {trad['full']['avg_pnl']:.2f} / {trad['full']['avg_r']:.2f} / {trad['full']['pf']:.2f} |
| IS | {dual['is']['n']} / {dual['is']['wr']:.1f}% / {dual['is']['avg_pnl']:.2f} / {dual['is']['avg_r']:.2f} / {dual['is']['pf']:.2f} | {all_p['is']['n']} / {all_p['is']['wr']:.1f}% / {all_p['is']['avg_pnl']:.2f} / {all_p['is']['avg_r']:.2f} / {all_p['is']['pf']:.2f} | {trad['is']['n']} / {trad['is']['wr']:.1f}% / {trad['is']['avg_pnl']:.2f} / {trad['is']['avg_r']:.2f} / {trad['is']['pf']:.2f} |
| OOS | {dual['oos']['n']} / {dual['oos']['wr']:.1f}% / {dual['oos']['avg_pnl']:.2f} / {dual['oos']['avg_r']:.2f} / {dual['oos']['pf']:.2f} | {all_p['oos']['n']} / {all_p['oos']['wr']:.1f}% / {all_p['oos']['avg_pnl']:.2f} / {all_p['oos']['avg_r']:.2f} / {all_p['oos']['pf']:.2f} | {trad['oos']['n']} / {trad['oos']['wr']:.1f}% / {trad['oos']['avg_pnl']:.2f} / {trad['oos']['avg_r']:.2f} / {trad['oos']['pf']:.2f} |

{ov_md}
Universe names with at least one closed trade (slice): {trad['full']['syms']} of {n_univ}. Live Closed N vs ALL-slice N can differ by a couple of fills (same freeze). Overlay Ann ROR / Max DD are capital-path — Dual’s low Max DD is a thin winner-cut book, not a tradable-tape property.

## Verdict

**{verdict}**

{why}

Promotion bar: research candidate only. Wider/walk-forward + PO/reconcile still required before gold. Do not wire DailyRun from this stamp.
"""
    BASELINE_PATH.write_text(md, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-stamp", default="", help="Tradable live run_vz stamp (auto-detect if omitted)")
    args = ap.parse_args()

    trad_list = load_universe_symbols(UNIVERSE_CSV)
    trad_syms = set(trad_list)
    dual_syms = set(load_universe_symbols(DUAL_UNIV))
    all_trades = load_closed(DRIVE / f"VZ_Closed_{ALL_STAMP}.csv")
    dual_trades = load_closed(DRIVE / f"VZ_Closed_{DUAL_STAMP}.csv")
    slice_trades = [t for t in all_trades if t["sym"] in trad_syms]
    all_syms = {t["sym"] for t in all_trades}

    live_stamp = detect_live_stamp(args.live_stamp)
    live_trades: list[dict[str, Any]] = []
    live_rep = None
    if live_stamp:
        live_path = DRIVE / f"VZ_Closed_{live_stamp}.csv"
        if live_path.is_file():
            live_trades = load_closed(live_path)
            live_rep = load_report(live_stamp)

    dual_rep = load_report(DUAL_STAMP)
    all_rep = load_report(ALL_STAMP)
    rejects = reject_counts(REJECT_CSV)

    packed = [
        pack("DualPaul78 live", dual_trades, dual_rep),
        pack("ALL live", all_trades, all_rep),
        pack("Tradable-slice (ALL fills)", slice_trades, None),
    ]
    if live_trades:
        packed.append(pack(f"Tradable live {live_stamp}", live_trades, live_rep))

    verdict, why = verdict_vs_all(packed[2]["oos"], packed[1]["oos"], packed[0]["oos"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_html(
        packed,
        verdict,
        why,
        trad_syms,
        dual_syms,
        all_syms,
        live_stamp if live_trades else "",
        rejects,
        len(trad_list),
    )
    write_baseline(
        packed,
        verdict,
        why,
        trad_syms,
        dual_syms,
        live_stamp if live_trades else "",
        rejects,
        len(trad_list),
    )

    def dump(tag: str, p: dict[str, Any]) -> None:
        for sk in ("full", "is", "oos"):
            s = p[sk]
            print(
                f"{tag:28} {sk:4} N={s['n']:5} names={s['syms']:4} "
                f"WR={s['wr']:5.1f} avg={s['avg_pnl']:6.2f} avgR={s['avg_r']:5.2f} "
                f"PF={s['pf']:4.2f} sheet={s['sheet']:.0f}"
            )

    for p in packed:
        dump(p["name"], p)
    print(f"UNIVERSE_N {len(trad_list)}")
    print(f"DUAL_NOT_TRADABLE {sorted(dual_syms - trad_syms)}")
    print(f"LIVE_STAMP {live_stamp or '(none)'}")
    print(f"VERDICT {verdict}")
    print("WHY " + why.replace("Δ", "d"))
    print(f"HTML {HTML_PATH}")
    print(f"BASELINE {BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
