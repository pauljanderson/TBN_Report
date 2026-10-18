"""Build the PO MAKO / PSX zone stamp from warehouse tape + today's BRT book."""
from __future__ import annotations

import html
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))
from compare_format import (  # noqa: E402
    ann_ror_from_closed,
    format_money,
    sharpe_from_equity_curve_csv,
)

STAMP = ROOT / "drive" / "paul_experiments" / "po_mako_psx_zone_20260930"
CLOSED = ROOT / "drive" / "BRT_Closed_260930184125.csv"
REPORT = ROOT / "drive" / "BRT_Report_260930184125.csv"
SUMMARY = ROOT / "drive" / "BRT_Summary_260930184125.csv"
EQUITY = ROOT / "drive" / "BRT_EquityCurve_260930184125.csv"
DATA = ROOT / "data" / "newdata" / "data"
IS_CUT = date(2024, 1, 1)
QUOTE = (
    "thanks. here's some more feedback from PO\n"
    "Mako, could go lower and fill that gap from August and retest that zone.  "
    "But it has room to go up and catch close to 20% before it hits all time high.\n"
    "Would have been great to have caught PSX on a BRT of that zone back in June.  "
    "Went up 60% from there."
)


def load_ohlc(sym: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sym}.csv")
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def unfilled_gaps(df: pd.DataFrame, start: str, end: str) -> list[dict]:
    """Classic gaps: low > prior high. Still open if no later low has traded back to the prior high."""
    out = []
    hi = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    dates = df["date"]
    n = len(df)
    for i in range(1, n):
        d = dates.iloc[i]
        if d < pd.Timestamp(start) or d > pd.Timestamp(end):
            continue
        if not (lo[i] > hi[i - 1]):
            continue
        later = lo[i + 1 :]
        deepest = float(later.min()) if len(later) else float("inf")
        filled = bool(len(later) and deepest <= hi[i - 1] + 1e-9)
        still_open_top = deepest if not filled else None
        # remaining hole is (prior high, min(gap low, deepest later low)) if deepest > prior high
        gap_bot = float(hi[i - 1])
        gap_top = float(lo[i])
        if len(later) and deepest < gap_top:
            # partial fill down to deepest
            if deepest <= gap_bot:
                remain_bot = remain_top = None
            else:
                remain_bot, remain_top = gap_bot, deepest
        else:
            remain_bot, remain_top = gap_bot, gap_top
        out.append(
            {
                "gap_date": d.date().isoformat(),
                "prior_date": dates.iloc[i - 1].date().isoformat(),
                "prior_high": round(gap_bot, 4),
                "gap_low": round(gap_top, 4),
                "open_": round(float(df["open"].iloc[i]), 4),
                "close": round(float(df["close"].iloc[i]), 4),
                "filled": filled,
                "unfilled_low": None if remain_bot is None else round(remain_bot, 4),
                "unfilled_high": None if remain_top is None else round(remain_top, 4),
                "later_min_low": None if not len(later) else round(deepest, 4),
            }
        )
    return out


def pct_down(px: float, level: float) -> float:
    return (px - level) / px * 100.0


def pct_up(px: float, level: float) -> float:
    return (level / px - 1.0) * 100.0


def parse_pnl_pct(s) -> float:
    t = str(s).strip().replace("%", "").replace(",", "")
    return float(t)


def parse_entry(s) -> date:
    t = str(s).strip().replace("-", "").replace("/", "")[:8]
    return datetime.strptime(t, "%Y%m%d").date()


def percentile(a: np.ndarray, q: float) -> float:
    if len(a) == 0:
        return float("nan")
    return float(np.quantile(a, q))


def max_dd_pct(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return abs(worst) * 100.0


def equity_slice(start: date | None, end_exclusive: date | None) -> list[float]:
    df = pd.read_csv(EQUITY, usecols=["Date", "Equity_Regular"])
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    if start is not None:
        df = df[df["Date"] >= start]
    if end_exclusive is not None:
        df = df[df["Date"] < end_exclusive]
    return [float(x) for x in df["Equity_Regular"].tolist() if pd.notna(x) and float(x) > 0]


def losing_streak(pnls: list[float]) -> int:
    best = cur = 0
    for p in pnls:
        if p < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def slice_metrics(trades: pd.DataFrame, *, label: str, brt_cash: float, report_row: dict | None) -> dict:
    n = len(trades)
    pnl = trades["pnl"].to_numpy(float) if n else np.array([])
    dollars = trades["dollars"].to_numpy(float) if n else np.array([])
    days = trades["days"].to_numpy(float) if n else np.array([])
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    win_d = dollars[dollars > 0]
    loss_d = dollars[dollars < 0]
    wr = (len(wins) / n * 100.0) if n else float("nan")
    avg = float(pnl.mean()) if n else float("nan")
    wo = float(np.delete(pnl, int(np.argmax(pnl))).mean()) if n > 1 else float("nan")
    avg_win = float(wins.mean()) if len(wins) else float("nan")
    avg_loss = float(losses.mean()) if len(losses) else float("nan")
    pf = (float(win_d.sum()) / abs(float(loss_d.sum()))) if len(loss_d) and abs(float(loss_d.sum())) > 0 else float("nan")
    wl_n = (len(wins) / len(losses)) if len(losses) else float("nan")
    wl_d = (float(win_d.sum()) / abs(float(loss_d.sum()))) if len(loss_d) and loss_d.sum() != 0 else float("nan")
    avg_days = float(days.mean()) if n else float("nan")
    total_pnl = float(dollars.sum()) if n else 0.0
    ann = ann_ror_from_closed(
        total_pnl=total_pnl,
        n_trades=n,
        avg_days_held=avg_days if avg_days == avg_days else 0.0,
        brt_cash=brt_cash,
    )
    if label == "Full" and report_row is not None:
        # Prefer the host report on the full book so Ann ROR / Max DD / Sharpe match DailyRun.
        ann = float(report_row["Ann_ROR"])
        maxdd = float(report_row["Max_DD"])
        sharpe = float(report_row["Sharpe"])
        calmar = float(report_row["Calmar"])
        exp_d = float(report_row["Expectancy"])
        ppc = float(report_row["Profit_Per_Capital_Day"])
        cap_days = int(float(report_row["Capital_Days"]))
        med_days = float(report_row["Median_Days_Held"])
        p90_days = float(report_row["P90_Days"])
        streak = int(float(report_row["Losing_Streak"]))
        avg_pos = float(report_row["Avg_Positions"])
    else:
        if label == "IS":
            eq = equity_slice(None, IS_CUT)
            sharpe = sharpe_from_equity_curve_csv(EQUITY, end_date_exclusive=IS_CUT)
        elif label == "OOS":
            eq = equity_slice(IS_CUT, None)
            sharpe = sharpe_from_equity_curve_csv(EQUITY, start_date=IS_CUT)
        else:
            eq = equity_slice(None, None)
            sharpe = sharpe_from_equity_curve_csv(EQUITY)
        maxdd = max_dd_pct(eq)
        calmar = (ann / maxdd) if ann is not None and maxdd not in (None, 0) else None
        exp_d = float(dollars.mean()) if n else float("nan")
        cap_days = int(days.sum()) if n else 0
        ppc = (total_pnl / cap_days) if cap_days else float("nan")
        med_days = float(np.median(days)) if n else float("nan")
        p90_days = percentile(days, 0.90) if n else float("nan")
        streak = losing_streak(pnl.tolist())
        avg_pos = float("nan")
    return {
        "slice": label,
        "n": n,
        "wins": int((pnl > 0).sum()) if n else 0,
        "losses": int((pnl < 0).sum()) if n else 0,
        "wr": wr,
        "avg": avg,
        "wo_max": wo,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "exp_d": exp_d,
        "exp_pct": avg,
        "wl_n": wl_n,
        "wl_d": wl_d,
        "pf": pf,
        "ann": ann,
        "maxdd": maxdd,
        "calmar": calmar,
        "sharpe": sharpe,
        "ppc": ppc,
        "cap_days": cap_days,
        "avg_days": avg_days,
        "med_days": med_days,
        "p90_days": p90_days,
        "streak": streak,
        "avg_pos": avg_pos,
    }


def fnum(x, nd=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}"


def fpct(x, nd=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:.{nd}f}%"


def fpx(x) -> str:
    return f"${x:,.2f}"


def th(label, kind) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    mako = load_ohlc("MAKO")
    psx = load_ohlc("PSX")
    last = mako.iloc[-1]
    last_px = float(last["close"])
    last_dt = last["date"].date().isoformat()
    ath_i = int(mako["high"].idxmax())
    ath_px = float(mako.iloc[ath_i]["high"])
    ath_dt = mako.iloc[ath_i]["date"].date().isoformat()
    run_i = int(mako.loc[mako["date"] >= "2024-01-01", "high"].idxmax())
    run_px = float(mako.iloc[run_i]["high"])
    run_dt = mako.iloc[run_i]["date"].date().isoformat()

    gaps = unfilled_gaps(mako, "2026-08-01", "2026-09-30")
    open_gaps = [g for g in gaps if g["unfilled_low"] is not None]
    # drop microscopic gaps under 0.5%
    open_gaps = [
        g
        for g in open_gaps
        if g["unfilled_high"] > g["unfilled_low"] * 1.002
    ]

    zones = pd.read_csv(ROOT / "tmp_po_mako_psx_diag" / "BRT_ZONES_MAKO_260930233720.csv")
    zones["DATE"] = pd.to_datetime(zones["DATE"])
    z26 = zones[zones["DATE"] >= "2026-01-01"].copy()

    level_rows = [
        {
            "item": "Latest close",
            "date": last_dt,
            "price_low": last_px,
            "price_high": last_px,
            "pct_from_here": 0.0,
            "note": f"Daily warehouse close on {last_dt}. Open {float(last['open']):.2f}, high {float(last['high']):.2f}, low {float(last['low']):.2f}.",
        },
        {
            "item": "High of this advance (Aug 25, 2026)",
            "date": run_dt,
            "price_low": run_px,
            "price_high": run_px,
            "pct_from_here": pct_up(last_px, run_px),
            "note": "Highest daily high from 2024 onward. This is the high the chart is testing. About 20% matches this level.",
        },
        {
            "item": "Warehouse all-time high (2012 print)",
            "date": ath_dt,
            "price_low": ath_px,
            "price_high": ath_px,
            "pct_from_here": pct_up(last_px, ath_px),
            "note": "Highest high in data/newdata since 2012-02-03. Volume that day was about 1,010 shares. This is farther than 20%.",
        },
    ]
    for g in open_gaps:
        level_rows.append(
            {
                "item": f"Unfilled August gap {g['gap_date']}",
                "date": g["gap_date"],
                "price_low": g["unfilled_low"],
                "price_high": g["unfilled_high"],
                "pct_from_here": -pct_down(last_px, g["unfilled_high"]),
                "note": (
                    f"Prior high {g['prior_date']} ${g['prior_high']:.2f} to gap-day low ${g['gap_low']:.2f}. "
                    f"Still open through {last_dt} (later min low ${g['later_min_low']:.2f}). "
                    f"Percent down is from the close to the top of the hole; the bottom of the hole is "
                    f"{pct_down(last_px, g['unfilled_low']):.1f}% below the close."
                ),
            }
        )
    for _, z in z26.sort_values("DATE").iterrows():
        if float(z["ZONE_HIGH"]) > last_px + 0.05 and float(z["ZONE_CENTER"]) > run_px - 0.01:
            kind = "BRT zone at the August high"
        elif float(z["ZONE_LOW"]) >= last_px:
            kind = "BRT zone above the close"
        else:
            kind = "BRT zone at or below the close"
        mid = float(z["ZONE_CENTER"])
        level_rows.append(
            {
                "item": f"{kind} (matured {pd.Timestamp(z['DATE']).date().isoformat()})",
                "date": pd.Timestamp(z["DATE"]).date().isoformat(),
                "price_low": float(z["ZONE_LOW"]),
                "price_high": float(z["ZONE_HIGH"]),
                "pct_from_here": (mid / last_px - 1.0) * 100.0,
                "note": (
                    f"Sheet zone center ${mid:.2f}, band ${float(z['ZONE_LOW']):.2f}–${float(z['ZONE_HIGH']):.2f} "
                    f"(band_pct 0.0154). Percent is from the close to the center "
                    f"({'down' if mid < last_px else 'up'})."
                ),
            }
        )

    levels = pd.DataFrame(level_rows)
    levels.to_csv(STAMP / "mako_levels.csv", index=False)

    # PSX path
    psx_win = psx[(psx["date"] >= "2026-06-01") & (psx["date"] <= "2026-09-30")].copy()
    hi_i = int(psx["high"].idxmax())
    psx_high = float(psx.iloc[hi_i]["high"])
    psx_high_dt = psx.iloc[hi_i]["date"].date().isoformat()
    june18 = psx.loc[psx["date"] == "2026-06-18"].iloc[0]
    june15 = psx.loc[psx["date"] == "2026-06-15"].iloc[0]
    jul13 = psx.loc[psx["date"] == "2026-07-13"].iloc[0]
    zone_c, zone_lo, zone_hi = 190.61, 187.67, 193.55
    path = psx_win[["date", "open", "high", "low", "close"]].copy()
    path["date"] = path["date"].dt.date.astype(str)
    path["note"] = ""
    notes = {
        "2026-06-08": "Pivot high $188.00. Pre-rise into that high was only 7.8% (the 10% touch test needs 10%).",
        "2026-06-15": "Close $173.26. From this close to the later high is about 60%.",
        "2026-06-18": "Pivot low $164.10, the June shelf low. Pivot lows do not birth BRT zones.",
        "2026-07-13": "BRT logged a breakout of the $187.67–$193.55 zone. No retest followed.",
        "2026-09-18": "Later high of the warehouse series.",
        "2026-09-30": "Latest close.",
    }
    path["note"] = path["date"].map(lambda d: notes.get(d, ""))
    path.to_csv(STAMP / "psx_path.csv", index=False)

    psx_notes = pd.DataFrame(
        [
            {
                "measure": "June 18 low to later high",
                "from_date": "2026-06-18",
                "from_price": float(june18["low"]),
                "to_date": psx_high_dt,
                "to_price": psx_high,
                "pct": pct_up(float(june18["low"]), psx_high),
                "matches_about_60": "no, higher than 60",
            },
            {
                "measure": "June 15 close to later high",
                "from_date": "2026-06-15",
                "from_price": float(june15["close"]),
                "to_date": psx_high_dt,
                "to_price": psx_high,
                "pct": pct_up(float(june15["close"]), psx_high),
                "matches_about_60": "yes, about 60",
            },
            {
                "measure": "BRT zone center to later high",
                "from_date": "2026-04-09",
                "from_price": zone_c,
                "to_date": psx_high_dt,
                "to_price": psx_high,
                "pct": pct_up(zone_c, psx_high),
                "matches_about_60": "no, that BRT zone is not a 60% move",
            },
            {
                "measure": "BRT zone upper edge to later high",
                "from_date": "2026-04-09",
                "from_price": zone_hi,
                "to_date": psx_high_dt,
                "to_price": psx_high,
                "pct": pct_up(zone_hi, psx_high),
                "matches_about_60": "no",
            },
            {
                "measure": "July 13 breakout close to later high",
                "from_date": "2026-07-13",
                "from_price": float(jul13["close"]),
                "to_date": psx_high_dt,
                "to_price": psx_high,
                "pct": pct_up(float(jul13["close"]), psx_high),
                "matches_about_60": "no",
            },
            {
                "measure": "Latest close vs later high",
                "from_date": "2026-09-30",
                "from_price": float(psx.iloc[-1]["close"]),
                "to_date": psx_high_dt,
                "to_price": psx_high,
                "pct": pct_up(float(psx.iloc[-1]["close"]), psx_high),
                "matches_about_60": "pullback from the high, not the June measurement",
            },
        ]
    )
    psx_notes.to_csv(STAMP / "psx_move.csv", index=False)

    # Control book
    rep = pd.read_csv(REPORT).iloc[0].to_dict()
    brt_cash = float(rep["brt_cash"])
    closed = pd.read_csv(CLOSED)
    closed["entry"] = closed["DATE_OPENED"].map(parse_entry)
    closed["pnl"] = closed["PNL_PCT"].map(parse_pnl_pct)
    closed["dollars"] = pd.to_numeric(closed["PNL_DOLLARS"], errors="coerce")
    closed["days"] = pd.to_numeric(closed["DAYS_HELD"], errors="coerce").fillna(0)
    closed = closed.sort_values(["entry", "SYMBOL"]).reset_index(drop=True)
    full = slice_metrics(closed, label="Full", brt_cash=brt_cash, report_row=rep)
    is_df = closed[closed["entry"] < IS_CUT]
    oos_df = closed[closed["entry"] >= IS_CUT]
    inn = slice_metrics(is_df, label="IS", brt_cash=brt_cash, report_row=None)
    oos = slice_metrics(oos_df, label="OOS", brt_cash=brt_cash, report_row=None)
    slices = [full, inn, oos]

    # sanity: reconstructed full max dd vs report
    recon_dd = max_dd_pct(equity_slice(None, None))
    recon_sh = sharpe_from_equity_curve_csv(EQUITY)

    exits = (
        closed.groupby("EXIT_TYPE")
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n", ascending=False)
    )
    exits["pct"] = exits["n"] / len(closed) * 100.0
    css_src = (ROOT / "drive" / "paul_experiments" / "_gen_too_high_diff.py").read_text(encoding="utf-8")
    sort_css = css_src.split('SORTABLE_TH_CSS = """', 1)[1].split('"""', 1)[0]
    sort_js = css_src.split('SORTABLE_TABLE_SCRIPT = """', 1)[1].split('"""', 1)[0]

    summary = pd.read_csv(SUMMARY)
    fit_mean = float(pd.to_numeric(summary["FIT_SCORE"], errors="coerce").mean())
    fit_sum = float(pd.to_numeric(summary["FIT_SCORE"], errors="coerce").sum())
    fitr_mean = float(pd.to_numeric(summary["FIT_SCORE_ROBUST"], errors="coerce").mean())
    paul_mean = float(pd.to_numeric(summary["PAUL_SCORE"], errors="coerce").mean())
    wo_mean = float(pd.to_numeric(summary["AVG_PNL_PCT_WO_MAX"], errors="coerce").mean())
    out_mean = float(pd.to_numeric(summary["OUTLIER_PCT_OF_WINS"], errors="coerce").mean())
    tpy_mean = float(pd.to_numeric(summary["AVG_TRADES_PER_YEAR"], errors="coerce").mean())
    pf_mean = float(pd.to_numeric(summary["PROFIT_FACTOR"], errors="coerce").replace([np.inf, -np.inf], np.nan).mean())

    # Descriptive gap / room split on the control book. Not an entry rule.
    by_sym: dict[str, pd.DataFrame] = {}
    flags = []
    for sym, grp in closed.groupby("SYMBOL"):
        path_df = load_ohlc(str(sym))
        by_sym[str(sym)] = path_df
        hi = path_df["high"].to_numpy(float)
        lo = path_df["low"].to_numpy(float)
        dts = path_df["date"].dt.date.to_numpy()
        # prefix min of future lows via reverse scan
        n = len(path_df)
        # For each entry, find index
        idx_map = {d: i for i, d in enumerate(dts)}
        for rec in grp.itertuples(index=False):
            i = idx_map.get(rec.entry)
            if i is None or i < 1:
                flags.append((rec.SYMBOL, rec.entry, False, float("nan"), rec.pnl))
                continue
            prior_high = float(np.max(hi[:i]))
            room = prior_high / float(rec.ENTRY_PRICE) - 1.0
            gap_below = False
            # Recent hole: formed in the 63 sessions before the entry, still unfilled,
            # and the top of the hole is within 20% under the entry. Matches the MAKO
            # picture (an August gap a short way under the price) rather than any old gap.
            look = max(1, i - 63)
            entry_px = float(rec.ENTRY_PRICE)
            for g in range(look, i):
                if lo[g] <= hi[g - 1]:
                    continue
                later_min = float(np.min(lo[g + 1 : i])) if g + 1 < i else float("inf")
                if later_min <= hi[g - 1]:
                    continue
                gap_top = float(lo[g])
                if gap_top < entry_px and (entry_px - gap_top) / entry_px <= 0.20:
                    gap_below = True
                    break
            flags.append((rec.SYMBOL, rec.entry, gap_below, room * 100.0, rec.pnl))
    flag_df = pd.DataFrame(flags, columns=["symbol", "entry", "gap_below", "room_pct", "pnl"])
    def _pack(sub, name):
        if len(sub) == 0:
            return {"group": name, "n": 0, "wr": float("nan"), "avg": float("nan")}
        pnl = sub["pnl"].to_numpy(float)
        return {
            "group": name,
            "n": int(len(sub)),
            "wr": float((pnl > 0).mean() * 100.0),
            "avg": float(pnl.mean()),
        }
    room_lt = flag_df["room_pct"] < 20
    room_ge = flag_df["room_pct"] >= 20
    split_rows = [
        _pack(flag_df[flag_df["gap_below"]], "Open gap below the entry"),
        _pack(flag_df[~flag_df["gap_below"]], "No open gap below the entry"),
        _pack(flag_df[room_lt & flag_df["room_pct"].notna()], "Room to prior high under 20%"),
        _pack(flag_df[room_ge], "Room to prior high 20% or more"),
    ]
    split_df = pd.DataFrame(split_rows)
    split_df.to_csv(STAMP / "control_gap_room_split.csv", index=False)

    # ---- HTML ----
    def metric_row(m):
        cells = [
            m["slice"],
            str(m["n"]),
            str(m["wins"]),
            str(m["losses"]),
            fpct(m["wr"]),
            fpct(m["avg"]),
            fpct(m["wo_max"]),
            format_money(m["exp_d"]),
            fpct(m["exp_pct"]),
            fpct(m["avg_win"]),
            fpct(m["avg_loss"]),
            fnum(m["wl_n"], 2),
            fnum(m["wl_d"], 2),
            fnum(m["pf"], 2),
            fpct(m["ann"]),
            fpct(m["maxdd"]),
            fnum(m["calmar"], 2),
            fnum(m["sharpe"], 2),
            format_money(m["ppc"]),
            str(m["cap_days"]),
            fnum(m["avg_days"], 1),
            fnum(m["med_days"], 1),
            fnum(m["p90_days"], 1),
            str(m["streak"]),
            fnum(m["avg_pos"], 2) if m["avg_pos"] == m["avg_pos"] else "—",
        ]
        return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    level_html = []
    for r in level_rows:
        level_html.append(
            "<tr>"
            f"<td>{html.escape(r['item'])}</td>"
            f"<td>{r['date']}</td>"
            f"<td>{fpx(r['price_low'])}</td>"
            f"<td>{fpx(r['price_high'])}</td>"
            f"<td>{r['pct_from_here']:+.1f}%</td>"
            f"<td>{html.escape(r['note'])}</td>"
            "</tr>"
        )
    psx_html = []
    for _, r in psx_notes.iterrows():
        psx_html.append(
            "<tr>"
            f"<td>{html.escape(str(r['measure']))}</td>"
            f"<td>{r['from_date']}</td>"
            f"<td>{fpx(r['from_price'])}</td>"
            f"<td>{r['to_date']}</td>"
            f"<td>{fpx(r['to_price'])}</td>"
            f"<td>{r['pct']:+.1f}%</td>"
            f"<td>{html.escape(str(r['matches_about_60']))}</td>"
            "</tr>"
        )
    exit_html = []
    for _, r in exits.iterrows():
        exit_html.append(
            f"<tr><td>{html.escape(str(r['EXIT_TYPE']))}</td><td>{int(r['n'])}</td><td>{r['pct']:.1f}%</td></tr>"
        )
    split_html = []
    for _, r in split_df.iterrows():
        split_html.append(
            f"<tr><td>{html.escape(r['group'])}</td><td>{int(r['n'])}</td>"
            f"<td>{r['wr']:.1f}%</td><td>{r['avg']:+.2f}%</td></tr>"
        )

    gap_n = int(split_df.iloc[0]["n"])
    gap_wr = split_df.iloc[0]["wr"]
    gap_avg = split_df.iloc[0]["avg"]
    nog_wr = split_df.iloc[1]["wr"]
    nog_avg = split_df.iloc[1]["avg"]

    # pick the two real August gaps for the prose
    prose_gaps = []
    for g in open_gaps:
        prose_gaps.append(
            f"{g['gap_date']} from ${g['unfilled_low']:.2f} to ${g['unfilled_high']:.2f} "
            f"({pct_down(last_px, g['unfilled_high']):.1f}% down to the top, "
            f"{pct_down(last_px, g['unfilled_low']):.1f}% down to the bottom)"
        )
    gap_sentence = "; ".join(prose_gaps) if prose_gaps else "none"

    # zones under price in 2026
    under = z26[z26["ZONE_HIGH"] < last_px].sort_values("ZONE_CENTER", ascending=False)
    under_bits = []
    for _, z in under.head(4).iterrows():
        under_bits.append(
            f"${float(z['ZONE_CENTER']):.2f} "
            f"(${float(z['ZONE_LOW']):.2f}–${float(z['ZONE_HIGH']):.2f}, matured {pd.Timestamp(z['DATE']).date().isoformat()}, "
            f"{pct_down(last_px, float(z['ZONE_CENTER'])):.1f}% below the close)"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>MAKO and PSX zone note — 2026-09-30</title>
<style>
  body {{ font-family: Georgia, "Iowan Old Style", serif; max-width: 1100px; margin: 2rem auto; padding: 0 1.2rem; color: #1c1917; background: #faf8f5; line-height: 1.45; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 0.2rem; }}
  h2 {{ font-size: 1.2rem; margin-top: 1.8rem; }}
  .meta {{ color: #57534e; font-size: 0.95rem; }}
  blockquote {{ background: #fff; border-left: 4px solid #3f6212; margin: 0.6rem 0; padding: 0.8rem 1rem; white-space: pre-wrap; }}
  .callout {{ background: #fff; border: 1px solid #d6d3d1; padding: 0.9rem 1rem; margin: 0.8rem 0 1.2rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; margin: 0.6rem 0 1rem; font-size: 0.92rem; }}
  th, td {{ border-bottom: 1px solid #e7e5e4; text-align: left; padding: 0.35rem 0.45rem; vertical-align: top; }}
  caption {{ text-align: left; font-size: 0.9rem; color: #57534e; margin-bottom: 0.3rem; }}
  {sort_css}
  td:nth-child(n+2) {{ font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>MAKO now, and the June PSX zone</h1>
<p class="meta">Research only. Not gold. Not DailyRun. Stamp 2026-09-30. Control book is today's production Break and ReTest run <code>BRT_*_260930184125</code> (42-name whitelist). In-sample is an entry before 2024-01-01. Out-of-sample is an entry on or after that date, and it is report-only.</p>

<h2>What you asked</h2>
<blockquote>{html.escape(QUOTE)}</blockquote>

<h2>In plain English</h2>
<div class="callout">
<p>MAKO can still fall into the August gap and retest the green zone, and if it rises instead the old high is not far away. PSX was a zone in June that then ran hard, and the question is whether Break and ReTest (BRT) as it stands would have bought that zone.</p>
<p>Annualized rate of return is the yearly pace of the book's percent gains, given how long each trade is held and how much cash is put to work. On the production book it is {fpct(full['ann'])}.</p>
</div>

<h2>What the photos show</h2>
<p>The first laptop screen is titled MAKO. The second is titled PSX. Both show a thick green horizontal band. On MAKO the price has come off a high on the right and the August advance left unfilled holes underneath. On PSX the price chopped around a horizontal area and then rallied after June.</p>

<h2>MAKO — measured on the daily warehouse</h2>
<p>Last close is <strong>{fpx(last_px)}</strong> on {last_dt}.</p>
<p>Unfilled August gaps (the price never traded back through them): {html.escape(gap_sentence)}.</p>
<p>Break and ReTest builds a zone from a strong pivot high, not from a hand-drawn line. Pivot lows do not start a zone (<code>zones_from_pivot_lows_enabled</code> is off). Walking down from the {fpx(last_px)} close: the nearest zone is $8.99 (band $8.85–$9.13, matured 2026-05-28), {pct_down(last_px, 8.99):.1f}% under the close. Just beneath that is the August 7 hole at $8.68–$8.94. The June 29 zone at $8.60 ($8.47–$8.73, {pct_down(last_px, 8.60):.1f}% down) sits on the bottom of that hole. Deeper, the August 5 hole is $7.58–$7.76, and the July 15 zone at $7.97 ($7.85–$8.09, {pct_down(last_px, 7.97):.1f}% down) sits just above it. Those two bands are the green-zone match for "fill the August gap and retest that zone."</p>
<p>Room up to the August 25, 2026 high of <strong>{fpx(run_px)}</strong> is <strong>{pct_up(last_px, run_px):+.1f}%</strong>. That is the high of this advance and the level "close to 20%" matches. The warehouse all-time high is {fpx(ath_px)} on {ath_dt}, which is {pct_up(last_px, ath_px):+.1f}% above the close. That older print does not match "about 20%."</p>
<p>MAKO is not on the production whitelist, so today's live book does not hold it. Running the same frozen entry on MAKO alone shows the last trade was an August 25, 2026 buy at $10.80 on a $10.30 zone, stopped on September 1 at $9.60 (−11.1%). Those August gaps were already open underneath that entry. That is the live version of "it could go lower and fill the gap."</p>
<table class="sortable">
<caption>MAKO levels. Percent is from the {last_dt} close to the price shown (negative means that level is under the close; for a gap it is the top of the hole). Click column headers to sort.</caption>
<thead><tr>
{th('Level','text')}{th('Date','date')}{th('Low','num')}{th('High','num')}{th('Percent from close','num')}{th('Note','text')}
</tr></thead>
<tbody>
{''.join(level_html)}
</tbody>
</table>

<h2>PSX — June zone and the later high</h2>
<p>PSX is not on the production whitelist either. The September 30 production closed file, watchlist, and breakout file have no PSX row. Running the frozen Break and ReTest entry on PSX by itself also takes no trade in June 2026.</p>
<p>The zone the engine did have near this rally matured on April 9, 2026 at <strong>$190.61</strong> (band $187.67–$193.55), from the March 30 pivot high. Price broke that band on July 13, 2026 (close {fpx(float(jul13['close']))}). The low never came back to $193.55 after that breakout, so the retest the system waits for never happened. June itself never opened a pending retest: the June 18 pivot low at $164.10 is not used to birth a zone, and the June 8 pivot high at $188.00 failed the 10% pre-rise test (it was 7.8%).</p>
<p>The stock's move: the June 18 low of {fpx(float(june18['low']))} to the high of <strong>{fpx(psx_high)}</strong> on {psx_high_dt} is <strong>{pct_up(float(june18['low']), psx_high):+.1f}%</strong>. The June 15 close of {fpx(float(june15['close']))} to that same high is <strong>{pct_up(float(june15['close']), psx_high):+.1f}%</strong>, which is the "about 60%." The engine's $190.61 zone to that high is only {pct_up(zone_c, psx_high):+.1f}%. So 60% matches a mid-June price around $173, not the zone Break and ReTest actually carried.</p>
<p>A nearby retest that did happen was February 23, 2026, on an older zone at $150.12 ($147.81–$152.43). The trace on that day and the next day is blocked by the red-to-green rule (the prior day was already a green candle, so it was not a red day turning green). Turning only that switch off does buy PSX on February 24 at $153.79 and sells the production +21% target on March 26 at $186.09. It does not buy June, and it does not hold the rest of the run. That is a different month and a different zone, so it was not frozen as the candidate.</p>
<p>Production exits at 1.21 times the entry (about +21%) or the stop at 0.934 times the entry-bar low. Even a June fill at the shelf would have been aiming at that +21% target, not at the full 60% the stock later traveled, unless the open jumped through the target.</p>
<table class="sortable">
<caption>PSX move from the June area to the later high. Click column headers to sort.</caption>
<thead><tr>
{th('Measure','text')}{th('From date','date')}{th('From','num')}{th('To date','date')}{th('To','num')}{th('Percent','num')}{th('About 60%?','text')}
</tr></thead>
<tbody>
{''.join(psx_html)}
</tbody>
</table>

<h2>The one comparison</h2>
<p>Break and ReTest already buys a retest of a matured pivot-high zone, with the same stop and target it uses now. The June PSX shelf never became that kind of zone, and the zone that did mature broke out without a retest. No single gate, switched alone, would have included the June case. A fitted lower pullback or a new line-drawing rule was not frozen. The candidate was not run. Verdict on in-sample quality: <strong>HOLD</strong>. Out-of-sample was not used to pick a knob.</p>

<h2>Today's Break and ReTest book</h2>
<p>Same production exit (stop multiplier 0.934, target multiplier 1.21, red-to-green on, 3-year price-up growth filter on, pivot-low zones off). Universe size {len(summary)}. Cash used in the annualized rate of return formula is {format_money(brt_cash)} per trade slot. Click column headers to sort.</p>
<table class="sortable">
<caption>Full book, in-sample (entry before 2024-01-01), and out-of-sample (entry on or after 2024-01-01). Out-of-sample is report-only.</caption>
<thead><tr>
{th('Slice','text')}{th('Trades','num')}{th('Wins','num')}{th('Losses','num')}{th('Win %','num')}
{th('Avg PnL %','num')}{th('Avg PnL % without the biggest win','num')}{th('Expectancy $','num')}{th('Expectancy %','num')}
{th('Avg win %','num')}{th('Avg loss %','num')}{th('Win/loss count','num')}{th('Win/loss $','num')}
{th('Profit factor','num')}{th('Ann ROR %','num')}{th('Max DD %','num')}{th('Calmar','num')}{th('Sharpe','num')}
{th('Profit per capital day','num')}{th('Capital days','num')}{th('Avg days held','num')}{th('Median days held','num')}
{th('P90 days held','num')}{th('Losing streak','num')}{th('Avg positions','num')}
</tr></thead>
<tbody>
{''.join(metric_row(m) for m in slices)}
</tbody>
</table>
<p class="meta">Full-book annualized rate of return, max drawdown, Calmar, and Sharpe are the host report values ({fpct(full['ann'])}, {fpct(full['maxdd'])}, {fnum(full['calmar'])}, {fnum(full['sharpe'])}). Recomputing Sharpe from the daily equity curve gives {fnum(recon_sh)}. Recomputing max drawdown from Equity_Regular gives {fpct(recon_dd)}. In-sample and out-of-sample annualized rate of return uses the same cash and the closed trades in that slice. Their max drawdown and Sharpe are the Equity_Regular curve cut on the calendar at 2024-01-01, which is not the same thing as a book that only held those trades. Symbol scores below are the full book only.</p>
<table class="sortable">
<caption>Exit mix on the full closed book. Click column headers to sort.</caption>
<thead><tr>{th('Exit','text')}{th('Trades','num')}{th('Percent of trades','num')}</tr></thead>
<tbody>{''.join(exit_html)}</tbody>
</table>
<table class="sortable">
<caption>Symbol-level scores on the full production summary. Click column headers to sort.</caption>
<thead><tr>{th('Score','text')}{th('Value','num')}</tr></thead>
<tbody>
<tr><td>Mean FIT score</td><td>{fit_mean:.2f}</td></tr>
<tr><td>Sum of FIT scores</td><td>{fit_sum:.0f}</td></tr>
<tr><td>Mean robust FIT score</td><td>{fitr_mean:.2f}</td></tr>
<tr><td>Mean Paul score</td><td>{paul_mean:.2f}</td></tr>
<tr><td>Mean profit factor</td><td>{pf_mean:.2f}</td></tr>
<tr><td>Mean average percent without the biggest win</td><td>{wo_mean:.2f}%</td></tr>
<tr><td>Mean outlier percent of wins</td><td>{out_mean:.1f}%</td></tr>
<tr><td>Mean trades per year</td><td>{tpy_mean:.2f}</td></tr>
</tbody>
</table>

<h2>A look at the control book, not a new filter</h2>
<p>On the production closed trades, {gap_n} entries had an unfilled gap still open below the entry price (win rate {gap_wr:.1f}%, average {gap_avg:+.2f}%) and the rest did not (win rate {nog_wr:.1f}%, average {nog_avg:+.2f}%). The 20% room split is the same idea as the MAKO comment, counted after the fact. A gap-below warning was not frozen before this look, so it would not have changed any entry.</p>
<table class="sortable">
<caption>Descriptive split of today's closed book. Click column headers to sort.</caption>
<thead><tr>{th('Group','text')}{th('Trades','num')}{th('Win %','num')}{th('Avg PnL %','num')}</tr></thead>
<tbody>{''.join(split_html)}</tbody>
</table>
{sort_js}
</body>
</html>
"""
    # CSS injection above reads the file at runtime inside the f-string — actually I inlined it
    # by calling open() inside the f-string. That's fine if it returns the CSS block.
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    baseline = f"""# MAKO and PSX zone note — 2026-09-30

Research only. Not gold. Not DailyRun. Nothing in this stamp is wired into production.

## What you asked

> {QUOTE.replace(chr(10), chr(10) + '> ')}

## In plain English

MAKO can still fall into the August gap and retest the green zone, and if it rises instead the old high is not far away. PSX was a zone in June that then ran hard, and the question is whether Break and ReTest (BRT) as it stands would have bought that zone.

Annualized rate of return is the yearly pace of the book's percent gains. On today's production book it is {full['ann']:.2f}%.

## Freeze

- Control: production Break and ReTest as of `BRT_*_260930184125`, launched by `run_brt.bat`.
- Universe: `drive/universes/BRT_universe.csv` (42 names). MAKO and PSX are not on it.
- Exit: `stop_pct=0.934` (multiplier), `target_pct=1.21`. Same exit on any candidate. No time stop in this identity.
- Entry that matters here: sheet pivot-high zones (`brt_sheet_touch`, `band_pct=0.0154`, strong pre and post 10% over 7 bars), red-to-green on, 3-year price-up growth filter on, pivot-low zones off.
- In-sample: `entry_date < 2024-01-01`. Out-of-sample: `entry_date >= 2024-01-01`, report-only.
- Candidate: none. See why below. No knob was changed after seeing the book.

## MAKO (live observation, not a 16-year test)

- Close {last_dt}: ${last_px:.2f}.
- Unfilled August gaps: {gap_sentence}.
- Zones under the close that match a retest into those holes: $8.60 matured 2026-06-29 ($8.47–$8.73, {pct_down(last_px, 8.60):.1f}% down) and $7.97 matured 2026-07-15 ($7.85–$8.09, {pct_down(last_px, 7.97):.1f}% down).
- Up to the August 25, 2026 high ${run_px:.2f}: {pct_up(last_px, run_px):+.1f}%. This matches "close to 20%."
- Up to the 2012 warehouse high ${ath_px:.2f} on {ath_dt}: {pct_up(last_px, ath_px):+.1f}%. This does not match 20%.

## PSX

- No production Break and ReTest signal in June 2026. The symbol is off the whitelist, and the frozen entry on the symbol still has no June trade.
- The zone the engine had matured 2026-04-09 at $190.61 ($187.67–$193.55). Breakout 2026-07-13. No retest, because price never came back to the band.
- June 18 low ${float(june18['low']):.2f} to the {psx_high_dt} high ${psx_high:.2f} is {pct_up(float(june18['low']), psx_high):+.1f}%.
- June 15 close ${float(june15['close']):.2f} to that high is {pct_up(float(june15['close']), psx_high):+.1f}%, which matches about 60%.
- Why June was missed: the shelf is a pivot low, and pivot lows do not birth zones; the nearby June pivot high failed the 10% pre-rise test. The breakout that did qualify never retested. That is the retest rule itself plus the zone-birth rules, not one switch.

## Verdict

**HOLD.** Break and ReTest already takes a zone retest of the kind it knows how to build. This June case was not one of those, and no single gate was relaxed. In-sample quality of a new rule was not scored. Out-of-sample was not used to retune.

| Slice | Trades | Win % | Avg PnL % | Ann ROR % |
| --- | ---: | ---: | ---: | ---: |
| Full | {full['n']} | {full['wr']:.1f} | {full['avg']:.2f} | {full['ann']:.2f} |
| IS | {inn['n']} | {inn['wr']:.1f} | {inn['avg']:.2f} | {inn['ann']:.2f} |
| OOS | {oos['n']} | {oos['wr']:.1f} | {oos['avg']:.2f} | {oos['ann']:.2f} |

## Gap note

{gap_n} control entries had an open gap below the fill (win rate {gap_wr:.1f}%, average {gap_avg:+.2f}%) versus the rest (win rate {nog_wr:.1f}%, average {nog_avg:+.2f}%). A gap-below warning was not frozen, so it would not have changed entries.
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")
    print("WROTE", STAMP)
    print("FULL", full["n"], full["wr"], full["avg"], full["ann"], full["maxdd"], full["sharpe"])
    print("IS", inn["n"], inn["wr"], inn["avg"], inn["ann"], inn["maxdd"], inn["sharpe"])
    print("OOS", oos["n"], oos["wr"], oos["avg"], oos["ann"], oos["maxdd"], oos["sharpe"])
    print("recon dd", recon_dd, "recon sharpe", recon_sh)
    print("gaps", open_gaps)
    print("split")
    print(split_df.to_string(index=False))
    print("psx notes")
    print(psx_notes.to_string(index=False))
    print("under", under_bits)


if __name__ == "__main__":
    main()
