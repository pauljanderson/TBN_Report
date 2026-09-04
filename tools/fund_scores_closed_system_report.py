#!/usr/bin/env python3
"""Enrich house Closed books with fund scorecard columns + cross-system pillar report.

Part 1: Join snapshot scores onto LatestRun / research Closed CSVs by SYMBOL.
Part 2: Bucket trades by pillar (Quality, Valuation, Growth Stability, Composite)
        and report N / WR / Avg PnL% / PF / WO_MAX by system (IS + OOS).

Research only — snapshot scores on historical entries (look-ahead labeled).
Not gold. Not DailyRun.

Usage:
  python tools/fund_scores_closed_system_report.py
  python tools/fund_scores_closed_system_report.py --enrich-only
  python tools/fund_scores_closed_system_report.py --report-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import filter_html_compare_columns, format_money  # noqa: E402
import rl_univ_compare_lists as _rlul  # noqa: E402
from rl_univ_compare_lists import book_stats, load_trades, split_is_oos  # noqa: E402

STAMP = "fund_scores_closed_system_report_20260831"
OUT = ROOT / "drive" / "paul_experiments" / STAMP
SCORES_DEFAULT = (
    ROOT / "drive" / "paul_experiments" / "fund_scorecard_v1_industry_20260831" / "scores.csv"
)
PILLAR_AB_METRICS = (
    ROOT / "drive" / "paul_experiments" / "fund_score_gate_pillars_rl_rs_vz_20260831" / "metrics_all.csv"
)
IS_CUT = date(2024, 1, 1)

# scorecard column → Closed column
FUND_JOIN: dict[str, str] = {
    "fund_quality": "score_quality",
    "fund_valuation": "score_valuation",
    "fund_growth_stability": "score_growth_stability",
    "fund_composite": "score_composite",
    "fund_financial_health": "score_financial_health",
    "fund_sector": "sector",
    "fund_industry": "industry",
    "fund_peer_group": "peer_mode",
    "fund_quality_sector": "score_quality_sector",
    "fund_valuation_sector": "score_valuation_sector",
    "fund_growth_stability_sector": "score_growth_stability_sector",
    "fund_composite_sector": "score_composite_sector",
}

PILLARS = [
    ("quality", "Quality", "fund_quality"),
    ("valuation", "Valuation", "fund_valuation"),
    ("growth_stability", "Growth Stability", "fund_growth_stability"),
    ("composite", "Composite", "fund_composite"),
]

BUCKETS = [
    ("ge70", "≥ 70", lambda v: v >= 70),
    ("60_69", "60–69", lambda v: 60 <= v < 70),
    ("lt60", "< 60", lambda v: v < 60),
    ("missing", "missing", None),
]

RL764_CANDIDATES = [
    ROOT
    / "drive"
    / "paul_experiments"
    / "rl_tradable_2010_adv2m_20260828"
    / "runs"
    / "tradable"
    / "RL_Closed_260828112205.csv",
    ROOT / "drive" / "RL_Closed_260828112205.csv",
]

# House systems with production LatestRun Closed under drive/
LATEST_RUN_SYSTEMS = [
    "BRT",
    "RL",
    "RS",
    "VZ",
    "YH",
    "WPBR",
    "MVCP",
    "SB",
    "MTS",
    "IND",
    "QULL",
    "CS",
    "KELL",
    "WRL",
]

CASH_BY_SYSTEM: dict[str, float] = {
    "VZ": 45_000.0,
    "RS": 47_500.0,
    "RL": 47_500.0,
    "RL764": 47_500.0,
}


def esc(x: object) -> str:
    return html_mod.escape("" if x is None else str(x))


def fmt_n(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def fmt_pct(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    return f"{v:.{d}f}"


def fmt_delta(v: float, d: int = 2) -> str:
    if v is None or not math.isfinite(v):
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{d}f}"


def _metric_delta(a: float, b: float) -> float:
    if not math.isfinite(a) or not math.isfinite(b):
        return float("nan")
    return a - b


CONTROL_LABEL = "control (full book)"
CONTROL_NOTE = (
    "Control = full Closed book for that system (all trades, unfiltered by fund-score bucket). "
    "Each pillar re-buckets the same book by that pillar's score; control metrics are identical "
    "across pillars within a system/split."
)


def _vs_control_table_cols() -> list[tuple[str, str]]:
    return filter_html_compare_columns(
        [
            ("Bucket", "text"),
            ("N", "num"),
            ("WR %", "num"),
            ("Avg PnL %", "num"),
            ("WO_MAX %", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Δ N vs ctrl", "num"),
            ("Δ WR vs ctrl", "num"),
            ("Δ Avg vs ctrl", "num"),
            ("Δ WO_MAX vs ctrl", "num"),
            ("Δ PF vs ctrl", "num"),
            ("Δ Ann ROR vs ctrl", "num"),
        ]
    )


def _ann_sort_val(v: float) -> str:
    return f"{v}" if math.isfinite(v) else ""


def _bucket_vs_control_row(
    bucket_label: str,
    bucket_id: str,
    m: dict[str, Any],
    ctrl: dict[str, Any],
    *,
    is_control: bool = False,
    row_class: str = "",
) -> str:
    ann = m.get("ann_ror", float("nan"))
    if is_control:
        d_n, d_wr, d_avg, d_wo, d_pf, d_ann = 0, 0.0, 0.0, 0.0, 0.0, 0.0
    else:
        d_n = m.get("n", 0) - ctrl.get("n", 0)
        d_wr = _metric_delta(m.get("wr", float("nan")), ctrl.get("wr", float("nan")))
        d_avg = _metric_delta(m.get("avg_pnl", float("nan")), ctrl.get("avg_pnl", float("nan")))
        d_wo = _metric_delta(m.get("wo_max", float("nan")), ctrl.get("wo_max", float("nan")))
        d_pf = _metric_delta(m.get("pf", float("nan")), ctrl.get("pf", float("nan")))
        d_ann = _metric_delta(ann, ctrl.get("ann_ror", float("nan")))
    cls = f' class="{row_class}"' if row_class else ""
    return (
        f"<tr{cls}>"
        f'<td data-sort-value="{esc(bucket_id)}">{esc(bucket_label)}</td>'
        f'<td data-sort-value="{m.get("n", 0)}">{m.get("n", 0)}</td>'
        f'<td data-sort-value="{m.get("wr", 0)}">{fmt_pct(m.get("wr", 0))}</td>'
        f'<td data-sort-value="{m.get("avg_pnl", 0)}">{fmt_pct(m.get("avg_pnl", 0))}</td>'
        f'<td data-sort-value="{m.get("wo_max", 0)}">{fmt_pct(m.get("wo_max", 0))}</td>'
        f'<td data-sort-value="{m.get("pf", 0)}">{fmt_n(m.get("pf", 0))}</td>'
        f'<td data-sort-value="{_ann_sort_val(ann)}">{fmt_pct(ann)}</td>'
        f'<td data-sort-value="{d_n}">{d_n if not is_control else "0"}</td>'
        f'<td data-sort-value="{d_wr if math.isfinite(d_wr) else 0}">'
        f'{fmt_delta(d_wr) if not is_control else "0.00"}</td>'
        f'<td data-sort-value="{d_avg if math.isfinite(d_avg) else 0}">'
        f'{fmt_delta(d_avg) if not is_control else "0.00"}</td>'
        f'<td data-sort-value="{d_wo if math.isfinite(d_wo) else 0}">'
        f'{fmt_delta(d_wo) if not is_control else "0.00"}</td>'
        f'<td data-sort-value="{d_pf if math.isfinite(d_pf) else 0}">'
        f'{fmt_delta(d_pf) if not is_control else "0.00"}</td>'
        f'<td data-sort-value="{d_ann if math.isfinite(d_ann) else 0}">'
        f'{fmt_delta(d_ann) if not is_control else "0.00"}</td>'
        "</tr>"
    )


def resolve_rl764() -> Optional[Path]:
    for p in RL764_CANDIDATES:
        if p.is_file():
            return p
    return None


def closed_targets() -> list[dict[str, Any]]:
    drive = ROOT / "drive"
    out: list[dict[str, Any]] = []
    for sys in LATEST_RUN_SYSTEMS:
        p = drive / f"{sys}_LatestRun_Closed.csv"
        if p.is_file():
            out.append(
                {
                    "id": sys,
                    "label": f"{sys} LatestRun",
                    "closed": p,
                    "cash": CASH_BY_SYSTEM.get(sys, 47_500.0),
                }
            )
    rl764 = resolve_rl764()
    if rl764:
        out.append(
            {
                "id": "RL764",
                "label": "RL 764 tradable",
                "closed": rl764,
                "cash": CASH_BY_SYSTEM["RL764"],
            }
        )
    return out


def load_scores(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    pillar_cols = [
        "score_valuation",
        "score_quality",
        "score_growth_stability",
        "score_financial_health",
    ]
    present = [c for c in pillar_cols if c in df.columns]
    if "score_composite" not in df.columns and present:
        df["score_composite"] = df[present].mean(axis=1, skipna=True)
    return df.set_index("symbol", drop=False)


def _symbol_col(fieldnames: list[str]) -> Optional[str]:
    norm = {c.upper().replace(" ", "_"): c for c in fieldnames}
    for key in ("SYMBOL",):
        if key in norm:
            return norm[key]
    return None


def enrich_closed_file(
    closed_path: Path,
    scores: pd.DataFrame,
    *,
    out_path: Path,
    backup_path: Optional[Path] = None,
    in_place: bool = False,
) -> dict[str, Any]:
    """Write enriched Closed CSV; optionally backup source first."""
    if not closed_path.is_file():
        return {"ok": False, "reason": "missing", "path": str(closed_path)}

    if backup_path and not backup_path.is_file():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(closed_path, backup_path)

    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"ok": False, "reason": "no_header", "path": str(closed_path)}
        sym_col = _symbol_col(list(reader.fieldnames))
        if not sym_col:
            return {"ok": False, "reason": "no_symbol_col", "path": str(closed_path)}

        existing = set(reader.fieldnames)
        new_cols = [c for c in FUND_JOIN if c not in existing]
        out_fields = list(reader.fieldnames) + new_cols

        rows_out: list[dict[str, str]] = []
        n_matched = n_rows = 0
        for raw in reader:
            n_rows += 1
            sym = (raw.get(sym_col) or "").strip().upper()
            row = dict(raw)
            if sym and sym in scores.index:
                n_matched += 1
                srow = scores.loc[sym]
                for out_col, src_col in FUND_JOIN.items():
                    if out_col in existing:
                        continue
                    val = srow[src_col] if src_col in scores.columns else ""
                    if val is None or (isinstance(val, float) and not math.isfinite(val)):
                        row[out_col] = ""
                    else:
                        row[out_col] = str(val)
            else:
                for out_col in new_cols:
                    row.setdefault(out_col, "")
            rows_out.append(row)

    dest = closed_path if in_place else out_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)

    return {
        "ok": True,
        "path": str(dest),
        "source": str(closed_path),
        "rows": n_rows,
        "matched": n_matched,
        "cols_added": new_cols,
        "backup": str(backup_path) if backup_path else "",
    }


def enrich_all(scores_path: Path, *, in_place_latest: bool = True) -> list[dict[str, Any]]:
    scores = load_scores(scores_path)
    results: list[dict[str, Any]] = []
    backup_dir = OUT / "backups"
    enriched_dir = OUT / "enriched"

    for spec in closed_targets():
        closed = spec["closed"]
        sys_id = spec["id"]
        backup = backup_dir / closed.name
        parallel = closed.parent / closed.name.replace("_Closed.csv", "_Closed_fundscores.csv")
        if parallel.name == closed.name:
            parallel = closed.parent / f"{closed.stem}_fundscores.csv"

        # Stamp copy (always)
        stamp_copy = enriched_dir / closed.name
        r = enrich_closed_file(
            closed,
            scores,
            out_path=stamp_copy,
            backup_path=backup,
            in_place=False,
        )
        r["system"] = sys_id
        r["kind"] = "stamp_enriched"
        results.append(r)

        # Parallel fundscores beside original (safe for reconcile)
        if r.get("ok"):
            shutil.copy2(stamp_copy, parallel)
            r_parallel = dict(r)
            r_parallel["path"] = str(parallel)
            r_parallel["kind"] = "parallel_fundscores"
            results.append(r_parallel)

        # In-place LatestRun enrich (append columns only)
        if in_place_latest and "_LatestRun_" in closed.name and r.get("ok"):
            r_live = enrich_closed_file(
                closed,
                scores,
                out_path=closed,
                backup_path=backup if not backup.is_file() else None,
                in_place=True,
            )
            r_live["system"] = sys_id
            r_live["kind"] = "latest_in_place"
            results.append(r_live)

    return results


def _bucket_label(score: Optional[float]) -> str:
    if score is None or not math.isfinite(score):
        return "missing"
    if score >= 70:
        return "ge70"
    if score >= 60:
        return "60_69"
    return "lt60"


def load_trades_with_fund(closed_path: Path, fund_col: str) -> list[dict[str, Any]]:
    """Load trades and attach fund score from enriched Closed column."""
    trades = load_trades(closed_path)
    if not trades:
        return trades

    fund_by_sym: dict[str, Optional[float]] = {}
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        sym_col = _symbol_col(list(reader.fieldnames or []))
        if not sym_col or fund_col not in (reader.fieldnames or []):
            return trades
        for raw in reader:
            sym = (raw.get(sym_col) or "").strip().upper()
            if not sym:
                continue
            try:
                v = float(raw.get(fund_col) or "")
                fund_by_sym[sym] = v if math.isfinite(v) else None
            except (TypeError, ValueError):
                fund_by_sym[sym] = None

    for t in trades:
        t["fund_score"] = fund_by_sym.get(t["sym"])
        t["bucket"] = _bucket_label(t["fund_score"])
    return trades


def stats_with_cash(trades: list[dict[str, Any]], cash: float) -> dict[str, Any]:
    prev = _rlul.RL_CASH
    try:
        _rlul.RL_CASH = cash
        return book_stats(trades)
    finally:
        _rlul.RL_CASH = prev


def analyze_system(spec: dict[str, Any], enriched_path: Path) -> dict[str, Any]:
    cash = spec["cash"]
    sys_id = spec["id"]
    pack: dict[str, Any] = {
        "id": sys_id,
        "label": spec["label"],
        "closed": str(enriched_path),
        "cash": cash,
        "pillars": {},
    }

    for pillar_id, pillar_label, fund_col in PILLARS:
        trades = load_trades_with_fund(enriched_path, fund_col)
        if not trades:
            pack["pillars"][pillar_id] = {"label": pillar_label, "buckets": {}, "n_trades": 0}
            continue

        by_bucket: dict[str, dict[str, Any]] = {}
        for bid, blabel, _ in BUCKETS:
            if bid == "missing":
                subset = [t for t in trades if t["bucket"] == "missing"]
            else:
                subset = [t for t in trades if t["bucket"] == bid]
            is_t, oos_t = split_is_oos(subset)
            by_bucket[bid] = {
                "label": blabel,
                "full": stats_with_cash(subset, cash),
                "is": stats_with_cash(is_t, cash),
                "oos": stats_with_cash(oos_t, cash),
            }

        # Control = full book for delta reference
        full = stats_with_cash(trades, cash)
        is_all, oos_all = split_is_oos(trades)
        pack["pillars"][pillar_id] = {
            "label": pillar_label,
            "fund_col": fund_col,
            "buckets": by_bucket,
            "control_full": full,
            "control_is": stats_with_cash(is_all, cash),
            "control_oos": stats_with_cash(oos_all, cash),
            "n_trades": len(trades),
        }
    return pack


def quality_spread(pack: dict[str, Any], split: str = "full") -> dict[str, float]:
    """ge70 minus lt60 avg pnl spread on Quality pillar."""
    q = pack.get("pillars", {}).get("quality", {})
    buckets = q.get("buckets", {})
    hi = buckets.get("ge70", {}).get(split, {})
    lo = buckets.get("lt60", {}).get(split, {})
    return {
        "ge70_avg": hi.get("avg_pnl", float("nan")),
        "lt60_avg": lo.get("avg_pnl", float("nan")),
        "spread": hi.get("avg_pnl", float("nan")) - lo.get("avg_pnl", float("nan")),
        "ge70_n": hi.get("n", 0),
        "lt60_n": lo.get("n", 0),
        "ge70_pf": hi.get("pf", float("nan")),
        "lt60_pf": lo.get("pf", float("nan")),
    }


def verdict_bucket(spread: float, ge70_n: int, lt60_n: int) -> str:
    if ge70_n < 20 or lt60_n < 20:
        return "HOLD (thin N)"
    if spread >= 2.0:
        return "LEAN KEEP"
    if spread >= 0.5:
        return "HOLD"
    if spread <= -1.0:
        return "DISMISS"
    return "HOLD"


def build_master_table(system_packs: list[dict[str, Any]]) -> str:
    cols = [
        ("System", "text"),
        ("Pillar", "text"),
        ("Bucket", "text"),
        ("Split", "text"),
        ("N", "num"),
        ("WR %", "num"),
        ("Avg PnL %", "num"),
        ("WO_MAX %", "num"),
        ("PF", "num"),
        ("Ann ROR %", "num"),
        ("Δ N vs ctrl", "num"),
        ("Δ WR vs ctrl", "num"),
        ("Δ Avg vs ctrl", "num"),
        ("Δ WO_MAX vs ctrl", "num"),
        ("Δ PF vs ctrl", "num"),
        ("Δ Ann ROR vs ctrl", "num"),
    ]
    cols = filter_html_compare_columns(cols)
    rows_html: list[str] = []

    for sp in system_packs:
        for pid, pdata in sp["pillars"].items():
            ctrl = {
                "full": pdata.get("control_full", {}),
                "is": pdata.get("control_is", {}),
                "oos": pdata.get("control_oos", {}),
            }
            for split_key, split_label in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
                c = ctrl.get(split_key, {})
                c_ann = c.get("ann_ror", float("nan"))
                rows_html.append(
                    "<tr class=\"control-row\">"
                    f'<td data-sort-value="{esc(sp["id"])}">{esc(sp["label"])}</td>'
                    f'<td data-sort-value="{esc(pdata["label"])}">{esc(pdata["label"])}</td>'
                    f'<td data-sort-value="control">{esc(CONTROL_LABEL)}</td>'
                    f'<td data-sort-value="{esc(split_label)}">{esc(split_label)}</td>'
                    f'<td data-sort-value="{c.get("n", 0)}">{c.get("n", 0)}</td>'
                    f'<td data-sort-value="{c.get("wr", 0)}">{fmt_pct(c.get("wr", 0))}</td>'
                    f'<td data-sort-value="{c.get("avg_pnl", 0)}">{fmt_pct(c.get("avg_pnl", 0))}</td>'
                    f'<td data-sort-value="{c.get("wo_max", 0)}">{fmt_pct(c.get("wo_max", 0))}</td>'
                    f'<td data-sort-value="{c.get("pf", 0)}">{fmt_n(c.get("pf", 0))}</td>'
                    f'<td data-sort-value="{_ann_sort_val(c_ann)}">{fmt_pct(c_ann)}</td>'
                    '<td data-sort-value="0">0</td>'
                    '<td data-sort-value="0">0.00</td>'
                    '<td data-sort-value="0">0.00</td>'
                    '<td data-sort-value="0">0.00</td>'
                    '<td data-sort-value="0">0.00</td>'
                    '<td data-sort-value="0">0.00</td>'
                    "</tr>"
                )
            for bid, bdata in pdata.get("buckets", {}).items():
                for split_key, split_label in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
                    m = bdata.get(split_key, {})
                    c = ctrl.get(split_key, {})
                    m_ann = m.get("ann_ror", float("nan"))
                    d_n = m.get("n", 0) - c.get("n", 0)
                    d_wr = _metric_delta(m.get("wr", float("nan")), c.get("wr", float("nan")))
                    d_avg = _metric_delta(m.get("avg_pnl", float("nan")), c.get("avg_pnl", float("nan")))
                    d_wo = _metric_delta(m.get("wo_max", float("nan")), c.get("wo_max", float("nan")))
                    d_pf = _metric_delta(m.get("pf", float("nan")), c.get("pf", float("nan")))
                    d_ann = _metric_delta(m_ann, c.get("ann_ror", float("nan")))
                    rows_html.append(
                        "<tr>"
                        f'<td data-sort-value="{esc(sp["id"])}">{esc(sp["label"])}</td>'
                        f'<td data-sort-value="{esc(pdata["label"])}">{esc(pdata["label"])}</td>'
                        f'<td data-sort-value="{esc(bid)}">{esc(bdata["label"])}</td>'
                        f'<td data-sort-value="{esc(split_label)}">{esc(split_label)}</td>'
                        f'<td data-sort-value="{m.get("n", 0)}">{m.get("n", 0)}</td>'
                        f'<td data-sort-value="{m.get("wr", 0)}">{fmt_pct(m.get("wr", 0))}</td>'
                        f'<td data-sort-value="{m.get("avg_pnl", 0)}">{fmt_pct(m.get("avg_pnl", 0))}</td>'
                        f'<td data-sort-value="{m.get("wo_max", 0)}">{fmt_pct(m.get("wo_max", 0))}</td>'
                        f'<td data-sort-value="{m.get("pf", 0)}">{fmt_n(m.get("pf", 0))}</td>'
                        f'<td data-sort-value="{_ann_sort_val(m_ann)}">{fmt_pct(m_ann)}</td>'
                        f'<td data-sort-value="{d_n}">{d_n}</td>'
                        f'<td data-sort-value="{d_wr if math.isfinite(d_wr) else ""}">'
                        f'{fmt_delta(d_wr) if math.isfinite(d_wr) else "—"}</td>'
                        f'<td data-sort-value="{d_avg if math.isfinite(d_avg) else ""}">'
                        f'{fmt_delta(d_avg) if math.isfinite(d_avg) else "—"}</td>'
                        f'<td data-sort-value="{d_wo if math.isfinite(d_wo) else ""}">'
                        f'{fmt_delta(d_wo) if math.isfinite(d_wo) else "—"}</td>'
                        f'<td data-sort-value="{d_pf if math.isfinite(d_pf) else ""}">'
                        f'{fmt_delta(d_pf) if math.isfinite(d_pf) else "—"}</td>'
                        f'<td data-sort-value="{d_ann if math.isfinite(d_ann) else ""}">'
                        f'{fmt_delta(d_ann) if math.isfinite(d_ann) else "—"}</td>'
                        "</tr>"
                    )

    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h2>All systems × pillar buckets (vs control)</h2>
<p class="sub">Click column headers to sort. {CONTROL_NOTE}
IS = entry &lt; {IS_CUT}; OOS report-only. No Sheet/Total PnL $.</p>
<table class="sortable">
<thead><tr>{thead}</tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table>
"""


def build_quality_highlight_table(system_packs: list[dict[str, Any]]) -> str:
    cols = [
        ("System", "text"),
        ("Split", "text"),
        ("N ≥70", "num"),
        ("Avg% ≥70", "num"),
        ("PF ≥70", "num"),
        ("N &lt;60", "num"),
        ("Avg% &lt;60", "num"),
        ("PF &lt;60", "num"),
        ("Spread Avg%", "num"),
        ("Verdict", "text"),
    ]
    rows = []
    for sp in system_packs:
        for split_key, split_label in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
            s = quality_spread(sp, split_key)
            v = verdict_bucket(s["spread"], int(s["ge70_n"]), int(s["lt60_n"]))
            rows.append(
                "<tr>"
                f'<td data-sort-value="{esc(sp["id"])}">{esc(sp["label"])}</td>'
                f'<td data-sort-value="{esc(split_label)}">{esc(split_label)}</td>'
                f'<td data-sort-value="{s["ge70_n"]}">{int(s["ge70_n"])}</td>'
                f'<td data-sort-value="{s["ge70_avg"]}">{fmt_pct(s["ge70_avg"])}</td>'
                f'<td data-sort-value="{s["ge70_pf"]}">{fmt_n(s["ge70_pf"])}</td>'
                f'<td data-sort-value="{s["lt60_n"]}">{int(s["lt60_n"])}</td>'
                f'<td data-sort-value="{s["lt60_avg"]}">{fmt_pct(s["lt60_avg"])}</td>'
                f'<td data-sort-value="{s["lt60_pf"]}">{fmt_n(s["lt60_pf"])}</td>'
                f'<td data-sort-value="{s["spread"]}">{fmt_n(s["spread"])}</td>'
                f'<td data-sort-value="{esc(v)}">{esc(v)}</td>'
                "</tr>"
            )
    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h2>Quality pillar — ≥70 vs &lt;60 spread</h2>
<p class="sub">Highlights RL / VZ prior LEAN KEEP on Quality gates. Contaminated overlay.</p>
<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table>
"""


def build_system_detail(sp: dict[str, Any]) -> str:
    parts = [
        f'<h2 id="{esc(sp["id"])}">{esc(sp["label"])}</h2>',
        f'<p class="sub">Closed: <code>{esc(sp["closed"])}</code></p>',
        f'<p class="sub">{CONTROL_NOTE}</p>',
    ]
    cols = _vs_control_table_cols()
    thead = "".join(sortable_th(a, b) for a, b in cols)
    for pid, pdata in sp["pillars"].items():
        ctrl = {
            "full": pdata.get("control_full", {}),
            "is": pdata.get("control_is", {}),
            "oos": pdata.get("control_oos", {}),
        }
        parts.append(f'<h3>{esc(pdata["label"])} ({esc(pdata.get("fund_col", ""))})</h3>')
        for split_key, split_label in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
            c = ctrl.get(split_key, {})
            rows = [
                _bucket_vs_control_row(
                    CONTROL_LABEL, "control", c, c, is_control=True, row_class="control-row"
                )
            ]
            for bid, blabel, _ in BUCKETS:
                bdata = pdata.get("buckets", {}).get(bid, {})
                m = bdata.get(split_key, {})
                rows.append(_bucket_vs_control_row(bdata.get("label", blabel), bid, m, c))
            parts.append(
                f'<h4>{esc(split_label)}</h4>'
                f'<p class="sub">Click column headers to sort. Control row = full book baseline.</p>'
                f'<table class="sortable"><thead><tr>{thead}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>'
            )
    return "\n".join(parts)


def build_gates_recap_table() -> str:
    if not PILLAR_AB_METRICS.is_file():
        return "<p>Gates recap unavailable — metrics_all.csv not found.</p>"
    df = pd.read_csv(PILLAR_AB_METRICS)
    df = df[df["split"].isin(["IS", "OOS"]) & df["arm"].ne("control")]
    cols = [
        ("System", "text"),
        ("Arm", "text"),
        ("Split", "text"),
        ("N", "num"),
        ("Avg PnL %", "num"),
        ("WO_MAX %", "num"),
        ("PF", "num"),
        ("WR %", "num"),
        ("Verdict", "text"),
    ]
    rows = []
    for _, r in df.iterrows():
        verdict_col = "verdict_is" if r["split"] == "IS" else "verdict_oos"
        rows.append(
            "<tr>"
            f'<td data-sort-value="{esc(r["system"])}">{esc(r["system"])}</td>'
            f'<td data-sort-value="{esc(r["arm"])}">{esc(r["arm"])}</td>'
            f'<td data-sort-value="{esc(r["split"])}">{esc(r["split"])}</td>'
            f'<td data-sort-value="{r["n"]}">{int(r["n"])}</td>'
            f'<td data-sort-value="{r["avg_pnl"]}">{fmt_pct(float(r["avg_pnl"]))}</td>'
            f'<td data-sort-value="{r["wo_max"]}">{fmt_pct(float(r["wo_max"]))}</td>'
            f'<td data-sort-value="{r["pf"]}">{fmt_n(float(r["pf"]))}</td>'
            f'<td data-sort-value="{r["wr"]}">{fmt_pct(float(r["wr"]))}</td>'
            f'<td data-sort-value="{esc(r[verdict_col])}">{esc(r[verdict_col])}</td>'
            "</tr>"
        )
    thead = "".join(sortable_th(a, b) for a, b in cols)
    return f"""
<h2>Pillar gate AB recap (RL / RS / VZ)</h2>
<p class="sub">Mirrors <code>fund_score_gate_pillars_rl_rs_vz_20260831</code> for consistency.</p>
<table class="sortable"><thead><tr>{thead}</tr></thead><tbody>{"".join(rows)}</tbody></table>
"""


def write_compare_html(system_packs: list[dict[str, Any]]) -> Path:
    body = [
        build_quality_highlight_table(system_packs),
        build_master_table(system_packs),
        build_gates_recap_table(),
    ]
    for sp in system_packs:
        body.append(build_system_detail(sp))

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<title>Fund scores × Closed systems — {STAMP}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; max-width: 1400px; }}
h1,h2,h3 {{ color: #1e293b; }}
.sub {{ color: #64748b; font-size: 0.92rem; }}
code {{ background: #f1f5f9; padding: 0.1rem 0.35rem; border-radius: 4px; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.88rem; }}
th, td {{ border: 1px solid #e2e8f0; padding: 0.35rem 0.5rem; text-align: right; }}
th {{ background: #f8fafc; }}
td:first-child, th:first-child {{ text-align: left; }}
tr.control-row {{ background: #f0f9ff; font-weight: 600; }}
h4 {{ color: #334155; margin: 0.75rem 0 0.25rem; font-size: 1rem; }}
{SORTABLE_TH_CSS}
</style>
</head><body>
<h1>Fund scorecard × house Closed books</h1>
<p class="sub"><strong>Research only.</strong> Snapshot scores ({SCORES_DEFAULT.name}) joined to
historical Closed trades — <strong>look-ahead / contaminated overlay</strong>.
IS = entry &lt; {IS_CUT}; OOS report-only; no OOS retune. Not gold. Not DailyRun.</p>
<p class="sub"><strong>Control baseline:</strong> {CONTROL_NOTE}</p>
{"".join(body)}
{SORTABLE_TABLE_SCRIPT}
</body></html>"""
    path = OUT / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def bucket_vs_control_summary(sp: dict[str, Any], pillar_id: str, bucket_id: str, split: str) -> dict[str, Any]:
    """Return bucket metrics + deltas vs full-book control for one system/pillar/bucket/split."""
    pdata = sp.get("pillars", {}).get(pillar_id, {})
    m = pdata.get("buckets", {}).get(bucket_id, {}).get(split, {})
    c = pdata.get(f"control_{split}", {})
    return {
        "n": m.get("n", 0),
        "wr": m.get("wr", 0),
        "avg_pnl": m.get("avg_pnl", 0),
        "wo_max": m.get("wo_max", 0),
        "pf": m.get("pf", 0),
        "ann_ror": m.get("ann_ror", float("nan")),
        "ctrl_n": c.get("n", 0),
        "ctrl_wr": c.get("wr", 0),
        "ctrl_avg_pnl": c.get("avg_pnl", 0),
        "ctrl_wo_max": c.get("wo_max", 0),
        "ctrl_pf": c.get("pf", 0),
        "ctrl_ann_ror": c.get("ann_ror", float("nan")),
        "d_n": m.get("n", 0) - c.get("n", 0),
        "d_wr": _metric_delta(m.get("wr", float("nan")), c.get("wr", float("nan"))),
        "d_avg_pnl": _metric_delta(m.get("avg_pnl", float("nan")), c.get("avg_pnl", float("nan"))),
        "d_wo_max": _metric_delta(m.get("wo_max", float("nan")), c.get("wo_max", float("nan"))),
        "d_pf": _metric_delta(m.get("pf", float("nan")), c.get("pf", float("nan"))),
        "d_ann_ror": _metric_delta(m.get("ann_ror", float("nan")), c.get("ann_ror", float("nan"))),
    }


def write_summary_md(system_packs: list[dict[str, Any]], enrich_results: list[dict[str, Any]]) -> None:
    lines = [
        f"# SUMMARY — `{STAMP}`",
        "",
        "**Research only.** Snapshot fund scores on historical Closed entries (look-ahead).",
        "**Not gold. Not DailyRun.**",
        "",
        "## Control baseline",
        "",
        CONTROL_NOTE,
        "",
        "Each bucket row in `compare.html` shows **Δ vs control** on N, WR%, Avg PnL%, WO_MAX%, PF, Ann ROR%.",
        "Per-system sections use FULL / IS / OOS panels with a highlighted control row.",
        "",
        "## Enrichment",
        "",
        f"Score source: `{SCORES_DEFAULT}`",
        "",
        "| System | Enriched path | Rows | Matched | Cols added |",
        "|--------|---------------|------|---------|------------|",
    ]
    seen: set[str] = set()
    for r in enrich_results:
        if r.get("kind") != "latest_in_place" or not r.get("ok"):
            continue
        key = r.get("system", "")
        if key in seen:
            continue
        seen.add(key)
        cols = ", ".join(r.get("cols_added") or [])
        lines.append(
            f"| {key} | `{r.get('path', '')}` | {r.get('rows', 0)} | "
            f"{r.get('matched', 0)} | {cols} |"
        )

    lines.extend(["", "## Quality headline (≥70 vs &lt;60 Avg PnL% spread)", ""])
    for sp in system_packs:
        for split_key, split_label in (("full", "FULL"), ("is", "IS"), ("oos", "OOS")):
            s = quality_spread(sp, split_key)
            v = verdict_bucket(s["spread"], int(s["ge70_n"]), int(s["lt60_n"]))
            lines.append(
                f"- **{sp['id']}** {split_label}: spread {fmt_n(s['spread'])} "
                f"(≥70 n={int(s['ge70_n'])} avg={fmt_pct(s['ge70_avg'])} vs "
                f"&lt;60 n={int(s['lt60_n'])} avg={fmt_pct(s['lt60_avg'])}) → **{v}**"
            )

    lines.extend(
        [
            "",
            "## Example: RL Quality ≥70 vs control (FULL)",
            "",
        ]
    )
    rl = next((sp for sp in system_packs if sp["id"] == "RL"), None)
    if rl:
        ex = bucket_vs_control_summary(rl, "quality", "ge70", "full")
        lines.append(
            f"- Control: n={ex['ctrl_n']}, WR {fmt_pct(ex['ctrl_wr'])}%, "
            f"Avg {fmt_pct(ex['ctrl_avg_pnl'])}%, PF {fmt_n(ex['ctrl_pf'])}, "
            f"AnnROR {fmt_pct(ex['ctrl_ann_ror'])}%"
        )
        lines.append(
            f"- Quality ≥70: n={ex['n']}, WR {fmt_pct(ex['wr'])}%, "
            f"Avg {fmt_pct(ex['avg_pnl'])}%, PF {fmt_n(ex['pf'])}, "
            f"AnnROR {fmt_pct(ex['ann_ror'])}%"
        )
        lines.append(
            f"- Δ vs control: N {ex['d_n']:+d}, WR {fmt_delta(ex['d_wr'])} pp, "
            f"Avg {fmt_delta(ex['d_avg_pnl'])} pp, PF {fmt_delta(ex['d_pf'])}, "
            f"AnnROR {fmt_delta(ex['d_ann_ror'])} pp"
        )

    lines.extend(["", "## System / pillar verdicts (descriptive buckets)", ""])
    for sp in system_packs:
        lines.append(f"### {sp['label']}")
        for pid, pdata in sp["pillars"].items():
            b = pdata.get("buckets", {})
            ge70 = b.get("ge70", {}).get("full", {})
            lt60 = b.get("lt60", {}).get("full", {})
            spread = ge70.get("avg_pnl", 0) - lt60.get("avg_pnl", 0)
            lines.append(
                f"- **{pdata['label']}**: ≥70 avg {fmt_pct(ge70.get('avg_pnl', 0))} "
                f"(n={ge70.get('n', 0)}, PF {fmt_n(ge70.get('pf', 0))}) vs "
                f"&lt;60 avg {fmt_pct(lt60.get('avg_pnl', 0))} "
                f"(n={lt60.get('n', 0)}) spread {fmt_n(spread)}"
            )
        lines.append("")

    lines.extend(
        [
            "## RL / VZ Quality (prior pillar AB)",
            "",
            "Prior `fund_score_gate_pillars_rl_rs_vz_20260831`: RL **LEAN KEEP** on Quality ≥60/≥70;",
            "VZ **LEAN KEEP** on Quality ≥60/≥70. Bucket report above should show Quality ≥70",
            "outperforming &lt;60 on those books if contaminated signal holds.",
            "",
            "See `compare.html` gates recap table and per-system detail sections.",
            "Per-system detail tables include FULL / IS / OOS panels with control row + Δ vs control.",
        ]
    )
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def scores_path_rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def write_baseline_md(enrich_results: list[dict[str, Any]]) -> None:
    enriched_paths = [
        r for r in enrich_results if r.get("ok") and r.get("kind") in ("latest_in_place", "parallel_fundscores")
    ]
    if not enriched_paths:
        for spec in closed_targets():
            p = spec["closed"]
            rel = p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else str(p)
            enriched_paths.append(
                {"system": spec["id"], "kind": "latest_in_place", "path": rel}
            )
            par = p.parent / f"{p.stem}_fundscores.csv"
            enriched_paths.append(
                {"system": spec["id"], "kind": "parallel_fundscores", "path": par.relative_to(ROOT).as_posix()}
            )
    scores_rel = scores_path_rel(SCORES_DEFAULT)
    backup_rel = f"drive/paul_experiments/{STAMP}/backups"

    text = f"""# BASELINE — `{STAMP}`

**Status:** RESEARCH only. **Not gold. Not DailyRun-wired.**

## Hypothesis

Do house fund scorecard pillars (Quality, Valuation, Growth Stability, Composite)
segment trade quality differently across house Closed books?

Descriptive bucket analysis on enriched Closed files — complements prior
`fund_score_gate_pillars_rl_rs_vz_20260831` gate AB (RL/RS/VZ).

## Look-ahead honesty (critical)

- Score source: `{scores_rel}` — **current snapshot**, not point-in-time at entry.
- Joining today's pillars to historical Closed trades = **contaminated overlay**.
- Threshold buckets ≥70 / 60–69 / &lt;60 chosen a priori; not retuned on OOS.
- IS = `entry_date < {IS_CUT}`; OOS report-only.

## Enrichment approach

Post-process join by SYMBOL (approach A). Originals backed up under `{backup_rel}`.
LatestRun files updated in-place with `fund_*` columns appended.
Parallel `*_Closed_fundscores.csv` copies kept beside originals for reconcile safety.

### Columns added

{", ".join(FUND_JOIN.keys())}

### Files touched

"""
    for r in enriched_paths:
        p = r.get("path", "")
        try:
            p = Path(p).relative_to(ROOT).as_posix()
        except (ValueError, TypeError):
            pass
        text += f"- **{r.get('system', '?')}** ({r.get('kind', '')}): `{p}`\n"

    text += f"""
## Control baseline

{CONTROL_NOTE}

Bucket rows in `compare.html` show Δ vs control on N, WR%, Avg PnL%, WO_MAX%, PF, Ann ROR%.
Ann ROR uses Closed-overlay book formula via `book_stats` → `overlay_ann_ror_max_dd` / `ann_ror_from_closed` (stamp cash model).
Per-system sections use FULL / IS / OOS panels with a highlighted control row.

## IS / OOS split

- IS: entry &lt; {IS_CUT}
- OOS: entry ≥ {IS_CUT} (report-only; no retune)

## Related stamps

- Scorecard: `fund_scorecard_v1_industry_20260831`
- Pillar gates: `fund_score_gate_pillars_rl_rs_vz_20260831`
"""
    (OUT / "BASELINE.md").write_text(text, encoding="utf-8")


def ntfy(html_path: Path, *, title: str = "Fund scores report vs control deltas") -> None:
    script = ROOT / "tools" / "ntfy_job_done.py"
    if script.is_file():
        subprocess.run(
            [sys.executable, str(script), "--path", str(html_path), "-t", title],
            cwd=str(ROOT),
            check=False,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", type=Path, default=SCORES_DEFAULT)
    ap.add_argument("--enrich-only", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--no-in-place", action="store_true", help="Skip mutating LatestRun Closed files")
    args = ap.parse_args()

    if not args.scores.is_file():
        print(f"Missing scores: {args.scores}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    enrich_results: list[dict[str, Any]] = []

    if not args.report_only:
        enrich_results = enrich_all(args.scores, in_place_latest=not args.no_in_place)
        ok = [r for r in enrich_results if r.get("ok")]
        print(f"Enriched {len(ok)} file writes from {len(closed_targets())} systems")

    enriched_dir = OUT / "enriched"
    system_packs: list[dict[str, Any]] = []
    if not args.enrich_only:
        for spec in closed_targets():
            sys_id = spec["id"]
            enriched = enriched_dir / spec["closed"].name
            if not enriched.is_file():
                enriched = spec["closed"]
            if not enriched.is_file():
                print(f"Skip report — missing enriched closed for {sys_id}", file=sys.stderr)
                continue
            system_packs.append(analyze_system(spec, enriched))

        html_path = write_compare_html(system_packs)
        write_summary_md(system_packs, enrich_results)
        write_baseline_md(enrich_results)

        # metrics csv for stamp (buckets + control + deltas)
        rows = []
        for sp in system_packs:
            for pid, pdata in sp["pillars"].items():
                for split_key in ("full", "is", "oos"):
                    c = pdata.get(f"control_{split_key}", {})
                    rows.append(
                        {
                            "system": sp["id"],
                            "pillar": pid,
                            "bucket": "control",
                            "split": split_key.upper(),
                            "n": c.get("n", 0),
                            "wr": c.get("wr", 0),
                            "avg_pnl": c.get("avg_pnl", 0),
                            "wo_max": c.get("wo_max", 0),
                            "pf": c.get("pf", 0),
                            "ann_ror": c.get("ann_ror", float("nan")),
                            "d_n": 0,
                            "d_wr": 0.0,
                            "d_avg_pnl": 0.0,
                            "d_wo_max": 0.0,
                            "d_pf": 0.0,
                            "d_ann_ror": 0.0,
                        }
                    )
                for bid, bdata in pdata.get("buckets", {}).items():
                    for split_key in ("full", "is", "oos"):
                        m = bdata.get(split_key, {})
                        c = pdata.get(f"control_{split_key}", {})
                        rows.append(
                            {
                                "system": sp["id"],
                                "pillar": pid,
                                "bucket": bid,
                                "split": split_key.upper(),
                                "n": m.get("n", 0),
                                "wr": m.get("wr", 0),
                                "avg_pnl": m.get("avg_pnl", 0),
                                "wo_max": m.get("wo_max", 0),
                                "pf": m.get("pf", 0),
                                "ann_ror": m.get("ann_ror", float("nan")),
                                "d_n": m.get("n", 0) - c.get("n", 0),
                                "d_wr": _metric_delta(
                                    m.get("wr", float("nan")), c.get("wr", float("nan"))
                                ),
                                "d_avg_pnl": _metric_delta(
                                    m.get("avg_pnl", float("nan")), c.get("avg_pnl", float("nan"))
                                ),
                                "d_wo_max": _metric_delta(
                                    m.get("wo_max", float("nan")), c.get("wo_max", float("nan"))
                                ),
                                "d_pf": _metric_delta(
                                    m.get("pf", float("nan")), c.get("pf", float("nan"))
                                ),
                                "d_ann_ror": _metric_delta(
                                    m.get("ann_ror", float("nan")), c.get("ann_ror", float("nan"))
                                ),
                            }
                        )
        pd.DataFrame(rows).to_csv(OUT / "bucket_metrics_all.csv", index=False)

        print(f"Wrote {html_path}")
        ntfy(html_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
