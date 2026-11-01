#!/usr/bin/env python3
"""Same clean-break buy, sold at the close of that day's last 15-minute bar.

Not gold. Not DailyRun. Entry is unchanged (next 15-minute open). The sale
is the 15:45 bar's close on the entry's calendar day, not the close 26 bars later.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from hv15m_cleanbreak_stop1pct_20260927 import ANN, load_signals  # noqa: E402

BARS = ROOT / "drive" / "paul_experiments" / "hv15m_day_zone_forward_20260925" / "cache_15m.parquet"
STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_daytrade_last15_20260927"
LAST_BUCKET = 25  # 15:45–16:00
ASK = "what are the results if i make this a day trade and sell during the last 15 minutes?"


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(avg) -> str:
    if avg is None or (isinstance(avg, float) and not np.isfinite(avg)):
        return "—"
    return _pct(float(avg) * ANN)


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def attach_daytrade(g: pd.DataFrame) -> pd.DataFrame:
    symbols = set(g["symbol"].astype(str))
    bars = pd.read_parquet(BARS, columns=["symbol", "day", "bucket", "open", "close"])
    bars = bars[bars["symbol"].astype(str).isin(symbols)].copy()
    bars["day"] = pd.to_datetime(bars["day"]).dt.strftime("%Y-%m-%d")
    bars["bucket"] = bars["bucket"].astype(int)
    by_sym: dict[str, tuple] = {}
    for sym, sub in bars.groupby("symbol", sort=False):
        sub = sub.sort_values(["day", "bucket"])
        by_sym[str(sym)] = (
            sub["day"].to_numpy(),
            sub["bucket"].to_numpy(dtype=int),
            sub["open"].to_numpy(dtype=float),
            sub["close"].to_numpy(dtype=float),
        )
    exit_px = np.full(len(g), np.nan)
    entry_day = np.empty(len(g), dtype=object)
    entry_bkt = np.full(len(g), -1, dtype=int)
    ok = np.zeros(len(g), dtype=bool)
    for i, rec in enumerate(g.itertuples(index=False)):
        pack = by_sym.get(str(rec.symbol))
        if pack is None:
            continue
        days, bk, op, cl = pack
        hit = np.flatnonzero((days == rec.signal_day) & (bk == int(rec.bucket)))
        if len(hit) != 1:
            continue
        i0 = int(hit[0]) + 1
        if i0 >= len(cl):
            continue
        entry = float(op[i0])
        stored = float(rec.entry)
        if not np.isfinite(entry) or abs(entry - stored) > max(0.02, abs(stored) * 1e-4):
            continue
        day = str(days[i0])
        same = np.flatnonzero((days == day) & (bk == LAST_BUCKET))
        if len(same) != 1:
            continue
        j = int(same[0])
        if j < i0:
            continue
        exit_px[i] = float(cl[j])
        entry_day[i] = day
        entry_bkt[i] = int(bk[i0])
        ok[i] = True
    out = g.copy()
    out["day_exit"] = exit_px
    out["entry_day"] = entry_day
    out["entry_bucket"] = entry_bkt
    out["day_ok"] = ok
    out["day_ret"] = out["day_exit"] / out["entry"] - 1.0
    out["day_ret"] = out["day_ret"].where(out["day_ok"])
    return out


def stats(g: pd.DataFrame) -> dict:
    x = g[g["day_ok"]].copy()
    n = int(len(x))
    day = x["day_ret"]
    night = x["fwd26"]
    return {
        "n": n,
        "missing": int((~g["day_ok"]).sum()),
        "avg_day": float(day.mean()) if n else None,
        "med_day": float(day.median()) if n else None,
        "win_day": int((day > 0).sum()) if n else 0,
        "lose_day": int((day < 0).sum()) if n else 0,
        "flat_day": int((day == 0).sum()) if n else 0,
        "avg_night": float(night.mean()) if n else None,
        "med_night": float(night.median()) if n else None,
        "win_night": int((night > 0).sum()) if n else 0,
        "night_win_day_lose": int(((night > 0) & (day < 0)).sum()) if n else 0,
        "night_lose_day_win": int(((night < 0) & (day > 0)).sum()) if n else 0,
    }


def _row(label: str, st: dict) -> str:
    win_pct = (st["win_day"] / st["n"]) if st["n"] else None
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{st['n']}</td>"
        f"<td>{_pct(st['avg_day'])}</td>"
        f"<td>{_pct(st['med_day'])}</td>"
        f"<td>{_ann(st['avg_day'])}</td>"
        f"<td>{st['win_day']}</td>"
        f"<td>{_pct(win_pct)}</td>"
        f"<td>{st['lose_day']}</td>"
        f"<td>{_pct(st['avg_night'])}</td>"
        f"<td>{_ann(st['avg_night'])}</td>"
        f"<td>{st['win_night']}</td>"
        f"<td>{st['night_win_day_lose']}</td>"
        f"<td>{st['night_lose_day_win']}</td>"
        "</tr>"
    )


def write_html(rows: list[tuple[str, dict]]) -> None:
    header = "".join(
        [
            _th("Book", "text"),
            _th("N", "num"),
            _th("Avg same-day", "num"),
            _th("Median same-day", "num"),
            _th("AnnRoR same-day", "num"),
            _th("Same-day winners", "num"),
            _th("Same-day win rate", "num"),
            _th("Same-day losers", "num"),
            _th("Avg next session", "num"),
            _th("AnnRoR next session", "num"),
            _th("Next-session winners", "num"),
            _th("Up next session, down same day", "num"),
            _th("Down next session, up same day", "num"),
        ]
    )
    body = "\n".join(_row(label, st) for label, st in rows)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clean break — sell in the last 15 minutes</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1200px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.note {{ color: #334155; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px; }}
th:first-child, td:first-child {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin: 6px 0; }}
th.sortable-th {{ cursor: pointer; user-select: none; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
</style>
</head>
<body>
<h1>Clean break sold in the last 15 minutes</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Window about 2026-07-23 to 2026-09-24.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>Same buy as the clean-break study: the first 15-minute bar that sits entirely above the highest high-volume zone, filled at the next 15-minute bar’s open. Instead of holding into the next session, this is a day trade. The sale is the close of the last 15-minute bar that day (the 15:45–16:00 bar), which is the regular-session close. If the signal is the 15:45 bar itself, the buy is the next morning’s open and the sale is that same day’s 15:45 close, so the trade still does not stay overnight.</p>
<p>The zone is the busiest 15-minute candle that starts before 15:45, kept for 20 trading days. The filter you liked is zone age 4, 5, 6, 7, or 8, a trigger from 09:30 through 11:00 Eastern including 11:00, and a signal close at least 20% under the prior 252-trading-day high. Annualized rate of return (AnnRoR) is the average return times 252. It scales that one-day move. It is not a yearly portfolio return.</p>
</div>
<h2>Same-day close versus holding to the next session</h2>
<p class="note">Click column headers to sort. Next session is the original score: the close 26 fifteen-minute bars after the buy.</p>
<table class="sortable">
<caption>Sell the 15:45 close on the entry day. Next session is the old hold.</caption>
<thead><tr>{header}</tr></thead>
<tbody>
{body}
</tbody>
</table>
</body>
<script>
(function () {{
  function parseSortValue(text, type) {{
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+]/g, "").replace(/,/g, "");
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
    STAMP.mkdir(parents=True, exist_ok=True)
    (STAMP / "compare.html").write_text(page, encoding="utf-8")


def write_signals(freeze: pd.DataFrame) -> None:
    cols = [
        "symbol",
        "signal_datetime",
        "signal_time_et",
        "entry_day",
        "entry",
        "day_exit",
        "day_ret",
        "fwd26",
    ]
    out = freeze.loc[freeze["day_ok"], cols].copy()
    out["AnnRoR_same_day"] = out["day_ret"] * ANN
    out["AnnRoR_next_session"] = out["fwd26"] * ANN
    out.to_csv(STAMP / "signals.csv", index=False)


def write_baseline(a: dict, f: dict) -> None:
    text = f"""# Clean break sold in the last 15 minutes

Study id: `hv15m_cleanbreak_daytrade_last15_20260927`

Not gold. Not DailyRun. Window about 2026-07-23 through 2026-09-24.

## What you asked

{ASK}

## Exit

Buy at the next 15-minute open after the clean-break signal. Sell the close of the 15:45 bar on that entry’s calendar day. No overnight hold.

Original score remains the close 26 bars later, shown only as a comparison.

AnnRoR = average return × 252. Scaled one-day move, not a portfolio yearly return.

## Counts

- Unfiltered clean break: N={a['n']}, same-day avg={a['avg_day']}, next-session avg={a['avg_night']}
- Chosen filter: N={f['n']}, same-day avg={f['avg_day']}, next-session avg={f['avg_night']}
- Missing same-day exits: unfiltered {a['missing']}, filter {f['missing']}
"""
    (STAMP / "BASELINE.md").write_text(text, encoding="utf-8")


def main() -> int:
    g = attach_daytrade(load_signals())
    missing = int((~g["day_ok"]).sum())
    print(f"rows {len(g)} missing {missing}", flush=True)
    if missing:
        print(g.loc[~g["day_ok"], ["symbol", "signal_datetime"]].head(12).to_string(index=False))
        raise SystemExit("missing day-trade exit")
    late = g["entry_date"] >= "2026-08-24"
    books = [
        ("Unfiltered clean break", stats(g)),
        ("Unfiltered, entry before 2026-08-24", stats(g[~late])),
        ("Unfiltered, entry on or after 2026-08-24", stats(g[late])),
        ("Chosen filter (age 4–8, 09:30–11:00, 20%+ below)", stats(g[g["in_freeze"]])),
        ("Chosen filter, entry on or after 2026-08-24", stats(g[g["in_freeze"] & late])),
    ]
    for label, st in books:
        print(
            f"{label}: N={st['n']} day={st['avg_day']} win={st['win_day']} night={st['avg_night']}",
            flush=True,
        )
    write_html(books)
    write_signals(g[g["in_freeze"]].copy())
    write_baseline(books[0][1], books[3][1])
    print(f"wrote {STAMP / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
