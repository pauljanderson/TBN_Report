#!/usr/bin/env python3
"""Which Similar Stock Difference pair the one-pair book takes.

Same Z025 exit, same entries, same one-pair account. The only change is which
qualifying pair is taken on a day the book can open a new pair.

Rankers and the verdict bar are frozen in this file before any profit number
from this run is read. Research only. Not gold. Not DailyRun. Does not retune
Z025 and does not adopt a new ranker.
"""
from __future__ import annotations

import html
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
sys.path.insert(0, str(ROOT))

import thorp_timestop_and_chain_scan_20261001 as thorp  # noqa: E402
import ssd_z025_multipair_20261001 as multi  # noqa: E402
from compare_format import ann_ror_from_closed, format_money  # noqa: E402
from report_page_extras import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, SWIPE_NOTE_HTML  # noqa: E402

OUT = ROOT / "drive" / "paul_experiments" / "ssd_z025_pair_choice_20261001"
PUBLISHED_TRADES = (
    ROOT / "drive" / "paul_experiments" / "ssd_z025_multipair_20261001" / "trades_one_pair.csv"
)
STUDY_END = multi.STUDY_END
IS_CUT = thorp.IS_CUT
STAKE = thorp.STAKE
EXIT_Z = 0.25
CLOCK = 15

# Frozen before this script looks at profit. One ranker per arm. No blend.
# key index into the signal tuple. higher=True means a larger key wins.
# A tie keeps the earlier pair in the saved menu (the 2010 loop uses strict >).
RANKERS = (
    {"id": "pct_max", "name": "Largest absolute percent gap", "key": 0, "higher": True, "control": True, "lookahead": False},
    {"id": "z_max", "name": "Largest absolute z-score", "key": 1, "higher": True, "control": False, "lookahead": False},
    {"id": "corr_full", "name": "Highest full-window correlation", "key": 2, "higher": True, "control": False, "lookahead": True},
    {"id": "corr_year", "name": "Highest prior-year correlation", "key": 3, "higher": True, "control": False, "lookahead": False},
    {"id": "pct_min", "name": "Smallest absolute percent gap", "key": 0, "higher": False, "control": False, "lookahead": False},
)
DROPPED = (
    "Oldest zone was skipped. The signal store has no field for how long the gap "
    "has already been open. The 2010 events table stores the whole stretch after "
    "the fact, including later sessions, so that length is not a decision-day age."
)

# Frozen verdict versus the largest-absolute-percent-gap book. In-sample closed
# trades only. Ann ROR is reported and does not change the label.
KEEP_AVG_EDGE = 1.0
KEEP_WR_DROP_MAX = 10.0
KEEP_N_RATIO_MIN = 0.80
OOS_SOFTEN = 1.0

ORIGINAL_REQUEST = (
    "if there are multiple pairs which pair are we choosing as the one pair? "
    "how is that decision made? do we know we are making the right choice? "
    "can we analyze all the variables and ensure we are taking the most likely winner?"
)

# Signal tuple: abs percent, abs z, full-window correlation, prior-year correlation,
# panel index, bar index, signed z, signed percent.
ABS_PCT, ABS_Z, CORR_FULL, PRIOR_CORR, PI, BAR, Z, PCT = range(8)


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
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}%"


def _num(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
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
    cap = f"{caption} Click a column header to sort. Swipe sideways to see more columns."
    return (
        '<div class="table-wrap"><table class="sortable">'
        f"<caption>{_esc(cap)}</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _calmar(ann: float, max_dd: float) -> float:
    if not (np.isfinite(ann) and np.isfinite(max_dd)) or abs(max_dd) < 1e-9:
        return float("nan")
    return float(ann / abs(max_dd))


def choose(recs: list[tuple], spec: dict) -> tuple | None:
    """Pick one signal. A missing key never beats a finite key. All-missing keeps the first menu pair."""
    if not recs:
        return None
    key_i = spec["key"]
    higher = spec["higher"]
    chosen = None
    chosen_key = None
    saw_finite = False
    for rec in recs:
        key = rec[key_i]
        if not np.isfinite(key):
            if chosen is None:
                chosen = rec
            continue
        if (
            not saw_finite
            or (higher and key > chosen_key)
            or ((not higher) and key < chosen_key)
        ):
            chosen = rec
            chosen_key = key
            saw_finite = True
    return chosen


def attach_menu(panels: list[dict], menu: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Full-window correlation and calendar-year correlations, aligned to built panels."""
    keyed = {}
    year_cols = sorted(c for c in menu.columns if c.startswith("y") and c[1:].isdigit())
    years = [int(c[1:]) for c in year_cols]
    if not years:
        raise SystemExit("The pair menu has no stored calendar-year correlation columns.")
    year0 = min(years)
    width = max(years) - year0 + 1
    for rec in menu.itertuples(index=False):
        keyed[(str(rec.left), str(rec.right))] = rec
    full = np.full(len(panels), np.nan)
    year_mat = np.full((len(panels), width), np.nan)
    for pi, panel in enumerate(panels):
        rec = keyed.get((panel["left"], panel["right"]))
        if rec is None:
            raise SystemExit(f"Panel {panel['left']}/{panel['right']} is not in the saved menu.")
        full[pi] = float(getattr(rec, "corr_full"))
        for col, year in zip(year_cols, years):
            val = getattr(rec, col)
            if val is not None and val == val:
                year_mat[pi, year - year0] = float(val)
    return full, year_mat


def collect_signals(panels: list[dict], bt, corr_full: np.ndarray, year_mat: np.ndarray) -> tuple[dict, list]:
    window = bt.WINDOW_START
    entry_z = float(bt.ENTRY_Z)
    year0 = 2010
    by_date: dict[pd.Timestamp, list[tuple]] = {}
    total = 0
    for pi, panel in enumerate(panels):
        z = panel["z"]
        pct = panel["pct"]
        dates = panel["dates"]
        years = dates.year.to_numpy()
        ok = np.isfinite(z) & np.isfinite(pct) & (np.abs(z) >= entry_z)
        ok &= (dates >= window) & (dates <= STUDY_END)
        cf = float(corr_full[pi])
        for i in np.flatnonzero(ok):
            d = pd.Timestamp(dates[int(i)])
            y = int(years[int(i)])
            prior_i = y - 1 - year0
            if 0 <= prior_i < year_mat.shape[1]:
                prior = float(year_mat[pi, prior_i])
            else:
                prior = float("nan")
            rec = (
                abs(float(pct[i])),
                abs(float(z[i])),
                cf,
                prior,
                pi,
                int(i),
                float(z[i]),
                float(pct[i]),
            )
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
    print(f"qualifying gaps {total} on {len(by_date)} sessions", flush=True)
    return by_date, all_dates


def best_on_for(by_date: dict, panels: list[dict], spec: dict) -> dict:
    out = {}
    for date, recs in by_date.items():
        rec = choose(recs, spec)
        if rec is None:
            continue
        out[date] = (rec[ABS_PCT], panels[rec[PI]], rec[BAR], rec[Z], rec[PCT])
    return out


def gap_count_for(by_date: dict) -> dict:
    return {d: len(recs) for d, recs in by_date.items()}


def check_control(frame: pd.DataFrame) -> str:
    published = pd.read_csv(PUBLISHED_TRADES)
    notes = []
    ok = len(frame) == len(published)
    if not ok:
        notes.append(f"trade count {len(frame)} vs published {len(published)}")
    n = min(len(frame), len(published))
    for i in range(n):
        got = frame.iloc[i]
        pub = published.iloc[i]
        for col in ("left", "right", "long", "short", "signal_date", "entry_date", "status", "reason"):
            if str(got[col]) != str(pub[col]):
                ok = False
                notes.append(f"row {i} {col}: {got[col]} vs {pub[col]}")
                break
        else:
            pub_exit = "" if pd.isna(pub.get("exit_date")) else str(pub["exit_date"])[:10]
            got_exit = "" if not str(got["exit_date"]) or str(got["exit_date"]) == "nan" else str(got["exit_date"])[:10]
            if str(pub["status"]) == "closed" and got_exit != pub_exit:
                ok = False
                notes.append(f"row {i} exit_date: {got_exit} vs {pub_exit}")
            elif abs(float(got["net_pct"]) - float(pub["net_pct"])) > 0.05:
                ok = False
                notes.append(f"row {i} net_pct: {got['net_pct']} vs {pub['net_pct']}")
        if len(notes) >= 6:
            break
    head = (
        "The control book matches the published Z025 one-pair trades."
        if ok
        else "The control book does not match the published Z025 one-pair trades. Numbers below are this rerun."
    )
    detail = " ".join(notes[:6])
    print(head, detail, flush=True)
    return head + (" " + detail if detail else "")


def pack_arm(spec: dict, frame: pd.DataFrame, equity: pd.DataFrame) -> dict:
    full_y, is_y, oos_y = thorp.slice_years(equity)
    samples = {}
    for name, years in (("full", full_y), ("IS", is_y), ("OOS", oos_y)):
        view = frame if name == "full" else frame[frame["sample"] == name]
        stats = thorp.closed_metrics(view, years)
        if name == "IS":
            path_eq = equity[equity["date"] < IS_CUT]
        elif name == "OOS":
            path_eq = equity[equity["date"] >= IS_CUT]
        else:
            path_eq = equity
        path = thorp.path_stats(path_eq)
        stats["max_dd"] = path["max_dd"]
        stats["sharpe"] = path["sharpe"]
        stats["calmar"] = _calmar(stats["ann_ror"], path["max_dd"])
        stats["open_n"] = int((view["status"] == "open").sum()) if view is not None and not view.empty else 0
        # House formula check: closed_metrics already calls ann_ror_from_closed.
        # Recompute here so a blank would be visible rather than a second formula.
        if stats["n"] and np.isfinite(stats["avg_days"]):
            again = ann_ror_from_closed(
                total_pnl=float(stats["total"]),
                n_trades=int(stats["n"]),
                avg_days_held=float(stats["avg_days"]),
                brt_cash=STAKE,
            )
            stats["ann_ror"] = float(again) if again is not None else float("nan")
        samples[name] = stats
    return {**spec, "frame": frame, "samples": samples}


def judge(arm: dict, control: dict) -> tuple[str, str]:
    if arm["control"]:
        return "control", "This is the rule in the code today. The other rows are judged against it."
    a = arm["samples"]["IS"]
    b = control["samples"]["IS"]
    if not b["n"] or not a["n"]:
        return "DISMISS", "An in-sample closed book is empty, so there is no quality comparison."
    avg_gap = a["avg_pct"] - b["avg_pct"]
    wr_drop = b["win_pct"] - a["win_pct"]
    n_ratio = a["n"] / b["n"]
    if n_ratio < KEEP_N_RATIO_MIN:
        label, why = "DISMISS", (
            f"In-sample closed count is {a['n']} versus {b['n']} on the current rule "
            f"({n_ratio:.0%}), under the 80% floor."
        )
    elif wr_drop > KEEP_WR_DROP_MAX:
        label, why = "DISMISS", (
            f"In-sample win rate is {wr_drop:.1f} points lower than the current rule."
        )
    elif avg_gap < -KEEP_AVG_EDGE:
        label, why = "DISMISS", (
            f"In-sample average is {avg_gap:+.2f} points versus the current rule, worse by more than 1 point."
        )
    elif avg_gap > KEEP_AVG_EDGE and wr_drop <= KEEP_WR_DROP_MAX and n_ratio >= KEEP_N_RATIO_MIN:
        label, why = "KEEP", (
            f"In-sample average is {avg_gap:+.2f} points, win rate is {a['win_pct']:.1f}% "
            f"versus {b['win_pct']:.1f}%, and closed count is {a['n']} versus {b['n']}."
        )
    else:
        label, why = "HOLD", (
            f"In-sample average is {avg_gap:+.2f} points versus the current rule, inside the 1 point bar. "
            f"Win rate {a['win_pct']:.1f}% versus {b['win_pct']:.1f}%. Closed count {a['n']} versus {b['n']}."
        )
    oos_a = arm["samples"]["OOS"]["avg_pct"]
    oos_b = control["samples"]["OOS"]["avg_pct"]
    oos_gap = oos_a - oos_b if np.isfinite(oos_a) and np.isfinite(oos_b) else float("nan")
    if label == "KEEP" and (not np.isfinite(oos_gap) or oos_gap < -OOS_SOFTEN):
        soft = "not a number" if not np.isfinite(oos_gap) else f"{oos_gap:+.2f} points"
        label = "HOLD"
        why += (
            f" Out-of-sample average versus the current rule is {soft}, softer by more than 1 point. "
            "The out-of-sample row was not used to pick a new ranker."
        )
    elif label == "KEEP" and arm["lookahead"]:
        label = "HOLD"
        why += (
            " The stored full-window correlation was fit on the whole menu, including sessions after the entry. "
            "That is not a clean keep. It is not adopted."
        )
    elif label == "KEEP":
        why += (
            " Out-of-sample did not soften by more than 1 point. This is a research finding only. "
            "Picking it after seeing this table is in-sample selection. It is not adopted."
        )
    else:
        why += " Out-of-sample was not used to change this label."
    if arm["lookahead"] and label != "HOLD":
        why += " Full-window correlation still looks ahead, past the entry date."
    return label, why


def walk_conflicts(by_date: dict, all_dates: list, panels: list[dict], bt, control_trades: list[dict]) -> dict:
    """Free days under the current ranker. Same state order as the published one-pair walk."""
    position = None
    pending_entry = None
    pending_exit = None
    accepted: list[tuple] = []
    date_set = set(all_dates)
    free_days = 0
    free_with_gap = 0
    free_multi = 0
    free_single = 0
    cand_counts: list[int] = []
    busy_gaps = 0
    runners = 0
    conflicts: list[dict] = []
    control_spec = next(s for s in RANKERS if s["control"])

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
            free_days += 1
            if cands:
                free_with_gap += 1
                cand_counts.append(len(cands))
                if len(cands) >= 2:
                    free_multi += 1
                    runners += len(cands) - 1
                    picks = {}
                    for spec in RANKERS:
                        rec = choose(cands, spec)
                        picks[spec["id"]] = (rec[PI], rec[BAR], rec[PCT], rec[ABS_PCT], rec[ABS_Z])
                    conflicts.append({"date": date, "n": len(cands), "picks": picks})
                else:
                    free_single += 1
                best = choose(cands, control_spec)
                panel = panels[best[PI]]
                fill_on = bt._next_session(panel, date)
                if fill_on is not None:
                    fill_on = pd.Timestamp(fill_on)
                    fill_i = bt._at(panel, fill_on)
                    short_sym, long_sym = multi._side(panel, best[PCT])
                    pending_entry = {
                        "panel": panel,
                        "left": panel["left"],
                        "right": panel["right"],
                        "long": long_sym,
                        "short": short_sym,
                        "entry_date": fill_on,
                        "entry_i": int(fill_i) if fill_i is not None else int(best[BAR]) + 1,
                        "alpha": float(panel["alpha"][best[BAR]]),
                        "beta": float(panel["beta"][best[BAR]]),
                        "center": float(panel["center"][best[BAR]]),
                        "scale": float(panel["scale"][best[BAR]]),
                        "fill_on": fill_on,
                    }
                    if fill_on in date_set:
                        accepted.append((panel["left"], panel["right"], _iso(date)))
        elif cands:
            busy_gaps += len(cands)

    taken = {(t["left"], t["right"], _iso(t["signal_date"])) for t in control_trades}
    got = set(accepted)
    if taken != got:
        raise SystemExit(
            f"Free-day walk does not match the control replay (missing {len(taken - got)} extra {len(got - taken)})"
        )
    counts = np.asarray(cand_counts, dtype=float) if cand_counts else np.asarray([np.nan])
    print(
        f"free days {free_days} with a gap {free_with_gap} multi {free_multi} single {free_single} "
        f"busy gaps {busy_gaps} runners {runners}",
        flush=True,
    )
    return {
        "free_days": free_days,
        "free_with_gap": free_with_gap,
        "free_multi": free_multi,
        "free_single": free_single,
        "busy_gaps": busy_gaps,
        "runners": runners,
        "median_cands": float(np.nanmedian(counts)),
        "mean_cands": float(np.nanmean(counts)),
        "max_cands": float(np.nanmax(counts)) if cand_counts else float("nan"),
        "conflicts": conflicts,
    }


def _alone_pct(panel: dict, bar: int, pct: float) -> dict | None:
    return multi.alone_outcome(panel, bar, pct)


def diagnose(conflicts: list[dict], panels: list[dict]) -> list[dict]:
    cache: dict[tuple, dict | None] = {}

    def outcome(pi: int, bar: int, pct: float) -> dict | None:
        key = (pi, bar)
        if key not in cache:
            cache[key] = _alone_pct(panels[pi], bar, pct)
        return cache[key]

    rows = []
    for spec in RANKERS:
        if spec["control"]:
            continue
        buckets = {"full": [], "IS": [], "OOS": []}
        disagree_days = {"full": 0, "IS": 0, "OOS": 0}
        multi_days = {"full": 0, "IS": 0, "OOS": 0}
        for row in conflicts:
            control_pick = row["picks"]["pct_max"]
            other = row["picks"][spec["id"]]
            # Sample uses the signal date. Entry is the next session, so a year-end
            # signal can fall in the other book slice by one day. The book tables use entry date.
            sample = "IS" if pd.Timestamp(row["date"]) < IS_CUT else "OOS"
            for label in ("full", sample):
                multi_days[label] += 1
            same = (control_pick[0], control_pick[1]) == (other[0], other[1])
            if same:
                continue
            for label in ("full", sample):
                disagree_days[label] += 1
            c_out = outcome(control_pick[0], control_pick[1], control_pick[2])
            o_out = outcome(other[0], other[1], other[2])
            if c_out is None or o_out is None:
                continue
            pair = (c_out["net_pct"], o_out["net_pct"], c_out["status"], o_out["status"])
            buckets["full"].append(pair)
            buckets[sample].append(pair)
        for sample in ("full", "IS", "OOS"):
            got = buckets[sample]
            c_avg = float(np.mean([p[0] for p in got])) if got else float("nan")
            o_avg = float(np.mean([p[1] for p in got])) if got else float("nan")
            better = int(sum(1 for p in got if p[1] > p[0]))
            both_closed = [p for p in got if p[2] == "closed" and p[3] == "closed"]
            c_closed = float(np.mean([p[0] for p in both_closed])) if both_closed else float("nan")
            o_closed = float(np.mean([p[1] for p in both_closed])) if both_closed else float("nan")
            multi_n = multi_days[sample]
            diff_n = disagree_days[sample]
            rows.append(
                {
                    "id": spec["id"],
                    "name": spec["name"],
                    "sample": sample,
                    "multi_days": multi_n,
                    "disagree": diff_n,
                    "disagree_pct": 100.0 * diff_n / multi_n if multi_n else float("nan"),
                    "compared": len(got),
                    "control_avg": c_avg,
                    "other_avg": o_avg,
                    "delta": o_avg - c_avg if np.isfinite(o_avg) and np.isfinite(c_avg) else float("nan"),
                    "other_better": better,
                    "other_better_pct": 100.0 * better / len(got) if got else float("nan"),
                    "closed_compared": len(both_closed),
                    "control_closed_avg": c_closed,
                    "other_closed_avg": o_closed,
                }
            )
    print(f"alone cache {len(cache)}", flush=True)
    return rows


def most_likely(arms: list[dict]) -> dict:
    """Named after the table exists. In-sample selection. Not a new freeze."""
    control = next(a for a in arms if a["control"])
    ranked = sorted(
        arms,
        key=lambda a: (
            -(a["samples"]["IS"]["avg_pct"] if np.isfinite(a["samples"]["IS"]["avg_pct"]) else -1e18),
            a["id"],
        ),
    )
    by_wr = sorted(
        arms,
        key=lambda a: (
            -(a["samples"]["IS"]["win_pct"] if np.isfinite(a["samples"]["IS"]["win_pct"]) else -1e18),
            a["id"],
        ),
    )
    best_avg = ranked[0]
    best_wr = by_wr[0]
    ctrl_avg = control["samples"]["IS"]["avg_pct"]
    ctrl_wr = control["samples"]["IS"]["win_pct"]
    return {
        "best_avg_id": best_avg["id"],
        "best_avg_name": best_avg["name"],
        "best_avg": best_avg["samples"]["IS"]["avg_pct"],
        "best_wr_id": best_wr["id"],
        "best_wr_name": best_wr["name"],
        "best_wr": best_wr["samples"]["IS"]["win_pct"],
        "control_is_best_avg": best_avg["id"] == control["id"]
        or (
            np.isfinite(best_avg["samples"]["IS"]["avg_pct"])
            and abs(best_avg["samples"]["IS"]["avg_pct"] - ctrl_avg) < 1e-9
        ),
        "control_is_best_wr": best_wr["id"] == control["id"]
        or (np.isfinite(best_wr["samples"]["IS"]["win_pct"]) and abs(best_wr["samples"]["IS"]["win_pct"] - ctrl_wr) < 1e-9),
        "control_avg": ctrl_avg,
        "control_wr": ctrl_wr,
    }


def headline_row(arm: dict) -> str:
    cells = [_td(arm["name"])]
    for sample in ("IS", "full", "OOS"):
        st = arm["samples"][sample]
        cells.append(_td(str(st["n"]), True))
        cells.append(_td(_pct(st["win_pct"], 1), True))
        cells.append(_td(_pct(st["avg_pct"]), True))
        cells.append(_td(_pct(st["ann_ror"], 1), True))
    cells.append(_td(arm["verdict"]))
    return "<tr>" + "".join(cells) + "</tr>"


def delta_row(arm: dict, control: dict) -> str:
    cells = [_td(arm["name"])]
    for sample, digits in (("IS", 2), ("OOS", 2)):
        a = arm["samples"][sample]
        b = control["samples"][sample]
        cells.append(_td(_pp(a["avg_pct"] - b["avg_pct"]), True))
        cells.append(_td(_pp(a["win_pct"] - b["win_pct"], 1), True))
        cells.append(_td(_pp(a["ann_ror"] - b["ann_ror"], 1), True))
        cells.append(_td(str(a["n"] - b["n"]), True))
    cells.append(_td(arm["verdict"]))
    return "<tr>" + "".join(cells) + "</tr>"


def canon_row(arm: dict, sample: str, control: dict) -> str:
    a = arm["samples"][sample]
    b = control["samples"][sample]
    def d(key: str, digits: int = 2) -> str:
        if not np.isfinite(a[key]) or not np.isfinite(b[key]):
            return "—"
        return _pp(a[key] - b[key], digits)

    return "<tr>" + "".join(
        [
            _td(arm["name"]),
            _td(str(a["n"]), True),
            _td(_pct(a["win_pct"], 1), True),
            _td(_pct(a["avg_pct"]), True),
            _td(d("avg_pct"), True),
            _td(_pct(a["ann_ror"], 1), True),
            _td(d("ann_ror", 1), True),
            _td(_pct(a["median_pct"]), True),
            _td(_num(a["pf"]), True),
            _td(_pct(a["wo_max"]), True),
            _td(_pct(a["outlier"], 1), True),
            _td(_num(a["avg_days"], 1), True),
            _td(_num(a["median_days"], 1), True),
            _td(str(a["capital_days"]) if a["capital_days"] else "—", True),
            _td(_num(a["tpy"], 2), True),
            _td(_pct(a["max_dd"], 1), True),
            _td(_num(a["sharpe"]), True),
            _td(_num(a["calmar"]), True),
            _td(str(a["line_n"]), True),
            _td(str(a["time_n"]), True),
            _td(str(a["open_n"]), True),
            _td(format_money(a["profit_per_capital_day"]) if np.isfinite(a["profit_per_capital_day"]) else "—", True),
        ]
    ) + "</tr>"


def diag_row(row: dict) -> str:
    return "<tr>" + "".join(
        [
            _td(row["name"]),
            _td(row["sample"]),
            _td(str(row["multi_days"]), True),
            _td(str(row["disagree"]), True),
            _td(_pct(row["disagree_pct"], 1), True),
            _td(str(row["compared"]), True),
            _td(_pct(row["control_avg"]), True),
            _td(_pct(row["other_avg"]), True),
            _td(_pp(row["delta"]), True),
            _td(str(row["other_better"]), True),
            _td(_pct(row["other_better_pct"], 1), True),
            _td(str(row["closed_compared"]), True),
            _td(_pct(row["control_closed_avg"]), True),
            _td(_pct(row["other_closed_avg"]), True),
        ]
    ) + "</tr>"


def answer_text(ctx: dict) -> str:
    free = ctx["walk"]
    likely = ctx["likely"]
    multi_share = 100.0 * free["free_multi"] / free["free_with_gap"] if free["free_with_gap"] else float("nan")
    def plain_pct(value: float, digits: int = 1) -> str:
        if value is None or not np.isfinite(value):
            return "—"
        return f"{value:.{digits}f}%"

    wr_name = likely["best_wr_name"]
    winner = (
        f"On the in-sample test the current rule has the highest average, "
        f"{_pct(likely['control_avg'])}, and the highest annualized rate of return. "
        f"It does not have the highest win rate. That belongs to {wr_name}, "
        f"at {plain_pct(likely['best_wr'])} of trades versus {plain_pct(likely['control_wr'])} for the current rule. "
        "A higher win rate with a lower average means more of the trades finished green, and the green ones were smaller. "
        "Full-window correlation is also the one ranker that was fit on later years, so that higher win rate was not a number the book knew on the signal day. "
        "The other rankers, which use only that day’s gap or the prior year’s correlation, also win a bit more often in-sample and still average less. "
        "On the same day, the other pair beat the current pick about half the time, but the average of the pair the current rule took was higher in-sample. "
        "After 2024 that same-day average flips, and the other pair looks better. That later slice is report-only. "
        "Naming the best cell after seeing this table is in-sample selection. No ranker is adopted."
    )
    return f"""
  <div class="callout">
    <strong>What you asked</strong>
    <blockquote class="ask">{_esc(ORIGINAL_REQUEST)}</blockquote>
  </div>
  <div class="callout">
    <strong>In plain English</strong>
    <p>Similar Stock Difference shorts one stock and buys a similar one when they pull apart. A gap means the latest close is at least 2 standard deviations off a 252-session line that was fit before that day. The account holds one pair. When several gaps show up on a day the account can take a new pair, the book has to pick one. This page says how it picks today, and whether a different way of picking would have caught the gap that was more likely to pay. Annualized rate of return is the house yearly pace of the closed trades.</p>
    <p>The exit stays the one already chosen: get out when a later close is back within 0.25 standard deviations of the line frozen at entry, or on the close of the 15th session, whichever comes first. That exit is not changed here.</p>
  </div>
  <div class="callout">
    <strong>How the one-pair book picks</strong>
    <p>When more than one pair qualifies and the account can take a new pair, it takes the pair whose close is furthest, in percent, from that pair’s own line. That is the largest absolute percent gap. If two pairs are tied on that percent, the earlier pair in the saved menu keeps the seat. Every other qualifying pair that day is skipped. They are not put in a queue. The book looks again only on a later day when it is flat: no open pair, no entry fill still waiting, and no exit fill still waiting. While it is busy, every new gap is skipped, including gaps in the same names and gaps in different names.</p>
    <p>That rule is the original gap definition from the 2010 write-up: if several pairs qualify and the book is flat, take the largest percent gap. It was not chosen because a test had already shown it had the best historical win rate. There was no ranker horse-race before this page.</p>
    <p>The line about a larger gap “claiming a shared stock” is a different book. That sentence is how the many-pairs account breaks a same-day tie when two gaps want the same stock. The one-pair account never gets that far. It already picked a single pair for the whole account.</p>
    <p>On days the account was free and at least one gap qualified, {free["free_multi"]:,} of {free["free_with_gap"]:,} days ({_num(multi_share, 1)}%) had two or more qualifying pairs. Median qualifying pairs on those free days with a gap: {_num(free["median_cands"], 1)}. The account was busy for another {free["busy_gaps"]:,} qualifying gaps. Those were skipped because a pair was already open or a fill was already reserved, not because they lost the same-day pick.</p>
    <p><strong>{_esc(winner)}</strong></p>
  </div>
"""


def render(ctx: dict) -> str:
    arms = ctx["arms"]
    control = next(a for a in arms if a["control"])
    head_headers = [
        ("Ranker", "text"),
        ("IS N", "num"), ("IS win rate", "num"), ("IS average", "num"), ("IS Ann ROR", "num"),
        ("Full N", "num"), ("Full win rate", "num"), ("Full average", "num"), ("Full Ann ROR", "num"),
        ("OOS N", "num"), ("OOS win rate", "num"), ("OOS average", "num"), ("OOS Ann ROR", "num"),
        ("Verdict", "text"),
    ]
    delta_headers = [
        ("Ranker", "text"),
        ("IS avg vs current", "num"), ("IS win rate vs current", "num"),
        ("IS Ann ROR vs current", "num"), ("IS N vs current", "num"),
        ("OOS avg vs current", "num"), ("OOS win rate vs current", "num"),
        ("OOS Ann ROR vs current", "num"), ("OOS N vs current", "num"),
        ("Verdict", "text"),
    ]
    canon_headers = [
        ("Ranker", "text"), ("N", "num"), ("Win rate", "num"), ("Average", "num"), ("Avg vs current", "num"),
        ("Ann ROR", "num"), ("Ann ROR vs current", "num"), ("Median", "num"), ("Profit factor", "num"),
        ("Avg without biggest win", "num"), ("Outlier % of wins", "num"),
        ("Avg days held", "num"), ("Median days held", "num"), ("Capital days", "num"),
        ("Trades per year", "num"), ("Max DD", "num"), ("Sharpe", "num"), ("Calmar", "num"),
        ("Line exits", "num"), ("Clock exits", "num"), ("Open", "num"),
        ("Profit per capital day", "num"),
    ]
    diag_headers = [
        ("Other ranker", "text"), ("Slice", "text"),
        ("Free days with 2 or more pairs", "num"),
        ("Days the pick differs", "num"), ("Share that differ", "num"),
        ("Days both filled", "num"),
        ("Current pick average", "num"), ("Other pick average", "num"),
        ("Other minus current", "num"),
        ("Days the other was higher", "num"), ("Share the other was higher", "num"),
        ("Both closed", "num"),
        ("Current closed average", "num"), ("Other closed average", "num"),
    ]
    verdicts = "".join(f"<li><strong>{_esc(a['name'])}: {_esc(a['verdict'])}.</strong> {_esc(a['why'])}</li>" for a in arms)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Similar Stock Difference, which pair the one-pair book takes</title>
  <style>
  :root {{
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --warn: #8a5a12; --warn-bg: #f7efe0; --fill: #f0eee6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 16px; line-height: 1.55; color: var(--ink); background: var(--bg);
  }}
  .page {{ max-width: 1280px; margin: 0 auto; padding: 36px 22px 72px; }}
  header.doc-head {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  .eyebrow {{ font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase; color: var(--accent); font-weight: 650; margin: 0 0 6px; }}
  h1 {{ font-size: 1.65rem; margin: 0 0 8px; letter-spacing: -0.02em; line-height: 1.25; }}
  h2 {{ font-size: 1.2rem; margin: 32px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
  p, li {{ margin: 0 0 10px; }}
  blockquote.ask {{ margin: 8px 0 0; white-space: pre-wrap; font-family: Georgia, "Times New Roman", serif; font-size: 0.95rem; }}
  .callout {{ background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }}
  .callout.warn {{ background: var(--warn-bg); border-left-color: var(--warn); }}
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
  {SORTABLE_TH_CSS}
  </style>
</head>
<body>
<div class="page">
  <header class="doc-head">
    <p class="eyebrow">Research only · not gold · not DailyRun</p>
    <h1>Similar Stock Difference: which pair, when several qualify</h1>
  </header>
  {SWIPE_NOTE_HTML}
  {answer_text(ctx)}

  <div class="callout warn">
    <strong>Read this before treating a winner as the rule</strong>
    <p>The rankers were written down before these profit numbers were computed. Judging the best cell after seeing the table is in-sample selection. Out-of-sample (entry on or after 2024-01-01) is report-only. If it softens, the label is hold, and the ranker is not changed. Nothing on this page is wired into the live book.</p>
    <p>{_esc(ctx["match"])}</p>
  </div>

  <h2>What was frozen</h2>
  <ul>
    <li>Pair menu: the saved 2010 file. Full-window correlation at least 0.60, each half at least 0.55. Prices stop on 2026-09-30.</li>
    <li>Entry: close at least 2 standard deviations off the prior 252 sessions, short the high side, long the low side, about $10,000 of whole shares each, next open. One pair in the account.</li>
    <li>Exit: 0.25 standard deviations or the close of the 15th session, whichever comes first. Not retuned.</li>
    <li>In-sample: entry before 2024-01-01. Out-of-sample: entry on or after 2024-01-01.</li>
    <li>Keep bar, frozen first: in-sample closed average more than 1 point higher than the current rule, win rate not more than 10 points worse, closed count at least 80%. Inside 1 point is a hold. Worse by more than 1 point, or a collapsed count or win rate, is a dismiss. If that bar would keep an arm and the out-of-sample average is more than 1 point softer, the label becomes hold. Annualized rate of return does not override the bar.</li>
    <li>Annualized rate of return uses the house formula on closed trades: one plus total result divided by ($10,000 times the number of trades), raised to 365 divided by average calendar days held, minus one. The two legs are $10,000 each. The formula still uses $10,000 because that is the stake this book already uses.</li>
    <li>Highest full-window correlation uses the stored number from the whole menu window, including later years. Even a clean in-sample keep on that arm is labeled hold.</li>
    <li>{_esc(DROPPED)} A 60-session correlation is not stored. The shortest correlation the study stored is the calendar year. This page uses the last completed calendar year, so the number does not include days after the signal. Signals in 2010 have no prior year in the file, so those days fall through to menu order.</li>
  </ul>

  <h2>The books</h2>
  {_table(head_headers, [headline_row(a) for a in arms], "Closed trades. In-sample, full book, and out-of-sample. Ann ROR is annualized rate of return.")}

  <h2>In-sample verdict versus the current ranker</h2>
  <ul>{verdicts}</ul>
  {_table(delta_headers, [delta_row(a, control) for a in arms], "Differences are this ranker minus the largest absolute percent gap, on the same slice. Out-of-sample differences are report-only.")}

  <h2>Book metrics, in-sample</h2>
  {_table(canon_headers, [canon_row(a, "IS", control) for a in arms], "In-sample closed trades, entry before 2024-01-01. Dollar profit totals are left off. Profit per capital day is the per-day figure.")}

  <h2>Book metrics, full history</h2>
  {_table(canon_headers, [canon_row(a, "full", control) for a in arms], "Full closed book.")}

  <h2>Out-of-sample, report only</h2>
  <p>These rows were not used to keep a ranker. A softer out-of-sample average turns a keep into a hold. It does not start a new search.</p>
  {_table(canon_headers, [canon_row(a, "OOS", control) for a in arms], "Out-of-sample closed trades, entry on or after 2024-01-01. Report only.")}

  <h2>Did the current rule leave the better pair on the table that day?</h2>
  <p>This is not another book. It stays on the current rule’s calendar: days when two or more pairs qualified and the account was free. On those days it asks whether another ranker would have pointed at a different pair, and what the frozen exit would have paid on each pair had that pair been taken by itself. Later trades are not rearranged here. The book tables above are the ones that do rearrange the later trades.</p>
  <p>Averages below include a still-open mark when the next open exists. The closed columns drop any side that was still open at the last price. A day where either pair has no next open is counted in “days the pick differs” and left out of the average.</p>
  {_table(diag_headers, [diag_row(r) for r in ctx["diag"]], "Same-day comparison on the current rule’s free days. In-sample and out-of-sample use the signal date.")}

  <footer>
    Research only. Not gold. Not DailyRun. Z025 was not retuned. No ranker was frozen into the live book.
    {_esc(ctx["match"])}
  </footer>
</div>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""


def baseline_md(ctx: dict) -> str:
    free = ctx["walk"]
    lines = [
        "# Similar Stock Difference, which pair the one-pair book takes",
        "",
        "Research only. Not gold. Not DailyRun. Z025 was not retuned. No ranker was adopted.",
        "",
        "## What you asked",
        "",
        f"> {ORIGINAL_REQUEST}",
        "",
        "## In plain English",
        "",
        "Similar Stock Difference shorts one stock and buys a similar one when they pull apart. A gap means the latest close is at least 2 standard deviations off a 252-session line fit before that day. When several gaps show up and the account can hold only one, the book has to pick. This note says how it picks today, and whether another way of picking would have caught the gap that was more likely to pay. Annualized rate of return is the house yearly pace of the closed trades.",
        "",
        "## How the pick is made",
        "",
        "Code wins. In `same_direction_pairs_gap_bt_2010_20260930.py` and in `thorp_timestop_and_chain_scan_20261001.prepare_signals`, each day keeps the pair with the largest absolute percent gap (`ap > cur[0]`). A tie keeps the earlier panel, which is the earlier pair in the saved menu. `thorp.replay` takes that pair only when the book is flat: no open position, no pending entry, and no pending exit. Other pairs that day are not stored for later. The next look is a later session, and it looks at that session’s gaps, not a backlog.",
        "",
        "The 2010 write-up says the same thing: if several pairs qualify and the book is flat, take the largest percent gap. That sentence is the definition of the gap. It was not the winner of a ranker horse-race.",
        "",
        "“On the same day, the larger absolute percent gap claims a shared stock” is the many-pairs book (`replay_multi` sorts candidates by absolute percent, then menu order, and skips a pair if either symbol is already reserved). It is not the one-pair pick.",
        "",
        f"Free calendar days: {free['free_days']}. Free days with at least one qualifying gap: {free['free_with_gap']}. Of those, {free['free_multi']} had two or more pairs and {free['free_single']} had exactly one. Median qualifying pairs on a free day with a gap: {free['median_cands']:.1f}. Qualifying gaps while the one-pair book was busy: {free['busy_gaps']}. Same-day runners-up on free days: {free['runners']}.",
        "",
        f"{ctx['match']}",
        "",
        "## Freeze (written before the profit numbers)",
        "",
        "- Same pair menu, same |z| >= 2 entry, same one-pair account, same Z025 exit (0.25 standard deviations or session 15).",
        "- One ranker per arm: largest absolute percent gap (control); largest absolute z-score; highest full-window correlation; highest prior calendar-year correlation; smallest absolute percent gap among pairs that already clear 2 standard deviations.",
        f"- {DROPPED}",
        "- A 60-session correlation is not in the study files. Prior calendar-year correlation is the shortest stored window, using the last completed year.",
        "- Full-window correlation looks ahead across the whole menu window. A numeric keep on that arm is forced to HOLD.",
        "- KEEP if in-sample closed average is more than 1 point higher, win rate is not more than 10 points worse, and closed count stays at least 80%. Inside 1 point is HOLD. Worse is DISMISS. Out-of-sample softer by more than 1 point turns KEEP into HOLD. Ann ROR does not override.",
        "- Ann ROR: `compare_format.ann_ror_from_closed`, brt_cash $10,000, the same formula `rocket_tbn.compute_metrics` uses.",
        "- Picking the best cell after this table is in-sample selection. Not adopted. Not DailyRun.",
        "",
        "## Results",
        "",
    ]
    for arm in ctx["arms"]:
        bits = []
        for sample in ("IS", "full", "OOS"):
            st = arm["samples"][sample]
            bits.append(
                f"{sample} N {st['n']}, win {st['win_pct']:.2f}%, avg {st['avg_pct']:+.2f}%, Ann ROR {st['ann_ror']:+.2f}%"
            )
        lines.append(f"- **{arm['name']} — {arm['verdict']}.** {' | '.join(bits)}")
        lines.append(f"  {arm['why']}")
    lines.append("")
    lines.append("## Same-day diagnostic")
    lines.append("")
    lines.append(
        "On free days with two or more pairs, under the current book’s calendar. "
        "Average is the standalone Z025 result of the pair each ranker would have taken that day."
    )
    lines.append("")
    for row in ctx["diag"]:
        lines.append(
            f"- {row['name']} / {row['sample']}: differ {row['disagree']} of {row['multi_days']} "
            f"({row['disagree_pct']:.1f}%). Compared {row['compared']}. "
            f"Current avg {row['control_avg']:+.2f}% vs other {row['other_avg']:+.2f}% "
            f"(delta {row['delta']:+.2f}). Other higher on {row['other_better']} days."
        )
    likely = ctx["likely"]
    lines.extend(
        [
            "",
            "## Is the current choice the most likely winner?",
            "",
            f"Highest in-sample average: {likely['best_avg_name']} at {likely['best_avg']:+.2f}%. "
            f"Highest in-sample win rate: {likely['best_wr_name']} at {likely['best_wr']:.2f}%. "
            "The current rule is the best in-sample average and the best in-sample annualized rate of return. "
            "It is not the highest win rate. A higher win rate with a lower average is more green trades, smaller green trades. "
            "Full-window correlation looks ahead across the whole menu window. "
            "Naming a cell after this table is in-sample selection. Nothing is adopted.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def summary_frame(ctx: dict) -> pd.DataFrame:
    rows = []
    for arm in ctx["arms"]:
        for sample in ("IS", "full", "OOS"):
            st = arm["samples"][sample]
            rows.append(
                {
                    "section": "book",
                    "ranker": arm["name"],
                    "ranker_id": arm["id"],
                    "sample": sample,
                    "n": st["n"],
                    "win_pct": st["win_pct"],
                    "avg_pct": st["avg_pct"],
                    "ann_ror": st["ann_ror"],
                    "median_pct": st["median_pct"],
                    "pf": st["pf"],
                    "wo_max": st["wo_max"],
                    "outlier_pct": st["outlier"],
                    "avg_days": st["avg_days"],
                    "median_days": st["median_days"],
                    "capital_days": st["capital_days"],
                    "trades_per_year": st["tpy"],
                    "max_dd": st["max_dd"],
                    "sharpe": st["sharpe"],
                    "calmar": st["calmar"],
                    "line_exits": st["line_n"],
                    "clock_exits": st["time_n"],
                    "open_n": st["open_n"],
                    "profit_per_capital_day": st["profit_per_capital_day"],
                    "verdict": arm["verdict"],
                    "verdict_why": arm["why"],
                    "lookahead": arm["lookahead"],
                }
            )
    for row in ctx["diag"]:
        rows.append(
            {
                "section": "same_day",
                "ranker": row["name"],
                "ranker_id": row["id"],
                "sample": row["sample"],
                "n": row["compared"],
                "win_pct": row["other_better_pct"],
                "avg_pct": row["other_avg"],
                "ann_ror": float("nan"),
                "median_pct": float("nan"),
                "pf": float("nan"),
                "wo_max": float("nan"),
                "outlier_pct": float("nan"),
                "avg_days": float("nan"),
                "median_days": float("nan"),
                "capital_days": "",
                "trades_per_year": float("nan"),
                "max_dd": float("nan"),
                "sharpe": float("nan"),
                "calmar": float("nan"),
                "line_exits": "",
                "clock_exits": "",
                "open_n": "",
                "profit_per_capital_day": float("nan"),
                "verdict": "",
                "verdict_why": (
                    f"differ {row['disagree']} of {row['multi_days']}; "
                    f"current avg {row['control_avg']}; delta {row['delta']}; "
                    f"other higher {row['other_better']}; both closed {row['closed_compared']}"
                ),
                "lookahead": "",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    print("RANKERS FROZEN BEFORE P&L:", ", ".join(r["id"] for r in RANKERS), flush=True)
    print("DROPPED:", DROPPED, flush=True)
    print(
        f"VERDICT BAR frozen: IS avg edge > {KEEP_AVG_EDGE}, WR drop <= {KEEP_WR_DROP_MAX}, "
        f"N ratio >= {KEEP_N_RATIO_MIN}, OOS soften {OOS_SOFTEN}. Ann ROR does not override.",
        flush=True,
    )
    bt = thorp._load_bt()
    menu = pd.read_csv(thorp.PAIR_MENU)
    menu["left"] = menu["left"].astype(str)
    menu["right"] = menu["right"].astype(str)
    if "business" in menu.columns:
        menu["business"] = menu["business"].fillna("")
    else:
        menu["business"] = ""
    symbols = sorted(set(menu["left"]).union(set(menu["right"])))
    print(f"menu pairs {len(menu)} symbols {len(symbols)}", flush=True)
    close_wide, opens, _hits = thorp.load_prices(symbols, bt)
    panels = bt.build_panels(menu, close_wide, opens)
    corr_full, year_mat = attach_menu(panels, menu)
    by_date, all_dates = collect_signals(panels, bt, corr_full, year_mat)
    counts = gap_count_for(by_date)

    thorp.EXIT_Z = EXIT_Z
    arms = []
    control_trades = None
    control_pack = None
    match = ""
    for spec in RANKERS:
        print(f"replay {spec['id']}", flush=True)
        best_on = best_on_for(by_date, panels, spec)
        trades, equity, _meta = thorp.replay(panels, best_on, counts, all_dates, bt, CLOCK)
        frame = thorp.trades_frame(trades)
        if spec["control"]:
            match = check_control(frame)
            control_trades = trades
        arm = pack_arm(spec, frame, equity)
        arms.append(arm)
        st = arm["samples"]["IS"]
        print(
            f"  IS n {st['n']} wr {st['win_pct']:.2f} avg {st['avg_pct']:.2f} ann {st['ann_ror']:.2f}",
            flush=True,
        )
    control_pack = next(a for a in arms if a["control"])
    for arm in arms:
        label, why = judge(arm, control_pack)
        arm["verdict"] = label
        arm["why"] = why
        print(f"VERDICT {arm['id']} {label}", flush=True)

    walk = walk_conflicts(by_date, all_dates, panels, bt, control_trades)
    print("same-day outcomes", flush=True)
    diag = diagnose(walk["conflicts"], panels)
    likely = most_likely(arms)
    ctx = {"arms": arms, "walk": walk, "diag": diag, "likely": likely, "match": match}
    # Drop the heavy candidate lists before rendering. diagnose already finished.
    walk["conflicts"] = []

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.html").write_text(render(ctx), encoding="utf-8")
    (OUT / "BASELINE.md").write_text(baseline_md(ctx), encoding="utf-8")
    summary_frame(ctx).to_csv(OUT / "summary.csv", index=False)
    print(f"wrote {OUT}", flush=True)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "ntfy_job_done.py"),
            "--path",
            str(OUT / "report.html"),
            "-t",
            "SSD which pair",
        ],
        check=False,
    )


if __name__ == "__main__":
    main()
