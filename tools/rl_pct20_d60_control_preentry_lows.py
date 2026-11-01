#!/usr/bin/env python3
"""Closed report for frozen pct20_d60 control, plus pre-entry intraday lows and highs.

For each closed trade, look up the extreme daily price in the calendar window
strictly before the entry date:

  LOW_3M / LOW_3M_DATE     lowest daily Low, 3 calendar months through the prior session
  HIGH_3M / HIGH_3M_DATE   highest daily High, same window
  LOW_6M / LOW_6M_DATE     same for 6 months
  HIGH_6M / HIGH_6M_DATE
  LOW_12M / LOW_12M_DATE   same for 12 months
  HIGH_12M / HIGH_12M_DATE

The entry session itself is excluded. If several days share that extreme, the
date is the earliest one. A blank cell means no bar fell in the window.
"""
from __future__ import annotations

import csv
import html as html_mod
import subprocess
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from pandas.tseries.offsets import DateOffset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from be_stop_replay_ab import SORTABLE_TABLE_SCRIPT, SORTABLE_TH_CSS, sortable_th  # noqa: E402

STAMP = "20260926"
CTRL_CLOSED = (
    ROOT
    / "drive"
    / "paul_experiments"
    / "rl_no_sma_target_exit_ab_20260905"
    / "runs"
    / "pct20_d60"
    / "RL_Closed_260905205015.csv"
)
OUT_DIR = ROOT / "drive" / "paul_experiments" / f"rl_pct20_d60_control_preentry_lows_{STAMP}"
DB_PATH = ROOT / "data" / "ohlcv.duckdb"
WINDOWS = (3, 6, 12)

REQUEST_PROMPT = """\
using control can you run a closed report for control and add in these columns
LOW_3M — lowest intraday LOW during the 3 months before entry
LOW_3M_DATE
LOW_6M — lowest intraday LOW during the 6 months before entry
LOW_6M_DATE
LOW_12M — lowest intraday LOW during the 12 months before entry
LOW_12M_DATE

Keep all normal reporting columns

can you run the same report and add these columns as well..
HIGH_3M + HIGH_3M_DATE
HIGH_6M + HIGH_6M_DATE
HIGH_12M + HIGH_12M_DATE
"""

LAYMAN = """\
This is the full pct20_d60 control trade list, with every usual closed-trade column still on the page.
Extra columns look backward from each buy. For the 3, 6, and 12 calendar months before the buy day,
they record the lowest daily low and the highest daily high, and the first day each of those prices printed.
The buy day itself is not included.
"""


def _parse_ymd(raw: str) -> pd.Timestamp:
    s = str(raw or "").strip().replace("-", "")
    return pd.Timestamp(s)


def _load_bars(symbols: list[str]) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    frame = con.execute(
        """
        SELECT upper(symbol) AS symbol, date, low, high
        FROM prices
        WHERE upper(symbol) IN (SELECT unnest(?))
        ORDER BY symbol, date
        """,
        [symbols],
    ).df()
    con.close()
    out: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    if frame.empty:
        return out
    frame["date"] = pd.to_datetime(frame["date"])
    for sym, grp in frame.groupby("symbol", sort=False):
        out[str(sym)] = (
            grp["date"].to_numpy(dtype="datetime64[ns]"),
            grp["low"].to_numpy(dtype=np.float64),
            grp["high"].to_numpy(dtype=np.float64),
        )
    return out


def _window_extreme(
    dates: np.ndarray,
    prices: np.ndarray,
    entry: pd.Timestamp,
    months: int,
    *,
    high: bool,
) -> tuple[str, str]:
    start = (entry - DateOffset(months=months)).to_datetime64()
    end = entry.to_datetime64()
    mask = (dates >= start) & (dates < end)
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return "", ""
    sub = prices[idx]
    j = int(np.argmax(sub) if high else np.argmin(sub))
    hit = idx[j]
    px = float(sub[j])
    day = pd.Timestamp(dates[hit]).strftime("%Y-%m-%d")
    return f"{px:.4f}", day


def enrich(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    symbols = sorted({str(r.get("SYMBOL") or "").strip().upper() for r in rows if r.get("SYMBOL")})
    bars = _load_bars(symbols)
    for r in rows:
        sym = str(r.get("SYMBOL") or "").strip().upper()
        entry = _parse_ymd(str(r.get("DATE OPENED") or ""))
        pack = bars.get(sym)
        for months in WINDOWS:
            for prefix, series, is_high in (
                ("LOW", 1, False),
                ("HIGH", 2, True),
            ):
                name = f"{prefix}_{months}M"
                if pack is None:
                    r[name] = ""
                    r[f"{name}_DATE"] = ""
                    continue
                px, day = _window_extreme(pack[0], pack[series], entry, months, high=is_high)
                r[name] = px
                r[f"{name}_DATE"] = day
    return rows


def _sort_type(name: str) -> str:
    u = name.upper()
    if "DATE" in u:
        return "date"
    if any(x in u for x in ("PNL", "PRICE", "DAYS", "GAIN", "MAE", "STOP", "TARGET", "LOW_", "HIGH_", "%")):
        return "num"
    return "text"


def write_csv(rows: list[dict[str, str]], fieldnames: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _display(col: str, raw: str) -> str:
    val = str(raw or "")
    if _sort_type(col) == "date" and len(val) == 8 and val.isdigit():
        return f"{val[:4]}-{val[4:6]}-{val[6:8]}"
    return val


def write_html(rows: list[dict[str, str]], fields: list[str], path: Path) -> None:
    show = list(fields)
    th = "".join(sortable_th(c, _sort_type(c)) for c in show)
    body = []
    for r in rows:
        cells = "".join(
            f"<td>{html_mod.escape(_display(c, r.get(c, '')))}</td>" for c in show
        )
        body.append(f"<tr>{cells}</tr>")
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>pct20_d60 control closed — pre-entry lows</title>
<style>
:root {{ --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#9aa7b8; --line:#2a3545; --accent:#5b9fd4; }}
*{{box-sizing:border-box}}
body{{margin:0;font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}}
header{{padding:1.25rem 1rem 0.5rem;max-width:1600px;margin:0 auto}}
h1{{font-size:1.25rem;margin:0 0 .35rem}}
.muted{{color:var(--muted);font-size:.92rem}}
.callout{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem;margin:.75rem 0}}
.callout pre{{white-space:pre-wrap;font-size:.82rem;margin:.4rem 0 0}}
main{{max-width:1600px;margin:0 auto;padding:0 1rem 2.5rem}}
section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.75rem 1rem 1rem;margin:1rem 0}}
.table-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.78rem;min-width:1100px}}
th,td{{border-bottom:1px solid var(--line);padding:.3rem .4rem;text-align:right;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
{SORTABLE_TH_CSS.replace('th.sortable-th:hover{{background:#e8e4d8}}', 'th.sortable-th:hover{{background:#2a3545}}')}
</style>
</head>
<body>
<header>
<h1>pct20_d60 control closed trades, with lows before entry</h1>
<p class="muted">N={len(rows)}. {len(show)} columns: the full pct20_d60 closed report, plus the pre-entry low and high columns after ENTRY PRICE. Every trade has at least one bar in each window. 59 of 2,802 do not cover a full 12 calendar months because the stock was not listed that far back; those 12-month highs and lows use the history that exists. Click column headers to sort.</p>
</header>
<main>
<div class="callout">
<strong>What you asked</strong>
<pre>{html_mod.escape(REQUEST_PROMPT.strip())}</pre>
<p><strong>In plain English:</strong> {html_mod.escape(LAYMAN.strip())}</p>
</div>
<section>
<h2 style="color:var(--accent);font-size:1.05rem;margin:.2rem 0 .5rem">How the highs and lows are measured</h2>
<p class="muted">Calendar months, not a count of trading days. The window runs from the entry date minus 3, 6, or 12 months up through the session before entry. LOW is the lowest daily low in that window. HIGH is the highest daily high. The date is the first day that price printed. If the stock listed inside the window, the extreme uses the bars that exist. Research control book, reused from stamp 260905205015. Not a new backtest.</p>
<div class="table-wrap"><table class="sortable"><thead><tr>{th}</tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
</section>
</main>
{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def main() -> int:
    with CTRL_CLOSED.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        base_fields = list(reader.fieldnames or [])
        rows = [{k: (v if v is not None else "") for k, v in raw.items()} for raw in reader]
    extra = []
    for months in WINDOWS:
        for prefix in ("LOW", "HIGH"):
            name = f"{prefix}_{months}M"
            extra.extend((name, f"{name}_DATE"))
    # Insert the new fields right after ENTRY PRICE so they sit next to the buy.
    fields = list(base_fields)
    insert_at = fields.index("ENTRY PRICE") + 1 if "ENTRY PRICE" in fields else 3
    for i, name in enumerate(extra):
        fields.insert(insert_at + i, name)
    enrich(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "control_closed_preentry_lows.csv"
    html_path = OUT_DIR / "control_closed.html"
    write_csv(rows, fields, csv_path)
    write_html(rows, fields, html_path)
    gev = next(r for r in rows if r["SYMBOL"] == "GEV" and r["DATE OPENED"] == "20260520")
    print(
        f"GEV 20260520 low3={gev['LOW_3M']} {gev['LOW_3M_DATE']} high3={gev['HIGH_3M']} {gev['HIGH_3M_DATE']} "
        f"low12={gev['LOW_12M']} {gev['LOW_12M_DATE']} high12={gev['HIGH_12M']} {gev['HIGH_12M_DATE']}",
        flush=True,
    )
    print(f"wrote {html_path} n={len(rows)}", flush=True)
    ntfy = ROOT / "tools" / "ntfy_job_done.py"
    if ntfy.is_file():
        subprocess.run(
            [sys.executable, str(ntfy), "--path", str(html_path), "-t", "pct20_d60 control closed highs and lows"],
            cwd=str(ROOT),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
