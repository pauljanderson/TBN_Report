#!/usr/bin/env python3
"""Scalp filter relax A/B — drop top N-killer filters, re-score (research only).

Ranks selection filters by absolute marginal N cut vs setup_bar_0p05 baseline,
then builds books that drop the top 1 / 2 / 3 killers while keeping
setup_bar_0p05 stop construction. Time-stop control = 1130 (reuse source PnL);
optional 1100/1200/1300 via reexit.

Usage:
  python tools/scalp_filter_relax_ab.py
  python tools/scalp_filter_relax_ab.py --stamp scalp_filter_relax_20260822
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from datetime import date as date_cls
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import scalp_filtered_timestop_ab as filt  # noqa: E402
import scalp_full_levers_pack as pack  # noqa: E402
import scalp_open15_reversal_ab as ab  # noqa: E402
from compare_format import format_money  # noqa: E402
from intraday_1m import DEFAULT_1M_DIR, ET, read_1m, resample_ohlcv  # noqa: E402

DRIVE = ROOT / "drive"
DEFAULT_STAMP = "scalp_filter_relax_20260822"
DEFAULT_SOURCE = "scalp_full_levers_20260822"
SYSTEM = "scalp"
CONTROL_ARM = "1130"

TIME_STOP_ARMS: list[tuple[str, time]] = [
    ("1100", time(11, 0)),
    ("1130", time(11, 30)),
    ("1200", time(12, 0)),
    ("1300", time(13, 0)),
]

# Selection filters eligible to drop (not stop construction / not exit arm).
FILTER_IDS = ("mid_5m_20m", "entirely_out", "40_60pct", "shape_side_or")


def _passes_mid(t: dict[str, Any]) -> bool:
    return str(t.get("adv_bucket") or "") == "mid_5m_20m"


def _passes_eo(t: dict[str, Any]) -> bool:
    return str(t.get("entirely_out") or "") == "entirely_out"


def _passes_range(t: dict[str, Any]) -> bool:
    return str(t.get("range_atr_bucket") or "") == "40_60pct"


def _passes_shape(t: dict[str, Any]) -> bool:
    return filt.passes_shape_side(t)


PASSERS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "mid_5m_20m": _passes_mid,
    "entirely_out": _passes_eo,
    "40_60pct": _passes_range,
    "shape_side_or": _passes_shape,
}

FILTER_LABELS = {
    "mid_5m_20m": "ADV$ mid_5m_20m",
    "entirely_out": "entirely_out",
    "40_60pct": "open15 range/ATR 40_60pct",
    "shape_side_or": "shape×side OR (5 allowed cells)",
}


def compute_funnel(source: list[dict[str, Any]]) -> dict[str, Any]:
    n0 = len(source)
    marginal: list[dict[str, Any]] = []
    for fid in FILTER_IDS:
        fn = PASSERS[fid]
        rem = sum(1 for t in source if fn(t))
        marginal.append(
            {
                "filter": fid,
                "remaining_N": rem,
                "abs_drop": n0 - rem,
            }
        )
    marginal.sort(key=lambda r: r["abs_drop"], reverse=True)

    # Sequential in tool order (shared then shape)
    seq_order = ["mid_5m_20m", "entirely_out", "40_60pct", "shape_side_or"]
    seq_rows: list[dict[str, Any]] = [{"step": "baseline_setup_bar_0p05", "remaining_N": n0, "delta": ""}]
    cur = source
    for fid in seq_order:
        fn = PASSERS[fid]
        nxt = [t for t in cur if fn(t)]
        seq_rows.append(
            {
                "step": f"+ {fid}",
                "remaining_N": len(nxt),
                "delta": len(nxt) - len(cur),
            }
        )
        cur = nxt

    # Leave-one-out from full stack
    full_fns = [PASSERS[f] for f in FILTER_IDS]
    full_n = sum(1 for t in source if all(fn(t) for fn in full_fns))
    loo: list[dict[str, Any]] = []
    for omit in FILTER_IDS:
        keep = [PASSERS[f] for f in FILTER_IDS if f != omit]
        rem = sum(1 for t in source if all(fn(t) for fn in keep))
        loo.append({"omit": omit, "remaining_N": rem, "recover": rem - full_n})
    loo.sort(key=lambda r: r["recover"], reverse=True)

    ranked = [r["filter"] for r in marginal]
    return {
        "n0": n0,
        "full_n": full_n,
        "marginal": marginal,
        "sequential": seq_rows,
        "leave_one_out": loo,
        "ranked_by_abs_drop": ranked,
    }


def apply_filters(
    source: list[dict[str, Any]],
    *,
    active: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in source:
        ok = True
        for fid in FILTER_IDS:
            if fid in active and not PASSERS[fid](t):
                ok = False
                break
        if ok:
            out.append(t)
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


def _metric_row(
    filter_arm: str,
    ts_arm: str,
    m: dict[str, Any],
    *,
    vs_full: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    row = {
        "filter_arm": filter_arm,
        "time_stop": ts_arm,
        "N": m.get("N"),
        "Win%": m.get("Win%"),
        "Avg_PnL_%": m.get("Avg_PnL_%"),
        "AVG_PNL_PCT_WO_MAX": m.get("AVG_PNL_PCT_WO_MAX"),
        "Profit_Factor": m.get("Profit_Factor"),
        "Sheet_PnL_$": m.get("Sheet_PnL_$", m.get("Total_PnL_$")),
        "Total_PnL_$": m.get("Total_PnL_$"),
        "Expectancy_$": m.get("Expectancy_$"),
        "Max_DD_%": m.get("Max_DD_%"),
        "Ann_ROR_%": m.get("Ann_ROR_%"),
        "exit_TIME": (m.get("exit_mix") or {}).get("TIME", 0),
        "exit_STOP": (m.get("exit_mix") or {}).get("STOP", 0),
        "exit_TARGET": (m.get("exit_mix") or {}).get("TARGET", 0),
    }
    if vs_full is not None:
        for key, dkey in (
            ("N", "ΔN_vs_full"),
            ("Avg_PnL_%", "ΔAvg_vs_full"),
            ("Win%", "ΔWin%_vs_full"),
            ("Profit_Factor", "ΔPF_vs_full"),
            ("Sheet_PnL_$", "ΔSheet_vs_full"),
            ("Max_DD_%", "ΔMaxDD_vs_full"),
        ):
            a, b = vs_full.get(key), m.get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(float(a)) and math.isfinite(float(b)):
                row[dkey] = float(b) - float(a)
            else:
                row[dkey] = ""
    return row


def pick_verdict(
    *,
    funnel: dict[str, Any],
    metrics_1130: dict[str, dict[str, Any]],
) -> str:
    full = metrics_1130.get("full_filtered") or {}
    n_full = int(full.get("N") or 0)
    notes = [
        f"Funnel top killers (marginal abs dN): {', '.join(funnel['ranked_by_abs_drop'][:3])}.",
        "Short Yahoo 1m window - IS/OOS chronological split not applicable; research-only.",
        "Selection bias: filters ranked on same book then dropped; not KEEP/gold/DailyRun.",
    ]
    # Thin N on full → any quality on drop arms is exploratory
    if n_full < 20:
        notes.append(
            f"HOLD - full_filtered N={n_full} too thin; drop arms inflate N but quality "
            "must not be overfit on short window."
        )
    best_arm = "full_filtered"
    best_avg = full.get("Avg_PnL_%")
    for arm, m in metrics_1130.items():
        if arm == "full_filtered":
            continue
        avg = m.get("Avg_PnL_%")
        n = int(m.get("N") or 0)
        if n < 20:
            continue
        if (
            isinstance(avg, float)
            and isinstance(best_avg, float)
            and math.isfinite(avg)
            and math.isfinite(best_avg)
            and avg > best_avg + 0.01
        ):
            # Prefer quality without collapsing PF badly — still HOLD if short window
            best_avg = avg
            best_arm = arm
    if best_arm == "full_filtered":
        notes.append(
            "HOLD - no drop arm clearly beats full_filtered on Avg PnL% with usable N "
            "(or full book too thin to promote)."
        )
    else:
        n_b = int(metrics_1130[best_arm].get("N") or 0)
        if n_b < 50:
            notes.append(
                f"HOLD - `{best_arm}` leads Avg on short window but N={n_b} still thin "
                "(no KEEP)."
            )
        else:
            notes.append(
                f"HOLD - `{best_arm}` modestly ahead on Avg under short-window research; "
                "do not KEEP / do not retune further on this book."
            )
    return " ".join(notes)


def write_baseline(
    path: Path,
    *,
    stamp: str,
    source_stamp: str,
    funnel: dict[str, Any],
    arm_defs: dict[str, dict[str, Any]],
    metrics_1130: dict[str, dict[str, Any]],
    verdict: str,
) -> None:
    ranked = funnel["ranked_by_abs_drop"]
    lines = [
        f"# BASELINE — Scalp filter relax A/B — `{stamp}`",
        "",
        f"**System:** `{SYSTEM}` (research only). **Not** DailyRun. **Not** gold.",
        f"Source: `drive/paul_experiments/{source_stamp}/trades_stop_setup_bar_0p05.csv` "
        f"(N={funnel['n0']}).",
        "",
        "## Ranking basis",
        "",
        "Selection filters ranked by **absolute marginal N cut** vs baseline "
        f"(each filter alone). Top killers: **{ranked[0]}**, **{ranked[1]}**, **{ranked[2]}**.",
        "`setup_bar_0p05` and time-stop `1130` are construction/exit — not dropped.",
        "",
        "## Arms (filters kept)",
        "",
        "| Arm | Dropped | Kept selection filters |",
        "|-----|---------|------------------------|",
    ]
    for arm, d in arm_defs.items():
        dropped = ", ".join(d["dropped"]) if d["dropped"] else "—(none)"
        kept = ", ".join(sorted(d["active"])) if d["active"] else "—(none)"
        lines.append(f"| `{arm}` | {dropped} | {kept} |")
    lines.extend(
        [
            "",
            "## Freeze (shared construction)",
            "",
            "| Knob | Value |",
            "|------|--------|",
            "| Stop | **setup_bar_0p05** (frozen) |",
            "| Target | open15 extreme (frozen) |",
            "| Time-stop arms | 11:00 / **11:30** / 12:00 / 13:00 ET |",
            f"| Sheet | ${ab.SHEET:,.0f}/trade |",
            "",
            "## Coverage / honesty",
            "",
            "- Default chronological IS/OOS **not applicable** (short Yahoo 1m window).",
            "- Filter ranking + drop arms = **in-sample selection** on levers book.",
            "- Judge **quality over N**; thin N → HOLD only.",
            "",
            "## Control 11:30 metrics by filter arm",
            "",
            "| Arm | N | WR% | Avg PnL% | Avg wo max | PF | Sheet PnL | Max DD% |",
            "|-----|---|-----|----------|------------|----|-----------|---------|",
        ]
    )
    for arm in arm_defs:
        m = metrics_1130[arm]
        lines.append(
            f"| `{arm}` | {m.get('N')} | {ab._fmt_num(m.get('Win%'))} | "
            f"{ab._fmt_num(m.get('Avg_PnL_%'), 4)} | {ab._fmt_num(m.get('AVG_PNL_PCT_WO_MAX'), 4)} | "
            f"{ab._fmt_num(m.get('Profit_Factor'))} | "
            f"{format_money(m.get('Sheet_PnL_$') or m.get('Total_PnL_$') or 0)} | "
            f"{ab._fmt_num(m.get('Max_DD_%'))} |"
        )
    lines.extend(["", f"**Verdict:** {verdict}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_compare_html(
    path: Path,
    *,
    stamp: str,
    source_stamp: str,
    funnel: dict[str, Any],
    arm_defs: dict[str, dict[str, Any]],
    all_metrics: dict[str, dict[str, dict[str, Any]]],
    verdict: str,
) -> None:
    ranked = funnel["ranked_by_abs_drop"]
    full_1130 = all_metrics["full_filtered"][CONTROL_ARM]

    # Funnel tables
    marg_head = "".join(
        ab.sortable_th(c, t)
        for c, t in (("filter", "text"), ("remaining_N", "num"), ("abs_drop", "num"))
    )
    marg_body = []
    for r in funnel["marginal"]:
        marg_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['filter'])}</td>"
            f"<td>{r['remaining_N']}</td>"
            f"<td>{r['abs_drop']}</td>"
            "</tr>"
        )

    seq_head = "".join(
        ab.sortable_th(c, t)
        for c, t in (("step", "text"), ("remaining_N", "num"), ("delta", "num"))
    )
    seq_body = []
    for r in funnel["sequential"]:
        seq_body.append(
            "<tr>"
            f"<td>{html_mod.escape(str(r['step']))}</td>"
            f"<td>{r['remaining_N']}</td>"
            f"<td>{html_mod.escape(str(r['delta']))}</td>"
            "</tr>"
        )

    # Main compare @1130
    cols = [
        ("filter_arm", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("AVG_PNL_PCT_WO_MAX", "num"),
        ("Profit_Factor", "num"),
        ("Sheet_PnL_$", "money"),
        ("Expectancy_$", "money"),
        ("Max_DD_%", "num"),
        ("ΔN_vs_full", "num"),
        ("ΔAvg_vs_full", "num"),
        ("ΔWin%_vs_full", "num"),
        ("ΔPF_vs_full", "num"),
        ("ΔSheet_vs_full", "num"),
        ("ΔMaxDD_vs_full", "num"),
        ("exit_TIME", "num"),
        ("exit_STOP", "num"),
        ("exit_TARGET", "num"),
        ("dropped", "text"),
    ]
    head = "".join(ab.sortable_th(c, t) for c, t in cols)
    body: list[str] = []
    for arm in arm_defs:
        m = all_metrics[arm][CONTROL_ARM]
        r = _metric_row(arm, CONTROL_ARM, m, vs_full=full_1130)
        r["dropped"] = ", ".join(arm_defs[arm]["dropped"]) if arm_defs[arm]["dropped"] else "—"
        cells = []
        for c, _t in cols:
            v = r.get(c)
            if c in ("Sheet_PnL_$", "Total_PnL_$", "Expectancy_$") and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif c.startswith("ΔSheet") and isinstance(v, (int, float)):
                cells.append(f"<td>{format_money(v)}</td>")
            elif isinstance(v, float):
                nd = 4 if ("Avg" in c or "ΔAvg" in c or "WO_MAX" in c) else 2
                cells.append(f"<td>{ab._fmt_num(v, nd)}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v if v is not None else '—'))}</td>")
        cls = " class='total-row'" if arm == "full_filtered" else ""
        body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")

    # Time-stop × filter grid
    ts_cols = [
        ("filter_arm", "text"),
        ("time_stop", "text"),
        ("N", "num"),
        ("Win%", "num"),
        ("Avg_PnL_%", "num"),
        ("Profit_Factor", "num"),
        ("Sheet_PnL_$", "money"),
        ("Max_DD_%", "num"),
        ("exit_TIME", "num"),
        ("exit_STOP", "num"),
        ("exit_TARGET", "num"),
    ]
    ts_head = "".join(ab.sortable_th(c, t) for c, t in ts_cols)
    ts_body: list[str] = []
    for arm in arm_defs:
        for lab, _ in TIME_STOP_ARMS:
            m = all_metrics[arm][lab]
            r = _metric_row(arm, lab, m)
            cells = []
            for c, _t in ts_cols:
                v = r.get(c)
                if c in ("Sheet_PnL_$", "Total_PnL_$") and isinstance(v, (int, float)):
                    cells.append(f"<td>{format_money(v)}</td>")
                elif isinstance(v, float):
                    cells.append(f"<td>{ab._fmt_num(v, 4 if 'Avg' in c else 2)}</td>")
                else:
                    cells.append(f"<td>{html_mod.escape(str(v if v is not None else '—'))}</td>")
            cls = " class='total-row'" if arm == "full_filtered" and lab == CONTROL_ARM else ""
            ts_body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")

    arm_note_rows = []
    for arm, d in arm_defs.items():
        arm_note_rows.append(
            f"<tr><td><code>{html_mod.escape(arm)}</code></td>"
            f"<td>{html_mod.escape(', '.join(d['dropped']) if d['dropped'] else '—')}</td>"
            f"<td>{html_mod.escape(', '.join(sorted(d['active'])) if d['active'] else '—')}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scalp filter relax — {html_mod.escape(stamp)}</title>
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
<h1>Scalp filter relax — drop top N-killers</h1>
<p class="sub">Stamp <code>{html_mod.escape(stamp)}</code> · source <code>{html_mod.escape(source_stamp)}</code> ·
research only · not DailyRun · not gold.</p>
<p class="note">Stop <code>setup_bar_0p05</code> frozen. Selection filters ranked by absolute marginal N cut.
Top killers: <strong>{html_mod.escape(ranked[0])}</strong>,
<strong>{html_mod.escape(ranked[1])}</strong>,
<strong>{html_mod.escape(ranked[2])}</strong>.
Control time-stop <strong>11:30</strong> reuses source book PnL; 11:00/12:00/13:00 reexit.
Tap / click column headers to sort (44px hit area).</p>

<p class="verdict">{html_mod.escape(verdict)}</p>

<h2>Arm definitions</h2>
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{ab.sortable_th("arm", "text")}
{ab.sortable_th("dropped", "text")}
{ab.sortable_th("kept", "text")}
</tr></thead>
<tbody>{''.join(arm_note_rows)}</tbody>
</table>
</div>

<h2>Funnel — marginal abs cut (ranking)</h2>
<p class="note">Baseline N={funnel['n0']}. Full filtered N={funnel['full_n']}.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{marg_head}</tr></thead>
<tbody>{''.join(marg_body)}</tbody>
</table>
</div>

<h2>Funnel — sequential AND stack</h2>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{seq_head}</tr></thead>
<tbody>{''.join(seq_body)}</tbody>
</table>
</div>

<h2>Filter arms @ control 11:30 (canonical-style)</h2>
<p class="note">Pinned row = full_filtered. Deltas vs full_filtered. Quality over N.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{head}</tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
</div>

<h2>Time-stop × filter arm grid</h2>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{ts_head}</tr></thead>
<tbody>{''.join(ts_body)}</tbody>
</table>
</div>

<p class="note">Generated {datetime.now(tz=ET).isoformat(timespec='seconds')} ·
tool <code>tools/scalp_filter_relax_ab.py</code></p>
{ab.SORT_JS}
</body></html>
"""
    path.write_text(html, encoding="utf-8")


def reexit_arm_book(
    trades: list[dict[str, Any]],
    *,
    day5_cache: dict[tuple[str, str], pd.DataFrame],
    arm_label: str,
    time_stop: time,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = len(trades)
    for i, t in enumerate(trades, 1):
        if i == 1 or i % 100 == 0 or i == n:
            print(f"  reexit {arm_label} [{i}/{n}] {t.get('symbol')} {t.get('session')}", flush=True)
        sym = str(t["symbol"])
        session = str(t["session"])
        key = (sym, session)
        if key not in day5_cache:
            d = date_cls.fromisoformat(str(session)[:10])
            df1 = ab.rth_filter(read_1m(sym, DEFAULT_1M_DIR))
            df5 = resample_ohlcv(df1, "5min")
            day5_cache[key] = ab.bars_on_day(df5, d)
        day5 = day5_cache[key]
        out.append(
            filt.reexit_time_stop(t, day5, arm_label=arm_label, time_stop=time_stop)
        )
    return out


def run(*, stamp: str, source_stamp: str) -> dict[str, Any]:
    out_dir = DRIVE / "paul_experiments" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    source = filt.load_setup_bar_trades(source_stamp)
    funnel = compute_funnel(source)
    ranked = funnel["ranked_by_abs_drop"]
    print("Ranked by abs marginal drop:", ranked, flush=True)

    # Arms: full + drop top1/2/3
    arm_defs: dict[str, dict[str, Any]] = {
        "full_filtered": {
            "dropped": [],
            "active": set(FILTER_IDS),
        },
        "drop_top1": {
            "dropped": ranked[:1],
            "active": set(FILTER_IDS) - set(ranked[:1]),
        },
        "drop_top2": {
            "dropped": ranked[:2],
            "active": set(FILTER_IDS) - set(ranked[:2]),
        },
        "drop_top3": {
            "dropped": ranked[:3],
            "active": set(FILTER_IDS) - set(ranked[:3]),
        },
    }

    filter_books: dict[str, list[dict[str, Any]]] = {}
    for arm, d in arm_defs.items():
        book = apply_filters(source, active=d["active"])
        filter_books[arm] = book
        print(f"{arm}: N={len(book)} dropped={d['dropped']}", flush=True)
        _write_csv(out_dir / f"trades_{arm}_source1130.csv", book)

    # Metrics: 1130 from source (already timed); other clocks reexit
    day5_cache: dict[tuple[str, str], pd.DataFrame] = {}
    all_books: dict[str, dict[str, list[dict[str, Any]]]] = {}
    all_metrics: dict[str, dict[str, dict[str, Any]]] = {}

    for arm, book in filter_books.items():
        all_books[arm] = {}
        all_metrics[arm] = {}
        # 1130: tag and reuse
        book_1130 = []
        for t in book:
            row = dict(t)
            row["time_stop_arm"] = CONTROL_ARM
            row["time_stop_clock"] = "11:30"
            row["filter_cells"] = "|".join(filt.cell_keys_for_trade(t))
            row["filter_relax_arm"] = arm
            book_1130.append(row)
        all_books[arm][CONTROL_ARM] = book_1130
        all_metrics[arm][CONTROL_ARM] = ab.metrics_from_trades(book_1130, include_slices=False)
        _write_csv(out_dir / f"trades_{arm}_timestop_{CONTROL_ARM}.csv", book_1130)

        for lab, ts in TIME_STOP_ARMS:
            if lab == CONTROL_ARM:
                continue
            print(f"Reexiting {arm} @ {lab} (N={len(book)})…", flush=True)
            rows = reexit_arm_book(book, day5_cache=day5_cache, arm_label=lab, time_stop=ts)
            for r in rows:
                r["filter_relax_arm"] = arm
            all_books[arm][lab] = rows
            all_metrics[arm][lab] = ab.metrics_from_trades(rows, include_slices=False)
            _write_csv(out_dir / f"trades_{arm}_timestop_{lab}.csv", rows)

    metrics_1130 = {arm: all_metrics[arm][CONTROL_ARM] for arm in arm_defs}
    verdict = pick_verdict(funnel=funnel, metrics_1130=metrics_1130)

    # Flat metrics CSV
    flat: list[dict[str, Any]] = []
    for arm in arm_defs:
        for lab, _ in TIME_STOP_ARMS:
            flat.append(
                _metric_row(
                    arm,
                    lab,
                    all_metrics[arm][lab],
                    vs_full=metrics_1130["full_filtered"] if lab == CONTROL_ARM else None,
                )
            )
    if flat:
        with (out_dir / "metrics_compare.csv").open("w", newline="", encoding="utf-8") as f:
            # union keys
            keys: list[str] = []
            seen: set[str] = set()
            for r in flat:
                for k in r:
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(flat)

    # Funnel CSV
    with (out_dir / "funnel_marginal.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["filter", "remaining_N", "abs_drop"])
        w.writeheader()
        w.writerows(funnel["marginal"])
    with (out_dir / "funnel_sequential.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["step", "remaining_N", "delta"])
        w.writeheader()
        w.writerows(funnel["sequential"])
    with (out_dir / "funnel_leave_one_out.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["omit", "remaining_N", "recover"])
        w.writeheader()
        w.writerows(funnel["leave_one_out"])

    write_baseline(
        out_dir / "BASELINE.md",
        stamp=stamp,
        source_stamp=source_stamp,
        funnel=funnel,
        arm_defs=arm_defs,
        metrics_1130=metrics_1130,
        verdict=verdict,
    )
    write_compare_html(
        out_dir / "compare.html",
        stamp=stamp,
        source_stamp=source_stamp,
        funnel=funnel,
        arm_defs=arm_defs,
        all_metrics=all_metrics,
        verdict=verdict,
    )

    # SUMMARY
    sum_lines = [
        f"# SUMMARY — `{stamp}`",
        "",
        f"**Verdict:** {verdict}",
        "",
        "## Funnel top killers (marginal abs ΔN)",
        "",
    ]
    for i, r in enumerate(funnel["marginal"], 1):
        sum_lines.append(
            f"{i}. `{r['filter']}`: remaining {r['remaining_N']} (drop −{r['abs_drop']})"
        )
    sum_lines.extend(
        [
            "",
            "## Arms @ control 11:30",
            "",
        ]
    )
    for arm in arm_defs:
        m = metrics_1130[arm]
        dropped = ", ".join(arm_defs[arm]["dropped"]) if arm_defs[arm]["dropped"] else "—"
        sum_lines.append(
            f"- **{arm}** (dropped: {dropped}): N={m.get('N')} "
            f"WR%={ab._fmt_num(m.get('Win%'))} Avg={ab._fmt_num(m.get('Avg_PnL_%'), 4)} "
            f"AvgWOmax={ab._fmt_num(m.get('AVG_PNL_PCT_WO_MAX'), 4)} "
            f"PF={ab._fmt_num(m.get('Profit_Factor'))} "
            f"Sheet={format_money(m.get('Sheet_PnL_$') or 0)} "
            f"MaxDD%={ab._fmt_num(m.get('Max_DD_%'))}"
        )
    sum_lines.extend(
        [
            "",
            f"See `compare.html` (mobile-sortable) in `{out_dir.as_posix()}`.",
            "Research only — no DailyRun.",
            "",
        ]
    )
    (out_dir / "SUMMARY.md").write_text("\n".join(sum_lines), encoding="utf-8")

    (out_dir / "AB_PLAN.md").write_text(
        "\n".join(
            [
                f"# AB_PLAN — `{stamp}`",
                "",
                "One hypothesis: **relax the strongest N-cutting selection filters** "
                "(ranked by absolute marginal cut) while freezing setup_bar_0p05 stop + target.",
                "",
                f"- Ranked killers: {', '.join(ranked)}",
                "- Arms: full_filtered, drop_top1, drop_top2, drop_top3",
                "- Time-stop: control 11:30 (+ 11:00/12:00/13:00 grid)",
                "- Judge quality (WR / Avg / PF / sheet / MaxDD) over N; thin → HOLD",
                "- Research only. No DailyRun.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(verdict, flush=True)
    for arm in arm_defs:
        m = metrics_1130[arm]
        print(
            f"  {arm}: N={m.get('N')} WR={ab._fmt_num(m.get('Win%'))} "
            f"Avg={ab._fmt_num(m.get('Avg_PnL_%'), 4)} PF={ab._fmt_num(m.get('Profit_Factor'))} "
            f"PnL={format_money(m.get('Total_PnL_$') or 0)}",
            flush=True,
        )
    return {
        "stamp": stamp,
        "out_dir": str(out_dir),
        "funnel": funnel,
        "metrics_1130": metrics_1130,
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
