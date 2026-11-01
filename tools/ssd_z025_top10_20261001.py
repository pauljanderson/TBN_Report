#!/usr/bin/env python3
"""Similar Stock Difference, frozen Z025, up to ten pairs at once.

Research only. Not gold. Not DailyRun. Does not change the one-pair freeze.
The position cap below is frozen in this file before any profit number is read.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT))

import ssd_z025_multipair_20261001 as multi  # noqa: E402
import thorp_timestop_and_chain_scan_20261001 as thorp  # noqa: E402
from compare_format import ann_ror_from_closed, format_money  # noqa: E402
from report_page_extras import RESPONSIVE_TABLE_CSS, SWIPE_NOTE_HTML  # noqa: E402

OUT = ROOT / "drive" / "paul_experiments" / "ssd_z025_top10_20261001"
MAX_PAIRS = 10
STAKE = thorp.STAKE
RESERVED = STAKE * MAX_PAIRS
ONE_RESERVED = STAKE
EXIT_Z = multi.EXIT_Z
CLOCK = multi.CLOCK
IS_CUT = thorp.IS_CUT
STUDY_END = multi.STUDY_END
KEEP_AVG_EDGE = 1.0
KEEP_WR_DROP_MAX = 10.0
KEEP_N_RATIO_MIN = 0.80

# Frozen before this script looks at profit.
FREEZE_RULE = (
    "The account may hold at most 10 pairs. A pair is eligible only when both "
    "symbols are free. Each day, fill the open slots with the largest absolute "
    "percent gaps whose stocks are free, largest first, until 10 pairs are "
    "reserved or the eligible list runs out. A fill that has not happened yet "
    "already uses a slot and both symbols. Do not take an 11th. Do not keep "
    "today's leftovers for tomorrow. Tomorrow ranks whatever is still a live "
    "gap and free. If two candidates share a stock, the wider percent gap gets "
    "that stock; a tie keeps the earlier pair in the saved menu. Each leg is "
    "about $10,000 of whole shares. The return percent divides the pair result "
    "by $10,000. The exit stays 0.25 standard deviations or the close of the "
    "15th session, whichever comes first. The ranker stays the largest absolute "
    "percent gap."
)

ORIGINAL_REQUEST = "what if we traded up to the top ten widest gaps at a time?"

# Cited from ssd_z025_multipair_20261001/summary.csv. Not rerun here.
UNLIMITED = {
    "full": {"n": 28015, "win_pct": 52.05425664822416, "avg_pct": 0.3310123082315188, "ann_ror": 5.8033193744257305},
    "IS": {"n": 23133, "win_pct": 52.25003242121644, "avg_pct": 0.357765362373795, "ann_ror": 6.29265580132905},
    "OOS": {"n": 4882, "win_pct": 51.12658746415404, "avg_pct": 0.2042449175159773, "ann_ror": 3.5267563437660465},
}
UNLIMITED_SOURCE = "ssd_z025_multipair_20261001/summary.csv"


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


def _table(headers: list[tuple[str, str]], rows: list[str], caption: str) -> str:
    head = "".join(_th(label, sort) for label, sort in headers)
    body = "".join(rows)
    cap = f"{caption} Click a column header to sort. Swipe sideways to see more columns."
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(cap)}</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def replay_top10(panels: list[dict], by_date: dict, all_dates: list, bt) -> tuple[list[dict], pd.DataFrame, dict]:
    """Same engine as the unlimited book, stopped at 10 reserved pairs."""
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
    skipped_cap = 0
    skipped_nofill = 0
    days_cap_bound = 0
    breached = 0

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

    def slots_used() -> int:
        return len(positions) + len(pending_entries)

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
        if slots_used() >= MAX_PAIRS:
            return False
        fill_on = bt._next_session(panel, date)
        if fill_on is None:
            return False
        short_sym, long_sym = multi._side(panel, pct)
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

        left_behind = 0
        cands = by_date.get(date)
        if cands:
            for rec in sorted(cands, key=lambda r: (-r[0], r[1])):
                panel = panels[rec[1]]
                if held(panel["left"]) or held(panel["right"]):
                    skipped_busy += 1
                    continue
                if slots_used() >= MAX_PAIRS:
                    left_behind += 1
                    skipped_cap += 1
                    continue
                if not accept(rec, date):
                    skipped_nofill += 1
        if left_behind:
            days_cap_bound += 1
        slot_n = slots_used()
        if slot_n > MAX_PAIRS:
            breached += 1

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
                "n_slots": slot_n,
                "left_behind": left_behind,
                "equity": RESERVED + realized + unreal,
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
    n_days = int(len(raw))
    full_days = int((raw["n_slots"] >= MAX_PAIRS).sum()) if n_days else 0
    meta = {
        "signals_taken": taken,
        "signals_skipped_symbol_busy": skipped_busy,
        "signals_skipped_cap": skipped_cap,
        "signals_skipped_nofill": skipped_nofill,
        "days_cap_bound": days_cap_bound,
        "slot_breaches": breached,
        "calendar_days": n_days,
        "days_full": full_days,
        "pct_days_full": (100.0 * full_days / n_days) if n_days else float("nan"),
        "peak_open_pairs": int(raw["n_open"].max()) if n_days else 0,
        "avg_open_pairs": float(raw["n_open"].mean()) if n_days else 0.0,
        "median_open_pairs": float(raw["n_open"].median()) if n_days else 0.0,
        "peak_slots": int(raw["n_slots"].max()) if n_days else 0,
        "avg_slots": float(raw["n_slots"].mean()) if n_days else 0.0,
        "median_slots": float(raw["n_slots"].median()) if n_days else 0.0,
        "slot_counts": {i: int((raw["n_slots"] == i).sum()) for i in range(0, MAX_PAIRS + 1)} if n_days else {},
    }
    print(
        f"top10 taken {taken} cap_skips {skipped_cap} busy {skipped_busy} "
        f"days_full {full_days}/{n_days} peak_open {meta['peak_open_pairs']} peak_slots {meta['peak_slots']}",
        flush=True,
    )
    if breached:
        raise SystemExit(f"slot cap breached on {breached} days")
    return trades, raw, meta


def calendar_days(equity: pd.DataFrame, sample: str) -> int:
    if equity is None or equity.empty:
        return 1
    first = pd.Timestamp(equity["date"].iloc[0])
    last = pd.Timestamp(equity["date"].iloc[-1])
    if sample == "IS":
        end = min(last, IS_CUT)
        return max(int((end - first).days), 1)
    if sample == "OOS":
        start = max(first, IS_CUT)
        return max(int((last - start).days), 1)
    return max(int((last - first).days), 1)


def account_ann_ror(frame: pd.DataFrame, equity: pd.DataFrame, sample: str, reserved: float) -> float:
    """House formula on the reserved account, not on one $10,000 ticket.

    n_trades is 1 and the hold is the slice calendar, so the dollars are the
    combined closed book and idle slots stay inside the reserved cash.
    """
    view = frame if sample == "full" else frame[frame["sample"] == sample]
    closed = view[view["status"] == "closed"] if not view.empty else view
    total = float(closed["net"].sum()) if not closed.empty else 0.0
    ann = ann_ror_from_closed(
        total_pnl=total,
        n_trades=1,
        avg_days_held=float(calendar_days(equity, sample)),
        brt_cash=reserved,
    )
    return float(ann) if ann is not None else float("nan")


def reserved_path(raw: pd.DataFrame, sample: str, reserved: float) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["date", "equity"])
    if sample == "IS":
        view = raw.loc[raw["date"] < IS_CUT]
    elif sample == "OOS":
        view = raw.loc[raw["date"] >= IS_CUT]
    else:
        view = raw
    if view.empty:
        return pd.DataFrame(columns=["date", "equity"])
    if sample == "full":
        base = 0.0
    else:
        loc = raw.index.get_loc(view.index[0])
        loc = int(loc) if not isinstance(loc, slice) else int(loc.start)
        base = float(raw["realized"].iloc[loc - 1]) if loc > 0 else 0.0
    out = view[["date"]].copy()
    out["equity"] = reserved + view["realized"].to_numpy() - base + view["unreal"].to_numpy()
    return out.reset_index(drop=True)


def enrich(stats: dict, frame: pd.DataFrame, equity: pd.DataFrame | None, sample: str, reserved: float) -> dict:
    stats = dict(stats)
    stats["ann_ror_trade"] = float(stats.get("ann_ror", float("nan")))
    if equity is None or equity.empty or "realized" not in getattr(equity, "columns", []):
        stats["ann_ror_account"] = float("nan")
        return stats
    stats["ann_ror_account"] = account_ann_ror(frame, equity, sample, reserved)
    path = thorp.path_stats(reserved_path(equity, sample, reserved))
    stats["max_dd"] = path["max_dd"]
    stats["sharpe"] = path["sharpe"]
    if np.isfinite(stats["ann_ror_account"]) and np.isfinite(path["max_dd"]) and abs(path["max_dd"]) > 1e-9:
        stats["calmar_account"] = float(stats["ann_ror_account"] / abs(path["max_dd"]))
    else:
        stats["calmar_account"] = float("nan")
    if np.isfinite(stats["ann_ror_trade"]) and np.isfinite(path["max_dd"]) and abs(path["max_dd"]) > 1e-9:
        stats["calmar"] = float(stats["ann_ror_trade"] / abs(path["max_dd"]))
    else:
        stats["calmar"] = float("nan")
    return stats


def judge(top: dict, one: dict) -> tuple[str, str, bool]:
    if not (np.isfinite(top["avg_pct"]) and np.isfinite(one["avg_pct"])):
        return "HOLD", "The in-sample average is not a number, so the top-ten book stays a hold.", False
    gap = float(top["avg_pct"] - one["avg_pct"])
    wr_drop = (one["win_pct"] - top["win_pct"]) if np.isfinite(top["win_pct"]) and np.isfinite(one["win_pct"]) else float("nan")
    collapsed = one["n"] > 0 and top["n"] < KEEP_N_RATIO_MIN * one["n"]
    base = (
        "Out-of-sample was not used to pick the exit or the ranker. "
        "The 0.25 band and the 15-session clock were not changed. "
        "The one-pair freeze stays the published rule. This page is not DailyRun."
    )
    softened_later = False
    if gap < -KEEP_AVG_EDGE:
        label, why = "DISMISS", (
            f"In-sample average is {gap:+.2f} points versus the one-pair Z025 book, "
            f"worse than the 1 point bar. {base}"
        )
    elif collapsed:
        label, why = "HOLD", f"In-sample count is under 80% of the one-pair book. {base}"
    elif gap > KEEP_AVG_EDGE and (not np.isfinite(wr_drop) or wr_drop <= KEEP_WR_DROP_MAX):
        label, why = "KEEP", (
            f"In-sample average is {gap:+.2f} points above the one-pair Z025 book, "
            "the win rate did not fall by more than 10 points, and the count did not collapse. "
            f"Research keep only. Not adopted. Not wired. {base}"
        )
    elif gap > KEEP_AVG_EDGE and np.isfinite(wr_drop) and wr_drop > KEEP_WR_DROP_MAX:
        label, why = "HOLD", (
            f"In-sample average is {gap:+.2f} points higher, but the win rate fell by {wr_drop:.1f} points. {base}"
        )
    else:
        label, why = "HOLD", (
            f"In-sample average is {gap:+.2f} points versus the one-pair Z025 book, inside the 1 point bar. {base}"
        )
    return label, why, softened_later


def apply_oos_hold(label: str, why: str, top_oos: dict, top_is: dict, one_oos: dict) -> tuple[str, str, str]:
    notes = []
    own = top_oos["avg_pct"] - top_is["avg_pct"] if np.isfinite(top_oos["avg_pct"]) and np.isfinite(top_is["avg_pct"]) else float("nan")
    vs = top_oos["avg_pct"] - one_oos["avg_pct"] if np.isfinite(top_oos["avg_pct"]) and np.isfinite(one_oos["avg_pct"]) else float("nan")
    if np.isfinite(own) and own < -KEEP_AVG_EDGE:
        notes.append(
            f"Out-of-sample average is {own:+.2f} points versus this book's own in-sample average, softer by more than 1 point."
        )
        if label == "KEEP":
            label = "HOLD"
            why = why + " Out-of-sample softened versus this book's in-sample average, so the research keep is a hold. Knobs were not changed."
    elif np.isfinite(own) and own < 0:
        notes.append(f"Out-of-sample average is {own:+.2f} points versus this book's own in-sample average.")
    else:
        notes.append("Out-of-sample average is not softer than this book's own in-sample average.")
    if np.isfinite(vs) and vs < -KEEP_AVG_EDGE:
        notes.append(
            f"Against the one-pair book, out-of-sample average is {vs:+.2f} points, softer by more than 1 point."
        )
    elif np.isfinite(vs):
        notes.append(f"Against the one-pair book, out-of-sample average is {vs:+.2f} points.")
    notes.append("Report only. Knobs were not changed.")
    return label, why, " ".join(notes)


SORT_JS = multi.SORT_JS


def headline_row(name: str, sample: str, st: dict, base: dict | None, account_note: str) -> str:
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
        _td(_pct(st.get("ann_ror_trade", st.get("ann_ror")), 2), True),
        _td(dlt("ann_ror_trade") if "ann_ror_trade" in st else dlt("ann_ror"), True),
        _td(_pct(st.get("ann_ror_account", float("nan")), 2), True),
        _td(account_note),
        _td(_pct(st.get("median_pct", float("nan"))), True),
        _td(_pct(st.get("max_dd", float("nan")), 2), True),
        _td(str(st.get("open_n", "—")), True),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def unlimited_row(sample: str) -> str:
    st = UNLIMITED[sample]
    cells = [
        _td("Unlimited, cited"),
        _td(sample),
        _td(str(st["n"]), True),
        _td(_pct(st["win_pct"], 1), True),
        _td(_pct(st["avg_pct"]), True),
        _td(_pct(st["ann_ror"], 2), True),
        _td("—"),
        _td("not rerun"),
        _td("$10,000 per trade, already published"),
        _td("—"),
        _td("—"),
        _td("—"),
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def canon_row(name: str, sample: str, st: dict, base: dict | None) -> str:
    def dlt(key: str) -> str:
        if base is None or not (np.isfinite(st.get(key, np.nan)) and np.isfinite(base.get(key, np.nan))):
            return "—"
        return _pp(st[key] - base[key])

    money = st.get("profit_per_capital_day", float("nan"))
    trade_ann = st.get("ann_ror_trade", st.get("ann_ror", float("nan")))
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
        _td(_pct(trade_ann, 2), True),
        _td(_pct(st.get("ann_ror_account", float("nan")), 2), True),
        _td(_pct(st["max_dd"], 2), True),
        _td(_num(st["sharpe"], 2), True),
        _td(_num(st.get("calmar_account", float("nan")), 2), True),
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
        ("Per-trade Ann ROR", "num"),
        ("Per-trade Ann ROR vs one pair", "num"),
        ("Account Ann ROR", "num"),
        ("Account capital", "text"),
        ("Median %", "num"),
        ("Max DD", "num"),
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
        ("Per-trade Ann ROR", "num"),
        ("Account Ann ROR", "num"),
        ("Max DD", "num"),
        ("Sharpe", "num"),
        ("Calmar on account Ann ROR", "num"),
        ("Line exits", "num"),
        ("Clock exits", "num"),
    ]
    headline_rows = []
    canon_rows = []
    for name, pack, reserved_label, base_ok in (
        ("One pair", ctx["one"], "$10,000, one slot", False),
        ("Top 10", ctx["top"], "$100,000 reserved, 10 slots", True),
    ):
        for sample in ("full", "IS", "OOS"):
            base = ctx["one"][sample] if base_ok else None
            headline_rows.append(headline_row(name, sample, pack[sample], base, reserved_label))
            canon_rows.append(canon_row(name, sample, pack[sample], base))
    for sample in ("full", "IS", "OOS"):
        headline_rows.append(unlimited_row(sample))

    occ_rows = []
    counts = ctx["slot_counts"]
    for n in range(0, MAX_PAIRS + 1):
        days = int(counts.get(n, 0))
        share = 100.0 * days / ctx["calendar_days"] if ctx["calendar_days"] else float("nan")
        occ_rows.append(
            "<tr>" + _td(str(n), True) + _td(str(days), True) + _td(f"{share:.1f}%", True) + "</tr>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Similar Stock Difference Z025, top ten gaps — 2026-10-01</title>
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
    <h1>Similar Stock Difference, frozen Z025, up to ten pairs</h1>
    {SWIPE_NOTE_HTML}
    <p>The one-pair rule stays as published. This page answers a what-if. It does not retune the 0.25 band, the 15-session clock, or the widest-gap ranker.</p>
  </header>

  <div class="callout">
    <strong>What you asked</strong>
    <blockquote class="ask">{_esc(ORIGINAL_REQUEST)}</blockquote>
  </div>

  <div class="callout">
    <strong>In plain English</strong>
    <p>Similar Stock Difference shorts one stock and buys a similar one when they pull apart. A standard deviation is the usual size of that pull, measured off a straight line fit to the prior 252 sessions. This test lets the account hold up to ten of these pairs at once, always the ten widest gaps whose stocks are free. It still sells the one that ran ahead and buys the one that lagged, and it still gets out when the gap is back within 0.25 standard deviations, or after 15 sessions, whichever comes first.</p>
    <p>Annualized rate of return is the house yearly pace. The per-trade figure uses a $10,000 stake, the same way as the one-pair page, so the averages can be compared. The account figure uses $100,000 reserved for the ten slots, even on days fewer than ten pairs are filled. Empty slots are cash that earned nothing. Those two yearly paces are not the same number.</p>
  </div>

  <h2>What was frozen before the results</h2>
  <ul>
    <li>{_esc(FREEZE_RULE)}</li>
    <li>Entry stays the saved pair menu: full-window correlation at least 0.60, each half at least 0.55. A gap is a close at least 2 standard deviations off a 252-session ordinary least squares line that stops the day before the signal. Short the high side, long the low side, next open.</li>
    <li>In-sample means the entry is before 2024-01-01. Out-of-sample means the entry is on or after that date. Out-of-sample is report-only.</li>
    <li>Per-trade annualized rate of return calls <code>compare_format.ann_ror_from_closed</code> with cash $10,000, the trade count, and the average days held. That is the same formula <code>rocket_tbn.compute_metrics</code> uses, and the same call as the one-pair page.</li>
    <li>Account annualized rate of return calls the same function with one combined result, cash equal to the reserved account, and the slice calendar as the hold. Top 10 reserves $100,000 (ten slots of $10,000) on every day, including days with fewer than ten pairs. One pair, in that column only, reserves $10,000. This was not on the earlier pages.</li>
    <li>A keep versus the one-pair book needs the in-sample average more than 1 point higher, a win rate no worse by more than 10 points, and a count at least 80% of the one-pair book. Inside 1 point is a hold. Worse by more than 1 point is a dismiss. If out-of-sample is softer than this book's own in-sample average by more than 1 point, a keep becomes a hold. Nothing is wired.</li>
  </ul>

  <div class="callout warn">
    <strong>Verdict</strong>
    <p><strong>Top 10 versus one-pair Z025: {_esc(ctx["verdict"])}.</strong> {_esc(ctx["verdict_why"])}</p>
    <p>{_esc(ctx["oos_line"])}</p>
    <p>{_esc(ctx["match_line"])}</p>
    <p>Unlimited pairs were not rerun. The unlimited row cites {_esc(UNLIMITED_SOURCE)}. That book's in-sample average was {_pct(UNLIMITED["IS"]["avg_pct"])}, which is why it was a dismiss next to the one-pair book. Its published annualized rate of return is the per-trade $10,000 figure.</p>
  </div>

  <h2>One pair, top ten, and the unlimited book</h2>
  <p>Per-trade annualized rate of return is the comparison to the one-pair page. Account annualized rate of return annualizes the combined closed profit on the cash the book reserved. For the top-ten book that cash is $100,000 even when fewer than ten pairs are open. The unlimited account pace was not recomputed.</p>
  {_table(h_headers, headline_rows, "Closed trades. Unlimited numbers are cited, not rerun.")}

  <h2>How often the book held ten</h2>
  <ul>
    <li>Calendar days in the replay: {ctx["calendar_days"]:,}.</li>
    <li>Days with 10 slots reserved after that day's fills and new signals: <strong>{ctx["days_full"]:,}</strong> ({_num(ctx["pct_days_full"], 1)}% of calendar days). A slot is an open pair or a fill that has not happened yet.</li>
    <li>Days the cap turned away at least one eligible gap (both stocks free, and the book already held 10): {ctx["days_cap_bound"]:,}.</li>
    <li>Signals taken: {ctx["taken"]:,}. Eligible gaps refused because the book was already at 10: {ctx["skipped_cap"]:,}. Gaps skipped because a stock was already in a pair: {ctx["skipped_busy"]:,}. Gaps with no next open inside the study: {ctx["skipped_nofill"]:,}.</li>
    <li>Filled pairs (not counting a fill that is still waiting for the next open): average {_num(ctx["avg_open"], 2)}, median {_num(ctx["median_open"], 1)}, peak {ctx["peak_open"]}. Reserved slots: average {_num(ctx["avg_slots"], 2)}, median {_num(ctx["median_slots"], 1)}, peak {ctx["peak_slots"]}.</li>
    <li>The account annualized rate of return still charges the empty slots, because the reserved cash stays $100,000 on the quiet days.</li>
  </ul>
  {_table(
      [("Slots reserved", "num"), ("Days", "num"), ("Share of calendar", "num")],
      occ_rows,
      "How many pairs the account had reserved at the end of each session.",
  )}

  <h2>Book metrics</h2>
  <p>One pair and top 10 only. Dollar profit totals are left off this page. Profit per capital day stays. The unlimited book is in the first table only, from the earlier page. Max drawdown and Sharpe use a path that starts at the reserved cash: $10,000 for one pair, $100,000 for top 10. Calmar divides the account annualized rate of return by the absolute max drawdown on that same path. The earlier one-pair Calmar used the per-trade annualized rate; that older figure is not repeated as a delta here.</p>
  {_table(c_headers, canon_rows, "One pair and top 10. Differences are the top-ten row minus the one-pair book on the same slice.")}

  <h2>Why the top-ten book is a {_esc(ctx["verdict"])}</h2>
  <p>{_esc(ctx["verdict_why"])} {_esc(ctx["oos_line"])}</p>
  <p>Closed in-sample average is {_pct(ctx["one"]["IS"]["avg_pct"])} on the one-pair book ({ctx["one"]["IS"]["n"]} trades) and {_pct(ctx["top"]["IS"]["avg_pct"])} on the top-ten book ({ctx["top"]["IS"]["n"]} trades). The per-trade annualized rates are {_pct(ctx["one"]["IS"]["ann_ror_trade"], 2)} and {_pct(ctx["top"]["IS"]["ann_ror_trade"], 2)}. The account rates, on $10,000 and $100,000, are {_pct(ctx["one"]["IS"]["ann_ror_account"], 2)} and {_pct(ctx["top"]["IS"]["ann_ror_account"], 2)}.</p>
  <p>Trades: <code>trades_top10.csv</code>. Research only. Not gold. Not DailyRun.</p>

  <footer>
    Research only · 1 October 2026 · ssd_z025_top10_20261001 · not gold · not DailyRun.
    The one-pair, multipair, exit-grid, and pair-choice folders were not overwritten.
  </footer>
</div>
{SORT_JS}
</body>
</html>
"""
    return page


def baseline_md(ctx: dict) -> str:
    def line(name: str, sample: str, st: dict, capital: str) -> str:
        trade = st.get("ann_ror_trade", st.get("ann_ror", float("nan")))
        acct = st.get("ann_ror_account", float("nan"))
        return (
            f"| {name} | {sample} | {st['n']} | {st['win_pct']:.1f}% | {st['avg_pct']:+.2f}% | "
            f"{trade:+.2f}% | {acct:+.2f}% | {capital} |"
        )

    rows = []
    for name, key, capital in (
        ("One pair", "one", "$10,000"),
        ("Top 10", "top", "$100,000 reserved"),
    ):
        for sample in ("full", "IS", "OOS"):
            rows.append(line(name, sample, ctx[key][sample], capital))
    for sample in ("full", "IS", "OOS"):
        st = UNLIMITED[sample]
        rows.append(
            f"| Unlimited, cited | {sample} | {st['n']} | {st['win_pct']:.1f}% | {st['avg_pct']:+.2f}% | "
            f"{st['ann_ror']:+.2f}% | not rerun | published per-trade $10,000 |"
        )
    return "\n".join(
        [
            "# Similar Stock Difference, frozen Z025, up to ten pairs",
            "",
            "Research only. Not gold. Not DailyRun. The one-pair Z025 rule is unchanged. The 0.25 band, the 15-session clock, and the widest-gap ranker were not retuned.",
            "",
            "## What you asked",
            "",
            "> " + ORIGINAL_REQUEST,
            "",
            "## In plain English",
            "",
            "Similar Stock Difference shorts one stock and buys a similar one when they pull apart. A standard deviation is the usual size of that pull, measured off a straight line fit to the prior 252 sessions. This test lets the account hold up to ten of these pairs at once, always the ten widest gaps whose stocks are free. It still sells the one that ran ahead and buys the one that lagged, and it still gets out when the gap is back within 0.25 standard deviations, or after 15 sessions, whichever comes first. Annualized rate of return is the house yearly pace. The per-trade figure uses a $10,000 stake. The account figure uses $100,000 reserved for ten slots, even on days fewer than ten pairs are filled.",
            "",
            "## Freeze, written before these profit numbers",
            "",
            f"- {FREEZE_RULE}",
            "- One pair: the published Z025 path, rerun here as a check. Flat days take the single largest absolute percent gap.",
            "- Unlimited: cited from `ssd_z025_multipair_20261001/summary.csv`. Not rerun.",
            "- Entry: saved 2010 menu, correlation floor 0.60 full window and 0.55 each half, |z| >= 2 on a 252-session OLS line that excludes the signal day, short high / long low, next open, whole shares.",
            "- Replay calendar ends 2026-09-30.",
            "- IS: entry before 2024-01-01. OOS: entry on or after 2024-01-01. OOS is report-only.",
            "- Per-trade annualized rate of return: `compare_format.ann_ror_from_closed`, brt_cash $10,000, same formula as `rocket_tbn.compute_metrics`.",
            "- Account annualized rate of return: the same function, n_trades 1, brt_cash equal to cash reserved, avg days equal to the slice calendar. Top 10 reserves $100,000 even when fewer than 10 pairs are open. One pair reserves $10,000 in that column.",
            "- KEEP if in-sample average beats the one-pair book by more than 1 point, win rate does not fall by more than 10 points, and count stays at least 80%. Inside 1 point is HOLD. Worse by more than 1 point is DISMISS. OOS softer than this book's own IS by more than 1 point turns KEEP into HOLD. Not adopted. Not DailyRun.",
            "",
            "## Match to the published Z025 page",
            "",
            ctx["match_line"],
            "",
            "## Results",
            "",
            "| Book | Slice | N | Win % | Avg % | Per-trade Ann ROR | Account Ann ROR | Account capital |",
            "|---|---|---:|---:|---:|---:|---:|---|",
            *rows,
            "",
            f"Top 10 versus one pair: **{ctx['verdict']}.** {ctx['verdict_why']}",
            "",
            ctx["oos_line"],
            "",
            "## How often the book was full",
            "",
            f"- Calendar days {ctx['calendar_days']}. Days with 10 slots reserved: {ctx['days_full']} ({ctx['pct_days_full']:.1f}%).",
            f"- Days the cap turned away at least one eligible gap: {ctx['days_cap_bound']}.",
            f"- Taken {ctx['taken']}. Refused at the cap {ctx['skipped_cap']}. Symbol busy {ctx['skipped_busy']}. No fill {ctx['skipped_nofill']}.",
            f"- Open pairs average {ctx['avg_open']:.2f}, median {ctx['median_open']:.1f}, peak {ctx['peak_open']}.",
            f"- Reserved slots average {ctx['avg_slots']:.2f}, median {ctx['median_slots']:.1f}, peak {ctx['peak_slots']}.",
            "",
            "Trades: `trades_top10.csv`.",
            "",
        ]
    )


def main() -> None:
    print("FREEZE BEFORE P&L:", FREEZE_RULE, flush=True)
    print(f"MAX_PAIRS {MAX_PAIRS} RESERVED {RESERVED:.0f} EXIT_Z {EXIT_Z} CLOCK {CLOCK}", flush=True)
    bt = thorp._load_bt()
    menu = pd.read_csv(thorp.PAIR_MENU)
    menu["left"] = menu["left"].astype(str)
    menu["right"] = menu["right"].astype(str)
    symbols = sorted(set(menu["left"]).union(set(menu["right"])))
    print(f"menu pairs {len(menu)} symbols {len(symbols)}", flush=True)
    close_wide, opens, _hits = thorp.load_prices(symbols, bt)
    panels = bt.build_panels(menu, close_wide, opens)
    by_date, best_on, gap_count, all_dates, n_gaps = multi.collect_signals(panels, bt)

    thorp.EXIT_Z = EXIT_Z
    print("replaying published one-pair Z025", flush=True)
    one_trades, one_eq, _meta = thorp.replay(panels, best_on, gap_count, all_dates, bt, CLOCK)
    one_frame = thorp.trades_frame(one_trades)
    match_line = multi.check_published(one_frame)

    print("replaying top 10", flush=True)
    top_trades, top_raw, top_meta = replay_top10(panels, by_date, all_dates, bt)
    top_frame = thorp.trades_frame(top_trades)

    full_y, is_y, oos_y = thorp.slice_years(one_eq)
    one_pack = {}
    top_pack = {}
    for sample, years in (("full", full_y), ("IS", is_y), ("OOS", oos_y)):
        one_stats = thorp.closed_metrics(one_frame if sample == "full" else one_frame, years)
        # closed_metrics already slices? No, it uses the frame passed in. Slice here.
        one_view = one_frame if sample == "full" else one_frame[one_frame["sample"] == sample]
        top_view = top_frame if sample == "full" else top_frame[top_frame["sample"] == sample]
        one_stats = thorp.closed_metrics(one_view, years)
        top_stats = thorp.closed_metrics(top_view, years)
        one_eq_slice = one_eq
        path = thorp.path_stats(
            one_eq if sample == "full" else one_eq[one_eq["date"] < IS_CUT] if sample == "IS" else one_eq[one_eq["date"] >= IS_CUT]
        )
        one_stats["max_dd"] = path["max_dd"]
        one_stats["sharpe"] = path["sharpe"]
        one_stats["open_n"] = int((one_view["status"] == "open").sum()) if not one_view.empty else 0
        top_stats["open_n"] = int((top_view["status"] == "open").sum()) if not top_view.empty else 0
        one_pack[sample] = enrich(one_stats, one_frame, _one_equity_as_raw(one_eq), sample, ONE_RESERVED)
        top_pack[sample] = enrich(top_stats, top_frame, top_raw, sample, RESERVED)
        # One-pair max DD stays the published $10,000 path (path_stats above), not a second base.
        one_pack[sample]["max_dd"] = path["max_dd"]
        one_pack[sample]["sharpe"] = path["sharpe"]
        if np.isfinite(path["max_dd"]) and abs(path["max_dd"]) > 1e-9:
            if np.isfinite(one_pack[sample]["ann_ror_account"]):
                one_pack[sample]["calmar_account"] = float(one_pack[sample]["ann_ror_account"] / abs(path["max_dd"]))
            if np.isfinite(one_pack[sample]["ann_ror_trade"]):
                one_pack[sample]["calmar"] = float(one_pack[sample]["ann_ror_trade"] / abs(path["max_dd"]))
        _ = one_eq_slice

    verdict, why, _flag = judge(top_pack["IS"], one_pack["IS"])
    verdict, why, oos_line = apply_oos_hold(verdict, why, top_pack["OOS"], top_pack["IS"], one_pack["OOS"])
    print(f"VERDICT {verdict}", flush=True)
    print(why, flush=True)
    print(oos_line, flush=True)

    ctx = {
        "one": one_pack,
        "top": top_pack,
        "verdict": verdict,
        "verdict_why": why,
        "oos_line": oos_line,
        "match_line": match_line,
        "days_full": top_meta["days_full"],
        "pct_days_full": top_meta["pct_days_full"],
        "calendar_days": top_meta["calendar_days"],
        "days_cap_bound": top_meta["days_cap_bound"],
        "taken": top_meta["signals_taken"],
        "skipped_cap": top_meta["signals_skipped_cap"],
        "skipped_busy": top_meta["signals_skipped_symbol_busy"],
        "skipped_nofill": top_meta["signals_skipped_nofill"],
        "avg_open": top_meta["avg_open_pairs"],
        "median_open": top_meta["median_open_pairs"],
        "peak_open": top_meta["peak_open_pairs"],
        "avg_slots": top_meta["avg_slots"],
        "median_slots": top_meta["median_slots"],
        "peak_slots": top_meta["peak_slots"],
        "slot_counts": top_meta["slot_counts"],
        "n_gaps": n_gaps,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    top_frame.to_csv(OUT / "trades_top10.csv", index=False)
    summary_rows = []
    for name, pack in (("one_pair", one_pack), ("top10", top_pack)):
        for sample, st in pack.items():
            summary_rows.append({"book": name, "sample": sample, "verdict": verdict if name == "top10" else "", **st})
    pd.DataFrame(summary_rows).to_csv(OUT / "summary.csv", index=False)
    (OUT / "report.html").write_text(render(ctx), encoding="utf-8")
    (OUT / "BASELINE.md").write_text(baseline_md(ctx), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    for sample in ("full", "IS", "OOS"):
        a, b = one_pack[sample], top_pack[sample]
        print(
            f"{sample} one n {a['n']} wr {a['win_pct']:.2f} avg {a['avg_pct']:.2f} "
            f"trade_ann {a['ann_ror_trade']:.2f} acct_ann {a['ann_ror_account']:.2f} | "
            f"top n {b['n']} wr {b['win_pct']:.2f} avg {b['avg_pct']:.2f} "
            f"trade_ann {b['ann_ror_trade']:.2f} acct_ann {b['ann_ror_account']:.2f}",
            flush=True,
        )


def _one_equity_as_raw(one_eq: pd.DataFrame) -> pd.DataFrame:
    """Shape the one-pair equity so the account formula can peel realized off the $10,000 start.

    thorp.replay stores equity = STAKE + realized + unreal, and has no separate realized column.
    Reconstruct realized from the path only for the calendar length used by the account formula.
    The account formula itself uses closed-trade dollars, so this frame is used for the calendar
    and, via reserved_path, only if realized exists. Closed dollars do not need this reconstruction
    for the account annualized rate. reserved_path does. For one pair, max drawdown is taken from
    the original equity and written over the reserved_path result in main().
    """
    if one_eq is None or one_eq.empty:
        return pd.DataFrame(columns=["date", "realized", "unreal"])
    out = one_eq[["date"]].copy()
    eq = one_eq["equity"].to_numpy(dtype=float)
    out["realized"] = eq - STAKE
    out["unreal"] = 0.0
    return out


if __name__ == "__main__":
    main()
