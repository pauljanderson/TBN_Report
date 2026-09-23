#!/usr/bin/env python3
"""Preview monthly + historical performance as if WRL were a first-class sleeve.

Weekly Range / Swing (WRL). Research preview only.

Does NOT wire DailyRun. Does NOT flip wired=False. Does NOT overwrite
live published monthly / system_performance / WRL_LatestRun / WRL_Closed_260906140457.
"""
from __future__ import annotations

import hashlib
import html
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS

import generate_monthly_system_report as monthly
import generate_system_performance_report as perf

ET = ZoneInfo("America/New_York")
STAMP = REPO / "drive" / "paul_experiments" / "wrl_wired_reports_preview_20260922"
SRC_DIR = REPO / "drive" / "paul_experiments" / "wrl_exitswing_univ29_20260922" / "EXIT_swing"
SRC_CLOSED = SRC_DIR / "WRL_LatestRun_Closed.csv"
SRC_OPEN = SRC_DIR / "WRL_LatestRun_Open.csv"
SRC_EQUITY = SRC_DIR / "WRL_LatestRun_EquityCurve.csv"

UNIVERSE_29 = (
    "GEHC", "FTRE", "UBER", "NE", "FANG", "CARR", "IBP", "TDG", "DELL", "HWM",
    "PANW", "STZ", "LNC", "HCA", "GDDY", "EXLS", "CWK", "CRM", "PVH", "SHC",
    "SPG", "DRI", "FNF", "FN", "ADBE", "CCL", "UNH", "HGV", "MAR",
)
IS_CUT = date(2024, 1, 1)
ORIGINAL_REQUEST = (
    "thanks - show me how this would look if it were wired in to these reports: "
    "Monthly report (all systems); Historical performance"
)

LIVE_GUARD = [
    REPO / "drive" / "Monthly_System_Report_Latest.html",
    REPO / "docs" / "monthly.html",
    REPO / "docs" / "system_performance.html",
    REPO / "drive" / "System_Performance_Latest.html",
    REPO / "drive" / "WRL_LatestRun_Closed.csv",
    REPO / "drive" / "WRL_Closed_260906140457.csv",
    REPO / "DailyRun.bat",
]


def _sha(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return f"{h.hexdigest()}:{path.stat().st_size}"


def _snapshot(paths: list[Path]) -> dict[str, Optional[str]]:
    return {str(p): _sha(p) for p in paths}


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _fmt_money(v: float) -> str:
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):,.0f}"


def _fmt_pct(v: float, signed: bool = True) -> str:
    if signed:
        return f"{v:+.2f}%"
    return f"{v:.1f}%"


def _book_stats(trades, *, opened_attr: str = "date_opened", pnl_attr: str = "pnl_dollars", pct_attr: str = "pnl_pct"):
    if not trades:
        return {"n": 0, "wr": 0.0, "avg_pct": 0.0, "pnl": 0.0, "wins": 0}
    wins = 0
    pnl = 0.0
    pct_sum = 0.0
    for t in trades:
        dollars = float(getattr(t, pnl_attr))
        pnl += dollars
        pct_sum += float(getattr(t, pct_attr))
        if dollars > 0:
            wins += 1
    n = len(trades)
    return {
        "n": n,
        "wr": 100.0 * wins / n,
        "avg_pct": pct_sum / n,
        "pnl": pnl,
        "wins": wins,
    }


MONTHLY_BANNER = """
<div style="background:#fff7ed;border:1px solid #fdba74;border-radius:10px;padding:12px 14px;margin:0 0 18px;">
  <strong>PREVIEW only — not the published monthly.</strong>
  Weekly Range / Swing (WRL) is shown as a peer of BRT / IND / RL / YH / MTS / WPBR / RS / SB / VZ / RSI
  so you can see the look of the page if the sleeve were first-class.
  <strong>Not DailyRun.</strong> <code>wired=False</code> stays. Not gold.
  Book = EXIT_swing (100% off at swing high; stop swing low; min-zone off) on the
  <strong>29-name first universe</strong>.
  Official live-style $250k wallet below stays SB / RSI / VZ / MTS / RL — same as other
  research sleeves (BRT, YH, …): they appear as system columns, not in that frozen wallet.
  29-name pick is in-sample selection; OOS softened (report-only; do not retune).
  Live <code>Monthly_System_Report_Latest.html</code> / <code>docs/monthly.html</code> were not overwritten.
</div>
"""

PERF_BANNER = """
<div class="notice ask"><strong>PREVIEW only — not the published historical performance page.</strong>
Weekly Range / Swing (WRL) is injected as a peer sleeve so you can see allocation + standalone
tables as if it were first-class. <strong>Not DailyRun.</strong> <code>wired=False</code> stays. Not gold.
Closed book = EXIT_swing on the 29-name first universe (in-sample name pick; OOS softened — report-only).
Official live-style $250k vs SPY at the top is the frozen 5-sleeve wallet (SB / RSI / VZ / MTS / RL) —
WRL is <em>not</em> added there, matching how BRT / YH / WPBR / RS appear on this page today.
Live <code>docs/system_performance.html</code> / <code>System_Performance_Latest.html</code> were not overwritten.
</div>
"""


def _copy_preview_books() -> tuple[Path, Optional[Path], Optional[Path]]:
    STAMP.mkdir(parents=True, exist_ok=True)
    closed = STAMP / "WRL_LatestRun_Closed_preview.csv"
    shutil.copy2(SRC_CLOSED, closed)
    open_p: Optional[Path] = None
    if SRC_OPEN.is_file():
        open_p = STAMP / "WRL_LatestRun_Open_preview.csv"
        shutil.copy2(SRC_OPEN, open_p)
    equity: Optional[Path] = None
    if SRC_EQUITY.is_file():
        equity = STAMP / "WRL_LatestRun_EquityCurve_preview.csv"
        shutil.copy2(SRC_EQUITY, equity)
    return closed, open_p, equity


def _inject_after(html_text: str, marker: str, banner: str) -> str:
    idx = html_text.find(marker)
    if idx < 0:
        return banner + html_text
    end = idx + len(marker)
    return html_text[:end] + banner + html_text[end:]


def build_monthly(drive: Path, closed: Path, open_p: Optional[Path]) -> tuple[Path, dict]:
    paths = monthly._resolve_system_paths(drive)
    paths["WRL"]["closed"] = closed
    paths["WRL"]["open"] = open_p if open_p and open_p.is_file() else None
    closed_rows, open_rows, sources = monthly._load_system_trades(paths)
    sources = [
        ("WRL closed: WRL_LatestRun_Closed_preview.csv "
         "(EXIT_swing univ29 — preview, not DailyRun LatestRun)")
        if s.startswith("WRL closed:") else s
        for s in sources
    ]
    now = datetime.now(tz=ET)
    year = now.year
    html_text = monthly.build_html(
        year=year,
        closed=closed_rows,
        open_rows=open_rows,
        sources=sources,
        generated=now,
    )
    html_text = _inject_after(html_text, "<body>", MONTHLY_BANNER)
    html_text = html_text.replace(
        "<title>Monthly Backtest Report",
        "<title>PREVIEW — Monthly Backtest Report (WRL wired look)",
        1,
    )
    out = STAMP / "monthly.html"
    out.write_text(html_text, encoding="utf-8")
    sidecar = REPO / "drive" / "Monthly_System_Report_WRL_preview.html"
    shutil.copy2(out, sidecar)

    year_closed = [t for t in closed_rows if t.date_closed and t.date_closed.year == year]
    by_sys: dict[str, list] = {s: [] for s in monthly.SYSTEMS}
    for t in year_closed:
        by_sys.setdefault(t.system, []).append(t)
    ytd = {s: _book_stats(rows) for s, rows in by_sys.items()}
    wrl_open = [t for t in open_rows if t.system == "WRL"]
    return out, {
        "year": year,
        "ytd": ytd,
        "wrl_open_n": len(wrl_open),
        "wrl_open_pnl": sum(t.pnl_dollars for t in wrl_open),
        "sidecar": str(sidecar),
        "sources": sources,
    }


def build_performance(drive: Path, closed: Path, equity: Optional[Path]) -> tuple[Path, dict]:
    orig_live = perf.live_performance_systems
    orig_resolve = perf.resolve_closed_path
    orig_equity = perf._equity_candidates
    orig_latest = perf.DRIVE_LATEST_NAME

    def live_plus_wrl() -> tuple[str, ...]:
        base = tuple(orig_live())
        if "WRL" in base:
            return base
        return base + ("WRL",)

    def resolve_closed(d: Path, system: str):
        if str(system).upper() == "WRL":
            return closed
        return orig_resolve(d, system)

    def equity_candidates(d: Path, system: str):
        if str(system).upper() == "WRL":
            return [equity] if equity and equity.is_file() else []
        return orig_equity(d, system)

    # drive_copy == output → skip live System_Performance_Latest.html
    rel = "paul_experiments/wrl_wired_reports_preview_20260922/system_performance.html"
    perf.live_performance_systems = live_plus_wrl  # type: ignore[assignment]
    perf.resolve_closed_path = resolve_closed  # type: ignore[assignment]
    perf._equity_candidates = equity_candidates  # type: ignore[assignment]
    perf.DRIVE_LATEST_NAME = rel
    try:
        out, payload = perf.build_report(drive, STAMP / "system_performance.html")
    finally:
        perf.live_performance_systems = orig_live
        perf.resolve_closed_path = orig_resolve
        perf._equity_candidates = orig_equity
        perf.DRIVE_LATEST_NAME = orig_latest

    html_text = out.read_text(encoding="utf-8")
    html_text = html_text.replace(
        "<title>Historical System Performance</title>",
        "<title>PREVIEW — Historical System Performance (WRL wired look)</title>",
        1,
    )
    html_text = _inject_after(html_text, '<div class="shell">', PERF_BANNER)
    out.write_text(html_text, encoding="utf-8")

    # Standalone headlines from the same Closed books the page used.
    wanted = live_plus_wrl()
    standalone: dict[str, dict] = {}
    for sys in wanted:
        path = closed if sys == "WRL" else orig_resolve(drive, sys)
        if path is None or not path.is_file():
            continue
        trades, _dup = perf.load_trades(path, sys)
        if not trades:
            continue
        m = perf.metrics(trades, system=sys)
        standalone[sys] = {
            "n": int(m["trades"]),
            "wr": float(m["win_rate"]),
            "avg_pct": float(m["avg_pct"]),
            "pnl": float(m["total_pnl"]),
            "pf": float(m["profit_factor"]) if m["profit_factor"] != float("inf") else None,
            "ann_ror": float(m.get("ann_ror") or 0.0),
            "max_dd_pct": float(m.get("max_dd_pct") or 0.0),
        }

    wrl_trades, _ = perf.load_trades(closed, "WRL")
    is_tr = [t for t in wrl_trades if t.opened < IS_CUT]
    oos_tr = [t for t in wrl_trades if t.opened >= IS_CUT]
    is_m = perf.metrics(is_tr, system="WRL") if is_tr else {}
    oos_m = perf.metrics(oos_tr, system="WRL") if oos_tr else {}

    weights = payload.get("weights") or {}
    rec = (weights.get("Recommended") or {}) if isinstance(weights, dict) else {}
    alloc = payload.get("allocation_dollars") or {}
    rec_dollars = (alloc.get("Recommended") or {}) if isinstance(alloc, dict) else {}

    return out, {
        "payload_systems": list(payload.get("systems") or []),
        "missing": list(payload.get("missing_systems") or []),
        "common_period": payload.get("common_period"),
        "recommended_weights": rec,
        "recommended_dollars": rec_dollars,
        "standalone": standalone,
        "wrl_is": {
            "n": int(is_m.get("trades") or 0),
            "wr": float(is_m.get("win_rate") or 0.0),
            "avg_pct": float(is_m.get("avg_pct") or 0.0),
            "pf": float(is_m.get("profit_factor") or 0.0),
        },
        "wrl_oos": {
            "n": int(oos_m.get("trades") or 0),
            "wr": float(oos_m.get("win_rate") or 0.0),
            "avg_pct": float(oos_m.get("avg_pct") or 0.0),
            "pf": float(oos_m.get("profit_factor") or 0.0),
        },
        "sources": payload.get("sources") or {},
        "drive_html": payload.get("drive_html"),
    }


def write_stamp(monthly_info: dict, perf_info: dict, hashes_before: dict, hashes_after: dict) -> None:
    ytd = monthly_info["ytd"]
    year = monthly_info["year"]
    standalone = perf_info["standalone"]
    period = perf_info.get("common_period") or {}
    rec_w = perf_info.get("recommended_weights") or {}
    rec_d = perf_info.get("recommended_dollars") or {}

    def _ytd_row(sys: str) -> str:
        s = ytd.get(sys) or {"n": 0, "wr": 0.0, "avg_pct": 0.0, "pnl": 0.0}
        return (
            f"<tr><td>{html.escape(sys)}</td>"
            f'<td class="num">{s["n"]}</td>'
            f'<td class="num">{s["wr"]:.1f}%</td>'
            f'<td class="num">{s["avg_pct"]:+.2f}%</td>'
            f'<td class="num">{_fmt_money(s["pnl"])}</td></tr>'
        )

    month_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("System", "text"),
            (f"{year} closed N", "num"),
            ("WR", "num"),
            ("Avg %", "num"),
            ("YTD realized $", "num"),
        )
    )
    month_body = "".join(_ytd_row(s) for s in monthly.SYSTEMS)

    def _hist_row(sys: str) -> str:
        s = standalone.get(sys)
        if not s:
            return (
                f"<tr><td>{html.escape(sys)}</td>"
                '<td class="num" colspan="6">—</td></tr>'
            )
        pf = "—" if s["pf"] is None else f"{s['pf']:.2f}"
        w = rec_w.get(sys)
        d = rec_d.get(sys)
        wtxt = f"{100.0 * float(w):.1f}%" if w is not None else "—"
        dtxt = f"${float(d):,.0f}" if d is not None else "—"
        return (
            f"<tr><td>{html.escape(sys)}</td>"
            f'<td class="num">{s["n"]:,}</td>'
            f'<td class="num">{s["wr"]:.1f}%</td>'
            f'<td class="num">{s["avg_pct"]:+.2f}%</td>'
            f'<td class="num">{pf}</td>'
            f'<td class="num">{wtxt}</td>'
            f'<td class="num">{dtxt}</td></tr>'
        )

    hist_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("System", "text"),
            ("N (full book)", "num"),
            ("WR", "num"),
            ("Avg %", "num"),
            ("PF", "num"),
            ("Recommended wt", "num"),
            ("Recommended $", "num"),
        )
    )
    hist_systems = list(perf_info.get("payload_systems") or standalone.keys())
    hist_body = "".join(_hist_row(s) for s in hist_systems)

    wrl_y = ytd.get("WRL") or {"n": 0, "wr": 0.0, "avg_pct": 0.0, "pnl": 0.0}
    wrl_s = standalone.get("WRL") or {}
    wrl_is = perf_info["wrl_is"]
    wrl_oos = perf_info["wrl_oos"]

    unchanged = []
    changed = []
    for path, before in hashes_before.items():
        after = hashes_after.get(path)
        name = Path(path).name
        if before == after:
            unchanged.append(name)
        else:
            changed.append(name)

    live_note = (
        "Live published files were <strong>not</strong> overwritten: "
        + ", ".join(html.escape(n) for n in unchanged)
        + "."
        if not changed
        else "WARNING — these live files changed during the job (not intended): "
        + ", ".join(html.escape(n) for n in changed)
        + "."
    )

    peers = [s for s in hist_systems if s != "WRL" and s in standalone]
    peer_bits = []
    for s in peers:
        m = standalone[s]
        peer_bits.append(f"{s} N={m['n']:,} WR={m['wr']:.1f}% Avg%={m['avg_pct']:+.2f}")
    peer_line = "; ".join(peer_bits)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>WRL wired-reports preview — 2026-09-22</title>
<style>
  :root {{ --bg:#f7f6f2; --ink:#1c1b19; --muted:#5a574f; --line:#d4d0c4;
    --card:#fff; --accent:#2a4a5c; --ok:#2d6a4f; --ok-bg:#e8f2ec;
    --warn:#8a5a12; --warn-bg:#f7efe0; --bad:#9b2226; --bad-bg:#fdecea; --fill:#f0eee6; }}
  body {{ margin:0; font-family:"Segoe UI","Helvetica Neue",Georgia,serif; font-size:15px;
    line-height:1.55; color:var(--ink); background:var(--bg); }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:1.55rem; margin:0 0 8px; }}
  h2 {{ font-size:1.12rem; margin:26px 0 10px; padding-bottom:5px; border-bottom:1px solid var(--line); }}
  .lede, .muted {{ color:var(--muted); }}
  .badge {{ display:inline-block; font-size:0.75rem; font-weight:700; padding:2px 8px; background:var(--bad-bg); color:var(--bad); }}
  .callout {{ background:#e8eef2; border-left:4px solid var(--accent); padding:12px 14px; margin:12px 0; }}
  .callout.warn {{ background:var(--warn-bg); border-left-color:var(--warn); }}
  .callout.ok {{ background:var(--ok-bg); border-left-color:var(--ok); }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:12px 0 8px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; min-width:150px; flex:1 1 150px; }}
  .card .k {{ font-size:0.75rem; color:var(--muted); font-weight:700; }}
  .card .v {{ font-size:1.2rem; font-weight:700; }}
  .table-wrap {{ overflow-x:auto; margin:8px 0 16px; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  th, td {{ border:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }}
  thead th {{ background:var(--fill); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  caption {{ text-align:left; font-size:0.82rem; color:var(--muted); caption-side:top; margin:0 0 6px; }}
  code {{ background:var(--fill); padding:0.08em 0.3em; }}
  th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  th.sortable-th:hover {{ background:#e4e4dc; }}
  .sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
  th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
  th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
  {SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="muted">Weekly Range / Swing (WRL) · preview stamp 2026-09-22 · not DailyRun</p>
  <h1>How monthly + historical performance look with WRL wired in</h1>
  <div class="badge">PREVIEW — not gold — wired=False stays — live pages not overwritten</div>

  <div class="callout">
    <strong>What you asked</strong>
    <p>{html.escape(ORIGINAL_REQUEST)}</p>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>You already have two published pages: the <em>monthly report</em> (all systems, this year’s
    closed trades by month) and <em>historical performance</em> (long-run sleeves plus a $500k
    mix). You asked to see those same pages <em>as if</em> Weekly Range / Swing (WRL) sat next
    to SB, RSI, VZ, MTS, RL and the rest — without actually turning DailyRun on.</p>
    <p>The numbers come from the 29-name first universe under EXIT_swing: sell the whole
    position at the swing high, stop at the swing low, min-zone off. That name list was
    picked after seeing a bigger in-sample table, so it is selection-biased. Out-of-sample
    quality softened; we report it and do not retune. The official live-style $250k vs SPY
    wallet stays the frozen five sleeves (SB / RSI / VZ / MTS / RL) — same as BRT or YH
    today: they show up as systems, not inside that wallet.</p>
  </div>

  <div class="callout warn">
    <strong>Freeze honesty.</strong> Preview ≠ DailyRun wire. Not gold. EXIT_swing house-default
    adopt may still be in flight — this only previews the <em>look</em> of the reports with
    WRL rows filled from the univ29 swing book. IS/OOS are report-only. Do not retune.
    {live_note}
  </div>

  <h2>Open the preview pages</h2>
  <ul>
    <li><a href="monthly.html">Monthly report (all systems) — WRL preview</a>
      · also <a href="../../Monthly_System_Report_WRL_preview.html">drive/Monthly_System_Report_WRL_preview.html</a></li>
    <li><a href="system_performance.html">Historical performance — WRL preview</a></li>
  </ul>
  <p class="muted">Same generators / UX as the live pages. Preview banners on those two files
  (no “What you asked” — Paul banned prompts on published investment/monthly). This stamp
  page is the one with the request + layman block.</p>

  <h2>WRL headlines on the preview</h2>
  <div class="cards">
    <div class="card"><div class="k">{year} monthly YTD</div>
      <div class="v">{_fmt_money(wrl_y["pnl"])}</div>
      <div class="muted">N={wrl_y["n"]} · WR={wrl_y["wr"]:.0f}% · Avg {wrl_y["avg_pct"]:+.2f}%</div>
    </div>
    <div class="card"><div class="k">Historical full book</div>
      <div class="v">N={wrl_s.get("n", 0):,}</div>
      <div class="muted">WR={wrl_s.get("wr", 0):.1f}% · Avg {wrl_s.get("avg_pct", 0):+.2f}% · PF={wrl_s.get("pf") or 0:.2f}</div>
    </div>
    <div class="card"><div class="k">IS (entry &lt; 2024-01-01)</div>
      <div class="v">N={wrl_is["n"]:,}</div>
      <div class="muted">WR={wrl_is["wr"]:.1f}% · Avg {wrl_is["avg_pct"]:+.2f}% · PF={wrl_is["pf"]:.2f}</div>
    </div>
    <div class="card"><div class="k">OOS (report only)</div>
      <div class="v">N={wrl_oos["n"]:,}</div>
      <div class="muted">WR={wrl_oos["wr"]:.1f}% · Avg {wrl_oos["avg_pct"]:+.2f}% · PF={wrl_oos["pf"]:.2f} — softened</div>
    </div>
  </div>
  <p class="muted">Open positions on the monthly preview: {monthly_info["wrl_open_n"]}
  (unrealized {_fmt_money(monthly_info["wrl_open_pnl"])}).
  Historical common period with WRL included:
  {html.escape(str(period.get("start", "—")))} through {html.escape(str(period.get("end", "—")))}.
  Recommended mix weight for WRL:
  {f"{100.0 * float(rec_w['WRL']):.1f}%" if rec_w.get("WRL") is not None else "—"}
  ({f"${float(rec_d['WRL']):,.0f}" if rec_d.get("WRL") is not None else "—"} of $500k).
  </p>

  <h2>{year} monthly YTD — WRL vs the other systems</h2>
  <p class="muted">House dummy Closed dollars (same as the live monthly table). Click column headers to sort.</p>
  <div class="table-wrap">
  <table class="sortable">
    <caption>Preview monthly cards / YTD column. WRL book = EXIT_swing univ29, not the old scale LatestRun.</caption>
    <thead><tr>{month_head}</tr></thead>
    <tbody>{month_body}</tbody>
  </table>
  </div>

  <h2>Historical standalone — WRL vs live sleeves</h2>
  <p class="muted">Full available period, native sizing. Recommended weight is the $500k mix
  <em>as if</em> WRL were a live sleeve. Click column headers to sort.</p>
  <div class="table-wrap">
  <table class="sortable">
    <caption>Same metric set the historical page uses for standalone rows, plus the preview Recommended sleeve.</caption>
    <thead><tr>{hist_head}</tr></thead>
    <tbody>{hist_body}</tbody>
  </table>
  </div>
  <p class="muted">Peer standalone (for chat return): {html.escape(peer_line)}</p>

  <h2>What was not changed</h2>
  <ul>
    <li>DailyRun.bat — not wired.</li>
    <li><code>tools/dailyrun_system_status.py</code> — WRL stays <code>wired=False</code>.</li>
    <li>Live monthly / historical HTML listed above.</li>
    <li>Live <code>WRL_LatestRun_Closed.csv</code> and <code>WRL_Closed_260906140457.csv</code> — not clobbered.
      Preview copies live in this stamp as <code>WRL_LatestRun_*_preview.csv</code>.</li>
    <li>Official live-style $250k vs SPY mix — WRL not added.</li>
  </ul>

  <h2>Universe (29 names, first universe)</h2>
  <p>{html.escape(", ".join(UNIVERSE_29))}</p>
  <p class="muted">Source book:
  <code>drive/paul_experiments/wrl_exitswing_univ29_20260922/EXIT_swing/</code>.
  Parent freeze: <code>wrl_target_mode=swing</code>, stop swing low, min-zone off, cooldown off.</p>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")
    (STAMP / "index.html").write_text(page, encoding="utf-8")

    baseline = f"""# WRL wired-reports preview — 2026-09-22

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

Preview of the published monthly (all systems) and historical performance pages
with Weekly Range / Swing (WRL) sitting as a peer sleeve. Not a DailyRun wire.
Not gold. Book = EXIT_swing on the 29-name first universe (in-sample selection;
OOS softened, report-only). Official live-style $250k wallet stays the frozen
five sleeves.

## Freeze honesty

- Preview ≠ DailyRun (`wired=False` stays)
- Not gold
- EXIT_swing default adopt may still be in flight — this is the look of the reports
- IS/OOS report-only; do not retune
- Live published monthly / system_performance not overwritten: {', '.join(unchanged) if not changed else 'CHANGED: ' + ', '.join(changed)}

## Book

`drive/paul_experiments/wrl_exitswing_univ29_20260922/EXIT_swing/`
(`wrl_target_mode=swing`, 100% off at swing high, stop swing low, min-zone off).

Universe 29: {', '.join(UNIVERSE_29)}

## Preview artifacts

- `monthly.html`
- `system_performance.html`
- `compare.html` / `index.html`
- `drive/Monthly_System_Report_WRL_preview.html`
- `WRL_LatestRun_*_preview.csv` (do not treat as DailyRun LatestRun)
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")


def main() -> int:
    if not SRC_CLOSED.is_file():
        raise FileNotFoundError(f"Missing EXIT_swing Closed: {SRC_CLOSED}")
    hashes_before = _snapshot(LIVE_GUARD)
    closed, open_p, equity = _copy_preview_books()
    drive = monthly._resolve_drive(REPO / "drive")
    print(f"[preview] drive={drive}")
    print(f"[preview] WRL closed={closed}")
    monthly_out, monthly_info = build_monthly(drive, closed, open_p)
    print(f"[preview] monthly -> {monthly_out}")
    perf_out, perf_info = build_performance(drive, closed, equity)
    print(f"[preview] performance -> {perf_out}")
    print(f"[preview] performance systems={perf_info['payload_systems']}")
    print(f"[preview] drive_html payload={perf_info.get('drive_html')}")
    hashes_after = _snapshot(LIVE_GUARD)
    write_stamp(monthly_info, perf_info, hashes_before, hashes_after)
    (STAMP / "preview_meta.json").write_text(
        json.dumps(
            {
                "monthly": {
                    "year": monthly_info["year"],
                    "ytd": monthly_info["ytd"],
                    "wrl_open_n": monthly_info["wrl_open_n"],
                    "wrl_open_pnl": monthly_info["wrl_open_pnl"],
                },
                "performance": {
                    "systems": perf_info["payload_systems"],
                    "missing": perf_info["missing"],
                    "common_period": perf_info["common_period"],
                    "recommended_weights": perf_info["recommended_weights"],
                    "recommended_dollars": perf_info["recommended_dollars"],
                    "standalone": perf_info["standalone"],
                    "wrl_is": perf_info["wrl_is"],
                    "wrl_oos": perf_info["wrl_oos"],
                    "drive_html": perf_info.get("drive_html"),
                },
                "hashes_before": hashes_before,
                "hashes_after": hashes_after,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    changed = [p for p, b in hashes_before.items() if hashes_after.get(p) != b]
    if changed:
        print("[preview] WARNING live files changed:")
        for p in changed:
            print(f"  {p}")
        return 2
    print("[preview] live published files unchanged")
    print(f"[preview] stamp {STAMP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
