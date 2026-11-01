#!/usr/bin/env python3
"""ImprovePriority one-knob ABs on house VZ pin 260821094043 / VZ_new56.

Closed-overlay exit replay + post-TARGET cooldown filter. Research only.
"""
from __future__ import annotations

import argparse
import csv
import html as html_mod
import math
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "drive" / "paul_experiments"))

from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)
from vol_zone_break_retest import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    lean_ab_v2_exit,
    load_ohlcv,
    sortable_th,
)

HOUSE_STAMP = "260821094043"
DEFAULT_OUT = REPO / "drive" / "paul_experiments" / "vz_improve_ab_20260821"
CLOSED_PATH = REPO / "drive" / f"VZ_Closed_{HOUSE_STAMP}.csv"
DATA_DIR = REPO / "data" / "newdata" / "data"
IS_CUT = date(2024, 1, 1)
SHEET = 45_000.0
INIT = 500_000.0

CTRL_STOP_ATR = 0.25
CTRL_TARGET_R = 1.5
CTRL_EXIT_BARS = 40


@dataclass(frozen=True)
class ExitArm:
    name: str
    label: str
    hypothesis: str
    stop_atr: float
    target_r: float
    exit_bars: int


EXIT_ARMS: list[ExitArm] = [
    ExitArm(
        "EXIT_stop_atr05",
        "stop_atr_buffer 0.25→0.50 (wider)",
        "stop_pct_tension_expand_vs_contract + peer_wider_stop",
        stop_atr=0.50,
        target_r=CTRL_TARGET_R,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_target_r20",
        "target_r 1.5→2.0 (expand)",
        "target_pct_tension_expand_vs_contract + small_target_wins",
        stop_atr=CTRL_STOP_ATR,
        target_r=2.0,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_target_r10",
        "target_r 1.5→1.0 (contract)",
        "target_pct_tension_expand_vs_contract (contract lens)",
        stop_atr=CTRL_STOP_ATR,
        target_r=1.0,
        exit_bars=CTRL_EXIT_BARS,
    ),
    ExitArm(
        "EXIT_ts20",
        "exit_bars 40→20 (cut losers)",
        "fat_stops (time-stop lever)",
        stop_atr=CTRL_STOP_ATR,
        target_r=CTRL_TARGET_R,
        exit_bars=20,
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
    if s in {"TARGET", "TIME", "GAP_UP", "GAP_DOWN"}:
        return s
    if "STOP" in s:
        return "STOP"
    if "TARGET" in s:
        return "TARGET"
    if "TIME" in s:
        return "TIME"
    return s or "OTHER"


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
) -> Optional[dict[str, Any]]:
    dates = df["Date"].dt.date.to_numpy()
    idxs = np.where(dates == entry_date)[0]
    if len(idxs) == 0:
        # nearest prior session
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
    for i in range(ei + 1, end + 1):
        if float(lows[i]) <= stop:
            pnl = (stop - entry) / entry * 100.0
            return {
                "pnl": pnl,
                "days": float(i - ei),
                "closed": dates[i],
                "exit_type": "STOP",
                "exit_price": stop,
                "r_mult": (stop - entry) / max(entry - stop, entry * 0.005),
            }
        if float(highs[i]) >= target:
            pnl = (target - entry) / entry * 100.0
            return {
                "pnl": pnl,
                "days": float(i - ei),
                "closed": dates[i],
                "exit_type": "TARGET",
                "exit_price": target,
                "r_mult": (target - entry) / max(entry - stop, entry * 0.005),
            }
    bars = float(end - ei)
    pnl = (float(closes[end]) - entry) / entry * 100.0
    reason = "TIME" if bars >= float(exit_bars) and end >= time_i else "TIME"
    return {
        "pnl": pnl,
        "days": max(1.0, bars),
        "closed": dates[end],
        "exit_type": reason,
        "exit_price": float(closes[end]),
        "r_mult": (pnl / 100.0 * entry) / max(entry - stop, entry * 0.005),
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
                "stop": stop,
                "target": target,
            }
        )
    if skip:
        print(f"  [{arm.name}] skipped {skip} trades (missing OHLC / entry bar)")
    return out


def filter_cd_target10(base: list[dict[str, Any]], cooldown_days: int = 10) -> list[dict[str, Any]]:
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


def metrics_pack(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "n_signals": 0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "avg_pnl_pct": 0.0,
            "med_pnl_pct": 0.0,
            "ann_ror": float("nan"),
            "max_dd": float("nan"),
            "pf": 0.0,
            "sheet_pnl": 0.0,
            "avg_days": 0.0,
            "exit_mix": "",
            "wo_max": 0.0,
        }
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
    # leave-max-win-out
    if wins:
        max_w = max(wins)
        wo = [p for p in pnls if p != max_w or p <= 0]
        # drop one instance of max win
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
    cap = overlay_ann_ror_max_dd(trades, cash=SHEET, initial_account=INIT)
    mix = Counter(str(t["exit_type"]) for t in trades)
    mix_s = ", ".join(f"{k}={v}({100.0 * v / n:.0f}%)" for k, v in sorted(mix.items()))
    return {
        "n_signals": n,
        "win_rate": wr,
        "avg_r": avg_r,
        "avg_pnl_pct": avg_pnl,
        "med_pnl_pct": med,
        "ann_ror": float(cap.get("ann_ror", float("nan"))),
        "max_dd": float(cap.get("max_dd", float("nan"))),
        "pf": pf,
        "sheet_pnl": sheet,
        "avg_days": avg_days,
        "exit_mix": mix_s,
        "wo_max": wo_max,
        "capital_days": float(cap.get("capital_days", 0.0) or 0.0),
    }


def split_trades(trades: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    is_rows = [t for t in trades if t["opened"] < IS_CUT]
    oos_rows = [t for t in trades if t["opened"] >= IS_CUT]
    return is_rows, oos_rows


def score_arm(arm: str, m: dict, ctrl: dict) -> tuple[str, str]:
    if arm in ("00_freeze", "CONTROL"):
        return "CONTROL", "House Closed freeze reference"
    lean, why = lean_ab_v2_exit(arm, m, ctrl)
    # stop-width special case: AvgR dilution expected — judge WR/PnL like prior ImproveHints
    if arm.startswith("EXIT_stop_atr") and lean == "DISMISS":
        d_wr = m["win_rate"] - ctrl["win_rate"]
        d_pnl = m["avg_pnl_pct"] - ctrl["avg_pnl_pct"]
        if d_wr >= 0.01 and d_pnl >= 0.10:
            return (
                "LEAN KEEP",
                "WR and AvgPnL% improve; AvgR falls as expected when stop widens — judge stop-width on PnL%/WR not AvgR",
            )
    return lean, why


def oos_softens(arm_oos: dict, ctrl_oos: dict) -> bool:
    if arm_oos["n_signals"] < 20 or ctrl_oos["n_signals"] < 20:
        return False
    d_wr = (arm_oos["win_rate"] - ctrl_oos["win_rate"]) * 100
    d_pnl = arm_oos["avg_pnl_pct"] - ctrl_oos["avg_pnl_pct"]
    d_ror = arm_oos["ann_ror"] - ctrl_oos["ann_ror"]
    if not math.isfinite(d_ror):
        d_ror = 0.0
    # Soften = clear quality drop on OOS vs control OOS
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


def build_html(
    out_path: Path,
    *,
    packs: list[dict[str, Any]],
    recommendation: str,
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

    # Full book table
    body_full = []
    for p in packs:
        m = p["full"]
        c = ctrl["full"]
        d_n = m["n_signals"] - c["n_signals"]
        d_wr = (m["win_rate"] - c["win_rate"]) * 100
        d_r = m["avg_r"] - c["avg_r"]
        d_pnl = m["avg_pnl_pct"] - c["avg_pnl_pct"]
        d_ror = m["ann_ror"] - c["ann_ror"] if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"]) else float("nan")
        d_dd = m["max_dd"] - c["max_dd"] if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"]) else float("nan")
        d_sheet = m["sheet_pnl"] - c["sheet_pnl"]
        body_full.append(
            "<tr class='{cls}'>"
            "<td>{arm}</td><td>{kind}</td><td>{knob}</td><td>{hyp}</td>"
            "<td>{n}</td><td>{wr}</td><td>{avg}</td><td>{avgr}</td><td>{med}</td>"
            "<td>{wo}</td><td>{ror}</td><td>{dd}</td><td>{pf}</td><td>{sheet}</td><td>{adays}</td>"
            "<td>{dn}</td><td>{dwr}</td><td>{dr}</td><td>{dpnl}</td><td>{dror}</td><td>{ddd}</td><td>{dsheet}</td>"
            "<td>{verdict}</td><td>{why}</td><td>{mix}</td>"
            "</tr>".format(
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
                pf=fmt_num(m["pf"]),
                sheet=format_money(m["sheet_pnl"]),
                adays=fmt_num(m["avg_days"], 1),
                dn=f"{d_n:+d}",
                dwr=f"{d_wr:+.1f}",
                dr=f"{d_r:+.2f}",
                dpnl=f"{d_pnl:+.2f}",
                dror=fmt_num(d_ror) if not math.isfinite(d_ror) else f"{d_ror:+.1f}",
                ddd=fmt_num(d_dd) if not math.isfinite(d_dd) else f"{d_dd:+.2f}",
                dsheet=format_money_delta(d_sheet),
                verdict=html_mod.escape(p["verdict"]),
                why=html_mod.escape(p["why"]),
                mix=html_mod.escape(m["exit_mix"]),
            )
        )

    # IS/OOS table
    body_split = []
    for p in packs:
        for slice_name, key in (("Full", "full"), ("IS", "is"), ("OOS", "oos")):
            m = p[key]
            body_split.append(
                "<tr class='{cls}'><td>{arm}</td><td>{sl}</td><td>{n}</td><td>{wr}</td>"
                "<td>{avg}</td><td>{avgr}</td><td>{ror}</td><td>{dd}</td><td>{pf}</td><td>{sheet}</td></tr>".format(
                    cls=row_class(p["verdict"]),
                    arm=html_mod.escape(p["arm"]),
                    sl=slice_name,
                    n=m["n_signals"],
                    wr=fmt_num(m["win_rate"] * 100, 1),
                    avg=fmt_num(m["avg_pnl_pct"]),
                    avgr=fmt_num(m["avg_r"]),
                    ror=fmt_num(m["ann_ror"]),
                    dd=fmt_num(m["max_dd"]),
                    pf=fmt_num(m["pf"]),
                    sheet=format_money(m["sheet_pnl"]),
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
            sortable_th("PF", "num"),
            sortable_th("Sheet PnL $", "num"),
            sortable_th("AvgDays", "num"),
            sortable_th("ΔN", "num"),
            sortable_th("ΔWR pp", "num"),
            sortable_th("ΔAvgR", "num"),
            sortable_th("ΔPnL%", "num"),
            sortable_th("ΔAnnROR pp", "num"),
            sortable_th("ΔMaxDD pp", "num"),
            sortable_th("ΔSheet $", "num"),
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
            sortable_th("PF", "num"),
            sortable_th("Sheet PnL $", "num"),
        ]
    )

    rec_cls = "hold"
    if "LEAN KEEP" in recommendation or recommendation.startswith("KEEP"):
        rec_cls = "keep"
    if "DISMISS" in recommendation and "LEAN KEEP" not in recommendation and "KEEP" not in recommendation.split("\n")[0]:
        # keep hold/default unless clearly adopt
        pass

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VZ ImprovePriority AB — vz_improve_ab_20260821</title>
<style>
  body {{ margin:0; padding:28px; font-family:"Segoe UI",Georgia,serif; background:#fafaf8; color:#1a1a18; }}
  .wrap {{ max-width:1600px; margin:0 auto; }}
  h1 {{ font-size:1.45rem; }}
  h2 {{ font-size:1.15rem; margin-top:1.8rem; }}
  .muted {{ color:#5c5c56; }}
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
  <h1>VZ ImprovePriority AB — vz_improve_ab_20260821</h1>
  <p class="muted">
    Research only (not gold / not DailyRun). Control = house pin
    <code>{HOUSE_STAMP}</code> / VZ_new56 Closed overlay.
    Freeze: HL-only, first_retest, mt≥1, eps=0.005, lookback=126, rw=63,
    <code>EXIT_atr4_s025_r15</code>, HVN false, long.
    IS = entry &lt; 2024-01-01; OOS report-only. Click column headers to sort.
    Canonical metrics + Ann ROR + Max DD (Closed overlay $45k / $500k DD seed).
  </p>

  <div class="rec {rec_cls}">
    <strong>Recommendation</strong>
    <pre style="white-space:pre-wrap;margin:0.6rem 0 0;font-family:inherit">{html_mod.escape(recommendation)}</pre>
  </div>

  <h2>One-knob arms vs freeze (full book)</h2>
  <p class="muted">Click column headers to sort. Judge quality over count.</p>
  <table class="sortable"><thead><tr>{th_full}</tr></thead><tbody>
  {''.join(body_full)}
  </tbody></table>

  <h2>IS / OOS / Full (Closed overlay)</h2>
  <p class="muted">OOS is report-only — do not retune if OOS softens.</p>
  <table class="sortable"><thead><tr>{th_split}</tr></thead><tbody>
  {''.join(body_split)}
  </tbody></table>

  <h2>Deferred</h2>
  <ul class="muted">
    <li>Band tighten / mt≥2 — live entry re-sim; prior DISMISS</li>
    <li>SPY SMA200 regime — prior DISMISS</li>
    <li>Trail BE / partial — prior DISMISS / untestable</li>
    <li>HVN / taller zones / short — prior HOLDs</li>
  </ul>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    out_path.write_text(html, encoding="utf-8")


def adopt_gate_hold(p: dict[str, Any], ctrl: dict[str, Any]) -> Optional[str]:
    """Return HOLD reason when capital-efficiency / OOS gates block adopt."""
    m, c = p["full"], ctrl["full"]
    o, co = p["oos"], ctrl["oos"]
    if oos_softens(o, co):
        return "OOS softens vs control OOS — HOLD (do not adopt / do not retune OOS)"
    d_ror = m["ann_ror"] - c["ann_ror"] if math.isfinite(m["ann_ror"]) and math.isfinite(c["ann_ror"]) else 0.0
    d_dd = m["max_dd"] - c["max_dd"] if math.isfinite(m["max_dd"]) and math.isfinite(c["max_dd"]) else 0.0
    # Wider-stop / capital: Ann ROR down a lot with Max DD worse → adopt HOLD (prior atr10 gate pattern)
    if p["arm"].startswith("EXIT_stop_atr") and d_ror <= -40.0 and d_dd >= 2.0:
        return (
            f"Adopt gate HOLD: Ann ROR Δ{d_ror:.1f}pp and Max DD Δ{d_dd:+.2f}pp vs freeze "
            "(trade PnL% lift not enough for house pin)"
        )
    return None


def recommend(packs: list[dict[str, Any]]) -> str:
    ctrl = next(p for p in packs if p["arm"] == "00_freeze")
    lines: list[str] = []
    keeps = [p for p in packs if p["verdict"] in ("KEEP", "LEAN KEEP")]

    final_keeps: list[dict[str, Any]] = []
    for p in keeps:
        gate = adopt_gate_hold(p, ctrl)
        if gate:
            p["verdict"] = "HOLD"
            p["why"] = p["why"] + " | " + gate
            lines.append(f"{p['arm']}: full-book LEAN KEEP -> HOLD after adopt gate.")
        else:
            final_keeps.append(p)

    # House freeze recommendation
    lines.insert(
        0,
        "Overall house freeze: **HOLD pin** "
        f"`{HOUSE_STAMP}` / VZ_new56 / `EXIT_atr4_s025_r15` — do not replace pin this stamp.",
    )
    if final_keeps:
        names = ", ".join(p["arm"] for p in final_keeps)
        lines.append(
            f"Research LEAN KEEP (not gold / not DailyRun / not auto-pin): {names}."
        )
    else:
        lines.append(
            "No clear one-knob LEAN KEEP that also passes Ann ROR / Max DD / OOS adopt gates."
        )

    lines.append(
        f"HOLD count: {len([p for p in packs if p['verdict']=='HOLD'])}; "
        f"DISMISS count: {len([p for p in packs if p['verdict']=='DISMISS'])}; "
        f"LEAN KEEP count: {len([p for p in packs if p['verdict'] in ('KEEP','LEAN KEEP')])}."
    )
    lines.append(
        "Selection bias labeled (ImprovePriority → arms on same new56 Closed). "
        "Research only — not gold / not DailyRun."
    )
    for p in packs:
        if p["arm"] == "00_freeze":
            continue
        m, c = p["full"], ctrl["full"]
        lines.append(
            f"  - {p['arm']}: {p['verdict']} — WR {m['win_rate']*100:.1f}% "
            f"(d{(m['win_rate']-c['win_rate'])*100:+.1f}pp) AvgPnL% {m['avg_pnl_pct']:.2f} "
            f"(d{m['avg_pnl_pct']-c['avg_pnl_pct']:+.2f}) AnnROR {fmt_num(m['ann_ror'])} "
            f"MaxDD {fmt_num(m['max_dd'])} | OOS WR {p['oos']['win_rate']*100:.1f}% "
            f"Avg {p['oos']['avg_pnl_pct']:.2f}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--closed", type=Path, default=CLOSED_PATH)
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    print(f"Loading Closed {args.closed}")
    base = load_house_closed(args.closed)
    print(f"  trades={len(base)}")
    if not base:
        print("ERROR: no trades")
        return 1

    # Control = house Closed as-is (authoritative pin metrics)
    ctrl_trades = [
        {
            **t,
            "stop": t.get("stop_house"),
            "target": t.get("target_house"),
        }
        for t in base
    ]

    packs: list[dict[str, Any]] = []

    def add_pack(
        arm: str,
        kind: str,
        knob: str,
        hypothesis: str,
        trades: list[dict[str, Any]],
    ) -> None:
        full = metrics_pack(trades)
        is_rows, oos_rows = split_trades(trades)
        is_m = metrics_pack(is_rows)
        oos_m = metrics_pack(oos_rows)
        ctrl_full = packs[0]["full"] if packs else full
        verdict, why = score_arm(arm, full, ctrl_full)
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
            f"  {arm}: N={full['n_signals']} WR={full['win_rate']*100:.1f}% "
            f"Avg={full['avg_pnl_pct']:.2f} ROR={fmt_num(full['ann_ror'])} "
            f"DD={fmt_num(full['max_dd'])} -> {verdict}"
        )

    add_pack(
        "00_freeze",
        "CONTROL",
        "EXIT_atr4_s025_r15 house Closed",
        "baseline",
        ctrl_trades,
    )

    for arm in EXIT_ARMS:
        print(f"Replaying {arm.name}…")
        trades = apply_exit_arm(base, arm)
        add_pack(arm.name, "EXIT", arm.label, arm.hypothesis, trades)

    print("Filtering ENTRY_cd_target10…")
    cd_trades = filter_cd_target10(ctrl_trades, cooldown_days=10)
    add_pack(
        "ENTRY_cd_target10",
        "ENTRY",
        "Skip entries ≤10d after TARGET exit (same symbol)",
        "post_target_quick_stop",
        cd_trades,
    )

    # Re-score after all packs exist (ctrl known); re-apply OOS gate inside recommend
    ctrl_full = packs[0]["full"]
    for p in packs[1:]:
        v, w = score_arm(p["arm"], p["full"], ctrl_full)
        p["verdict"], p["why"] = v, w

    rec = recommend(packs)
    # recommend may mutate verdicts for OOS soften
    write_html = out / "compare.html"
    build_html(write_html, packs=packs, recommendation=rec)

    # metrics.csv
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
            "PF",
            "Sheet_PnL",
            "AvgDays",
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
                        "PF": round(m["pf"], 4),
                        "Sheet_PnL": round(m["sheet_pnl"], 2),
                        "AvgDays": round(m["avg_days"], 3),
                        "why": p["why"],
                    }
                )

    # Append / refresh recommendation on BASELINE
    base_md = out / "BASELINE.md"
    if base_md.exists():
        text = base_md.read_text(encoding="utf-8")
        marker = "\n## Auto results\n"
        if marker in text:
            text = text.split(marker)[0].rstrip() + "\n"
        text += marker + "\n```\n" + rec + "\n```\n"
        base_md.write_text(text, encoding="utf-8")

    print("\n=== RECOMMENDATION ===")
    print(rec)
    print(f"\nWrote {write_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
