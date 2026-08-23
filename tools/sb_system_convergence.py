#!/usr/bin/env python3
"""
SB vs other-systems historical convergence (LatestRun Closed books).

Overlap (primary)
-----------------
Same SYMBOL and intersecting hold ranges:
  SB[DATE_OPENED..DATE_CLOSED] overlaps peer[DATE_OPENED..DATE_CLOSED]
  (inclusive calendar days). Same-day entry is flagged as a subset.

Second-signal aggregate
-----------------------
For each overlap pair:
  Entry  = later of the two buy dates (second signal); price = that side's ENTRY_PRICE.
           Same-day tie-break: prefer peer entry (confirmation outside SB).
  Exit   = earlier exit date among sides still open on/after the second entry
           ("wait for confirmation, then ride until first exit of either").
           If the other side already exited before second entry, use the remaining
           side's exit date/price.
  Dedupe (portfolio / all-peers bucket): unique by (symbol, second_entry_date);
           keep earliest exit (then peer name). Per-peer buckets are also deduped
           the same way within that peer.

Standalone baselines
--------------------
Same metric columns are also computed for each system's full Closed book
(LatestRun / stamp twin used above) — one row per system — under the shared
host capital assumptions (not that system's native Summary notional).

Agg table section order:
  1. Standalone systems (SB, then preferred peers that exist)
  2. SB x peer second-signal rows
  3. ALL PEERS (deduped)

Metrics match rocket_tbn.compute_metrics + tbn_host_sizing defaults where possible:
  initial_capital=500_000, aggressive_max_multiple=2.0, margin_utilization=0.6
  -> deployable 600_000; brt_cash = deployable / Max_Positions;
  Total_PNL uses that per-slot notional; Max_DD from realized equity curve
  (no OHLC mark-to-market).

Writes under drive/paul_experiments/ (or --out-dir):
  SB_System_Convergence_<prefix>.html
  SB_System_Convergence_<prefix>.csv
  SB_System_Convergence_<prefix>.md
  SB_System_Convergence_SecondSignal_Agg_<prefix>.csv
  (default prefix: LatestRun; SecondSignal agg omits duplicate _LatestRun_ infix)

Usage:
  python tools/sb_system_convergence.py
  python tools/sb_system_convergence.py --out-prefix OverlapUniverse --closed-map path/to/map.json
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stock_analysis"))

try:
    from tbn_host_sizing import (  # type: ignore
        DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_MARGIN_UTILIZATION,
        max_concurrent_positions,
        report_adjusted_brt_cash,
    )
except Exception:  # pragma: no cover
    DEFAULT_INITIAL_CAPITAL = 500_000.0
    DEFAULT_AGGRESSIVE_MAX_MULTIPLE = 2.0
    DEFAULT_MARGIN_UTILIZATION = 0.6

    def report_adjusted_brt_cash(max_positions: int, **kwargs) -> float:
        init = float(kwargs.get("initial_capital", DEFAULT_INITIAL_CAPITAL) or DEFAULT_INITIAL_CAPITAL)
        mult = float(
            kwargs.get("aggressive_max_multiple", DEFAULT_AGGRESSIVE_MAX_MULTIPLE)
            or DEFAULT_AGGRESSIVE_MAX_MULTIPLE
        )
        util = float(kwargs.get("margin_utilization", DEFAULT_MARGIN_UTILIZATION) or DEFAULT_MARGIN_UTILIZATION)
        util = max(0.0, min(util, 1.0))
        mp = max(int(max_positions or 0), 1)
        return (init * mult * util) / mp

    def max_concurrent_positions(closed: list) -> int:
        events: list[tuple[pd.Timestamp, int]] = []
        for t in closed:
            dopen = pd.Timestamp(str(t.get("DATE_OPENED") if isinstance(t, dict) else t.date_opened)[:10])
            dclose = pd.Timestamp(str(t.get("DATE_CLOSED") if isinstance(t, dict) else t.date_closed)[:10])
            events.append((dopen, 1))
            events.append((dclose, -1))
        if not events:
            return 0
        events.sort(key=lambda x: (x[0], -x[1]))
        cur = mx = 0
        for _, delta in events:
            cur += delta
            mx = max(mx, cur)
        return mx

PREFERRED_PEERS = (
    "BRT",
    "YH",
    "RS",
    "WPBR",
    "RL",
    "MTS",
    "VZ",
    "QULL",
    "KELL",
    "CS",
    "IND",
)
SKIP_IF_WPBR = frozenset({"PBR"})
SYSTEM_LABELS = {
    "SB": "StockBee (SB)",
    "BRT": "Breakout / BRT",
    "YH": "YH",
    "RS": "Relative Strength (RS)",
    "WPBR": "WPBR",
    "RL": "Rocket Launcher (RL)",
    "MTS": "MTS",
    "MVCP": "Minervini VCP (MVCP, retired)",
    "VZ": "Volume Zone (VZ)",
    "QULL": "Qullamaggie (QULL)",
    "KELL": "Kell (KELL)",
    "CS": "CAN SLIM (CS)",
    "IND": "Indicators (IND)",
    "PBR": "PBR (legacy WPBR)",
}

DAYS_PER_YEAR = 365.0

_ENTRY_DATE_ALIASES = ("DATE_OPENED", "DATE OPENED", "ENTRY_DATE", "BUY_DATE", "OPEN_DATE")
_EXIT_DATE_ALIASES = ("DATE_CLOSED", "DATE CLOSED", "EXIT_DATE", "CLOSE_DATE", "SELL_DATE")
_ENTRY_PRICE_ALIASES = ("ENTRY_PRICE", "ENTRY PRICE", "BUY_PRICE", "OPEN_PRICE")
_EXIT_PRICE_ALIASES = ("EXIT_PRICE", "EXIT PRICE", "SELL_PRICE", "CLOSE_PRICE")
_PNL_PCT_ALIASES = ("PNL_PCT", "PNL %", "GainPct", "PNL")
_SYMBOL_ALIASES = ("SYMBOL", "TICKER", "SYM")
_SIDE_ALIASES = ("SIDE",)

_STAMP_RE = re.compile(r"^([A-Za-z]+)_Closed_(\d{12})\.csv$", re.I)
# Allow engine-specific stamps like 260803qep1 / 260802kell01 / 260803fund1
_STAMP_RE_ALT = re.compile(r"^([A-Za-z]+)_Closed_(\d{6}[A-Za-z0-9]{1,12})\.csv$", re.I)
_LATEST_RE = re.compile(r"^([A-Za-z]+)_LatestRun_Closed\.csv$", re.I)


def _closed_stamp(name: str) -> Optional[tuple[str, str]]:
    """Return (SYSTEM, stamp) for a valid Closed filename; skip mirrors / variants."""
    if "_RL_" in name.upper():
        return None
    m = _STAMP_RE.match(name) or _STAMP_RE_ALT.match(name)
    if not m:
        return None
    stamp = m.group(2)
    # Reject multi-token stamps like SecondChanceOnly_260722...
    if "_" in stamp:
        return None
    return m.group(1).upper(), stamp


def _latest_stamped_closed(drive: Path, system: str) -> Optional[Path]:
    """Newest stamped {SYS}_Closed_<stamp>.csv by stamp token (then mtime)."""
    best: Optional[tuple[str, float, Path]] = None
    for p in drive.glob(f"{system}_Closed_*.csv"):
        parsed = _closed_stamp(p.name)
        if not parsed or parsed[0] != system.upper():
            continue
        stamp = parsed[1]
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if best is None or (stamp, mt) > (best[0], best[1]):
            best = (stamp, mt, p)
    return best[2] if best else None


def _find_stamp_twin(drive: Path, system: str, latest: Path) -> Optional[str]:
    try:
        ls = latest.stat().st_size
        lm = latest.stat().st_mtime
    except OSError:
        return None
    candidates: list[tuple[float, str]] = []
    for p in drive.glob(f"{system}_Closed_*.csv"):
        parsed = _closed_stamp(p.name)
        if not parsed or parsed[0] != system.upper():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size != ls:
            continue
        candidates.append((abs(st.st_mtime - lm), p.name))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    return candidates[0][1]


@dataclass
class SourceFile:
    system: str
    path: Path
    stamp_twin: Optional[str]
    n_rows: int
    note: str = ""


@dataclass
class Trade:
    system: str
    symbol: str
    side: str
    entry_date: date
    exit_date: date
    entry_price: Optional[float]
    exit_price: Optional[float]
    pnl_pct: Optional[float]
    row_ix: int


@dataclass
class SecondSignalTrade:
    symbol: str
    peer: str
    side: str
    entry_date: date
    entry_price: float
    entry_system: str
    exit_date: date
    exit_price: float
    exit_system: str
    days_held: int
    pnl_pct: float
    sb_buy_date: date
    peer_buy_date: date
    same_day_entry: bool


def _resolve_drive(drive: Path) -> Path:
    d = drive.resolve()
    if d.is_dir():
        return d
    for alt in (ROOT / "drive", ROOT / "Drive"):
        if alt.is_dir():
            return alt.resolve()
    raise FileNotFoundError(f"Drive folder not found: {drive}")


def _parse_date(v) -> Optional[date]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, pd.Timestamp):
        if pd.isna(v):
            return None
        return v.date()
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "nat"}:
        return None
    s_digits = s.replace("-", "").replace("/", "")[:8]
    if len(s_digits) == 8 and s_digits.isdigit():
        try:
            return date(int(s_digits[:4]), int(s_digits[4:6]), int(s_digits[6:8]))
        except ValueError:
            return None
    try:
        ts = pd.to_datetime(s, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def _parse_float(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _pick_col(columns: list[str], aliases: tuple[str, ...]) -> Optional[str]:
    upper = {c.upper().strip(): c for c in columns}
    for a in aliases:
        if a.upper() in upper:
            return upper[a.upper()]
    norm = {re.sub(r"[\s_]+", "", c.upper()): c for c in columns}
    for a in aliases:
        key = re.sub(r"[\s_]+", "", a.upper())
        if key in norm:
            return norm[key]
    return None


def resolve_closed_source(drive: Path, system: str) -> Optional[SourceFile]:
    """
    Prefer current stamped Closed (what DailyRun/copy_latest would promote).

    If *_LatestRun_Closed.csv matches that stamp (same size), use LatestRun path
    and record the stamp twin. If LatestRun is stale/missing, use the stamped file
    directly and note the stale LatestRun.
    """
    stamped = _latest_stamped_closed(drive, system)
    latest = drive / f"{system}_LatestRun_Closed.csv"
    if stamped is None and not latest.is_file():
        return None

    if stamped is not None:
        twin_name = stamped.name
        try:
            stamped_size = stamped.stat().st_size
        except OSError:
            stamped_size = -1
        if latest.is_file():
            try:
                ls = latest.stat().st_size
            except OSError:
                ls = -2
            if ls == stamped_size:
                path = latest
                note = f"LatestRun matches stamp twin {twin_name}"
            else:
                path = stamped
                note = (
                    f"LatestRun stale/mismatched (size {ls}); "
                    f"using current stamp {twin_name}"
                )
        else:
            path = stamped
            note = f"LatestRun missing; using stamp {twin_name}"
    else:
        path = latest
        twin_name = _find_stamp_twin(drive, system, latest)
        note = f"no stamped Closed; LatestRun only (twin={twin_name})"

    try:
        n = max(0, sum(1 for _ in path.open("r", encoding="utf-8", errors="replace")) - 1)
    except OSError:
        n = 0
    return SourceFile(
        system=system,
        path=path,
        stamp_twin=twin_name if stamped is not None else _find_stamp_twin(drive, system, path),
        n_rows=n,
        note=note,
    )


def discover_latest_closed(drive: Path) -> dict[str, SourceFile]:
    """Discover systems from LatestRun and/or stamped Closed files."""
    systems: set[str] = set()
    for p in drive.glob("*_LatestRun_Closed.csv"):
        m = _LATEST_RE.match(p.name)
        if m:
            systems.add(m.group(1).upper())
    for p in drive.glob("*_Closed_*.csv"):
        parsed = _closed_stamp(p.name)
        if parsed:
            systems.add(parsed[0])

    found: dict[str, SourceFile] = {}
    for system in sorted(systems):
        src = resolve_closed_source(drive, system)
        if src is not None:
            found[system] = src
    return found


def _source_from_path(system: str, path: Path, note: str = "") -> SourceFile:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{system}: closed file not found: {path}")
    try:
        n = max(0, sum(1 for _ in path.open("r", encoding="utf-8", errors="replace")) - 1)
    except OSError:
        n = 0
    twin = path.name if _closed_stamp(path.name) else None
    return SourceFile(
        system=system.upper(),
        path=path,
        stamp_twin=twin,
        n_rows=n,
        note=note or f"explicit closed-map path {path.name}",
    )


def load_closed_map(map_path: Path, drive: Path) -> dict[str, SourceFile]:
    """
    Load an explicit system→Closed mapping.

    Accepts:
      - JSON object: {"SB": "drive/SB_Closed_….csv"} or {"SB": {"closed": "…", "stamp": "…"}}
      - JSON list of {"system","closed"|"stamp"|"path"}
      - text/CSV lines: SYS=path_or_stamp  OR  SYS,path_or_stamp
    Paths may be absolute or relative to repo / drive.
    Stamp tokens resolve to drive/{SYS}_Closed_{stamp}.csv.
    """
    map_path = map_path.resolve()
    if not map_path.is_file():
        raise FileNotFoundError(f"--closed-map not found: {map_path}")
    raw = map_path.read_text(encoding="utf-8").strip()
    entries: dict[str, str] = {}

    def _add(sys: str, val: str) -> None:
        sys_u = sys.strip().upper()
        val_s = str(val).strip().strip('"').strip("'")
        if sys_u and val_s:
            entries[sys_u] = val_s

    if raw.startswith("{") or raw.startswith("["):
        data = json.loads(raw)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    val = v.get("closed") or v.get("path") or v.get("stamp") or ""
                else:
                    val = v
                _add(str(k), str(val))
        elif isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                sys = item.get("system") or item.get("sys") or item.get("name")
                val = item.get("closed") or item.get("path") or item.get("stamp") or ""
                if sys:
                    _add(str(sys), str(val))
    else:
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                sys, val = line.split("=", 1)
            elif "," in line:
                sys, val = line.split(",", 1)
            elif "\t" in line:
                sys, val = line.split("\t", 1)
            else:
                continue
            if sys.strip().lower() in ("system", "sys", "name"):
                continue
            _add(sys, val)

    found: dict[str, SourceFile] = {}
    for sys, val in entries.items():
        p = Path(val)
        if not p.is_file():
            cand = (ROOT / val).resolve()
            if cand.is_file():
                p = cand
            else:
                cand2 = (drive / val).resolve()
                if cand2.is_file():
                    p = cand2
                elif not any(ch in val for ch in ("/", "\\", ".")):
                    # bare stamp token
                    p = (drive / f"{sys}_Closed_{val}.csv").resolve()
                else:
                    p = cand2
        found[sys] = _source_from_path(sys, p, note=f"closed-map -> {p.name}")
    return found


def second_signal_agg_name(out_prefix: str) -> str:
    """LatestRun keeps legacy name; other prefixes append _<prefix>."""
    if out_prefix == "LatestRun":
        return "SB_System_Convergence_SecondSignal_Agg.csv"
    return f"SB_System_Convergence_SecondSignal_Agg_{out_prefix}.csv"


def load_trades(src: SourceFile) -> list[Trade]:
    df = pd.read_csv(src.path, low_memory=False)
    cols = list(df.columns)
    sym_c = _pick_col(cols, _SYMBOL_ALIASES)
    entry_d = _pick_col(cols, _ENTRY_DATE_ALIASES)
    exit_d = _pick_col(cols, _EXIT_DATE_ALIASES)
    entry_p = _pick_col(cols, _ENTRY_PRICE_ALIASES)
    exit_p = _pick_col(cols, _EXIT_PRICE_ALIASES)
    pnl_c = _pick_col(cols, _PNL_PCT_ALIASES)
    side_c = _pick_col(cols, _SIDE_ALIASES)
    if not sym_c or not entry_d or not exit_d:
        raise ValueError(
            f"{src.path.name}: missing required columns "
            f"(need SYMBOL + entry/exit dates); have {cols[:12]}..."
        )
    trades: list[Trade] = []
    for i, row in df.iterrows():
        symbol = str(row.get(sym_c, "")).strip().upper()
        if not symbol or symbol in {"NAN", "NONE", "SYMBOL"}:
            continue
        ed = _parse_date(row.get(entry_d))
        xd = _parse_date(row.get(exit_d))
        if not ed or not xd:
            continue
        if xd < ed:
            ed, xd = xd, ed
        side = str(row.get(side_c, "LONG") if side_c else "LONG").strip().upper() or "LONG"
        trades.append(
            Trade(
                system=src.system,
                symbol=symbol,
                side=side,
                entry_date=ed,
                exit_date=xd,
                entry_price=_parse_float(row.get(entry_p)) if entry_p else None,
                exit_price=_parse_float(row.get(exit_p)) if exit_p else None,
                pnl_pct=_parse_float(row.get(pnl_c)) if pnl_c else None,
                row_ix=int(i) if isinstance(i, (int, float)) else 0,
            )
        )
    return trades


def _ranges_overlap(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


def _overlap_days(a0: date, a1: date, b0: date, b1: date) -> int:
    start = max(a0, b0)
    end = min(a1, b1)
    if end < start:
        return 0
    return (end - start).days + 1


def find_overlap_pairs(sb: list[Trade], other: list[Trade]) -> list[tuple[Trade, Trade]]:
    by_sym: dict[str, list[Trade]] = {}
    for t in other:
        by_sym.setdefault(t.symbol, []).append(t)
    for lst in by_sym.values():
        lst.sort(key=lambda t: (t.entry_date, t.exit_date, t.row_ix))
    pairs: list[tuple[Trade, Trade]] = []
    for a in sb:
        peers = by_sym.get(a.symbol)
        if not peers:
            continue
        for b in peers:
            if _ranges_overlap(a.entry_date, a.exit_date, b.entry_date, b.exit_date):
                pairs.append((a, b))
    return pairs


def overlap_pair_to_row(a: Trade, b: Trade) -> dict:
    return {
        "system_a": a.system,
        "system_b": b.system,
        "symbol": a.symbol,
        "side_a": a.side,
        "side_b": b.side,
        "sb_buy_date": a.entry_date.isoformat(),
        "sb_entry_price": a.entry_price,
        "sb_exit_date": a.exit_date.isoformat(),
        "sb_exit_price": a.exit_price,
        "sb_pnl_pct": a.pnl_pct,
        "b_buy_date": b.entry_date.isoformat(),
        "b_entry_price": b.entry_price,
        "b_exit_date": b.exit_date.isoformat(),
        "b_exit_price": b.exit_price,
        "b_pnl_pct": b.pnl_pct,
        "hold_overlap_days": _overlap_days(a.entry_date, a.exit_date, b.entry_date, b.exit_date),
        "entry_date_delta_days": (b.entry_date - a.entry_date).days,
        "same_day_entry": a.entry_date == b.entry_date,
    }


def summarize(rows: list[dict], peers: list[str]) -> list[dict]:
    out = []
    for peer in peers:
        subset = [r for r in rows if r["system_b"] == peer]
        out.append(
            {
                "pair": f"SB x {peer}",
                "system_b": peer,
                "n_overlapping_trades": len(subset),
                "n_unique_symbols": len({r["symbol"] for r in subset}),
                "n_same_day_entry": sum(1 for r in subset if r["same_day_entry"]),
            }
        )
    return out


def build_second_signal(a: Trade, b: Trade) -> Optional[SecondSignalTrade]:
    """Build one second-signal trade from an SB x peer overlap pair."""
    # Later buy date = second signal. Same-day: prefer peer (confirmation).
    if a.entry_date < b.entry_date:
        second, first = b, a
    elif b.entry_date < a.entry_date:
        second, first = a, b
    else:
        second, first = b, a  # tie -> peer

    if second.entry_price is None or second.entry_price <= 0:
        return None

    # Exit = earlier exit among sides still open on/after second entry.
    still_open = [t for t in (a, b) if t.exit_date >= second.entry_date]
    if still_open:
        exit_side = min(still_open, key=lambda t: (t.exit_date, t.system))
    else:
        # Degenerate: both closed before second entry — use later exit of the two.
        exit_side = max([a, b], key=lambda t: t.exit_date)

    if exit_side.exit_price is None or exit_side.exit_price <= 0:
        return None
    if exit_side.exit_date < second.entry_date:
        return None

    side = (second.side or "LONG").upper()
    ep, xp = float(second.entry_price), float(exit_side.exit_price)
    if side.startswith("S"):  # SHORT
        pnl_pct = (ep - xp) / ep * 100.0
    else:
        pnl_pct = (xp - ep) / ep * 100.0

    days = (exit_side.exit_date - second.entry_date).days
    if days < 0:
        return None
    # Same-day entry/exit -> 1 day (matches engine habit for Ann_ROR divisors).
    days_held = max(days, 1)

    return SecondSignalTrade(
        symbol=a.symbol,
        peer=b.system,
        side=side,
        entry_date=second.entry_date,
        entry_price=ep,
        entry_system=second.system,
        exit_date=exit_side.exit_date,
        exit_price=xp,
        exit_system=exit_side.system,
        days_held=days_held,
        pnl_pct=pnl_pct,
        sb_buy_date=a.entry_date,
        peer_buy_date=b.entry_date,
        same_day_entry=a.entry_date == b.entry_date,
    )


def dedupe_second_signal(trades: list[SecondSignalTrade]) -> list[SecondSignalTrade]:
    """Unique by (symbol, second_entry_date); keep earliest exit, then peer name."""
    best: dict[tuple[str, date], SecondSignalTrade] = {}
    for t in trades:
        key = (t.symbol, t.entry_date)
        prev = best.get(key)
        if prev is None:
            best[key] = t
            continue
        if (t.exit_date, t.peer) < (prev.exit_date, prev.peer):
            best[key] = t
    out = list(best.values())
    out.sort(key=lambda t: (t.entry_date, t.exit_date, t.symbol, t.peer))
    return out


def _trade_pnl_pct(t: Trade) -> Optional[float]:
    """
    Closed PNL as percent points (e.g. 11.86 for +11.86%).

    Prefer price-derived % (same as second-signal path). Some books (QULL, KELL)
    store PNL_PCT as a unit fraction (0.1186); scale those when prices are missing.
    """
    if t.entry_price is not None and t.exit_price is not None and float(t.entry_price) > 0:
        ep, xp = float(t.entry_price), float(t.exit_price)
        side = (t.side or "LONG").upper()
        if side.startswith("S"):
            return (ep - xp) / ep * 100.0
        return (xp - ep) / ep * 100.0
    if t.pnl_pct is None:
        return None
    stored = float(t.pnl_pct)
    # Unit-fraction Closed (abs <= 1) without usable prices
    if abs(stored) <= 1.0:
        return stored * 100.0
    return stored


def trades_to_metric_rows(trades: list[Trade]) -> list[SecondSignalTrade]:
    """
    Map a system's standalone Closed trades into SecondSignalTrade rows so
    aggregate_second_signal can reuse the same capital / metric formulas.
    """
    out: list[SecondSignalTrade] = []
    for t in trades:
        pnl = _trade_pnl_pct(t)
        if pnl is None:
            continue
        days = (t.exit_date - t.entry_date).days
        days_held = max(days, 1)
        ep = float(t.entry_price) if t.entry_price is not None else 0.0
        xp = float(t.exit_price) if t.exit_price is not None else 0.0
        out.append(
            SecondSignalTrade(
                symbol=t.symbol,
                peer=t.system,
                side=(t.side or "LONG").upper(),
                entry_date=t.entry_date,
                entry_price=ep,
                entry_system=t.system,
                exit_date=t.exit_date,
                exit_price=xp,
                exit_system=t.system,
                days_held=days_held,
                pnl_pct=pnl,
                sb_buy_date=t.entry_date,
                peer_buy_date=t.entry_date,
                same_day_entry=True,
            )
        )
    out.sort(key=lambda x: (x.entry_date, x.exit_date, x.symbol))
    return out


def _realized_max_dd_pct(trades: list[SecondSignalTrade], brt_cash: float, initial_capital: float) -> float:
    """Peak-to-trough drawdown % on cumulative realized PNL equity (no OHLC MTM)."""
    if not trades or brt_cash <= 0:
        return 0.0
    events: dict[date, float] = {}
    for t in trades:
        pnl_d = (t.pnl_pct / 100.0) * brt_cash
        events[t.exit_date] = events.get(t.exit_date, 0.0) + pnl_d
    equity = float(initial_capital)
    peak = equity
    max_dd = 0.0
    for d in sorted(events):
        equity += events[d]
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def aggregate_second_signal(
    trades: list[SecondSignalTrade],
    *,
    bucket: str,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    max_multiple: float = DEFAULT_AGGRESSIVE_MAX_MULTIPLE,
    margin_util: float = DEFAULT_MARGIN_UTILIZATION,
    days_per_year: float = DAYS_PER_YEAR,
) -> dict:
    """Summary-style metrics for a second-signal trade list (already deduped)."""
    empty = {
        "bucket": bucket,
        "total_trades": 0,
        "win_rate_pct": 0.0,
        "avg_profit_pct": 0.0,
        "Ann_ROR": 0.0,
        "avg_days_in_trade": 0.0,
        "Total_PNL": 0.0,
        "Drawdown": 0.0,
        "profit_factor": 0.0,
        "losing_streak": 0,
        "p90_days": 0,
        "brt_cash": 0.0,
        "Max_Positions": 0,
        "wins": 0,
        "losses": 0,
        "bes": 0,
        "n_before_dedupe_note": "",
    }
    if not trades:
        return empty

    # Max concurrent using host helper (expects DATE_OPENED/DATE_CLOSED attrs or dicts)
    closed_for_pos = [
        {
            "DATE_OPENED": t.entry_date.isoformat(),
            "DATE_CLOSED": t.exit_date.isoformat(),
            "date_opened": t.entry_date.isoformat(),
            "date_closed": t.exit_date.isoformat(),
        }
        for t in trades
    ]
    max_pos = max(max_concurrent_positions(closed_for_pos), 1)
    brt_cash = report_adjusted_brt_cash(
        max_pos,
        initial_capital=initial_capital,
        aggressive_max_multiple=max_multiple,
        margin_utilization=margin_util,
    )

    # Chronological by entry (matches typical closed-book streak iteration)
    ordered = sorted(trades, key=lambda t: (t.entry_date, t.exit_date, t.symbol))
    wins = sum(1 for t in ordered if t.pnl_pct > 0)
    losses = sum(1 for t in ordered if t.pnl_pct < 0)
    bes = sum(1 for t in ordered if t.pnl_pct == 0)
    n = len(ordered)
    win_rate = wins / n * 100.0 if n else 0.0
    avg_pnl_pct = sum(t.pnl_pct for t in ordered) / n if n else 0.0

    pnl_dollars = [(t.pnl_pct / 100.0) * brt_cash for t in ordered]
    total_pnl = sum(pnl_dollars)
    sum_wins = sum(d for d, t in zip(pnl_dollars, ordered) if t.pnl_pct > 0)
    sum_losses = abs(sum(d for d, t in zip(pnl_dollars, ordered) if t.pnl_pct < 0))
    pf = sum_wins / sum_losses if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0.0)

    days_held = [t.days_held for t in ordered if t.days_held > 0]
    avg_days = sum(days_held) / len(days_held) if days_held else 0.0
    if len(days_held) >= 10:
        p90 = sorted(days_held)[int(len(days_held) * 0.9) - 1]
    else:
        p90 = max(days_held) if days_held else 0

    ann_ror = 0.0
    if avg_days > 0 and n > 0 and brt_cash > 0:
        base = 1.0 + total_pnl / (brt_cash * n)
        if base > 0:
            ann_ror = (base ** (days_per_year / avg_days) - 1.0) * 100.0

    max_streak = cur = 0
    for t in ordered:
        if t.pnl_pct < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    max_dd = _realized_max_dd_pct(ordered, brt_cash, initial_capital)

    return {
        "bucket": bucket,
        "total_trades": n,
        "win_rate_pct": round(win_rate, 2),
        "avg_profit_pct": round(avg_pnl_pct, 2),
        "Ann_ROR": round(ann_ror, 2),
        "avg_days_in_trade": round(avg_days, 1),
        "Total_PNL": round(total_pnl, 2),
        "Drawdown": round(max_dd, 2),
        "profit_factor": round(pf, 2),
        "losing_streak": int(max_streak),
        "p90_days": int(p90),
        "brt_cash": round(brt_cash, 2),
        "Max_Positions": int(max_pos),
        "wins": wins,
        "losses": losses,
        "bes": bes,
        "n_before_dedupe_note": "",
    }


def _fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v:+.2f}%"


def _pnl_class(v: Optional[float]) -> str:
    if v is None:
        return ""
    if v > 0:
        return "pos"
    if v < 0:
        return "neg"
    return ""


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
    if (!s || s === "—" || s === "-" || s === "") return type === "text" ? "" : 0;
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

_AGG_COLS = [
    ("Bucket", "text", "bucket"),
    ("Total trades", "num", "total_trades"),
    ("Win rate %", "num", "win_rate_pct"),
    ("Avg profit %", "num", "avg_profit_pct"),
    ("Ann_ROR", "num", "Ann_ROR"),
    ("Avg days", "num", "avg_days_in_trade"),
    ("Total_PNL", "num", "Total_PNL"),
    ("Drawdown %", "num", "Drawdown"),
    ("Profit factor", "num", "profit_factor"),
    ("Losing streak", "num", "losing_streak"),
    ("p90 days", "num", "p90_days"),
    ("brt_cash", "num", "brt_cash"),
    ("Max_Positions", "num", "Max_Positions"),
]


def render_html(
    *,
    summary: list[dict],
    detail: list[dict],
    agg_rows: list[dict],
    sources: list[SourceFile],
    missing: list[str],
    gen_ts: str,
    sb_n: int,
    ss_raw_n: int,
    ss_deduped_n: int,
    out_prefix: str = "LatestRun",
) -> str:
    sum_head = "".join(
        [
            _sortable_th("Pair", "text"),
            _sortable_th("# Overlapping trades", "num"),
            _sortable_th("# Unique symbols", "num"),
            _sortable_th("# Same-day entry", "num"),
        ]
    )
    sum_body = ""
    tot_ov = tot_sd = 0
    all_syms: set[str] = set()
    for s in summary:
        tot_ov += s["n_overlapping_trades"]
        tot_sd += s["n_same_day_entry"]
        sum_body += (
            "<tr>"
            f"<td>{html_mod.escape(s['pair'])}</td>"
            f"<td>{s['n_overlapping_trades']}</td>"
            f"<td>{s['n_unique_symbols']}</td>"
            f"<td>{s['n_same_day_entry']}</td>"
            "</tr>"
        )
    for r in detail:
        all_syms.add(r["symbol"])
    sum_foot = (
        f'<tr class="total-row"><td><strong>All SB x peers (rows)</strong></td>'
        f"<td><strong>{tot_ov}</strong></td>"
        f"<td><strong>{len(all_syms)}</strong> <span class=\"small\">(unique across pairs)</span></td>"
        f"<td><strong>{tot_sd}</strong></td></tr>"
    )

    det_cols = [
        ("System A", "text", "system_a"),
        ("System B", "text", "system_b"),
        ("Symbol", "text", "symbol"),
        ("SB buy date", "date", "sb_buy_date"),
        ("SB entry $", "num", "sb_entry_price"),
        ("SB exit date", "date", "sb_exit_date"),
        ("SB exit $", "num", "sb_exit_price"),
        ("SB PNL%", "num", "sb_pnl_pct"),
        ("B buy date", "date", "b_buy_date"),
        ("B entry $", "num", "b_entry_price"),
        ("B exit date", "date", "b_exit_date"),
        ("B exit $", "num", "b_exit_price"),
        ("B PNL%", "num", "b_pnl_pct"),
        ("Hold overlap days", "num", "hold_overlap_days"),
        ("Entry delta days", "num", "entry_date_delta_days"),
        ("Same-day entry", "text", "same_day_entry"),
    ]
    det_head = "".join(_sortable_th(lab, typ) for lab, typ, _ in det_cols)
    det_body = ""
    for r in detail:
        cells = []
        for _lab, _typ, key in det_cols:
            v = r[key]
            if key.endswith("_price"):
                cells.append(f"<td>{_fmt_price(v)}</td>")
            elif key.endswith("pnl_pct"):
                cells.append(f'<td class="{_pnl_class(v)}">{_fmt_pct(v)}</td>')
            elif key == "same_day_entry":
                cells.append(f"<td>{'Y' if v else ''}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v) if v is not None else '-')}</td>")
        det_body += "<tr>" + "".join(cells) + "</tr>"

    agg_head = "".join(_sortable_th(lab, typ) for lab, typ, _ in _AGG_COLS)
    agg_body = ""
    for r in agg_rows:
        cells = []
        for _lab, _typ, key in _AGG_COLS:
            v = r.get(key)
            if key in ("win_rate_pct", "avg_profit_pct", "Ann_ROR", "Drawdown"):
                cls = _pnl_class(v if key != "Drawdown" else (-v if isinstance(v, (int, float)) else None))
                if key == "Drawdown":
                    cells.append(f"<td>{v:.2f}%</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>")
                elif key == "win_rate_pct":
                    cells.append(f"<td>{v:.2f}%</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>")
                else:
                    cells.append(
                        f'<td class="{cls}">{v:+.2f}%</td>'
                        if isinstance(v, (int, float))
                        else f"<td>{v}</td>"
                    )
            elif key == "Total_PNL":
                cells.append(
                    f'<td class="{_pnl_class(v)}">{v:,.2f}</td>'
                    if isinstance(v, (int, float))
                    else f"<td>{v}</td>"
                )
            elif key == "brt_cash":
                cells.append(f"<td>{v:,.2f}</td>" if isinstance(v, (int, float)) else f"<td>{v}</td>")
            elif key == "bucket":
                bold = (
                    "total-row"
                    if str(v).startswith("ALL")
                    else ("standalone" if "(standalone)" in str(v) else "")
                )
                if bold == "total-row":
                    cells.append(f"<td><strong>{html_mod.escape(str(v))}</strong></td>")
                else:
                    cells.append(f"<td>{html_mod.escape(str(v))}</td>")
            else:
                cells.append(f"<td>{html_mod.escape(str(v))}</td>")
        bkt = str(r.get("bucket", ""))
        if bkt.startswith("ALL"):
            row_cls = ' class="total-row"'
        elif "(standalone)" in bkt:
            row_cls = ' class="standalone-row"'
        else:
            row_cls = ""
        agg_body += f"<tr{row_cls}>" + "".join(cells) + "</tr>"

    src_li = ""
    for s in sources:
        twin = s.stamp_twin or "(none)"
        label = SYSTEM_LABELS.get(s.system, s.system)
        src_li += (
            f"<li><strong>{html_mod.escape(s.system)}</strong> "
            f"({html_mod.escape(label)}): "
            f"<code>{html_mod.escape(s.path.name)}</code> - {s.n_rows} rows; "
            f"stamp twin <code>{html_mod.escape(twin)}</code></li>"
        )
    miss_html = ""
    if missing:
        miss_html = (
            "<p class=\"small\">Skipped / not found on disk: "
            + ", ".join(html_mod.escape(m) for m in missing)
            + "</p>"
        )

    deployable = DEFAULT_INITIAL_CAPITAL * DEFAULT_AGGRESSIVE_MAX_MULTIPLE * DEFAULT_MARGIN_UTILIZATION

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SB System Convergence - {html_mod.escape(out_prefix)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1400px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.small {{ font-size:12px; color:#64748b; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
tr.standalone-row td {{ background:#f0fdf4; }}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
ul.sources {{ font-size:12px; color:#475569; line-height:1.7; }}
.def {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:12px 0 20px; font-size:0.92rem; line-height:1.5; }}
</style></head><body>
<h1>SB System Convergence - {html_mod.escape(out_prefix)}</h1>
<p class="sub">
  Historical hold-period overlap between StockBee (SB) closed trades and peer systems,
  using each system's Closed book (LatestRun / stamp twin / closed-map).
  Generated {html_mod.escape(gen_ts)}. SB closed trades loaded: {sb_n}.
</p>

<div class="def">
  <strong>Overlap definition (primary):</strong> same <em>SYMBOL</em>, and position date ranges
  intersect - SB <code>DATE_OPENED..DATE_CLOSED</code> overlaps peer
  <code>DATE_OPENED..DATE_CLOSED</code> (inclusive calendar days).<br>
  <strong>Same-day entry subset:</strong> overlapping rows where SB buy date equals peer buy date
  (flagged in detail; counted in summary).
</div>

<section>
<h2>Summary by system pair</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{sum_head}</tr></thead>
  <tbody>{sum_body}{sum_foot}</tbody>
</table>
</div>
{miss_html}
</section>

<section>
<h2>Aggregates (standalone + second-signal)</h2>
<div class="def">
  <strong>Table order:</strong>
  (1) each system's <em>standalone</em> Closed book,
  (2) SB × peer second-signal overlaps,
  (3) ALL PEERS deduped.<br>
  <strong>Standalone:</strong> full Closed from the same LatestRun / stamp twin listed under Data sources
  (native entry→exit, that system's own PNL%). Same metric columns / capital model as second-signal
  rows for apples-to-apples comparison.<br>
  <strong>Second-signal strategy:</strong> wait for confirmation (second buy), then ride until the first exit of either system.<br>
  <strong>Entry:</strong> later of the two buy dates; price = that system's <code>ENTRY_PRICE</code>
  (same-day tie-break: prefer peer).<br>
  <strong>Exit:</strong> earlier exit date among sides still open on/after the second entry;
  use that side's exit price. If one side already exited before second entry, use the remaining open side.<br>
  <strong>Dedupe:</strong> per second-signal bucket, unique by <code>(symbol, second_entry_date)</code>; keep earliest exit
  (then peer name). All-peers combined uses the same key across peers so one SB lot is not triple-counted.
  Raw second-signal rows before all-peers dedupe: {ss_raw_n}; after: {ss_deduped_n}.<br>
  <strong>Capital (all rows):</strong> initial_capital={DEFAULT_INITIAL_CAPITAL:,.0f},
  max_multiple={DEFAULT_AGGRESSIVE_MAX_MULTIPLE}, margin_util={DEFAULT_MARGIN_UTILIZATION}
  (deployable {deployable:,.0f}).
  <code>brt_cash</code> = deployable / Max_Positions (host Closed sizing via <code>tbn_host_sizing</code>).
  <code>Total_PNL</code> = sum(pnl% × brt_cash).
  <code>Ann_ROR</code> / win rate / PF / losing streak / p90 days match <code>rocket_tbn.compute_metrics</code> formulas.
  <code>Drawdown</code> = max peak-to-trough % on cumulative <em>realized</em> equity (no OHLC MTM).<br>
  <strong>Native Summary note:</strong> each system's <code>*_LatestRun_Summary.csv</code> is typically
  per-symbol with that engine's own notional (<code>TOTAL_PNL</code> / <code>SHEET_PNL</code>). Those dollars
  will <em>not</em> match these host-sized rows; use this table for cross-system comparability.
</div>
<p class="small">Click column headers to sort. Standalone rows highlighted; ALL PEERS (deduped) pinned as total.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{agg_head}</tr></thead>
  <tbody>{agg_body if agg_body else '<tr><td colspan="13">No aggregate trades.</td></tr>'}</tbody>
</table>
</div>
</section>

<section>
<h2>Overlap detail</h2>
<p class="small">One row per SB x peer trade pair with intersecting hold ranges. Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>{det_head}</tr></thead>
  <tbody>{det_body if det_body else '<tr><td colspan="16">No overlapping trades.</td></tr>'}</tbody>
</table>
</div>
</section>

<section>
<h2>Data sources</h2>
<ul class="sources">{src_li}</ul>
</section>
{_SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def render_md(
    *,
    summary: list[dict],
    agg_rows: list[dict],
    sources: list[SourceFile],
    missing: list[str],
    gen_ts: str,
    detail_n: int,
    sb_n: int,
    ss_raw_n: int,
    ss_deduped_n: int,
    out_prefix: str = "LatestRun",
) -> str:
    deployable = DEFAULT_INITIAL_CAPITAL * DEFAULT_AGGRESSIVE_MAX_MULTIPLE * DEFAULT_MARGIN_UTILIZATION
    lines = [
        f"# SB System Convergence - {out_prefix}",
        "",
        f"Generated: {gen_ts}",
        "",
        "## Overlap definition",
        "",
        "**Primary:** same `SYMBOL` (case-insensitive), and position date ranges **overlap**:",
        "SB `DATE_OPENED..DATE_CLOSED` intersects peer `DATE_OPENED..DATE_CLOSED`",
        "(inclusive calendar-day intervals).",
        "",
        "**Same-day entry subset:** overlapping rows where SB buy date == peer buy date.",
        "",
        f"SB closed trades loaded: **{sb_n}**. Detail overlap rows: **{detail_n}**.",
        "",
        "## Second-signal strategy",
        "",
        "For each overlap pair (same symbol, intersecting holds):",
        "",
        "1. **Entry** = later of the two buy dates (second signal).",
        "   Entry price = that system's `ENTRY_PRICE`.",
        "   Same-day tie-break: prefer the peer system's entry (confirmation outside SB).",
        "2. **Exit** = earlier exit among sides still open on/after the second entry",
        "   (first system to exit after confirmation), using that side's exit price.",
        "   If one side already exited before second entry, use the remaining open trade's exit.",
        "3. **Dedupe** (portfolio aggregates): unique by `(symbol, second_entry_date)`;",
        "   keep earliest exit (then peer name). Applied within each peer bucket and for",
        f"   all-peers combined. Raw second-signal rows: {ss_raw_n}; all-peers deduped: {ss_deduped_n}.",
        "",
        "### Capital / metrics",
        "",
        f"- `initial_capital`={DEFAULT_INITIAL_CAPITAL:,.0f}, "
        f"`aggressive_max_multiple`={DEFAULT_AGGRESSIVE_MAX_MULTIPLE}, "
        f"`margin_utilization`={DEFAULT_MARGIN_UTILIZATION}",
        f"  -> deployable **{deployable:,.0f}**",
        "- `Max_Positions` = peak concurrent holds in that bucket",
        "  (standalone = peak concurrent in that system's Closed book;",
        "  second-signal = peak concurrent second-signal holds)",
        "- `brt_cash` = deployable / Max_Positions (`tbn_host_sizing.report_adjusted_brt_cash`)",
        "- `Total_PNL` = sum(pnl_pct/100 * brt_cash)",
        "- `Ann_ROR`, win rate, profit factor, losing streak, p90 days:",
        "  same formulas as `rocket_tbn.compute_metrics`",
        "- `Drawdown` = max peak-to-trough % on cumulative realized equity (no OHLC MTM)",
        "- Native `*_LatestRun_Summary.csv` dollars use each engine's own notional and",
        "  are usually per-symbol — not directly comparable to these host-sized rows",
        "",
        "## Summary counts (overlap rows)",
        "",
        "| Pair | # Overlapping trades | # Unique symbols | # Same-day entry |",
        "|---|---:|---:|---:|",
    ]
    for s in summary:
        lines.append(
            f"| {s['pair']} | {s['n_overlapping_trades']} | "
            f"{s['n_unique_symbols']} | {s['n_same_day_entry']} |"
        )

    lines += [
        "",
        "## Aggregates (standalone + second-signal)",
        "",
        "Section order: **standalone systems** → **SB × peer second-signal** → **ALL PEERS (deduped)**.",
        "",
        "Standalone rows use each system's full Closed book (same LatestRun / stamp twin as Data sources)",
        "with the shared host capital model below — not that system's native Summary notional.",
        f"`*_LatestRun_Summary.csv` files are typically per-symbol with engine-native dollars",
        "(`TOTAL_PNL` / `SHEET_PNL`); those will not match these host-sized rows.",
        "",
        "| Bucket | Trades | Win% | Avg% | Ann_ROR | Avg days | Total_PNL | DD% | PF | Lose streak | p90 | brt_cash | Max_Pos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in agg_rows:
        lines.append(
            f"| {r['bucket']} | {r['total_trades']} | {r['win_rate_pct']} | "
            f"{r['avg_profit_pct']} | {r['Ann_ROR']} | {r['avg_days_in_trade']} | "
            f"{r['Total_PNL']} | {r['Drawdown']} | {r['profit_factor']} | "
            f"{r['losing_streak']} | {r['p90_days']} | {r['brt_cash']} | {r['Max_Positions']} |"
        )

    lines += [
        "",
        "## Closed files used",
        "",
        "| System | Closed file | Rows | Stamp twin |",
        "|---|---|---:|---|",
    ]
    for src in sources:
        twin = src.stamp_twin or "(none)"
        lines.append(f"| {src.system} | `{src.path.name}` | {src.n_rows} | `{twin}` |")
    if missing:
        lines += ["", "## Skipped / missing", "", ", ".join(f"`{m}`" for m in missing)]
    agg_name = second_signal_agg_name(out_prefix)
    lines += [
        "",
        "## Outputs",
        "",
        f"- `SB_System_Convergence_{out_prefix}.html`",
        f"- `SB_System_Convergence_{out_prefix}.csv` (overlap detail)",
        f"- `{agg_name}`",
        f"- `SB_System_Convergence_{out_prefix}.md` (this note)",
        "",
        "Re-run: `python tools/sb_system_convergence.py`",
        "",
        "Note: legacy `PBR_LatestRun_Closed.csv` is skipped when WPBR is present.",
        "",
    ]
    return "\n".join(lines)


def peer_order(systems: list[str]) -> list[str]:
    preferred = [s for s in PREFERRED_PEERS if s in systems]
    extras = sorted(s for s in systems if s not in preferred and s != "SB")
    return preferred + extras


def main() -> int:
    ap = argparse.ArgumentParser(description="SB vs peers LatestRun closed-trade convergence")
    ap.add_argument("--drive", type=Path, default=ROOT / "drive", help="drive/ folder")
    ap.add_argument("--out-dir", type=Path, default=None, help="output directory")
    ap.add_argument("--anchor", default="SB", help="anchor system (default SB)")
    ap.add_argument(
        "--out-prefix",
        default="LatestRun",
        help="output filename suffix (default LatestRun → SB_System_Convergence_LatestRun.*)",
    )
    ap.add_argument(
        "--closed-map",
        type=Path,
        default=None,
        help="explicit system→Closed path/stamp map (JSON/text); skips LatestRun discovery",
    )
    args = ap.parse_args()

    drive = _resolve_drive(args.drive)
    out_dir = (args.out_dir or (drive / "paul_experiments")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_prefix = str(args.out_prefix or "LatestRun").strip() or "LatestRun"

    if args.closed_map:
        discovered = load_closed_map(args.closed_map, drive)
    else:
        discovered = discover_latest_closed(drive)
    anchor = args.anchor.upper()
    if anchor not in discovered:
        raise SystemExit(
            f"Anchor {anchor} Closed not found under {drive}"
            + (f" (closed-map={args.closed_map})" if args.closed_map else "")
        )

    expected = list(PREFERRED_PEERS)
    missing = [s for s in expected if s not in discovered]
    # Prefer documented peer list only (skip incidental Closed books like DB).
    peers = [s for s in PREFERRED_PEERS if s in discovered and s != anchor]
    if "WPBR" in discovered:
        peers = [s for s in peers if s not in SKIP_IF_WPBR]

    print(f"Drive: {drive}")
    print(f"Out:   {out_dir}")
    print(f"Anchor {anchor}: {discovered[anchor].path.name} ({discovered[anchor].n_rows} rows)")
    print(f"  {discovered[anchor].note}")
    if discovered[anchor].stamp_twin:
        print(f"  stamp twin: {discovered[anchor].stamp_twin}")
    if missing:
        print(f"Missing expected peers: {', '.join(missing)}")

    sb_trades = load_trades(discovered[anchor])
    print(f"Loaded {len(sb_trades)} {anchor} trades with valid dates")

    all_detail: list[dict] = []
    all_ss: list[SecondSignalTrade] = []
    used_sources = [discovered[anchor]]
    ss_by_peer: dict[str, list[SecondSignalTrade]] = {p: [] for p in peers}
    trades_by_system: dict[str, list[Trade]] = {anchor: sb_trades}

    for peer in peers:
        src = discovered[peer]
        used_sources.append(src)
        try:
            trades = load_trades(src)
        except Exception as e:
            print(f"  SKIP {peer}: {e}")
            missing.append(f"{peer} (load error)")
            continue
        trades_by_system[peer] = trades
        pairs = find_overlap_pairs(sb_trades, trades)
        rows = [overlap_pair_to_row(a, b) for a, b in pairs]
        rows.sort(key=lambda r: (r["system_b"], r["symbol"], r["sb_buy_date"], r["b_buy_date"]))
        peer_ss: list[SecondSignalTrade] = []
        for a, b in pairs:
            ss = build_second_signal(a, b)
            if ss is not None:
                peer_ss.append(ss)
        all_detail.extend(rows)
        all_ss.extend(peer_ss)
        ss_by_peer[peer] = peer_ss
        print(
            f"  SB x {peer}: {len(rows)} overlaps, "
            f"{len({r['symbol'] for r in rows})} symbols, "
            f"{len(peer_ss)} second-signal "
            f"(peer trades={len(trades)}; twin={src.stamp_twin or 'n/a'})"
        )

    summary = summarize(all_detail, peers)

    # Aggregates: standalone systems → per peer second-signal → all peers combined
    standalone_order = [anchor] + [p for p in peers if p in trades_by_system]
    agg_rows: list[dict] = []
    for sys_name in standalone_order:
        raw_tr = trades_by_system.get(sys_name, [])
        metric_rows = trades_to_metric_rows(raw_tr)
        label = SYSTEM_LABELS.get(sys_name, sys_name)
        m = aggregate_second_signal(metric_rows, bucket=f"{sys_name} (standalone)")
        m["n_before_dedupe_note"] = (
            f"standalone Closed n={len(raw_tr)} metric_rows={len(metric_rows)}; {label}"
        )
        agg_rows.append(m)
        print(
            f"  standalone {sys_name}: trades={m['total_trades']} "
            f"WR={m['win_rate_pct']}% Ann_ROR={m['Ann_ROR']}% "
            f"MaxPos={m['Max_Positions']} brt_cash={m['brt_cash']}"
        )

    for peer in peers:
        raw = ss_by_peer.get(peer, [])
        ded = dedupe_second_signal(raw)
        m = aggregate_second_signal(ded, bucket=f"SB x {peer}")
        m["n_before_dedupe_note"] = f"{len(raw)}->{len(ded)}"
        agg_rows.append(m)

    all_deduped = dedupe_second_signal(all_ss)
    all_metrics = aggregate_second_signal(all_deduped, bucket="ALL PEERS (deduped)")
    all_metrics["n_before_dedupe_note"] = f"{len(all_ss)}->{len(all_deduped)}"
    agg_rows.append(all_metrics)

    gen_ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    csv_path = out_dir / f"SB_System_Convergence_{out_prefix}.csv"
    agg_csv_path = out_dir / second_signal_agg_name(out_prefix)
    html_path = out_dir / f"SB_System_Convergence_{out_prefix}.html"
    md_path = out_dir / f"SB_System_Convergence_{out_prefix}.md"

    detail_df = pd.DataFrame(all_detail)
    if detail_df.empty:
        detail_df = pd.DataFrame(
            columns=[
                "system_a", "system_b", "symbol", "side_a", "side_b",
                "sb_buy_date", "sb_entry_price", "sb_exit_date", "sb_exit_price", "sb_pnl_pct",
                "b_buy_date", "b_entry_price", "b_exit_date", "b_exit_price", "b_pnl_pct",
                "hold_overlap_days", "entry_date_delta_days", "same_day_entry",
            ]
        )
    detail_df.to_csv(csv_path, index=False)

    agg_df = pd.DataFrame(agg_rows)
    agg_cols = [
        "bucket", "total_trades", "wins", "losses", "bes", "win_rate_pct", "avg_profit_pct",
        "Ann_ROR", "avg_days_in_trade", "Total_PNL", "Drawdown", "profit_factor",
        "losing_streak", "p90_days", "brt_cash", "Max_Positions", "n_before_dedupe_note",
    ]
    for c in agg_cols:
        if c not in agg_df.columns:
            agg_df[c] = None
    agg_df[agg_cols].to_csv(agg_csv_path, index=False)

    html_path.write_text(
        render_html(
            summary=summary,
            detail=all_detail,
            agg_rows=agg_rows,
            sources=used_sources,
            missing=missing,
            gen_ts=gen_ts,
            sb_n=len(sb_trades),
            ss_raw_n=len(all_ss),
            ss_deduped_n=len(all_deduped),
            out_prefix=out_prefix,
        ),
        encoding="utf-8",
    )
    md_path.write_text(
        render_md(
            summary=summary,
            agg_rows=agg_rows,
            sources=used_sources,
            missing=missing,
            gen_ts=gen_ts,
            detail_n=len(all_detail),
            sb_n=len(sb_trades),
            ss_raw_n=len(all_ss),
            ss_deduped_n=len(all_deduped),
            out_prefix=out_prefix,
        ),
        encoding="utf-8",
    )

    print()
    print("=== Overlap summary ===")
    for s in summary:
        print(
            f"  {s['pair']}: {s['n_overlapping_trades']} overlaps, "
            f"{s['n_unique_symbols']} symbols ({s['n_same_day_entry']} same-day)"
        )
    print(f"  TOTAL overlap rows: {len(all_detail)}")
    print()
    print("=== Second-signal ALL PEERS (deduped) ===")
    m = all_metrics
    print(f"  total_trades:     {m['total_trades']}  (raw {len(all_ss)} -> deduped {len(all_deduped)})")
    print(f"  win_rate_pct:     {m['win_rate_pct']}%  (W/L/BE {m['wins']}/{m['losses']}/{m['bes']})")
    print(f"  avg_profit_pct:   {m['avg_profit_pct']}%")
    print(f"  Ann_ROR:          {m['Ann_ROR']}%")
    print(f"  avg_days:         {m['avg_days_in_trade']}")
    print(f"  Total_PNL:        {m['Total_PNL']}")
    print(f"  Drawdown:         {m['Drawdown']}%")
    print(f"  profit_factor:    {m['profit_factor']}")
    print(f"  losing_streak:    {m['losing_streak']}")
    print(f"  p90_days:         {m['p90_days']}")
    print(f"  brt_cash:         {m['brt_cash']}")
    print(f"  Max_Positions:    {m['Max_Positions']}")
    print()
    print(f"Wrote:\n  {csv_path}\n  {agg_csv_path}\n  {html_path}\n  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
