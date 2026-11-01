#!/usr/bin/env python3
"""Similar Stock Difference, frozen Z025 exit, one pair versus many pairs.

Research only. Not gold. Not DailyRun.

The position rule below is frozen in this file before any profit number from
this run is read. Do not change 0.25 or 15 after seeing the page.
"""
from __future__ import annotations

import html
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT))

import thorp_timestop_and_chain_scan_20261001 as thorp  # noqa: E402
from compare_format import format_money  # noqa: E402
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

OUT = ROOT / "drive" / "paul_experiments" / "ssd_z025_multipair_20261001"
PRIOR_BASELINE = ROOT / "drive" / "paul_experiments" / "ssd_exit_grid_20261001" / "BASELINE.md"
STUDY_END = pd.Timestamp("2026-09-30")
IS_CUT = thorp.IS_CUT
STAKE = thorp.STAKE
EXIT_Z = 0.25
CLOCK = 15
KEEP_AVG_EDGE = 1.0
KEEP_WR_DROP_MAX = 10.0
KEEP_N_RATIO_MIN = 0.80
HTML_SCREEN = 40
HTML_FULL_MAX = 500

# Frozen before this script looks at profit. Rocket Launcher, Volume Zone, and
# Break and ReTest do not share one account-wide position cap in the replay.
# The usual house rule is one open position per symbol. max_positions left at 0
# only records the peak overlap after the run; it does not refuse a new name.
# This book copies that: no pair-count cap. A gap is refused only when a symbol
# is already spoken for.
FREEZE_RULE = (
    "No account-wide pair cap. Every qualifying gap is taken at the next open "
    "when both symbols are free. If either symbol is already in an open SSD pair, "
    "or already reserved for a fill that has not happened yet, skip that gap. "
    "One position per symbol. Same-day conflicts: the larger absolute percent gap "
    "claims the symbols; a tie keeps the earlier pair in the saved menu. "
    "Each taken pair is $10,000 of whole shares on each leg. The return percent "
    "divides the pair result by $10,000, the same stake as the one-pair book. "
    "The exit stays 0.25 standard deviations or the close of the 15th session, "
    "whichever comes first."
)

ORIGINAL_REQUEST = (
    "for this run: ssd_exit_grid_20261001 I like Z025. can we freeze that? "
    "are there other opportunities that we are missing because we only hold one position at a time? "
    "this should work like all other systems where we can hold multiple."
)

PUBLISHED = {
    "full": {"n": 247, "win_pct": 49.797570850202426, "avg_pct": 1.3815985104453437},
    "IS": {"n": 205, "win_pct": 49.75609756097561, "avg_pct": 1.796268305999999},
    "OOS": {"n": 42, "win_pct": 50.0, "avg_pct": -0.6423850154761876},
}


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _th(label: str, sort: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{_esc(label)}<span class="sort-ind"></span></th>'
    )


def _td(text: str, num: bool = False) -> str:
    cls = ' class="num"' if num else ""
    return f"<td{cls}>{_esc(text)}</td>"


def _pct(value: float, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    return f"{value:+.{digits}f}%"


def _num(value: float, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    return f"{value:,.{digits}f}"


def _pp(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}"


def _iso(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()


def _table(headers: list[tuple[str, str]], rows: list[str], caption: str) -> str:
    head = "".join(_th(label, sort) for label, sort in headers)
    body = "".join(rows)
    cap = f"{caption} Swipe sideways to see more columns."
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(cap)}</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def collect_signals(panels: list[dict], bt) -> tuple[dict, dict, list, int]:
    """Every |z| >= 2 gap, not just the best pair of the day."""
    window = bt.WINDOW_START
    entry_z = float(bt.ENTRY_Z)
    by_date: dict[pd.Timestamp, list[tuple]] = {}
    total = 0
    for pi, panel in enumerate(panels):
        z = panel["z"]
        pct = panel["pct"]
        dates = panel["dates"]
        ok = np.isfinite(z) & np.isfinite(pct) & (np.abs(z) >= entry_z)
        for i in np.flatnonzero(ok):
            d = pd.Timestamp(dates[int(i)])
            if d < window or d > STUDY_END:
                continue
            rec = (abs(float(pct[i])), pi, int(i), float(z[i]), float(pct[i]))
            bucket = by_date.get(d)
            if bucket is None:
                by_date[d] = [rec]
            else:
                bucket.append(rec)
            total += 1
        if (pi + 1) % 400 == 0:
            print(f"signals scanned {pi + 1} panels, gaps {total}", flush=True)
    all_dates = sorted(set().union(*[set(p["dates"]) for p in panels])) if panels else []
    all_dates = [pd.Timestamp(d) for d in all_dates if window <= pd.Timestamp(d) <= STUDY_END]
    best_on = {}
    gap_count = {}
    for d, recs in by_date.items():
        ap, pi, i, zi, pct = min(recs, key=lambda r: (-r[0], r[1]))
        best_on[d] = (ap, panels[pi], i, zi, pct)
        gap_count[d] = len(recs)
    print(f"qualifying gaps {total} on {len(by_date)} sessions", flush=True)
    return by_date, best_on, gap_count, all_dates, total


def _side(panel: dict, pct: float) -> tuple[str, str]:
    if pct >= 0:
        return panel["left"], panel["right"]
    return panel["right"], panel["left"]


def _frozen_z(panel: dict, i: int, alpha: float, beta: float, center: float, scale: float) -> float:
    if i < 0 or scale <= 1e-12:
        return float("nan")
    cl = float(panel["close_l"][i])
    cr = float(panel["close_r"][i])
    if cl <= 0 or cr <= 0:
        return float("nan")
    resid = math.log(cl) - (alpha + beta * math.log(cr))
    return float((resid - center) / scale)


def alone_outcome(panel: dict, sig_i: int, pct: float) -> dict | None:
    """Z025 result if this signal is entered on its own. Overlap is allowed here."""
    dates = panel["dates"]
    n = len(dates)
    if sig_i + 1 >= n:
        return None
    entry_i = sig_i + 1
    entry_date = pd.Timestamp(dates[entry_i])
    if entry_date > STUDY_END:
        return None
    alpha = float(panel["alpha"][sig_i])
    beta = float(panel["beta"][sig_i])
    center = float(panel["center"][sig_i])
    scale = float(panel["scale"][sig_i])
    if not np.isfinite(scale) or scale <= 1e-12:
        return None
    short_sym, long_sym = _side(panel, pct)
    left = panel["left"]
    if long_sym == left:
        long_px = float(panel["open_l"][entry_i])
        short_px = float(panel["open_r"][entry_i])
    else:
        long_px = float(panel["open_r"][entry_i])
        short_px = float(panel["open_l"][entry_i])
    shares_long = int(STAKE // long_px) if long_px > 0 else 0
    shares_short = int(STAKE // short_px) if short_px > 0 else 0
    if shares_long <= 0 or shares_short <= 0:
        return None

    def prices(j: int, which: str) -> tuple[float, float]:
        if which == "close":
            px_l, px_r = float(panel["close_l"][j]), float(panel["close_r"][j])
        else:
            px_l, px_r = float(panel["open_l"][j]), float(panel["open_r"][j])
        if long_sym == left:
            return px_l, px_r
        return px_r, px_l

    def pnl(j: int, which: str) -> tuple[float, float, float, float]:
        lp, sp = prices(j, which)
        long_pnl = shares_long * (lp - long_px)
        short_pnl = shares_short * (short_px - sp)
        return long_pnl, short_pnl, lp, sp

    pending_fill = None
    pending_z = float("nan")
    last_j = entry_i
    closest = None
    for j in range(entry_i, n):
        date = pd.Timestamp(dates[j])
        if date > STUDY_END:
            break
        last_j = j
        if pending_fill is not None and date >= pending_fill:
            long_pnl, short_pnl, lp, sp = pnl(j, "open")
            return _outcome(
                panel, sig_i, entry_i, entry_date, j, date, "closed", "open",
                "Back near the entry line", long_pnl, short_pnl, lp, sp, pending_z, closest,
                long_sym, short_sym, long_px, short_px, shares_long, shares_short, pct,
            )
        if date > entry_date:
            z_now = _frozen_z(panel, j, alpha, beta, center, scale)
            if np.isfinite(z_now):
                closest = abs(z_now) if closest is None else min(closest, abs(z_now))
            sessions = j - entry_i
            future = pending_fill is not None and pending_fill > date
            if sessions >= CLOCK and (pending_fill is None or future):
                long_pnl, short_pnl, lp, sp = pnl(j, "close")
                return _outcome(
                    panel, sig_i, entry_i, entry_date, j, date, "closed", "close",
                    "15-session time stop", long_pnl, short_pnl, lp, sp, z_now, closest,
                    long_sym, short_sym, long_px, short_px, shares_long, shares_short, pct,
                )
            if pending_fill is None and np.isfinite(z_now) and abs(z_now) <= EXIT_Z and j + 1 < n:
                pending_fill = pd.Timestamp(dates[j + 1])
                pending_z = z_now

    long_pnl, short_pnl, lp, sp = pnl(last_j, "close")
    reason = "Still open at the last price"
    if pending_fill is not None:
        reason = "Lined up on the last signal day; the next open is not in the file yet"
    z_exit = _frozen_z(panel, last_j, alpha, beta, center, scale)
    return _outcome(
        panel, sig_i, entry_i, entry_date, last_j, pd.Timestamp(dates[last_j]), "open", "close",
        reason, long_pnl, short_pnl, lp, sp, z_exit, closest,
        long_sym, short_sym, long_px, short_px, shares_long, shares_short, pct,
        mark=True,
    )


def _outcome(
    panel, sig_i, entry_i, entry_date, exit_i, exit_date, status, which, reason,
    long_pnl, short_pnl, exit_long, exit_short, z_exit, closest,
    long_sym, short_sym, entry_long, entry_short, shares_long, shares_short, pct,
    mark: bool = False,
) -> dict:
    net = float(long_pnl + short_pnl)
    return {
        "left": panel["left"],
        "right": panel["right"],
        "signal_i": sig_i,
        "signal_date": pd.Timestamp(panel["dates"][sig_i]),
        "entry_date": entry_date,
        "entry_i": entry_i,
        "exit_date": pd.NaT if mark else exit_date,
        "mark_date": exit_date if mark else pd.NaT,
        "exit_i": exit_i,
        "status": status,
        "exit_which": which,
        "reason": reason,
        "long": long_sym,
        "short": short_sym,
        "shares_long": shares_long,
        "shares_short": shares_short,
        "entry_long": entry_long,
        "entry_short": entry_short,
        "exit_long": exit_long,
        "exit_short": exit_short,
        "z_entry": float(panel["z"][sig_i]),
        "z_exit": z_exit,
        "closest_abs_z": closest,
        "pct_entry": pct,
        "long_pnl": float(long_pnl),
        "short_pnl": float(short_pnl),
        "net": net,
        "net_pct": net / STAKE * 100.0,
        "worst": None,
        "alpha": float(panel["alpha"][sig_i]),
        "beta": float(panel["beta"][sig_i]),
        "center": float(panel["center"][sig_i]),
        "scale": float(panel["scale"][sig_i]),
    }


def _as_trade(row: dict, panel: dict) -> dict:
    """Shape alone_outcome into the dict thorp.trades_frame expects."""
    out = dict(row)
    out["panel"] = panel
    return out


def replay_multi(panels: list[dict], by_date: dict, all_dates: list, bt) -> tuple[list[dict], pd.DataFrame, dict]:
    """Many pairs. Symbols are reserved from the signal through the exit fill."""
    positions: dict[int, dict] = {}
    pending_entries: list[dict] = []
    pending_exits: dict[int, dict] = {}
    busy: dict[str, int] = {}
    trades: list[dict] = []
    next_id = 1
    realized = 0.0
    last_unreal: dict[int, float] = {}
    equity_rows: list[dict] = []
    taken = 0
    skipped_busy = 0

    def occupy(a: str, b: str) -> None:
        busy[a] = busy.get(a, 0) + 1
        busy[b] = busy.get(b, 0) + 1

    def release(a: str, b: str) -> None:
        for sym in (a, b):
            busy[sym] = busy.get(sym, 0) - 1
            if busy[sym] <= 0:
                busy.pop(sym, None)

    def held(sym: str) -> bool:
        return busy.get(sym, 0) > 0

    def mark(pos: dict, date: pd.Timestamp) -> float | None:
        panel = pos["panel"]
        i = bt._at(panel, date)
        if i is None:
            return None
        long_px, short_px = bt._side_prices(panel, i, "close", pos["long"], pos["short"], pos["left"])
        return bt._leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long") + bt._leg_pnl(
            pos["shares_short"], pos["entry_short"], short_px, "short"
        )

    def finish(pid: int, date: pd.Timestamp, which: str, reason: str, z_exit: float, signal_date) -> None:
        nonlocal realized
        pos = positions.pop(pid)
        pending_exits.pop(pid, None)
        release(pos["left"], pos["right"])
        panel = pos["panel"]
        i = bt._at(panel, date)
        long_px, short_px = bt._side_prices(panel, i, which, pos["long"], pos["short"], pos["left"])
        long_pnl = bt._leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long")
        short_pnl = bt._leg_pnl(pos["shares_short"], pos["entry_short"], short_px, "short")
        realized += long_pnl + short_pnl
        last_unreal.pop(pid, None)
        trades.append(
            {
                **{k: v for k, v in pos.items() if k != "panel"},
                "exit_date": date,
                "exit_i": i,
                "exit_which": which,
                "exit_signal_date": signal_date,
                "exit_long": long_px,
                "exit_short": short_px,
                "long_pnl": long_pnl,
                "short_pnl": short_pnl,
                "net": long_pnl + short_pnl,
                "z_exit": z_exit,
                "status": "closed",
                "reason": reason,
            }
        )

    def accept(rec: tuple, date: pd.Timestamp) -> bool:
        nonlocal next_id, taken
        _ap, pi, i, zi, pct = rec
        panel = panels[pi]
        if held(panel["left"]) or held(panel["right"]):
            return False
        fill_on = bt._next_session(panel, date)
        if fill_on is None:
            return False
        short_sym, long_sym = _side(panel, pct)
        pid = next_id
        next_id += 1
        occupy(panel["left"], panel["right"])
        pending_entries.append(
            {
                "pid": pid,
                "panel": panel,
                "left": panel["left"],
                "right": panel["right"],
                "label": panel["label"],
                "long": long_sym,
                "short": short_sym,
                "signal_date": date,
                "z_entry": zi,
                "pct_entry": pct,
                "abs_pct": abs(pct),
                "alpha": float(panel["alpha"][i]),
                "beta": float(panel["beta"][i]),
                "center": float(panel["center"][i]),
                "scale": float(panel["scale"][i]),
                "fill_on": fill_on,
            }
        )
        taken += 1
        return True

    for date in all_dates:
        due = [pid for pid, pe in pending_exits.items() if pid in positions and date >= pe["fill_on"]]
        for pid in due:
            pos = positions[pid]
            pe = pending_exits[pid]
            z_exit = bt._frozen_z(pos["panel"], pe["signal_date"], pos["alpha"], pos["beta"], pos["center"], pos["scale"])
            finish(pid, date, "open", "Back near the entry line", z_exit, pe["signal_date"])

        still: list[dict] = []
        for pe in pending_entries:
            if date < pe["fill_on"]:
                still.append(pe)
                continue
            panel = pe["panel"]
            i = bt._at(panel, date)
            filled = False
            if i is not None:
                long_px, short_px = bt._side_prices(panel, i, "open", pe["long"], pe["short"], pe["left"])
                shares_long = int(STAKE // long_px) if long_px > 0 else 0
                shares_short = int(STAKE // short_px) if short_px > 0 else 0
                if shares_long > 0 and shares_short > 0:
                    pid = pe["pid"]
                    positions[pid] = {
                        **pe,
                        "entry_date": date,
                        "entry_i": i,
                        "entry_long": long_px,
                        "entry_short": short_px,
                        "shares_long": shares_long,
                        "shares_short": shares_short,
                        "worst": None,
                        "closest_abs_z": None,
                    }
                    last_unreal[pid] = 0.0
                    filled = True
            if not filled:
                release(pe["left"], pe["right"])
        pending_entries = still

        for pid, pos in list(positions.items()):
            panel = pos["panel"]
            i = bt._at(panel, date)
            if i is None or date < pos["entry_date"]:
                continue
            mtm = mark(pos, date)
            if mtm is not None:
                pos["worst"] = mtm if pos["worst"] is None else min(pos["worst"], mtm)
            if date <= pos["entry_date"]:
                continue
            z_now = bt._frozen_z(panel, date, pos["alpha"], pos["beta"], pos["center"], pos["scale"])
            if np.isfinite(z_now):
                pos["closest_abs_z"] = (
                    abs(z_now) if pos["closest_abs_z"] is None else min(pos["closest_abs_z"], abs(z_now))
                )
            sessions_after = i - pos["entry_i"]
            pe = pending_exits.get(pid)
            future_cover = pe is not None and pe["fill_on"] > date
            if sessions_after >= CLOCK and (pe is None or future_cover):
                finish(pid, date, "close", "15-session time stop", z_now, date)
            elif pe is None and np.isfinite(z_now) and abs(z_now) <= EXIT_Z:
                fill_on = bt._next_session(panel, date)
                if fill_on is not None:
                    pending_exits[pid] = {"signal_date": date, "fill_on": fill_on, "z": z_now}

        cands = by_date.get(date)
        if cands:
            for rec in sorted(cands, key=lambda r: (-r[0], r[1])):
                panel = panels[rec[1]]
                if held(panel["left"]) or held(panel["right"]):
                    skipped_busy += 1
                    continue
                accept(rec, date)

        unreal = 0.0
        for pid, pos in positions.items():
            marked = mark(pos, date)
            if marked is None:
                marked = last_unreal.get(pid, 0.0)
            else:
                last_unreal[pid] = marked
            unreal += marked
        equity_rows.append(
            {
                "date": date,
                "realized": realized,
                "unreal": unreal,
                "n_open": len(positions),
                "equity": realized + unreal,
            }
        )

    if all_dates:
        last_cal = all_dates[-1]
        for pid, pos in list(positions.items()):
            panel = pos["panel"]
            eligible = [pd.Timestamp(d) for d in panel["dates"] if pd.Timestamp(d) <= last_cal]
            if not eligible:
                continue
            last = max(eligible)
            i = bt._at(panel, last)
            long_px, short_px = bt._side_prices(panel, i, "close", pos["long"], pos["short"], pos["left"])
            long_pnl = bt._leg_pnl(pos["shares_long"], pos["entry_long"], long_px, "long")
            short_pnl = bt._leg_pnl(pos["shares_short"], pos["entry_short"], short_px, "short")
            z_exit = bt._frozen_z(panel, last, pos["alpha"], pos["beta"], pos["center"], pos["scale"])
            reason = "Still open at the last price"
            pe = pending_exits.get(pid)
            if pe is not None:
                reason = "Lined up on the last signal day; the next open is not in the file yet"
            trades.append(
                {
                    **{k: v for k, v in pos.items() if k != "panel"},
                    "exit_date": pd.NaT,
                    "mark_date": last,
                    "exit_i": i,
                    "exit_which": "close",
                    "exit_signal_date": pe["signal_date"] if pe else pd.NaT,
                    "exit_long": long_px,
                    "exit_short": short_px,
                    "long_pnl": long_pnl,
                    "short_pnl": short_pnl,
                    "net": long_pnl + short_pnl,
                    "z_exit": z_exit,
                    "status": "open",
                    "reason": reason,
                }
            )

    raw = pd.DataFrame(equity_rows)
    meta = {
        "signals_taken": taken,
        "signals_skipped_symbol_busy": skipped_busy,
        "peak_open_pairs": int(raw["n_open"].max()) if not raw.empty else 0,
        "avg_open_pairs": float(raw["n_open"].mean()) if not raw.empty else 0.0,
        "median_open_pairs": float(raw["n_open"].median()) if not raw.empty else 0.0,
    }
    print(
        f"multiple taken {taken} skipped_busy {skipped_busy} peak {meta['peak_open_pairs']}",
        flush=True,
    )
    return trades, raw, meta


def fund_equity(raw: pd.DataFrame, mask: pd.Series | None = None) -> pd.DataFrame:
    """Constant stake sized to the observed peak inside this slice. Entry did not use it.

    Realized profit from before the slice is taken out, so a later slice is not shifted
    by the earlier book's closed results.
    """
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "equity"])
    view = raw if mask is None else raw.loc[mask]
    if view.empty:
        return pd.DataFrame(columns=["date", "equity"])
    peak = max(int(view["n_open"].max()), 1)
    if mask is None:
        base = 0.0
    else:
        first_label = view.index[0]
        loc = raw.index.get_loc(first_label)
        loc = int(loc) if not isinstance(loc, slice) else int(loc.start)
        base = float(raw["realized"].iloc[loc - 1]) if loc > 0 else 0.0
    out = view[["date"]].copy()
    out["equity"] = peak * STAKE + view["realized"].to_numpy() - base + view["unreal"].to_numpy()
    return out.reset_index(drop=True)


def one_pair_blockers(trades: list[dict], by_date: dict, all_dates: list, panels: list[dict], bt) -> dict:
    """Replay the published one-pair state machine only to label days it was not free.

    The trade list itself comes from thorp.replay. This walk must accept the same signals.
    """
    position = None
    pending_entry = None
    pending_exit = None
    accepted: list[tuple] = []
    blocked: list[dict] = []
    runners = 0
    free_days = 0
    date_set = set(all_dates)

    for date in all_dates:
        if pending_exit is not None and position is not None and date >= pending_exit["fill_on"]:
            position = None
            pending_exit = None
        if pending_entry is not None and position is None and date >= pending_entry["fill_on"]:
            position = pending_entry
            pending_entry = None
        if position is not None and date > position["entry_date"]:
            panel = position["panel"]
            i = bt._at(panel, date)
            if i is not None:
                sessions = i - position["entry_i"]
                pe = pending_exit
                future = pe is not None and pe["fill_on"] > date
                if sessions >= CLOCK and (pe is None or future):
                    position = None
                    pending_exit = None
                elif pe is None:
                    z_now = bt._frozen_z(
                        panel, date, position["alpha"], position["beta"], position["center"], position["scale"]
                    )
                    if np.isfinite(z_now) and abs(z_now) <= EXIT_Z:
                        fill_on = bt._next_session(panel, date)
                        if fill_on is not None:
                            pending_exit = {"fill_on": fill_on}

        cands = by_date.get(date) or []
        free = position is None and pending_entry is None and pending_exit is None
        if free:
            if cands:
                free_days += 1
                best = min(cands, key=lambda r: (-r[0], r[1]))
                _ap, pi, i, zi, pct = best
                panel = panels[pi]
                short_sym, long_sym = _side(panel, pct)
                fill_on = bt._next_session(panel, date)
                runners += len(cands) - 1
                if fill_on is not None:
                    fill_on = pd.Timestamp(fill_on)
                    fill_i = bt._at(panel, fill_on)
                    pending_entry = {
                        "panel": panel,
                        "left": panel["left"],
                        "right": panel["right"],
                        "long": long_sym,
                        "short": short_sym,
                        "entry_date": fill_on,
                        "entry_i": int(fill_i) if fill_i is not None else int(i) + 1,
                        "alpha": float(panel["alpha"][i]),
                        "beta": float(panel["beta"][i]),
                        "center": float(panel["center"][i]),
                        "scale": float(panel["scale"][i]),
                        "fill_on": fill_on,
                    }
                    if fill_on in date_set:
                        accepted.append((panel["left"], panel["right"], _iso(date)))
        elif cands:
            if position is not None:
                reason = "open pair"
                held_left, held_right = position["left"], position["right"]
            else:
                reason = "fill already reserved"
                held_left = pending_entry["left"] if pending_entry else ""
                held_right = pending_entry["right"] if pending_entry else ""
            for rec in cands:
                _ap, pi, i, zi, pct = rec
                panel = panels[pi]
                blocked.append(
                    {
                        "left": panel["left"],
                        "right": panel["right"],
                        "pi": pi,
                        "i": i,
                        "pct": pct,
                        "z": zi,
                        "signal_date": date,
                        "reason": reason,
                        "held_left": held_left,
                        "held_right": held_right,
                    }
                )
    taken_keys = {(t["left"], t["right"], _iso(t["signal_date"])) for t in trades}
    got = set(accepted)
    missing = taken_keys - got
    extra = got - taken_keys
    if missing or extra:
        raise SystemExit(
            f"One-pair signal walk does not match the published replay "
            f"(missing {len(missing)} extra {len(extra)})"
        )
    print(f"blocked gaps {len(blocked)} same-day runners-up {runners}", flush=True)
    return {"blocked": blocked, "runners": runners, "free_days": free_days}


def relation(row: dict) -> str:
    pair = {row["left"], row["right"]}
    held = {row["held_left"], row["held_right"]}
    if pair == held:
        return "same pair"
    if pair & held:
        return "shares a symbol"
    return "different symbols"


def stretch_flags(frame: pd.DataFrame) -> pd.Series:
    """A stretch starts when this pair did not also qualify on the previous blocked bar."""
    if frame.empty:
        return pd.Series(dtype=bool)
    ordered = frame.sort_values(["left", "right", "signal_date", "i"])
    pair = ordered["left"].astype(str) + "\t" + ordered["right"].astype(str)
    prev_i = ordered["i"].groupby(pair, sort=False).shift(1)
    start = prev_i.isna() | (ordered["i"].to_numpy() != prev_i.to_numpy() + 1)
    return pd.Series(start.to_numpy(), index=ordered.index).reindex(frame.index).fillna(False)


def check_published(frame: pd.DataFrame) -> str:
    notes = []
    ok = True
    for sample, pub in PUBLISHED.items():
        view = frame if sample == "full" else frame[frame["sample"] == sample]
        closed = view[view["status"] == "closed"]
        n = int(len(closed))
        wr = 100.0 * float((closed["net_pct"] > 0).mean()) if n else float("nan")
        avg = float(closed["net_pct"].mean()) if n else float("nan")
        n_ok = n == pub["n"]
        wr_ok = np.isfinite(wr) and abs(wr - pub["win_pct"]) <= 0.05
        avg_ok = np.isfinite(avg) and abs(avg - pub["avg_pct"]) <= 0.05
        flag = "match" if n_ok and wr_ok and avg_ok else "MISMATCH"
        if flag != "match":
            ok = False
        notes.append(
            f"{sample} {flag}: n {n} vs {pub['n']}, win {wr:.4f}% vs {pub['win_pct']:.4f}%, "
            f"avg {avg:.4f}% vs {pub['avg_pct']:.4f}%"
        )
        print(notes[-1], flush=True)
    head = "The one-pair book matches the published Z025 page within 0.05 points." if ok else (
        "The one-pair book does not match the published Z025 page within 0.05 points. "
        "The freeze is still Z025. The numbers below are this rerun."
    )
    return head + " " + " ".join(notes)


def slice_stats(frame: pd.DataFrame, equity: pd.DataFrame | None, sample: str, years: float) -> dict:
    view = frame if sample == "full" else frame[frame["sample"] == sample]
    stats = thorp.closed_metrics(view, years)
    if equity is not None and not equity.empty:
        if sample == "IS":
            path_eq = fund_equity(equity, equity["date"] < IS_CUT) if "n_open" in equity.columns else equity[equity["date"] < IS_CUT]
        elif sample == "OOS":
            path_eq = fund_equity(equity, equity["date"] >= IS_CUT) if "n_open" in equity.columns else equity[equity["date"] >= IS_CUT]
        else:
            path_eq = fund_equity(equity) if "n_open" in equity.columns else equity
        path = thorp.path_stats(path_eq)
    else:
        path = {"max_dd": float("nan"), "sharpe": float("nan"), "ann": float("nan")}
    stats["max_dd"] = path["max_dd"]
    stats["sharpe"] = path["sharpe"]
    if np.isfinite(stats["ann_ror"]) and np.isfinite(path["max_dd"]) and abs(path["max_dd"]) > 1e-9:
        stats["calmar"] = float(stats["ann_ror"] / abs(path["max_dd"]))
    else:
        stats["calmar"] = float("nan")
    stats["open_n"] = int((view["status"] == "open").sum()) if not view.empty else 0
    return stats


def judge_multi(marked_m: dict, marked_o: dict) -> tuple[str, str]:
    a = marked_m
    b = marked_o
    if not (np.isfinite(a["avg"]) and np.isfinite(b["avg"])):
        return "HOLD", "The in-sample marked average is not a number, so the multiple book stays a hold."
    gap = float(a["avg"] - b["avg"])
    wr_drop = (b["wr"] - a["wr"]) if np.isfinite(a["wr"]) and np.isfinite(b["wr"]) else float("nan")
    collapsed = b["n"] > 0 and a["n"] < KEEP_N_RATIO_MIN * b["n"]
    base = "Out-of-sample was not used. The 0.25 band and the 15-session clock were not changed."
    if gap < -KEEP_AVG_EDGE:
        return "DISMISS", (
            f"In-sample marked average is {gap:+.2f} points versus the one-pair Z025 book, "
            f"worse than the 1 point bar. {base}"
        )
    if collapsed:
        return "HOLD", f"In-sample marked count is under 80% of the one-pair book. {base}"
    if gap > KEEP_AVG_EDGE and (not np.isfinite(wr_drop) or wr_drop <= KEEP_WR_DROP_MAX):
        return "KEEP", (
            f"In-sample marked average is {gap:+.2f} points above the one-pair Z025 book, "
            "the win rate did not fall by more than 10 points, and the marked count did not collapse. "
            f"Research only. {base}"
        )
    if gap > KEEP_AVG_EDGE and np.isfinite(wr_drop) and wr_drop > KEEP_WR_DROP_MAX:
        return "HOLD", (
            f"In-sample marked average is {gap:+.2f} points higher, but the win rate fell by "
            f"{wr_drop:.1f} points. {base}"
        )
    return "HOLD", (
        f"In-sample marked average is {gap:+.2f} points versus the one-pair Z025 book, inside the 1 point bar. {base}"
    )


def oos_note(multi: dict, one: dict) -> str:
    a = multi["avg_pct"]
    b = one["avg_pct"]
    if np.isfinite(a) and np.isfinite(b) and a < b - KEEP_AVG_EDGE:
        return (
            f"Out-of-sample average is {a - b:+.2f} points versus the one-pair book, softer by more than 1 point. "
            "Report only. Knobs were not changed."
        )
    if np.isfinite(a) and np.isfinite(b) and a < b:
        return (
            f"Out-of-sample average is {a - b:+.2f} points versus the one-pair book. "
            "Report only. Knobs were not changed."
        )
    return "Out-of-sample is report-only. Knobs were not changed."


SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-" || s === "flat") return type === "text" || type === "date" ? "" : 0;
    if (type === "text" || type === "date" || type === "month") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "").replace(/ pp/g, "");
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
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
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
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(headers, function (th, col) {
      if (th.classList.contains("sortable-th")) bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def headline_row(name: str, sample: str, st: dict, base: dict | None) -> str:
    def dlt(key: str) -> str:
        if base is None or not (np.isfinite(st.get(key, np.nan)) and np.isfinite(base.get(key, np.nan))):
            return "—"
        return _pp(st[key] - base[key])

    cells = [
        _td(name),
        _td(sample),
        _td(str(st["n"]), True),
        _td(_pct(st["win_pct"], 1), True),
        _td(_pct(st["avg_pct"]), True),
        _td(_pct(st["ann_ror"], 2), True),
        _td(dlt("win_pct"), True),
        _td(dlt("avg_pct"), True),
        _td(dlt("ann_ror"), True),
        _td(_pct(st["median_pct"]), True),
        _td(str(st["open_n"]), True),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def canon_row(name: str, sample: str, st: dict, base: dict | None) -> str:
    def dlt(key: str) -> str:
        if base is None or not (np.isfinite(st.get(key, np.nan)) and np.isfinite(base.get(key, np.nan))):
            return "—"
        return _pp(st[key] - base[key])

    money = st.get("profit_per_capital_day", float("nan"))
    cells = [
        _td(name),
        _td(sample),
        _td(str(st["n"]), True),
        _td(str(st["wins"]), True),
        _td(str(st["losses"]), True),
        _td(_pct(st["win_pct"], 1), True),
        _td(dlt("win_pct"), True),
        _td(_pct(st["avg_pct"]), True),
        _td(dlt("avg_pct"), True),
        _td(_pct(st["median_pct"]), True),
        _td(_pct(st["avg_win"]), True),
        _td(_pct(st["avg_loss"]), True),
        _td(thorp._pf_text(st["pf"], st["wins"], st["n"]), True),
        _td(_pct(st["wo_max"]), True),
        _td(_pct(st["outlier"], 1), True),
        _td(_pct(st["expectancy_pct"]), True),
        _td(_num(st["tpy"], 2), True),
        _td(_num(st["avg_days"], 1), True),
        _td(_num(st["median_days"], 1), True),
        _td(str(st["capital_days"]), True),
        _td(format_money(money) if np.isfinite(money) else "—", True),
        _td(_pct(st["ann_ror"], 2), True),
        _td(dlt("ann_ror"), True),
        _td(_pct(st["max_dd"], 2), True),
        _td(_num(st["sharpe"], 2), True),
        _td(_num(st["calmar"], 2), True),
        _td(str(st["line_n"]), True),
        _td(str(st["time_n"]), True),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def render(ctx: dict) -> str:
    h_headers = [
        ("Book", "text"),
        ("Slice", "text"),
        ("N", "num"),
        ("Win %", "num"),
        ("Avg %", "num"),
        ("Ann ROR", "num"),
        ("Win % vs one pair", "num"),
        ("Avg % vs one pair", "num"),
        ("Ann ROR vs one pair", "num"),
        ("Median %", "num"),
        ("Still open", "num"),
    ]
    c_headers = [
        ("Book", "text"),
        ("Slice", "text"),
        ("N", "num"),
        ("Wins", "num"),
        ("Losses", "num"),
        ("Win %", "num"),
        ("Win % vs one pair", "num"),
        ("Avg %", "num"),
        ("Avg % vs one pair", "num"),
        ("Median %", "num"),
        ("Avg win %", "num"),
        ("Avg loss %", "num"),
        ("Profit factor", "num"),
        ("Avg % without the largest win", "num"),
        ("Outlier share of winning %", "num"),
        ("Expectancy %", "num"),
        ("Trades per year", "num"),
        ("Avg days held", "num"),
        ("Median days held", "num"),
        ("Capital days", "num"),
        ("Profit per capital day", "num"),
        ("Ann ROR", "num"),
        ("Ann ROR vs one pair", "num"),
        ("Max DD", "num"),
        ("Sharpe", "num"),
        ("Calmar", "num"),
        ("Line exits", "num"),
        ("Clock exits", "num"),
    ]
    books = [("One pair", ctx["one"]), ("Multiple", ctx["multi"]), ("If taken alone", ctx["alone"])]
    headline_rows = []
    canon_rows = []
    for name, pack in books:
        for sample in ("full", "IS", "OOS"):
            base = None if name == "One pair" else ctx["one"][sample]
            headline_rows.append(headline_row(name, sample, pack[sample], base))
            canon_rows.append(canon_row(name, sample, pack[sample], base))
    missed = ctx["missed_screen"]
    miss_rows = []
    for rec in missed.itertuples(index=False):
        when = rec.alone_exit if rec.alone_status == "closed" else rec.alone_mark
        miss_rows.append(
            "<tr>"
            + _td(f"{rec.left}/{rec.right}")
            + _td(rec.signal_date)
            + _td(rec.long_sym)
            + _td(rec.short_sym)
            + _td(rec.held_pair)
            + _td(rec.symbol_link)
            + _td(rec.alone_status)
            + _td(str(when))
            + _td(rec.alone_sample)
            + _td(_pct(rec.alone_net_pct), True)
            + _td(rec.alone_reason)
            + "</tr>"
        )
    screen_note = (
        f"All {ctx['blocked_n']} skipped gaps are in this table."
        if ctx["show_all_missed"]
        else (
            f"First {len(missed)} rows by signal date. The full list of {ctx['blocked_n']} gaps is "
            "missed_if_taken_alone.csv. Sorting works on the rows shown here."
        )
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Similar Stock Difference Z025, many pairs — 2026-10-01</title>
  <style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --warn: #8a5a12; --warn-bg: #f7efe0; --fill: #f0eee6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 16px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }}
  .wrap {{ max-width: 1280px; margin: 0 auto; padding: 36px 22px 72px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }}
  h1 {{ font-size: 1.65rem; margin: 0 0 8px; letter-spacing: -0.02em; line-height: 1.25; }}
  h2 {{ font-size: 1.2rem; margin: 32px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  p, li {{ margin: 0 0 10px; }}
  blockquote.ask {{
    margin: 8px 0 0; white-space: pre-wrap;
    font-family: Georgia, "Times New Roman", serif; font-size: 0.95rem;
  }}
  .callout {{ background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.warn {{ background: var(--warn-bg); border-left-color: var(--warn); }}
  .table-wrap {{ overflow-x: auto; margin: 8px 0 16px; }}
  table.sortable {{ border-collapse: collapse; width: 100%; font-size: 13.5px; background: var(--card); }}
  th, td {{ border: 1px solid var(--line); padding: 7px 8px; text-align: left; vertical-align: top; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  thead th {{ background: var(--fill); }}
  th.sortable-th {{ cursor: pointer; user-select: none; }}
  th.sortable-th:hover {{ background: #e8e4d8; }}
  .sort-ind {{ display: inline-block; width: 0.9em; margin-left: 4px; color: #9a9588; font-size: 10px; }}
  th.sort-asc .sort-ind::after {{ content: "\\25B2"; color: var(--ink); }}
  th.sort-desc .sort-ind::after {{ content: "\\25BC"; color: var(--ink); }}
  caption {{ text-align: left; font-size: 0.86rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }}
  footer {{ margin-top: 28px; font-size: 0.82rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }}
  {RESPONSIVE_TABLE_CSS}
  </style>
</head>
<body>
<div class="wrap">
  <header class="doc-head">
    <p class="eyebrow">Research only · not gold · not DailyRun</p>
    <h1>Similar Stock Difference, frozen Z025, one pair or many</h1>
    {SWIPE_NOTE_HTML}
    <p>Paul locked Z025 on 1 October 2026. The grid had already been seen, and the out-of-sample average on that page was softer than the 0.5-band 15-session baseline. This page does not retune the band or the clock.</p>
  </header>

  <div class="callout">
    <strong>What you asked</strong>
    <blockquote class="ask">{_esc(ORIGINAL_REQUEST)}</blockquote>
  </div>

  <div class="callout">
    <strong>In plain English</strong>
    <p>Similar Stock Difference shorts one stock and buys a similar one when they pull apart. He is locking the exit that gets out at a 0.25 standard-deviation band or after 15 sessions. The old test could only hold one pair, so a second pair had to wait. This page holds many pairs at once, one per stock, like the other systems.</p>
    <p>The one-pair book is the freeze. It is the Z025 arm from the exit grid, still one pair in the whole account. The multiple book uses the same signals and the same exit, and it may hold several pairs at once. A stock can be in only one pair. If a new gap needs a stock that is already in a pair, that gap waits.</p>
  </div>

  <h2>What was frozen before the results</h2>
  <ul>
    <li>{_esc(FREEZE_RULE)}</li>
    <li>Entry stays the saved pair menu: full-window correlation at least 0.60, each half at least 0.55. A gap is a close at least 2 standard deviations off a 252-session ordinary least squares (OLS) line that stops the day before the signal. Short the high side, long the low side, next open.</li>
    <li>The one-pair book, when it is flat, still takes only the largest absolute percent gap that day. That is the published Z025 path. The multiple book takes every gap that day whose two stocks are free.</li>
    <li>In-sample means the entry is before 2024-01-01. Out-of-sample means the entry is on or after that date. Out-of-sample is report-only.</li>
    <li>Annualized rate of return is one plus the total result divided by ($10,000 times the number of closed trades), raised to 365 divided by the average calendar days held, minus one. Ann ROR after that. Paul score and FIT are not on this pairs book.</li>
    <li>Max drawdown on the multiple book uses a starting stake of $10,000 times the busiest pair count seen in that slice. That count was recorded after the run, the same way the other systems record a peak when they are not given a hard cap. It was not used to skip trades. The "if taken alone" rows are each their own $10,000. They are not stacked into one account, so that set has no path drawdown.</li>
    <li>A keep versus the one-pair book needs the in-sample marked average more than 1 point higher, a win rate no worse by more than 10 points, and a marked count at least 80% of the one-pair book. Inside 1 point is a hold. Worse by more than 1 point is a dismiss.</li>
  </ul>

  <div class="callout warn">
    <strong>Verdict</strong>
    <p>Freezing Z025 is Paul's call. Research only. Not gold. Not DailyRun. He chose it after the exit grid was already on the page, and that grid's out-of-sample average for Z025 was softer than the 0.5 band.</p>
    <p><strong>Multiple book versus one-pair Z025: {_esc(ctx["verdict"])}.</strong> {_esc(ctx["verdict_why"])}</p>
    <p>{_esc(ctx["oos_line"])}</p>
    <p>{_esc(ctx["match_line"])}</p>
  </div>

  <h2>One pair and many pairs</h2>
  <p>N, win rate, average percent, and Ann ROR. The "if taken alone" set is every qualifying gap the one-pair book skipped because it was already in a pair, replayed as if that gap had the account to itself. Those rows overlap on the calendar on purpose. They are not the multiple book.</p>
  {_table(h_headers, headline_rows, "Closed trades. Click a column header to sort.")}

  <h2>Book metrics</h2>
  <p>Dollar profit totals are left off this page. Profit per capital day stays. Click a column header to sort.</p>
  {_table(c_headers, canon_rows, "Canonical compare columns. Differences are the row minus the one-pair book on the same slice.")}

  <h2>How many gaps the one-pair book left behind</h2>
  <ul>
    <li>Qualifying gaps while the one-pair account was already in a pair, or already waiting to fill the one it had just taken: <strong>{ctx["blocked_n"]:,}</strong>.</li>
    <li>Of those, {ctx["blocked_open"]:,} were while a pair was open, and {ctx["blocked_pending"]:,} were while the next open was already reserved.</li>
    <li>Same pair still gapping while it was the one being held: {ctx["same_pair"]:,}. A different pair that shares one of those two stocks: {ctx["share_symbol"]:,}. A pair that uses two other stocks: {ctx["disjoint"]:,}.</li>
    <li>Fresh stretches, counting a new stretch only when that pair did not also qualify on the previous blocked bar: {ctx["stretches"]:,}. Unique pairs inside the skipped list: {ctx["unique_pairs"]:,}.</li>
    <li>On days the account was flat, the one-pair book still took only the largest gap. Other gaps that day, not in the busy count above: {ctx["runners"]:,}.</li>
    <li>Observed overlap on the multiple book, recorded after the run and not used as a skip cap: peak {ctx["peak"]} pairs open at once, average {_num(ctx["avg_open"], 2)} pairs, median {_num(ctx["median_open"], 1)} pairs. That is two stocks per pair, and no stock in two pairs.</li>
  </ul>
  <p>{_esc(screen_note)} The percent column is labeled if taken alone. Overlap is allowed in that column only. An open row is a mark at the last price, not a finished exit.</p>
  {_table(
      [
          ("Pair", "text"),
          ("Signal date", "date"),
          ("Long", "text"),
          ("Short", "text"),
          ("Pair already in the account", "text"),
          ("Link to that pair", "text"),
          ("Alone status", "text"),
          ("Alone exit or mark", "date"),
          ("Slice", "text"),
          ("If taken alone", "num"),
          ("Alone exit reason", "text"),
      ],
      miss_rows,
      screen_note,
  )}

  <h2>Why the multiple book is a {_esc(ctx["verdict"])}</h2>
  <p>{_esc(ctx["verdict_why"])} {_esc(ctx["oos_line"])}</p>
  <p>In-sample marked average is {_pct(ctx["marked_one"]["avg"])} on the one-pair book ({ctx["marked_one"]["n"]} marked) and {_pct(ctx["marked_multi"]["avg"])} on the multiple book ({ctx["marked_multi"]["n"]} marked). Median is shown in the tables and is not the verdict input.</p>

  <footer>
    Research only · 1 October 2026 · ssd_z025_multipair_20261001 · not gold · not DailyRun.
    The exit grid folder was not overwritten except for one freeze line on its baseline note.
  </footer>
</div>
{SORT_JS}
</body>
</html>
"""
    return page


def baseline_md(ctx: dict) -> str:
    def line(name: str, sample: str) -> str:
        st = ctx[{"One pair": "one", "Multiple": "multi", "If taken alone": "alone"}[name]][sample]
        return (
            f"| {name} | {sample} | {st['n']} | {st['win_pct']:.1f}% | {st['avg_pct']:+.2f}% | "
            f"{st['ann_ror']:+.2f}% | {st['median_pct']:+.2f}% | "
            f"{'—' if not np.isfinite(st['max_dd']) else format(st['max_dd'], '+.2f') + '%'} |"
        )

    rows = [line(n, s) for n in ("One pair", "Multiple", "If taken alone") for s in ("full", "IS", "OOS")]
    return "\n".join(
        [
            "# Similar Stock Difference, frozen Z025, one pair or many",
            "",
            "Research only. Not gold. Not DailyRun. Z025 is frozen because Paul asked. The exit grid had already been seen, and out-of-sample on that page was softer than the 0.5-band 15-session baseline. The 0.25 band and the 15-session clock were not retuned.",
            "",
            "## What you asked",
            "",
            "> " + ORIGINAL_REQUEST,
            "",
            "## In plain English",
            "",
            "Similar Stock Difference shorts one stock and buys a similar one when they pull apart. He is locking the exit that gets out at a 0.25 standard-deviation band or after 15 sessions. The old test could only hold one pair, so a second pair had to wait. This page holds many pairs at once, one per stock, like the other systems.",
            "",
            "## Freeze, written before these profit numbers",
            "",
            f"- {FREEZE_RULE}",
            "- One pair: the published Z025 path. Flat days take the single largest absolute percent gap.",
            "- Entry: saved 2010 menu, correlation floor 0.60 full window and 0.55 each half, |z| >= 2 on a 252-session OLS line that excludes the signal day, short high / long low, next open, whole shares.",
            "- Replay calendar ends 2026-09-30.",
            "- IS: entry before 2024-01-01. OOS: entry on or after 2024-01-01. OOS is report-only.",
            "- Annualized rate of return uses `compare_format.ann_ror_from_closed` with brt_cash $10,000.",
            "- Multiple-book max drawdown funds $10,000 times the observed peak pair count in that slice, after the run. That peak was not a skip cap.",
            "- If taken alone is a per-trade statistic. Those trades are not one account, so they have no path drawdown.",
            "- KEEP if in-sample marked average beats the one-pair book by more than 1 point, win rate does not fall by more than 10 points, and marked count stays at least 80%. Inside 1 point is HOLD. Worse by more than 1 point is DISMISS.",
            "",
            "## Match to the published Z025 page",
            "",
            ctx["match_line"],
            "",
            "## Results",
            "",
            "| Book | Slice | N | Win % | Avg % | Ann ROR | Median % | Max DD |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            f"Multiple versus one pair: **{ctx['verdict']}.** {ctx['verdict_why']}",
            "",
            ctx["oos_line"],
            "",
            "## Gaps the one-pair book skipped",
            "",
            f"- Qualifying gaps while already in a pair or already waiting to fill one: {ctx['blocked_n']}.",
            f"- While a pair was open: {ctx['blocked_open']}. While a fill was reserved: {ctx['blocked_pending']}.",
            f"- Same pair {ctx['same_pair']}, shares a symbol {ctx['share_symbol']}, different symbols {ctx['disjoint']}.",
            f"- Fresh stretches {ctx['stretches']}. Unique pairs {ctx['unique_pairs']}. Same-day runners-up while flat, not in the busy count: {ctx['runners']}.",
            f"- Multiple book peak open pairs {ctx['peak']} (observed after the run, not a cap). Average {_num(ctx['avg_open'], 2)}.",
            "",
            "Full skipped list: `missed_if_taken_alone.csv`. Trade lists: `trades_one_pair.csv`, `trades_multiple.csv`.",
            "",
        ]
    )


def append_prior_freeze() -> None:
    if not PRIOR_BASELINE.exists():
        print("prior baseline missing; skip append", flush=True)
        return
    text = PRIOR_BASELINE.read_text(encoding="utf-8")
    if "froze Z025 on 2026-10-01" in text:
        print("prior baseline already notes the freeze", flush=True)
        return
    line = (
        "\nPaul froze Z025 (0.25 standard-deviation band or the close of the 15th session, whichever comes first) "
        "on 2026-10-01 for further tests. The grid had already been seen, and out-of-sample was softer. "
        "See `ssd_z025_multipair_20261001`. Not a retune of 0.25 or 15.\n"
    )
    PRIOR_BASELINE.write_text(text.rstrip() + "\n" + line, encoding="utf-8")
    print(f"appended freeze line to {PRIOR_BASELINE}", flush=True)


def assert_alone_matches(trades: list[dict], panel_map: dict, name: str) -> None:
    """A taken signal's Z025 result does not depend on other pairs."""
    bad = 0
    for trade in trades:
        panel = panel_map[(trade["left"], trade["right"])]
        loc = panel["loc"].get(pd.Timestamp(trade["signal_date"]))
        outcome = None if loc is None else alone_outcome(panel, int(loc), float(trade["pct_entry"]))
        got = float(trade["net"]) / STAKE * 100.0
        if (
            outcome is None
            or outcome["status"] != trade["status"]
            or abs(float(outcome["net_pct"]) - got) > 0.02
        ):
            bad += 1
            if bad <= 5:
                print(
                    f"{name} alone mismatch",
                    trade["left"],
                    trade["right"],
                    _iso(trade["signal_date"]),
                    None if outcome is None else (outcome["status"], round(outcome["net_pct"], 4)),
                    trade["status"],
                    round(got, 4),
                    flush=True,
                )
    if bad:
        raise SystemExit(f"{name} alone engine disagrees on {bad} of {len(trades)} trades")
    print(f"{name} alone engine matches {len(trades)} trades", flush=True)


def main() -> None:
    print("FREEZE BEFORE P&L:", FREEZE_RULE, flush=True)
    bt = thorp._load_bt()
    menu = pd.read_csv(thorp.PAIR_MENU)
    menu["left"] = menu["left"].astype(str)
    menu["right"] = menu["right"].astype(str)
    menu["business"] = menu["business"].fillna("") if "business" in menu.columns else ""
    symbols = sorted(set(menu["left"]).union(set(menu["right"])))
    print(f"menu pairs {len(menu)} symbols {len(symbols)}", flush=True)
    close_wide, opens, _hits = thorp.load_prices(symbols, bt)
    panels = bt.build_panels(menu, close_wide, opens)
    panel_map = {(p["left"], p["right"]): p for p in panels}
    by_date, best_on, gap_count, all_dates, n_gaps = collect_signals(panels, bt)

    thorp.EXIT_Z = EXIT_Z
    print("replaying published one-pair Z025", flush=True)
    one_trades, one_eq, _meta = thorp.replay(panels, best_on, gap_count, all_dates, bt, CLOCK)
    one_frame = thorp.trades_frame(one_trades)
    match_line = check_published(one_frame)
    assert_alone_matches(one_trades, panel_map, "one-pair")
    blockers = one_pair_blockers(one_trades, by_date, all_dates, panels, bt)

    print("replaying multiple book", flush=True)
    multi_trades, multi_raw, multi_meta = replay_multi(panels, by_date, all_dates, bt)
    multi_frame = thorp.trades_frame(multi_trades)
    assert_alone_matches(multi_trades, panel_map, "multiple")

    print(f"alone outcomes for {len(blockers['blocked'])} skipped gaps", flush=True)
    missed_rows = []
    alone_frame_rows = []
    for n, row in enumerate(blockers["blocked"], start=1):
        panel = panels[row["pi"]]
        outcome = alone_outcome(panel, row["i"], row["pct"])
        if outcome is None:
            continue
        entry = pd.Timestamp(outcome["entry_date"])
        sample = "IS" if entry < IS_CUT else "OOS"
        exit_or_mark = outcome["exit_date"] if outcome["status"] == "closed" else outcome["mark_date"]
        alone_frame_rows.append(
            {
                "status": outcome["status"],
                "sample": sample,
                "net": outcome["net"],
                "net_pct": outcome["net_pct"],
                "days_held": int((pd.Timestamp(exit_or_mark) - entry).days),
                "reason": outcome["reason"],
            }
        )
        missed_rows.append(
            {
                "left": row["left"],
                "right": row["right"],
                "signal_date": _iso(row["signal_date"]),
                "long_sym": outcome["long"],
                "short_sym": outcome["short"],
                "held_pair": f"{row['held_left']}/{row['held_right']}",
                "symbol_link": relation(row),
                "skip_reason": row["reason"],
                "i": row["i"],
                "alone_status": outcome["status"],
                "alone_entry": _iso(outcome["entry_date"]),
                "alone_exit": _iso(outcome["exit_date"]) if outcome["status"] == "closed" else "",
                "alone_mark": _iso(outcome["mark_date"]) if outcome["status"] != "closed" else "",
                "alone_sample": sample,
                "alone_net_pct": outcome["net_pct"],
                "alone_reason": outcome["reason"],
                "alone_days": int((pd.Timestamp(exit_or_mark) - entry).days),
            }
        )
        if n % 20000 == 0:
            print(f"alone {n}", flush=True)

    missed = pd.DataFrame(missed_rows)
    if missed.empty:
        missed = pd.DataFrame(
            columns=[
                "left", "right", "signal_date", "long_sym", "short_sym", "held_pair", "symbol_link",
                "skip_reason", "i", "alone_status", "alone_entry", "alone_exit", "alone_mark",
                "alone_sample", "alone_net_pct", "alone_reason", "alone_days",
            ]
        )
    missed["stretch_start"] = stretch_flags(missed) if not missed.empty else False
    alone_for_metrics = (
        pd.DataFrame(alone_frame_rows)
        if alone_frame_rows
        else pd.DataFrame(columns=["status", "sample", "net", "net_pct", "days_held", "reason"])
    )

    full_y, is_y, oos_y = thorp.slice_years(one_eq)
    one_pack = {s: slice_stats(one_frame, None, s, y) for s, y in (("full", full_y), ("IS", is_y), ("OOS", oos_y))}
    # One-pair path is the published $10,000 account, not a re-funded peak.
    for sample, eq_view in (
        ("full", one_eq),
        ("IS", one_eq[one_eq["date"] < IS_CUT]),
        ("OOS", one_eq[one_eq["date"] >= IS_CUT]),
    ):
        path = thorp.path_stats(eq_view)
        one_pack[sample]["max_dd"] = path["max_dd"]
        one_pack[sample]["sharpe"] = path["sharpe"]
        one_pack[sample]["calmar"] = (
            float(one_pack[sample]["ann_ror"] / abs(path["max_dd"]))
            if np.isfinite(one_pack[sample]["ann_ror"]) and np.isfinite(path["max_dd"]) and abs(path["max_dd"]) > 1e-9
            else float("nan")
        )

    multi_pack = {s: slice_stats(multi_frame, multi_raw, s, y) for s, y in (("full", full_y), ("IS", is_y), ("OOS", oos_y))}
    alone_pack = {s: slice_stats(alone_for_metrics, None, s, y) for s, y in (("full", full_y), ("IS", is_y), ("OOS", oos_y))}

    marked_one = {
        "n": int(len(thorp.marked_is_pcts(one_frame, one_trades, panel_map, bt))),
        "avg": float("nan"),
        "wr": float("nan"),
    }
    pcts_one = thorp.marked_is_pcts(one_frame, one_trades, panel_map, bt)
    if pcts_one:
        arr = np.asarray(pcts_one, dtype=float)
        marked_one = {"n": int(len(arr)), "avg": float(np.mean(arr)), "wr": 100.0 * float(np.mean(arr > 0))}
    pcts_multi = thorp.marked_is_pcts(multi_frame, multi_trades, panel_map, bt)
    marked_multi = {"n": 0, "avg": float("nan"), "wr": float("nan")}
    if pcts_multi:
        arr = np.asarray(pcts_multi, dtype=float)
        marked_multi = {"n": int(len(arr)), "avg": float(np.mean(arr)), "wr": 100.0 * float(np.mean(arr > 0))}
    verdict, why = judge_multi(marked_multi, marked_one)
    oos_line = oos_note(multi_pack["OOS"], one_pack["OOS"])
    print(f"VERDICT {verdict}", flush=True)
    print(why, flush=True)
    print(oos_line, flush=True)

    counts = missed["symbol_link"].value_counts().to_dict() if not missed.empty else {}
    show_all = len(missed) <= HTML_FULL_MAX
    screen = missed.sort_values(["signal_date", "left", "right"]) if not missed.empty else missed
    if not show_all:
        screen = screen.head(HTML_SCREEN)

    ctx = {
        "one": one_pack,
        "multi": multi_pack,
        "alone": alone_pack,
        "verdict": verdict,
        "verdict_why": why,
        "oos_line": oos_line,
        "match_line": match_line,
        "missed_screen": screen,
        "show_all_missed": show_all,
        "blocked_n": int(len(missed)),
        "blocked_open": int((missed["skip_reason"] == "open pair").sum()) if not missed.empty else 0,
        "blocked_pending": int((missed["skip_reason"] == "fill already reserved").sum()) if not missed.empty else 0,
        "same_pair": int(counts.get("same pair", 0)),
        "share_symbol": int(counts.get("shares a symbol", 0)),
        "disjoint": int(counts.get("different symbols", 0)),
        "stretches": int(missed["stretch_start"].sum()) if not missed.empty else 0,
        "unique_pairs": int(missed.groupby(["left", "right"]).ngroups) if not missed.empty else 0,
        "runners": int(blockers["runners"]),
        "peak": int(multi_meta["peak_open_pairs"]),
        "avg_open": float(multi_meta["avg_open_pairs"]),
        "median_open": float(multi_meta["median_open_pairs"]),
        "marked_one": marked_one,
        "marked_multi": marked_multi,
        "n_gaps": n_gaps,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    one_frame.to_csv(OUT / "trades_one_pair.csv", index=False)
    multi_frame.to_csv(OUT / "trades_multiple.csv", index=False)
    missed.sort_values(["signal_date", "left", "right"]).to_csv(OUT / "missed_if_taken_alone.csv", index=False)
    summary_rows = []
    for name, pack in (("one_pair", one_pack), ("multiple", multi_pack), ("if_taken_alone", alone_pack)):
        for sample, st in pack.items():
            summary_rows.append({"book": name, "sample": sample, "verdict": verdict if name == "multiple" else "", **st})
    pd.DataFrame(summary_rows).to_csv(OUT / "summary.csv", index=False)
    (OUT / "report.html").write_text(render(ctx), encoding="utf-8")
    (OUT / "BASELINE.md").write_text(baseline_md(ctx), encoding="utf-8")
    append_prior_freeze()
    print(f"wrote {OUT}", flush=True)
    for sample in ("full", "IS", "OOS"):
        a, b = one_pack[sample], multi_pack[sample]
        print(
            f"{sample} one n {a['n']} wr {a['win_pct']:.2f} avg {a['avg_pct']:.2f} ann {a['ann_ror']:.2f} | "
            f"multi n {b['n']} wr {b['win_pct']:.2f} avg {b['avg_pct']:.2f} ann {b['ann_ror']:.2f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
