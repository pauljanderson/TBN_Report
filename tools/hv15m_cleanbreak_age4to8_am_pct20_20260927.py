#!/usr/bin/env python3
"""Research freeze: clean break, zone age 4–8, trigger 09:30–11:00, at least 20% under the 252-day high.

Chosen after seeing the short 2026 window. Not gold. Not DailyRun.
"""
from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "drive" / "paul_experiments" / "hv15m_age4to8_pct252_20260927" / "signals.csv"
STAMP = ROOT / "drive" / "paul_experiments" / "hv15m_cleanbreak_age4to8_am_pct20_20260927"

HALF_CUT = "2026-08-24"
N_CARRY = 20
ZONE_RULE = "ex_last_bar"
PATTERN = "clean_break_highest"
AGES = (4, 5, 6, 7, 8)
MORNING = ("09:30", "09:45", "10:00", "10:15", "10:30", "10:45", "11:00")
PCT_FLOOR = 0.20
ANN_ROR_DAYS = 252
HOLDING_TRADING_DAYS = 1

ASK_1 = "i like this filter on the clean break of the highest zone"
ASK_2 = "Age 4–8, 09:30–11:00, and 20% or more below"


def _pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{100.0 * float(x):.{digits}f}%"


def _ann(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return _pct(float(x) * (ANN_ROR_DAYS / HOLDING_TRADING_DAYS), digits)


def _stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    if n == 0:
        return {
            "n": 0,
            "symbols": 0,
            "days": 0,
            "win": None,
            "avg": None,
            "med": None,
            "ann": None,
        }
    fwd = g["fwd26"].to_numpy(dtype=float)
    return {
        "n": n,
        "symbols": int(g["symbol"].nunique()),
        "days": int(g["day"].nunique()),
        "win": float((fwd > 0).mean()),
        "avg": float(np.nanmean(fwd)),
        "med": float(np.nanmedian(fwd)),
        "ann": float(np.nanmean(fwd) * (ANN_ROR_DAYS / HOLDING_TRADING_DAYS)),
    }


def _th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{html.escape(label)}<span class="sort-ind"></span></th>'
    )


def _row(label: str, st: dict) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(label)}</td>"
        f"<td>{st['n']}</td>"
        f"<td>{st['symbols']}</td>"
        f"<td>{st['days']}</td>"
        f"<td>{_pct(st['win'])}</td>"
        f"<td>{_pct(st['avg'])}</td>"
        f"<td>{_ann(st['avg'])}</td>"
        f"<td>{_pct(st['med'])}</td>"
        "</tr>"
    )


def load_clean() -> pd.DataFrame:
    df = pd.read_csv(SOURCE)
    g = df[
        (df["pattern"] == PATTERN)
        & (df["N"] == N_CARRY)
        & (df["zone_rule"] == ZONE_RULE)
    ].copy()
    g["zone_age"] = pd.to_numeric(g["zone_age"], errors="coerce")
    g["pct_below_252d_high_at_signal_close"] = pd.to_numeric(
        g["pct_below_252d_high_at_signal_close"], errors="coerce"
    )
    g["fwd26"] = pd.to_numeric(g["fwd26"], errors="coerce")
    g["trigger_bar_time_et"] = g["signal_time_et"].astype(str)
    g["in_age_4_8"] = g["zone_age"].isin(AGES)
    g["morning_gate"] = g["trigger_bar_time_et"].isin(MORNING)
    g["pct_20_plus"] = g["pct_below_252d_high_at_signal_close"] >= PCT_FLOOR
    g["in_freeze"] = g["in_age_4_8"] & g["morning_gate"] & g["pct_20_plus"]
    g["later_half"] = np.where(g["day"].astype(str) >= HALF_CUT, "yes", "no")
    g["AnnRoR"] = g["fwd26"] * (ANN_ROR_DAYS / HOLDING_TRADING_DAYS)
    g["signal_datetime"] = g["signal_day"].astype(str) + " " + g["trigger_bar_time_et"]
    return g


def export_cols(g: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "symbol": g["symbol"],
            "signal_datetime": g["signal_datetime"],
            "entry_date": g["day"].astype(str),
            "trigger_bar_time_et": g["trigger_bar_time_et"],
            "zone_date": g["zone_date"],
            "zone_age": g["zone_age"],
            "zone_lo": g["zone_lo"],
            "zone_hi": g["zone_hi"],
            "signal_close": g["signal_close"],
            "pct_below_252d_high_at_signal_close": g["pct_below_252d_high_at_signal_close"],
            "forward_return": g["fwd26"],
            "AnnRoR": g["AnnRoR"],
            "later_half": g["later_half"],
        }
    )
    return out.sort_values(["signal_datetime", "symbol"])


def verdict(full: dict, late: dict) -> tuple[str, str]:
    """HOLD when N is tiny or the later half is soft. Never KEEP for DailyRun."""
    if full["n"] == 0:
        return (
            "The combined filter produced no signals on this window. There is no book to study.",
            "empty — not a research candidate",
        )
    late_soft = (
        late["n"] > 0
        and late["avg"] is not None
        and (late["avg"] <= 0 or (late["med"] is not None and late["med"] < 0))
    )
    tiny = full["n"] < 40 or late["n"] < 15
    bits = [
        f"Combined freeze: {full['n']} signals, average next-session {_pct(full['avg'])}, "
        f"median {_pct(full['med'])}, AnnRoR {_ann(full['avg'])}.",
        f"Unfiltered clean break is the control on the same carry.",
        f"Entries on or after {HALF_CUT}: {late['n']} signals, average {_pct(late['avg'])}, "
        f"median {_pct(late['med'])}.",
    ]
    if tiny and late_soft:
        tag = "HOLD"
        bits.append(
            "HOLD. The sample is tiny and the later half is soft. "
            "That later half is report-only. Do not retune the filter to fix it."
        )
    elif tiny:
        tag = "HOLD"
        bits.append(
            "HOLD. The combined book is not empty, but it is too small to treat as confirmed, "
            f"and the later half is only {late['n']} signals. "
            "A positive later-half average on a handful of trades is not confirmation. "
            "Do not retune the cutoff on this window."
        )
    elif late_soft:
        tag = "HOLD"
        bits.append(
            "HOLD. The later half is softer than the full window. "
            "Do not retune the filter to fix that. This choice was already made after seeing the same history."
        )
    else:
        tag = "research candidate"
        bits.append(
            "Research candidate only. Chosen after seeing this same short window, so it is in-sample selection. "
            "Not gold. Not wired into DailyRun."
        )
    bits.append("Not gold. Not a DailyRun keep.")
    return " ".join(bits), tag


def write_reports(g: pd.DataFrame) -> None:
    STAMP.mkdir(parents=True, exist_ok=True)
    freeze = g[g["in_freeze"]].copy()
    arms = [
        ("Unfiltered clean break", g),
        ("Age 4–8 only", g[g["in_age_4_8"]]),
        ("Trigger 09:30–11:00 only", g[g["morning_gate"]]),
        ("20% or more below the 252-day high only", g[g["pct_20_plus"]]),
        ("Combined freeze: age 4–8 and 09:30–11:00 and 20%+ below", freeze),
        (
            f"Combined freeze, entries before {HALF_CUT} (report only)",
            freeze[freeze["later_half"] == "no"],
        ),
        (
            f"Combined freeze, entries on or after {HALF_CUT}",
            freeze[freeze["later_half"] == "yes"],
        ),
    ]
    stats = [(label, _stats(sub)) for label, sub in arms]
    full = stats[4][1]
    late = stats[6][1]
    prose, tag = verdict(full, late)
    raw = stats[0][1]

    header = "".join(
        [
            _th("Slice", "text"),
            _th("Signals", "num"),
            _th("Symbols", "num"),
            _th("Days", "num"),
            _th("Win %", "num"),
            _th("Avg next session", "num"),
            _th("AnnRoR", "num"),
            _th("Median", "num"),
        ]
    )
    body = "".join(_row(label, st) for label, st in stats)

    signal_rows = []
    show = freeze.sort_values(["signal_datetime", "symbol"])
    for rec in show.itertuples(index=False):
        signal_rows.append(
            "<tr>"
            f"<td>{html.escape(str(rec.symbol))}</td>"
            f"<td>{html.escape(str(rec.signal_datetime))}</td>"
            f"<td>{html.escape(str(rec.trigger_bar_time_et))}</td>"
            f"<td>{int(rec.zone_age) if rec.zone_age == rec.zone_age else '—'}</td>"
            f"<td>{_pct(rec.pct_below_252d_high_at_signal_close)}</td>"
            f"<td>{_pct(rec.fwd26)}</td>"
            f"<td>{_ann(rec.fwd26)}</td>"
            f"<td>{html.escape(str(rec.later_half))}</td>"
            "</tr>"
        )
    sig_header = "".join(
        [
            _th("Symbol", "text"),
            _th("Signal", "text"),
            _th("Trigger bar", "text"),
            _th("Zone age", "num"),
            _th("% below 252-day high", "num"),
            _th("Next session", "num"),
            _th("AnnRoR", "num"),
            _th("Later half", "text"),
        ]
    )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Clean break freeze — age 4–8, morning, 20% under the yearly high</title>
<style>
body {{ font-family: system-ui, Segoe UI, sans-serif; margin: 24px auto; max-width: 1100px; padding: 0 16px 48px; color: #0f172a; line-height: 1.45; }}
h1 {{ font-size: 1.45rem; }}
h2 {{ font-size: 1.15rem; margin-top: 1.6rem; }}
.callout {{ background: #f8fafc; border-left: 4px solid #2563eb; padding: 12px 16px; margin: 12px 0 16px; }}
.callout.plain {{ border-left-color: #059669; }}
.callout.warn {{ border-left-color: #b45309; background: #fffbeb; }}
.note {{ color: #334155; font-size: 0.95rem; }}
table.sortable {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; margin: 8px 0 18px; }}
th, td {{ border-bottom: 1px solid #e2e8f0; text-align: right; padding: 8px; }}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
caption {{ text-align: left; font-weight: 600; margin: 6px 0; }}
th.sortable-th {{ cursor: pointer; user-select: none; white-space: nowrap; }}
th.sortable-th:hover {{ background: #e2e8f0; }}
th.sortable-th .sort-ind::after {{ content: " \\2195"; opacity: .35; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " \\2191"; opacity: .9; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " \\2193"; opacity: .9; }}
</style>
</head>
<body>
<h1>Clean break of the highest zone — chosen filter</h1>
<p class="note">Research only. Not gold. Not wired into DailyRun. Not the daily Volume Zone (VZ) system. Window about 2026-07-23 to 2026-09-24. In-sample selection on that same window.</p>
<div class="callout">
<h2 style="margin-top:0">What you asked</h2>
<p>{html.escape(ASK_1)}</p>
<p>{html.escape(ASK_2)}</p>
</div>
<div class="callout plain">
<h2 style="margin-top:0">In plain English</h2>
<p>You liked one row from the clean-break compare: keep a buy only when the zone is 4, 5, 6, 7, or 8 trading days old, the trigger candle starts from 9:30 through 11:00 Eastern (the 11:00 candle counts), and the stock’s close is at least 20% under its high of the past year. This page freezes those three gates together. Each gate is also shown by itself so the mix is not a black box.</p>
<p>The zone is the low-to-high of the day’s busiest 15-minute candle before the 15:45 close. If the close is the busiest candle, the next-busiest earlier candle is the zone. That zone stays active for 20 trading days. A clean break means the whole 15-minute bar is above the highest active zone, the prior close was not, and it is the first time for that zone. The buy is the next 15-minute open. Zone age counts trading sessions after the zone’s own day. Age 4 is the fourth session after that day.</p>
<p>The “20% or more below” figure uses the prior 252 trading days, not counting the signal day. Take the highest daily high in that window, subtract the signal candle’s close, and divide by that high. At least 20% below means this result is 0.20 or larger. A bigger number means further below that high. A negative number means the close is already above it, so the gate fails.</p>
<p>Annualized rate of return (AnnRoR) is the next-session return multiplied by 252. It scales that one-day move. It is not compound growth and not a yearly portfolio return. A large AnnRoR does not change the verdict.</p>
</div>
<div class="callout warn">
<h2 style="margin-top:0">Selection bias</h2>
<p>This combination was picked after looking at the same short 2026 window. That is in-sample selection. The split at {HALF_CUT} is only a caution check inside this sample. It is not a 2024 holdout, and it was not used to change the filter.</p>
</div>
<h2>Verdict</h2>
<p>{html.escape(prose)}</p>
<p>Tag: <strong>{html.escape(tag)}</strong>.</p>
<p class="note">Click column headers to sort. The average is from the buy to the close 26 fifteen-minute bars later (about one regular session). AnnRoR sits beside that average.</p>
<h2>Gates, then the freeze</h2>
<table class="sortable">
<caption>Unfiltered clean break, each gate alone, then all three together. Carry is 20 trading days.</caption>
<thead><tr>{header}</tr></thead>
<tbody>
{body}
</tbody>
</table>
<h2>Signals in the freeze</h2>
<p class="note">{full['n']} rows. The same list is signals.csv. Later half means the entry date is on or after {HALF_CUT}.</p>
<table class="sortable">
<caption>Every combined-freeze signal on this window.</caption>
<thead><tr>{sig_header}</tr></thead>
<tbody>
{"".join(signal_rows)}
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
    (STAMP / "compare.html").write_text(page, encoding="utf-8")

    baseline = f"""# Research baseline — clean-break freeze

Study id: `hv15m_cleanbreak_age4to8_am_pct20_20260927`

Not gold. Not DailyRun. Not the daily Volume Zone (VZ) system.

## What you asked

> {ASK_1}

> {ASK_2}

## In plain English

Keep a clean break of the highest zone only when the zone is 4 to 8 trading days old, the trigger candle starts from 9:30 through 11:00 Eastern (11:00 included), and the signal close is at least 20% under the high of the prior 252 trading days. Each gate is also shown alone. Annualized rate of return (AnnRoR) is the next-session return times 252. That scales the one-day move. It is not a yearly portfolio return.

## Selection bias

This combination was chosen after seeing results on the same window, about 2026-07-23 through 2026-09-24. That is in-sample selection. There is no pre-2024 history, so no 2024 in-sample / out-of-sample split is invented. Entries on or after {HALF_CUT} are a caution row only. They do not change the freeze.

## Freeze

- Pattern: **clean break of the highest active zone**. The whole 15-minute bar sits above that zone’s high, the prior close did not, and it is the first break of that zone. Fill is the next 15-minute open.
- Zone: low to high of the day’s busiest 15-minute candle **before 15:45**. If the 15:45 bar is busiest, the busiest earlier candle is used. Carry: **20 trading sessions**. Same book as the age and morning compare (`hv15m_age4to8_pct252_20260927`).
- Zone age: exactly 4, 5, 6, 7, or 8 trading sessions after the zone’s birth day.
- Morning gate: trigger bar starts at 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, or 11:00 US/Eastern. The 11:00 bar is included. 11:15 and later are out.
- At least 20% below the prior 252-trading-day high. Formula: (highest daily high of the 252 trading days strictly before the signal date, minus the signal candle’s close) divided by that high. The gate is that result at least 0.20. Missing history does not pass.
- Score: next-session return (26 fifteen-minute bars). AnnRoR = that return × 252 / 1. Simple annualization of the one-day move. Not compound. Not a portfolio equity curve.
- `signals.csv` is this freeze only. `signals_all_clean_break.csv` is every clean break on the same carry, with gate flags, so the control can be checked.

## Headline

- Unfiltered clean break: {raw['n']} signals, average {_pct(raw['avg'])}, median {_pct(raw['med'])}, AnnRoR {_ann(raw['avg'])}.
- Combined freeze: {full['n']} signals, average {_pct(full['avg'])}, median {_pct(full['med'])}, AnnRoR {_ann(full['avg'])}.
- Combined freeze on or after {HALF_CUT}: {late['n']} signals, average {_pct(late['avg'])}, median {_pct(late['med'])}.

Verdict tag: {tag}.
"""
    (STAMP / "BASELINE.md").write_text(baseline, encoding="utf-8")

    summary = f"""# Summary — clean-break freeze

## What you asked

> {ASK_1}

> {ASK_2}

## In plain English

One clean-break filter: zone age 4 through 8, trigger from the 9:30 candle through the 11:00 candle, and a close at least 20% under the prior year’s high. Carry is 20 trading days. Annualized rate of return (AnnRoR) is the next-session return multiplied by 252, a scaled one-day move, not a yearly portfolio return.

## Verdict

{prose}

Tag: {tag}.

- Unfiltered clean break: {raw['n']} signals, average {_pct(raw['avg'])}, median {_pct(raw['med'])}, AnnRoR {_ann(raw['avg'])}.
- Combined freeze: {full['n']} signals, average {_pct(full['avg'])}, median {_pct(full['med'])}, AnnRoR {_ann(full['avg'])}.
- Later half (entry on or after {HALF_CUT}): {late['n']} signals, average {_pct(late['avg'])}, median {_pct(late['med'])}, AnnRoR {_ann(late['avg'])}.

Research only. Not gold. Not DailyRun.
"""
    (STAMP / "SUMMARY.md").write_text(summary, encoding="utf-8")
    print(f"wrote {STAMP / 'compare.html'}", flush=True)
    print(tag, flush=True)
    for label, st in stats:
        print(f"  {label}: n={st['n']} avg={_pct(st['avg'])} med={_pct(st['med'])} ann={_ann(st['avg'])}", flush=True)


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"missing source signals {SOURCE}")
    g = load_clean()
    STAMP.mkdir(parents=True, exist_ok=True)
    freeze = export_cols(g[g["in_freeze"]])
    all_rows = export_cols(g)
    flags = g[
        [
            "symbol",
            "signal_datetime",
            "in_age_4_8",
            "morning_gate",
            "pct_20_plus",
            "in_freeze",
        ]
    ]
    all_rows = all_rows.merge(
        flags,
        on=["symbol", "signal_datetime"],
        how="left",
    )
    freeze_path = STAMP / "signals.csv"
    all_path = STAMP / "signals_all_clean_break.csv"
    freeze.to_csv(freeze_path, index=False)
    all_rows.to_csv(all_path, index=False)
    print(f"wrote {freeze_path} rows {len(freeze)}", flush=True)
    print(f"wrote {all_path} rows {len(all_rows)}", flush=True)
    write_reports(g)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
