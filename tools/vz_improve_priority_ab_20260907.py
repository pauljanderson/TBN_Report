#!/usr/bin/env python3
"""VZ ImprovePriority one-knob ABs — Paul78.142 house adopt 20260907.

Control = current house freeze ``run_vz.bat`` / ``EXIT_atr4_s05_r15_ts20``
(stop 0.5, target 1.5, exit_bars 20, cd=10) on the Paul78.142 Closed book.

Do **not** reuse ``tools/vz_improve_priority_ab_20260906.py`` (that file still
has old s025 / ts40 control knobs).

Exit / cooldown-tighten / SPY filter: Closed overlay.
Cooldown 0 / eps / min_touches: isolated live ``run_vz.bat -o`` (no house pin).

Research only — not gold / not DailyRun. Do not adopt winners into DailyRun.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import format_money, overlay_ann_ror_max_dd  # noqa: E402
from vol_zone_break_retest import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    load_ohlcv,
    sortable_th,
)

DEFAULT_OUT = REPO / "drive" / "paul_experiments" / "vz_paul78_142_improve_ab_20260907"
DATA_DIR = REPO / "data" / "newdata" / "data"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = 500_000.0

# Current house freeze (2026-09-07) — do not copy 20260906 s025/ts40.
CTRL_STOP_ATR = 0.5
CTRL_TARGET_R = 1.5
CTRL_EXIT_BARS = 20
CTRL_CD_DAYS = 10

ORIGINAL_REQUEST = (
    "cool. I can't remember how the 56 was chosen, and I'm wondering if it was "
    "picked after looking at full results. so i think we should pick one of these "
    "new ones and I'm leaning toward the Paul78.142. the numbers still look great "
    "and the aggressive MaxDD is only 20. can we pick this and then run it through "
    "and then run post_run_analysis and then wire in a bunch of AB tests and run them?"
)


@dataclass(frozen=True)
class ExitArm:
    name: str
    label: str
    hypothesis: str
    stop_atr: float
    target_r: float
    exit_bars: int
    trail_be_r: Optional[float] = None


EXIT_ARMS: list[ExitArm] = [
    ExitArm(
        "EXIT_stop_atr025",
        "stop_atr_buffer 0.50→0.25 (tighter)",
        "fat_stops + stop_pct_tension contract lens",
        stop_atr=0.25,
        target_r=CTRL_TARGET_R,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_stop_atr075",
        "stop_atr_buffer 0.50→0.75 (wider)",
        "stop_pct_tension_expand (lean expand)",
        stop_atr=0.75,
        target_r=CTRL_TARGET_R,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_target_r10",
        "target_r 1.5→1.0 (contract)",
        "target_pct_tension_contract lens",
        stop_atr=CTRL_STOP_ATR,
        target_r=1.0,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_target_r20",
        "target_r 1.5→2.0 (expand)",
        "small_target_wins + target_pct_tension_expand",
        stop_atr=CTRL_STOP_ATR,
        target_r=2.0,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_ts10",
        "exit_bars 20→10 (cut losers faster)",
        "fat_stops (time-stop lever)",
        stop_atr=CTRL_STOP_ATR,
        target_r=CTRL_TARGET_R,
        exit_bars=10,
    ),
    ExitArm(
        "EXIT_ts40",
        "exit_bars 20→40 (hold longer)",
        "winner_peak_giveback / hold-through TIME giveback",
        stop_atr=CTRL_STOP_ATR,
        target_r=CTRL_TARGET_R,
        exit_bars=40,
    ),
    ExitArm(
        "EXIT_trail_be1r",
        "trail: raise stop to breakeven after +1R MFE",
        "winner_peak_giveback",
        stop_atr=CTRL_STOP_ATR,
        target_r=CTRL_TARGET_R,
        exit_bars=CTRL_EXIT_BARS,
        trail_be_r=1.0,
    ),
]


def _f(v: Any, default: float = float("nan")) -> float:
    if v is None or v == "":
        return default
    s = str(v).strip().replace("%", "").replace(",", "").replace("$", "")
    if not s or s.upper() in {"N/A", "NONE"}:
        return default
    try:
        return float(s)
    except ValueError:
        return default


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


def _exit_type_norm(raw: str) -> str:
    s = str(raw or "").strip().upper().replace(" ", "_")
    if s in {"STOP", "STOP_LOSS"}:
        return "STOP"
    if s in {"TARGET", "TIME", "GAP_UP", "GAP_DOWN", "TRAIL_BE"}:
        return s
    if "STOP" in s:
        return "STOP"
    if "TARGET" in s:
        return "TARGET"
    if "TIME" in s:
        return "TIME"
    return s or "OTHER"


def read_house_stamp(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()


def load_house_closed(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            opened = _parse_d(raw.get("DATE_OPENED"))
            closed = _parse_d(raw.get("DATE_CLOSED"))
            if opened is None or closed is None:
                continue
            sym = str(raw.get("SYMBOL", "")).strip().upper()
            entry = _f(raw.get("ENTRY_PRICE"))
            zone_lo = _f(raw.get("ZONE_LO"))
            atr = _f(raw.get("ATR_14_AT_ENTRY"))
            if not sym or not math.isfinite(entry) or entry <= 0:
                continue
            if not math.isfinite(zone_lo) or not math.isfinite(atr) or atr <= 0:
                continue
            pnl = _f(raw.get("PNL_PCT"), 0.0)
            pnl_d = _f(raw.get("PNL_DOLLARS"), pnl / 100.0 * SHEET)
            days = _f(raw.get("DAYS_HELD"), float((closed - opened).days))
            rows.append(
                {
                    "symbol": sym,
                    "opened": opened,
                    "closed": closed,
                    "entry": entry,
                    "zone_lo": zone_lo,
                    "atr": atr,
                    "pnl": pnl,
                    "pnl_d": pnl_d,
                    "days": max(1.0, days if math.isfinite(days) and days > 0 else 1.0),
                    "exit_type": _exit_type_norm(str(raw.get("EXIT_TYPE", ""))),
                    "stop_house": _f(raw.get("STOP_PRICE")),
                    "target_house": _f(raw.get("TARGET_PRICE")),
                    "r_mult": _f(raw.get("R_MULT"), 0.0),
                }
            )
    return rows


_OHLC_CACHE: dict[str, pd.DataFrame] = {}


def get_ohlc(sym: str) -> Optional[pd.DataFrame]:
    if sym in _OHLC_CACHE:
        return _OHLC_CACHE[sym]
    path = DATA_DIR / f"{sym}.csv"
    if not path.exists():
        return None
    df = load_ohlcv(path)
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    _OHLC_CACHE[sym] = df
    return df


def replay_exit(
    df: pd.DataFrame,
    *,
    entry_date: date,
    entry: float,
    stop: float,
    target: float,
    exit_bars: int,
    trail_be_r: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    dates = df["Date"].dt.date.to_numpy()
    idxs = np.where(dates == entry_date)[0]
    if len(idxs) == 0:
        prior = np.where(dates <= entry_date)[0]
        if len(prior) == 0:
            return None
        ei = int(prior[-1])
    else:
        ei = int(idxs[0])
    highs = df["High"].to_numpy(dtype=np.float64)
    lows = df["Low"].to_numpy(dtype=np.float64)
    closes = df["Close"].to_numpy(dtype=np.float64)
    last_i = len(df) - 1
    time_i = ei + int(exit_bars)
    end = min(last_i, time_i)
    stop_px = float(stop)
    risk = max(entry - stop_px, entry * 0.005)
    activated = False
    for i in range(ei + 1, end + 1):
        if trail_be_r is not None and not activated:
            mfe = float(highs[i]) - entry
            if mfe >= float(trail_be_r) * risk:
                activated = True
                stop_px = max(stop_px, entry)
        if float(lows[i]) <= stop_px:
            pnl = (stop_px - entry) / entry * 100.0
            et = "TRAIL_BE" if activated and abs(stop_px - entry) < 1e-9 else "STOP"
            return {
                "pnl": pnl,
                "days": float(i - ei),
                "closed": dates[i],
                "exit_type": et,
                "exit_price": stop_px,
                "r_mult": (stop_px - entry) / risk,
            }
        if float(highs[i]) >= target:
            pnl = (target - entry) / entry * 100.0
            return {
                "pnl": pnl,
                "days": float(i - ei),
                "closed": dates[i],
                "exit_type": "TARGET",
                "exit_price": target,
                "r_mult": (target - entry) / risk,
            }
    bars = float(end - ei)
    pnl = (float(closes[end]) - entry) / entry * 100.0
    return {
        "pnl": pnl,
        "days": max(1.0, bars),
        "closed": dates[end],
        "exit_type": "TIME",
        "exit_price": float(closes[end]),
        "r_mult": (pnl / 100.0 * entry) / risk,
    }


def apply_exit_arm(base: list[dict[str, Any]], arm: ExitArm) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    skip = 0
    for t in base:
        df = get_ohlc(t["symbol"])
        if df is None:
            skip += 1
            continue
        stop = float(t["zone_lo"]) - float(arm.stop_atr) * float(t["atr"])
        risk = max(float(t["entry"]) - stop, float(t["entry"]) * 0.005)
        target = float(t["entry"]) + float(arm.target_r) * risk
        sim = replay_exit(
            df,
            entry_date=t["opened"],
            entry=float(t["entry"]),
            stop=stop,
            target=target,
            exit_bars=arm.exit_bars,
            trail_be_r=arm.trail_be_r,
        )
        if sim is None:
            skip += 1
            continue
        pnl = float(sim["pnl"])
        out.append(
            {
                "symbol": t["symbol"],
                "opened": t["opened"],
                "closed": sim["closed"],
                "entry": t["entry"],
                "pnl": pnl,
                "pnl_d": pnl / 100.0 * SHEET,
                "days": float(sim["days"]),
                "exit_type": sim["exit_type"],
                "r_mult": float(sim["r_mult"]),
                "stop": stop if arm.trail_be_r is None else sim["exit_price"],
                "target": target,
            }
        )
    if skip:
        print(f"  [{arm.name}] skipped {skip} trades (missing OHLC / entry bar)")
    return out


def filter_cd_after_target(
    base: list[dict[str, Any]], cooldown_days: int
) -> list[dict[str, Any]]:
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for t in base:
        by_sym.setdefault(t["symbol"], []).append(t)
    kept: list[dict[str, Any]] = []
    for _sym, rs in by_sym.items():
        rs = sorted(rs, key=lambda x: (x["opened"], x["closed"]))
        last_target_exit: Optional[date] = None
        for t in rs:
            if last_target_exit is not None:
                gap = (t["opened"] - last_target_exit).days
                if 0 <= gap <= cooldown_days:
                    continue
            kept.append(dict(t))
            if t["exit_type"] == "TARGET":
                last_target_exit = t["closed"]
    return kept


def load_spy_sma200() -> pd.Series:
    spy = load_ohlcv(DATA_DIR / "SPY.csv")
    close = spy["Close"].astype(float)
    sma = close.rolling(200, min_periods=200).mean()
    ok = close > sma
    return pd.Series(ok.to_numpy(), index=pd.to_datetime(spy["Date"]).dt.normalize())


def filter_spy_regime(
    base: list[dict[str, Any]], spy_ok: pd.Series
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in base:
        d = pd.Timestamp(t["opened"]).normalize()
        if d in spy_ok.index:
            if bool(spy_ok.loc[d]):
                out.append(dict(t))
            continue
        prior = spy_ok.loc[:d]
        if len(prior) and bool(prior.iloc[-1]):
            out.append(dict(t))
    return out


def metrics_pack(
    trades: list[dict[str, Any]],
    *,
    equity_curve_path: Optional[Path] = None,
    start_date=None,
    end_date_exclusive=None,
) -> dict[str, Any]:
    n = len(trades)
    empty = {
        "n_signals": 0,
        "win_rate": 0.0,
        "avg_r": 0.0,
        "avg_pnl_pct": 0.0,
        "med_pnl_pct": 0.0,
        "ann_ror": float("nan"),
        "max_dd": float("nan"),
        "calmar": float("nan"),
        "sharpe": float("nan"),
        "sharpe_source": "",
        "pf": 0.0,
        "sheet_pnl": 0.0,
        "expectancy_d": 0.0,
        "avg_days": 0.0,
        "exit_mix": "",
        "wo_max": 0.0,
        "capital_days": 0.0,
    }
    if n == 0:
        return empty
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    rs = [float(t.get("r_mult", 0.0) or 0.0) for t in trades]
    wr = len(wins) / n
    avg_pnl = float(np.mean(pnls))
    med = float(np.median(pnls))
    avg_r = float(np.mean(rs)) if rs else 0.0
    gross_w = sum(wins) if wins else 0.0
    gross_l = abs(sum(losses)) if losses else 0.0
    pf = (gross_w / gross_l) if gross_l > 1e-12 else (999.0 if gross_w > 0 else 0.0)
    sheet = sum(float(t["pnl_d"]) for t in trades)
    avg_days = float(np.mean([float(t["days"]) for t in trades]))
    if wins:
        max_w = max(wins)
        dropped = False
        wo2: list[float] = []
        for p in pnls:
            if (not dropped) and p == max_w and p > 0:
                dropped = True
                continue
            wo2.append(p)
        wo_max = float(np.mean(wo2)) if wo2 else avg_pnl
    else:
        wo_max = avg_pnl
    cap = overlay_ann_ror_max_dd(
        trades,
        cash=SHEET,
        initial_account=INIT,
        equity_curve_path=equity_curve_path,
        start_date=start_date,
        end_date_exclusive=end_date_exclusive,
    )
    ann = float(cap.get("ann_ror", float("nan")))
    dd = float(cap.get("max_dd", float("nan")))
    calmar = float(cap.get("calmar", float("nan")))
    if not math.isfinite(calmar):
        calmar = (
            ann / abs(dd)
            if math.isfinite(ann) and math.isfinite(dd) and abs(dd) > 1e-9
            else float("nan")
        )
    sharpe = float(cap.get("sharpe", float("nan")))
    mix = Counter(str(t["exit_type"]) for t in trades)
    mix_s = ", ".join(f"{k}={v}({100.0 * v / n:.0f}%)" for k, v in sorted(mix.items()))
    return {
        "n_signals": n,
        "win_rate": wr,
        "avg_r": avg_r,
        "avg_pnl_pct": avg_pnl,
        "med_pnl_pct": med,
        "ann_ror": ann,
        "max_dd": dd,
        "calmar": calmar,
        "sharpe": sharpe,
        "sharpe_source": str(cap.get("sharpe_source") or ""),
        "pf": pf,
        "sheet_pnl": sheet,
        "expectancy_d": sheet / n,
        "avg_days": avg_days,
        "exit_mix": mix_s,
        "wo_max": wo_max,
        "capital_days": float(cap.get("capital_days", 0.0) or 0.0),
    }


def split_trades(trades: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    is_rows = [t for t in trades if t["opened"] < IS_CUT]
    oos_rows = [t for t in trades if t["opened"] >= IS_CUT]
    return is_rows, oos_rows


def score_arm_is(arm: str, m: dict, ctrl: dict) -> tuple[str, str]:
    """IS judge. Do not treat EXIT_ts40 as control (house is now ts20)."""
    if arm in ("00_freeze", "CONTROL"):
        return "CONTROL", "Paul78.142 house freeze reference (stop 0.5 / 1.5R / ts20 / cd=10)"
    n, wr, avg_r, avg_pnl = m["n_signals"], m["win_rate"], m["avg_r"], m["avg_pnl_pct"]
    c_n, c_wr, c_r, c_pnl = (
        ctrl["n_signals"],
        ctrl["win_rate"],
        ctrl["avg_r"],
        ctrl["avg_pnl_pct"],
    )
    if n < max(20, int(0.15 * c_n)):
        return "DISMISS", f"Sample collapsed ({n} vs ctrl {c_n})"
    d_wr = wr - c_wr
    d_r = avg_r - c_r
    d_pnl = avg_pnl - c_pnl
    better_wr = d_wr >= 0.015
    better_r = d_r >= 0.03
    better_pnl = d_pnl >= 0.15
    worse_wr = d_wr <= -0.02
    worse_r = d_r <= -0.03
    worse_pnl = d_pnl <= -0.15
    if arm.startswith("EXIT_stop_atr") and d_wr >= 0.01 and d_pnl >= 0.10:
        return (
            "LEAN KEEP",
            "WR and AvgPnL% improve; AvgR may fall when stop widens — judge stop-width on PnL%/WR not AvgR",
        )
    if better_wr and better_r:
        return "KEEP", "WR and AvgR both improve vs freeze"
    if (better_r or better_pnl) and d_wr >= -0.015:
        return "LEAN KEEP", "AvgR/PnL up; WR roughly holds"
    if better_wr and d_r >= -0.02:
        return "LEAN KEEP", "WR up; AvgR roughly holds"
    if worse_wr and worse_r:
        return "DISMISS", "WR and AvgR both worse"
    if worse_wr or worse_r or worse_pnl:
        return "DISMISS", "Quality regresses on WR, AvgR, or PnL%"
    if d_wr > 0 and d_r > 0:
        return "LEAN KEEP", "Small quality lift on both WR and AvgR"
    return "HOLD", "Mixed / flat vs freeze — no clear edge"


def oos_softens(arm_oos: dict, ctrl_oos: dict) -> bool:
    if arm_oos["n_signals"] < 20 or ctrl_oos["n_signals"] < 20:
        return False
    d_wr = (arm_oos["win_rate"] - ctrl_oos["win_rate"]) * 100
    d_pnl = arm_oos["avg_pnl_pct"] - ctrl_oos["avg_pnl_pct"]
    d_ror = arm_oos["ann_ror"] - ctrl_oos["ann_ror"]
    if not math.isfinite(d_ror):
        d_ror = 0.0
    return (d_wr <= -3.0 and d_pnl <= -0.2) or (d_ror <= -15.0 and d_pnl < 0.5)


def fmt_num(x: float, nd: int = 2) -> str:
    if x is None or not math.isfinite(float(x)):
        return "—"
    return f"{float(x):.{nd}f}"


def write_arm_csv(path: Path, trades: list[dict[str, Any]]) -> None:
    cols = [
        "SYMBOL",
        "DATE_OPENED",
        "DATE_CLOSED",
        "ENTRY_PRICE",
        "PNL_PCT",
        "PNL_DOLLARS",
        "DAYS_HELD",
        "EXIT_TYPE",
        "R_MULT",
        "STOP_PRICE",
        "TARGET_PRICE",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for t in trades:
            w.writerow(
                {
                    "SYMBOL": t["symbol"],
                    "DATE_OPENED": t["opened"].isoformat(),
                    "DATE_CLOSED": t["closed"].isoformat()
                    if hasattr(t["closed"], "isoformat")
                    else str(t["closed"]),
                    "ENTRY_PRICE": f"{t['entry']:.4f}",
                    "PNL_PCT": f"{t['pnl']:.4f}",
                    "PNL_DOLLARS": f"{t['pnl_d']:.2f}",
                    "DAYS_HELD": f"{t['days']:.0f}",
                    "EXIT_TYPE": t["exit_type"],
                    "R_MULT": f"{t.get('r_mult', 0):.4f}",
                    "STOP_PRICE": f"{t.get('stop', t.get('stop_house', ''))}",
                    "TARGET_PRICE": f"{t.get('target', t.get('target_house', ''))}",
                }
            )


def find_closed_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_house_stamp(ts_file)
        p = d / f"VZ_Closed_{stamp}.csv"
        if p.exists():
            return p
    latest = d / "VZ_LatestRun_Closed.csv"
    if latest.exists():
        return latest
    hits = sorted(d.glob("VZ_Closed_*.csv"))
    return hits[-1] if hits else None


def find_equity_in_dir(d: Path) -> Optional[Path]:
    ts_file = d / "VZ_last_run_ts.txt"
    if ts_file.exists():
        stamp = read_house_stamp(ts_file)
        for name in (
            f"VZ_EquityCurve_{stamp}.csv",
            f"VZ_EquityCurve_Regular_{stamp}.csv",
        ):
            p = d / name
            if p.exists():
                return p
    latest = d / "VZ_LatestRun_EquityCurve.csv"
    return latest if latest.exists() else None


def run_isolated_live(out_dir: Path, extra_env: dict[str, str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("VZ_SYMBOLS", None)
    env.pop("VZ_UNIVERSE_CSV", None)
    env.update(extra_env)
    rel_out = out_dir.relative_to(REPO).as_posix().replace("/", "\\")
    cmd = f"run_vz.bat -o {rel_out}"
    print(f"[live] {cmd} env={extra_env}", flush=True)
    subprocess.run(cmd, shell=True, check=True, cwd=str(REPO), env=env)
    closed = find_closed_in_dir(out_dir)
    if closed is None:
        raise FileNotFoundError(f"no Closed in {out_dir}")
    return closed


def build_html(
    out_path: Path,
    *,
    packs: list[dict[str, Any]],
    recommendation: str,
    deferred: list[str],
    control_stamp: str,
) -> None:
    ctrl = next(p for p in packs if p["arm"] == "00_freeze")

    def row_class(v: str) -> str:
        if v in ("KEEP", "LEAN KEEP"):
            return "keep"
        if v == "DISMISS":
            return "dismiss"
        if v == "HOLD":
            return "hold"
        return ""

    def pack_row(p: dict[str, Any], key: str, ctrl_key: str) -> str:
        m = p[key]
        c = ctrl[ctrl_key]
        d_n = m["n_signals"] - c["n_signals"]
        d_wr = (m["win_rate"] - c["win_rate"]) * 100
        d_r = m["avg_r"] - c["avg_r"]
        d_pnl = m["avg_pnl_pct"] - c["avg_pnl_pct"]
        d_ror = (
            m["ann_ror"] - c["ann_ror"]
            if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"])
            else float("nan")
        )
        d_dd = (
            m["max_dd"] - c["max_dd"]
            if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"])
            else float("nan")
        )
        d_cal = (
            m["calmar"] - c["calmar"]
            if math.isfinite(m["calmar"]) and math.isfinite(c["calmar"])
            else float("nan")
        )
        d_sh = (
            m["sharpe"] - c["sharpe"]
            if math.isfinite(m.get("sharpe", float("nan")))
            and math.isfinite(c.get("sharpe", float("nan")))
            else float("nan")
        )
        d_pf = m["pf"] - c["pf"]
        return (
            "<tr class='{cls}'>"
            "<td>{arm}</td><td>{kind}</td><td>{knob}</td><td>{hyp}</td>"
            "<td>{n}</td><td>{wr}</td><td>{avg}</td><td>{avgr}</td><td>{med}</td>"
            "<td>{wo}</td><td>{ror}</td><td>{dd}</td><td>{cal}</td><td>{sh}</td>"
            "<td>{pf}</td><td>{exp}</td><td>{adays}</td><td>{cdays}</td>"
            "<td>{dn}</td><td>{dwr}</td><td>{dr}</td><td>{dpnl}</td><td>{dror}</td>"
            "<td>{ddd}</td><td>{dcal}</td><td>{dsh}</td><td>{dpf}</td>"
            "<td>{verdict}</td><td>{why}</td><td>{mix}</td>"
            "</tr>"
        ).format(
            cls=row_class(p["verdict"]),
            arm=html_mod.escape(p["arm"]),
            kind=html_mod.escape(p["kind"]),
            knob=html_mod.escape(p["knob"]),
            hyp=html_mod.escape(p["hypothesis"]),
            n=m["n_signals"],
            wr=fmt_num(m["win_rate"] * 100, 1),
            avg=fmt_num(m["avg_pnl_pct"]),
            avgr=fmt_num(m["avg_r"]),
            med=fmt_num(m["med_pnl_pct"]),
            wo=fmt_num(m["wo_max"]),
            ror=fmt_num(m["ann_ror"]),
            dd=fmt_num(m["max_dd"]),
            cal=fmt_num(m["calmar"]),
            sh=fmt_num(m.get("sharpe", float("nan"))),
            pf=fmt_num(m["pf"]),
            exp=format_money(m.get("expectancy_d")),
            adays=fmt_num(m["avg_days"], 1),
            cdays=fmt_num(m["capital_days"], 0),
            dn=f"{d_n:+d}",
            dwr=f"{d_wr:+.1f}",
            dr=f"{d_r:+.2f}",
            dpnl=f"{d_pnl:+.2f}",
            dror=fmt_num(d_ror) if not math.isfinite(d_ror) else f"{d_ror:+.1f}",
            ddd=fmt_num(d_dd) if not math.isfinite(d_dd) else f"{d_dd:+.2f}",
            dcal=fmt_num(d_cal) if not math.isfinite(d_cal) else f"{d_cal:+.2f}",
            dsh=fmt_num(d_sh) if not math.isfinite(d_sh) else f"{d_sh:+.2f}",
            dpf=f"{d_pf:+.2f}",
            verdict=html_mod.escape(p["verdict"]),
            why=html_mod.escape(p["why"]),
            mix=html_mod.escape(m["exit_mix"]),
        )

    body_is = [pack_row(p, "is", "is") for p in packs]
    body_full = [pack_row(p, "full", "full") for p in packs]

    body_split = []
    for p in packs:
        for slice_name, key in (("IS (judge)", "is"), ("OOS (report-only)", "oos"), ("Full", "full")):
            m = p[key]
            body_split.append(
                "<tr class='{cls}'><td>{arm}</td><td>{sl}</td><td>{n}</td><td>{wr}</td>"
                "<td>{avg}</td><td>{avgr}</td><td>{ror}</td><td>{dd}</td><td>{cal}</td>"
                "<td>{sh}</td><td>{pf}</td><td>{exp}</td></tr>".format(
                    cls=row_class(p["verdict"]),
                    arm=html_mod.escape(p["arm"]),
                    sl=slice_name,
                    n=m["n_signals"],
                    wr=fmt_num(m["win_rate"] * 100, 1),
                    avg=fmt_num(m["avg_pnl_pct"]),
                    avgr=fmt_num(m["avg_r"]),
                    ror=fmt_num(m["ann_ror"]),
                    dd=fmt_num(m["max_dd"]),
                    cal=fmt_num(m["calmar"]),
                    sh=fmt_num(m.get("sharpe", float("nan"))),
                    pf=fmt_num(m["pf"]),
                    exp=format_money(m.get("expectancy_d")),
                )
            )

    th_full = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("Kind", "text"),
            sortable_th("Knob", "text"),
            sortable_th("Hypothesis", "text"),
            sortable_th("N", "num"),
            sortable_th("WR%", "num"),
            sortable_th("AvgPnL%", "num"),
            sortable_th("AvgR", "num"),
            sortable_th("MedPnL%", "num"),
            sortable_th("WO_MAX%", "num"),
            sortable_th("Ann ROR%", "num"),
            sortable_th("Max DD%", "num"),
            sortable_th("Calmar", "num"),
            sortable_th("Sharpe", "num"),
            sortable_th("PF", "num"),
            sortable_th("Expectancy $", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("CapitalDays", "num"),
            sortable_th("ΔN", "num"),
            sortable_th("ΔWR pp", "num"),
            sortable_th("ΔAvgR", "num"),
            sortable_th("ΔPnL%", "num"),
            sortable_th("ΔAnnROR pp", "num"),
            sortable_th("ΔMaxDD pp", "num"),
            sortable_th("ΔCalmar", "num"),
            sortable_th("ΔSharpe", "num"),
            sortable_th("ΔPF", "num"),
            sortable_th("Verdict", "text"),
            sortable_th("Why", "text"),
            sortable_th("Exit mix", "text"),
        ]
    )
    th_split = "".join(
        [
            sortable_th("Arm", "text"),
            sortable_th("Slice", "text"),
            sortable_th("N", "num"),
            sortable_th("WR%", "num"),
            sortable_th("AvgPnL%", "num"),
            sortable_th("AvgR", "num"),
            sortable_th("Ann ROR%", "num"),
            sortable_th("Max DD%", "num"),
            sortable_th("Calmar", "num"),
            sortable_th("Sharpe", "num"),
            sortable_th("PF", "num"),
            sortable_th("Expectancy $", "num"),
        ]
    )

    deferred_li = "".join(f"<li>{html_mod.escape(x)}</li>" for x in deferred)
    rec_cls = "hold"
    if "LEAN KEEP" in recommendation or recommendation.startswith("KEEP"):
        rec_cls = "keep"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ImprovePriority AB — Paul78.142 house {control_stamp}</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1760px; margin:0 auto; }}
  h1 {{ font-size:1.45rem; }}
  h2 {{ font-size:1.15rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
  .callout {{ background:#eef2ff; border:1px solid #c7d2fe; padding:14px 16px; margin:1rem 0; }}
  .rec {{ background:#f0f0ea; border:1px solid #d8d8d0; padding:14px 16px; margin:1rem 0; }}
  .rec.keep {{ background:#ecfdf5; }}
  .rec.hold {{ background:#fffbeb; }}
  table.sortable {{ border-collapse:collapse; width:100%; font-size:12.5px; margin-bottom:1.4rem; }}
  table.sortable th, table.sortable td {{ border:1px solid #d8d8d0; padding:5px 7px; vertical-align:top; }}
  table.sortable th {{ background:#f0f0ea; }}
  tr.keep {{ background:#ecfdf5; }}
  tr.dismiss {{ background:#fef2f2; }}
  tr.hold {{ background:#fffbeb; }}
  code {{ font-size:0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<div class="wrap">
  <h1>Volume Zone (VZ) ImprovePriority AB — Paul78.142 house</h1>

  <div class="callout">
    <p><strong>What you asked</strong></p>
    <p>{html_mod.escape(ORIGINAL_REQUEST)}</p>
    <p><strong>In plain English</strong></p>
    <p>Volume Zone (VZ) buys the first retest after price breaks a high/low shelf.
    Paul Score is the house quality score. We adopted the 142-name Paul78.142 list
    as the research sleeve (product choice, not gold). Then we asked: if we change
    <em>one</em> rule at a time — stop a bit wider or tighter, take profits sooner
    or later, cut losers faster, wait longer after a win before re-entering — does
    the <em>quality</em> of trades get better? We judge on trades that started
    before 2024. Results after 2024 are a report card only. Nothing here is wired
    into DailyRun.</p>
  </div>

  <p class="muted">
    Research only (not gold / not DailyRun). Control = house <code>run_vz.bat</code>
    freeze on Paul78.142 Closed <code>{html_mod.escape(control_stamp)}</code>.
    Freeze: HL-only, first_retest, mt≥1, eps=0.005, lookback=126, rw=63,
    <code>EXIT_atr4_s05_r15_ts20</code>, stop 0.5, target 1.5, exit_bars=20,
    HVN false, long, cooldown_after_target=10.
    IS = entry &lt; 2024-01-01 (judge); OOS report-only. Click column headers to sort.
    Overlay Ann ROR / Max DD / Calmar / Sharpe via $45k sheet / $500k seed.
    Total PnL $ / Sheet PnL $ omitted from HTML (canonical).
  </p>

  <div class="rec {rec_cls}">
    <strong>Recommendation</strong>
    <pre style="white-space:pre-wrap;margin:0.6rem 0 0;font-family:inherit">{html_mod.escape(recommendation)}</pre>
  </div>

  <h2>IS judge (entry &lt; 2024-01-01) — one-knob vs freeze</h2>
  <p class="muted">Click column headers to sort. Judge quality over count. KEEP/LEAN KEEP only if IS quality improves without collapsing N.</p>
  <table class="sortable"><thead><tr>{th_full}</tr></thead><tbody>
  {''.join(body_is)}
  </tbody></table>

  <h2>Full book (context — not the judge)</h2>
  <p class="muted">Same columns. Do not pick KEEP from this table if IS is flat/worse.</p>
  <table class="sortable"><thead><tr>{th_full}</tr></thead><tbody>
  {''.join(body_full)}
  </tbody></table>

  <h2>IS / OOS / Full</h2>
  <p class="muted">OOS is report-only — do not retune if OOS softens. Click column headers to sort.</p>
  <table class="sortable"><thead><tr>{th_split}</tr></thead><tbody>
  {''.join(body_split)}
  </tbody></table>

  <h2>Deferred / skipped</h2>
  <ul class="muted">{deferred_li or "<li>None</li>"}</ul>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def recommend(packs: list[dict[str, Any]], control_stamp: str) -> str:
    ctrl = next(p for p in packs if p["arm"] == "00_freeze")
    lines: list[str] = [
        f"Overall freeze: **HOLD pin** `{control_stamp}` Paul78.142 / "
        "`EXIT_atr4_s05_r15_ts20` + cd_target=10 — research sleeve, not gold. "
        "Do not adopt any AB winner into DailyRun.",
    ]
    for p in packs[1:]:
        if p["verdict"] in ("KEEP", "LEAN KEEP") and oos_softens(p["oos"], ctrl["oos"]):
            p["verdict"] = "HOLD"
            p["why"] = p["why"] + " | OOS softens vs control OOS — HOLD (do not retune OOS)"
    keeps = [p for p in packs if p["verdict"] in ("KEEP", "LEAN KEEP")]
    if keeps:
        names = ", ".join(p["arm"] for p in keeps)
        lines.append(
            f"Research LEAN KEEP / KEEP (not gold / not DailyRun / not auto-pin): {names}."
        )
    else:
        lines.append("No one-knob KEEP/LEAN KEEP on IS quality that also survives OOS soften gate.")
    lines.append(
        f"HOLD count: {len([p for p in packs if p['verdict']=='HOLD'])}; "
        f"DISMISS count: {len([p for p in packs if p['verdict']=='DISMISS'])}; "
        f"LEAN KEEP/KEEP count: {len(keeps)}."
    )
    lines.append(
        "Selection bias labeled (ImprovePriority → arms on the same Paul78.142 Closed). "
        "Research only — not gold / not DailyRun."
    )
    for p in packs:
        if p["arm"] == "00_freeze":
            continue
        m, c = p["is"], ctrl["is"]
        lines.append(
            f"  - {p['arm']}: {p['verdict']} — IS WR {m['win_rate']*100:.1f}% "
            f"(d{(m['win_rate']-c['win_rate'])*100:+.1f}pp) AvgPnL% {m['avg_pnl_pct']:.2f} "
            f"(d{m['avg_pnl_pct']-c['avg_pnl_pct']:+.2f}) AnnROR {fmt_num(m['ann_ror'])} "
            f"MaxDD {fmt_num(m['max_dd'])} | OOS WR {p['oos']['win_rate']*100:.1f}% "
            f"Avg {p['oos']['avg_pnl_pct']:.2f}"
        )
    return "\n".join(lines)


def write_docs(out: Path, control_stamp: str) -> None:
    hyp = f"""# HYPOTHESIS — VZ ImprovePriority ABs on Paul78.142 (`{control_stamp}`)

**Status:** research only. Not gold. Not DailyRun. One knob per arm.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

Volume Zone (VZ) buys the first retest of a broken high/low shelf. We adopted the
142-name Paul78.142 list (Paul Score = house quality rank) as the research sleeve.
These A/Bs change one exit or entry gate at a time on that book and ask whether
trade *quality* improves before 2024.

## Evidence → knob (from ImprovePriority / ImproveHints on this freeze)

| Evidence | Arm | Method |
|----------|-----|--------|
| `fat_stops` + stop contract lens | `EXIT_stop_atr025`, `EXIT_ts10` | Closed overlay |
| `stop_pct_tension` lean expand | `EXIT_stop_atr075` | Closed overlay |
| `target_pct_tension` contract | `EXIT_target_r10` | Closed overlay |
| `small_target_wins` + target expand | `EXIT_target_r20` | Closed overlay |
| `winner_peak_giveback` | `EXIT_trail_be1r`, `EXIT_ts40` | Closed overlay |
| `post_target_quick_stop` | `ENTRY_cd_target20` | Closed overlay (tighten vs house cd=10) |
| same hint, opposite lens | `ENTRY_cd_target0` | **live** isolated (Closed already has cd=10; cannot add trades back) |
| `false_start_2022_2023` | `ENTRY_spy_sma200` | Closed overlay |
| `band_tighten_weak_fill` | `ENTRY_eps002`, `ENTRY_mt2` | **live** isolated |
| `peer_wider_stop_won_rs` (after house LatestRun exists) | same as `EXIT_stop_atr075` | already wired |
| `peer_longer_hold_won_rs` | same as `EXIT_ts40` | already wired |

## Skipped (already-known HOLD or no new priority)

- HVN overlap — prior engine A/B HOLD; ImprovePriority did not newly prioritize it.
- Shorts — prior HOLD; house `trade_side=long`.
- `first_retest_only` flip — not in ImprovePriority.
- Partial / scale-out — no simulator.
- `ENTRY_start_2024` — would zero the IS judge window.

## Freeze (control)

HL-only, first_retest, mt≥1, eps=0.005, lookback=126, rw=63, next_open,
`EXIT_atr4_s05_r15_ts20`, exit_bars=20, stop_atr=0.5, target_r=1.5, min_atr=4,
HVN=false, long, cooldown 10d, aggressive, $500k.

## Judge

IS = entry &lt; 2024-01-01. OOS report-only. Quality over N. No OOS retune.
No DailyRun adopt from this table.
"""
    (out / "HYPOTHESIS.md").write_text(hyp, encoding="utf-8")

    plan = f"""# AB_PLAN — VZ ImprovePriority Paul78.142 `{control_stamp}`

One knob per arm. Control = house freeze on Paul78.142 Closed `{control_stamp}`.

## Overlay now (same entries)

1. EXIT stop 0.25 / 0.75
2. EXIT target 1.0 / 2.0
3. EXIT time-stop 10 / 40
4. EXIT trail BE@1R
5. ENTRY cd_target20 (vs house 10)
6. ENTRY SPY>SMA200

## Live isolated `-o` (do not overwrite house pin)

- `ENTRY_cd_target0` — `VZ_COOLDOWN_AFTER_TARGET_DAYS=0`
- `ENTRY_eps002` — `VZ_RETEST_EPS=0.002`
- `ENTRY_mt2` — `VZ_MIN_TOUCHES=2`

## Dismiss / skip

- HVN, shorts, first_retest flip, partial/scale-out, start_date 2024 (zeros IS)

## Outputs

- `compare.html` — sortable canonical metrics, IS judge, OOS report-only
- `metrics.csv` / arm Closed CSVs
- `HYPOTHESIS.md` / `AB_PLAN.md` / `BASELINE.md`
"""
    (out / "AB_PLAN.md").write_text(plan, encoding="utf-8")

    baseline = f"""# BASELINE — VZ ImprovePriority AB Paul78.142 (NOT gold)

**Stamp folder:** `drive/paul_experiments/vz_paul78_142_improve_ab_20260907/`
**Control pin:** house `{control_stamp}` / Paul78.142
**Status:** Research candidate ABs only — **not** gold, **not** DailyRun-wired.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

Same 142-name Volume Zone (VZ) book; change one exit or entry gate at a time;
keep only quality lifts that hold up without collapsing trade count. OOS is report-only.

## Frozen control

| Knob | Value |
|------|-------|
| Universe | Paul78.142 (`drive/universes/VZ_universe.csv`) |
| zone_kinds | HL only |
| first_retest_only | true |
| min_touches | ≥1 |
| retest_eps_pct | 0.005 |
| lookback / retest_window | 126 / 63 |
| entry_on | next_open |
| exit | `EXIT_atr4_s05_r15_ts20` — zone.lo−0.5·ATR, 1.5R, time-stop 20 |
| require_hvn_overlap | false |
| trade_side | long |
| cooldown_after_target_days | **10** |
| Sheet notional | $45,000 |

## Chronologic split

- IS = `entry_date < 2024-01-01` (**judge**)
- OOS = `entry_date >= 2024-01-01` — report-only; do not retune

## Selection bias

Arms chosen from ImprovePriority / ImproveHints on this same Closed book
(in-sample selection). Label honesty: research-only.
"""
    (out / "BASELINE.md").write_text(baseline, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--stamp",
        default="",
        help="House Closed stamp (default: drive/VZ_house_last_run_ts.txt)",
    )
    ap.add_argument("--closed", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-live", action="store_true")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    stamp = (args.stamp or "").strip()
    if not stamp:
        stamp = read_house_stamp(REPO / "drive" / "VZ_house_last_run_ts.txt")
    closed_path = args.closed or (REPO / "drive" / f"VZ_Closed_{stamp}.csv")
    write_docs(out, stamp)

    print(f"Loading Closed {closed_path}")
    base = load_house_closed(closed_path)
    print(f"  trades={len(base)} stamp={stamp}")
    if not base:
        print("ERROR: no trades")
        return 1

    syms = sorted({t["symbol"] for t in base})
    print(f"Warming OHLC for {len(syms)} symbols…")
    for s in syms:
        get_ohlc(s)

    ctrl_trades = [
        {**t, "stop": t.get("stop_house"), "target": t.get("target_house")}
        for t in base
    ]
    house_eq = REPO / "drive" / f"VZ_EquityCurve_{stamp}.csv"
    if not house_eq.exists():
        house_eq = None

    packs: list[dict[str, Any]] = []

    def add_pack(
        arm: str,
        kind: str,
        knob: str,
        hypothesis: str,
        trades: list[dict[str, Any]],
        equity: Optional[Path] = None,
    ) -> None:
        full = metrics_pack(trades, equity_curve_path=equity)
        is_rows, oos_rows = split_trades(trades)
        is_m = metrics_pack(is_rows)
        oos_m = metrics_pack(oos_rows)
        ctrl_is = packs[0]["is"] if packs else is_m
        verdict, why = score_arm_is(arm, is_m, ctrl_is)
        packs.append(
            {
                "arm": arm,
                "kind": kind,
                "knob": knob,
                "hypothesis": hypothesis,
                "full": full,
                "is": is_m,
                "oos": oos_m,
                "verdict": verdict,
                "why": why,
                "trades": trades,
            }
        )
        write_arm_csv(out / f"closed_{arm}.csv", trades)
        print(
            f"  {arm}: IS N={is_m['n_signals']} WR={is_m['win_rate']*100:.1f}% "
            f"Avg={is_m['avg_pnl_pct']:.2f} ROR={fmt_num(is_m['ann_ror'])} "
            f"DD={fmt_num(is_m['max_dd'])} -> {verdict}"
        )

    add_pack(
        "00_freeze",
        "CONTROL",
        "EXIT_atr4_s05_r15_ts20 + cd=10 Paul78.142",
        "baseline",
        ctrl_trades,
        equity=house_eq,
    )

    print(f"Replaying {len(EXIT_ARMS)} EXIT arms ({args.workers} workers)…")
    exit_results: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(apply_exit_arm, base, arm): arm for arm in EXIT_ARMS}
        for fut in as_completed(futs):
            arm = futs[fut]
            trades = fut.result()
            exit_results[arm.name] = trades
            print(f"  done {arm.name} N={len(trades)}")

    for arm in EXIT_ARMS:
        add_pack(arm.name, "EXIT", arm.label, arm.hypothesis, exit_results[arm.name])

    print("Filtering ENTRY_cd_target20 (control already has cd=10)…")
    add_pack(
        "ENTRY_cd_target20",
        "ENTRY",
        "Skip entries ≤20d after TARGET (vs house 10)",
        "post_target_quick_stop",
        filter_cd_after_target(ctrl_trades, cooldown_days=20),
    )

    print("Filtering ENTRY_spy_sma200…")
    add_pack(
        "ENTRY_spy_sma200",
        "ENTRY",
        "Require SPY Close > SMA200 on entry date",
        "false_start_2022_2023",
        filter_spy_regime(ctrl_trades, load_spy_sma200()),
    )

    deferred = [
        "HVN overlap — prior HOLD; ImprovePriority did not newly prioritize — skipped",
        "shorts — prior HOLD; house trade_side=long — skipped",
        "first_retest_only flip — not in ImprovePriority — skipped",
        "partial_exit / scale-out — no simulator → DISMISS untestable",
        "ENTRY_start_2024 — would zero IS judge window — skipped",
        "peer_learn — no peers on this book — skipped",
    ]

    if args.skip_live:
        deferred.append(
            "LIVE skipped (--skip-live): ENTRY_cd_target0 / ENTRY_eps002 / ENTRY_mt2"
        )
    else:
        live_specs = [
            (
                "ENTRY_cd_target0",
                "ENTRY",
                "cooldown_after_target_days 10→0 (live)",
                "post_target_quick_stop opposite lens (Closed cannot add trades back)",
                {"VZ_COOLDOWN_AFTER_TARGET_DAYS": "0"},
                out / "live_cd0",
            ),
            (
                "ENTRY_eps002",
                "ENTRY",
                "retest_eps_pct 0.005→0.002 (tighter band)",
                "band_tighten_weak_fill",
                {"VZ_RETEST_EPS": "0.002"},
                out / "live_eps002",
            ),
            (
                "ENTRY_mt2",
                "ENTRY",
                "min_touches 1→2",
                "band_tighten_weak_fill (stricter acceptance)",
                {"VZ_MIN_TOUCHES": "2"},
                out / "live_mt2",
            ),
        ]
        for name, kind, knob, hyp, extra, live_dir in live_specs:
            try:
                closed_live = find_closed_in_dir(live_dir)
                if closed_live is None:
                    closed_live = run_isolated_live(live_dir, extra)
                else:
                    print(f"[live] reuse {closed_live}")
                trades = load_house_closed(closed_live)
                for t in trades:
                    t["stop"] = t.get("stop_house")
                    t["target"] = t.get("target_house")
                add_pack(name, kind, knob, hyp, trades, equity=find_equity_in_dir(live_dir))
            except Exception as exc:
                deferred.append(f"{name} live run failed: {exc}")
                print(f"[live] FAIL {name}: {exc}")

    ctrl_is = packs[0]["is"]
    for p in packs[1:]:
        v, w = score_arm_is(p["arm"], p["is"], ctrl_is)
        p["verdict"], p["why"] = v, w

    rec = recommend(packs, stamp)
    write_html = out / "compare.html"
    build_html(
        write_html,
        packs=packs,
        recommendation=rec,
        deferred=deferred,
        control_stamp=stamp,
    )

    with (out / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        cols = [
            "arm",
            "kind",
            "verdict",
            "slice",
            "N",
            "WR_pct",
            "AvgPnL_pct",
            "AvgR",
            "MedPnL_pct",
            "WO_MAX_pct",
            "Ann_ROR_pct",
            "Max_DD_pct",
            "Calmar",
            "Sharpe",
            "Sharpe_source",
            "PF",
            "Expectancy_d",
            "Sheet_PnL",
            "AvgDays",
            "CapitalDays",
            "why",
        ]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in packs:
            for sl, key in (("full", "full"), ("IS", "is"), ("OOS", "oos")):
                m = p[key]
                w.writerow(
                    {
                        "arm": p["arm"],
                        "kind": p["kind"],
                        "verdict": p["verdict"],
                        "slice": sl,
                        "N": m["n_signals"],
                        "WR_pct": round(m["win_rate"] * 100, 3),
                        "AvgPnL_pct": round(m["avg_pnl_pct"], 4),
                        "AvgR": round(m["avg_r"], 4),
                        "MedPnL_pct": round(m["med_pnl_pct"], 4),
                        "WO_MAX_pct": round(m["wo_max"], 4),
                        "Ann_ROR_pct": m["ann_ror"] if math.isfinite(m["ann_ror"]) else "",
                        "Max_DD_pct": m["max_dd"] if math.isfinite(m["max_dd"]) else "",
                        "Calmar": m["calmar"] if math.isfinite(m["calmar"]) else "",
                        "Sharpe": m.get("sharpe", "")
                        if isinstance(m.get("sharpe"), (int, float))
                        and math.isfinite(float(m.get("sharpe")))
                        else "",
                        "Sharpe_source": m.get("sharpe_source", ""),
                        "PF": round(m["pf"], 4),
                        "Expectancy_d": round(m.get("expectancy_d", 0.0), 2),
                        "Sheet_PnL": round(m["sheet_pnl"], 2),
                        "AvgDays": round(m["avg_days"], 3),
                        "CapitalDays": round(m["capital_days"], 3),
                        "why": p["why"],
                    }
                )

    base_md = out / "BASELINE.md"
    text = base_md.read_text(encoding="utf-8")
    marker = "\n## Auto results\n"
    if marker in text:
        text = text.split(marker)[0].rstrip() + "\n"
    text += marker + "\n```\n" + rec + "\n```\n"
    base_md.write_text(text, encoding="utf-8")

    print("\n=== RECOMMENDATION ===")
    try:
        print(rec)
    except UnicodeEncodeError:
        print(rec.encode("ascii", "replace").decode("ascii"))
    print(f"\nWrote {write_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
