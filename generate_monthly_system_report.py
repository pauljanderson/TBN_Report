#!/usr/bin/env python3
"""
Monthly backtest P&L by trading system (BRT / IND (deprecated) / RL / YH / MTS / WPBR).

Uses paper-trading outputs from the latest engine runs:
  Drive/{BRT,IND,YH,MTS,WPBR}_LatestRun_Closed.csv / _Open.csv
  Drive/BRT_Closed_RL_<ts>.csv / BRT_Open_RL_<ts>.csv (newest RL mirror)

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
SYSTEMS = ("BRT", "IND", "RL", "YH", "MTS", "WPBR")
SYSTEM_LABELS = {"IND": "IND (deprecated)"}
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


def _fmt_money_plain(v: float) -> str:
    return f"${v:,.0f}"


def _fmt_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _pnl_class(v: float) -> str:
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return ""


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
    for sys in ("BRT", "IND", "YH", "MTS", "WPBR"):
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
                    exit_type=str(r.get(exit_type_c, "")).strip() if exit_type_c else "",
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
                exit_type=str(r.get(exit_type_c, "")).strip() if exit_type_c else "",
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


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  var MONTHS = {
    january:1, february:2, march:3, april:4, may:5, june:6,
    july:7, august:8, september:9, october:10, november:11, december:12
  };
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "month") {
      var key = s.toLowerCase().split(/\\s/)[0];
      return MONTHS[key] || 0;
    }
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      var mdy = s.match(/(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})/);
      if (mdy) return parseInt(mdy[3] + mdy[1].padStart(2, "0") + mdy[2].padStart(2, "0"), 10);
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
  function bindSortHeader(table, th, col) {
    function onActivate(e) {
      if (e.type === "touchend") e.preventDefault();
      var type = th.dataset.sort || "text";
      var dir = th.dataset.dir === "asc" ? -1 : 1;
      table.querySelectorAll("th.sortable-th").forEach(function (h) {
        h.dataset.dir = "";
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
      th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
      sortTable(table, col, type, dir);
    }
    th.addEventListener("click", onActivate);
    th.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


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
            f"<td>{html_mod.escape(t.symbol)}</td>"
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
            f"<td>{html_mod.escape(t.symbol)}</td>"
            f"<td>{t.date_opened.strftime('%Y-%m-%d')}</td>"
            f"<td>{_fmt_money_plain(t.entry_price)}</td>"
            f"<td>{_fmt_money_plain(t.exit_price or 0.0)}</td>"
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

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monthly Backtest Report — {year}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1200px; }}
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
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; min-width:640px; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.6; }}
</style></head><body>
<h1>Monthly Backtest Report — {year}</h1>
<p class="sub">
  Paper-trading P&amp;L from latest {SYSTEMS_LABEL} backtest runs (not live broker accounts).<br>
  Closed trades grouped by <strong>exit month</strong>. Open positions show mark-to-market unrealized P&amp;L.<br>
  Generated {html_mod.escape(gen_s)}.
</p>
<div class="cards">{cards}</div>

<section>
<h2>Monthly realized P&amp;L by system</h2>
<p class="small">Each cell is backtest P&amp;L for trades closed that month. Dollar amounts use each engine's position sizing. Click column headers to sort.</p>
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
