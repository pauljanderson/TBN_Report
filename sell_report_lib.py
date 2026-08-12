"""
Pending exit alerts for open positions (investment report → Pending sells).

Rules:
  1) BRT/IND sell_on_low_vol — exit next session open when entry-day REL_VOL
     is below the audit threshold.
  2) SB time-based — gold freeze no-FT (3d) / time stop (5d); exit at close
     (or next open if overdue). Fidelity stop/target does not cover these.
  3) VZ time stop — research freeze zone_atr05_ts40 (40 bars); flag when
     approaching (within warn window) or hit. Works when VZ opens exist
     (gettarget / VZ_Open) even before DailyRun wire.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "newdata" / "data"

# Any system prefix with stamped Open/Audit (skip RL twin names in callers).
_AUDIT_TS_RE = re.compile(r"^(?P<prefix>[A-Za-z]+)_Audit_Report_(?P<ts>\d{12})\.csv$", re.I)
_OPEN_TS_RE = re.compile(r"^(?P<prefix>[A-Za-z]+)_Open_(?P<ts>\d{12})\.csv$", re.I)

# SB gold freeze defaults (run_stockbee_burst.bat / sb_baseline).
DEFAULT_SB_TIME_STOP_DAYS = 5
DEFAULT_SB_NO_FT_DAYS = 3
# VZ research freeze zone_atr05_ts40.
DEFAULT_VZ_TIME_STOP_DAYS = 40
DEFAULT_VZ_APPROACH_BARS = 3


@dataclass
class PendingSell:
    symbol: str
    system: str
    entry_date: date
    as_of_date: date
    exit_reason: str
    sell_when: str = "Next session open"
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    days_held: Optional[int] = None
    rel_vol_at_entry: Optional[float] = None
    sell_on_low_vol: Optional[float] = None
    rel_vol_source: str = ""


# Backward-compatible name used by older callers / tests.
PendingLowVolSell = PendingSell


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


def load_sb_time_exit_params(drive_dir: Path) -> tuple[int, int]:
    """(burst_time_stop_days, burst_no_ft_days) from latest SB audit, else gold defaults."""
    time_stop = DEFAULT_SB_TIME_STOP_DAYS
    no_ft = DEFAULT_SB_NO_FT_DAYS
    path = _latest_audit_path(drive_dir, "SB")
    if not path:
        return time_stop, no_ft
    try:
        df = pd.read_csv(path, nrows=1)
        if "burst_time_stop_days" in df.columns:
            v = df["burst_time_stop_days"].iloc[0]
            if pd.notna(v):
                time_stop = int(float(v))
        if "burst_no_ft_days" in df.columns:
            v = df["burst_no_ft_days"].iloc[0]
            if pd.notna(v):
                no_ft = int(float(v))
    except (OSError, ValueError, TypeError):
        pass
    return time_stop, no_ft


def load_vz_time_exit_params(drive_dir: Path) -> tuple[int, int]:
    """(time_stop_days, approach_warn_bars). Audit override when present; else research freeze."""
    time_stop = DEFAULT_VZ_TIME_STOP_DAYS
    approach = DEFAULT_VZ_APPROACH_BARS
    path = _latest_audit_path(drive_dir, "VZ")
    if path:
        try:
            df = pd.read_csv(path, nrows=1)
            for col in ("vz_time_stop_days", "exit_bars", "time_stop_days"):
                if col in df.columns and pd.notna(df[col].iloc[0]):
                    time_stop = int(float(df[col].iloc[0]))
                    break
        except (OSError, ValueError, TypeError):
            pass
    return time_stop, approach


def _latest_open_path(drive_dir: Path, prefix: str) -> Optional[Path]:
    pfx = prefix.upper()
    best: Optional[tuple[str, Path]] = None
    for path in drive_dir.glob(f"{pfx}_Open_*.csv"):
        if "_RL_" in path.name.upper():
            continue
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


def _collect_open_candidates(
    *,
    positions_path: Path,
    gettarget_path: Path,
    drive_dir: Path,
    open_prefixes: tuple[str, ...] = (),
) -> tuple[
    list[tuple[str, str, date, Optional[float], Optional[float]]],
    dict[tuple[str, str], dict],
]:
    """
    Open lots from gettarget_positions + getTarget + optional *Open* CSVs.
    Returns (candidates, gt_rows keyed by (symbol, entry_iso)).
    """
    gt_rows: dict[tuple[str, str], dict] = {}
    if gettarget_path.is_file():
        gt = pd.read_csv(gettarget_path)
        if not gt.empty and "Symbol" in gt.columns:
            gt["Symbol"] = gt["Symbol"].astype(str).str.upper()
            for _, r in gt.iterrows():
                sym = str(r["Symbol"]).strip().upper()
                sys_ = str(r.get("System", "")).strip().upper()
                pd_raw = r.get("PurchaseDate", r.get("EntryDateUsed"))
                pd_d = _parse_trade_date(pd_raw)
                if sym and sys_ and pd_d:
                    gt_rows[(sym, pd_d.isoformat())] = r.to_dict()

    candidates: list[tuple[str, str, date, Optional[float], Optional[float]]] = []
    seen_keys: set[tuple[str, str, date]] = set()

    def _add(sym: str, sys_: str, ed: date, ep: Optional[float], cp: Optional[float]) -> None:
        if not sym or not sys_ or sys_ == "RL" or ed is None:
            return
        key = (sym, sys_, ed)
        if key in seen_keys:
            return
        seen_keys.add(key)
        candidates.append((sym, sys_, ed, ep, cp))

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
        ep = None
        cp = None
        try:
            if r.get("EntryPrice") is not None and not pd.isna(r.get("EntryPrice")):
                ep = float(r["EntryPrice"])
        except (TypeError, ValueError):
            ep = None
        try:
            if r.get("CurrentPrice") is not None and not pd.isna(r.get("CurrentPrice")):
                cp = float(r["CurrentPrice"])
        except (TypeError, ValueError):
            cp = None
        _add(sym, sys_, ed, ep, cp)

    for prefix in open_prefixes:
        for sym, ed, _rv, ep, cp in _load_open_csv_positions(drive_dir, prefix):
            _add(sym, prefix.upper(), ed, ep, cp)

    return candidates, gt_rows


def _load_ohlcv(data_dir: Path, symbol: str) -> Optional[pd.DataFrame]:
    path = data_dir / f"{symbol.upper()}.csv"
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path)
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    except OSError:
        return None
    return df if not df.empty else None


def bars_held_and_follow_through(
    data_dir: Path,
    symbol: str,
    entry_date: date,
    entry_price: Optional[float],
    as_of: date,
) -> tuple[Optional[int], bool, Optional[float]]:
    """
    Trading-bar held count matching SB engine (i - entry_idx), whether any close
    since entry exceeded entry_price, and last close <= as_of.
    """
    df = _load_ohlcv(data_dir, symbol)
    if df is None:
        return None, False, None
    entry_rows = df.index[df["Date"] == entry_date].tolist()
    if not entry_rows:
        # Broker fill date may miss a session — nearest on/after.
        after = df.index[df["Date"] >= entry_date].tolist()
        if not after:
            return None, False, None
        entry_i = int(after[0])
    else:
        entry_i = int(entry_rows[-1])
    asof_rows = df.index[df["Date"] <= as_of].tolist()
    if not asof_rows:
        return None, False, None
    last_i = int(asof_rows[-1])
    if last_i < entry_i:
        return None, False, None
    held = last_i - entry_i
    last_close = float(df["Close"].iloc[last_i])
    saw_ft = False
    if entry_price is not None and entry_price > 0:
        closes = df["Close"].iloc[entry_i : last_i + 1]
        saw_ft = bool((closes > float(entry_price)).any())
    return held, saw_ft, last_close


def _sell_when_for_bar_exit(held: int, trigger_days: int) -> str:
    if held > trigger_days:
        return "Next session open (overdue)"
    return "At close"


def find_pending_low_vol_sells(
    *,
    positions_path: Path,
    gettarget_path: Path,
    drive_dir: Path,
    as_of_date: Optional[date] = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    thresholds: Optional[dict[str, float]] = None,
) -> tuple[list[PendingSell], dict[str, float], date]:
    """
    Open positions (any entry date) whose stored entry-day rel vol is below threshold.
    Matches rocket_brt LOW_REL_VOL_EXIT: sell at next session open after entry when
    REL_VOL_AT_ENTRY < sell_on_low_vol. While still holding, flag for the upcoming open.
    """
    as_of = _resolve_as_of_date(gettarget_path, as_of_date)
    thresh = load_sell_on_low_vol_thresholds(drive_dir, overrides=thresholds)
    rel_lookups = {pfx: load_open_rel_vol_lookup(drive_dir, pfx) for pfx in ("IND", "BRT")}

    open_prefixes = tuple(
        pfx for pfx in ("IND", "BRT") if float(thresh.get(pfx, 0.0) or 0.0) > 0
    )
    candidates, gt_rows = _collect_open_candidates(
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        drive_dir=drive_dir,
        open_prefixes=open_prefixes,
    )

    pending: list[PendingSell] = []
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
            if gt_r is not None:
                try:
                    raw_cp = gt_r.get("CurrentPrice")
                    if raw_cp is not None and not pd.isna(raw_cp):
                        cp = float(raw_cp)
                except (TypeError, ValueError):
                    pass
        pending.append(
            PendingSell(
                symbol=sym,
                system=sys_,
                entry_date=ed,
                as_of_date=as_of,
                exit_reason="LOW_REL_VOL_EXIT",
                sell_when="Next session open",
                entry_price=ep,
                current_price=cp,
                rel_vol_at_entry=round(float(rv), 4),
                sell_on_low_vol=thr,
                rel_vol_source=src,
            )
        )

    pending.sort(key=lambda x: (x.system, x.symbol))
    return pending, thresh, as_of


def find_pending_time_based_sells(
    *,
    positions_path: Path,
    gettarget_path: Path,
    drive_dir: Path,
    as_of_date: Optional[date] = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    sb_time_stop_days: Optional[int] = None,
    sb_no_ft_days: Optional[int] = None,
    vz_time_stop_days: Optional[int] = None,
    vz_approach_bars: Optional[int] = None,
) -> tuple[list[PendingSell], dict[str, int], date]:
    """
    SB: flag when no-FT or time-stop bar count is reached (engine close exits).
    VZ: flag when within approach window of 40d time stop, or hit/overdue.
    """
    as_of = _resolve_as_of_date(gettarget_path, as_of_date)
    audit_ts, audit_nft = load_sb_time_exit_params(drive_dir)
    time_stop = int(sb_time_stop_days if sb_time_stop_days is not None else audit_ts)
    no_ft = int(sb_no_ft_days if sb_no_ft_days is not None else audit_nft)
    vz_ts_audit, vz_ap_audit = load_vz_time_exit_params(drive_dir)
    vz_ts = int(vz_time_stop_days if vz_time_stop_days is not None else vz_ts_audit)
    vz_ap = int(vz_approach_bars if vz_approach_bars is not None else vz_ap_audit)

    params = {
        "sb_time_stop_days": time_stop,
        "sb_no_ft_days": no_ft,
        "vz_time_stop_days": vz_ts,
        "vz_approach_bars": vz_ap,
    }

    candidates, gt_rows = _collect_open_candidates(
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        drive_dir=drive_dir,
        open_prefixes=("SB", "VZ"),
    )

    pending: list[PendingSell] = []
    seen: set[tuple[str, str, date, str]] = set()

    for sym, sys_, ed, ep, cp in candidates:
        if sys_ not in ("SB", "VZ"):
            continue
        if ep is None:
            gt_r = gt_rows.get((sym, ed.isoformat()))
            if gt_r is not None:
                try:
                    raw_ep = gt_r.get("EntryPrice")
                    if raw_ep is not None and not pd.isna(raw_ep):
                        ep = float(raw_ep)
                except (TypeError, ValueError):
                    pass
        held, saw_ft, last_close = bars_held_and_follow_through(
            data_dir, sym, ed, ep, as_of
        )
        if held is None:
            continue
        if cp is None:
            cp = last_close
            gt_r = gt_rows.get((sym, ed.isoformat()))
            if gt_r is not None:
                try:
                    raw_cp = gt_r.get("CurrentPrice")
                    if raw_cp is not None and not pd.isna(raw_cp):
                        cp = float(raw_cp)
                except (TypeError, ValueError):
                    pass

        reason = ""
        sell_when = ""
        if sys_ == "SB":
            # Match engine priority: NO_FT before TIME.
            if no_ft > 0 and held >= no_ft and not saw_ft:
                reason = f"SB no follow-through ({no_ft}d)"
                sell_when = _sell_when_for_bar_exit(held, no_ft)
            elif time_stop > 0 and held >= time_stop:
                reason = f"SB time stop ({time_stop}d)"
                sell_when = _sell_when_for_bar_exit(held, time_stop)
        elif sys_ == "VZ" and vz_ts > 0:
            if held >= vz_ts:
                reason = f"VZ time stop ({vz_ts}d)"
                sell_when = _sell_when_for_bar_exit(held, vz_ts)
            elif vz_ap > 0 and held >= max(0, vz_ts - vz_ap):
                left = vz_ts - held
                reason = f"VZ time stop approaching ({held}/{vz_ts}d)"
                sell_when = f"Plan exit by day {vz_ts} close ({left}d left)"

        if not reason:
            continue
        dedupe = (sym, sys_, ed, reason)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        pending.append(
            PendingSell(
                symbol=sym,
                system=sys_,
                entry_date=ed,
                as_of_date=as_of,
                exit_reason=reason,
                sell_when=sell_when,
                entry_price=ep,
                current_price=cp,
                days_held=held,
            )
        )

    pending.sort(key=lambda x: (x.system, x.symbol, x.exit_reason))
    return pending, params, as_of


def find_all_pending_sells(
    *,
    positions_path: Path,
    gettarget_path: Path,
    drive_dir: Path,
    as_of_date: Optional[date] = None,
    data_dir: Path = DEFAULT_DATA_DIR,
    thresholds: Optional[dict[str, float]] = None,
) -> tuple[list[PendingSell], dict[str, float], dict[str, int], date]:
    """Merge low-vol + time-based pending sells (dedupe by symbol/system/entry/reason)."""
    low_vol, thresh, as_of = find_pending_low_vol_sells(
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        drive_dir=drive_dir,
        as_of_date=as_of_date,
        data_dir=data_dir,
        thresholds=thresholds,
    )
    timed, time_params, as_of2 = find_pending_time_based_sells(
        positions_path=positions_path,
        gettarget_path=gettarget_path,
        drive_dir=drive_dir,
        as_of_date=as_of_date or as_of,
        data_dir=data_dir,
    )
    as_of = as_of_date or as_of2 or as_of
    pending = list(low_vol)
    seen = {(p.symbol, p.system, p.entry_date, p.exit_reason) for p in pending}
    for p in timed:
        key = (p.symbol, p.system, p.entry_date, p.exit_reason)
        if key in seen:
            continue
        seen.add(key)
        pending.append(p)
    pending.sort(key=lambda x: (x.system, x.symbol, x.exit_reason))
    return pending, thresh, time_params, as_of


def pending_sells_to_dataframe(pending: list[PendingSell]) -> pd.DataFrame:
    cols = [
        "Symbol",
        "System",
        "EntryDate",
        "AsOfDate",
        "DaysHeld",
        "ExitReason",
        "SellWhen",
        "EntryPrice",
        "CurrentPrice",
        "REL_VOL_AT_ENTRY",
        "sell_on_low_vol",
        "RelVolSource",
    ]
    if not pending:
        return pd.DataFrame(columns=cols)
    rows = [
        {
            "Symbol": p.symbol,
            "System": p.system,
            "EntryDate": p.entry_date.isoformat(),
            "AsOfDate": p.as_of_date.isoformat(),
            "DaysHeld": p.days_held,
            "ExitReason": p.exit_reason,
            "SellWhen": p.sell_when,
            "EntryPrice": p.entry_price,
            "CurrentPrice": p.current_price,
            "REL_VOL_AT_ENTRY": p.rel_vol_at_entry,
            "sell_on_low_vol": p.sell_on_low_vol,
            "RelVolSource": p.rel_vol_source,
        }
        for p in pending
    ]
    return pd.DataFrame(rows)


def write_sell_report_csv(
    pending: list[PendingSell],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_sells_to_dataframe(pending).to_csv(output_path, index=False)
    return output_path


def format_sell_report_html_rows(
    pending: list[PendingSell],
) -> tuple[list[list[str]], list[str], list[str]]:
    headers = [
        "Symbol",
        "System",
        "Entry",
        "Days held",
        "Exit reason",
        "When",
        "Entry $",
        "Current $",
        "REL_VOL",
    ]
    rows: list[list[str]] = []
    for p in pending:
        rows.append(
            [
                p.symbol,
                p.system,
                p.entry_date.strftime("%m/%d/%Y"),
                str(p.days_held) if p.days_held is not None else "—",
                p.exit_reason,
                p.sell_when,
                f"${p.entry_price:.2f}" if p.entry_price is not None else "—",
                f"${p.current_price:.2f}" if p.current_price is not None else "—",
                f"{p.rel_vol_at_entry:.4f}" if p.rel_vol_at_entry is not None else "—",
            ]
        )
    sort_types = ["text", "text", "date", "num", "text", "text", "num", "num", "num"]
    return rows, headers, sort_types


def sell_report_html_section(
    pending: list[PendingSell],
    thresholds: dict[str, float],
    as_of: date,
    *,
    html_table_fn,
    time_params: Optional[dict[str, int]] = None,
) -> str:
    """HTML fragment for investment report (html_table_fn = _html_table)."""
    ind_thr = thresholds.get("IND", 0.0)
    brt_thr = thresholds.get("BRT", 0.0)
    tp = time_params or {}
    sb_ts = tp.get("sb_time_stop_days", DEFAULT_SB_TIME_STOP_DAYS)
    sb_nft = tp.get("sb_no_ft_days", DEFAULT_SB_NO_FT_DAYS)
    vz_ts = tp.get("vz_time_stop_days", DEFAULT_VZ_TIME_STOP_DAYS)
    thr_note = (
        f"IND/BRT sell_on_low_vol={ind_thr:g}/{brt_thr:g} · "
        f"SB no-FT={sb_nft}d / time={sb_ts}d · VZ time={vz_ts}d · "
        f"As-of {as_of:%Y-%m-%d}"
    )
    rule_note = (
        "Fidelity stop/target covers price exits. Time-based exits "
        "(SB no-FT / SB time stop / VZ 40d) are <strong>not</strong> in the broker ticket — "
        "watch this section after each DailyRun / investment report refresh. "
        "Low-vol BRT/IND exits: next session open when REL_VOL_AT_ENTRY &lt; threshold."
    )
    if not pending:
        return f"""
<section>
<h2>Pending sells</h2>
<p class="small">{thr_note}</p>
<p>No open positions currently flagged for low-vol or time-based exits.</p>
<p class="small">{rule_note}</p>
</section>
"""
    rows, headers, sort_types = format_sell_report_html_rows(pending)
    table = html_table_fn(
        headers,
        rows,
        sort_types,
        table_id="pending-sells-table",
    )
    n = len(pending)
    return f"""
<section class="pagebreak" id="pending-sells-section">
<h2>Pending sells</h2>
<p id="pending-sells-warn" class="small warn">⚠ {n} open position(s) need a manual sell action — see Exit reason / When (Fidelity stop/target alone is not enough for time exits).</p>
<p class="small">{thr_note}</p>
<div class="table-wrap">{table}</div>
<p class="small">{rule_note} Click column headers to sort.</p>
</section>
"""
