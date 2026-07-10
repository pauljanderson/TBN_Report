"""
Classify IND/BRT scanner candidates at the session open vs entry-open band gates.

Opens are fetched from Yahoo Finance (batch yfinance) — no local CSV / pygetall required.
Long (default): BUY when open <= MAX_ENTRY_OPEN and open >= MIN_ENTRY_OPEN (if set).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
MARKET_OPEN_ET = dt_time(9, 30)
OPEN_POLL_END_ET = dt_time(9, 45)
OPEN_POLL_INTERVAL_SEC = 20

_SCANNER_RE = re.compile(r"^(?P<prefix>BRT|IND)_Scanner_(?P<ts>\d{12})\.csv$", re.I)
_RUN_TS_RE = re.compile(
    r"^(?P<prefix>BRT|IND)_(?:Closed|Open|Watchlist)_(?P<ts>\d{12})\.csv$", re.I
)


@dataclass
class OpenQuote:
    price: Optional[float]
    source: str
    quote_time_et: Optional[datetime] = None
    quote_session: Optional[date] = None


@dataclass
class ScannerOpenRow:
    symbol: str
    signal_date: str
    scanner_close: Optional[float]
    max_entry_open: Optional[float]
    min_entry_open: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    ind_diff: Optional[float]
    ind_score: Optional[float]
    atr_pct_at_trigger: Optional[float]
    atr_pct_at_entry: Optional[float]
    session_open: Optional[float]
    open_source: str
    open_quote_time_et: Optional[str]
    action: str  # BUY | IGNORE
    reason: str


def _market_open_dt(session: date) -> datetime:
    return datetime.combine(session, MARKET_OPEN_ET, tzinfo=ET)


def _is_session_market_open_now(session: date, now_et: datetime) -> bool:
    return now_et >= _market_open_dt(session)


def market_status_message(session: date, now_et: datetime) -> str:
    open_dt = _market_open_dt(session)
    if now_et.date() < session:
        return f"Session {session.isoformat()} is in the future."
    if now_et.date() > session:
        return f"Session {session.isoformat()} is historical (using daily Yahoo bars)."
    if now_et < open_dt:
        return (
            f"Market not open yet for {session.isoformat()} "
            f"(now {now_et.strftime('%H:%M')} ET; opens 09:30 ET)."
        )
    return f"Regular session open for {session.isoformat()} (now {now_et.strftime('%H:%M')} ET)."


def _parse_yyyymmdd(raw) -> Optional[date]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _fmt_date(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def _expected_signal_date(session: date) -> date:
    return (pd.Timestamp(session) - pd.offsets.BDay(1)).date()


def latest_run_timestamp(prefix: str, drive_dir: Path) -> Optional[str]:
    pfx = prefix.upper()
    stamps: set[str] = set()
    for path in drive_dir.glob(f"{pfx}_*.csv"):
        m = _RUN_TS_RE.match(path.name)
        if m and m.group("prefix").upper() == pfx:
            stamps.add(m.group("ts"))
    return max(stamps) if stamps else None


def resolve_scanner_csv(
    drive_dir: Path,
    *,
    prefix: str = "IND",
    run_ts: Optional[str] = None,
    scanner_path: Optional[Path] = None,
) -> tuple[Path, str]:
    if scanner_path is not None:
        p = Path(scanner_path)
        if not p.is_file():
            raise FileNotFoundError(f"Scanner not found: {p}")
        m = _SCANNER_RE.match(p.name)
        ts = m.group("ts") if m else "manual"
        return p, ts
    pfx = prefix.upper()
    if run_ts:
        path = drive_dir / f"{pfx}_Scanner_{run_ts}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"Scanner not found: {path}")
        return path, run_ts
    best: Optional[tuple[str, Path]] = None
    for path in drive_dir.glob(f"{pfx}_Scanner_*.csv"):
        m = _SCANNER_RE.match(path.name)
        if not m or m.group("prefix").upper() != pfx:
            continue
        ts = m.group("ts")
        if best is None or ts > best[0]:
            best = (ts, path)
    if best is None:
        raise FileNotFoundError(f"No {pfx}_Scanner_*.csv in {drive_dir}")
    return best[1], best[0]


def _num(val) -> Optional[float]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def open_from_csv(data_dir: Path, symbol: str, session: date) -> Optional[float]:
    path = data_dir / f"{symbol.upper()}.csv"
    if not path.is_file():
        return None
    try:
        df = pd.read_csv(path, usecols=["Date", "Open"], low_memory=False)
    except ValueError:
        df = pd.read_csv(path, low_memory=False)
        if "Open" not in df.columns:
            return None
        df = df[["Date", "Open"]]
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    row = df[df["Date"] == session]
    if row.empty:
        return None
    v = _num(row.iloc[-1]["Open"])
    return v if v and v > 0 else None


def _yf_open_from_frame(df: pd.DataFrame, symbol: str) -> Optional[float]:
    sym = symbol.upper()
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if sym in df.columns.get_level_values(0):
                col = (sym, "Open")
                if col in df.columns:
                    series = df[col].dropna()
                    if not series.empty:
                        v = float(series.iloc[0])
                        return v if v > 0 and v == v else None
        elif "Open" in df.columns:
            series = df["Open"].dropna()
            if not series.empty:
                v = float(series.iloc[0])
                return v if v > 0 and v == v else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def _yf_first_1m_open_on_session(
    df: pd.DataFrame, symbol: str, session: date
) -> Optional[tuple[float, datetime]]:
    """First 1m bar on ``session`` at or after 09:30 ET. Never uses prior sessions."""
    sym = symbol.upper()
    try:
        if isinstance(df.columns, pd.MultiIndex) and sym not in df.columns.get_level_values(0):
            return None
        sub = df[sym].copy() if isinstance(df.columns, pd.MultiIndex) else df.copy()
        if sub.empty or "Open" not in sub.columns:
            return None
        idx = pd.to_datetime(sub.index)
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        idx_et = idx.tz_convert(ET)
        open_dt = _market_open_dt(session)
        for i in range(len(sub)):
            ts = idx_et[i]
            if ts.date() != session or ts < open_dt:
                continue
            v = float(sub["Open"].iloc[i])
            if v > 0 and v == v:
                return v, ts
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def _empty_quote() -> OpenQuote:
    return OpenQuote(price=None, source="")


def fetch_session_opens_yfinance(
    symbols: list[str],
    session: date,
    *,
    now_et: Optional[datetime] = None,
) -> dict[str, OpenQuote]:
    """
    Batch-fetch session opens from Yahoo (no local CSV).
    Live session (today): only the first 1m bar on ``session`` at/after 09:30 ET.
    Before 09:30 ET: returns no opens (avoids prior-day stale bars).
    Historical session: daily Open for that date.
    """
    syms = [s.strip().upper() for s in symbols if str(s).strip()]
    out: dict[str, OpenQuote] = {s: _empty_quote() for s in syms}
    if not syms:
        return out
    try:
        import yfinance as yf
    except ImportError:
        return out

    now_et = now_et or datetime.now(ET)
    today_et = now_et.date()

    if session == today_et and not _is_session_market_open_now(session, now_et):
        return out

    try:
        if session == today_et:
            raw = yf.download(
                syms,
                period="1d",
                interval="1m",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
            if raw is not None and not raw.empty:
                for sym in syms:
                    hit = _yf_first_1m_open_on_session(raw, sym, session)
                    if hit is not None:
                        px, ts = hit
                        out[sym] = OpenQuote(
                            price=px,
                            source="yfinance_1m",
                            quote_time_et=ts,
                            quote_session=session,
                        )
        else:
            raw = yf.download(
                syms,
                start=session.isoformat(),
                end=(session + timedelta(days=1)).isoformat(),
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=True,
            )
            if raw is not None and not raw.empty:
                qtime = _market_open_dt(session)
                for sym in syms:
                    v = _yf_open_from_frame(raw, sym)
                    if v is not None:
                        out[sym] = OpenQuote(
                            price=v,
                            source="yfinance_daily",
                            quote_time_et=qtime,
                            quote_session=session,
                        )
    except Exception:
        pass
    return out


def _classify_long_open(
    *,
    session_open: Optional[float],
    max_entry_open: Optional[float],
    min_entry_open: Optional[float],
    signal_date: Optional[date],
    session: date,
    require_fresh_signal: bool,
    quote: Optional[OpenQuote] = None,
    now_et: Optional[datetime] = None,
) -> tuple[str, str]:
    now_et = now_et or datetime.now(ET)
    if session == now_et.date() and not _is_session_market_open_now(session, now_et):
        return "IGNORE", "market not open yet (no today open from Yahoo; run after 09:30 ET)"
    if require_fresh_signal and signal_date is not None:
        expected = _expected_signal_date(session)
        if signal_date != expected:
            return "IGNORE", f"stale signal ({_fmt_date(signal_date)}; expected {_fmt_date(expected)})"
    if quote is not None and quote.price is not None:
        if quote.quote_session is not None and quote.quote_session != session:
            qts = (
                quote.quote_time_et.strftime("%Y-%m-%d %H:%M ET")
                if quote.quote_time_et is not None
                else _fmt_date(quote.quote_session)
            )
            return "IGNORE", f"stale quote ({qts}; need {session.isoformat()} open)"
    if session_open is None:
        return "IGNORE", "no session open from Yahoo for this date yet"
    if max_entry_open is None or max_entry_open <= 0:
        return "IGNORE", "missing MAX_ENTRY_OPEN"
    if session_open > max_entry_open + 1e-4:
        return "IGNORE", f"too high (open {session_open:.4f} > max {max_entry_open:.4f})"
    if min_entry_open is not None and min_entry_open > 0 and session_open < min_entry_open - 1e-4:
        return "IGNORE", f"too low (open {session_open:.4f} < min {min_entry_open:.4f})"
    return "BUY", "open within entry band"


def load_scanner_rows(scanner_path: Path) -> pd.DataFrame:
    df = pd.read_csv(scanner_path, dtype=str, keep_default_na=False, low_memory=False)
    if df.empty:
        return df
    cols = {c.upper(): c for c in df.columns}
    if "SYMBOL" not in cols:
        raise ValueError(f"Scanner missing SYMBOL column: {scanner_path}")
    return df


def _quote_time_str(quote: OpenQuote) -> Optional[str]:
    if quote.quote_time_et is not None:
        return quote.quote_time_et.strftime("%Y-%m-%d %H:%M:%S ET")
    if quote.quote_session is not None:
        return f"{quote.quote_session.isoformat()} 09:30:00 ET (daily)"
    return None


def _build_row_from_scanner(
    r: pd.Series,
    cols: dict[str, str],
    *,
    session_date: date,
    quote: OpenQuote,
    require_fresh_signal: bool,
    now_et: Optional[datetime] = None,
) -> Optional[ScannerOpenRow]:
    sym = str(r.get(cols["SYMBOL"], "")).strip().upper()
    if not sym:
        return None
    signal_raw = r.get(cols.get("DATE", ""), "")
    signal_d = _parse_yyyymmdd(signal_raw)
    max_o = _num(r.get(cols.get("MAX_ENTRY_OPEN", ""), None))
    min_o = _num(r.get(cols.get("MIN_ENTRY_OPEN", ""), None))
    opx = quote.price
    action, reason = _classify_long_open(
        session_open=opx,
        max_entry_open=max_o,
        min_entry_open=min_o,
        signal_date=signal_d,
        session=session_date,
        require_fresh_signal=require_fresh_signal,
        quote=quote,
        now_et=now_et,
    )
    return ScannerOpenRow(
        symbol=sym,
        signal_date=str(signal_raw).strip(),
        scanner_close=_num(r.get(cols.get("CLOSE", ""), None)),
        max_entry_open=max_o,
        min_entry_open=min_o,
        stop_loss=_num(r.get(cols.get("STOP_LOSS", ""), None)),
        target=_num(r.get(cols.get("TARGET", ""), None)),
        ind_diff=_num(r.get(cols.get("IND_DIFF", ""), None)),
        ind_score=_num(r.get(cols.get("IND_SCORE", ""), None)),
        atr_pct_at_trigger=_num(r.get(cols.get("ATR_PCT_AT_TRIGGER", ""), None)),
        atr_pct_at_entry=_num(r.get(cols.get("ATR_PCT_AT_ENTRY", ""), None)),
        session_open=opx,
        open_source=quote.source,
        open_quote_time_et=_quote_time_str(quote),
        action=action,
        reason=reason,
    )


def evaluate_scanner_opens(
    scanner_path: Path,
    *,
    session_date: date,
    data_dir: Optional[Path] = None,
    use_csv_fallback: bool = False,
    is_long: bool = True,
    require_fresh_signal: bool = True,
) -> list[ScannerOpenRow]:
    if not is_long:
        raise NotImplementedError("Only long entry-open band is supported today.")
    df = load_scanner_rows(scanner_path)
    cols = {c.upper(): c for c in df.columns}
    symbols = [str(r.get(cols["SYMBOL"], "")).strip().upper() for _, r in df.iterrows()]
    symbols = [s for s in symbols if s]
    now_et = datetime.now(ET)
    yf_opens = fetch_session_opens_yfinance(symbols, session_date, now_et=now_et)
    if use_csv_fallback and data_dir is not None:
        for sym in symbols:
            if yf_opens.get(sym, _empty_quote()).price is not None:
                continue
            v = open_from_csv(data_dir, sym, session_date)
            if v is not None:
                yf_opens[sym] = OpenQuote(
                    price=v,
                    source="csv",
                    quote_time_et=_market_open_dt(session_date),
                    quote_session=session_date,
                )

    out: list[ScannerOpenRow] = []
    for _, r in df.iterrows():
        sym = str(r.get(cols["SYMBOL"], "")).strip().upper()
        if not sym:
            continue
        quote = yf_opens.get(sym, _empty_quote())
        row = _build_row_from_scanner(
            r,
            cols,
            session_date=session_date,
            quote=quote,
            require_fresh_signal=require_fresh_signal,
            now_et=now_et,
        )
        if row is not None:
            out.append(row)
    out.sort(key=lambda x: (0 if x.action == "BUY" else 1, x.symbol))
    return out


def wait_until_market_open(now_et: Optional[datetime] = None) -> None:
    now_et = now_et or datetime.now(ET)
    open_dt = datetime.combine(now_et.date(), MARKET_OPEN_ET, tzinfo=ET)
    if now_et < open_dt:
        secs = (open_dt - now_et).total_seconds()
        if secs > 0:
            print(f"[scanner-open] Waiting until 9:30 AM ET ({secs:.0f}s)...")
            time.sleep(secs)


def poll_session_opens(
    rows: list[ScannerOpenRow],
    *,
    session_date: date,
    data_dir: Optional[Path] = None,
    use_csv_fallback: bool = False,
    is_long: bool = True,
    require_fresh_signal: bool = True,
    now_et: Optional[datetime] = None,
) -> list[ScannerOpenRow]:
    """Re-fetch opens from Yahoo until all symbols have data or 9:45 AM ET."""
    del is_long
    now_et = now_et or datetime.now(ET)
    deadline = datetime.combine(session_date, OPEN_POLL_END_ET, tzinfo=ET)
    symbols = [r.symbol for r in rows]
    meta = {r.symbol: r for r in rows}

    while True:
        now_et = datetime.now(ET)
        yf_opens = fetch_session_opens_yfinance(symbols, session_date, now_et=now_et)
        if use_csv_fallback and data_dir is not None:
            for sym in symbols:
                if yf_opens.get(sym, _empty_quote()).price is not None:
                    continue
                v = open_from_csv(data_dir, sym, session_date)
                if v is not None:
                    yf_opens[sym] = OpenQuote(
                        price=v,
                        source="csv",
                        quote_time_et=_market_open_dt(session_date),
                        quote_session=session_date,
                    )

        missing: list[str] = []
        updated: list[ScannerOpenRow] = []
        for sym in symbols:
            base = meta[sym]
            quote = yf_opens.get(sym, _empty_quote())
            action, reason = _classify_long_open(
                session_open=quote.price,
                max_entry_open=base.max_entry_open,
                min_entry_open=base.min_entry_open,
                signal_date=_parse_yyyymmdd(base.signal_date),
                session=session_date,
                require_fresh_signal=require_fresh_signal,
                quote=quote,
                now_et=now_et,
            )
            updated.append(
                ScannerOpenRow(
                    symbol=base.symbol,
                    signal_date=base.signal_date,
                    scanner_close=base.scanner_close,
                    max_entry_open=base.max_entry_open,
                    min_entry_open=base.min_entry_open,
                    stop_loss=base.stop_loss,
                    target=base.target,
                    ind_diff=base.ind_diff,
                    ind_score=base.ind_score,
                    atr_pct_at_trigger=base.atr_pct_at_trigger,
                    atr_pct_at_entry=base.atr_pct_at_entry,
                    session_open=quote.price,
                    open_source=quote.source,
                    open_quote_time_et=_quote_time_str(quote),
                    action=action,
                    reason=reason,
                )
            )
            if quote.price is None:
                missing.append(sym)
        rows = updated
        now_et = datetime.now(ET)
        if not missing:
            print(f"[scanner-open] All {len(symbols)} opens from Yahoo.")
            break
        if now_et >= deadline:
            print(
                f"[scanner-open] Stop polling at {OPEN_POLL_END_ET.strftime('%H:%M')} ET; "
                f"missing open for: {', '.join(missing)}"
            )
            break
        print(
            f"[scanner-open] Yahoo opens pending ({len(missing)} missing); "
            f"retry in {OPEN_POLL_INTERVAL_SEC}s..."
        )
        time.sleep(OPEN_POLL_INTERVAL_SEC)
    rows.sort(key=lambda x: (0 if x.action == "BUY" else 1, x.symbol))
    return rows


def rows_to_dataframe(rows: list[ScannerOpenRow], *, session_date: date, scanner_path: Path, run_ts: str) -> pd.DataFrame:
    data = []
    for r in rows:
        data.append(
            {
                "Action": r.action,
                "Reason": r.reason,
                "Symbol": r.symbol,
                "SessionDate": session_date.isoformat(),
                "SessionOpen": r.session_open,
                "OpenQuoteTimeET": r.open_quote_time_et,
                "OpenSource": r.open_source,
                "MaxEntryOpen": r.max_entry_open,
                "MinEntryOpen": r.min_entry_open,
                "SignalDate": r.signal_date,
                "ScannerClose": r.scanner_close,
                "StopLoss": r.stop_loss,
                "Target": r.target,
                "IND_DIFF": r.ind_diff,
                "IND_SCORE": r.ind_score,
                "ATR_PCT_AT_TRIGGER": r.atr_pct_at_trigger,
                "ATR_PCT_AT_ENTRY": r.atr_pct_at_entry,
                "ScannerRunTs": run_ts,
                "ScannerFile": scanner_path.name,
            }
        )
    return pd.DataFrame(data)


def write_scanner_open_csv(rows: list[ScannerOpenRow], path: Path, *, session_date: date, scanner_path: Path, run_ts: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_to_dataframe(rows, session_date=session_date, scanner_path=scanner_path, run_ts=run_ts).to_csv(path, index=False)
    return path


def _fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.4f}"


def _html_table(headers: list[str], table_rows: list[list[str]]) -> str:
    if not table_rows:
        return "<p><em>None</em></p>"
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = []
    for row in table_rows:
        tds = "".join(f"<td>{c}</td>" for c in row)
        body.append(f"<tr>{tds}</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def write_scanner_open_html(
    rows: list[ScannerOpenRow],
    path: Path,
    *,
    session_date: date,
    scanner_path: Path,
    run_ts: str,
    generated_et: datetime,
) -> Path:
    buy = [r for r in rows if r.action == "BUY"]
    ignore = [r for r in rows if r.action == "IGNORE"]
    status = market_status_message(session_date, generated_et)
    headers = [
        "Symbol",
        "Open",
        "Quote time (ET)",
        "Max",
        "Min",
        "Stop",
        "Target",
        "ATR%@Trigger",
        "ATR%@Entry",
        "IND_DIFF",
        "Reason",
    ]

    def _rows(chunk: list[ScannerOpenRow]) -> list[list[str]]:
        return [
            [
                r.symbol,
                _fmt_price(r.session_open),
                r.open_quote_time_et or "—",
                _fmt_price(r.max_entry_open),
                _fmt_price(r.min_entry_open),
                _fmt_price(r.stop_loss),
                _fmt_price(r.target),
                "—" if r.atr_pct_at_trigger is None else f"{r.atr_pct_at_trigger:.2f}",
                "—" if r.atr_pct_at_entry is None else f"{r.atr_pct_at_entry:.2f}",
                "—" if r.ind_diff is None else f"{r.ind_diff:.0f}",
                r.reason,
            ]
            for r in chunk
        ]

    from report_page_extras import CACHE_META, FORCE_RELOAD_SCRIPT

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
{CACHE_META}
{FORCE_RELOAD_SCRIPT}
<meta charset="utf-8"/>
<title>Scanner open report {session_date.isoformat()}</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #111; }}
h1 {{ font-size: 1.35rem; margin-bottom: 0.25rem; }}
.sub {{ color: #555; margin-bottom: 1.25rem; }}
h2 {{ margin-top: 1.5rem; font-size: 1.1rem; }}
h2.buy {{ color: #166534; }}
h2.ignore {{ color: #991b1b; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 0.5rem; font-size: 0.92rem; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
th {{ background: #f3f4f6; }}
tr:nth-child(even) {{ background: #fafafa; }}
.count {{ font-weight: normal; color: #555; }}
</style>
</head>
<body>
<h1>Scanner open report</h1>
<div class="sub">
  Session {session_date.isoformat()} · Generated {generated_et.strftime("%Y-%m-%d %H:%M:%S")} ET<br/>
  {status}<br/>
  Scanner: {scanner_path.name} (run {run_ts})<br/>
  Open prices: Yahoo 1m bar on session date at/after 09:30 ET only (never prior-day close).<br/>
  ATR%@Trigger = (ATR<sub>14</sub> / trigger-day close) × 100 on the signal bar (known at trigger).<br/>
  ATR%@Entry = (ATR<sub>14</sub> / entry-day open) × 100 on the session after the trigger (not known at trigger).
</div>
<h2 class="buy">Buy <span class="count">({len(buy)})</span></h2>
<p>Open is within the entry band (open ≤ MAX_ENTRY_OPEN and ≥ MIN_ENTRY_OPEN when set).</p>
{_html_table(headers, _rows(buy))}
<h2 class="ignore">Ignore <span class="count">({len(ignore)})</span></h2>
<p>Too far above/below the band, stale signal date, or open not available yet.</p>
{_html_table(headers, _rows(ignore))}
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
