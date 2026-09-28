#!/usr/bin/env python3
"""2%, 3%, and 4% stops on the same clean-break path as the 1% stop.

Not gold. Not DailyRun. A low at or below entry * (1 - stop) exits at exactly -stop.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from hv15m_cleanbreak_stop1pct_20260927 import ANN, attach_path, load_signals  # noqa: E402

STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_stop_grid_20260927"
STOPS = (0.01, 0.02, 0.03, 0.04)
ASK = "thanks. back to the 1% stop loss can we see what 2, 3, and 4% stop losses would result in?"


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(avg) -> str:
    if avg is None or (isinstance(avg, float) and not np.isfinite(avg)):
        return "—"
    return _pct(float(avg) * ANN)


def _pp(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.2f} pp"


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def one_stop(g: pd.DataFrame, stop: float) -> dict:
    entry = g["entry"].to_numpy(dtype=float)
    low = g["path_low"].to_numpy(dtype=float)
    fwd = g["fwd26"].to_numpy(dtype=float)
    hit = low <= entry * (1.0 - stop) + 1e-9
    stopped = np.where(hit, -stop, fwd)
    winner = fwd > 0
    loser = fwd < 0
    capped = fwd < -stop
    n = int(len(g))
    return {
        "stop": stop,
        "n": n,
        "avg0": float(fwd.mean()) if n else None,
        "avg1": float(stopped.mean()) if n else None,
        "winners": int(winner.sum()),
        "winners_stopped": int((winner & hit).sum()),
        "losers": int(loser.sum()),
        "losers_capped": int(capped.sum()),
        "avg_avoided": float(((-stop) - fwd[capped]).mean()) if capped.any() else None,
        "shallow_stopped": int((loser & (fwd >= -stop) & hit).sum()),
    }


def _row(book: str, st: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(book)}</td>"
        f"<td>{_pct(st['stop'], 0)}</td>"
        f"<td>{st['n']}</td>"
        f"<td>{_pct(st['avg0'])}</td>"
        f"<td>{_pct(st['avg1'])}</td>"
        f"<td>{_ann(st['avg1'])}</td>"
        f"<td>{st['winners']}</td>"
        f"<td>{st['winners_stopped']}</td>"
        f"<td>{st['losers']}</td>"
        f"<td>{st['losers_capped']}</td>"
        f"<td>{_pp(st['avg_avoided'])}</td>"
        f"<td>{st['shallow_stopped']}</td>"
        "</tr>"
    )


SORT_JS = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : NaN;
    if (type === "text") return s.toUpperCase();
    var n = s.replace(/[$,%+pp]/g, "").replace(/,/g, "");
    var v = parseFloat(n);
    return Number.isFinite(v) ? v : NaN;
  }
  function sortTable(table, col, type, dir) {
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll("tr"));
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


def write(all_g: pd.DataFrame, freeze: pd.DataFrame) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    books = (("Unfiltered clean break", all_g), ("Chosen filter", freeze))
    rows = []
    for label, frame in books:
        for stop in STOPS:
            rows.append((label, one_stop(frame, stop)))
    header = "".join(
        [
            _th("Book", "text"),
            _th("Stop", "num"),
            _th("N", "num"),
            _th("Avg without stop", "num"),
            _th("Avg with stop", "num"),
            _th("AnnRoR with stop", "num"),
            _th("Winners", "num"),
            _th("Winners stopped out", "num"),
            _th("Losers", "num"),
            _th("Losers capped", "num"),
            _th("Avg loss avoided on capped trades", "num"),
            _th("Shallow losers still stopped", "num"),
        ]
    )
    body = "\n".join(_row(label, st) for label, st in rows)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clean break — 1% to 4% stops</title>
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
<h1>Clean break with a 1%, 2%, 3%, or 4% stop</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Window about 2026-07-23 to 2026-09-24.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>Same buy and same window as the 1% stop check. The purchase is the next 15-minute bar’s open. The result with no stop is the close 26 fifteen-minute bars later, about one regular session. The stop looks at the lows of those same 26 bars. If any low trades at or below the stop distance under the purchase, the trade is sold at exactly that loss. A 2% stop sells at −2%, a 3% stop at −3%, a 4% stop at −4%. It does not get a worse price if the bar trades through the stop.</p>
<p>A winner is a trade that would have closed up with no stop. Getting stopped out of a winner means the dip hit the stop and we locked in that loss instead of the higher close. A loser the stop prevents from losing further is one whose close, with no stop, was worse than the stop. A shallow loser closed between zero and the stop; if the low still tagged the stop, we exit at the stop, which is a bit worse than that close.</p>
<p>Annualized rate of return (AnnRoR) is the average return with the stop, times 252. It scales the one-day move. It is not a yearly portfolio return. The chosen filter is zone age 4 to 8, a trigger from 09:30 through 11:00 Eastern including 11:00, and a close at least 20% under the prior 252-trading-day high. The zone is the busiest 15-minute candle before the 15:45 close, carried 20 trading days.</p>
</div>
<h2>Each stop</h2>
<p class="note">Click column headers to sort. “Avg loss avoided” is the average of (the stop minus the original return) on trades whose close was worse than the stop, in percentage points.</p>
<table class="sortable">
<caption>1% row repeats the earlier check. 2%, 3%, and 4% use the same path.</caption>
<thead><tr>{header}</tr></thead>
<tbody>
{body}
</tbody>
</table>
</body>
{SORT_JS}
</html>
"""
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    entry = freeze["entry"].to_numpy(dtype=float)
    low = freeze["path_low"].to_numpy(dtype=float)
    fwd = freeze["fwd26"].to_numpy(dtype=float)
    out = freeze[["symbol", "signal_datetime", "entry", "fwd26", "path_low"]].copy()
    out["AnnRoR_without_stop"] = out["fwd26"] * ANN
    for stop in STOPS:
        hit = low <= entry * (1.0 - stop) + 1e-9
        label = f"{int(stop * 100)}pct"
        out[f"return_{label}"] = np.where(hit, -stop, fwd)
        out[f"winner_stopped_{label}"] = (fwd > 0) & hit
        out[f"loser_capped_{label}"] = fwd < -stop
    out.to_csv(STAMP / "signals.csv", index=False)
    (STAMP / "BASELINE.md").write_text(
        f"""# Clean break stops at 1%, 2%, 3%, and 4%

Study id: `hv15m_cleanbreak_stop_grid_20260927`

Not gold. Not DailyRun. Same path as `hv15m_cleanbreak_stop1pct_20260927`.

## What you asked

{ASK}

Entry is the next 15-minute open. No-stop return is the close 26 bars later. A tag of the low at or below entry × (1 − stop) exits at exactly −stop.

AnnRoR = average with-stop return × 252. Scaled one-day move, not a portfolio yearly return.
""",
        encoding="utf-8",
    )


def main() -> int:
    g = attach_path(load_signals())
    missing = int((~g["path_ok"]).sum())
    if missing:
        raise SystemExit(f"path missing {missing}")
    freeze = g[g["in_freeze"]].copy()
    for label, frame in (("all", g), ("filter", freeze)):
        for stop in STOPS:
            st = one_stop(frame, stop)
            print(
                f"{label} stop={st['stop']:.0%} avg={st['avg1']:.4f} "
                f"win_stopped={st['winners_stopped']}/{st['winners']} "
                f"capped={st['losers_capped']}/{st['losers']}",
                flush=True,
            )
    write(g, freeze)
    print(f"wrote {STAMP / 'compare.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
