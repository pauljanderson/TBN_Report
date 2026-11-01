#!/usr/bin/env python3
"""Emit Trendlines_AllTF ThinkScript: same frozen M/W/D lines on any aggregation.

The live ``{SYM}_trendlines_mwd`` studies interpolate with BarNumber and require
both pivot dates on the chart. A 1-minute chart almost never loads June/July
weekly pivots, so the lines vanish (or scribble). This generator keeps the
**same** last-two fractal segments and draws them with calendar time so 1m, 2m,
4h, and Daily show the identical weekly/daily/monthly support and resistance.

Does **not** rewrite ``gen_trendlines_tos_studies.py`` (sibling may be cleaning
extra markers on the old MWD study). No SMA / Vol Zone (VZ) / HV6m / bubbles —
lines only.

Research tooling. Not gold. Not DailyRun.

  python tools/gen_trendlines_alltf_tos.py
  python tools/gen_trendlines_alltf_tos.py --symbols NVDA,SPY,TSLA
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

DEFAULT_SEGMENTS = (
    _REPO / "drive" / "paul_studies" / "trendlines_opens_latest" / "segments.json",
    _REPO / "drive" / "paul_studies" / "trendlines_tos_20260916" / "segments.json",
)
DEFAULT_STAMP = "trendline_all_tf_20260917"
DEFAULT_STAMP_DIR = _REPO / "drive" / "paul_experiments" / DEFAULT_STAMP
DEFAULT_DATA = _REPO / "data" / "newdata" / "data"

TF_RGB = {
    "monthly": (186, 104, 200),
    "weekly": (255, 152, 0),
    "daily": (0, 188, 212),
}
TF_LABEL = {"monthly": "M", "weekly": "W", "daily": "D"}
CORE_SYMBOLS = (
    "NVDA",
    "SPY",
    "TSLA",
    "AAPL",
    "AMD",
    "AMZN",
    "META",
    "MSFT",
    "AU",
    "QQQ",
)

SORTABLE_TH_CSS = """
th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
th.sortable-th:hover { background: #e2e8f0; }
th.sortable-th .sort-ind::after { content: " \\2195"; opacity: .35; font-size: .85em; }
th.sortable-th.sort-asc .sort-ind::after { content: " \\2191"; opacity: .9; }
th.sortable-th.sort-desc .sort-ind::after { content: " \\2193"; opacity: .9; }
"""

SORTABLE_TABLE_SCRIPT = r"""
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
    th.addEventListener("touchend", onActivate, { passive: false });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    table.querySelectorAll("th.sortable-th").forEach(function (th, col) {
      bindSortHeader(table, th, col);
    });
  });
})();
</script>
"""

ORIGINAL_REQUEST = (
    "also, can you make sure the trendlines show up on all charts? "
    "I am currently looking at a 4-hr chart. I want to see them also on the 1m chart"
)

LAYMAN = (
    "The weekly (and daily / monthly) support and resistance you already see on a "
    "4-hour chart should be the same lines on a 1-minute chart — not a new 1-minute "
    "scribble, and not blank. The old Thinkorswim study counted bars on whatever "
    "chart you had open, so a 1-minute window never reached the weekly pivot dates "
    "and the lines disappeared. This study stores those two pivot prices and dates "
    "and draws a straight price-versus-calendar-time line, so 1-minute, 2-minute, "
    "4-hour, and Daily all show the same geometry."
)


def _fmt_px(px: float) -> str:
    text = f"{float(px):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _ymd(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def _parse_iso(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def civil_days(ymd: int) -> int:
    """Julian-day-style serial matching the ThinkScript CivilDays script."""
    y = int(ymd) // 10000
    m = (int(ymd) % 10000) // 100
    d = int(ymd) % 100
    a = 1 if m <= 2 else 0
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    return 365 * yy + yy // 4 - yy // 100 + yy // 400 + (153 * mm + 2) // 5 + d - 32045


def _sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{html_mod.escape(label)}'
        f'<span class="sort-ind"></span></th>'
    )


def verify_civil_days() -> None:
    samples = [
        date(2020, 1, 1),
        date(2024, 2, 29),
        date(2025, 4, 7),
        date(2026, 6, 29),
        date(2026, 7, 29),
        date(2026, 9, 16),
    ]
    for a, b in zip(samples, samples[1:]):
        da = civil_days(_ymd(a))
        db = civil_days(_ymd(b))
        if (db - da) != (b - a).days:
            raise RuntimeError(f"CivilDays mismatch {a} → {b}: {db - da} vs {(b - a).days}")


def load_segments_json(paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        symbols = raw.get("symbols") or {}
        if not isinstance(symbols, dict):
            continue
        for key, rec in symbols.items():
            sym = str(key or "").strip().upper()
            segs = (rec or {}).get("segments") if isinstance(rec, dict) else None
            if sym and isinstance(segs, list) and segs and sym not in out:
                out[sym] = segs
    return out


def segs_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        tf = str(rec.get("timeframe") or "").strip().lower()
        side = str(rec.get("side") or "").strip().lower()
        if tf not in TF_LABEL or side not in ("support", "resistance"):
            continue
        try:
            d1 = _parse_iso(str(rec["d1"]))
            d2 = _parse_iso(str(rec["d2"]))
            p1 = float(rec["p1"])
            p2 = float(rec["p2"])
        except (KeyError, TypeError, ValueError):
            continue
        if d1 >= d2:
            continue
        cleaned.append(
            {"timeframe": tf, "side": side, "d1": d1, "p1": p1, "d2": d2, "p2": p2}
        )
    return cleaned


def compute_segments(symbol: str, data_dir: Path) -> list[dict[str, Any]]:
    from gen_trendlines_tos_studies import (  # noqa: WPS433
        TrendLineSeg,
        resolve_symbol,
        trendlines_for_symbol,
    )

    stamp_scratch = DEFAULT_STAMP_DIR
    stamp_scratch.mkdir(parents=True, exist_ok=True)
    _key, _tos, df, _note = resolve_symbol(symbol, data_dir, stamp_scratch)
    segs: list[TrendLineSeg] = trendlines_for_symbol(df)
    return [
        {
            "timeframe": s.timeframe,
            "side": s.side,
            "d1": s.d1,
            "p1": s.p1,
            "d2": s.d2,
            "p2": s.p2,
        }
        for s in segs
    ]


def build_thinkscript_alltf(
    *,
    symbol: str,
    stamp: str,
    segs: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        f"# {symbol} Trendlines_AllTF — stamp {stamp}",
        "# Same frozen last-two fractal M/W/D support + resistance as the MWD study,",
        "# drawn with calendar time (not BarNumber). Works on 1m, 2m, 4h, Daily.",
        "# Pivot dates do NOT need to be loaded on the chart.",
        "# Geometry matches tools/trendline_slopes_paultwenty.line_price_at (calendar days)",
        "# plus SecondsFromTime(0)/86400 so the line is continuous inside a session.",
        "# No SMA / VZ / HV6m / AddChartBubble (avoid extra markers on 1m).",
        "# Create once; add the saved study to any aggregation of this symbol.",
        "# Do not stack on top of {SYM}_trendlines_mwd (duplicate lines).",
        "",
        "declare upper;",
        "",
        "input showMonthly = yes;",
        "input showWeekly = yes;",
        "input showDaily = yes;",
        "input showSupport = yes;",
        "input showResistance = yes;",
        "input extendRight = yes;",
        "input useIntradayFraction = yes;",
        "",
        "# Civil day serial (same formula for bar / d1 / d2 so slope is consistent).",
        "script CivilDays {",
        "    input ymd = 20200101;",
        "    def y = Floor(ymd / 10000);",
        "    def m = Floor((ymd - y * 10000) / 100);",
        "    def d = ymd - y * 10000 - m * 100;",
        "    def a = if m <= 2 then 1 else 0;",
        "    def yy = y + 4800 - a;",
        "    def mm = m + 12 * a - 3;",
        "    plot days = Floor(365 * yy + Floor(yy / 4) - Floor(yy / 100) + Floor(yy / 400) + Floor((153 * mm + 2) / 5) + d - 32045);",
        "}",
        "",
        "def barYmd = GetYYYYMMDD();",
        "def barSerial = CivilDays(barYmd);",
        "def dayFrac = if useIntradayFraction then SecondsFromTime(0) / 86400 else 0;",
        "def barT = barSerial + dayFrac;",
        "",
    ]
    for tf, (r, g, b) in TF_RGB.items():
        lines.append(f'DefineGlobalColor("{tf.capitalize()}", CreateColor({r}, {g}, {b}));')
    lines.extend(
        [
            "",
            'AddLabel(yes, "Trendlines_AllTF — same M/W/D lines on 1m, 4h, Daily", Color.GRAY);',
            'AddLabel(showWeekly, "Orange solid = weekly support (buy-today)", GlobalColor("Weekly"));',
            'AddLabel(showDaily, "Cyan = daily   solid=support  dashed=resistance", GlobalColor("Daily"));',
            'AddLabel(showMonthly, "Violet = monthly", GlobalColor("Monthly"));',
            "",
        ]
    )

    if not segs:
        lines.append("# (no frozen segments for this symbol)")
        lines.append("plot _empty = Double.NaN;")
        lines.append("_empty.SetHiding(yes);")
        return "\n".join(lines) + "\n"

    for i, seg in enumerate(segs, 1):
        tf = str(seg["timeframe"])
        gname = tf.capitalize()
        show_tf = f"show{gname}"
        show_side = "showSupport" if seg["side"] == "support" else "showResistance"
        d1 = _ymd(seg["d1"])
        d2 = _ymd(seg["d2"])
        p1 = _fmt_px(float(seg["p1"]))
        p2 = _fmt_px(float(seg["p2"]))
        label = f"{TF_LABEL[tf]} {'Sup' if seg['side'] == 'support' else 'Res'}"
        style = "Curve.FIRM" if seg["side"] == "support" else "Curve.SHORT_DASH"
        weight = 3 if tf == "monthly" else (2 if tf == "weekly" else 1)
        t1 = civil_days(d1)
        t2 = civil_days(d2)
        lines.append(
            f"# {label}: {seg['d1'].isoformat()} @ {p1}  →  {seg['d2'].isoformat()} @ {p2}"
            f"  (CivilDays {t1} → {t2})"
        )
        lines.append(f"def t{i}1 = CivilDays({d1});")
        lines.append(f"def t{i}2 = CivilDays({d2});")
        lines.append(
            f"def on{i} = {show_tf} and {show_side} and t{i}2 != t{i}1 "
            f"and barYmd >= {d1} and (extendRight or barYmd <= {d2});"
        )
        lines.append(
            f"plot TL{i} = if on{i} then {p1} + ({p2} - {p1}) * "
            f"(barT - t{i}1) / (t{i}2 - t{i}1) else Double.NaN;"
        )
        lines.append(f'TL{i}.SetDefaultColor(GlobalColor("{gname}"));')
        lines.append(f"TL{i}.SetLineWeight({weight});")
        lines.append(f"TL{i}.SetStyle({style});")
        lines.append("")

    # Remove accidental duplicate SetStyle line I just added - wait I'll fix in the loop
    return "\n".join(lines) + "\n"


def apply_markdown(*, stamp: str, n_studies: int, n_segs: int) -> str:
    return f"""# How to load Trendlines_AllTF on 1m and 4h

Stamp `{stamp}`. Research / chart tooling. Not gold. Not DailyRun.

## Study name

Per symbol: `{{SYM}}_Trendlines_AllTF`  
Thinkorswim (ToS) library name to create: `{{SYM}} Trendlines AllTF`  
Example: paste `studies/NVDA_Trendlines_AllTF.ts` and name it `NVDA Trendlines AllTF`.

## Fast path (same chart, change aggregation)

The study is **not** tied to 4-hour bars. After it is saved once:

1. Open **NVDA** (or your symbol) on the **4-hour** chart.
2. **Studies → Edit Studies → Create**.
3. Paste the matching `studies/{{SYM}}_Trendlines_AllTF.ts` file. Name it `{{SYM}} Trendlines AllTF`. Save.
4. Apply it. You should see the same weekly (orange) / daily (cyan) / monthly (violet) lines as the old MWD study.
5. On **that same chart**, change aggregation to **1m** (or 2m). The study stays attached. The **same** lines stay on price — they do not need the June/July pivot bars to be in the 1m window.

## Two-chart grid (4h + 1m side by side)

Thinkorswim stores the study in the library, but each open chart has its own study list:

1. Create/save `{{SYM}} Trendlines AllTF` once (steps above).
2. On the **1-minute** chart: **Studies → Edit Studies →** add the already-saved `{{SYM}} Trendlines AllTF`.
3. On the **4-hour** chart: add the same saved study (or leave it if you created it there).

You do **not** need a second script for 1m. One paste, then add that saved study to every aggregation you care about.

## Do not stack

Remove or hide `{'{SYM}'}_trendlines_mwd` on the 1m / 4h charts after AllTF is on. Stacking both draws the same geometry twice (old BarNumber version may still be blank on 1m).

The sibling job may still be cleaning extra markers on the old MWD study. AllTF is lines-only (no Vol Zone / SMA / bubbles) so it will not add those markers.

## Toggles

- `showWeekly` / `showDaily` / `showMonthly`
- `showSupport` / `showResistance`
- `extendRight` (default on)
- `useIntradayFraction` (default on) — uses `SecondsFromTime(0)` so the line slopes inside the session instead of stepping once per calendar day

Buy-today line = orange **solid** weekly support. Turn the others off if you only want that.

## Regenerated

- Studies: {n_studies}
- Frozen segments: {n_segs}
- Generated: {datetime.now().isoformat(timespec="seconds")}
"""


def write_baseline(stamp_dir: Path, *, n_studies: int, n_segs: int) -> None:
    text = f"""# BASELINE — `{DEFAULT_STAMP}`

Research / chart tooling. Not gold. Not DailyRun. No commit.

## What you asked

{ORIGINAL_REQUEST}

## In plain English

{LAYMAN}

## Freeze (drawing change only)

| Knob | Value |
|---|---|
| Segments | Same last-two fractal swings as `{'{SYM}'}_trendlines_mwd` (daily k=5, weekly k=3, monthly k=2) |
| Fits | One support + one resistance per TF already in the product (monthly / weekly / daily). No new S/R fits. |
| Old drawing | `BarNumber` linear interp; both pivot dates must exist on the chart |
| New drawing | Calendar-day serial + optional `SecondsFromTime(0)/86400`; matches `line_price_at` |
| Overlays | None (no SMA / VZ / HV6m / bubbles) — sibling owns extra-marker cleanup on MWD |
| Universe | Frozen segments from `trendlines_opens_latest` / `trendlines_tos_20260916`, plus OHLC recompute for missing core names |
| Promotion | Research only. Not wired to DailyRun. |

## Before / after

| | Old `{'{SYM}'}_trendlines_mwd` | New `{'{SYM}'}_Trendlines_AllTF` |
|---|---|---|
| 4-hour chart with months of history | Often visible (pivot dates still on the tape) | Same prices / dates |
| 1-minute chart (days–weeks of bars) | Weekly/monthly lines usually **blank** (`HighestAll(BarNumber)` is NaN) | Same lines, no pivot bar required |
| Extra markers | SMA + VZ + HV6m + a bubble on every 1m bar of the pivot day | Lines + 4 labels only |
| Stack | — | Do not stack with MWD |

## Study name

`{{SYM}}_Trendlines_AllTF` — paste from `studies/`. How to apply: `APPLY.md`.

## Counts

- Studies written: {n_studies}
- Segments: {n_segs}
"""
    (stamp_dir / "BASELINE.md").write_text(text, encoding="utf-8")


def write_compare_html(
    stamp_dir: Path,
    *,
    stamp: str,
    rows: list[dict[str, Any]],
    notes: list[str],
) -> Path:
    def th(label: str, typ: str) -> str:
        return _sortable_th(label, typ)

    body = []
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{html_mod.escape(r['symbol'])}</td>"
            f"<td>{html_mod.escape(r['timeframe'])}</td>"
            f"<td>{html_mod.escape(r['side'])}</td>"
            f"<td>{html_mod.escape(r['d1'])}</td>"
            f"<td>{html_mod.escape(r['p1'])}</td>"
            f"<td>{html_mod.escape(r['d2'])}</td>"
            f"<td>{html_mod.escape(r['p2'])}</td>"
            f"<td><code>{html_mod.escape(r['study'])}</code></td>"
            "</tr>"
        )
    notes_html = "".join(f"<li>{html_mod.escape(n)}</li>" for n in notes)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Trendlines_AllTF — {html_mod.escape(stamp)}</title>
<style>
body {{ font-family: ui-sans-serif, system-ui, Segoe UI, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
h1 {{ font-size: 1.45rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.15rem; margin: 28px 0 8px; }}
p, li {{ line-height: 1.45; }}
.meta, .note {{ color: #475569; font-size: 0.95rem; }}
.callout {{ background: #fff; border: 1px solid #cbd5e1; border-left: 4px solid #0369a1; padding: 12px 16px; margin: 16px 0; }}
.callout h2 {{ margin-top: 0; }}
blockquote {{ margin: 8px 0; padding-left: 12px; border-left: 3px solid #94a3b8; color: #334155; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; font-size: 0.85rem; }}
table.sortable th, table.sortable td {{ border: 1px solid #e2e8f0; padding: 8px 10px; text-align: left; }}
table.sortable th {{ background: #f1f5f9; position: sticky; top: 0; }}
.wrap {{ overflow-x: auto; }}
code {{ font-size: 0.92em; }}
{SORTABLE_TH_CSS}
</style>
</head>
<body>
<h1>Trendlines_AllTF — same weekly/daily lines on 1m and 4h</h1>
<p class="meta">Stamp <code>{html_mod.escape(stamp)}</code>. Research / chart tooling. Not gold. Not DailyRun. Click column headers to sort.</p>

<div class="callout">
<h2>What you asked</h2>
<blockquote>{html_mod.escape(ORIGINAL_REQUEST)}</blockquote>
<h2>In plain English</h2>
<p>{html_mod.escape(LAYMAN)}</p>
</div>

<h2>Study name + how to load it on the 1-minute chart</h2>
<p><strong>Study:</strong> <code>{{SYM}}_Trendlines_AllTF</code> (example <code>NVDA Trendlines AllTF</code>).</p>
<ol>
<li>Thinkorswim → open the symbol → <strong>Studies → Edit Studies → Create</strong>.</li>
<li>Paste <code>drive/paul_experiments/{html_mod.escape(stamp)}/studies/NVDA_Trendlines_AllTF.ts</code> (or your symbol). Name it <code>NVDA Trendlines AllTF</code>.</li>
<li>Apply on the <strong>4-hour</strong> chart, then change that chart to <strong>1m</strong> — the study stays on and the <em>same</em> weekly/daily/monthly lines remain.</li>
<li>If 4h and 1m are <em>separate</em> grid charts: add the already-saved study on the 1m chart too. One script; each chart has its own study list.</li>
<li>Do <strong>not</strong> stack this on top of <code>{{SYM}}_trendlines_mwd</code>. Replace / hide the old one on 1m and 4h.</li>
</ol>
<p class="note">Full click path: <code>APPLY.md</code>. ToS cannot share one study instance across two open charts automatically — you add the saved study to each chart. Changing aggregation on the <em>same</em> chart keeps it.</p>

<h2>Before / after</h2>
<div class="wrap">
<table class="sortable">
<thead><tr>{th("item", "text")}{th("old MWD (BarNumber)", "text")}{th("AllTF (calendar time)", "text")}</tr></thead>
<tbody>
<tr><td>Drawing</td><td>price interpolates by bar index between the two pivot bars</td><td>price interpolates by calendar day (+ session fraction)</td></tr>
<tr><td>4-hour (months of history)</td><td>usually visible</td><td>same frozen pivot prices / dates</td></tr>
<tr><td>1-minute (short history)</td><td>weekly/monthly usually blank — pivot dates not on the tape</td><td>same lines; pivots do not need to be loaded</td></tr>
<tr><td>Markers</td><td>SMA + VZ + HV6m + bubble every 1m bar on the pivot day</td><td>lines + 4 labels only (sibling owns extra-marker cleanup on MWD)</td></tr>
<tr><td>New S/R fits</td><td>last-two fractal per TF</td><td>same segments — no extra fits</td></tr>
<tr><td>HTML 1m gallery</td><td>daily / 6m PNGs only</td><td>skipped — no <code>data/intraday/1m/</code> files here; ToS is the fix</td></tr>
</tbody>
</table>
</div>

<h2>Frozen segments in this pack</h2>
<p class="meta">{len(rows)} rows. Orange weekly support is the buy-today line. Click headers to sort.</p>
<div class="wrap">
<table class="sortable">
<thead><tr>{th("symbol", "text")}{th("timeframe", "text")}{th("side", "text")}{th("d1", "date")}{th("p1", "num")}{th("d2", "date")}{th("p2", "num")}{th("study", "text")}</tr></thead>
<tbody>
{"".join(body)}
</tbody>
</table>
</div>

<h2>Notes</h2>
<ul>
{notes_html}
<li>Generator: <code>tools/gen_trendlines_alltf_tos.py</code>. Did not edit the MWD publisher (sibling job).</li>
<li>Not gold. Not DailyRun.</li>
</ul>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""
    path = stamp_dir / "compare.html"
    path.write_text(html, encoding="utf-8")
    return path


def _parse_symbols(symbols: str, symbols_file: Path | None) -> list[str]:
    raw: list[str] = []
    if symbols_file is not None and symbols_file.is_file():
        for part in symbols_file.read_text(encoding="utf-8").replace(",", "\n").splitlines():
            tok = part.strip().upper()
            if tok:
                raw.append(tok)
    for part in str(symbols or "").split(","):
        tok = part.strip().upper()
        if tok:
            raw.append(tok)
    return list(dict.fromkeys(raw))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="", help="Comma list. Empty = all known segments + core names.")
    ap.add_argument("--symbols-file", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--stamp", default=DEFAULT_STAMP)
    ap.add_argument("--stamp-dir", type=Path, default=None)
    ap.add_argument(
        "--recompute-core",
        action="store_true",
        help="Recompute CORE_SYMBOLS from OHLC even if segments.json has them.",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    verify_civil_days()

    stamp_dir = Path(args.stamp_dir) if args.stamp_dir else (_REPO / "drive" / "paul_experiments" / args.stamp)
    stamp_dir.mkdir(parents=True, exist_ok=True)
    studies_dir = stamp_dir / "studies"
    studies_dir.mkdir(parents=True, exist_ok=True)

    cached = load_segments_json(list(DEFAULT_SEGMENTS))
    requested = _parse_symbols(args.symbols, args.symbols_file)
    if not requested:
        requested = list(dict.fromkeys([*CORE_SYMBOLS, *sorted(cached.keys())]))

    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    meta: dict[str, Any] = {
        "stamp": args.stamp,
        "study": "Trendlines_AllTF",
        "drawing": "calendar_time_civil_days",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "symbols": {},
    }

    for raw in requested:
        sym = raw.strip().upper()
        if not sym:
            continue
        segs: list[dict[str, Any]] = []
        source = "segments.json"
        if args.recompute_core and sym in CORE_SYMBOLS:
            try:
                segs = compute_segments(sym, Path(args.data_dir))
                source = "ohlc_recompute"
            except Exception as exc:  # noqa: BLE001 — keep going
                notes.append(f"{sym}: OHLC recompute failed ({exc}); falling back to cache")
                segs = segs_from_records(cached.get(sym) or [])
                source = "segments.json_fallback"
        elif sym in cached:
            segs = segs_from_records(cached[sym])
        if not segs:
            try:
                segs = compute_segments(sym, Path(args.data_dir))
                source = "ohlc_recompute"
            except Exception as exc:  # noqa: BLE001
                notes.append(f"SKIP {sym}: no segments ({exc})")
                print(f"[skip] {sym}: {exc}")
                continue
        ts_name = f"{sym}_Trendlines_AllTF.ts"
        text = build_thinkscript_alltf(symbol=sym, stamp=args.stamp, segs=segs)
        (studies_dir / ts_name).write_text(text, encoding="utf-8")
        meta["symbols"][sym] = {
            "study": ts_name,
            "source": source,
            "n_segments": len(segs),
            "segments": [
                {
                    "timeframe": s["timeframe"],
                    "side": s["side"],
                    "d1": s["d1"].isoformat(),
                    "p1": s["p1"],
                    "d2": s["d2"].isoformat(),
                    "p2": s["p2"],
                }
                for s in segs
            ],
        }
        for s in segs:
            rows.append(
                {
                    "symbol": sym,
                    "timeframe": s["timeframe"],
                    "side": s["side"],
                    "d1": s["d1"].isoformat(),
                    "p2": _fmt_px(float(s["p2"])),
                    "p1": _fmt_px(float(s["p1"])),
                    "d2": s["d2"].isoformat(),
                    "study": ts_name,
                }
            )
        print(f"[ok] {sym}: {len(segs)} lines ({source}) -> {ts_name}")

    notes.insert(
        0,
        f"Wrote {len(meta['symbols'])} AllTF studies; {len(rows)} frozen segments. "
        "HTML 1m overlay skipped (no data/intraday/1m/ in this workspace).",
    )
    (stamp_dir / "segments.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (stamp_dir / "APPLY.md").write_text(
        apply_markdown(stamp=args.stamp, n_studies=len(meta["symbols"]), n_segs=len(rows)),
        encoding="utf-8",
    )
    write_baseline(stamp_dir, n_studies=len(meta["symbols"]), n_segs=len(rows))
    html_path = write_compare_html(stamp_dir, stamp=args.stamp, rows=rows, notes=notes)
    print(f"[ok] HTML {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
