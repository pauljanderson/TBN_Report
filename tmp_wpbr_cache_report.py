"""Generate report.html for WPBR weekly/zone DuckDB cache investigation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from report_page_extras import (  # noqa: E402
    CACHE_META,
    FORCE_RELOAD_SCRIPT,
    SORTABLE_TABLE_SCRIPT,
    SORTABLE_TH_CSS,
    SWIPE_NOTE_HTML,
)

OUT = ROOT / "drive" / "paul_experiments" / "wpbr_weekly_zone_cache_20261002"
OUT.mkdir(parents=True, exist_ok=True)

timing = json.loads((OUT / "timing_slice.json").read_text(encoding="utf-8"))
parity = json.loads((OUT / "parity_timing.json").read_text(encoding="utf-8"))

REQUEST = (
    "can we save historical weekly prices and zones in the duckdb so we don't have to "
    "calculate them except for the latest, if that is expensive?"
)

LAYMAN = (
    "Weekly Pivot Break and Retest (WPBR) turns daily prices into Friday week bars, then finds "
    "weekly price shelves (zones). Building those week bars is cheap. Finding and scoring the "
    "zones is the slower part of that step — on the order of a few minutes across the whole "
    "stock list, before the trade simulator even runs. We measured that, then built an optional "
    "sidecar database that remembers finished week bars and the zone results. On the next run "
    "with the same history, WPBR can reuse them. If daily history was adjusted (splits, "
    "corrections), the cache throws that symbol away and rebuilds. The switch stays off by "
    "default so DailyRun is unchanged until you turn it on for research."
)


def th(label: str, typ: str) -> str:
    return (
        f'<th class="sortable-th" data-sort="{typ}" tabindex="0" role="columnheader" '
        f'aria-sort="none">{label}<span class="sort-ind"></span></th>'
    )


def timing_rows() -> str:
    body = []
    for r in timing.get("rows") or []:
        body.append(
            "<tr>"
            f"<td>{r['symbol']}</td>"
            f"<td>{r['bars']}</td>"
            f"<td>{r['weeks']}</td>"
            f"<td>{r['zones']}</td>"
            f"<td>{r['load_s']}</td>"
            f"<td>{r['weekly_s']}</td>"
            f"<td>{r['zone_s']}</td>"
            f"<td>{r['zone_plus_weekly_s']}</td>"
            "</tr>"
        )
    return "\n".join(body)


def parity_rows() -> str:
    body = []
    for r in parity.get("rows") or []:
        body.append(
            "<tr>"
            f"<td>{r['symbol']}</td>"
            f"<td>{'PASS' if r['ok'] else 'FAIL'}</td>"
            f"<td>{r['n_zones']}</td>"
            f"<td>{r['no_cache_s']}</td>"
            f"<td>{r['cold_fill_s']}</td>"
            f"<td>{r['warm_s']}</td>"
            f"<td>{r['speedup_vs_no_cache']}</td>"
            "</tr>"
        )
    return "\n".join(body)


html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
{CACHE_META}
<title>WPBR weekly / zone DuckDB cache — 2026-10-02</title>
<style>
body {{ font-family: Georgia, "Times New Roman", serif; margin: 0; background: #f7f4ef; color: #1c1917; }}
main {{ max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; }}
h1 {{ font-size: 1.6rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.2rem; margin: 28px 0 8px; }}
p, li {{ line-height: 1.45; }}
.muted {{ color: #57534e; }}
.callout {{ background: #fff; border-left: 4px solid #0f766e; padding: 12px 14px; margin: 16px 0; }}
.callout h2 {{ margin-top: 0; }}
.verdict {{ background: #ecfdf5; border: 1px solid #6ee7b7; padding: 12px 14px; margin: 16px 0; }}
code, .mono {{ font-family: Consolas, "Courier New", monospace; font-size: 0.92em; }}
table.sortable {{ border-collapse: collapse; width: 100%; background: #fff; }}
th.sortable-th, td {{ border: 1px solid #d6d3d1; padding: 6px 8px; text-align: left; }}
th.sortable-th {{ background: #f4f1ea; cursor: pointer; user-select: none; }}
th.sortable-th.sort-asc .sort-ind::after {{ content: " ▲"; }}
th.sortable-th.sort-desc .sort-ind::after {{ content: " ▼"; }}
tr.total-row {{ font-weight: 700; background: #f8fafc; }}
{SORTABLE_TH_CSS}
</style>
{FORCE_RELOAD_SCRIPT}
</head>
<body>
<main>
<h1>WPBR weekly / zone DuckDB cache</h1>
<p class="muted">Stamp <span class="mono">wpbr_weekly_zone_cache_20261002</span> · research only · not DailyRun · not gold</p>

<div class="callout">
<h2>What you asked</h2>
<p>{REQUEST}</p>
<h2>In plain English</h2>
<p>{LAYMAN}</p>
</div>

<div class="verdict">
<p><strong>Verdict:</strong> Caching <em>weeklies alone</em> is a small win (~4% of the weekly+zone step, ~9s across ~1100 names). Caching <em>zone streams</em> is the real prize for that step (~3 minutes cold across the universe; warm reuse skips most of it). Expected speedup is large for the zone-build phase on repeat runs with unchanged history and unchanged WPBR knobs; overall full WPBR wall time still includes trade simulation, so end-to-end gain is smaller (often meaningful on exit A/Bs that reuse the same zones).</p>
<p><strong>Flag (default OFF):</strong> <span class="mono">wpbr_weekly_zone_cache=true</span> or env <span class="mono">WPBR_WEEKLY_ZONE_CACHE=1</span>. Optional DB path: <span class="mono">wpbr_weekly_zone_cache_db</span> / <span class="mono">WPBR_WEEKLY_ZONE_CACHE_DB</span> (default <span class="mono">data/wpbr_weekly_zone_cache.duckdb</span>).</p>
<p><strong>Parity:</strong> {"PASS" if parity.get("all_ok") else "FAIL"} on {parity.get("n_symbols")} symbols (cold no-cache vs warm cache: zone ids, entry bars, zone arrays).</p>
</div>

<h2>Is it expensive?</h2>
<p>Timed slice on {timing.get("n_symbols")} symbols (CSV load; box may have been CPU-contended by other WPBR jobs). Zone pipeline = <span class="mono">aggregate_weekly</span> + <span class="mono">compute_wpbr_touch_stream</span>.</p>
<ul>
<li>Weekly share of zone pipeline: <strong>{timing.get("weekly_share_of_zone_pipeline_pct")}%</strong> (mean {timing.get("mean_weekly_ms")} ms/symbol).</li>
<li>Zone share: <strong>{timing.get("zone_share_of_zone_pipeline_pct")}%</strong> (mean {timing.get("mean_zone_ms")} ms/symbol).</li>
<li>Extrapolate ~1100 symbols: weeklies ~{timing.get("extrapolate_1100_symbols_weekly_s")}s, zones ~{timing.get("extrapolate_1100_symbols_zone_s")}s, combined ~{timing.get("extrapolate_1100_symbols_pipeline_s")}s.</li>
</ul>
<p class="muted">{timing.get("note")}</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{th("Symbol", "text")}{th("Bars", "num")}{th("Weeks", "num")}{th("Zones", "num")}
{th("Load s", "num")}{th("Weekly s", "num")}{th("Zone s", "num")}{th("Weekly+zone s", "num")}
</tr></thead>
<tbody>
{timing_rows()}
</tbody>
</table>
</div>
<p class="muted">Click column headers to sort.</p>

<h2>What exists today</h2>
<ul>
<li><span class="mono">data/ohlcv.duckdb</span> table <span class="mono">prices</span> only (daily OHLCV). No weeklies, no WPBR zones.</li>
<li>WPBR builds weeklies in <span class="mono">wpbr_zones.aggregate_weekly</span> (<span class="mono">W-FRI</span> resample) inside <span class="mono">compute_wpbr_touch_stream</span>, then pivots / breakout / retest / strength.</li>
<li>BRT has a separate per-symbol indicator pickle cache (<span class="mono">.brt_indicator_cache</span>); WPBR zones did not use it.</li>
</ul>

<h2>What we built</h2>
<ul>
<li>Module <span class="mono">stock_analysis/wpbr_weekly_zone_cache.py</span> — schema + read/write helpers.</li>
<li>Sidecar DuckDB (not <span class="mono">ohlcv.duckdb</span>, so cache writes do not lock daily prices): tables <span class="mono">weekly_bars</span>, <span class="mono">symbol_daily_meta</span>, <span class="mono">wpbr_stream_cache</span>.</li>
<li>Wired into <span class="mono">compute_wpbr_touch_stream</span> and <span class="mono">rocket_tbn</span> cfg fields; <strong>default OFF</strong>.</li>
</ul>

<h2>Schema</h2>
<ul>
<li><span class="mono">weekly_bars(symbol, week_end, open, high, low, close, volume)</span> PK (symbol, week_end)</li>
<li><span class="mono">symbol_daily_meta(symbol, daily_fp, n_bars, first_date, last_date, prefix_fp, cache_version, updated_at)</span></li>
<li><span class="mono">wpbr_stream_cache(symbol, config_hash, daily_fp, n_bars, cache_version, payload BLOB, updated_at)</span> — pickled zone arrays + events keyed by WPBR knobs hash</li>
</ul>

<h2>Invalidation rule</h2>
<ol>
<li><strong>daily_fp</strong> = blake2b fingerprint of daily OHLCV (same idea as BRT indicator cache). Split/dividend/revision that changes history → fingerprint changes → delete that symbol's weeklies + stream blob → rebuild.</li>
<li><strong>Exact match</strong> (same fp + bar count + config hash): reuse weeklies and full zone stream.</li>
<li><strong>Append-only</strong> (prefix of old n_bars still matches): keep completed week rows before the week that contains the first new daily bar; rebuild from that week forward; <em>always</em> rebuild zone stream (new bars can complete breakouts/retests).</li>
<li>Incomplete current week is never trusted from cache alone without the append rebuild path.</li>
<li>DuckDB lock contention: skip cache write/read and cold-compute (no crash). Parallel ProcessPool writers can still contend — research flag, not forced on DailyRun.</li>
</ol>

<h2>Parity + warm timing</h2>
<p>Cache stats: <span class="mono">{parity.get("cache_stats")}</span>. Mean fill→warm speedup on this box: {parity.get("mean_speedup_warm_vs_fill")}× (fill includes first-time DuckDB writes; CPU was busy). Warm vs no-cache per symbol is noisy under load — AAPL showed ~6× when the hit path was clean.</p>
{SWIPE_NOTE_HTML}
<div class="table-wrap">
<table class="sortable">
<thead><tr>
{th("Symbol", "text")}{th("Parity", "text")}{th("Zones", "num")}
{th("No-cache s", "num")}{th("Cold fill s", "num")}{th("Warm s", "num")}{th("Speedup vs no-cache", "num")}
</tr></thead>
<tbody>
{parity_rows()}
</tbody>
</table>
</div>

<h2>Recommendation</h2>
<ul>
<li><strong>Weeklies-only cache:</strong> low priority by itself.</li>
<li><strong>Zone stream cache:</strong> worth enabling for research repeat runs (exit horse-races, same knobs, same data).</li>
<li><strong>Default:</strong> keep <span class="mono">OFF</span> for DailyRun until a longer soak / full-universe parity stamp. Turn on with <span class="mono">-v wpbr_weekly_zone_cache=true</span>.</li>
<li>Expected speedup: roughly the zone-pipeline cost (~{timing.get("extrapolate_1100_symbols_zone_s")}s/universe) on warm exact hits; not the whole WPBR backtest.</li>
</ul>

<p class="muted">Artifacts: <span class="mono">timing_slice.json</span>, <span class="mono">parity_timing.json</span>, code under <span class="mono">stock_analysis/wpbr_weekly_zone_cache.py</span>.</p>
</main>
{SORTABLE_TABLE_SCRIPT}
</body>
</html>
"""

report = OUT / "report.html"
report.write_text(html, encoding="utf-8")
print(f"wrote {report}")
