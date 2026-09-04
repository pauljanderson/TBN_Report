#!/usr/bin/env python3
"""RL universe compare: List1 (97) vs List2 (95) vs house RL (59).

House freeze knobs identical. IS pick on quality; OOS report-only.
Research-only. Not gold. Not DailyRun.

Usage:
  python tools/rl_univ_compare_lists.py
  python tools/rl_univ_compare_lists.py --summarize-only
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import os
import shutil
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
OUT_DIR = DRIVE / "paul_experiments" / f"rl_univ_compare_list1_list2_{STAMP}"
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
    find_host_equity_curve_csv,
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
    sharpe_from_equity_curve_csv,
)

# Exact lists — preserve order
LIST1 = [
    "ABUS", "ACAD", "AEHR", "AGI", "AGX", "AHCO", "ALNY", "AMRC", "ANDE", "APA",
    "APPS", "APYX", "ARGX", "AVAV", "AVGO", "AX", "BBW", "BBWI", "BELFA", "BLDR",
    "CCJ", "CF", "CMCL", "CORT", "CRWD", "CYTK", "CZR", "DDS", "DXPE", "EDVMF",
    "ENVA", "EXEL", "FANG", "FIVN", "FSI", "FSLY", "GFI", "GGAL", "GHM", "HCI",
    "HIMS", "HUBS", "IDR", "IESC", "INOD", "IRMD", "JBLU", "LMAT", "LMB", "LULU",
    "M", "MELI", "MOD", "MPWR", "MRNA", "MTDR", "MTZ", "MU", "NFLX", "NGVC",
    "NMIH", "NTRA", "NVAX", "NVDA", "P", "PANW", "PATK", "PAYC", "PDEX", "PSIX",
    "RDNT", "RMBS", "RNG", "SAIA", "SBS", "SHOP", "SIMO", "SMID", "SNFCA", "STLD",
    "STX", "TALO", "TBBK", "TENB", "TGB", "TGLS", "TPC", "TPL", "VEEV", "VRT",
    "WLDN", "WPM", "WRLD", "XPEL", "ZM",
]
LIST2 = [s for s in LIST1 if s not in ("IDR", "RDNT")]

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
    "rl_dip_pct=1.055",
    "rl_expansion=1.163",
    "rl_stop_pct=0.934",
    "rl_target_pct=1.2",
    "rl_cut_the_losers=1000",
    "rl_exit_percent=0.40",
    "rl_exit_days=30",
    "rl_post_target_reentry_bars=0",
]

CONTROL_ID = "house59"


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


def build_arms(house: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": "list1",
            "label": "List 1 (95 names)",
            "role": "candidate",
            "symbols": LIST1,
            "csv_name": "list1.csv",
        },
        {
            "id": "list2",
            "label": "List 2 (93 names, L1−IDR/RDNT)",
            "role": "candidate",
            "symbols": LIST2,
            "csv_name": "list2.csv",
        },
        {
            "id": CONTROL_ID,
            "label": "House RL (59 names, control)",
            "role": "control",
            "symbols": house,
            "csv_name": "rl_universe_59.csv",
        },
    ]


def write_univ_csvs(house: list[str]) -> tuple[list[str], list[str], dict[str, list[str]]]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "list1.csv").write_text("\n".join(LIST1) + "\n", encoding="utf-8")
    (OUT_DIR / "list2.csv").write_text("\n".join(LIST2) + "\n", encoding="utf-8")
    (OUT_DIR / "rl_universe_59.csv").write_text("\n".join(house) + "\n", encoding="utf-8")
    missing: list[str] = []
    for s in LIST1:
        if not (DATA_DIR / f"{s}.csv").is_file():
            missing.append(s)
    dropped = [s for s in LIST1 if s not in set(LIST2)]
    overlap = {
        "list1_house": sorted(set(LIST1) & set(house)),
        "list2_house": sorted(set(LIST2) & set(house)),
        "house_only": sorted(set(house) - set(LIST1)),
        "list1_only": sorted(set(LIST1) - set(house)),
        "list2_only": sorted(set(LIST2) - set(house)),
    }
    return missing, dropped, overlap


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
                    "max_gain": _f(_row_get(raw, "MAX GAIN", "MAX_GAIN")),
                    "mae": _f(_row_get(raw, "MAE")),
                    "hist_high": _f(_row_get(raw, "HIST_HIGH_PCT")),
                    "entry": _f(_row_get(raw, "ENTRY PRICE", "ENTRY_PRICE")),
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
    if m["n"] < 20:
        return -1e9
    ann = m["ann_ror"] if math.isfinite(m["ann_ror"]) else 0.0
    dd = m["max_dd"] if math.isfinite(m["max_dd"]) else 99.0
    cal = m["calmar"] if math.isfinite(m["calmar"]) else 0.0
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


def pick_is_winner(packed: list[dict[str, Any]]) -> tuple[str, str]:
    scored = [(quality_score(p["m_is"]), p) for p in packed]
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    second_score, second = scored[1]
    best_id = best["arm"]["id"]
    bm, sm = best["m_is"], second["m_is"]
    note = (
        f"IS quality score favors `{best_id}` "
        f"(Avg% {bm['avg_pnl']:.2f} vs {sm['avg_pnl']:.2f}, "
        f"PF {bm['pf']:.2f} vs {sm['pf']:.2f}, "
        f"WO_MAX {bm['wo_max']:.2f} vs {sm['wo_max']:.2f}, "
        f"N {bm['n']} vs {sm['n']}; quality over N; score gap {best_score - second_score:.1f})"
    )
    return best_id, note


def verdict_vs_control(candidate: dict[str, Any], control: dict[str, Any], split_key: str) -> tuple[str, str]:
    """KEEP / LEAN KEEP / HOLD / DISMISS vs house 59."""
    m, c = candidate[split_key], control[split_key]
    if m["n"] < 15:
        return "HOLD", f"thin N={m['n']}"
    better = (
        m["avg_pnl"] > c["avg_pnl"] + 0.05
        and m["wo_max"] >= c["wo_max"] - 0.05
        and m["pf"] >= c["pf"] - 0.03
    )
    worse = (
        m["avg_pnl"] < c["avg_pnl"] - 0.10
        or (m["pf"] + 0.05 < c["pf"] and m["avg_pnl"] <= c["avg_pnl"])
        or (math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"]) and m["max_dd"] > c["max_dd"] + 3.0)
    )
    note = (
        f"Avg% {m['avg_pnl']:.2f} vs ctrl {c['avg_pnl']:.2f}; "
        f"PF {m['pf']:.2f} vs {c['pf']:.2f}; WR {m['wr']:.1f} vs {c['wr']:.1f}"
    )
    if better and not worse:
        return "LEAN KEEP", note
    if worse:
        return "DISMISS", note
    return "HOLD", note


def oos_supports(is_pick: str, packed: list[dict[str, Any]]) -> tuple[str, str]:
    by_id = {p["arm"]["id"]: p for p in packed}
    win = by_id[is_pick]
    others = [p for p in packed if p["arm"]["id"] != is_pick]
    mw = win["m_oos"]
    if mw["n"] < 15:
        return "HOLD", f"OOS thin for IS pick (N={mw['n']}) — caution"
    soft = any(
        mw["avg_pnl"] < p["m_oos"]["avg_pnl"] - 0.15
        or (mw["pf"] + 0.05 < p["m_oos"]["pf"] and mw["avg_pnl"] <= p["m_oos"]["avg_pnl"])
        for p in others
        if p["m_oos"]["n"] >= 15
    )
    best_oos = max(packed, key=lambda p: quality_score(p["m_oos"]))
    note = (
        f"IS pick `{is_pick}` OOS: Avg% {mw['avg_pnl']:.2f}, PF {mw['pf']:.2f}, N={mw['n']}; "
        f"best OOS arm={best_oos['arm']['id']} (Avg% {best_oos['m_oos']['avg_pnl']:.2f})"
    )
    if soft:
        return "HOLD", note + " — OOS softens IS pick (do not retune)"
    if best_oos["arm"]["id"] == is_pick:
        return "LEAN KEEP", note + " — OOS supports IS pick (research candidate ≠ gold)"
    return "HOLD", note + " — OOS mixed vs IS pick"


def _resolve_equity_curve(run: dict[str, Any]) -> Optional[Path]:
    """Host daily EquityCurve for Sharpe (FULL + IS/OOS calendar slices)."""
    explicit = run.get("equity_curve")
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
    stamp = str(run.get("stamp") or "").strip() or None
    for key in ("closed", "equity_meta", "report", "summary"):
        ref = run.get(key)
        if not ref:
            continue
        parent = Path(ref).parent
        found = find_host_equity_curve_csv(parent, stamp=stamp)
        if found is not None:
            return found
        found = find_host_equity_curve_csv(parent, stamp=None)
        if found is not None:
            return found
    return None


def _attach_split_sharpes(
    m_full: dict[str, Any],
    m_is: dict[str, Any],
    m_oos: dict[str, Any],
    *,
    equity_curve: Optional[Path],
    eq_meta: dict[str, Any],
) -> None:
    """Fill book Sharpe from EquityMeta (FULL) and EquityCurve date slices (IS/OOS).

    Host daily curve (prefer Equity_Regular) — same definition as Report / EquityMeta.
    Overlay Ann ROR / Max DD remain Closed-replay; Sharpe is host-curve descriptive.
    """
    meta_s = eq_meta.get("sharpe", float("nan"))
    if isinstance(meta_s, (int, float)) and math.isfinite(float(meta_s)):
        m_full["sharpe"] = float(meta_s)
    else:
        s_full = sharpe_from_equity_curve_csv(equity_curve)
        m_full["sharpe"] = float(s_full) if s_full is not None else float("nan")
    s_is = sharpe_from_equity_curve_csv(equity_curve, end_date_exclusive=IS_CUT)
    s_oos = sharpe_from_equity_curve_csv(equity_curve, start_date=IS_CUT)
    m_is["sharpe"] = float(s_is) if s_is is not None else float("nan")
    m_oos["sharpe"] = float(s_oos) if s_oos is not None else float("nan")


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


def compare_row(
    p: dict[str, Any],
    split_key: str,
    baseline: dict[str, Any],
    is_pick: str,
    baseline_id: str,
) -> str:
    m = p[split_key]
    c = baseline[split_key]
    arm = p["arm"]
    d_avg = m["avg_pnl"] - c["avg_pnl"]
    d_pf = m["pf"] - c["pf"]
    d_ann = m["ann_ror"] - c["ann_ror"] if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"]) else float("nan")
    d_dd = m["max_dd"] - c["max_dd"] if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"]) else float("nan")
    d_cal = m["calmar"] - c["calmar"] if math.isfinite(m["calmar"]) and math.isfinite(c["calmar"]) else float("nan")
    d_wr = m["wr"] - c["wr"]
    cls = "ctrl-row" if arm["id"] == baseline_id else ""
    pick_mark = "★ IS pick" if arm["id"] == is_pick and split_key == "m_is" else ""
    sa = p["sum_agg"] if split_key == "m_full" else {}
    eq = p["eq_meta"] if split_key == "m_full" else {}
    sharpe = m.get("sharpe", float("nan"))
    is_ctrl = arm["id"] == baseline_id
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
        f'<td data-sort-value="{d_avg if not is_ctrl else ""}">'
        f'{"—" if is_ctrl else f"{d_avg:+.2f}"}</td>'
        f'<td data-sort-value="{d_wr if not is_ctrl else ""}">'
        f'{"—" if is_ctrl else f"{d_wr:+.2f}"}</td>'
        f'<td data-sort-value="{d_pf if not is_ctrl else ""}">'
        f'{"—" if is_ctrl else f"{d_pf:+.3f}"}</td>'
        f'<td data-sort-value="{d_ann if not is_ctrl else ""}">'
        f'{"—" if is_ctrl else fmt_n(d_ann, 2)}</td>'
        f'<td data-sort-value="{d_dd if not is_ctrl else ""}">'
        f'{"—" if is_ctrl else fmt_n(d_dd, 2)}</td>'
        f'<td data-sort-value="{d_cal if not is_ctrl else ""}">'
        f'{"—" if is_ctrl else fmt_n(d_cal, 2)}</td>'
        f'<td data-sort-value="{pick_mark}">{html_mod.escape(pick_mark)}</td>'
        "</tr>"
    )


def pairwise_delta_row(
    row_a: dict[str, Any],
    row_b: dict[str, Any],
    split_key: str,
    label: str,
) -> str:
    ma, mb = row_a[split_key], row_b[split_key]
    return (
        "<tr>"
        f"<td>{html_mod.escape(label)}</td>"
        f'<td data-sort-value="{mb["n"] - ma["n"]}">{mb["n"] - ma["n"]:+d}</td>'
        f'<td data-sort-value="{mb["avg_pnl"] - ma["avg_pnl"]}">{mb["avg_pnl"] - ma["avg_pnl"]:+.2f}</td>'
        f'<td data-sort-value="{mb["wo_max"] - ma["wo_max"]}">{mb["wo_max"] - ma["wo_max"]:+.2f}</td>'
        f'<td data-sort-value="{mb["wr"] - ma["wr"]}">{mb["wr"] - ma["wr"]:+.2f}</td>'
        f'<td data-sort-value="{mb["pf"] - ma["pf"]}">{mb["pf"] - ma["pf"]:+.3f}</td>'
        f'<td data-sort-value="{mb["ann_ror"] - ma["ann_ror"] if math.isfinite(mb["ann_ror"]) and math.isfinite(ma["ann_ror"]) else float("nan")}">'
        f'{fmt_n(mb["ann_ror"] - ma["ann_ror"] if math.isfinite(mb["ann_ror"]) and math.isfinite(ma["ann_ror"]) else float("nan"), 2)}</td>'
        f'<td data-sort-value="{mb["max_dd"] - ma["max_dd"] if math.isfinite(mb["max_dd"]) and math.isfinite(ma["max_dd"]) else float("nan")}">'
        f'{fmt_n(mb["max_dd"] - ma["max_dd"] if math.isfinite(mb["max_dd"]) and math.isfinite(ma["max_dd"]) else float("nan"), 2)}</td>'
        "</tr>"
    )


def write_compare_html(
    packed: list[dict[str, Any]],
    is_pick: str,
    pick_note: str,
    oos_verdict: str,
    oos_note: str,
    dropped: list[str],
    overlap: dict[str, list[str]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> Path:
    by_id = {p["arm"]["id"]: p for p in packed}
    baseline = by_id[CONTROL_ID]
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
            ("Δ Sheet $ vs 59", "num"),
            ("Δ Avg% vs 59", "num"),
            ("Δ WR vs 59", "num"),
            ("Δ PF vs 59", "num"),
            ("Δ Ann ROR vs 59", "num"),
            ("Δ Max DD vs 59", "num"),
            ("Δ Calmar vs 59", "num"),
            ("IS pick", "text"),
        ]
    )
    th = "".join(sortable_th(a, b) for a, b in th_cols)
    sections = []
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS (report-only)"), ("m_full", "FULL book")):
        body = "".join(
            compare_row(p, split_key, baseline, is_pick, CONTROL_ID) for p in packed
        )
        note = (
            "Paul/FIT/UW from host Summary + EquityMeta. Sharpe from host EquityCurve "
            "(Equity_Regular when present; IS/OOS = calendar slices)."
            if split_key == "m_full"
            else "Closed overlay at $47,500 cash / $500k initial. Sharpe from host EquityCurve "
            "calendar slice. Paul/FIT N/A on slices."
        )
        sections.append(
            f'<section><h2>RL universe compare — {title}</h2>'
            f'<p class="muted">Split=<strong>{title.split()[0]}</strong>. Δ vs house 59 control. {note} '
            f"Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>'
            f"<tbody>{body}</tbody></table></div></section>"
        )

    pw_th = "".join(
        sortable_th(a, b)
        for a, b in filter_html_compare_columns(
            [
                ("Pair (B − A)", "text"),
                ("Δ Trades", "num"),
                ("Δ Avg%", "num"),
                ("Δ WO_MAX", "num"),
                ("Δ WR", "num"),
                ("Δ PF", "num"),
                ("Δ Sheet $", "num"),
                ("Δ Ann ROR", "num"),
                ("Δ Max DD", "num"),
            ]
        )
    )
    pw_sections = []
    pairs = [
        ("list2 − list1", by_id["list1"], by_id["list2"]),
        ("list1 − house59", by_id[CONTROL_ID], by_id["list1"]),
        ("list2 − house59", by_id[CONTROL_ID], by_id["list2"]),
    ]
    for split_key, title in (("m_is", "IS"), ("m_oos", "OOS"), ("m_full", "FULL")):
        rows = "".join(pairwise_delta_row(a, b, split_key, lbl) for lbl, a, b in pairs)
        pw_sections.append(
            f'<section><h2>Pairwise deltas — {title}</h2>'
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{pw_th}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>"
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

    verdict_lines = []
    for aid in ("list1", "list2"):
        v_is, n_is = verdicts[aid]["is"]
        v_oos, n_oos = verdicts[aid]["oos"]
        verdict_lines.append(
            f"<li><strong>{aid}</strong> vs house59 — IS: {html_mod.escape(v_is)} ({html_mod.escape(n_is)}); "
            f"OOS: {html_mod.escape(v_oos)} ({html_mod.escape(n_oos)})</li>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL list1 vs list2 vs 59 — {STAMP}</title>
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
<h1>RL universe compare — List1 (95) vs List2 (93) vs House 59</h1>
<p class="muted">Stamp <code>rl_univ_compare_list1_list2_{STAMP}</code>. Universe compare (not stop/knob AB).
House freeze: dip=1.055, expansion=1.163, rl_stop_pct=0.934, target=1.20, too_high=off, brt_zones=false, cash $47.5k.
IS = entry &lt; 2024-01-01 (pick); OOS ≥ 2024-01-01 report-only. Research-only — not gold / not DailyRun.
Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>IS pick:</strong> {html_mod.escape(is_pick)} — {html_mod.escape(pick_note)}<br/>
<strong>OOS validation:</strong> {html_mod.escape(oos_verdict)} — {html_mod.escape(oos_note)}<br/>
<strong>Dropped (List1−List2):</strong> {html_mod.escape(", ".join(dropped))}<br/>
<strong>Overlap List1∩House59:</strong> {len(overlap['list1_house'])} names — {html_mod.escape(", ".join(overlap['list1_house']))}<br/>
<strong>House59 only (not in List1):</strong> {html_mod.escape(", ".join(overlap['house_only']))}<br/>
<strong>List1 only (not in House59):</strong> {len(overlap['list1_only'])} names<br/>
<ul>{"".join(verdict_lines)}</ul>
</div>
{"".join(sections)}
{"".join(pw_sections)}
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


def write_baseline(
    packed: list[dict[str, Any]],
    missing: list[str],
    dropped: list[str],
    overlap: dict[str, list[str]],
) -> None:
    lines = [
        f"# BASELINE — `rl_univ_compare_list1_list2_{STAMP}`",
        "",
        "**Universe compare** (not a stop/knob AB). Research candidate ≠ gold ≠ DailyRun.",
        "",
        "## House RL freeze (identical all arms)",
        "",
        "| Knob | Value | Source |",
        "|------|-------|--------|",
        "| `rl_dip_pct` | **1.055** | `run_rl.bat` / Paul override |",
        "| `rl_expansion` | **1.163** | `RLConfig` / rl.html |",
        "| `rl_stop_pct` | **0.934** | `RLConfig` / rl.html |",
        "| `rl_target_pct` | **1.20** | `RLConfig` |",
        "| `rl_too_high` | **0 / off** | `run_rl.bat` |",
        "| `brt_zones` | **false** | `run_rl.bat` |",
        "| cash | **$47,500** | house RL |",
        "",
        "Do **not** retune knobs on this stamp.",
        "",
        "## Universes",
        "",
        f"- **List1** (`list1.csv`): {len(LIST1)} names",
        f"- **List2** (`list2.csv`): {len(LIST2)} names",
        f"- **House59** (`rl_universe_59.csv`): copy of `drive/universes/RL_universe.csv`",
        f"- **Dropped (List1−List2):** {', '.join(dropped)}",
        f"- **List1∩House59:** {len(overlap['list1_house'])} — {', '.join(overlap['list1_house'])}",
        f"- **House59 only:** {', '.join(overlap['house_only'])}",
        f"- **List1 only:** {len(overlap['list1_only'])} — {', '.join(overlap['list1_only'])}",
        "",
        "## IS pick rule",
        "",
        "- Split: IS = `entry_date < 2024-01-01`; OOS = `entry_date >= 2024-01-01`",
        "- Pick on **IS quality** — **quality over N**",
        "- OOS is **report-only** — do not change pick; if OOS softens → HOLD",
        "",
        "## Missing OHLC",
        "",
        f"- {', '.join(missing) if missing else 'None — all List1 symbols present under data/newdata/data/'}",
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
            "- `list1.csv` / `list2.csv` / `rl_universe_59.csv`",
            "- `compare.html` — sortable IS / OOS / FULL + pairwise",
            "- `why.html` — Closed composition (shared vs List2-only vs house-only)",
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
    oos_verdict: str,
    oos_note: str,
    dropped: list[str],
    overlap: dict[str, list[str]],
    verdicts: dict[str, dict[str, tuple[str, str]]],
) -> None:
    by_id = {p["arm"]["id"]: p for p in packed}
    lines = [
        f"# SUMMARY — `rl_univ_compare_list1_list2_{STAMP}`",
        "",
        "**Universe compare.** Research only. Not gold / not DailyRun.",
        "",
        "## Freeze",
        "",
        "`rl_dip_pct=1.055`, `rl_expansion=1.163`, `rl_stop_pct=0.934`, `rl_target_pct=1.20`, "
        "`rl_too_high=0`, `brt_zones=false`, cash $47.5k.",
        "",
        f"**Dropped (List1−List2):** {', '.join(dropped)}",
        f"**List1∩House59:** {len(overlap['list1_house'])} names",
        f"**House59 only:** {', '.join(overlap['house_only'])}",
        f"**List1 only:** {len(overlap['list1_only'])} names",
        "",
        "## IS pick (entry < 2024-01-01)",
        "",
        f"**Pick: `{is_pick}`** — {pick_note}",
        "",
        "| Arm | N | WR% | Avg% | WO_MAX | PF | Ann ROR | Max DD | Calmar |",
        "|-----|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for aid in ("list1", "list2", CONTROL_ID):
        p = by_id[aid]
        m = p["m_is"]
        mark = " ← IS pick" if aid == is_pick else ""
        lines.append(
            f"| {p['arm']['label']}{mark} | {m['n']} | {m['wr']:.1f} | {m['avg_pnl']:.2f} | "
            f"{m['wo_max']:.2f} | {m['pf']:.2f} | "
            f"{fmt_n(m['ann_ror'], 1)} | {fmt_n(m['max_dd'], 2)} | {fmt_n(m['calmar'], 2)} |"
        )
    lines.extend(["", "## OOS validation (report-only)", "", f"**Verdict: {oos_verdict}** — {oos_note}", ""])
    for aid in ("list1", "list2", CONTROL_ID):
        p = by_id[aid]
        m = p["m_oos"]
        lines.append(
            f"- **{p['arm']['label']}**: N={m['n']}, WR={m['wr']:.1f}%, Avg%={m['avg_pnl']:.2f}, "
            f"WO_MAX={m['wo_max']:.2f}, PF={m['pf']:.2f}, "
            f"Ann ROR={fmt_n(m['ann_ror'], 1)}, Max DD={fmt_n(m['max_dd'], 2)}, "
            f"Calmar={fmt_n(m['calmar'], 2)}"
        )
    lines.extend(["", "## vs House59 (control)", ""])
    for aid in ("list1", "list2"):
        v_is, n_is = verdicts[aid]["is"]
        v_oos, n_oos = verdicts[aid]["oos"]
        lines.append(f"- **`{aid}`** IS: **{v_is}** — {n_is}")
        lines.append(f"- **`{aid}`** OOS: **{v_oos}** — {n_oos}")
    adopt = "HOLD house59"
    if is_pick != CONTROL_ID:
        v_is = verdicts[is_pick]["is"][0]
        if v_is in ("LEAN KEEP", "KEEP") and oos_verdict in ("LEAN KEEP", "KEEP"):
            adopt = f"Research candidate `{is_pick}` — still not DailyRun/gold"
        elif v_is == "DISMISS":
            adopt = "HOLD house59 — candidate DISMISS vs control on IS"
    lines.extend(
        [
            "",
            "## FULL book",
            "",
        ]
    )
    for aid in ("list1", "list2", CONTROL_ID):
        p = by_id[aid]
        m = p["m_full"]
        sa = p["sum_agg"]
        eq = p["eq_meta"]
        lines.append(
            f"- **{p['arm']['label']}**: N={m['n']}, WR={m['wr']:.1f}%, Avg%={m['avg_pnl']:.2f}, "
            f"PF={m['pf']:.2f}, Ann ROR={fmt_n(m['ann_ror'], 1)}, "
            f"Max DD overlay={fmt_n(m['max_dd'], 2)}, Calmar={fmt_n(m['calmar'], 2)}, "
            f"Sharpe={fmt_n(eq.get('sharpe'), 2)}, mean Paul={fmt_n(sa.get('mean_paul'), 2)}, "
            f"mean FIT={fmt_n(sa.get('mean_fit'), 2)}, mean robust={fmt_n(sa.get('mean_robust'), 2)}"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- IS pick frozen: **`{is_pick}`**",
            f"- After OOS: **{oos_verdict}**",
            f"- vs existing 59: **{adopt}**",
            "- Do not retune knobs or re-pick from OOS",
        ]
    )
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _slice_metric_row(label: str, n_names: int, m: dict[str, Any], highlight: str = "") -> str:
    tot = max(m["n"], 1)
    tgt = 100.0 * m["exits"].get("TARGET", 0) / tot if m["n"] else 0.0
    stp = 100.0 * m["exits"].get("STOP_LOSS", 0) / tot if m["n"] else 0.0
    cls = f' class="{highlight}"' if highlight else ""
    return (
        f"<tr{cls}>"
        f"<td>{html_mod.escape(label)}</td>"
        f'<td data-sort-value="{n_names}">{n_names}</td>'
        f'<td data-sort-value="{m["n"]}">{m["n"]}</td>'
        f'<td data-sort-value="{m["wr"]}">{fmt_n(m["wr"], 1)}</td>'
        f'<td data-sort-value="{m["avg_pnl"]}">{fmt_n(m["avg_pnl"], 2)}</td>'
        f'<td data-sort-value="{m["wo_max"]}">{fmt_n(m["wo_max"], 2)}</td>'
        f'<td data-sort-value="{m["avg_win"]}">{fmt_n(m["avg_win"], 2)}</td>'
        f'<td data-sort-value="{m["avg_loss"]}">{fmt_n(m["avg_loss"], 2)}</td>'
        f'<td data-sort-value="{m["pf"]}">{fmt_n(m["pf"], 2)}</td>'
        f'<td data-sort-value="{m["ann_ror"]}">{fmt_n(m["ann_ror"], 1)}</td>'
        f'<td data-sort-value="{m["max_dd"]}">{fmt_n(m["max_dd"], 2)}</td>'
        f'<td data-sort-value="{m["calmar"]}">{fmt_n(m["calmar"], 2)}</td>'
        f'<td data-sort-value="{m["exp_d"]}">{format_money(m["exp_d"])}</td>'
        f'<td data-sort-value="{m["avg_days"]}">{fmt_n(m["avg_days"], 1)}</td>'
        f'<td data-sort-value="{m["cap_days"]}">{fmt_n(m["cap_days"], 0)}</td>'
        f'<td data-sort-value="{m["ppc"]}">{format_money(m["ppc"]) if math.isfinite(m["ppc"]) else "—"}</td>'
        f'<td data-sort-value="{m["lose_streak"]}">{m["lose_streak"]}</td>'
        f'<td data-sort-value="{m["tpy"]}">{fmt_n(m["tpy"], 1)}</td>'
        f'<td data-sort-value="{tgt}">{fmt_n(tgt, 1)}</td>'
        f'<td data-sort-value="{stp}">{fmt_n(stp, 1)}</td>'
        "</tr>"
    )


def _sym_rows(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        by.setdefault(t["sym"], []).append(t)
    out: list[dict[str, Any]] = []
    for sym, ts in by.items():
        is_t, oos_t = split_is_oos(ts)
        mo = book_stats(oos_t)
        mi = book_stats(is_t)
        mf = book_stats(ts)
        oos_wins = [t["pnl"] for t in oos_t]
        max_win = max(oos_wins) if oos_wins else 0.0
        gains = [t["max_gain"] * 100.0 for t in oos_t if t.get("max_gain") is not None]
        hh = [t["hist_high"] * 100.0 for t in oos_t if t.get("hist_high")]
        out.append(
            {
                "sym": sym,
                "n_full": mf["n"],
                "n_is": mi["n"],
                "n_oos": mo["n"],
                "is_avg": mi["avg_pnl"],
                "is_wr": mi["wr"],
                "oos_avg": mo["avg_pnl"],
                "oos_wo": mo["wo_max"],
                "oos_wr": mo["wr"],
                "oos_pf": mo["pf"],
                "oos_days": mo["avg_days"],
                "oos_max_win": max_win,
                "oos_avg_mfe": (sum(gains) / len(gains)) if gains else 0.0,
                "oos_avg_hh": (sum(hh) / len(hh)) if hh else 0.0,
                "oos_tgt": 100.0 * mo["exits"].get("TARGET", 0) / max(mo["n"], 1) if mo["n"] else 0.0,
                "oos_stp": 100.0 * mo["exits"].get("STOP_LOSS", 0) / max(mo["n"], 1) if mo["n"] else 0.0,
            }
        )
    out.sort(key=lambda r: (r["oos_avg"] if r["n_oos"] else 9e9, -r["n_oos"]))
    return out


def _sym_table(rows: list[dict[str, Any]], caption: str) -> str:
    th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Symbol", "text"),
            ("OOS N", "num"),
            ("OOS WR%", "num"),
            ("OOS Avg%", "num"),
            ("OOS WO_MAX", "num"),
            ("OOS PF", "num"),
            ("OOS avg days", "num"),
            ("OOS max win%", "num"),
            ("OOS avg MFE%", "num"),
            ("OOS avg hist-high%", "num"),
            ("OOS TARGET%", "num"),
            ("OOS STOP%", "num"),
            ("IS N", "num"),
            ("IS WR%", "num"),
            ("IS Avg%", "num"),
            ("Full N", "num"),
        ]
    )
    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['sym'])}</td>"
            f'<td data-sort-value="{r["n_oos"]}">{r["n_oos"]}</td>'
            f'<td data-sort-value="{r["oos_wr"]}">{fmt_n(r["oos_wr"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_avg"]}">{fmt_n(r["oos_avg"], 2) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_wo"]}">{fmt_n(r["oos_wo"], 2) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_pf"]}">{fmt_n(r["oos_pf"], 2) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_days"]}">{fmt_n(r["oos_days"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_max_win"]}">{fmt_n(r["oos_max_win"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_avg_mfe"]}">{fmt_n(r["oos_avg_mfe"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_avg_hh"]}">{fmt_n(r["oos_avg_hh"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_tgt"]}">{fmt_n(r["oos_tgt"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["oos_stp"]}">{fmt_n(r["oos_stp"], 1) if r["n_oos"] else "—"}</td>'
            f'<td data-sort-value="{r["n_is"]}">{r["n_is"]}</td>'
            f'<td data-sort-value="{r["is_wr"]}">{fmt_n(r["is_wr"], 1) if r["n_is"] else "—"}</td>'
            f'<td data-sort-value="{r["is_avg"]}">{fmt_n(r["is_avg"], 2) if r["n_is"] else "—"}</td>'
            f'<td data-sort-value="{r["n_full"]}">{r["n_full"]}</td>'
            "</tr>"
        )
    return (
        f"<section><h2>{html_mod.escape(caption)}</h2>"
        '<p class="muted">Click column headers to sort. Default order: worst OOS Avg% first. '
        "MFE = Closed MAX GAIN. Hist-high = HIST_HIGH_PCT at entry (how extended vs history).</p>"
        f'<div class="table-wrap"><table class="sortable"><caption>Click column headers to sort</caption>'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table></div></section>"
    )


def write_why_html(
    list2_trades: list[dict[str, Any]],
    house_trades: list[dict[str, Any]],
    overlap: dict[str, list[str]],
) -> Path:
    shared = set(overlap["list2_house"])
    l2_only = set(overlap["list2_only"])
    h_only = set(overlap["house_only"])

    slices = [
        ("List2 shared (∩ house 39)", shared, [t for t in list2_trades if t["sym"] in shared], ""),
        ("List2 only (54 new names)", l2_only, [t for t in list2_trades if t["sym"] in l2_only], ""),
        ("House shared (same 39)", shared, [t for t in house_trades if t["sym"] in shared], ""),
        ("House only (20 dropped by List2)", h_only, [t for t in house_trades if t["sym"] in h_only], "ctrl-row"),
        ("List2 full (93)", set(overlap["list2_house"]) | set(overlap["list2_only"]), list2_trades, ""),
        ("House full (59)", set(overlap["list2_house"]) | set(overlap["house_only"]), house_trades, "ctrl-row"),
    ]

    slice_th = "".join(
        sortable_th(a, b)
        for a, b in [
            ("Slice", "text"),
            ("Names", "num"),
            ("Trades", "num"),
            ("WR%", "num"),
            ("Avg PnL%", "num"),
            ("Avg% w/o max", "num"),
            ("Avg win%", "num"),
            ("Avg loss%", "num"),
            ("PF", "num"),
            ("Ann ROR%", "num"),
            ("Max DD%", "num"),
            ("Calmar", "num"),
            ("Expect $", "num"),
            ("Avg days", "num"),
            ("Cap days", "num"),
            ("PPCD", "num"),
            ("Lose streak", "num"),
            ("Trades/yr", "num"),
            ("TARGET%", "num"),
            ("STOP%", "num"),
        ]
    )
    slice_sections = []
    slice_stats: dict[str, dict[str, Any]] = {}
    for split_key, title in (("is", "IS"), ("oos", "OOS (report-only)"), ("full", "FULL")):
        rows = []
        for label, names, trades, hl in slices:
            is_t, oos_t = split_is_oos(trades)
            book = {"is": is_t, "oos": oos_t, "full": trades}[split_key]
            m = book_stats(book)
            slice_stats[f"{label}|{split_key}"] = m
            rows.append(_slice_metric_row(label, len(names), m, hl))
        slice_sections.append(
            f"<section><h2>Composition overlay — {title}</h2>"
            '<p class="muted">Closed overlay at $47,500 / $500k. Same freeze knobs. '
            "Click column headers to sort.</p>"
            f'<div class="table-wrap"><table class="sortable"><thead><tr>{slice_th}</tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table></div></section>"
        )

    l2o_oos = book_stats([t for t in list2_trades if t["sym"] in l2_only and t["opened"] >= IS_CUT])
    h_o_oos = book_stats([t for t in house_trades if t["sym"] in h_only and t["opened"] >= IS_CUT])
    sh_oos = book_stats([t for t in list2_trades if t["sym"] in shared and t["opened"] >= IS_CUT])
    h_full_oos = book_stats([t for t in house_trades if t["opened"] >= IS_CUT])
    l2_full_oos = book_stats([t for t in list2_trades if t["opened"] >= IS_CUT])

    why_bits = []
    why_bits.append(
        f"OOS trade counts are almost identical (List2 {l2_full_oos['n']} vs house {h_full_oos['n']}). "
        "List2 did not ‘take more OOS trades’ — it swapped names."
    )
    why_bits.append(
        f"List2-only OOS: N={l2o_oos['n']}, WR={l2o_oos['wr']:.1f}%, Avg%={l2o_oos['avg_pnl']:.2f}, "
        f"PF={l2o_oos['pf']:.2f}."
    )
    why_bits.append(
        f"House-only OOS (the 20 List2 dropped): N={h_o_oos['n']}, WR={h_o_oos['wr']:.1f}%, "
        f"Avg%={h_o_oos['avg_pnl']:.2f}, PF={h_o_oos['pf']:.2f}."
    )
    why_bits.append(
        f"Shared 39 OOS (from List2 Closed): N={sh_oos['n']}, WR={sh_oos['wr']:.1f}%, "
        f"Avg%={sh_oos['avg_pnl']:.2f}, PF={sh_oos['pf']:.2f}."
    )
    if l2o_oos["avg_pnl"] + 1.0 < sh_oos["avg_pnl"] and h_o_oos["avg_pnl"] > sh_oos["avg_pnl"]:
        why_bits.append(
            "Conclusion: OOS collapse is the 54 new names, while the 20 house-only names carried "
            "house OOS quality. This is a universe composition miss — not an RL knob miss."
        )
    elif l2o_oos["avg_pnl"] + 1.0 < sh_oos["avg_pnl"]:
        why_bits.append(
            "Conclusion: OOS damage is concentrated in List2-only names. Do not retune dip/expansion/stops."
        )
    else:
        why_bits.append(
            "Conclusion: check whether shared names also softened; if they did, it is not only the new names."
        )
    why_bits.append(
        "House OOS looking this strong is still partly because the 59 were chosen on the full sheet "
        "(including 2024+). Do not treat house OOS as a clean holdout. Still: do not adopt List2."
    )

    l2_only_sym = _sym_rows([t for t in list2_trades if t["sym"] in l2_only])
    h_only_sym = _sym_rows([t for t in house_trades if t["sym"] in h_only])
    shared_sym = _sym_rows([t for t in list2_trades if t["sym"] in shared])
    worst = [r for r in l2_only_sym if r["n_oos"] > 0][:15]
    worst_names = ", ".join(r["sym"] for r in worst[:8]) if worst else "(none)"

    md = [
        f"# WHY — `rl_univ_compare_list1_list2_{STAMP}`",
        "",
        "Closed overlay (no new engine run). OOS report-only. Do not retune.",
        "",
        "## Finding",
        "",
        *[f"- {b}" for b in why_bits],
        "",
        f"Worst List2-only OOS Avg% names (top of table): {worst_names}",
        "",
        "## Verdict",
        "",
        "- **Do not adopt List2** (or List1) as house universe.",
        "- Keep house 59. Keep freeze dip=1.055 on that universe.",
        "- Next work is not another universe cut. Optional ToS only on the worst incremental names.",
        "",
        f"See `why.html`.",
        "",
    ]
    (OUT_DIR / "WHY.md").write_text("\n".join(md), encoding="utf-8")

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RL List2 OOS why — {STAMP}</title>
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
caption{{text-align:left;font-size:0.82rem;color:var(--muted);margin:0 0 6px;caption-side:top}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
@media (max-width:700px){{ table{{font-size:.72rem;min-width:900px}} }}
</style>
</head>
<body>
<header>
<h1>Why List2 OOS broke — composition vs house 59</h1>
<p class="muted">Stamp <code>rl_univ_compare_list1_list2_{STAMP}</code>. Overlay of existing Closed
(<code>runs/list2</code> vs <code>runs/house59</code>). Same freeze (dip=1.055). Not a new run.
IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>Adoption:</strong> do not replace house 59 with List2 (or List1).<br/>
{"<br/>".join(html_mod.escape(b) for b in why_bits)}<br/>
<strong>Worst List2-only OOS names:</strong> {html_mod.escape(worst_names)}
</div>
<p class="muted"><a href="compare.html">Back to compare.html</a> · House-only names:
{html_mod.escape(", ".join(sorted(h_only)))}</p>
{"".join(slice_sections)}
{_sym_table(l2_only_sym, "Per-symbol OOS — List2 only (54 names)")}
{_sym_table(h_only_sym, "Per-symbol OOS — House only (20 names List2 dropped)")}
{_sym_table(shared_sym, "Per-symbol OOS — Shared 39")}
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path = OUT_DIR / "why.html"
    path.write_text(html, encoding="utf-8")
    return path


def summarize(
    packed: list[dict[str, Any]],
    missing: list[str],
    dropped: list[str],
    overlap: dict[str, list[str]],
) -> dict[str, Any]:
    by_id = {p["arm"]["id"]: p for p in packed}
    control = by_id[CONTROL_ID]
    is_pick, pick_note = pick_is_winner(packed)
    oos_verdict, oos_note = oos_supports(is_pick, packed)
    verdicts: dict[str, dict[str, tuple[str, str]]] = {}
    for aid in ("list1", "list2"):
        verdicts[aid] = {
            "is": verdict_vs_control(by_id[aid], control, "m_is"),
            "oos": verdict_vs_control(by_id[aid], control, "m_oos"),
        }
    write_compare_html(packed, is_pick, pick_note, oos_verdict, oos_note, dropped, overlap, verdicts)
    write_metrics_csv(packed, is_pick, OUT_DIR / "metrics_all.csv")
    write_baseline(packed, missing, dropped, overlap)
    write_summary(packed, is_pick, pick_note, oos_verdict, oos_note, dropped, overlap, verdicts)
    by_id = {p["arm"]["id"]: p for p in packed}
    if "list2" in by_id and CONTROL_ID in by_id:
        why = write_why_html(by_id["list2"]["trades"], by_id[CONTROL_ID]["trades"], overlap)
        print(f"[RL-LISTS] Wrote {why}", flush=True)
    print(f"[RL-LISTS] Wrote {OUT_DIR / 'compare.html'}", flush=True)
    print(f"[RL-LISTS] IS pick={is_pick} | oos={oos_verdict}", flush=True)
    return {
        "is_pick": is_pick,
        "pick_note": pick_note,
        "oos_verdict": oos_verdict,
        "oos_note": oos_note,
        "verdicts": verdicts,
        "packed": packed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--why-only", action="store_true", help="Closed composition why.html from existing runs")
    parser.add_argument("--skip-existing", action="store_true", default=False)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    skip_existing = (args.skip_existing or args.summarize_only or args.why_only) and not args.force

    house = load_house_univ()
    if not house:
        print("[RL-LISTS] Missing house universe", flush=True)
        return 1
    arms = build_arms(house)
    missing, dropped, overlap = write_univ_csvs(house)
    print(f"[RL-LISTS] Stamp {OUT_DIR}", flush=True)
    print(
        f"[RL-LISTS] L1={len(LIST1)} L2={len(LIST2)} house={len(house)} "
        f"dropped={dropped} overlap={len(overlap['list1_house'])} missing_ohlc={missing}",
        flush=True,
    )

    py = _resolve_python()
    if args.why_only:
        l2_closed = _find_latest(OUT_DIR / "runs" / "list2", "RL_Closed_*.csv")
        h_closed = _find_latest(OUT_DIR / "runs" / CONTROL_ID, "RL_Closed_*.csv")
        if not l2_closed or not h_closed:
            print("[RL-LISTS] Missing Closed for why-only (need runs/list2 and runs/house59)", flush=True)
            return 1
        why = write_why_html(load_trades(l2_closed), load_trades(h_closed), overlap)
        print(f"[RL-LISTS] Wrote {why}", flush=True)
        ntfy = ROOT / "tools" / "ntfy_job_done.py"
        if ntfy.is_file():
            subprocess.run(
                [
                    py,
                    str(ntfy),
                    "--path",
                    str(why),
                    "-t",
                    "RL List2 OOS why pack",
                    "-m",
                    "Composition overlay: shared vs List2-only vs house-only",
                ],
                cwd=str(ROOT),
            )
        return 0

    runs: list[dict[str, Any]] = []
    if args.summarize_only:
        for arm in arms:
            arm_dir = OUT_DIR / "runs" / arm["id"]
            closed = _find_latest(arm_dir, "RL_Closed_*.csv")
            if not closed:
                print(f"[RL-LISTS] Missing Closed for {arm['id']}", flush=True)
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
            futs = {ex.submit(run_arm, py, arm, args.workers, skip_existing): arm for arm in arms}
            for fut in as_completed(futs):
                arm = futs[fut]
                run = fut.result()
                print(
                    f"[RL-LISTS] {arm['id']} ok={run['ok']} n={len(run['trades'])} "
                    f"elapsed={run.get('elapsed_s', 0):.0f}s skipped={run.get('skipped')}",
                    flush=True,
                )
                runs.append(run)

    order = {"list1": 0, "list2": 1, CONTROL_ID: 2}
    runs.sort(key=lambda r: order.get(r["arm"]["id"], 99))
    if not all(r.get("ok") for r in runs):
        print("[RL-LISTS] One or more arms failed", flush=True)
        for r in runs:
            print(f"  {r['arm']['id']}: ok={r.get('ok')} exit={r.get('exit_code')}", flush=True)
        if not any(r.get("trades") for r in runs):
            return 1

    packed = [pack_result(r) for r in runs]
    result = summarize(packed, missing, dropped, overlap)

    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [
                py,
                str(ntfy),
                "--path",
                str(OUT_DIR / "compare.html"),
                "--path",
                str(OUT_DIR / "why.html"),
                "-t",
                "RL univ list1 vs list2 vs 59",
                "-m",
                f"IS pick={result['is_pick']} oos={result['oos_verdict']}",
            ],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
