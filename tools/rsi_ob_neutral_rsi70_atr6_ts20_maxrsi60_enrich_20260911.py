#!/usr/bin/env python3
"""Enrich CONTROL Closed for rsi_ob_neutral_rsi70_atr6_ts20_maxrsi60_20260911 + correlation.

Reads closed_fulluniv.csv (CONTROL alias) under the stamp, writes RSIN_* artifacts.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "stock_analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "stock_analysis"))

from rocket_tbn import (  # noqa: E402
    BRTConfig,
    BRTTrade,
    _bar_index_on_or_before,
    _compute_sma_arr,
    _enrich_symbol_ohlc_features,
    _high_52w_and_dist_pct,
    _load_symbol_data,
    _precomputed_sma_arr_from_df,
    _rel_vol_at_bar,
    _rsi14_ob_os_label,
    _sma_at_bar,
    _trade_ymd_to_bar_index,
    _wilder_rsi14_arr,
    write_brt_summary,
)
from correlate_brt_closed import run_correlation_report  # noqa: E402

STAMP_DIR = ROOT / "drive" / "paul_experiments" / "rsi_ob_neutral_rsi70_atr6_ts20_maxrsi60_20260911"
SRC = STAMP_DIR / "closed_fulluniv.csv"
OUT_CLOSED = STAMP_DIR / "RSIN_Closed_20260911.csv"
OUT_SUMMARY = STAMP_DIR / "RSIN_Summary_20260911.csv"
OUT_CORR = STAMP_DIR / "RSIN_Correlation_20260911.csv"
OUT_CORR_IS = STAMP_DIR / "RSIN_Correlation_IS_20260911.csv"
DRIVE_CLOSED = ROOT / "drive" / "RSIN_LatestRun_Closed.csv"
DATA_DIR = ROOT / "data" / "newdata" / "data"
IS_CUT = pd.Timestamp("2024-01-01")
NOTIONAL = 10_000.0
DAYS_PER_YEAR = 365.0
RSI_OB = 70.0


def _iso_list(df: pd.DataFrame) -> list[str]:
    return [
        (d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d)[:10].replace("-", ""))
        for d in df.index
    ]


def _fmt(v: object, nd: int = 4) -> str:
    if v is None:
        return ""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(fv):
        return ""
    return f"{fv:.{nd}f}"


def _ann_ror(pnl_pct: float, days: int) -> str:
    if days <= 0:
        return ""
    base = 1.0 + pnl_pct / 100.0
    if base <= 0:
        return ""
    return f"{((base ** (DAYS_PER_YEAR / days) - 1.0) * 100.0):.2f}%"


def enrich_symbol(sym: str, rows: list[dict], spy_df: Optional[pd.DataFrame]) -> list[dict]:
    df = None
    try:
        df = _load_symbol_data(sym, DATA_DIR)
    except Exception:
        df = None
    if df is None or df.empty:
        return []

    stubs: list[BRTTrade] = []
    for r in rows:
        t = BRTTrade(
            symbol=sym,
            date_opened=str(r.get("DATE_OPENED") or ""),
            entry_price=float(r.get("ENTRY_PRICE") or 0) or 0.0,
            stop_price=0.0,
            target_price=0.0,
            date_closed=str(r.get("DATE_CLOSED") or ""),
            exit_price=float(r.get("EXIT_PRICE") or 0) or 0.0,
            exit_type=str(r.get("EXIT_TYPE") or ""),
            days_held=int(float(r.get("DAYS_HELD") or 0) or 0),
            pnl_pct=float(r.get("PNL_PCT") or 0) or 0.0,
            pnl_dollars=float(r.get("PNL_DOLLARS") or 0) or 0.0,
        )
        t.signal_date = str(r.get("SIGNAL_DATE") or "")
        stubs.append(t)

    _enrich_symbol_ohlc_features(sym, stubs, df, BRTConfig(), spy_df)

    close = df["Close"].to_numpy(dtype=np.float64)
    high = df["High"].to_numpy(dtype=np.float64) if "High" in df.columns else close
    vol = df["Volume"].to_numpy(dtype=np.float64) if "Volume" in df.columns else None
    rsi = _wilder_rsi14_arr(close)
    index_iso = _iso_list(df)
    n = len(close)
    sma20 = _precomputed_sma_arr_from_df(df, "SMA20")
    if sma20 is None:
        sma20 = _compute_sma_arr(close, 20)
    sma50 = _precomputed_sma_arr_from_df(df, "SMA50")
    if sma50 is None:
        sma50 = _compute_sma_arr(close, 50)
    sma100 = _precomputed_sma_arr_from_df(df, "SMA100")
    if sma100 is None:
        sma100 = _compute_sma_arr(close, 100)

    out: list[dict] = []
    for r, t in zip(rows, stubs):
        entry_bar = int(getattr(t, "entry_bar_index", -1) or -1)
        if entry_bar < 0:
            mapped = _bar_index_on_or_before(index_iso, str(r.get("DATE_OPENED") or ""))
            entry_bar = int(mapped) if mapped is not None else -1
        trig_bar = -1
        sig = str(r.get("SIGNAL_DATE") or "")
        if sig:
            mapped = _trade_ymd_to_bar_index(index_iso, sig)
            if mapped is None:
                mapped = _bar_index_on_or_before(index_iso, sig)
            if mapped is not None:
                trig_bar = int(mapped)
        if trig_bar < 0:
            trig_bar = entry_bar - 1 if entry_bar > 0 else entry_bar

        exit_bar = _bar_index_on_or_before(index_iso, str(r.get("DATE_CLOSED") or ""))
        exit_bar = int(exit_bar) if exit_bar is not None else -1

        max_px = float("nan")
        hit10 = 0
        if entry_bar >= 0 and exit_bar >= entry_bar:
            sl = high[entry_bar : exit_bar + 1]
            if sl.size:
                max_px = float(np.nanmax(sl))
                ep = float(r.get("ENTRY_PRICE") or 0) or 0.0
                if ep > 0 and max_px >= ep * 1.10:
                    hit10 = 1

        prior_ob = float("nan")
        if trig_bar > 0:
            for j in range(trig_bar - 1, -1, -1):
                v = float(rsi[j])
                if np.isfinite(v) and v >= RSI_OB:
                    prior_ob = v
                    break
        trig_rsi = float(getattr(t, "rsi14_at_trigger", None) or float("nan"))
        if not np.isfinite(trig_rsi) and 0 <= trig_bar < n:
            trig_rsi = float(rsi[trig_bar])
        rsi_drop = (prior_ob - trig_rsi) if np.isfinite(prior_ob) and np.isfinite(trig_rsi) else float("nan")

        cl = float(close[trig_bar]) if 0 <= trig_bar < n else float("nan")
        s20 = _sma_at_bar(sma20, trig_bar)
        s50 = _sma_at_bar(sma50, trig_bar)
        s100 = _sma_at_bar(sma100, trig_bar)

        def vs_sma(sma: Optional[float]) -> float:
            if sma is None or not np.isfinite(cl) or sma <= 0:
                return float("nan")
            return (cl / sma - 1.0) * 100.0

        days = int(float(r.get("DAYS_HELD") or 0) or 0)
        pnl = float(r.get("PNL_PCT") or 0) or 0.0
        row = {
            "SYMBOL": sym,
            "SIDE": "LONG",
            "DATE_OPENED": str(r.get("DATE_OPENED") or ""),
            "ENTRY_PRICE": r.get("ENTRY_PRICE") or "",
            "STOP_PRICE": "",
            "TARGET_PRICE": "",
            "DATE_CLOSED": str(r.get("DATE_CLOSED") or ""),
            "EXIT_PRICE": r.get("EXIT_PRICE") or "",
            "EXIT_TYPE": r.get("EXIT_TYPE") or "",
            "DAYS_HELD": days,
            "PNL_PCT": f"{pnl:.4f}%",
            "PNL_DOLLARS": f"{float(r.get('PNL_DOLLARS') or 0):.2f}",
            "ANN_ROR_PCT": _ann_ror(pnl, days),
            "MAX_PRICE": _fmt(max_px, 4),
            "POST_ENTRY_GAIN_HIT": hit10,
            "SIGNAL_DATE": sig,
            "RSI14_AT_ENTRY": _fmt(getattr(t, "rsi14_at_entry", None), 2),
            "RSI14_AT_TRIGGER": _fmt(trig_rsi, 2),
            "RSI14_AT_EXIT": r.get("RSI14_AT_EXIT") or "",
            "RSI14_OB_OS": _rsi14_ob_os_label(trig_rsi) if np.isfinite(trig_rsi) else "",
            "RSI14_PRIOR_OB": _fmt(prior_ob, 2),
            "RSI14_DROP_FROM_OB": _fmt(rsi_drop, 2),
            "ATR_14_AT_TRIGGER": _fmt(getattr(t, "atr_14_at_trigger", None), 4),
            "ATR_PCT_AT_TRIGGER": (
                f"{float(t.atr_pct_at_trigger):.2f}%"
                if getattr(t, "atr_pct_at_trigger", None) is not None
                else ""
            ),
            "REL_VOL_ON_TRIGGER": _fmt(getattr(t, "rel_vol_on_trigger", None), 4),
            "Z_SCORE_AT_TRIGGER": _fmt(getattr(t, "z_score_at_trigger", None), 4),
            "UPPER_WICK_ATR_AT_TRIGGER": _fmt(getattr(t, "upper_wick_atr_at_trigger", None), 4),
            "LOWER_WICK_ATR_AT_TRIGGER": _fmt(getattr(t, "lower_wick_atr_at_trigger", None), 4),
            "IS_20BAR_HIGH_AT_TRIGGER": int(getattr(t, "is_20bar_high_at_trigger", 0) or 0),
            "IS_20BAR_LOW_AT_TRIGGER": int(getattr(t, "is_20bar_low_at_trigger", 0) or 0),
            "MOVE_BODY_ATR_AT_TRIGGER": _fmt(getattr(t, "move_body_atr_at_trigger", None), 4),
            "SMA20_AT_TRIGGER": _fmt(s20, 4),
            "SMA50_AT_TRIGGER": _fmt(s50, 4),
            "SMA100_AT_TRIGGER": _fmt(s100, 4),
            "CLOSE_VS_SMA20_PCT": _fmt(vs_sma(s20), 2),
            "CLOSE_VS_SMA50_PCT": _fmt(vs_sma(s50), 2),
            "CLOSE_VS_SMA100_PCT": _fmt(vs_sma(s100), 2),
            "HIGH_52W_AT_TRIGGER": _fmt(getattr(t, "high_52w_at_trigger", None), 2),
            "DIST_TO_52W_HIGH_PCT_AT_TRIGGER": (
                f"{float(t.dist_to_52w_high_pct_at_trigger):.2f}%"
                if getattr(t, "dist_to_52w_high_pct_at_trigger", None) is not None
                else ""
            ),
            "HAD_METEORIC_RISE_BEFORE_ENTRY": int(getattr(t, "had_meteoric_rise_before_entry", 0) or 0),
            "HAD_METEORIC_FALL_BEFORE_ENTRY": int(getattr(t, "had_meteoric_fall_before_entry", 0) or 0),
            "SPY_COMPARE_1Y": _fmt(getattr(t, "spy_compare_1y", None), 4),
            "SPY_COMPARE_2Y": _fmt(getattr(t, "spy_compare_2y", None), 4),
            "SPY_COMPARE_3Y": _fmt(getattr(t, "spy_compare_3y", None), 4),
            "TRADING_DAYS_SINCE_LAST_ATH_AT_ENTRY": int(
                getattr(t, "trading_days_since_last_ath_at_entry", 0) or 0
            ),
        }
        if vol is not None and 0 <= trig_bar < n:
            row["REL_VOL_ON_TRIGGER"] = _fmt(_rel_vol_at_bar(vol, trig_bar), 4)
        if getattr(t, "high_52w_at_trigger", None) is None and 0 <= trig_bar < n:
            hi52, dist = _high_52w_and_dist_pct(high, trig_bar, cl)
            row["HIGH_52W_AT_TRIGGER"] = _fmt(hi52, 2)
            row["DIST_TO_52W_HIGH_PCT_AT_TRIGGER"] = f"{dist:.2f}%" if dist is not None else ""
        out.append(row)
    return out


def write_summary_from_closed(closed_rows: list[dict], path: Path) -> None:
    stubs: list[BRTTrade] = []
    for r in closed_rows:
        pnl_s = str(r.get("PNL_PCT") or "").replace("%", "")
        try:
            pnl = float(pnl_s)
        except ValueError:
            pnl = 0.0
        try:
            dollars = float(r.get("PNL_DOLLARS") or 0)
        except ValueError:
            dollars = 0.0
        stubs.append(
            BRTTrade(
                symbol=str(r.get("SYMBOL") or ""),
                date_opened=str(r.get("DATE_OPENED") or ""),
                entry_price=0.0,
                stop_price=0.0,
                target_price=0.0,
                date_closed=str(r.get("DATE_CLOSED") or ""),
                days_held=int(float(r.get("DAYS_HELD") or 0) or 0),
                pnl_pct=pnl,
                pnl_dollars=dollars,
            )
        )
    cfg = BRTConfig()
    cfg.brt_cash = NOTIONAL
    write_brt_summary(stubs, str(path), cfg=cfg, data_dir=DATA_DIR)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not SRC.is_file():
        print(f"ERROR missing {SRC}", flush=True)
        return 1
    raw = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        by_sym[str(r.get("SYMBOL") or "").strip().upper()].append(r)
    spy_df = None
    try:
        spy_df = _load_symbol_data("SPY", DATA_DIR)
    except Exception:
        spy_df = None

    closed: list[dict] = []
    syms = sorted(s for s in by_sym if s)
    for i, sym in enumerate(syms, 1):
        closed.extend(enrich_symbol(sym, by_sym[sym], spy_df))
        if i % 50 == 0 or i == len(syms):
            print(f"  enrich {i}/{len(syms)} rows={len(closed)}", flush=True)

    if not closed:
        print("ERROR no enriched rows", flush=True)
        return 1

    fields = list(closed[0].keys())
    STAMP_DIR.mkdir(parents=True, exist_ok=True)
    for dest in (OUT_CLOSED, DRIVE_CLOSED):
        with dest.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(closed)
        print(f"Wrote {dest}  n={len(closed)}", flush=True)

    write_summary_from_closed(closed, OUT_SUMMARY)
    print(f"Wrote {OUT_SUMMARY}", flush=True)

    run_correlation_report(str(OUT_CLOSED), str(OUT_CORR))
    print(f"Wrote {OUT_CORR}", flush=True)

    is_rows = [
        r for r in closed
        if pd.to_datetime(r.get("DATE_OPENED"), errors="coerce") is not pd.NaT
        and pd.to_datetime(r["DATE_OPENED"]) < IS_CUT
    ]
    is_tmp = STAMP_DIR / "_tmp_closed_is.csv"
    with is_tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(is_rows)
    run_correlation_report(str(is_tmp), str(OUT_CORR_IS))
    try:
        is_tmp.unlink()
    except OSError:
        pass
    print(f"Wrote {OUT_CORR_IS}  IS n={len(is_rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
