#!/usr/bin/env python3
"""Scalp full re-score on expanded 1m store — control + setup_bar book + IS/OOS slices.

Re-runs the frozen scalp entry book on all 1m parquets, re-exits with setup_bar_0p05,
reports full book + winner sleeves with canonical and provisional temporal IS/OOS.

Usage:
  python tools/scalp_rescore_ab.py --all
  python tools/scalp_rescore_ab.py --all --stamp scalp_rescore_20260827
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import subprocess
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_filtered_timestop_ab as filt  # noqa: E402
import scalp_full_levers_pack as pack  # noqa: E402
import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, read_1m, resample_ohlcv  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_rescore_20260827"
SYSTEM = "scalp"
CANONICAL_OOS = date(2024, 1, 1)
PROVISIONAL_OOS = date(2026, 8, 1)
DRIVE_SEARCH = "https://drive.google.com/drive/search?q=scalp_rescore_20260827"


def _session_date(t: dict[str, Any]) -> date:
    s = str(t.get("session") or t.get("entry_date") or "")[:10]
    return datetime.strptime(s, "%Y-%m-%d").date()


def winner_sleeve(t: dict[str, Any]) -> bool:
    return (
        str(t.get("entirely_out") or "") == "entirely_out"
        and str(t.get("range_atr_bucket") or "") == "40_60pct"
        and filt.passes_shape_side(t)
    )


def full_mid_stack(t: dict[str, Any]) -> bool:
    return filt.passes_shared_filters(t) and filt.passes_shape_side(t)


def scan_setup_bar_book(symbols: list[str]) -> tuple[list[dict[str, Any]], str]:
    trades: list[dict[str, Any]] = []
    sides = {"long", "short"}
    n_sym = len(symbols)
    min_sess: Optional[date] = None
    max_sess: Optional[date] = None

    for i, sym in enumerate(symbols, 1):
        if i == 1 or i % 50 == 0 or i == n_sym:
            print(f"[{i}/{n_sym}] {sym} … N={len(trades)}", flush=True)
        daily = ab.load_ohlc(sym)
        if daily is None:
            continue
        atr_map = ab.prior_close_atr_map(daily)
        adv_map = ab.prior_close_adv_map(daily)
        df1 = ab.rth_filter(read_1m(sym, DEFAULT_1M_DIR))
        if df1.empty:
            continue
        df5 = resample_ohlcv(df1, "5min")
        df15 = resample_ohlcv(df1, "15min")
        for d in ab.session_dates(df1):
            atr = atr_map.get(d)
            if atr is None or not math.isfinite(atr) or atr <= 0:
                continue
            adv = float(adv_map.get(d, float("nan")))
            trade, _diag = ab.simulate_day(
                sym,
                d,
                df5,
                df15,
                float(atr),
                sides=sides,
                adv_prior=adv,
                time_stop=ab.TIME_STOP_T,
                eod_flat=ab.EOD_FLAT_T,
            )
            if not trade:
                continue
            trade = pack.enrich_shape(trade, daily, d)
            day5 = ab.bars_on_day(df5, d)
            lod = float(trade["lod"]) if trade.get("lod") not in ("", None) else float("nan")
            hod = float(trade["hod"]) if trade.get("hod") not in ("", None) else float("nan")
            setup_l = float(trade.get("setup_l") or float("nan"))
            setup_h = float(trade.get("setup_h") or float("nan"))
            stop = pack.compute_stop(
                "setup_bar_0p05",
                side=str(trade["side"]),
                entry=float(trade["entry"]),
                lod=lod,
                hod=hod,
                setup_l=setup_l,
                setup_h=setup_h,
                prior_lo=float("nan"),
                prior_hi=float("nan"),
                week_lo=float("nan"),
                week_hi=float("nan"),
            )
            if stop is None or not pack.stop_valid(str(trade["side"]), float(trade["entry"]), stop):
                continue
            out = pack.reexit_with_stop(
                trade,
                day5,
                stop=stop,
                stop_arm="setup_bar_0p05",
                time_stop=ab.TIME_STOP_T,
            )
            sd = _session_date(out)
            min_sess = sd if min_sess is None else min(min_sess, sd)
            max_sess = sd if max_sess is None else max(max_sess, sd)
            trades.append(out)

    cov = (
        f"1m under `data/intraday/1m/` · {len(symbols)} symbols requested · "
        f"session span {min_sess} → {max_sess} (symbol-dependent gaps)."
        if min_sess
        else "No trades — check 1m store."
    )
    return trades, cov


def split_trades(
    trades: list[dict[str, Any]],
    holdout: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    is_tr = [t for t in trades if _session_date(t) < holdout]
    oos_tr = [t for t in trades if _session_date(t) >= holdout]
    return is_tr, oos_tr


def metrics_row(label: str, trades: list[dict[str, Any]], *, vs: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    m = ab.metrics_from_trades(trades, include_slices=False)
    row: dict[str, Any] = {
        "population": label,
        "N": m.get("N"),
        "Win%": m.get("Win%"),
        "Avg_PnL_%": m.get("Avg_PnL_%"),
        "AVG_PNL_PCT_WO_MAX": m.get("AVG_PNL_PCT_WO_MAX"),
        "Profit_Factor": m.get("Profit_Factor"),
        "Sheet_PnL_$": m.get("Sheet_PnL_$"),
        "Max_DD_%": m.get("Max_DD_%"),
        "Ann_ROR_%": m.get("Ann_ROR_%"),
    }
    if vs:
        for k in ("N", "Win%", "Avg_PnL_%", "Profit_Factor", "Sheet_PnL_$", "Max_DD_%"):
            a = row.get(k)
            b = vs.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(a) and math.isfinite(b):
                row[f"d_{k}"] = a - b
    return row


def verdict_control(m: dict[str, Any], *, n_min: int = 50) -> str:
    n = int(m.get("N") or 0)
    avg = m.get("Avg_PnL_%")
    pf = m.get("Profit_Factor")
    if n < n_min:
        return "HOLD - thin N on expanded window (research only; not DailyRun)"
    if isinstance(avg, float) and math.isfinite(avg) and avg > 0 and (
        not isinstance(pf, float) or not math.isfinite(pf) or pf >= 1.05
    ):
        return "HOLD - modest edge; needs longer 1m history + walk-forward before KEEP"
    return "HOLD - flat/soft quality on short Yahoo window (research only)"


def verdict_winner(m: dict[str, Any]) -> str:
    n = int(m.get("N") or 0)
    if n < 20:
        return "HOLD - winner sleeve still thin N"
    avg = m.get("Avg_PnL_%")
    pf = m.get("Profit_Factor")
    if isinstance(avg, float) and math.isfinite(avg) and avg > 0.15 and isinstance(pf, float) and pf >= 1.5:
        return "HOLD - descriptive quality ok; selection bias on same book — no KEEP"
    return "HOLD - descriptive only; do not wire DailyRun"


def write_baseline(
    path: Path,
    *,
    stamp: str,
    cov: str,
    n_all: int,
    n_win: int,
    n_full: int,
    canon_is: int,
    prov_is: int,
    prov_oos: int,
    verdict_all: str,
) -> None:
    text = f"""# BASELINE — Scalp re-score — `{stamp}`

**System:** `{SYSTEM}` · research only · **not** DailyRun · **not** gold.

Re-run of frozen scalp open15→5m book on expanded Yahoo 1m store.
Stop arm: **setup_bar_0p05** · time stop **11:30** · target open15 extreme.

## Source / prior stamps

| Item | Value |
|------|--------|
| Prior full levers | `scalp_full_levers_20260822` |
| Prior filtered | `scalp_filtered_timestop_20260822` |
| Entry freeze | Same as `scalp_open15_reversal_ab.py` / full levers BASELINE |

## Populations

| Label | Definition | N |
|-------|------------|---|
| all_trades | Full setup_bar_0p05 book | **{n_all}** |
| winner_sleeve | `entirely_out` ∧ `40_60pct` ∧ shape×side OR (**no** mid ADV) | **{n_win}** |
| full_mid_stack | above + **mid_5m_20m** (prior filtered stack) | **{n_full}** |

## IS / OOS honesty

| Split | Rule | IS N | OOS N | Use |
|-------|------|------|-------|-----|
| Canonical | entry `< 2024-01-01` / `≥ 2024-01-01` | **{canon_is}** | all post-2024 | **N/A** — entire window is 2026 Yahoo 1m |
| Provisional | entry `< 2026-08-01` / `≥ 2026-08-01` | **{prov_is}** | **{prov_oos}** | Temporal holdout within short window — **report only**, not promotion |

Never retune on OOS. Provisional split is labeled; do not treat as gold evidence.

## Coverage

{cov}

## Verdict

**All book:** {verdict_all}

Winner / full_mid sleeves: descriptive HOLD only (in-sample filter discovery on same history).

## Drive

Compare HTML: `drive/paul_experiments/{stamp}/compare.html`
"""
    path.write_text(text, encoding="utf-8")


def _metric_table(rows: list[dict[str, Any]], *, title: str, note: str = "") -> str:
    cols = [
        ("population", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Profit_Factor", "num"),
        ("Sheet_PnL_$", "money"),
        ("Max_DD_%", "num"),
        ("Ann_ROR_%", "num"),
    ]
    head = "".join(ab.sortable_th(c, t) for c, t in cols)
    body = []
    for r in rows:
        cells = []
        for c, t in cols:
            v = r.get(c, "")
            if t == "money" and isinstance(v, (int, float)) and math.isfinite(v):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{ab._fmt_num(v, 4 if 'PnL' in c else 2)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    note_p = f"<p>{html_mod.escape(note)}</p>" if note else ""
    return f"""<h2>{html_mod.escape(title)}</h2>
{note_p}
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{''.join(body) or "<tr><td colspan='8'>No rows</td></tr>"}</tbody>
</table>"""


def write_compare_html(
    path: Path,
    *,
    stamp: str,
    cov: str,
    pop_rows: list[dict[str, Any]],
    is_oos_rows: list[dict[str, Any]],
    side_rows: list[dict[str, Any]],
    verdicts: dict[str, str],
    n_sym: int,
) -> None:
    ctrl = pop_rows[0] if pop_rows else {}
    metric_bits = (
        f"N={ctrl.get('N')} · WR%={ab._fmt_num(ctrl.get('Win%'))} · "
        f"AvgPnL%={ab._fmt_num(ctrl.get('Avg_PnL_%'), 4)} · "
        f"PF={ab._fmt_num(ctrl.get('Profit_Factor'))} · "
        f"PnL$={format_money(ctrl.get('Sheet_PnL_$') or 0)}"
    )
    v_html = "".join(f'<p class="verdict">{html_mod.escape(k)}: {html_mod.escape(v)}</p>' for k, v in verdicts.items())
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scalp re-score — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1rem 1.25rem; color: #0f172a; background: #f8fafc; }}
h1,h2 {{ color: #0f172a; font-size: 1.25rem; }}
.note {{ background: #fff7ed; border-left: 4px solid #f97316; padding: .75rem 1rem; margin: 1rem 0; font-size: .92rem; }}
.verdict {{ font-weight: 600; margin: .35rem 0; font-size: .95rem; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; margin: .75rem 0 1.25rem; font-size: .85rem; }}
th, td {{ border: 1px solid #cbd5e1; padding: .35rem .45rem; text-align: left; }}
th {{ background: #e2e8f0; }}
{ab.SORT_CSS}
code {{ background: #e2e8f0; padding: .1rem .3rem; border-radius: 3px; }}
</style>
</head>
<body>
<h1>Scalp re-score (expanded 1m)</h1>
<p>Stamp <code>{html_mod.escape(stamp)}</code> · {n_sym} symbols · <strong>research only</strong></p>
<p><strong>Setup_bar_0p05 book:</strong> {html_mod.escape(metric_bits)}</p>
<div class="note">
<strong>Coverage.</strong> {html_mod.escape(cov)}<br/>
<strong>IS/OOS:</strong> Canonical 2024 holdout is empty IS (all 2026 data). Provisional split at 2026-08-01 is report-only.<br/>
Click column headers to sort.
</div>
{v_html}
{_metric_table(pop_rows, title="Populations (full book + winner sleeves)")}
{_metric_table(is_oos_rows, title="IS / OOS slices (provisional + canonical)", note="Rows tagged is_canonical / oos_canonical / is_provisional / oos_provisional.")}
{_metric_table(side_rows, title="By side (all book)")}
{ab.SORT_JS}
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


def write_trades_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    if not trades:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({k for t in trades for k in t})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)


def notify(html_path: Path, stamp: str) -> None:
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if not ntfy.is_file():
        return
    msg = (
        f"Scalp rescore done — compare.html on Drive: {DRIVE_SEARCH} "
        f"(local: drive/paul_experiments/{stamp}/compare.html)"
    )
    subprocess.run(
        [sys.executable, str(ntfy), "--path", str(html_path), "-t", "Scalp rescore", "-m", msg],
        cwd=str(ROOT),
        check=False,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Scalp full re-score on expanded 1m store")
    ap.add_argument("--all", action="store_true", help="All 1m parquets")
    ap.add_argument("-s", "--symbols", default="", help="Comma-separated symbols")
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    args = ap.parse_args()

    if args.all:
        symbols = sorted(p.stem.upper() for p in DEFAULT_1M_DIR.glob("*.parquet"))
    elif args.symbols:
        symbols = [x.strip().upper() for x in args.symbols.replace(";", ",").split(",") if x.strip()]
    else:
        symbols = sorted(p.stem.upper() for p in DEFAULT_1M_DIR.glob("*.parquet"))

    stamp = args.stamp
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning {len(symbols)} symbols → {out_dir}", flush=True)
    trades, cov = scan_setup_bar_book(symbols)
    if not trades:
        print("ERROR: no trades", flush=True)
        return 1

    all_m = ab.metrics_from_trades(trades, include_slices=False)
    winners = [t for t in trades if winner_sleeve(t)]
    fulls = [t for t in trades if full_mid_stack(t)]

    pop_rows = [
        metrics_row("all_trades", trades),
        metrics_row("winner_sleeve", winners, vs=all_m),
        metrics_row("full_mid_stack", fulls, vs=all_m),
    ]

    is_oos_rows: list[dict[str, Any]] = []
    for label, holdout in (("canonical", CANONICAL_OOS), ("provisional", PROVISIONAL_OOS)):
        is_tr, oos_tr = split_trades(trades, holdout)
        is_oos_rows.append(metrics_row(f"is_{label}", is_tr))
        is_oos_rows.append(metrics_row(f"oos_{label}", oos_tr))
        is_oos_rows.append(metrics_row(f"is_{label}_winner", [t for t in is_tr if winner_sleeve(t)]))
        is_oos_rows.append(metrics_row(f"oos_{label}_winner", [t for t in oos_tr if winner_sleeve(t)]))

    by_side: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by_side.setdefault(str(t.get("side") or ""), []).append(t)
    side_rows = [metrics_row(f"{side}_only", ts) for side, ts in sorted(by_side.items())]

    canon_is, _ = split_trades(trades, CANONICAL_OOS)
    prov_is, prov_oos = split_trades(trades, PROVISIONAL_OOS)
    v_all = verdict_control(all_m)
    verdicts = {
        "all_trades": v_all,
        "winner_sleeve": verdict_winner(metrics_row("w", winners)),
        "full_mid_stack": "HOLD - ultra-thin N" if len(fulls) < 10 else verdict_winner(metrics_row("f", fulls)),
    }

    write_trades_csv(out_dir / "trades_setup_bar_0p05.csv", trades)
    with (out_dir / "metrics_populations.csv").open("w", newline="", encoding="utf-8") as f:
        keys = sorted({k for r in pop_rows + is_oos_rows + side_rows for k in r})
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(pop_rows + is_oos_rows + side_rows)

    html_path = out_dir / "compare.html"
    write_compare_html(
        html_path,
        stamp=stamp,
        cov=cov,
        pop_rows=pop_rows,
        is_oos_rows=is_oos_rows,
        side_rows=side_rows,
        verdicts=verdicts,
        n_sym=len(symbols),
    )
    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        cov=cov,
        n_all=len(trades),
        n_win=len(winners),
        n_full=len(fulls),
        canon_is=len(canon_is),
        prov_is=len(prov_is),
        prov_oos=len(prov_oos),
        verdict_all=v_all,
    )
    (out_dir / "SUMMARY.md").write_text(
        f"""# SUMMARY — `{stamp}`

**Verdict:** HOLD (research only; not DailyRun / not gold)

## Book
- All N={len(trades)} WR%={ab._fmt_num(all_m.get('Win%'))} Avg={ab._fmt_num(all_m.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(all_m.get('Profit_Factor'))} Sheet={format_money(all_m.get('Sheet_PnL_$') or 0)}
- Winner sleeve N={len(winners)} WR%={ab._fmt_num(metrics_row('w', winners).get('Win%'))} Avg={ab._fmt_num(metrics_row('w', winners).get('Avg_PnL_%'), 4)} PF={ab._fmt_num(metrics_row('w', winners).get('Profit_Factor'))}
- Full+mid N={len(fulls)}

## IS/OOS
- Canonical IS (pre-2024): N={len(canon_is)} — N/A
- Provisional IS (pre 2026-08-01): N={len(prov_is)}
- Provisional OOS (≥ 2026-08-01): N={len(prov_oos)}

See `compare.html` · Drive search: {DRIVE_SEARCH}
""",
        encoding="utf-8",
    )

    print(f"DONE N={len(trades)} winner={len(winners)} full_mid={len(fulls)}", flush=True)
    print(f"HTML={html_path}", flush=True)
    notify(html_path, stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
