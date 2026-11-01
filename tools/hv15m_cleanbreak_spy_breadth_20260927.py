#!/usr/bin/env python3
"""3% stop on the chosen clean-break filter, plus a SPY breadth test.

Buy SPY (S&P 500 exchange-traded fund) after a day with enough clean-break
signals. Sell after a day whose count falls under an exit number.

Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_spy_breadth_20260927"
FREEZE_CSV = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "hv15m_cleanbreak_age4to8_am_pct20_20260927"
    / "signals.csv"
)
ALL_CSV = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "hv15m_cleanbreak_age4to8_am_pct20_20260927"
    / "signals_all_clean_break.csv"
)
STOP_CSV = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "hv15m_cleanbreak_stop_grid_20260927"
    / "signals.csv"
)
SPY_CSV = ROOT / "data" / "newdata" / "data" / "SPY.csv"
ANN = 252
LATER = pd.Timestamp("2026-08-24")
ASK = (
    "OK. let's put a -3% stop loss in. something I noticed - there were 12 signals on 8/4 alone. "
    "if we look at the results of our current filter and buy the SPY when there is more than 1 signal "
    "in a day, and sell when there is less than 2 signals in a day, we would make 1.8% in 8 days - 8/3 - 8/10 "
    "what would happen if we remove our filters and look to see if there are 5, 10, or 20 signals in a day "
    "and buy the SPY and sell when it drops below a certain number?"
)


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _date(ts) -> str:
    if ts is None or (isinstance(ts, float) and not np.isfinite(ts)):
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


SORT_CSS = """
table.sortable { border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 18px; }
th, td { border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px; }
th:first-child, td:first-child { text-align: left; }
caption { text-align: left; font-weight: 600; margin: 6px 0; }
th.sortable-th { cursor: pointer; user-select: none; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""

SORT_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "date") return s;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+pp]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr")).filter(function (r) {
      return !r.classList.contains("total-row");
    });
    var pin = Array.from(tbody.querySelectorAll("tr.total-row"));
    rows.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
    pin.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {
      function activate(ev) {
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) { h.classList.remove("sort-asc", "sort-desc"); h.setAttribute("aria-sort", "none"); });
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", activate);
    });
  });
})();
</script>
"""


def day_counts(df: pd.DataFrame) -> pd.Series:
    days = pd.to_datetime(df["entry_date"]).dt.normalize()
    return days.value_counts().sort_index()


def load_spy() -> pd.DataFrame:
    spy = pd.read_csv(SPY_CSV, parse_dates=["Date"])
    spy = spy[(spy["Date"] >= "2026-07-23") & (spy["Date"] <= "2026-09-26")].copy()
    return spy.sort_values("Date").reset_index(drop=True)


def simulate(spy: pd.DataFrame, counts: pd.Series, buy_n: int, sell_n: int) -> dict:
    dates = [pd.Timestamp(d).normalize() for d in spy["Date"]]
    opens = spy["Open"].to_numpy(dtype=float)
    closes = spy["Close"].to_numpy(dtype=float)
    n = len(dates)
    count = [int(counts.get(d, 0)) for d in dates]
    long = False
    pending = None
    entry_i = None
    trades = []
    held_close = [False] * n
    eq = 1.0
    equity = []
    peak = 1.0
    max_dd = 0.0
    prev_close = None

    def _record(mark: float) -> None:
        nonlocal eq, peak, max_dd
        eq = mark
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)

    for i in range(n):
        sold_today = False
        if pending == "buy" and not long:
            long = True
            entry_i = i
            pending = None
        elif pending == "sell" and long:
            exit_px = float(opens[i])
            entry_px = float(opens[entry_i])
            ret = exit_px / entry_px - 1.0
            sessions = i - entry_i
            trades.append(
                {
                    "buy_n": buy_n,
                    "sell_below": sell_n,
                    "signal_day": dates[entry_i - 1] if entry_i else None,
                    "entry_date": dates[entry_i],
                    "exit_date": dates[i],
                    "entry": entry_px,
                    "exit": exit_px,
                    "return": ret,
                    "sessions": sessions,
                    "still_open": False,
                    "later_half": dates[entry_i] >= LATER,
                }
            )
            if prev_close:
                _record(eq * (exit_px / prev_close))
            long = False
            entry_i = None
            pending = None
            sold_today = True
        if long and not sold_today:
            held_close[i] = True
            if entry_i == i:
                _record(eq * (float(closes[i]) / float(opens[i])))
            elif prev_close:
                _record(eq * (float(closes[i]) / prev_close))
        equity.append(eq)
        if (not long) and count[i] >= buy_n:
            pending = "buy"
        elif long and count[i] < sell_n:
            pending = "sell"
        prev_close = float(closes[i])

    if long and entry_i is not None:
        exit_px = float(closes[-1])
        entry_px = float(opens[entry_i])
        ret = exit_px / entry_px - 1.0
        trades.append(
            {
                "buy_n": buy_n,
                "sell_below": sell_n,
                "signal_day": dates[entry_i - 1] if entry_i else None,
                "entry_date": dates[entry_i],
                "exit_date": dates[-1],
                "entry": entry_px,
                "exit": exit_px,
                "return": ret,
                "sessions": n - entry_i,
                "still_open": True,
                "later_half": dates[entry_i] >= LATER,
            }
        )

    rets = np.array([t["return"] for t in trades], dtype=float)
    later = [t for t in trades if t["later_half"]]
    later_rets = np.array([t["return"] for t in later], dtype=float)
    compound = float(np.prod(1.0 + rets) - 1.0) if len(rets) else 0.0
    later_compound = float(np.prod(1.0 + later_rets) - 1.0) if len(later_rets) else 0.0
    sessions_held = int(sum(held_close))
    return {
        "buy_n": buy_n,
        "sell_below": sell_n,
        "trades": trades,
        "n": len(trades),
        "winners": int((rets > 0).sum()) if len(rets) else 0,
        "avg": float(rets.mean()) if len(rets) else None,
        "median": float(np.median(rets)) if len(rets) else None,
        "compound": compound,
        "later_n": len(later),
        "later_compound": later_compound,
        "sessions_held": sessions_held,
        "sessions": n,
        "max_dd": float(max_dd),
        "final_eq": float(eq),
        "days_long_share": sessions_held / n if n else None,
    }


def buy_hold(spy: pd.DataFrame) -> float:
    if len(spy) < 2:
        return float("nan")
    return float(spy["Close"].iloc[-1] / spy["Open"].iloc[1] - 1.0)


def rule_rows() -> list[tuple[str, pd.Series, int, int]]:
    return []


def main() -> int:
    freeze = pd.read_csv(FREEZE_CSV)
    allb = pd.read_csv(ALL_CSV)
    stop = pd.read_csv(STOP_CSV)
    spy = load_spy()
    filt_counts = day_counts(freeze)
    all_counts = day_counts(allb)

    stock = freeze.merge(
        stop[
            [
                "symbol",
                "signal_datetime",
                "return_3pct",
                "winner_stopped_3pct",
                "loser_capped_3pct",
            ]
        ],
        on=["symbol", "signal_datetime"],
        how="left",
    )
    if stock["return_3pct"].isna().any():
        raise SystemExit("3% stop missing on a freeze row")

    rules = [("Chosen filter", filt_counts, 2, 2)]
    for buy_n, sells in ((5, (5, 2, 1)), (10, (10, 5, 2)), (20, (20, 10, 5))):
        for sell_n in sells:
            rules.append(("Unfiltered clean break", all_counts, buy_n, sell_n))

    results = []
    for book, counts, buy_n, sell_n in rules:
        st = simulate(spy, counts, buy_n, sell_n)
        st["book"] = book
        results.append(st)

    bh = buy_hold(spy)
    # Named window: morning after 8/3 through morning after 8/10, even though 8/6 had 0 filter signals.
    by_date = {pd.Timestamp(r.Date).normalize(): r for r in spy.itertuples(index=False)}
    named = None
    if pd.Timestamp("2026-08-04") in by_date and pd.Timestamp("2026-08-11") in by_date:
        named = float(by_date[pd.Timestamp("2026-08-11")].Open / by_date[pd.Timestamp("2026-08-04")].Open - 1.0)

    aug6 = int(filt_counts.get(pd.Timestamp("2026-08-06"), 0))
    aug4 = int(filt_counts.get(pd.Timestamp("2026-08-04"), 0))
    filt = results[0]
    first = filt["trades"][0] if filt["trades"] else None

    STAMP.mkdir(parents=True, exist_ok=True)
    stock_out = stock[
        [
            "symbol",
            "signal_datetime",
            "entry_date",
            "trigger_bar_time_et",
            "zone_age",
            "forward_return",
            "return_3pct",
            "winner_stopped_3pct",
            "loser_capped_3pct",
            "later_half",
        ]
    ].copy()
    stock_out["AnnRoR_3pct"] = stock_out["return_3pct"] * ANN
    stock_out.to_csv(STAMP / "signals.csv", index=False)

    trade_rows = []
    for st in results:
        for t in st["trades"]:
            row = dict(t)
            row["book"] = st["book"]
            trade_rows.append(row)
    trades_df = pd.DataFrame(trade_rows)
    if len(trades_df):
        trades_df["annror"] = trades_df["return"] * ANN / trades_df["sessions"].clip(lower=1)
        trades_df.to_csv(STAMP / "spy_trades.csv", index=False)

    day_idx = pd.to_datetime(spy["Date"]).dt.normalize()
    days = pd.DataFrame(
        {
            "date": day_idx.dt.strftime("%Y-%m-%d"),
            "spy_open": spy["Open"].to_numpy(),
            "spy_close": spy["Close"].to_numpy(),
            "filter_signals": [int(filt_counts.get(d, 0)) for d in day_idx],
            "unfiltered_signals": [int(all_counts.get(d, 0)) for d in day_idx],
        }
    )
    days.to_csv(STAMP / "spy_days.csv", index=False)

    summary = pd.DataFrame(
        [
            {
                "book": st["book"],
                "buy_when_at_least": st["buy_n"],
                "sell_when_below": st["sell_below"],
                "trades": st["n"],
                "winners": st["winners"],
                "avg_trade": st["avg"],
                "median_trade": st["median"],
                "compound": st["compound"],
                "annror_scaled": (st["compound"] * ANN / st["sessions"]) if st["sessions"] else None,
                "days_long": st["sessions_held"],
                "days_in_window": st["sessions"],
                "max_dd": st["max_dd"],
                "later_trades": st["later_n"],
                "later_compound": st["later_compound"],
            }
            for st in results
        ]
    )
    summary.to_csv(STAMP / "spy_rules.csv", index=False)

    stop_avg = float(stock_out["return_3pct"].mean())
    winners = int((stock_out["forward_return"] > 0).sum())
    stopped_w = int(stock_out["winner_stopped_3pct"].sum())
    losers = int((stock_out["forward_return"] < 0).sum())
    capped = int(stock_out["loser_capped_3pct"].sum())

    def trade_line(t) -> str:
        if t is None:
            return "no trade"
        flag = " marked at the last close" if t["still_open"] else ""
        return (
            f"{_date(t['entry_date'])} open {_pct(t['return'])} "
            f"through {_date(t['exit_date'])}{flag}"
        )

    first_txt = "none"
    if first:
        first_txt = (
            f"buys the {_date(first['entry_date'])} open at {first['entry']:.2f} and sells the "
            f"{_date(first['exit_date'])} open at {first['exit']:.2f}, a return of {_pct(first['return'])}"
        )

    named_txt = _pct(named) if named is not None else "—"
    plain_grid = []
    for st in results[1:]:
        plain_grid.append(
            f"At least {st['buy_n']} signals, sell below {st['sell_below']}: "
            f"{st['n']} SPY trades, compound {_pct(st['compound'])}, "
            f"long {st['sessions_held']} of {st['sessions']} sessions."
        )

    sum_header = "".join(
        [
            _th("Book", "text"),
            _th("Buy when signals are at least", "num"),
            _th("Sell when signals fall below", "num"),
            _th("SPY trades", "num"),
            _th("Winners", "num"),
            _th("Avg trade", "num"),
            _th("Compounded while in", "num"),
            _th("AnnRoR (scaled)", "num"),
            _th("Sessions long", "num"),
            _th("Max drop while in", "num"),
            _th("Trades entered on/after 2026-08-24", "num"),
            _th("Compound of those later trades", "num"),
        ]
    )
    sum_body = []
    for st in results:
        scaled = st["compound"] * ANN / st["sessions"] if st["sessions"] else None
        sum_body.append(
            "<tr>"
            f"<td>{html.escape(st['book'])}</td>"
            f"<td>{st['buy_n']}</td>"
            f"<td>{st['sell_below']}</td>"
            f"<td>{st['n']}</td>"
            f"<td>{st['winners']}</td>"
            f"<td>{_pct(st['avg'])}</td>"
            f"<td>{_pct(st['compound'])}</td>"
            f"<td>{_pct(scaled)}</td>"
            f"<td>{st['sessions_held']}</td>"
            f"<td>{_pct(st['max_dd'])}</td>"
            f"<td>{st['later_n']}</td>"
            f"<td>{_pct(st['later_compound'])}</td>"
            "</tr>"
        )

    tr_header = "".join(
        [
            _th("Book", "text"),
            _th("Buy at least", "num"),
            _th("Sell below", "num"),
            _th("Signal day that turned it on", "date"),
            _th("Buy date", "date"),
            _th("Sell date", "date"),
            _th("SPY return", "num"),
            _th("Sessions held", "num"),
            _th("AnnRoR (scaled)", "num"),
            _th("Still open at the last close", "text"),
        ]
    )
    tr_body = []
    for st in results:
        for t in st["trades"]:
            ann = t["return"] * ANN / max(int(t["sessions"]), 1)
            tr_body.append(
                "<tr>"
                f"<td>{html.escape(st['book'])}</td>"
                f"<td>{st['buy_n']}</td>"
                f"<td>{st['sell_below']}</td>"
                f"<td>{_date(t['signal_day'])}</td>"
                f"<td>{_date(t['entry_date'])}</td>"
                f"<td>{_date(t['exit_date'])}</td>"
                f"<td>{_pct(t['return'])}</td>"
                f"<td>{t['sessions']}</td>"
                f"<td>{_pct(ann)}</td>"
                f"<td>{'yes' if t['still_open'] else 'no'}</td>"
                "</tr>"
            )

    stock_header = "".join(
        [
            _th("Symbol", "text"),
            _th("Signal", "date"),
            _th("Age", "num"),
            _th("Trigger", "text"),
            _th("Next-session return, no stop", "num"),
            _th("Return with a 3% stop", "num"),
            _th("AnnRoR with a 3% stop", "num"),
            _th("Winner stopped", "text"),
            _th("Loser capped", "text"),
            _th("On/after 2026-08-24", "text"),
        ]
    )
    stock_body = []
    for rec in stock_out.itertuples(index=False):
        stock_body.append(
            "<tr>"
            f"<td>{html.escape(str(rec.symbol))}</td>"
            f"<td>{html.escape(str(rec.signal_datetime))}</td>"
            f"<td>{int(rec.zone_age)}</td>"
            f"<td>{html.escape(str(rec.trigger_bar_time_et))}</td>"
            f"<td>{_pct(rec.forward_return)}</td>"
            f"<td>{_pct(rec.return_3pct)}</td>"
            f"<td>{_pct(rec.AnnRoR_3pct)}</td>"
            f"<td>{'yes' if rec.winner_stopped_3pct else 'no'}</td>"
            f"<td>{'yes' if rec.loser_capped_3pct else 'no'}</td>"
            f"<td>{html.escape(str(rec.later_half))}</td>"
            "</tr>"
        )

    day_header = "".join(
        [
            _th("Date", "date"),
            _th("Filter signals", "num"),
            _th("Unfiltered signals", "num"),
            _th("SPY open", "num"),
            _th("SPY close", "num"),
        ]
    )
    day_body = [
        "<tr>"
        f"<td>{html.escape(r.date)}</td>"
        f"<td>{int(r.filter_signals)}</td>"
        f"<td>{int(r.unfiltered_signals)}</td>"
        f"<td>{r.spy_open:.2f}</td>"
        f"<td>{r.spy_close:.2f}</td>"
        "</tr>"
        for r in days.itertuples(index=False)
    ]

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clean break — 3% stop and SPY signal count</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1200px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #334155; font-size: 0.95rem; }}
{SORT_CSS}
</style>
</head>
<body>
<h1>3% stop on the filter, and buying SPY when many signals fire</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Signal window about 2026-07-23 to 2026-09-24. One change for the stocks: a 3% stop. The SPY test is a separate idea. Click column headers to sort.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>The stocks stay the same buys as the chosen filter: a clean break of the highest zone, zone age 4 to 8 trading days, trigger candle from 9:30 through 11:00 Eastern (11:00 included), and a close at least 20% under the high of the prior 252 trading days. Those trades now use a 3% stop on the next session. If a low in that session trades 3% under the purchase, the trade is sold at a 3% loss. If the low never gets there, the trade still exits at the close 26 fifteen-minute bars later. Average return with that stop is {_pct(stop_avg)} on {len(stock_out)} trades. Winners stopped out: {stopped_w} of {winners}. Losers kept from falling further: {capped} of {losers}.</p>
<p>SPY means the S&amp;P 500 exchange-traded fund. The count is how many of these signals printed that day. A day with no signals counts as zero. The count is known only after that day, so the buy is the next session’s open, and the sale is the next session’s open after a day falls under the exit count. There is only one SPY position. Sitting in cash earns nothing here.</p>
<p>August 4 had {aug4} filter signals, and August 3, 5, and 7 also had more than one. August 6 had {aug6}. Under the rule “buy when more than one, sell when fewer than two,” that zero day is an exit. The first round trip {first_txt}. It does not stay on from August 3 through August 10. If the zero day is ignored and SPY is held from the August 4 open (the morning after August 3) to the August 11 open (the morning after August 10), the move is {named_txt}. That is the 1.8% in that 8-day stretch. The strict rule does not take that whole stretch.</p>
<p>With the filters removed, the same next-open rule is tested at 5, 10, and 20 signals. The exit numbers tried are the buy number itself, plus lower counts, so a burst can cool off before the sale. The first week after July 23 has a flood of clean breaks because the zone history is just starting (172 signals on July 27). Annualized rate of return (AnnRoR) on a SPY trade is that trade’s return times 252, divided by the sessions it was held. On the summary row it is the compounded result times 252, divided by every session in the window, including days in cash. It scales this short stretch. It is not a yearly portfolio return. Entries on or after August 24 are a caution column only.</p>
</div>
<h2>3% stop on the chosen filter</h2>
<p class="note">Same 29 trades as the freeze. Average with the 3% stop {_pct(stop_avg)}. AnnRoR {_pct(stop_avg * ANN)} scales that one-session average by 252. It is not a yearly portfolio return.</p>
<table class="sortable">
<caption>Each filtered trade with the 3% stop filled in.</caption>
<thead><tr>{stock_header}</tr></thead>
<tbody>
{''.join(stock_body)}
</tbody>
</table>
<h2>Buying SPY from the signal count</h2>
<p class="note">Buy-and-hold SPY from the July 24 open to the last close in this window is {_pct(bh)}. That is the comparison for every row. “Max drop while in” is the deepest decline of this SPY sleeve from a peak, including the path between buy and sell.</p>
<table class="sortable">
<caption>Filter rule plus unfiltered counts of 5, 10, and 20.</caption>
<thead><tr>{sum_header}</tr></thead>
<tbody>
{''.join(sum_body)}
</tbody>
</table>
<h2>Each SPY round trip</h2>
<table class="sortable">
<caption>One row per buy and sell.</caption>
<thead><tr>{tr_header}</tr></thead>
<tbody>
{''.join(tr_body)}
</tbody>
</table>
<h2>Signals per day</h2>
<table class="sortable">
<caption>A blank signal file day is zero. August 4 is 12 on the filter.</caption>
<thead><tr>{day_header}</tr></thead>
<tbody>
{''.join(day_body)}
</tbody>
</table>
</body>
{SORT_JS}
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")
    (STAMP / "BASELINE.md").write_text(
        f"""# 3% stop on the clean-break filter, and a SPY signal-count test

Study id: `hv15m_cleanbreak_spy_breadth_20260927`

Not gold. Not DailyRun.

## What you asked

{ASK}

## In plain English

The stock filter is unchanged: clean break of the highest zone, age 4–8, trigger 09:30 through 11:00 Eastern including 11:00, and at least 20% below the prior 252-trading-day high. The research exit on those trades is now a 3% stop on the next session. Average with that stop: {_pct(stop_avg)} on {len(stock_out)} trades. Winners stopped: {stopped_w} of {winners}. Losers capped: {capped} of {losers}.

SPY (S&P 500 exchange-traded fund) is bought at the next session open after a day whose signal count reaches the buy number, and sold at the next session open after a day whose count falls below the sell number. Days with no signals count as zero. Annualized rate of return (AnnRoR) scales the short result by 252. It is not a yearly portfolio return.

August 6 had {aug6} filter signals, so the strict “more than 1 / fewer than 2” rule exits there. The first round trip {first_txt}. Holding from the August 4 open to the August 11 open, which skips that exit, is {named_txt}.

## Freeze for the stocks

- Same signals as `hv15m_cleanbreak_age4to8_am_pct20_20260927`.
- Exit: 3% stop on the next 26 fifteen-minute bars, from `hv15m_cleanbreak_stop_grid_20260927`. A low at or below entry × 0.97 exits at exactly −3%. Otherwise the close 26 bars later is kept.
- Chosen after seeing the 1–4% stop grid on this same window. In-sample. Later half (entry on or after 2026-08-24) is report-only.

## SPY rules tried

- Filter book: buy at 2 or more signals, sell below 2.
- Unfiltered clean break: buy at 5, 10, or 20. Sell below the buy number, and below the lower counts listed in `compare.html`.
- Buy-and-hold SPY over the same window: {_pct(bh)}.
- Not a selection of one SPY rule. The grid is the result.

Verdict tag: HOLD. Do not wire DailyRun.
""",
        encoding="utf-8",
    )
    print(f"filter aug4={aug4} aug6={aug6} named={named_txt} first={trade_line(first)}", flush=True)
    print(f"buy_hold={bh:.4f} stop_avg={stop_avg:.4f}", flush=True)
    for st in results:
        print(
            f"{st['book']} buy>={st['buy_n']} sell<{st['sell_below']} "
            f"n={st['n']} compound={st['compound']:.4f} long={st['sessions_held']}/{st['sessions']} "
            f"dd={st['max_dd']:.4f} later_n={st['later_n']} later={st['later_compound']:.4f}",
            flush=True,
        )
    print(f"wrote {STAMP / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
