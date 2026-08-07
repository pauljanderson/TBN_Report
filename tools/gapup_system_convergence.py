#!/usr/bin/env python3
"""
Gap-up (>2%) × system Closed convergence — entry-aligned value over time.

Overlap definitions (documented in HTML)
----------------------------------------
Same SYMBOL, and gap date relates to the trade:

  A) GAP_DATE == DATE_OPENED          (same-day entry as the gap)
  B) GAP_DATE == prior trading day of DATE_OPENED
     (signal / day-before fill when entry is next_open)

  Entry-aligned (primary): A or B. Each Closed trade counted at most once
  (prefer A over B if both; if multiple gaps, keep largest GAP_PCT).

  Hold overlap (optional / separate): any GAP_DATE with GAP_PCT > threshold
  strictly inside (DATE_OPENED, DATE_CLOSED] — gap while already in the trade
  (excludes entry day so A is not double-counted as hold-only).

Value metrics
-------------
Per system: gap entry-aligned subset vs all other Closed (baseline = non-gap).
n, win rate, avg PnL%, Total_PNL (host capacity), Ann_ROR when feasible.
Lift = gap subset − baseline for WR / avg% / Ann.
Time stability: by calendar year and H1/H2 of DATE_OPENED.

Writes:
  drive/paul_experiments/GapUp_System_Convergence.html
  drive/paul_experiments/GapUp_System_Convergence.csv
  drive/paul_experiments/GapUp_System_Convergence_detail.csv
  drive/paul_experiments/GapUp_System_Convergence_stability.csv

Usage:
  python tools/gapup_system_convergence.py
  python tools/gapup_system_convergence.py --min-gap-pct 2.0
  python tools/gapup_system_convergence.py --gap-csv drive/GapUp_Scan_….csv
"""
from __future__ import annotations

import argparse
import html as html_mod
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stock_analysis"))

from gapup_market_correlation import find_latest_gap_csv  # noqa: E402
from sb_system_convergence import (  # noqa: E402
    DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_MARGIN_UTILIZATION,
    PREFERRED_PEERS,
    SKIP_IF_WPBR,
    SYSTEM_LABELS,
    SecondSignalTrade,
    SourceFile,
    Trade,
    _SORTABLE_TABLE_SCRIPT,
    _resolve_drive,
    _sortable_th,
    aggregate_second_signal,
    discover_latest_closed,
    load_closed_map,
    load_trades,
)

DRIVE = ROOT / "drive"
OUT_DIR = DRIVE / "paul_experiments"
DEFAULT_SPY = ROOT / "data" / "newdata" / "data" / "SPY.csv"
THIN_N = 30  # honest thin-sample flag

SYSTEM_ORDER = ("SB",) + PREFERRED_PEERS

SORTABLE_TH_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""


@dataclass
class GapEvent:
    symbol: str
    gap_date: date
    gap_pct: float


@dataclass
class MatchRow:
    system: str
    symbol: str
    side: str
    date_opened: date
    date_closed: date
    pnl_pct: Optional[float]
    entry_price: Optional[float]
    exit_price: Optional[float]
    gap_date: date
    gap_pct: float
    align: str  # A | B | HOLD
    trade_ix: int


def trade_to_ss(t: Trade, peer: str = "GAP") -> Optional[SecondSignalTrade]:
    ep = t.entry_price
    xp = t.exit_price
    if ep is None or ep <= 0:
        return None
    side = (t.side or "LONG").upper()
    if t.pnl_pct is not None:
        pnl_pct = float(t.pnl_pct)
    elif xp is not None and xp > 0:
        if side.startswith("S"):
            pnl_pct = (ep - xp) / ep * 100.0
        else:
            pnl_pct = (xp - ep) / ep * 100.0
    else:
        return None
    if xp is None or xp <= 0:
        if side.startswith("S"):
            xp = ep * (1.0 - pnl_pct / 100.0)
        else:
            xp = ep * (1.0 + pnl_pct / 100.0)
        if xp <= 0:
            return None
    days = (t.exit_date - t.entry_date).days
    if days < 0:
        return None
    return SecondSignalTrade(
        symbol=t.symbol,
        peer=peer,
        side=side,
        entry_date=t.entry_date,
        entry_price=float(ep),
        entry_system=t.system,
        exit_date=t.exit_date,
        exit_price=float(xp),
        exit_system=t.system,
        days_held=max(days, 1),
        pnl_pct=pnl_pct,
        sb_buy_date=t.entry_date,
        peer_buy_date=t.entry_date,
        same_day_entry=True,
    )


def load_trading_days(spy_path: Path) -> list[date]:
    if not spy_path.is_file():
        return []
    spy = pd.read_csv(spy_path, usecols=lambda c: c.lower() in {"date", "datetime"})
    col = spy.columns[0]
    dts = pd.to_datetime(spy[col], errors="coerce").dropna().dt.date
    return sorted(set(dts.tolist()))


def build_prev_trading_day(trading_days: list[date]) -> dict[date, date]:
    """Map each trading day -> prior trading day."""
    prev: dict[date, date] = {}
    for i in range(1, len(trading_days)):
        prev[trading_days[i]] = trading_days[i - 1]
    return prev


def load_gaps(
    gap_csv: Path,
    min_gap_pct: float,
) -> list[GapEvent]:
    """Load gaps with GAP_PCT > min_gap_pct (strict)."""
    usecols = ["SYMBOL", "GAP_DATE", "GAP_PCT"]
    events: list[GapEvent] = []
    for chunk in pd.read_csv(gap_csv, usecols=usecols, chunksize=250_000):
        chunk["GAP_PCT"] = pd.to_numeric(chunk["GAP_PCT"], errors="coerce")
        chunk = chunk[chunk["GAP_PCT"] > min_gap_pct]
        if chunk.empty:
            continue
        chunk["SYMBOL"] = chunk["SYMBOL"].astype(str).str.strip().str.upper()
        chunk["GAP_DATE"] = pd.to_datetime(chunk["GAP_DATE"], errors="coerce")
        chunk = chunk.dropna(subset=["SYMBOL", "GAP_DATE", "GAP_PCT"])
        for row in chunk.itertuples(index=False):
            sym = str(row.SYMBOL)
            if not sym or sym in {"NAN", "NONE", "SYMBOL"}:
                continue
            gd = row.GAP_DATE.date() if hasattr(row.GAP_DATE, "date") else row.GAP_DATE
            events.append(GapEvent(symbol=sym, gap_date=gd, gap_pct=float(row.GAP_PCT)))
    return events


def index_gaps(events: list[GapEvent]) -> dict[str, dict[date, float]]:
    """symbol -> {gap_date -> max GAP_PCT that day}."""
    out: dict[str, dict[date, float]] = {}
    for e in events:
        by_d = out.setdefault(e.symbol, {})
        prev = by_d.get(e.gap_date)
        if prev is None or e.gap_pct > prev:
            by_d[e.gap_date] = e.gap_pct
    return out


def match_entry_aligned(
    trades: list[Trade],
    gaps_by_sym: dict[str, dict[date, float]],
    prev_td: dict[date, date],
) -> list[MatchRow]:
    """One row per trade with A or B match (prefer A)."""
    rows: list[MatchRow] = []
    for t in trades:
        by_d = gaps_by_sym.get(t.symbol)
        if not by_d:
            continue
        align = ""
        gap_date: Optional[date] = None
        gap_pct = 0.0
        if t.entry_date in by_d:
            align = "A"
            gap_date = t.entry_date
            gap_pct = by_d[t.entry_date]
        else:
            prior = prev_td.get(t.entry_date)
            if prior is not None and prior in by_d:
                align = "B"
                gap_date = prior
                gap_pct = by_d[prior]
        if not align or gap_date is None:
            continue
        rows.append(
            MatchRow(
                system=t.system,
                symbol=t.symbol,
                side=t.side,
                date_opened=t.entry_date,
                date_closed=t.exit_date,
                pnl_pct=t.pnl_pct,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                gap_date=gap_date,
                gap_pct=gap_pct,
                align=align,
                trade_ix=t.row_ix,
            )
        )
    return rows


def match_hold_overlap(
    trades: list[Trade],
    gaps_by_sym: dict[str, dict[date, float]],
    entry_aligned_ix: set[int],
) -> list[MatchRow]:
    """
    Trades with a >threshold gap while open, excluding trades already
    entry-aligned (so HOLD bucket is complementary). Largest gap in open window.
    Window: (DATE_OPENED, DATE_CLOSED] — after entry through close.
    """
    rows: list[MatchRow] = []
    for t in trades:
        if t.row_ix in entry_aligned_ix:
            continue
        by_d = gaps_by_sym.get(t.symbol)
        if not by_d:
            continue
        best_d: Optional[date] = None
        best_pct = -1.0
        for gd, gp in by_d.items():
            if t.entry_date < gd <= t.exit_date and gp > best_pct:
                best_pct = gp
                best_d = gd
        if best_d is None:
            continue
        rows.append(
            MatchRow(
                system=t.system,
                symbol=t.symbol,
                side=t.side,
                date_opened=t.entry_date,
                date_closed=t.exit_date,
                pnl_pct=t.pnl_pct,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                gap_date=best_d,
                gap_pct=best_pct,
                align="HOLD",
                trade_ix=t.row_ix,
            )
        )
    return rows


def match_ix_set(matches: list[MatchRow]) -> set[int]:
    return {m.trade_ix for m in matches}


def metrics_for_trades(
    trades: list[Trade],
    bucket: str,
) -> dict:
    ss = [x for t in trades if (x := trade_to_ss(t, peer=bucket)) is not None]
    return aggregate_second_signal(ss, bucket=bucket)


def half_label(d: date) -> str:
    return f"{d.year}-H{'1' if d.month <= 6 else '2'}"


def select_systems(discovered: dict[str, SourceFile]) -> list[str]:
    systems = [s for s in SYSTEM_ORDER if s in discovered]
    if "WPBR" in discovered:
        systems = [s for s in systems if s not in SKIP_IF_WPBR]
    extras = sorted(
        s
        for s in discovered
        if s not in systems and s not in SKIP_IF_WPBR and s != "DB"
    )
    # Keep preferred-only for main report; drop incidental empty books
    out = []
    for s in systems:
        out.append(s)
    return out


def lift_verdict(row: dict) -> str:
    """Honest verdict: require meaningful avg% lift, not just rounding noise."""
    n = int(row.get("gap_n") or 0)
    if n < THIN_N:
        return "thin / inconclusive"
    wr_raw = row.get("wr_lift_pp")
    avg_raw = row.get("avg_pnl_lift_pp")
    if wr_raw is None or avg_raw is None or (isinstance(wr_raw, float) and np.isnan(wr_raw)):
        return "thin / inconclusive"
    wr_lift = float(wr_raw)
    avg_lift = float(avg_raw)
    # Positive: both WR and avg% improve, with avg% lift at least +0.5 pp
    if wr_lift > 0 and avg_lift >= 0.5:
        return "positive lift"
    # Mild: solid avg% with WR not much worse
    if avg_lift >= 1.0 and wr_lift >= -2.0:
        return "mixed / mild positive"
    if wr_lift < 0 and avg_lift < 0:
        return "no edge (negative)"
    # e.g. WR up but avg% flat/down, or tiny avg% noise
    return "no clear edge"


def stability_rows(
    system: str,
    gap_trades: list[Trade],
    baseline_trades: list[Trade],
    by: str,
) -> list[dict]:
    """by = 'year' | 'half'."""
    def key_fn(t: Trade) -> str:
        if by == "year":
            return str(t.entry_date.year)
        return half_label(t.entry_date)

    gap_by: dict[str, list[Trade]] = {}
    base_by: dict[str, list[Trade]] = {}
    for t in gap_trades:
        gap_by.setdefault(key_fn(t), []).append(t)
    for t in baseline_trades:
        base_by.setdefault(key_fn(t), []).append(t)
    keys = sorted(set(gap_by) | set(base_by))
    out = []
    for k in keys:
        g = gap_by.get(k, [])
        b = base_by.get(k, [])
        gm = metrics_for_trades(g, f"{system}_gap_{k}")
        bm = metrics_for_trades(b, f"{system}_base_{k}")
        out.append(
            {
                "system": system,
                "period_type": by,
                "period": k,
                "gap_n": gm["total_trades"],
                "gap_wr_pct": gm["win_rate_pct"],
                "gap_avg_pnl_pct": gm["avg_profit_pct"],
                "gap_Ann_ROR": gm["Ann_ROR"],
                "gap_Total_PNL": gm["Total_PNL"],
                "base_n": bm["total_trades"],
                "base_wr_pct": bm["win_rate_pct"],
                "base_avg_pnl_pct": bm["avg_profit_pct"],
                "wr_lift_pp": round(gm["win_rate_pct"] - bm["win_rate_pct"], 2)
                if g and b
                else None,
                "avg_pnl_lift_pp": round(gm["avg_profit_pct"] - bm["avg_profit_pct"], 2)
                if g and b
                else None,
                "thin": gm["total_trades"] < THIN_N,
            }
        )
    return out


def _fmt_num(v, digits=2, signed=False) -> str:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if signed:
        return f"{float(v):+.{digits}f}"
    return f"{float(v):,.{digits}f}"


def _fmt_pct_pp(v) -> str:
    if v is None:
        return "—"
    return f"{float(v):+.2f} pp"


def build_html(
    *,
    gap_csv: Path,
    min_gap_pct: float,
    n_gaps: int,
    sources: dict[str, SourceFile],
    systems: list[str],
    verdict_rows: list[dict],
    hold_rows: list[dict],
    stability: list[dict],
    detail_n: int,
    capital_note: str,
) -> str:
    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    v_head = "".join(
        _sortable_th(lab, typ)
        for lab, typ in [
            ("System", "text"),
            ("Verdict", "text"),
            ("Gap n", "num"),
            ("Base n", "num"),
            ("Gap WR%", "num"),
            ("Base WR%", "num"),
            ("WR lift", "num"),
            ("Gap avg PnL%", "num"),
            ("Base avg PnL%", "num"),
            ("Avg% lift", "num"),
            ("Gap Ann_ROR%", "num"),
            ("Base Ann_ROR%", "num"),
            ("Gap Total_PNL", "num"),
            ("Base Total_PNL", "num"),
            ("A (same day)", "num"),
            ("B (prior TD)", "num"),
            ("Thin?", "text"),
        ]
    )
    v_body = []
    for r in verdict_rows:
        thin = "yes" if r["thin"] else "no"
        cls = ""
        if r["verdict"].startswith("positive"):
            cls = "pos"
        elif "negative" in r["verdict"]:
            cls = "neg"
        v_body.append(
            "<tr>"
            f"<td>{html_mod.escape(SYSTEM_LABELS.get(r['system'], r['system']))}</td>"
            f"<td class=\"{cls}\">{html_mod.escape(r['verdict'])}</td>"
            f"<td>{r['gap_n']}</td>"
            f"<td>{r['base_n']}</td>"
            f"<td>{_fmt_num(r['gap_wr_pct'])}</td>"
            f"<td>{_fmt_num(r['base_wr_pct'])}</td>"
            f"<td class=\"{_pnl_cls(r['wr_lift_pp'])}\">{_fmt_pct_pp(r['wr_lift_pp'])}</td>"
            f"<td>{_fmt_num(r['gap_avg_pnl_pct'], signed=True)}</td>"
            f"<td>{_fmt_num(r['base_avg_pnl_pct'], signed=True)}</td>"
            f"<td class=\"{_pnl_cls(r['avg_pnl_lift_pp'])}\">{_fmt_pct_pp(r['avg_pnl_lift_pp'])}</td>"
            f"<td>{_fmt_num(r['gap_Ann_ROR'], signed=True)}</td>"
            f"<td>{_fmt_num(r['base_Ann_ROR'], signed=True)}</td>"
            f"<td>{_fmt_num(r['gap_Total_PNL'], signed=True)}</td>"
            f"<td>{_fmt_num(r['base_Total_PNL'], signed=True)}</td>"
            f"<td>{r['n_A']}</td>"
            f"<td>{r['n_B']}</td>"
            f"<td>{thin}</td>"
            "</tr>"
        )

    h_head = "".join(
        _sortable_th(lab, typ)
        for lab, typ in [
            ("System", "text"),
            ("Hold-gap n", "num"),
            ("Hold WR%", "num"),
            ("Hold avg PnL%", "num"),
            ("Base n (non entry-aligned)", "num"),
            ("Base WR%", "num"),
            ("WR lift", "num"),
            ("Avg% lift", "num"),
            ("Note", "text"),
        ]
    )
    h_body = []
    for r in hold_rows:
        note = "thin" if r["thin"] else ""
        h_body.append(
            "<tr>"
            f"<td>{html_mod.escape(SYSTEM_LABELS.get(r['system'], r['system']))}</td>"
            f"<td>{r['hold_n']}</td>"
            f"<td>{_fmt_num(r['hold_wr_pct'])}</td>"
            f"<td>{_fmt_num(r['hold_avg_pnl_pct'], signed=True)}</td>"
            f"<td>{r['base_n']}</td>"
            f"<td>{_fmt_num(r['base_wr_pct'])}</td>"
            f"<td class=\"{_pnl_cls(r['wr_lift_pp'])}\">{_fmt_pct_pp(r['wr_lift_pp'])}</td>"
            f"<td class=\"{_pnl_cls(r['avg_pnl_lift_pp'])}\">{_fmt_pct_pp(r['avg_pnl_lift_pp'])}</td>"
            f"<td>{note}</td>"
            "</tr>"
        )

    # Stability: show year rows primarily
    stab_year = [s for s in stability if s["period_type"] == "year"]
    s_head = "".join(
        _sortable_th(lab, typ)
        for lab, typ in [
            ("System", "text"),
            ("Year", "text"),
            ("Gap n", "num"),
            ("Gap WR%", "num"),
            ("Base WR%", "num"),
            ("WR lift", "num"),
            ("Gap avg%", "num"),
            ("Base avg%", "num"),
            ("Avg% lift", "num"),
            ("Thin?", "text"),
        ]
    )
    s_body = []
    for r in stab_year:
        s_body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['system'])}</td>"
            f"<td>{html_mod.escape(str(r['period']))}</td>"
            f"<td>{r['gap_n']}</td>"
            f"<td>{_fmt_num(r['gap_wr_pct'])}</td>"
            f"<td>{_fmt_num(r['base_wr_pct'])}</td>"
            f"<td class=\"{_pnl_cls(r['wr_lift_pp'])}\">{_fmt_pct_pp(r['wr_lift_pp'])}</td>"
            f"<td>{_fmt_num(r['gap_avg_pnl_pct'], signed=True)}</td>"
            f"<td>{_fmt_num(r['base_avg_pnl_pct'], signed=True)}</td>"
            f"<td class=\"{_pnl_cls(r['avg_pnl_lift_pp'])}\">{_fmt_pct_pp(r['avg_pnl_lift_pp'])}</td>"
            f"<td>{'yes' if r['thin'] else 'no'}</td>"
            "</tr>"
        )

    src_lis = []
    for s in systems:
        src = sources[s]
        twin = src.stamp_twin or "—"
        src_lis.append(
            f"<li><code>{html_mod.escape(src.path.name)}</code> "
            f"({src.n_rows} rows) — {html_mod.escape(src.note)}; twin={html_mod.escape(str(twin))}</li>"
        )

    pos_systems = [r["system"] for r in verdict_rows if r["verdict"] == "positive lift"]
    no_edge = [
        r["system"]
        for r in verdict_rows
        if r["verdict"] in ("no edge (negative)", "no clear edge")
        and not r["thin"]
        and r["system"] != "ALL (pooled)"
    ]
    thin_sys = [r["system"] for r in verdict_rows if r["thin"] and r["system"] != "ALL (pooled)"]

    # Year-level: how often WR and avg both lift when gap_n >= 15 (relaxed for year slices)
    year_ok: dict[str, tuple[int, int]] = {}
    for srow in stability:
        if srow.get("period_type") != "year":
            continue
        sys = srow["system"]
        if srow.get("gap_n", 0) < 15:
            continue
        wr_l = srow.get("wr_lift_pp")
        av_l = srow.get("avg_pnl_lift_pp")
        if wr_l is None or av_l is None or (isinstance(wr_l, float) and np.isnan(wr_l)):
            continue
        good, tot = year_ok.get(sys, (0, 0))
        tot += 1
        if float(wr_l) > 0 and float(av_l) > 0:
            good += 1
        year_ok[sys] = (good, tot)

    takeaway = []
    if pos_systems:
        takeaway.append(
            "Positive lift (WR lift &gt; 0 and avg PnL% lift ≥ +0.5 pp, n≥"
            f"{THIN_N}): <strong>{', '.join(pos_systems)}</strong>."
        )
    else:
        takeaway.append(
            "No system cleared the <strong>positive lift</strong> bar "
            f"(WR &gt; 0 and avg% ≥ +0.5 pp with n≥{THIN_N})."
        )
    if no_edge:
        takeaway.append(f"No clear / negative edge: {', '.join(no_edge)}.")
    if thin_sys:
        takeaway.append(
            f"Thin samples (n&lt;{THIN_N}), treat as inconclusive: {', '.join(thin_sys)}."
        )
    # Stability blurb
    stab_bits = []
    for sys in pos_systems:
        if sys in year_ok:
            g, t = year_ok[sys]
            stab_bits.append(f"{sys} {g}/{t} years (gap n≥15) both lifts positive")
    if stab_bits:
        takeaway.append(
            "Time stability (coarse): "
            + "; ".join(stab_bits)
            + ". Most year buckets are still thin — edge is not uniformly persistent."
        )
    else:
        takeaway.append(
            "Time stability: year slices are mostly thin (n&lt;30); do not treat overall lift as year-stable."
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Gap-Up (&gt;{min_gap_pct:g}%) × System Closed Convergence</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#0f172a;background:#f8fafc;line-height:1.45;max-width:1500px}}
h1{{font-size:1.45rem;margin:0 0 .4rem}}
h2{{font-size:1.1rem;margin:1.6rem 0 .5rem;border-bottom:1px solid #cbd5e1;padding-bottom:.25rem}}
.meta{{color:#475569;font-size:.9rem;margin-bottom:1rem}}
.def{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 14px;margin:12px 0 20px;font-size:.92rem}}
.verdict{{background:#fff;border-left:4px solid #0369a1;padding:.85rem 1rem;margin:1rem 0;border-radius:0 6px 6px 0;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.pos{{color:#16a34a}} .neg{{color:#dc2626}}
.small{{color:#64748b;font-size:.85rem}}
.caption{{color:#64748b;font-size:.82rem;margin:.25rem 0 .6rem}}
table.sortable{{border-collapse:collapse;width:100%;background:#fff;font-size:.85rem;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
table.sortable th,table.sortable td{{border:1px solid #e2e8f0;padding:.35rem .5rem;text-align:left}}
table.sortable th{{background:#f1f5f9}}
table.sortable tr:nth-child(even){{background:#f8fafc}}
tr.total-row td{{background:#f1f5f9;font-weight:600;border-top:2px solid #334155}}
ul.sources{{font-size:12px;color:#475569;line-height:1.7}}
code{{font-size:11px;background:#f1f5f9;padding:1px 4px;border-radius:3px}}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Gap-Up (&gt;{min_gap_pct:g}%) × System Closed Convergence</h1>
<p class="meta">Generated {html_mod.escape(gen)}. Gap scan:
<code>{html_mod.escape(gap_csv.name)}</code> — {n_gaps:,} events with
GAP_PCT &gt; {min_gap_pct:g}%. Detail matches: {detail_n:,}. Focus: <em>entry-aligned</em> (A+B).</p>

<div class="def">
  <strong>Overlap definition (entry-aligned, primary):</strong> same <em>SYMBOL</em>, and
  <ul style="margin:.4rem 0 .4rem 1.2rem">
    <li><strong>A)</strong> <code>GAP_DATE == DATE_OPENED</code> (entered the day of the gap), and/or</li>
    <li><strong>B)</strong> <code>GAP_DATE ==</code> prior <em>trading</em> day of <code>DATE_OPENED</code>
        (signal / day-before fill when fill is next open). Prior TD from SPY calendar.</li>
  </ul>
  Each Closed trade is counted once (prefer A over B). Metrics use that trade's native
  <code>PNL_PCT</code> from open→close.<br><br>
  <strong>Hold overlap (separate):</strong> a &gt;{min_gap_pct:g}% gap occurs while the position is already open —
  <code>DATE_OPENED &lt; GAP_DATE ≤ DATE_CLOSED</code>. Trades that are already entry-aligned are excluded
  from the hold-only table so the buckets do not double-count.<br><br>
  <strong>Baseline:</strong> that system's Closed trades that are <em>not</em> entry-aligned to a
  &gt;{min_gap_pct:g}% gap. Lift = gap subset − baseline (percentage points).<br><br>
  <strong>Capital / Total_PNL:</strong> {html_mod.escape(capital_note)}
  Thin-sample flag: gap n &lt; {THIN_N}.
</div>

<div class="verdict">
  <strong>Takeaway</strong>
  {" ".join(takeaway)}
</div>

<section>
<h2>Verdict — entry-aligned gap vs baseline</h2>
<p class="caption">Click column headers to sort. Positive lift requires WR lift &gt; 0 and avg PnL% lift ≥ +0.5 pp with n≥{THIN_N}.</p>
<div class="table-wrap">
<table class="sortable">
<thead><tr>{v_head}</tr></thead>
<tbody>
{"".join(v_body)}
</tbody>
</table>
</div>
</section>

<section>
<h2>Hold-overlap only (optional)</h2>
<p class="caption">Gaps while already in the trade — not the main “entered on/around the gap” question. Click headers to sort.</p>
<table class="sortable">
<thead><tr>{h_head}</tr></thead>
<tbody>
{"".join(h_body)}
</tbody>
</table>
</section>

<section>
<h2>Time stability (by year of DATE_OPENED)</h2>
<p class="caption">Does entry-aligned edge persist? Half-year detail is in the stability CSV. Click headers to sort.</p>
<table class="sortable">
<thead><tr>{s_head}</tr></thead>
<tbody>
{"".join(s_body) if s_body else "<tr><td colspan='10'>No stability rows</td></tr>"}
</tbody>
</table>
</section>

<section>
<h2>Data sources</h2>
<ul class="sources">
{"".join(src_lis)}
</ul>
</section>

{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def _pnl_cls(v) -> str:
    if v is None:
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 0:
        return "pos"
    if x < 0:
        return "neg"
    return ""


def run(
    *,
    drive: Path,
    out_dir: Path,
    gap_csv: Optional[Path],
    min_gap_pct: float,
    spy_path: Path,
    closed_map: Optional[Path],
) -> dict:
    drive = _resolve_drive(drive)
    out_dir.mkdir(parents=True, exist_ok=True)

    if gap_csv is None:
        # Prefer ≥1% full scan then filter; find_latest prefers ~1.0 floor
        gap_csv = find_latest_gap_csv(drive, prefer_min_gap=1.0)
    else:
        gap_csv = Path(gap_csv)
        if not gap_csv.is_file():
            cand = (ROOT / gap_csv).resolve()
            gap_csv = cand if cand.is_file() else (drive / gap_csv.name)

    print(f"Gap scan: {gap_csv}")
    events = load_gaps(gap_csv, min_gap_pct=min_gap_pct)
    print(f"Gaps with GAP_PCT > {min_gap_pct:g}: {len(events):,}")
    gaps_by_sym = index_gaps(events)

    trading_days = load_trading_days(spy_path)
    if not trading_days:
        # Fallback: union of gap dates as pseudo-calendar (weaker for B)
        all_dates = sorted({e.gap_date for e in events})
        trading_days = all_dates
        print("WARN: SPY calendar missing; using gap dates as trading-day proxy for B")
    prev_td = build_prev_trading_day(trading_days)

    if closed_map:
        discovered = load_closed_map(closed_map, drive)
    else:
        discovered = discover_latest_closed(drive)
    systems = select_systems(discovered)
    # Drop systems with zero loadable trades
    trades_by_sys: dict[str, list[Trade]] = {}
    for s in list(systems):
        tr = load_trades(discovered[s])
        if not tr:
            print(f"Skip {s}: 0 trades")
            systems.remove(s)
            continue
        trades_by_sys[s] = tr
        print(f"Loaded {s}: {len(tr)} trades from {discovered[s].path.name}")

    capital_note = (
        f"initial_capital={DEFAULT_INITIAL_CAPITAL:,.0f}, "
        f"max_multiple={DEFAULT_AGGRESSIVE_MAX_MULTIPLE}, "
        f"margin_util={DEFAULT_MARGIN_UTILIZATION} → deployable "
        f"{DEFAULT_INITIAL_CAPITAL * DEFAULT_AGGRESSIVE_MAX_MULTIPLE * DEFAULT_MARGIN_UTILIZATION:,.0f}; "
        "brt_cash = deployable / Max_Positions; Total_PNL = sum(pnl% × brt_cash). "
        "Same host model as SB_System_Convergence."
    )

    all_detail: list[dict] = []
    verdict_rows: list[dict] = []
    hold_summary: list[dict] = []
    stability: list[dict] = []

    overall_gap: list[Trade] = []
    overall_base: list[Trade] = []

    for s in systems:
        trades = trades_by_sys[s]
        entry_m = match_entry_aligned(trades, gaps_by_sym, prev_td)
        entry_ix = match_ix_set(entry_m)
        hold_m = match_hold_overlap(trades, gaps_by_sym, entry_ix)

        gap_trades = [t for t in trades if t.row_ix in entry_ix]
        base_trades = [t for t in trades if t.row_ix not in entry_ix]
        overall_gap.extend(gap_trades)
        overall_base.extend(base_trades)

        gm = metrics_for_trades(gap_trades, f"{s}_gap")
        bm = metrics_for_trades(base_trades, f"{s}_base")
        n_A = sum(1 for m in entry_m if m.align == "A")
        n_B = sum(1 for m in entry_m if m.align == "B")

        row = {
            "system": s,
            "gap_n": gm["total_trades"],
            "base_n": bm["total_trades"],
            "system_n": len(trades),
            "gap_wr_pct": gm["win_rate_pct"],
            "base_wr_pct": bm["win_rate_pct"],
            "wr_lift_pp": round(gm["win_rate_pct"] - bm["win_rate_pct"], 2)
            if gap_trades and base_trades
            else None,
            "gap_avg_pnl_pct": gm["avg_profit_pct"],
            "base_avg_pnl_pct": bm["avg_profit_pct"],
            "avg_pnl_lift_pp": round(gm["avg_profit_pct"] - bm["avg_profit_pct"], 2)
            if gap_trades and base_trades
            else None,
            "gap_Ann_ROR": gm["Ann_ROR"],
            "base_Ann_ROR": bm["Ann_ROR"],
            "ann_lift_pp": round(gm["Ann_ROR"] - bm["Ann_ROR"], 2)
            if gap_trades and base_trades
            else None,
            "gap_Total_PNL": gm["Total_PNL"],
            "base_Total_PNL": bm["Total_PNL"],
            "gap_brt_cash": gm["brt_cash"],
            "base_brt_cash": bm["brt_cash"],
            "n_A": n_A,
            "n_B": n_B,
            "thin": gm["total_trades"] < THIN_N,
        }
        row["verdict"] = lift_verdict(row)
        verdict_rows.append(row)

        # Hold summary: hold matches vs trades that are neither entry nor hold? 
        # Baseline for hold = all non-entry-aligned (includes hold matches themselves
        # in "all other" would be wrong). Compare hold-matched vs trades with no gap
        # in hold window (non-entry, non-hold).
        hold_ix = match_ix_set(hold_m)
        hold_trades = [t for t in trades if t.row_ix in hold_ix]
        neither = [t for t in trades if t.row_ix not in entry_ix and t.row_ix not in hold_ix]
        hm = metrics_for_trades(hold_trades, f"{s}_hold")
        nm = metrics_for_trades(neither, f"{s}_neither")
        hold_summary.append(
            {
                "system": s,
                "hold_n": hm["total_trades"],
                "hold_wr_pct": hm["win_rate_pct"],
                "hold_avg_pnl_pct": hm["avg_profit_pct"],
                "base_n": nm["total_trades"],
                "base_wr_pct": nm["win_rate_pct"],
                "wr_lift_pp": round(hm["win_rate_pct"] - nm["win_rate_pct"], 2)
                if hold_trades and neither
                else None,
                "avg_pnl_lift_pp": round(hm["avg_profit_pct"] - nm["avg_profit_pct"], 2)
                if hold_trades and neither
                else None,
                "thin": hm["total_trades"] < THIN_N,
            }
        )

        stability.extend(stability_rows(s, gap_trades, base_trades, "year"))
        stability.extend(stability_rows(s, gap_trades, base_trades, "half"))

        for m in entry_m:
            all_detail.append(
                {
                    "overlap_kind": "entry_aligned",
                    "align": m.align,
                    "system": m.system,
                    "symbol": m.symbol,
                    "side": m.side,
                    "date_opened": m.date_opened.isoformat(),
                    "date_closed": m.date_closed.isoformat(),
                    "pnl_pct": m.pnl_pct,
                    "entry_price": m.entry_price,
                    "exit_price": m.exit_price,
                    "gap_date": m.gap_date.isoformat(),
                    "gap_pct": round(m.gap_pct, 4),
                }
            )
        for m in hold_m:
            all_detail.append(
                {
                    "overlap_kind": "hold",
                    "align": "HOLD",
                    "system": m.system,
                    "symbol": m.symbol,
                    "side": m.side,
                    "date_opened": m.date_opened.isoformat(),
                    "date_closed": m.date_closed.isoformat(),
                    "pnl_pct": m.pnl_pct,
                    "entry_price": m.entry_price,
                    "exit_price": m.exit_price,
                    "gap_date": m.gap_date.isoformat(),
                    "gap_pct": round(m.gap_pct, 4),
                }
            )

    # Overall row (dedupe not needed — different systems; report pooled trades)
    og = metrics_for_trades(overall_gap, "ALL_gap")
    ob = metrics_for_trades(overall_base, "ALL_base")
    overall = {
        "system": "ALL (pooled)",
        "gap_n": og["total_trades"],
        "base_n": ob["total_trades"],
        "system_n": og["total_trades"] + ob["total_trades"],
        "gap_wr_pct": og["win_rate_pct"],
        "base_wr_pct": ob["win_rate_pct"],
        "wr_lift_pp": round(og["win_rate_pct"] - ob["win_rate_pct"], 2),
        "gap_avg_pnl_pct": og["avg_profit_pct"],
        "base_avg_pnl_pct": ob["avg_profit_pct"],
        "avg_pnl_lift_pp": round(og["avg_profit_pct"] - ob["avg_profit_pct"], 2),
        "gap_Ann_ROR": og["Ann_ROR"],
        "base_Ann_ROR": ob["Ann_ROR"],
        "ann_lift_pp": round(og["Ann_ROR"] - ob["Ann_ROR"], 2),
        "gap_Total_PNL": og["Total_PNL"],
        "base_Total_PNL": ob["Total_PNL"],
        "gap_brt_cash": og["brt_cash"],
        "base_brt_cash": ob["brt_cash"],
        "n_A": sum(1 for d in all_detail if d["overlap_kind"] == "entry_aligned" and d["align"] == "A"),
        "n_B": sum(1 for d in all_detail if d["overlap_kind"] == "entry_aligned" and d["align"] == "B"),
        "thin": og["total_trades"] < THIN_N,
    }
    overall["verdict"] = lift_verdict(overall)
    verdict_rows.append(overall)

    # Write outputs
    html_path = out_dir / "GapUp_System_Convergence.html"
    csv_path = out_dir / "GapUp_System_Convergence.csv"
    detail_path = out_dir / "GapUp_System_Convergence_detail.csv"
    stab_path = out_dir / "GapUp_System_Convergence_stability.csv"

    pd.DataFrame(verdict_rows).to_csv(csv_path, index=False)
    pd.DataFrame(all_detail).to_csv(detail_path, index=False)
    pd.DataFrame(stability).to_csv(stab_path, index=False)

    html = build_html(
        gap_csv=gap_csv,
        min_gap_pct=min_gap_pct,
        n_gaps=len(events),
        sources={s: discovered[s] for s in systems},
        systems=systems,
        verdict_rows=verdict_rows,
        hold_rows=hold_summary,
        stability=stability,
        detail_n=len(all_detail),
        capital_note=capital_note,
    )
    html_path.write_text(html, encoding="utf-8")

    print(f"Wrote {html_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {detail_path}")
    print(f"Wrote {stab_path}")
    print("--- Verdict ---")
    for r in verdict_rows:
        print(
            f"  {r['system']:12s}  n={r['gap_n']:4d}  "
            f"WR lift={r['wr_lift_pp']}  avg% lift={r['avg_pnl_lift_pp']}  "
            f"=> {r['verdict']}"
        )
    return {
        "html": str(html_path),
        "csv": str(csv_path),
        "verdict_rows": verdict_rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Gap-up (>2%) × system Closed entry-aligned convergence"
    )
    ap.add_argument("--drive", type=Path, default=DRIVE)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument(
        "--gap-csv",
        type=Path,
        default=None,
        help="GapUp_Scan CSV (default: newest prefer ≥1%% floor, then filter)",
    )
    ap.add_argument(
        "--min-gap-pct",
        type=float,
        default=2.0,
        help="Strict GAP_PCT threshold (default 2.0 → keep >2%%)",
    )
    ap.add_argument("--spy", type=Path, default=DEFAULT_SPY)
    ap.add_argument("--closed-map", type=Path, default=None)
    args = ap.parse_args()
    run(
        drive=args.drive,
        out_dir=args.out_dir,
        gap_csv=args.gap_csv,
        min_gap_pct=float(args.min_gap_pct),
        spy_path=args.spy,
        closed_map=args.closed_map,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
