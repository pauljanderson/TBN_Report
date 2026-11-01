#!/usr/bin/env python3
"""1% stop on the clean-break book, using the stored 15-minute path.

Not gold. Not DailyRun. The stop is checked on the same 26 bars as the
next-session return. A touch at or below entry * 0.99 exits at exactly -1%.
"""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BARS = ROOT / "drive" / "paul_experiments" / "hv15m_day_zone_forward_20260925" / "cache_15m.parquet"
SOURCE = ROOT / "drive" / "paul_experiments" / "hv15m_age4to8_pct252_20260927" / "signals.csv"
FREEZE = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_age4to8_am_pct20_20260927" / "signals.csv"
STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_stop1pct_20260927"

ASK = (
    "what happens if we add a 1% stop loss? overall returns? "
    "how many winners do we get stopped out of? how many losers does it prevent from losing further?"
)
H26 = 26
STOP = 0.01
ANN = 252


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann_txt(avg) -> str:
    if avg is None or (isinstance(avg, float) and not np.isfinite(avg)):
        return "—"
    return _pct(float(avg) * ANN)


def _pp(x, digits=2) -> str:
    """Percentage points, already a fraction of price (0.02 -> 2.00 pp)."""
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f} pp"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _bkt(label: str) -> int:
    hh, mm = str(label).split(":")
    return (int(hh) * 60 + int(mm) - (9 * 60 + 30)) // 15


def load_signals() -> pd.DataFrame:
    df = pd.read_csv(SOURCE)
    g = df[
        (df["pattern"] == "clean_break_highest")
        & (df["N"] == 20)
        & (df["zone_rule"] == "ex_last_bar")
    ].copy()
    g["signal_day"] = g["signal_day"].astype(str).str.slice(0, 10)
    g["entry_date"] = g["day"].astype(str).str.slice(0, 10)
    g["signal_time_et"] = g["signal_time_et"].astype(str)
    g["bucket"] = g["signal_time_et"].map(_bkt)
    g["entry"] = pd.to_numeric(g["entry"], errors="coerce")
    g["fwd26"] = pd.to_numeric(g["fwd26"], errors="coerce")
    freeze = pd.read_csv(FREEZE)
    freeze["signal_datetime"] = freeze["signal_datetime"].astype(str)
    g["signal_datetime"] = g["signal_day"] + " " + g["signal_time_et"]
    keys = set(zip(freeze["symbol"].astype(str), freeze["signal_datetime"]))
    g["in_freeze"] = [
        (str(s), str(t)) in keys for s, t in zip(g["symbol"], g["signal_datetime"])
    ]
    if int(g["in_freeze"].sum()) != len(freeze):
        raise SystemExit(f"freeze match {int(g['in_freeze'].sum())} vs {len(freeze)}")
    return g


def attach_path(g: pd.DataFrame) -> pd.DataFrame:
    symbols = set(g["symbol"].astype(str))
    bars = pd.read_parquet(BARS, columns=["symbol", "day", "bucket", "open", "low", "close"])
    bars = bars[bars["symbol"].astype(str).isin(symbols)].copy()
    bars["day"] = pd.to_datetime(bars["day"]).dt.strftime("%Y-%m-%d")
    bars["bucket"] = bars["bucket"].astype(int)
    by_sym: dict[str, tuple] = {}
    for sym, sub in bars.groupby("symbol", sort=False):
        sub = sub.sort_values(["day", "bucket"])
        by_sym[str(sym)] = (
            sub["day"].to_numpy(),
            sub["bucket"].to_numpy(),
            sub["open"].to_numpy(dtype=float),
            sub["low"].to_numpy(dtype=float),
            sub["close"].to_numpy(dtype=float),
        )
    lows = np.empty(len(g), dtype=float)
    closes = np.empty(len(g), dtype=float)
    ok = np.zeros(len(g), dtype=bool)
    for i, rec in enumerate(g.itertuples(index=False)):
        pack = by_sym.get(str(rec.symbol))
        if pack is None:
            lows[i] = np.nan
            closes[i] = np.nan
            continue
        days, bk, op, lo, cl = pack
        hit = np.flatnonzero((days == rec.signal_day) & (bk == int(rec.bucket)))
        if len(hit) != 1:
            lows[i] = np.nan
            closes[i] = np.nan
            continue
        i0 = int(hit[0]) + 1
        if i0 + H26 > len(cl):
            lows[i] = np.nan
            closes[i] = np.nan
            continue
        entry = float(op[i0])
        stored = float(rec.entry)
        if not np.isfinite(entry) or abs(entry - stored) > max(0.02, abs(stored) * 1e-4):
            lows[i] = np.nan
            closes[i] = np.nan
            continue
        lows[i] = float(np.min(lo[i0 : i0 + H26]))
        closes[i] = float(cl[i0 + H26 - 1])
        ok[i] = True
    out = g.copy()
    out["path_low"] = lows
    out["path_close"] = closes
    out["path_ok"] = ok
    return out


def score(g: pd.DataFrame) -> pd.DataFrame:
    out = g.copy()
    entry = out["entry"].to_numpy(dtype=float)
    low = out["path_low"].to_numpy(dtype=float)
    fwd = out["fwd26"].to_numpy(dtype=float)
    hit = low <= entry * (1.0 - STOP) + 1e-9
    # Keep the stored next-session return when the stop is not touched.
    stopped_ret = np.where(hit, -STOP, fwd)
    out["stop_hit"] = hit
    out["return_with_stop"] = stopped_ret
    out["winner"] = fwd > 0
    out["loser"] = fwd < 0
    out["winner_stopped"] = (fwd > 0) & hit
    out["loser_capped"] = fwd < -STOP
    # Close between 0 and -1%, low tagged the stop: stopped loser, not "saved".
    out["stopped_shallow_loser"] = (fwd < 0) & (fwd >= -STOP) & hit
    out["unchanged_shallow_loser"] = (fwd < 0) & (fwd >= -STOP) & ~hit
    out["loss_avoided"] = np.where(out["loser_capped"], (-STOP) - fwd, np.nan)
    return out


def book_stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    avg0 = float(g["fwd26"].mean()) if n else None
    avg1 = float(g["return_with_stop"].mean()) if n else None
    capped = g[g["loser_capped"]]
    avoided = float(capped["loss_avoided"].mean()) if len(capped) else None
    return {
        "n": n,
        "avg0": avg0,
        "avg1": avg1,
        "winners": int(g["winner"].sum()),
        "winners_stopped": int(g["winner_stopped"].sum()),
        "losers": int(g["loser"].sum()),
        "losers_capped": int(len(capped)),
        "avg_avoided": avoided,
        "shallow_stopped": int(g["stopped_shallow_loser"].sum()),
        "shallow_unchanged": int(g["unchanged_shallow_loser"].sum()),
        "flat": int((~g["winner"] & ~g["loser"]).sum()),
        "path_missing": int((~g["path_ok"]).sum()) if "path_ok" in g.columns else 0,
    }


def _row(label: str, st: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{st['n']}</td>"
        f"<td>{_pct(st['avg0'])}</td>"
        f"<td>{_pct(st['avg1'])}</td>"
        f"<td>{_ann_txt(st['avg0'])}</td>"
        f"<td>{_ann_txt(st['avg1'])}</td>"
        f"<td>{st['winners']}</td>"
        f"<td>{st['winners_stopped']}</td>"
        f"<td>{st['losers']}</td>"
        f"<td>{st['losers_capped']}</td>"
        f"<td>{_pp(st['avg_avoided'])}</td>"
        "</tr>"
    )


def write(all_rows: pd.DataFrame, freeze: pd.DataFrame, a: dict, f: dict) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    header = "".join(
        [
            _th("Book", "text"),
            _th("N", "num"),
            _th("Avg without stop", "num"),
            _th("Avg with 1% stop", "num"),
            _th("AnnRoR without stop", "num"),
            _th("AnnRoR with 1% stop", "num"),
            _th("Winners", "num"),
            _th("Winners stopped out", "num"),
            _th("Losers", "num"),
            _th("Losers capped (close worse than −1%)", "num"),
            _th("Avg loss avoided on capped trades", "num"),
        ]
    )
    extra_header = "".join(
        [
            _th("Book", "text"),
            _th("Winners kept", "num"),
            _th("Losers between 0 and −1%, unchanged", "num"),
            _th("Losers between 0 and −1%, low tagged −1%", "num"),
        ]
    )
    extra = (
        "<tr>"
        f"<td>Unfiltered clean break</td><td>{a['winners'] - a['winners_stopped']}</td>"
        f"<td>{a['shallow_unchanged']}</td><td>{a['shallow_stopped']}</td></tr>"
        "<tr>"
        f"<td>Chosen filter</td><td>{f['winners'] - f['winners_stopped']}</td>"
        f"<td>{f['shallow_unchanged']}</td><td>{f['shallow_stopped']}</td></tr>"
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clean break — 1% stop</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1100px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #334155; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px; }}
th:first-child, td:first-child {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin: 6px 0; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
</style>
</head>
<body>
<h1>What a 1% stop does to the clean break</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Window about 2026-07-23 to 2026-09-24. Not a new system.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>Take the buy that is already in the clean-break study and ask what changes if we get out as soon as price is down 1% from the purchase. The purchase price is the next 15-minute bar’s open, which is the same price behind the next-session return. That return is not a close-to-close move from the signal candle. It is from that open to the close 26 fifteen-minute bars later, about one regular session.</p>
<p>The stop looks at the lows of those same 26 bars. If any low trades at or below 1% under the purchase price, the trade is sold at exactly −1%. It does not get a worse price if the bar trades through the stop, and it does not get a better price than −1%. If price never trades down 1%, the original next-session return stays.</p>
<p>A winner is a trade that would have closed up with no stop. Getting stopped out of a winner means that trade dipped 1% and we locked in −1% instead of the higher close. A loser the stop prevents from losing further is one whose close, with no stop, was worse than −1%. The stop caps that loss at −1% and the gap is what was saved. A loser whose close was between 0 and −1% is not “saved”: if the low never tagged −1%, nothing changes; if the low did tag −1%, we exit at −1%, which is a bit worse than that close.</p>
<p>Annualized rate of return (AnnRoR) is that average next-session return multiplied by 252. It scales the one-day move. It is not a yearly portfolio return. Two books are shown: every clean break, and the smaller filter you liked (zone age 4 to 8, trigger from 9:30 through 11:00 Eastern including 11:00, and a close at least 20% under the prior 252-trading-day high). Carry is 20 trading days. The zone is the low-to-high of the busiest 15-minute candle before the 15:45 close.</p>
</div>
<h2>With the stop and without it</h2>
<p class="note">Click column headers to sort. “Avg loss avoided” is the average of (−1% minus the original return) on trades whose close was worse than −1%, in percentage points.</p>
<table class="sortable">
<caption>Same 26-bar window. Stop fill is −1% when the low tags it.</caption>
<thead><tr>{header}</tr></thead>
<tbody>
{_row("Unfiltered clean break", a)}
{_row("Chosen filter (age 4–8, 09:30–11:00, 20%+ below)", f)}
</tbody>
</table>
<h2>The trades that are not “saved”</h2>
<table class="sortable">
<caption>Winners the stop leaves alone, and losers whose close was already between 0 and −1%.</caption>
<thead><tr>{extra_header}</tr></thead>
<tbody>
{extra}
</tbody>
</table>
<p class="note">Path matched the stored entry on every row (missing paths: unfiltered {a['path_missing']}, chosen filter {f['path_missing']}). Trades whose next-session return is exactly zero are neither winners nor losers: unfiltered {a['flat']}, chosen filter {f['flat']}. Winners plus losers plus those flats equal N.</p>
</body>
<script>
(function () {{
  function parseSortValue(text, type) {{
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+pp]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }}
  function sortTable(table, col, type, dir) {{
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {{
      var av = parseSortValue(a.cells[col] ? a.cells[col].textContent : "", type);
      var bv = parseSortValue(b.cells[col] ? b.cells[col].textContent : "", type);
      var aMiss = typeof av === "number" && !Number.isFinite(av);
      var bMiss = typeof bv === "number" && !Number.isFinite(bv);
      if (aMiss && bMiss) return 0;
      if (aMiss) return 1;
      if (bMiss) return -1;
      if (typeof av === "string" || typeof bv === "string") return dir * String(av).localeCompare(String(bv));
      return dir * (av - bv);
    }});
    rows.forEach(function (r) {{ tbody.appendChild(r); }});
  }}
  document.querySelectorAll("table.sortable").forEach(function (table) {{
    var headers = table.querySelectorAll("th.sortable-th");
    headers.forEach(function (th, col) {{
      function activate(ev) {{
        if (ev.type === "keydown" && ev.key !== "Enter" && ev.key !== " ") return;
        if (ev.type === "keydown") ev.preventDefault();
        var type = th.getAttribute("data-sort") || "text";
        var dir = th.classList.contains("sort-asc") ? -1 : 1;
        headers.forEach(function (h) {{ h.classList.remove("sort-asc", "sort-desc"); h.setAttribute("aria-sort", "none"); }});
        th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        sortTable(table, col, type, dir);
      }}
      th.addEventListener("click", activate);
      th.addEventListener("keydown", activate);
    }});
  }});
}})();
</script>
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    def dump(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": frame["symbol"],
                "signal_datetime": frame["signal_datetime"],
                "entry": frame["entry"],
                "path_low": frame["path_low"],
                "forward_return": frame["fwd26"],
                "return_with_stop": frame["return_with_stop"],
                "AnnRoR_without_stop": frame["fwd26"] * ANN,
                "AnnRoR_with_stop": frame["return_with_stop"] * ANN,
                "winner_stopped": frame["winner_stopped"],
                "loser_capped": frame["loser_capped"],
                "stopped_shallow_loser": frame["stopped_shallow_loser"],
            }
        )

    dump(freeze).sort_values(["signal_datetime", "symbol"]).to_csv(STAMP / "signals.csv", index=False)
    dump(all_rows).sort_values(["signal_datetime", "symbol"]).to_csv(
        STAMP / "signals_unfiltered_clean_break.csv", index=False
    )

    baseline = f"""# 1% stop on the clean break — research note

Study id: `hv15m_cleanbreak_stop1pct_20260927`

Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system. Window about 2026-07-23 through 2026-09-24.

## What you asked

> {ASK}

## In plain English

If price trades 1% under the purchase during the same next-session window, sell at exactly −1%. Otherwise keep the original next-session result. The purchase is the next 15-minute open, not the signal close.

## Stop

- Entry is the open of the 15-minute bar after the signal bar. The next-session return is from that open to the close 26 bars later.
- Path low is the lowest low of those 26 bars, from the stored 15-minute cache. No new download.
- Stop if that low is at or below entry × 0.99. Fill is −1%. No better fill. No worse fill if the bar trades through.
- Winner: no-stop return > 0. Winner stopped out: that winner’s low tags −1%.
- Loser capped: no-stop return worse than −1%. Average loss avoided is the average of (−1% minus that return), in percentage points.
- A close already between 0 and −1% is not “prevented from losing further.” If its low also tags −1%, it is a stopped shallow loser and exits at −1%.

## Books

1. Unfiltered clean break of the highest zone. Zone is the busiest 15-minute candle before 15:45. Carry 20 trading days. {a['n']} signals.
2. Chosen filter already stamped: age exactly 4–8, trigger 09:30 through 11:00 Eastern inclusive, signal close at least 20% below the prior 252-trading-day high. {f['n']} signals. In-sample selection on this short window. This stop test does not retune that filter.

## Headline

- Unfiltered: average {_pct(a['avg0'])} without the stop, {_pct(a['avg1'])} with it. Winners {a['winners']}, of which {a['winners_stopped']} were stopped out. Losers capped {a['losers_capped']}.
- Chosen filter: average {_pct(f['avg0'])} without the stop, {_pct(f['avg1'])} with it. Winners {f['winners']}, of which {f['winners_stopped']} were stopped out. Losers capped {f['losers_capped']}.

Annualized rate of return (AnnRoR) is the average next-session return times 252. Scaled one-day move, not a portfolio yearly return.
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")
    print("unfiltered", a, flush=True)
    print("freeze", f, flush=True)


def main() -> int:
    g = load_signals()
    print(f"clean breaks {len(g)}", flush=True)
    g = attach_path(g)
    missing = int((~g["path_ok"]).sum())
    if missing:
        bad = g.loc[~g["path_ok"], ["symbol", "signal_datetime", "entry"]].head(8)
        print(bad.to_string(index=False), flush=True)
        raise SystemExit(f"path match failed on {missing} rows")
    # Stored forward return should match the path close.
    recomputed = g["path_close"] / g["entry"] - 1.0
    gap = (recomputed - g["fwd26"]).abs()
    print(f"fwd gap max {float(gap.max()):.6g} median {float(gap.median()):.6g}", flush=True)
    if float(gap.max()) > 1e-4:
        raise SystemExit("recomputed forward return does not match the stored one")
    g = score(g)
    freeze = g[g["in_freeze"]].copy()
    write(g, freeze, book_stats(g), book_stats(freeze))
    print(f"wrote {STAMP / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
