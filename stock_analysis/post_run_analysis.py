#!/usr/bin/env python3
"""Optional post-run deep analysis (charts + CRWD-style HTML) for any system.

**Not part of DailyRun.** Cheap ONE_LINER / FIT / ImproveHints already emit from
system post-report writers (RL via ``write_rl_post_reports``; BRT/WPBR/YH/… via
``write_all_outputs`` → ``write_analysis_artifacts``).

Usage (from repo root)::

  python stock_analysis/post_run_analysis.py --system RL --stamp 260729143509 --charts
  python stock_analysis/post_run_analysis.py --system RL --stamp 260729143509 --missed-moves --no-charts
  python stock_analysis/post_run_analysis.py --system BRT --stamp 260729143513 -w 4
  python stock_analysis/post_run_analysis.py --stamp 260729143509   # auto-detect prefix
  python stock_analysis/rl_post_run_analysis.py --stamp … --missed-moves

Outputs under ``--output-dir`` (default ``drive``)::

  {prefix}_Charts_<ts>/{prefix}_<SYM>_<ts>.png
  {prefix}_SymbolAssessments_<ts>.html
  {prefix}_ImprovePriority_<ts>.html
  RL_MissedMoves_<ts>.csv          # with --missed-moves (RL/DB only)

Rule-based prose (no LLM).
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_SA = _REPO / "stock_analysis"
if str(_SA) not in sys.path:
    sys.path.insert(0, str(_SA))

try:
    from rocket_post_analysis import (
        KNOWN_SYSTEM_PREFIXES,
        RL_SYSTEMS,
        _collect_improve_hints,
        _col,
        _fnum,
        _ymd8,
        assess_symbol_fit,
        closed_summary_open_paths,
        detect_system,
        enrich_closed_csv_with_one_liners,
        enrich_summary_csv_with_avg_days_held,
        enrich_summary_csv_with_fit,
        enrich_summary_csv_with_yfinance,
        format_trade_one_liner,
        normalize_system,
        resolve_workers,
        write_improve_hints,
        write_system_charts,
    )
except ImportError:
    from stock_analysis.rocket_post_analysis import (  # type: ignore[no-redef]
        KNOWN_SYSTEM_PREFIXES,
        RL_SYSTEMS,
        _collect_improve_hints,
        _col,
        _fnum,
        _ymd8,
        assess_symbol_fit,
        closed_summary_open_paths,
        detect_system,
        enrich_closed_csv_with_one_liners,
        enrich_summary_csv_with_avg_days_held,
        enrich_summary_csv_with_fit,
        enrich_summary_csv_with_yfinance,
        format_trade_one_liner,
        normalize_system,
        resolve_workers,
        write_improve_hints,
        write_system_charts,
    )


_SORTABLE_TH_CSS = """
th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
th.sortable-th:hover { background:#e2e8f0; }
th.sortable-th .sort-ind::after { content:" \\2195"; opacity:0.35; font-size:0.85em; }
th.sortable-th.sort-asc .sort-ind::after { content:" \\2191"; opacity:0.9; }
th.sortable-th.sort-desc .sort-ind::after { content:" \\2193"; opacity:0.9; }
"""

_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      return 0;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : 0;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] && a.cells[col].textContent, type);
      var bv = parseSortValue(b.cells[col] && b.cells[col].textContent, type);
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) { x.classList.remove("sort-asc", "sort-desc"); x.setAttribute("aria-sort", "none"); });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _resolve_stamp(output_dir: Path, stamp: Optional[str]) -> str:
    if stamp and str(stamp).strip():
        return str(stamp).strip()
    ts_file = output_dir / "last_run_ts.txt"
    if ts_file.is_file():
        return ts_file.read_text(encoding="utf-8").strip()
    raise SystemExit(f"No --stamp and no {ts_file}")


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_tickers(symbols: list[str], data_dir: Path, *, workers: int = 4) -> dict[str, pd.DataFrame]:
    """Load OHLC via rocket_brt helpers when available; else raw CSV."""
    tickers: dict[str, pd.DataFrame] = {}
    try:
        from rocket_brt import load_all_tickers  # type: ignore
    except ImportError:
        try:
            from stock_analysis.rocket_brt import load_all_tickers  # type: ignore
        except ImportError:
            load_all_tickers = None  # type: ignore

    if load_all_tickers is not None:
        try:
            loaded = load_all_tickers(
                str(data_dir),
                symbols_filter={s.upper() for s in symbols},
                max_workers=max(1, workers),
            )
            if isinstance(loaded, dict):
                return {str(k).upper(): v for k, v in loaded.items()}
        except Exception as e:
            print(f"[post_run_analysis] load_all_tickers failed ({e}); falling back to CSV.", flush=True)

    for sym in symbols:
        for candidate in (
            data_dir / f"{sym}.csv",
            data_dir / f"{sym.upper()}.csv",
            data_dir / f"{sym.lower()}.csv",
        ):
            if candidate.is_file():
                df = pd.read_csv(candidate)
                cols = {c.lower(): c for c in df.columns}
                date_col = cols.get("date")
                if date_col:
                    df[date_col] = pd.to_datetime(df[date_col])
                    df = df.set_index(date_col)
                tickers[sym.upper()] = df
                break
    return tickers


def _era_breakdown(rows: list[dict[str, Any]]) -> list[tuple[str, int, int, float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        ymd = _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED"))
        year = ymd[:4] if len(ymd) >= 4 else "?"
        buckets[year].append(_fnum(_col(r, "PNL %", "PNL_PCT")))
    out = []
    for year in sorted(buckets):
        pnls = buckets[year]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p < 0)
        out.append((year, wins, losses, sum(pnls)))
    return out


def _symbol_hypotheses(rows: list[dict[str, Any]], *, prefix: str) -> list[str]:
    lines: list[str] = []
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            _ymd8(_col(r, "DATE OPENED", "DATE_OPENED")),
            _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED")),
        ),
    )
    quick_stop_after_target = 0
    shallow_fails = 0
    givebacks = 0
    false_2223 = 0
    slow_targets = 0
    peak_givebacks = 0
    early_long_tails = 0
    for i, r in enumerate(sorted_rows):
        exit_type = str(_col(r, "EXIT TYPE", "EXIT_TYPE", default="")).upper()
        days = int(_fnum(_col(r, "DAYS HELD", "DAYS_HELD"), 0))
        pnl = _fnum(_col(r, "PNL %", "PNL_PCT"))
        max_gain = _fnum(_col(r, "MAX GAIN", "MAX_GAIN"))
        max_gain_pct = abs(max_gain) * 100 if 0 < abs(max_gain) < 2 else abs(max_gain)
        entry = _fnum(_col(r, "ENTRY PRICE", "ENTRY_PRICE"))
        max_px = _fnum(_col(r, "MAX_PRICE", "MAX PRICE"))
        mfe_pct = (
            (max_px / entry - 1.0) * 100.0
            if entry > 0 and max_px > entry
            else max_gain_pct
        )
        d10 = _fnum(_col(r, "DAYS_HELD_FIRST_UP_10PCT", "DAYS HELD FIRST UP 10PCT"), -1.0)
        s50 = _fnum(_col(r, "SMA50"))
        ymd = _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED"))
        year = int(ymd[:4]) if len(ymd) >= 4 and ymd[:4].isdigit() else 0
        if i + 1 < len(sorted_rows):
            nxt = sorted_rows[i + 1]
            if "TARGET" in exit_type and "STOP" in str(
                _col(nxt, "EXIT TYPE", "EXIT_TYPE", default="")
            ).upper():
                if int(_fnum(_col(nxt, "DAYS HELD", "DAYS_HELD"), 0)) <= 10:
                    quick_stop_after_target += 1
        if "STOP" in exit_type and days <= 7 and entry > 0 and s50 > 0 and abs(entry / s50 - 1) * 100 <= 3:
            shallow_fails += 1
        if "STOP" in exit_type and max_gain_pct >= 15 and pnl < 0:
            givebacks += 1
        if "STOP" in exit_type and year in (2022, 2023) and days <= 15 and pnl < 0:
            false_2223 += 1
        if "TARGET" in exit_type and days >= 100:
            slow_targets += 1
        if pnl > 0 and mfe_pct >= 15.0 and (mfe_pct - pnl) >= 10.0 and days >= 15:
            peak_givebacks += 1
        if pnl > 0 and 0 < d10 <= 25 and days >= 80:
            early_long_tails += 1

    p = normalize_system(prefix)
    if p in RL_SYSTEMS:
        if quick_stop_after_target:
            lines.append(
                f"Post-TARGET quick STOP ×{quick_stop_after_target} → try "
                f"``rl_post_target_reentry_bars`` + ``rl_post_target_reentry_mode`` "
                f"(``stop_loss`` / ``min_stack`` / ``under_sma_limit`` / ``none``; "
                f"avoid calendar cooldown)."
            )
        if shallow_fails:
            lines.append(
                f"Shallow SMA50 fails ×{shallow_fails} → tighten ``rl_dip_pct`` or raise "
                f"``rl_slope_threshold``."
            )
        if givebacks:
            lines.append(
                f"MTM giveback then STOP ×{givebacks} → enable ``rl_trail_profit`` / ``rl_trail_stop``."
            )
        if false_2223:
            lines.append(
                f"2022–2023 false-start STOPs ×{false_2223} → slope/extension gates or SPY weak block."
            )
        if slow_targets:
            lines.append(
                f"Slow TARGET (≥100d) ×{slow_targets} → contract ``rl_target_pct`` or "
                f"``rl_exit_percent``/``rl_exit_days`` / partial exit (turnover)."
            )
        if peak_givebacks:
            lines.append(
                f"Winner peak giveback ×{peak_givebacks} → ``rl_trail_profit`` / ``rl_trail_stop``."
            )
        if early_long_tails:
            lines.append(
                f"Early +10% then long hold ×{early_long_tails} → trail-after-profit or closer target."
            )
    else:
        if quick_stop_after_target:
            lines.append(
                f"Post-TARGET quick STOP ×{quick_stop_after_target} → "
                f"``rl_post_target_reentry_bars`` + mode "
                f"(``none`` / ``under_sma_limit`` / ``min_stack`` / ``stop_loss``) "
                f"or longer ``symbol_reentry_cooldown_days``."
            )
        if shallow_fails:
            lines.append(
                f"Shallow SMA50 fails ×{shallow_fails} → tighten entry quality / zone proximity."
            )
        if givebacks:
            lines.append(f"MTM giveback then STOP ×{givebacks} → trails or partial scale-out.")
        if false_2223:
            lines.append(
                f"2022–2023 false-start STOPs ×{false_2223} → regime / start_date filters."
            )
        if slow_targets:
            lines.append(
                f"Slow TARGET (≥100d) ×{slow_targets} → contract ``target_pct`` or shorter "
                f"``time_stop_days`` / STRENGTH-style early take (turnover/Ann_ROR)."
            )
        if peak_givebacks:
            lines.append(
                f"Winner peak giveback ×{peak_givebacks} → trail "
                f"(``trailing_stop_increment`` / ``sma_stop_days`` / chandelier) or scale-out."
            )
        if early_long_tails:
            lines.append(
                f"Early +10% then long hold ×{early_long_tails} → trail after +10% or closer target."
            )
    if not lines:
        lines.append("No strong rule-based pattern cluster; review charts + one-liners manually.")
    return lines


def _product_owner_line(
    sym: str, fr_text: str, trades: int, pct_wins: float, avg_pnl: float, *, prefix: str
) -> str:
    label = normalize_system(prefix) or "system"
    verdict = (
        f"fits {label} well"
        if "High" in fr_text
        else (f"mixed {label} fit" if "Medium" in fr_text else f"poor {label} fit / needs gates")
    )
    return (
        f"{sym}: {verdict} — {trades} trades, {pct_wins:.0f}% wins, avg {avg_pnl:+.1f}%. "
        f"{fr_text}"
    )


def _missed_moves_section_html(events: list[Any], *, max_rows: int = 12) -> str:
    """Per-symbol missed / blind-spot table (RL ``--missed-moves``)."""
    if not events:
        return (
            "<h3>6. Missed / almost-taken moves</h3>"
            "<p class=\"muted\">No material NEAR_MISS / BLIND_SPOT events "
            "(or <code>--missed-moves</code> not requested).</p>"
        )
    parts: list[str] = [
        "<h3>6. Missed / almost-taken moves</h3>",
        "<p class=\"muted\">Heuristic OHLC+SMA scan (not full MarkTen). "
        "NEAR_MISS = dip+stack OK but secondary gate blocked; "
        "BLIND_SPOT = stack+near-dip rally where primary gate was incomplete. "
        "Click headers to sort.</p>",
        '<table class="sortable"><thead><tr>',
    ]
    for lab, typ in (
        ("Kind", "text"),
        ("Trigger", "date"),
        ("Block / miss", "text"),
        ("Fwd max 20d%", "num"),
        ("Fwd max 60d%", "num"),
        ("Fwd ret 20d%", "num"),
        ("Hit TARGET-like 60d", "num"),
        ("Notes", "text"),
    ):
        parts.append(_sortable_th(lab, typ))
    parts.append("</tr></thead><tbody>")
    for e in events[:max_rows]:
        raw_d = str(getattr(e, "trigger_date", "") or "")
        ymd = _ymd8(raw_d)
        trig = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) >= 8 else raw_d
        parts.append(
            "<tr>"
            f"<td>{html.escape(str(getattr(e, 'kind', '')))}</td>"
            f"<td>{html.escape(trig)}</td>"
            f"<td><code>{html.escape(str(getattr(e, 'block_reasons', '')))}</code></td>"
            f"<td>{float(getattr(e, 'fwd_max_gain_20d_pct', 0)):.1f}</td>"
            f"<td>{float(getattr(e, 'fwd_max_gain_60d_pct', 0)):.1f}</td>"
            f"<td>{float(getattr(e, 'fwd_ret_20d_pct', 0)):.1f}</td>"
            f"<td>{int(getattr(e, 'hit_target_like_60d', 0))}</td>"
            f"<td>{html.escape(str(getattr(e, 'setup_notes', '')))}</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")
    if len(events) > max_rows:
        parts.append(
            f"<p class=\"muted\">Showing top {max_rows} of {len(events)} "
            f"(see MissedMoves CSV for full list).</p>"
        )
    return "\n".join(parts)


def build_symbol_assessment(
    sym: str,
    summary_row: dict[str, Any],
    closed_rows: list[dict[str, Any]],
    *,
    prefix: str,
    dip_pct: float,
    chart_rel: Optional[str] = None,
    missed_events: Optional[list[Any]] = None,
) -> str:
    """CRWD-style HTML section for one symbol (rule-based)."""
    trades = int(_fnum(summary_row.get("TRADES"), len(closed_rows)))
    wins = int(_fnum(summary_row.get("WINS"), 0))
    losses = int(_fnum(summary_row.get("LOSSES"), 0))
    pct_wins = _fnum(str(summary_row.get("PCT_WINS", "")).replace("%", ""))
    if trades and not pct_wins and wins:
        pct_wins = wins / trades * 100
    avg_pnl = _fnum(str(summary_row.get("AVG_PNL_PCT", "")).replace("%", ""))
    sheet_pnl = _fnum(summary_row.get("SHEET_PNL"))
    avg_tpy = _fnum(summary_row.get("AVG_TRADES_PER_YEAR"))
    fr = assess_symbol_fit(
        trades=trades,
        wins=wins,
        losses=losses,
        pct_wins=pct_wins,
        avg_pnl_pct=avg_pnl,
        sheet_pnl=sheet_pnl,
        avg_tpy=avg_tpy,
        closed_rows=closed_rows,
    )

    win_pnls = [_fnum(_col(r, "PNL %", "PNL_PCT")) for r in closed_rows if _fnum(_col(r, "PNL %", "PNL_PCT")) > 0]
    loss_pnls = [_fnum(_col(r, "PNL %", "PNL_PCT")) for r in closed_rows if _fnum(_col(r, "PNL %", "PNL_PCT")) < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

    eras = _era_breakdown(closed_rows)
    hyps = _symbol_hypotheses(closed_rows, prefix=prefix)
    owner = _product_owner_line(sym, fr.text, trades, pct_wins, avg_pnl, prefix=prefix)
    pref = normalize_system(prefix)

    parts: list[str] = [
        f'<section class="sym" id="{html.escape(sym)}">',
        f"<h2>{html.escape(sym)} — {html.escape(fr.fit)} fit (score {fr.score}"
        + (
            f"; robust {html.escape(fr.fit_robust)} {fr.score_robust}"
            if fr.fit_robust and (fr.score_robust != fr.score or fr.fit_robust != fr.fit)
            else ""
        )
        + ")</h2>",
        f'<p class="owner"><strong>PO one-liner:</strong> {html.escape(owner)}</p>',
    ]
    if chart_rel:
        parts.append(
            f'<p class="chart"><img src="{html.escape(chart_rel)}" alt="{html.escape(sym)} {html.escape(pref)} chart" '
            f'loading="lazy" style="max-width:100%;height:auto;border:1px solid #d8d8d0"/></p>'
        )

    parts.append("<h3>1. Ledger + Summary</h3>")
    parts.append('<table class="sortable"><thead><tr>')
    for lab, typ in (
        ("Trades", "num"),
        ("W/L", "text"),
        ("Pct wins", "num"),
        ("Avg PnL%", "num"),
        ("Sheet PnL", "num"),
        ("Trades/yr", "num"),
        ("Avg win%", "num"),
        ("Avg loss%", "num"),
        ("FIT", "text"),
    ):
        parts.append(_sortable_th(lab, typ))
    parts.append("</tr></thead><tbody><tr>")
    parts.extend(
        [
            f"<td>{trades}</td>",
            f"<td>{wins}/{losses}</td>",
            f"<td>{pct_wins:.1f}%</td>",
            f"<td>{avg_pnl:+.2f}%</td>",
            f"<td>{sheet_pnl:,.0f}</td>",
            f"<td>{avg_tpy:.2f}</td>",
            f"<td>{avg_win:+.1f}</td>",
            f"<td>{avg_loss:+.1f}</td>",
            f"<td>{html.escape(fr.fit)}</td>",
        ]
    )
    parts.append("</tr></tbody></table>")

    parts.append("<h3>2. Era breakdown</h3>")
    if eras:
        parts.append('<table class="sortable"><thead><tr>')
        for lab, typ in (("Year", "num"), ("Wins", "num"), ("Losses", "num"), ("Sum PnL%", "num")):
            parts.append(_sortable_th(lab, typ))
        parts.append("</tr></thead><tbody>")
        for year, w, l, sp in eras:
            parts.append(
                f"<tr><td>{html.escape(year)}</td><td>{w}</td><td>{l}</td><td>{sp:+.1f}</td></tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append("<p>No closed trades.</p>")

    parts.append(f"<h3>3. Does it behave as we want for {html.escape(pref)}?</h3>")
    want = (
        f"Yes — win rate and expectancy support keeping this name in the {pref} universe."
        if fr.fit == "High"
        else (
            "Mixed — some eras work; review hypotheses and charts before changing levers globally."
            if fr.fit == "Medium"
            else f"No / weak — consider dropping from universe or symbol-specific gates."
        )
    )
    parts.append(f"<p>{html.escape(want)}</p>")
    parts.append(f'<p class="muted">{html.escape(fr.text)}</p>')

    parts.append(f"<h3>4. Improvement hypotheses → {html.escape(pref)} levers</h3><ul>")
    for h in hyps:
        parts.append(f"<li>{html.escape(h)}</li>")
    parts.append("</ul>")

    dip_note = ""
    if pref in RL_SYSTEMS and dip_pct > 1.0:
        dip_note = f" (dip ±{(dip_pct - 1.0) * 100:.1f}%)"
    parts.append(f"<h3>5. Trade-by-trade one-liners{html.escape(dip_note)}</h3><ul class=\"oneliners\">")
    for r in sorted(closed_rows, key=lambda x: _ymd8(_col(x, "DATE OPENED", "DATE_OPENED"))):
        line = r.get("ONE_LINER") or format_trade_one_liner(r, dip_pct=dip_pct)
        parts.append(f"<li><code>{html.escape(str(line))}</code></li>")
    parts.append("</ul>")
    if missed_events is not None:
        parts.append(_missed_moves_section_html(missed_events))
    parts.append("</section>")
    return "\n".join(parts)


def write_symbol_assessments_html(
    *,
    path: Path,
    ts: str,
    prefix: str,
    dip_pct: float,
    summary_rows: list[dict[str, Any]],
    closed_by_sym: dict[str, list[dict[str, Any]]],
    symbols: list[str],
    chart_dir: Optional[Path],
    missed_by_sym: Optional[dict[str, list[Any]]] = None,
) -> Path:
    pref = normalize_system(prefix)
    sections: list[str] = []
    for sym in symbols:
        srow = next((r for r in summary_rows if str(r.get("SYMBOL", "")).upper() == sym), {})
        if not srow and sym not in closed_by_sym and not (missed_by_sym and sym in missed_by_sym):
            continue
        chart_rel = None
        if chart_dir and (chart_dir / f"{pref}_{sym}_{ts}.png").is_file():
            try:
                chart_rel = str((chart_dir / f"{pref}_{sym}_{ts}.png").relative_to(path.parent)).replace("\\", "/")
            except ValueError:
                chart_rel = str(chart_dir / f"{pref}_{sym}_{ts}.png")
        sections.append(
            build_symbol_assessment(
                sym,
                srow or {"SYMBOL": sym, "TRADES": len(closed_by_sym.get(sym, []))},
                closed_by_sym.get(sym, []),
                prefix=pref,
                dip_pct=dip_pct,
                chart_rel=chart_rel,
                missed_events=(missed_by_sym or {}).get(sym) if missed_by_sym is not None else None,
            )
        )

    body = "\n".join(sections) or "<p>No symbols to assess.</p>"
    toc = "".join(f'<li><a href="#{html.escape(s)}">{html.escape(s)}</a></li>' for s in symbols if s in closed_by_sym)
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(pref)} Symbol Assessments — {html.escape(ts)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; line-height:1.45; }}
  .wrap {{ max-width:1100px; margin:0 auto; }}
  h1 {{ font-size:1.6rem; margin:0 0 8px; }}
  h2 {{ margin-top:2.2rem; border-bottom:1px solid #d8d8d0; padding-bottom:4px; }}
  h3 {{ margin-top:1.2rem; font-size:1.05rem; }}
  .muted {{ color:#5c5c56; }}
  .owner {{ background:#eef3f8; padding:10px 12px; border-radius:4px; }}
  table.sortable {{ border-collapse:collapse; width:100%; margin:8px 0 16px; font-size:13px; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:6px 8px; text-align:left; }}
  table.sortable th {{ background:#f0f0ea; }}
  ul.oneliners {{ font-size:12px; }}
  ul.oneliners code {{ white-space:pre-wrap; }}
  {_SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>{html.escape(pref)} Symbol Assessments — stamp {html.escape(ts)}</h1>
  <p class="muted">Rule-based CRWD-style briefs (not LLM). Generated by
  <code>post_run_analysis.py</code> — <strong>not</strong> part of DailyRun.
  Click column headers to sort. Charts embedded when present under <code>{html.escape(pref)}_Charts_{html.escape(ts)}/</code>.
  Section 6 (missed moves) appears when run with <code>--missed-moves</code> (RL heuristic).</p>
  <nav><strong>Symbols:</strong><ul>{toc}</ul></nav>
  {body}
</div>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path


def _yh_param_ab_action(param: str, direction: str, ts: str, pref: str) -> str:
    """Inline Run AB hint for YH band/target/stop cards (hypothesis-test one-knob)."""
    p = (param or "").strip().lower()
    d = (direction or "").strip().lower()
    if pref.upper() != "YH" or p not in ("band_pct", "target_pct", "stop_pct"):
        return ""
    if d in ("", "hold", "mixed", "adopt"):
        return "<span class=\"muted\">no mapped alt</span>"
    bat = f"run_yh_param_hint_ab.bat {html.escape(ts)}"
    cmp_rel = "paul_experiments/yh_param_hint_ab/comparison.html"
    return (
        f"<code>{bat}</code><br/>"
        f"<span class=\"muted\">one knob · </span>"
        f"<a href=\"{html.escape(cmp_rel)}\">comparison.html</a>"
    )


def write_improve_priority_html(
    *,
    path: Path,
    ts: str,
    prefix: str,
    closed_rows: list[dict[str, Any]],
    miss_themes: Optional[list[dict[str, Any]]] = None,
    drive_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> Path:
    pref = normalize_system(prefix)
    hints = _collect_improve_hints(
        closed_rows,
        prefix=pref,
        drive_dir=drive_dir or path.parent,
        data_dir=data_dir,
    )

    def _rows_for(cat: str, *, with_ab: bool = False) -> str:
        items = [h for h in hints if getattr(h, "category", "pattern") == cat]
        colspan = 13 if with_ab else 12
        if not items:
            return f'<tr><td colspan="{colspan}">None met threshold / data unavailable.</td></tr>'
        parts = []
        for i, h in enumerate(items, 1):
            pct = f"{h.pct_of_trades:.1f}" if getattr(h, "pct_of_trades", 0) else ""
            ab_cell = ""
            if with_ab:
                ab = _yh_param_ab_action(
                    getattr(h, "param", "") or "",
                    getattr(h, "direction", "") or "",
                    ts,
                    pref,
                )
                ab_cell = f"<td>{ab}</td>"
            parts.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{html.escape(h.hypothesis_id)}</td>"
                f"<td>{html.escape(getattr(h, 'param', '') or '')}</td>"
                f"<td>{html.escape(getattr(h, 'direction', '') or '')}</td>"
                f"<td>{html.escape(getattr(h, 'confidence', '') or '')}</td>"
                f"<td>{h.symbol_count}</td>"
                f"<td>{h.trade_count}</td>"
                f"<td>{html.escape(pct)}</td>"
                f"<td>{html.escape(h.lever)}</td>"
                f"<td>{html.escape(h.suggestion)}</td>"
                f"<td>{html.escape(','.join(h.symbols[:12]))}</td>"
                f"<td>{html.escape(h.evidence)}</td>"
                f"{ab_cell}"
                "</tr>"
            )
        return "".join(parts)

    hint_thead = f"""
    {_sortable_th("#", "num")}
    {_sortable_th("Hypothesis", "text")}
    {_sortable_th("Param", "text")}
    {_sortable_th("Direction", "text")}
    {_sortable_th("Confidence", "text")}
    {_sortable_th("Symbols", "num")}
    {_sortable_th("Trades", "num")}
    {_sortable_th("% scored", "num")}
    {_sortable_th("Lever", "text")}
    {_sortable_th("Suggestion", "text")}
    {_sortable_th("Example symbols", "text")}
    {_sortable_th("Evidence", "text")}
"""
    param_thead = hint_thead + f"    {_sortable_th('Run AB', 'text')}\n"

    miss_block = ""
    if miss_themes is not None:
        miss_rows = []
        for i, t in enumerate(miss_themes, 1):
            miss_rows.append(
                "<tr>"
                f"<td>{i}</td>"
                f"<td>{html.escape(str(t.get('hypothesis_id', '')))}</td>"
                f"<td>{html.escape(str(t.get('tag', '')))}</td>"
                f"<td>{int(t.get('symbol_count', 0))}</td>"
                f"<td>{int(t.get('event_count', 0))}</td>"
                f"<td>{int(t.get('near_miss', 0))}</td>"
                f"<td>{int(t.get('blind_spot', 0))}</td>"
                f"<td>{float(t.get('avg_fwd_max_gain_60d', 0)):.1f}</td>"
                f"<td>{html.escape(str(t.get('lever', '')))}</td>"
                f"<td>{html.escape(str(t.get('suggestion', '')))}</td>"
                f"<td>{html.escape(','.join(t.get('symbols', [])[:12]))}</td>"
                f"<td>{html.escape(str(t.get('evidence', '')))}</td>"
                "</tr>"
            )
        if not miss_rows:
            miss_rows.append(
                '<tr><td colspan="12">No multi-symbol missed-winner themes '
                "(or no material forward-gain events).</td></tr>"
            )
        miss_block = f"""
  <h2>Why we miss winners (heuristic)</h2>
  <p class="muted">From <code>--missed-moves</code>: gates that blocked dip+stack setups
  (NEAR_MISS) or primary incompleteness before a rally (BLIND_SPOT). Heuristic != MarkTen;
  confirm on charts. Click headers to sort.</p>
  <table class="sortable"><thead><tr>
    {_sortable_th("#", "num")}
    {_sortable_th("Hypothesis", "text")}
    {_sortable_th("Tag", "text")}
    {_sortable_th("Symbols", "num")}
    {_sortable_th("Events", "num")}
    {_sortable_th("Near-miss", "num")}
    {_sortable_th("Blind spot", "num")}
    {_sortable_th("Avg fwd max 60d%", "num")}
    {_sortable_th("Lever", "text")}
    {_sortable_th("Suggestion", "text")}
    {_sortable_th("Example symbols", "text")}
    {_sortable_th("Evidence", "text")}
  </tr></thead><tbody>
  {''.join(miss_rows)}
  </tbody></table>
"""

    # Primary section = actionable param hypotheses (+ Run AB for YH). Taken-trade
    # patterns and peer-learn follow so AB does not read as a bolted-on second feature.
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(pref)} Improve Priority — {html.escape(ts)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1200px; margin:0 auto; }}
  h1 {{ font-size:1.5rem; }}
  h2 {{ font-size:1.2rem; margin-top:2rem; }}
  .muted {{ color:#5c5c56; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:6px 8px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  code {{ font-size:12px; }}
  {_SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>{html.escape(pref)} Improve Priority — stamp {html.escape(ts)}</h1>
  <p class="muted">Portfolio-level rule hypotheses ranked by symbol/trade frequency.
  Layout: <strong>Parameter suggestions</strong> (with Run AB) first, then taken-trade patterns / peer-learn.
  Companion to cheap <code>{html.escape(pref)}_ImproveHints_{html.escape(ts)}.csv</code> from DailyRun
  (also includes param-tweak + peer-learn sections). Click headers to sort.
  Not LLM; use with charts + SymbolAssessments HTML.
  Next step is a <strong>one-knob hypothesis test</strong> (see <code>docs/HYPOTHESIS_TEST.md</code>), not a search for optimal params.</p>
  <h2>Parameter suggestions (band / target / stop)</h2>
  <p class="muted">Primary workbench: direction = tighten/loosen/expand/contract/hold/mixed.
  Same-param opposing lenses (e.g. stop expand vs hold) are merged into one tension card;
  confidence is capped when evidence conflicts. Prefer one coherent next hypothesis.
  YH: use <code>run_yh_param_hint_ab.bat {html.escape(ts)}</code> (control vs suggested direction).</p>
  <table class="sortable"><thead><tr>{param_thead}</tr></thead>
  <tbody>{_rows_for("param", with_ab=True)}</tbody></table>
  <h2>Taken-trade patterns</h2>
  <table class="sortable"><thead><tr>{hint_thead}</tr></thead>
  <tbody>{_rows_for("pattern")}</tbody></table>
  <h2>Peer-learn (cross-system overlap)</h2>
  <p class="muted">Countable adopt-from-peer suggestions when hold ranges overlap peer Closed books.</p>
  <table class="sortable"><thead><tr>{hint_thead}</tr></thead>
  <tbody>{_rows_for("peer_learn")}</tbody></table>
  {miss_block}
</div>
{_SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path



def _harden_stdio() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def main(argv: Optional[list[str]] = None, *, default_system: str = "") -> int:
    _harden_stdio()
    ap = argparse.ArgumentParser(
        description="Optional charts + CRWD-style deep HTML for any system (NOT part of DailyRun)."
    )
    ap.add_argument("--stamp", "-t", default="", help="Run stamp (default: drive/last_run_ts.txt)")
    ap.add_argument(
        "--system",
        default=default_system,
        help=f"System prefix ({'|'.join(KNOWN_SYSTEM_PREFIXES)}); default auto-detect from Closed",
    )
    ap.add_argument("--closed", default="", help="Explicit Closed CSV path (overrides stamp/prefix)")
    ap.add_argument("--output-dir", "-o", default="drive", help="Output dir (default drive)")
    ap.add_argument(
        "--data-dir",
        default="data/newdata/data",
        help="OHLC CSV directory for charts",
    )
    ap.add_argument(
        "--charts",
        action="store_true",
        default=True,
        help="Generate matplotlib PNGs (default: on for this script)",
    )
    ap.add_argument("--no-charts", action="store_true", help="Skip PNG generation")
    ap.add_argument(
        "--workers",
        "-w",
        type=int,
        default=-1,
        help="Parallel chart workers (default: min(4, CPUs); 0=sequential)",
    )
    ap.add_argument(
        "--symbols",
        "-s",
        default="",
        help="Comma-separated symbols (default: all traded in Closed)",
    )
    ap.add_argument("--dip-pct", type=float, default=0.0, help="Override rl_dip_pct (0=read Report or 1.041)")
    ap.add_argument("--band-pct", type=float, default=0.02, help="Zone half-width for zone-system charts")
    ap.add_argument(
        "--refresh-cheap",
        action="store_true",
        help=(
            "Re-write ONE_LINER / CURRENT_MARKET_CAP+SECTOR+INDUSTRY / FIT / "
            "ImproveHints CSV before deep HTML"
        ),
    )
    ap.add_argument(
        "--missed-moves",
        action="store_true",
        help=(
            "RL/DB only: heuristic near-miss + blind-spot scan (OHLC+SMA); "
            "writes RL_MissedMoves_<ts>.csv and HTML sections. Not MarkTen-perfect."
        ),
    )
    ap.add_argument(
        "--missed-min-gain",
        type=float,
        default=8.0,
        help="Min fwd max-gain %% to keep a NEAR_MISS (default 8)",
    )
    ap.add_argument(
        "--missed-blind-min-gain",
        type=float,
        default=12.0,
        help="Min fwd max-gain %% to keep a BLIND_SPOT (default 12)",
    )
    args = ap.parse_args(argv)

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = _REPO / output_dir
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = _REPO / data_dir

    closed_override = Path(args.closed) if str(args.closed).strip() else None
    if closed_override is not None and not closed_override.is_absolute():
        closed_override = _REPO / closed_override

    ts = _resolve_stamp(output_dir, args.stamp)
    if closed_override and closed_override.is_file():
        # Stamp from filename when possible
        stem = closed_override.stem
        if "_Closed_" in stem:
            ts = stem.split("_Closed_", 1)[-1]

    prefix = detect_system(
        output_dir,
        ts,
        system=args.system,
        closed_path=closed_override,
    )
    closed_path, summary_path, open_path = closed_summary_open_paths(
        output_dir, prefix, ts, closed_path=closed_override
    )
    if not closed_path.is_file():
        raise SystemExit(f"Missing Closed CSV: {closed_path}")

    dip = float(args.dip_pct) if args.dip_pct and args.dip_pct > 0 else 0.0
    if dip <= 0:
        report = output_dir / f"{prefix}_Report_{ts}.csv"
        if report.is_file() and prefix in RL_SYSTEMS:
            with report.open(newline="", encoding="utf-8") as f:
                r = next(csv.DictReader(f), {})
            dip = _fnum(r.get("rl_dip_pct"), 1.041) or 1.041
        else:
            dip = 1.041

    n_workers = resolve_workers(int(args.workers))
    print(
        f"[post_run_analysis] system={prefix} stamp={ts} dip_pct={dip} "
        f"workers={n_workers} output={output_dir}",
        flush=True,
    )

    if args.refresh_cheap or not summary_path.is_file():
        if summary_path.is_file():
            enrich_closed_csv_with_one_liners(closed_path, dip_pct=dip)
            enrich_summary_csv_with_yfinance(summary_path)
            # AVG_DAYS_HELD before FIT/PAUL_SCORE so the days-held peer component can fire.
            enrich_summary_csv_with_avg_days_held(summary_path, closed_path)
            enrich_summary_csv_with_fit(summary_path, closed_path, prefix=prefix)
            write_improve_hints(
                closed_path,
                output_dir,
                ts,
                prefix=prefix,
                drive_dir=output_dir,
                data_dir=Path(args.data_dir) if args.data_dir else None,
            )
        else:
            enrich_closed_csv_with_one_liners(closed_path, dip_pct=dip)
            print(f"[post_run_analysis] No Summary yet: {summary_path}", flush=True)

    enrich_closed_csv_with_one_liners(closed_path, dip_pct=dip)
    if summary_path.is_file():
        enrich_summary_csv_with_yfinance(summary_path)
        # AVG_DAYS_HELD before FIT/PAUL_SCORE so the days-held peer component can fire.
        enrich_summary_csv_with_avg_days_held(summary_path, closed_path)
        enrich_summary_csv_with_fit(summary_path, closed_path, prefix=prefix)

    closed_rows = _read_csv(closed_path)
    summary_rows = _read_csv(summary_path)
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in closed_rows:
        sym = str(r.get("SYMBOL", "")).strip().upper()
        if sym:
            by_sym[sym].append(r)

    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = sorted(by_sym.keys())

    do_charts = bool(args.charts) and not bool(args.no_charts)
    do_missed = bool(args.missed_moves) and prefix in RL_SYSTEMS
    if bool(args.missed_moves) and prefix not in RL_SYSTEMS:
        print(
            f"[post_run_analysis] --missed-moves ignored for system={prefix} "
            "(RL/DB only in v1).",
            flush=True,
        )

    chart_dir: Optional[Path] = output_dir / f"{prefix}_Charts_{ts}"
    tickers: dict[str, pd.DataFrame] = {}
    if do_charts or do_missed:
        tickers = _load_tickers(symbols, data_dir, workers=min(4, n_workers))

    if do_charts:
        # Prefer path-based ProcessPool charts (each worker loads its CSV).
        # Preload is optional; used only if CSVs missing for some symbols.
        chart_dir = write_system_charts(
            tickers=tickers or None,
            data_dir=data_dir,
            closed_path=closed_path,
            output_dir=output_dir,
            ts=ts,
            prefix=prefix,
            dip_pct=dip,
            band_pct=float(args.band_pct),
            open_path=open_path if open_path.is_file() else None,
            traded_only=True,
            workers=n_workers,
            symbols=symbols,
        )
        if not any(chart_dir.glob("*.png")):
            print("[post_run_analysis] No OHLC charts produced.", flush=True)
            chart_dir = None
    else:
        if chart_dir and not chart_dir.is_dir():
            chart_dir = None
        print("[post_run_analysis] Charts skipped (--no-charts).", flush=True)

    missed_by_sym: Optional[dict[str, list[Any]]] = None
    miss_themes: Optional[list[dict[str, Any]]] = None
    if do_missed:
        try:
            from rl_missed_moves import (
                aggregate_miss_themes,
                events_by_symbol,
                rl_config_from_report,
                scan_missed_moves,
                write_missed_moves_csv,
            )
        except ImportError:
            from stock_analysis.rl_missed_moves import (  # type: ignore
                aggregate_miss_themes,
                events_by_symbol,
                rl_config_from_report,
                scan_missed_moves,
                write_missed_moves_csv,
            )
        report_path = output_dir / f"{prefix}_Report_{ts}.csv"
        cfg = rl_config_from_report(report_path if report_path.is_file() else None)
        spy_df = None
        for spy_name in ("SPY", "spy"):
            if spy_name in tickers:
                spy_df = tickers[spy_name]
                break
        if spy_df is None:
            spy_loaded = _load_tickers(["SPY"], data_dir, workers=1)
            spy_df = spy_loaded.get("SPY")
        print(
            f"[post_run_analysis] Missed-moves scan: {len(symbols)} symbols "
            f"(dip={getattr(cfg, 'rl_dip_pct', dip)}, heuristic!=MarkTen)...",
            flush=True,
        )
        events = scan_missed_moves(
            {s: tickers[s] for s in symbols if s in tickers},
            cfg,
            closed_rows,
            spy_df=spy_df,
            min_fwd_max_gain_pct=float(args.missed_min_gain),
            min_blind_max_gain_pct=float(args.missed_blind_min_gain),
        )
        mm_path = output_dir / f"{prefix}_MissedMoves_{ts}.csv"
        write_missed_moves_csv(events, mm_path)
        missed_by_sym = events_by_symbol(events)
        miss_themes = aggregate_miss_themes(events)
        print(
            f"[post_run_analysis] Wrote {mm_path.name} "
            f"({len(events)} events; {len(miss_themes)} themes)",
            flush=True,
        )

    assess_path = output_dir / f"{prefix}_SymbolAssessments_{ts}.html"
    write_symbol_assessments_html(
        path=assess_path,
        ts=ts,
        prefix=prefix,
        dip_pct=dip,
        summary_rows=summary_rows,
        closed_by_sym=by_sym,
        symbols=symbols,
        chart_dir=chart_dir,
        missed_by_sym=missed_by_sym,
    )
    print(f"[post_run_analysis] Wrote {assess_path.name}", flush=True)

    prio_path = output_dir / f"{prefix}_ImprovePriority_{ts}.html"
    write_improve_priority_html(
        path=prio_path,
        ts=ts,
        prefix=prefix,
        closed_rows=closed_rows,
        miss_themes=miss_themes,
        drive_dir=output_dir,
        data_dir=Path(args.data_dir) if args.data_dir else None,
    )
    print(f"[post_run_analysis] Wrote {prio_path.name}", flush=True)

    write_improve_hints(
        closed_path,
        output_dir,
        ts,
        prefix=prefix,
        drive_dir=output_dir,
        data_dir=Path(args.data_dir) if args.data_dir else None,
    )
    return 0


if __name__ == "__main__":
    # Windows ProcessPoolExecutor requires this guard.
    raise SystemExit(main())
