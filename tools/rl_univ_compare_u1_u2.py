#!/usr/bin/env python3
"""RL universe compare: custom U1 (63) vs U2 (51 subset).

House freeze knobs identical. IS pick on quality; OOS report-only.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_univ_compare_u1_u2.py
  python tools/rl_univ_compare_u1_u2.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
DRIVE = ROOT / "drive"
DATA_DIR = ROOT / "data" / "newdata" / "data"
SA = ROOT / "stock_analysis"
STAMP = "20260827"
OUT_DIR = DRIVE / "paul_experiments" / f"rl_univ_compare_u1_u2_{STAMP}"
HOUSE_UNIV = DRIVE / "universes" / "RL_universe.csv"
PER_SYMBOL = SA / "Per_Symbol_Optimized_Settings_Approved_Latest.json"
IS_CUT = date(2024, 1, 1)
RL_CASH = 47_500.0
INIT = 500_000.0

sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(DRIVE / "paul_experiments"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402
from compare_format import (  # noqa: E402
    calmar_ratio,
    filter_html_compare_columns,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from rl_univ_compare_lists import (  # noqa: E402
    _attach_split_sharpes,
    _resolve_equity_curve,
)

# Exact lists — preserve order
U1 = [
    "IDR", "APPS", "ANIP", "FSI", "CORT", "MRNA", "NVAX", "CYTK", "DXPE", "PAYC",
    "BLDR", "P", "BC", "PSIX", "PATK", "NTRA", "SNFCA", "ABUS", "TGB", "AGI",
    "BELFA", "XPEL", "MOD", "IRMD", "SIMO", "AEHR", "DDS", "INOD", "STLD", "NGVC",
    "TGLS", "TPL", "AMRC", "FIVN", "HIMS", "ZM", "GFI", "AVAV", "NVDA", "TPC",
    "HCI", "ENVA", "TBBK", "ARGX", "NFLX", "AGX", "LMAT", "PANW", "WRLD", "FANG",
    "AHCO", "PDEX", "MU", "GHM", "VRT", "CF", "TALO", "LMB", "HUBS", "SBS",
    "RNG", "SAIA", "MTZ",
]
U2 = [
    "FSI", "NVAX", "PAYC", "BC", "PATK", "NTRA", "SNFCA", "ABUS", "TGB", "BELFA",
    "MOD", "IRMD", "SIMO", "AEHR", "DDS", "INOD", "STLD", "NGVC", "TGLS", "TPL",
    "AMRC", "FIVN", "HIMS", "ZM", "GFI", "AVAV", "NVDA", "TPC", "HCI", "ENVA",
    "TBBK", "ARGX", "NFLX", "AGX", "LMAT", "PANW", "WRLD", "FANG", "AHCO", "PDEX",
    "MU", "GHM", "VRT", "CF", "TALO", "LMB", "HUBS", "SBS", "RNG", "SAIA", "MTZ",
]

RL_COMMON_V = [
    "rl_mode=true",
    "brt_zones=false",
    "yh_zones=false",
    "wpbr_zones=false",
    "indicator_buy=off",
    "rl_sma_qual=1",
    "ATR_LOW=off",
    "ATR_HIGH=off",
    "rl_slope_threshold=0",
    "rl_too_high=0",
    "rl_dip_pct=1.041",
    "rl_expansion=1.163",
    "rl_stop_pct=0.934",
    "rl_target_pct=1.2",
    "rl_post_target_reentry_bars=0",
]

ARMS: list[dict[str, Any]] = [
    {
        "id": "univ1",
        "label": "Universe 1 (63 names)",
        "role": "baseline",
        "symbols": U1,
        "csv_name": "univ1.csv",
    },
    {
        "id": "univ2",
        "label": "Universe 2 (51 names, U1 subset)",
        "role": "candidate",
        "symbols": U2,
        "csv_name": "univ2.csv",
    },
]


def _resolve_python() -> str:
    env_py = os.environ.get("PY", "").strip()
    if env_py and Path(env_py).is_file():
        return env_py
    for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python310/python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Python/Python311/python.exe",
    ):
        if p.is_file():
            return str(p)
    return sys.executable


def write_univ_csvs() -> tuple[list[str], list[str]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "univ1.csv").write_text("\n".join(U1) + "\n", encoding="utf-8")
    (OUT_DIR / "univ2.csv").write_text("\n".join(U2) + "\n", encoding="utf-8")
    missing: list[str] = []
    for s in U1:
        if not (DATA_DIR / f"{s}.csv").is_file():
            missing.append(s)
    dropped = [s for s in U1 if s not in set(U2)]
    return missing, dropped


def load_house_univ() -> list[str]:
    if not HOUSE_UNIV.is_file():
        return []
    out: list[str] = []
    for line in HOUSE_UNIV.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip().upper()
        if not s or s.startswith("#") or s == "SYMBOL":
            continue
        out.append(s.split(",")[0].strip().upper())
    return out


def build_cmd(py: str, outdir: Path, workers: int, symbols: str) -> list[str]:
    cmd = [
        py,
        str(SA / "rocket_tbn.py"),
        str(DATA_DIR),
        "-o",
        str(outdir),
        "-w",
        str(workers),
        "--aggressive",
        "--use-duckdb",
        "--no-regression",
    ]
    if PER_SYMBOL.is_file():
        cmd.extend(["--per-symbol-settings", str(PER_SYMBOL)])
    for v in RL_COMMON_V:
        cmd.extend(["-v", v])
    cmd.extend(["-s", symbols])
    return cmd


def _find_latest(outdir: Path, pattern: str) -> Optional[Path]:
    files = sorted(outdir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_d(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if not t:
        return None
    compact = t.replace("-", "").replace("/", "")[:8]
    for cand, fmt in ((t[:10], "%Y-%m-%d"), (compact, "%Y%m%d"), (t[:10], "%m/%d/%Y")):
        try:
            return datetime.strptime(cand, fmt).date()
        except ValueError:
            continue
    return None


def _f(v: Any, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _row_get(row: dict, *names: str) -> str:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
        for k, v in row.items():
            if str(k).strip().upper().replace(" ", "_") == n.upper().replace(" ", "_") and v not in (None, ""):
                return str(v).strip()
    return ""


def load_trades(closed_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with closed_path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(_row_get(raw, "DATE OPENED", "DATE_OPENED"))
            closed = _parse_d(_row_get(raw, "DATE CLOSED", "DATE_CLOSED"))
            if opened is None:
                continue
            pnl = _f(_row_get(raw, "PNL %", "PNL_PCT"))
            days = _f(_row_get(raw, "DAYS HELD", "DAYS_HELD"))
            pnl_d = _f(_row_get(raw, "PNL_DOLLARS"))
            if pnl_d == 0.0 and pnl != 0.0:
                pnl_d = RL_CASH * pnl / 100.0
            rows.append(
                {
                    "sym": _row_get(raw, "SYMBOL").upper(),
                    "opened": opened,
                    "closed": closed,
                    "pnl": pnl,
                    "days": days,
                    "pnl_d": pnl_d,
                    "exit": _row_get(raw, "EXIT TYPE", "EXIT_TYPE") or "?",
                }
            )
    return rows


def book_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    empty: dict[str, Any] = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "wr": 0.0,
        "avg_pnl": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "pf": 0.0,
        "sheet": 0.0,
        "pnl_d": 0.0,
        "avg_days": 0.0,
        "med_days": 0.0,
        "cap_days": 0.0,
        "ppc": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "wo_max": 0.0,
        "exp_d": 0.0,
        "lose_streak": 0,
        "tpy": float("nan"),
        "sharpe": float("nan"),
        "exits": {},
    }
    if n == 0:
        return empty
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    mx = max(pnls)
    wo = (sum(pnls) - mx) / (n - 1) if n >= 2 else pnls[0]
    days = [t["days"] for t in trades if math.isfinite(t["days"]) and t["days"] > 0]
    cap = overlay_ann_ror_max_dd(trades, cash=RL_CASH, initial_account=INIT)
    sheet = sum(p / 100.0 * RL_CASH for p in pnls)
    pnl_d = sum(t["pnl_d"] for t in trades if math.isfinite(t["pnl_d"]))
    ann = cap["ann_ror"]
    dd = cap["max_dd"]
    cal = calmar_ratio(ann, dd) if calmar_ratio else float("nan")
    opens = [t["opened"] for t in trades if t["opened"]]
    closes = [t["closed"] for t in trades if t["closed"]]
    span = None
    if opens:
        lo = min(opens)
        hi = max(closes) if closes else max(opens)
        span = (hi - lo).days / 365.25
    tpy = (n / span) if span and span > 0 else float("nan")
    cur = max_streak = 0
    for p in pnls:
        if p < 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": 100.0 * len(wins) / n,
        "avg_pnl": sum(pnls) / n,
        "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "pf": (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "sheet": sheet,
        "pnl_d": pnl_d,
        "avg_days": (sum(days) / len(days)) if days else 0.0,
        "med_days": sorted(days)[len(days) // 2] if days else 0.0,
        "cap_days": float(cap["capital_days"] or 0.0),
        "ppc": (pnl_d / cap["capital_days"]) if cap["capital_days"] else float("nan"),
        "ann_ror": ann,
        "max_dd": dd,
        "calmar": cal if cal is not None else float("nan"),
        "wo_max": wo,
        "exp_d": sheet / n,
        "lose_streak": max_streak,
        "tpy": tpy,
        "sharpe": float("nan"),
        "exits": dict(Counter(str(t.get("exit") or "?").strip().upper() for t in trades)),
    }


def split_is_oos(trades: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    return [t for t in trades if t["opened"] < IS_CUT], [t for t in trades if t["opened"] >= IS_CUT]


def load_summary_aggs(path: Optional[Path]) -> dict[str, Any]:
    empty = {
        "n_sym": 0,
        "sum_paul": 0.0,
        "mean_paul": float("nan"),
        "sum_fit": 0.0,
        "mean_fit": float("nan"),
        "sum_robust": 0.0,
        "mean_robust": float("nan"),
        "mean_wo_max": float("nan"),
        "mean_outlier": float("nan"),
        "mean_tpy": float("nan"),
        "mean_pf": float("nan"),
    }
    if not path or not path.is_file():
        return empty
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return empty

    def nums(key: str) -> list[float]:
        out = []
        for r in rows:
            v = _f(_row_get(r, key), default=float("nan"))
            if math.isfinite(v):
                out.append(v)
        return out

    paul = nums("PAUL_SCORE")
    fit = nums("FIT_SCORE")
    rob = nums("FIT_SCORE_ROBUST")
    wo = nums("AVG_PNL_PCT_WO_MAX")
    outl = nums("OUTLIER_PCT_OF_WINS")
    tpy = nums("AVG_TRADES_PER_YEAR")
    pf = nums("PROFIT_FACTOR")
    return {
        "n_sym": len(rows),
        "sum_paul": sum(paul) if paul else 0.0,
        "mean_paul": (sum(paul) / len(paul)) if paul else float("nan"),
        "sum_fit": sum(fit) if fit else 0.0,
        "mean_fit": (sum(fit) / len(fit)) if fit else float("nan"),
        "sum_robust": sum(rob) if rob else 0.0,
        "mean_robust": (sum(rob) / len(rob)) if rob else float("nan"),
        "mean_wo_max": (sum(wo) / len(wo)) if wo else float("nan"),
        "mean_outlier": (sum(outl) / len(outl)) if outl else float("nan"),
        "mean_tpy": (sum(tpy) / len(tpy)) if tpy else float("nan"),
        "mean_pf": (sum(pf) / len(pf)) if pf else float("nan"),
    }


def load_equity_meta(path: Optional[Path]) -> dict[str, Any]:
    empty = {
        "eq_dd": float("nan"),
        "sharpe": float("nan"),
        "uw_days": float("nan"),
        "uw_pct": float("nan"),
    }
    if not path or not path.is_file():
        return empty
    with path.open(newline="", encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return empty
    return {
        "eq_dd": _f(_row_get(row, "Max_Drawdown_pct"), float("nan")),
        "sharpe": _f(_row_get(row, "Sharpe"), float("nan")),
        "uw_days": _f(_row_get(row, "Max_Days_Underwater"), float("nan")),
        "uw_pct": _f(_row_get(row, "Pct_Days_Underwater"), float("nan")),
    }


def run_arm(py: str, arm: dict[str, Any], workers: int, skip_existing: bool) -> dict[str, Any]:
    arm_dir = OUT_DIR / "runs" / arm["id"]
    arm_dir.mkdir(parents=True, exist_ok=True)
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    if skip_existing and closed and closed.stat().st_size > 0:
        trades = load_trades(closed)
        if trades:
            stamp = closed.stem.split("_")[-1]
            return {
                "arm": arm,
                "ok": True,
                "skipped": True,
                "closed": closed,
                "trades": trades,
                "stamp": stamp,
                "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
                "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
                "report": _find_latest(arm_dir, "RL_Report_*.csv"),
            }
    symbols = ",".join(arm["symbols"])
    cmd = build_cmd(py, arm_dir, workers, symbols)
    log_path = arm_dir / "run.log"
    t0 = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("CMD: " + " ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT))
    closed = _find_latest(arm_dir, "RL_Closed_*.csv")
    trades = load_trades(closed) if closed else []
    ok = proc.returncode == 0 and len(trades) > 0
    return {
        "arm": arm,
        "ok": ok,
        "skipped": False,
        "closed": closed,
        "trades": trades,
        "stamp": closed.stem.split("_")[-1] if closed else "",
        "elapsed_s": time.time() - t0,
        "exit_code": proc.returncode,
        "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
        "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
        "report": _find_latest(arm_dir, "RL_Report_*.csv"),
    }


def quality_score(m: dict[str, Any]) -> float:
    """Composite for IS pick — quality over N. Higher = better."""
    if m["n"] < 20:
        return -1e9
    ann = m["ann_ror"] if math.isfinite(m["ann_ror"]) else 0.0
    dd = m["max_dd"] if math.isfinite(m["max_dd"]) else 99.0
    cal = m["calmar"] if math.isfinite(m["calmar"]) else 0.0
    # Prefer avg quality, PF, calmar; penalize DD; slight sheet boost but not N
    return (
        m["avg_pnl"] * 3.0
        + m["wo_max"] * 2.0
        + m["wr"] * 0.05
        + m["pf"] * 2.0
        + ann * 0.02
        + cal * 1.5
        - dd * 0.15
        + (m["sheet"] / 1_000_000.0) * 0.5
    )


def pick_is_winner(u1: dict[str, Any], u2: dict[str, Any]) -> tuple[str, str]:
    m1, m2 = u1["m_is"], u2["m_is"]
    s1, s2 = quality_score(m1), quality_score(m2)
    # Quality edge: Avg% / WO_MAX / PF / Calmar; N secondary
    better_u2 = (
        (m2["avg_pnl"] > m1["avg_pnl"] + 0.05 and m2["wo_max"] >= m1["wo_max"] - 0.05)
        or (m2["avg_pnl"] >= m1["avg_pnl"] - 0.05 and m2["pf"] > m1["pf"] + 0.05 and m2["wr"] >= m1["wr"] - 0.5)
        or (s2 > s1 + 0.5 and m2["avg_pnl"] >= m1["avg_pnl"] - 0.15)
    )
    better_u1 = (
        (m1["avg_pnl"] > m2["avg_pnl"] + 0.05 and m1["wo_max"] >= m2["wo_max"] - 0.05)
        or (m1["avg_pnl"] >= m2["avg_pnl"] - 0.05 and m1["pf"] > m2["pf"] + 0.05 and m1["wr"] >= m2["wr"] - 0.5)
        or (s1 > s2 + 0.5 and m1["avg_pnl"] >= m2["avg_pnl"] - 0.15)
    )
    if better_u2 and not better_u1:
        return "univ2", (
            f"IS quality favors U2 (Avg% {m2['avg_pnl']:.2f} vs {m1['avg_pnl']:.2f}, "
            f"PF {m2['pf']:.2f} vs {m1['pf']:.2f}, N {m2['n']} vs {m1['n']}; quality over N)"
        )
    if better_u1 and not better_u2:
        return "univ1", (
            f"IS quality favors U1 (Avg% {m1['avg_pnl']:.2f} vs {m2['avg_pnl']:.2f}, "
            f"PF {m1['pf']:.2f} vs {m2['pf']:.2f}, N {m1['n']} vs {m2['n']})"
        )
    # Tie-break: higher Avg% then higher PF then lower DD
    if abs(m1["avg_pnl"] - m2["avg_pnl"]) > 0.02:
        win = "univ1" if m1["avg_pnl"] > m2["avg_pnl"] else "univ2"
    elif abs(m1["pf"] - m2["pf"]) > 0.02:
        win = "univ1" if m1["pf"] > m2["pf"] else "univ2"
    else:
        d1 = m1["max_dd"] if math.isfinite(m1["max_dd"]) else 99.0
        d2 = m2["max_dd"] if math.isfinite(m2["max_dd"]) else 99.0
        win = "univ1" if d1 <= d2 else "univ2"
    mw = m1 if win == "univ1" else m2
    ml = m2 if win == "univ1" else m1
    return win, (
        f"IS mixed/flat → tie-break on Avg%/PF/DD → {win} "
        f"(Avg% {mw['avg_pnl']:.2f} vs {ml['avg_pnl']:.2f})"
    )


def oos_supports(winner_id: str, u1: dict[str, Any], u2: dict[str, Any]) -> tuple[str, str]:
    """Report-only OOS validation of frozen IS pick. Does not change pick."""
    win = u1 if winner_id == "univ1" else u2
    lose = u2 if winner_id == "univ1" else u1
    mw, ml = win["m_oos"], lose["m_oos"]
    if mw["n"] < 15 or ml["n"] < 15:
        return "HOLD", f"OOS thin (winner N={mw['n']}, other N={ml['n']}) — caution"
    soft = (mw["avg_pnl"] < ml["avg_pnl"] - 0.15) or (mw["wr"] < ml["wr"] - 1.0) or (
        mw["pf"] + 0.05 < ml["pf"] and mw["avg_pnl"] <= ml["avg_pnl"]
    )
    note = (
        f"OOS winner Avg% {mw['avg_pnl']:.2f} vs other {ml['avg_pnl']:.2f}; "
        f"PF {mw['pf']:.2f} vs {ml['pf']:.2f}; WR {mw['wr']:.1f} vs {ml['wr']:.1f}"
    )
    if soft:
        return "HOLD", note + " — OOS softens IS pick (do not retune)"
    # Clear OOS support
    if mw["avg_pnl"] >= ml["avg_pnl"] - 0.05 and mw["pf"] >= ml["pf"] - 0.05:
        return "LEAN KEEP", note + " — OOS supports IS pick (research candidate ≠ gold)"
    return "HOLD", note + " — OOS mixed"


def pack_result(run: dict[str, Any]) -> dict[str, Any]:
    trades = run["trades"]
    is_t, oos_t = split_is_oos(trades)
    m_full = book_stats(trades)
    m_is = book_stats(is_t)
    m_oos = book_stats(oos_t)
    eq_meta = load_equity_meta(run.get("equity_meta"))
    equity_curve = _resolve_equity_curve(run)
    _attach_split_sharpes(m_full, m_is, m_oos, equity_curve=equity_curve, eq_meta=eq_meta)
    return {
        **run,
        "m_full": m_full,
        "m_is": m_is,
        "m_oos": m_oos,
        "sum_agg": load_summary_aggs(run.get("summary")),
        "eq_meta": eq_meta,
        "equity_curve": equity_curve,
    }


def fmt_n(v: Any, nd: int = 2) -> str:
    if v is None:
        return "—"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(x):
        return "—"
    if nd == 0:
        return str(int(round(x)))
    return f"{x:.{nd}f}"


def compare_row(p: dict[str, Any], split_key: str, baseline: dict[str, Any], is_pick: str) -> str:
    m = p[split_key]
    c = baseline[split_key]
    arm = p["arm"]
    d_avg = m["avg_pnl"] - c["avg_pnl"]
    d_pf = m["pf"] - c["pf"]
    d_ann = m["ann_ror"] - c["ann_ror"] if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"]) else float("nan")
    d_dd = m["max_dd"] - c["max_dd"] if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"]) else float("nan")
    d_cal = m["calmar"] - c["calmar"] if math.isfinite(m["calmar"]) and math.isfinite(c["calmar"]) else float("nan")
    d_wr = m["wr"] - c["wr"]
    cls = "ctrl-row" if arm["id"] == "univ1" else ""
    pick_mark = "★ IS pick" if arm["id"] == is_pick and split_key == "m_is" else ""
    sa = p["sum_agg"] if split_key == "m_full" else {}
    eq = p["eq_meta"] if split_key == "m_full" else {}
    sharpe = m.get("sharpe", float("nan"))
    return (
        f'<tr class="{cls}">'
        f'<td data-sort-value="{html_mod.escape(arm["label"])}">{html_mod.escape(arm["label"])}</td>'
        f'<td data-sort-value="{len(arm["symbols"])}">{len(arm["symbols"])}</td>'
        f'<td data-sort-value="{m["n"]}">{m["n"]}</td>'
        f'<td data-sort-value="{m["wr"]}">{fmt_n(m["wr"], 2)}</td>'
        f'<td data-sort-value="{m["avg_pnl"]}">{fmt_n(m["avg_pnl"], 2)}</td>'
        f'<td data-sort-value="{m["wo_max"]}">{fmt_n(m["wo_max"], 2)}</td>'
        f'<td data-sort-value="{m["avg_win"]}">{fmt_n(m["avg_win"], 2)}</td>'
        f'<td data-sort-value="{m["avg_loss"]}">{fmt_n(m["avg_loss"], 2)}</td>'
        f'<td data-sort-value="{m["pf"]}">{fmt_n(m["pf"], 3)}</td>'
        f'<td data-sort-value="{m["ann_ror"]}">{fmt_n(m["ann_ror"], 2)}</td>'
        f'<td data-sort-value="{m["max_dd"]}">{fmt_n(m["max_dd"], 2)}</td>'
        f'<td data-sort-value="{m["calmar"]}">{fmt_n(m["calmar"], 2)}</td>'
        f'<td data-sort-value="{sharpe}">{fmt_n(sharpe, 2)}</td>'
        f'<td data-sort-value="{m["exp_d"]}">{format_money(m["exp_d"])}</td>'
        f'<td data-sort-value="{m["avg_days"]}">{fmt_n(m["avg_days"], 2)}</td>'
        f'<td data-sort-value="{m["cap_days"]}">{fmt_n(m["cap_days"], 0)}</td>'
        f'<td data-sort-value="{m["ppc"]}">{format_money(m["ppc"]) if math.isfinite(m["ppc"]) else "—"}</td>'
        f'<td data-sort-value="{m["lose_streak"]}">{m["lose_streak"]}</td>'
        f'<td data-sort-value="{m["tpy"]}">{fmt_n(m["tpy"], 2)}</td>'
        f'<td data-sort-value="{sa.get("mean_paul", float("nan"))}">{fmt_n(sa.get("mean_paul"), 2) if split_key == "m_full" else "—"}</td>'
        f'<td data-sort-value="{sa.get("mean_fit", float("nan"))}">{fmt_n(sa.get("mean_fit"), 2) if split_key == "m_full" else "—"}</td>'
        f'<td data-sort-value="{sa.get("mean_robust", float("nan"))}">{fmt_n(sa.get("mean_robust"), 2) if split_key == "m_full" else "—"}</td>'
        f'<td data-sort-value="{eq.get("uw_days", float("nan"))}">{fmt_n(eq.get("uw_days"), 0) if split_key == "m_full" else "—"}</td>'
        f'<td data-sort-value="{d_avg if arm["id"] != "univ1" else ""}">'
        f'{"—" if arm["id"] == "univ1" else f"{d_avg:+.2f}"}</td>'
        f'<td data-sort-value="{d_wr if arm["id"] != "univ1" else ""}">'
        f'{"—" if arm["id"] == "univ1" else f"{d_wr:+.2f}"}</td>'
        f'<td data-sort-value="{d_pf if arm["id"] != "univ1" else ""}">'
        f'{"—" if arm["id"] == "univ1" else f"{d_pf:+.3f}"}</td>'
        f'<td data-sort-value="{d_ann if arm["id"] != "univ1" else ""}">'
        f'{"—" if arm["id"] == "univ1" else fmt_n(d_ann, 2)}</td>'
        f'<td data-sort-value="{d_dd if arm["id"] != "univ1" else ""}">'
        f'{"—" if arm["id"] == "univ1" else fmt_n(d_dd, 2)}</td>'
        f'<td data-sort-value="{d_cal if arm["id"] != "univ1" else ""}">'
        f'{"—" if arm["id"] == "univ1" else fmt_n(d_cal, 2)}</td>'
        f'<td data-sort-value="{pick_mark}">{html_mod.escape(pick_mark)}</td>'
        "</tr>"
    )


def write_compare_html(
    packed: list[dict[str, Any]],
    is_pick: str,
    pick_note: str,
    verdict: str,
    oos_note: str,
    dropped: list[str],
) -> Path:
    baseline = next(p for p in packed if p["arm"]["id"] == "univ1")
    th_cols = filter_html_compare_columns(
        [
            ("Arm", "text"),
            ("Univ N", "num"),
            ("Trades", "num"),
            ("WR%", "num"),
            ("Sheet PnL $", "num"),
            ("Total PnL $", "num"),
            ("Avg PnL%", "num"),
            ("Avg% w/o max", "num"),
            ("Avg win%", "num"),
            ("Avg loss%", "num"),
            ("PF", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Sharpe", "num"),
            ("Expect $", "num"),
            ("Avg days", "num"),
            ("Cap days", "num"),
            ("PPCD", "num"),
            ("Lose streak", "num"),
            ("Trades/yr", "num"),
            ("Mean Paul", "num"),
            ("Mean FIT", "num"),
            ("Mean robust FIT", "num"),
            ("Max UW days", "num"),
            ("Δ Sheet $", "num"),
            ("Δ Avg%", "num"),
            ("Δ WR", "num"),
            ("Δ PF", "num"),
            ("Δ Ann ROR", "num"),
            ("Δ Max DD", "num"),
            ("Δ Calmar", "num"),
            ("IS pick", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(compare_row(p, split_key, baseline, is_pick) for p in packed)
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta. Sharpe from host EquityCurve "
            "(Equity_Regular when present; IS/OOS = calendar slices)."
            if split_key == "m_full"
            else "Closed overlay at $47,500 cash / $500k initial. Sharpe from host EquityCurve "
            "calendar slice. Paul/FIT N/A on slices."
        )
        sections.append(
            f'<section><h2>RL universe compare — {title}</h2>'
            f'<p class="muted">Split=<strong>{title.split()[0]}</strong>. {note} '
            f"Click column headers to sort. Δ vs Universe 1.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    exit_rows = []
    for p in packed:
        ex = p["m_full"]["exits"]
        tot = max(p["m_full"]["n"], 1)
        exit_rows.append(
            "<tr>"
            f"<td>{html_mod.escape(p['arm']['label'])}</td>"
            f"<td>{ex.get('TARGET', 0)} ({100*ex.get('TARGET',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('STOP_LOSS', 0)} ({100*ex.get('STOP_LOSS',0)/tot:.1f}%)</td>"
            f"<td>{ex.get('GAP_DOWN', 0)}</td>"
            f"<td>{ex.get('GAP_UP', 0)}</td>"
            f"<td>{ex.get('TIME', 0)}</td>"
            "</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL univ1 vs univ2 — {STAMP}</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; --ctrl:#243044; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1400px;margin:0 auto}}
h1{{font-size:1.35rem;margin:0 0 .35rem}}
h2{{font-size:1.05rem;margin:1.25rem 0 .4rem;color:var(--accent)}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
main{{max-width:1400px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.35rem .4rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}
tr.ctrl-row{{background:var(--ctrl)}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{background:#e8e4d8}', 'th.sortable-th:hover{background:#2a3545}')}
@media (max-width:700px){{ table{{font-size:.72rem;min-width:900px}} }}
</style>
</head>
<body>
<header>
<h1>RL universe compare — U1 (63) vs U2 (51 subset)</h1>
<p class="muted">Stamp <code>rl_univ_compare_u1_u2_{STAMP}</code>. Label: <strong>universe compare</strong> (not stop/knob AB).
House freeze: dip=1.041, expansion=1.163, rl_stop_pct=0.934, target=1.20, too_high=off, brt_zones=false.
IS = entry &lt; 2024-01-01 (pick); OOS ≥ 2024-01-01 report-only. Research-only — not gold / not DailyRun.
Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>IS pick:</strong> {html_mod.escape(is_pick)} — {html_mod.escape(pick_note)}<br/>
<strong>OOS validation:</strong> {html_mod.escape(verdict)} — {html_mod.escape(oos_note)}<br/>
<strong>Dropped (U1−U2):</strong> {html_mod.escape(", ".join(dropped))}
</div>
{"".join(sections)}
<section>
<h2>Exit mix (FULL)</h2>
<p class="muted">Counts and % from Closed EXIT_TYPE.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>
{sortable_th("Arm", "text")}{sortable_th("TARGET", "text")}{sortable_th("STOP_LOSS", "text")}
{sortable_th("GAP_DOWN", "num")}{sortable_th("GAP_UP", "num")}{sortable_th("TIME", "num")}
</tr></thead><tbody>{"".join(exit_rows)}</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_metrics_csv(packed: list[dict[str, Any]], is_pick: str, path: Path) -> None:
    fields = [
        "arm", "univ_n", "split", "n", "wr", "sheet", "pnl_d", "avg_pnl", "wo_max",
        "avg_win", "avg_loss", "pf", "ann_ror", "max_dd", "calmar", "exp_d", "avg_days",
        "cap_days", "ppc", "lose_streak", "tpy", "mean_paul", "mean_fit", "mean_robust",
        "sharpe", "is_pick",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for p in packed:
            for split, key in (("IS", "m_is"), ("OOS", "m_oos"), ("FULL", "m_full")):
                m = p[key]
                sa = p["sum_agg"] if key == "m_full" else {}
                w.writerow(
                    {
                        "arm": p["arm"]["id"],
                        "univ_n": len(p["arm"]["symbols"]),
                        "split": split,
                        "n": m["n"],
                        "wr": m["wr"],
                        "sheet": m["sheet"],
                        "pnl_d": m["pnl_d"],
                        "avg_pnl": m["avg_pnl"],
                        "wo_max": m["wo_max"],
                        "avg_win": m["avg_win"],
                        "avg_loss": m["avg_loss"],
                        "pf": m["pf"],
                        "ann_ror": m["ann_ror"],
                        "max_dd": m["max_dd"],
                        "calmar": m["calmar"],
                        "exp_d": m["exp_d"],
                        "avg_days": m["avg_days"],
                        "cap_days": m["cap_days"],
                        "ppc": m["ppc"],
                        "lose_streak": m["lose_streak"],
                        "tpy": m["tpy"],
                        "mean_paul": sa.get("mean_paul", ""),
                        "mean_fit": sa.get("mean_fit", ""),
                        "mean_robust": sa.get("mean_robust", ""),
                        "sharpe": m.get("sharpe", ""),
                        "is_pick": "yes" if p["arm"]["id"] == is_pick and split == "IS" else "",
                    }
                )


def write_baseline(packed: list[dict[str, Any]], missing: list[str], dropped: list[str], house: list[str]) -> None:
    lines = [
        f"# BASELINE — `rl_univ_compare_u1_u2_{STAMP}`",
        "",
        "**Universe compare** (not a stop/knob AB). Research candidate ≠ gold ≠ DailyRun.",
        "",
        "## House RL freeze (identical both arms)",
        "",
        "| Knob | Value | Source |",
        "|------|-------|--------|",
        "| `rl_dip_pct` | **1.041** | `run_rl.bat` / `RLConfig` / `docs/systems/rl.html` |",
        "| `rl_expansion` | **1.163** | `RLConfig` / rl.html |",
        "| `rl_stop_pct` | **0.934** | `RLConfig` / rl.html |",
        "| `rl_target_pct` | **1.20** | `RLConfig` |",
        "| `rl_too_high` | **0 / off** | `run_rl.bat` `-v rl_too_high=0` |",
        "| `brt_zones` | **false** | `run_rl.bat` |",
        "| `yh_zones` / `indicator_buy` | false / off | house |",
        "| `rl_sma_qual` | 1 | house |",
        "",
        "Do **not** retune knobs on this stamp.",
        "",
        "## Universes",
        "",
        f"- **U1** (`univ1.csv`): {len(U1)} names — {', '.join(U1)}",
        f"- **U2** (`univ2.csv`): {len(U2)} names — {', '.join(U2)}",
        f"- **Dropped (U1−U2):** {', '.join(dropped)} ({len(dropped)} names)",
        f"- **House RL_universe.csv:** {len(house)} names (reference only; not an arm here)",
        "",
        "## IS pick rule",
        "",
        "- Split: IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01`",
        "- Pick on **IS quality** (WR, Avg PnL%, WO_MAX, PF, Ann ROR, Max DD, Calmar, sheet PnL) — **quality over N**",
        "- OOS is **report-only** — do not change pick; if OOS softens → HOLD, do not retune",
        "",
        "## Missing OHLC",
        "",
        f"- {', '.join(missing) if missing else 'None — all U1 symbols present under data/newdata/data/'}",
        "",
        "## Arms",
        "",
        "| Arm | Stamp | N_full | OK |",
        "|-----|-------|--------|-----|",
    ]
    for p in packed:
        lines.append(
            f"| `{p['arm']['id']}` | `{p.get('stamp','')}` | {p['m_full']['n']} | "
            f"{'yes' if p.get('ok') else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `univ1.csv` / `univ2.csv`",
            "- `compare.html` — sortable IS / OOS / FULL",
            "- `metrics_all.csv`",
            "- `SUMMARY.md`",
            "- `runs/<arm>/RL_*`",
        ]
    )
    (OUT_DIR / "BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(
    packed: list[dict[str, Any]],
    is_pick: str,
    pick_note: str,
    verdict: str,
    oos_note: str,
    dropped: list[str],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# SUMMARY — `rl_univ_compare_u1_u2_{STAMP}`",
        "",
        "**Universe compare.** Research only. Not gold / not DailyRun.",
        "",
        "## Freeze",
        "",
        "`rl_dip_pct=1.041`, `rl_expansion=1.163`, `rl_stop_pct=0.934`, `rl_target_pct=1.20`, "
        "`rl_too_high=0`, `brt_zones=false`.",
        "",
        f"**Dropped (U1−U2):** {', '.join(dropped)}",
        "",
        "## IS pick (entry < 2024-01-01)",
        "",
        f"**Pick: `{is_pick}`** — {pick_note}",
        "",
        "| Arm | N | WR% | Avg% | WO_MAX | PF | Ann ROR | Max DD | Calmar |",
        "|-----|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for aid in ("univ1", "univ2"):
        p = by_id[aid]
        m = p["m_is"]
        mark = " ← IS pick" if aid == is_pick else ""
        lines.append(
            f"| {p['arm']['label']}{mark} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
            f"{m['wo_max']:.2f} | {m['pf']:.2f} | "
            f"{fmt_n(m['ann_ror'], 1)} | {fmt_n(m['max_dd'], 2)} | {fmt_n(m['calmar'], 2)} |"
        )
    lines.extend(["", "## OOS validation (report-only)", "", f"**Verdict: {verdict}** — {oos_note}", ""])
    for aid in ("univ1", "univ2"):
        p = by_id[aid]
        m = p["m_oos"]
        lines.append(
            f"- **{p['arm']['label']}**: N={m['n']}, WR={m['wr']:.1f}%, Avg%={m['avg_pnl']:.2f}, "
            f"WO_MAX={m['wo_max']:.2f}, PF={m['pf']:.2f}, "
            f"Ann ROR={fmt_n(m['ann_ror'], 1)}, Max DD={fmt_n(m['max_dd'], 2)}, "
            f"Calmar={fmt_n(m['calmar'], 2)}"
        )
    lines.extend(["", "## FULL book", ""])
    for aid in ("univ1", "univ2"):
        p = by_id[aid]
        m = p["m_full"]
        sa = p["sum_agg"]
        eq = p["eq_meta"]
        lines.append(
            f"- **{p['arm']['label']}**: N={m['n']}, WR={m['wr']:.1f}%, Avg%={m['avg_pnl']:.2f}, "
            f"PF={m['pf']:.2f}, Ann ROR={fmt_n(m['ann_ror'], 1)}, "
            f"Max DD overlay={fmt_n(m['max_dd'], 2)}, Calmar={fmt_n(m['calmar'], 2)}, "
            f"Sharpe(EquityMeta)={fmt_n(eq.get('sharpe'), 2)}, "
            f"mean Paul={fmt_n(sa.get('mean_paul'), 2)}, mean FIT={fmt_n(sa.get('mean_fit'), 2)}, "
            f"mean robust={fmt_n(sa.get('mean_robust'), 2)}"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- IS pick frozen: **`{is_pick}`**",
            f"- After OOS: **{verdict}** (research candidate only; do not wire DailyRun)",
            "- Do not retune knobs or re-pick from OOS",
            "",
            "## Process notes",
            "",
            "- Quality over trade count",
            "- OOS soften → HOLD, do not retune",
            "- Selection: U2 is a named subset of U1 (dropped set documented)",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(packed: list[dict[str, Any]], missing: list[str], dropped: list[str], house: list[str]) -> dict[str, Any]:
    u1 = next(p for p in packed if p["arm"]["id"] == "univ1")
    u2 = next(p for p in packed if p["arm"]["id"] == "univ2")
    is_pick, pick_note = pick_is_winner(u1, u2)
    verdict, oos_note = oos_supports(is_pick, u1, u2)
    write_compare_html(packed, is_pick, pick_note, verdict, oos_note, dropped)
    write_metrics_csv(packed, is_pick, OUT_DIR / "metrics_all.csv")
    write_baseline(packed, missing, dropped, house)
    write_summary(packed, is_pick, pick_note, verdict, oos_note, dropped)
    print(f"[RL-UNIV] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(f"[RL-UNIV] IS pick={is_pick} | verdict={verdict}", flush=True)
    return {
        "is_pick": is_pick,
        "pick_note": pick_note,
        "verdict": verdict,
        "oos_note": oos_note,
        "u1": u1,
        "u2": u2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", default=False)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    skip_existing = (args.skip_existing or args.summarize_only) and not args.force

    missing, dropped = write_univ_csvs()
    house = load_house_univ()
    print(f"[RL-UNIV] Stamp {OUT_DIR}", flush=True)
    print(f"[RL-UNIV] U1={len(U1)} U2={len(U2)} dropped={len(dropped)} missing_ohlc={missing}", flush=True)
    print(f"[RL-UNIV] House RL univ N={len(house)}", flush=True)

    py = _resolve_python()
    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in ARMS:
            arm_dir = OUT_DIR / "runs" / arm["id"]
            closed = _find_latest(arm_dir, "RL_Closed_*.csv")
            if not closed:
                print(f"[RL-UNIV] Missing Closed for {arm['id']}", flush=True)
                return 1
            trades = load_trades(closed)
            runs.append(
                {
                    "arm": arm,
                    "ok": len(trades) > 0,
                    "skipped": True,
                    "closed": closed,
                    "trades": trades,
                    "stamp": closed.stem.split("_")[-1],
                    "summary": _find_latest(arm_dir, "RL_Summary_*.csv"),
                    "equity_meta": _find_latest(arm_dir, "RL_EquityMeta_*.csv"),
                    "report": _find_latest(arm_dir, "RL_Report_*.csv"),
                }
            )
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(run_arm, py, arm, args.workers, skip_existing): arm for arm in ARMS}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[RL-UNIV] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                    flush=True,
                )
                runs.append(run)

    runs.sort(key=lambda r: 0 if r["arm"]["id"] == "univ1" else 1)
    if not all(r.get("ok") for r in runs):
        print("[RL-UNIV] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        # Continue if we have any trades to report
        if not any(r.get("trades") for r in runs):
            return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed, missing, dropped, house)

    # ntfy
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "-t",
                "RL univ1 vs univ2",
                "-m",
                f"IS pick={result['is_pick']} verdict={result['verdict']}",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
