"""
Compute live stop/target levels for open positions (gettarget_output.csv).

Each symbol uses a **system** profile: RL (Rocket Launcher / portfolio_audit.awk),
BRT (backtest percent or ATR live params), IND (deprecated; manual/historical support),
YH (year-high zone backtest percent params), or MTS (Magic Touch sheet parity).

Edit gettarget_positions.csv (symbol, purchase_date, entry_price, system).
  entry_price may be blank to use CSV Open on the entry date.
  system is RL, BRT, IND, YH, MTS, or WPBR (case-insensitive).

When entry_price is set, getTarget can compute target/limit from that price even if
purchase_date is not in the symbol CSV yet (e.g. bought today before files update).
Use --default-atr-pct when ATR mode needs a proxy % and history is missing.

CLI sets defaults per system, e.g.:
  --brt-atr-target 8 --ind-atr-target 2.4 --rl-target-pct 1.20 --rl-use-sma50
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

DEFAULT_DATA_DIR = Path(r"C:\Users\songg\Downloads\stockresearch\data\newdata\data")
# User-editable positions live here (not in this .py file — avoids accidental overwrites).
DEFAULT_POSITIONS_CSV = Path(__file__).resolve().parent / "gettarget_positions.csv"

# Optional overrides only (normally leave empty). CSV is the source of truth.
POSITIONS: dict[str, tuple[str, str | float, str]] = {}

_SYSTEM_ALIASES = {"PBR": "WPBR"}


def _normalize_system(system: str) -> str:
    s = str(system).strip().upper()
    return _SYSTEM_ALIASES.get(s, s)


@dataclass
class PositionSpec:
    symbol: str
    purchase_date: str
    entry_price: Optional[float]
    system: str  # RL, BRT, IND, YH, MTS, WPBR


@dataclass
class AtrProfile:
    atr_target: float = 0.0
    atr_stop: float = 0.0
    atr_increment: float = 0.0
    atr_progress: float = 0.0
    atr_days: int = 0
    atr_progress_incremental_stop: bool = True
    sma_stop_days: int = 0


@dataclass
class RlProfile:
  # portfolio_audit.awk defaults
    rl_target_pct: float = 1.20
    rl_stop_pct: float = 0.934
    use_sma50_target: bool = True
    rl_trail_profit: float = 0.0
    rl_trail_stop: float = 0.0
    rl_trail_profit2: float = 0.0
    rl_trail_stop2: float = 0.0


@dataclass
class PercentProfile:
    """Percent stop/target (rocket_brt target_pct / stop_pct when atr_* are 0)."""
    target_pct: float = 1.21
    stop_pct: float = 0.934
    trailing_stop_increment: float = 0.0
    use_sma50_target: bool = False
    sma_stop_days: int = 0
    stop_anchor: str = "entry"  # entry | signal_low (MTS sheet AM = signal-bar Low * stop_pct)


def _parse_entry_price(raw: str | float | None) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        p = float(raw)
    except (TypeError, ValueError):
        return None
    return p if p > 0 else None


def load_positions(
    positions_csv: Optional[Path] = None,
    default_system: str = "BRT",
) -> dict[str, PositionSpec]:
    out: dict[str, PositionSpec] = {}
    ds = default_system.strip().upper() or "BRT"

    csv_path = positions_csv
    if csv_path and csv_path.exists():
        df = pd.read_csv(csv_path)
        cols = {c.lower(): c for c in df.columns}
        sym_c = cols.get("symbol", "Symbol")
        date_c = cols.get("purchasedate", cols.get("purchase_date", "PurchaseDate"))
        price_c = cols.get("entryprice", cols.get("entry_price", "EntryPrice"))
        sys_c = cols.get("system", "System")
        for _, r in df.iterrows():
            sym = str(r[sym_c]).strip().upper()
            if not sym:
                continue
            out[sym] = PositionSpec(
                symbol=sym,
                purchase_date=str(r[date_c]).strip()[:10],
                entry_price=_parse_entry_price(r.get(price_c, "")),
                system=_normalize_system(str(r.get(sys_c, ds)).strip().upper() or ds),
            )

    for sym, row in POSITIONS.items():
        if not isinstance(row, (tuple, list)) or len(row) < 3:
            raise ValueError(f"POSITIONS[{sym!r}] must be (date, price, system)")
        date_s, price_raw, system = row[0], row[1], row[2]
        out[sym.strip().upper()] = PositionSpec(
            symbol=sym.strip().upper(),
            purchase_date=str(date_s).strip(),
            entry_price=_parse_entry_price(price_raw),
            system=_normalize_system(str(system).strip().upper() or ds),
        )

    if not out:
        raise FileNotFoundError(
            f"No positions loaded. Edit {DEFAULT_POSITIONS_CSV} or pass --positions-csv."
        )

    return out


def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    tr = pd.Series(index=df.index, dtype=float)
    if len(df.index) == 0:
        return tr
    tr.iloc[0] = high[0] - low[0]
    for j in range(1, len(df.index)):
        prev_close = close[j - 1]
        tr.iloc[j] = max(high[j] - low[j], abs(high[j] - prev_close), abs(low[j] - prev_close))
    return tr.rolling(n).mean()


def compute_sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def pick_entry_ts(df: pd.DataFrame, requested_date: pd.Timestamp, use_next_trading_day: bool) -> pd.Timestamp | None:
    if requested_date in df.index:
        return requested_date
    if not use_next_trading_day:
        return None
    pos = df.index.searchsorted(requested_date, side="left")
    if pos >= len(df.index):
        return None
    return df.index[pos]


def resolve_entry(
    df: Optional[pd.DataFrame],
    requested_ts: pd.Timestamp,
    entry_price: Optional[float],
    *,
    use_next_trading_day: bool,
    allow_synthetic_entry: bool,
) -> tuple[Optional[pd.Timestamp], bool, str]:
    """
    Resolve entry timestamp and whether that date exists in OHLC data.
    When allow_synthetic_entry and entry_price are set, use purchase_date even if
    it is absent from the CSV (stale files / bought today).
    """
    if df is None or len(df.index) == 0:
        if allow_synthetic_entry and entry_price is not None:
            return requested_ts, False, "POSITIONS_NO_CSV"
        return None, False, ""

    entry_ts = pick_entry_ts(df, requested_ts, use_next_trading_day)
    if entry_ts is not None and entry_ts in df.index:
        return entry_ts, True, "CSV"

    if allow_synthetic_entry and entry_price is not None:
        return requested_ts, False, "POSITIONS_ENTRY_NOT_IN_CSV"

    return None, False, ""


def _max_high_since_entry(
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_price: float,
    as_of_effective: pd.Timestamp,
    entry_in_data: bool,
) -> float:
    if entry_in_data and entry_ts in df.index:
        mask = (df.index >= entry_ts) & (df.index <= as_of_effective)
        if mask.any():
            return max(float(entry_price), float(df.loc[mask, "High"].max()))
        return float(entry_price)
    hist = df.loc[df.index <= as_of_effective, "High"] if len(df.index) else pd.Series(dtype=float)
    peak = float(hist.max()) if len(hist) else float(entry_price)
    return max(float(entry_price), peak)


def _atr_value_for_entry(
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    as_of_effective: pd.Timestamp,
    entry_in_data: bool,
    entry_price: float,
    default_atr_pct: float,
) -> float:
    if entry_in_data and entry_ts in df.index:
        v = df.loc[entry_ts, "ATR"]
        if pd.notna(v):
            return float(v)
    for ts in (as_of_effective,):
        if ts in df.index:
            v = df.loc[ts, "ATR"]
            if pd.notna(v):
                return float(v)
    s = df["ATR"].dropna()
    if len(s):
        return float(s.iloc[-1])
    if default_atr_pct > 0 and entry_price > 0:
        return float(entry_price) * float(default_atr_pct) / 100.0
    return float("nan")


def _prior_trading_ts(df: pd.DataFrame, ts: pd.Timestamp) -> Optional[pd.Timestamp]:
    pos = df.index.get_loc(ts)
    if isinstance(pos, slice):
        pos = pos.start or 0
    if pos <= 0:
        return None
    return df.index[pos - 1]


def _resolve_as_of(df: pd.DataFrame, as_of_ts: Optional[pd.Timestamp]) -> pd.Timestamp:
    if as_of_ts is None:
        return df.index.max()
    if as_of_ts in df.index:
        return as_of_ts
    pos = df.index.searchsorted(as_of_ts, side="left")
    return df.index[pos] if pos < len(df.index) else df.index.max()


def _apply_stop_floor(
    sym: str,
    stop_trailing: float,
    stop_floor_by_symbol: dict[str, float],
) -> tuple[float, bool, bool, Optional[float]]:
    prev_floor = stop_floor_by_symbol.get(sym)
    stop_trailing_raw = stop_trailing
    requires_stop_increase = False
    stop_floor_applied = False
    if prev_floor is not None and pd.notna(stop_trailing_raw):
        requires_stop_increase = bool(float(stop_trailing_raw) > float(prev_floor))
    if prev_floor is not None and pd.notna(stop_trailing):
        if float(stop_trailing) < float(prev_floor):
            print(
                f"[WARN] {sym}: computed StopTrailing would decrease "
                f"({float(stop_trailing_raw):.4f} -> floor {float(prev_floor):.4f}); keeping floor."
            )
            stop_trailing = float(prev_floor)
            stop_floor_applied = True
    return stop_trailing, stop_floor_applied, requires_stop_increase, prev_floor


def compute_atr_system(
    sym: str,
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_price: float,
    entry_src: str,
    as_of_effective: pd.Timestamp,
    atr_period: int,
    profile: AtrProfile,
    system_label: str,
    *,
    entry_in_data: bool = True,
    default_atr_pct: float = 0.0,
) -> dict[str, Any]:
    atr_val = _atr_value_for_entry(
        df, entry_ts, as_of_effective, entry_in_data, entry_price, default_atr_pct
    )
    if not (entry_price > 0) or pd.isna(atr_val):
        return {"error": "ATR unavailable"}

    atr_pct = (atr_val / entry_price) * 100.0
    target_price = (
        entry_price * (1.0 + atr_pct * profile.atr_target / 100.0)
        if profile.atr_target > 0
        else float("nan")
    )
    stop_initial = (
        entry_price * (1.0 - atr_pct * profile.atr_stop / 100.0)
        if profile.atr_stop > 0
        else float("nan")
    )

    if profile.atr_increment > 0 and pd.notna(stop_initial):
        max_high = _max_high_since_entry(df, entry_ts, entry_price, as_of_effective, entry_in_data)
        gain_pct = (max_high - entry_price) / entry_price * 100.0
        increments = int(gain_pct / profile.atr_increment)
        stop_trailing = float(stop_initial) + increments * 0.01 * entry_price
    else:
        stop_trailing = stop_initial

    atr_schedule_exit_date = None
    atr_schedule_exit_price = None
    atr_schedule_reason = None
    atr_schedule_progress_price = None
    ad = int(profile.atr_days or 0)
    ap = float(profile.atr_progress or 0.0)
    if ad > 0:
        if entry_in_data and entry_ts in df.index:
            entry_i = int(df.index.get_loc(entry_ts))
        else:
            entry_i = len(df.index)
        exit_i = entry_i + ad
        if ap > 0.0:
            atr_schedule_progress_price = entry_price * (1.0 + ap * atr_pct / 100.0)
        if exit_i < len(df.index):
            exit_ts = df.index[exit_i]
            if ap <= 0.0:
                atr_schedule_exit_date = str(exit_ts.date())
                atr_schedule_exit_price = float(df.iloc[exit_i]["Open"])
                atr_schedule_reason = "ATR_timed"
            elif atr_schedule_progress_price is not None:
                hi_window = df.iloc[entry_i:exit_i]["High"]
                if not bool((hi_window >= atr_schedule_progress_price).any()):
                    atr_schedule_exit_date = str(exit_ts.date())
                    atr_schedule_exit_price = float(df.iloc[exit_i]["Open"])
                    atr_schedule_reason = "ATR_inaction"

    atr_progress_stop_applied = False
    if (
        profile.atr_progress_incremental_stop
        and atr_schedule_progress_price is not None
        and ad > 0
        and ap > 0
    ):
        due_ts = entry_ts + pd.Timedelta(days=ad)
        if as_of_effective > due_ts:
            if pd.notna(stop_trailing) and float(stop_trailing) < float(atr_schedule_progress_price):
                stop_trailing = float(atr_schedule_progress_price)
                atr_progress_stop_applied = True
            elif pd.isna(stop_trailing):
                stop_trailing = float(atr_schedule_progress_price)
                atr_progress_stop_applied = True

    sma_stop_applied = False
    sma_stop_level = None
    if (
        int(profile.sma_stop_days or 0) > 0
        and pd.notna(stop_trailing)
        and as_of_effective in df.index
    ):
        sma_s = compute_sma(df["Close"], int(profile.sma_stop_days))
        sma_val = float(sma_s.loc[as_of_effective]) if pd.notna(sma_s.loc[as_of_effective]) else float("nan")
        close_as_of = float(df.loc[as_of_effective, "Close"])
        stop_trailing, sma_stop_applied = apply_sma_stop_to_trailing(
            float(stop_trailing), close_as_of, sma_val, is_long=True
        )
        if np_finite(sma_val):
            sma_stop_level = sma_val

    return {
        "System": system_label,
        "EntrySource": entry_src,
        "EntryInData": entry_in_data,
        "ATR": atr_val,
        "ATRPct": atr_pct,
        "TargetPrice": target_price if pd.notna(target_price) else None,
        "StopInitial": stop_initial if pd.notna(stop_initial) else None,
        "StopTrailing": stop_trailing if pd.notna(stop_trailing) else None,
        "atr_target": profile.atr_target,
        "atr_stop": profile.atr_stop,
        "atr_increment": profile.atr_increment,
        "atr_progress": profile.atr_progress,
        "atr_days": profile.atr_days,
        "atr_progress_incremental_stop": profile.atr_progress_incremental_stop,
        "ATRScheduleProgressPrice": atr_schedule_progress_price,
        "ATRScheduleExitDate": atr_schedule_exit_date,
        "ATRScheduleExitPrice": atr_schedule_exit_price,
        "ATRScheduleReason": atr_schedule_reason,
        "ATRProgressStopApplied": atr_progress_stop_applied,
        "SMAStopApplied": sma_stop_applied,
        "SMAStopLevel": sma_stop_level,
        "sma_stop_days": int(profile.sma_stop_days or 0),
        "SMA50": None,
        "RL_TrailTier": None,
        "use_sma50": False,
        "rl_trail_profit": None,
        "rl_trail_stop": None,
    }


def compute_rl_system(
    sym: str,
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_price: float,
    entry_src: str,
    as_of_effective: pd.Timestamp,
    profile: RlProfile,
    *,
    entry_in_data: bool = True,
) -> dict[str, Any]:
    if entry_in_data and entry_ts in df.index:
        signal_ts = _prior_trading_ts(df, entry_ts) or entry_ts
        signal_low = float(df.loc[signal_ts, "Low"])
        stop_initial = signal_low * profile.rl_stop_pct if signal_low > 0 else float("nan")
        signal_date = str(signal_ts.date())
    else:
        signal_ts = None
        signal_low = float(entry_price)
        stop_initial = float(entry_price) * float(profile.rl_stop_pct)
        signal_date = str(entry_ts.date())

    sma50_series = compute_sma(df["Close"], 50)
    sma50_signal = (
        float(sma50_series.loc[signal_ts])
        if signal_ts is not None and signal_ts in sma50_series.index and pd.notna(sma50_series.loc[signal_ts])
        else float("nan")
    )
    sma50_as_of = (
        float(sma50_series.loc[as_of_effective])
        if as_of_effective in df.index and pd.notna(sma50_series.loc[as_of_effective])
        else float("nan")
    )

    if profile.use_sma50_target and np_finite(sma50_as_of):
        target_price = sma50_as_of * profile.rl_target_pct
        target_note = "SMA50(as_of)"
    elif profile.use_sma50_target and np_finite(sma50_signal):
        target_price = sma50_signal * profile.rl_target_pct
        target_note = "SMA50(signal_bar)"
    else:
        target_price = entry_price * profile.rl_target_pct
        target_note = "entry"

    max_high = _max_high_since_entry(df, entry_ts, entry_price, as_of_effective, entry_in_data)

    trail_tier = 0
    stop_trailing = stop_initial
    if profile.rl_trail_profit2 > 0 and max_high >= entry_price * (1.0 + profile.rl_trail_profit2):
        trail_tier = 2
        stop_trailing = entry_price * (1.0 + profile.rl_trail_stop2)
    elif profile.rl_trail_profit > 0 and max_high >= entry_price * (1.0 + profile.rl_trail_profit):
        trail_tier = 1
        stop_trailing = entry_price * (1.0 + profile.rl_trail_stop)

    atr_at_entry = None
    if entry_in_data and entry_ts in df.index and "ATR" in df.columns:
        v = df.loc[entry_ts, "ATR"]
        atr_at_entry = float(v) if pd.notna(v) else None

    return {
        "System": "RL",
        "EntrySource": entry_src,
        "EntryInData": entry_in_data,
        "ATR": atr_at_entry,
        "ATRPct": None,
        "TargetPrice": target_price,
        "TargetNote": target_note,
        "StopInitial": stop_initial,
        "StopTrailing": stop_trailing,
        "atr_target": None,
        "atr_stop": None,
        "atr_increment": None,
        "atr_progress": None,
        "atr_days": None,
        "atr_progress_incremental_stop": False,
        "ATRScheduleProgressPrice": None,
        "ATRScheduleExitDate": None,
        "ATRScheduleExitPrice": None,
        "ATRScheduleReason": None,
        "ATRProgressStopApplied": False,
        "SMA50": sma50_as_of if np_finite(sma50_as_of) else sma50_signal,
        "RL_TrailTier": trail_tier,
        "use_sma50": profile.use_sma50_target,
        "rl_trail_profit": profile.rl_trail_profit,
        "rl_trail_stop": profile.rl_trail_stop,
        "rl_trail_profit2": profile.rl_trail_profit2,
        "rl_trail_stop2": profile.rl_trail_stop2,
        "SignalDate": signal_date,
        "SignalLow": signal_low,
    }


def compute_percent_system(
    sym: str,
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_price: float,
    entry_src: str,
    as_of_effective: pd.Timestamp,
    profile: PercentProfile,
    system_label: str,
    *,
    entry_in_data: bool = True,
) -> dict[str, Any]:
    sma50_as_of = float("nan")
    if as_of_effective in df.index:
        sma50_series = compute_sma(df["Close"], 50)
        sma50_as_of = (
            float(sma50_series.loc[as_of_effective])
            if pd.notna(sma50_series.loc[as_of_effective])
            else float("nan")
        )

    if profile.use_sma50_target and np_finite(sma50_as_of):
        target_price = sma50_as_of * profile.target_pct
    else:
        target_price = entry_price * profile.target_pct

    stop_anchor = str(profile.stop_anchor or "entry").strip().lower()
    signal_ts = None
    signal_low = None
    if stop_anchor == "signal_low" and entry_in_data and entry_ts in df.index:
        signal_ts = _prior_trading_ts(df, entry_ts) or entry_ts
        signal_low = float(df.loc[signal_ts, "Low"])
        stop_initial = signal_low * profile.stop_pct if signal_low > 0 else entry_price * profile.stop_pct
    else:
        stop_initial = entry_price * profile.stop_pct
    max_high = _max_high_since_entry(df, entry_ts, entry_price, as_of_effective, entry_in_data)
    if profile.trailing_stop_increment > 0 and entry_price > 0:
        gain_pct = (max_high - entry_price) / entry_price * 100.0
        step_ratio = max(0.0, gain_pct) / float(profile.trailing_stop_increment)
        stop_trailing = stop_initial + step_ratio * 0.01 * entry_price
    else:
        stop_trailing = stop_initial

    sma_stop_applied = False
    sma_stop_level = None
    if (
        int(profile.sma_stop_days or 0) > 0
        and pd.notna(stop_trailing)
        and as_of_effective in df.index
    ):
        sma_s = compute_sma(df["Close"], int(profile.sma_stop_days))
        sma_val = float(sma_s.loc[as_of_effective]) if pd.notna(sma_s.loc[as_of_effective]) else float("nan")
        close_as_of = float(df.loc[as_of_effective, "Close"])
        stop_trailing, sma_stop_applied = apply_sma_stop_to_trailing(
            float(stop_trailing), close_as_of, sma_val, is_long=True
        )
        if np_finite(sma_val):
            sma_stop_level = sma_val

    return {
        "System": system_label,
        "EntrySource": entry_src,
        "EntryInData": entry_in_data,
        "ATR": None,
        "ATRPct": None,
        "TargetPrice": target_price,
        "StopInitial": stop_initial,
        "StopTrailing": stop_trailing,
        "atr_target": None,
        "atr_stop": None,
        "atr_increment": profile.trailing_stop_increment,
        "atr_progress": None,
        "atr_days": None,
        "atr_progress_incremental_stop": False,
        "ATRScheduleProgressPrice": None,
        "ATRScheduleExitDate": None,
        "ATRScheduleExitPrice": None,
        "ATRScheduleReason": None,
        "ATRProgressStopApplied": False,
        "SMAStopApplied": sma_stop_applied,
        "SMAStopLevel": sma_stop_level,
        "sma_stop_days": int(profile.sma_stop_days or 0),
        "SMA50": sma50_as_of if np_finite(sma50_as_of) else None,
        "RL_TrailTier": None,
        "use_sma50": profile.use_sma50_target,
        "target_pct": profile.target_pct,
        "stop_pct": profile.stop_pct,
        "stop_anchor": stop_anchor,
        "SignalDate": str(signal_ts.date()) if signal_ts is not None else None,
        "SignalLow": signal_low,
    }


def np_finite(x: float) -> bool:
    return pd.notna(x) and float(x) > 0


def apply_sma_stop_to_trailing(
    stop_trailing: float,
    close: float,
    sma: float,
    is_long: bool = True,
) -> tuple[float, bool]:
    """
    Match rocket_brt SMA stop: when long and close > SMA(N), stop = max(stop, SMA);
    when short and close < SMA(N), stop = min(stop, SMA). Never loosens.
    """
    if not np_finite(sma) or not np_finite(close) or pd.isna(stop_trailing):
        return stop_trailing, False
    st = float(stop_trailing)
    if is_long and float(close) > float(sma):
        merged = max(st, float(sma))
        return merged, merged > st
    if not is_long and float(close) < float(sma):
        merged = min(st, float(sma))
        return merged, merged < st
    return st, False


def atr_profile_enabled(profile: AtrProfile) -> bool:
    """Match rocket_brt: atr_* used when non-zero; all zero => target_pct / stop_pct."""
    return (
        float(profile.atr_target or 0) > 0
        or float(profile.atr_stop or 0) > 0
        or float(profile.atr_increment or 0) > 0
        or (float(profile.atr_progress or 0) > 0 and int(profile.atr_days or 0) > 0)
        or int(profile.atr_days or 0) > 0
    )


def resolve_exit_mode(cli_mode: str, atr_profile: AtrProfile) -> str:
    """Return 'percent' or 'atr' (rocket_brt-style fallback when atr multipliers are 0)."""
    mode = (cli_mode or "auto").strip().lower()
    if mode == "auto":
        return "atr" if atr_profile_enabled(atr_profile) else "percent"
    if mode == "atr" and not atr_profile_enabled(atr_profile):
        return "percent"
    return mode


def compute_price_only_payload(
    system: str,
    entry_price: float,
    entry_src: str,
    *,
    brt_mode_resolved: str,
    ind_mode_resolved: str,
    rl_profile: RlProfile,
    brt_percent: PercentProfile,
    brt_atr: AtrProfile,
    ind_percent: PercentProfile,
    ind_atr: AtrProfile,
    yh_mode_resolved: str,
    yh_percent: PercentProfile,
    yh_atr: AtrProfile,
    mts_mode_resolved: str,
    mts_percent: PercentProfile,
    mts_atr: AtrProfile,
    wpbr_mode_resolved: str,
    wpbr_percent: PercentProfile,
    wpbr_atr: AtrProfile,
    default_atr_pct: float,
) -> dict[str, Any]:
    """Target/limit from entry_price only (no OHLC file). Uses percent or default ATR %."""
    if system == "RL":
        target_price = entry_price * rl_profile.rl_target_pct
        stop_initial = entry_price * rl_profile.rl_stop_pct
        return {
            "System": "RL",
            "EntrySource": entry_src,
            "EntryInData": False,
            "TargetPrice": target_price,
            "TargetNote": "entry_no_csv",
            "StopInitial": stop_initial,
            "StopTrailing": stop_initial,
            "ATR": None,
            "ATRPct": None,
            "SMA20": None,
            "SMA50": None,
        }
    if system == "BRT":
        mode = brt_mode_resolved
        profile_atr = brt_atr
        profile_pct = brt_percent
        label = "BRT"
    elif system == "IND":
        mode = ind_mode_resolved
        profile_atr = ind_atr
        profile_pct = ind_percent
        label = "IND"
    elif system == "YH":
        mode = yh_mode_resolved
        profile_atr = yh_atr
        profile_pct = yh_percent
        label = "YH"
    elif system == "MTS":
        mode = mts_mode_resolved
        profile_atr = mts_atr
        profile_pct = mts_percent
        label = "MTS"
    elif system == "WPBR":
        mode = wpbr_mode_resolved
        profile_atr = wpbr_atr
        profile_pct = wpbr_percent
        label = "WPBR"
    else:
        return {"error": f"unknown system {system!r}"}

    if mode == "percent":
        target_price = entry_price * profile_pct.target_pct
        stop_anchor = str(profile_pct.stop_anchor or "entry").strip().lower()
        stop_initial = entry_price * profile_pct.stop_pct
        return {
            "System": label,
            "EntrySource": entry_src,
            "EntryInData": False,
            "TargetPrice": target_price,
            "StopInitial": stop_initial,
            "StopTrailing": stop_initial,
            "ATRPct": None,
            "SMA20": None,
            "target_pct": profile_pct.target_pct,
            "stop_pct": profile_pct.stop_pct,
            "stop_anchor": stop_anchor,
        }

    if default_atr_pct <= 0:
        return {"error": "ATR unavailable (no CSV); set --default-atr-pct"}
    atr_pct = float(default_atr_pct)
    target_price = entry_price * (1.0 + atr_pct * profile_atr.atr_target / 100.0) if profile_atr.atr_target > 0 else None
    stop_initial = entry_price * (1.0 - atr_pct * profile_atr.atr_stop / 100.0) if profile_atr.atr_stop > 0 else None
    return {
        "System": label,
        "EntrySource": entry_src,
        "EntryInData": False,
        "TargetPrice": target_price,
        "StopInitial": stop_initial,
        "StopTrailing": stop_initial,
        "ATRPct": atr_pct,
        "ATR": entry_price * atr_pct / 100.0,
        "SMA20": None,
        "atr_target": profile_atr.atr_target,
        "atr_stop": profile_atr.atr_stop,
    }


def compute_position_payload(
    system: str,
    sym: str,
    df: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_price: float,
    entry_src: str,
    as_of_effective: pd.Timestamp,
    *,
    atr_period: int,
    brt_mode_resolved: str,
    ind_mode_resolved: str,
    rl_profile: RlProfile,
    brt_percent: PercentProfile,
    brt_atr: AtrProfile,
    ind_percent: PercentProfile,
    ind_atr: AtrProfile,
    yh_mode_resolved: str,
    yh_percent: PercentProfile,
    yh_atr: AtrProfile,
    mts_mode_resolved: str,
    mts_percent: PercentProfile,
    mts_atr: AtrProfile,
    wpbr_mode_resolved: str,
    wpbr_percent: PercentProfile,
    wpbr_atr: AtrProfile,
    entry_in_data: bool = True,
    default_atr_pct: float = 0.0,
) -> dict[str, Any]:
    """Dispatch to RL / BRT / IND / YH / MTS / WPBR calculator for a given as-of date."""
    kw = dict(entry_in_data=entry_in_data, default_atr_pct=default_atr_pct)
    if system == "RL":
        return compute_rl_system(
            sym, df, entry_ts, entry_price, entry_src, as_of_effective, rl_profile, entry_in_data=entry_in_data
        )
    if system == "BRT":
        if brt_mode_resolved == "percent":
            return compute_percent_system(
                sym, df, entry_ts, entry_price, entry_src, as_of_effective, brt_percent, "BRT",
                entry_in_data=entry_in_data,
            )
        return compute_atr_system(
            sym, df, entry_ts, entry_price, entry_src, as_of_effective, atr_period, brt_atr, "BRT", **kw
        )
    if system == "IND":
        if ind_mode_resolved == "percent":
            return compute_percent_system(
                sym, df, entry_ts, entry_price, entry_src, as_of_effective, ind_percent, "IND",
                entry_in_data=entry_in_data,
            )
        return compute_atr_system(
            sym, df, entry_ts, entry_price, entry_src, as_of_effective, atr_period, ind_atr, "IND", **kw
        )
    if system == "YH":
        if yh_mode_resolved == "percent":
            return compute_percent_system(
                sym, df, entry_ts, entry_price, entry_src, as_of_effective, yh_percent, "YH",
                entry_in_data=entry_in_data,
            )
        return compute_atr_system(
            sym, df, entry_ts, entry_price, entry_src, as_of_effective, atr_period, yh_atr, "YH", **kw
        )
    if system == "MTS":
        if mts_mode_resolved == "percent":
            return compute_percent_system(
                sym, df, entry_ts, entry_price, entry_src, as_of_effective, mts_percent, "MTS",
                entry_in_data=entry_in_data,
            )
        return compute_atr_system(
            sym, df, entry_ts, entry_price, entry_src, as_of_effective, atr_period, mts_atr, "MTS", **kw
        )
    if system == "WPBR":
        if wpbr_mode_resolved == "percent":
            return compute_percent_system(
                sym, df, entry_ts, entry_price, entry_src, as_of_effective, wpbr_percent, "WPBR",
                entry_in_data=entry_in_data,
            )
        return compute_atr_system(
            sym, df, entry_ts, entry_price, entry_src, as_of_effective, atr_period, wpbr_atr, "WPBR", **kw
        )
    return {"error": f"unknown system {system!r}"}


def _add_atr_profile_args(p: argparse.ArgumentParser, prefix: str, defaults: AtrProfile) -> None:
    px = prefix.lower()
    p.add_argument(f"--{px}-atr-target", type=float, default=defaults.atr_target, dest=f"{px}_atr_target")
    p.add_argument(f"--{px}-atr-stop", type=float, default=defaults.atr_stop, dest=f"{px}_atr_stop")
    p.add_argument(f"--{px}-atr-increment", type=float, default=defaults.atr_increment, dest=f"{px}_atr_increment")
    p.add_argument(f"--{px}-atr-progress", type=float, default=defaults.atr_progress, dest=f"{px}_atr_progress")
    p.add_argument(f"--{px}-atr-days", type=int, default=defaults.atr_days, dest=f"{px}_atr_days")
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument(
        f"--{px}-atr-progress-incremental-stop",
        dest=f"{px}_atr_progress_incremental_stop",
        action="store_true",
        default=None,
        help=f"Enable ATR progress stop floor for {prefix}.",
    )
    g.add_argument(
        f"--{px}-no-atr-progress-incremental-stop",
        dest=f"{px}_atr_progress_incremental_stop",
        action="store_false",
        help=f"Disable ATR progress stop floor for {prefix}.",
    )
    p.set_defaults(**{f"{px}_atr_progress_incremental_stop": defaults.atr_progress_incremental_stop})
    p.add_argument(
        f"--{px}-sma-stop-days",
        type=int,
        default=defaults.sma_stop_days,
        dest=f"{px}_sma_stop_days",
        help=f"SMA(N) trailing stop floor for {prefix} (0=off; try 20 or 8).",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Live stop/target for open positions "
            "(RL / BRT / YH / MTS / WPBR; deprecated IND remains available manually)."
        )
    )
    parser.add_argument("--data-dir", type=str, default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--entry-price-col", type=str, default="Open")
    parser.add_argument(
        "--positions-csv",
        type=str,
        default=str(DEFAULT_POSITIONS_CSV),
        help="Positions table CSV (default: gettarget_positions.csv next to this script).",
    )
    parser.add_argument("--default-system", type=str, default="BRT", help="When system column missing.")
    parser.add_argument(
        "--exclude-system",
        action="append",
        default=[],
        help="Skip live targets for this system (repeatable; DailyRun excludes deprecated IND).",
    )
    parser.add_argument(
        "--brt-mode",
        choices=("auto", "atr", "percent"),
        default="auto",
        help="BRT: auto=percent when --brt-atr-* are 0 (rocket_brt target_pct); else ATR.",
    )
    parser.add_argument(
        "--ind-mode",
        choices=("auto", "atr", "percent"),
        default="auto",
        help="IND: auto=percent when --ind-atr-* are 0 (rocket_brt target_pct); else ATR.",
    )
    parser.add_argument(
        "--yh-mode",
        choices=("auto", "atr", "percent"),
        default="auto",
        help="YH: auto=percent when --yh-atr-* are 0 (rocket_brt target_pct); else ATR.",
    )
    parser.add_argument(
        "--mts-mode",
        choices=("auto", "atr", "percent"),
        default="auto",
        help="MTS: auto=percent when --mts-atr-* are 0 (rocket_brt target_pct); else ATR.",
    )
    parser.add_argument(
        "--wpbr-mode",
        choices=("auto", "atr", "percent"),
        default="auto",
        help="WPBR: auto=percent when --wpbr-atr-* are 0 (rocket_brt target_pct); else ATR.",
    )
    parser.add_argument("--as-of-date", type=str, default=None)
    parser.add_argument("--use-next-trading-day", action="store_true")
    parser.add_argument("--out-csv", type=str, default="getTarget_output.csv")
    parser.add_argument("--no-stop-floor", action="store_true")
    parser.add_argument(
        "--allow-synthetic-entry",
        action="store_true",
        default=True,
        help="Use purchase_date + entry_price when entry date is missing from CSV (default: on).",
    )
    parser.add_argument(
        "--no-allow-synthetic-entry",
        dest="allow_synthetic_entry",
        action="store_false",
        help="Require entry date to exist in symbol CSV.",
    )
    parser.add_argument(
        "--allow-missing-csv",
        action="store_true",
        default=True,
        help="Compute target/limit from entry_price when symbol CSV is absent (default: on).",
    )
    parser.add_argument(
        "--no-allow-missing-csv",
        dest="allow_missing_csv",
        action="store_false",
        help="Skip symbols with no CSV file.",
    )
    parser.add_argument(
        "--default-atr-pct",
        type=float,
        default=8.0,
        help="ATR%% proxy for entry_price-only rows when CSV missing or entry not in file (default 8).",
    )

    _add_atr_profile_args(parser, "brt", AtrProfile(atr_target=8, atr_stop=3, atr_increment=12, atr_progress=1.1, atr_days=14))
    _add_atr_profile_args(
        parser,
        "ind",
        AtrProfile(atr_target=2.0, atr_stop=1.2, atr_increment=0, atr_progress=0.0, atr_days=0),
    )
    _add_atr_profile_args(parser, "yh", AtrProfile())
    _add_atr_profile_args(parser, "mts", AtrProfile())
    _add_atr_profile_args(parser, "wpbr", AtrProfile())

    parser.add_argument("--rl-target-pct", type=float, default=1.20)
    parser.add_argument("--rl-stop-pct", type=float, default=0.934)
    parser.add_argument("--rl-use-sma50", action="store_true", default=True)
    parser.add_argument("--rl-no-sma50", dest="rl_use_sma50", action="store_false")
    parser.add_argument("--rl-trail-profit", type=float, default=0.0)
    parser.add_argument("--rl-trail-stop", type=float, default=0.0)
    parser.add_argument("--rl-trail-profit2", type=float, default=0.0)
    parser.add_argument("--rl-trail-stop2", type=float, default=0.0)
    parser.add_argument("--brt-target-pct", type=float, default=1.21)
    parser.add_argument("--brt-stop-pct", type=float, default=0.934)
    parser.add_argument("--brt-trailing-stop-increment", type=float, default=0.0)
    parser.add_argument("--brt-use-sma50", action="store_true", default=False)
    parser.add_argument("--ind-target-pct", type=float, default=1.21)
    parser.add_argument("--ind-stop-pct", type=float, default=0.903)
    parser.add_argument("--ind-trailing-stop-increment", type=float, default=0.0)
    parser.add_argument("--ind-use-sma50", action="store_true", default=False)
    parser.add_argument("--yh-target-pct", type=float, default=1.27)
    parser.add_argument("--yh-stop-pct", type=float, default=0.923)
    parser.add_argument("--yh-trailing-stop-increment", type=float, default=0.0)
    parser.add_argument("--yh-use-sma50", action="store_true", default=False)
    parser.add_argument("--mts-target-pct", type=float, default=1.22)
    parser.add_argument("--mts-stop-pct", type=float, default=0.934)
    parser.add_argument("--mts-trailing-stop-increment", type=float, default=0.0)
    parser.add_argument("--mts-use-sma50", action="store_true", default=False)
    parser.add_argument(
        "--mts-stop-anchor",
        type=str,
        default="signal_low",
        choices=("entry", "signal_low"),
        help="MTS stop anchor: signal_low = prior-bar Low * stop_pct (sheet AM); entry = entry_price * stop_pct.",
    )
    parser.add_argument("--wpbr-target-pct", type=float, default=1.24)
    parser.add_argument("--wpbr-stop-pct", type=float, default=0.927)
    parser.add_argument("--wpbr-trailing-stop-increment", type=float, default=0.0)
    parser.add_argument("--wpbr-use-sma50", action="store_true", default=False)
    parser.add_argument(
        "--per-symbol-settings",
        default="",
        help="Per-symbol optimized params JSON (default: PER_SYMBOL_SETTINGS env or "
        "stock_analysis/Per_Symbol_Optimized_Settings_Latest.json)",
    )

    args = parser.parse_args()

    positions = load_positions(
        Path(args.positions_csv) if str(args.positions_csv).strip() else None,
        default_system=args.default_system,
    )
    excluded_systems = {
        _normalize_system(str(system).strip().upper())
        for system in args.exclude_system
        if str(system).strip()
    }
    if excluded_systems:
        skipped = [pos for pos in positions.values() if pos.system in excluded_systems]
        positions = {
            sym: pos for sym, pos in positions.items() if pos.system not in excluded_systems
        }
        print(
            f"[getTarget] Skipping {len(skipped)} position(s) for excluded system(s): "
            f"{', '.join(sorted(excluded_systems))}"
        )
        if not positions:
            out_path = Path(args.out_csv)
            columns = ["Symbol", "System", "PurchaseDate", "TargetPrice", "LimitPrice"]
            if out_path.exists():
                try:
                    columns = list(pd.read_csv(out_path, nrows=0).columns) or columns
                except Exception:
                    pass
            pd.DataFrame(columns=columns).to_csv(out_path, index=False)
            print(f"No active-system positions; cleared live target rows in {out_path.resolve()}")
            return

    brt_atr = AtrProfile(
        atr_target=args.brt_atr_target,
        atr_stop=args.brt_atr_stop,
        atr_increment=args.brt_atr_increment,
        atr_progress=args.brt_atr_progress,
        atr_days=args.brt_atr_days,
        atr_progress_incremental_stop=bool(args.brt_atr_progress_incremental_stop),
        sma_stop_days=int(args.brt_sma_stop_days or 0),
    )
    ind_atr = AtrProfile(
        atr_target=args.ind_atr_target,
        atr_stop=args.ind_atr_stop,
        atr_increment=args.ind_atr_increment,
        atr_progress=args.ind_atr_progress,
        atr_days=args.ind_atr_days,
        atr_progress_incremental_stop=bool(args.ind_atr_progress_incremental_stop),
        sma_stop_days=int(args.ind_sma_stop_days or 0),
    )
    yh_atr = AtrProfile(
        atr_target=args.yh_atr_target,
        atr_stop=args.yh_atr_stop,
        atr_increment=args.yh_atr_increment,
        atr_progress=args.yh_atr_progress,
        atr_days=args.yh_atr_days,
        atr_progress_incremental_stop=bool(args.yh_atr_progress_incremental_stop),
        sma_stop_days=int(args.yh_sma_stop_days or 0),
    )
    mts_atr = AtrProfile(
        atr_target=args.mts_atr_target,
        atr_stop=args.mts_atr_stop,
        atr_increment=args.mts_atr_increment,
        atr_progress=args.mts_atr_progress,
        atr_days=args.mts_atr_days,
        atr_progress_incremental_stop=bool(args.mts_atr_progress_incremental_stop),
        sma_stop_days=int(args.mts_sma_stop_days or 0),
    )
    wpbr_atr = AtrProfile(
        atr_target=args.wpbr_atr_target,
        atr_stop=args.wpbr_atr_stop,
        atr_increment=args.wpbr_atr_increment,
        atr_progress=args.wpbr_atr_progress,
        atr_days=args.wpbr_atr_days,
        atr_progress_incremental_stop=bool(args.wpbr_atr_progress_incremental_stop),
        sma_stop_days=int(args.wpbr_sma_stop_days or 0),
    )
    rl_profile = RlProfile(
        rl_target_pct=args.rl_target_pct,
        rl_stop_pct=args.rl_stop_pct,
        use_sma50_target=bool(args.rl_use_sma50),
        rl_trail_profit=args.rl_trail_profit,
        rl_trail_stop=args.rl_trail_stop,
        rl_trail_profit2=args.rl_trail_profit2,
        rl_trail_stop2=args.rl_trail_stop2,
    )
    brt_percent = PercentProfile(
        target_pct=args.brt_target_pct,
        stop_pct=args.brt_stop_pct,
        trailing_stop_increment=args.brt_trailing_stop_increment,
        use_sma50_target=bool(args.brt_use_sma50),
        sma_stop_days=int(args.brt_sma_stop_days or 0),
    )
    ind_percent = PercentProfile(
        target_pct=args.ind_target_pct,
        stop_pct=args.ind_stop_pct,
        trailing_stop_increment=args.ind_trailing_stop_increment,
        use_sma50_target=bool(args.ind_use_sma50),
        sma_stop_days=int(args.ind_sma_stop_days or 0),
    )
    yh_percent = PercentProfile(
        target_pct=args.yh_target_pct,
        stop_pct=args.yh_stop_pct,
        trailing_stop_increment=args.yh_trailing_stop_increment,
        use_sma50_target=bool(args.yh_use_sma50),
        sma_stop_days=int(args.yh_sma_stop_days or 0),
    )
    mts_percent = PercentProfile(
        target_pct=args.mts_target_pct,
        stop_pct=args.mts_stop_pct,
        trailing_stop_increment=args.mts_trailing_stop_increment,
        use_sma50_target=bool(args.mts_use_sma50),
        sma_stop_days=int(args.mts_sma_stop_days or 0),
        stop_anchor=str(args.mts_stop_anchor or "signal_low"),
    )
    wpbr_percent = PercentProfile(
        target_pct=args.wpbr_target_pct,
        stop_pct=args.wpbr_stop_pct,
        trailing_stop_increment=args.wpbr_trailing_stop_increment,
        use_sma50_target=bool(args.wpbr_use_sma50),
        sma_stop_days=int(args.wpbr_sma_stop_days or 0),
    )

    try:
        from stock_analysis.per_symbol_settings import (
            apply_brt_percent_overrides,
            apply_rl_profile_overrides,
            load_per_symbol_settings,
            overrides_for_symbol,
            resolve_settings_path,
        )
    except ImportError:
        from per_symbol_settings import (  # type: ignore
            apply_brt_percent_overrides,
            apply_rl_profile_overrides,
            load_per_symbol_settings,
            overrides_for_symbol,
            resolve_settings_path,
        )

    _ps_arg = str(getattr(args, "per_symbol_settings", "") or "").strip()
    _ps_path = resolve_settings_path(_ps_arg) if _ps_arg else resolve_settings_path()
    _per_symbol_settings = load_per_symbol_settings(_ps_path) if _ps_path else {}
    if _per_symbol_settings:
        print(f"[getTarget] Per-symbol settings: {_ps_path} ({len(_per_symbol_settings)} symbols)")

    data_dir = Path(args.data_dir)
    as_of_ts = pd.to_datetime(args.as_of_date) if args.as_of_date else None
    out_path = Path(args.out_csv)
    stop_floor_by_key: dict[tuple[str, str], float] = {}
    if (not args.no_stop_floor) and out_path.exists():
        try:
            prev = pd.read_csv(out_path)
            if "Symbol" in prev.columns and "StopTrailing" in prev.columns:
                cols = ["Symbol", "StopTrailing"]
                if "System" in prev.columns:
                    cols.insert(1, "System")
                prev = prev[cols].copy()
                prev["StopTrailing"] = pd.to_numeric(prev["StopTrailing"], errors="coerce")
                prev = prev.dropna(subset=["StopTrailing"])
                if "System" in prev.columns:
                    prev["System"] = prev["System"].astype(str).str.upper()
                    grouped = prev.groupby(["Symbol", "System"], as_index=False)["StopTrailing"].max()
                    stop_floor_by_key = {
                        (str(r["Symbol"]), str(r["System"])): float(r["StopTrailing"])
                        for _, r in grouped.iterrows()
                    }
                else:
                    for sym, st in (
                        prev.groupby("Symbol", as_index=False)["StopTrailing"].max()
                        .set_index("Symbol")["StopTrailing"]
                        .items()
                    ):
                        stop_floor_by_key[(str(sym), "")] = float(st)
        except Exception as e:
            print(f"[WARN] Could not read prior stop floor from {out_path}: {e}")

    brt_mode_resolved = resolve_exit_mode(args.brt_mode, brt_atr)
    ind_mode_resolved = resolve_exit_mode(args.ind_mode, ind_atr)
    yh_mode_resolved = resolve_exit_mode(args.yh_mode, yh_atr)
    mts_mode_resolved = resolve_exit_mode(args.mts_mode, mts_atr)
    wpbr_mode_resolved = resolve_exit_mode(args.wpbr_mode, wpbr_atr)
    if brt_mode_resolved == "percent" and args.brt_mode.strip().lower() in ("auto", "atr"):
        print(
            "[INFO] BRT using percent stops/targets "
            f"(target_pct={args.brt_target_pct}, stop_pct={args.brt_stop_pct}); "
            "BRT ATR multipliers are all zero."
        )
    if ind_mode_resolved == "percent" and args.ind_mode.strip().lower() in ("auto", "atr"):
        print(
            "[INFO] IND using percent stops/targets "
            f"(target_pct={args.ind_target_pct}, stop_pct={args.ind_stop_pct}); "
            "IND ATR multipliers are all zero."
        )
    if yh_mode_resolved == "percent" and args.yh_mode.strip().lower() in ("auto", "atr"):
        print(
            "[INFO] YH using percent stops/targets "
            f"(target_pct={args.yh_target_pct}, stop_pct={args.yh_stop_pct}); "
            "YH ATR multipliers are all zero."
        )
    if mts_mode_resolved == "percent" and args.mts_mode.strip().lower() in ("auto", "atr"):
        print(
            "[INFO] MTS using percent stops/targets "
            f"(target_pct={args.mts_target_pct}, stop_pct={args.mts_stop_pct}, "
            f"stop_anchor={args.mts_stop_anchor}); MTS ATR multipliers are all zero."
        )
    if wpbr_mode_resolved == "percent" and args.wpbr_mode.strip().lower() in ("auto", "atr"):
        print(
            "[INFO] WPBR using percent stops/targets "
            f"(target_pct={args.wpbr_target_pct}, stop_pct={args.wpbr_stop_pct}); "
            "WPBR ATR multipliers are all zero."
        )

    results: list[dict] = []

    for sym, pos in sorted(positions.items()):
        csv_path = data_dir / f"{sym}.csv"
        requested_ts = pd.to_datetime(pos.purchase_date)
        system = pos.system
        has_csv = csv_path.exists()
        df: Optional[pd.DataFrame] = None
        as_of_effective: Optional[pd.Timestamp] = None
        current_price = None
        sma20 = None

        if has_csv:
            df = pd.read_csv(csv_path, parse_dates=["Date"]).set_index("Date").sort_index()
            df["ATR"] = compute_atr(df, int(args.atr_period))
            as_of_effective = _resolve_as_of(df, as_of_ts)
            if "Close" in df.columns and as_of_effective in df.index and pd.notna(df.loc[as_of_effective, "Close"]):
                current_price = float(df.loc[as_of_effective, "Close"])
            sma20_series = compute_sma(df["Close"], 20)
            if as_of_effective in df.index and pd.notna(sma20_series.loc[as_of_effective]):
                sma20 = float(sma20_series.loc[as_of_effective])
        elif not args.allow_missing_csv:
            print(sym, pos.purchase_date, "CSV not found:", csv_path)
            continue

        entry_ts, entry_in_data, entry_hint = resolve_entry(
            df,
            requested_ts,
            pos.entry_price,
            use_next_trading_day=args.use_next_trading_day,
            allow_synthetic_entry=args.allow_synthetic_entry,
        )
        if entry_ts is None:
            print(sym, pos.purchase_date, "entry date not found in data (set entry_price for synthetic entry)")
            continue

        if pos.entry_price is not None:
            entry_price = float(pos.entry_price)
            entry_src = entry_hint or "POSITIONS"
        elif df is not None and entry_in_data:
            if args.entry_price_col not in df.columns:
                print(sym, "entry-price column not found:", args.entry_price_col)
                continue
            entry_price = float(df.loc[entry_ts][args.entry_price_col])
            entry_src = f"csv:{args.entry_price_col}"
        else:
            print(sym, pos.purchase_date, "entry_price required when CSV missing or entry not in file")
            continue

        if not entry_in_data:
            print(
                f"[INFO] {sym}: entry {requested_ts.date()} not in CSV; "
                f"using entry_price={entry_price:.4f} ({entry_src})"
            )

        _sym_ov = overrides_for_symbol(_per_symbol_settings, sym, system) if _per_symbol_settings else {}
        sym_rl_profile = apply_rl_profile_overrides(rl_profile, _sym_ov)
        sym_brt_percent = apply_brt_percent_overrides(brt_percent, _sym_ov)
        sym_mts_percent = apply_brt_percent_overrides(mts_percent, _sym_ov)
        sym_wpbr_percent = apply_brt_percent_overrides(wpbr_percent, _sym_ov)

        _payload_kw = dict(
            atr_period=int(args.atr_period),
            brt_mode_resolved=brt_mode_resolved,
            ind_mode_resolved=ind_mode_resolved,
            yh_mode_resolved=yh_mode_resolved,
            mts_mode_resolved=mts_mode_resolved,
            wpbr_mode_resolved=wpbr_mode_resolved,
            rl_profile=sym_rl_profile,
            brt_percent=sym_brt_percent,
            brt_atr=brt_atr,
            ind_percent=ind_percent,
            ind_atr=ind_atr,
            yh_percent=yh_percent,
            yh_atr=yh_atr,
            mts_percent=sym_mts_percent,
            mts_atr=mts_atr,
            wpbr_percent=sym_wpbr_percent,
            wpbr_atr=wpbr_atr,
            default_atr_pct=float(args.default_atr_pct),
        )

        if df is None:
            as_of_effective = requested_ts
            payload = compute_price_only_payload(
                system,
                entry_price,
                entry_src,
                **{k: v for k, v in _payload_kw.items() if k != "atr_period"},
            )
        else:
            assert as_of_effective is not None
            payload = compute_position_payload(
                system,
                sym,
                df,
                entry_ts,
                entry_price,
                entry_src,
                as_of_effective,
                entry_in_data=entry_in_data,
                **_payload_kw,
            )
        if payload.get("error"):
            if payload.get("error", "").startswith("unknown system"):
                print(sym, payload["error"])
            else:
                print(sym, entry_ts.date(), payload["error"])
            continue

        target_price_yesterday = None
        as_of_yesterday = None
        if df is not None and as_of_effective is not None:
            prior_ts = _prior_trading_ts(df, as_of_effective)
            if prior_ts is not None:
                prior_payload = compute_position_payload(
                    system,
                    sym,
                    df,
                    entry_ts,
                    entry_price,
                    entry_src,
                    prior_ts,
                    entry_in_data=entry_in_data,
                    **_payload_kw,
                )
                if not prior_payload.get("error"):
                    target_price_yesterday = prior_payload.get("TargetPrice")
                    as_of_yesterday = str(prior_ts.date())

        target_today = payload.get("TargetPrice")
        target_changed = None
        if target_price_yesterday is not None and target_today is not None:
            try:
                target_changed = abs(float(target_today) - float(target_price_yesterday)) > 1e-4
            except (TypeError, ValueError):
                target_changed = None

        stop_trailing = payload.get("StopTrailing")
        floor_key = (sym, system)
        prev_floor = stop_floor_by_key.get(floor_key)
        if stop_trailing is not None and pd.notna(stop_trailing):
            floor_map = {sym: prev_floor} if prev_floor is not None else {}
            stop_trailing, stop_floor_applied, requires_stop_increase, prev_floor = _apply_stop_floor(
                sym, float(stop_trailing), floor_map
            )
        else:
            stop_floor_applied = False
            requires_stop_increase = False

        limit_price = stop_trailing
        if limit_price is None or (isinstance(limit_price, float) and pd.isna(limit_price)):
            limit_price = payload.get("StopInitial")

        row_out = {
            "Symbol": sym,
            "System": payload.get("System"),
            "PurchaseDate": str(requested_ts.date()),
            "EntryDateUsed": str(entry_ts.date()),
            "EntryInData": payload.get("EntryInData", entry_in_data),
            "EntryPrice": entry_price,
            "EntrySource": payload.get("EntrySource"),
            "ATRPeriod": int(args.atr_period),
            "AsOfDate": str(as_of_effective.date()) if as_of_effective is not None else None,
            "CurrentPrice": current_price,
            "SMA20": sma20,
            "TargetPrice": payload.get("TargetPrice"),
            "LimitPrice": limit_price,
            "TargetPriceYesterday": target_price_yesterday,
            "TargetAsOfYesterday": as_of_yesterday,
            "TargetChanged": target_changed,
            "StopInitial": payload.get("StopInitial"),
            "StopTrailing": stop_trailing,
            "BrtMode": brt_mode_resolved if system == "BRT" else None,
            "IndMode": ind_mode_resolved if system == "IND" else None,
            "YhMode": yh_mode_resolved if system == "YH" else None,
            "MtsMode": mts_mode_resolved if system == "MTS" else None,
            "WpbrMode": wpbr_mode_resolved if system == "WPBR" else None,
            "PrevStopFloor": float(prev_floor) if prev_floor is not None else None,
            "RequiresStopIncrease": requires_stop_increase,
            "StopFloorApplied": stop_floor_applied,
            **{k: v for k, v in payload.items() if k not in ("error",)},
        }
        results.append(row_out)

        tgt = payload.get("TargetPrice")
        st = stop_trailing
        extra = ""
        if payload.get("ATRProgressStopApplied"):
            extra += f" [progress_stop={payload.get('ATRScheduleProgressPrice'):.4f}]"
        if payload.get("SMAStopApplied") and payload.get("SMAStopLevel") is not None:
            extra += f" [sma_stop={float(payload['SMAStopLevel']):.4f} N={payload.get('sma_stop_days')}]"
        if payload.get("RL_TrailTier"):
            extra += f" [RL_trail_tier={payload.get('RL_TrailTier')}]"
        if stop_floor_applied and prev_floor is not None:
            extra += f" [floor={float(prev_floor):.4f}]"
        if payload.get("use_sma50") and payload.get("SMA50"):
            extra += f" [SMA50={float(payload['SMA50']):.2f}]"

        print(
            f"{sym} [{system}] {entry_ts.date()} | "
            f"Entry={entry_price:.4f} ({entry_src}) | "
            f"Current={current_price if current_price is not None else 'NaN'} | "
            f"SMA20={sma20 if sma20 is not None else 'NaN'} | "
            f"Target={tgt if tgt is not None else 'NaN'} | "
            f"Target_yday={target_price_yesterday if target_price_yesterday is not None else 'NaN'}"
            f"{' *CHANGED*' if target_changed else ''} | "
            f"Limit={limit_price if limit_price is not None else 'NaN'} | "
            f"Stop_initial={payload.get('StopInitial')} | "
            f"Stop_trailing={st if st is not None else 'NaN'} | "
            f"as_of={as_of_effective.date() if as_of_effective is not None else requested_ts.date()}{extra}"
        )

    if results:
        pd.DataFrame(results).to_csv(out_path, index=False)
        print(f"\nWrote {len(results)} rows to {out_path.resolve()}")
    else:
        print("\nNo rows written.")


if __name__ == "__main__":
    main()
