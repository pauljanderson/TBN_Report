#!/usr/bin/env python3
"""Filtered scalp book + one-knob time-stop A/B (research only).

Freeze (AND shared filters; shape×side is OR of allowed cells):
  Shared: ADV$ mid_5m_20m, stop setup_bar_0p05, entirely_out, open15 range/ATR 40_60pct
  Allowed cells: hammer_like×long, doji×short, engulfing_day×short,
                 marubozu×short, shooting_star_like×short
  Time-stop arms: flat at 11:00 / 11:30 / 12:00 / 13:00 ET (5m bar open ≥ clock)
  Target: open15 extreme (unchanged)

Usage:
  python tools/scalp_filtered_timestop_ab.py
  python tools/scalp_filtered_timestop_ab.py --source-stamp scalp_full_levers_20260822
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_full_levers_pack as pack  # noqa: E402
import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m, resample_ohlcv  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_filtered_timestop_20260822"
DEFAULT_SOURCE = "scalp_full_levers_20260822"
SYSTEM = "scalp"

# Control arm for cell breakdown
CONTROL_ARM = "1130"

TIME_STOP_ARMS: list[tuple[str, time]] = [
    ("1100", time(11, 0)),
    ("1130", time(11, 30)),
    ("1200", time(12, 0)),
    ("1300", time(13, 0)),
]

ALLOWED_CELLS: list[tuple[str, str]] = [
    ("hammer_like", "long"),
    ("doji", "short"),
    ("engulfing_day", "short"),
    ("marubozu", "short"),
    ("shooting_star_like", "short"),
]


def _as_dict_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rec in df.to_dict(orient="records"):
        out: dict[str, Any] = {}
        for k, v in rec.items():
            if isinstance(v, float) and math.isnan(v):
                out[k] = ""
            else:
                out[k] = v
        rows.append(out)
    return rows


def passes_shared_filters(t: dict[str, Any]) -> bool:
    return (
        str(t.get("adv_bucket") or "") == "mid_5m_20m"
        and str(t.get("entirely_out") or "") == "entirely_out"
        and str(t.get("range_atr_bucket") or "") == "40_60pct"
    )


def passes_shape_side(t: dict[str, Any]) -> bool:
    shape = str(t.get("open15_shape") or "")
    side = str(t.get("side") or "")
    engulf = int(t.get("open15_engulfing_day") or 0) == 1
    if shape == "hammer_like" and side == "long":
        return True
    if shape == "doji" and side == "short":
        return True
    if engulf and side == "short":
        return True
    if shape == "marubozu" and side == "short":
        return True
    if shape == "shooting_star_like" and side == "short":
        return True
    return False


def cell_keys_for_trade(t: dict[str, Any]) -> list[str]:
    """OR cells this trade belongs to (engulfing may overlap geometry)."""
    keys: list[str] = []
    shape = str(t.get("open15_shape") or "")
    side = str(t.get("side") or "")
    engulf = int(t.get("open15_engulfing_day") or 0) == 1
    if shape == "hammer_like" and side == "long":
        keys.append("hammer_like×long")
    if shape == "doji" and side == "short":
        keys.append("doji×short")
    if engulf and side == "short":
        keys.append("engulfing_day×short")
    if shape == "marubozu" and side == "short":
        keys.append("marubozu×short")
    if shape == "shooting_star_like" and side == "short":
        keys.append("shooting_star_like×short")
    return keys


def load_setup_bar_trades(source_stamp: str) -> list[dict[str, Any]]:
    path = DRIVE / "paul_experiments" / source_stamp / "trades_stop_setup_bar_0p05.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing source stop book: {path}")
    df = pd.read_csv(path)
    return _as_dict_rows(df)


def filter_book(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in trades if passes_shared_filters(t) and passes_shape_side(t)]


def reexit_time_stop(
    trade: dict[str, Any],
    day5: pd.DataFrame,
    *,
    arm_label: str,
    time_stop: time,
) -> dict[str, Any]:
    stop = float(trade["stop"])
    out = pack.reexit_with_stop(
        trade,
        day5,
        stop=stop,
        stop_arm="setup_bar_0p05",
        time_stop=time_stop,
        eod_flat=ab.EOD_FLAT_T,
    )
    out["time_stop_arm"] = arm_label
    out["time_stop_clock"] = time_stop.strftime("%H:%M")
    out["filter_cells"] = "|".join(cell_keys_for_trade(trade))
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("note\nno_trades\n", encoding="utf-8")
        return
    keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _metric_row(arm: str, m: dict[str, Any], *, vs_ctrl: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    row = {
        "arm": arm,
        "N": m.get("N"),
        "Win%": m.get("Win%"),
        "Avg_PnL_%": m.get("Avg_PnL_%"),
        "Profit_Factor": m.get("Profit_Factor"),
        "Sheet_PnL_$": m.get("Sheet_PnL_$", m.get("Total_PnL_$")),
        "Total_PnL_$": m.get("Total_PnL_$"),
        "Max_DD_%": m.get("Max_DD_%"),
        "exit_TIME": (m.get("exit_mix") or {}).get("TIME", 0),
        "exit_STOP": (m.get("exit_mix") or {}).get("STOP", 0),
        "exit_TARGET": (m.get("exit_mix") or {}).get("TARGET", 0),
    }
    if vs_ctrl is not None:
        ca, ka = vs_ctrl.get("Avg_PnL_%"), m.get("Avg_PnL_%")
        if isinstance(ca, float) and isinstance(ka, float) and math.isfinite(ca) and math.isfinite(ka):
            row["ΔAvg_vs_1130"] = ka - ca
        else:
            row["ΔAvg_vs_1130"] = ""
    return row


def pick_timestop_verdict(ctrl: dict[str, Any], arms: dict[str, dict[str, Any]]) -> str:
    n = int(ctrl.get("N") or 0)
    if n < 20:
        return (
            f"HOLD - filtered book N={n} too thin for KEEP (research only; short 1m window; "
            "not DailyRun)"
        )
    best_label = CONTROL_ARM
    best_avg = ctrl.get("Avg_PnL_%")
    for lab, m in arms.items():
        if lab == CONTROL_ARM:
            continue
        avg = m.get("Avg_PnL_%")
        if (
            isinstance(avg, float)
            and isinstance(best_avg, float)
            and math.isfinite(avg)
            and math.isfinite(best_avg)
            and avg > best_avg + 0.01
        ):
            best_avg = avg
            best_label = lab
    if best_label == CONTROL_ARM:
        return "HOLD - no time-stop arm clearly better than 11:30 on quality (research only)"
    return (
        f"HOLD - {best_label} modestly ahead of 11:30 on short window only "
        f"(research; selection bias; not KEEP / not DailyRun)"
    )


def write_baseline(
    path: Path,
    *,
    stamp: str,
    source_stamp: str,
    n_source: int,
    n_shared: int,
    n_filtered: int,
    verdict: str,
    arm_metrics: dict[str, dict[str, Any]],
) -> None:
    lines = [
        f"# BASELINE — Scalp filtered time-stop A/B — `{stamp}`",
        "",
        f"**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.",
        f"Source book: `drive/paul_experiments/{source_stamp}/trades_stop_setup_bar_0p05.csv` (N={n_source}).",
        "",
        "## Freeze (filtered entry / exit)",
        "",
        "| Knob | Value |",
        "|------|--------|",
        "| Shared ADV$ | **mid_5m_20m** (5m–20m prior-close ADV$) |",
        "| Stop | **setup_bar_0p05** (setup candle extreme ±0.05%) |",
        "| entirely_out | **entirely_out** only (setup fully outside open15 box) |",
        "| Open15 range/ATR | **40_60pct** |",
        "| Shape×side (OR) | hammer_like×long; doji×short; engulfing_day×short; "
        "marubozu×short; shooting_star_like×short |",
        "| Target | Long open15 High / short open15 Low (frozen) |",
        "| Time-stop arms (one knob) | Exit flat at **11:00, 11:30, 12:00, 13:00** ET |",
        "| Time-stop bar | First **5m bar open** with ET clock ≥ time-stop "
        f"(`resolve_exit` / `{pack.__name__}.reexit_with_stop`) |",
        f"| Sheet | ${ab.SHEET:,.0f}/trade |",
        "",
        "## Counts",
        "",
        f"- Source setup_bar_0p05 book: **{n_source}**",
        f"- After shared filters only: **{n_shared}**",
        f"- After shared + shape×side OR: **{n_filtered}**",
        "",
        "## Coverage / honesty",
        "",
        "- Default chronological IS/OOS **not applicable** (short Yahoo 1m window).",
        "- Filter + time-stop compare is **in-sample selection** on the prior levers book — research only.",
        "- Thin N under this freeze → **no KEEP**, **no gold**, **no DailyRun**.",
        "",
        "## Time-stop metrics (filtered book)",
        "",
        "| Arm | N | WR% | Avg PnL% | PF | Sheet PnL | Max DD% |",
        "|-----|---|-----|----------|----|-----------|---------|",
    ]
    for lab, _ts in TIME_STOP_ARMS:
        m = arm_metrics[lab]
        lines.append(
            f"| `{lab}` | {m.get('N')} | {ab._fmt_num(m.get('Win%'))} | "
            f"{ab._fmt_num(m.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m.get('Profit_Factor'))} | "
            f"{format_money(m.get('Sheet_PnL_$') or m.get('Total_PnL_$') or 0)} | "
            f"{ab._fmt_num(m.get('Max_DD_%'))} |"
        )
    lines.extend(
        [
            "",
            f"**Verdict:** {verdict}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_compare_html(
    path: Path,
    *,
    stamp: str,
    source_stamp: str,
    n_source: int,
    n_shared: int,
    n_filtered: int,
    arm_books: dict[str, list[dict[str, Any]]],
    arm_metrics: dict[str, dict[str, Any]],
    verdict: str,
    breakdown_arm: str,
) -> None:
    ctrl = arm_metrics[CONTROL_ARM]
    ab_cols = [
        ("arm", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Profit_Factor", "num"),
        ("Sheet_PnL_$", "money"),
        ("Max_DD_%", "num"),
        ("ΔAvg_vs_1130", "num"),
        ("exit_TIME", "num"),
        ("exit_STOP", "num"),
        ("exit_TARGET", "num"),
    ]
    ab_head = "".join(ab.sortable_th(c, t) for c, t in ab_cols)
    ab_body: list[str] = []
    for lab, _ts in TIME_STOP_ARMS:
        r = _metric_row(lab, arm_metrics[lab], vs_ctrl=ctrl)
        cells = []
        for c, _t in ab_cols:
            v = r.get(c)
            if c in ("Sheet_PnL_$", "Total_PnL_$") and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{ab._fmt_num(v, 4 if 'PnL' in c or 'Avg' in c or 'Δ' in c else 2)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v if v is not None else '—'))}</td>")
        cls = " class='total-row'" if lab == CONTROL_ARM else ""
        ab_body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")

    # Cell breakdown under breakdown_arm
    bd_trades = arm_books[breakdown_arm]
    cell_buckets: dict[str, list[dict[str, Any]]] = {f"{s}×{side}": [] for s, side in ALLOWED_CELLS}
    for t in bd_trades:
        for k in cell_keys_for_trade(t):
            cell_buckets.setdefault(k, []).append(t)
    cell_metrics = {
        k: ab.metrics_from_trades(v, include_slices=False) for k, v in cell_buckets.items()
    }
    cell_html = ab._slice_table(
        f"Shape×side cells under `{breakdown_arm}` (control 11:30 unless noted)",
        "OR membership — engulfing_day×short may overlap geometry cells.",
        "shape×side",
        cell_metrics,
    )

    trade_cols = [
        ("symbol", "text"),
        ("side", "text"),
        ("session", "date"),
        ("open15_shape", "text"),
        ("open15_engulfing_day", "num"),
        ("filter_cells", "text"),
        ("entry_ts", "text"),
        ("exit_ts", "text"),
        ("exit_type", "text"),
        ("pnl_pct", "num"),
        ("pnl_usd", "money"),
        ("time_stop_arm", "text"),
    ]
    thead = "".join(ab.sortable_th(c, t) for c, t in trade_cols)
    tbody: list[str] = []
    for t in sorted(bd_trades, key=lambda x: (str(x.get("session")), str(x.get("symbol")))):
        cells = []
        for c, _t in trade_cols:
            v = t.get(c, "")
            if c == "pnl_usd" and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                cells.append(f"<td>{ab._fmt_num(v, 4)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        tbody.append("<tr>" + "".join(cells) + "</tr>")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scalp filtered time-stop — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 1.25rem; color: #0f172a; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
.sub, .note {{ color: #475569; font-size: .92rem; }}
.verdict {{ background: #f1f5f9; border-left: 4px solid #334155; padding: .75rem 1rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: .85rem; margin: .75rem 0; }}
th, td {{ border: 1px solid #e2e8f0; padding: 6px 8px; text-align: left; }}
th {{ background: #f8fafc; }}
tr.total-row td {{ background: #f1f5f9; font-weight: 600; }}
.table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
{ab.SORT_CSS}
</style>
</head><body>
<h1>Scalp filtered book — time-stop A/B</h1>
<p class="sub">Stamp <code>{html_mod.escape(stamp)}</code> · source <code>{html_mod.escape(source_stamp)}</code> ·
research only · not DailyRun · not gold.</p>
<p class="note">Shared AND: ADV$ <code>mid_5m_20m</code> · stop <code>setup_bar_0p05</code> ·
<code>entirely_out</code> · range/ATR <code>40_60pct</code>. Shape×side OR of five allowed cells.
Time-stop = first <strong>5m bar open</strong> with ET clock ≥ arm (11:00 / 11:30 / 12:00 / 13:00).
Target = open15 extreme. Click / tap column headers to sort.</p>

<p class="note">Source N={n_source} → shared filters N={n_shared} → filtered N={n_filtered}.</p>
<p class="verdict">{html_mod.escape(verdict)}</p>

<h2>Time-stop arms (filtered book)</h2>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{ab_head}</tr></thead>
<tbody>{''.join(ab_body)}</tbody>
</table>
</div>

<div id="cells">
{cell_html}
</div>

<h2>Trades under `{html_mod.escape(breakdown_arm)}`</h2>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{thead}</tr></thead>
<tbody>{''.join(tbody) if tbody else f"<tr><td colspan='{len(trade_cols)}'>No trades</td></tr>"}</tbody>
</table>
</div>

<p class="note">Generated {datetime.now(tz=ET).isoformat(timespec='seconds')} ·
tool <code>tools/scalp_filtered_timestop_ab.py</code></p>
{ab.SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def run(
    *,
    stamp: str,
    source_stamp: str,
) -> dict[str, Any]:
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    source = load_setup_bar_trades(source_stamp)
    shared = [t for t in source if passes_shared_filters(t)]
    filtered = filter_book(source)

    # Cache day5 per (symbol, session)
    day5_cache: dict[tuple[str, str], pd.DataFrame] = {}

    def get_day5(sym: str, session: str) -> pd.DataFrame:
        key = (sym, session)
        if key in day5_cache:
            return day5_cache[key]
        from datetime import date as date_cls

        d = date_cls.fromisoformat(str(session)[:10])
        df1 = ab.rth_filter(read_1m(sym, DEFAULT_1M_DIR))
        df5 = resample_ohlcv(df1, "5min")
        day5 = ab.bars_on_day(df5, d)
        day5_cache[key] = day5
        return day5

    arm_books: dict[str, list[dict[str, Any]]] = {lab: [] for lab, _ in TIME_STOP_ARMS}
    for i, t in enumerate(filtered, 1):
        sym = str(t["symbol"])
        session = str(t["session"])
        if i == 1 or i % 25 == 0 or i == len(filtered):
            print(f"[{i}/{len(filtered)}] {sym} {session}", flush=True)
        day5 = get_day5(sym, session)
        for lab, ts in TIME_STOP_ARMS:
            arm_books[lab].append(reexit_time_stop(t, day5, arm_label=lab, time_stop=ts))

    arm_metrics = {
        lab: ab.metrics_from_trades(rows, include_slices=False) for lab, rows in arm_books.items()
    }
    verdict = pick_timestop_verdict(arm_metrics[CONTROL_ARM], arm_metrics)

    # Prefer control 1130 for cell breakdown; if empty, fall back to best Avg
    breakdown_arm = CONTROL_ARM
    if int(arm_metrics[CONTROL_ARM].get("N") or 0) == 0:
        breakdown_arm = max(
            arm_metrics.keys(),
            key=lambda k: (
                arm_metrics[k].get("Avg_PnL_%")
                if isinstance(arm_metrics[k].get("Avg_PnL_%"), float)
                else float("-inf")
            ),
        )

    _write_csv(out_dir / "trades_filtered_source.csv", filtered)
    for lab, rows in arm_books.items():
        _write_csv(out_dir / f"trades_timestop_{lab}.csv", rows)

    flat_rows = [_metric_row(lab, arm_metrics[lab], vs_ctrl=arm_metrics[CONTROL_ARM]) for lab, _ in TIME_STOP_ARMS]
    if flat_rows:
        with (out_dir / "metrics_timestop.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
            w.writeheader()
            w.writerows(flat_rows)

    # Cell breakdown CSV under control
    cell_rows = []
    for shape, side in ALLOWED_CELLS:
        key = f"{shape}×{side}"
        bucket = [t for t in arm_books[breakdown_arm] if key in cell_keys_for_trade(t)]
        m = ab.metrics_from_trades(bucket, include_slices=False)
        cell_rows.append(
            {
                "shape_side": key,
                "N": m.get("N"),
                "Win%": m.get("Win%"),
                "Avg_PnL_%": m.get("Avg_PnL_%"),
                "Profit_Factor": m.get("Profit_Factor"),
                "Sheet_PnL_$": m.get("Sheet_PnL_$", m.get("Total_PnL_$")),
                "Max_DD_%": m.get("Max_DD_%"),
            }
        )
    with (out_dir / "metrics_cells_1130.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cell_rows[0].keys()) if cell_rows else ["shape_side"])
        w.writeheader()
        w.writerows(cell_rows)

    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        source_stamp=source_stamp,
        n_source=len(source),
        n_shared=len(shared),
        n_filtered=len(filtered),
        verdict=verdict,
        arm_metrics=arm_metrics,
    )
    write_compare_html(
        out_dir / "compare.html",
        stamp=stamp,
        source_stamp=source_stamp,
        n_source=len(source),
        n_shared=len(shared),
        n_filtered=len(filtered),
        arm_books=arm_books,
        arm_metrics=arm_metrics,
        verdict=verdict,
        breakdown_arm=breakdown_arm,
    )

    summary_lines = [
        f"# SUMMARY — `{stamp}`",
        "",
        f"Filtered N={len(filtered)} (shared {len(shared)} of source {len(source)}).",
        f"**{verdict}**",
        "",
        "## Time-stop arms",
    ]
    for lab, _ts in TIME_STOP_ARMS:
        m = arm_metrics[lab]
        summary_lines.append(
            f"- **{lab}**: N={m.get('N')} WR%={ab._fmt_num(m.get('Win%'))} "
            f"Avg={ab._fmt_num(m.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(m.get('Profit_Factor'))} "
            f"Sheet={format_money(m.get('Sheet_PnL_$') or m.get('Total_PnL_$') or 0)} "
            f"MaxDD%={ab._fmt_num(m.get('Max_DD_%'))}"
        )
    summary_lines.extend(["", f"See `compare.html` (mobile-sortable) in `{out_dir.as_posix()}`."])
    (out_dir / "SUMMARY.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    (out_dir / "AB_PLAN.md").write_text(
        "\n".join(
            [
                f"# AB_PLAN — `{stamp}`",
                "",
                "One-knob: **time-stop clock** on a frozen filtered book.",
                "",
                "- Control: **11:30 ET** (prior scalp default).",
                "- Candidates: 11:00, 12:00, 13:00 ET.",
                "- Entries / stop / target / filters frozen (see BASELINE.md).",
                "- Judge on N / WR / Avg PnL% / PF / sheet PnL / Max DD; thin N → HOLD only.",
                "- Research only. No DailyRun wire.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(verdict, flush=True)
    for lab, _ts in TIME_STOP_ARMS:
        m = arm_metrics[lab]
        print(
            f"  {lab}: N={m.get('N')} WR={ab._fmt_num(m.get('Win%'))} "
            f"Avg={ab._fmt_num(m.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(m.get('Profit_Factor'))} "
            f"PnL={format_money(m.get('Total_PnL_$') or 0)} MaxDD={ab._fmt_num(m.get('Max_DD_%'))}",
            flush=True,
        )
    return {
        "stamp": stamp,
        "out_dir": str(out_dir),
        "n_filtered": len(filtered),
        "arm_metrics": arm_metrics,
        "verdict": verdict,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stamp", default=DEFAULT_STAMP)
    p.add_argument("--source-stamp", default=DEFAULT_SOURCE)
    args = p.parse_args()
    run(stamp=args.stamp, source_stamp=args.source_stamp)


if __name__ == "__main__":
    main()
