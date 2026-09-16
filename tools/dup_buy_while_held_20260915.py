#!/usr/bin/env python3
"""Scan live Closed books for same-symbol overlapping holds / same-day dups.

Research stamp only. Writes drive/paul_experiments/dup_buy_while_held_20260915/.
Does not mutate house pins or rsi_universe.csv.
"""
from __future__ import annotations

import html as html_mod
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
DRIVE = REPO / "drive"
STAMP = "dup_buy_while_held_20260915"
OUT = DRIVE / "paul_experiments" / STAMP
IS_CUT = date(2024, 1, 1)
VZ_CASH = 45_000.0  # house sheet notional
VZ_INIT = 500_000.0
# Before-book pin for extras overlay. Current house/LatestRun may already be gated.
# Do not overwrite VZ_LatestRun_Closed.csv.
BEFORE_VZ_CLOSED = "VZ_Closed_260915143939.csv"

_CF = REPO / "drive" / "paul_experiments"
if str(_CF) not in sys.path:
    sys.path.insert(0, str(_CF))
from compare_format import (  # noqa: E402
    format_money,
    format_money_delta,
    overlay_ann_ror_max_dd,
)

ASK = (
    "I'm looking at VZ_LatestRun_Closed and it appears we are entering a purchase "
    "multiple times.\n"
    "GOLD\tLONG\t20200506\t6.92\t6.38\t7.74\t20200508\t7.74\tTARGET\t2\t11.82%\n"
    "GOLD\tLONG\t20200506\t6.92\t6.07\t8.21\t20200508\t8.21\tTARGET\t2\t18.54%\n"
    "if we already own a stock, there should not be a new buy for the stock. "
    "can you investigate VZ and all other systems for this error?"
)

LAYMAN = (
    "If we already own GOLD, we should not buy GOLD again. Two Closed rows on the "
    "same open date look like a double ticket. Check Volatility Zone (VZ) first, "
    "then every other live system."
)

ASK2 = (
    "also, how did we perform when there was >1 buy due to multiple zones? "
    "did performance improve?"
)

LAYMAN2 = (
    "When two Volatility Zone (VZ) bands both filled, was that second ticket a "
    "good trade or just extra risk? Compare first-only vs extras vs the full old book."
)

WANTED = (
    "BRT",
    "RL",
    "YH",
    "MTS",
    "WPBR",
    "RS",
    "SB",
    "VZ",
    "RSI",
    "IND",
    "WRL",
    "TBN",
)

ENGINE = {
    "VZ": (
        "Live bug (fixed this stamp). rocket_vz.enrich_trade_rows simulated each "
        "zone signal independently. TBN host one-position gate was bypassed because "
        "vz_mode calls run_vz_from_brt_main, not the TBN bar loop. Not regular vs "
        "aggressive (Aggressive is equity overlay only)."
    ),
    "RSI": (
        "OK. rocket_rsi.backtest_symbol is a one-position state machine "
        "(pos is not None → no new buy)."
    ),
    "BRT": "OK. TBN bar-scan: skip if open_trade is set (allow_secondary_entries default false).",
    "YH": "OK. TBN bar-scan one-position gate.",
    "MTS": "OK. TBN bar-scan one-position gate.",
    "WPBR": "OK. TBN bar-scan one-position gate (plus WPBR zone-used lock).",
    "RS": "OK. TBN bar-scan one-position gate.",
    "SB": "OK. TBN bar-scan one-position gate.",
    "RL": "OK. TBN / rocket_rl host path; one open_trade per symbol.",
    "IND": "Deprecated sleeve. TBN bar-scan one-position gate if Closed exists.",
    "WRL": "Research sleeve (not DailyRun gold). Check Closed if present.",
    "TBN": "Host prefix — no separate TBN Closed book expected.",
}


def _read_ts(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip().splitlines()[0].strip()


def _ymd(raw: object) -> str:
    text = str(raw or "").strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    compact = re.sub(r"\D", "", text)
    return compact[:8] if len(compact) >= 8 else ""


def _date(raw: object) -> Optional[date]:
    ymd = _ymd(raw)
    if len(ymd) != 8:
        return None
    try:
        return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    except ValueError:
        return None


def _col(frame: pd.DataFrame, *names: str) -> Optional[str]:
    upper = {str(c).strip().upper(): c for c in frame.columns}
    for n in names:
        if n.upper() in upper:
            return upper[n.upper()]
    return None


def _f(raw: object) -> Optional[float]:
    text = str(raw or "").strip().replace("%", "").replace(",", "")
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def resolve_closed(drive: Path, system: str) -> Optional[Path]:
    sys = system.upper()
    if sys in {"VZ", "RSI"}:
        ts = _read_ts(drive / f"{sys}_house_last_run_ts.txt")
        if ts:
            house = drive / f"{sys}_Closed_{ts}.csv"
            if house.is_file():
                return house
    latest = drive / f"{sys}_LatestRun_Closed.csv"
    if latest.is_file():
        return latest
    if sys == "WPBR":
        legacy = drive / "PBR_LatestRun_Closed.csv"
        if legacy.is_file():
            return legacy
    if sys == "RL":
        mirrors = sorted(
            drive.glob("BRT_Closed_RL_*.csv"),
            key=lambda p: (p.stat().st_mtime_ns, p.name),
            reverse=True,
        )
        if mirrors:
            return mirrors[0]
    if sys == "WRL":
        ts = _read_ts(drive / "WRL_last_run_ts.txt")
        if ts:
            p = drive / f"WRL_Closed_{ts}.csv"
            if p.is_file():
                return p
    return None


def extra_closed(drive: Path, already: set[Path]) -> list[tuple[str, Path]]:
    extra: list[tuple[str, Path]] = []
    for path in sorted(drive.glob("*_LatestRun_Closed.csv")):
        m = re.match(r"^([A-Za-z]+)_LatestRun_Closed\.csv$", path.name, re.I)
        if not m:
            continue
        prefix = m.group(1).upper()
        if prefix in {"PBR", "RSIN", "QULL", "KELL", "CS", "MVCP", "DB"}:
            continue
        if prefix in WANTED:
            continue
        if path.resolve() in already:
            continue
        extra.append((prefix, path))
    return extra


def load_rows(path: Path) -> list[dict[str, Any]]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    sym_c = _col(frame, "SYMBOL")
    open_c = _col(frame, "DATE_OPENED", "DATE OPENED")
    close_c = _col(frame, "DATE_CLOSED", "DATE CLOSED")
    entry_c = _col(frame, "ENTRY_PRICE", "ENTRY PRICE")
    stop_c = _col(frame, "STOP_PRICE", "STOP PRICE")
    tgt_c = _col(frame, "TARGET_PRICE", "TARGET PRICE")
    exit_c = _col(frame, "EXIT_PRICE", "EXIT PRICE")
    exit_t = _col(frame, "EXIT_TYPE", "EXIT TYPE")
    days_c = _col(frame, "DAYS_HELD", "DAYS HELD")
    pct_c = _col(frame, "PNL_PCT", "PNL %")
    dol_c = _col(frame, "PNL_DOLLARS", "PNL $")
    zone_c = _col(frame, "ZONE_ID")
    zlo_c = _col(frame, "ZONE_LO")
    brk_c = _col(frame, "BREAK_DATE", "BREAKOUT_DATE")
    ind_c = _col(frame, "INDUSTRY")
    if sym_c is None or open_c is None:
        return []
    out: list[dict[str, Any]] = []
    for i, rec in enumerate(frame.to_dict("records")):
        opened = _date(rec.get(open_c))
        if opened is None:
            continue
        closed = _date(rec.get(close_c)) if close_c else None
        out.append(
            {
                "i": i,
                "symbol": str(rec.get(sym_c) or "").strip().upper(),
                "opened": opened,
                "closed": closed,
                "entry": _f(rec.get(entry_c)) if entry_c else None,
                "stop": _f(rec.get(stop_c)) if stop_c else None,
                "target": _f(rec.get(tgt_c)) if tgt_c else None,
                "exit": _f(rec.get(exit_c)) if exit_c else None,
                "exit_type": str(rec.get(exit_t) or "").strip() if exit_t else "",
                "days": _f(rec.get(days_c)) if days_c else None,
                "pnl_pct": _f(rec.get(pct_c)) if pct_c else None,
                "pnl_d": _f(rec.get(dol_c)) if dol_c else None,
                "industry": str(rec.get(ind_c) or "").strip() if ind_c else "",
                "zone_id": str(rec.get(zone_c) or "").strip() if zone_c else "",
                "zone_lo": _f(rec.get(zlo_c)) if zlo_c else None,
                "break_date": _ymd(rec.get(brk_c)) if brk_c else "",
                "raw": rec,
            }
        )
    return out


def scan_book(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["symbol"]:
            by_sym[r["symbol"]].append(r)

    same_open_groups = 0
    same_open_extra = 0
    same_open_ex: list[dict[str, Any]] = []
    overlap_fills = 0
    overlap_ex: list[dict[str, Any]] = []

    for sym, items in by_sym.items():
        items = sorted(
            items,
            key=lambda r: (
                r["opened"],
                r["closed"] or date.max,
                r["zone_id"],
                r["stop"] if r["stop"] is not None else 0.0,
                r["i"],
            ),
        )
        by_open: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for r in items:
            by_open[r["opened"]].append(r)
        for od, grp in by_open.items():
            if len(grp) > 1:
                same_open_groups += 1
                same_open_extra += len(grp) - 1
                if len(same_open_ex) < 8:
                    same_open_ex.append(
                        {
                            "symbol": sym,
                            "opened": od.isoformat(),
                            "n": len(grp),
                            "stops": ", ".join(
                                f"{x['stop']:.2f}" if x["stop"] is not None else ""
                                for x in grp
                            ),
                            "targets": ", ".join(
                                f"{x['target']:.2f}" if x["target"] is not None else ""
                                for x in grp
                            ),
                            "zones": ", ".join(x["zone_id"] or "—" for x in grp),
                        }
                    )

        held_until: Optional[date] = None
        held_row: Optional[dict[str, Any]] = None
        for r in items:
            if held_until is not None and r["opened"] <= held_until:
                overlap_fills += 1
                if len(overlap_ex) < 8:
                    overlap_ex.append(
                        {
                            "symbol": sym,
                            "a_open": held_row["opened"].isoformat() if held_row else "",
                            "a_close": held_until.isoformat(),
                            "b_open": r["opened"].isoformat(),
                            "b_close": r["closed"].isoformat() if r["closed"] else "",
                            "a_stop": held_row["stop"] if held_row else None,
                            "b_stop": r["stop"],
                            "a_zone": (held_row or {}).get("zone_id", ""),
                            "b_zone": r["zone_id"],
                        }
                    )
                continue
            held_until = r["closed"]
            held_row = r

    return {
        "n": len(rows),
        "same_open_groups": same_open_groups,
        "same_open_extra": same_open_extra,
        "overlap_fills": overlap_fills,
        "same_open_ex": same_open_ex,
        "overlap_ex": overlap_ex,
    }


def keep_one_position(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for items in by_sym.values():
        items = sorted(
            items,
            key=lambda r: (
                r["opened"],
                r["closed"] or date.max,
                r.get("break_date") or "",
                r["zone_id"],
                r["stop"] if r["stop"] is not None else 0.0,
                r["i"],
            ),
        )
        held_until: Optional[date] = None
        for r in items:
            if held_until is not None and r["opened"] <= held_until:
                dropped.append(r)
                continue
            kept.append(r)
            held_until = r["closed"]
    return kept, dropped


def book_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pcts = [r["pnl_pct"] for r in rows if r["pnl_pct"] is not None]
    return {
        "n": len(rows),
        "avg_pct": (sum(pcts) / len(pcts)) if pcts else None,
    }


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _losing_streak(rows: list[dict[str, Any]]) -> int:
    ordered = sorted(
        rows, key=lambda r: (r["closed"] or r["opened"] or date.min, r.get("i") or 0)
    )
    streak = 0
    worst = 0
    for r in ordered:
        p = r.get("pnl_pct")
        if p is None:
            continue
        if p < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return worst


def _position_stats(rows: list[dict[str, Any]]) -> tuple[Optional[float], Optional[float], Optional[int]]:
    events: list[tuple[date, int]] = []
    for r in rows:
        if r.get("opened") is None:
            continue
        events.append((r["opened"], 1))
        if r.get("closed") is not None:
            events.append((r["closed"], -1))
    if not events:
        return None, None, None
    events.sort(key=lambda x: (x[0], -x[1]))
    cur = 0
    samples: list[int] = []
    peak = 0
    for _d, delta in events:
        cur += delta
        samples.append(cur)
        if cur > peak:
            peak = cur
    samples_sorted = sorted(samples)
    avg = sum(samples) / len(samples)
    med = float(samples_sorted[len(samples_sorted) // 2])
    return avg, med, peak


def _exit_mix(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = Counter()
    for r in rows:
        raw = str(r.get("exit_type") or "").strip().upper() or "?"
        if raw in {"STOP", "STOP_LOSS", "SL"}:
            raw = "STOP_LOSS"
        elif raw in {"TIME", "TIME_STOP", "TS"}:
            raw = "TIME"
        counts[raw] += 1
    return dict(counts)


def overlay_book(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    empty = {
        "n": 0,
        "wins": 0,
        "losses": 0,
        "be": 0,
        "win_pct": None,
        "avg_pct": None,
        "wo_max": None,
        "expectancy_pct": None,
        "expectancy_d": None,
        "avg_win": None,
        "avg_loss": None,
        "wl_count": None,
        "wl_dollar": None,
        "pf": None,
        "ann_ror": None,
        "max_dd": None,
        "calmar": None,
        "sharpe": None,
        "sharpe_source": "",
        "ppc": None,
        "capital_days": 0.0,
        "avg_days": None,
        "med_days": None,
        "p90_days": None,
        "losing_streak": 0,
        "avg_pos": None,
        "med_pos": None,
        "max_pos": None,
        "pct_max_sym": None,
        "pct_max_trade": None,
        "pct_max_ind": None,
        "pct_top10": None,
        "pct_bot10": None,
        "trades_per_year": None,
        "exit_mix": {},
        "pnl_d": 0.0,
        "n_symbols": 0,
    }
    if n <= 0:
        return empty

    pcts = [r["pnl_pct"] for r in rows if r.get("pnl_pct") is not None]
    pnls_d: list[float] = []
    overlay_rows: list[dict[str, Any]] = []
    for r in rows:
        pd = r.get("pnl_d")
        pct = r.get("pnl_pct")
        if pd is None and pct is not None:
            pd = float(pct) / 100.0 * VZ_CASH
        if pd is None:
            continue
        pnls_d.append(float(pd))
        overlay_rows.append(
            {
                "pnl": pct,
                "pnl_d": float(pd),
                "days": r.get("days"),
                "closed": r.get("closed"),
                "opened": r.get("opened"),
            }
        )

    wins = sum(1 for p in pcts if p > 0)
    losses = sum(1 for p in pcts if p < 0)
    be = n - wins - losses
    avg = (sum(pcts) / len(pcts)) if pcts else None
    wo = None
    if pcts:
        ordered = sorted(pcts)
        wo = (sum(ordered[:-1]) / (len(ordered) - 1)) if len(ordered) > 1 else avg
    win_pcts = [p for p in pcts if p > 0]
    loss_pcts = [p for p in pcts if p < 0]
    avg_w = (sum(win_pcts) / len(win_pcts)) if win_pcts else None
    avg_l = (sum(loss_pcts) / len(loss_pcts)) if loss_pcts else None
    days = [float(r["days"]) for r in rows if r.get("days") is not None and r["days"] > 0]
    avg_days = (sum(days) / len(days)) if days else None
    med_days = sorted(days)[len(days) // 2] if days else None
    p90_days = sorted(days)[int(0.9 * (len(days) - 1))] if days else None

    ov = overlay_ann_ror_max_dd(
        overlay_rows, cash=VZ_CASH, initial_account=VZ_INIT
    )
    total_pnl = float(ov.get("pnl_d") or (sum(pnls_d) if pnls_d else 0.0))
    cap_days = float(ov.get("capital_days") or (sum(days) if days else 0.0))
    ppc = (total_pnl / cap_days) if cap_days else None
    sum_w = sum(x for x in pnls_d if x > 0)
    sum_l = abs(sum(x for x in pnls_d if x < 0))
    pf = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else 0.0)
    wl_count = (wins / losses) if losses else (float(wins) if wins else None)
    wl_dollar = (sum_w / sum_l) if sum_l > 0 else (sum_w if sum_w > 0 else None)

    by_sym: dict[str, float] = defaultdict(float)
    by_ind: dict[str, float] = defaultdict(float)
    for r, pd in zip(
        [r for r in rows if r.get("pnl_d") is not None or r.get("pnl_pct") is not None],
        pnls_d,
    ):
        by_sym[r.get("symbol") or "?"] += pd
        by_ind[r.get("industry") or "?"] += pd
    abs_total = abs(total_pnl) if abs(total_pnl) > 1e-9 else None
    max_trade = max(pnls_d, key=lambda x: abs(x)) if pnls_d else None
    max_sym = max(by_sym.values(), key=lambda x: abs(x)) if by_sym else None
    max_ind = max(by_ind.values(), key=lambda x: abs(x)) if by_ind else None
    sym_sorted = sorted(by_sym.values(), key=lambda x: -abs(x))
    top10 = sum(sym_sorted[:10]) if sym_sorted else None
    bot10 = sum(sorted(by_sym.values())[:10]) if by_sym else None

    opened_dates = [r["opened"] for r in rows if r.get("opened")]
    tpy = None
    if opened_dates:
        span = (max(opened_dates) - min(opened_dates)).days / 365.25
        if span > 0:
            tpy = n / span

    avg_pos, med_pos, max_pos = _position_stats(rows)
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "be": be,
        "win_pct": 100.0 * wins / n,
        "avg_pct": avg,
        "wo_max": wo,
        "expectancy_pct": avg,
        "expectancy_d": (total_pnl / n) if n else None,
        "avg_win": avg_w,
        "avg_loss": avg_l,
        "wl_count": wl_count,
        "wl_dollar": wl_dollar,
        "pf": pf,
        "ann_ror": ov.get("ann_ror"),
        "max_dd": ov.get("max_dd"),
        "calmar": ov.get("calmar"),
        "sharpe": ov.get("sharpe"),
        "sharpe_source": ov.get("sharpe_source") or "",
        "ppc": ppc,
        "capital_days": cap_days,
        "avg_days": avg_days,
        "med_days": med_days,
        "p90_days": p90_days,
        "losing_streak": _losing_streak(rows),
        "avg_pos": avg_pos,
        "med_pos": med_pos,
        "max_pos": max_pos,
        "pct_max_sym": (100.0 * max_sym / total_pnl) if abs_total and max_sym is not None else None,
        "pct_max_trade": (100.0 * max_trade / total_pnl) if abs_total and max_trade is not None else None,
        "pct_max_ind": (100.0 * max_ind / total_pnl) if abs_total and max_ind is not None else None,
        "pct_top10": (100.0 * top10 / total_pnl) if abs_total and top10 is not None else None,
        "pct_bot10": (100.0 * bot10 / total_pnl) if abs_total and bot10 is not None else None,
        "trades_per_year": tpy,
        "exit_mix": _exit_mix(rows),
        "pnl_d": total_pnl,
        "n_symbols": len({r["symbol"] for r in rows if r.get("symbol")}),
        "overlay_note": ov.get("note") or "",
    }


def classify_extras(
    kept: list[dict[str, Any]], dropped: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Same-day extras vs later fills while the first lot was still open."""
    held_opens: dict[str, list[date]] = defaultdict(list)
    for r in kept:
        if r.get("opened"):
            held_opens[r["symbol"]].append(r["opened"])
    same_day: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for r in dropped:
        if r.get("opened") is not None and r["opened"] in held_opens.get(r["symbol"], []):
            same_day.append(r)
        else:
            later.append(r)
    return same_day, later


def same_open_extras(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extra rows that share DATE_OPENED with another fill on the same symbol (autopsy 202)."""
    by: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("symbol") and r.get("opened"):
            by[(r["symbol"], r["opened"])].append(r)
    extras: list[dict[str, Any]] = []
    for grp in by.values():
        if len(grp) < 2:
            continue
        grp = sorted(
            grp,
            key=lambda r: (
                r["closed"] or date.max,
                r.get("zone_id") or "",
                r["stop"] if r.get("stop") is not None else 0.0,
                r.get("i") or 0,
            ),
        )
        extras.extend(grp[1:])
    return extras


def extras_arms(
    all_rows: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    extra_syms = {r["symbol"] for r in dropped if r.get("symbol")}
    same_day, later = classify_extras(kept, dropped)
    return {
        "ALL": all_rows,
        "FIRST_ONLY": kept,
        "EXTRAS_ONLY": dropped,
        "SAME_OPEN_EXTRAS": same_open_extras(all_rows),
        "SAME_DAY_EXTRAS": same_day,
        "LATER_EXTRAS": later,
        "MULTI_ZONE_EVENTS": [r for r in all_rows if r.get("symbol") in extra_syms],
        "FIRST_ON_MULTI": [r for r in kept if r.get("symbol") in extra_syms],
        "SOLO": [r for r in all_rows if r.get("symbol") not in extra_syms],
    }


def score_scopes(arm_rows: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for name, rows in arm_rows.items():
        is_rows, oos_rows = split_is_oos(rows)
        out[name] = {
            "FULL": overlay_book(rows),
            "IS": overlay_book(is_rows),
            "OOS": overlay_book(oos_rows),
        }
    return out


def split_is_oos(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    is_rows = [r for r in rows if r["opened"] < IS_CUT]
    oos_rows = [r for r in rows if r["opened"] >= IS_CUT]
    return is_rows, oos_rows


def gold_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["symbol"] == "GOLD"]


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\\d{4})-(\\d{2})-(\\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
      var ymd = s.match(/^(\\d{8})$/);
      if (ymd) return parseInt(ymd[1], 10);
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


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}%"


def _fmt_n(v: Optional[int]) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def _fmt_num(v: Any, d: int = 2) -> str:
    x = _finite(v)
    if x is None:
        return "—"
    return f"{x:,.{d}f}"


def _esc(s: object) -> str:
    return html_mod.escape(str(s or ""))


def _delta(a: Any, b: Any) -> Optional[float]:
    xa, xb = _finite(a), _finite(b)
    if xa is None or xb is None:
        return None
    return xb - xa


def extras_verdict(scores: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    all_f = scores["ALL"]["FULL"]
    first_f = scores["FIRST_ONLY"]["FULL"]
    extra_f = scores["EXTRAS_ONLY"]["FULL"]
    all_o = scores["ALL"]["OOS"]
    first_o = scores["FIRST_ONLY"]["OOS"]
    extra_o = scores["EXTRAS_ONLY"]["OOS"]
    first_m = scores["FIRST_ON_MULTI"]["FULL"]
    solo = scores["SOLO"]["FULL"]
    extra_better_avg = (
        extra_f.get("avg_pct") is not None
        and first_f.get("avg_pct") is not None
        and extra_f["avg_pct"] > first_f["avg_pct"]
    )
    extra_better_oos = (
        extra_o.get("avg_pct") is not None
        and first_o.get("avg_pct") is not None
        and extra_o["avg_pct"] > first_o["avg_pct"]
    )
    names_better = (
        first_m.get("avg_pct") is not None
        and solo.get("avg_pct") is not None
        and first_m["avg_pct"] > solo["avg_pct"]
    )
    extras_vs_own_first = (
        extra_f.get("avg_pct") is not None
        and first_m.get("avg_pct") is not None
        and extra_f["avg_pct"] > first_m["avg_pct"]
    )
    stacked = (all_f.get("pnl_d") or 0) - (first_f.get("pnl_d") or 0)
    return {
        "extra_better_avg": extra_better_avg,
        "extra_better_oos": extra_better_oos,
        "names_better": names_better,
        "extras_vs_own_first": extras_vs_own_first,
        "stacked_d": stacked,
        "verdict": "DISMISS",
        "research": (
            "YES — extras printed a higher Avg% than FIRST_ONLY"
            if extra_better_avg
            else "NO — extras did not beat FIRST_ONLY on Avg%"
        ),
        "operational": "NO — one position per symbol; do not keep the pyramid bug",
    }


def _metric_cell(m: dict[str, Any], key: str, kind: str) -> str:
    v = m.get(key)
    if kind == "int":
        return _fmt_n(int(v) if v is not None else None)
    if kind == "pct":
        return _fmt_pct(v)
    if kind == "num0":
        return _fmt_num(v, 0)
    if kind == "num1":
        return _fmt_num(v, 1)
    if kind == "num2":
        return _fmt_num(v, 2)
    if kind == "money":
        return format_money(v)
    return _esc(v)


CANONICAL_ROWS = (
    ("Total trades", "n", "int"),
    ("Wins", "wins", "int"),
    ("Losses", "losses", "int"),
    ("Win %", "win_pct", "pct"),
    ("Avg PnL %", "avg_pct", "pct"),
    ("Book AVG_PNL_PCT_WO_MAX", "wo_max", "pct"),
    ("Expectancy %", "expectancy_pct", "pct"),
    ("Expectancy $", "expectancy_d", "money"),
    ("Avg win %", "avg_win", "pct"),
    ("Avg loss %", "avg_loss", "pct"),
    ("Win/Loss ratio (count)", "wl_count", "num2"),
    ("Win/Loss ratio $", "wl_dollar", "num2"),
    ("Profit factor", "pf", "num2"),
    ("Ann ROR %", "ann_ror", "pct"),
    ("Max DD %", "max_dd", "pct"),
    ("Calmar", "calmar", "num2"),
    ("Sharpe", "sharpe", "num2"),
    ("Profit per capital day", "ppc", "money"),
    ("Capital days", "capital_days", "num0"),
    ("Avg days held", "avg_days", "num1"),
    ("Median days held", "med_days", "num1"),
    ("P90 days held", "p90_days", "num1"),
    ("Losing streak", "losing_streak", "int"),
    ("Avg positions", "avg_pos", "num1"),
    ("Median positions", "med_pos", "num1"),
    ("Max positions", "max_pos", "int"),
    ("Pct PnL max symbol", "pct_max_sym", "pct"),
    ("Pct PnL max trade", "pct_max_trade", "pct"),
    ("Pct PnL max industry", "pct_max_ind", "pct"),
    ("Pct PnL top10", "pct_top10", "pct"),
    ("Pct PnL bottom10", "pct_bot10", "pct"),
    ("Mean AVG_TRADES_PER_YEAR", "trades_per_year", "num2"),
    ("Symbols", "n_symbols", "int"),
)


def _canon_table(
    scores: dict[str, dict[str, dict[str, Any]]],
    scope: str,
    arms: list[tuple[str, str]],
) -> str:
    head = _sortable_th("Metric", "text") + "".join(
        _sortable_th(label, "num") for _key, label in arms
    )
    body = ""
    for label, key, kind in CANONICAL_ROWS:
        body += f"<tr><td>{_esc(label)}</td>"
        for arm_key, _lab in arms:
            body += f"<td>{_metric_cell(scores[arm_key][scope], key, kind)}</td>"
        body += "</tr>"
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def _exit_table(
    scores: dict[str, dict[str, dict[str, Any]]],
    scope: str,
    arms: list[tuple[str, str]],
) -> str:
    keys = set()
    for arm_key, _lab in arms:
        keys.update(scores[arm_key][scope].get("exit_mix") or {})
    order = ["TARGET", "STOP_LOSS", "TIME", "GAP_UP", "GAP_DOWN"]
    rest = sorted(k for k in keys if k not in order)
    head = _sortable_th("Exit", "text") + "".join(
        _sortable_th(label, "num") for _k, label in arms
    )
    body = ""
    for ex in [k for k in order if k in keys] + rest:
        body += f"<tr><td>{_esc(ex)}</td>"
        for arm_key, _lab in arms:
            mix = scores[arm_key][scope].get("exit_mix") or {}
            n = scores[arm_key][scope].get("n") or 0
            c = mix.get(ex, 0)
            pct = (100.0 * c / n) if n else None
            body += f"<td>{_fmt_n(c)} ({_fmt_pct(pct)})</td>"
        body += "</tr>"
    return (
        f'<table class="sortable"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )


def extras_html(
    scores: dict[str, dict[str, dict[str, Any]]],
    closed_name: str,
) -> str:
    v = extras_verdict(scores)
    core = [
        ("ALL", "ALL (old engine)"),
        ("FIRST_ONLY", "FIRST_ONLY"),
        ("EXTRAS_ONLY", "EXTRAS_ONLY"),
    ]
    extra_split = [
        ("EXTRAS_ONLY", "EXTRAS_ONLY"),
        ("SAME_OPEN_EXTRAS", "SAME_OPEN extras"),
        ("SAME_DAY_EXTRAS", "same-open vs kept first"),
        ("LATER_EXTRAS", "LATER extras"),
    ]
    multi = [
        ("MULTI_ZONE_EVENTS", "MULTI_ZONE_EVENTS"),
        ("FIRST_ON_MULTI", "FIRST_ON_MULTI"),
        ("SOLO", "SOLO names"),
        ("EXTRAS_ONLY", "EXTRAS_ONLY"),
    ]
    headline_arms = core

    def head_row(scope: str) -> str:
        cells = ""
        for key, lab in headline_arms:
            m = scores[key][scope]
            cells += (
                "<tr>"
                f"<td>{_esc(lab)}</td>"
                f"<td>{_esc(scope)}</td>"
                f"<td>{_fmt_n(m['n'])}</td>"
                f"<td>{_fmt_pct(m['avg_pct'])}</td>"
                f"<td>{_fmt_pct(m['win_pct'])}</td>"
                f"<td>{_fmt_pct(m['wo_max'])}</td>"
                f"<td>{_fmt_num(m['pf'])}</td>"
                f"<td>{_fmt_pct(m['ann_ror'])}</td>"
                f"<td>{_fmt_pct(m['max_dd'])}</td>"
                f"<td>{format_money(m.get('ppc'))}</td>"
                f"<td>{_fmt_pct(_delta(scores['FIRST_ONLY'][scope]['avg_pct'], m['avg_pct']))}</td>"
                f"<td>{_fmt_pct(_delta(scores['ALL'][scope]['avg_pct'], m['avg_pct']))}</td>"
                "</tr>"
            )
        return cells

    h_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("Arm", "text"),
            ("Scope", "text"),
            ("N", "num"),
            ("Avg PnL %", "num"),
            ("Win %", "num"),
            ("AVG_PNL_PCT_WO_MAX", "num"),
            ("PF", "num"),
            ("Ann ROR %", "num"),
            ("Max DD %", "num"),
            ("Profit / cap day", "num"),
            ("Δ Avg% vs FIRST_ONLY", "num"),
            ("Δ Avg% vs ALL", "num"),
        )
    )
    h_body = head_row("FULL") + head_row("IS") + head_row("OOS")

    gold_note = (
        "Quality of extras looked better, but it is two tickets on the same name "
        "(selection + double size), not a reason to keep the bug. Example: GOLD "
        "2020-05-06 is two Volatility Zone (High-Low / HL) fills on the same open "
        "— 11.82% and 18.54% — stacked $ on one symbol, not a new edge."
    )
    research = v["research"]
    return f"""
<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{_esc(ASK2)}</blockquote>
<h2>In plain English</h2>
<p>{_esc(LAYMAN2)}</p>
</div>

<div class="insight">
<h2 style="margin-top:0;border:0">Did extras help? — verdict</h2>
<p><strong>Operational:</strong> {_esc(v['operational'])}. Verdict for keeping pyramids: <span class="badge">{_esc(v['verdict'])}</span>.</p>
<p><strong>Research quality:</strong> {_esc(research)}. Overlay $ from extras vs FIRST_ONLY: {format_money_delta(v['stacked_d'])} (stacked sheet dollars, not a new system).</p>
<p class="caveat">{_esc(gold_note)}</p>
<p class="meta">Before book: <code>{_esc(closed_name)}</code> (N=2708 old engine). Current house pin / LatestRun may already be the gated book (~2170) and was not overwritten. Sheet ${VZ_CASH:,.0f} · overlay Max DD / Sharpe seed ${VZ_INIT:,.0f} · exit-date equity (no daily EquityCurve) · IS = entry &lt; 2024-01-01 · OOS report-only. Paul / FIT Summary scores are N/A on this Closed overlay (no per-arm Summary).</p>
</div>

<h2>Multiple-zone extras vs first-only vs old book</h2>
<p class="meta">One overlay, same exits. <code>ALL</code> = every Closed fill including pyramids. <code>FIRST_ONLY</code> = the fill the new one-position gate keeps. <code>EXTRAS_ONLY</code> = the dropped pyramid fills. Click column headers to sort.</p>
<table class="sortable"><thead><tr>{h_head}</tr></thead><tbody>{h_body}</tbody></table>

<h3>FULL — canonical book</h3>
<p class="meta">Click column headers to sort. Sheet / Total PnL $ omitted (quality over stacked $). Ann ROR / Max DD / Calmar / Sharpe from Closed overlay.</p>
{_canon_table(scores, "FULL", core)}

<h3>IS (entry &lt; 2024-01-01) — canonical book</h3>
<p class="meta">Click column headers to sort. Used for KEEP/DISMISS quality. OOS is not for retune.</p>
{_canon_table(scores, "IS", core)}

<h3>OOS (entry ≥ 2024-01-01) — report-only</h3>
<p class="meta">Click column headers to sort. Report-only — do not pick knobs from this row.</p>
{_canon_table(scores, "OOS", core)}

<h3>Same-day extras vs later overlap extras</h3>
<p class="meta"><code>SAME_OPEN extras</code> = extra rows that share DATE_OPENED with another fill on the same symbol (the autopsy 202). <code>same-open vs kept first</code> = dropped fills whose open date matches the kept first lot (a same-day pair that opened while an earlier hold was still open is counted in LATER, not here). <code>LATER extras</code> = new zone fill on a later date, or a same-day pair stacked on an already-open lot. Click headers to sort.</p>
{_canon_table(scores, "FULL", extra_split)}

<h3>MULTI_ZONE_EVENTS vs SOLO names</h3>
<p class="meta"><code>MULTI_ZONE_EVENTS</code> = first + extras on symbols that had &gt;1 buy. <code>FIRST_ON_MULTI</code> = only the kept first lots on those same names (selection check). <code>SOLO</code> = symbols that never pyramided. If FIRST_ON_MULTI already beats SOLO, the extra fills sat on stronger names. Click headers to sort.</p>
{_canon_table(scores, "FULL", multi)}

<h3>Exit mix (FULL)</h3>
<p class="meta">Counts and % of Closed EXIT_TYPE. STOP maps to STOP_LOSS. Click headers to sort.</p>
{_exit_table(scores, "FULL", core + [("SAME_DAY_EXTRAS", "SAME_DAY extras"), ("SOLO", "SOLO")])}
"""


def write_html(
    *,
    systems: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    gold_overlap: list[dict[str, Any]],
    vz_before_after: dict[str, Any],
    fix_status: str,
    extras_scores: Optional[dict[str, dict[str, dict[str, Any]]]] = None,
    extras_closed: str = "",
) -> str:
    sys_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("System", "text"),
            ("Wired", "text"),
            ("Closed file", "text"),
            ("N closed", "num"),
            ("Same-day dup groups", "num"),
            ("Same-day extra rows", "num"),
            ("Overlap fills (B while A open)", "num"),
            ("Engine", "text"),
        )
    )
    sys_body = ""
    for s in systems:
        sys_body += (
            "<tr>"
            f"<td>{_esc(s['system'])}</td>"
            f"<td>{_esc(s['wired'])}</td>"
            f"<td>{_esc(s['file'])}</td>"
            f"<td>{_fmt_n(s['n'])}</td>"
            f"<td>{_fmt_n(s['same_open_groups'])}</td>"
            f"<td>{_fmt_n(s['same_open_extra'])}</td>"
            f"<td>{_fmt_n(s['overlap_fills'])}</td>"
            f"<td>{_esc(s['engine'])}</td>"
            "</tr>"
        )

    ex_rows = ""
    for s in systems:
        for e in s.get("same_open_ex") or []:
            ex_rows += (
                "<tr>"
                f"<td>{_esc(s['system'])}</td>"
                f"<td>{_esc(e['symbol'])}</td>"
                f"<td>{_esc(e['opened'])}</td>"
                f"<td>{_esc(e['n'])}</td>"
                f"<td>{_esc(e['stops'])}</td>"
                f"<td>{_esc(e['targets'])}</td>"
                f"<td>{_esc(e['zones'])}</td>"
                "</tr>"
            )
    if not ex_rows:
        ex_rows = "<tr><td colspan='7'>None</td></tr>"
    ex_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("System", "text"),
            ("Symbol", "text"),
            ("Opened", "date"),
            ("Rows", "num"),
            ("Stops", "text"),
            ("Targets", "text"),
            ("Zone IDs", "text"),
        )
    )

    ov_rows = ""
    for s in systems:
        for e in s.get("overlap_ex") or []:
            ov_rows += (
                "<tr>"
                f"<td>{_esc(s['system'])}</td>"
                f"<td>{_esc(e['symbol'])}</td>"
                f"<td>{_esc(e['a_open'])}</td>"
                f"<td>{_esc(e['a_close'])}</td>"
                f"<td>{_esc(e['b_open'])}</td>"
                f"<td>{_esc(e['b_close'])}</td>"
                f"<td>{_esc(e.get('a_zone'))}</td>"
                f"<td>{_esc(e.get('b_zone'))}</td>"
                "</tr>"
            )
    if not ov_rows:
        ov_rows = "<tr><td colspan='8'>None</td></tr>"
    ov_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("System", "text"),
            ("Symbol", "text"),
            ("A opened", "date"),
            ("A closed", "date"),
            ("B opened", "date"),
            ("B closed", "date"),
            ("A zone", "text"),
            ("B zone", "text"),
        )
    )

    gold_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("Opened", "date"),
            ("Closed", "date"),
            ("Entry", "num"),
            ("Stop", "num"),
            ("Target", "num"),
            ("Exit", "text"),
            ("PnL %", "num"),
            ("Days", "num"),
            ("Zone", "text"),
            ("Zone lo", "num"),
            ("Break", "text"),
        )
    )
    gold_body = ""
    for r in gold:
        gold_body += (
            "<tr>"
            f"<td>{r['opened'].isoformat()}</td>"
            f"<td>{r['closed'].isoformat() if r['closed'] else ''}</td>"
            f"<td>{'' if r['entry'] is None else format(r['entry'], '.2f')}</td>"
            f"<td>{'' if r['stop'] is None else format(r['stop'], '.2f')}</td>"
            f"<td>{'' if r['target'] is None else format(r['target'], '.2f')}</td>"
            f"<td>{_esc(r['exit_type'])}</td>"
            f"<td>{_fmt_pct(r['pnl_pct'])}</td>"
            f"<td>{'' if r['days'] is None else int(r['days'])}</td>"
            f"<td>{_esc(r['zone_id'])}</td>"
            f"<td>{'' if r['zone_lo'] is None else format(r['zone_lo'], '.4f')}</td>"
            f"<td>{_esc(r['break_date'])}</td>"
            "</tr>"
        )

    ba_head = "".join(
        _sortable_th(label, typ)
        for label, typ in (
            ("Book", "text"),
            ("Scope", "text"),
            ("N before", "num"),
            ("Avg % before", "num"),
            ("N after", "num"),
            ("Avg % after", "num"),
            ("Δ N", "num"),
            ("Δ Avg %", "num"),
        )
    )
    ba_body = ""
    for row in vz_before_after.get("rows") or []:
        ba_body += (
            "<tr>"
            f"<td>{_esc(row['book'])}</td>"
            f"<td>{_esc(row['scope'])}</td>"
            f"<td>{_fmt_n(row['n_before'])}</td>"
            f"<td>{_fmt_pct(row['avg_before'])}</td>"
            f"<td>{_fmt_n(row['n_after'])}</td>"
            f"<td>{_fmt_pct(row['avg_after'])}</td>"
            f"<td>{_fmt_n(row['dn'])}</td>"
            f"<td>{_fmt_pct(row['davg'])}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{STAMP}</title>
<style>
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; touch-action: manipulation; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 1.5rem; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.4rem; margin: 0 0 .35rem; }}
h2 {{ font-size: 1.12rem; margin: 1.5rem 0 .45rem; border-bottom: 1px solid #cbd5e1; padding-bottom: .25rem; }}
.meta {{ color: #475569; font-size: .92rem; max-width: 78rem; }}
.insight {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: .75rem 1rem; margin: .75rem 0; max-width: 78rem; }}
.ask {{ background: #eff6ff; border: 1px solid #bfdbfe; }}
.fix {{ background: #ecfdf5; border: 1px solid #6ee7b7; }}
.caveat {{ color: #9a3412; }}
table.sortable {{ border-collapse: collapse; background: #fff; font-size: .82rem; margin: .5rem 0 1rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: .32rem .5rem; text-align: left; }}
table.sortable th {{ background: #f1f5f9; }}
blockquote.meta {{ margin: .4rem 0 0; padding-left: .8rem; border-left: 3px solid #93c5fd; white-space: pre-wrap; }}
.badge {{ display: inline-block; padding: .1rem .45rem; border-radius: 4px; font-size: .8rem; background: #e2e8f0; }}
</style></head><body>
<h1>Duplicate buy while held — VZ autopsy + all live Closed</h1>
<p class="badge">Research note · not gold · operational one-position rule · replay drops pyramid fills</p>
<p class="meta">Stamp <code>{STAMP}</code> · {datetime.now().strftime("%Y-%m-%d")} · Click column headers to sort</p>

<div class="insight ask">
<h2 style="margin-top:0;border:0">What you asked</h2>
<blockquote class="meta">{_esc(ASK)}</blockquote>
<h2>In plain English</h2>
<p>{_esc(LAYMAN)}</p>
<p class="meta" style="margin-top:.75rem"><strong>Follow-up:</strong></p>
<blockquote class="meta">{_esc(ASK2)}</blockquote>
<p class="meta"><strong>In plain English:</strong> {_esc(LAYMAN2)}</p>
</div>

<div class="insight fix">
<h2 style="margin-top:0;border:0">Fix status</h2>
<p>{_esc(fix_status)}</p>
<p class="meta">Paul rule: <strong>one open position per symbol per system</strong>. Same-day two fills are an error, not an intended pyramid, and not regular vs aggressive (Aggressive is the equity overlay, not a second Closed book).</p>
</div>

<h2>Why GOLD has two 2020-05-06 rows</h2>
<p class="meta">Both tickets fill at next open 6.92 after the 2020-05-05 signal. Stops/targets differ (6.38 / 7.74 vs 6.07 / 8.21) because <em>two different Volatility Zone (High-Low / HL) bands</em> retested the same session. <code>run_system</code> only unique's <code>(zone_id, entry_idx, side)</code>, so two zones on the same fill bar both become Closed rows. <code>enrich_trade_rows</code> then simulated each signal as if the symbol were flat. House Aggressive equity did not create the second ticket. The Closed <code>ZONE_ID</code> column can look identical on those two rows because DNA splice used to key only (symbol, open, close) — last zone won; stops still prove they were two lots.</p>
<p class="meta">TBN host already skips a new entry when <code>open_trade</code> is set. VZ DailyRun never enters that loop — <code>vz_mode</code> calls <code>rocket_vz.run_vz_from_brt_main</code>.</p>
<table class="sortable"><thead><tr>{gold_head}</tr></thead><tbody>{gold_body}</tbody></table>
<p class="meta">Other GOLD overlaps on the same house Closed (B opens while A still open), first 8:</p>
<table class="sortable"><thead><tr>{ov_head}</tr></thead><tbody>
{''.join(
    '<tr>'
    f"<td>VZ</td><td>{_esc(e['symbol'])}</td><td>{_esc(e['a_open'])}</td>"
    f"<td>{_esc(e['a_close'])}</td><td>{_esc(e['b_open'])}</td>"
    f"<td>{_esc(e['b_close'])}</td><td>{_esc(e.get('a_zone'))}</td>"
    f"<td>{_esc(e.get('b_zone'))}</td></tr>"
    for e in gold_overlap
) or "<tr><td colspan='8'>None besides the same-day pair</td></tr>"}
</tbody></table>

<h2>Per-system duplicate counts</h2>
<p class="meta">LatestRun Closed, or house pin for VZ / RSI. Overlap = a later row whose DATE_OPENED is on or before the prior row's DATE_CLOSED (including same-day). Click headers to sort.</p>
<table class="sortable"><thead><tr>{sys_head}</tr></thead><tbody>{sys_body}</tbody></table>

<h2>Same-day duplicate examples</h2>
<table class="sortable"><thead><tr>{ex_head}</tr></thead><tbody>{ex_rows}</tbody></table>

<h2>Overlap examples (B while A open)</h2>
<table class="sortable"><thead><tr>{ov_head}</tr></thead><tbody>{ov_rows}</tbody></table>

<h2>VZ house Closed — before vs after one-position filter</h2>
<p class="meta">Offline replay of the house Closed (drop later overlapping fills). Research note, not gold. In-sample (IS) = entry &lt; 2024-01-01; out-of-sample (OOS) = entry ≥ 2024-01-01 is report-only. Next DailyRun VZ will apply the gate in <code>enrich_trade_rows</code>.</p>
<table class="sortable"><thead><tr>{ba_head}</tr></thead><tbody>{ba_body}</tbody></table>
<p class="caveat meta">Replay will drop pyramid fills from older research stamps that used the independent-signal book. Signal lists used by some ABs are unchanged; only the live Closed/Open fill layer is gated.</p>

{extras_html(extras_scores, extras_closed) if extras_scores else ""}

{_SORTABLE_TABLE_SCRIPT}
</body></html>
"""


def _ba_row(book: str, scope: str, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    mb = book_metrics(before)
    ma = book_metrics(after)
    davg = None
    if mb["avg_pct"] is not None and ma["avg_pct"] is not None:
        davg = ma["avg_pct"] - mb["avg_pct"]
    return {
        "book": book,
        "scope": scope,
        "n_before": mb["n"],
        "avg_before": mb["avg_pct"],
        "n_after": ma["n"],
        "avg_after": ma["avg_pct"],
        "dn": ma["n"] - mb["n"],
        "davg": davg,
    }


def main() -> None:
    try:
        from tools.dailyrun_system_status import DAILYRUN_REGISTRY, live_wired_systems
    except ImportError:
        import sys

        sys.path.insert(0, str(REPO))
        from tools.dailyrun_system_status import DAILYRUN_REGISTRY, live_wired_systems

    wired = set(live_wired_systems())
    OUT.mkdir(parents=True, exist_ok=True)

    systems: list[dict[str, Any]] = []
    seen_files: set[Path] = set()
    vz_rows: list[dict[str, Any]] = []
    vz_path: Optional[Path] = None

    for sys in WANTED:
        path = resolve_closed(DRIVE, sys)
        wired_flag = "yes" if sys in wired else (
            "no — " + str((DAILYRUN_REGISTRY.get(sys) or {}).get("note") or "not in DailyRun registry")
        )
        if path is None:
            systems.append(
                {
                    "system": sys,
                    "wired": wired_flag,
                    "file": "— missing —",
                    "n": 0,
                    "same_open_groups": 0,
                    "same_open_extra": 0,
                    "overlap_fills": 0,
                    "same_open_ex": [],
                    "overlap_ex": [],
                    "engine": ENGINE.get(sys, ""),
                }
            )
            continue
        seen_files.add(path.resolve())
        rows = load_rows(path)
        stats = scan_book(rows)
        if sys == "VZ":
            before_pin = DRIVE / BEFORE_VZ_CLOSED
            if before_pin.is_file():
                vz_rows = load_rows(before_pin)
                vz_path = before_pin
                stats = scan_book(vz_rows)
            else:
                vz_rows = rows
                vz_path = path
        systems.append(
            {
                "system": sys,
                "wired": wired_flag,
                "file": (vz_path.name if sys == "VZ" and vz_path else path.name),
                **stats,
                "engine": ENGINE.get(sys, ""),
            }
        )

    for prefix, path in extra_closed(DRIVE, seen_files):
        rows = load_rows(path)
        stats = scan_book(rows)
        systems.append(
            {
                "system": prefix,
                "wired": "disk extra",
                "file": path.name,
                **stats,
                "engine": ENGINE.get(prefix, "Discovered LatestRun Closed"),
            }
        )

    gold = gold_rows(vz_rows)
    gold_focus = [r for r in gold if r["opened"] in {date(2020, 5, 6), date(2016, 2, 19), date(2016, 2, 26), date(2024, 4, 16)}]
    if not gold_focus:
        gold_focus = gold[:12]
    vz_scan = scan_book(vz_rows)
    gold_overlap = [e for e in vz_scan["overlap_ex"] if e["symbol"] == "GOLD"]
    if not gold_overlap:
        # rebuild full GOLD overlaps (scan_book caps examples at 8 across all symbols)
        gold_overlap = []
        items = sorted(
            gold,
            key=lambda r: (r["opened"], r["closed"] or date.max, r["zone_id"], r["i"]),
        )
        held_until = None
        held_row = None
        for r in items:
            if held_until is not None and r["opened"] <= held_until:
                gold_overlap.append(
                    {
                        "symbol": "GOLD",
                        "a_open": held_row["opened"].isoformat() if held_row else "",
                        "a_close": held_until.isoformat(),
                        "b_open": r["opened"].isoformat(),
                        "b_close": r["closed"].isoformat() if r["closed"] else "",
                        "a_zone": (held_row or {}).get("zone_id", ""),
                        "b_zone": r["zone_id"],
                    }
                )
                continue
            held_until = r["closed"]
            held_row = r
        gold_overlap = gold_overlap[:12]

    kept, dropped = keep_one_position(vz_rows)
    is_b, oos_b = split_is_oos(vz_rows)
    is_a, oos_a = split_is_oos(kept)
    vz_ba = {
        "closed": vz_path.name if vz_path else "",
        "dropped_n": len(dropped),
        "rows": [
            _ba_row("house VZ", "FULL", vz_rows, kept),
            _ba_row("house VZ", "IS entry < 2024-01-01", is_b, is_a),
            _ba_row("house VZ", "OOS entry >= 2024-01-01 (report-only)", oos_b, oos_a),
        ],
    }
    arm_rows = extras_arms(vz_rows, kept, dropped)
    extras_scores = score_scopes(arm_rows)
    extras_v = extras_verdict(extras_scores)

    fix_status = (
        "Fixed live VZ path in stock_analysis/rocket_vz.py enrich_trade_rows: "
        "after a fill, skip later signals whose entry bar is still on or before "
        "that trade's exit bar. Other DailyRun sleeves already had a one-position "
        "gate (TBN open_trade or RSI pos). rsi_universe.csv unchanged. Not committed."
    )

    html = write_html(
        systems=systems,
        gold=gold_focus,
        gold_overlap=gold_overlap,
        vz_before_after=vz_ba,
        fix_status=fix_status,
        extras_scores=extras_scores,
        extras_closed=vz_ba["closed"],
    )
    html_path = OUT / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    def _md_pct(v: Any) -> str:
        x = _finite(v)
        return f"{x:.2f}" if x is not None else "—"

    def _md_arm_row(scope: str, key: str, label: str) -> str:
        m = extras_scores[key][scope]
        return (
            f"| {label} | {scope} | {m['n']} | {_md_pct(m['avg_pct'])} | "
            f"{_md_pct(m['win_pct'])} | {_md_pct(m['wo_max'])} | "
            f"{_fmt_num(m['pf'])} | {_md_pct(m['ann_ror'])} | "
            f"{_md_pct(m['max_dd'])} |\n"
        )

    baseline = f"""# {STAMP}

## What you asked

> {ASK}

## In plain English

{LAYMAN}

## Follow-up

> {ASK2}

## In plain English (follow-up)

{LAYMAN2}

## Freeze / note

- Operational rule, not a param A/B: one open position per symbol per system.
- Live fix: `stock_analysis/rocket_vz.py` `enrich_trade_rows` (2026-09-15).
- Replay of older VZ Closed books will drop pyramid / overlapping fills.
- Research note, not gold, not a DailyRun wire change beyond the engine gate.
- `rsi_universe.csv` not touched. Not committed.
- One-change overlay: same exits; arms are slices of the house Closed (ALL / FIRST_ONLY / EXTRAS_ONLY). IS = entry < 2024-01-01; OOS report-only.

## VZ before / after (house Closed overlay)

Closed file: `{vz_ba["closed"]}` · dropped overlapping fills: {vz_ba["dropped_n"]}

| Scope | N before | Avg% before | N after | Avg% after |
|---|---:|---:|---:|---:|
"""
    for row in vz_ba["rows"]:
        ab = f"{row['avg_before']:.2f}" if row["avg_before"] is not None else "—"
        aa = f"{row['avg_after']:.2f}" if row["avg_after"] is not None else "—"
        baseline += (
            f"| {row['scope']} | {row['n_before']} | {ab} | {row['n_after']} | {aa} |\n"
        )

    baseline += f"""
## Multiple-zone extras — did performance improve?

Closed: `{vz_ba["closed"]}` · sheet ${VZ_CASH:,.0f} · overlay seed ${VZ_INIT:,.0f}

**Operational:** {extras_v["operational"]}. **KEEP/DISMISS for keeping pyramids:** {extras_v["verdict"]} (not a live rule; Paul already wants one position).

**Research quality:** {extras_v["research"]}. Overlay $ extras added vs FIRST_ONLY: {format_money_delta(extras_v["stacked_d"])}. Quality of extras can look better while still being two tickets on the same name (selection + double size) — not a reason to keep the bug.

| Arm | Scope | N | Avg% | Win% | WO_MAX | PF | Ann ROR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
"""
    for scope in ("FULL", "IS", "OOS"):
        for key, lab in (
            ("ALL", "ALL (old engine)"),
            ("FIRST_ONLY", "FIRST_ONLY"),
            ("EXTRAS_ONLY", "EXTRAS_ONLY"),
        ):
            baseline += _md_arm_row(scope, key, lab)
    baseline += "\nSame-day vs later extras, and MULTI_ZONE vs SOLO (FULL):\n\n"
    baseline += (
        "| Arm | Scope | N | Avg% | Win% | WO_MAX | PF | Ann ROR | Max DD |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    for key, lab in (
        ("SAME_OPEN_EXTRAS", "SAME_OPEN extras"),
        ("SAME_DAY_EXTRAS", "same-open vs kept first"),
        ("LATER_EXTRAS", "LATER extras"),
        ("MULTI_ZONE_EVENTS", "MULTI_ZONE_EVENTS"),
        ("FIRST_ON_MULTI", "FIRST_ON_MULTI"),
        ("SOLO", "SOLO names"),
    ):
        baseline += _md_arm_row("FULL", key, lab)
    baseline += (
        "\nSelection honesty: FIRST_ON_MULTI Avg% 4.17 is *below* SOLO 5.31 — extras "
        "did not sit on stronger first lots. EXTRAS 8.89 beat FIRST_ON_MULTI 4.17 on "
        "the same names. SAME_OPEN extras (N=202, the two-zone same-bar set) Avg% 11.02 "
        "/ WR 72.28. OOS extras Avg% still higher (7.02 vs FIRST 4.36) but OOS win% is "
        "flat (58.82 vs 59.04). Quality of extras looked better; it is still two tickets "
        "on the same name (selection + double size), not a reason to keep the bug.\n"
    )
    (OUT / "BASELINE.md").write_text(baseline, encoding="utf-8")

    summary = {
        "stamp": STAMP,
        "fix": "rocket_vz.enrich_trade_rows one-position-per-symbol",
        "systems": [
            {k: v for k, v in s.items() if k not in {"same_open_ex", "overlap_ex"}}
            for s in systems
        ],
        "vz_before_after": vz_ba,
        "extras_followup": {
            "ask": ASK2,
            "verdict": extras_v,
            "scores": extras_scores,
        },
        "gold_20200506": [
            {
                "opened": r["opened"].isoformat(),
                "closed": r["closed"].isoformat() if r["closed"] else "",
                "entry": r["entry"],
                "stop": r["stop"],
                "target": r["target"],
                "pnl_pct": r["pnl_pct"],
                "zone_id": r["zone_id"],
                "zone_lo": r["zone_lo"],
                "break_date": r["break_date"],
            }
            for r in gold
            if r["opened"] == date(2020, 5, 6)
        ],
    }
    def _jsonable(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _jsonable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_jsonable(v) for v in obj]
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        return obj

    (OUT / "summary.json").write_text(
        json.dumps(_jsonable(summary), indent=2), encoding="utf-8"
    )
    print(f"wrote {html_path}")
    print(f"VZ dropped {len(dropped)} overlapping fills of {len(vz_rows)}")
    for row in vz_ba["rows"]:
        print(
            f"  {row['scope']}: N {row['n_before']} -> {row['n_after']} "
            f"Avg% {row['avg_before']} -> {row['avg_after']}"
        )
    for scope in ("FULL", "IS", "OOS"):
        e = extras_scores["EXTRAS_ONLY"][scope]
        f = extras_scores["FIRST_ONLY"][scope]
        a = extras_scores["ALL"][scope]
        print(
            f"  extras {scope}: N={e['n']} Avg%={e['avg_pct']} "
            f"vs FIRST {f['avg_pct']} vs ALL {a['avg_pct']}"
        )
    print(f"  verdict={extras_v['verdict']} stacked={extras_v['stacked_d']}")


if __name__ == "__main__":
    main()
