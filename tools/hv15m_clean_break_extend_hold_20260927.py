#!/usr/bin/env python3
"""Score the narrower hv15m hold: keep the position open on a new signal.

Same buy as hv15m_clean_break_nmax_exit_20260926 at the frozen 20-session
carry (clean break of the highest zone, 15:45 bar cannot be the zone,
fill at the next 15-minute open).

Control: every signal is its own trade. Sell the close 26 bars after the
fill (one session). Overlaps are all counted.

Skip: one position per symbol. A new signal while that trade is open is
ignored. The sale stays on the original 26-bar clock. Already on the
prior page. Printed again so the extend rule has a neighbor.

Narrower rule (this page): one position per symbol. If another clean
break prints before that sale, do not open a second trade and do not
sell on the original clock. Move the sale to 26 bars after the new fill.
Repeat until a 26-bar window finishes with no newer signal before it.
The buy price stays the first fill. If the moved sale is not in the tape,
that chain is still open and is left out of the closed numbers.

Research only. Not gold. Not DailyRun. Not the daily Volume Zone system.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "drive" / "paul_experiments"))

import hv15m_clean_break_nmax_exit_20260926 as ex  # noqa: E402
import hv15m_day_zone_forward_20260925 as base  # noqa: E402
from compare_format import ann_ror_from_closed  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_clean_break_extend_hold_20260927"
H1 = 26
N_CARRY = 20
HALF_CUT = "2026-08-24"

ORIGINAL_REQUEST = (
    "can you score the narrower rule? keep a position open when another signal "
    "occurs before the prior position is closed out"
)


def _pct(x, digits=2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(x) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{float(x):.1f}%"


def _num(x, digits=2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{float(x):.{digits}f}"


def _pp(x) -> str:
    """Percentage-point delta from a return difference."""
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):+.2f} pp"


def _signals(sym: str, g: pd.DataFrame) -> tuple[list[dict], np.ndarray, np.ndarray]:
    g = g.sort_values(["day", "bucket"])
    day = g["day"].to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    o = g["open"].to_numpy(dtype=np.float64)
    h = g["high"].to_numpy(dtype=np.float64)
    l = g["low"].to_numpy(dtype=np.float64)
    c = g["close"].to_numpy(dtype=np.float64)
    v = g["volume"].to_numpy(dtype=np.float64)
    n = len(c)
    if n < H1 + 5:
        return [], day, c
    uniq = pd.unique(day)
    counts = pd.Series(day).value_counts()
    good_days = [d for d in uniq if int(counts.get(d, 0)) >= base.MIN_BARS_SESSION]
    if len(good_days) < base.MIN_SESSIONS:
        return [], day, c
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    z_lo, z_hi, z_bkt, valid = ex._zones_ex_last(day, sess, bucket, l, h, v, n, good_days)
    prior_i, prior_hi = ex._prior_best(z_hi, valid, N_CARRY)
    clean_done = np.zeros(len(good_days), dtype=np.int8)
    sigs: list[dict] = []
    for j in range(1, n - 1):
        s = int(sess[j])
        if s < 0 or int(sess[j - 1]) < 0:
            continue
        hi_z = int(prior_i[s])
        best_hi = float(prior_hi[s]) if hi_z >= 0 else -1e300
        if valid[s] and int(bucket[j]) > int(z_bkt[s]):
            zh_today = float(z_hi[s])
            if zh_today > best_hi or (zh_today == best_hi and s > hi_z):
                hi_z = s
                best_hi = zh_today
        if hi_z < 0 or clean_done[hi_z]:
            continue
        zh = float(z_hi[hi_z])
        if not (l[j] > zh and c[j] > zh and c[j - 1] <= zh):
            continue
        entry_i = j + 1
        entry = float(o[entry_i])
        if not np.isfinite(entry) or entry <= 0:
            continue
        clean_done[hi_z] = 1
        complete = entry_i + H1 <= n
        sigs.append(
            {
                "symbol": sym,
                "j": int(j),
                "entry_i": int(entry_i),
                "entry": entry,
                "complete": bool(complete),
                "day": pd.Timestamp(day[entry_i]).date().isoformat(),
            }
        )
    return sigs, day, c


def _iso_at(day: np.ndarray, i: int) -> str:
    return pd.Timestamp(day[i]).date().isoformat()


def _chain(sigs: list[dict], day: np.ndarray, close: np.ndarray) -> tuple[list[dict], list[dict], dict]:
    """Return (stacked, skip, extend) closed rows and a small count dict."""
    stacked: list[dict] = []
    for s in sigs:
        if not s["complete"]:
            continue
        exit_i = s["entry_i"] + H1 - 1
        px = float(close[exit_i])
        if not np.isfinite(px):
            continue
        exit_day = _iso_at(day, exit_i)
        stacked.append(
            {
                "symbol": s["symbol"],
                "book": "stacked",
                "day": s["day"],
                "exit_day": exit_day,
                "entry_i": s["entry_i"],
                "exit_i": exit_i,
                "ret": px / s["entry"] - 1.0,
                "n_signals": 1,
                "extensions": 0,
                "days_held": int((pd.Timestamp(exit_day) - pd.Timestamp(s["day"])).days),
            }
        )

    skip: list[dict] = []
    busy = -1
    for row in stacked:
        if int(row["entry_i"]) <= busy:
            continue
        skip.append({**row, "book": "skip"})
        busy = int(row["exit_i"])

    extend: list[dict] = []
    still_open = 0
    i = 0
    nbar = len(close)
    while i < len(sigs):
        if not sigs[i]["complete"]:
            i += 1
            continue
        k = i
        exit_i = sigs[i]["entry_i"] + H1 - 1
        unfinished = False
        while True:
            nxt = None
            for t in range(k + 1, len(sigs)):
                if sigs[t]["j"] < exit_i:
                    nxt = t
                else:
                    break
            if nxt is None:
                break
            k = nxt
            new_end = sigs[k]["entry_i"] + H1
            if new_end > nbar:
                unfinished = True
                break
            exit_i = new_end - 1
        if unfinished:
            still_open += 1
            i = k + 1
            continue
        px = float(close[exit_i])
        entry = float(sigs[i]["entry"])
        if not np.isfinite(px) or entry <= 0:
            i = k + 1
            continue
        exit_day = _iso_at(day, exit_i)
        entry_day = sigs[i]["day"]
        n_sig = k - i + 1
        extend.append(
            {
                "symbol": sigs[i]["symbol"],
                "book": "extend",
                "day": entry_day,
                "exit_day": exit_day,
                "entry_i": sigs[i]["entry_i"],
                "exit_i": exit_i,
                "ret": px / entry - 1.0,
                "n_signals": n_sig,
                "extensions": n_sig - 1,
                "days_held": int((pd.Timestamp(exit_day) - pd.Timestamp(entry_day)).days),
            }
        )
        i = k + 1
    meta = {"still_open_chains": still_open}
    return stacked, skip, extend, meta  # type: ignore[return-value]


def _stats(g: pd.DataFrame, window: str) -> dict:
    n = int(len(g))
    empty = {
        "window": window,
        "signals": 0,
        "symbols": 0,
        "days": 0,
        "wins": 0,
        "losses": 0,
        "win_pct": np.nan,
        "avg": np.nan,
        "med": np.nan,
        "avg_exmax": np.nan,
        "day_avg": np.nan,
        "day_med": np.nan,
        "pf": np.nan,
        "avg_win": np.nan,
        "avg_loss": np.nan,
        "avg_days_held": np.nan,
        "med_days_held": np.nan,
        "ann_ror": np.nan,
        "extended_trades": 0,
        "signals_inside": 0,
        "mean_extensions": np.nan,
    }
    if n == 0:
        return empty
    ret = g["ret"].to_numpy(dtype=float)
    order = np.argsort(ret)
    ex = ret[order[:-1]] if n > 1 else ret
    by_day = g.groupby("day")["ret"].mean()
    wins_d = float(ret[ret > 0].sum())
    losses_d = float(ret[ret < 0].sum())
    pf = float(wins_d / abs(losses_d)) if losses_d < 0 else np.nan
    held = g["days_held"].to_numpy(dtype=float)
    held_pos = held[held > 0]
    avg_days = float(held_pos.mean()) if len(held_pos) else 0.0
    ann = ann_ror_from_closed(
        total_pnl=float(ret.sum()),
        n_trades=n,
        avg_days_held=avg_days,
        brt_cash=1.0,
    )
    ext = g["extensions"].to_numpy(dtype=float)
    return {
        "window": window,
        "signals": n,
        "symbols": int(g["symbol"].nunique()),
        "days": int(g["day"].nunique()),
        "wins": int((ret > 0).sum()),
        "losses": int((ret < 0).sum()),
        "win_pct": float((ret > 0).mean()),
        "avg": float(ret.mean()),
        "med": float(np.median(ret)),
        "avg_exmax": float(ex.mean()),
        "day_avg": float(by_day.mean()),
        "day_med": float(by_day.median()),
        "pf": pf,
        "avg_win": float(ret[ret > 0].mean()) if (ret > 0).any() else np.nan,
        "avg_loss": float(ret[ret < 0].mean()) if (ret < 0).any() else np.nan,
        "avg_days_held": avg_days if avg_days > 0 else np.nan,
        "med_days_held": float(np.median(held)),
        "ann_ror": float(ann) if ann is not None else np.nan,
        "extended_trades": int((ext > 0).sum()),
        "signals_inside": int(g["n_signals"].sum()),
        "mean_extensions": float(ext.mean()),
    }


def _slice(df: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "full":
        return df
    if window == "early":
        return df[df["day"] < HALF_CUT]
    return df[df["day"] >= HALF_CUT]


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _td(val: str) -> str:
    return f"<td>{html.escape(val)}</td>"


HEADERS = (
    ("Book", "text"),
    ("Window", "text"),
    ("Trades", "num"),
    ("Symbols", "num"),
    ("Entry days", "num"),
    ("Wins", "num"),
    ("Losses", "num"),
    ("Win %", "num"),
    ("Avg return", "num"),
    ("Median", "num"),
    ("Avg ex-best", "num"),
    ("Avg win", "num"),
    ("Avg loss", "num"),
    ("Day-avg", "num"),
    ("Day-median", "num"),
    ("Profit factor", "num"),
    ("Ann ROR %", "num"),
    ("Avg calendar days held", "num"),
    ("Median calendar days", "num"),
    ("Trades that were extended", "num"),
    ("Signals inside those trades", "num"),
)


def _cells(label: str, window: str, r: dict) -> str:
    vals = [
        label,
        window,
        str(r["signals"]),
        str(r["symbols"]),
        str(r["days"]),
        str(r["wins"]),
        str(r["losses"]),
        _pct(r["win_pct"]),
        _pct(r["avg"]),
        _pct(r["med"]),
        _pct(r["avg_exmax"]),
        _pct(r["avg_win"]),
        _pct(r["avg_loss"]),
        _pct(r["day_avg"]),
        _pct(r["day_med"]),
        _num(r["pf"]),
        _ann(r["ann_ror"]),
        _num(r["avg_days_held"]),
        _num(r["med_days_held"]),
        str(r["extended_trades"]),
        str(r["signals_inside"]),
    ]
    return "<tr>" + "".join(_td(v) for v in vals) + "</tr>"


def _delta_row(name: str, a: dict, b: dict) -> str:
    """b minus a on the quality columns that are differences of rates."""
    def dpp(key):
        if not (np.isfinite(a.get(key, np.nan)) and np.isfinite(b.get(key, np.nan))):
            return "—"
        return _pp(b[key] - a[key])

    def dnum(key, digits=2):
        if not (np.isfinite(a.get(key, np.nan)) and np.isfinite(b.get(key, np.nan))):
            return "—"
        return f"{b[key] - a[key]:+.{digits}f}"

    def dann():
        if not (np.isfinite(a.get("ann_ror", np.nan)) and np.isfinite(b.get("ann_ror", np.nan))):
            return "—"
        return f"{b['ann_ror'] - a['ann_ror']:+.1f} pp"

    vals = [
        name,
        "full minus neighbor",
        f"{b['signals'] - a['signals']:+d}",
        "—",
        "—",
        f"{b['wins'] - a['wins']:+d}",
        f"{b['losses'] - a['losses']:+d}",
        dpp("win_pct"),
        dpp("avg"),
        dpp("med"),
        dpp("avg_exmax"),
        dpp("avg_win"),
        dpp("avg_loss"),
        dpp("day_avg"),
        dpp("day_med"),
        dnum("pf"),
        dann(),
        dnum("avg_days_held"),
        dnum("med_days_held"),
        "—",
        "—",
    ]
    return "<tr>" + "".join(_td(v) for v in vals) + "</tr>"


def _judge(ext: dict, skip: dict, stacked: dict, late_ext: dict, late_skip: dict) -> str:
    """HOLD / DISMISS from quality vs the one-position skip, later half can veto."""
    if ext["signals"] == 0 or skip["signals"] == 0:
        return "HOLD. The closed count is empty, so there is nothing to adopt."
    avg_up = ext["avg"] > skip["avg"] + 0.0005
    med_ok = ext["med"] >= skip["med"] - 1e-9
    day_ok = np.isfinite(ext["day_avg"]) and ext["day_avg"] >= skip["day_avg"] - 0.0002
    wo_ok = np.isfinite(ext["avg_exmax"]) and ext["avg_exmax"] >= skip["avg_exmax"] - 0.0002
    late_soft = (
        np.isfinite(late_ext.get("med", np.nan))
        and np.isfinite(late_skip.get("med", np.nan))
        and late_ext["med"] < late_skip["med"] - 0.001
    )
    if avg_up and med_ok and day_ok and wo_ok and not late_soft:
        return (
            "LEAN KEEP as a research note only, against the one-position sale that ignores a new signal. "
            "Not adopted. This tape is about nine weeks in 2026, the pattern was already the preferred look, "
            "and this hold rule was chosen after seeing those pages."
        )
    if ext["avg"] < skip["avg"] - 0.0005 and ext["med"] <= skip["med"] + 1e-9:
        return (
            "DISMISS as a replacement for the one-session sale. Keeping the position open when a new signal "
            "prints did not lift the average and the median together. Not adopted."
        )
    if late_soft:
        return (
            "HOLD. The later half (entries on or after 2026-08-24) is softer than the same names sold on the "
            "original clock. That split is report-only. Do not retune the hold to repair it. Not adopted."
        )
    return (
        "HOLD. The keep-open rule is close to selling on the original one-session clock. "
        "A flat quality change is not a reason to change the sale. Not adopted."
    )


SORT_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/pp/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var movable = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    movable.sort(function (a, b) {
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") {
        return dir * String(av).localeCompare(String(bv));
      }
      return dir * (av - bv);
    });
    movable.concat(pinned).forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {
      function activate(ev) {
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) {
          h.classList.remove("sort-asc", "sort-desc");
          h.setAttribute("aria-sort", "none");
        });
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


def write_reports(info: dict, books: dict[str, pd.DataFrame], stats: dict, still_open: int) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    stacked = stats[("stacked", "full")]
    skip = stats[("skip", "full")]
    ext = stats[("extend", "full")]
    late_ext = stats[("extend", "late")]
    late_skip = stats[("skip", "late")]
    verdict = _judge(ext, skip, stacked, late_ext, late_skip)
    match = stacked["signals"] == 979 and abs(stacked["avg"] - 0.0061221146411236434) < 0.0004

    labels = {
        "stacked": "Every signal, sell after one session",
        "skip": "One position, ignore a new signal",
        "extend": "Keep open when a new signal prints",
    }
    windows = (
        ("full", "Full tape"),
        ("early", f"Before {HALF_CUT}"),
        ("late", f"On or after {HALF_CUT}"),
    )
    body = []
    for key in ("stacked", "skip", "extend"):
        for wkey, wlab in windows:
            body.append(_cells(labels[key], wlab, stats[(key, wkey)]))
    delta_body = [
        _delta_row("Keep-open minus every-signal", stacked, ext),
        _delta_row("Keep-open minus ignore-new-signal", skip, ext),
    ]
    head = "".join(_th(lab, typ) for lab, typ in HEADERS)

    ext_share = (
        f"{ext['extended_trades']} of {ext['signals']} closed keep-open trades "
        f"({_pct(ext['extended_trades'] / ext['signals']) if ext['signals'] else '—'}) "
        f"were lengthened by a later signal. Those trades contain {ext['signals_inside']} signals. "
        f"Average extensions per closed trade: {_num(ext['mean_extensions'])}."
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Clean break — keep the position open, 20260927</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 24px auto; max-width: 1280px; color: #1a1a1a; line-height: 1.45; }}
h1 {{ font-size: 1.55rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f4f7fb; border: 1px solid #d5deea; padding: 12px 16px; margin: 12px 0; }}
.plain {{ background: #f8f6f1; }}
.note {{ color: #444; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 6px 8px; white-space: nowrap; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin-bottom: 6px; }}
th.sortable-th {{ cursor: pointer; user-select: none; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; font-size: .85em; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
code {{ background: #f1f5f9; padding: 0 4px; }}
</style>
</head>
<body>
<h1>Clean break — keep the position open when a new signal prints</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Same 20-day clean break as <code>hv15m_clean_break_nmax_exit_20260926</code>. Tape {html.escape(info["date_min"])} to {html.escape(info["date_max"])}, {info["symbols_liquid"]} liquid symbols. Click column headers to sort.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ORIGINAL_REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>The buy is the one already scored. Each day we take the busiest 15-minute candle that starts before 3:45pm, and we remember that candle’s high and low for 20 trading days. A buy signal is the first later 15-minute candle that sits entirely above the highest of those highs. We buy the next 15-minute bar’s open.</p>
<p>Until now, each of those signals was its own trade, sold about one session later (26 fifteen-minute bars), even when a second signal arrived while the first trade was still open. The narrower rule is one share lot per name. If another signal prints before that sale, we do not buy more, and we do not sell yet. We push the sale out to one session after the new signal, and we keep doing that if it happens again. The original buy price stays. We only book the trade once it actually reaches that later sale.</p>
<p>The neighbor rule, already on the prior page, is stricter in a different way: one lot per name, but a new signal is ignored and the sale stays on the original clock.</p>
</div>

<h2>Verdict</h2>
<p>{html.escape(verdict)}</p>
<p>{html.escape(ext_share)} Chains still open at the end of the tape, because a late signal would have moved the sale past the last bar: {still_open}. Those are not in the closed rows.</p>
<p class="note">Annualized rate of return (Ann ROR) uses the book formula: one plus the average trade, raised to 365 divided by the average calendar days held, then minus one. A trade that opens and closes on the same calendar date is left out of that day average. It annualizes the average trade. It is not one account’s compounded growth, because many names are open at the same time. Max drawdown, Calmar, and Sharpe are not on this page for that reason. There is no sized book and no daily equity curve.</p>
<p class="note">{"The every-signal row matches the prior page: 979 trades and an average of 0.61%." if match else "The every-signal row does not match the prior page’s 979 trades at 0.61%. Treat the keep-open numbers as a new count until that gap is explained."}</p>

<h2>Full tape and the later half</h2>
<p class="note">The later half is entries on or after {HALF_CUT}. It is a caution split inside this 2026 window only. The house cut at 2024-01-01 does not exist here. It is not used to pick a winner.</p>
<table class="sortable">
<caption>Three ways to treat a second signal. Returns are percent of the first fill.</caption>
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>

<h2>What changed versus the neighbors</h2>
<p class="note">A positive average, median, or win rate means the keep-open rule was higher. Profit factor is gross winning percent divided by gross losing percent. “pp” is percentage points.</p>
<table class="sortable">
<caption>Keep-open minus the other two books, full tape.</caption>
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(delta_body)}
</tbody>
</table>

<h2>Freeze</h2>
<ul>
<li>Buy: clean break of the highest zone from the last 20 trading sessions. The whole bar is above that zone’s high, the prior close was not, and it is the first time for that zone. Fill is the next 15-minute open.</li>
<li>Zone: busiest 15-minute bar that starts before 15:45. Ties go to the earlier bar.</li>
<li>Control sale: close of the 26th 15-minute bar from the fill. No stop.</li>
<li>Narrower sale: that same 26-bar close, moved to the newest signal whenever another clean break’s bar is before the scheduled sale bar. One position. Buy price unchanged.</li>
<li>A signal on the sale bar itself does not extend. The sale and the signal share that bar’s close, so the signal is not before the position is closed.</li>
<li>Universe: liquid names from the parent study, {html.escape(info["date_min"])} through {html.escape(info["date_max"])}.</li>
<li>Selection: this hold was requested after the stacked score and the fixed longer holds. Research only. Nothing is wired into DailyRun.</li>
</ul>
</body>
{SORT_JS}
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    def line(r: dict) -> str:
        return (
            f"{r['signals']} trades, average {_pct(r['avg'])}, median {_pct(r['med'])}, "
            f"win rate {_pct(r['win_pct'])}, day-average {_pct(r['day_avg'])}, "
            f"average without the best trade {_pct(r['avg_exmax'])}, profit factor {_num(r['pf'])}, "
            f"Ann ROR {_ann(r['ann_ror'])}, average calendar days held {_num(r['avg_days_held'])}."
        )

    baseline = f"""# Clean break — keep the position open

Study id: `hv15m_clean_break_extend_hold_20260927`

Parent: `hv15m_clean_break_nmax_exit_20260926`. Research only. Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system.

## What you asked

> {ORIGINAL_REQUEST}

## In plain English

The buy is unchanged: first 15-minute bar that sits entirely above the highest high-volume zone from the last 20 trading days, skipping the 15:45 candle when the zone is chosen, fill at the next open. The original score sells one session later even if a second signal prints while the trade is open. The narrower rule keeps that one position open and moves the sale one session past the new signal. It does not buy a second lot.

## Freeze

- Pattern and carry: frozen at the prior 20-day clean break, exclude 15:45.
- Control: every signal, close of the 26th bar from the fill.
- Neighbor: one position, new signals ignored until that sale (the prior page’s one-trade table).
- This arm: one position; a new signal before the sale moves the 26-bar clock. Buy price stays the first fill.
- Caution split: entry before {HALF_CUT} versus on or after. Report only. No 2024-01-01 split exists in this store.
- Selection: the pattern was already preferred on this tape, and this hold was requested after those scores. Not adopted from this page.
- Ann ROR uses the book formula on the average trade and calendar days held. Same-day holds are left out of the day average. It is not one account’s compounded return. Max drawdown is not claimed.

## Check

{"Every-signal matches the prior page: 979 trades, average 0.61%." if match else "Every-signal does not match 979 / 0.61%."}

Still-open chains left out of the closed keep-open row: {still_open}.

## Result

{verdict}

Every signal, full tape: {line(stacked)} Later half: {line(stats[("stacked", "late")])}

One position, ignore a new signal, full tape: {line(skip)} Later half: {line(late_skip)}

Keep open when a new signal prints, full tape: {line(ext)} Later half: {line(late_ext)}

{ext_share}
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")
    print(verdict, flush=True)
    print(ext_share, flush=True)
    print(f"wrote {STAMP / 'compare.html'}", flush=True)


def main() -> int:
    con = __import__("duckdb").connect()
    bars = base.build_15m(con)
    liquid, info = base.select_universe(bars)
    print(
        f"symbols {info['symbols_liquid']} {info['date_min']} {info['date_max']}",
        flush=True,
    )
    stacked_rows: list[dict] = []
    skip_rows: list[dict] = []
    extend_rows: list[dict] = []
    still_open = 0
    n_sym = 0
    for sym, g in liquid.groupby("symbol", sort=False):
        sigs, day, close = _signals(str(sym), g)
        if sigs:
            st, sk, exr, meta = _chain(sigs, day, close)
            stacked_rows.extend(st)
            skip_rows.extend(sk)
            extend_rows.extend(exr)
            still_open += int(meta["still_open_chains"])
        n_sym += 1
        if n_sym % 200 == 0:
            print(f"  {n_sym} stacked {len(stacked_rows)} extend {len(extend_rows)}", flush=True)
    books = {
        "stacked": pd.DataFrame(stacked_rows),
        "skip": pd.DataFrame(skip_rows),
        "extend": pd.DataFrame(extend_rows),
    }
    STAMP.mkdir(parents=True, exist_ok=True)
    parts = []
    for name, df in books.items():
        if df.empty:
            continue
        parts.append(df)
    pd.concat(parts, ignore_index=True).to_csv(STAMP / "trades.csv", index=False)
    stats = {}
    for name, df in books.items():
        for window in ("full", "early", "late"):
            stats[(name, window)] = _stats(_slice(df, window), window)
            r = stats[(name, window)]
            print(
                f"{name:8} {window:5} n={r['signals']:5} avg={_pct(r['avg']):8} "
                f"med={_pct(r['med']):8} win={_pct(r['win_pct']):8} ann={_ann(r['ann_ror']):8} "
                f"days={_num(r['avg_days_held'])}",
                flush=True,
            )
    (STAMP / "scan_meta.json").write_text(
        json.dumps(
            {
                "info": info,
                "half_cut": HALF_CUT,
                "still_open_chains": still_open,
                "stats": {f"{a}|{b}": stats[(a, b)] for a, b in stats},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    write_reports(info, books, stats, still_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
