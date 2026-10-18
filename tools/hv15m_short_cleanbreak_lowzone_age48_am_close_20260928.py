#!/usr/bin/env python3
"""Morning clean-break short: age 4-8, cover at the same-day close, 2% stop.

Research listing only. Reuses the short study's zone, age, and clean-break
definitions. Does not edit other stamps. Not gold. Not DailyRun.
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
import hv15m_day_zone_forward_short_20260928 as short  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_short_cleanbreak_lowzone_age48_am_close_20260928"
SOURCE = short.STAMP
PUBLISHED_BOOK = SOURCE / "clean_break_down_n20.csv"

N_CARRY = 20
AGES = short.AGES
MORNING = short.MORNING_TIMES
STOP_PCT = 0.02
H26 = base.H26

REQUEST = (
    "no. one of us is misunderstanding the other. I did NOT ask for a system that simply "
    "shorts every single stock if the 3:45 bar was the most volume of the day before. that "
    "is trigger. here's what i meant. lets exclude the 15:45 close bar as a zone source, and "
    "let's use a clean break down of the lowest zone as the trigger. the zone must be aged 4-8. "
    "we only looks for signals between 9:30 and 11AM, and we cover at the close of the day. "
    "can you give me that report please? and our stop should be 2%."
)


def _bkt_label(bucket: int) -> str:
    return base._bkt_label(int(bucket))


def _bar_start_min(bucket: int) -> int:
    return 9 * 60 + 30 + int(bucket) * 15


def scan_symbol(sym: str, g: pd.DataFrame, trades: list, skips: list) -> None:
    """Clean break down of the lowest zone at carry 20, exclude the 15:45 zone bar.

    Zone construction and the clean-break test match scan_symbol in the short study
    for zone_rule ex_last_bar and N=20. The 26-bar forward requirement is not applied.
    """
    g = g.sort_values(["day", "bucket"])
    day = g["day"].to_numpy()
    bucket = g["bucket"].to_numpy(dtype=np.int16)
    o = g["open"].to_numpy(dtype=np.float64)
    h = g["high"].to_numpy(dtype=np.float64)
    c = g["close"].to_numpy(dtype=np.float64)
    v = g["volume"].to_numpy(dtype=np.float64)
    n = len(c)
    if n < 5:
        return

    uniq_days = pd.unique(day)
    counts = pd.Series(day).value_counts()
    good_days = [d for d in uniq_days if int(counts.get(d, 0)) >= base.MIN_BARS_SESSION]
    if len(good_days) < base.MIN_SESSIONS:
        return
    day_to_s = {d: i for i, d in enumerate(good_days)}
    sess = np.fromiter((day_to_s.get(d, -1) for d in day), dtype=np.int16, count=n)
    S = len(good_days)

    z_lo = np.full(S, np.nan)
    z_hi = np.full(S, np.nan)
    z_bkt = np.full(S, -1, dtype=np.int16)
    for s, d in enumerate(good_days):
        m = (day == d) & (sess == s)
        if not np.any(m):
            continue
        idx = np.flatnonzero(m)
        idx = idx[bucket[idx] < 25]
        if len(idx) == 0:
            continue
        vols = v[idx]
        bk = bucket[idx]
        best = idx[int(np.lexsort((bk, -vols))[0])]
        lo = float(g["low"].to_numpy(dtype=np.float64)[best])
        hi = float(h[best])
        mid = 0.5 * (lo + hi)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo or mid <= 0:
            continue
        if (hi - lo) / mid < 0.0005:
            continue
        z_lo[s] = lo
        z_hi[s] = hi
        z_bkt[s] = int(bucket[best])

    valid_zone = np.isfinite(z_lo) & np.isfinite(z_hi) & (z_bkt >= 0)
    low_px = g["low"].to_numpy(dtype=np.float64)
    N = N_CARRY
    clean_done = np.zeros(S, dtype=np.int8)

    eod_of_day = {}
    for j in range(n):
        if int(bucket[j]) == 25:
            eod_of_day[day[j]] = j

    for j in range(n):
        s = int(sess[j])
        if s < 0:
            continue
        b = int(bucket[j])
        s0 = max(0, s - N)
        lo_z = -1
        best_lo = 1e300
        px = c[j]
        if not np.isfinite(px) or px <= 0:
            continue
        for zs in range(s0, s + 1):
            if not valid_zone[zs]:
                continue
            if (s - zs) > N:
                continue
            if zs == s and b <= int(z_bkt[zs]):
                continue
            zl = float(z_lo[zs])
            if zl < best_lo or (zl == best_lo and zs > lo_z):
                best_lo = zl
                lo_z = zs

        if lo_z < 0 or j == 0 or int(sess[j - 1]) < 0:
            continue
        if clean_done[lo_z] != 0:
            continue
        zl = float(z_lo[lo_z])
        if not (h[j] < zl and c[j] < zl and c[j - 1] >= zl):
            continue
        clean_done[lo_z] = 1

        age = int(s - lo_z)
        sig_time = _bkt_label(b)
        if age not in AGES or sig_time not in MORNING:
            continue

        birth = pd.Timestamp(good_days[lo_z]).date().isoformat()
        sig_day = pd.Timestamp(day[j]).date().isoformat()
        base_row = {
            "symbol": sym,
            "signal_day": sig_day,
            "signal_time_et": sig_time,
            "zone_date": birth,
            "zone_age": age,
            "zone_low": zl,
            "zone_high": float(z_hi[lo_z]),
        }

        entry_i = j + 1
        if entry_i >= n or day[entry_i] != day[j]:
            skips.append({**base_row, "reason": "next open is not before this session close"})
            continue
        entry = float(o[entry_i])
        if not np.isfinite(entry) or entry <= 0:
            skips.append({**base_row, "reason": "entry open missing"})
            continue
        eod = eod_of_day.get(day[entry_i], -1)
        if eod < entry_i or not np.isfinite(c[eod]):
            skips.append({**base_row, "reason": "no 15:45 close bar on the entry session"})
            continue

        stop_px = entry * (1.0 + STOP_PCT)
        exit_px = float(c[eod])
        exit_bucket = 25
        reason = "same-day close"
        gap = False
        for k in range(entry_i, eod + 1):
            if day[k] != day[entry_i]:
                continue
            if float(o[k]) >= stop_px - 1e-9:
                exit_px = float(o[k])
                exit_bucket = int(bucket[k])
                reason = "2% stop"
                gap = True
                break
            if float(h[k]) >= stop_px - 1e-9:
                exit_px = stop_px
                exit_bucket = int(bucket[k])
                reason = "2% stop"
                gap = False
                break

        ret = (entry - exit_px) / entry
        start_m = _bar_start_min(int(bucket[entry_i]))
        if reason == "same-day close":
            end_m = 16 * 60
            cover_time = "16:00"
        else:
            end_m = _bar_start_min(exit_bucket) + 15
            cover_time = _bkt_label(exit_bucket)
        had_h26 = entry_i + H26 <= n
        trades.append(
            {
                **base_row,
                "session_date": pd.Timestamp(day[entry_i]).date().isoformat(),
                "entry_time_et": _bkt_label(int(bucket[entry_i])),
                "entry": entry,
                "stop": stop_px,
                "cover_time_et": cover_time,
                "cover": exit_px,
                "exit_reason": reason,
                "stop_gap": gap,
                "return": ret,
                "hold_min": int(end_m - start_m),
                "had_26_bars": had_h26,
                "close_only_return": (entry - float(c[eod])) / entry,
            }
        )


def _pct(x: float | None, digits: int = 2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _px(x: float) -> str:
    return f"{float(x):.4f}"


def load_published() -> pd.DataFrame:
    pub = pd.read_csv(PUBLISHED_BOOK)
    age = pub["in_age"].astype(str).str.lower().isin(["true", "1"])
    morning = pub["in_morning"].astype(str).str.lower().isin(["true", "1"])
    out = pub[age & morning].copy()
    out["signal_day"] = out["signal_day"].astype(str).str.slice(0, 10)
    out["zone_date"] = out["zone_date"].astype(str).str.slice(0, 10)
    out["signal_time_et"] = out["signal_time_et"].astype(str)
    return out


def reconcile(trades: pd.DataFrame, pub: pd.DataFrame) -> dict:
    keys = ["symbol", "signal_day", "signal_time_et", "zone_date"]
    t = trades.copy()
    for col in keys:
        t[col] = t[col].astype(str)
        pub[col] = pub[col].astype(str)
    m = t.merge(pub, on=keys, how="outer", suffixes=("", "_pub"), indicator=True)
    both = m[m["_merge"] == "both"]
    only_me = m[m["_merge"] == "left_only"]
    only_pub = m[m["_merge"] == "right_only"]
    close_gap = None
    entry_gap = None
    if len(both):
        close_gap = float((both["close_only_return"] - both["day_ret"]).abs().max())
        entry_gap = float((both["entry"] - both["entry_pub"]).abs().max())
    extra_no_h26 = int((~only_me["had_26_bars"].fillna(False)).sum()) if len(only_me) else 0
    return {
        "published_n": int(len(pub)),
        "matched": int(len(both)),
        "only_here": int(len(only_me)),
        "only_published": int(len(only_pub)),
        "extra_without_26_bars": extra_no_h26,
        "max_abs_close_gap": close_gap,
        "max_abs_entry_gap": entry_gap,
    }


def summarize(trades: pd.DataFrame) -> dict:
    r = trades["return"].to_numpy(dtype=float)
    n = int(len(r))
    if n == 0:
        return {"n": 0}
    wins = int((r > 1e-12).sum())
    losses = int((r < -1e-12).sum())
    flat = n - wins - losses
    n_stop = int((trades["exit_reason"] == "2% stop").sum())
    n_close = int((trades["exit_reason"] == "same-day close").sum())
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win": wins / n,
        "avg": float(np.mean(r)),
        "med": float(np.median(r)),
        "best": float(np.max(r)),
        "worst": float(np.min(r)),
        "hold": float(trades["hold_min"].mean()),
        "n_stop": n_stop,
        "n_close": n_close,
        "n_gap": int(trades["stop_gap"].sum()),
        "date_min": str(trades["session_date"].min()),
        "date_max": str(trades["session_date"].max()),
    }


SORT_CSS = """
table.sortable { border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 18px; }
th, td { border-bottom: 1px solid #e2e8f0; text-align: right; padding: 6px 8px; }
table.trades th:first-child, table.trades td:first-child,
table.trades th:nth-child(10), table.trades td:nth-child(10) { text-align: left; }
caption { text-align: left; font-weight: 600; margin-bottom: 6px; }
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""

SORT_JS = r"""
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    if (type === "date") {
      var d = Date.parse(s);
      return Number.isFinite(d) ? d : NaN;
    }
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    var pinned = rows.filter(function (r) { return r.classList.contains("total-row"); });
    var body = rows.filter(function (r) { return !r.classList.contains("total-row"); });
    body.sort(function (a, b) {
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
    body.forEach(function (r) { tbody.appendChild(r); });
    pinned.forEach(function (r) { tbody.appendChild(r); });
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


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def write_outputs(trades: pd.DataFrame, skips: pd.DataFrame, info: dict, rec: dict, st: dict) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    cols = [
        "symbol",
        "session_date",
        "zone_date",
        "zone_age",
        "zone_low",
        "signal_time_et",
        "entry_time_et",
        "entry",
        "stop",
        "exit_reason",
        "cover_time_et",
        "cover",
        "return_pct",
        "hold_min",
        "signal_day",
        "had_26_bars",
    ]
    out = trades.copy()
    out["return_pct"] = out["return"] * 100.0
    out = out.sort_values(["session_date", "symbol", "signal_time_et"])
    out[cols].to_csv(STAMP / "trades.csv", index=False)

    rows = []
    for rec_t in out.itertuples(index=False):
        rows.append(
            "<tr>"
            f"<td>{html.escape(rec_t.symbol)}</td>"
            f"<td>{html.escape(rec_t.session_date)}</td>"
            f"<td>{html.escape(rec_t.zone_date)}</td>"
            f"<td>{int(rec_t.zone_age)}</td>"
            f"<td>{_px(rec_t.zone_low)}</td>"
            f"<td>{html.escape(rec_t.signal_time_et)}</td>"
            f"<td>{html.escape(rec_t.entry_time_et)}</td>"
            f"<td>{_px(rec_t.entry)}</td>"
            f"<td>{_px(rec_t.stop)}</td>"
            f"<td>{html.escape(rec_t.exit_reason)}</td>"
            f"<td>{html.escape(rec_t.cover_time_et)}</td>"
            f"<td>{_px(rec_t.cover)}</td>"
            f"<td>{rec_t.return_pct:.4f}%</td>"
            "</tr>"
        )

    match_note = (
        f"Published cousin cell “Age 4 to 8 and morning 09:30-11:00” "
        f"(exclude the 15:45 bar, clean break down of the lowest zone, carry 20, "
        f"zone age 4 to 8, signal bar 09:30 through 11:00) has {rec['published_n']} signals. "
        f"This listing matched {rec['matched']} of them. "
        f"Extra trades here: {rec['only_here']}. "
        f"Of those extras, {rec['extra_without_26_bars']} are signals the published file dropped "
        f"because it requires 26 fifteen-minute bars after the fill. "
        f"This exit does not. Published-only rows: {rec['only_published']}."
    )
    if rec["max_abs_close_gap"] is not None:
        match_note += (
            f" On the matched rows, the same-day close with the stop turned off differs from "
            f"the published day-trade return by at most {rec['max_abs_close_gap']:.2e}. "
            f"Entry prices differ by at most {rec['max_abs_entry_gap']:.2e}."
        )
    match_note += (
        " The published day-trade cell covers at the 15:45 close with no 2% stop, and it still "
        "scores a 26-bar book that has been filtered down to age and morning. "
        "The returns on this page are the 2% stop or the same-day close, not that 26-bar return. "
        "The published combined freeze also requires the close to be at least 20% under the prior "
        "252-day high. That filter is not used here."
    )

    n_skip = int(len(skips))
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Morning clean-break short, age 4–8, 2% stop, same-day close</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1200px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.5rem; margin-bottom: 0.2rem; }}
h2 {{ font-size: 1.12rem; margin-top: 1.5rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #334155; font-size: 0.95rem; }}
{SORT_CSS}
code {{ background: #f1f5f9; padding: 0 4px; }}
</style>
</head>
<body>
<h1>Morning clean-break short, same-day close, 2% stop</h1>
<p class="note">Research listing only. Not gold. Not wired into DailyRun. Not a new horse-race and not a retune. Bars {html.escape(str(info.get('date_min')))} through {html.escape(str(info.get('date_max')))}. Liquid symbols: {info.get('symbols_liquid')}.</p>

<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(REQUEST)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>We ignore the 3:45 bar when choosing the zone. We sell short when price cleanly breaks under the lowest high-volume 15-minute zone, and only if that zone is 4 to 8 days old and the break happens in the morning. A 2% rise from the fill covers the short early. Otherwise we buy back at that same day’s close.</p>
<p>This is not “short every stock whose 3:45 bar was the busiest.”</p>
</div>

<h2>Frozen rule</h2>
<ul>
<li><strong>Side.</strong> Short. A short makes money if price falls. Return is (entry − cover) / entry. Percent only. The source study did not size shares.</li>
<li><strong>Zone.</strong> One band per session: the low and high of the highest-volume 15-minute candle. The 15:45 close bar is excluded, so it cannot be the zone. A volume tie keeps the earlier bar. A band thinner than 0.05% of its midpoint is skipped. The band is known only after that candle closes. It can stay active for 20 trading sessions, the carry the later short study used for this clean break. The lowest zone is the active band with the lowest low. A newer band wins a tie.</li>
<li><strong>Trigger.</strong> Clean break down of that lowest zone: the whole signal bar is under the zone (high and close both below the zone low) and the prior bar’s close was not. First time that zone breaks. Same test as the short study’s “Clean break down of lowest zone.”</li>
<li><strong>Age.</strong> Zone age is how many trading sessions the zone has been carried: signal session index minus the session that created the zone, counting only sessions with at least 20 valid 15-minute bars, same as the long freeze. Ages 4, 5, 6, 7, and 8 are kept.</li>
<li><strong>Signal clock.</strong> The study’s existing “09:30–11:00” window, not a new one. The signal bar must start at 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, or 11:00 Eastern Time. The 11:00 bar is included. That bar runs 11:00–11:14. The window is not “bars that finish by 11:00,” which would have stopped at the 10:45 bar.</li>
<li><strong>Fill.</strong> The next 15-minute bar’s open after the signal bar, including when that open is after 11:00. An 11:00 signal fills at the 11:15 open, still the same day. If that next open is not before the session close, the signal is skipped.</li>
<li><strong>Stop.</strong> 2% above the fill (entry × 1.02). On the entry bar and each later bar through the close, the open is checked first. If the open is already at or above the stop, the cover fills at that open (a gap). Otherwise, if that bar’s high reaches the stop, the cover is exactly the stop price, a −2% result. The stop is checked before the scheduled close.</li>
<li><strong>Close cover.</strong> If the stop has not hit, buy back at the close of the entry day’s 15:45–16:00 bar. That close is the regular-session close in this 15-minute store. No overnight hold. No 26-bar or 52-bar forward window.</li>
<li><strong>Not used.</strong> The “at least 20% under the prior 252-day high” filter is not used. Shorting because the 15:45 bar was the busiest bar is not this system.</li>
</ul>
<p class="note">Skipped signals that passed age and the morning clock but could not be filled and covered the same day: {n_skip}. Hold minutes run from the entry bar’s start to 16:00 when the trade reaches the close, or to the end of the 15-minute bar that contained the stop. A stop inside a bar is timed at that bar’s end.</p>
<p class="note">{html.escape(match_note)}</p>
<p class="note">There is no 2024 in-sample / out-of-sample split. This 15-minute history starts in July 2026, so a cut at 2024-01-01 would be empty. Nothing was retuned after seeing the returns.</p>

<h2>Summary</h2>
<table class="sortable">
<caption>Click column headers to sort</caption>
<thead><tr>
{_th("Trades", "num")}
{_th("Wins", "num")}
{_th("Losses", "num")}
{_th("Flat", "num")}
{_th("Win rate", "num")}
{_th("Average", "num")}
{_th("Median", "num")}
{_th("Best", "num")}
{_th("Worst", "num")}
{_th("Stopped at 2%", "num")}
{_th("Reached the close", "num")}
{_th("Avg hold (min)", "num")}
</tr></thead>
<tbody>
<tr>
<td>{st['n']}</td>
<td>{st['wins']}</td>
<td>{st['losses']}</td>
<td>{st['flat']}</td>
<td>{_pct(st['win'])}</td>
<td>{_pct(st['avg'])}</td>
<td>{_pct(st['med'])}</td>
<td>{_pct(st['best'])}</td>
<td>{_pct(st['worst'])}</td>
<td>{st['n_stop']}</td>
<td>{st['n_close']}</td>
<td>{st['hold']:.1f}</td>
</tr>
</tbody>
</table>
<p class="note">Trade dates {html.escape(st['date_min'])} through {html.escape(st['date_max'])}. Universe is the short study’s liquid set ({info.get('symbols_liquid')} symbols, 15-minute bars {html.escape(str(info.get('date_min')))} through {html.escape(str(info.get('date_max')))}). A win is a return strictly above zero. Of the {st['n_stop']} stop exits, {st['n_gap']} filled at a gap open through the stop rather than at exactly −2%.</p>

<h2>Every trade</h2>
<table class="sortable trades">
<caption>Click column headers to sort</caption>
<thead><tr>
{_th("Symbol", "text")}
{_th("Session date", "date")}
{_th("Zone date", "date")}
{_th("Zone age", "num")}
{_th("Zone low", "num")}
{_th("Signal time", "text")}
{_th("Entry time", "text")}
{_th("Entry price", "num")}
{_th("Stop price", "num")}
{_th("Exit reason", "text")}
{_th("Cover time", "text")}
{_th("Cover price", "num")}
{_th("Return %", "num")}
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<p class="note">Cover time is 16:00 when the exit is the regular-session close. When the exit is the 2% stop, cover time is the start of the 15-minute bar that contained the stop. Signal time and entry time are bar starts, Eastern Time. Source scan: <code>tools/hv15m_day_zone_forward_short_20260928.py</code>, zone rule exclude the 15:45 close bar, pattern clean break down of the lowest zone, carry 20. Generator: <code>tools/hv15m_short_cleanbreak_lowzone_age48_am_close_20260928.py</code>.</p>
</body>
{SORT_JS}
</html>
"""
    (STAMP / "report.html").write_text(page, encoding="utf-8")

    baseline = f"""# Morning clean-break short, age 4–8, 2% stop, same-day close

Study id: `hv15m_short_cleanbreak_lowzone_age48_am_close_20260928`

Research listing only. Not gold. Not wired into DailyRun. Not a horse-race and not a retune. Knobs were not chosen from this table.

## What you asked

> {REQUEST}

## In plain English

We ignore the 3:45 bar when choosing the zone. We sell short when price cleanly breaks under the lowest high-volume 15-minute zone, and only if that zone is 4 to 8 days old and the break happens in the morning. A 2% rise from the fill covers the short early. Otherwise we buy back at that same day’s close.

This is not “short every stock whose 3:45 bar was the busiest.”

## Frozen rule

- Side: short. Return (entry − cover) / entry. Percent only. No share size.
- Zone source: exclude the 15:45 close bar. Highest-volume earlier 15-minute candle of the session. Ties keep the earlier bar. Band must be at least 0.05% of its midpoint.
- Carry: 20 trading sessions. Lowest zone = active zone with the lowest low. Newer zone wins a tie. The zone is usable only after its candle closes.
- Trigger: clean break down. The whole signal bar is under the lowest zone (high and close both below the zone low) and the prior close was not. First time per zone.
- Zone age: signal session index minus zone session index, on sessions with at least {base.MIN_BARS_SESSION} valid 15-minute bars. Keep 4, 5, 6, 7, 8. Same count the long freeze used.
- Signal clock: bar starts 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, and 11:00 Eastern Time. The 11:00–11:14 bar is included.
- Fill: next 15-minute open. An 11:00 signal fills at 11:15. Skip if that open is not before the session close.
- Stop: entry × 1.02. Open through the stop covers at the open. A high that reaches the stop covers at the stop (−2%). Checked before the close, on the entry bar and later bars the same day.
- Exit if not stopped: close of the entry day’s 15:45 bar (regular-session close, 16:00). No overnight. No 26-bar window.
- Not used: 20% under the prior 252-day high. Not “15:45 was the highest-volume bar.”

## Universe and exit

- Universe: the short study liquid set, {info.get('symbols_liquid')} symbols. At least {base.MIN_SESSIONS} sessions with at least {base.MIN_BARS_SESSION} bars, median session dollar volume at least $1,000,000, median close at least $5.
- Bar span: {info.get('date_min')} through {info.get('date_max')}. No 2024 in-sample / out-of-sample split. The 15-minute store starts in July 2026.
- Source script: `tools/hv15m_day_zone_forward_short_20260928.py` and the zone definitions in `tools/hv15m_day_zone_forward_20260925.py`.
- This listing’s generator: `tools/hv15m_short_cleanbreak_lowzone_age48_am_close_20260928.py`.
- Published cousin for the signal count: “Age 4 to 8 and morning 09:30-11:00” in `drive/paul_experiments/hv15m_day_zone_forward_short_20260928`. That cell’s day-trade return has no 2% stop. This page recomputes the cover with the stop.

## Result

N={st['n']}; wins={st['wins']}; losses={st['losses']}; flat={st['flat']}; win={_pct(st['win'])}; average={_pct(st['avg'])}; median={_pct(st['med'])}; best={_pct(st['best'])}; worst={_pct(st['worst'])}; stopped at 2%={st['n_stop']}; reached the close={st['n_close']}; skipped={n_skip}.

{match_note}

Research only. Not gold. Not DailyRun.
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")


def main() -> int:
    print("loading 15-minute cache", flush=True)
    bars = pd.read_parquet(short.CACHE)
    liquid, info = base.select_universe(bars)
    trades: list[dict] = []
    skips: list[dict] = []
    n_sym = 0
    for sym, g in liquid.groupby("symbol", sort=False):
        scan_symbol(str(sym), g, trades, skips)
        n_sym += 1
        if n_sym % 100 == 0:
            print(f"  {n_sym} symbols, trades {len(trades)} skips {len(skips)}", flush=True)
    print(f"done symbols {n_sym} trades {len(trades)} skips {len(skips)}", flush=True)
    frame = pd.DataFrame(trades)
    skip_frame = pd.DataFrame(skips)
    pub = load_published()
    rec = reconcile(frame, pub) if len(frame) else {
        "published_n": int(len(pub)),
        "matched": 0,
        "only_here": 0,
        "only_published": int(len(pub)),
        "extra_without_26_bars": 0,
        "max_abs_close_gap": None,
        "max_abs_entry_gap": None,
    }
    st = summarize(frame)
    print("reconcile", rec, flush=True)
    print("summary", st, flush=True)
    if len(frame) == 0:
        print("no trades", file=sys.stderr)
        return 2
    write_outputs(frame, skip_frame, info, rec, st)
    print(f"wrote {STAMP}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
