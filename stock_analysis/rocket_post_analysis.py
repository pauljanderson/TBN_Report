"""System-agnostic post-run analysis: one-liners, fit scores, hints, charts.

Cheap enrichments (DailyRun-safe):
  - Closed ``ONE_LINER``
  - Summary ``FIT`` / ``FIT_SCORE`` / ``FIT_SCORE_ROBUST`` / outlier cols /
    ``FIT_ASSESSMENT`` (plus ``RL_FIT`` for RL)
  - ``{prefix}_ImproveHints_<ts>.csv|.md``

Deep / optional (``post_run_analysis.py``, not DailyRun):
  - matplotlib charts under ``{prefix}_Charts_<ts>/``
  - SymbolAssessments / ImprovePriority HTML

RL helpers remain importable from ``rocket_rl_analysis`` (re-exports).
"""
from __future__ import annotations

import csv
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
    "BRT",
    "IND",
    "MTS",
    "YH",
    "VEC",
    "PBR",
    "RS",
    "RL",
    "DB",
)

ZONE_SYSTEMS = frozenset({"BRT", "WPBR", "YH", "VEC", "PBR"})
RL_SYSTEMS = frozenset({"RL", "DB"})


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
    """Map CLI ``--workers`` to process count. ``-1`` → min(4, CPUs); ``0`` → sequential (1)."""
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
    """Parse ``BRT_Closed_2607….csv`` → ``BRT``."""
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
    out = Path(output_dir)
    closed = Path(closed_path) if closed_path else out / f"{prefix}_Closed_{stamp}.csv"
    return closed, out / f"{prefix}_Summary_{stamp}.csv", out / f"{prefix}_Open_{stamp}.csv"


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
        f"{sym} | IN {d_in} @ {entry:.2f} → OUT {d_out} @ {exit_px:.2f} | "
        f"{exit_type} {_pct_str(pnl)} | {days}d | MAE {mae_pct:.2f}% (stop {stop_s}) | {narrative}"
    )


def enrich_closed_csv_with_one_liners(
    closed_path: Path,
    *,
    dip_pct: float = 1.041,
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

@dataclass
class FitResult:
    fit: str  # High | Medium | Low
    score: int
    text: str
    score_robust: int = 0
    fit_robust: str = ""
    max_win_pct: float = 0.0
    median_pnl_pct: float = 0.0
    outlier_pct_of_wins: float = 0.0
    outlier_pct_of_sheet: float = 0.0
    outlier_penalty: int = 0


def _fit_tier(score: int) -> str:
    if score >= 5:
        return "High"
    if score >= 2:
        return "Medium"
    return "Low"


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
    """Shared point rules for headline FIT_SCORE and FIT_SCORE_ROBUST."""
    score = 0
    if pct_wins >= 55:
        score += 2
    elif pct_wins >= 45:
        score += 1
    if pnl_pct_for_avg_bucket >= 8:
        score += 2
    elif pnl_pct_for_avg_bucket >= 3:
        score += 1
    elif pnl_pct_for_avg_bucket < 0:
        score -= 2
    if sheet_pnl > 5000:
        score += 2
    elif sheet_pnl > 0:
        score += 1
    elif sheet_pnl < -2000:
        score -= 2
    # Trades/year: more activity is better (no busy/high-frequency penalty).
    if avg_tpy >= 1.0:
        score += 2
    elif avg_tpy >= 0.36:
        score += 1  # ~promotion-threshold activity
    if wins >= 3 and losses == 0:
        score += 1
    if asym_penalty:
        score -= 1
    score -= max(0, int(outlier_penalty))
    return score


def _closed_trade_pnls(closed_rows: list[dict[str, Any]]) -> list[float]:
    return [_fnum(_col(r, "PNL %", "PNL_PCT")) for r in closed_rows]


def _outlier_fit_metrics(pnls: list[float]) -> tuple[float, float, float, float]:
    """max_win%, median trade PnL%, top-win/sum(wins), top-win/sum(all) ≈ sheet share."""
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

    ``FIT_SCORE`` (headline) uses mean ``avg_pnl_pct`` as today.
    ``FIT_SCORE_ROBUST`` uses median trade PnL% for the avg-pnl points bucket and a
    soft outlier penalty when one win dominates positive PnL% or sheet contribution.
    """
    closed_rows = closed_rows or []
    notes: list[str] = []
    pnls = _closed_trade_pnls(closed_rows)
    max_win, median_pnl, outlier_of_wins, outlier_of_sheet = _outlier_fit_metrics(pnls)
    outlier_pen = _outlier_soft_penalty(outlier_of_wins, outlier_of_sheet)

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
        return FitResult("Low", 0, "no trades", fit_robust="Low")

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
    score_robust = _fit_component_score(
        pct_wins=pct_wins,
        pnl_pct_for_avg_bucket=median_pnl if pnls else avg_pnl_pct,
        sheet_pnl=sheet_pnl,
        avg_tpy=avg_tpy,
        wins=wins,
        losses=losses,
        asym_penalty=asym,
        outlier_penalty=outlier_pen,
    )
    fit = _fit_tier(score)
    fit_robust = _fit_tier(score_robust)

    head = f"{fit}: {pct_wins:.0f}%W avg {avg_pnl_pct:+.1f}% {trades}tr/{avg_tpy:.1f}y"
    if notes:
        head = f"{head}; " + "; ".join(notes[:2])
    # Flag when robust is materially weaker (outlier-carried mean / sheet).
    if score_robust <= score - 2 or (
        fit_robust != fit and _fit_tier_rank(fit_robust) < _fit_tier_rank(fit)
    ):
        head = (
            f"{head}; robust {fit_robust} (med {median_pnl:+.1f}%, "
            f"outlier {outlier_of_wins:.0f}% of wins)"
        )
    return FitResult(
        fit=fit,
        score=score,
        text=head[:220],
        score_robust=score_robust,
        fit_robust=fit_robust,
        max_win_pct=max_win,
        median_pnl_pct=median_pnl,
        outlier_pct_of_wins=outlier_of_wins,
        outlier_pct_of_sheet=outlier_of_sheet,
        outlier_penalty=outlier_pen,
    )


def _fit_tier_rank(fit: str) -> int:
    return {"High": 2, "Medium": 1, "Low": 0}.get(str(fit), 0)


def enrich_summary_csv_with_fit(
    summary_path: Path,
    closed_path: Path,
    *,
    prefix: str = "RL",
) -> int:
    """Add FIT (+ RL_FIT when prefix is RL) and robust/outlier columns to Summary CSV."""
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

    fit_cols = [
        "FIT",
        "FIT_SCORE",
        "FIT_SCORE_ROBUST",
        "MAX_WIN_PCT",
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
        trades = int(_fnum(row.get("TRADES"), 0))
        wins = int(_fnum(row.get("WINS"), 0))
        losses = int(_fnum(row.get("LOSSES"), 0))
        pct_wins = _fnum(str(row.get("PCT_WINS", "")).replace("%", ""))
        avg_pnl = _fnum(str(row.get("AVG_PNL_PCT", "")).replace("%", ""))
        sheet_pnl = _fnum(row.get("SHEET_PNL"))
        avg_tpy = _fnum(row.get("AVG_TRADES_PER_YEAR"))
        fr = assess_symbol_fit(
            trades=trades,
            wins=wins,
            losses=losses,
            pct_wins=pct_wins,
            avg_pnl_pct=avg_pnl,
            sheet_pnl=sheet_pnl,
            avg_tpy=avg_tpy,
            closed_rows=by_sym.get(sym, []),
        )
        row["FIT"] = fr.fit
        if "RL_FIT" in fieldnames:
            row["RL_FIT"] = fr.fit
        row["FIT_SCORE"] = str(fr.score)
        row["FIT_SCORE_ROBUST"] = str(fr.score_robust)
        row["MAX_WIN_PCT"] = f"{fr.max_win_pct:.2f}%" if fr.max_win_pct else "0.00%"
        row["MEDIAN_PNL_PCT"] = f"{fr.median_pnl_pct:+.2f}%"
        row["OUTLIER_PCT_OF_WINS"] = f"{fr.outlier_pct_of_wins:.1f}%"
        row["FIT_ASSESSMENT"] = fr.text

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


def _hint_catalog(prefix: str) -> dict[str, tuple[str, str]]:
    """Hypothesis id → (lever, suggestion). RL keeps dip/trail levers; others generic."""
    p = normalize_system(prefix)
    generic = {
        "post_target_quick_stop": (
            "symbol_reentry_cooldown_days / stricter re-entry gates",
            "Many symbols take a TARGET then immediately re-enter and STOP quickly — "
            "test a short post-win cooldown or stricter re-entry filter.",
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
        }
    if p in ZONE_SYSTEMS:
        generic["shallow_entry_sma50_fail"] = (
            "band_pct / zone strength / touch_count gates",
            "Quick stops near entry — tighten zone band, require stronger pivot, or "
            "raise min touch_count / zone_strength.",
        )
        generic["post_target_quick_stop"] = (
            "symbol_reentry_cooldown_days / require_no_zone_above",
            "TARGET then quick STOP re-entry — cooldown or block crowded zone stacks.",
        )
    return generic


def _collect_improve_hints(
    closed_rows: list[dict[str, Any]],
    *,
    prefix: str = "RL",
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
                            f"{sym} TARGET {_iso_dash(_col(r, 'DATE CLOSED', 'DATE_CLOSED'))} → "
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
                        f"{sym} peak~{max_gain_pct:.0f}% → STOP {_pct_str(pnl)} "
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
            )
        )
    hints.sort(key=lambda h: (-h.priority, h.hypothesis_id))
    return hints


def write_improve_hints(
    closed_path: Path,
    output_dir: Path,
    ts: str,
    *,
    prefix: str = "RL",
) -> Optional[Path]:
    """Write ``{prefix}_ImproveHints_<ts>.csv`` (+ short .md). Returns CSV path or None."""
    cp = Path(closed_path)
    if not cp.is_file():
        return None
    with cp.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    hints = _collect_improve_hints(rows, prefix=prefix)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pref = normalize_system(prefix) or "RL"
    csv_path = out_dir / f"{pref}_ImproveHints_{ts}.csv"
    md_path = out_dir / f"{pref}_ImproveHints_{ts}.md"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "PRIORITY",
                "HYPOTHESIS_ID",
                "SYMBOL_COUNT",
                "TRADE_COUNT",
                "LEVER",
                "SUGGESTION",
                "EXAMPLE_SYMBOLS",
                "EVIDENCE",
            ]
        )
        for i, h in enumerate(hints, 1):
            w.writerow(
                [
                    i,
                    h.hypothesis_id,
                    h.symbol_count,
                    h.trade_count,
                    h.lever,
                    h.suggestion,
                    ",".join(h.symbols[:15]),
                    h.evidence,
                ]
            )

    lines = [
        f"# {pref} Improve Hints — stamp `{ts}`",
        "",
        "Rule-based hypotheses ranked by how often they fire across symbols. "
        "Not a substitute for chart review; use with ONE_LINER / FIT_ASSESSMENT / charts.",
        "",
    ]
    if not hints:
        lines.append("_No multi-symbol patterns met the minimum frequency threshold._")
    else:
        for i, h in enumerate(hints, 1):
            lines.append(f"## {i}. `{h.hypothesis_id}` ({h.symbol_count} sym / {h.trade_count} trades)")
            lines.append(f"- **Lever:** {h.lever}")
            lines.append(f"- **Suggestion:** {h.suggestion}")
            lines.append(f"- **Symbols:** {', '.join(h.symbols[:20])}")
            if h.evidence:
                lines.append(f"- **Evidence:** {h.evidence}")
            lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
    for r in closed_rows:
        for key in ("DATE OPENED", "DATE_OPENED", "DATE CLOSED", "DATE_CLOSED"):
            y = _ymd8(_col(r, key))
            if len(y) == 8:
                dates_in.append(pd.Timestamp(f"{y[:4]}-{y[4:6]}-{y[6:8]}"))
    for r in open_rows or []:
        y = _ymd8(_col(r, "DATE OPENED", "DATE_OPENED"))
        if len(y) == 8:
            dates_in.append(pd.Timestamp(f"{y[:4]}-{y[4:6]}-{y[6:8]}"))
    if not dates_in:
        return None, None
    lo = min(dates_in) - pd.Timedelta(days=pad_days)
    hi = max(dates_in) + pd.Timedelta(days=pad_days)
    lo = max(lo, ohlc.index[0])
    hi = min(hi, ohlc.index[-1])
    return lo, hi


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
    dip_pct: float = 1.041,
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
    """OHLC Close + SMA50 + IN/OUT/stop; optional ZONE_CENTER bands from Closed rows."""
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

        if draw_zones:
            seen_zc: set[float] = set()
            for r in list(closed_rows) + list(open_rows or []):
                zc = _fnum(_col(r, "ZONE_CENTER", "ZONE CENTER"))
                if zc <= 0:
                    continue
                key = round(zc, 4)
                if key in seen_zc:
                    continue
                seen_zc.add(key)
                zl = zc * (1.0 - band_pct)
                zh = zc * (1.0 + band_pct)
                ax.axhline(y=zc, color="#3b82f6", alpha=0.45, lw=0.9, zorder=1)
                ax.axhspan(zl, zh, alpha=0.12, color="#3b82f6", zorder=0)
            if seen_zc:
                ax.plot([], [], color="#3b82f6", lw=2, label="Zone (from Closed)")

        _plot_trade_markers(ax, closed_rows, open_rows, ohlc)

        style = "zones + trades" if draw_zones else "trades"
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
    dip_pct: float = 1.041,
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
            print(f"[{pref} charts] {total} symbols, workers={n_workers} …", flush=True)
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                futs = {ex.submit(_chart_one_task, t): t[0] for t in tasks}
                done = 0
                for fut in as_completed(futs):
                    _sym, ok = fut.result()
                    if ok:
                        n_ok += 1
                    done += 1
                    if done % 10 == 0 or done == total:
                        print(f"[{pref} charts] {done}/{total} …", flush=True)
        else:
            for i, task in enumerate(tasks, 1):
                _sym, ok = _chart_one_task(task)
                if ok:
                    n_ok += 1
                if i % 10 == 0 or i == total:
                    print(f"[{pref} charts] {i}/{total} …", flush=True)

    n_total = n_ok + n_mem
    print(f"[{pref} charts] Wrote {n_total} PNG(s) → {chart_dir}", flush=True)
    return chart_dir


def write_rl_charts(
    *,
    tickers: dict[str, pd.DataFrame],
    closed_path: Path,
    output_dir: Path,
    ts: str,
    dip_pct: float = 1.041,
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
) -> dict[str, Path]:
    """Cheap enrichments only (no charts, no deep HTML)."""
    del tickers, open_path  # reserved
    out: dict[str, Path] = {}
    pref = normalize_system(prefix) or "RL"
    dip = 1.041
    if cfg is not None:
        dip = float(getattr(cfg, "rl_dip_pct", 1.041) or 1.041)
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
        print(f"[{pref} analysis] ONE_LINER on {n} closed rows → {Path(closed_path).name}", flush=True)
        out["closed"] = Path(closed_path)
    except Exception as e:
        print(f"[{pref} analysis] ONE_LINER failed: {e}", file=sys.stderr)

    try:
        n = enrich_summary_csv_with_fit(summary_path, closed_path, prefix=pref)
        print(f"[{pref} analysis] FIT columns on {n} summary rows → {Path(summary_path).name}", flush=True)
        out["summary"] = Path(summary_path)
    except Exception as e:
        print(f"[{pref} analysis] FIT enrichment failed: {e}", file=sys.stderr)

    try:
        hints_path = write_improve_hints(closed_path, out_dir, ts, prefix=pref)
        if hints_path:
            print(f"[{pref} analysis] Wrote {hints_path.name} (+ .md)", flush=True)
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
