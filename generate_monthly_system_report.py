#!/usr/bin/env python3
"""
Monthly backtest P&L by trading system (BRT / IND (deprecated) / RL / YH / MTS / WPBR / RS / SB / VZ / RSI).

Uses paper-trading Closed/Open CSVs pinned to production stamps (same policy as investment.html):
  - BRT / IND / YH / MTS / WPBR / RS / SB: max stamped Closed/Open on Drive (DailyRun production)
  - VZ: DualPaul78 house only — VZ_house_last_run_ts.txt / house-sized Summary (never ALL / research)
  - RSI: Relative Strength Index house only — RSI_house_last_run_ts.txt (not RS vs SPY)
  - WRL: {PREFIX}_last_run_ts.txt when present, else LatestRun
  - RL: newest BRT_Closed_RL_<ts>.csv / BRT_Open_RL_<ts>.csv mirror (not RL_LatestRun)
  - MVCP: retired 2026-08-21 — omitted from this report (historical Closed stamps retained on Drive)

Falls back to {SYS}_LatestRun_Closed.csv / _Open.csv when no pin resolves.

Writes:
  Drive/Monthly_System_Report_<stamp>.html
  Drive/Monthly_System_Report_Latest.html
"""
from __future__ import annotations

import argparse
import html as html_mod
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
DRIVE = ROOT / "Drive"
ET = ZoneInfo("America/New_York")
SYSTEMS = ("BRT", "IND", "RL", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL")

try:
    from stock_analysis.live_style_sizing import (
        official_live_style_callout_html as _live_style_callout,
        parse_live_style_month_ledger as _live_style_months,
        load_freeze_summary as _live_style_summary,
        NAME_CAP_FRAC as _LIVE_NAME_CAP,
        ACCOUNT_START as _LIVE_START,
        FREEZE_STAMP as _LIVE_STAMP,
        TABLE_UNCAP_CSS as _TABLE_UNCAP_CSS,
    )
except Exception:
    try:
        import sys

        sys.path.insert(0, str(ROOT / "stock_analysis"))
        from live_style_sizing import (  # type: ignore
            official_live_style_callout_html as _live_style_callout,
            parse_live_style_month_ledger as _live_style_months,
            load_freeze_summary as _live_style_summary,
            NAME_CAP_FRAC as _LIVE_NAME_CAP,
            ACCOUNT_START as _LIVE_START,
            FREEZE_STAMP as _LIVE_STAMP,
            TABLE_UNCAP_CSS as _TABLE_UNCAP_CSS,
        )
    except Exception:
        def _live_style_callout() -> str:
            return ""

        def _live_style_months(_year: int) -> list:
            return []

        def _live_style_summary() -> dict:
            return {}

        _LIVE_NAME_CAP = 0.175
        _LIVE_START = 250_000.0
        _LIVE_STAMP = "risk_1pct_50k_adv_17name_20260917"
        _TABLE_UNCAP_CSS = (
            "body { max-width: none !important; } "
            ".table-wrap { overflow-x: auto !important; -webkit-overflow-scrolling: touch; } "
            "table, table.sortable { width: max-content; min-width: 100%; }"
        )

try:
    from stock_analysis.exit_type_normalize import normalize_exit_type as _normalize_exit_type
except Exception:
    try:
        import sys

        sys.path.insert(0, str(ROOT / "stock_analysis"))
        from exit_type_normalize import normalize_exit_type as _normalize_exit_type
    except Exception:

        def _normalize_exit_type(exit_type: str | None) -> str:
            return (exit_type or "").strip().upper()
SYSTEM_LABELS = {
    "IND": "IND (deprecated)",
    "SB": "SB",
    "VZ": "VZ",
    "RSI": "RSI",
    "WRL": "WRL",
}
SYSTEMS_LABEL = " / ".join(SYSTEM_LABELS.get(sys, sys) for sys in SYSTEMS)
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
RL_MIRROR_RE = re.compile(r"^BRT_Closed_RL_(?P<ts>\d{12})\.csv$", re.I)


@dataclass
class TradeRow:
    system: str
    symbol: str
    date_opened: date
    date_closed: Optional[date]
    entry_price: float
    exit_price: Optional[float]
    exit_type: str
    days_held: int
    pnl_dollars: float
    pnl_pct: float
    status: str  # closed | open


def _resolve_drive(drive: Path) -> Path:
    d = drive.resolve()
    if d.is_dir():
        return d
    alt = ROOT / "drive"
    if alt.is_dir():
        return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {drive}")


def _parse_yyyymmdd(raw) -> Optional[date]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = s.replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _parse_money(raw) -> float:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 0.0
    s = str(raw).strip().replace("$", "").replace(",", "")
    if not s or s.lower() in {"nan", "none"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_pct(raw) -> float:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 0.0
    s = str(raw).strip().replace("%", "").replace(",", "")
    if not s or s.lower() in {"nan", "none"}:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_int(raw) -> int:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 0
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none"}:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _fmt_money(v: float) -> str:
    sign = "+" if v >= 0 else "-"
    return f"{sign}${abs(v):,.0f}"


def _fmt_price(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _pnl_class(v: float) -> str:
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return ""


def _read_engine_last_run_ts(prefix: str, drive: Path) -> Optional[str]:
    """12-digit yyMMddHHmmss from drive/{PREFIX}_last_run_ts.txt, if present."""
    path = drive / f"{prefix.upper()}_last_run_ts.txt"
    if not path.is_file():
        return None
    try:
        ts = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return None
    return ts if re.fullmatch(r"\d{12}", ts) else None


def _production_run_stamp(prefix: str, drive: Path) -> Optional[str]:
    """Production/house stamp per system — mirrors generate_investment_report._latest_run_timestamp."""
    pfx = prefix.upper()
    if pfx == "RL":
        return None
    try:
        from generate_investment_report import _latest_run_timestamp

        ts = _latest_run_timestamp(pfx, drive)
        if ts:
            return ts
    except Exception:
        pass
    return _read_engine_last_run_ts(pfx, drive)


def _stamped_paths(prefix: str, drive: Path, ts: str) -> tuple[Optional[Path], Optional[Path]]:
    aliases = [prefix.upper()]
    if prefix.upper() == "WPBR":
        aliases.append("PBR")
    closed: Optional[Path] = None
    open_p: Optional[Path] = None
    for alias in aliases:
        c = drive / f"{alias}_Closed_{ts}.csv"
        o = drive / f"{alias}_Open_{ts}.csv"
        if c.is_file():
            closed = c
        if o.is_file():
            open_p = o
        if closed is not None:
            break
    return closed, open_p


def _newest_rl_mirror_paths(drive: Path) -> tuple[Optional[Path], Optional[Path]]:
    best_ts = ""
    closed: Optional[Path] = None
    for path in drive.glob("BRT_Closed_RL_*.csv"):
        m = RL_MIRROR_RE.match(path.name)
        if not m:
            continue
        ts = m.group("ts")
        if ts > best_ts:
            best_ts = ts
            closed = path
    if closed is None:
        return None, None
    open_path = drive / f"BRT_Open_RL_{best_ts}.csv"
    return closed, open_path if open_path.is_file() else None


def _resolve_system_paths(drive: Path) -> dict[str, dict[str, Optional[Path]]]:
    paths: dict[str, dict[str, Optional[Path]]] = {
        sys: {"closed": None, "open": None} for sys in SYSTEMS
    }
    for sys in ("BRT", "IND", "YH", "MTS", "WPBR", "RS", "SB", "VZ", "RSI", "WRL"):
        closed: Optional[Path] = None
        open_p: Optional[Path] = None
        run_ts = _production_run_stamp(sys, drive)
        if run_ts:
            closed, open_p = _stamped_paths(sys, drive, run_ts)
        if closed is None:
            closed = drive / f"{sys}_LatestRun_Closed.csv"
            open_p = drive / f"{sys}_LatestRun_Open.csv"
            if sys == "WPBR" and not closed.is_file():
                # Legacy copy-latest / outputs before PBR→WPBR rename
                closed = drive / "PBR_LatestRun_Closed.csv"
                open_p = drive / "PBR_LatestRun_Open.csv"
        paths[sys]["closed"] = closed if closed.is_file() else None
        paths[sys]["open"] = open_p if open_p.is_file() else None

    rl_closed, rl_open = _newest_rl_mirror_paths(drive)
    paths["RL"]["closed"] = rl_closed
    paths["RL"]["open"] = rl_open
    if rl_closed is None:
        fallback = drive / "RL_LatestRun_Closed.csv"
        if fallback.is_file():
            paths["RL"]["closed"] = fallback
    if rl_open is None:
        fallback = drive / "RL_LatestRun_Open.csv"
        if fallback.is_file():
            paths["RL"]["open"] = fallback
    return paths


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    upper = {c.upper(): c for c in df.columns}
    for name in names:
        if name.upper() in upper:
            return upper[name.upper()]
    return None


def _load_brt_style(path: Path, system: str, *, status: str) -> list[TradeRow]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    sym_c = _col(df, "SYMBOL")
    opened_c = _col(df, "DATE_OPENED")
    entry_c = _col(df, "ENTRY_PRICE")
    if not sym_c or not opened_c or not entry_c:
        return []

    closed_c = _col(df, "DATE_CLOSED")
    exit_c = _col(df, "EXIT_PRICE")
    exit_type_c = _col(df, "EXIT_TYPE")
    days_c = _col(df, "DAYS_HELD")
    pnl_d_c = _col(df, "PNL_DOLLARS")
    pnl_p_c = _col(df, "PNL_PCT")
    current_c = _col(df, "CURRENT_PRICE")

    rows: list[TradeRow] = []
    for _, r in df.iterrows():
        sym = str(r.get(sym_c, "")).strip().upper()
        d_open = _parse_yyyymmdd(r.get(opened_c))
        if not sym or d_open is None:
            continue
        entry = _parse_money(r.get(entry_c))
        if status == "closed":
            d_close = _parse_yyyymmdd(r.get(closed_c)) if closed_c else None
            if d_close is None:
                continue
            rows.append(
                TradeRow(
                    system=system,
                    symbol=sym,
                    date_opened=d_open,
                    date_closed=d_close,
                    entry_price=entry,
                    exit_price=_parse_money(r.get(exit_c)) if exit_c else None,
                    exit_type=_normalize_exit_type(
                        str(r.get(exit_type_c, "")).strip() if exit_type_c else ""
                    ),
                    days_held=_parse_int(r.get(days_c)) if days_c else 0,
                    pnl_dollars=_parse_money(r.get(pnl_d_c)) if pnl_d_c else 0.0,
                    pnl_pct=_parse_pct(r.get(pnl_p_c)) if pnl_p_c else 0.0,
                    status="closed",
                )
            )
        else:
            cur = _parse_money(r.get(current_c)) if current_c else entry
            pnl_d = _parse_money(r.get(pnl_d_c)) if pnl_d_c else 0.0
            pnl_p = _parse_pct(r.get(pnl_p_c)) if pnl_p_c else 0.0
            rows.append(
                TradeRow(
                    system=system,
                    symbol=sym,
                    date_opened=d_open,
                    date_closed=None,
                    entry_price=entry,
                    exit_price=cur,
                    exit_type="OPEN",
                    days_held=_parse_int(r.get(days_c)) if days_c else 0,
                    pnl_dollars=pnl_d,
                    pnl_pct=pnl_p,
                    status="open",
                )
            )
    return rows


def _load_rl_native_closed(path: Path) -> list[TradeRow]:
    df = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    sym_c = _col(df, "SYMBOL")
    opened_c = _col(df, "DATE OPENED")
    entry_c = _col(df, "ENTRY PRICE")
    closed_c = _col(df, "DATE CLOSED")
    exit_c = _col(df, "EXIT PRICE")
    exit_type_c = _col(df, "EXIT TYPE")
    days_c = _col(df, "DAYS HELD")
    pnl_p_c = _col(df, "PNL %")
    if not sym_c or not opened_c or not entry_c or not closed_c:
        return []

    brt_cash = 47_500.0
    rows: list[TradeRow] = []
    for _, r in df.iterrows():
        sym = str(r.get(sym_c, "")).strip().upper()
        d_open = _parse_yyyymmdd(r.get(opened_c))
        d_close = _parse_yyyymmdd(r.get(closed_c))
        if not sym or d_open is None or d_close is None:
            continue
        entry = _parse_money(r.get(entry_c))
        exit_p = _parse_money(r.get(exit_c)) if exit_c else 0.0
        pnl_d = 0.0
        if entry > 0:
            pnl_d = (brt_cash / entry) * (exit_p - entry)
        rows.append(
            TradeRow(
                system="RL",
                symbol=sym,
                date_opened=d_open,
                date_closed=d_close,
                entry_price=entry,
                exit_price=exit_p,
                exit_type=_normalize_exit_type(
                    str(r.get(exit_type_c, "")).strip() if exit_type_c else ""
                ),
                days_held=_parse_int(r.get(days_c)) if days_c else 0,
                pnl_dollars=pnl_d,
                pnl_pct=_parse_pct(r.get(pnl_p_c)) if pnl_p_c else 0.0,
                status="closed",
            )
        )
    return rows


def _load_system_trades(
    paths: dict[str, dict[str, Optional[Path]]],
) -> tuple[list[TradeRow], list[TradeRow], list[str]]:
    closed: list[TradeRow] = []
    open_rows: list[TradeRow] = []
    sources: list[str] = []

    for sys in SYSTEMS:
        cpath = paths[sys]["closed"]
        opath = paths[sys]["open"]
        if cpath is not None:
            sources.append(f"{sys} closed: {cpath.name}")
            if sys == "RL" and "BRT_Closed_RL" not in cpath.name:
                closed.extend(_load_rl_native_closed(cpath))
            else:
                closed.extend(_load_brt_style(cpath, sys, status="closed"))
        else:
            sources.append(f"{sys} closed: (missing)")

        if opath is not None:
            sources.append(f"{sys} open: {opath.name}")
            if sys == "RL" and "BRT_Open_RL" not in opath.name:
                # Native RL open — skip unless mirror exists; RL open mirror preferred
                pass
            else:
                open_rows.extend(_load_brt_style(opath, sys, status="open"))
        else:
            sources.append(f"{sys} open: (missing)")

    return closed, open_rows, sources


def _month_key(d: date) -> tuple[int, int]:
    return d.year, d.month


def _month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


# Published monthly.html lives next to docs/trendlines/index.html (GitHub Pages).
# Chart sections use id="{SYMBOL}" (see tools/gen_trendlines_charts_html.py).
TRENDLINES_CHART_HREF = "trendlines/index.html"


def _symbol_link(symbol: str) -> str:
    """Clickable ticker → trendlines chart anchor (sort still uses cell text)."""
    sym = (symbol or "").strip().upper()
    esc = html_mod.escape(sym)
    frag = html_mod.escape(sym, quote=True)
    return (
        f'<a class="sym" href="{TRENDLINES_CHART_HREF}#{frag}" '
        f'title="Open {esc} trendline chart">{esc}</a>'
    )


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


from report_page_extras import SORTABLE_TABLE_SCRIPT as _SORTABLE_TABLE_SCRIPT
from report_page_extras import SORTABLE_TH_CSS as _SORTABLE_TH_CSS


def _trade_detail_table(trades: list[TradeRow]) -> str:
    if not trades:
        return "<p class=\"small\">No trades.</p>"
    rows = sorted(trades, key=lambda t: (t.date_closed or date.min, t.symbol))
    body = ""
    for t in rows:
        d_close = t.date_closed.strftime("%Y-%m-%d") if t.date_closed else ""
        d_open = t.date_opened.strftime("%Y-%m-%d")
        body += (
            "<tr>"
            f"<td>{_symbol_link(t.symbol)}</td>"
            f"<td>{d_open}</td>"
            f"<td>{d_close}</td>"
            f"<td>{html_mod.escape(t.exit_type)}</td>"
            f"<td>{t.days_held}</td>"
            f"<td class=\"{_pnl_class(t.pnl_pct)}\">{_fmt_pct(t.pnl_pct)}</td>"
            f"<td class=\"{_pnl_class(t.pnl_dollars)}\">{_fmt_money(t.pnl_dollars)}</td>"
            "</tr>"
        )
    head = "".join(
        _sortable_th(label, sort_type)
        for label, sort_type in (
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Closed", "date"),
            ("Exit", "text"),
            ("Days", "num"),
            ("PnL %", "num"),
            ("PnL $", "num"),
        )
    )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>'
        + body
        + "</tbody></table>"
    )


def _open_table(trades: list[TradeRow]) -> str:
    if not trades:
        return "<p class=\"small\">No open positions.</p>"
    rows = sorted(trades, key=lambda t: t.symbol)
    body = ""
    for t in rows:
        body += (
            "<tr>"
            f"<td>{_symbol_link(t.symbol)}</td>"
            f"<td>{t.date_opened.strftime('%Y-%m-%d')}</td>"
            f"<td>{_fmt_price(t.entry_price)}</td>"
            f"<td>{_fmt_price(t.exit_price or 0.0)}</td>"
            f"<td>{t.days_held}</td>"
            f"<td class=\"{_pnl_class(t.pnl_pct)}\">{_fmt_pct(t.pnl_pct)}</td>"
            f"<td class=\"{_pnl_class(t.pnl_dollars)}\">{_fmt_money(t.pnl_dollars)}</td>"
            "</tr>"
        )
    head = "".join(
        _sortable_th(label, sort_type)
        for label, sort_type in (
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Entry", "num"),
            ("Current", "num"),
            ("Days", "num"),
            ("PnL %", "num"),
            ("Unrealized $", "num"),
        )
    )
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>'
        + body
        + "</tbody></table>"
    )


def _live_style_250k_section(year: int) -> str:
    """Official $250k live-style wallet for the report year. Not house dummy Closed."""
    summ = _live_style_summary() or {}
    live = summ.get("live175") or {}
    rows = _live_style_months(year)
    cap_pct = f"{float(_LIVE_NAME_CAP) * 100:.1f}".rstrip("0").rstrip(".")
    start = float(live.get("start") or _LIVE_START)
    asof = live.get("end")
    ye2012 = live.get("eq_2012")
    dd = live.get("max_dd_pct")

    def _m(v: object) -> str:
        try:
            return f"${float(v):,.0f}"
        except (TypeError, ValueError):
            return "—"

    def _p(v: object) -> str:
        try:
            return f"{float(v):.2f}%"
        except (TypeError, ValueError):
            return "—"

    ytd_realized = 0.0
    realized_ok = True
    body = ""
    for r in rows:
        realized = str(r.get("Realized $") or "—")
        eom = str(r.get("EOM equity") or "—")
        bom = str(r.get("BOM equity") or "—")
        wd = str(r.get("Withdrawn $") or "—")
        month = str(r.get("Month") or "—")
        body += (
            f"<tr><td>{html_mod.escape(month)}</td>"
            f"<td>{html_mod.escape(bom)}</td>"
            f"<td>{html_mod.escape(realized)}</td>"
            f"<td>{html_mod.escape(wd)}</td>"
            f"<td>{html_mod.escape(eom)}</td></tr>"
        )
        raw = realized.replace("$", "").replace(",", "").replace("+", "").replace("—", "").strip()
        if raw:
            try:
                ytd_realized += float(raw)
            except ValueError:
                realized_ok = False
        else:
            realized_ok = False
    if not rows:
        body = (
            "<tr><td colspan='5'>Live-style month ledger not on disk — "
            "see <a href='live_style_monthly.html'>wallet monthly</a>.</td></tr>"
        )
    ytd_txt = f"${ytd_realized:,.0f}" if rows and realized_ok else "—"
    head = "".join(
        _sortable_th(label, sort_type)
        for label, sort_type in (
            ("Month", "month"),
            ("BOM equity", "num"),
            ("Realized $", "num"),
            ("Withdrawn $", "num"),
            ("EOM equity", "num"),
        )
    )
    return f"""
<section id="live-style-250k">
<h2>If we started with $250k — official live-style size</h2>
<p class="small">
  Same recipe as Suggested shares: risk = min(1% beginning-of-month equity, $50k),
  shares ≤ 1% ADV20, notional ≤ {cap_pct}% of current equity
  (freeze <code>{html_mod.escape(str(_LIVE_STAMP))}</code>).
  Start {_m(start)}. Path is the official <strong>6-sys</strong> compound wallet
  (SB / RSI / VZ / MTS / RL / WRL; DailyRun wire — not gold).
  Already includes the freeze’s $7,500/mo withdraw + 10.5% margin on borrowed cash —
  not added here as a new wire.
  Leftover 5-sys pin stays on <a href="system_performance.html">historical performance</a>.
  <strong>Does not replace</strong> the house dummy Closed tables below.
  Full ledger: <a href="live_style_monthly.html">live_style_monthly.html</a>
  · compound story: <a href="live_style.html">live_style.html</a>.
</p>
<div class="cards">
  <div class="card">
    <h3>Start</h3>
    <div class="metric">{_m(start)}</div>
    <div class="small">Official 6-sys · SB / RSI / VZ / MTS / RL / WRL · leftover 5-sys pin on system_performance</div>
  </div>
  <div class="card">
    <h3>YE2012</h3>
    <div class="metric">{_m(ye2012)}</div>
    <div class="small">vs SPY {_m(summ.get('spy_2012'))}</div>
  </div>
  <div class="card">
    <h3>As-of equity</h3>
    <div class="metric">{_m(asof)}</div>
    <div class="small">Max DD {_p(dd)} · name cap {cap_pct}%</div>
  </div>
  <div class="card">
    <h3>{year} realized (wallet)</h3>
    <div class="metric">{ytd_txt}</div>
    <div class="small">Sum of live-style month Realized $ · withdraws separate</div>
  </div>
</div>
<p class="small">Click column headers to sort. {year} months from the locked 17.5% wallet ledger.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{head}</tr></thead>
  <tbody>{body}</tbody>
</table>
</div>
</section>
"""


def build_html(
    *,
    year: int,
    closed: list[TradeRow],
    open_rows: list[TradeRow],
    sources: list[str],
    generated: datetime,
) -> str:
    year_closed = [t for t in closed if t.date_closed and t.date_closed.year == year]
    now = generated.astimezone(ET)
    through_month = now.month if now.year == year else 12

    # Monthly aggregates: (year, month, system) -> stats
    monthly: dict[tuple[int, int, str], dict] = {}
    for t in year_closed:
        assert t.date_closed is not None
        key = (*_month_key(t.date_closed), t.system)
        bucket = monthly.setdefault(
            key,
            {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0},
        )
        bucket["pnl"] += t.pnl_dollars
        bucket["trades"] += 1
        if t.pnl_dollars > 0:
            bucket["wins"] += 1
        elif t.pnl_dollars < 0:
            bucket["losses"] += 1

    ytd_by_system: dict[str, dict] = {
        sys: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0} for sys in SYSTEMS
    }
    for t in year_closed:
        ytd_by_system[t.system]["pnl"] += t.pnl_dollars
        ytd_by_system[t.system]["trades"] += 1
        if t.pnl_dollars > 0:
            ytd_by_system[t.system]["wins"] += 1
        elif t.pnl_dollars < 0:
            ytd_by_system[t.system]["losses"] += 1

    open_by_system: dict[str, list[TradeRow]] = {sys: [] for sys in SYSTEMS}
    for t in open_rows:
        open_by_system[t.system].append(t)
    open_totals = {sys: sum(t.pnl_dollars for t in rows) for sys, rows in open_by_system.items()}

    # Summary cards
    cards = ""
    for sys in SYSTEMS:
        sys_label = SYSTEM_LABELS.get(sys, sys)
        ytd = ytd_by_system[sys]
        unreal = open_totals[sys]
        total = ytd["pnl"] + unreal
        win_pct = (100.0 * ytd["wins"] / ytd["trades"]) if ytd["trades"] else 0.0
        cards += f"""
  <div class="card">
    <h3>{sys_label}</h3>
    <div class="metric {_pnl_class(ytd['pnl'])}">{_fmt_money(ytd['pnl'])}</div>
    <div class="small">YTD realized · {ytd['trades']} closed · {win_pct:.0f}% win</div>
    <div class="small">Open unrealized: <span class="{_pnl_class(unreal)}">{_fmt_money(unreal)}</span>
      ({len(open_by_system[sys])} positions)</div>
    <div class="small">Realized + open: <span class="{_pnl_class(total)}">{_fmt_money(total)}</span></div>
  </div>"""

    total_ytd = sum(v["pnl"] for v in ytd_by_system.values())
    total_open = sum(open_totals.values())
    cards += f"""
  <div class="card card-total">
    <h3>All systems</h3>
    <div class="metric {_pnl_class(total_ytd)}">{_fmt_money(total_ytd)}</div>
    <div class="small">YTD realized across {SYSTEMS_LABEL}</div>
    <div class="small">Open unrealized: <span class="{_pnl_class(total_open)}">{_fmt_money(total_open)}</span></div>
    <div class="small">Combined: <span class="{_pnl_class(total_ytd + total_open)}">{_fmt_money(total_ytd + total_open)}</span></div>
  </div>"""

    # Monthly pivot table
    pivot_head = _sortable_th("Month", "month") + "".join(
        _sortable_th(SYSTEM_LABELS.get(sys, sys), "num") for sys in SYSTEMS
    ) + _sortable_th("Total", "num")
    pivot_body = ""
    ytd_month_totals = {sys: 0.0 for sys in SYSTEMS}
    for month in range(1, through_month + 1):
        label = MONTH_NAMES[month - 1]
        cells = []
        row_total = 0.0
        for sys in SYSTEMS:
            stats = monthly.get((year, month, sys), {"pnl": 0.0, "trades": 0})
            pnl = stats["pnl"]
            n = stats["trades"]
            ytd_month_totals[sys] += pnl
            row_total += pnl
            if n:
                cells.append(
                    f'<td class="{_pnl_class(pnl)}">{_fmt_money(pnl)}<br><span class="small">({n} trades)</span></td>'
                )
            else:
                cells.append('<td class="muted">—</td>')
        pivot_body += (
            f"<tr><th>{label}</th>"
            + "".join(cells)
            + f'<td class="{_pnl_class(row_total)}"><strong>{_fmt_money(row_total)}</strong></td></tr>'
        )

    pivot_foot_cells = []
    grand = 0.0
    for sys in SYSTEMS:
        pnl = ytd_month_totals[sys]
        grand += pnl
        pivot_foot_cells.append(f'<td class="{_pnl_class(pnl)}"><strong>{_fmt_money(pnl)}</strong></td>')
    pivot_foot = (
        "<tr class=\"total-row\"><th>YTD</th>"
        + "".join(pivot_foot_cells)
        + f'<td class="{_pnl_class(grand)}"><strong>{_fmt_money(grand)}</strong></td></tr>'
    )

    # Per-month detail sections
    month_sections = ""
    for month in range(1, through_month + 1):
        label = _month_label(year, month)
        month_trades = [
            t
            for t in year_closed
            if t.date_closed and t.date_closed.year == year and t.date_closed.month == month
        ]
        if not month_trades:
            month_sections += f"""
<section class="month-section">
  <h2>{label}</h2>
  <p class="small muted">No closed backtest trades this month.</p>
</section>"""
            continue

        month_total = sum(t.pnl_dollars for t in month_trades)
        sys_blocks = ""
        for sys in SYSTEMS:
            sys_trades = [t for t in month_trades if t.system == sys]
            if not sys_trades:
                continue
            sys_pnl = sum(t.pnl_dollars for t in sys_trades)
            sys_blocks += f"""
  <div class="sys-block">
    <h3>{SYSTEM_LABELS.get(sys, sys)} · <span class="{_pnl_class(sys_pnl)}">{_fmt_money(sys_pnl)}</span> · {len(sys_trades)} closed</h3>
    <div class="table-wrap">{_trade_detail_table(sys_trades)}</div>
  </div>"""
        month_sections += f"""
<section class="month-section">
  <h2>{label} · <span class="{_pnl_class(month_total)}">{_fmt_money(month_total)}</span> total</h2>
  {sys_blocks}
</section>"""

    open_sections = ""
    for sys in SYSTEMS:
        rows = open_by_system[sys]
        if not rows:
            continue
        sys_pnl = open_totals[sys]
        open_sections += f"""
  <div class="sys-block">
    <h3>{SYSTEM_LABELS.get(sys, sys)} · <span class="{_pnl_class(sys_pnl)}">{_fmt_money(sys_pnl)}</span> · {len(rows)} open</h3>
    <div class="table-wrap">{_open_table(rows)}</div>
  </div>"""

    sources_html = "".join(f"<li>{html_mod.escape(s)}</li>" for s in sources)
    gen_s = now.strftime("%Y-%m-%d %H:%M %Z")
    live_section = _live_style_250k_section(year)
    live_callout = _live_style_callout()

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monthly Backtest Report — {year}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:none; width:auto; }}
{_TABLE_UNCAP_CSS}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
h3 {{ font-size:1rem; margin:16px 0 8px; color:#334155; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.cards {{ display:flex; flex-wrap:wrap; gap:12px; margin:16px 0 24px; }}
.card {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:14px 16px; min-width:200px; flex:1 1 220px; }}
.card-total {{ background:#eef2ff; border-color:#c7d2fe; }}
.card h3 {{ margin:0 0 8px; font-size:13px; color:#475569; font-weight:700; }}
.metric {{ font-size:1.35rem; font-weight:700; line-height:1.2; }}
.small {{ font-size:12px; color:#64748b; }}
.muted {{ color:#94a3b8; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
section {{ margin-top:24px; }}
.month-section {{ border-top:1px solid #e2e8f0; padding-top:8px; }}
.sys-block {{ margin:12px 0 20px; }}
.table-wrap {{ overflow-x:auto; overflow-y:visible; -webkit-overflow-scrolling:touch; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:max-content; min-width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; position:relative; z-index:3; pointer-events:auto; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.6; }}
a.sym {{ color:#1d4ed8; text-decoration:none; font-weight:600; }}
a.sym:hover {{ text-decoration:underline; }}
{_SORTABLE_TH_CSS}
</style></head><body>
{live_callout}
<h1>Monthly Backtest Report — {year}</h1>
<p class="sub">
  Paper-trading P&amp;L from latest {SYSTEMS_LABEL} backtest runs (not live broker accounts).<br>
  Closed trades grouped by <strong>exit month</strong>. Open positions show mark-to-market unrealized P&amp;L.<br>
  Tickers link to that symbol’s chart in <a href="{TRENDLINES_CHART_HREF}">Trendlines + VZ charts</a>.<br>
  Dollar tables below are <strong>house dummy Closed reconcile</strong> unless labeled live-style.<br>
  Generated {html_mod.escape(gen_s)}.
</p>
{live_section}
<div class="cards">{cards}</div>

<section>
<h2>Monthly realized P&amp;L by system (house dummy Closed)</h2>
<p class="small">Each cell is backtest P&amp;L for trades closed that month. Dollar amounts use each engine's <strong>house dummy</strong> position sizing for reconcile — not the $250k live-style book above. Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{pivot_head}</tr></thead>
  <tbody>{pivot_body}{pivot_foot}</tbody>
</table>
</div>
</section>

{month_sections}

<section>
<h2>Open positions (unrealized)</h2>
<p class="small">Current backtest open book from latest runs — what each system would show if held through the latest price update.</p>
{open_sections if open_sections else '<p class="small muted">No open positions in latest backtest outputs.</p>'}
</section>

<section>
<h2>Data sources</h2>
<ul class="sources">{sources_html}</ul>
</section>
{_SORTABLE_TABLE_SCRIPT}
</body></html>"""


def build_report(
    drive_dir: Path,
    *,
    year: Optional[int] = None,
    output_path: Optional[Path] = None,
) -> Path:
    drive = _resolve_drive(drive_dir)
    report_year = year or datetime.now(tz=ET).year
    paths = _resolve_system_paths(drive)
    closed, open_rows, sources = _load_system_trades(paths)

    now = datetime.now(tz=ET)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    out = output_path or (drive / f"Monthly_System_Report_{stamp}.html")
    html_text = build_html(
        year=report_year,
        closed=closed,
        open_rows=open_rows,
        sources=sources,
        generated=now,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")

    latest = drive / "Monthly_System_Report_Latest.html"
    shutil.copy2(out, latest)
    return latest


def main() -> int:
    p = argparse.ArgumentParser(description=f"Monthly backtest P&L by system ({SYSTEMS_LABEL})")
    p.add_argument("--drive", type=Path, default=DRIVE)
    p.add_argument("--year", type=int, default=None, help="Calendar year (default: current year ET)")
    p.add_argument("-o", "--output", type=Path, default=None)
    args = p.parse_args()

    out = build_report(args.drive, year=args.year, output_path=args.output)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
