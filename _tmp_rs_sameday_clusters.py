"""Analyze RS same-day DATE_OPENED entry clusters (gold-65 Closed)."""
from __future__ import annotations

import csv
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r"C:\Users\songg\Downloads\stockresearch")
CLOSED = (
    ROOT
    / "drive/paul_experiments/rs_baseline_260807141317/engine_closed/RS_Closed_260807141317.csv"
)
OUT_HTML = ROOT / "drive/paul_experiments/RS_SameDay_Entry_Clusters.html"
OUT_JSON = ROOT / "_tmp_rs_sameday_clusters.json"

SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  function parseSortValue(text, type) {
    var s = String(text || "").trim();
    if (!s || s === "—" || s === "-") return type === "text" ? "" : 0;
    if (type === "text") return s.toUpperCase();
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
  function bind(table) {
    var ths = table.querySelectorAll("th.sortable-th");
    ths.forEach(function (th, idx) {
      function activate() {
        var type = th.getAttribute("data-sort") || "text";
        var asc = !th.classList.contains("sort-asc");
        ths.forEach(function (x) {
          x.classList.remove("sort-asc", "sort-desc");
          x.setAttribute("aria-sort", "none");
        });
        th.classList.add(asc ? "sort-asc" : "sort-desc");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        sortTable(table, idx, type, asc ? 1 : -1);
      }
      th.addEventListener("click", activate);
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); activate(); }
      });
    });
  }
  document.querySelectorAll("table.sortable").forEach(bind);
})();
</script>
"""


def sortable_th(label: str, sort_type: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{html.escape(sort_type)}" '
        f'tabindex="0" role="columnheader" aria-sort="none">'
        f"{html.escape(label)}<span class=\"sort-ind\"></span></th>"
    )


def parse_pct(s):
    if s is None or s == "":
        return None
    return float(str(s).replace("%", "").replace(",", "").strip())


def parse_num(s):
    if s is None or s == "":
        return None
    return float(str(s).replace(",", "").strip())


def ymd(s):
    s = str(s).strip()
    if len(s) == 8 and s.isdigit():
        return datetime.strptime(s, "%Y%m%d")
    return datetime.strptime(s[:10], "%Y-%m-%d")


def fmt_date(s):
    return ymd(s).strftime("%Y-%m-%d")


def agg(trades):
    pn = [parse_pct(t["PNL_PCT"]) for t in trades]
    dol = [parse_num(t["PNL_DOLLARS"]) for t in trades]
    dh = [parse_num(t["DAYS_HELD"]) for t in trades]
    w = sum(1 for p in pn if p is not None and p > 0)
    l = sum(1 for p in pn if p is not None and p <= 0)
    return {
        "n": len(trades),
        "wins": w,
        "losses": l,
        "wr": 100.0 * w / len(trades) if trades else 0.0,
        "avg_pnl": statistics.mean(pn) if pn else 0.0,
        "med_pnl": statistics.median(pn) if pn else 0.0,
        "sum_pnl": sum(dol) if dol else 0.0,
        "avg_days": statistics.mean(dh) if dh else 0.0,
        "symbols": sorted({t["SYMBOL"] for t in trades}),
    }


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%" if x != 0 else "0.00%"


def fmt_pct_plain(x: float) -> str:
    return f"{x:.1f}%"


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def cls_for(x: float) -> str:
    if x > 0:
        return "pos"
    if x < 0:
        return "neg"
    return ""


def main() -> None:
    rows = list(csv.DictReader(CLOSED.open(encoding="utf-8")))
    print(f"Loaded {len(rows)} trades from gold {CLOSED.name}")

    pnls = [parse_pct(r["PNL_PCT"]) for r in rows]
    dollars = [parse_num(r["PNL_DOLLARS"]) for r in rows]
    days = [parse_num(r["DAYS_HELD"]) for r in rows]
    wins = sum(1 for p in pnls if p is not None and p > 0)
    n = len(rows)
    base = {
        "n": n,
        "wr": 100.0 * wins / n,
        "avg_pnl": statistics.mean(pnls),
        "med_pnl": statistics.median(pnls),
        "sum_pnl": sum(dollars),
        "avg_days": statistics.mean(days),
    }
    print(
        "BASELINE",
        {k: (round(v, 2) if isinstance(v, float) else v) for k, v in base.items()},
    )

    by_open: dict[str, list] = defaultdict(list)
    for r in rows:
        by_open[r["DATE_OPENED"]].append(r)

    counts = sorted(
        ((d, len(tr)) for d, tr in by_open.items()), key=lambda x: (-x[1], x[0])
    )
    max_n = counts[0][1]
    print(
        f"Unique DATE_OPENED days: {len(by_open)}; max same-day entries: {max_n}"
    )

    def days_ge(thresh: int):
        return [(d, nn) for d, nn in counts if nn >= thresh]

    for t in (8, 10, 12, 11, 9):
        xs = days_ge(t)
        print(f"N>={t}: {len(xs)} days; peak N={xs[0][1] if xs else 0}")

    print("\nTop 20 DATE_OPENED by N:")
    for d, nn in counts[:20]:
        print(f"  {fmt_date(d)}  N={nn}")

    # Concurrent open positions (optional secondary)
    all_events = []
    for r in rows:
        o = ymd(r["DATE_OPENED"]).date()
        c = ymd(r["DATE_CLOSED"]).date()
        all_events.append((o, +1))
        all_events.append((c + timedelta(days=1), -1))
    all_events.sort()
    cur = 0
    max_conc = 0
    max_conc_day = None
    days_ge12_conc = []
    i = 0
    while i < len(all_events):
        day = all_events[i][0]
        while i < len(all_events) and all_events[i][0] == day:
            cur += all_events[i][1]
            i += 1
        if cur > max_conc:
            max_conc = cur
            max_conc_day = day
        if cur >= 12:
            days_ge12_conc.append((day, cur))

    print(f"\nMax concurrent open positions: {max_conc} on {max_conc_day}")
    print(f"Days with concurrent >=12: {len(days_ge12_conc)}")
    if days_ge12_conc:
        topc = sorted(days_ge12_conc, key=lambda x: (-x[1], x[0]))[:15]
        for d, c in topc:
            print(f"  concurrent {c} on {d}")

    THRESH = 8
    high_days = [(d, by_open[d]) for d, _n in counts if _n >= THRESH]

    def pool(thresh: int):
        ts = []
        for d, nn in counts:
            if nn >= thresh:
                ts.extend(by_open[d])
        return agg(ts) if ts else None

    for t in (8, 10, 12):
        a = pool(t)
        if not a:
            print(f"\nPOOL N>={t}: none")
        else:
            print(
                f"\nPOOL N>={t}:",
                {
                    k: (
                        round(v, 2)
                        if isinstance(v, float)
                        else (v if k != "symbols" else len(v))
                    )
                    for k, v in a.items()
                },
            )

    print("\n=== Per-day detail N>=8 ===")
    day_stats = []
    for d, trades in high_days:
        a = agg(trades)
        a["date"] = d
        a["date_fmt"] = fmt_date(d)
        day_stats.append(a)
        print(
            f"{a['date_fmt']} N={a['n']} W/L={a['wins']}/{a['losses']} "
            f"WR={a['wr']:.1f}% avgPNL%={a['avg_pnl']:.2f} medPNL%={a['med_pnl']:.2f} "
            f"sum$={a['sum_pnl']:.0f} avgDays={a['avg_days']:.1f} "
            f"syms={','.join(a['symbols'])}"
        )

    # Distribution of N
    from collections import Counter

    n_hist = Counter(nn for _, nn in counts)
    print("\nDistribution of same-day N:")
    for nn in sorted(n_hist.keys(), reverse=True):
        print(f"  N={nn}: {n_hist[nn]} days")

    summary = {
        "source": str(CLOSED.relative_to(ROOT)).replace("\\", "/"),
        "stamp": "260807141317",
        "baseline": base,
        "max_same_day_n": max_n,
        "n_days_ge": {str(t): len(days_ge(t)) for t in (8, 10, 12)},
        "n_hist": {str(k): v for k, v in sorted(n_hist.items())},
        "max_concurrent": max_conc,
        "max_concurrent_day": str(max_conc_day),
        "days_concurrent_ge12": len(days_ge12_conc),
        "top_counts": [(fmt_date(d), nn) for d, nn in counts[:40]],
        "day_stats": [
            {**{k: v for k, v in a.items() if k != "symbols"}, "symbols": a["symbols"]}
            for a in day_stats
        ],
        "pools": {
            str(t): (
                {k: (v if k != "symbols" else len(v)) for k, v in pool(t).items()}
                if pool(t)
                else None
            )
            for t in (8, 10, 12)
        },
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}")

    write_html(summary, day_stats, base, counts, max_n, max_conc, max_conc_day, days_ge12_conc)
    print(f"Wrote {OUT_HTML}")


def write_html(summary, day_stats, base, counts, max_n, max_conc, max_conc_day, days_ge12_conc):
    yes12 = summary["n_days_ge"]["12"] > 0
    verdict = (
        f"<strong>Yes</strong> — {summary['n_days_ge']['12']} day(s) with ≥12 same-day entries."
        if yes12
        else (
            f"<strong>No</strong> — never hit 12 same-day DATE_OPENED entries. "
            f"Peak was <strong>N={max_n}</strong> "
            f"({', '.join(f'{d} (N={n})' for d, n in summary['top_counts'][:3] if n == max_n)})."
        )
    )

    # threshold summary rows
    thresh_rows = []
    for t in (8, 10, 12):
        p = summary["pools"].get(str(t))
        nd = summary["n_days_ge"][str(t)]
        if not p:
            thresh_rows.append(
                f"<tr><td>≥{t}</td><td>{nd}</td><td colspan='7'>— no days —</td></tr>"
            )
            continue
        d_wr = p["wr"] - base["wr"]
        d_avg = p["avg_pnl"] - base["avg_pnl"]
        d_days = p["avg_days"] - base["avg_days"]
        thresh_rows.append(
            "<tr>"
            f"<td>≥{t}</td>"
            f"<td>{nd}</td>"
            f"<td>{p['n']}</td>"
            f"<td>{p['wins']}/{p['losses']}</td>"
            f"<td class='{cls_for(d_wr)}'>{fmt_pct_plain(p['wr'])} ({d_wr:+.1f}pp)</td>"
            f"<td class='{cls_for(p['avg_pnl'])}'>{fmt_pct(p['avg_pnl'])}</td>"
            f"<td class='{cls_for(p['med_pnl'])}'>{fmt_pct(p['med_pnl'])}</td>"
            f"<td class='{cls_for(p['sum_pnl'])}'>{fmt_money(p['sum_pnl'])}</td>"
            f"<td>{p['avg_days']:.1f} ({d_days:+.1f})</td>"
            "</tr>"
        )

    detail_rows = []
    for a in day_stats:
        d_wr = a["wr"] - base["wr"]
        d_avg = a["avg_pnl"] - base["avg_pnl"]
        d_days = a["avg_days"] - base["avg_days"]
        syms = ", ".join(a["symbols"])
        detail_rows.append(
            "<tr>"
            f"<td>{html.escape(a['date_fmt'])}</td>"
            f"<td>{a['n']}</td>"
            f"<td>{html.escape(syms)}</td>"
            f"<td>{a['wins']}/{a['losses']}</td>"
            f"<td class='{cls_for(d_wr)}'>{fmt_pct_plain(a['wr'])} ({d_wr:+.1f}pp)</td>"
            f"<td class='{cls_for(a['avg_pnl'])}'>{fmt_pct(a['avg_pnl'])}</td>"
            f"<td class='{cls_for(a['med_pnl'])}'>{fmt_pct(a['med_pnl'])}</td>"
            f"<td class='{cls_for(a['sum_pnl'])}'>{fmt_money(a['sum_pnl'])}</td>"
            f"<td>{a['avg_days']:.1f} ({d_days:+.1f})</td>"
            "</tr>"
        )

    top_rows = []
    for d, nn in summary["top_counts"][:25]:
        top_rows.append(
            f"<tr><td>{html.escape(d)}</td><td>{nn}</td></tr>"
        )

    # concurrent note
    conc_note = (
        f"Max concurrent open positions (DATE_OPENED ≤ day ≤ DATE_CLOSED): "
        f"<strong>{max_conc}</strong> on {max_conc_day}. "
        f"Calendar days with concurrent ≥12: <strong>{len(days_ge12_conc)}</strong>."
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RS Same-Day Entry Clusters</title>
<style>
body {{ font-family: system-ui, sans-serif; margin:24px; color:#0f172a; max-width:1400px; }}
h1 {{ font-size:1.5rem; margin-bottom:4px; }}
h2 {{ font-size:1.15rem; margin-top:28px; }}
.sub {{ color:#64748b; margin-bottom:20px; line-height:1.5; font-size:0.95rem; }}
.small {{ font-size:12px; color:#64748b; }}
.pos {{ color:#16a34a; }} .neg {{ color:#dc2626; }}
.table-wrap {{ overflow-x:auto; margin:8px 0; }}
table {{ border-collapse:collapse; font-size:12px; width:100%; }}
th, td {{ border:1px solid #e2e8f0; padding:7px 8px; text-align:left; vertical-align:top; }}
th {{ background:#f1f5f9; }}
th.sortable-th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
th.sortable-th:hover {{ background:#e2e8f0; }}
.sort-ind {{ display:inline-block; width:0.9em; margin-left:4px; color:#94a3b8; font-size:10px; }}
th.sort-asc .sort-ind::after {{ content:"▲"; color:#334155; }}
th.sort-desc .sort-ind::after {{ content:"▼"; color:#334155; }}
tr.total-row th, tr.total-row td {{ background:#f8fafc; border-top:2px solid #334155; }}
code {{ font-size:11px; background:#f1f5f9; padding:1px 4px; border-radius:3px; }}
.def {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px 14px; margin:12px 0 20px; font-size:0.92rem; line-height:1.5; }}
.verdict {{ font-size:1.05rem; margin:12px 0 8px; }}
</style></head><body>
<h1>RS Same-Day Entry Clusters</h1>
<p class="sub">
  Gold-65 Closed stamp <code>260807141317</code>
  (<code>{html.escape(summary['source'])}</code>).
  Primary metric: entries opened on the same calendar day (<code>DATE_OPENED</code>).
  Generated {now}. Book size: {base['n']} closed trades.
</p>

<div class="def verdict">
  {verdict}
</div>

<div class="def">
  <strong>Book baseline:</strong>
  WR {fmt_pct_plain(base['wr'])},
  avg PNL% {fmt_pct(base['avg_pnl'])},
  median PNL% {fmt_pct(base['med_pnl'])},
  sum PnL$ {fmt_money(base['sum_pnl'])},
  avg days held {base['avg_days']:.1f}.
  Deltas in tables are vs this baseline (pp = percentage points).<br>
  <strong>Optional secondary:</strong> {conc_note}
</div>

<section>
<h2>Threshold pools (all trades on days with N≥threshold)</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>
    {sortable_th("Threshold", "text")}
    {sortable_th("# Days", "num")}
    {sortable_th("# Trades", "num")}
    {sortable_th("W/L", "text")}
    {sortable_th("WR (Δpp)", "num")}
    {sortable_th("Avg PNL%", "num")}
    {sortable_th("Med PNL%", "num")}
    {sortable_th("Sum PnL$", "num")}
    {sortable_th("Avg days (Δ)", "num")}
  </tr></thead>
  <tbody>
    {''.join(thresh_rows)}
    <tr class="total-row">
      <td><strong>Book baseline</strong></td>
      <td>—</td>
      <td>{base['n']}</td>
      <td>—</td>
      <td>{fmt_pct_plain(base['wr'])}</td>
      <td class="{cls_for(base['avg_pnl'])}">{fmt_pct(base['avg_pnl'])}</td>
      <td class="{cls_for(base['med_pnl'])}">{fmt_pct(base['med_pnl'])}</td>
      <td class="{cls_for(base['sum_pnl'])}">{fmt_money(base['sum_pnl'])}</td>
      <td>{base['avg_days']:.1f}</td>
    </tr>
  </tbody>
</table>
</div>
</section>

<section>
<h2>High-activity days (N≥8 same-day entries)</h2>
<p class="small">Click column headers to sort. Symbols listed alphabetically.</p>
<div class="table-wrap">
<table class="sortable">
  <thead><tr>
    {sortable_th("DATE_OPENED", "date")}
    {sortable_th("N", "num")}
    {sortable_th("Symbols", "text")}
    {sortable_th("W/L", "text")}
    {sortable_th("WR (Δpp)", "num")}
    {sortable_th("Avg PNL%", "num")}
    {sortable_th("Med PNL%", "num")}
    {sortable_th("Sum PnL$", "num")}
    {sortable_th("Avg days (Δ)", "num")}
  </tr></thead>
  <tbody>
    {''.join(detail_rows) if detail_rows else '<tr><td colspan="9">No days with N≥8</td></tr>'}
  </tbody>
</table>
</div>
</section>

<section>
<h2>Top DATE_OPENED by entry count</h2>
<p class="small">Click column headers to sort.</p>
<div class="table-wrap">
<table class="sortable" style="max-width:420px">
  <thead><tr>
    {sortable_th("DATE_OPENED", "date")}
    {sortable_th("N entries", "num")}
  </tr></thead>
  <tbody>
    {''.join(top_rows)}
  </tbody>
</table>
</div>
</section>

{SORTABLE_TABLE_SCRIPT}
</body></html>
"""
    OUT_HTML.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
