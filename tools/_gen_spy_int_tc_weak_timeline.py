#!/usr/bin/env python3
"""Generate SPY_INT_TC_WEAK_TIMELINE.html from SPY_INT_TC_REGIME*.csv."""
from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "drive" / "paul_experiments" / "rs_oneil_filters"
DAILY_PATH = OUT / "SPY_INT_TC_REGIME.csv"
RANGES_PATH = OUT / "SPY_INT_TC_REGIME_RANGES.csv"
HTML_PATH = OUT / "SPY_INT_TC_WEAK_TIMELINE.html"

COLORS = {"Strong": "#2f9e44", "Neutral": "#f59f00", "Weak": "#e03131"}


def parse_d(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def main() -> None:
    daily: list[dict] = []
    with open(DAILY_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            daily.append(row)

    ranges: list[dict] = []
    with open(RANGES_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["n_days"] = int(row["n_days"])
            ranges.append(row)

    for r in ranges:
        s, e = parse_d(r["start_date"]), parse_d(r["end_date"])
        r["calendar_days"] = (e - s).days + 1

    with open(RANGES_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["outlook", "start_date", "end_date", "n_days", "calendar_days"]
        )
        w.writeheader()
        w.writerows(ranges)

    counts = {"Strong": 0, "Neutral": 0, "Weak": 0}
    for row in daily:
        lab = row["IND_TC_INT_OUTLOOK"]
        counts[lab] = counts.get(lab, 0) + 1

    n_sess = len(daily)
    weak_ranges = [r for r in ranges if r["outlook"] == "Weak"]
    weak_sess = counts.get("Weak", 0)
    weak_pct = 100.0 * weak_sess / n_sess if n_sess else 0.0
    start_all = daily[0]["date"]
    end_all = daily[-1]["date"]
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    pct = {k: 100.0 * counts.get(k, 0) / n_sess for k in ("Strong", "Neutral", "Weak")}
    latest = ranges[-1]

    years: dict[str, dict[str, int]] = {}
    for row in daily:
        y = row["date"][:4]
        years.setdefault(y, {"Strong": 0, "Neutral": 0, "Weak": 0})
        years[y][row["IND_TC_INT_OUTLOOK"]] += 1
    year_list = sorted(years.keys())

    # --- Timeline SVG ---
    W, H = 1100, 220
    pad_l, pad_r, pad_t = 56, 24, 36
    plot_w = W - pad_l - pad_r
    t0 = parse_d(start_all).timestamp()
    t1 = parse_d(end_all).timestamp()
    span = max(t1 - t0, 1.0)

    def x_of(date_s: str) -> float:
        return pad_l + (parse_d(date_s).timestamp() - t0) / span * plot_w

    band_y = pad_t + 20
    band_h = 48
    bands: list[str] = []
    for r in ranges:
        x1 = x_of(r["start_date"])
        x2 = x_of(r["end_date"])
        w = max(x2 - x1, 1.2)
        title = (
            f"{r['outlook']}: {r['start_date']} → {r['end_date']} "
            f"({r['n_days']} sess, {r['calendar_days']} cal)"
        )
        opacity = 0.95 if r["outlook"] == "Weak" else 0.55
        bands.append(
            f'<rect x="{x1:.2f}" y="{band_y}" width="{w:.2f}" height="{band_h}" '
            f'fill="{COLORS[r["outlook"]]}" opacity="{opacity}" rx="1">'
            f"<title>{html.escape(title)}</title></rect>"
        )

    ticks: list[str] = []
    labels: list[str] = []
    for y in year_list:
        if int(y) % 2 == 1 and y not in (year_list[0], year_list[-1]):
            continue
        xd = pad_l if y == year_list[0] else x_of(f"{y}-01-01")
        ticks.append(
            f'<line x1="{xd:.1f}" y1="{band_y + band_h}" x2="{xd:.1f}" '
            f'y2="{band_y + band_h + 8}" stroke="#868e96" stroke-width="1"/>'
        )
        labels.append(
            f'<text x="{xd:.1f}" y="{band_y + band_h + 24}" text-anchor="middle" '
            f'class="tick">{y}</text>'
        )

    weak_row_y = band_y + band_h + 36
    weak_marks: list[str] = []
    for r in weak_ranges:
        x1 = x_of(r["start_date"])
        x2 = x_of(r["end_date"])
        w = max(x2 - x1, 1.5)
        title = (
            f"Weak {r['start_date']} → {r['end_date']} · "
            f"{r['n_days']} sessions · {r['calendar_days']} calendar days"
        )
        weak_marks.append(
            f'<rect x="{x1:.2f}" y="{weak_row_y}" width="{w:.2f}" height="14" '
            f'fill="#e03131" opacity="0.85" rx="2">'
            f"<title>{html.escape(title)}</title></rect>"
        )

    timeline_svg = f"""<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="SPY intermediate TC regime timeline">
  <text x="{pad_l}" y="22" class="svg-title">SPY IND_TC_INT_OUTLOOK · {start_all} → {end_all}</text>
  <text x="{W - pad_r}" y="22" text-anchor="end" class="svg-sub">{n_sess:,} sessions</text>
  <rect x="{pad_l}" y="{band_y}" width="{plot_w}" height="{band_h}" fill="#f8f9fa" stroke="#dee2e6"/>
  {"".join(bands)}
  {"".join(ticks)}
  {"".join(labels)}
  <text x="{pad_l}" y="{weak_row_y - 6}" class="svg-sub">Weak periods only</text>
  <rect x="{pad_l}" y="{weak_row_y}" width="{plot_w}" height="14" fill="#fff5f5" stroke="#ffc9c9"/>
  {"".join(weak_marks)}
</svg>"""

    # --- Yearly stacked bars ---
    YH, YW = 260, 1100
    ypad_l, ypad_r, ypad_t = 56, 24, 28
    yplot_w = YW - ypad_l - ypad_r
    yplot_h = YH - ypad_t - 44
    max_y = max(sum(years[y].values()) for y in year_list)
    n_years = len(year_list)
    bar_gap = 4
    bar_w = (yplot_w - bar_gap * (n_years - 1)) / n_years
    year_bars: list[str] = []
    for i, y in enumerate(year_list):
        x = ypad_l + i * (bar_w + bar_gap)
        stack = 0.0
        for lab in ("Strong", "Neutral", "Weak"):
            v = years[y][lab]
            if v <= 0:
                continue
            h = v / max_y * yplot_h
            yy = ypad_t + yplot_h - stack - h
            year_bars.append(
                f'<rect x="{x:.2f}" y="{yy:.2f}" width="{bar_w:.2f}" height="{h:.2f}" '
                f'fill="{COLORS[lab]}" opacity="0.9"><title>{y}: {lab} {v}</title></rect>'
            )
            stack += h
        if n_years <= 20 or int(y) % 2 == 0 or y in (year_list[0], year_list[-1]):
            year_bars.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{YH - 16}" text-anchor="middle" '
                f'class="tick">{y[2:]}</text>'
            )

    yticks: list[str] = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        val = int(round(max_y * frac))
        yy = ypad_t + yplot_h * (1 - frac)
        yticks.append(
            f'<line x1="{ypad_l}" y1="{yy:.1f}" x2="{YW - ypad_r}" y2="{yy:.1f}" '
            f'stroke="#e9ecef" stroke-width="1"/>'
        )
        yticks.append(
            f'<text x="{ypad_l - 8}" y="{yy + 4:.1f}" text-anchor="end" class="tick">{val}</text>'
        )

    yearly_svg = f"""<svg viewBox="0 0 {YW} {YH}" width="100%" role="img" aria-label="Sessions by year and outlook">
  <text x="{ypad_l}" y="18" class="svg-title">Sessions by year</text>
  {"".join(yticks)}
  {"".join(year_bars)}
</svg>"""

    def row_html(i: int, r: dict) -> str:
        long = " long" if r["n_days"] >= 10 else ""
        return (
            f'<tr class="weak{long}">'
            f'<td class="num">{i}</td>'
            f'<td>{r["start_date"]}</td>'
            f'<td>{r["end_date"]}</td>'
            f'<td class="num">{r["n_days"]}</td>'
            f'<td class="num">{r["calendar_days"]}</td>'
            f"</tr>"
        )

    weak_sorted = sorted(weak_ranges, key=lambda r: r["start_date"])
    table_rows = "\n".join(row_html(i + 1, r) for i, r in enumerate(weak_sorted))
    top = sorted(weak_ranges, key=lambda r: (-r["n_days"], r["start_date"]))[:8]
    top_rows = "\n".join(
        f'<tr><td>{r["start_date"]}</td><td>{r["end_date"]}</td>'
        f'<td class="num">{r["n_days"]}</td><td class="num">{r["calendar_days"]}</td></tr>'
        for r in top
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SPY Intermediate TC — Weak Timeline</title>
<style>
  :root {{
    --ink: #212529;
    --muted: #868e96;
    --line: #dee2e6;
    --bg: #ffffff;
    --paper: #f8f9fa;
    --strong: #2f9e44;
    --neutral: #f59f00;
    --weak: #e03131;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--paper); color: var(--ink);
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 14px; line-height: 1.45; }}
  .page {{ max-width: 1120px; margin: 0 auto; padding: 28px 24px 48px; background: var(--bg);
    box-shadow: 0 0 0 1px var(--line); min-height: 100vh; }}
  header {{ border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }}
  h1 {{ margin: 0 0 6px; font-size: 26px; letter-spacing: -0.02em; font-weight: 700; }}
  .subtitle {{ color: var(--muted); margin: 0; font-size: 13px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px;
    font-weight: 600; letter-spacing: 0.02em; vertical-align: middle; }}
  .badge.weak {{ background: #ffe3e3; color: #c92a2a; }}
  .badge.strong {{ background: #d3f9d8; color: #2b8a3e; }}
  .badge.neutral {{ background: #fff3bf; color: #e67700; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 18px 0 22px; }}
  .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px 14px 12px; background: #fff; }}
  .card .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-bottom: 4px; }}
  .card .value {{ font-size: 28px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; }}
  .card .meta {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .card.weak-card {{ border-color: #ffa8a8; background: linear-gradient(180deg, #fff 0%, #fff5f5 100%); }}
  .card.weak-card .value {{ color: var(--weak); }}
  .card.strong-card .value {{ color: var(--strong); }}
  .card.neutral-card .value {{ color: #e67700; }}
  section {{ margin: 28px 0; }}
  h2 {{ margin: 0 0 10px; font-size: 17px; border-bottom: 1px solid var(--line); padding-bottom: 6px; }}
  h3 {{ margin: 16px 0 8px; font-size: 14px; color: #495057; }}
  .panel {{ border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px 8px; background: #fff; }}
  .legend {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 8px 0 4px; font-size: 12px; color: #495057; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 2px; display: inline-block; }}
  .note {{ font-size: 12px; color: var(--muted); margin: 8px 0 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: left; }}
  th {{ background: #f1f3f5; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #495057; position: sticky; top: 0; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.weak.long {{ background: #fff5f5; }}
  tr.weak.long td:first-child {{ box-shadow: inset 3px 0 0 var(--weak); }}
  .table-wrap {{ max-height: 520px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }}
  .two-col {{ display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 16px; }}
  .svg-title {{ font: 600 13px "Segoe UI", Arial, sans-serif; fill: #212529; }}
  .svg-sub {{ font: 11px "Segoe UI", Arial, sans-serif; fill: #868e96; }}
  .tick {{ font: 10px "Segoe UI", Arial, sans-serif; fill: #868e96; }}
  footer {{ margin-top: 36px; padding-top: 12px; border-top: 1px solid var(--line); font-size: 11px; color: var(--muted); }}
  code {{ font-size: 12px; }}
  @media print {{
    body {{ background: #fff; }}
    .page {{ box-shadow: none; max-width: none; padding: 12mm; }}
    .table-wrap {{ max-height: none; overflow: visible; }}
    tr.weak.long, .card, .panel, rect {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    h2 {{ break-after: avoid; }}
    section {{ break-inside: avoid; }}
  }}
  @media (max-width: 800px) {{
    .cards {{ grid-template-columns: 1fr 1fr; }}
    .two-col {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
  <div class="page">
    <header>
      <h1>SPY Intermediate TC — Weak Timeline</h1>
      <p class="subtitle">
        Indicator: <code>IND_TC_INT_OUTLOOK</code> ·
        {start_all} → {end_all} ·
        Generated {generated}
        &nbsp;<span class="badge weak">Weak blocked by rs_spy_int_tc_not_weak</span>
      </p>
    </header>

    <div class="cards">
      <div class="card weak-card">
        <div class="label">Weak sessions</div>
        <div class="value">{weak_sess:,}</div>
        <div class="meta">{weak_pct:.1f}% of {n_sess:,} sessions · {len(weak_ranges)} ranges</div>
      </div>
      <div class="card strong-card">
        <div class="label">Strong sessions</div>
        <div class="value">{counts.get("Strong", 0):,}</div>
        <div class="meta">{pct["Strong"]:.1f}% of sessions</div>
      </div>
      <div class="card neutral-card">
        <div class="label">Neutral sessions</div>
        <div class="value">{counts.get("Neutral", 0):,}</div>
        <div class="meta">{pct["Neutral"]:.1f}% of sessions</div>
      </div>
      <div class="card">
        <div class="label">Latest regime</div>
        <div class="value" style="font-size:22px;color:{COLORS[latest['outlook']]}">{latest['outlook']}</div>
        <div class="meta">{latest['start_date']} → {latest['end_date']} ({latest['n_days']} sess)</div>
      </div>
    </div>

    <section>
      <h2>Regime timeline</h2>
      <div class="panel">
        <div class="legend">
          <span><i class="swatch" style="background:var(--strong)"></i> Strong</span>
          <span><i class="swatch" style="background:var(--neutral)"></i> Neutral</span>
          <span><i class="swatch" style="background:var(--weak)"></i> Weak</span>
        </div>
        {timeline_svg}
        <p class="note">Top strip: contiguous Strong / Neutral / Weak regimes. Bottom strip: Weak intervals only (RS filter blocks these dates).</p>
      </div>
    </section>

    <section>
      <h2>Sessions by year</h2>
      <div class="panel">
        {yearly_svg}
      </div>
    </section>

    <section>
      <h2>Weak ranges summary</h2>
      <div class="two-col">
        <div>
          <h3>All Weak periods ({len(weak_ranges)})</h3>
          <p class="note" style="margin-top:0">Rows with ≥10 sessions highlighted. Length = trading sessions; calendar days include weekends/holidays in the span.</p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th class="num">#</th>
                  <th>Start</th>
                  <th>End</th>
                  <th class="num">Sessions</th>
                  <th class="num">Calendar days</th>
                </tr>
              </thead>
              <tbody>
                {table_rows}
              </tbody>
            </table>
          </div>
        </div>
        <div>
          <h3>Longest Weak stretches</h3>
          <div class="table-wrap" style="max-height:none">
            <table>
              <thead>
                <tr>
                  <th>Start</th>
                  <th>End</th>
                  <th class="num">Sess</th>
                  <th class="num">Cal</th>
                </tr>
              </thead>
              <tbody>
                {top_rows}
              </tbody>
            </table>
          </div>
          <h3>Session totals</h3>
          <table>
            <thead><tr><th>Outlook</th><th class="num">Sessions</th><th class="num">%</th></tr></thead>
            <tbody>
              <tr><td><span class="badge strong">Strong</span></td><td class="num">{counts.get("Strong", 0):,}</td><td class="num">{pct["Strong"]:.1f}%</td></tr>
              <tr><td><span class="badge neutral">Neutral</span></td><td class="num">{counts.get("Neutral", 0):,}</td><td class="num">{pct["Neutral"]:.1f}%</td></tr>
              <tr><td><span class="badge weak">Weak</span></td><td class="num">{weak_sess:,}</td><td class="num">{weak_pct:.1f}%</td></tr>
              <tr><td><strong>Total</strong></td><td class="num"><strong>{n_sess:,}</strong></td><td class="num">100%</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <footer>
      Source: <code>SPY_INT_TC_REGIME.csv</code> / <code>SPY_INT_TC_REGIME_RANGES.csv</code>
      (from SPY <code>IND_TC_INT_OUTLOOK</code> via indicator cache).
      Filter note: <code>rs_spy_int_tc_not_weak=true</code> allows Strong + Neutral; blocks Weak only.
    </footer>
  </div>
</body>
</html>
"""
    HTML_PATH.write_text(doc, encoding="utf-8")
    print(f"Wrote {HTML_PATH}")
    print(f"Weak ranges: {len(weak_ranges)}")
    print(f"Weak sessions: {weak_sess}/{n_sess} = {weak_pct:.2f}%")


if __name__ == "__main__":
    main()
