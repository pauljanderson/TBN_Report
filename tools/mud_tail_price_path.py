#!/usr/bin/env python3
"""Price path of MUD top-decile winners, filtered vs full L5_R1 book.

Most Up / Most Down (MUD) trades enter at the next open after the signal close
and, with rebalance 1, exit at the following session's open. This script splits
that hold into the open gap (known at the fill), the entry-day session, and the
overnight into the exit open. It also counts how many unfiltered top-decile
winners the average-minimum filter drops, and scores one precommitted at-the-open
rule. Out-of-sample numbers are report-only.
"""
from __future__ import annotations

import html as html_mod
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

import duckdb
import numpy as np
import pandas as pd

_REPO = Path(__file__).resolve().parents[1]
_PE = _REPO / "drive" / "paul_experiments"
for _p in (_PE, _REPO / "tools", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from compare_format import ann_ror_from_closed  # noqa: E402
from report_page_extras import (  # noqa: E402
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

STAMP = _PE / "mud_tail_price_path_20261007"
FILTER_DIR = _PE / "mud_avg_min_filter_ab_20261005"
LONGS_CSV = FILTER_DIR / "MUD_Closed_longs_avgmin_261005223347.csv"
SHORTS_CSV = FILTER_DIR / "MUD_Closed_shorts_avgmin_261005223347.csv"
FULL_CSV = _REPO / "drive" / "MUD_LatestRun_Closed.csv"
DB = _REPO / "data" / "ohlcv.duckdb"
IS_CUT = pd.Timestamp("2024-01-01")

ASK = (
    "i liked the numbers in MUD, but it looks like without the top 10%, it is a "
    "losing system. Can you help identify what happens in the stock price of those "
    "10% of the top winners, that might lead us to a solid filter? "
    "you may want to also try this after taking off the filters. i bet there are "
    "even more big winners in those that are currently being filtered out"
)
PLAIN = (
    "Most Up / Most Down (MUD) buys the names that just fell the hardest and shorts "
    "the names that just rose the hardest, then gets out at the next morning's open. "
    "The strong annualized rate of return (Ann ROR) on the filtered book disappears "
    "if you delete the best 10% of trades, so those winners are the whole edge. "
    "This page splits each winner's move into three pieces: the gap from the signal "
    "close to the entry open (you can see this before you are filled), the rest of "
    "the entry day, and the jump from that day's close to the next open (you cannot "
    "know this when you enter). It also checks the full book with the average-minimum "
    "filters turned off, to see whether those filters throw away the same kind of winner."
)

USECOLS = [
    "SYMBOL",
    "SIDE",
    "DATE_OPENED",
    "DATE_CLOSED",
    "SIGNAL_DATE",
    "ENTRY_PRICE",
    "EXIT_PRICE",
    "PNL_PCT",
    "PNL_DOLLARS",
    "SHARES",
    "ENTRY_NOTIONAL",
    "DAYS_HELD",
    "LOOKBACK_RETURN_PCT",
    "ATR_PCT_AT_TRIGGER",
    "RSI14_AT_TRIGGER",
    "REL_VOL_AT_TRIGGER",
    "DIST_TO_52W_HIGH_PCT_AT_TRIGGER",
]


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def _fmt(v: Any, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return ""
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    try:
        x = float(v)
    except (TypeError, ValueError):
        return html_mod.escape(str(v))
    if not math.isfinite(x):
        return ""
    return f"{x:,.{nd}f}"


def _load_closed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=USECOLS, low_memory=False)
    df["SYMBOL"] = df["SYMBOL"].astype(str).str.upper()
    df["SIDE"] = df["SIDE"].astype(str).str.lower()
    for c in (
        "DATE_OPENED",
        "DATE_CLOSED",
        "SIGNAL_DATE",
    ):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in USECOLS:
        if c in ("SYMBOL", "SIDE", "DATE_OPENED", "DATE_CLOSED", "SIGNAL_DATE"):
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["SYMBOL", "SIDE", "DATE_OPENED", "SIGNAL_DATE", "PNL_PCT"])
    df["key"] = (
        df["SYMBOL"]
        + "|"
        + df["SIDE"]
        + "|"
        + df["DATE_OPENED"].dt.strftime("%Y-%m-%d")
        + "|"
        + df["SIGNAL_DATE"].dt.strftime("%Y-%m-%d")
    )
    df["slice"] = np.where(df["DATE_OPENED"] < IS_CUT, "IS", "OOS")
    return df


def _mark_top(df: pd.DataFrame, by: list[str], col: str) -> pd.Series:
    thr = df.groupby(by)["PNL_PCT"].transform(lambda s: s.quantile(0.9))
    return df["PNL_PCT"] >= thr


def _fetch_prices(need: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    con.register("need", need)
    px = con.execute(
        """
        SELECT upper(p.symbol) AS symbol,
               CAST(p.date AS DATE) AS d,
               p.open AS o,
               p.high AS h,
               p.low AS l,
               p.close AS c
        FROM prices p
        SEMI JOIN need n
          ON upper(p.symbol) = n.symbol
         AND CAST(p.date AS DATE) = n.d
        """
    ).fetchdf()
    con.close()
    px["symbol"] = px["symbol"].astype(str)
    px["d"] = pd.to_datetime(px["d"])
    return px.drop_duplicates(["symbol", "d"])


def _attach_path(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for role, col in (
        ("sig", "SIGNAL_DATE"),
        ("ent", "DATE_OPENED"),
        ("ex", "DATE_CLOSED"),
    ):
        t = df[["SYMBOL", col]].dropna().copy()
        t["d"] = t[col].dt.normalize()
        t = t.rename(columns={"SYMBOL": "symbol"})[["symbol", "d"]]
        parts.append(t)
    need = pd.concat(parts, ignore_index=True).drop_duplicates()
    print(f"price keys {len(need):,}", flush=True)
    px = _fetch_prices(need)
    print(f"price rows {len(px):,}", flush=True)
    sig = px.rename(columns={"o": "sig_o", "h": "sig_h", "l": "sig_l", "c": "sig_c"})
    ent = px.rename(columns={"o": "ent_o", "h": "ent_h", "l": "ent_l", "c": "ent_c"})
    ex = px.rename(columns={"c": "ex_c", "o": "ex_o"})[["symbol", "d", "ex_o"]]
    out = df.copy()
    out["_sig"] = out["SIGNAL_DATE"].dt.normalize()
    out["_ent"] = out["DATE_OPENED"].dt.normalize()
    out["_ex"] = out["DATE_CLOSED"].dt.normalize()
    out = out.merge(sig, left_on=["SYMBOL", "_sig"], right_on=["symbol", "d"], how="left")
    out = out.drop(columns=["symbol", "d"])
    out = out.merge(ent, left_on=["SYMBOL", "_ent"], right_on=["symbol", "d"], how="left")
    out = out.drop(columns=["symbol", "d"])
    out = out.merge(ex, left_on=["SYMBOL", "_ex"], right_on=["symbol", "d"], how="left")
    out = out.drop(columns=["symbol", "d", "_sig", "_ent", "_ex"])
    entry = out["ENTRY_PRICE"].to_numpy(dtype=float)
    exit_ = out["EXIT_PRICE"].to_numpy(dtype=float)
    sig_c = out["sig_c"].to_numpy(dtype=float)
    sig_o = out["sig_o"].to_numpy(dtype=float)
    ent_c = out["ent_c"].to_numpy(dtype=float)
    ent_h = out["ent_h"].to_numpy(dtype=float)
    ent_l = out["ent_l"].to_numpy(dtype=float)
    sh = out["SHARES"].to_numpy(dtype=float)
    side_long = (out["SIDE"] == "long").to_numpy()
    ok = (
        np.isfinite(entry)
        & (entry > 0)
        & np.isfinite(exit_)
        & (exit_ > 0)
        & np.isfinite(sig_c)
        & (sig_c > 0)
        & np.isfinite(ent_c)
        & (ent_c > 0)
        & np.isfinite(sh)
        & (sh > 0)
    )
    gap_in = np.full(len(out), np.nan)
    intra = np.full(len(out), np.nan)
    gap_out = np.full(len(out), np.nan)
    sig_day = np.full(len(out), np.nan)
    loc = np.full(len(out), np.nan)
    gap_in[ok] = (entry[ok] / sig_c[ok] - 1.0) * 100.0
    intra[ok] = (ent_c[ok] / entry[ok] - 1.0) * 100.0
    gap_out[ok] = (exit_[ok] / ent_c[ok] - 1.0) * 100.0
    sig_ok = ok & np.isfinite(sig_o) & (sig_o > 0)
    sig_day[sig_ok] = (sig_c[sig_ok] / sig_o[sig_ok] - 1.0) * 100.0
    rng = ent_h - ent_l
    loc_ok = ok & np.isfinite(ent_h) & np.isfinite(ent_l) & (rng > 0)
    # 1 = closed at the high (long-friendly), 0 = closed at the low.
    loc[loc_ok] = (ent_c[loc_ok] - ent_l[loc_ok]) / rng[loc_ok]
    intra_d = np.full(len(out), np.nan)
    out_d = np.full(len(out), np.nan)
    intra_d[ok & side_long] = sh[ok & side_long] * (ent_c[ok & side_long] - entry[ok & side_long])
    out_d[ok & side_long] = sh[ok & side_long] * (exit_[ok & side_long] - ent_c[ok & side_long])
    intra_d[ok & ~side_long] = sh[ok & ~side_long] * (entry[ok & ~side_long] - ent_c[ok & ~side_long])
    out_d[ok & ~side_long] = sh[ok & ~side_long] * (ent_c[ok & ~side_long] - exit_[ok & ~side_long])
    # Favorable price change: up for longs, down for shorts.
    fav_gap = np.where(side_long, gap_in, -gap_in)
    fav_intra = np.where(side_long, intra, -intra)
    fav_out = np.where(side_long, gap_out, -gap_out)
    # Already reversed at the open: long opens above the signal close, short opens below.
    already = np.where(side_long, gap_in > 0, gap_in < 0)
    already = np.where(ok, already, np.nan)
    out["path_ok"] = ok
    out["gap_in_pct"] = gap_in
    out["intra_pct"] = intra
    out["gap_out_pct"] = gap_out
    out["fav_gap_pct"] = fav_gap
    out["fav_intra_pct"] = fav_intra
    out["fav_out_pct"] = fav_out
    out["sig_day_pct"] = sig_day
    out["close_loc"] = loc
    out["intra_d"] = intra_d
    out["out_d"] = out_d
    out["already_reversed"] = already
    # Open has not already moved in the reversal direction (flat counts as not reversed).
    out["keep_open_rule"] = np.where(ok, ~already.astype(bool), False)
    out.loc[~ok, "keep_open_rule"] = False
    return out


def _med(s: pd.Series) -> float:
    s = pd.to_numeric(s, errors="coerce")
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return float("nan")
    return float(s.median())


def _path_row(label: str, book: str, side: str, cohort: str, sl: str, g: pd.DataFrame) -> dict[str, Any]:
    ok = g[g["path_ok"]]
    intra_d = float(ok["intra_d"].sum()) if len(ok) else 0.0
    out_d = float(ok["out_d"].sum()) if len(ok) else 0.0
    both = intra_d + out_d
    bigger_out = (ok["fav_out_pct"].abs() > ok["fav_intra_pct"].abs()) if len(ok) else pd.Series(dtype=bool)
    return {
        "label": label,
        "book": book,
        "side": side,
        "cohort": cohort,
        "slice": sl,
        "n": int(len(g)),
        "n_path": int(len(ok)),
        "med_gap_in": _med(ok["gap_in_pct"]),
        "med_intra": _med(ok["intra_pct"]),
        "med_gap_out": _med(ok["gap_out_pct"]),
        "med_fav_gap": _med(ok["fav_gap_pct"]),
        "med_fav_intra": _med(ok["fav_intra_pct"]),
        "med_fav_out": _med(ok["fav_out_pct"]),
        "med_sig_day": _med(ok["sig_day_pct"]),
        "med_close_loc": _med(ok["close_loc"]),
        "med_lb": _med(g["LOOKBACK_RETURN_PCT"]),
        "med_rsi": _med(g["RSI14_AT_TRIGGER"]),
        "med_atr": _med(g["ATR_PCT_AT_TRIGGER"]),
        "med_relvol": _med(g["REL_VOL_AT_TRIGGER"]),
        "med_dist52": _med(g["DIST_TO_52W_HIGH_PCT_AT_TRIGGER"]),
        "pct_already": float(np.nanmean(ok["already_reversed"])) * 100.0 if len(ok) else float("nan"),
        "pct_out_bigger": float(bigger_out.mean()) * 100.0 if len(ok) else float("nan"),
        "sum_intra_d": intra_d,
        "sum_out_d": out_d,
        "out_share_d": (out_d / both * 100.0) if both else float("nan"),
        "sum_pnl_d": float(pd.to_numeric(g["PNL_DOLLARS"], errors="coerce").sum()),
    }


def _ann(df: pd.DataFrame) -> Optional[float]:
    if len(df) == 0:
        return None
    pnl = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    days = pd.to_numeric(df["DAYS_HELD"], errors="coerce")
    cash = pd.to_numeric(df["ENTRY_NOTIONAL"], errors="coerce")
    days_ok = days[days > 0]
    cash_m = float(cash.mean()) if cash.notna().any() else 0.0
    avg_days = float(days_ok.mean()) if len(days_ok) else 0.0
    return ann_ror_from_closed(
        total_pnl=float(pnl.sum()),
        n_trades=int(len(df)),
        avg_days_held=avg_days,
        brt_cash=cash_m,
    )


def _book_metrics(name: str, df: pd.DataFrame) -> dict[str, Any]:
    pnl = pd.to_numeric(df["PNL_PCT"], errors="coerce")
    dol = pd.to_numeric(df["PNL_DOLLARS"], errors="coerce")
    wins = dol[dol > 0]
    losses = dol[dol < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and abs(float(losses.sum())) > 0 else float("nan")
    is_df = df[df["slice"] == "IS"]
    oos_df = df[df["slice"] == "OOS"]
    return {
        "name": name,
        "n": int(len(df)),
        "win_pct": float((pnl > 0).mean() * 100.0) if len(df) else float("nan"),
        "avg_pct": float(pnl.mean()) if len(df) else float("nan"),
        "med_pct": float(pnl.median()) if len(df) else float("nan"),
        "pf": pf,
        "ann": _ann(df),
        "ann_is": _ann(is_df),
        "ann_oos": _ann(oos_df),
        "n_is": int(len(is_df)),
        "n_oos": int(len(oos_df)),
    }


def _rows_html(rows: list[dict[str, Any]], cols: list[tuple[str, str, int]]) -> str:
    th = "".join(_th(lab, typ) for lab, key, typ, _nd in [(c[0], c[1], "text" if c[1] in ("label", "book", "side", "cohort", "slice", "name") else "num", 0) for c in cols])
    # rebuild properly
    th = ""
    for lab, key, nd in cols:
        typ = "text" if key in ("label", "book", "side", "cohort", "slice", "name") else "num"
        th += _th(lab, typ)
    body = []
    for r in rows:
        tds = []
        for lab, key, nd in cols:
            v = r.get(key)
            if key in ("label", "book", "side", "cohort", "slice", "name"):
                tds.append(f"<td>{html_mod.escape(str(v))}</td>")
            elif key == "n" or key.endswith("_n") or key in ("n_path", "n_is", "n_oos"):
                tds.append(f"<td>{_fmt(v, 0)}</td>")
            else:
                tds.append(f"<td>{_fmt(v, nd)}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (
        '<div class="table-wrap"><table class="sortable"><thead><tr>'
        + th
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def main() -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    print("loading filtered", flush=True)
    filt = pd.concat([_load_closed(LONGS_CSV), _load_closed(SHORTS_CSV)], ignore_index=True)
    filt["in_filter"] = True
    print(f"filtered {len(filt):,}", flush=True)
    print("loading full L5_R1", flush=True)
    full = _load_closed(FULL_CSV)
    print(f"full {len(full):,}", flush=True)
    filt_keys = set(filt["key"])
    full["in_filter"] = full["key"].isin(filt_keys)
    full["top10"] = _mark_top(full, ["SIDE"], "top10")
    filt["top10"] = _mark_top(filt, ["SIDE"], "top10")
    full["top10_slice"] = _mark_top(full, ["SIDE", "slice"], "top10_slice")
    filt["top10_slice"] = _mark_top(filt, ["SIDE", "slice"], "top10_slice")

    print("joining prices", flush=True)
    full = _attach_path(full)
    # Filtered path from the same join keys already on full, via key.
    path_cols = [
        "key",
        "path_ok",
        "gap_in_pct",
        "intra_pct",
        "gap_out_pct",
        "fav_gap_pct",
        "fav_intra_pct",
        "fav_out_pct",
        "sig_day_pct",
        "close_loc",
        "intra_d",
        "out_d",
        "already_reversed",
        "keep_open_rule",
    ]
    filt = filt.drop(columns=[c for c in path_cols if c in filt.columns and c != "key"], errors="ignore")
    filt = filt.merge(full[path_cols].drop_duplicates("key"), on="key", how="left")
    print(
        f"path coverage full {full['path_ok'].mean()*100:.1f}%  "
        f"filtered matched {filt['path_ok'].notna().mean()*100:.1f}%",
        flush=True,
    )

    path_rows: list[dict[str, Any]] = []
    for book, df in (("unfiltered", full), ("filtered", filt)):
        for side in ("long", "short"):
            sub = df[df["SIDE"] == side]
            for sl in ("FULL", "IS", "OOS"):
                g = sub if sl == "FULL" else sub[sub["slice"] == sl]
                # Slice-local top decile for IS/OOS discovery; full-book decile on FULL.
                flag = "top10" if sl == "FULL" else "top10_slice"
                for cohort, mask in (
                    ("top 10%", g[flag] == True),  # noqa: E712
                    ("other 90%", g[flag] == False),  # noqa: E712
                ):
                    path_rows.append(
                        _path_row(f"{book} {side} {sl} {cohort}", book, side, cohort, sl, g[mask])
                    )

    # Unfiltered top decile (full-book definition) kept vs dropped by the avg-min filter.
    drop_rows: list[dict[str, Any]] = []
    for side in ("long", "short"):
        sub = full[(full["SIDE"] == side) & (full["top10"] == True)]  # noqa: E712
        for cohort, mask in (
            ("top 10% kept by filter", sub["in_filter"] == True),  # noqa: E712
            ("top 10% dropped by filter", sub["in_filter"] == False),  # noqa: E712
        ):
            drop_rows.append(_path_row(f"{side} {cohort}", "unfiltered", side, cohort, "FULL", sub[mask]))
        rest = full[(full["SIDE"] == side) & (full["top10"] == False)]  # noqa: E712
        drop_rows.append(_path_row(f"{side} other 90%", "unfiltered", side, "other 90%", "FULL", rest))

    # Open rule: skip if the open has already reversed vs the signal close.
    rule_rows = [
        _book_metrics("unfiltered control", full),
        _book_metrics("unfiltered open-not-already-reversed", full[full["keep_open_rule"] == True]),  # noqa: E712
        _book_metrics("filtered control", filt),
        _book_metrics("filtered open-not-already-reversed", filt[filt["keep_open_rule"] == True]),  # noqa: E712
    ]
    for side in ("long", "short"):
        rule_rows.append(_book_metrics(f"unfiltered {side} control", full[full["SIDE"] == side]))
        rule_rows.append(
            _book_metrics(
                f"unfiltered {side} open rule",
                full[(full["SIDE"] == side) & (full["keep_open_rule"] == True)],  # noqa: E712
            )
        )

    path_df = pd.DataFrame(path_rows)
    drop_df = pd.DataFrame(drop_rows)
    rule_df = pd.DataFrame(rule_rows)
    path_df.to_csv(STAMP / "path_stats.csv", index=False)
    drop_df.to_csv(STAMP / "filter_drop_top10.csv", index=False)
    rule_df.to_csv(STAMP / "open_rule_scores.csv", index=False)

    def pick(book: str, side: str, cohort: str, sl: str) -> dict[str, Any]:
        m = path_df[
            (path_df["book"] == book)
            & (path_df["side"] == side)
            & (path_df["cohort"] == cohort)
            & (path_df["slice"] == sl)
        ]
        return m.iloc[0].to_dict() if len(m) else {}

    def drop_pick(side: str, cohort: str) -> dict[str, Any]:
        m = drop_df[(drop_df["side"] == side) & (drop_df["cohort"] == cohort)]
        return m.iloc[0].to_dict() if len(m) else {}

    # Narrative numbers from IS discovery, OOS as confirmation.
    bits = []
    for side, bounce in (("long", "up"), ("short", "down")):
        top = pick("unfiltered", side, "top 10%", "IS")
        oth = pick("unfiltered", side, "other 90%", "IS")
        topo = pick("unfiltered", side, "top 10%", "OOS")
        bits.append(
            f"Unfiltered {side}s, in-sample: the top 10% median favorable move is "
            f"{top.get('med_fav_intra', float('nan')):.2f} points during the entry day and "
            f"{top.get('med_fav_out', float('nan')):.2f} points on the next-morning gap "
            f"({top.get('out_share_d', float('nan')):.0f}% of that group's dollars are the overnight). "
            f"The other 90% are {oth.get('med_fav_intra', float('nan')):.2f} and "
            f"{oth.get('med_fav_out', float('nan')):.2f}. "
            f"Share of top-decile trades whose open had already reversed {bounce}: "
            f"{top.get('pct_already', float('nan')):.0f}% vs {oth.get('pct_already', float('nan')):.0f}% "
            f"in the rest. Out-of-sample top decile (report-only) is "
            f"{topo.get('med_fav_intra', float('nan')):.2f} intraday and "
            f"{topo.get('med_fav_out', float('nan')):.2f} overnight, "
            f"already-reversed {topo.get('pct_already', float('nan')):.0f}%."
        )

    drop_bits = []
    for side in ("long", "short"):
        kept = drop_pick(side, "top 10% kept by filter")
        dropped = drop_pick(side, "top 10% dropped by filter")
        n_top = kept.get("n", 0) + dropped.get("n", 0)
        drop_bits.append(
            f"{side}: unfiltered top decile N={n_top:,}. Filter keeps {kept.get('n', 0):,} "
            f"(${kept.get('sum_pnl_d', 0):,.0f}) and drops {dropped.get('n', 0):,} "
            f"(${dropped.get('sum_pnl_d', 0):,.0f}). "
            f"Dropped winners' median favorable intraday / overnight: "
            f"{dropped.get('med_fav_intra', float('nan')):.2f} / {dropped.get('med_fav_out', float('nan')):.2f}. "
            f"Kept winners: {kept.get('med_fav_intra', float('nan')):.2f} / {kept.get('med_fav_out', float('nan')):.2f}."
        )

    story = " ".join(bits)
    drop_story = " ".join(drop_bits)

    path_cols_h = [
        ("Book", "book", 0),
        ("Side", "side", 0),
        ("Slice", "slice", 0),
        ("Cohort", "cohort", 0),
        ("N", "n", 0),
        ("Med gap into open %", "med_gap_in", 2),
        ("Med entry-day %", "med_intra", 2),
        ("Med next-open %", "med_gap_out", 2),
        ("Med favorable gap %", "med_fav_gap", 2),
        ("Med favorable entry-day %", "med_fav_intra", 2),
        ("Med favorable overnight %", "med_fav_out", 2),
        ("Overnight $ share %", "out_share_d", 1),
        ("Bigger leg is overnight %", "pct_out_bigger", 1),
        ("Open already reversed %", "pct_already", 1),
        ("Med signal-day %", "med_sig_day", 2),
        ("Med close location", "med_close_loc", 2),
        ("Med RSI at signal", "med_rsi", 1),
        ("Med ATR % at signal", "med_atr", 2),
        ("Med rel volume", "med_relvol", 2),
        ("Med dist to 52w high %", "med_dist52", 1),
        ("Med lookback return %", "med_lb", 2),
    ]
    drop_cols_h = [
        ("Side", "side", 0),
        ("Cohort", "cohort", 0),
        ("N", "n", 0),
        ("Sum PnL $", "sum_pnl_d", 0),
        ("Med favorable entry-day %", "med_fav_intra", 2),
        ("Med favorable overnight %", "med_fav_out", 2),
        ("Overnight $ share %", "out_share_d", 1),
        ("Open already reversed %", "pct_already", 1),
        ("Med signal-day %", "med_sig_day", 2),
        ("Med RSI at signal", "med_rsi", 1),
        ("Med ATR % at signal", "med_atr", 2),
        ("Med lookback return %", "med_lb", 2),
    ]
    rule_cols_h = [
        ("Arm", "name", 0),
        ("N", "n", 0),
        ("N IS", "n_is", 0),
        ("N OOS", "n_oos", 0),
        ("Win %", "win_pct", 1),
        ("Avg PnL %", "avg_pct", 3),
        ("Median PnL %", "med_pct", 3),
        ("Profit factor", "pf", 2),
        ("Ann ROR %", "ann", 2),
        ("Ann ROR IS %", "ann_is", 2),
        ("Ann ROR OOS %", "ann_oos", 2),
    ]

    # Examples: largest unfiltered winners by pnl % with path, flag filter.
    examples = []
    for side in ("long", "short"):
        sub = full[(full["SIDE"] == side) & (full["path_ok"])].nlargest(8, "PNL_PCT")
        for _, r in sub.iterrows():
            examples.append(
                {
                    "side": side,
                    "symbol": r["SYMBOL"],
                    "opened": str(r["DATE_OPENED"].date()),
                    "pnl_pct": r["PNL_PCT"],
                    "pnl_d": r["PNL_DOLLARS"],
                    "gap_in": r["gap_in_pct"],
                    "intra": r["intra_pct"],
                    "gap_out": r["gap_out_pct"],
                    "in_filter": "yes" if r["in_filter"] else "no",
                    "slice": r["slice"],
                }
            )
    pd.DataFrame(examples).to_csv(STAMP / "example_winners.csv", index=False)
    ex_cols = [
        ("Side", "side", 0),
        ("Symbol", "symbol", 0),
        ("Opened", "opened", 0),
        ("Slice", "slice", 0),
        ("In avg-min filter", "in_filter", 0),
        ("PnL %", "pnl_pct", 1),
        ("PnL $", "pnl_d", 0),
        ("Gap into open %", "gap_in", 2),
        ("Entry day %", "intra", 2),
        ("Next open %", "gap_out", 2),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>MUD top-winner price path</title>
<style>
body {{ font-family: Georgia, serif; margin: 24px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.6rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f4f1ea; border-left: 4px solid #8a6a3b; padding: 12px 14px; margin: 12px 0 18px; }}
.note {{ color: #444; font-size: 0.95rem; }}
code {{ font-family: Consolas, monospace; font-size: 0.9em; }}
{SORTABLE_TH_CSS}
</style>
</head><body>
<h1>MUD top 10% price path</h1>
<p class="note">Most Up / Most Down (MUD), lookback 5 trading days, rebalance every 1 trading day. Research only. Not gold. Not DailyRun.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html_mod.escape(ASK)}</p>
<h2>In plain English</h2>
<p>{html_mod.escape(PLAIN)}</p>
</div>
{SWIPE_NOTE_HTML}
<p class="note">Click column headers to sort. In-sample (IS) is entry before 2024-01-01. Out-of-sample (OOS) is entry on or after that date and is report-only. Annualized rate of return (Ann ROR) uses the house formula with slot cash equal to the average entry notional of that arm. Favorable means up for longs and down for shorts. The top 10% is the sleeve's 90th percentile of percent PnL. On the FULL rows that cut is the whole sleeve; on IS and OOS rows the cut is inside that slice, so the path check is not borrowed from the other period.</p>

<h2>What the winning prices actually do</h2>
<p>{html_mod.escape(story)}</p>
<p>A move after the fill explains the tail. It is not, by itself, an entry filter. The only piece you can see before the fill is the gap from the signal close to the entry open, plus anything on the signal bar (that day's open-to-close, Relative Strength Index (RSI), Average True Range (ATR) percent, relative volume, distance to the 52-week high, and the 5-day lookback return).</p>
{_rows_html(path_rows, path_cols_h)}

<h2>Does the average-minimum filter throw away big winners?</h2>
<p>Yes if the dropped top-decile count and dollars are large. These rows use the unfiltered book's own top 10% (one cut per side on the full history). {html_mod.escape(drop_story)}</p>
<p class="note">The average-minimum filter was chosen after looking at correlations on this same history, so this comparison is in-sample selection. It is not a new promotion test.</p>
{_rows_html(drop_rows, drop_cols_h)}

<h2>One at-the-open rule (exploratory)</h2>
<p>Precommitted rule, not a searched threshold: skip a long if the entry open is already above the signal close, and skip a short if the entry open is already below the signal close. A flat open is kept. If the top decile is mostly names that had already reversed at the open, this rule cuts the tail and should not be used. OOS is report-only. Do not retune the rule from OOS. Not gold. Not DailyRun.</p>
{_rows_html(rule_rows, rule_cols_h)}

<h2>Largest percent winners (unfiltered)</h2>
<p class="note">Eight largest percent winners per side. "In avg-min filter = no" means the current filter would have skipped that trade.</p>
{_rows_html(examples, ex_cols)}

<h2>Freeze</h2>
<ul>
<li>Control book: L5_R1 Closed at <code>drive/MUD_LatestRun_Closed.csv</code>. Signal close, enter next open, exit next session open. No stop and no target.</li>
<li>Filtered book: average-minimum AND gates from <code>mud_avg_min_filter_ab_20261005</code> (longs and shorts files dated 261005223347).</li>
<li>Path prices: <code>data/ohlcv.duckdb</code> table <code>prices</code>. Entry and exit fills stay the Closed prices. Entry-day high and low are used only for close location. Exit-day high and low are not used.</li>
<li>Open rule was fixed before reading OOS scores. No second threshold was chosen.</li>
</ul>
<script>
{SORTABLE_TABLE_SCRIPT}
</script>
</body></html>
"""
    html_path = STAMP / "compare.html"
    html_path.write_text(html, encoding="utf-8")

    base = f"""# MUD top-winner price path

Research only. Not gold. Not DailyRun.

## What you asked

{ASK}

## In plain English

{PLAIN}

## Path (IS discovery)

{story}

## Filter vs unfiltered top decile

{drop_story}

## Open rule

Skip longs that open above the signal close and shorts that open below it.
Scores are in `open_rule_scores.csv`. OOS is report-only. Exploratory, in-sample
mechanism look. Not gold. Not DailyRun.

## Files

- `compare.html`
- `path_stats.csv`
- `filter_drop_top10.csv`
- `open_rule_scores.csv`
- `example_winners.csv`
"""
    (STAMP / "BASELINE.md").write_text(base, encoding="utf-8")
    print(f"wrote {html_path}", flush=True)
    print(rule_df.to_string(index=False), flush=True)
    print(drop_df[["side", "cohort", "n", "sum_pnl_d", "med_fav_intra", "med_fav_out", "pct_already"]].to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
