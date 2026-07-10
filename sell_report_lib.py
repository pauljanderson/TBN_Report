"""
Pending exit alerts for BRT/IND open positions (next session at open).

Primary rule: sell_on_low_vol — exit at the first bar after entry when
REL_VOL_AT_ENTRY (entry-day volume / 10d avg) is below the audit threshold.
At EOD on the entry date, flag positions that will trigger on the next open.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "newdata" / "data"

_AUDIT_TS_RE = re.compile(r"^(?P<prefix>BRT|IND)_Audit_Report_(?P<ts>\d{12})\.csv$", re.I)
_OPEN_TS_RE = re.compile(r"^(?P<prefix>BRT|IND)_Open_(?P<ts>\d{12})\.csv$", re.I)


@dataclass
class PendingLowVolSell:
    symbol: str
    system: str
    entry_date: date
    as_of_date: date
    rel_vol_at_entry: float
    sell_on_low_vol: float
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    rel_vol_source: str = ""

    @property
    def exit_reason(self) -> str:
        return "LOW_REL_VOL_EXIT"

    @property
    def sell_when(self) -> str:
        return "Next session open"


def _parse_trade_date(raw) -> Optional[date]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    if re.fullmatch(r"\d{8}", s):
        return datetime.strptime(s, "%Y%m%d").date()
    try:
        return pd.to_datetime(s).date()
    except (TypeError, ValueError):
        return None


def _latest_audit_path(drive_dir: Path, prefix: str) -> Optional[Path]:
    pfx = prefix.upper()
    best: Optional[tuple[str, float, Path]] = None
    for path in drive_dir.glob(f"{pfx}_Audit_Report_*.csv"):
        if "_RL_" in path.name.upper():
            continue
        m = _AUDIT_TS_RE.match(path.name)
        if m and m.group("prefix").upper() == pfx:
            cand = (m.group("ts"), path.stat().st_mtime, path)
            if best is None or cand[0] > best[0]:
                best = cand
    return best[2] if best else None


def load_sell_on_low_vol_thresholds(
    drive_dir: Path,
    *,
    overrides: Optional[dict[str, float]] = None,
) -> dict[str, float]:
    """Per-system sell_on_low_vol from latest audit (0 = disabled)."""
    out: dict[str, float] = {}
    for prefix in ("IND", "BRT"):
        if overrides and prefix in overrides:
            out[prefix] = float(overrides[prefix])
            continue
        path = _latest_audit_path(drive_dir, prefix)
        if not path:
            out[prefix] = 0.0
            continue
        try:
            df = pd.read_csv(path, nrows=1)
            if "sell_on_low_vol" not in df.columns:
                out[prefix] = 0.0
            else:
                out[prefix] = float(df["sell_on_low_vol"].iloc[0] or 0.0)
        except (OSError, ValueError, TypeError):
            out[prefix] = 0.0
    return out


def _latest_open_path(drive_dir: Path, prefix: str) -> Optional[Path]:
    pfx = prefix.upper()
    best: Optional[tuple[str, Path]] = None
    for path in drive_dir.glob(f"{pfx}_Open_*.csv"):
        m = _OPEN_TS_RE.match(path.name)
        if m and m.group("prefix").upper() == pfx:
            ts = m.group("ts")
            if best is None or ts > best[0]:
                best = (ts, path)
    return best[1] if best else None


def load_open_rel_vol_lookup(drive_dir: Path, prefix: str) -> dict[tuple[str, date], float]:
    """(symbol, entry_date) -> REL_VOL_AT_ENTRY from latest Open CSV."""
    path = _latest_open_path(drive_dir, prefix)
    if not path or not path.is_file():
        return {}
    try:
        df = pd.read_csv(path)
    except OSError:
        return {}
    if df.empty or "SYMBOL" not in df.columns:
        return {}
    out: dict[tuple[str, date], float] = {}
    for _, r in df.iterrows():
        sym = str(r.get("SYMBOL", "")).strip().upper()
        if not sym:
            continue
        ed = _parse_trade_date(r.get("DATE_OPENED"))
        if ed is None:
            continue
        rv = r.get("REL_VOL_AT_ENTRY")
        if rv is None or (isinstance(rv, float) and pd.isna(rv)):
            continue
        try:
            out[(sym, ed)] = float(rv)
        except (TypeError, ValueError):
            continue
    return out


def rel_vol_from_ohlcv(data_dir: Path, symbol: str, entry_date: date) -> Optional[float]:
    """Entry-day volume / mean(prior 9 sessions + entry day), matching rocket_brt entry bar."""
    path = data_dir / f"{symbol.upper()}.csv"
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
        df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce")
        df = df.dropna(subset=["Date", "Volume"]).sort_values("Date")
    except OSError:
        return None
    row = df[df["Date"] == entry_date]
    if row.empty:
        return None
    idx = df.index.get_loc(row.index[-1])
    if isinstance(idx, slice):
        idx = idx.start
    start = max(0, int(idx) - 9)
    sl = df["Volume"].iloc[start : int(idx) + 1]
    if sl.empty:
        return None
    avg = float(sl.mean())
    vol = float(row["Volume"].iloc[-1])
    if not avg or avg <= 0:
        return None
    return vol / avg


def _resolve_as_of_date(gettarget_path: Path, explicit: Optional[date]) -> date:
    if explicit is not None:
        return explicit
    if gettarget_path.is_file():
        try:
            df = pd.read_csv(gettarget_path, nrows=5)
            if "AsOfDate" in df.columns:
                s = pd.to_datetime(df["AsOfDate"], errors="coerce").dropna()
                if not s.empty:
                    return s.iloc[0].date()
        except OSError:
            pass
    return date.today()


def _load_open_csv_positions(
    drive_dir: Path, prefix: str
) -> list[tuple[str, date, Optional[float], Optional[float], Optional[float]]]:
    """symbol, entry_date, rel_vol, entry_price, current_price from latest Open CSV."""
    path = _latest_open_path(drive_dir, prefix)
    if not path or not path.is_file():
        return []
    try:
        df = pd.read_csv(path)
    except OSError:
        return []
    if df.empty or "SYMBOL" not in df.columns:
        return []
    out: list[tuple[str, date, Optional[float], Optional[float], Optional[float]]] = []
    for _, r in df.iterrows():
        sym = str(r.get("SYMBOL", "")).strip().upper()
        if not sym:
            continue
        ed = _parse_trade_date(r.get("DATE_OPENED"))
        if ed is None:
            continue
        rv = None
        try:
            raw_rv = r.get("REL_VOL_AT_ENTRY")
            if raw_rv is not None and not (isinstance(raw_rv, float) and pd.isna(raw_rv)):
                rv = float(raw_rv)
        except (TypeError, ValueError):
            rv = None
        ep = None
        cp = None
        try:
            raw_ep = r.get("ENTRY_PRICE")
            if raw_ep is not None and not (isinstance(raw_ep, float) and pd.isna(raw_ep)):
                ep = float(raw_ep)
        except (TypeError, ValueError):
            ep = None
        try:
            raw_cp = r.get("CURRENT_PRICE")
            if raw_cp is not None and not (isinstance(raw_cp, float) and pd.isna(raw_cp)):
                cp = float(raw_cp)
        except (TypeError, ValueError):
            cp = None
        out.append((sym, ed, rv, ep, cp))
    return out


def find_pending_low_vol_sells(
    *,
    positions_path: Path,
    gettarget_path: Path,
    drive_dir: Path,
    as_of_date: Optional[date] = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    thresholds: Optional[dict[str, float]] = None,
) -> tuple[list[PendingLowVolSell], dict[str, float], date]:
    """
    Open positions (any entry date) whose stored entry-day rel vol is below threshold.
    Matches rocket_brt LOW_REL_VOL_EXIT: sell at next session open after entry when
    REL_VOL_AT_ENTRY < sell_on_low_vol. While still holding, flag for the upcoming open.
    """
    as_of = _resolve_as_of_date(gettarget_path, as_of_date)
    thresh = load_sell_on_low_vol_thresholds(drive_dir, overrides=thresholds)
    rel_lookups = {pfx: load_open_rel_vol_lookup(drive_dir, pfx) for pfx in ("IND", "BRT")}

    gt_rows: dict[tuple[str, str], dict] = {}
    if gettarget_path.is_file():
        gt = pd.read_csv(gettarget_path)
        if not gt.empty:
            gt["Symbol"] = gt["Symbol"].astype(str).str.upper()
            for _, r in gt.iterrows():
                sym = str(r["Symbol"]).strip().upper()
                sys_ = str(r.get("System", "")).strip().upper()
                pd_raw = r.get("PurchaseDate", r.get("EntryDateUsed"))
                pd_d = _parse_trade_date(pd_raw)
                if sym and sys_ and pd_d:
                    gt_rows[(sym, pd_d.isoformat())] = r

    candidates: list[tuple[str, str, date, Optional[float], Optional[float]]] = []
    seen_keys: set[tuple[str, str, date]] = set()

    def _add(sym: str, sys_: str, ed: date, ep: Optional[float], cp: Optional[float]) -> None:
        if not sym or not sys_ or sys_ == "RL" or ed is None:
            return
        key = (sym, sys_, ed)
        if key in seen_keys:
            return
        seen_keys.add(key)
        candidates.append(key + (ep, cp))

    if positions_path.is_file():
        pos = pd.read_csv(positions_path, dtype=str, keep_default_na=False)
        cols = {c.lower(): c for c in pos.columns}
        sym_c = cols.get("symbol", "symbol")
        date_c = cols.get("purchase_date", "purchase_date")
        sys_c = cols.get("system", "system")
        price_c = cols.get("entry_price", "entry_price")
        for _, r in pos.iterrows():
            sym = str(r.get(sym_c, "")).strip().upper()
            sys_ = str(r.get(sys_c, "")).strip().upper()
            ed = _parse_trade_date(r.get(date_c, ""))
            if ed is None:
                continue
            ep = None
            try:
                ep = float(str(r.get(price_c, "")).strip() or 0) or None
            except (TypeError, ValueError):
                ep = None
            _add(sym, sys_, ed, ep, None)

    for (sym, pd_iso), r in gt_rows.items():
        ed = _parse_trade_date(pd_iso)
        if ed is None:
            continue
        sys_ = str(r.get("System", "")).strip().upper()
        ep = float(r["EntryPrice"]) if pd.notna(r.get("EntryPrice")) else None
        cp = float(r["CurrentPrice"]) if pd.notna(r.get("CurrentPrice")) else None
        _add(sym, sys_, ed, ep, cp)

    # Strategy open files: all symbols still open in the latest backtest run.
    for prefix in ("IND", "BRT"):
        if float(thresh.get(prefix, 0.0) or 0.0) <= 0:
            continue
        for sym, ed, _rv, ep, cp in _load_open_csv_positions(drive_dir, prefix):
            _add(sym, prefix, ed, ep, cp)

    pending: list[PendingLowVolSell] = []
    seen: set[tuple[str, str, date]] = set()
    for sym, sys_, ed, ep, cp in candidates:
        if (sym, sys_, ed) in seen:
            continue
        seen.add((sym, sys_, ed))
        thr = float(thresh.get(sys_, 0.0) or 0.0)
        if thr <= 0:
            continue
        rv = rel_lookups.get(sys_, {}).get((sym, ed))
        src = "open_csv"
        if rv is None:
            rv = rel_vol_from_ohlcv(data_dir, sym, ed)
            src = "ohlcv" if rv is not None else ""
        if rv is None:
            continue
        if float(rv) >= thr:
            continue
        if cp is None:
            gt_r = gt_rows.get((sym, ed.isoformat()))
            if gt_r is not None and pd.notna(gt_r.get("CurrentPrice")):
                cp = float(gt_r["CurrentPrice"])
        pending.append(
            PendingLowVolSell(
                symbol=sym,
                system=sys_,
                entry_date=ed,
                as_of_date=as_of,
                rel_vol_at_entry=round(float(rv), 4),
                sell_on_low_vol=thr,
                entry_price=ep,
                current_price=cp,
                rel_vol_source=src,
            )
        )

    pending.sort(key=lambda x: (x.system, x.symbol))
    return pending, thresh, as_of


def pending_sells_to_dataframe(pending: list[PendingLowVolSell]) -> pd.DataFrame:
    if not pending:
        return pd.DataFrame(
            columns=[
                "Symbol",
                "System",
                "EntryDate",
                "AsOfDate",
                "REL_VOL_AT_ENTRY",
                "sell_on_low_vol",
                "ExitReason",
                "SellWhen",
                "EntryPrice",
                "CurrentPrice",
                "RelVolSource",
            ]
        )
    rows = [
        {
            "Symbol": p.symbol,
            "System": p.system,
            "EntryDate": p.entry_date.isoformat(),
            "AsOfDate": p.as_of_date.isoformat(),
            "REL_VOL_AT_ENTRY": p.rel_vol_at_entry,
            "sell_on_low_vol": p.sell_on_low_vol,
            "ExitReason": p.exit_reason,
            "SellWhen": p.sell_when,
            "EntryPrice": p.entry_price,
            "CurrentPrice": p.current_price,
            "RelVolSource": p.rel_vol_source,
        }
        for p in pending
    ]
    return pd.DataFrame(rows)


def write_sell_report_csv(
    pending: list[PendingLowVolSell],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_sells_to_dataframe(pending).to_csv(output_path, index=False)
    return output_path


def format_sell_report_html_rows(
    pending: list[PendingLowVolSell],
) -> tuple[list[list[str]], list[str], list[str]]:
    headers = [
        "Symbol",
        "System",
        "Entry",
        "REL_VOL",
        "Threshold",
        "Exit",
        "When",
        "Entry $",
        "Current $",
    ]
    rows: list[list[str]] = []
    for p in pending:
        rows.append(
            [
                p.symbol,
                p.system,
                p.entry_date.strftime("%m/%d/%Y"),
                f"{p.rel_vol_at_entry:.4f}",
                f"{p.sell_on_low_vol:.4f}",
                p.exit_reason,
                p.sell_when,
                f"${p.entry_price:.2f}" if p.entry_price is not None else "—",
                f"${p.current_price:.2f}" if p.current_price is not None else "—",
            ]
        )
    sort_types = ["text", "text", "date", "num", "num", "text", "text", "num", "num"]
    return rows, headers, sort_types


def sell_report_html_section(
    pending: list[PendingLowVolSell],
    thresholds: dict[str, float],
    as_of: date,
    *,
    html_table_fn,
) -> str:
    """HTML fragment for investment report (html_table_fn = _html_table)."""
    ind_thr = thresholds.get("IND", 0.0)
    brt_thr = thresholds.get("BRT", 0.0)
    thr_note = (
        f"IND sell_on_low_vol={ind_thr:g} · BRT sell_on_low_vol={brt_thr:g} · "
        f"As-of {as_of:%Y-%m-%d}"
    )
    if not pending:
        return f"""
<section>
<h2>Pending sells (next open)</h2>
<p class="small">{thr_note}</p>
<p>No open positions with entry-day relative volume below the low-volume exit threshold.</p>
<p class="small">Rule: exit at the <strong>next session open</strong> when REL_VOL_AT_ENTRY (entry-day volume ÷ 10-day avg) is below sell_on_low_vol. All current holdings are checked, regardless of entry date.</p>
</section>
"""
    rows, headers, sort_types = format_sell_report_html_rows(pending)
    table = html_table_fn(
        headers,
        rows,
        sort_types,
        table_id="pending-sells-table",
    )
    return f"""
<section class="pagebreak" id="pending-sells-section">
<h2>Pending sells (next open)</h2>
<p id="pending-sells-warn" class="small warn">⚠ {len(pending)} open position(s) with low entry-day volume — plan to sell at the <strong>next session open</strong> per backtest rules.</p>
<p class="small">{thr_note}</p>
<div class="table-wrap">{table}</div>
<p class="small">REL_VOL_AT_ENTRY is from the latest Open run or OHLCV when missing. Matches rocket_brt LOW_REL_VOL_EXIT.</p>
</section>
"""
