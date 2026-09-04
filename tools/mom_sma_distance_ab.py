#!/usr/bin/env python3
"""MOM SMA-distance AB — max entry extension vs SMA50 / SMA100.

Interprets Paul's "~12% from SMA50 / ~25% from SMA100" as **entry** one-knob
filters (Close/SMA - 1 ≤ threshold), matching winner-pattern `dist_sma*_pct`.

Research only. Not gold / not DailyRun.

Stamp: drive/paul_experiments/mom_sma_distance_ab_20260829/
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from datetime import date
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

from compare_format import (  # noqa: E402
    DEFAULT_INITIAL_ACCOUNT,
    is_excluded_html_compare_label,
)
import mom_clenow_ab as mom  # noqa: E402

STAMP = "mom_sma_distance_ab_20260829"
OUT_DIR = _PE / STAMP
IS_CUT = date(2024, 1, 1)
DEFAULT_UNIV = _PE / "mom_baseline_20260828" / "MOM_universe.csv"  # ALL_ohlc tape

# ENTRY extension arms — one knob each (max Close/SMA - 1). Exit = control freeze.
ARMS: list[dict[str, Any]] = [
    {
        "id": "control",
        "label": "Control (no max extension)",
        "max_ext_sma50": None,
        "max_ext_sma100": None,
        "knobs": "baseline freeze — no max dist filter",
        "one_knob": True,
        "kind": "control",
    },
    {
        "id": "max_ext_sma50_10",
        "label": "Max ext SMA50 ≤ 10%",
        "max_ext_sma50": 0.10,
        "max_ext_sma100": None,
        "knobs": "ENTRY: (Close/SMA50-1) ≤ 0.10",
        "one_knob": True,
        "kind": "entry_ext",
    },
    {
        "id": "max_ext_sma50_12",
        "label": "Max ext SMA50 ≤ 12%",
        "max_ext_sma50": 0.12,
        "max_ext_sma100": None,
        "knobs": "ENTRY: (Close/SMA50-1) ≤ 0.12 (Paul ~12%)",
        "one_knob": True,
        "kind": "entry_ext",
    },
    {
        "id": "max_ext_sma50_15",
        "label": "Max ext SMA50 ≤ 15%",
        "max_ext_sma50": 0.15,
        "max_ext_sma100": None,
        "knobs": "ENTRY: (Close/SMA50-1) ≤ 0.15 (nearby grid)",
        "one_knob": True,
        "kind": "entry_ext",
    },
    {
        "id": "max_ext_sma100_20",
        "label": "Max ext SMA100 ≤ 20%",
        "max_ext_sma50": None,
        "max_ext_sma100": 0.20,
        "knobs": "ENTRY: (Close/SMA100-1) ≤ 0.20 (nearby grid)",
        "one_knob": True,
        "kind": "entry_ext",
    },
    {
        "id": "max_ext_sma100_25",
        "label": "Max ext SMA100 ≤ 25%",
        "max_ext_sma50": None,
        "max_ext_sma100": 0.25,
        "knobs": "ENTRY: (Close/SMA100-1) ≤ 0.25 (Paul ~25%)",
        "one_knob": True,
        "kind": "entry_ext",
    },
    {
        "id": "max_ext_sma100_30",
        "label": "Max ext SMA100 ≤ 30%",
        "max_ext_sma50": None,
        "max_ext_sma100": 0.30,
        "knobs": "ENTRY: (Close/SMA100-1) ≤ 0.30 (nearby grid)",
        "one_knob": True,
        "kind": "entry_ext",
    },
]


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _pack_metrics(result: dict[str, Any]) -> dict[str, Any]:
    trades = result["trades"]
    eq_df = pd.DataFrame(result["equity"])
    eq_df["d"] = pd.to_datetime(eq_df["date"]).dt.date
    full_m = mom.equity_slice_metrics(eq_df, eq_df["d"].iloc[0], eq_df["d"].iloc[-1], "full")
    is_m = mom.equity_slice_metrics(eq_df, eq_df["d"].iloc[0], date(2023, 12, 31), "IS_eq")
    oos_m = mom.equity_slice_metrics(eq_df, IS_CUT, eq_df["d"].iloc[-1], "OOS_eq")
    is_tr = [t for t in trades if t.entry_date < IS_CUT]
    oos_tr = [t for t in trades if t.entry_date >= IS_CUT]
    tm_all = mom.trade_metrics(trades)
    tm_is = mom.trade_metrics(is_tr)
    tm_oos = mom.trade_metrics(oos_tr)
    exit_counts: dict[str, int] = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
    return {
        "full_m": full_m,
        "is_m": is_m,
        "oos_m": oos_m,
        "tm_all": tm_all,
        "tm_is": tm_is,
        "tm_oos": tm_oos,
        "exit_counts": exit_counts,
        "n_trades": len(trades),
        "final_equity": result["final_equity"],
        "calendar_start": result["calendar_start"].isoformat(),
        "calendar_end": result["calendar_end"].isoformat(),
    }


def _verdict(control: dict[str, Any], cand: dict[str, Any], arm: dict[str, Any]) -> str:
    """Quality-over-N KEEP/HOLD/DISMISS on IS trade metrics; OOS report-only."""
    c, x = control["tm_is"], cand["tm_is"]
    if c["n"] < 30 or x["n"] < 30:
        return "HOLD — thin IS N"
    n_ratio = x["n"] / c["n"] if c["n"] else 1.0
    better_avg = (
        (x["avg_pnl_pct"] - c["avg_pnl_pct"])
        if np.isfinite(x["avg_pnl_pct"]) and np.isfinite(c["avg_pnl_pct"])
        else 0.0
    )
    better_wr = (
        (x["win_rate"] - c["win_rate"])
        if np.isfinite(x["win_rate"]) and np.isfinite(c["win_rate"])
        else 0.0
    )
    better_pf = 0.0
    if np.isfinite(x["profit_factor"]) and np.isfinite(c["profit_factor"]):
        better_pf = x["profit_factor"] - c["profit_factor"]
    c_ann, x_ann = control["is_m"].get("ann_ror"), cand["is_m"].get("ann_ror")
    c_dd, x_dd = control["is_m"].get("max_dd"), cand["is_m"].get("max_dd")
    better_ann = (float(x_ann) - float(c_ann)) if np.isfinite(x_ann) and np.isfinite(c_ann) else 0.0
    better_dd = (float(c_dd) - float(x_dd)) if np.isfinite(x_dd) and np.isfinite(c_dd) else 0.0

    oos_note = ""
    o_c, o_x = control["tm_oos"], cand["tm_oos"]
    if o_c["n"] and o_x["n"] and np.isfinite(o_c["avg_pnl_pct"]) and np.isfinite(o_x["avg_pnl_pct"]):
        if o_x["avg_pnl_pct"] + 0.5 < o_c["avg_pnl_pct"] and better_avg > 0:
            oos_note = " OOS softens vs control → do not retune."

    if not arm["one_knob"]:
        return "HOLD — two-knob combo (selection bias); report-only."

    if n_ratio < 0.55 and better_avg < 1.0:
        return "DISMISS — N collapses without clear quality lift." + oos_note

    quality_up = (better_avg > 0.3 and better_pf >= -0.05) or (better_ann > 0.3 and better_dd >= -1.0)
    quality_down = (better_avg < -0.5 and better_pf < 0) or (better_ann < -0.5 and better_dd < -1.0)

    if quality_up and better_wr > -2.0 and n_ratio > 0.7:
        if o_c["n"] >= 20 and o_x["n"] >= 20 and np.isfinite(o_x["avg_pnl_pct"]) and np.isfinite(
            o_c["avg_pnl_pct"]
        ):
            if o_x["avg_pnl_pct"] + 1.0 < o_c["avg_pnl_pct"]:
                return "HOLD — IS quality up but OOS softens (report-only)." + oos_note
        return "LEAN KEEP — IS quality improves without N collapse; research-only, not gold." + oos_note
    if quality_down:
        return "DISMISS — IS quality worse vs control." + oos_note
    return "HOLD — flat / mixed vs control." + oos_note


def _fmt(x: Any, nd: int = 2) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(v):
        return "—"
    return f"{v:.{nd}f}"


def write_compare_html(out: Path, packs: dict[str, dict[str, Any]], arms: list[dict[str, Any]], univ_n: int) -> Path:
    control = packs["control"]
    cols = [
        ("Arm", "text"),
        ("Knobs", "text"),
        ("N full", "num"),
        ("N IS", "num"),
        ("N OOS", "num"),
        ("WR% IS", "num"),
        ("AvgPnL% IS", "num"),
        ("PF IS", "num"),
        ("Avg days IS", "num"),
        ("AnnROR% IS eq", "num"),
        ("MaxDD% IS eq", "num"),
        ("WR% OOS", "num"),
        ("AvgPnL% OOS", "num"),
        ("PF OOS", "num"),
        ("AnnROR% OOS eq", "num"),
        ("MaxDD% OOS eq", "num"),
        ("Verdict", "text"),
    ]
    head = "".join(_sortable_th(a, b) for a, b in cols if not is_excluded_html_compare_label(a))
    body = ""
    for arm in arms:
        p = packs[arm["id"]]
        if p.get("verdict"):
            v = p["verdict"]
        else:
            v = "CONTROL" if arm["id"] == "control" else _verdict(control, p, arm)
            packs[arm["id"]]["verdict"] = v
        row = [
            arm["id"],
            arm["knobs"],
            p["tm_all"]["n"],
            p["tm_is"]["n"],
            p["tm_oos"]["n"],
            _fmt(p["tm_is"]["win_rate"]),
            _fmt(p["tm_is"]["avg_pnl_pct"]),
            _fmt(p["tm_is"]["profit_factor"]),
            _fmt(p["tm_is"]["avg_days"]),
            _fmt(p["is_m"].get("ann_ror")),
            _fmt(p["is_m"].get("max_dd")),
            _fmt(p["tm_oos"]["win_rate"]),
            _fmt(p["tm_oos"]["avg_pnl_pct"]),
            _fmt(p["tm_oos"]["profit_factor"]),
            _fmt(p["oos_m"].get("ann_ror")),
            _fmt(p["oos_m"].get("max_dd")),
            v,
        ]
        tds = "".join(f"<td>{html_mod.escape(str(x))}</td>" for x in row)
        cls = ' class="total-row"' if arm["id"] == "control" else ""
        body += f"<tr{cls}>{tds}</tr>"

    exit_sections = ""
    for arm in arms:
        p = packs[arm["id"]]
        eh = _sortable_th("Exit reason", "text") + _sortable_th("N", "num")
        eb = "".join(
            f"<tr><td>{html_mod.escape(k)}</td><td>{v}</td></tr>"
            for k, v in sorted(p["exit_counts"].items(), key=lambda kv: -kv[1])
        )
        exit_sections += f"""
    <h3>{html_mod.escape(arm["id"])}</h3>
    <table class="sortable"><thead><tr>{eh}</tr></thead><tbody>{eb}</tbody></table>
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MOM SMA-distance AB — {STAMP}</title>
<style>
  body {{ font-family: "Segoe UI", system-ui, sans-serif; margin: 1.5rem; background: #f7f6f2; color: #1a1a1a; }}
  h1 {{ font-size: 1.35rem; }}
  .meta {{ color: #555; font-size: 0.92rem; max-width: 54rem; }}
  table.sortable {{ border-collapse: collapse; background: #fff; margin: 1rem 0 1.5rem; font-size: 0.88rem; }}
  th, td {{ border: 1px solid #d8d5cc; padding: 0.35rem 0.55rem; text-align: left; }}
  th {{ background: #efece4; }}
  tr.total-row {{ font-weight: 600; background: #f3f1ea; }}
  {mom.SORTABLE_TH_CSS}
</style>
</head>
<body>
  <h1>MOM SMA-distance AB — <code>{STAMP}</code></h1>
  <p class="meta">Research only · Not gold · Not DailyRun. Universe N={univ_n}
  (same ALL_ohlc tape as <code>mom_baseline_20260828</code>).
  Arms = <strong>ENTRY</strong> max extension filters: (Close/SMA − 1) ≤ threshold;
  exit unchanged (SMA100 weekly + rank, no hard stop). IS = entry &lt; 2024-01-01; OOS report-only.
  Click column headers to sort. No Sheet/Total PnL $ columns.</p>

  <h2>Arm compare (IS / OOS)</h2>
  <table class="sortable">
    <thead><tr>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table>

  <h2>Exit mix by arm</h2>
  {exit_sections}

  {mom.SORT_JS}
</body>
</html>
"""
    path = out / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_docs(out: Path, packs: dict[str, dict[str, Any]], arms: list[dict[str, Any]], univ_n: int, univ_path: Path) -> None:
    control = packs["control"]
    lines = [
        f"# BASELINE — `{STAMP}`",
        "",
        "**Status:** RESEARCH entry AB only. **Not gold. Not DailyRun-wired.**",
        "",
        "**Parent freeze:** `mom_baseline_20260828` (MOM = Momentum / Clenow weekly rank).",
        "",
        "**Hypothesis:** Cap how far price may sit **above** SMA50 / SMA100 at entry",
        "(Paul ~12% / ~25%). Winner scan (`mom_winner_patterns_20260829`) found large winners",
        "slightly *more* extended — this AB tests the opposite filter (max extension).",
        "",
        "## Universe",
        "",
        f"- Same tape as parent: `{univ_path.as_posix()}` → **N={univ_n}** (ALL_ohlc / full liquid list).",
        "- OHLC: `data/ohlcv.duckdb`.",
        "",
        "## Control (frozen)",
        "",
        "- Weekly review Wednesday; buy above SMA100 + gap filter + top 20% momentum; SPY > SMA200 for new buys.",
        "- **Exit:** close below SMA100 on weekly review; rank drop; **no hard stop**.",
        "- **No** max extension filter at entry.",
        "",
        "## Arm definitions (ENTRY one-knob)",
        "",
        "Eligibility filter (with Close > SMA100 + gap):",
        "",
        "- `max_ext_sma50_X`: only eligible if `(Close / SMA50 - 1) ≤ X/100`",
        "- `max_ext_sma100_X`: only eligible if `(Close / SMA100 - 1) ≤ X/100`",
        "",
        "Top 20% rank is computed **after** the extension filter (eligible pool shrinks).",
        "Do **not** combine SMA50 + SMA100 max-ext in one arm (would be two-knob).",
        "",
        "## Arms",
        "",
    ]
    for arm in arms:
        lines.append(
            f"- **`{arm['id']}`**: {arm['label']} — {arm['knobs']} (one_knob={arm['one_knob']})"
        )
    lines += [
        "",
        "## Exit / band variants (deferred)",
        "",
        "- Prior exit AB already DISMISS'd SMA50-cross and 5% hard stop (`mom_exit_tighten_20260829`).",
        "- \"Exit when Close falls >12% *below* SMA50\" would be a **wider** band than SMA-cross",
        "  (looser exit) — distinct but not the natural reading of Paul's distance ask given",
        "  winner `dist_sma*_pct` at entry. Deferred unless entry arms are thin / inconclusive.",
        "",
        "## IS / OOS",
        "",
        "- IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01` (report-only — do not retune).",
        "- KEEP/DISMISS on **quality** (WR, Avg PnL%, PF, Ann ROR / Max DD), not trade count alone.",
        "",
        "## Selection bias",
        "",
        "- Nearby grid (10/15%, 20/30%) chosen a priori around Paul's 12%/25% — still in-sample",
        "  if picking best grid cell after seeing the table; prefer Paul's exact arms for claims.",
        "",
        "## How to re-run",
        "",
        "```bash",
        "python tools/mom_sma_distance_ab.py",
        "python tools/mom_sma_distance_ab.py --limit 80  # smoke",
        "python tools/mom_sma_distance_ab.py --core-only  # control + Paul 12%/25% only",
        "```",
        "",
    ]
    (out / "BASELINE.md").write_text("\n".join(lines), encoding="utf-8")

    sum_lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        "MOM SMA-distance entry AB — research only.",
        "",
        "## Calendar",
        "",
        f"- Control window: {control['calendar_start']} → {control['calendar_end']}",
        "",
        "## Verdicts",
        "",
        "| Arm | Verdict |",
        "|-----|---------|",
    ]
    for arm in arms:
        p = packs[arm["id"]]
        sum_lines.append(f"| `{arm['id']}` | {p.get('verdict', '—')} |")
    sum_lines += [
        "",
        "## IS trade metrics",
        "",
        "| Arm | N | WR% | Avg PnL% | PF | Avg days | AnnROR% eq | MaxDD% eq |",
        "|-----|---|-----|----------|----|----------|------------|-----------|",
    ]
    for arm in arms:
        p = packs[arm["id"]]
        t = p["tm_is"]
        sum_lines.append(
            f"| `{arm['id']}` | {t['n']} | {_fmt(t['win_rate'])} | {_fmt(t['avg_pnl_pct'])} | "
            f"{_fmt(t['profit_factor'])} | {_fmt(t['avg_days'])} | "
            f"{_fmt(p['is_m'].get('ann_ror'))} | {_fmt(p['is_m'].get('max_dd'))} |"
        )
    sum_lines += [
        "",
        "## OOS trade metrics (report-only)",
        "",
        "| Arm | N | WR% | Avg PnL% | PF | AnnROR% eq | MaxDD% eq |",
        "|-----|---|-----|----------|----|------------|-----------|",
    ]
    for arm in arms:
        p = packs[arm["id"]]
        t = p["tm_oos"]
        sum_lines.append(
            f"| `{arm['id']}` | {t['n']} | {_fmt(t['win_rate'])} | {_fmt(t['avg_pnl_pct'])} | "
            f"{_fmt(t['profit_factor'])} | {_fmt(p['oos_m'].get('ann_ror'))} | {_fmt(p['oos_m'].get('max_dd'))} |"
        )
    sum_lines += [
        "",
        "## Notes",
        "",
        "1. OOS is report-only — do not retune on OOS lifts/softens.",
        "2. Winner patterns suggested more extension at entry for big winners — expect max-ext",
        "   filters may cut winners; quality over N decides KEEP/DISMISS.",
        "3. Not gold / not DailyRun.",
        "",
        "## Artifacts",
        "",
        "- `compare.html` — sortable arm table",
        "- `arms/*.csv` — per-arm Closed / Equity",
        "- `BASELINE.md` / `SUMMARY.md` / `meta.json`",
        "",
    ]
    (out / "SUMMARY.md").write_text("\n".join(sum_lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="MOM SMA-distance entry AB")
    ap.add_argument("--db", type=Path, default=mom.DEFAULT_DB)
    ap.add_argument("--universe", type=Path, default=DEFAULT_UNIV)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--start", type=str, default="2010-01-04")
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--capital", type=float, default=DEFAULT_INITIAL_ACCOUNT)
    ap.add_argument(
        "--core-only",
        action="store_true",
        help="Run only control + max_ext_sma50_12 + max_ext_sma100_25",
    )
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    arms_dir = out / "arms"
    arms_dir.mkdir(parents=True, exist_ok=True)

    univ = mom.load_universe(args.universe)
    if args.limit and args.limit > 0:
        univ = univ[: args.limit]
        print(f"[sma-dist-AB] smoke limit -> {len(univ)}")

    start = date.fromisoformat(args.start) if args.start else None
    end = date.fromisoformat(args.end) if args.end else None

    print(f"[sma-dist-AB] Loading panel {len(univ)} + SPY ...")
    panel = mom.load_panel(args.db, univ, start=start, end=end)
    loaded = [s for s in univ if s in panel]
    print(f"[sma-dist-AB] Loaded {len(loaded)} / {len(univ)}")

    if args.core_only:
        keep = {"control", "max_ext_sma50_12", "max_ext_sma100_25"}
        arms = [a for a in ARMS if a["id"] in keep]
    else:
        arms = list(ARMS)

    packs: dict[str, dict[str, Any]] = {}

    for arm in arms:
        print(
            f"[sma-dist-AB] Running {arm['id']} "
            f"ext50={arm['max_ext_sma50']} ext100={arm['max_ext_sma100']} ..."
        )
        result = mom.run_backtest(
            panel,
            loaded,
            initial_capital=args.capital,
            bt_start=start,
            bt_end=end,
            sma_exit_n=100,
            stop_pct=None,
            max_ext_sma50=arm["max_ext_sma50"],
            max_ext_sma100=arm["max_ext_sma100"],
        )
        pack = _pack_metrics(result)
        packs[arm["id"]] = pack
        closed = arms_dir / f"MOM_Closed_{arm['id']}.csv"
        with closed.open("w", encoding="utf-8", newline="") as f:
            f.write(
                "SYMBOL,ENTRY_DATE,EXIT_DATE,ENTRY_PX,EXIT_PX,SHARES,PNL_PCT,PNL_DOLLARS,"
                "DAYS_HELD,EXIT_REASON,ENTRY_SCORE\n"
            )
            for t in result["trades"]:
                f.write(
                    f"{t.symbol},{t.entry_date.isoformat()},{t.exit_date.isoformat()},"
                    f"{t.entry_px:.4f},{t.exit_px:.4f},{t.shares},{t.pnl_pct:.4f},"
                    f"{t.pnl_dollars:.2f},{t.days_held},{t.exit_reason},{t.entry_score:.6f}\n"
                )
        eq = arms_dir / f"MOM_Equity_{arm['id']}.csv"
        pd.DataFrame(result["equity"]).to_csv(eq, index=False)
        print(
            f"  trades={pack['n_trades']} final_eq={pack['final_equity']:.0f} "
            f"IS avgPnL={_fmt(pack['tm_is']['avg_pnl_pct'])} OOS n={pack['tm_oos']['n']}"
        )

    for arm in arms:
        if arm["id"] == "control":
            packs[arm["id"]]["verdict"] = "CONTROL"
        else:
            packs[arm["id"]]["verdict"] = _verdict(packs["control"], packs[arm["id"]], arm)

    write_compare_html(out, packs, arms, len(loaded))
    write_docs(out, packs, arms, len(loaded), args.universe)

    meta = {
        "stamp": STAMP,
        "universe": str(args.universe),
        "univ_n": len(loaded),
        "arms": {
            a["id"]: {
                "verdict": packs[a["id"]]["verdict"],
                "max_ext_sma50": a["max_ext_sma50"],
                "max_ext_sma100": a["max_ext_sma100"],
                "metrics": {
                    "n_is": packs[a["id"]]["tm_is"]["n"],
                    "avg_pnl_is": packs[a["id"]]["tm_is"]["avg_pnl_pct"],
                    "wr_is": packs[a["id"]]["tm_is"]["win_rate"],
                    "pf_is": packs[a["id"]]["tm_is"]["profit_factor"],
                    "n_oos": packs[a["id"]]["tm_oos"]["n"],
                    "avg_pnl_oos": packs[a["id"]]["tm_oos"]["avg_pnl_pct"],
                    "wr_oos": packs[a["id"]]["tm_oos"]["win_rate"],
                    "pf_oos": packs[a["id"]]["tm_oos"]["profit_factor"],
                    "ann_ror_is": packs[a["id"]]["is_m"].get("ann_ror"),
                    "max_dd_is": packs[a["id"]]["is_m"].get("max_dd"),
                    "ann_ror_oos": packs[a["id"]]["oos_m"].get("ann_ror"),
                    "max_dd_oos": packs[a["id"]]["oos_m"].get("max_dd"),
                },
            }
            for a in arms
        },
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"[sma-dist-AB] Wrote stamp {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
