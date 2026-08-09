"""Parameter-tweak + cross-system peer-learn heuristics for ImproveHints.

Cheap DailyRun path (Closed CSV columns only + optional peer LatestRun books):
  - band_pct / acceptance: weak fills vs near-miss proxies
  - target_pct: left-money vs approach-then-reverse
  - stop_pct: stopped-out-of-winners vs never-worked losers
  - peer_learn: countable overlap evidence vs peer Closed books

Optional OHLC (when ``tickers`` or ``data_dir`` is provided):
  - post-TARGET continuation (expand target)
  - post-STOP rebound (expand stop)
  - RejectedFills forward follow-through (loosen band / too_high gate)

Honest about thin samples: confidence ``insufficient`` when n is small.

Outputs are **hypothesis / missed-trade evidence**, not an optimization mandate:
act only with countable evidence; one knob; ToS before/after; see
``docs/HYPOTHESIS_TEST.md``.

Same-param opposing directions (e.g. stop_pct expand vs hold from different
STOP subsets) are reconciled into one tension card so ImprovePriority does not
ship two high-confidence opposite knob recommendations — aligns with
“prefer one coherent hypothesis” / no silent dual advice.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Shared parsing (kept local so this module can run without circular imports)
# ---------------------------------------------------------------------------

_MIN_TRADES_HINT = 5
_MIN_TRADES_LOW = 3
_POST_EXIT_BARS = 15
_NEAR_MISS_FWD_GAIN = 8.0  # %
_WEAK_MFE_PCT = 3.0
_TARGET_APPROACH_LO = 0.50
_TARGET_APPROACH_HI = 0.95
_LEFT_MONEY_HOLD_PCT = 3.0  # MAX_PRICE above TARGET by >= this % of entry
_STOP_MFE_WINNER_PCT = 5.0
_SLOW_TARGET_DAYS = 100  # TARGET holds this long → contract/turnover lens
_PEER_HOLD_EXTRA_DAYS = 5
_PEER_PNL_EDGE = 5.0  # percentage points
# Clear lean when one opposing lens has ≥ this multiple of the other's trade_count
_OPPOSE_LEAN_RATIO = 1.25
_CONF_RANK = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}
_RANK_CONF = {v: k for k, v in _CONF_RANK.items()}
# Direction pairs that must not both appear as actionable advice for one param
_OPPOSING_DIRECTION_PAIRS = (
    ("expand", "hold"),
    ("expand", "contract"),
    ("tighten", "loosen"),
)


def _fnum(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    s = str(val).strip().replace("%", "").replace(",", "")
    if not s or s.upper() in ("N/A", "NAN", "NONE"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _col(row: dict[str, Any], *names: str, default: Any = "") -> Any:
    for n in names:
        if n in row and row[n] is not None and str(row[n]).strip() != "":
            return row[n]
    lower = {str(k).strip().lower(): k for k in row.keys()}
    for n in names:
        k = lower.get(n.lower())
        if k is not None and row[k] is not None and str(row[k]).strip() != "":
            return row[k]
    return default


def _ymd8(val: Any) -> str:
    s = str(val or "").strip().replace("-", "")
    return s[:8] if len(s) >= 8 else s


def _parse_date(val: Any) -> Optional[date]:
    y = _ymd8(val)
    if len(y) == 8 and y.isdigit():
        try:
            return date(int(y[:4]), int(y[4:6]), int(y[6:8]))
        except ValueError:
            return None
    s = str(val or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    try:
        return pd.Timestamp(s).date()
    except Exception:
        return None


def _iso(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def _exit_family(exit_type: str) -> str:
    """Coarse exit family. GAP_DOWN/GAP_UP stay distinct from STOP (fat-gap stats)."""
    try:
        from exit_type_normalize import exit_family as _ef

        return _ef(exit_type)
    except Exception:
        e = (exit_type or "").upper()
        if "TARGET" in e and "GAP" not in e:
            return "TARGET"
        if "GAP_DOWN" in e:
            return "GAP_DOWN"
        if "GAP_UP" in e:
            return "GAP_UP"
        if "STOP" in e:
            return "STOP"
        if "TRAIL" in e:
            return "TRAIL"
        if "TIME" in e or "NO_FT" in e:
            return "TIME"
        return e or "OTHER"


def _confidence(n: int, pct: float) -> str:
    if n < _MIN_TRADES_LOW:
        return "insufficient"
    if n >= 20 and pct >= 15.0:
        return "high"
    if n >= 8 and pct >= 8.0:
        return "medium"
    if n >= _MIN_TRADES_HINT:
        return "low"
    return "insufficient"


def _pct(n: int, denom: int) -> float:
    return (100.0 * n / denom) if denom > 0 else 0.0


def _mfe_pct(entry: float, max_price: float) -> float:
    if entry <= 0 or max_price <= 0:
        return 0.0
    return (max_price / entry - 1.0) * 100.0


def _target_progress(entry: float, target: float, max_price: float) -> float:
    if entry <= 0 or target <= entry or max_price <= 0:
        return 0.0
    return (max_price - entry) / (target - entry)


def _stop_risk_pct(entry: float, stop: float) -> float:
    if entry <= 0 or stop <= 0 or stop >= entry:
        return 0.0
    return (entry - stop) / entry * 100.0


def _param_levers(prefix: str) -> dict[str, str]:
    p = (prefix or "").upper()
    if p in ("RL", "DB"):
        return {
            "band": "rl_dip_pct / entry band (tighter dip = stricter)",
            "target": "rl_target_pct / rl_expansion",
            "stop": "rl_stop_pct",
        }
    if p in ("BRT", "WPBR", "YH", "VEC", "PBR"):
        return {
            "band": "band_pct / ATR band / zone acceptance",
            "target": "target_pct / atr_target",
            "stop": "stop_pct / atr_stop",
        }
    if p == "SB":
        return {
            "band": "burst fill band (must_open_above / at_or_below / max_risk) / too_high gate",
            "target": "target_pct (SB burst target)",
            "stop": "stop_pct / signal_low stop geometry",
        }
    if p in ("RS", "MTS", "IND", "MVCP"):
        return {
            "band": "entry band / pivot proximity gates",
            "target": "target_pct",
            "stop": "stop_pct",
        }
    return {
        "band": "band_pct / entry acceptance",
        "target": "target_pct",
        "stop": "stop_pct",
    }


@dataclass
class ParamHint:
    hypothesis_id: str
    category: str  # param | peer_learn
    param: str
    direction: str
    priority: int
    symbol_count: int
    trade_count: int
    pct_of_trades: float
    confidence: str
    symbols: list[str] = field(default_factory=list)
    lever: str = ""
    suggestion: str = ""
    evidence: str = ""
    heuristic: str = ""


# ---------------------------------------------------------------------------
# OHLC helpers
# ---------------------------------------------------------------------------

def _ohlc_slice(df: pd.DataFrame, start: date, bars: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty or bars <= 0:
        return None
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return None
    start_ts = pd.Timestamp(start)
    # first bar strictly after exit date
    after = df[idx > start_ts]
    if after.empty:
        after = df[idx >= start_ts]
    if after.empty:
        return None
    return after.iloc[:bars]


def _fwd_max_gain_pct(df: pd.DataFrame, start: date, ref_px: float, bars: int = _POST_EXIT_BARS) -> float:
    if ref_px <= 0:
        return 0.0
    sl = _ohlc_slice(df, start, bars)
    if sl is None or sl.empty:
        return 0.0
    high_col = "High" if "High" in sl.columns else None
    if high_col is None:
        for c in sl.columns:
            if str(c).lower() == "high":
                high_col = c
                break
    if high_col is None:
        return 0.0
    mx = float(pd.to_numeric(sl[high_col], errors="coerce").max() or 0.0)
    if mx <= 0:
        return 0.0
    return (mx / ref_px - 1.0) * 100.0


def _fwd_recovered_above(df: pd.DataFrame, start: date, level: float, bars: int = _POST_EXIT_BARS) -> bool:
    if level <= 0:
        return False
    sl = _ohlc_slice(df, start, bars)
    if sl is None or sl.empty:
        return False
    high_col = "High" if "High" in sl.columns else None
    if high_col is None:
        for c in sl.columns:
            if str(c).lower() == "high":
                high_col = c
                break
    if high_col is None:
        return False
    mx = float(pd.to_numeric(sl[high_col], errors="coerce").max() or 0.0)
    return mx >= level


def _normalize_ohlc_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        date_col = None
        for c in out.columns:
            if str(c).lower() in ("date", "datetime", "timestamp"):
                date_col = c
                break
        if date_col is not None:
            out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
            out = out.dropna(subset=[date_col]).set_index(date_col)
    if not isinstance(out.index, pd.DatetimeIndex):
        return out
    out = out.sort_index()
    rename = {}
    for c in out.columns:
        cl = str(c).lower()
        if cl == "high":
            rename[c] = "High"
        elif cl == "low":
            rename[c] = "Low"
        elif cl == "close":
            rename[c] = "Close"
        elif cl == "open":
            rename[c] = "Open"
    if rename:
        out = out.rename(columns=rename)
    return out


def _resolve_symbol_ohlc(
    sym: str,
    tickers: Optional[dict[str, pd.DataFrame]],
    data_dir: Optional[Path],
) -> Optional[pd.DataFrame]:
    su = sym.upper()
    if tickers:
        for k, v in tickers.items():
            if str(k).upper() == su and v is not None and not getattr(v, "empty", True):
                return _normalize_ohlc_frame(v)
    if data_dir is None:
        return None
    dd = Path(data_dir)
    for name in (f"{su}.csv", f"{su.lower()}.csv", f"{sym}.csv"):
        p = dd / name
        if p.is_file():
            try:
                return _normalize_ohlc_frame(pd.read_csv(p))
            except Exception:
                return None
    return None


# ---------------------------------------------------------------------------
# Closed-book param heuristics
# ---------------------------------------------------------------------------

def _collect_band_hints(
    rows: list[dict[str, Any]],
    *,
    prefix: str,
    levers: dict[str, str],
    rejected_rows: Optional[list[dict[str, Any]]] = None,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    data_dir: Optional[Path] = None,
) -> list[ParamHint]:
    hints: list[ParamHint] = []
    n = len(rows)
    if n <= 0:
        return hints

    weak_syms: set[str] = set()
    weak_ev: list[str] = []
    weak_n = 0
    for r in rows:
        sym = str(_col(r, "SYMBOL", default="")).strip().upper()
        if not sym:
            continue
        entry = _fnum(_col(r, "ENTRY_PRICE", "ENTRY PRICE"))
        mx = _fnum(_col(r, "MAX_PRICE", "MAX PRICE", "MAX_GAIN"))
        # MAX_GAIN may be a %; MAX_PRICE is absolute
        if "MAX_GAIN" in r and "MAX_PRICE" not in r and 0 < abs(mx) < 5:
            mfe = abs(mx) * 100.0 if abs(mx) < 2 else abs(mx)
        else:
            mfe = _mfe_pct(entry, mx)
        exit_f = _exit_family(str(_col(r, "EXIT_TYPE", "EXIT TYPE", default="")))
        days = int(_fnum(_col(r, "DAYS_HELD", "DAYS HELD"), 0))
        pnl = _fnum(_col(r, "PNL_PCT", "PNL %"))
        # Weak fill: little expansion then STOP/TIME (or tiny win)
        if mfe < _WEAK_MFE_PCT and exit_f in ("STOP", "TIME") and days <= 15 and pnl < 5:
            weak_n += 1
            weak_syms.add(sym)
            if len(weak_ev) < 6:
                weak_ev.append(f"{sym} MFE~{mfe:.1f}% {exit_f} {days}d")

    pct_weak = _pct(weak_n, n)
    conf = _confidence(weak_n, pct_weak)
    if weak_n >= _MIN_TRADES_LOW:
        hints.append(
            ParamHint(
                hypothesis_id="band_tighten_weak_fill",
                category="param",
                param="band_pct",
                direction="tighten",
                priority=weak_n * 10 + len(weak_syms),
                symbol_count=len(weak_syms),
                trade_count=weak_n,
                pct_of_trades=round(pct_weak, 1),
                confidence=conf,
                symbols=sorted(weak_syms)[:40],
                lever=levers["band"],
                suggestion=(
                    f"Tighten band/acceptance: {weak_n}/{n} trades ({pct_weak:.0f}%) entered but "
                    f"expanded <{_WEAK_MFE_PCT:.0f}% MFE then STOP/TIME — shallow fills may be noise."
                ),
                evidence="; ".join(weak_ev),
                heuristic=(
                    f"weak_fill: MAX_PRICE MFE < {_WEAK_MFE_PCT}% AND exit in STOP|TIME "
                    f"AND days_held<=15 AND pnl%<5"
                ),
            )
        )

    # Near-miss loosen from RejectedFills + optional OHLC follow-through
    if rejected_rows:
        near_syms: set[str] = set()
        near_ev: list[str] = []
        near_n = 0
        checked = 0
        for r in rejected_rows:
            sym = str(_col(r, "SYMBOL", default="")).strip().upper()
            reason = str(_col(r, "REJECT_REASON", "REASON", default="")).upper()
            if not sym or reason not in ("TOO_HIGH", "TOO_LOW", "OUT_OF_BAND", "BAND"):
                continue
            fill_d = _parse_date(_col(r, "FILL_DATE", "SIGNAL_DATE", "DATE"))
            ref = _fnum(_col(r, "FILL_OPEN", "SIGNAL_LOW", "MUST_OPEN_ABOVE"))
            if not fill_d or ref <= 0:
                continue
            checked += 1
            df = _resolve_symbol_ohlc(sym, tickers, data_dir)
            if df is None:
                continue
            fwd = _fwd_max_gain_pct(df, fill_d, ref, bars=_POST_EXIT_BARS)
            if fwd >= _NEAR_MISS_FWD_GAIN:
                near_n += 1
                near_syms.add(sym)
                if len(near_ev) < 6:
                    near_ev.append(f"{sym} {reason} {_iso(fill_d)} fwd+{fwd:.0f}%/{_POST_EXIT_BARS}d")

        if checked == 0 and rejected_rows:
            # No OHLC — report thin evidence honestly
            reasons = sum(
                1
                for r in rejected_rows
                if str(_col(r, "REJECT_REASON", "REASON", default="")).upper()
                in ("TOO_HIGH", "TOO_LOW", "OUT_OF_BAND", "BAND")
            )
            if reasons >= _MIN_TRADES_LOW:
                hints.append(
                    ParamHint(
                        hypothesis_id="band_loosen_near_miss",
                        category="param",
                        param="band_pct",
                        direction="loosen",
                        priority=reasons,
                        symbol_count=0,
                        trade_count=reasons,
                        pct_of_trades=0.0,
                        confidence="insufficient",
                        symbols=[],
                        lever=levers["band"],
                        suggestion=(
                            f"Possible loosen band/too_high: {reasons} RejectedFills near-band rejects "
                            f"found, but OHLC not available to confirm post-reject follow-through "
                            f"(need tickers/data_dir). Re-run with OHLC for confidence."
                        ),
                        evidence="RejectedFills present; OHLC follow-through not scored",
                        heuristic=(
                            "near_miss: RejectedFills TOO_HIGH|TOO_LOW then fwd max-gain "
                            f">={_NEAR_MISS_FWD_GAIN}% in {_POST_EXIT_BARS} bars (OHLC required)"
                        ),
                    )
                )
        elif near_n >= _MIN_TRADES_LOW:
            denom = max(checked, 1)
            pct_n = _pct(near_n, denom)
            conf = _confidence(near_n, pct_n)
            hints.append(
                ParamHint(
                    hypothesis_id="band_loosen_near_miss",
                    category="param",
                    param="band_pct",
                    direction="loosen",
                    priority=near_n * 10 + len(near_syms),
                    symbol_count=len(near_syms),
                    trade_count=near_n,
                    pct_of_trades=round(pct_n, 1),
                    confidence=conf,
                    symbols=sorted(near_syms)[:40],
                    lever=levers["band"],
                    suggestion=(
                        f"Loosen band / too_high gate: {near_n}/{checked} scored rejects "
                        f"({pct_n:.0f}%) still rallied ≥{_NEAR_MISS_FWD_GAIN:.0f}% within "
                        f"{_POST_EXIT_BARS} bars after reject — quality may be just outside band."
                    ),
                    evidence="; ".join(near_ev),
                    heuristic=(
                        "near_miss: RejectedFills TOO_HIGH|TOO_LOW + OHLC fwd max-gain "
                        f">={_NEAR_MISS_FWD_GAIN}% / {_POST_EXIT_BARS} bars"
                    ),
                )
            )

    return hints


def _collect_target_hints(
    rows: list[dict[str, Any]],
    *,
    prefix: str,
    levers: dict[str, str],
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    data_dir: Optional[Path] = None,
) -> list[ParamHint]:
    hints: list[ParamHint] = []
    n = len(rows)
    if n <= 0:
        return hints

    # Expand: TARGET exits with MAX_PRICE materially above TARGET during hold
    left_syms: set[str] = set()
    left_ev: list[str] = []
    left_n = 0
    target_n = 0
    # Expand via post-exit OHLC
    post_syms: set[str] = set()
    post_ev: list[str] = []
    post_n = 0
    post_checked = 0

    # Contract: approach target then reverse without hitting
    appr_syms: set[str] = set()
    appr_ev: list[str] = []
    appr_n = 0
    # Contract: slow TARGET grind (turnover / Ann_ROR framing)
    slow_syms: set[str] = set()
    slow_ev: list[str] = []
    slow_n = 0

    for r in rows:
        sym = str(_col(r, "SYMBOL", default="")).strip().upper()
        if not sym:
            continue
        entry = _fnum(_col(r, "ENTRY_PRICE", "ENTRY PRICE"))
        target = _fnum(_col(r, "TARGET_PRICE", "TARGET PRICE", "TARGET"))
        mx = _fnum(_col(r, "MAX_PRICE", "MAX PRICE"))
        exit_px = _fnum(_col(r, "EXIT_PRICE", "EXIT PRICE"))
        exit_f = _exit_family(str(_col(r, "EXIT_TYPE", "EXIT TYPE", default="")))
        d_out = _parse_date(_col(r, "DATE_CLOSED", "DATE CLOSED"))
        days = int(_fnum(_col(r, "DAYS_HELD", "DAYS HELD"), 0))
        pnl = _fnum(_col(r, "PNL_PCT", "PNL %", "PNL"))

        if exit_f == "TARGET":
            target_n += 1
            if days >= _SLOW_TARGET_DAYS:
                slow_n += 1
                slow_syms.add(sym)
                if len(slow_ev) < 6:
                    ppd = (pnl / days) if days > 0 else 0.0
                    slow_ev.append(f"{sym} TARGET {days}d {pnl:+.1f}% (~{ppd:.2f}%/d)")
            if entry > 0 and target > entry and mx > target:
                over = (mx - target) / entry * 100.0
                if over >= _LEFT_MONEY_HOLD_PCT:
                    left_n += 1
                    left_syms.add(sym)
                    if len(left_ev) < 6:
                        left_ev.append(f"{sym} MAX {over:.1f}% past target while held")

            # Post-exit continuation
            ref = exit_px if exit_px > 0 else target
            if d_out and ref > 0:
                df = _resolve_symbol_ohlc(sym, tickers, data_dir)
                if df is not None:
                    post_checked += 1
                    fwd = _fwd_max_gain_pct(df, d_out, ref, bars=_POST_EXIT_BARS)
                    if fwd >= _LEFT_MONEY_HOLD_PCT + 2.0:
                        post_n += 1
                        post_syms.add(sym)
                        if len(post_ev) < 6:
                            post_ev.append(f"{sym} +{fwd:.0f}% in {_POST_EXIT_BARS}d after TARGET")

        # Contract: approached target then failed
        if exit_f in ("STOP", "TIME", "TRAIL") and entry > 0 and target > entry and mx > 0:
            prog = _target_progress(entry, target, mx)
            if _TARGET_APPROACH_LO <= prog < _TARGET_APPROACH_HI:
                appr_n += 1
                appr_syms.add(sym)
                if len(appr_ev) < 6:
                    appr_ev.append(f"{sym} reached {prog:.0%} of target then {exit_f}")

    # Prefer post-exit OHLC when available; else in-hold MAX>TARGET
    if post_checked > 0 and post_n >= _MIN_TRADES_LOW:
        denom = max(post_checked, 1)
        pct = _pct(post_n, denom)
        hints.append(
            ParamHint(
                hypothesis_id="target_expand_post_exit",
                category="param",
                param="target_pct",
                direction="expand",
                priority=post_n * 12 + len(post_syms),
                symbol_count=len(post_syms),
                trade_count=post_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(post_n, pct),
                symbols=sorted(post_syms)[:40],
                lever=levers["target"],
                suggestion=(
                    f"Expand target: {post_n}/{post_checked} TARGET exits ({pct:.0f}%) continued "
                    f"≥{_LEFT_MONEY_HOLD_PCT + 2:.0f}% higher within {_POST_EXIT_BARS} bars — "
                    f"possible money left on table."
                ),
                evidence="; ".join(post_ev),
                heuristic=(
                    f"TARGET exit then OHLC fwd max-gain >= {_LEFT_MONEY_HOLD_PCT + 2:.0f}% "
                    f"in {_POST_EXIT_BARS} bars"
                ),
            )
        )
    elif left_n >= _MIN_TRADES_LOW:
        denom = max(target_n, 1)
        pct = _pct(left_n, denom)
        hints.append(
            ParamHint(
                hypothesis_id="target_expand_in_hold",
                category="param",
                param="target_pct",
                direction="expand",
                priority=left_n * 10 + len(left_syms),
                symbol_count=len(left_syms),
                trade_count=left_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(left_n, pct),
                symbols=sorted(left_syms)[:40],
                lever=levers["target"],
                suggestion=(
                    f"Expand target: {left_n}/{target_n} TARGET wins ({pct:.0f}%) printed MAX_PRICE "
                    f"≥{_LEFT_MONEY_HOLD_PCT:.0f}% of entry past TARGET before exit — "
                    f"runners often overshoot the tag (Closed-only; no post-exit OHLC)."
                ),
                evidence="; ".join(left_ev),
                heuristic=(
                    f"TARGET exit AND (MAX_PRICE-TARGET)/ENTRY >= {_LEFT_MONEY_HOLD_PCT}%"
                ),
            )
        )
    elif target_n > 0 and (tickers is None and data_dir is None):
        hints.append(
            ParamHint(
                hypothesis_id="target_expand_post_exit",
                category="param",
                param="target_pct",
                direction="expand",
                priority=0,
                symbol_count=0,
                trade_count=0,
                pct_of_trades=0.0,
                confidence="insufficient",
                symbols=[],
                lever=levers["target"],
                suggestion=(
                    f"{target_n} TARGET exits found but insufficient in-hold overshoot and no OHLC "
                    f"for post-exit continuation — cannot recommend expand yet."
                ),
                evidence="thin sample / no OHLC",
                heuristic="TARGET + post-exit OHLC continuation (unavailable)",
            )
        )

    if appr_n >= _MIN_TRADES_LOW:
        pct = _pct(appr_n, n)
        hints.append(
            ParamHint(
                hypothesis_id="target_contract_approach_fail",
                category="param",
                param="target_pct",
                direction="contract",
                priority=appr_n * 10 + len(appr_syms),
                symbol_count=len(appr_syms),
                trade_count=appr_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(appr_n, pct),
                symbols=sorted(appr_syms)[:40],
                lever=levers["target"],
                suggestion=(
                    f"Contract target: {appr_n}/{n} trades ({pct:.0f}%) reached "
                    f"{_TARGET_APPROACH_LO:.0%}–{_TARGET_APPROACH_HI:.0%} of entry→target "
                    f"distance (via MAX_PRICE) then exited STOP/TIME without tagging — "
                    f"a closer target may lock gains more often."
                ),
                evidence="; ".join(appr_ev),
                heuristic=(
                    f"non-TARGET exit AND target_progress in "
                    f"[{_TARGET_APPROACH_LO},{_TARGET_APPROACH_HI})"
                ),
            )
        )

    if slow_n >= _MIN_TRADES_LOW and target_n > 0:
        pct = _pct(slow_n, target_n)
        hints.append(
            ParamHint(
                hypothesis_id="target_contract_slow_hold",
                category="param",
                param="target_pct",
                direction="contract",
                priority=slow_n * 9 + len(slow_syms),
                symbol_count=len(slow_syms),
                trade_count=slow_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(slow_n, pct),
                symbols=sorted(slow_syms)[:40],
                lever=levers["target"],
                suggestion=(
                    f"Contract target (turnover): {slow_n}/{target_n} TARGET exits ({pct:.0f}%) "
                    f"held ≥{_SLOW_TARGET_DAYS}d — closer target may recycle capital sooner "
                    f"(Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis)."
                ),
                evidence="; ".join(slow_ev),
                heuristic=f"TARGET exit AND DAYS_HELD >= {_SLOW_TARGET_DAYS}",
            )
        )

    return hints


def _collect_stop_hints(
    rows: list[dict[str, Any]],
    *,
    prefix: str,
    levers: dict[str, str],
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    data_dir: Optional[Path] = None,
) -> list[ParamHint]:
    hints: list[ParamHint] = []
    n = len(rows)
    if n <= 0:
        return hints

    stop_rows = [r for r in rows if _exit_family(str(_col(r, "EXIT_TYPE", "EXIT TYPE", default=""))) == "STOP"]
    stop_n = len(stop_rows)
    if stop_n <= 0:
        return hints

    # Expand: stopped after meaningful MFE (Closed) OR post-STOP rebound (OHLC)
    mfe_syms: set[str] = set()
    mfe_ev: list[str] = []
    mfe_n = 0
    reb_syms: set[str] = set()
    reb_ev: list[str] = []
    reb_n = 0
    reb_checked = 0

    # Contract / ok: never-worked losers (MFE tiny) — informational "stop may be fine"
    dead_syms: set[str] = set()
    dead_ev: list[str] = []
    dead_n = 0

    for r in stop_rows:
        sym = str(_col(r, "SYMBOL", default="")).strip().upper()
        if not sym:
            continue
        entry = _fnum(_col(r, "ENTRY_PRICE", "ENTRY PRICE"))
        stop = _fnum(_col(r, "STOP_PRICE", "STOP PRICE", "ORIGINAL STOP", "STOP"))
        mx = _fnum(_col(r, "MAX_PRICE", "MAX PRICE"))
        exit_px = _fnum(_col(r, "EXIT_PRICE", "EXIT PRICE"))
        d_out = _parse_date(_col(r, "DATE_CLOSED", "DATE CLOSED"))
        mfe = _mfe_pct(entry, mx)
        risk = _stop_risk_pct(entry, stop)

        if mfe >= _STOP_MFE_WINNER_PCT:
            mfe_n += 1
            mfe_syms.add(sym)
            if len(mfe_ev) < 6:
                mfe_ev.append(f"{sym} MFE~{mfe:.0f}% then STOP (risk~{risk:.1f}%)")

        if mfe < 2.0:
            dead_n += 1
            dead_syms.add(sym)
            if len(dead_ev) < 6:
                dead_ev.append(f"{sym} MFE~{mfe:.1f}% STOP")

        if d_out and entry > 0:
            df = _resolve_symbol_ohlc(sym, tickers, data_dir)
            if df is not None:
                reb_checked += 1
                # rebound above entry (classic stop-out of eventual winner)
                if _fwd_recovered_above(df, d_out, entry, bars=_POST_EXIT_BARS):
                    reb_n += 1
                    reb_syms.add(sym)
                    if len(reb_ev) < 6:
                        reb_ev.append(f"{sym} STOP {_iso(d_out)} then back above entry/{_POST_EXIT_BARS}d")

    if reb_checked > 0 and reb_n >= _MIN_TRADES_LOW:
        pct = _pct(reb_n, reb_checked)
        hints.append(
            ParamHint(
                hypothesis_id="stop_expand_post_stop_rebound",
                category="param",
                param="stop_pct",
                direction="expand",
                priority=reb_n * 14 + len(reb_syms),
                symbol_count=len(reb_syms),
                trade_count=reb_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(reb_n, pct),
                symbols=sorted(reb_syms)[:40],
                lever=levers["stop"],
                suggestion=(
                    f"Expand stop: {reb_n}/{reb_checked} STOP exits ({pct:.0f}%) recovered "
                    f"above entry within {_POST_EXIT_BARS} bars — classic wick-through / "
                    f"stopped-out-of-winner pattern."
                ),
                evidence="; ".join(reb_ev),
                heuristic=(
                    f"STOP exit then OHLC High >= entry within {_POST_EXIT_BARS} bars"
                ),
            )
        )
    elif mfe_n >= _MIN_TRADES_LOW:
        pct = _pct(mfe_n, stop_n)
        hints.append(
            ParamHint(
                hypothesis_id="stop_expand_mfe_then_stop",
                category="param",
                param="stop_pct",
                direction="expand",
                priority=mfe_n * 11 + len(mfe_syms),
                symbol_count=len(mfe_syms),
                trade_count=mfe_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(mfe_n, pct),
                symbols=sorted(mfe_syms)[:40],
                lever=levers["stop"],
                suggestion=(
                    f"Expand stop / add trail: {mfe_n}/{stop_n} STOPs ({pct:.0f}%) had "
                    f"MFE≥{_STOP_MFE_WINNER_PCT:.0f}% before stopping — giveback / tight stop "
                    f"on working trades (Closed MAX_PRICE; confirm with charts)."
                ),
                evidence="; ".join(mfe_ev),
                heuristic=f"STOP exit AND MAX_PRICE MFE >= {_STOP_MFE_WINNER_PCT}%",
            )
        )

    if dead_n >= _MIN_TRADES_LOW:
        pct = _pct(dead_n, stop_n)
        # Direction "contract" only when these dominate AND fat losses are rare;
        # otherwise informational: stop geometry may already be fine.
        fat = sum(1 for r in stop_rows if _fnum(_col(r, "PNL_PCT", "PNL %")) <= -12)
        direction = "contract" if fat >= max(3, stop_n * 0.15) else "hold"
        if direction == "contract":
            sugg = (
                f"Tighten stop or cut faster: {dead_n}/{stop_n} STOPs ({pct:.0f}%) never "
                f"expanded (MFE<2%) and {fat} fat losses (pnl%≤-12) — losers that don't rebound."
            )
            hid = "stop_contract_dead_losers"
        else:
            sugg = (
                f"Stop may be adequate: {dead_n}/{stop_n} STOPs ({pct:.0f}%) never worked "
                f"(MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry."
            )
            hid = "stop_ok_never_worked"
            direction = "hold"
        hints.append(
            ParamHint(
                hypothesis_id=hid,
                category="param",
                param="stop_pct",
                direction=direction,
                priority=dead_n * 8 + len(dead_syms),
                symbol_count=len(dead_syms),
                trade_count=dead_n,
                pct_of_trades=round(pct, 1),
                confidence=_confidence(dead_n, pct),
                symbols=sorted(dead_syms)[:40],
                lever=levers["stop"],
                suggestion=sugg,
                evidence="; ".join(dead_ev),
                heuristic="STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)",
            )
        )

    return hints


# ---------------------------------------------------------------------------
# Peer-learn (LatestRun / stamped Closed overlap)
# ---------------------------------------------------------------------------

_PREFERRED_PEERS = (
    "BRT", "YH", "RS", "WPBR", "RL", "MTS", "MVCP", "SB", "IND", "QULL", "KELL", "CS",
)


@dataclass
class _PeerTrade:
    system: str
    symbol: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    pnl_pct: float
    exit_type: str
    days_held: int


def _load_peer_trades(path: Path, system: str) -> list[_PeerTrade]:
    if not path.is_file():
        return []
    out: list[_PeerTrade] = []
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            sym = str(_col(row, "SYMBOL", default="")).strip().upper()
            ed = _parse_date(_col(row, "DATE_OPENED", "DATE OPENED"))
            xd = _parse_date(_col(row, "DATE_CLOSED", "DATE CLOSED"))
            if not sym or not ed or not xd:
                continue
            if xd < ed:
                ed, xd = xd, ed
            out.append(
                _PeerTrade(
                    system=system,
                    symbol=sym,
                    entry_date=ed,
                    exit_date=xd,
                    entry_price=_fnum(_col(row, "ENTRY_PRICE", "ENTRY PRICE")),
                    exit_price=_fnum(_col(row, "EXIT_PRICE", "EXIT PRICE")),
                    stop_price=_fnum(_col(row, "STOP_PRICE", "STOP PRICE", "STOP")),
                    target_price=_fnum(_col(row, "TARGET_PRICE", "TARGET PRICE")),
                    pnl_pct=_fnum(_col(row, "PNL_PCT", "PNL %")),
                    exit_type=str(_col(row, "EXIT_TYPE", "EXIT TYPE", default="")),
                    days_held=int(_fnum(_col(row, "DAYS_HELD", "DAYS HELD"), (xd - ed).days)),
                )
            )
    return out


def _discover_peer_closed(drive: Path, hub: str) -> dict[str, Path]:
    """Map peer system -> Closed CSV (LatestRun preferred, else newest stamp)."""
    found: dict[str, Path] = {}
    hub_u = hub.upper()
    for peer in _PREFERRED_PEERS:
        if peer == hub_u:
            continue
        if peer == "PBR" and (drive / "WPBR_LatestRun_Closed.csv").is_file():
            continue
        latest = drive / f"{peer}_LatestRun_Closed.csv"
        if latest.is_file():
            found[peer] = latest
            continue
        stamps = sorted(
            drive.glob(f"{peer}_Closed_*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in stamps:
            if "_RL_" in p.name.upper():
                continue
            found[peer] = p
            break
    return found


def _ranges_overlap(a0: date, a1: date, b0: date, b1: date) -> bool:
    return a0 <= b1 and b0 <= a1


def _collect_peer_learn_hints(
    rows: list[dict[str, Any]],
    *,
    prefix: str,
    drive_dir: Optional[Path],
) -> list[ParamHint]:
    if drive_dir is None:
        return []
    drive = Path(drive_dir)
    if not drive.is_dir():
        return []

    hub = (prefix or "").upper()
    hub_trades = _load_peer_trades_from_rows(rows, hub)
    if len(hub_trades) < _MIN_TRADES_LOW:
        return [
            ParamHint(
                hypothesis_id="peer_learn_insufficient",
                category="peer_learn",
                param="cross_system",
                direction="adopt",
                priority=0,
                symbol_count=0,
                trade_count=0,
                pct_of_trades=0.0,
                confidence="insufficient",
                lever="peer Closed overlap",
                suggestion="Insufficient hub trades for peer-learn overlap scan.",
                evidence="",
                heuristic="hold-range overlap with peer LatestRun Closed",
            )
        ]

    peers = _discover_peer_closed(drive, hub)
    if not peers:
        return [
            ParamHint(
                hypothesis_id="peer_learn_no_peers",
                category="peer_learn",
                param="cross_system",
                direction="adopt",
                priority=0,
                symbol_count=0,
                trade_count=0,
                pct_of_trades=0.0,
                confidence="insufficient",
                lever="peer Closed overlap",
                suggestion="No peer LatestRun/stamped Closed books found under drive/.",
                evidence="",
                heuristic="discover {SYS}_LatestRun_Closed.csv",
            )
        ]

    # Aggregate countable events
    # peer hit TARGET after we STOP
    stop_then_peer_target: dict[str, list[str]] = defaultdict(list)
    # peer wider stop (risk%) and better pnl on overlap
    wider_stop_won: dict[str, list[str]] = defaultdict(list)
    # peer held longer and better pnl
    longer_hold_won: dict[str, list[str]] = defaultdict(list)

    hub_by_sym: dict[str, list[_PeerTrade]] = defaultdict(list)
    for t in hub_trades:
        hub_by_sym[t.symbol].append(t)

    for peer, path in peers.items():
        peer_trades = _load_peer_trades(path, peer)
        peer_by_sym: dict[str, list[_PeerTrade]] = defaultdict(list)
        for t in peer_trades:
            peer_by_sym[t.symbol].append(t)

        for sym, hlist in hub_by_sym.items():
            plist = peer_by_sym.get(sym)
            if not plist:
                continue
            for a in hlist:
                for b in plist:
                    if not _ranges_overlap(a.entry_date, a.exit_date, b.entry_date, b.exit_date):
                        continue
                    a_ex = _exit_family(a.exit_type)
                    b_ex = _exit_family(b.exit_type)
                    # Peer TARGET after our STOP (peer exit on/after our stop, peer won)
                    if a_ex == "STOP" and b_ex == "TARGET" and b.exit_date >= a.exit_date and b.pnl_pct > 0:
                        stop_then_peer_target[peer].append(
                            f"{sym} we STOP {_iso(a.exit_date)} peer TARGET {_iso(b.exit_date)} "
                            f"({b.pnl_pct:+.1f}%)"
                        )
                    # Wider stop + won
                    a_risk = _stop_risk_pct(a.entry_price, a.stop_price)
                    b_risk = _stop_risk_pct(b.entry_price, b.stop_price)
                    if (
                        a_risk > 0
                        and b_risk > a_risk * 1.15
                        and b.pnl_pct >= a.pnl_pct + _PEER_PNL_EDGE
                        and b.pnl_pct > 0
                    ):
                        wider_stop_won[peer].append(
                            f"{sym} peer stop risk {b_risk:.1f}% vs our {a_risk:.1f}% "
                            f"(pnl {b.pnl_pct:+.1f}% vs {a.pnl_pct:+.1f}%)"
                        )
                    # Longer hold + better
                    if (
                        b.days_held >= a.days_held + _PEER_HOLD_EXTRA_DAYS
                        and b.pnl_pct >= a.pnl_pct + _PEER_PNL_EDGE
                        and b.pnl_pct > 0
                        and a_ex == "STOP"
                    ):
                        longer_hold_won[peer].append(
                            f"{sym} peer held {b.days_held}d vs our {a.days_held}d "
                            f"({b.pnl_pct:+.1f}% vs {a.pnl_pct:+.1f}%)"
                        )

    hints: list[ParamHint] = []

    def _add_peer_bucket(
        hid: str,
        bucket: dict[str, list[str]],
        *,
        direction: str,
        lever: str,
        suggestion_fmt: str,
        heuristic: str,
    ) -> None:
        # Flatten countable events across peers; emit one hint per peer with enough evidence
        for peer, evs in sorted(bucket.items(), key=lambda kv: -len(kv[1])):
            # dedupe evidence strings lightly
            uniq = list(dict.fromkeys(evs))
            n_ev = len(uniq)
            if n_ev < _MIN_TRADES_LOW:
                continue
            syms = sorted({e.split()[0] for e in uniq if e})
            pct = 0.0  # overlap-event based; not % of book
            conf = _confidence(n_ev, max(10.0, n_ev * 2.0))
            hints.append(
                ParamHint(
                    hypothesis_id=f"{hid}_{peer.lower()}",
                    category="peer_learn",
                    param="cross_system",
                    direction=direction,
                    priority=n_ev * 15 + len(syms),
                    symbol_count=len(syms),
                    trade_count=n_ev,
                    pct_of_trades=pct,
                    confidence=conf,
                    symbols=syms[:40],
                    lever=f"{lever} (from {peer})",
                    suggestion=suggestion_fmt.format(n=n_ev, peer=peer, syms=len(syms)),
                    evidence="; ".join(uniq[:5]),
                    heuristic=heuristic,
                )
            )

    _add_peer_bucket(
        "peer_target_after_our_stop",
        stop_then_peer_target,
        direction="adopt",
        lever="wider stop / hold-to-target / trail",
        suggestion_fmt=(
            "Consider adopting hold/target behavior from {peer}: on {n} overlapping trades "
            "({syms} sym) we STOP'd while {peer} later hit TARGET — countable peer edge."
        ),
        heuristic="overlap hold ranges; hub STOP; peer TARGET on/after hub exit; peer pnl>0",
    )
    _add_peer_bucket(
        "peer_wider_stop_won",
        wider_stop_won,
        direction="adopt",
        lever="stop_pct (wider)",
        suggestion_fmt=(
            "Consider wider stop like {peer}: {n} overlaps ({syms} sym) where peer stop risk "
            "was ≥15% wider and peer PnL beat ours by ≥{_edge}pp.".replace(
                "{_edge}", str(int(_PEER_PNL_EDGE))
            )
        ),
        heuristic="overlap; peer stop_risk >= 1.15× hub; peer pnl >= hub + 5pp and >0",
    )
    _add_peer_bucket(
        "peer_longer_hold_won",
        longer_hold_won,
        direction="adopt",
        lever="target_pct / time-stop / trail (hold longer)",
        suggestion_fmt=(
            "Consider longer hold like {peer}: {n} overlaps ({syms} sym) where peer held "
            f"≥{_PEER_HOLD_EXTRA_DAYS}d longer after our STOP and beat PnL by ≥{int(_PEER_PNL_EDGE)}pp."
        ),
        heuristic=f"overlap; hub STOP; peer days_held >= hub+{_PEER_HOLD_EXTRA_DAYS}; pnl edge",
    )

    if not hints:
        hints.append(
            ParamHint(
                hypothesis_id="peer_learn_no_edge",
                category="peer_learn",
                param="cross_system",
                direction="adopt",
                priority=0,
                symbol_count=0,
                trade_count=0,
                pct_of_trades=0.0,
                confidence="insufficient",
                lever="peer Closed overlap",
                suggestion=(
                    f"Scanned {len(peers)} peer Closed books for hold overlaps with {hub}; "
                    f"no countable adopt-X-from-Y patterns met the min evidence threshold "
                    f"(n≥{_MIN_TRADES_LOW})."
                ),
                evidence=", ".join(sorted(peers.keys())),
                heuristic="peer TARGET after STOP / wider stop won / longer hold won",
            )
        )
    return hints


def _load_peer_trades_from_rows(rows: list[dict[str, Any]], system: str) -> list[_PeerTrade]:
    out: list[_PeerTrade] = []
    for row in rows:
        sym = str(_col(row, "SYMBOL", default="")).strip().upper()
        ed = _parse_date(_col(row, "DATE_OPENED", "DATE OPENED"))
        xd = _parse_date(_col(row, "DATE_CLOSED", "DATE CLOSED"))
        if not sym or not ed or not xd:
            continue
        if xd < ed:
            ed, xd = xd, ed
        out.append(
            _PeerTrade(
                system=system,
                symbol=sym,
                entry_date=ed,
                exit_date=xd,
                entry_price=_fnum(_col(row, "ENTRY_PRICE", "ENTRY PRICE")),
                exit_price=_fnum(_col(row, "EXIT_PRICE", "EXIT PRICE")),
                stop_price=_fnum(_col(row, "STOP_PRICE", "STOP PRICE", "STOP")),
                target_price=_fnum(_col(row, "TARGET_PRICE", "TARGET PRICE")),
                pnl_pct=_fnum(_col(row, "PNL_PCT", "PNL %")),
                exit_type=str(_col(row, "EXIT_TYPE", "EXIT TYPE", default="")),
                days_held=int(_fnum(_col(row, "DAYS_HELD", "DAYS HELD"), (xd - ed).days)),
            )
        )
    return out


def _cap_confidence(conf: str, max_conf: str) -> str:
    return _RANK_CONF[min(_CONF_RANK.get(conf, 0), _CONF_RANK.get(max_conf, 3))]


def _reconcile_opposing_param_hints(hints: list[ParamHint]) -> list[ParamHint]:
    """Collapse same-param opposing directions into one tension card.

    Independent lenses (e.g. post-STOP rebound → expand vs never-worked MFE → hold)
    can both clear high confidence on disjoint STOP subsets. Shipping both as
    separate rows looks like contradictory recommendations. Prefer one card that
    states the tension, leans only when counts clearly favor one side, and caps
    confidence at medium when opposition is real.
    """
    param_hints = [h for h in hints if h.category == "param"]
    other = [h for h in hints if h.category != "param"]
    if not param_hints:
        return hints

    by_param: dict[str, list[ParamHint]] = defaultdict(list)
    for h in param_hints:
        by_param[h.param or "_"].append(h)

    out: list[ParamHint] = []
    for param, group in by_param.items():
        absorbed: set[str] = set()
        extras: list[ParamHint] = []
        dirs = {h.direction for h in group}

        for dir_a, dir_b in _OPPOSING_DIRECTION_PAIRS:
            if dir_a not in dirs or dir_b not in dirs:
                continue
            cands_a = [h for h in group if h.direction == dir_a and h.hypothesis_id not in absorbed]
            cands_b = [h for h in group if h.direction == dir_b and h.hypothesis_id not in absorbed]
            if not cands_a or not cands_b:
                continue
            ha = max(cands_a, key=lambda h: (h.trade_count, h.priority))
            hb = max(cands_b, key=lambda h: (h.trade_count, h.priority))
            if ha.trade_count < _MIN_TRADES_LOW or hb.trade_count < _MIN_TRADES_LOW:
                continue

            na, nb = ha.trade_count, hb.trade_count
            if na >= nb * _OPPOSE_LEAN_RATIO:
                lean, lean_h, other_h = dir_a, ha, hb
            elif nb >= na * _OPPOSE_LEAN_RATIO:
                lean, lean_h, other_h = dir_b, hb, ha
            else:
                lean, lean_h, other_h = "mixed", ha if na >= nb else hb, hb if na >= nb else ha

            # Cap confidence: never keep "high" when an opposing lens also cleared
            opp_rank = min(_CONF_RANK.get(ha.confidence, 0), _CONF_RANK.get(hb.confidence, 0))
            winner_conf = lean_h.confidence
            if opp_rank >= _CONF_RANK["medium"] or (
                _CONF_RANK.get(ha.confidence, 0) >= _CONF_RANK["high"]
                and _CONF_RANK.get(hb.confidence, 0) >= _CONF_RANK["high"]
            ):
                conf = _cap_confidence(winner_conf, "medium")
            else:
                conf = _cap_confidence(winner_conf, "medium") if lean == "mixed" else winner_conf

            syms = sorted(set(ha.symbols) | set(hb.symbols))
            pct = round(max(ha.pct_of_trades, hb.pct_of_trades), 1)
            lean_note = (
                f"lean {lean}"
                if lean != "mixed"
                else "no clear lean — pick one A/B arm or segment trades"
            )
            extras.append(
                ParamHint(
                    hypothesis_id=f"{param}_tension_{dir_a}_vs_{dir_b}",
                    category="param",
                    param=param,
                    direction=lean,
                    priority=max(ha.priority, hb.priority) + 1,
                    symbol_count=len(syms),
                    trade_count=max(na, nb),
                    pct_of_trades=pct,
                    confidence=conf,
                    symbols=syms[:40],
                    lever=lean_h.lever or other_h.lever,
                    suggestion=(
                        f"Mixed {param} evidence ({lean_note}): "
                        f"{ha.hypothesis_id} → {dir_a} "
                        f"({na} trades, {ha.pct_of_trades:.0f}%, {ha.confidence}) vs "
                        f"{hb.hypothesis_id} → {dir_b} "
                        f"({nb} trades, {hb.pct_of_trades:.0f}%, {hb.confidence}). "
                        f"Independent trade subsets — not a single high-confidence knob move. "
                        f"A: {ha.suggestion} B: {hb.suggestion}"
                    ),
                    evidence=(
                        f"[A {dir_a}] {ha.evidence}"
                        + (f" | [B {dir_b}] {hb.evidence}" if hb.evidence else "")
                    ),
                    heuristic=(
                        f"reconcile opposing lenses: {ha.heuristic} || {hb.heuristic}"
                    ),
                )
            )
            absorbed.add(ha.hypothesis_id)
            absorbed.add(hb.hypothesis_id)

        for h in group:
            if h.hypothesis_id not in absorbed:
                extras.append(h)
        out.extend(extras)

    return other + out


def load_rejected_fills(path: Optional[Path]) -> list[dict[str, Any]]:
    if path is None or not Path(path).is_file():
        return []
    with Path(path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_rejected_fills_path(closed_path: Path, prefix: str, ts: str) -> Optional[Path]:
    """Best-effort locate RejectedFills next to Closed (SB) or LatestRun twin."""
    d = Path(closed_path).parent
    pref = (prefix or "").upper()
    cands = [
        d / f"{pref}_RejectedFills_{ts}.csv",
        d / f"{pref}_LatestRun_RejectedFills.csv",
    ]
    for p in cands:
        if p.is_file():
            return p
    # newest stamp for this prefix
    stamps = sorted(d.glob(f"{pref}_RejectedFills_*.csv"), key=lambda x: x.stat().st_mtime, reverse=True)
    return stamps[0] if stamps else None


def collect_param_tweak_hints(
    closed_rows: list[dict[str, Any]],
    *,
    prefix: str = "RL",
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    data_dir: Optional[Path] = None,
    drive_dir: Optional[Path] = None,
    rejected_fills_path: Optional[Path] = None,
    include_peer_learn: bool = True,
) -> list[ParamHint]:
    """Return param + peer-learn hints (may include insufficient-sample rows)."""
    levers = _param_levers(prefix)
    rejected = load_rejected_fills(rejected_fills_path)
    hints: list[ParamHint] = []
    hints.extend(
        _collect_band_hints(
            closed_rows,
            prefix=prefix,
            levers=levers,
            rejected_rows=rejected or None,
            tickers=tickers,
            data_dir=data_dir,
        )
    )
    hints.extend(
        _collect_target_hints(
            closed_rows,
            prefix=prefix,
            levers=levers,
            tickers=tickers,
            data_dir=data_dir,
        )
    )
    hints.extend(
        _collect_stop_hints(
            closed_rows,
            prefix=prefix,
            levers=levers,
            tickers=tickers,
            data_dir=data_dir,
        )
    )
    if include_peer_learn:
        hints.extend(
            _collect_peer_learn_hints(closed_rows, prefix=prefix, drive_dir=drive_dir)
        )
    # Drop pure-zero insufficient noise except peer/no-ohlc notices with useful text
    filtered: list[ParamHint] = []
    for h in hints:
        if h.confidence == "insufficient" and h.trade_count == 0 and h.hypothesis_id.startswith("target_expand"):
            # keep only if it adds guidance
            filtered.append(h)
            continue
        if h.confidence == "insufficient" and h.trade_count == 0 and "peer_learn" in h.hypothesis_id:
            filtered.append(h)
            continue
        if h.trade_count <= 0 and h.confidence == "insufficient":
            continue
        filtered.append(h)
    filtered = _reconcile_opposing_param_hints(filtered)
    filtered.sort(key=lambda h: (-h.priority, h.hypothesis_id))
    return filtered


def param_hints_to_improve_rows(hints: list[ParamHint]) -> list[dict[str, Any]]:
    """Flatten ParamHint to dicts aligned with ImproveHints CSV columns."""
    rows = []
    for h in hints:
        rows.append(
            {
                "hypothesis_id": h.hypothesis_id,
                "category": h.category,
                "param": h.param,
                "direction": h.direction,
                "priority": h.priority,
                "symbol_count": h.symbol_count,
                "trade_count": h.trade_count,
                "pct_of_trades": h.pct_of_trades,
                "confidence": h.confidence,
                "symbols": h.symbols,
                "lever": h.lever,
                "suggestion": h.suggestion,
                "evidence": h.evidence,
                "heuristic": h.heuristic,
            }
        )
    return rows
