#!/usr/bin/env python3
"""Stop check for Paul's open positions. Research helper only.

Not gold. Not wired into DailyRun. Reads gettarget_positions.csv joined to
getTarget_output.csv. He still holds the names, so a stop that was touched
earlier is only a note. The stop to use now follows the highest high since
the buy. Last price under that stop means sell. Last price at or above it
means hold.
"""
from __future__ import annotations

import html
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import report_page_extras as extras  # noqa: E402
from stock_analysis.intraday_1m import ET, fetch_1m_yfinance, read_1m  # noqa: E402
from stock_analysis.ohlcv_store import DEFAULT_DB_PATH  # noqa: E402

POSITIONS = ROOT / "gettarget_positions.csv"
GETTARGET = ROOT / "getTarget_output.csv"
OUT_HTML = ROOT / "drive" / "paul_experiments" / "open_position_stops_20261015" / "latest.html"

ASK = (
    "Paul wants run_open_position_stops.bat to even show the trailing stop on a buy "
    "day. If it goes up a lot on the buy day, he wants to move the stop accordingly. "
    "It's unlikely, but we should still compute it."
)

PLAIN = (
    "You still hold these stocks. Each name has an initial stop (the base under the "
    "trigger or signal low) and a trailing stop that turns on after a set percent "
    "rise from the buy, then keeps a fraction of the gain to the highest high since "
    "the fill. We compute that trailing stop on the buy day too. If the stock runs "
    "up enough that day, the stop moves up with it. If the trail is not on yet, the "
    "stop you see is still the initial stop — we do not hide it. The buy day is "
    "still not a sale; if the last price is already under the stop, the next open "
    "is a sale if it is still under. An old stop that price already went through is "
    "only a note. This looks only at your open positions, and it is not part of the "
    "live daily run."
)

# base_pct is the percent under the anchor. None means no price stop until the trail is on.
# act is the percent the high-water mark must be above the buy before the trail turns on.
# keep is the fraction of the gain from the buy to the high-water mark that the trail holds.
RULES: dict[str, dict] = {
    "BRT": {"name": "Break and ReTest (BRT)", "base_pct": 13.6, "act": 6.0, "keep": 0.70, "anchor": "trigger"},
    "RL": {"name": "Rocket Launcher (RL)", "base_pct": 0.65, "act": 6.0, "keep": 0.80, "anchor": "signal"},
    "YH": {"name": "Year High (YH)", "base_pct": 0.95, "act": 2.0, "keep": 0.70, "anchor": "trigger"},
    "MTS": {"name": "Magic Touch (MTS)", "base_pct": 2.56, "act": 4.0, "keep": 0.60, "anchor": "trigger"},
    "WPBR": {"name": "Weekly Pivot Break and Retest (WPBR)", "base_pct": 3.03, "act": 2.0, "keep": 0.80, "anchor": "trigger"},
    "RS": {"name": "Relative Strength vs SPY (RS)", "base_pct": 15.0, "act": 10.0, "keep": 0.80, "anchor": "entry"},
    "RSI": {"name": "Relative Strength Index (RSI)", "base_pct": None, "act": 6.0, "keep": 0.80, "anchor": "none"},
}

NAMES = {
    "SB": "StockBee (SB)",
    "VZ": "Volume Zone (VZ)",
    "WRL": "Weekly Range / Swing (WRL)",
    "MVCP": "Minervini Volatility Contraction Pattern (MVCP)",
    "CS": "CAN SLIM (CS)",
    "IND": "Indicators (IND)",
}


@dataclass
class Bar:
    when: datetime
    session: date
    open: float
    high: float
    low: float
    close: float


def _num(raw) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().replace(",", "").replace("$", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v != v or v <= 0:
        return None
    return v


def _ymd(raw) -> date | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)


def _px(v: float | None) -> str:
    if v is None or v != v:
        return "—"
    if abs(v) >= 1:
        return f"{v:.2f}"
    return f"{v:.4f}"


def _le(a: float, b: float) -> bool:
    return a == a and b == b and float(a) <= float(b) + 1e-6


def market_is_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.timetz().replace(tzinfo=None)
    return dt_time(9, 30) <= t < dt_time(16, 0)


def session_date(now: datetime) -> date:
    """Regular session to replay: today once the open has passed, else the prior weekday."""
    d = now.date()
    if now.weekday() < 5 and now.timetz().replace(tzinfo=None) >= dt_time(9, 30):
        return d
    d = d - timedelta(days=1)
    while d.weekday() >= 5:
        d = d - timedelta(days=1)
    return d


def trail_price(entry: float, hwm: float, act: float, keep: float) -> float | None:
    """Same trail as later days: on when the high-water mark is at least act% above the buy.

    The trail is entry + keep × (high-water mark − entry). Used on the buy day too.
    """
    if entry > 0 and hwm > entry:
        gain_pct = (hwm - entry) / entry * 100.0
        if gain_pct + 1e-12 >= act:
            return entry + keep * (hwm - entry)
    return None


def effective_stop(entry: float, hwm: float, base: float | None, act: float, keep: float) -> tuple[float | None, bool]:
    """Trail turns on when the high-water mark is at least act% above the buy.

    The trail is entry + keep × (high-water mark − entry). It never sits under the base.
    """
    trail_px = trail_price(entry, hwm, act, keep)
    if trail_px is not None and (base is None or trail_px > base + 1e-9):
        return trail_px, True
    return base, trail_px is not None


def _under(price: float | None, stop: float | None) -> bool:
    return price is not None and stop is not None and price == price and stop == stop and float(price) < float(stop) - 1e-6


def replay(
    entry: float,
    entry_day: date,
    base: float | None,
    act: float,
    keep: float,
    daily: list[Bar],
    minutes: list[Bar],
    session: date,
) -> dict:
    """Walk every bar after the fill. He still holds the stock.

    The first time price trades through the stop in force is kept as a note.
    The walk does not stop there. A later high raises the high-water mark, and
    the stop to use now is entry + keep × (that mark − entry), never under the
    base. On the current session, minutes are walked in order so a new high
    raises the stop before a later pullback, including on the buy day. The buy
    day never counts as a sale.
    """
    hwm = float(entry)
    touch_px = None
    touch_when = ""
    minute_session = session if minutes else None

    hist = [b for b in daily if entry_day <= b.session < (minute_session or date.max)]
    if minute_session is None:
        hist = [b for b in daily if entry_day <= b.session <= session]

    def _note(px: float, when: str) -> None:
        nonlocal touch_px, touch_when
        if touch_px is None:
            touch_px = float(px)
            touch_when = when

    def _raise(hi: float) -> None:
        nonlocal hwm
        if hi == hi and hi > hwm:
            hwm = float(hi)

    for b in hist:
        if b.session == entry_day:
            _raise(b.high)
            continue
        stop, _on = effective_stop(entry, hwm, base, act, keep)
        if stop is not None and _le(b.open, stop):
            _note(b.open, f"{b.session.isoformat()} 09:30 ET")
        elif stop is not None and _le(b.low, stop):
            _note(stop, f"{b.session.isoformat()} session (daily bar)")
        _raise(b.high)

    if minutes:
        buy_day = session == entry_day
        for b in minutes:
            if not buy_day:
                stop, _on = effective_stop(entry, hwm, base, act, keep)
                stamp = b.when.strftime("%Y-%m-%d %H:%M ET")
                if stop is not None and _le(b.open, stop):
                    _note(b.open, stamp)
                elif stop is not None and _le(b.low, stop):
                    _note(stop, stamp)
            _raise(b.high)

    for b in daily:
        if entry_day <= b.session <= session:
            _raise(b.high)

    trail_px = trail_price(entry, hwm, act, keep)
    stop, trail_on = effective_stop(entry, hwm, base, act, keep)
    return {
        "stop": stop,
        "trail_on": trail_on,
        "trail_px": trail_px,
        "base": base,
        "hwm": hwm,
        "touch_px": touch_px,
        "touch_when": touch_when,
    }


def decide(stop: float | None, price: float | None, entry_day: date, session: date) -> str:
    """Last price under the current stop is a sell, unless today is the buy day."""
    if stop is None:
        return "HOLD"
    if entry_day == session:
        return "NEXT OPEN" if _under(price, stop) else "HOLD"
    if price is None:
        return "quote failed"
    return "SELL" if _under(price, stop) else "HOLD"


def _self_test() -> None:
    entry_day = date(2026, 10, 1)
    day2 = date(2026, 10, 2)
    day3 = date(2026, 10, 5)

    def D(sess: date, o: float, h: float, l: float, c: float) -> Bar:
        return Bar(datetime(sess.year, sess.month, sess.day, 9, 30, tzinfo=ET), sess, o, h, l, c)

    def M(sess: date, hh: int, mm: int, o: float, h: float, l: float, c: float) -> Bar:
        return Bar(datetime(sess.year, sess.month, sess.day, hh, mm, tzinfo=ET), sess, o, h, l, c)

    # (c) Later days unchanged: entry-day high 110 arms a 6% / keep-80% trail.
    # Next open 100 touches 108. He still holds, and that day did not make a higher
    # high, so the stop stays 108.
    hit = replay(100.0, entry_day, 90.0, 6.0, 0.80, [D(entry_day, 100, 110, 99, 108), D(day2, 100, 101, 99, 100)], [], day2)
    assert abs(hit["stop"] - 108.0) < 1e-9 and abs(hit["touch_px"] - 100.0) < 1e-9, hit
    assert decide(hit["stop"], 100.0, entry_day, day2) == "SELL"
    assert decide(hit["stop"], 108.0, entry_day, day2) == "HOLD"

    # Day 2 does not tag 108. High 112 lifts the stop to 109.6. Close 111 holds.
    stay = replay(100.0, entry_day, 90.0, 6.0, 0.80, [D(entry_day, 100, 110, 99, 108), D(day2, 109, 112, 108.5, 111)], [], day2)
    assert stay["touch_px"] is None and abs(stay["stop"] - 109.6) < 1e-9 and stay["trail_on"], stay
    assert decide(stay["stop"], 111.0, entry_day, day2) == "HOLD"

    # (a) Buy day with no run-up still shows the initial stop. Not a sale.
    held = replay(100.0, entry_day, 99.0, 6.0, 0.80, [D(entry_day, 100, 101, 90, 100)], [], entry_day)
    assert held["touch_px"] is None and abs(held["stop"] - 99.0) < 1e-9 and not held["trail_on"], held
    assert held["trail_px"] is None and abs(held["base"] - 99.0) < 1e-9, held
    assert decide(held["stop"], 90.0, entry_day, entry_day) == "NEXT OPEN"
    assert decide(held["stop"], 100.0, entry_day, entry_day) == "HOLD"

    # (b) Buy day with a large high ratchets the trailing stop (6% / keep 80% → 108).
    runup = replay(100.0, entry_day, 90.0, 6.0, 0.80, [D(entry_day, 100, 110, 99, 108)], [], entry_day)
    assert runup["touch_px"] is None and abs(runup["hwm"] - 110.0) < 1e-9, runup
    assert abs(runup["stop"] - 108.0) < 1e-9 and runup["trail_on"], runup
    assert abs(runup["trail_px"] - 108.0) < 1e-9 and abs(runup["base"] - 90.0) < 1e-9, runup
    assert decide(runup["stop"], 108.0, entry_day, entry_day) == "HOLD"
    assert decide(runup["stop"], 100.0, entry_day, entry_day) == "NEXT OPEN"

    # Buy-day minutes: a 10% high turns the trail on. A later pullback is not a sale.
    mins0 = [
        M(entry_day, 9, 30, 100, 110, 99.5, 109),
        M(entry_day, 9, 31, 109, 109.2, 107.0, 107.5),
    ]
    intra0 = replay(100.0, entry_day, 90.0, 6.0, 0.80, [], mins0, entry_day)
    assert intra0["touch_px"] is None and abs(intra0["stop"] - 108.0) < 1e-9 and intra0["trail_on"], intra0
    assert decide(intra0["stop"], 107.5, entry_day, entry_day) == "NEXT OPEN"

    # Minute 1 high turns the trail on. Minute 2 tags it. The high-water mark stays 107.
    mins = [
        M(day2, 9, 30, 100, 107, 99.5, 106),
        M(day2, 9, 31, 106, 106.2, 105.0, 105.2),
    ]
    intra = replay(100.0, entry_day, 90.0, 6.0, 0.80, [D(entry_day, 100, 100.5, 99.8, 100.2)], mins, day2)
    assert abs(intra["stop"] - 105.6) < 1e-6 and abs(intra["touch_px"] - 105.6) < 1e-6, intra
    assert decide(intra["stop"], 105.2, entry_day, day2) == "SELL"

    # A new high on minute 1 lifts the stop before minute 2. Minute 2 stays above it.
    mins2 = [
        M(day2, 9, 30, 100, 104, 99.5, 103),
        M(day2, 9, 31, 103, 103.2, 102.2, 102.5),
    ]
    lifted = replay(100.0, entry_day, 95.0, 2.0, 0.50, [D(entry_day, 100, 100.2, 99.5, 100)], mins2, day2)
    assert lifted["touch_px"] is None and abs(lifted["stop"] - 102.0) < 1e-9, lifted
    assert decide(lifted["stop"], 102.5, entry_day, day2) == "HOLD"

    # The low tags the old stop. The same bar's high still counts, because he held.
    tagged = replay(
        100.0, entry_day, 95.0, 2.0, 0.50,
        [D(entry_day, 100, 100, 99.5, 100)],
        [M(day2, 9, 30, 100, 110, 94, 100)],
        day2,
    )
    assert abs(tagged["touch_px"] - 95.0) < 1e-9 and abs(tagged["hwm"] - 110.0) < 1e-9, tagged
    assert abs(tagged["stop"] - 105.0) < 1e-9, tagged
    assert decide(tagged["stop"], 100.0, entry_day, day2) == "SELL"
    assert decide(tagged["stop"], 105.0, entry_day, day2) == "HOLD"

    # After the first touch the stock makes a higher high. The new stop is the one to use.
    later = replay(
        100.0, entry_day, 99.0, 6.0, 0.80,
        [D(entry_day, 100, 101, 99.5, 100.5), D(day2, 100, 104, 98, 103), D(day3, 110, 120, 109, 115)],
        [], day3,
    )
    assert abs(later["touch_px"] - 99.0) < 1e-9 and "10-02" in later["touch_when"], later
    assert abs(later["hwm"] - 120.0) < 1e-9 and abs(later["stop"] - 116.0) < 1e-9, later
    assert decide(later["stop"], 115.0, entry_day, day3) == "SELL"
    assert decide(later["stop"], 117.0, entry_day, day3) == "HOLD"

    # Trail under the base stays at the base. RSI has no price stop until the trail is on.
    under = effective_stop(100.0, 101.0, 99.5, 2.0, 0.10)
    assert under[0] == 99.5 and under[1] is False, under
    rsi_off = effective_stop(100.0, 103.0, None, 6.0, 0.80)
    assert rsi_off[0] is None and rsi_off[1] is False, rsi_off
    rsi_on = effective_stop(100.0, 110.0, None, 6.0, 0.80)
    assert abs(rsi_on[0] - 108.0) < 1e-9 and rsi_on[1] is True, rsi_on

    shown = _stop_display({
        "status": "NEXT OPEN", "stop": 99.0, "base": 99.0, "trail_px": None,
        "trail_on": False, "live_stop": None,
    })
    assert shown == ("99.00", "99.00", "99.00", "no"), shown
    shown_on = _stop_display({
        "status": "NEXT OPEN", "stop": 108.0, "base": 90.0, "trail_px": 108.0,
        "trail_on": True, "live_stop": None,
    })
    assert shown_on == ("90.00", "108.00", "108.00", "yes"), shown_on
    later_shown = _stop_display({
        "status": "HOLD", "stop": 108.0, "base": 90.0, "trail_px": 108.0,
        "trail_on": True, "live_stop": None,
    })
    assert later_shown == ("90.00", "108.00", "108.00", "yes"), later_shown
    print("self-test ok", flush=True)


def load_positions() -> list[dict]:
    pos = _read_csv(POSITIONS)
    gt = _read_csv(GETTARGET)
    by_key: dict[tuple[str, str], dict] = {}
    by_sym: dict[str, dict] = {}
    if not gt.empty and "Symbol" in gt.columns:
        for _, r in gt.iterrows():
            sym = str(r.get("Symbol") or "").strip().upper()
            if not sym:
                continue
            row = {
                "live_stop": _num(r.get("StopTrailing")) or _num(r.get("StopInitial")) or _num(r.get("LimitPrice")),
                "signal_low": _num(r.get("SignalLow")),
                "signal_date": _ymd(r.get("SignalDate")),
                "gt_entry": _num(r.get("EntryPrice")),
                "gt_system": str(r.get("System") or "").strip().upper(),
                "file_price": _num(r.get("CurrentPrice")),
                "asof": _ymd(r.get("AsOfDate")),
            }
            by_sym[sym] = row
            by_key[(sym, row["gt_system"])] = row
    rows = []
    if pos.empty:
        return rows
    sym_col = "symbol" if "symbol" in pos.columns else "Symbol"
    for _, r in pos.iterrows():
        sym = str(r.get(sym_col) or "").strip().upper()
        if not sym:
            continue
        system = str(r.get("system") or r.get("System") or "").strip().upper()
        joined = by_key.get((sym, system)) or by_sym.get(sym) or {}
        entry = _num(r.get("entry_price") or r.get("EntryPrice")) or joined.get("gt_entry")
        opened = _ymd(r.get("purchase_date") or r.get("PurchaseDate"))
        rows.append({
            "symbol": sym,
            "system": system,
            "entry": entry,
            "entry_date": opened,
            "live_stop": joined.get("live_stop"),
            "signal_low": joined.get("signal_low"),
            "signal_date": joined.get("signal_date"),
            "file_price": joined.get("file_price"),
            "asof": joined.get("asof"),
        })
    return rows


def load_daily(symbols: list[str], start: date) -> tuple[dict[str, list[Bar]], str]:
    if not symbols:
        return {}, "no symbols"
    import duckdb

    out: dict[str, list[Bar]] = {s: [] for s in symbols}
    note = str(DEFAULT_DB_PATH)
    con = duckdb.connect(str(DEFAULT_DB_PATH), read_only=True)
    try:
        df = con.execute(
            """
            SELECT UPPER(symbol) AS symbol, CAST(date AS DATE) AS d,
                   open, high, low, close
            FROM prices
            WHERE UPPER(symbol) IN (SELECT * FROM UNNEST(?))
              AND CAST(date AS DATE) >= ?
            ORDER BY 1, 2
            """,
            [symbols, start],
        ).fetchdf()
    finally:
        con.close()
    if df is None or df.empty:
        return out, note + " (no rows)"
    for _, r in df.iterrows():
        sym = str(r["symbol"])
        sess = pd.Timestamp(r["d"]).date()
        when = datetime(sess.year, sess.month, sess.day, 9, 30, tzinfo=ET)
        try:
            bar = Bar(when, sess, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        except (TypeError, ValueError):
            continue
        out.setdefault(sym, []).append(bar)
    return out, note


def _rth_minutes(df: pd.DataFrame, session: date) -> list[Bar]:
    if df is None or df.empty or "ts" not in df.columns:
        return []
    bars: list[Bar] = []
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(ET)
    for i, row in df.iterrows():
        when = ts.loc[i].to_pydatetime()
        if when.date() != session:
            continue
        t = when.timetz().replace(tzinfo=None)
        if t < dt_time(9, 30) or t >= dt_time(16, 0):
            continue
        try:
            bars.append(Bar(
                when, session,
                float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
            ))
        except (TypeError, ValueError, KeyError):
            continue
    bars.sort(key=lambda b: b.when)
    return bars


def _minutes_complete(bars: list[Bar]) -> bool:
    if not bars:
        return False
    last = bars[-1].when.timetz().replace(tzinfo=None)
    return last >= dt_time(15, 55)


def fetch_minutes(symbols: list[str], session: date, now: datetime) -> dict[str, tuple[list[Bar], str]]:
    """1-minute regular-hours bars for the session. One quote failure does not stop the rest."""
    out: dict[str, tuple[list[Bar], str]] = {}

    def one(sym: str) -> tuple[str, list[Bar], str]:
        cached: list[Bar] = []
        try:
            cached = _rth_minutes(read_1m(sym), session)
        except Exception as exc:  # noqa: BLE001
            cached = []
            cache_err = str(exc)
        else:
            cache_err = ""
        need = not _minutes_complete(cached)
        if market_is_open(now):
            if cached:
                age = (now - cached[-1].when).total_seconds()
                need = age > 90
            else:
                need = True
        if not need:
            return sym, cached, ""
        start = datetime(session.year, session.month, session.day, 9, 30, tzinfo=ET)
        end = datetime(session.year, session.month, session.day, 16, 1, tzinfo=ET)
        try:
            fresh = fetch_1m_yfinance(sym, start_et=start, end_et=end)
            bars = _rth_minutes(fresh, session)
        except Exception as exc:  # noqa: BLE001
            if cached:
                return sym, cached, f"quote failed ({exc}); used stored 1-minute bars"
            return sym, [], f"quote failed ({exc})" + (f"; cache {cache_err}" if cache_err else "")
        if not bars and cached:
            return sym, cached, "quote returned no bars; used stored 1-minute bars"
        if not bars:
            return sym, [], "quote returned no 1-minute bars"
        return sym, bars, ""

    if not symbols:
        return out
    workers = min(8, len(symbols))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, s) for s in symbols]
        for fut in as_completed(futs):
            sym, bars, err = fut.result()
            out[sym] = (bars, err)
    return out


def _anchor(pos: dict, daily: list[Bar], rule: dict) -> tuple[float | None, str]:
    kind = rule["anchor"]
    entry = pos["entry"]
    if kind == "entry":
        return entry, "entry"
    if kind == "none":
        return None, ""
    if pos.get("signal_low"):
        label = "signal-day low" if kind == "signal" else "trigger-day low"
        src = "getTarget SignalLow"
        if pos.get("signal_date"):
            src += f" {pos['signal_date'].isoformat()}"
        return float(pos["signal_low"]), f"{label} {src}"
    opened = pos.get("entry_date")
    prior = [b for b in daily if opened and b.session < opened]
    if prior:
        b = prior[-1]
        return float(b.low), f"warehouse low on {b.session.isoformat()} (day before the buy; SignalLow was blank)"
    return None, "trigger low missing"


def _base_stop(pos: dict, daily: list[Bar], rule: dict) -> tuple[float | None, str, str]:
    if rule["base_pct"] is None:
        return None, "", "no price stop until the trail is on"
    anchor, how = _anchor(pos, daily, rule)
    if anchor is None or not (anchor == anchor and anchor > 0):
        return None, how, "anchor low missing"
    base = anchor * (1.0 - float(rule["base_pct"]) / 100.0)
    return base, how, ""


def _current_price(minutes: list[Bar], daily: list[Bar], session: date, file_price: float | None) -> tuple[float | None, str]:
    if minutes:
        return float(minutes[-1].close), f"1-minute close {minutes[-1].when.strftime('%Y-%m-%d %H:%M ET')}"
    today = [b for b in daily if b.session == session]
    if today:
        return float(today[-1].close), f"daily close {session.isoformat()}"
    if daily:
        b = daily[-1]
        return float(b.close), f"daily close {b.session.isoformat()}"
    if file_price:
        return float(file_price), "getTarget CurrentPrice"
    return None, ""


def analyze_one(pos: dict, daily: list[Bar], minutes: list[Bar], minute_note: str, session: date, market_open: bool) -> dict:
    system = pos["system"] or "?"
    rule = RULES.get(system)
    price, price_src = _current_price(minutes, daily, session, pos.get("file_price"))
    row = {
        "symbol": pos["symbol"],
        "system": system,
        "system_name": (rule or {}).get("name") or NAMES.get(system) or system,
        "entry": pos.get("entry"),
        "entry_date": pos.get("entry_date"),
        "price": price,
        "price_src": price_src,
        "live_stop": pos.get("live_stop"),
        "stop": None,
        "base": None,
        "trail_px": None,
        "trail_on": False,
        "hwm": None,
        "status": "",
        "touch_px": None,
        "touch_when": "",
        "note": minute_note,
        "sentence": "",
    }
    if rule is None:
        live = _px(pos.get("live_stop"))
        row["status"] = "no new stop rule picked"
        row["stop"] = pos.get("live_stop")
        row["sentence"] = (
            f"{row['system_name']} {pos['symbol']}: live stop from getTarget is {live}. "
            "No new stop rule picked."
        )
        if minute_note:
            row["sentence"] += " " + minute_note + "."
        return row
    if not pos.get("entry") or not pos.get("entry_date"):
        row["status"] = "missing entry"
        row["sentence"] = f"{row['system_name']} {pos['symbol']}: entry price or buy date is missing, so no stop was computed."
        return row
    if not daily and not minutes:
        row["status"] = "quote failed"
        row["sentence"] = (
            f"{row['system_name']} {pos['symbol']}: no daily bars and no 1-minute bars. "
            + (minute_note or "Quote failed.")
        )
        return row

    base, anchor_how, base_note = _base_stop(pos, daily, rule)
    if base_note == "anchor low missing":
        row["status"] = "anchor low missing"
        row["sentence"] = (
            f"{row['system_name']} {pos['symbol']}: the trigger low is not in getTarget and "
            "not in the daily warehouse, so no new stop was computed. "
            f"Live stop from getTarget is {_px(pos.get('live_stop'))}."
        )
        return row

    walked = replay(
        float(pos["entry"]), pos["entry_date"], base,
        float(rule["act"]), float(rule["keep"]),
        daily, minutes, session,
    )
    row.update(walked)
    status = decide(walked["stop"], price, pos["entry_date"], session)
    row["status"] = status
    if minute_note and not minutes:
        row["note"] = minute_note + ". Prior sessions use the daily warehouse only."
    touch = ""
    if walked["touch_px"] is not None:
        touch = f"An earlier stop was touched at {_px(walked['touch_px'])} ({walked['touch_when']}). "
    if status == "SELL" and walked["touch_px"] is not None and walked["stop"] is not None and walked["stop"] > walked["touch_px"] + 1e-6:
        bits = [(
            f"{row['system_name']} {pos['symbol']}: an earlier stop was touched at "
            f"{_px(walked['touch_px'])} ({walked['touch_when']}), but the stock went higher, "
            f"so the new stop is {_px(walked['stop'])}. The last price {_px(price)} is under "
            f"that new stop, so sell at {_px(price)}."
        )]
    elif status == "SELL":
        bits = [(
            f"{row['system_name']} {pos['symbol']}: {touch}the stop to use now is {_px(walked['stop'])}. "
            f"The last price {_px(price)} is under that stop, so sell at {_px(price)}."
        )]
    elif status == "NEXT OPEN":
        init = _px(base) if base is not None else "no price stop"
        trail_txt = _px(walked["trail_px"]) if walked.get("trail_px") is not None else init
        bits = [(
            f"{row['system_name']} {pos['symbol']}: today is the buy day, so this is not a sale. "
            f"Initial stop {init}. Trailing stop {trail_txt}. "
            f"Move the stop to {_px(walked['stop'])}. "
            f"The last price {_px(price)} is under that stop, so the next open is a sale if it is still under the stop."
        )]
    elif walked["stop"] is None:
        bits = [(
            f"{row['system_name']} {pos['symbol']}: there is no price stop yet, so hold. "
            f"The trail turns on after a {rule['act']:.0f}% rise and then keeps {rule['keep']*100:.0f}% of that gain. "
            f"High-water mark {_px(walked['hwm'])}. The stock is now {_px(price)}."
        )]
    else:
        held = "hold" if status == "HOLD" else status.lower()
        where = "at or above" if price is not None and not _under(price, walked["stop"]) else "against"
        old = ""
        if walked["touch_px"] is not None:
            old = "That earlier price is not the stop to use now. "
        init = _px(base) if base is not None else "no price stop"
        trail_txt = _px(walked["trail_px"]) if walked.get("trail_px") is not None else init
        buy = ""
        if pos.get("entry_date") == session:
            buy = f"Today is the buy day, so this is not a sale. Initial stop {init}. Trailing stop {trail_txt}. "
        bits = [(
            f"{row['system_name']} {pos['symbol']}: {touch}{old}{buy}"
            f"Move the stop to {_px(walked['stop'])}. "
            f"The last price {_px(price)} is {where} that stop, so {held}."
        )]
    if anchor_how:
        anchor_px = base / (1.0 - rule["base_pct"] / 100.0) if base is not None and rule["base_pct"] else None
        bits.append(f"Anchor: {anchor_how} ({_px(anchor_px)}).")
    if base is not None and rule["base_pct"] is not None:
        bits.append(f"Base stop {_px(base)} is {rule['base_pct']}% under that anchor.")
    if walked["trail_on"] and base is not None and walked["stop"] is not None and walked["stop"] <= base + 1e-6:
        bits.append("The trail is on, and it is not above the base, so the stop stays at the base.")
    elif walked["trail_on"]:
        bits.append("The trail is on.")
    if minute_note:
        bits.append(minute_note + ".")
    if base is not None and pos["entry"] and base >= float(pos["entry"]) - 1e-9:
        bits.append("That base is above the buy.")
    if not market_open and status == "HOLD" and walked["stop"] is not None:
        bits.append("The market is closed, so this is the stop for the next session.")
    row["sentence"] = " ".join(bits)
    return row


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _td(text: str, num: bool = False) -> str:
    style = ' style="text-align:right"' if num else ""
    return f"<td{style}>{html.escape(text)}</td>"


def _stop_display(row: dict) -> tuple[str, str, str, str]:
    """Initial stop, trailing stop, stop now, trail-on label. Never hide the stop on buy day."""
    if row["status"] == "no new stop rule picked":
        live = _px(row.get("live_stop") or row.get("stop"))
        return live, "n/a", live, "n/a"
    if row["stop"] is None and row["status"] == "HOLD":
        none = "no price stop"
        return none, none, none, "no"
    init = _px(row["base"]) if row.get("base") is not None else (
        "no price stop" if row["stop"] is None else _px(row["stop"])
    )
    if row.get("trail_px") is not None:
        trail_txt = _px(row["trail_px"])
    else:
        trail_txt = init
    stop_txt = _px(row["stop"]) if row["stop"] is not None else "no price stop"
    on = "—"
    if row["status"] in {"HOLD", "SELL", "NEXT OPEN"}:
        on = "yes" if row["trail_on"] else "no"
    return init, trail_txt, stop_txt, on


def write_html(rows: list[dict], now: datetime, market_open: bool, elapsed: float, daily_note: str) -> None:
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for r in rows:
        init_txt, trail_txt, stop_txt, trail = _stop_display(r)
        sell_at = _px(r["price"]) if r["status"] == "SELL" else "—"
        body.append(
            "<tr>"
            + _td(r["symbol"])
            + _td(r["system_name"])
            + _td(_px(r["entry"]), True)
            + _td(_px(r["price"]), True)
            + _td(init_txt, True)
            + _td(trail_txt, True)
            + _td(stop_txt, True)
            + _td(sell_at, True)
            + _td(trail)
            + _td(r["status"])
            + _td(_px(r["touch_px"]) if r["touch_px"] is not None else "—", True)
            + _td(r["touch_when"] or "—")
            + _td(_px(r["hwm"]), True)
            + "</tr>"
        )
    sentences = "".join(f"<li>{html.escape(r['sentence'])}</li>" for r in rows)
    state = "The market is open." if market_open else "The market is closed."
    knobs = (
        "Break and ReTest (BRT): base 13.6% under the trigger-day low, trail on at 6%, keep 70%. "
        "Rocket Launcher (RL): base 0.65% under the signal-day low, trail on at 6%, keep 80%. "
        "The live 80%-at-+20% ladder is not applied here. "
        "Year High (YH): base 0.95% under the trigger-day low, trail on at 2%, keep 70%. "
        "Magic Touch (MTS): base 2.56% under the trigger-day low, trail on at 4%, keep 60%. "
        "Weekly Pivot Break and Retest (WPBR): base 3.03% under the trigger-day low, trail on at 2%, keep 80%. "
        "Relative Strength vs SPY (RS): live base is 15% under the buy, trail on at 10%, keep 80%. "
        "Relative Strength Index (RSI): no price stop until the trail is on at 6%, keep 80%."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Open position stops</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.4rem; }}
h2 {{ font-size: 1.1rem; margin-top: 1.2rem; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; border-radius: 10px; padding: 12px 14px; margin: 12px 0; }}
.note {{ color: #475569; font-size: 0.95rem; }}
{extras.SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Open position stops</h1>
<p class="note">Research helper only. Not gold. Not DailyRun. Ran {html.escape(now.strftime("%Y-%m-%d %H:%M ET"))} in {elapsed:.1f}s. {html.escape(state)} Click column headers to sort.</p>
<div class="callout">
<h2>What you asked</h2>
<p>{html.escape(ASK).replace(chr(10), "<br>")}</p>
<h2>In plain English</h2>
<p>{html.escape(PLAIN)}</p>
<p>{html.escape(knobs)}</p>
<p>He still holds every name in the position file, so the first time a stop was touched is a note, not the price to use now. The stop now is the base (initial stop), or the buy plus the keep fraction of the rise to the highest high since the fill (trailing stop), whichever is higher. Both numbers are shown, including on the buy day. Completed days come from the local daily warehouse ({html.escape(daily_note)}). Today uses 1-minute bars from 9:30 to 4:00 Eastern, and only for these open symbols, walked in order so a new high raises the stop before a later pullback — including on the buy day. The buy day is never a sale. If the last price is already under that stop, the next open is a sale if it is still under the stop. A system with no rule above keeps the live getTarget stop and is labeled &quot;no new stop rule picked.&quot;</p>
</div>
{extras.SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{_th("Symbol", "text")}
{_th("System", "text")}
{_th("Entry", "num")}
{_th("Current price", "num")}
{_th("Initial stop", "num")}
{_th("Trailing stop", "num")}
{_th("Stop now", "num")}
{_th("Sell at", "num")}
{_th("Trail on?", "text")}
{_th("Status", "text")}
{_th("First touch (note)", "num")}
{_th("First touch when", "text")}
{_th("High-water mark", "num")}
</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>
</div>
<h2>Each name</h2>
<ul>
{sentences}
</ul>
{extras.SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")


def _print_table(rows: list[dict], market_open: bool, elapsed: float) -> None:
    state = "MARKET OPEN" if market_open else "MARKET CLOSED"
    print(f"{state}  open-position stops  ({elapsed:.1f}s)")
    print("Research helper only. Not gold. Not DailyRun.")
    hdr = (
        f"{'Symbol':<8} {'System':<6} {'Price':>8} {'Initial':>9} {'Trailing':>9} "
        f"{'Stop now':>10} {'Trail':<5} {'Status':<26} {'Sell at':>8}  First touch"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        init_txt, trail_txt, stop_txt, on = _stop_display(r)
        if stop_txt == "no price stop":
            stop_txt = "no px stop"
        if init_txt == "no price stop":
            init_txt = "no px stop"
        if trail_txt == "no price stop":
            trail_txt = "no px stop"
        sell_at = _px(r["price"]) if r["status"] == "SELL" else "-"
        touch = "-"
        if r.get("touch_px") is not None:
            touch = f"{_px(r['touch_px'])} at {r['touch_when']}"
        print(
            f"{r['symbol']:<8} {r['system']:<6} {_px(r['price']):>8} "
            f"{init_txt:>9} {trail_txt:>9} {stop_txt:>10} {on:<5} "
            f"{r['status']:<26} {sell_at:>8}  {touch}"
        )
        if r["status"] not in {"HOLD", "SELL", "NEXT OPEN", "no new stop rule picked"} or r.get("note"):
            extra = r["sentence"]
            if len(extra) > 220:
                extra = extra[:217] + "..."
            print(f"         {extra}")


def main() -> int:
    t0 = time.perf_counter()
    _self_test()
    now = datetime.now(ET)
    session = session_date(now)
    open_now = market_is_open(now)
    positions = load_positions()
    if not positions:
        print("No rows in gettarget_positions.csv")
        return 1
    symbols = sorted({p["symbol"] for p in positions})
    starts = [p["entry_date"] for p in positions if p.get("entry_date")]
    start = min(starts) - timedelta(days=10) if starts else session - timedelta(days=40)
    try:
        daily_map, daily_note = load_daily(symbols, start)
    except Exception as exc:  # noqa: BLE001
        daily_map = {s: [] for s in symbols}
        daily_note = f"daily warehouse failed: {exc}"
        print(daily_note, flush=True)
    try:
        minute_map = fetch_minutes(symbols, session, now)
    except Exception as exc:  # noqa: BLE001
        minute_map = {s: ([], f"quote failed ({exc})") for s in symbols}
        print(f"1-minute fetch failed: {exc}", flush=True)
    rows = []
    for pos in positions:
        minutes, note = minute_map.get(pos["symbol"], ([], "quote failed"))
        daily = daily_map.get(pos["symbol"], [])
        rows.append(analyze_one(pos, daily, minutes, note, session, open_now))
    elapsed = time.perf_counter() - t0
    _print_table(rows, open_now, elapsed)
    write_html(rows, now, open_now, elapsed, daily_note)
    print(f"Wrote {OUT_HTML}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
