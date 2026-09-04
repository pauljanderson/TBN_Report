"""System-agnostic post-run analysis: one-liners, fit scores, hints, charts.

Cheap enrichments (DailyRun-safe):
  - Closed ``ONE_LINER``
  - Summary ``CURRENT_MARKET_CAP`` / ``SECTOR`` / ``INDUSTRY`` (Yahoo cache;
    same names as BRT/YH/RS ``write_brt_summary``)
  - Summary ``AVG_DAYS_HELD`` (mean Closed ``DAYS_HELD`` per symbol; aligns with
    Report/Audit ``Avg_Days_Held``)
  - Summary ``PROFIT_FACTOR`` (per-symbol gross win $ / |gross loss $|)
  - Summary ``FIT`` / ``FIT_SCORE`` / ``FIT_SCORE_ROBUST`` / outlier cols /
    ``FIT_ASSESSMENT`` (plus ``RL_FIT`` for RL); ``PAUL_SCORE`` (0–8 peer
    thresholds vs run **mean** only — median is not used)
  - ``{prefix}_ImproveHints_<ts>.csv|.md|.html`` (pattern hints + param tweaks +
    peer-learn when peer Closed books exist under drive/)

Deep / optional (``post_run_analysis.py``, not DailyRun):
  - matplotlib charts under ``{prefix}_Charts_<ts>/``
  - SymbolAssessments / ImprovePriority HTML

RL helpers remain importable from ``rocket_rl_analysis`` (re-exports).
"""
from __future__ import annotations

import csv
import html
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    from param_tweak_hints import (
        collect_param_tweak_hints,
        find_rejected_fills_path,
    )
except ImportError:  # pragma: no cover
    from stock_analysis.param_tweak_hints import (  # type: ignore
        collect_param_tweak_hints,
        find_rejected_fills_path,
    )

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# Longest-first so WPBR / ADX match before shorter prefixes.
KNOWN_SYSTEM_PREFIXES: tuple[str, ...] = (
    "WPBR",
    "ADX",
    "MVCP",
    "BRT",
    "IND",
    "MTS",
    "YH",
    "VEC",
    "PBR",
    "RS",
    "RL",
    "DB",
    "SB",
    "VZ",
    "WRL",
)

ZONE_SYSTEMS = frozenset({"BRT", "WPBR", "YH", "VEC", "PBR", "VZ"})
RL_SYSTEMS = frozenset({"RL", "DB"})

# Match BRT/YH/RS Summary schema (write_brt_summary): after PCT_OF_TOTAL_PNL.
SUMMARY_YF_META_COLS: tuple[str, ...] = (
    "CURRENT_MARKET_CAP",
    "SECTOR",
    "INDUSTRY",
)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

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


def _pct_str(val: float, digits: int = 1) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.{digits}f}%"


def _iso_dash(ymd: Any) -> str:
    s = str(ymd or "").strip().replace("-", "")
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(ymd or "").strip()


def _ymd8(val: Any) -> str:
    s = str(val or "").strip().replace("-", "")
    return s[:8] if len(s) >= 8 else s


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


def resolve_workers(n: int) -> int:
    """Map CLI ``--workers`` to process count. ``-1`` -> min(4, CPUs); ``0`` -> sequential (1)."""
    cpus = os.cpu_count() or 4
    if n < 0:
        return max(1, min(4, cpus))
    if n == 0:
        return 1
    return max(1, int(n))


def normalize_system(system: str) -> str:
    s = str(system or "").strip().upper()
    if not s:
        return ""
    aliases = {"ROCKET": "RL", "ROCKETLAUNCHER": "RL", "YEARHIGH": "YH"}
    return aliases.get(s, s)


def prefix_from_closed_name(name: str) -> Optional[str]:
    """Parse ``BRT_Closed_2607....csv`` -> ``BRT``."""
    stem = Path(name).stem
    for p in KNOWN_SYSTEM_PREFIXES:
        if stem.upper().startswith(f"{p}_CLOSED_"):
            return p
    if "_CLOSED_" in stem.upper():
        return stem.split("_")[0].upper()
    return None


def detect_system(
    output_dir: Path,
    stamp: str,
    *,
    system: str = "",
    closed_path: Optional[Path] = None,
) -> str:
    """Resolve system prefix from explicit flag, Closed path, or stamp scan."""
    explicit = normalize_system(system)
    if explicit:
        return explicit
    if closed_path is not None:
        parsed = prefix_from_closed_name(Path(closed_path).name)
        if parsed:
            return parsed
    hits: list[str] = []
    for p in KNOWN_SYSTEM_PREFIXES:
        if (Path(output_dir) / f"{p}_Closed_{stamp}.csv").is_file():
            hits.append(p)
    if len(hits) == 1:
        return hits[0]
    if "RL" in hits:
        return "RL"
    if hits:
        raise SystemExit(
            f"Multiple Closed CSVs for stamp {stamp}: {', '.join(hits)}. "
            f"Pass --system {'|'.join(hits)}."
        )
    raise SystemExit(
        f"No *Closed_{stamp}.csv under {output_dir}. Pass --system or --closed."
    )


def closed_summary_open_paths(
    output_dir: Path,
    prefix: str,
    stamp: str,
    *,
    closed_path: Optional[Path] = None,
) -> tuple[Path, Path, Path]:
    """Return Closed / Summary / Open paths for a stamp.

    Prefer ``{prefix}_Summary_Symbols_{stamp}.csv`` when present (per-symbol ledger
    with ``TRADES``/``WINS``/``PCT_WINS``/Paul scores — e.g. VZ). The thin
    ``{prefix}_Summary_{stamp}.csv`` often uses ``N_TRADES``/``WIN_RATE_PCT`` only
    and must not be treated as the assessment source of truth when Symbols exists.
    """
    out = Path(output_dir)
    closed = Path(closed_path) if closed_path else out / f"{prefix}_Closed_{stamp}.csv"
    symbols_summary = out / f"{prefix}_Summary_Symbols_{stamp}.csv"
    summary = symbols_summary if symbols_summary.is_file() else out / f"{prefix}_Summary_{stamp}.csv"
    return closed, summary, out / f"{prefix}_Open_{stamp}.csv"


def resolve_symbol_ledger_stats(
    summary_row: dict[str, Any],
    closed_rows: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Normalize per-symbol trade stats from Summary (+ Closed fallback).

    Accepts both full ledger columns (``TRADES``/``WINS``/``PCT_WINS``/``SHEET_PNL``)
    and thin VZ-style Summary (``N_TRADES``/``WIN_RATE_PCT``/``TOTAL_PNL``). When
    win columns are missing, derive W/L and win% from Closed ``PNL_PCT``.
    """
    closed_rows = closed_rows or []
    pnls = [
        _fnum(_col(r, "PNL %", "PNL_PCT", "PNL"))
        for r in closed_rows
    ]
    closed_wins = sum(1 for p in pnls if p > 0)
    closed_losses = sum(1 for p in pnls if p < 0)

    trades = int(
        _fnum(
            _col(summary_row, "TRADES", "N_TRADES", default=""),
            float(len(closed_rows)) if closed_rows else 0.0,
        )
    )
    if trades <= 0 and closed_rows:
        trades = len(closed_rows)

    wins = int(_fnum(_col(summary_row, "WINS", default=""), 0))
    losses = int(_fnum(_col(summary_row, "LOSSES", default=""), 0))
    pct_raw = _col(summary_row, "PCT_WINS", "WIN_RATE_PCT", "WIN_RATE", default="")
    pct_wins = _fnum(str(pct_raw).replace("%", "")) if pct_raw != "" else 0.0

    # Thin Summary has WIN_RATE_PCT but no WINS/LOSSES — fill from Closed.
    if closed_rows and wins <= 0 and losses <= 0:
        wins, losses = closed_wins, closed_losses
    if trades and not pct_wins and wins:
        pct_wins = wins / trades * 100.0
    elif trades and not pct_wins and closed_rows:
        pct_wins = closed_wins / trades * 100.0

    avg_pnl = _fnum(str(_col(summary_row, "AVG_PNL_PCT", default="") or "").replace("%", ""))
    if not avg_pnl and pnls:
        avg_pnl = sum(pnls) / len(pnls)

    sheet_pnl = _fnum(_col(summary_row, "SHEET_PNL", "TOTAL_PNL", default=""))
    if not sheet_pnl and closed_rows:
        sheet_pnl = sum(_fnum(_col(r, "PNL $", "PNL_DOLLARS", "PNL_DOLLAR")) for r in closed_rows)

    avg_tpy = _fnum(_col(summary_row, "AVG_TRADES_PER_YEAR", default=""))
    if not avg_tpy and closed_rows and trades > 0:
        years: list[int] = []
        for r in closed_rows:
            ymd = _ymd8(_col(r, "DATE OPENED", "DATE_OPENED"))
            if len(ymd) >= 4 and ymd[:4].isdigit():
                years.append(int(ymd[:4]))
        if years:
            span = max(years) - min(years) + 1
            if span > 0:
                avg_tpy = trades / float(span)

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "pct_wins": pct_wins,
        "avg_pnl_pct": avg_pnl,
        "sheet_pnl": sheet_pnl,
        "avg_tpy": avg_tpy,
    }


# ---------------------------------------------------------------------------
# One-liners
# ---------------------------------------------------------------------------

def _stack_hint(row: dict[str, Any]) -> str:
    s20 = _fnum(_col(row, "SMA20"))
    s50 = _fnum(_col(row, "SMA50"))
    s100 = _fnum(_col(row, "SMA100"))
    s200 = _fnum(_col(row, "SMA200"))
    if min(s20, s50, s100, s200) <= 0:
        return ""
    if s20 > s50 > s100 > s200:
        return "full SMA stack"
    if s50 > s100 > s200:
        return "partial stack (50>100>200)"
    if s20 < s50:
        return "under SMA20"
    return "flat/mixed stack"


def _narrative_for_trade(row: dict[str, Any]) -> str:
    """Template narrative from exit type / MAE / days / MTM / stack."""
    exit_type = str(_col(row, "EXIT TYPE", "EXIT_TYPE", default="")).strip().upper()
    days = int(_fnum(_col(row, "DAYS HELD", "DAYS_HELD"), 0))
    mae = _fnum(_col(row, "MAE", "MAE_PCT"))
    if 0 < abs(mae) < 1.5:
        mae_pct = abs(mae) * 100.0
    else:
        mae_pct = abs(mae)
    max_gain = _fnum(_col(row, "MAX GAIN", "MAX_GAIN", "MAX_PRICE"))
    # Prefer explicit MAX GAIN % fields; MAX_PRICE alone is not a %
    if "MAX GAIN" in row or "MAX_GAIN" in {str(k).upper() for k in row}:
        if 0 < abs(max_gain) < 2.0:
            max_gain_pct = abs(max_gain) * 100.0
        else:
            max_gain_pct = abs(max_gain)
    else:
        max_gain_pct = 0.0
    pnl = _fnum(_col(row, "PNL %", "PNL_PCT", "PNL"))
    entry = _fnum(_col(row, "ENTRY PRICE", "ENTRY_PRICE"))
    s50 = _fnum(_col(row, "SMA50"))
    stack = _stack_hint(row)
    zc = _fnum(_col(row, "ZONE_CENTER", "ZONE CENTER"))
    bits: list[str] = []

    if exit_type in ("TARGET", "TARGET_HIT", "HIT_TARGET"):
        if days <= 10:
            bits.append("quick TARGET")
        elif days <= 40:
            bits.append("TARGET mid-hold")
        else:
            bits.append("slow grind to TARGET")
        if mae_pct >= 8:
            bits.append(f"held through {mae_pct:.0f}% MAE")
    elif "STOP" in exit_type:
        if days <= 5:
            bits.append("failed bounce / quick stop")
        elif max_gain_pct >= 12 and pnl < 0:
            bits.append(f"MTM giveback (~{max_gain_pct:.0f}% peak) then STOP")
        elif mae_pct >= 12:
            bits.append(f"deep MAE {mae_pct:.0f}% then STOP")
        else:
            bits.append("STOP_LOSS")
    elif "TRAIL" in exit_type:
        bits.append("trail exit")
    elif "FLUSH" in exit_type:
        bits.append("flush exit")
    elif "SPY" in exit_type or "WEAK" in exit_type:
        bits.append("SPY/regime exit")
    elif exit_type:
        bits.append(exit_type.replace("_", " ").title())
    else:
        bits.append("exit")

    if entry > 0 and s50 > 0:
        rel = (entry / s50 - 1.0) * 100.0
        if rel <= -2.0:
            bits.append(f"entry {abs(rel):.1f}% below SMA50")
        elif abs(rel) <= 1.0:
            bits.append("entry near SMA50")
    if entry > 0 and zc > 0:
        zrel = (entry / zc - 1.0) * 100.0
        if abs(zrel) <= 3.0:
            bits.append("entry near zone")
        elif zrel > 3.0:
            bits.append(f"entry {zrel:.1f}% above zone")

    if stack:
        bits.append(stack)

    seen: set[str] = set()
    out: list[str] = []
    for b in bits:
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return "; ".join(out)


def format_trade_one_liner(row: dict[str, Any], *, dip_pct: Optional[float] = None) -> str:
    """Pasteable sheet one-liner from a Closed CSV row dict."""
    sym = str(_col(row, "SYMBOL", default="?")).strip().upper()
    d_in = _iso_dash(_col(row, "DATE OPENED", "DATE_OPENED"))
    d_out = _iso_dash(_col(row, "DATE CLOSED", "DATE_CLOSED"))
    entry = _fnum(_col(row, "ENTRY PRICE", "ENTRY_PRICE"))
    exit_px = _fnum(_col(row, "EXIT PRICE", "EXIT_PRICE"))
    exit_type = str(_col(row, "EXIT TYPE", "EXIT_TYPE", default="EXIT")).strip().upper() or "EXIT"
    pnl = _fnum(_col(row, "PNL %", "PNL_PCT", "PNL"))
    days = int(_fnum(_col(row, "DAYS HELD", "DAYS_HELD"), 0))
    mae = _fnum(_col(row, "MAE", "MAE_PCT"))
    if 0 < abs(mae) < 1.5:
        mae_pct = abs(mae) * 100.0
    else:
        mae_pct = abs(mae)
    stop = _fnum(
        _col(row, "ORIGINAL STOP", "STOP LOSS AT CLOSE", "STOP_PRICE", "STOP LOSS", "STOP")
    )
    narrative = _narrative_for_trade(row)

    stop_s = f"{stop:.2f}" if stop > 0 else "?"
    return (
        f"{sym} | IN {d_in} @ {entry:.2f} -> OUT {d_out} @ {exit_px:.2f} | "
        f"{exit_type} {_pct_str(pnl)} | {days}d | MAE {mae_pct:.2f}% (stop {stop_s}) | {narrative}"
    )


def enrich_closed_csv_with_one_liners(
    closed_path: Path,
    *,
    dip_pct: float = 1.055,
) -> int:
    """Add/overwrite ONE_LINER column on Closed CSV. Returns row count."""
    path = Path(closed_path)
    if not path.is_file():
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return 0
    if "ONE_LINER" not in fieldnames:
        fieldnames.append("ONE_LINER")
    for row in rows:
        row["ONE_LINER"] = format_trade_one_liner(row, dip_pct=dip_pct)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Fit assessment (per symbol)
# ---------------------------------------------------------------------------
# House FIT_ASSESSMENT gates (pass/fail checklist on Summary). Units:
#   Expectancy  → Summary AVG_PNL_PCT (mean trade PnL %, same field FIT_SCORE uses)
#   Trades/year → Summary AVG_TRADES_PER_YEAR
#   Robustness  → AVG_PNL_PCT_WO_MAX (leave-max-win-out mean PnL %)
#   Dollar PnL  → Summary SHEET_PNL (sheet-scaled $; FIT never uses TOTAL_PNL for this gate)
FIT_GATE_EXPECTANCY_PCT = 2.5
FIT_GATE_TRADES_PER_YEAR = 1.0
FIT_GATE_ROBUST_AVG_PNL_PCT = 0.20
FIT_GATE_SHEET_PNL = 10_000.0


@dataclass
class FitResult:
    fit: str  # High | Medium | Low
    score: int
    text: str
    score_robust: int = 0
    fit_robust: str = ""
    max_win_pct: float = 0.0
    median_pnl_pct: float = 0.0  # diagnostic only; not used in FIT_SCORE_ROBUST
    avg_pnl_pct_wo_max: float = 0.0
    sheet_pnl_wo_max: float = 0.0
    outlier_pct_of_wins: float = 0.0
    outlier_pct_of_sheet: float = 0.0
    outlier_penalty: int = 0
    # Assessment checklist (four house gates)
    gate_expectancy: bool = False
    gate_tpy: bool = False
    gate_robust: bool = False
    gate_sheet: bool = False
    gates_pass: bool = False
    gates_passed: int = 0


def _fit_tier(score: int) -> str:
    if score >= 5:
        return "High"
    if score >= 2:
        return "Medium"
    return "Low"


def _fit_assessment_gates(
    *,
    avg_pnl_pct: float,
    avg_tpy: float,
    avg_pnl_pct_wo_max: float,
    sheet_pnl: float,
) -> tuple[bool, bool, bool, bool]:
    """Four house FIT_ASSESSMENT gates (Expectancy / tpy / robust wo-max / sheet $)."""
    g_exp = avg_pnl_pct >= FIT_GATE_EXPECTANCY_PCT
    g_tpy = avg_tpy >= FIT_GATE_TRADES_PER_YEAR
    g_rob = avg_pnl_pct_wo_max >= FIT_GATE_ROBUST_AVG_PNL_PCT
    g_sheet = sheet_pnl > FIT_GATE_SHEET_PNL
    return g_exp, g_tpy, g_rob, g_sheet


def _fit_gates_assessment_text(
    *,
    avg_pnl_pct: float,
    avg_tpy: float,
    avg_pnl_pct_wo_max: float,
    sheet_pnl: float,
    g_exp: bool,
    g_tpy: bool,
    g_rob: bool,
    g_sheet: bool,
) -> str:
    """Compact pass/fail line for Summary FIT_ASSESSMENT (ASCII-safe for CSV)."""
    n_ok = int(g_exp) + int(g_tpy) + int(g_rob) + int(g_sheet)
    status = "PASS" if n_ok == 4 else "FAIL"
    mark = lambda ok: "ok" if ok else "FAIL"
    return (
        f"gates {status} {n_ok}/4 "
        f"[exp AVG_PNL_PCT {avg_pnl_pct:+.2f}% >={FIT_GATE_EXPECTANCY_PCT:.1f} {mark(g_exp)}; "
        f"tpy {avg_tpy:.2f} >={FIT_GATE_TRADES_PER_YEAR:.0f} {mark(g_tpy)}; "
        f"wo AVG_PNL_PCT_WO_MAX {avg_pnl_pct_wo_max:+.2f}% >={FIT_GATE_ROBUST_AVG_PNL_PCT:.2f} {mark(g_rob)}; "
        f"sheet SHEET_PNL ${sheet_pnl:,.0f} >{FIT_GATE_SHEET_PNL:,.0f} {mark(g_sheet)}]"
    )


def _fit_component_score(
    *,
    pct_wins: float,
    pnl_pct_for_avg_bucket: float,
    sheet_pnl: float,
    avg_tpy: float,
    wins: int,
    losses: int,
    asym_penalty: bool = False,
    outlier_penalty: int = 0,
) -> int:
    """Shared point rules for headline FIT_SCORE and FIT_SCORE_ROBUST.

    Point floors aligned with house FIT_ASSESSMENT gates where they overlap:
    expectancy (AVG_PNL_PCT / wo-max) ≥ 2.5% → +1; sheet $ > 10k → +2; tpy ≥ 1 → +2.
    """
    score = 0
    if pct_wins >= 55:
        score += 2
    elif pct_wins >= 45:
        score += 1
    if pnl_pct_for_avg_bucket >= 8:
        score += 2
    elif pnl_pct_for_avg_bucket >= FIT_GATE_EXPECTANCY_PCT:
        score += 1
    elif pnl_pct_for_avg_bucket < 0:
        score -= 2
    if sheet_pnl > FIT_GATE_SHEET_PNL:
        score += 2
    elif sheet_pnl > 0:
        score += 1
    elif sheet_pnl < -2000:
        score -= 2
    # Trades/year: full credit only at house gate (≥1); no soft 0.36 partial.
    if avg_tpy >= FIT_GATE_TRADES_PER_YEAR:
        score += 2
    if wins >= 3 and losses == 0:
        score += 1
    if asym_penalty:
        score -= 1
    score -= max(0, int(outlier_penalty))
    return score


def _closed_trade_pnls(closed_rows: list[dict[str, Any]]) -> list[float]:
    return [_fnum(_col(r, "PNL %", "PNL_PCT")) for r in closed_rows]


def _closed_trade_dollar_pnls(closed_rows: list[dict[str, Any]]) -> list[float]:
    return [_fnum(_col(r, "PNL $", "PNL_DOLLARS", "PNL_DOLLAR")) for r in closed_rows]


def profit_factor_from_dollar_pnls(pnls: list[float]) -> float:
    """Gross winning $ / |gross losing $| — same definition as Report ``Profit_Factor``."""
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p < 0))
    if gl > 0:
        return gp / gl
    return gp if gp > 0 else 0.0


def _ensure_summary_profit_factor_fieldnames(fieldnames: list[str]) -> list[str]:
    """Insert ``PROFIT_FACTOR`` after ``AVG_PNL_PCT`` (drop legacy ``Profit_Factor``)."""
    out = [c for c in fieldnames if c not in ("PROFIT_FACTOR", "Profit_Factor")]
    if "AVG_PNL_PCT" in out:
        out.insert(out.index("AVG_PNL_PCT") + 1, "PROFIT_FACTOR")
    elif "SHEET_PNL" in out:
        out.insert(out.index("SHEET_PNL") + 1, "PROFIT_FACTOR")
    else:
        out.append("PROFIT_FACTOR")
    return out


def _outlier_fit_metrics(pnls: list[float]) -> tuple[float, float, float, float]:
    """max_win%, median trade PnL% (diag), top-win/sum(wins), top-win/sum(all) ≈ sheet share."""
    if not pnls:
        return 0.0, 0.0, 0.0, 0.0
    wins = [p for p in pnls if p > 0]
    max_win = max(wins) if wins else 0.0
    median = float(statistics.median(pnls))
    sum_wins = sum(wins)
    outlier_of_wins = 100.0 * max_win / sum_wins if sum_wins > 0 else 0.0
    sum_all = sum(pnls)
    # Fixed-notional sheet: trade $ share = pnl% / sum(pnl%).
    if sum_all > 0 and max_win > 0:
        outlier_of_sheet = 100.0 * max_win / sum_all
    else:
        outlier_of_sheet = outlier_of_wins
    return max_win, median, outlier_of_wins, outlier_of_sheet


def _leave_max_win_out(
    pnls: list[float],
    *,
    avg_pnl_pct: float,
    sheet_pnl: float,
) -> tuple[float, float, bool]:
    """Mean PnL% and sheet $ after dropping the single largest winning trade.

    Returns ``(avg_pnl_wo_max, sheet_pnl_wo_max, dropped)``. When there is no
    positive max win to drop (or fewer than 2 trades), returns the inputs unchanged
    and ``dropped=False``.
    """
    if len(pnls) < 2:
        return avg_pnl_pct, sheet_pnl, False
    max_i = -1
    max_v = 0.0
    for i, p in enumerate(pnls):
        if p > max_v:
            max_v = p
            max_i = i
    if max_i < 0 or max_v <= 0:
        return avg_pnl_pct, sheet_pnl, False
    remaining = [p for i, p in enumerate(pnls) if i != max_i]
    avg_wo = sum(remaining) / len(remaining) if remaining else 0.0
    sum_all = sum(pnls)
    # Fixed-notional: sheet $ scales with sum(PnL%). Drop max win's share.
    if abs(sum_all) > 1e-9:
        sheet_wo = sheet_pnl * (sum_all - max_v) / sum_all
    else:
        sheet_wo = sheet_pnl
    return avg_wo, sheet_wo, True


def _outlier_soft_penalty(outlier_pct_of_wins: float, outlier_pct_of_sheet: float) -> int:
    """Soft −1/−2 when one trade carries wins or sheet PnL (hard to game vs dropping trades)."""
    if outlier_pct_of_wins > 70.0 or outlier_pct_of_sheet > 80.0:
        return 2
    if outlier_pct_of_wins > 50.0 or outlier_pct_of_sheet > 60.0:
        return 1
    return 0


def assess_symbol_fit(
    *,
    trades: int,
    wins: int,
    losses: int,
    pct_wins: float,
    avg_pnl_pct: float,
    sheet_pnl: float,
    avg_tpy: float,
    closed_rows: Optional[list[dict[str, Any]]] = None,
) -> FitResult:
    """Rule-based High/Medium/Low fit for sheet paste.

    ``FIT_SCORE`` (headline) uses mean ``avg_pnl_pct`` (Summary ``AVG_PNL_PCT`` —
    house “Expectancy” for FIT; not Report dollar Expectancy).
    ``FIT_SCORE_ROBUST`` re-scores with leave-max-win-out mean PnL% and sheet $,
    plus a soft outlier penalty when one win dominates positive PnL% or sheet share.
    Median trade PnL% is kept as a diagnostic column only (not scored).

    ``FIT_ASSESSMENT`` always lists the four house gates (Expectancy /
    trades-per-year / robust wo-max / sheet $) with pass/fail marks.
    """
    closed_rows = closed_rows or []
    notes: list[str] = []
    pnls = _closed_trade_pnls(closed_rows)
    max_win, median_pnl, outlier_of_wins, outlier_of_sheet = _outlier_fit_metrics(pnls)
    outlier_pen = _outlier_soft_penalty(outlier_of_wins, outlier_of_sheet)
    avg_wo_max, sheet_wo_max, dropped_max = _leave_max_win_out(
        pnls, avg_pnl_pct=avg_pnl_pct, sheet_pnl=sheet_pnl
    )
    if not pnls:
        avg_wo_max = avg_pnl_pct
        sheet_wo_max = sheet_pnl

    win_pnls = [p for p in pnls if p > 0]
    loss_pnls = [p for p in pnls if p < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
    asym = avg_win > 0 and avg_loss < 0 and avg_win < abs(avg_loss) * 0.85
    if asym:
        notes.append(f"asym: avgW {avg_win:.0f}% < |avgL| {abs(avg_loss):.0f}%")

    years: list[int] = []
    for r in closed_rows:
        ymd = _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED"))
        if len(ymd) >= 4 and ymd[:4].isdigit():
            years.append(int(ymd[:4]))
    years.sort()
    if len(years) >= 2:
        gaps = [years[i + 1] - years[i] for i in range(len(years) - 1)]
        if max(gaps) >= 3:
            notes.append(f"era gap {max(gaps)}y")
    if years:
        span = years[-1] - years[0] + 1
        if span >= 6 and trades <= 3:
            notes.append(f"sparse {trades}tr/{span}y")

    if trades <= 0:
        g_exp, g_tpy, g_rob, g_sheet = _fit_assessment_gates(
            avg_pnl_pct=0.0,
            avg_tpy=0.0,
            avg_pnl_pct_wo_max=0.0,
            sheet_pnl=0.0,
        )
        gate_line = _fit_gates_assessment_text(
            avg_pnl_pct=0.0,
            avg_tpy=0.0,
            avg_pnl_pct_wo_max=0.0,
            sheet_pnl=0.0,
            g_exp=g_exp,
            g_tpy=g_tpy,
            g_rob=g_rob,
            g_sheet=g_sheet,
        )
        return FitResult(
            "Low",
            0,
            f"no trades; {gate_line}"[:400],
            fit_robust="Low",
            gate_expectancy=g_exp,
            gate_tpy=g_tpy,
            gate_robust=g_rob,
            gate_sheet=g_sheet,
            gates_pass=False,
            gates_passed=0,
        )

    # Soft floor only: near-zero tpy gets a note, not a score hit.
    if 0 < avg_tpy < 0.2:
        notes.append("rare setups")

    score = _fit_component_score(
        pct_wins=pct_wins,
        pnl_pct_for_avg_bucket=avg_pnl_pct,
        sheet_pnl=sheet_pnl,
        avg_tpy=avg_tpy,
        wins=wins,
        losses=losses,
        asym_penalty=asym,
        outlier_penalty=0,
    )
    # Robust: same win-rate / tpy / clean-book / asymmetry; PnL + sheet buckets use
    # leave-max-win-out values; soft outlier penalty still applies.
    score_robust = _fit_component_score(
        pct_wins=pct_wins,
        pnl_pct_for_avg_bucket=avg_wo_max if pnls else avg_pnl_pct,
        sheet_pnl=sheet_wo_max if pnls else sheet_pnl,
        avg_tpy=avg_tpy,
        wins=wins,
        losses=losses,
        asym_penalty=asym,
        outlier_penalty=outlier_pen,
    )
    fit = _fit_tier(score)
    fit_robust = _fit_tier(score_robust)

    g_exp, g_tpy, g_rob, g_sheet = _fit_assessment_gates(
        avg_pnl_pct=avg_pnl_pct,
        avg_tpy=avg_tpy,
        avg_pnl_pct_wo_max=avg_wo_max,
        sheet_pnl=sheet_pnl,
    )
    gates_passed = int(g_exp) + int(g_tpy) + int(g_rob) + int(g_sheet)
    gates_pass = gates_passed == 4
    gate_line = _fit_gates_assessment_text(
        avg_pnl_pct=avg_pnl_pct,
        avg_tpy=avg_tpy,
        avg_pnl_pct_wo_max=avg_wo_max,
        sheet_pnl=sheet_pnl,
        g_exp=g_exp,
        g_tpy=g_tpy,
        g_rob=g_rob,
        g_sheet=g_sheet,
    )

    head = (
        f"{fit}: {gate_line}; "
        f"{pct_wins:.0f}%W avg {avg_pnl_pct:+.1f}% {trades}tr/{avg_tpy:.1f}y"
    )
    if notes:
        head = f"{head}; " + "; ".join(notes[:2])
    # Flag when robust is materially weaker (outlier-carried mean / sheet).
    if score_robust <= score - 2 or (
        fit_robust != fit and _fit_tier_rank(fit_robust) < _fit_tier_rank(fit)
    ):
        wo_note = f"wo-max avg {avg_wo_max:+.1f}%" if dropped_max else f"avg {avg_pnl_pct:+.1f}%"
        head = (
            f"{head}; robust {fit_robust} ({wo_note}, "
            f"outlier {outlier_of_wins:.0f}% of wins)"
        )
    return FitResult(
        fit=fit,
        score=score,
        text=head[:400],
        score_robust=score_robust,
        fit_robust=fit_robust,
        max_win_pct=max_win,
        median_pnl_pct=median_pnl,
        avg_pnl_pct_wo_max=avg_wo_max,
        sheet_pnl_wo_max=sheet_wo_max,
        outlier_pct_of_wins=outlier_of_wins,
        outlier_pct_of_sheet=outlier_of_sheet,
        outlier_penalty=outlier_pen,
        gate_expectancy=g_exp,
        gate_tpy=g_tpy,
        gate_robust=g_rob,
        gate_sheet=g_sheet,
        gates_pass=gates_pass,
        gates_passed=gates_passed,
    )


def _fit_tier_rank(fit: str) -> int:
    return {"High": 2, "Medium": 1, "Low": 0}.get(str(fit), 0)


def _ensure_summary_yf_meta_fieldnames(fieldnames: list[str]) -> list[str]:
    """Insert CURRENT_MARKET_CAP / SECTOR / INDUSTRY after PCT_OF_TOTAL_PNL (BRT order)."""
    out = [c for c in fieldnames if c not in SUMMARY_YF_META_COLS]
    if "PCT_OF_TOTAL_PNL" in out:
        i = out.index("PCT_OF_TOTAL_PNL") + 1
        for col in SUMMARY_YF_META_COLS:
            out.insert(i, col)
            i += 1
        return out
    # Fallback: before FIRST_DATA_DATE, else append.
    if "FIRST_DATA_DATE" in out:
        i = out.index("FIRST_DATA_DATE")
        for j, col in enumerate(SUMMARY_YF_META_COLS):
            out.insert(i + j, col)
        return out
    out.extend(SUMMARY_YF_META_COLS)
    return out


def _ensure_summary_avg_days_held_fieldnames(fieldnames: list[str]) -> list[str]:
    """Insert ``AVG_DAYS_HELD`` after ``AVG_TRADES_PER_YEAR`` (or ``AVG_PNL_PCT``).

    Drops legacy ``AVG_DAYS`` so Summary CSVs converge on one name (matches MVCP /
    ``write_brt_summary``; Report/Audit keep Title-Case ``Avg_Days_Held``).
    """
    out = [c for c in fieldnames if c not in ("AVG_DAYS_HELD", "AVG_DAYS")]
    if "AVG_TRADES_PER_YEAR" in out:
        out.insert(out.index("AVG_TRADES_PER_YEAR") + 1, "AVG_DAYS_HELD")
    elif "AVG_PNL_PCT" in out:
        out.insert(out.index("AVG_PNL_PCT") + 1, "AVG_DAYS_HELD")
    else:
        out.append("AVG_DAYS_HELD")
    return out


def enrich_summary_csv_with_avg_days_held(
    summary_path: Path,
    closed_path: Path,
) -> int:
    """Fill / rename ``AVG_DAYS_HELD`` on Summary from Closed ``DAYS_HELD`` (mean per symbol)."""
    sp = Path(summary_path)
    cp = Path(closed_path)
    if not sp.is_file():
        return 0

    by_sym: dict[str, list[float]] = defaultdict(list)
    if cp.is_file():
        with cp.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("SYMBOL", "")).strip().upper()
                if not sym or sym == "ALL":
                    continue
                days = _fnum(_col(row, "DAYS_HELD", "DAYS HELD", "DAYS"), default=float("nan"))
                if days == days:  # not NaN
                    by_sym[sym].append(float(days))

    with sp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return 0

    fieldnames = _ensure_summary_avg_days_held_fieldnames(fieldnames)
    for row in rows:
        sym = str(row.get("SYMBOL", "")).strip().upper()
        legacy = str(row.get("AVG_DAYS", "") or "").strip()
        days_list = by_sym.get(sym, [])
        if days_list:
            row["AVG_DAYS_HELD"] = f"{(sum(days_list) / len(days_list)):.1f}"
        elif legacy:
            row["AVG_DAYS_HELD"] = legacy
        else:
            existing = str(row.get("AVG_DAYS_HELD", "") or "").strip()
            row["AVG_DAYS_HELD"] = existing
        row.pop("AVG_DAYS", None)

    with sp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def lookup_yfinance_symbol_meta(
    symbols: list[str] | set[str],
    *,
    yfinance_workers: Optional[int] = None,
    allow_stale_cache: bool = True,
) -> dict[str, dict[str, Any]]:
    """Return ``{SYM: {market_cap, sector, industry, ...}}`` using repo ``yfinance_cache.json``.

    Same cache / fetch path as BRT ``_enrich_trades_yfinance`` (today-fresh preferred;
    ``allow_stale_cache`` keeps prior-day cache hits to avoid Yahoo when backfilling).
    """
    syms = sorted({str(s).strip().upper() for s in symbols if str(s).strip()})
    if not syms:
        return {}
    try:
        from rocket_tbn import (  # type: ignore
            _load_yfinance_cache,
            _save_yfinance_cache,
            _yfinance_backfill_market_cap,
            _yfinance_cache_entry_fresh,
            _yfinance_fetch_symbol_info,
        )
    except ImportError:
        from stock_analysis.rocket_tbn import (  # type: ignore
            _load_yfinance_cache,
            _save_yfinance_cache,
            _yfinance_backfill_market_cap,
            _yfinance_cache_entry_fresh,
            _yfinance_fetch_symbol_info,
        )
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    file_cache = _load_yfinance_cache()
    cache: dict[str, dict[str, Any]] = {}
    to_fetch: list[str] = []
    for sym in syms:
        entry = dict(file_cache.get(sym, {}) or {})
        if _yfinance_cache_entry_fresh(entry, today, allow_stale=bool(allow_stale_cache)):
            cache[sym] = _yfinance_backfill_market_cap(entry)
        else:
            to_fetch.append(sym)

    n_cached = len(syms) - len(to_fetch)
    if n_cached or to_fetch:
        print(
            f"[analysis] yfinance summary meta: {n_cached} from cache, "
            f"{len(to_fetch)} fetch",
            flush=True,
        )

    if to_fetch:
        if yfinance_workers is None or yfinance_workers < 1:
            _yf_w = min(8, os.cpu_count() or 4, max(1, len(to_fetch)))
        else:
            _yf_w = min(int(yfinance_workers), 24, max(1, len(to_fetch)))
        if len(to_fetch) > 1 and _yf_w > 1:
            with ThreadPoolExecutor(max_workers=_yf_w) as ex:
                futs = [ex.submit(_yfinance_fetch_symbol_info, sym, today) for sym in to_fetch]
                for fut in as_completed(futs):
                    sym, data = fut.result()
                    cache[sym] = data or {}
        else:
            for sym in to_fetch:
                sym2, data = _yfinance_fetch_symbol_info(sym, today)
                cache[sym2] = data or {}
        merged = dict(file_cache)
        for sym, data in cache.items():
            if not data:
                continue
            if data.get("as_of_date") == today or data.get("_yf_checked"):
                row = dict(data)
                if row.get("as_of_date") != today:
                    row["as_of_date"] = today
                row["_yf_checked"] = True
                merged[sym] = row
        _save_yfinance_cache(merged)

    return {s: cache.get(s, {}) for s in syms}


def enrich_summary_csv_with_yfinance(
    summary_path: Path,
    *,
    no_yfinance: bool = False,
    yfinance_workers: Optional[int] = None,
) -> int:
    """Ensure Summary has CURRENT_MARKET_CAP / SECTOR / INDUSTRY (BRT/YH/RS names).

    Inserts columns after ``PCT_OF_TOTAL_PNL`` when missing, then fills from Yahoo cache
    (and fresh fetch on miss). Safe for SB/MVCP backfill via ``--refresh-cheap``.
    """
    sp = Path(summary_path)
    if not sp.is_file():
        return 0

    with sp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return 0

    fieldnames = _ensure_summary_yf_meta_fieldnames(fieldnames)
    if no_yfinance:
        for row in rows:
            for col in SUMMARY_YF_META_COLS:
                row.setdefault(col, "")
        with sp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    symbols = [
        str(r.get("SYMBOL", "")).strip().upper()
        for r in rows
        if str(r.get("SYMBOL", "")).strip()
    ]
    meta = lookup_yfinance_symbol_meta(symbols, yfinance_workers=yfinance_workers)
    for row in rows:
        sym = str(row.get("SYMBOL", "")).strip().upper()
        c = meta.get(sym, {}) or {}
        mc = c.get("market_cap")
        try:
            row["CURRENT_MARKET_CAP"] = f"{float(mc):.0f}" if mc is not None else ""
        except (TypeError, ValueError):
            row["CURRENT_MARKET_CAP"] = ""
        sector = c.get("sector")
        industry = c.get("industry")
        row["SECTOR"] = str(sector).replace(",", " ") if sector is not None else ""
        row["INDUSTRY"] = str(industry).replace(",", " ") if industry is not None else ""

    with sp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# Paul Score: per-run peer thresholds on Summary (after FIT / WO_MAX cols exist).
# +1 each if value ≥ mean: PCT_WINS, TOTAL_PNL, SHEET_PNL, AVG_PNL_PCT,
# AVG_PNL_PCT_WO_MAX, AVG_TRADES_PER_YEAR; +1 if ≤ mean:
# OUTLIER_PCT_OF_WINS, AVG_DAYS_HELD (faster turnover = better).
# Peer median is diagnostic-only (not used for thresholds). MEDIAN_PNL_PCT is never scored.
# Integer 0–8. Blank/non-numeric cells skipped for thresholds and that component.
_PAUL_SCORE_COL = "PAUL_SCORE"
_PAUL_SCORE_HIGH_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("PCT_WINS", "Pct_Wins", "PCT_WINS_%"),
    ("TOTAL_PNL", "Total_PNL", "Total_PnL"),
    ("SHEET_PNL", "Sheet_PNL", "sheet_Total_PNL", "SHEET_TOTAL_PNL"),
    ("AVG_PNL_PCT", "Avg_PNL_Pct", "AVG_PNL_%"),
    ("AVG_PNL_PCT_WO_MAX", "Avg_PNL_Pct_WO_Max"),
    ("AVG_TRADES_PER_YEAR", "Avg_Trades_Per_Year", "AVG_TPY"),
)
_PAUL_SCORE_LOW_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("OUTLIER_PCT_OF_WINS", "Outlier_Pct_Of_Wins"),
    ("AVG_DAYS_HELD", "Avg_Days_Held", "AVG_DAYS"),
)


def _optional_fnum(val: Any) -> Optional[float]:
    """Parse a numeric Summary cell; return None for blank / non-numeric (keeps 0.0)."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip().replace("%", "").replace(",", "")
    if not s or s.upper() in ("N/A", "NAN", "NONE"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _resolve_summary_col(fieldnames: list[str], *candidates: str) -> Optional[str]:
    """Return the actual header matching any candidate (exact, then case-insensitive)."""
    if not fieldnames:
        return None
    exact = {c: c for c in fieldnames}
    lower = {str(c).strip().lower(): c for c in fieldnames}
    for name in candidates:
        if name in exact:
            return exact[name]
        hit = lower.get(str(name).strip().lower())
        if hit is not None:
            return hit
    return None


def apply_paul_scores_to_summary_rows(
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> dict[str, Any]:
    """Write ``PAUL_SCORE`` (0–8) on each row; ensure column is in *fieldnames*.

    Returns threshold diagnostics: resolved cols, per-field mean/median (diag)/threshold.
    """
    if _PAUL_SCORE_COL not in fieldnames:
        fieldnames.append(_PAUL_SCORE_COL)

    high_specs: list[tuple[str, str]] = []  # (resolved_col, label)
    for cands in _PAUL_SCORE_HIGH_CANDIDATES:
        col = _resolve_summary_col(fieldnames, *cands)
        if col:
            high_specs.append((col, cands[0]))
    low_specs: list[tuple[str, str]] = []
    for cands in _PAUL_SCORE_LOW_CANDIDATES:
        col = _resolve_summary_col(fieldnames, *cands)
        if col:
            low_specs.append((col, cands[0]))

    thresholds: dict[str, dict[str, Any]] = {}
    high_thr: dict[str, float] = {}
    low_thr: dict[str, float] = {}

    for col, label in high_specs:
        vals = [v for row in rows if (v := _optional_fnum(row.get(col))) is not None]
        if not vals:
            continue
        mean_v = float(statistics.mean(vals))
        med_v = float(statistics.median(vals))
        thr = mean_v
        high_thr[col] = thr
        thresholds[label] = {
            "col": col,
            "n": len(vals),
            "mean": mean_v,
            "median": med_v,
            "threshold": thr,
            "rule": ">= mean",
        }

    for col, label in low_specs:
        vals = [v for row in rows if (v := _optional_fnum(row.get(col))) is not None]
        if not vals:
            continue
        mean_v = float(statistics.mean(vals))
        med_v = float(statistics.median(vals))
        thr = mean_v
        low_thr[col] = thr
        thresholds[label] = {
            "col": col,
            "n": len(vals),
            "mean": mean_v,
            "median": med_v,
            "threshold": thr,
            "rule": "<= mean",
        }

    for row in rows:
        score = 0
        for col, _label in high_specs:
            thr = high_thr.get(col)
            if thr is None:
                continue
            v = _optional_fnum(row.get(col))
            if v is not None and v >= thr:
                score += 1
        for col, _label in low_specs:
            thr = low_thr.get(col)
            if thr is None:
                continue
            v = _optional_fnum(row.get(col))
            if v is not None and v <= thr:
                score += 1
        row[_PAUL_SCORE_COL] = str(int(score))

    return {"column": _PAUL_SCORE_COL, "max_score": 8, "thresholds": thresholds}


def enrich_summary_csv_with_fit(
    summary_path: Path,
    closed_path: Path,
    *,
    prefix: str = "RL",
) -> int:
    """Add FIT (+ RL_FIT when prefix is RL), robust/outlier cols, and PAUL_SCORE to Summary CSV."""
    sp = Path(summary_path)
    cp = Path(closed_path)
    if not sp.is_file():
        return 0

    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if cp.is_file():
        with cp.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("SYMBOL", "")).strip().upper()
                if sym:
                    by_sym[sym].append(row)

    with sp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if not fieldnames:
        return 0

    # Keep Yahoo meta columns in BRT position if a prior enrich already added them.
    if any(c in fieldnames for c in SUMMARY_YF_META_COLS):
        fieldnames = _ensure_summary_yf_meta_fieldnames(fieldnames)

    fieldnames = _ensure_summary_profit_factor_fieldnames(fieldnames)

    fit_cols = [
        "FIT",
        "FIT_SCORE",
        "FIT_SCORE_ROBUST",
        "MAX_WIN_PCT",
        "AVG_PNL_PCT_WO_MAX",
        "MEDIAN_PNL_PCT",
        "OUTLIER_PCT_OF_WINS",
        "FIT_ASSESSMENT",
    ]
    if normalize_system(prefix) in RL_SYSTEMS:
        fit_cols = ["RL_FIT", *fit_cols]
    for col in fit_cols:
        if col not in fieldnames:
            fieldnames.append(col)

    for row in rows:
        sym = str(row.get("SYMBOL", "")).strip().upper()
        if sym in ("", "ALL"):
            continue
        closed_sym = by_sym.get(sym, [])
        stats = resolve_symbol_ledger_stats(row, closed_sym)
        fr = assess_symbol_fit(
            trades=int(stats["trades"]),
            wins=int(stats["wins"]),
            losses=int(stats["losses"]),
            pct_wins=float(stats["pct_wins"]),
            avg_pnl_pct=float(stats["avg_pnl_pct"]),
            sheet_pnl=float(stats["sheet_pnl"]),
            avg_tpy=float(stats["avg_tpy"]),
            closed_rows=closed_sym,
        )
        # Per-symbol PF from Closed (overwrites thin/missing Summary cells).
        if closed_sym:
            pf = profit_factor_from_dollar_pnls(_closed_trade_dollar_pnls(closed_sym))
            row["PROFIT_FACTOR"] = f"{pf:.2f}"
        elif not str(row.get("PROFIT_FACTOR", "") or "").strip():
            row["PROFIT_FACTOR"] = ""
        row["FIT"] = fr.fit
        if "RL_FIT" in fieldnames:
            row["RL_FIT"] = fr.fit
        row["FIT_SCORE"] = str(fr.score)
        row["FIT_SCORE_ROBUST"] = str(fr.score_robust)
        row["MAX_WIN_PCT"] = f"{fr.max_win_pct:.2f}%" if fr.max_win_pct else "0.00%"
        # Numeric pct points (like Report Avg_PNL_Pct); format with % only at HTML/render time.
        row["AVG_PNL_PCT_WO_MAX"] = f"{fr.avg_pnl_pct_wo_max:.2f}"
        row["MEDIAN_PNL_PCT"] = f"{fr.median_pnl_pct:.2f}"
        row["OUTLIER_PCT_OF_WINS"] = f"{fr.outlier_pct_of_wins:.1f}"
        row["FIT_ASSESSMENT"] = fr.text

    # After WO_MAX / outlier FIT cols exist: peer Paul Score (0–8) vs this Summary's mean.
    apply_paul_scores_to_summary_rows(rows, fieldnames)

    with sp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Improve hints (portfolio-level, prioritized)
# ---------------------------------------------------------------------------

@dataclass
class ImproveHint:
    hypothesis_id: str
    priority: int
    symbol_count: int
    trade_count: int
    symbols: list[str]
    lever: str
    suggestion: str
    evidence: str
    category: str = "pattern"
    param: str = ""
    direction: str = ""
    confidence: str = ""
    pct_of_trades: float = 0.0
    heuristic: str = ""


def _hint_catalog(prefix: str) -> dict[str, tuple[str, str]]:
    """Hypothesis id -> (lever, suggestion). RL keeps dip/trail levers; others generic."""
    p = normalize_system(prefix)
    generic = {
        "post_target_quick_stop": (
            "rl_post_target_reentry_bars + mode (or longer symbol_reentry_cooldown_days)",
            "Many symbols take a TARGET then immediately re-enter and STOP quickly — "
            "test post-TARGET-only cooldown (mode=none / under_sma_limit) or longer blanket cd.",
        ),
        "shallow_entry_sma50_fail": (
            "entry quality / SMA or zone proximity gates",
            "Quick stops with entry hugging SMA50 suggest shallow dips — "
            "tighten entry band or require stronger structure.",
        ),
        "mtm_giveback_stop": (
            "trail_profit / trail_stop (or partial scale-out)",
            "Trades that ran ≥15% MTM then exited STOP — trails may salvage giveback.",
        ),
        "false_start_2022_2023": (
            "slope/regime gates, optional start_date / SPY weak block",
            "Cluster of short 2022–2023 STOP false starts — regime filters may help "
            "(tradeoff: fewer bull-market entries).",
        ),
        "small_target_wins": (
            "target_pct / expansion / partial_exit",
            "Many small TARGET wins — consider higher target or partial scale-out.",
        ),
        "fat_stops": (
            "stop_pct (tighter) or time-stop / cut_the_losers",
            "Large STOP losses dominate — tighter stop or time-based exit.",
        ),
        # Slow-winner / long-hold turnover lenses (Ann_ROR / trades-per-year over max single PnL)
        "slow_target_grind": (
            "target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take",
            "Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) "
            "recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag "
            "(one knob A/B; not an optimize sweep).",
        ),
        "winner_peak_giveback": (
            "trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out",
            "Winners that peaked ≥15% MFE then exited ≥10pp below peak — "
            "trail or scale-out may lock more of the run (hypothesis; one trail knob).",
        ),
        "early_run_long_tail": (
            "trail after +10% / lower target_pct / shorter time_stop after milestone",
            "Hit +10% within 25 days then held ≥80 days — capital sat after the early run; "
            "test trail-after-+10%, STRENGTH-style early take, or shorter time_stop "
            "(turnover over max single-trade profit).",
        ),
    }
    if p in RL_SYSTEMS:
        return {
            "post_target_quick_stop": (
                "rl_post_target_reentry_bars + rl_post_target_reentry_mode "
                "(stop_loss / min_stack / under_sma_limit / none)",
                "Many symbols take a TARGET then immediately re-enter and STOP quickly — "
                "A/B modes: stop_loss (N×stop_pct), min_stack, under_sma_limit, or none cooldown; "
                "avoid calendar symbol_reentry_cooldown_days (kills NTRA ladder).",
            ),
            "shallow_entry_sma50_fail": (
                "rl_dip_pct (tighter), rl_slope_threshold, rl_sma_qual stack",
                "Quick stops with entry hugging SMA50 suggest shallow dips / weak slope — "
                "tighten dip band or require stronger SMA50 slope.",
            ),
            "mtm_giveback_stop": (
                "rl_trail_profit / rl_trail_stop (or trail2)",
                "Trades that ran ≥15% MTM then exited STOP — trails may salvage giveback.",
            ),
            "false_start_2022_2023": (
                "rl_slope_threshold, rl_cut_the_losers, optional start_date / regime filter",
                "Cluster of short 2022–2023 STOP false starts — slope/extension gates or "
                "SPY INT weak block may help (tradeoff: fewer bull-market entries).",
            ),
            "small_target_wins": (
                "rl_target_pct / rl_expansion / partial_exit",
                "Many small TARGET wins — consider higher target or partial scale-out to let runners work.",
            ),
            "fat_stops": (
                "rl_stop_pct (tighter) or rl_exit_percent/days time-stop",
                "Large STOP losses dominate — tighter stop or time-based cut_the_losers exit.",
            ),
            "slow_target_grind": (
                "rl_target_pct (contract) — alt: rl_exit_percent/days or rl_partial_exit",
                "Many TARGET hits took ≥100 days — hypothesis: closer target / partial exit / "
                "RL_EXIT_DAYS after a profit gate recycles capital sooner (turnover/Ann_ROR; one knob).",
            ),
            "winner_peak_giveback": (
                "rl_trail_profit / rl_trail_stop (or trail2) or rl_partial_exit",
                "Winners that peaked ≥15% MFE then exited ≥10pp below peak — "
                "enable trail or partial scale-out (hypothesis; one knob).",
            ),
            "early_run_long_tail": (
                "rl_trail_profit after ~+10% / rl_target_pct contract / rl_exit_days",
                "Hit +10% within 25 days then held ≥80 days — test trail-after-profit, "
                "closer target, or RL_EXIT_DAYS (turnover over max single-trade).",
            ),
        }
    if p in ZONE_SYSTEMS:
        generic["shallow_entry_sma50_fail"] = (
            "band_pct / zone strength / touch_count gates",
            "Quick stops near entry — tighten zone band, require stronger pivot, or "
            "raise min touch_count / zone_strength.",
        )
        generic["post_target_quick_stop"] = (
            "rl_post_target_reentry_bars + rl_post_target_reentry_mode "
            "(none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days",
            "TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.",
        )
    if p == "SB":
        generic["slow_target_grind"] = (
            "target_pct (contract) — alt: shorter burst_time_stop_days",
            "Slow TARGET grinds (≥100d) — SB already times out fast in prod; if this fires, "
            "closer target_pct may still improve turnover (one knob).",
        )
        generic["early_run_long_tail"] = (
            "target_pct (contract) / burst_time_stop_days / burst_no_ft_days",
            "Early +10% then long hold — closer target or tighter TIME/NO_FT (hypothesis).",
        )
    if p == "MVCP":
        generic["slow_target_grind"] = (
            "mvcp_strength_pct/bars (earlier STRENGTH) or target_pct contract",
            "Slow full TARGET — raise STRENGTH early-take aggressiveness or lower full target "
            "(one knob; turnover/Ann_ROR framing).",
        )
        generic["winner_peak_giveback"] = (
            "mvcp_trail_sma / mvcp_trail_arm_pct (earlier arm) or partial scale-out",
            "Winners that gave back MFE — arm trail sooner after +X% (hypothesis).",
        )
        generic["early_run_long_tail"] = (
            "mvcp_strength_* early take / mvcp_trail_arm_pct / mvcp_time_stop_*",
            "Early +10% then long hold — STRENGTH early take or earlier trail arm (one knob).",
        )
    return generic


def _collect_improve_hints(
    closed_rows: list[dict[str, Any]],
    *,
    prefix: str = "RL",
    tickers=None,
    data_dir=None,
    drive_dir=None,
    rejected_fills_path=None,
    include_param_tweaks: bool = True,
    include_peer_learn: bool = True,
) -> list[ImproveHint]:
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in closed_rows:
        sym = str(_col(r, "SYMBOL", default="")).strip().upper()
        if sym:
            by_sym[sym].append(r)

    for sym in by_sym:
        by_sym[sym].sort(
            key=lambda r: (_ymd8(_col(r, "DATE OPENED", "DATE_OPENED")), _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED")))
        )

    hit_syms: dict[str, set[str]] = defaultdict(set)
    hit_trades: Counter[str] = Counter()
    evidence: dict[str, list[str]] = defaultdict(list)

    for sym, trades in by_sym.items():
        for i, r in enumerate(trades):
            exit_type = str(_col(r, "EXIT TYPE", "EXIT_TYPE", default="")).upper()
            days = int(_fnum(_col(r, "DAYS HELD", "DAYS_HELD"), 0))
            pnl = _fnum(_col(r, "PNL %", "PNL_PCT"))
            max_gain = _fnum(_col(r, "MAX GAIN", "MAX_GAIN"))
            if 0 < abs(max_gain) < 2:
                max_gain_pct = abs(max_gain) * 100
            else:
                max_gain_pct = abs(max_gain) if ("MAX GAIN" in r or "MAX_GAIN" in r) else 0.0
            entry = _fnum(_col(r, "ENTRY PRICE", "ENTRY_PRICE"))
            s50 = _fnum(_col(r, "SMA50"))
            ymd_out = _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED"))
            year = int(ymd_out[:4]) if len(ymd_out) >= 4 and ymd_out[:4].isdigit() else 0

            if i + 1 < len(trades):
                nxt = trades[i + 1]
                nxt_exit = str(_col(nxt, "EXIT TYPE", "EXIT_TYPE", default="")).upper()
                nxt_days = int(_fnum(_col(nxt, "DAYS HELD", "DAYS_HELD"), 0))
                if "TARGET" in exit_type and "STOP" in nxt_exit and nxt_days <= 10:
                    hid = "post_target_quick_stop"
                    hit_syms[hid].add(sym)
                    hit_trades[hid] += 1
                    if len(evidence[hid]) < 8:
                        evidence[hid].append(
                            f"{sym} TARGET {_iso_dash(_col(r, 'DATE CLOSED', 'DATE_CLOSED'))} -> "
                            f"STOP {_iso_dash(_col(nxt, 'DATE CLOSED', 'DATE_CLOSED'))} ({nxt_days}d)"
                        )

            if "STOP" in exit_type and days <= 7 and entry > 0 and s50 > 0:
                rel = abs(entry / s50 - 1.0) * 100.0
                if rel <= 3.0:
                    hid = "shallow_entry_sma50_fail"
                    hit_syms[hid].add(sym)
                    hit_trades[hid] += 1
                    if len(evidence[hid]) < 8:
                        evidence[hid].append(
                            f"{sym} {_iso_dash(_col(r, 'DATE OPENED', 'DATE_OPENED'))} stop {days}d entry~SMA50"
                        )

            if "STOP" in exit_type and max_gain_pct >= 15 and pnl < 0:
                hid = "mtm_giveback_stop"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1
                if len(evidence[hid]) < 8:
                    evidence[hid].append(
                        f"{sym} peak~{max_gain_pct:.0f}% -> STOP {_pct_str(pnl)} "
                        f"({_iso_dash(_col(r, 'DATE CLOSED', 'DATE_CLOSED'))})"
                    )

            if "STOP" in exit_type and year in (2022, 2023) and days <= 15 and pnl < 0:
                hid = "false_start_2022_2023"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1
                if len(evidence[hid]) < 8:
                    evidence[hid].append(f"{sym} {year} STOP {days}d {_pct_str(pnl)}")

            if "TARGET" in exit_type and 0 < pnl < 8:
                hid = "small_target_wins"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1

            if "STOP" in exit_type and pnl <= -12:
                hid = "fat_stops"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1

            # --- Slow-winner / long-hold turnover lenses ---
            # Prefer Closed MAX_PRICE MFE when present; fall back to MAX_GAIN %.
            entry_px = entry
            max_px = _fnum(_col(r, "MAX_PRICE", "MAX PRICE"))
            if entry_px > 0 and max_px > entry_px:
                mfe_pct = (max_px / entry_px - 1.0) * 100.0
            else:
                mfe_pct = max_gain_pct
            d10 = _fnum(_col(r, "DAYS_HELD_FIRST_UP_10PCT", "DAYS HELD FIRST UP 10PCT"), -1.0)

            if "TARGET" in exit_type and days >= 100:
                hid = "slow_target_grind"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1
                if len(evidence[hid]) < 8:
                    ppd = (pnl / days) if days > 0 else 0.0
                    evidence[hid].append(
                        f"{sym} TARGET {days}d {_pct_str(pnl)} (~{ppd:.2f}%/d) "
                        f"{_iso_dash(_col(r, 'DATE CLOSED', 'DATE_CLOSED'))}"
                    )

            if pnl > 0 and mfe_pct >= 15.0 and (mfe_pct - pnl) >= 10.0 and days >= 15:
                hid = "winner_peak_giveback"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1
                if len(evidence[hid]) < 8:
                    evidence[hid].append(
                        f"{sym} peak~{mfe_pct:.0f}% -> exit {_pct_str(pnl)} "
                        f"(giveback~{mfe_pct - pnl:.0f}pp, {days}d, {exit_type})"
                    )

            if pnl > 0 and 0 < d10 <= 25 and days >= 80:
                hid = "early_run_long_tail"
                hit_syms[hid].add(sym)
                hit_trades[hid] += 1
                if len(evidence[hid]) < 8:
                    evidence[hid].append(
                        f"{sym} +10% by day {int(d10)} then held {days}d "
                        f"exit {_pct_str(pnl)} ({exit_type})"
                    )

    catalog = _hint_catalog(prefix)
    hints: list[ImproveHint] = []
    for hid, (lever, suggestion) in catalog.items():
        n_sym = len(hit_syms.get(hid, ()))
        n_tr = int(hit_trades.get(hid, 0))
        if n_tr < 2 and n_sym < 2:
            continue
        priority = n_sym * 10 + n_tr
        hints.append(
            ImproveHint(
                hypothesis_id=hid,
                priority=priority,
                symbol_count=n_sym,
                trade_count=n_tr,
                symbols=sorted(hit_syms[hid])[:40],
                lever=lever,
                suggestion=suggestion,
                evidence="; ".join(evidence.get(hid, [])[:5]),
                category="pattern",
            )
        )

    if include_param_tweaks:
        try:
            for ph in collect_param_tweak_hints(
                closed_rows,
                prefix=prefix,
                tickers=tickers,
                data_dir=data_dir,
                drive_dir=drive_dir,
                rejected_fills_path=rejected_fills_path,
                include_peer_learn=include_peer_learn,
            ):
                hints.append(
                    ImproveHint(
                        hypothesis_id=ph.hypothesis_id,
                        priority=ph.priority,
                        symbol_count=ph.symbol_count,
                        trade_count=ph.trade_count,
                        symbols=list(ph.symbols)[:40],
                        lever=ph.lever,
                        suggestion=ph.suggestion,
                        evidence=ph.evidence,
                        category=ph.category,
                        param=ph.param,
                        direction=ph.direction,
                        confidence=ph.confidence,
                        pct_of_trades=float(ph.pct_of_trades),
                        heuristic=ph.heuristic,
                    )
                )
        except Exception as e:
            print(
                f"[{normalize_system(prefix) or prefix} analysis] param tweak hints failed: {e}",
                file=sys.stderr,
            )

    hints.sort(key=lambda h: (-h.priority, h.hypothesis_id))
    return hints


_IMPROVE_HINTS_HTML_CSS = """
th.sortable-th { cursor:pointer; user-select:none; white-space:nowrap; }
th.sortable-th:hover { background:#e2e8f0; }
th.sortable-th .sort-ind::after { content:" \\2195"; opacity:0.35; font-size:0.85em; }
th.sortable-th.sort-asc .sort-ind::after { content:" \\2191"; opacity:0.9; }
th.sortable-th.sort-desc .sort-ind::after { content:" \\2193"; opacity:0.9; }
.conf-high { color:#166534; font-weight:600; }
.conf-medium { color:#92400e; font-weight:600; }
.conf-low { color:#475569; }
.conf-insufficient { color:#94a3b8; font-style:italic; }
"""


_IMPROVE_HINTS_SORT_SCRIPT = """
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


def _sortable_th_hint(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _hint_md_title(h: ImproveHint, idx: int) -> str:
    title = f"## {idx}. `{h.hypothesis_id}` ({h.symbol_count} sym / {h.trade_count} trades)"
    meta: list[str] = []
    if h.direction:
        meta.append(f"direction: {h.direction}")
    if h.confidence:
        meta.append(f"confidence: {h.confidence}")
    if h.pct_of_trades:
        meta.append(f"{h.pct_of_trades:.1f}% of trades")
    if meta:
        title += " — " + ", ".join(meta)
    return title


def _hint_md_lines(h: ImproveHint, idx: int) -> list[str]:
    lines = [_hint_md_title(h, idx)]
    if h.param:
        lines.append(f"- **Param:** {h.param}")
    lines.append(f"- **Lever:** {h.lever}")
    lines.append(f"- **Suggestion:** {h.suggestion}")
    if h.heuristic:
        lines.append(f"- **Heuristic:** {h.heuristic}")
    lines.append(f"- **Symbols:** {', '.join(h.symbols[:20])}")
    if h.evidence:
        lines.append(f"- **Evidence:** {h.evidence}")
    lines.append("")
    return lines


def _hints_by_category(hints: list[ImproveHint], category: str) -> list[ImproveHint]:
    return [h for h in hints if h.category == category]


def _conf_html(conf: str) -> str:
    c = (conf or "").strip().lower()
    if not c:
        return "—"
    cls = {
        "high": "conf-high",
        "medium": "conf-medium",
        "low": "conf-low",
        "insufficient": "conf-insufficient",
    }.get(c, "")
    if cls:
        return f'<span class="{cls}">{html.escape(conf)}</span>'
    return html.escape(conf)


def _improve_hints_table_rows(hints: list[ImproveHint], *, start_idx: int = 1) -> list[str]:
    rows: list[str] = []
    for i, h in enumerate(hints, start_idx):
        pct = f"{h.pct_of_trades:.1f}" if h.pct_of_trades else "—"
        rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{html.escape(h.category)}</td>"
            f"<td>{html.escape(h.hypothesis_id)}</td>"
            f"<td>{html.escape(h.param or '—')}</td>"
            f"<td>{html.escape(h.direction or '—')}</td>"
            f"<td>{_conf_html(h.confidence)}</td>"
            f"<td>{h.symbol_count}</td>"
            f"<td>{h.trade_count}</td>"
            f"<td>{pct}</td>"
            f"<td>{html.escape(h.lever)}</td>"
            f"<td>{html.escape(h.suggestion)}</td>"
            f"<td>{html.escape(','.join(h.symbols[:15]))}</td>"
            f"<td>{html.escape(h.evidence)}</td>"
            f"<td>{html.escape(h.heuristic or '—')}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="14">No hints in this section.</td></tr>')
    return rows


def _improve_hints_table_html(hints: list[ImproveHint], *, start_idx: int = 1) -> str:
    head = "".join(
        [
            _sortable_th_hint("#", "num"),
            _sortable_th_hint("Category", "text"),
            _sortable_th_hint("Hypothesis", "text"),
            _sortable_th_hint("Param", "text"),
            _sortable_th_hint("Direction", "text"),
            _sortable_th_hint("Confidence", "text"),
            _sortable_th_hint("Symbols", "num"),
            _sortable_th_hint("Trades", "num"),
            _sortable_th_hint("% trades", "num"),
            _sortable_th_hint("Lever", "text"),
            _sortable_th_hint("Suggestion", "text"),
            _sortable_th_hint("Example symbols", "text"),
            _sortable_th_hint("Evidence", "text"),
            _sortable_th_hint("Heuristic", "text"),
        ]
    )
    body = "".join(_improve_hints_table_rows(hints, start_idx=start_idx))
    return f'<table class="sortable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def write_improve_hints(
    closed_path: Path,
    output_dir: Path,
    ts: str,
    *,
    prefix: str = "RL",
    tickers=None,
    data_dir=None,
    drive_dir=None,
    rejected_fills_path=None,
    include_param_tweaks: bool = True,
    include_peer_learn: bool = True,
) -> Optional[Path]:
    """Write ``{prefix}_ImproveHints_<ts>.csv|.md|.html``. Returns CSV path or None."""
    cp = Path(closed_path)
    if not cp.is_file():
        return None
    with cp.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pref = normalize_system(prefix) or "RL"
    drive = drive_dir or out_dir

    rej = rejected_fills_path
    if rej is None and include_param_tweaks:
        rej = find_rejected_fills_path(cp, pref, ts)

    hints = _collect_improve_hints(
        rows,
        prefix=prefix,
        tickers=tickers,
        data_dir=data_dir,
        drive_dir=drive,
        rejected_fills_path=rej,
        include_param_tweaks=include_param_tweaks,
        include_peer_learn=include_peer_learn,
    )

    csv_path = out_dir / f"{pref}_ImproveHints_{ts}.csv"
    md_path = out_dir / f"{pref}_ImproveHints_{ts}.md"
    html_path = out_dir / f"{pref}_ImproveHints_{ts}.html"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "PRIORITY",
                "CATEGORY",
                "HYPOTHESIS_ID",
                "PARAM",
                "DIRECTION",
                "CONFIDENCE",
                "SYMBOL_COUNT",
                "TRADE_COUNT",
                "PCT_OF_TRADES",
                "LEVER",
                "SUGGESTION",
                "EXAMPLE_SYMBOLS",
                "EVIDENCE",
                "HEURISTIC",
            ]
        )
        for i, h in enumerate(hints, 1):
            w.writerow(
                [
                    i,
                    h.category,
                    h.hypothesis_id,
                    h.param,
                    h.direction,
                    h.confidence,
                    h.symbol_count,
                    h.trade_count,
                    f"{h.pct_of_trades:.2f}" if h.pct_of_trades else "",
                    h.lever,
                    h.suggestion,
                    ",".join(h.symbols[:15]),
                    h.evidence,
                    h.heuristic,
                ]
            )

    pattern_hints = _hints_by_category(hints, "pattern")
    param_hints = _hints_by_category(hints, "param")
    peer_hints = _hints_by_category(hints, "peer_learn")

    lines = [
        f"# {pref} Improve Hints — stamp `{ts}`",
        "",
        "Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. "
        "If nothing actionable and charts already look on-thesis, leave params alone. "
        "Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL "
        "(see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.",
        "",
        "## Taken-trade patterns",
        "",
    ]
    if not pattern_hints:
        lines.append("_No multi-symbol patterns met the minimum frequency threshold._")
        lines.append("")
    else:
        for i, h in enumerate(pattern_hints, 1):
            lines.extend(_hint_md_lines(h, i))

    lines.extend(
        [
            "## Parameter suggestions (band / target / stop)",
            "",
        ]
    )
    if not param_hints:
        lines.append("_No parameter-tweak hypotheses met the threshold._")
        lines.append("")
    else:
        for i, h in enumerate(param_hints, 1):
            lines.extend(_hint_md_lines(h, i))

    lines.extend(
        [
            "## Peer-learn (cross-system overlap)",
            "",
        ]
    )
    if not peer_hints:
        lines.append("_No peer-learn overlap patterns met the threshold._")
        lines.append("")
    else:
        for i, h in enumerate(peer_hints, 1):
            lines.extend(_hint_md_lines(h, i))

    md_path.write_text("\n".join(lines), encoding="utf-8")

    pattern_table = _improve_hints_table_html(pattern_hints)
    param_table = _improve_hints_table_html(param_hints)
    peer_table = _improve_hints_table_html(peer_hints)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(pref)} Improve Hints — {html.escape(ts)}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1400px; margin:0 auto; }}
  h1 {{ font-size:1.5rem; }}
  h2 {{ font-size:1.2rem; margin-top:2rem; }}
  .muted {{ color:#5c5c56; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:13px; margin-bottom:1.5rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:6px 8px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  {_IMPROVE_HINTS_HTML_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>{html.escape(pref)} Improve Hints — stamp {html.escape(ts)}</h1>
  <p class="muted">Portfolio-level rule <strong>hypotheses</strong> (patterns, param directions, peer-learn)—not an order to optimize.
  If empty / thin and charts look good, do not hunt knobs. One knob + ToS gate when you do test
  (<code>docs/HYPOTHESIS_TEST.md</code>).
  Companion to <code>{html.escape(pref)}_ImproveHints_{html.escape(ts)}.csv</code>.
  Click column headers to sort. Not LLM; use with charts + SymbolAssessments.</p>

  <h2>Taken-trade patterns</h2>
  {pattern_table}

  <h2>Parameter suggestions (band / target / stop)</h2>
  {param_table}

  <h2>Peer-learn (cross-system overlap)</h2>
  {peer_table}
</div>
{_IMPROVE_HINTS_SORT_SCRIPT}
</body>
</html>
"""
    html_path.write_text(html_doc, encoding="utf-8")
    return csv_path

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _ensure_ohlc_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "Date" in out.columns:
            out["Date"] = pd.to_datetime(out["Date"])
            out = out.set_index("Date")
        else:
            out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    rename = {}
    for c in out.columns:
        cl = str(c).strip().lower()
        if cl == "close":
            rename[c] = "Close"
        elif cl == "open":
            rename[c] = "Open"
        elif cl == "high":
            rename[c] = "High"
        elif cl == "low":
            rename[c] = "Low"
        elif cl == "volume":
            rename[c] = "Volume"
    if rename:
        out = out.rename(columns=rename)
    return out


def _load_ohlc_csv(path: Path) -> Optional[pd.DataFrame]:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        df = pd.read_csv(p)
        return _ensure_ohlc_frame(df)
    except Exception:
        return None


def _trade_date_window(
    closed_rows: list[dict[str, Any]],
    open_rows: Optional[list[dict[str, Any]]],
    ohlc: pd.DataFrame,
    pad_days: int,
) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    dates_in: list[pd.Timestamp] = []
    for r in list(closed_rows) + list(open_rows or []):
        for key in (
            "DATE OPENED",
            "DATE_OPENED",
            "DATE CLOSED",
            "DATE_CLOSED",
            "BREAK_DATE",
            "BREAKOUT_DATE",
            "DATE BREAKOUT",
            "BREAK DATE",
        ):
            y = _ymd8(_col(r, key))
            if len(y) == 8:
                dates_in.append(pd.Timestamp(f"{y[:4]}-{y[4:6]}-{y[6:8]}"))
        mv = _parse_zone_id_date(_col(r, "ZONE_ID", "ZONE ID", default=""))
        if mv is not None:
            dates_in.append(mv)
    if not dates_in:
        return None, None
    lo = min(dates_in) - pd.Timedelta(days=pad_days)
    hi = max(dates_in) + pd.Timedelta(days=pad_days)
    lo = max(lo, ohlc.index[0])
    hi = min(hi, ohlc.index[-1])
    return lo, hi


def _parse_zone_id_date(zone_id: Any) -> Optional[pd.Timestamp]:
    """Parse ``HL_2010-05-11`` / ``OC_2010-05-11`` → max-vol bar date."""
    s = str(zone_id or "").strip()
    if "_" not in s:
        return None
    tail = s.split("_", 1)[1].strip()
    if not tail:
        return None
    try:
        ts = pd.Timestamp(tail)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.normalize()


def _ohlc_bar_on_or_near(ohlc: pd.DataFrame, when: pd.Timestamp, *, tol_days: int = 3) -> Optional[pd.Series]:
    if ohlc is None or ohlc.empty or when is None:
        return None
    idx = ohlc.index
    w = pd.Timestamp(when).normalize()
    if w in idx:
        return ohlc.loc[w]
    # Nearest prior bar within tol, else nearest within tol.
    try:
        pos = int(idx.searchsorted(w, side="right") - 1)
    except Exception:
        return None
    best: Optional[pd.Series] = None
    best_abs = None
    for p in (pos, pos + 1):
        if p < 0 or p >= len(idx):
            continue
        d = abs((pd.Timestamp(idx[p]).normalize() - w).days)
        if d > int(tol_days):
            continue
        if best_abs is None or d < best_abs:
            best_abs = d
            best = ohlc.iloc[p]
    return best


def _rolling_max_vol_active_spans(
    ohlc: pd.DataFrame,
    lookback_days: int = 126,
) -> dict[pd.Timestamp, tuple[pd.Timestamp, pd.Timestamp]]:
    """Map max-vol bar date → (first_active, last_active) as rolling lookback winner.

    Mirrors ``tools/vol_zone_break_retest.build_zones`` / plot_max_vol_day_zone rolling
    identity walk: each bar that is the trailing ``lookback_days`` volume argmax gets
    first/last dates it held that crown. Break/retest keeps zones in memory forever for
    signals; this span is for **chart shading only**.
    """
    if ohlc is None or ohlc.empty or "Volume" not in ohlc.columns:
        return {}
    n = len(ohlc)
    if n <= int(lookback_days):
        return {}
    lb = int(lookback_days)
    vol = ohlc["Volume"].astype(float).to_numpy()
    idx = ohlc.index
    first_active: dict[int, int] = {}
    last_active: dict[int, int] = {}
    for t in range(lb - 1, n):
        w0 = t - lb + 1
        # argmax on ties takes the earliest bar (left-stable), matching VZ research.
        winner = w0 + int(vol[w0 : t + 1].argmax())
        if winner not in first_active:
            first_active[winner] = t
        last_active[winner] = t
    out: dict[pd.Timestamp, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for w, t0 in first_active.items():
        t1 = last_active[w]
        mv = pd.Timestamp(idx[w]).normalize()
        out[mv] = (
            pd.Timestamp(idx[t0]).normalize(),
            pd.Timestamp(idx[t1]).normalize(),
        )
    return out


def _parse_optional_ymd(row: dict[str, Any], *keys: str) -> Optional[pd.Timestamp]:
    raw = _ymd8(_col(row, *keys, default=""))
    if len(raw) != 8:
        return None
    return pd.Timestamp(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")


def _zone_date_span(
    row: dict[str, Any],
    ohlc: pd.DataFrame,
    *,
    max_vol_dt: Optional[pd.Timestamp],
    active_spans: dict[pd.Timestamp, tuple[pd.Timestamp, pd.Timestamp]],
) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """Resolve visual begin/end for one zone band (not infinite full-chart bands).

    Semantics (documented for chart UX; signals are unchanged):
      Begin: ``ZONE_START`` if present; else **max_vol_date** from ``ZONE_ID``
        (zone formation day); else rolling first_active; else trade ``DATE_OPENED``.
      End: ``ZONE_END`` if present; else **last date the zone was the rolling 126-bar
        max-vol winner** (regime end from ``active_spans``); else trade ``DATE_CLOSED``;
        else as-of chart end for still-open / still-active zones.

    Prefer reconstructing active intervals in the plot path (avoids re-running VZ /
    adding Closed columns). Optional ``ZONE_START``/``ZONE_END`` override when present.
    """
    z_start = _parse_optional_ymd(row, "ZONE_START", "ZONE START", "ZONE_BEGIN", "ZONE BEGIN")
    z_end = _parse_optional_ymd(row, "ZONE_END", "ZONE END")
    opened = _parse_optional_ymd(row, "DATE OPENED", "DATE_OPENED")
    closed = _parse_optional_ymd(row, "DATE CLOSED", "DATE_CLOSED")
    chart_end = pd.Timestamp(ohlc.index[-1]).normalize() if len(ohlc) else None

    first_act: Optional[pd.Timestamp] = None
    last_act: Optional[pd.Timestamp] = None
    if max_vol_dt is not None:
        span = active_spans.get(pd.Timestamp(max_vol_dt).normalize())
        if span is not None:
            first_act, last_act = span

    # Begin: formation day (max-vol) preferred over first_active (crown start).
    begin = z_start or max_vol_dt or first_act or opened
    end = z_end or last_act or closed or chart_end
    if begin is None or end is None:
        return None, None
    begin = pd.Timestamp(begin).normalize()
    end = pd.Timestamp(end).normalize()
    if end < begin:
        end = begin
    # Single-day regimes still need a visible width for fill_between.
    if end == begin and chart_end is not None and begin < chart_end:
        # nudge to next bar if available
        try:
            pos = int(ohlc.index.searchsorted(begin, side="right"))
            if 0 <= pos < len(ohlc.index):
                end = pd.Timestamp(ohlc.index[pos]).normalize()
            else:
                end = begin + pd.Timedelta(days=1)
        except Exception:
            end = begin + pd.Timedelta(days=1)
    return begin, end


def _zone_band_from_row(
    row: dict[str, Any],
    ohlc: Optional[pd.DataFrame],
    *,
    band_pct: float = 0.02,
) -> Optional[tuple[float, float, str, Optional[pd.Timestamp], Optional[pd.Timestamp]]]:
    """Return (lo, hi, label, max_vol_date, break_date) for one Closed/Open row.

    Preference:
      1) explicit ZONE_LO + ZONE_HI
      2) reconstruct HL/OC band from OHLC at ZONE_ID max-vol date (VZ)
      3) ZONE_CENTER ± band_pct (BRT-style)
    No-op when none of the above are available.
    """
    zid = str(_col(row, "ZONE_ID", "ZONE ID", default="") or "").strip()
    zkind = str(_col(row, "ZONE_KIND", "ZONE KIND", default="") or "").strip().upper()
    if not zkind and zid:
        zkind = zid.split("_", 1)[0].upper()
    zlo = _fnum(_col(row, "ZONE_LO", "ZONE LO", "ZONE_LOWER", "ZONE LOWER"))
    zhi = _fnum(_col(row, "ZONE_HI", "ZONE HI", "ZONE_UPPER", "ZONE UPPER", "ZONE_HIGH", "ZONE HIGH"))
    zc = _fnum(_col(row, "ZONE_CENTER", "ZONE CENTER"))
    break_raw = _ymd8(_col(row, "BREAK_DATE", "BREAKOUT_DATE", "DATE BREAKOUT", "BREAK DATE"))
    break_dt: Optional[pd.Timestamp] = None
    if len(break_raw) == 8:
        break_dt = pd.Timestamp(f"{break_raw[:4]}-{break_raw[4:6]}-{break_raw[6:8]}")
    max_vol_dt = _parse_zone_id_date(zid)

    if zlo > 0 and zhi > 0 and zhi >= zlo:
        label = zid or f"zone {zlo:.2f}-{zhi:.2f}"
        return zlo, zhi, label, max_vol_dt, break_dt

    if ohlc is not None and max_vol_dt is not None:
        bar = _ohlc_bar_on_or_near(ohlc, max_vol_dt)
        if bar is not None:
            try:
                o = float(bar.get("Open", bar.get("open", float("nan"))))
                h = float(bar.get("High", bar.get("high", float("nan"))))
                l = float(bar.get("Low", bar.get("low", float("nan"))))
                c = float(bar.get("Close", bar.get("close", float("nan"))))
            except Exception:
                o = h = l = c = float("nan")
            if zkind.startswith("OC") and o == o and c == c:
                lo_r, hi_r = (min(o, c), max(o, c))
            elif h == h and l == l:
                lo_r, hi_r = (l, h)
            else:
                lo_r = hi_r = float("nan")
            if lo_r == lo_r and hi_r == hi_r and hi_r >= lo_r and hi_r > 0:
                # Prefer CSV ZONE_LO when present (rounded freeze value).
                lo_use = zlo if zlo > 0 else float(lo_r)
                hi_use = float(hi_r)
                if zlo > 0 and abs(zlo - lo_r) > max(0.05, 0.02 * abs(lo_r)):
                    # ZONE_LO disagrees with reconstructed low — keep both CSV lo and OHLC hi
                    # only when hi still above lo; else trust OHLC pair.
                    if hi_use < lo_use:
                        lo_use, hi_use = float(lo_r), float(hi_r)
                label = zid or f"{zkind or 'zone'} {lo_use:.2f}-{hi_use:.2f}"
                return lo_use, hi_use, label, max_vol_dt, break_dt

    if zc > 0:
        half = abs(float(band_pct))
        zl = zc * (1.0 - half)
        zh = zc * (1.0 + half)
        label = zid or f"center {zc:.2f}"
        return zl, zh, label, max_vol_dt, break_dt

    return None


def _plot_zone_bands(
    ax: Any,
    closed_rows: list[dict[str, Any]],
    open_rows: Optional[list[dict[str, Any]]],
    ohlc: pd.DataFrame,
    *,
    band_pct: float = 0.02,
    lookback_days: int = 126,
) -> int:
    """Shade trade zones only between begin/end dates; mark max-vol + breakout.

    Visual span (see ``_zone_date_span``): begin at max_vol_date (ZONE_ID), end at last
    rolling-126 max-vol-winner day when reconstructable — not infinite ``axhspan`` bands.
    Returns #bands drawn.
    """
    active_spans = _rolling_max_vol_active_spans(ohlc, lookback_days=int(lookback_days))
    seen: set[tuple[float, float, str, str]] = set()
    seen_break: set[pd.Timestamp] = set()
    seen_maxvol: set[pd.Timestamp] = set()
    n_bands = 0
    for r in list(closed_rows) + list(open_rows or []):
        band = _zone_band_from_row(r, ohlc, band_pct=band_pct)
        if band is None:
            continue
        zl, zh, _label, max_vol_dt, break_dt = band
        d0, d1 = _zone_date_span(
            r, ohlc, max_vol_dt=max_vol_dt, active_spans=active_spans
        )
        if d0 is None or d1 is None:
            continue
        key = (
            round(float(zl), 4),
            round(float(zh), 4),
            d0.strftime("%Y%m%d"),
            d1.strftime("%Y%m%d"),
        )
        if key not in seen:
            seen.add(key)
            mask = (ohlc.index >= d0) & (ohlc.index <= d1)
            xs = ohlc.index[mask]
            if len(xs) == 0:
                # Dates may fall in a pad gap — still draw a rectangle via fill endpoints.
                xs = pd.DatetimeIndex([d0, d1])
            ax.fill_between(
                xs,
                float(zl),
                float(zh),
                alpha=0.22,
                color="#3b82f6",
                zorder=0,
                linewidth=0,
            )
            ax.plot([d0, d1], [zl, zl], color="#60a5fa", alpha=0.55, lw=0.8, zorder=1)
            ax.plot([d0, d1], [zh, zh], color="#60a5fa", alpha=0.55, lw=0.8, zorder=1)
            # Light date label at mid-span / mid-band (skip when many zones).
            if n_bands < 8:
                mid_t = d0 + (d1 - d0) / 2
                mid_y = (float(zl) + float(zh)) / 2.0
                ax.annotate(
                    f"{d0.strftime('%Y-%m-%d')}→{d1.strftime('%Y-%m-%d')}",
                    xy=(mid_t, mid_y),
                    fontsize=6.5,
                    color="#93c5fd",
                    alpha=0.85,
                    ha="center",
                    va="center",
                    zorder=2,
                )
            n_bands += 1
        if max_vol_dt is not None:
            mv = pd.Timestamp(max_vol_dt).normalize()
            if mv not in seen_maxvol:
                seen_maxvol.add(mv)
                ax.axvline(mv, color="#f59e0b", ls="--", lw=1.0, alpha=0.75, zorder=2)
        if break_dt is not None:
            bd = pd.Timestamp(break_dt).normalize()
            if bd not in seen_break:
                seen_break.add(bd)
                ax.axvline(bd, color="#a78bfa", ls=":", lw=1.1, alpha=0.85, zorder=2)
    if n_bands:
        ax.plot([], [], color="#3b82f6", lw=8, alpha=0.35, label="Volume zone (active span)")
    if seen_maxvol:
        ax.plot([], [], color="#f59e0b", ls="--", lw=1.2, label="Max-vol day")
    if seen_break:
        ax.plot([], [], color="#a78bfa", ls=":", lw=1.2, label="Breakout")
    return n_bands


def _plot_trade_markers(
    ax: Any,
    closed_rows: list[dict[str, Any]],
    open_rows: Optional[list[dict[str, Any]]],
    ohlc: pd.DataFrame,
) -> None:
    for r in closed_rows:
        d0 = _ymd8(_col(r, "DATE OPENED", "DATE_OPENED"))
        d1 = _ymd8(_col(r, "DATE CLOSED", "DATE_CLOSED"))
        if len(d0) != 8 or len(d1) != 8:
            continue
        t0 = pd.Timestamp(f"{d0[:4]}-{d0[4:6]}-{d0[6:8]}")
        t1 = pd.Timestamp(f"{d1[:4]}-{d1[4:6]}-{d1[6:8]}")
        entry = _fnum(_col(r, "ENTRY PRICE", "ENTRY_PRICE"))
        exit_px = _fnum(_col(r, "EXIT PRICE", "EXIT_PRICE"))
        stop = _fnum(
            _col(r, "ORIGINAL STOP", "STOP LOSS AT CLOSE", "STOP_PRICE", "STOP LOSS", "STOP")
        )
        pnl = _fnum(_col(r, "PNL %", "PNL_PCT"))
        ax.scatter(
            [t0], [entry], color="#22c55e", marker="^", s=70, zorder=5, edgecolors="white", linewidths=0.4
        )
        out_color = "#22c55e" if pnl >= 0 else "#f87171"
        ax.scatter(
            [t1], [exit_px], color=out_color, marker="v", s=70, zorder=5, edgecolors="white", linewidths=0.4
        )
        if stop > 0:
            ax.plot([t0, t1], [stop, stop], color="#ef4444", lw=1.4, solid_capstyle="butt", zorder=4, alpha=0.9)

    for r in open_rows or []:
        d0 = _ymd8(_col(r, "DATE OPENED", "DATE_OPENED"))
        if len(d0) != 8:
            continue
        t0 = pd.Timestamp(f"{d0[:4]}-{d0[4:6]}-{d0[6:8]}")
        entry = _fnum(_col(r, "ENTRY PRICE", "ENTRY_PRICE"))
        stop = _fnum(_col(r, "STOP LOSS", "STOP_PRICE", "STOP", "ORIGINAL STOP"))
        ax.scatter([t0], [entry], color="#fbbf24", marker="^", s=80, zorder=5)
        if stop > 0 and ohlc.index[-1] is not None:
            ax.plot([t0, ohlc.index[-1]], [stop, stop], color="#ef4444", lw=1.2, linestyle="--", zorder=4)


def plot_rl_symbol_chart(
    symbol: str,
    df: pd.DataFrame,
    closed_rows: list[dict[str, Any]],
    output_path: Path,
    *,
    dip_pct: float = 1.055,
    open_rows: Optional[list[dict[str, Any]]] = None,
    pad_days: int = 40,
) -> bool:
    """Write one PNG: Close, SMA20/50/100/200, dip band, IN/OUT, stop segments."""
    if not HAS_MATPLOTLIB:
        return False
    try:
        ohlc = _ensure_ohlc_frame(df)
        if "Close" not in ohlc.columns or ohlc.empty:
            return False
        close = ohlc["Close"].astype(float)
        sma20 = close.rolling(20, min_periods=20).mean()
        sma50 = close.rolling(50, min_periods=50).mean()
        sma100 = close.rolling(100, min_periods=100).mean()
        sma200 = close.rolling(200, min_periods=200).mean()
        band_hi = sma50 * dip_pct
        band_lo = sma50 * (1.0 - (dip_pct - 1.0))
        stack_bull = (sma20 > sma50) & (sma50 > sma100) & (sma100 > sma200)

        fig, ax = plt.subplots(figsize=(14, 7), facecolor="#1e1e1e")
        ax.set_facecolor("#1e1e1e")
        ax.plot(ohlc.index, close, color="#d0d0d0", lw=1.0, label="Close", zorder=3)
        ax.plot(ohlc.index, sma20, color="#ff4444", lw=1.2, label="SMA20", zorder=2)
        ax.plot(ohlc.index, sma50, color="#ffffff", lw=1.2, label="SMA50", zorder=2)
        ax.plot(ohlc.index, sma100, color="#ffd700", lw=1.1, label="SMA100", zorder=2)
        ax.plot(ohlc.index, sma200, color="#b266ff", lw=1.1, label="SMA200", zorder=2)

        ax.fill_between(
            ohlc.index,
            band_lo,
            band_hi,
            where=stack_bull.fillna(False),
            color="#22c55e",
            alpha=0.18,
            interpolate=False,
            label="Dip band (bull stack)",
            zorder=1,
        )
        ax.fill_between(
            ohlc.index,
            band_lo,
            band_hi,
            where=(~stack_bull.fillna(False)) & sma50.notna(),
            color="#ef4444",
            alpha=0.10,
            interpolate=False,
            label="Dip band (no stack)",
            zorder=1,
        )

        _plot_trade_markers(ax, closed_rows, open_rows, ohlc)

        band_label = f"±{(dip_pct - 1.0) * 100:.1f}%"
        ax.set_title(
            f"RL {symbol} — SMA20/50/100/200 + dip {band_label} | green IN / OUT | red stop",
            color="white",
            fontsize=12,
        )
        ax.tick_params(colors="#cccccc")
        for spine in ax.spines.values():
            spine.set_color("#555555")
        ax.yaxis.label.set_color("#cccccc")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(True, alpha=0.2, color="#666666")
        leg = ax.legend(loc="upper left", fontsize=8, framealpha=0.35)
        for t in leg.get_texts():
            t.set_color("white")

        lo, hi = _trade_date_window(closed_rows, open_rows, ohlc, pad_days)
        if lo is not None and hi is not None:
            ax.set_xlim(lo, hi)
            mask = (ohlc.index >= lo) & (ohlc.index <= hi)
            if mask.any():
                y_lo = float(close[mask].min())
                y_hi = float(close[mask].max())
                pad = (y_hi - y_lo) * 0.08 or 1.0
                ax.set_ylim(y_lo - pad, y_hi + pad)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(output_path, dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        return True
    except Exception as e:
        print(f"[charts] {symbol}: {e}", file=sys.stderr)
        try:
            plt.close("all")
        except Exception:
            pass
        return False


def plot_common_trade_chart(
    symbol: str,
    df: pd.DataFrame,
    closed_rows: list[dict[str, Any]],
    output_path: Path,
    *,
    prefix: str = "BRT",
    open_rows: Optional[list[dict[str, Any]]] = None,
    pad_days: int = 40,
    band_pct: float = 0.02,
    draw_zones: bool = False,
) -> bool:
    """OHLC Close + SMA50 + IN/OUT/stop; optional zone bands from Closed rows.

    Zone sources (no-op when absent — safe for RS/SB):
      - ``ZONE_LO`` / ``ZONE_HI`` (explicit)
      - VZ ``ZONE_ID`` + OHLC reconstruct of HL/OC max-vol bar
      - ``ZONE_CENTER`` ± ``band_pct`` (BRT-style)
    Zone shading is **date-bounded** (max_vol_date → last rolling-126 winner day when
    reconstructable; see ``_zone_date_span``), not full-chart horizontal bands.
    Also marks max-vol day and ``BREAK_DATE`` when present. Entry/exit/stop via markers.
    """
    if not HAS_MATPLOTLIB:
        return False
    try:
        ohlc = _ensure_ohlc_frame(df)
        if "Close" not in ohlc.columns or ohlc.empty:
            return False
        close = ohlc["Close"].astype(float)
        sma50 = close.rolling(50, min_periods=50).mean()

        fig, ax = plt.subplots(figsize=(14, 7), facecolor="#1e1e1e")
        ax.set_facecolor("#1e1e1e")
        ax.plot(ohlc.index, close, color="#d0d0d0", lw=1.0, label="Close", zorder=3)
        ax.plot(ohlc.index, sma50, color="#ffffff", lw=1.1, label="SMA50", zorder=2)

        n_zones = 0
        if draw_zones:
            n_zones = _plot_zone_bands(
                ax, closed_rows, open_rows, ohlc, band_pct=float(band_pct)
            )

        _plot_trade_markers(ax, closed_rows, open_rows, ohlc)

        style = "zones + trades" if n_zones else ("zones attempted" if draw_zones else "trades")
        if n_zones:
            style = f"{n_zones} zone(s) + trades"
        ax.set_title(
            f"{prefix} {symbol} — Close/SMA50 + {style} | green IN / OUT | red stop",
            color="white",
            fontsize=12,
        )
        ax.tick_params(colors="#cccccc")
        for spine in ax.spines.values():
            spine.set_color("#555555")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.grid(True, alpha=0.2, color="#666666")
        leg = ax.legend(loc="upper left", fontsize=8, framealpha=0.35)
        for t in leg.get_texts():
            t.set_color("white")

        lo, hi = _trade_date_window(closed_rows, open_rows, ohlc, pad_days)
        if lo is not None and hi is not None:
            ax.set_xlim(lo, hi)
            mask = (ohlc.index >= lo) & (ohlc.index <= hi)
            if mask.any():
                y_lo = float(close[mask].min())
                y_hi = float(close[mask].max())
                # Include zone edges in y-limits so bands stay visible.
                if n_zones:
                    for r in list(closed_rows) + list(open_rows or []):
                        band = _zone_band_from_row(r, ohlc, band_pct=float(band_pct))
                        if band is None:
                            continue
                        y_lo = min(y_lo, float(band[0]))
                        y_hi = max(y_hi, float(band[1]))
                pad = (y_hi - y_lo) * 0.08 or 1.0
                ax.set_ylim(y_lo - pad, y_hi + pad)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        fig.savefig(output_path, dpi=120, facecolor=fig.get_facecolor())
        plt.close(fig)
        return True
    except Exception as e:
        print(f"[charts] {symbol}: {e}", file=sys.stderr)
        try:
            plt.close("all")
        except Exception:
            pass
        return False


def chart_style_for_system(prefix: str) -> str:
    p = normalize_system(prefix)
    if p in RL_SYSTEMS:
        return "rl"
    if p in ZONE_SYSTEMS:
        return "zones"
    return "common"


def _closed_rows_have_zone_cols(by_sym: dict[str, list[dict[str, Any]]]) -> bool:
    """True when Closed/Open rows carry zone levels (VZ / BRT-style) — enables overlays."""
    for rows in by_sym.values():
        for r in rows[:3]:
            if _fnum(_col(r, "ZONE_LO", "ZONE LO", "ZONE_HI", "ZONE HI", "ZONE_CENTER", "ZONE CENTER")) > 0:
                return True
            if str(_col(r, "ZONE_ID", "ZONE ID", default="") or "").strip():
                return True
    return False


def _chart_one_task(task: tuple[Any, ...]) -> tuple[str, bool]:
    """Picklable ProcessPool worker: (sym, csv_path, closed, open, out, style, dip, band, prefix)."""
    (
        sym,
        csv_path,
        closed_rows,
        open_rows,
        out_path,
        style,
        dip_pct,
        band_pct,
        prefix,
    ) = task
    df = _load_ohlc_csv(Path(csv_path))
    if df is None or df.empty:
        return sym, False
    if style == "rl":
        ok = plot_rl_symbol_chart(
            sym,
            df,
            closed_rows,
            Path(out_path),
            dip_pct=float(dip_pct),
            open_rows=open_rows or None,
        )
    else:
        ok = plot_common_trade_chart(
            sym,
            df,
            closed_rows,
            Path(out_path),
            prefix=str(prefix),
            open_rows=open_rows or None,
            band_pct=float(band_pct),
            draw_zones=(style == "zones"),
        )
    return sym, bool(ok)


def _resolve_symbol_csv(data_dir: Path, sym: str) -> Optional[Path]:
    for candidate in (
        data_dir / f"{sym}.csv",
        data_dir / f"{sym.upper()}.csv",
        data_dir / f"{sym.lower()}.csv",
    ):
        if candidate.is_file():
            return candidate
    return None


def write_system_charts(
    *,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    data_dir: Optional[Path] = None,
    closed_path: Path,
    output_dir: Path,
    ts: str,
    prefix: str = "RL",
    dip_pct: float = 1.055,
    band_pct: float = 0.02,
    open_path: Optional[Path] = None,
    traded_only: bool = True,
    workers: int = -1,
    symbols: Optional[list[str]] = None,
) -> Path:
    """Write PNGs under ``output_dir/{prefix}_Charts_<ts>/``. Returns chart directory."""
    pref = normalize_system(prefix) or "RL"
    chart_dir = Path(output_dir) / f"{pref}_Charts_{ts}"
    chart_dir.mkdir(parents=True, exist_ok=True)
    if not HAS_MATPLOTLIB:
        print(f"[{pref} charts] matplotlib not installed; skipping charts.", file=sys.stderr)
        return chart_dir

    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with Path(closed_path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sym = str(row.get("SYMBOL", "")).strip().upper()
            if sym:
                by_sym[sym].append(row)

    open_by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if open_path and Path(open_path).is_file():
        with Path(open_path).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("SYMBOL", "")).strip().upper()
                if sym:
                    open_by_sym[sym].append(row)

    if symbols:
        sym_list = [s.strip().upper() for s in symbols if s.strip()]
    elif traded_only:
        sym_list = sorted(set(by_sym.keys()) | set(open_by_sym.keys()))
    else:
        sym_list = sorted(set(by_sym) | set(open_by_sym))

    style = chart_style_for_system(pref)
    if style == "common" and (
        _closed_rows_have_zone_cols(by_sym) or _closed_rows_have_zone_cols(open_by_sym)
    ):
        style = "zones"
    data_dir_p = Path(data_dir) if data_dir else None
    tasks: list[tuple[Any, ...]] = []
    n_mem = 0
    for sym in sym_list:
        out = chart_dir / f"{pref}_{sym}_{ts}.png"
        csv_path = ""
        if data_dir_p is not None:
            p = _resolve_symbol_csv(data_dir_p, sym)
            if p is not None:
                csv_path = str(p)
        if not csv_path and tickers:
            df = tickers.get(sym) or tickers.get(sym.lower()) or tickers.get(sym.upper())
            if df is not None and not getattr(df, "empty", True):
                if style == "rl":
                    ok = plot_rl_symbol_chart(
                        sym, df, by_sym.get(sym, []), out, dip_pct=dip_pct, open_rows=open_by_sym.get(sym)
                    )
                else:
                    ok = plot_common_trade_chart(
                        sym,
                        df,
                        by_sym.get(sym, []),
                        out,
                        prefix=pref,
                        open_rows=open_by_sym.get(sym),
                        band_pct=band_pct,
                        draw_zones=(style == "zones"),
                    )
                if ok:
                    n_mem += 1
                continue
        if not csv_path:
            continue
        tasks.append(
            (
                sym,
                csv_path,
                by_sym.get(sym, []),
                open_by_sym.get(sym, []),
                str(out),
                style,
                float(dip_pct),
                float(band_pct),
                pref,
            )
        )

    n_workers = resolve_workers(workers)
    total = len(tasks)
    n_ok = 0
    if total > 0:
        if n_workers > 1 and total > 1:
            print(f"[{pref} charts] {total} symbols, workers={n_workers} ...", flush=True)
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                futs = {ex.submit(_chart_one_task, t): t[0] for t in tasks}
                done = 0
                for fut in as_completed(futs):
                    _sym, ok = fut.result()
                    if ok:
                        n_ok += 1
                    done += 1
                    if done % 10 == 0 or done == total:
                        print(f"[{pref} charts] {done}/{total} ...", flush=True)
        else:
            for i, task in enumerate(tasks, 1):
                _sym, ok = _chart_one_task(task)
                if ok:
                    n_ok += 1
                if i % 10 == 0 or i == total:
                    print(f"[{pref} charts] {i}/{total} ...", flush=True)

    n_total = n_ok + n_mem
    print(f"[{pref} charts] Wrote {n_total} PNG(s) -> {chart_dir}", flush=True)
    return chart_dir


def write_rl_charts(
    *,
    tickers: dict[str, pd.DataFrame],
    closed_path: Path,
    output_dir: Path,
    ts: str,
    dip_pct: float = 1.055,
    open_path: Optional[Path] = None,
    traded_only: bool = True,
    workers: int = 1,
) -> Path:
    """RL-compatible wrapper around ``write_system_charts``."""
    return write_system_charts(
        tickers=tickers,
        closed_path=closed_path,
        output_dir=output_dir,
        ts=ts,
        prefix="RL",
        dip_pct=dip_pct,
        open_path=open_path,
        traded_only=traded_only,
        workers=workers,
    )


# ---------------------------------------------------------------------------
# Orchestrator (cheap DailyRun enrichments)
# ---------------------------------------------------------------------------

def write_analysis_artifacts(
    *,
    cfg: Any = None,
    tickers: Optional[dict[str, pd.DataFrame]] = None,
    output_dir: Path,
    ts: str,
    closed_path: Path,
    summary_path: Path,
    open_path: Optional[Path] = None,
    prefix: str = "RL",
    no_yfinance: bool = False,
) -> dict[str, Path]:
    """Cheap enrichments only (no charts, no deep HTML).

    ImproveHints include pattern hypotheses plus parameter-tweak / peer-learn
    suggestions. When ``tickers`` is provided (in-run backtest frames), OHLC-based
    post-exit / stop-rebound / RejectedFills follow-through heuristics also run.
    """
    del open_path  # reserved
    out: dict[str, Path] = {}
    pref = normalize_system(prefix) or "RL"
    dip = 1.055
    skip_yf = bool(no_yfinance)
    if cfg is not None:
        dip = float(getattr(cfg, "rl_dip_pct", 1.055) or 1.055)
        if _truthy(getattr(cfg, "no_yfinance", False)):
            skip_yf = True
    out_dir = Path(output_dir)

    if cfg is not None and (
        _truthy(getattr(cfg, "rl_charts", False)) or _truthy(getattr(cfg, "rl_deep_analysis", False))
    ):
        print(
            f"[{pref} analysis] Charts/deep narrative are NOT part of DailyRun. "
            f"Use: python stock_analysis/post_run_analysis.py --system {pref} --stamp "
            f"{ts} --charts  (see docs/POST_RUN_ANALYSIS.md).",
            flush=True,
        )

    try:
        n = enrich_closed_csv_with_one_liners(closed_path, dip_pct=dip)
        print(f"[{pref} analysis] ONE_LINER on {n} closed rows -> {Path(closed_path).name}", flush=True)
        out["closed"] = Path(closed_path)
    except Exception as e:
        print(f"[{pref} analysis] ONE_LINER failed: {e}", file=sys.stderr)

    try:
        n = enrich_summary_csv_with_yfinance(summary_path, no_yfinance=skip_yf)
        print(
            f"[{pref} analysis] CURRENT_MARKET_CAP/SECTOR/INDUSTRY on {n} summary rows "
            f"-> {Path(summary_path).name}"
            + (" (skipped fetch)" if skip_yf else ""),
            flush=True,
        )
        out["summary"] = Path(summary_path)
    except Exception as e:
        print(f"[{pref} analysis] yfinance Summary meta failed: {e}", file=sys.stderr)

    # AVG_DAYS_HELD before FIT/PAUL_SCORE so the days-held peer component can fire (0–8).
    try:
        n = enrich_summary_csv_with_avg_days_held(summary_path, closed_path)
        print(
            f"[{pref} analysis] AVG_DAYS_HELD on {n} summary rows -> {Path(summary_path).name}",
            flush=True,
        )
        out["summary"] = Path(summary_path)
    except Exception as e:
        print(f"[{pref} analysis] AVG_DAYS_HELD enrichment failed: {e}", file=sys.stderr)

    try:
        n = enrich_summary_csv_with_fit(summary_path, closed_path, prefix=pref)
        print(f"[{pref} analysis] FIT columns on {n} summary rows -> {Path(summary_path).name}", flush=True)
        out["summary"] = Path(summary_path)
    except Exception as e:
        print(f"[{pref} analysis] FIT enrichment failed: {e}", file=sys.stderr)

    try:
        hints_path = write_improve_hints(
            closed_path,
            out_dir,
            ts,
            prefix=pref,
            tickers=tickers,
            drive_dir=out_dir,
        )
        if hints_path:
            print(f"[{pref} analysis] Wrote {hints_path.name} (+ .md/.html)", flush=True)
            out["improve_hints"] = hints_path
    except Exception as e:
        print(f"[{pref} analysis] ImproveHints failed: {e}", file=sys.stderr)

    return out


def write_rl_analysis_artifacts(
    *,
    cfg: Any,
    tickers: dict[str, pd.DataFrame],
    output_dir: Path,
    ts: str,
    closed_path: Path,
    summary_path: Path,
    open_path: Optional[Path] = None,
) -> dict[str, Path]:
    """RL alias for ``write_analysis_artifacts``."""
    return write_analysis_artifacts(
        cfg=cfg,
        tickers=tickers,
        output_dir=output_dir,
        ts=ts,
        closed_path=closed_path,
        summary_path=summary_path,
        open_path=open_path,
        prefix="RL",
    )


def _truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in ("true", "1", "yes", "on")
