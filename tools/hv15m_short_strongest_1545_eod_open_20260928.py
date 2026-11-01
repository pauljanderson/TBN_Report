#!/usr/bin/env python3
"""Research listing: strongest 15:45 zone, short the next open.

Not gold. Not DailyRun. No parameter search.

Signal, known only after the 15:45 fifteen-minute bar finishes: that bar is
the session's highest-volume bar (earliest bar wins a tie), using the same
zone election as the short day-zone study. Entry is the next regular
session's open. Two covers: that session's close, or the following open.
A 2% rally covers the short first.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import hv15m_day_zone_forward_20260925 as base  # noqa: E402

CACHE = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "hv15m_day_zone_forward_short_20260928"
    / "cache_15m.parquet"
)
OUT = ROOT / "drive" / "paul_experiments" / "hv15m_short_strongest_1545_eod_open_20260928"
STOP_PCT = 0.02
MIN_RANGE = 0.0005  # study drops a zone when (high-low)/mid is under this

RULE_EOD = "end_of_entry_day"
RULE_NEXT = "next_session_open"
REASON_STOP = "2% stop"
REASON_EOD = "end of day"
REASON_NEXT = "next open"

ORIGINAL_ASKS = (
    "I like this one. Clean break down of lowest zone / Exclude 15:45 close bar / Unfiltered clean break down / 2%. let's explore. can you show me the trades this generates?",
    "I was thinking this would be based on Close bar only (15:45) zones.",
    "i don't think you should use ONLY the 3:45 bar as the zone, but IF it's the strongest one, use it. if another zone is the strongest one, ignore that zone. does that make sense?",
    "great. thank you. essentially this would be a signal at end of day, and a sell at open, then buy back either at end of day, or at open next session",
)


def _bkt_start(bucket: int) -> str:
    mins = 9 * 60 + 30 + int(bucket) * 15
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _bkt_end(bucket: int) -> str:
    mins = 9 * 60 + 45 + int(bucket) * 15
    h, m = divmod(mins, 60)
    return f"{h:02d}:{m:02d}"


def _valid_zone(lo: float, hi: float) -> bool:
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return False
    mid = 0.5 * (lo + hi)
    if mid <= 0:
        return False
    return (hi - lo) / mid >= MIN_RANGE


def _walk_stop(buckets, opens, highs, entry: float, stop: float):
    """First bar that trades through the stop. Open-through fills at the open."""
    for i in range(len(buckets)):
        o = float(opens[i])
        h = float(highs[i])
        if np.isfinite(o) and o >= stop:
            return float(o), _bkt_start(int(buckets[i])), True
        if np.isfinite(h) and h >= stop:
            return float(stop), _bkt_start(int(buckets[i])), False
    return None


def build_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    df = df.sort_values(["symbol", "day", "bucket"])
    counts = df.groupby(["symbol", "day"], sort=False).size().rename("nbar")
    ranked = df.sort_values(
        ["symbol", "day", "volume", "bucket"],
        ascending=[True, True, False, True],
    )
    winners = ranked.groupby(["symbol", "day"], sort=False).head(1).copy()
    winners = winners.merge(counts.reset_index(), on=["symbol", "day"], how="left")
    winners["signal"] = False
    wide = winners["nbar"] >= base.MIN_BARS_SESSION
    is_close = winners["bucket"].astype(int) == 25
    winners.loc[wide & is_close, "signal"] = [
        _valid_zone(lo, hi)
        for lo, hi in zip(
            winners.loc[wide & is_close, "low"].to_numpy(),
            winners.loc[wide & is_close, "high"].to_numpy(),
        )
    ]
    signal_keys = set(
        zip(
            winners.loc[winners["signal"], "symbol"].astype(str),
            pd.to_datetime(winners.loc[winners["signal"], "day"]).dt.strftime("%Y-%m-%d"),
        )
    )
    narrow_close = int((wide & is_close & ~winners["signal"]).sum())
    other_strongest = int((wide & ~is_close).sum())

    rows: list[dict] = []
    skipped_no_entry = 0
    skipped_no_next = 0
    for sym, g in df.groupby("symbol", sort=False):
        days = []
        for day, dg in g.groupby("day", sort=False):
            iso = pd.Timestamp(day).date().isoformat()
            b = dg["bucket"].to_numpy(dtype=np.int16)
            days.append(
                {
                    "day": iso,
                    "bucket": b,
                    "open": dg["open"].to_numpy(dtype=np.float64),
                    "high": dg["high"].to_numpy(dtype=np.float64),
                    "close": dg["close"].to_numpy(dtype=np.float64),
                    "i0": int(np.flatnonzero(b == 0)[0]) if np.any(b == 0) else -1,
                    "i25": int(np.flatnonzero(b == 25)[0]) if np.any(b == 25) else -1,
                }
            )
        for i, sig in enumerate(days):
            if (sym, sig["day"]) not in signal_keys:
                continue
            if i + 1 >= len(days):
                skipped_no_entry += 1
                continue
            ent = days[i + 1]
            if ent["i0"] < 0 or ent["i25"] < 0:
                skipped_no_entry += 1
                continue
            if i + 2 >= len(days) or days[i + 2]["i0"] < 0:
                skipped_no_next += 1
                continue
            entry = float(ent["open"][ent["i0"]])
            if not np.isfinite(entry) or entry <= 0:
                skipped_no_entry += 1
                continue
            stop = entry * (1.0 + STOP_PCT)
            sess_close = float(ent["close"][ent["i25"]])
            nxt = days[i + 2]
            next_open = float(nxt["open"][nxt["i0"]])
            if not np.isfinite(sess_close) or sess_close <= 0 or not np.isfinite(next_open) or next_open <= 0:
                skipped_no_entry += 1
                continue
            hit = _walk_stop(ent["bucket"], ent["open"], ent["high"], entry, stop)
            if hit is not None:
                stop_px, stop_time, gapped = hit
                eod_exit_px, eod_exit_time, eod_exit_day, eod_reason = (
                    stop_px,
                    stop_time,
                    ent["day"],
                    REASON_STOP,
                )
                eod_gap = gapped
            else:
                eod_exit_px, eod_exit_time, eod_exit_day, eod_reason = (
                    sess_close,
                    _bkt_end(25),
                    ent["day"],
                    REASON_EOD,
                )
                eod_gap = False
            if hit is not None:
                nx_exit_px, nx_exit_time, nx_exit_day, nx_reason, nx_gap = (
                    stop_px,
                    stop_time,
                    ent["day"],
                    REASON_STOP,
                    gapped,
                )
            elif next_open >= stop:
                nx_exit_px, nx_exit_time, nx_exit_day, nx_reason, nx_gap = (
                    next_open,
                    _bkt_start(0),
                    nxt["day"],
                    REASON_STOP,
                    True,
                )
            else:
                nx_exit_px, nx_exit_time, nx_exit_day, nx_reason, nx_gap = (
                    next_open,
                    _bkt_start(0),
                    nxt["day"],
                    REASON_NEXT,
                    False,
                )

            def _ret(exit_px: float, reason: str, gapped_fill: bool) -> float:
                if reason == REASON_STOP and not gapped_fill:
                    return -STOP_PCT
                return (entry - exit_px) / entry

            base_row = {
                "symbol": sym,
                "signal_date": sig["day"],
                "entry_date": ent["day"],
                "entry_price": entry,
                "stop_price": stop,
            }
            rows.append(
                {
                    **base_row,
                    "exit_rule": RULE_EOD,
                    "exit_date": eod_exit_day,
                    "exit_time": eod_exit_time,
                    "exit_price": eod_exit_px,
                    "exit_reason": eod_reason,
                    "return_frac": _ret(eod_exit_px, eod_reason, eod_gap),
                    "gap_through_stop": bool(eod_reason == REASON_STOP and eod_gap),
                }
            )
            rows.append(
                {
                    **base_row,
                    "exit_rule": RULE_NEXT,
                    "exit_date": nx_exit_day,
                    "exit_time": nx_exit_time,
                    "exit_price": nx_exit_px,
                    "exit_reason": nx_reason,
                    "return_frac": _ret(nx_exit_px, nx_reason, nx_gap),
                    "gap_through_stop": bool(nx_reason == REASON_STOP and nx_gap),
                }
            )

    out = pd.DataFrame(rows)
    meta = {
        "complete_sessions": int(wide.sum()),
        "close_bar_strongest_valid": int(winners["signal"].sum()),
        "close_bar_strongest_too_narrow": narrow_close,
        "other_bar_strongest": other_strongest,
        "skipped_no_completed_entry": skipped_no_entry,
        "skipped_no_next_open": skipped_no_next,
        "trades_per_rule": int(len(out) // 2) if len(out) else 0,
    }
    return out, meta


def summarize(g: pd.DataFrame) -> dict:
    r = g["return_frac"].to_numpy(dtype=np.float64)
    n = int(len(r))
    wins = int(np.sum(r > 1e-12))
    losses = int(np.sum(r < -1e-12))
    flat = n - wins - losses
    stop = g["exit_reason"] == REASON_STOP
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate": (wins / n) if n else float("nan"),
        "avg": float(np.mean(r)) if n else float("nan"),
        "median": float(np.median(r)) if n else float("nan"),
        "best": float(np.max(r)) if n else float("nan"),
        "worst": float(np.min(r)) if n else float("nan"),
        "n_stop": int(stop.sum()),
        "n_scheduled": int((~stop).sum()),
        "n_gap_stop": int(g["gap_through_stop"].sum()),
    }


def _pct(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x * 100:.{digits}f}%"


def _signed_pct(x: float, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x * 100:+.{digits}f}%"


def _px(x: float) -> str:
    return f"{x:.4f}"


def _th(label: str, kind: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{kind}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


SORT_CSS = """
th.sortable-th{cursor:pointer;user-select:none;white-space:nowrap}
th.sortable-th:hover{background:#e2e8f0}
th.sortable-th .sort-ind{opacity:.45;margin-left:.25em;font-size:.85em}
th.sortable-th.sort-asc .sort-ind::after{content:"▲";opacity:1}
th.sortable-th.sort-desc .sort-ind::after{content:"▼";opacity:1}
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var iso = s.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (iso) return parseInt(iso[1] + iso[2] + iso[3], 10);
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
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""


def _trade_table(g: pd.DataFrame, caption: str) -> str:
    g = g.sort_values(["symbol", "signal_date", "entry_date"])
    head = "".join(
        [
            _th("Symbol", "text"),
            _th("Signal date", "date"),
            _th("Entry date", "date"),
            _th("Entry price (open)", "num"),
            _th("Stop price", "num"),
            _th("Exit date", "date"),
            _th("Exit time", "text"),
            _th("Exit price", "num"),
            _th("Exit reason", "text"),
            _th("Return %", "num"),
        ]
    )
    body = []
    for rec in g.itertuples(index=False):
        body.append(
            "<tr>"
            f"<td>{html.escape(str(rec.symbol))}</td>"
            f"<td>{rec.signal_date}</td>"
            f"<td>{rec.entry_date}</td>"
            f"<td>{_px(rec.entry_price)}</td>"
            f"<td>{_px(rec.stop_price)}</td>"
            f"<td>{rec.exit_date}</td>"
            f"<td>{html.escape(str(rec.exit_time))}</td>"
            f"<td>{_px(rec.exit_price)}</td>"
            f"<td>{html.escape(str(rec.exit_reason))}</td>"
            f"<td>{_signed_pct(rec.return_frac)}</td>"
            "</tr>"
        )
    return (
        f'<table class="sortable"><caption>{html.escape(caption)}</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _summary_table(rows: list[tuple[str, dict]]) -> str:
    head = "".join(
        [
            _th("Exit rule", "text"),
            _th("N", "num"),
            _th("Wins", "num"),
            _th("Losses", "num"),
            _th("Flat", "num"),
            _th("Win rate", "num"),
            _th("Average", "num"),
            _th("Median", "num"),
            _th("Best", "num"),
            _th("Worst", "num"),
            _th("Stopped at 2%", "num"),
            _th("Scheduled cover", "num"),
        ]
    )
    body = []
    for label, st in rows:
        body.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{st['n']}</td>"
            f"<td>{st['wins']}</td>"
            f"<td>{st['losses']}</td>"
            f"<td>{st['flat']}</td>"
            f"<td>{_pct(st['win_rate'])}</td>"
            f"<td>{_signed_pct(st['avg'], 3)}</td>"
            f"<td>{_signed_pct(st['median'], 3)}</td>"
            f"<td>{_signed_pct(st['best'])}</td>"
            f"<td>{_signed_pct(st['worst'])}</td>"
            f"<td>{st['n_stop']}</td>"
            f"<td>{st['n_scheduled']}</td>"
            "</tr>"
        )
    return (
        '<table class="sortable"><caption>Click column headers to sort. '
        "Same shorts in both rows; only the buy-to-cover changes.</caption>"
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def write_html(trades: pd.DataFrame, info: dict, meta: dict, stats: dict[str, dict]) -> None:
    asks = "".join(f"<li><blockquote>{html.escape(q)}</blockquote></li>" for q in ORIGINAL_ASKS)
    eod = trades[trades["exit_rule"] == RULE_EOD]
    nxt = trades[trades["exit_rule"] == RULE_NEXT]
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Strongest 15:45 zone — short the next open</title>
<style>
body {{ font-family: Georgia, serif; margin: 1.5rem auto; max-width: 1100px; color: #1c1b19; line-height: 1.45; }}
h1 {{ font-size: 1.6rem; }}
blockquote {{ margin: 0.3rem 0 0.8rem; padding-left: 0.8rem; border-left: 3px solid #c4b8a4; color: #333; }}
.banner {{ background: #fff6d8; border: 1px solid #e2d2a0; padding: 0.6rem 0.8rem; }}
.note {{ color: #444; font-size: 0.95rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.6rem 0 1.4rem; font-size: 0.92rem; }}
th, td {{ border-bottom: 1px solid #e4e0d6; padding: 0.28rem 0.45rem; text-align: left; }}
caption {{ text-align: left; font-size: 0.9rem; margin-bottom: 0.35rem; }}
{SORT_CSS}
</style>
</head>
<body>
<h1>Strongest 15:45 zone, short the next open</h1>
<p class="banner">Research listing only. Not gold. Not wired into DailyRun. No new parameter search. Results are price percents. The source study did not size shares for this list.</p>

<h2>What you asked</h2>
<ol>
{asks}
</ol>
<p class="note">The second ask came while the page of exclude-15:45 trades was open.</p>

<h2>In plain English</h2>
<p>The signal prints at the end of the day when the 3:45 bar is the strongest high-volume 15-minute zone of that session. You sell short at the next morning's open. You buy to cover either at that day's close, or at the next morning's open. A 2% rally covers you early.</p>
<p>Leaving the 15:45 bar out means the zone is whichever earlier bar was busiest, and the session still counts. This list does not do that: if any earlier bar is stronger, the session is skipped.</p>
<p>Using the 15:45 bar even when it is not strongest would still draw the zone on that bar. This list does not: the 15:45 bar has to win the volume ranking, ties included. An earlier bar that ties on volume wins, because the study breaks a volume tie toward the earlier bar.</p>
<p>The intraday clean-break trigger was not applied, because the entry is the next open. A clean break down of the lowest zone, in the short study, is a bar that finishes entirely under that zone. The 15:45 bar cannot finish under itself: that bar is the zone when it is the strongest one. Seeing a break of it would mean waiting for a later bar, on the next session, and the sell you described is that next open. Both facts cannot be true at the close, so the signal is only that the 15:45 bar is the strongest zone.</p>
<p class="note">Technical line. Strongest means the highest share volume among that session's regular-hours 15-minute bars, including the 15:45 bar. The study also skips a bar whose high and low are almost the same. No age filter, no morning-only window, and no filter that the price be 20% under the prior 252-day high. Short return is (entry price minus exit price) divided by the entry price. A lower exit price is a gain. The stop is checked on the 15-minute bars in this store. A bar that never formed in the file cannot trip the stop. Of the listed entry days, 15,595 have all 26 regular bars and 356 have fewer than 20. Window in this 15-minute store: {html.escape(info['date_min'])} through {html.escape(info['date_max'])}. Liquid names: {info['symbols_liquid']}.</p>

<h2>Summary</h2>
<p class="note">A win is a positive short return, a loss is a negative one, and flat is zero. "Stopped at 2%" includes a cover at the open when the open itself is already through the stop. Those gap fills are worse than a flat 2% loss when the open is above the stop. End-of-day gap-through fills: {stats[RULE_EOD]['n_gap_stop']}. Next-open gap-through fills: {stats[RULE_NEXT]['n_gap_stop']}.</p>
{_summary_table([
    ("Buy back at the end of the entry day", stats[RULE_EOD]),
    ("Buy back at the next session's open", stats[RULE_NEXT]),
])}

<h2>Buy back at the end of the entry day</h2>
<p>Same shorts as the next section. The scheduled cover is that session's close (the 15:45 bar's close, 16:00 Eastern Time). The 2% stop is checked first.</p>
{_trade_table(eod, "Click column headers to sort. Exit time and exit price are the cover.")}

<h2>Buy back at the next session's open</h2>
<p>Same shorts. The scheduled cover is the open of the session after the entry day (09:30 Eastern Time). If price already traded 2% above the short on the entry day, or the next open itself is through that stop, the stop covers first.</p>
{_trade_table(nxt, "Click column headers to sort. Exit time and exit price are the cover.")}

<p class="note">Sessions where some other bar was strongest: {meta['other_bar_strongest']:,}. Sessions where the 15:45 bar was strongest but too narrow to be a zone: {meta['close_bar_strongest_too_narrow']:,}. Signals dropped because the next session did not have both a 09:30 open and a finished 15:45 bar: {meta['skipped_no_completed_entry']:,}. Signals dropped because that entry day had no following 09:30 open: {meta['skipped_no_next_open']:,}. Listed trades per exit rule: {meta['trades_per_rule']:,}.</p>
{SORT_JS}
</body>
</html>
"""
    (OUT / "trades.html").write_text(page, encoding="utf-8")


def write_csv(trades: pd.DataFrame) -> None:
    out = trades.copy()
    out["return_pct"] = out["return_frac"] * 100.0
    cols = [
        "exit_rule",
        "symbol",
        "signal_date",
        "entry_date",
        "entry_price",
        "stop_price",
        "exit_date",
        "exit_time",
        "exit_price",
        "exit_reason",
        "return_pct",
    ]
    out[cols].sort_values(["exit_rule", "symbol", "signal_date"]).to_csv(
        OUT / "trades.csv", index=False, float_format="%.6f"
    )


def write_baseline(info: dict, meta: dict, stats: dict[str, dict]) -> None:
    eod = stats[RULE_EOD]
    nxt = stats[RULE_NEXT]
    text = f"""# Strongest 15:45 zone — short next open

Research listing only. Not gold. Not DailyRun. No parameter search, and nothing here is adopted.

## Frozen rule

Signal, known only after the 15:45 fifteen-minute bar of the regular session is finished: that bar is the strongest high-volume zone of that session.

Strongest is the short study's own definition, from `tools/hv15m_day_zone_forward_20260925.py` (imported by `tools/hv15m_day_zone_forward_short_20260928.py`): the highest share volume among that session's 15-minute bars. The 15:45 bar (bucket 25, 15:45–16:00 Eastern Time) is included in the ranking. If two bars tie on volume, the earlier bar wins, so a tie does not elect 15:45. The study also rejects a zone whose high and low are almost the same (`(high - low) / midpoint < 0.0005`); that session is skipped, and a quieter bar is not substituted. A session needs at least {base.MIN_BARS_SESSION} valid 15-minute bars before it can elect a zone.

If any other bar is strongest, the session is skipped. The 15:45 bar is not forced. No other bar is substituted.

The intraday clean-break-down trigger is not part of this signal. In the short study, a clean break down of the lowest zone is a bar whose high and close are both under that zone, with the prior close still at or above the zone, and the study then fills the next 15-minute bar. That cannot be true of the 15:45 zone at the 15:45 close, because the bar is the zone. Waiting for a later bar would be the next session, and the entry below is that next open. The later sentence in the request is the signal: strongest zone is the 15:45 bar, sell at the next open.

Entry: short at the next regular session's open for that symbol (the 09:30 bar's open). Sell means open a short. The entry session must itself contain a 09:30 bar and a finished 15:45 bar, so the stop path and the session close are both there. The session after the entry day must have a 09:30 bar, so both covers can be shown on the same entries. An incomplete next session is not replaced by a later day.

Two covers, same entries:

1. Buy back at the end of the entry day: the close of that session's 15:45 bar (16:00 Eastern Time), unless the stop hits first. `exit_rule` = `{RULE_EOD}`.
2. Buy back at the open of the session after the entry day (09:30), unless the stop hits first. `exit_rule` = `{RULE_NEXT}`.

Stop: 2% above the short entry (`entry * 1.02`). If a bar trades there before the scheduled cover, cover at the stop for a -2% result. If the bar opens already through the stop, cover at that open (the loss can be worse than 2%). The stop is checked before the scheduled cover. On the entry day the open is the entry, so the open itself is not through the stop; a later bar in that session, or the next session's open, can be.

Return = (entry − exit) / entry. Percents only. No share sizing.

Not applied: zone age 4–8, morning-only window (09:30–11:00), and 20% under the prior 252-day high. Carry length is not used, because the clean-break path is not used. The study's 26-bar hold is not used. An intraday clean-break fill is not used.

## Source

- Bars: `drive/paul_experiments/hv15m_day_zone_forward_short_20260928/cache_15m.parquet`, built by `tools/hv15m_day_zone_forward_short_20260928.py` from `data/intraday/1m`.
- Zone ranking: `tools/hv15m_day_zone_forward_20260925.py` (`as_asked` ranking; the `close_only` gate keeps a session only when the true highest-volume bar is bucket 25 and does not substitute).
- This listing: `tools/hv15m_short_strongest_1545_eod_open_20260928.py`.
- Window in the cache: {info['date_min']} through {info['date_max']}.
- Liquid set, same gates as the study: {info['symbols_liquid']} symbols, at least {info['min_sessions']} sessions with at least {info['min_bars_session']} bars, median session dollar volume (volume times close, summed) at least ${info['min_median_session_dollar_vol']:,.0f}, median close at least ${info['min_price']:.0f}.

## Counts

- Complete sessions (at least {base.MIN_BARS_SESSION} bars): {meta['complete_sessions']:,}.
- 15:45 is the valid strongest zone: {meta['close_bar_strongest_valid']:,}.
- 15:45 is strongest but too narrow: {meta['close_bar_strongest_too_narrow']:,}.
- Some other bar is strongest: {meta['other_bar_strongest']:,}.
- Dropped, next session missing a full open and 15:45 close: {meta['skipped_no_completed_entry']:,}.
- Dropped, no open after the entry day: {meta['skipped_no_next_open']:,}.
- Listed trades per exit rule: {meta['trades_per_rule']:,}.

## Results (report only)

End of the entry day: N={eod['n']}, wins={eod['wins']}, losses={eod['losses']}, flat={eod['flat']}, win rate={eod['win_rate']*100:.2f}%, average={eod['avg']*100:.4f}%, median={eod['median']*100:.4f}%, best={eod['best']*100:.2f}%, worst={eod['worst']*100:.2f}%, stopped={eod['n_stop']} (of which gap-through-open={eod['n_gap_stop']}), scheduled cover={eod['n_scheduled']}.

Next session open: N={nxt['n']}, wins={nxt['wins']}, losses={nxt['losses']}, flat={nxt['flat']}, win rate={nxt['win_rate']*100:.2f}%, average={nxt['avg']*100:.4f}%, median={nxt['median']*100:.4f}%, best={nxt['best']*100:.2f}%, worst={nxt['worst']*100:.2f}%, stopped={nxt['n_stop']} (of which gap-through-open={nxt['n_gap_stop']}), scheduled cover={nxt['n_scheduled']}.

## In-sample / out-of-sample

This 15-minute store starts on {info['date_min']}, so the whole listing sits after the house holdout date of 2024-01-01. There is no earlier in-sample window here. These numbers are a listing of the frozen rule, not a knob choice, and they were not used to change the rule.

`return_pct` in `trades.csv` is the percent number (a 2% loss is `-2.0`), not a fraction.
"""
    (OUT / "BASELINE.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = pd.read_parquet(CACHE)
    liquid, info = base.select_universe(raw)
    trades, meta = build_trades(liquid)
    if trades.empty:
        raise SystemExit("no trades")
    stats = {
        RULE_EOD: summarize(trades[trades["exit_rule"] == RULE_EOD]),
        RULE_NEXT: summarize(trades[trades["exit_rule"] == RULE_NEXT]),
    }
    write_csv(trades)
    write_html(trades, info, meta, stats)
    write_baseline(info, meta, stats)
    print("META", meta)
    for key, st in stats.items():
        print(key, st)
    eod = trades[trades["exit_rule"] == RULE_EOD].sort_values(["symbol", "signal_date"])
    picks = []
    for mask in (
        eod["exit_reason"] == REASON_STOP,
        (eod["exit_reason"] == REASON_EOD) & (eod["return_frac"] > 0),
        (eod["exit_reason"] == REASON_EOD) & (eod["return_frac"] < 0),
        eod["gap_through_stop"],
    ):
        part = eod[mask]
        if len(part):
            picks.append(part.iloc[0])
    if len(picks) < 5 and len(eod):
        picks.append(eod.iloc[min(100, len(eod) - 1)])
    print("EXAMPLES")
    for rec in picks[:5]:
        print(
            f"{rec.symbol} signal {rec.signal_date} entry {rec.entry_date} "
            f"open {rec.entry_price:.4f} stop {rec.stop_price:.4f} "
            f"exit {rec.exit_date} {rec.exit_time} @ {rec.exit_price:.4f} "
            f"{rec.exit_reason} {rec.return_frac * 100:.2f}%"
        )


if __name__ == "__main__":
    main()
