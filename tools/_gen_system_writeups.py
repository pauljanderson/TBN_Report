#!/usr/bin/env python3
"""Generate detailed TBN system write-ups.

Writes:
  drive/systems/<slug>.html          (canonical; GitHub Pages copies from here)
  docs/systems/<slug>.html           (committed Pages copy)
  drive/paul_experiments/<CODE>_System_Guide.html

Style matches drive/TBN_Philosophy.html. Content depth matches the RS/SB/VZ
guides (identity, entry, exit, frozen levers, universe, caveats, links).

Production knobs are taken from the run_*.bat wrappers, not engine defaults.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVE_SYSTEMS = ROOT / "drive" / "systems"
DOCS_SYSTEMS = ROOT / "docs" / "systems"
PAUL = ROOT / "drive" / "paul_experiments"

CSS = """
  :root {
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }
  .wrap { max-width: 920px; margin: 0 auto; padding: 36px 24px 64px; }
  header.doc-head { border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }
  .eyebrow {
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }
  h1 { font-size: 1.7rem; margin: 0 0 6px; letter-spacing: -0.02em; line-height: 1.2; }
  h2 { font-size: 1.12rem; margin: 26px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }
  h3 { font-size: 1.0rem; margin: 18px 0 8px; }
  .lede { margin: 0; color: var(--muted); max-width: 72ch; }
  .back { font-size: 0.9rem; margin: 0 0 10px; }
  .meta-row { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 10px; font-size: 0.82rem; color: var(--muted); }
  .badge {
    display: inline-block; font-size: 0.75rem; font-weight: 700;
    letter-spacing: 0.04em; padding: 2px 8px; margin: 10px 0 0;
  }
  .badge-ok { background: var(--ok-bg); color: var(--ok); }
  .badge-warn { background: var(--warn-bg); color: var(--warn); }
  .badge-muted { background: var(--fill); color: var(--muted); }
  .badge-bad { background: var(--bad-bg); color: var(--bad); }
  p, li { margin: 0 0 10px; }
  ul, ol { padding-left: 1.25rem; margin: 0 0 12px; }
  ol.steps li { margin: 0.35em 0; }
  a { color: var(--accent); }
  code, .path {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 0.86em; background: var(--fill); padding: 0.08em 0.3em;
  }
  .callout { background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }
  .callout.warn { background: var(--warn-bg); border-left-color: var(--warn); }
  .callout.ok { background: var(--ok-bg); border-left-color: var(--ok); }
  .callout.bad { background: var(--bad-bg); border-left-color: var(--bad); }
  .card {
    background: var(--card); border: 1px solid var(--line);
    padding: 12px 14px; margin: 0 0 14px;
  }
  .table-wrap { overflow-x: auto; margin: 8px 0 16px; }
  table.sortable { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid var(--line); padding: 7px 8px; text-align: left; vertical-align: top; }
  thead th { background: var(--fill); }
  th.sortable-th { cursor: pointer; user-select: none; white-space: nowrap; }
  th.sortable-th:hover { background: #e8e4d8; }
  .sort-ind { display: inline-block; width: 0.9em; margin-left: 4px; color: #9a9588; font-size: 10px; }
  th.sort-asc .sort-ind::after { content: "▲"; color: var(--ink); }
  th.sort-desc .sort-ind::after { content: "▼"; color: var(--ink); }
  caption { text-align: left; font-size: 0.82rem; color: var(--muted); margin: 0 0 6px; caption-side: top; }
  footer { margin-top: 28px; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }
"""

SORT_JS = r"""
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


def th(label: str, sort_type: str = "text") -> str:
    return (
        f'<th class="sortable-th" data-sort="{sort_type}" tabindex="0" '
        f'role="columnheader" aria-sort="none">{label}<span class="sort-ind"></span></th>'
    )


def table(headers: list[tuple[str, str]], rows: list[list[str]], caption: str = "") -> str:
    head = "".join(th(h, t) for h, t in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    cap = f"<caption>{caption} Click column headers to sort.</caption>" if caption else "<caption>Click column headers to sort.</caption>"
    return (
        f'<div class="table-wrap"><table class="sortable">{cap}'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def levers(rows: list[tuple[str, str, str, str]]) -> str:
    return table(
        [("Lever", "text"), ("What it does", "text"), ("Freeze / prod", "text"), ("Count vs quality (tendency)", "text")],
        [[a, b, c, d] for a, b, c, d in rows],
        caption="Frozen production (or adopted research) knobs.",
    )


def kv(rows: list[tuple[str, str]]) -> str:
    return table(
        [("Item", "text"), ("Value", "text")],
        [[a, b] for a, b in rows],
    )


def page(
    *,
    title: str,
    eyebrow: str,
    lede: str,
    badge_class: str,
    badge_text: str,
    meta: str,
    body: str,
    footer: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>{CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="back"><a href="../tbn_philosophy.html">&larr; TBN Philosophy</a></p>
  <header class="doc-head">
    <p class="eyebrow">{eyebrow}</p>
    <h1>{title}</h1>
    <p class="lede">{lede}</p>
    <div class="badge {badge_class}">{badge_text}</div>
    <div class="meta-row">{meta}</div>
  </header>
{body}
  <footer>{footer}</footer>
</div>
{SORT_JS}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Per-system bodies
# ---------------------------------------------------------------------------

def rs() -> str:
    return page(
        title="RS — Relative Strength",
        eyebrow="Production · Relative Strength (RS)",
        lede=(
            "<strong>RS</strong> (Relative Strength) buys names beating SPY on 1Y/2Y/3Y excess returns "
            "that also show Strong Intermediate/Short/Long Trend Condition (TC) outlooks, while SPY’s "
            "intermediate TC is not Weak. It is a regime/strength sleeve — no Break and ReTest (BRT) zones — "
            "with a fixed multiplier stop/target and a long time stop."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Engine <code>rocket_tbn.py</code> (<code>rs_mode</code> / <code>--relative-strength</code>)</span>"
            "<span>Runner <code>run_rs.bat</code></span>"
            "<span>Prefix <code>RS_*</code></span>"
            "<span>Freeze <code>rs_baseline_260807141317</code></span>"
        ),
        body="""
<div class="callout ok">
  <strong>Status:</strong> Production gold · DailyRun step [9/14] · reconcile-gated.
  Universe <code>drive/universes/RS_universe.csv</code> — <strong>64</strong> names
  (ATEYY dropped 2026-08-10; freeze Closed still has historical ATEYY trades, not gated).
</div>

<h2>1. What it is</h2>
<p>
  Fill is always the <strong>next open</strong> after the trigger close. Gates are never re-checked
  on the entry bar. Role: multi-month leadership sleeve vs short-hold StockBee (SB) bursts and
  zone retest books (BRT / Year High / Pivot Break and Retest).
</p>

<h2>2. Entry logic</h2>
<p>Signal bar <strong>T</strong> close — then fill at T+1 open. One position at a time per symbol.</p>
<ol class="steps">
  <li>Require <code>SPY_COMPARE_1Y</code>, <code>2Y</code>, and <code>3Y</code> all <strong>&gt; 0</strong> (excess vs SPY). <code>SPY.csv</code> must be present.</li>
  <li>If <code>rs_require_tc_strong=true</code> (prod): stock <code>IND_TC_*_OUTLOOK</code> all <strong>Strong</strong> on T.</li>
  <li>If <code>rs_spy_int_tc_not_weak=true</code> (prod): lagged SPY TC (horizon <code>int</code>, lag 1) ≠ <strong>Weak</strong> (Strong or Neutral OK).</li>
  <li>Optional O'Neil-style filters (prod <strong>off</strong>): near-52-week-high, growth filter, Average True Range (ATR)% caps.</li>
  <li>Respect <code>symbol_reentry_cooldown_days</code> (prod <strong>60</strong>) after a prior exit on that symbol.</li>
  <li>Fill at <strong>T+1 open</strong>. Do not re-check SPY_COMPARE / TC on the entry bar.</li>
</ol>

<h2>3. Exit logic</h2>
<ul>
  <li><strong>Stop:</strong> <code>entry × stop_pct</code> with <code>stop_pct_is_multiplier=true</code> → prod <strong>0.85</strong> (−15%).</li>
  <li><strong>Target:</strong> <code>entry × target_pct</code> → prod <strong>1.25</strong> (+25%).</li>
  <li><strong>Time stop:</strong> sell at close when bars held ≥ <code>time_stop_days</code> → prod <strong>252</strong> (set <code>RS_TIME_STOP=0</code> to disable).</li>
  <li><strong>No-follow-through:</strong> <code>no_ft_days=0</code> (off) in production.</li>
  <li><strong>sell_breakdown:</strong> <code>off</code> in production (research: breakdown_plus / only / both).</li>
  <li>Gap / shared host exit schedule otherwise matches BRT Closed writers (no zone pivots).</li>
</ul>
<div class="callout warn">
  <strong>Fidelity:</strong> stop and target can sit as broker orders. The <strong>252-bar time stop</strong>
  is not a broker order — sell manually when due (watch Pending sells after DailyRun).
</div>

<h2>4. Levers</h2>
<p class="lede" style="margin-bottom:10px">Values from <code>run_rs.bat</code> + freeze <code>rs_baseline_260807141317</code>. Effects are directional tendencies from A/B history — not guarantees.</p>
"""
        + levers([
            ("<code>target_pct</code>", "Take-profit as entry multiplier", "<strong>1.25</strong>", "Higher → fewer TARGET hits, longer holds; lower → more TARGET exits, smaller avg win"),
            ("<code>stop_pct</code> + multiplier", "Stop as entry multiplier", "<strong>0.85</strong> / true (−15%; prior 0.88 = −12%)", "Lower multiplier = wider stop → fewer STOPs, larger losers. Prod adopted 0.85 from post-252 A/B"),
            ("<code>time_stop_days</code> (<code>RS_TIME_STOP</code>)", "Hard exit after N bars held", "<strong>252</strong>", "Shorter → more TIME exits; 0 = off. Adopted arm <code>15_time_252</code>"),
            ("<code>symbol_reentry_cooldown_days</code>", "Min days before re-arming same symbol", "<strong>60</strong>", "Higher → fewer re-entries (cuts post-TARGET STOP churn)"),
            ("<code>rs_require_tc_strong</code>", "Require stock IND_TC outlooks Strong on T", "<strong>true</strong>", "On → fewer, higher-quality regime entries"),
            ("<code>rs_spy_int_tc_not_weak</code>", "Block when lagged SPY int TC is Weak", "<strong>true</strong>", "On → fewer entries in weak SPY regimes"),
            ("<code>rs_max_pct_below_52w_high</code>", "Close_T within X of 52w high (0=off)", "<strong>0</strong> (off)", "Tighten X → fewer near-high leadership entries"),
            ("<code>growth_filter_enabled</code>", "Close_T ≥ Close_{T−N}", "<strong>false</strong>", "On → fewer entries; quality mix depends on N"),
            ("<code>sell_breakdown</code>", "Exit on SPY_COMPARE / TC breakdown", "<strong>off</strong>", "On → earlier exits in regime breaks"),
            ("Universe CSV", "Whitelist symbols", "<strong>64</strong> FIT names", "Expand → more trades / capacity; shrink → concentration"),
        ])
        + """
<div class="callout warn">
  <strong>Stop multiplier reminder:</strong> <code>stop_pct=0.85</code> means stop at 85% of entry (−15%).
  Raising the multiplier <em>tightens</em> the stop.
</div>

<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun + reconcile gate"),
            ("Runner", "<code>run_rs.bat</code>"),
            ("Universe", "<code>drive/universes/RS_universe.csv</code> (64; twin <code>RS_universe_expand.csv</code>)"),
            ("Reconcile freeze", "<code>drive/paul_experiments/rs_baseline_260807141317/</code>"),
            ("Prior freezes", "<code>260807114545</code> (54 / stop 0.88 / ts 252); <code>260801111512</code> (54 / 0.88 / ts 0)"),
            ("Outputs", "<code>drive/RS_*_&lt;ts&gt;.*</code>, LatestRun copies"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>Gates use trigger bar T only — entry open can gap against you with no TC re-check.</li>
  <li>Requires indicator/TC + SPY series; <code>use_indicators=true</code>, <code>indicator_buy=off</code>.</li>
  <li><code>min_spy_compare_1y_at_trigger</code> and BRT <code>too_high_multiplier</code> are neutralized in <code>run_rs.bat</code> (would wrongly cut RS).</li>
  <li>Freeze Closed still lists ATEYY historically; production universe/gate no longer include it.</li>
  <li>Many A/B bats still default <code>RS_STOP=0.88</code> — that is research BASE, not current prod.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><span class="path">drive/paul_experiments/rs_baseline_260807141317/README.md</span> — freeze levers + metrics</li>
  <li><code>run_rs.bat</code> — production CLI</li>
  <li><span class="path">stock_analysis/rocket_tbn.py</span> — <code>relative_strength_enabled</code> / bar-scan entry</li>
  <li><span class="path">docs/TBN_VS_BRT.md</span> — DailyRun placement</li>
  <li><a href="../system_setup_process.html">System setup process</a></li>
</ul>
""",
        footer="Canonical RS write-up · Twin Beacon Networks (TBN) · production knobs from run_rs.bat",
    )


def sb() -> str:
    return page(
        title="SB — StockBee Momentum Burst",
        eyebrow="Production · StockBee Momentum Burst (SB)",
        lede=(
            "<strong>SB</strong> (StockBee Momentum Burst) captures the <em>start</em> of a 3–5 session impulse: "
            "a +4%+ expansion day after a tight coil, with volume up, Day's Close Range (DCR) strong, "
            "and not already day-2+ of a run. Risk is the signal-bar Low of Day (LOD)."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Module <code>rocket_stockbee_burst.py</code> via <code>sb_mode=true</code></span>"
            "<span>Runner <code>run_sb.bat</code> → <code>run_stockbee_burst.bat</code></span>"
            "<span>Prefix <code>SB_*</code></span>"
            "<span>Freeze <code>sb_baseline_260803184014</code></span>"
        ),
        body="""
<div class="callout ok">
  <strong>Status:</strong> Production / DailyRun step [10/14] (reconcile-gated), gold-56 universe.
  Playbook: Pradeep Bonde (StockBee) — short impulse burst after compression → day-1 range expansion.
  Skip with <code>SKIP_SB=1</code>.
</div>
<div class="callout">
  Deeper theory already exists. Canonical:
  <span class="path">drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/10_theory.md</span>,
  <span class="path">HOW_TO_RUN.html</span>,
  <span class="path">sb_baseline_260803184014/README.md</span>,
  <span class="path">stock_analysis/SB_Burst_DNA_Columns.md</span>.
</div>

<h2>1. What it is</h2>
<p>
  No earnings catalyst required. Role: short-hold diversity sleeve vs multi-week systems
  (Minervini Volatility Contraction Pattern / Relative Strength / zone retests).
</p>

<h2>2. Entry logic</h2>
<p>Signal bar <strong>T</strong> — all must pass (<code>_signal_at</code> in <code>rocket_stockbee_burst.py</code>):</p>
<ol class="steps">
  <li><strong>% day:</strong> <code>Close_T / Close_{T-1} − 1 ≥ burst_min_pct</code> (prod <strong>0.04</strong> = +4%).</li>
  <li><strong>Volume:</strong> <code>Volume_T &gt; Volume_{T-1}</code> when <code>burst_vol_gt_prior=true</code>.</li>
  <li><strong>Range expansion:</strong> <code>(H−L)_T</code> strictly larger than each of the prior <code>burst_range_lookback</code> (prod <strong>5</strong>) daily ranges.</li>
  <li><strong>DCR:</strong> <code>(C−L)/(H−L) ≥ burst_dcr_min</code> (prod <strong>0.70</strong>).</li>
  <li><strong>Start-of-swing:</strong> consecutive large-up days ending at T−1 ≤ <code>burst_max_prior_up_days</code> (prod <strong>1</strong> → reject if ≥2 already into T).</li>
  <li><strong>Price:</strong> <code>Close_T ≥ burst_min_price</code> (prod <strong>$5</strong>).</li>
  <li>Optional (prod <strong>off</strong>): Market Monitor gate, T−1 narrow/down, vol-vs-50d-avg, ATR%/52w-high gates.</li>
  <li><strong>Fill:</strong> next open T+1 (<code>burst_fill=next_open</code>). Accept only if open &gt; LOD and risk <code>(open−LOD)/open ≤ burst_max_risk_pct</code>. Else <code>TOO_LOW</code> / <code>TOO_HIGH</code> → RejectedFills.</li>
</ol>

<h2>3. Exit logic</h2>
<p>Priority order on each bar while in trade:</p>
<ol class="steps">
  <li><strong>Stop:</strong> signal-bar LOD. Gap through → <code>GAP_DOWN</code> @ open; else <code>STOP_LOSS</code> @ stop.</li>
  <li><strong>Target:</strong> <code>entry × target_pct</code> → prod <strong>1.097</strong> (~+9.7%).</li>
  <li><strong>NO_FT:</strong> if held ≥ <code>burst_no_ft_days</code> (prod <strong>3</strong>) and never <code>Close &gt; entry</code> → exit @ close.</li>
  <li><strong>TIME:</strong> if held ≥ <code>burst_time_stop_days</code> (prod <strong>5</strong>) → exit @ close.</li>
</ol>
<div class="callout warn">
  <strong>Fidelity:</strong> enter the LOD stop and target as usual. <strong>NO_FT (3d)</strong> and
  <strong>time stop (5d)</strong> are not broker orders — sell manually. After DailyRun, watch
  Pending sells for <code>SB no follow-through (3d)</code> / <code>SB time stop (5d)</code>.
</div>

<h2>4. Levers</h2>
<p>Production values from <code>run_stockbee_burst.bat</code> / freeze <code>sb_baseline_260803184014</code>. Theory doc historically listed max_risk=0.03 / target 1.10 — superseded.</p>
"""
        + levers([
            ("<code>burst_min_pct</code>", "Min day % move for signal", "<strong>0.04</strong>", "Higher → fewer, stronger bursts"),
            ("<code>burst_dcr_min</code>", "Min day's close range", "<strong>0.70</strong>", "Higher → fewer weak-close expansions"),
            ("<code>burst_range_lookback</code>", "Prior days each must have smaller range", "<strong>5</strong>", "Longer lookback → stricter compression→expansion"),
            ("<code>burst_vol_gt_prior</code>", "Require V_T &gt; V_{T−1}", "<strong>true</strong>", "Off → more signals without participation"),
            ("<code>burst_max_prior_up_days</code>", "Max consecutive +min_pct days before T", "<strong>1</strong>", "0 = only true day-1 starts; higher → chase further into the run"),
            ("<code>burst_min_price</code>", "Min Close_T", "<strong>5</strong>", "Higher floor → fewer low-priced bursts"),
            ("<code>burst_max_risk_pct</code> (<code>SB_MAX_RISK</code>)", "Reject fill if (open−LOD)/open &gt; R", "<strong>0.078</strong>", "Lower → more TOO_HIGH rejects, tighter risk. Theory 0.03 is research/restore only"),
            ("<code>target_pct</code> (<code>SB_TARGET</code>)", "Profit target multiplier", "<strong>1.097</strong>", "Higher → fewer TARGET hits, more TIME/NO_FT. Prior Seed-opt 1.10 obsolete"),
            ("<code>burst_time_stop_days</code> (<code>SB_TIME_STOP</code>)", "Hard flat by day N", "<strong>5</strong>", "Shorter → faster recycling, more TIME exits"),
            ("<code>burst_no_ft_days</code> (<code>SB_NO_FT</code>)", "Exit if never green by day N", "<strong>3</strong>", "Shorter → cuts dead trades faster"),
            ("<code>burst_mm_gate</code>", "Market Monitor breadth gate", "<strong>false</strong> (off)", "On → idle/filter in weak breadth"),
            ("<code>burst_size_from_stop</code>", "Risk-frac share sizing vs host dollar scale", "<strong>false</strong> (host parity)", "true = Seed-opt research $R path; changes PnL scale, not signal count"),
            ("Universe", "Gold whitelist", "<strong>56</strong> names", "Expand dilutes edge (see 90_universe_expand); ALL = full CSV scan"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun + reconcile gate"),
            ("Runner", "<code>run_sb.bat</code> → <code>run_stockbee_burst.bat</code>"),
            ("Universe", "<code>drive/universes/SB_universe.csv</code> (56)"),
            ("Reconcile freeze", "<code>drive/paul_experiments/sb_baseline_260803184014/</code> (1.097 / 0.078)"),
            ("Obsolete freeze", "<code>sb_baseline_260803121109</code> (1.10 / 0.08) — do not use"),
            ("Sizing", "Host parity: 500k × 2 × 0.6 = 600k deployable / max_positions; <code>--aggressive</code> default"),
            ("Outputs", "<code>drive/SB_*_&lt;ts&gt;.*</code> incl. RejectedFills, burst DNA columns"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>Theory <code>10_theory.md</code> still mentions max_risk 0.03 / target ~+10% — production is <strong>0.078 / 1.097</strong>.</li>
  <li>Never pass <code>entry_start_date</code> / <code>start_date</code> on production runs (research AB only).</li>
  <li>LOD stop can be gapped through at open; RejectedFills are expected when open is outside the buy band.</li>
  <li>Optional gates (MM, T1, vol-vs-50) default off — DNA columns still recorded for correlation.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><span class="path">drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/HOW_TO_RUN.html</span></li>
  <li><span class="path">drive/paul_experiments/tbn_new_systems/stockbee_momentum_burst/10_theory.md</span></li>
  <li><span class="path">drive/paul_experiments/sb_baseline_260803184014/README.md</span></li>
  <li><span class="path">stock_analysis/rocket_stockbee_burst.py</span>, <span class="path">stock_analysis/SB_Burst_DNA_Columns.md</span></li>
</ul>
""",
        footer="Canonical SB write-up · Twin Beacon Networks (TBN) · production knobs from run_stockbee_burst.bat",
    )


def rl() -> str:
    return page(
        title="RL — Rocket Launcher",
        eyebrow="Production · Rocket Launcher (RL)",
        lede=(
            "<strong>RL</strong> (Rocket Launcher) is the 50-day Simple Moving Average (SMA) dip-and-stack "
            "launcher for liquid mega-caps. AWK <code>portfolio_audit.awk</code> math is authoritative; "
            "the Python port (<code>rocket_rl.py</code>) must stay in parity before lever promotion."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Mode <code>rl_mode=true</code></span>"
            "<span>Runner <code>run_rl.bat</code> · AWK <code>run_audit.bat</code> · <code>run_rl_compare.bat</code></span>"
            "<span>Prefix <code>RL_*</code> (+ <code>BRT_Closed_RL_*</code> mirrors)</span>"
        ),
        body="""
<div class="callout ok">
  <strong>Status:</strong> Production gold · DailyRun steps [2–3/14] run AWK then Python then compare.
  Treat AWK as ground truth for RL math. Isolate from BRT/YH/IND zone paths via
  <code>rl_mode=true</code> with <code>brt_zones=false</code> / <code>yh_zones=false</code> / <code>indicator_buy=off</code>.
</div>
<div class="callout">
  Bar order (AWK + Python): lagged peak/ATR/shock on the <em>prior</em> bar, signal on the
  <em>current</em> bar, fill at the <strong>next open</strong>.
</div>

<h2>1. What it is</h2>
<p>
  RL waits for a stacked SMA tape (20&gt;50&gt;100&gt;200) with a rising 50-SMA, then buys a
  controlled dip into a ±4.1% band around yesterday’s 50-SMA, provided expansion, acceptance
  (8 of 10 closes above the prior 50-SMA), peak, and fill gates pass. It is <em>not</em> a zone-retest system.
  Sizing is fixed <code>rl_cash</code> (default $47,500 per name), not the host 500k×2×0.6 deployable path.
</p>
<p>
  Seed / gold list: <span class="path">data/rl_gold_universe.txt</span> (keep in sync with
  <span class="path">drive/universes/RL_universe.csv</span>). Typical MarkTen mega-caps.
  Optional per-symbol JSON: <span class="path">stock_analysis/Per_Symbol_Optimized_Settings_Approved_Latest.json</span>.
</p>

<h2>2. Entry logic</h2>
<p>Signal bar <strong>T</strong> (Python <code>rocket_rl.py</code> dip gate, AWK 50-trigger path):</p>
<ol class="steps">
  <li><strong>SMA stack + 200-SMA exists:</strong> SMA20 &gt; SMA50 &gt; SMA100 &gt; SMA200, all finite/positive. <code>rl_sma_qual=1</code> (prod on).</li>
  <li><strong>50-SMA rising:</strong> SMA50[T] &gt; SMA50[T − <code>rl_50_sma_lookback</code>] (prod lookback <strong>4</strong>).</li>
  <li><strong>In the 50-zone:</strong> Low_T is inside yesterday’s 50-SMA × <code>rl_dip_pct</code> band. Prod <code>rl_dip_pct=1.041</code> → band is SMA50 × 0.959 … SMA50 × 1.041 (±4.1%).</li>
  <li><strong>Uptick + close above 50-SMA:</strong> Close_T &gt; Open_T and Close_T &gt; yesterday’s SMA50.</li>
  <li><strong>Expansion:</strong> some close in the last <code>expansion_lookback_days</code> (10) ≥ prior-bar SMA50 × <code>rl_expansion</code> (prod <strong>1.163</strong>).</li>
  <li><strong>Acceptance:</strong> at least <code>rl_acc_min</code> of the last <code>rl_acc_count</code> bars close above prior SMA50 (defaults <strong>8 / 10</strong>).</li>
  <li><strong>Cut-the-losers / ATR% / peak / slope / shock / volume</strong> as configured. Prod <code>run_rl.bat</code> sets <code>ATR_LOW=off</code>, <code>ATR_HIGH=off</code>, <code>rl_slope_threshold=0</code> (those filters off).</li>
  <li><strong>Too-low reject:</strong> next open &lt; signal Low × <code>rl_stop_pct</code> (0.934) → no fill.</li>
  <li><strong>Too-high fill gate:</strong> prod <code>rl_too_high=0</code> (off). When on: next open must be ≤ signal Low × too_high × stop_pct. Historical production used 1.14.</li>
  <li><strong>Fill:</strong> T+1 open. Do not re-check dip/stack on the entry bar.</li>
</ol>

<h2>3. Exit logic</h2>
<ul>
  <li><strong>Stop:</strong> signal-bar Low × <code>rl_stop_pct</code> → prod / AWK default <strong>0.934</strong> (−6.6% vs signal low).</li>
  <li><strong>Target:</strong> SMA50 × <code>rl_target_pct</code> → AWK/Python default <strong>1.20</strong>. Anchored to the 50-SMA (not entry) and <em>updated while the trade is open</em>.</li>
  <li>Shared gap-down / gap-up / intraday stop / target schedule (first match wins), matching AWK bar order.</li>
  <li>Trail / partial / flush / time-exit levers exist in AWK BEGIN; Python honors the same config fields. Prod bat does not turn trails on.</li>
  <li>Post-TARGET re-entry window: prod <code>rl_post_target_reentry_bars=0</code> (off).</li>
  <li>AWK-only subsystems (not in the Python 50-trigger port): RL100 (100-SMA) and Dive Bomber shorts — audit defaults show them off.</li>
</ul>

<h2>4. Levers</h2>
<p>Production from <code>run_rl.bat</code>; remaining defaults from <code>RLConfig</code> / AWK BEGIN. Do not promote a Python-only lever until AWK compare is clean.</p>
"""
        + levers([
            ("<code>rl_dip_pct</code>", "Half-width of the 50-SMA dip band", "<strong>1.041</strong> (±4.1%)", "Tighter band → fewer dips that qualify"),
            ("<code>rl_sma_qual</code>", "Require SMA stack + rising 50", "<strong>1</strong> (on)", "Off → many more unstructured dips"),
            ("<code>rl_50_sma_lookback</code>", "Bars for “50-SMA rising”", "<strong>4</strong> (config default)", "Longer lookback → slower trend confirmation"),
            ("<code>rl_stop_pct</code>", "Stop = signal Low × multiplier", "<strong>0.934</strong>", "Lower multiplier = wider stop"),
            ("<code>rl_target_pct</code>", "Target = prior SMA50 × multiplier", "<strong>1.20</strong> (config default)", "Higher → fewer TARGET hits, longer holds"),
            ("<code>rl_too_high</code>", "Fill ceiling vs signal Low × stop", "<strong>0</strong> (off)", "On (hist 1.14) rejects opens that gap too far above the stop line"),
            ("<code>rl_expansion</code>", "Min close vs SMA50 for expansion", "<strong>1.163</strong> (config default)", "Higher → require a stronger prior thrust"),
            ("<code>rl_acc_min</code> / <code>rl_acc_count</code>", "Acceptance: closes above SMA50 in window", "<strong>8 / 10</strong>", "Higher min → fewer accepted dips"),
            ("<code>rl_cash</code>", "Fixed notional per name", "<strong>$47,500</strong>", "RL does not use host 600k deployable / max_positions"),
            ("<code>ATR_LOW</code> / <code>ATR_HIGH</code>", "ATR% band at signal", "<strong>off / off</strong> in prod bat", "Config defaults 2.44% / 8.48% if not overridden"),
            ("<code>rl_slope_threshold</code>", "Min 30-bar slope", "<strong>0</strong> (off in prod bat)", "Config default 0.0643 if not overridden"),
            ("<code>rl_cut_the_losers</code>", "Prior-bar high vs SMA50 cap", "<strong>0.25</strong> (config default)", "Blocks entries already extended above the 50"),
            ("Per-symbol JSON", "Approved overlay on gold names", "Loaded when file exists", "Keep JSON <code>rl_too_high=0</code> in sync with the bat"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun AWK → Python → compare"),
            ("Runners", "<code>run_audit.bat</code> (AWK) · <code>run_rl.bat</code> (Python) · <code>run_rl_compare.bat</code>"),
            ("Universe", "<code>drive/universes/RL_universe.csv</code> · keep <code>data/rl_gold_universe.txt</code> in sync"),
            ("Engine", "<span class='path'>stock_analysis/rocket_rl.py</span> + <span class='path'>rocket_rl_config.py</span> via TBN host"),
            ("AWK source of truth", "<span class='path'>portfolio_audit.awk</span> 50-trigger path"),
            ("Outputs", "<code>drive/RL_*_&lt;ts&gt;.*</code>; some reports still read <code>BRT_Closed_RL_*</code> mirrors"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li><strong>AWK wins</strong> on math disagreements. Do not DailyRun-wire a Python-only knob.</li>
  <li><code>rl_too_high=1</code> with stop 0.934 almost never fills (open would have to be below the signal low). Prod is <strong>0 / off</strong>.</li>
  <li>Target is anchored to the 50-SMA, not to entry — reward/risk vs entry therefore moves with how deep the dip was.</li>
  <li>IND_TC columns are not on RL_Closed yet (indicators only for optional mandatory/exclude gates; prod off).</li>
  <li>Charts / CRWD-style HTML are <em>not</em> in DailyRun: <code>python stock_analysis/rl_post_run_analysis.py --stamp &lt;ts&gt; --charts</code>.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><code>run_rl.bat</code> · <code>run_audit.bat</code> · <code>run_rl_compare.bat</code></li>
  <li><span class="path">stock_analysis/rocket_rl.py</span>, <span class="path">rocket_rl_config.py</span></li>
  <li><a href="../system_setup_process.html">System setup process</a> — AWK ↔ Python parity callout</li>
  <li><span class="path">docs/TBN_VS_BRT.md</span></li>
</ul>
""",
        footer="Canonical RL write-up · Twin Beacon Networks (TBN) · AWK portfolio_audit.awk is authoritative",
    )


def yh() -> str:
    return page(
        title="YH — Year High",
        eyebrow="Production · Year High (YH)",
        lede=(
            "<strong>YH</strong> (Year High) trades year-high / band setups on the Twin Beacon Networks (TBN) "
            "zone path with Break and ReTest (BRT) zones off. A new 52-week high becomes a candidate; "
            "the zone activates after a 3% move-away, then the book looks for breakout → support retest."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Mode <code>yh_zones=true</code> · <code>brt_zones=false</code></span>"
            "<span>Runner <code>run_yh.bat</code></span>"
            "<span>Prefix <code>YH_*</code></span>"
        ),
        body="""
<div class="callout ok">
  <strong>Status:</strong> Production gold · DailyRun step [6/14].
  Production universe is Mag9-style without TSLA (<span class="path">drive/universes/YH_universe.csv</span>).
</div>

<h2>1. What it is</h2>
<p>
  YH is a <em>zone origin</em> swap on the shared TBN host: zones come from rolling year-highs
  rather than BRT pivot-touch maturity. Once a YH zone is active, breakout / retest / fill /
  stop / target still ride the host’s zone path (not the Relative Strength or Rocket Launcher engines).
</p>

<h2>2. Entry logic</h2>
<ol class="steps">
  <li><strong>New YH:</strong> High[t] &gt; MAX(High[t − <code>yh_lookback</code> : t−1]) after warmup. Prod lookback <strong>252</strong> trading days.</li>
  <li><strong>Activation (sheet memory):</strong> rounded High ≥ YH × (1 + <code>yh_move_away_pct</code>). Prod <strong>0.03</strong> (3% move away). <code>yh_memory_mode=sheet</code> matches the YH-tab state machine (active level + next candidate), not a single persisted cell.</li>
  <li><strong>Zone band:</strong> YH price × (1 ± <code>band_pct</code>). Prod <strong>0.015</strong> (±1.5%).</li>
  <li><strong>Breakout → retest → green entry</strong> on the host zone path (same family as BRT once the zone exists).</li>
  <li><strong>Growth filter:</strong> prod <code>growth_filter_enabled=true</code>, <code>growth_bars=756</code> (close ≥ close 3 years ago).</li>
  <li><strong>Fill:</strong> next open after the signal bar (host convention).</li>
  <li>SPY-compare / ATR% / indicator-buy gates are neutralized in <code>run_yh.bat</code> (<code>use_indicators=false</code>, <code>indicator_buy=off</code>, spy/ATR bounds 0).</li>
</ol>

<h2>3. Exit logic</h2>
<ul>
  <li><strong>Stop:</strong> multiplier <code>stop_pct=0.934</code> (<code>stop_pct_is_multiplier=true</code>).</li>
  <li><strong>Target:</strong> <code>target_pct=1.21</code> (+21% vs entry).</li>
  <li><strong>Stop compare:</strong> <code>stop_compare_round_decimals=-1</code> (full-float vs Low/High — YH-only; shared TBN default remains 2 decimals for BRT/WPBR/RL/RS). Fixes false STOPs such as AU 2025-02-28 (stop 28.44964 vs Low 28.45).</li>
  <li><code>too_high_multiplier=0</code> (off). <code>strong_pivot_mode=off</code>.</li>
  <li>Gap-down / gap-up / intraday stop / target — first match wins (host schedule).</li>
</ul>

<h2>4. Levers</h2>
"""
        + levers([
            ("<code>yh_lookback</code>", "Trading days for rolling 52w high", "<strong>252</strong>", "Shorter → more/fresh YH events"),
            ("<code>yh_move_away_pct</code>", "Rally above YH before zone activates", "<strong>0.03</strong>", "Higher → fewer activations, more confirmed thrust"),
            ("<code>yh_memory_mode</code>", "Candidate queue (sheet / fifo / parallel)", "<strong>sheet</strong>", "fifo/parallel are test variants — do not silently swap"),
            ("<code>band_pct</code>", "Zone half-width around YH price", "<strong>0.015</strong>", "Wider band → easier retests, noisier levels"),
            ("<code>target_pct</code>", "Take-profit vs entry", "<strong>1.21</strong>", "Higher → fewer TARGET hits"),
            ("<code>stop_pct</code>", "Stop multiplier", "<strong>0.934</strong>", "Lower multiplier = wider stop"),
            ("<code>stop_compare_round_decimals</code>", "Round stop vs Low/High", "<strong>−1</strong> (full float)", "2-dec round can false-STOP (AU example)"),
            ("<code>growth_filter_enabled</code> / <code>growth_bars</code>", "3-year growth gate", "<strong>true / 756</strong>", "Off → more names without a 3Y advance"),
            ("<code>strong_pre/post_pivot_*</code>", "Strong-pivot geometry (unused when mode=off)", "pre 7/0.12 · post 7/0.109 · mode <strong>off</strong>", "On would filter YH origins like BRT pivots"),
            ("<code>too_high_multiplier</code>", "Gap-up fill reject", "<strong>0</strong> (off)", "On (e.g. 1.058) is a research override"),
            ("<code>max_market_cap</code>", "Post-enrich cap filter", "<strong>0</strong> (disabled)", "Engine default bound can wipe names when Yahoo omits cap (AMD class of bug)"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun"),
            ("Runner", "<code>run_yh.bat</code>"),
            ("Universe", "<code>drive/universes/YH_universe.csv</code> (Mag9-style, no TSLA in prod list)"),
            ("Engine", "TBN host <code>yh_zones=true</code> — see <code>_compute_yh_zones</code> in <span class='path'>rocket_tbn.py</span>"),
            ("A/B ledger", "<span class='path'>drive/paul_experiments/YH_Deep_Analysis.html</span>"),
            ("Outputs", "<code>drive/YH_*_&lt;ts&gt;.*</code>"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>Do not enable BRT or WPBR zones on the same run — YH owns zone origin.</li>
  <li>Sheet-mode activation uses rounded High vs full-precision Active YH Touch Price (AAPL 2014-10-22 / NVDA examples in the engine docstring).</li>
  <li>Param-hint A/Bs froze stop/target/band — do not retune on out-of-sample (OOS) to “fix” a soft year.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><code>run_yh.bat</code></li>
  <li><span class="path">stock_analysis/rocket_tbn.py</span> — Year-High zone engine</li>
  <li><span class="path">drive/paul_experiments/YH_Deep_Analysis.html</span></li>
  <li><a href="../system_setup_process.html">System setup process</a></li>
</ul>
""",
        footer="Canonical YH write-up · Twin Beacon Networks (TBN) · production knobs from run_yh.bat",
    )


def brt() -> str:
    return page(
        title="BRT — Break and ReTest",
        eyebrow="Production · Break and ReTest (BRT)",
        lede=(
            "<strong>BRT</strong> (Break and ReTest) is the core daily pivot-zone sleeve hosted by "
            "Twin Beacon Networks (TBN). TBN is the engine; BRT is one system prefix (<code>BRT_*</code>). "
            "It buys acceptance above a matured pivot band on a support retest."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Mode <code>brt_zones=true</code> · <code>yh_zones=false</code></span>"
            "<span>Runner <code>run_brt.bat</code></span>"
            "<span>Prefix <code>BRT_*</code></span>"
            "<span>Spec <span class='path'>stock_analysis/BRT_LOGIC_SPEC.md</span></span>"
        ),
        body="""
<div class="callout">
  <strong>TBN vs BRT:</strong> do not rename engine docs as “BRT engine.”
  See <span class="path">docs/TBN_VS_BRT.md</span>.
</div>
<div class="callout ok">
  <strong>Status:</strong> Production gold · DailyRun step [4/14].
  Optional research flag <code>brt_like_wpbr=true</code> is <strong>off</strong> in production
  (WPBR-like daily package on BRT zones — see spec § BRT_Like_WPBR).
</div>

<h2>1. What it is</h2>
<p>
  Pivots create touches; overlapping touches inside a <code>band_pct</code> envelope mature a zone
  (default 2 touches). After maturity, a bullish candle (same day or next) arms a next-open entry,
  subject to tight-range, level-acceptance, growth, and sheet red-to-green gates.
</p>

<h2>2. Entry logic</h2>
<p>Condensed from <span class="path">BRT_LOGIC_SPEC.md</span> + <code>run_brt.bat</code> freeze:</p>
<ol class="steps">
  <li><strong>Pivots:</strong> local high/low in a ±k window with future confirmation (drop/rally). Sheet-touch Final Pivot High also requires post-drop and not-also-pivot-low. Consecutive same-price Final PHs are allowed (PO 2026-07-20).</li>
  <li><strong>Zone band:</strong> touch price × (1 ± <code>band_pct</code>). Prod <strong>0.0154</strong>. Overlapping bands are <em>not</em> merged.</li>
  <li><strong>Maturity:</strong> touch count in <code>lookback_long</code> reaches <code>touch_threshold</code> (sheet <strong>2</strong>).</li>
  <li><strong>Strong-pivot filter:</strong> prod pre 7 bars / 8.1%, post 7 / 10.8% (bat sets the percents; spec default mode is pre).</li>
  <li><strong>Tight range:</strong> (max high / min low − 1) over 105 bars must be &gt; 35% or the level is blocked (dead-range qualifier).</li>
  <li><strong>Level acceptance (7/10):</strong> at least 7 of the last 10 bars close above the anchored zone lower, tied to Support Test when enabled.</li>
  <li><strong>Bullish candle window:</strong> Close &gt; Open on the maturity bar <em>or</em> the next bar only. Fill = next session open after that candle.</li>
  <li><strong>Sheet red-to-green:</strong> prod <code>sheet_red_to_green_entry_enabled=true</code>.</li>
  <li><strong>Growth filter:</strong> prod on. <code>brt_sheet_touch=true</code>. <code>min_spy_compare_1y_at_trigger=-1000</code> (neutralized). Cap filters 0 (disabled).</li>
</ol>

<h2>3. Exit logic</h2>
<ol class="steps">
  <li>Gap down: Open ≤ stop → <code>GAP_DOWN</code> @ open</li>
  <li>Gap up through target: Open ≥ target → <code>GAP_UP</code> @ open</li>
  <li>Intraday stop: Low ≤ stop → <code>STOP_LOSS</code> @ stop</li>
  <li>Intraday target: High ≥ target → <code>TARGET</code> @ target</li>
</ol>
<ul>
  <li>Prod stop <code>stop_pct=0.934</code> (multiplier vs trigger/entry-bar low per spec/host).</li>
  <li>Prod target <code>target_pct=1.21</code> (entry × 1.21). Always multiplier form — do not mix with percent-add form.</li>
  <li><code>too_high_multiplier=0</code> (off).</li>
</ul>

<h2>4. Levers</h2>
"""
        + levers([
            ("<code>band_pct</code>", "Zone half-width around touch price", "<strong>0.0154</strong>", "Wider → more overlapping/mature zones"),
            ("<code>stop_pct</code>", "Stop multiplier", "<strong>0.934</strong>", "Lower multiplier = wider stop"),
            ("<code>target_pct</code>", "Take-profit vs entry", "<strong>1.21</strong>", "Higher → fewer TARGET hits"),
            ("<code>strong_pre_pivot_pct</code> / bars", "Pre-pivot thrust", "<strong>0.081 / 7</strong>", "Higher % → fewer “strong” pivots"),
            ("<code>strong_post_pivot_pct</code> / bars", "Post-pivot follow-through", "<strong>0.108 / 7</strong>", "Higher % → stricter confirmation"),
            ("<code>breakout_bars</code>", "Breakout lookback", "<strong>100</strong>", "Sheet C-cell analog"),
            ("<code>tight_range_threshold_pct</code> / lookback", "Dead-range block", "<strong>0.35 / 105</strong>", "Higher threshold → more blocks"),
            ("<code>brt_sheet_touch</code>", "Sheet Final-PH touch stream", "<strong>true</strong>", "Off → engine pivot-only stream"),
            ("<code>sheet_red_to_green_entry_enabled</code>", "Red-to-green entry gate", "<strong>true</strong>", "Off → more fills without that sheet rule"),
            ("<code>growth_filter_enabled</code>", "Growth gate", "<strong>true</strong>", "Off → more names without the advance"),
            ("<code>too_high_multiplier</code>", "Gap-up fill reject", "<strong>0</strong> (off)", "On is research"),
            ("<code>brt_like_wpbr</code>", "Daily WPBR-like break/confirm/retest package", "<strong>false</strong> (prod)", "Research only — leaves stops/targets/zones classic BRT"),
            ("<code>max_market_cap</code>", "Post-enrich cap filter", "<strong>0</strong> (disabled)", "Default bound can wipe AMD-class names"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun"),
            ("Runner", "<code>run_brt.bat</code> → <span class='path'>stock_analysis/rocket_tbn.py</span>"),
            ("Universe", "<code>drive/universes/BRT_universe.csv</code>"),
            ("Per-symbol overlay", "<span class='path'>stock_analysis/Per_Symbol_Optimized_Settings_Approved_Latest.json</span> when present"),
            ("Outputs", "<code>BRT_Closed_*</code>, <code>BRT_Open_*</code>, Scanner / Watchlist / Report / Summary"),
            ("Workers", "<code>-w 32</code> · <code>--aggressive</code> · <code>--print-zones</code>"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>Spec stop-reference language (trigger-bar low vs entry-bar low) is in <span class="path">BRT_LOGIC_SPEC.md</span> — production uses the host’s current <code>stop_loss_based</code> / multiplier path; do not mix percent-form <code>stop_pct</code>.</li>
  <li>Sheet ladder (DE/DF/DG) is optional parity — see spec §3.5 and <span class="path">SHEET_PARITY_DIFF.md</span>.</li>
  <li>Related sleeves: <a href="wpbr.html">WPBR</a> (weekly pivots), <a href="yh.html">YH</a> (year-high origin), <a href="mts.html">MTS</a> (sheet BI first-touch, not BRT retest), <a href="ind.html">IND</a> (deprecated).</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><span class="path">stock_analysis/BRT_LOGIC_SPEC.md</span></li>
  <li><span class="path">docs/TBN_VS_BRT.md</span></li>
  <li><code>run_brt.bat</code></li>
  <li><a href="../system_setup_process.html">System setup process</a></li>
</ul>
""",
        footer="Canonical BRT write-up · Twin Beacon Networks (TBN) · production knobs from run_brt.bat",
    )


def wpbr() -> str:
    return page(
        title="WPBR — Pivot Break and Retest",
        eyebrow="Production · Pivot Break and Retest (WPBR)",
        lede=(
            "<strong>WPBR</strong> (Pivot Break and Retest) builds <em>weekly</em> pivot zones, requires a "
            "weekly breakout plus confirmation, then buys a <em>daily</em> hold-above retest. "
            "It is not daily BRT and not the optional <code>brt_like_wpbr</code> research package."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Mode <code>wpbr_zones=true</code> (BRT/YH/VEC off)</span>"
            "<span>Runner <code>run_wpbr.bat</code></span>"
            "<span>Prefix <code>WPBR_*</code></span>"
            "<span>Module <span class='path'>stock_analysis/wpbr_zones.py</span></span>"
        ),
        body="""
<div class="callout ok">
  <strong>Status:</strong> Production gold · DailyRun step [8/14].
  Mag9 production universe (<span class="path">drive/universes/WPBR_universe.csv</span>).
  Comment in the bat: AMD is out of WPBR. Seed historically used the MarkTen mega-cap set
  (AAPL AMZN GOOGL META MSFT NVDA TSLA AU AMD NFLX) — production CSV is source of truth.
</div>
<div class="callout">
  Product decision (2026-07-22): <strong>the sheet wins</strong> on daily-retest scan.
  Default <code>retest_mode=stop_looking</code> (abandon-kill). Do not add
  <code>-v start_date=2016</code> on DailyRun — earlier pre-2016 trades are intentional in the current golden.
</div>

<h2>1. What it is</h2>
<p>
  Weekly pivot → zone band → Stage 1 weekly close above the upper band → Stage 2 weekly high
  confirmation (+3%) → daily retest from the Monday after the confirmation week → green daily
  close in a short window → next-open fill.
</p>

<h2>2. Entry logic</h2>
<ol class="steps">
  <li><strong>Weekly pivot zones</strong> with strong-pivot either-mode: pre/post 3 bars / 10% (prod).</li>
  <li><strong>Stage 1 breakout:</strong> first weekly close &gt; zone_upper.</li>
  <li><strong>Stage 2 confirm:</strong> first weekly high &gt; zone_upper × (1 + <code>wpbr_breakout_confirmation</code>). Prod <strong>0.03</strong>. Same week allowed.</li>
  <li><strong>Daily retest</strong> starting the Monday after confirm week:
    <code>stop_looking</code> = first bar with Low ≤ upper AND Close &gt; upper, but <em>only before</em>
    the first Close &lt; zone_lower (sheet abandon-kill). No prior Close[r−1] ≥ lower gate.
    <code>keep_looking</code> is the legacy unbounded scan (A/B only).</li>
  <li><strong>Entry window:</strong> <code>wpbr_max_days_after_retest=2</code> (inclusive) for a green daily close above the upper band; fill = next open.</li>
  <li><strong>Second chance after win:</strong> prod <code>wpbr_second_chance_after_win=true</code>.</li>
  <li><code>sheet_no_entry_same_bar_after_exit=false</code> is forced (WPBR nosamebarexit off vs some sheet defaults).</li>
  <li>Growth filter <strong>off</strong>. SPY-compare floor neutralized (−1000). Indicators on for report columns, not as buy gates.</li>
</ol>

<h2>3. Exit logic</h2>
<ul>
  <li><strong>Stop:</strong> <code>stop_pct=0.91</code> (wider than BRT’s 0.934).</li>
  <li><strong>Target:</strong> <code>target_pct=1.22</code> (+22%).</li>
  <li>Host gap / stop / target schedule. HALF_UP retest compares + variant C pivot rounding live in <code>wpbr_zones.py</code>.</li>
</ul>

<h2>4. Levers</h2>
"""
        + levers([
            ("<code>band_pct</code>", "Weekly zone half-width", "<strong>0.015</strong>", "Wider → easier weekly BO/retest"),
            ("<code>wpbr_breakout_confirmation</code>", "Stage 2 high vs upper band", "<strong>0.03</strong>", "Higher → stricter weekly confirm"),
            ("<code>wpbr_max_days_after_retest</code>", "Green-entry window after retest", "<strong>2</strong>", "Longer → more late greens"),
            ("<code>retest_mode</code>", "Daily scan terminate rule", "<strong>stop_looking</strong> (sheet)", "<code>keep_looking</code> is legacy A/B only"),
            ("<code>wpbr_second_chance_after_win</code>", "Re-arm after a winning exit", "<strong>true</strong>", "Off → one-and-done per zone episode"),
            ("<code>strong_pivot_mode</code>", "Pre/post/either/both", "<strong>either</strong> · 3 bars / 10%", "Stricter modes cut pivot inventory"),
            ("<code>target_pct</code>", "Take-profit vs entry", "<strong>1.22</strong>", "Higher → fewer TARGET hits; longer holds (WPBR avg hold is multi-month)"),
            ("<code>stop_pct</code>", "Stop multiplier", "<strong>0.91</strong>", "Wider than BRT 0.934"),
            ("<code>wpbr_merge_overlapping_zones</code>", "Merge overlapping weekly bands", "<strong>false</strong> (optional on)", "On → ZONE_STRENGTH = member count"),
            ("<code>growth_filter_enabled</code>", "3-year growth gate", "<strong>false</strong>", "On would cut Mag9 history"),
            ("<code>start_date</code>", "Entry/pivot window", "<strong>unset</strong> (full history)", "Do not add 2016 on DailyRun / reconcile freeze"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun Mag9"),
            ("Runner", "<code>run_wpbr.bat</code>"),
            ("Universe", "<code>drive/universes/WPBR_universe.csv</code>"),
            ("Engine", "<span class='path'>stock_analysis/wpbr_zones.py</span> via TBN host"),
            ("Parity tools", "<span class='path'>tools/run_wpbr_*_markten.py</span>"),
            ("Outputs", "<code>drive/WPBR_*_&lt;ts&gt;.*</code>"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>Do not confuse with <code>brt_like_wpbr</code> (daily package on BRT zones) or with BRT itself.</li>
  <li>Sheet <code>Daily Retest Row</code> abandon-kill is the production retest; META 48/48 is the parity story in the module docstring.</li>
  <li>Strength fields (POC, pre/post rise, …) are audit-only unless later promoted to gates.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><span class="path">stock_analysis/wpbr_zones.py</span></li>
  <li><span class="path">stock_analysis/BRT_LOGIC_SPEC.md</span> § WPBR standalone retest scan</li>
  <li><code>run_wpbr.bat</code></li>
  <li><a href="../system_setup_process.html">System setup process</a></li>
</ul>
""",
        footer="Canonical WPBR write-up · Twin Beacon Networks (TBN) · production knobs from run_wpbr.bat",
    )


def mts() -> str:
    return page(
        title="MTS — Magic Touch",
        eyebrow="Production · Magic Touch (MTS)",
        lede=(
            "<strong>MTS</strong> (Magic Touch) is the sheet-parity path against the STONK_DATA <em>MTS</em> tab "
            "(columns D:DP). It is not the Break and ReTest (BRT) retest pipeline: the buy gate is "
            "sheet <strong>BI</strong> on first touch after zone availability (DP), fill at next open."
        ),
        badge_class="badge-ok",
        badge_text="Production / DailyRun",
        meta=(
            "<span>Flag <code>--mts-sheet-parity</code> / <code>mts_mode=true</code></span>"
            "<span>Runners <code>run_mts.bat</code> · <code>run_mts_sheet.bat</code></span>"
            "<span>Prefix <code>MTS_*</code></span>"
        ),
        body="""
<div class="callout ok">
  <strong>Status:</strong> Production gold · DailyRun step [7/14].
  Universe SSoT: <span class="path">drive/universes/MTS_universe.csv</span>
  (also read by <span class="path">stock_analysis/mts_universe.py</span>).
</div>
<div class="callout">
  Exact BI precompute in the TBN host is authoritative. Approximate BRT gates are bypassed
  when <code>mts_mode</code> is on. See <code>mts_sheet_parity_overrides()</code> in
  <span class="path">stock_analysis/rocket_tbn.py</span>.
</div>

<h2>1. What it is</h2>
<p>
  Zones come from the sheet AF Touch Price stream (pivot-high <em>and</em> pivot-low), matured
  C14 = 7 bars later, then a 10-rung ladder overlap picks the active zone (DK:DN).
  Each zone episode fires <strong>one</strong> entry candidate on first touch (or when the active zone changes).
  There is <strong>no</strong> BY/DV retest-day COUNTIF (that is BRT/YH only).
</p>

<h2>2. Entry logic (sheet BI)</h2>
<p>BI = AND of:</p>
<ol class="steps">
  <li><strong>BW Growth 3 Year:</strong> Close ≥ Close[756 bars ago].</li>
  <li><strong>OR(BC, BC[-1]):</strong> Range Qualifier on this bar or prior (max high / min low over C24 − 1 &gt; C7).</li>
  <li><strong>BE:</strong> Close &gt; Open.</li>
  <li><strong>BG Level Acceptance:</strong> 7 closes above DK in the last 10 bars (needs AK).</li>
  <li><strong>OR(AQ, AQ[-1]):</strong> Zone Eligible Long on this bar or prior.</li>
</ol>
<p>
  <strong>When to evaluate:</strong> DP = first touch after availability (DO and (not DO[-1] or DN changed)).
  AW (AR≥C6 crossing) still counts touches but does <em>not</em> gate BC or create entries.
  Fill = next open after the first-touch bar.
</p>
<p>
  Additional bat overlays on top of the preset: <code>min_upper_wick_atr_at_trigger=0.25</code>,
  <code>min_dist_to_52w_high_pct_at_trigger=25</code>, <code>--symbol-reentry-cooldown-days 20</code>.
  <code>band_pct=0.018</code> is a <strong>manual override</strong> of optimizer 0.016.
</p>

<h2>3. Exit logic</h2>
<ul>
  <li><strong>Target:</strong> entry × <code>target_pct</code> → prod / sheet C3 path <strong>1.22</strong> (+22%).</li>
  <li><strong>Stop:</strong> signal-bar Low × <code>stop_pct</code> with <code>stop_loss_based=trigger_low</code> → <strong>0.934</strong> (sheet BJ / C4). Not entry-anchored.</li>
  <li>Host gap / stop / target schedule.</li>
</ul>

<h2>4. Levers</h2>
"""
        + levers([
            ("<code>band_pct</code>", "Zone half-width (C5 analog; bat override)", "<strong>0.018</strong> (optimizer was 0.016)", "Wider → more ladder overlaps / first touches"),
            ("<code>touch_threshold</code>", "Touches to mature (C6)", "<strong>2</strong>", "Higher → fewer matured zones"),
            ("<code>strong_pre_pivot_*</code>", "Pre-pivot thrust", "<strong>7 / 0.12</strong>", "Sheet C-cell analog"),
            ("<code>strong_post_pivot_*</code>", "Post-pivot follow-through", "<strong>7 / 0.06</strong>", "Looser post than BRT’s 0.108"),
            ("<code>target_pct</code>", "Take-profit vs entry", "<strong>1.22</strong>", "Sheet C3 / +22% cap language in overrides"),
            ("<code>stop_pct</code> + <code>stop_loss_based</code>", "Stop vs signal-bar low", "<strong>0.934 / trigger_low</strong>", "Do not switch to entry-anchored without a new freeze"),
            ("<code>symbol_reentry_cooldown_days</code>", "Re-arm delay after exit", "<strong>20</strong>", "Higher → fewer re-entries"),
            ("<code>min_upper_wick_atr_at_trigger</code>", "Upper-wick vs ATR gate", "<strong>0.25</strong>", "Higher → fewer first-touch fills"),
            ("<code>min_dist_to_52w_high_pct_at_trigger</code>", "Min % below 52w high", "<strong>25</strong>", "Blocks names already hugging the high"),
            ("<code>mts_first_touch_entry</code>", "One candidate per zone episode", "<strong>true</strong> (preset)", "Off would re-fire on later touches"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Production gold</strong> — DailyRun"),
            ("Runners", "<code>run_mts.bat</code> (then <code>run_copy_latest.bat</code>) · <code>run_mts_sheet.bat</code>"),
            ("Universe", "<code>drive/universes/MTS_universe.csv</code>"),
            ("Preset", "<code>--mts-sheet-parity</code> → <code>mts_sheet_parity_overrides()</code>"),
            ("Workers", "<code>-w 22</code> · <code>--aggressive</code>"),
            ("Outputs", "<code>drive/MTS_*_&lt;ts&gt;.*</code>"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>Do not describe MTS as “BRT with different numbers.” Magic Touch BI / DP first-touch is a different entry identity.</li>
  <li>Preset disables many BRT gates (red-to-green, magic touch, spy-compare, too-high, …). Bat-level wick/52w gates are extra on top.</li>
  <li><code>band_pct=0.018</code> is an explicit manual override — putting 0.016 back is a one-knob AB, not a silent restore.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><code>run_mts.bat</code> · <code>run_mts_sheet.bat</code></li>
  <li><span class="path">stock_analysis/rocket_tbn.py</span> — <code>mts_sheet_parity_overrides</code></li>
  <li><span class="path">stock_analysis/mts_universe.py</span></li>
  <li><a href="../system_setup_process.html">System setup process</a></li>
</ul>
""",
        footer="Canonical MTS write-up · Twin Beacon Networks (TBN) · production knobs from run_mts.bat + sheet preset",
    )


def vz() -> str:
    return page(
        title="VZ — Volume Zone",
        eyebrow="Research · Volume Zone (VZ) Break and Retest",
        lede=(
            "<strong>VZ</strong> (Volume Zone) is a research prototype: rolling max-volume days become "
            "High–Low (HL) price zones; after an upside break, the system buys a support retest. "
            "It is not Break and ReTest (BRT) production and is not DailyRun-wired."
        ),
        badge_class="badge-bad",
        badge_text="Research candidate — not DailyRun",
        meta=(
            "<span>Mode <code>vz_mode=true</code></span>"
            "<span>Runner <code>run_vz.bat</code></span>"
            "<span>Engine <span class='path'>tools/vol_zone_break_retest.py</span></span>"
            "<span>Freeze <code>vol_zone_v2_rw63_20260810</code></span>"
        ),
        body="""
<div class="callout bad">
  <strong>Not production gold. Not DailyRun-wired.</strong>
  House artifacts: <code>drive/VZ_*_&lt;ts&gt;.*</code> via the TBN host.
  Adopted freeze: entry gates <code>RESEARCH_CANDIDATE_V2_RW63</code> · exit <code>zone_atr05_ts40</code> ·
  house fill <code>entry_on=next_open</code>.
</div>
<div class="callout ok">
  <strong>Predictive timing:</strong> signal known at retest-bar <em>close</em> (uses that bar’s Low/High/Close).
  Default fill = <strong>next open</strong> (T+1). Never buys the open of the signal morning.
</div>

<h2>1. What it is</h2>
<p>
  Hypothesis: high-volume nodes act as support after acceptance above them.
  Default research universe is DualPaul78 (<code>drive/universes/VZ_universe.csv</code>).
</p>

<h2>2. Entry logic</h2>
<ol class="steps">
  <li><strong>Zone creation:</strong> each day after <code>lookback_days</code>, find the max-volume bar in the trailing window; when a new winner appears, create zone(s) that persist. Adopted freeze uses <strong>HL-only</strong>.</li>
  <li><strong>Break-up:</strong> close &gt; zone.hi (break_pct=0, break_atr=0 = no extra distance), having been at/below the top sometime prior.</li>
  <li><strong>Retest clock:</strong> within <code>retest_window</code> bars after break (adopted <strong>63</strong>).</li>
  <li><strong>Signal bar T:</strong> bar intersects the zone band (or near-miss within <code>retest_eps_pct</code> of zone.hi), approach from_above, close still ≥ zone.lo. Known only at/after T’s close.</li>
  <li><strong>Quality gates (v2):</strong> <code>first_retest_only=True</code>; <code>min_touches_before_entry ≥ 1</code>.</li>
  <li><strong>Fill:</strong> <code>entry_on=next_open</code> → Open of T+1. Alternate research: close of T. Forbidden: Open of T using T’s range.</li>
</ol>

<h2>3. Exit logic</h2>
<p>Exit recipe <code>zone_atr05_ts40</code> (chosen in-sample on PaulTwenty — label selection bias).</p>
"""
        + kv([
            ("Stop", "<code>zone.lo − 0.5 · ATR14[entry]</code>"),
            ("Target", "<strong>2.0R</strong> from entry vs stop distance"),
            ("Time stop", "<strong>40</strong> trading bars (end-of-data truncation stays Open, not Closed TIME)"),
        ])
        + """
<div class="callout warn">
  <strong>Fidelity:</strong> zone stop and 2R target can sit in the broker. The <strong>40-day time stop</strong>
  is not a broker order.
</div>

<h2>4. Levers</h2>
"""
        + levers([
            ("<code>lookback_days</code>", "Rolling window for max-vol winner", "<strong>126</strong>", "Shorter → more/fresh zones"),
            ("<code>zone_kinds</code>", "OC and/or HL geometry", "<strong>HL only</strong>", "OC+HL → more signals; HL-only lean-kept on PaulTwenty"),
            ("<code>retest_eps_pct</code>", "Near-miss around zone edge", "<strong>0.005</strong>", "Higher → more near-miss entries; eps=0 dismissed"),
            ("<code>retest_window</code>", "Bars after breakout for retest", "<strong>63</strong>", "Shorter → fewer late retests; lean-kept vs rw126"),
            ("<code>first_retest_only</code>", "One entry per zone after break", "<strong>True</strong>", "False → later visits / more signals"),
            ("<code>min_touches_before_entry</code>", "Min prior intersections", "<strong>1</strong>", "mt0 dismissed"),
            ("<code>entry_on</code>", "Fill at retest close vs next open", "<strong>next_open</strong> (house)", "Prior AB freeze used close"),
            ("Exit <code>zone_atr05_ts40</code>", "ATR buffer / 2R / 40d", "<strong>0.5 / 2.0 / 40</strong>", "In-sample exit compare winner — selection bias labeled"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Research candidate only</strong> — not gold, not DailyRun"),
            ("TBN mode", "<code>vz_mode=true</code> (early dispatch in rocket_tbn)"),
            ("Default univ", "<code>drive/universes/VZ_universe.csv</code> (DualPaul78)"),
            ("PaulTwenty", "<code>run_vz.bat drive\\\\universes\\\\PaulTwenty_universe.csv</code>"),
            ("IS / OOS", "IS = entry_date &lt; 2024-01-01; OOS = 2024+ holdout — report-only"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li><strong>Selection bias:</strong> HL / first_retest / mt≥1 / eps / rw63 / <code>zone_atr05_ts40</code> were chosen on overlapping PaulTwenty history.</li>
  <li>House <code>entry_on=next_open</code> differs from prior AB freeze <code>close</code> — do not silently retune other freeze knobs on OOS.</li>
  <li>Promotion bar: wider/walk-forward + process PO — research stamps alone do not wire DailyRun.</li>
  <li>OOS softened under the toy exit on <code>vol_zone_hl_quality_20260810</code> — HOLD, not a retune trigger.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><span class="path">drive/paul_experiments/vol_zone_v2_rw63_20260810/BASELINE.md</span></li>
  <li><span class="path">drive/paul_experiments/VZ_TBN_Integration_And_Predictive_Timing.html</span></li>
  <li><code>run_vz.bat</code> / <span class="path">stock_analysis/rocket_vz.py</span> / <span class="path">tools/vol_zone_break_retest.py</span></li>
  <li><span class="path">drive/paul_experiments/tbn_new_systems/volume_zone/HOW_TO_RUN.md</span></li>
</ul>
""",
        footer="Canonical VZ write-up · Twin Beacon Networks (TBN) · research only",
    )


def mvcp() -> str:
    return page(
        title="MVCP — Minervini VCP",
        eyebrow="Parked · Minervini Volatility Contraction Pattern (VCP)",
        lede=(
            "<strong>MVCP</strong> (Minervini Volatility Contraction Pattern) is a Specific Entry Point Analysis (SEPA) "
            "Stage-2 pivot-breakout sleeve. The engine is kept; the sleeve is parked from DailyRun and "
            "active $500k allocation as of 2026-08-12."
        ),
        badge_class="badge-warn",
        badge_text="Parked from live sleeve (2026-08-12)",
        meta=(
            "<span>Mode <code>mvcp_mode=true</code></span>"
            "<span>Runner <code>run_mvcp.bat</code> → <code>run_minervini_vcp.bat</code></span>"
            "<span>Prefix <code>MVCP_*</code></span>"
            "<span>Module <span class='path'>stock_analysis/rocket_minervini_vcp.py</span></span>"
        ),
        body="""
<div class="callout warn">
  <strong>What parked means:</strong> out of DailyRun by default (<code>SKIP_MVCP=1</code>; opt-in
  <code>SKIP_MVCP=0</code>); out of monthly / investment / system-performance active lists;
  reconcile gate MVCP <code>enabled: false</code>. Engine kept for research.
  Source of truth: <span class="path">drive/paul_experiments/PARK.md</span>.
</div>

<h2>1. What it is</h2>
<p>
  Template (Relative Strength percentile, 200-SMA rising, position vs 52-week high/low) plus
  Volatility Contraction Pattern geometry (2–6 contractions, shrinking depth, volume dry-up),
  then a volume-confirmed Stage-2 break of the pivot with limited extension.
  Not a BRT/YH/WPBR remap.
</p>

<h2>2. Entry logic</h2>
<p>Defaults from <code>MvcpConfig</code> / <code>run_minervini_vcp.bat</code> (Theory + 40_engine_plan freeze):</p>
<ol class="steps">
  <li><strong>RS template:</strong> RS percentile ≥ <code>mvcp_rs_min_percentile</code> (prod/research default <strong>80</strong>) on a 252-bar lookback vs the RS universe (<code>mvcp_rs_universe=data_dir</code>).</li>
  <li><strong>Trend template:</strong> 200-SMA rising over 21 bars; close ≥ 30% above 52w low; close within 25% of 52w high.</li>
  <li><strong>VCP geometry:</strong> 2–6 contractions, depth shrink ≤ 0.65, first depth ≤ 40%, final depth ≥ 2%, base 15–120 bars, optional volume dry-up (0.85) with soft confirm.</li>
  <li><strong>Prior advance:</strong> +20% in 63 bars (required by default).</li>
  <li><strong>Stage-2 break:</strong> volume ≥ 1.5×, extension above pivot ≤ 5%.</li>
  <li><strong>Fill:</strong> host next-open path. Reentry cooldown 20 days. Peer systems neutralized (<code>brt/yh/wpbr/rl/rs</code> off, <code>indicator_buy=off</code>).</li>
</ol>

<h2>3. Exit logic</h2>
<ul>
  <li><strong>Stop:</strong> <code>stop_pct=0.92</code> multiplier (env <code>MVCP_STOP</code>).</li>
  <li><strong>Target:</strong> <code>target_pct=1.25</code> (env <code>MVCP_TARGET</code>).</li>
  <li><strong>Time stop:</strong> 10 bars (<code>mvcp_time_stop_bars</code>), with a min-gain qualifier in config (5%).</li>
  <li><strong>Trail:</strong> arm at +10% (<code>mvcp_trail_arm_pct</code>), 20-SMA trail.</li>
</ul>
<div class="callout warn">
  Time stop and SMA trail are not broker resting orders — handle manually if you ever re-enable the sleeve.
</div>

<h2>4. Levers</h2>
"""
        + levers([
            ("<code>mvcp_rs_min_percentile</code>", "Min RS percentile vs universe", "<strong>80</strong>", "Higher → fewer, stronger RS names"),
            ("<code>mvcp_depth_shrink</code>", "Each contraction vs prior depth", "<strong>0.65</strong>", "Lower → stricter coil"),
            ("<code>mvcp_vol_breakout_mult</code>", "Breakout volume vs average", "<strong>1.5</strong>", "Higher → fewer Stage-2 fills"),
            ("<code>mvcp_max_extension_above_pivot</code>", "Max chase above pivot", "<strong>0.05</strong>", "Lower → reject extended breaks"),
            ("<code>stop_pct</code> (<code>MVCP_STOP</code>)", "Stop multiplier", "<strong>0.92</strong>", "Lower multiplier = wider stop"),
            ("<code>target_pct</code> (<code>MVCP_TARGET</code>)", "Take-profit vs entry", "<strong>1.25</strong>", "Higher → fewer TARGET hits"),
            ("<code>mvcp_time_stop_bars</code>", "Hard/time exit", "<strong>10</strong>", "Shorter → faster recycle"),
            ("<code>mvcp_trail_arm_pct</code>", "Gain before SMA trail arms", "<strong>0.10</strong>", "Higher → trail starts later"),
            ("<code>symbol_reentry_cooldown_days</code>", "Re-arm delay", "<strong>20</strong>", "Higher → fewer re-entries"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Parked</strong> — research only; DailyRun skip unless SKIP_MVCP=0"),
            ("Runner", "<code>run_mvcp.bat</code> → <code>run_minervini_vcp.bat</code>"),
            ("Universe", "<code>drive/universes/MVCP_universe.csv</code> (default * = full scan)"),
            ("Sizing", "Host: 500k × 2 × 0.6 = 600k deployable; <code>MVCP_MAX_POSITIONS=0</code> auto peak concurrent"),
            ("Park evidence", "<span class='path'>drive/paul_experiments/mvcp_vs_sb_rl_yearly_20260811.html</span>"),
        ])
        + """
<h2>6. Caveats / do not</h2>
<ul>
  <li>Do not retune on out-of-sample (OOS) to “fix” the park.</li>
  <li>Do not re-wire DailyRun without a new failure-mode hypothesis and promotion bar.</li>
  <li>Park is process, not a silent deletion of the engine.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><span class="path">drive/paul_experiments/PARK.md</span></li>
  <li><span class="path">drive/paul_experiments/tbn_new_systems/minervini_vcp/HOW_TO_RUN.html</span></li>
  <li><span class="path">drive/paul_experiments/tbn_new_systems/minervini_vcp/10_theory.md</span></li>
  <li><span class="path">stock_analysis/rocket_minervini_vcp.py</span></li>
</ul>
""",
        footer="Canonical MVCP write-up · Twin Beacon Networks (TBN) · PARK.md is status SSoT",
    )


def ind() -> str:
    return page(
        title="IND — Indicator / Trend Condition",
        eyebrow="Deprecated · Indicator (IND) / Trend Condition (TC)",
        lede=(
            "<strong>IND</strong> is the legacy indicator-buy path: entries fire from Trend Condition (TC) / "
            "indicator score rules rather than zones. It remains in some monthly/report columns "
            "but is not an active gold allocation sleeve."
        ),
        badge_class="badge-muted",
        badge_text="Deprecated — report legacy only",
        meta=(
            "<span>Mode <code>indicator_buy=only</code></span>"
            "<span>Runner <code>run_ind.bat</code> (DailyRun skipped)</span>"
            "<span>Prefix <code>IND_*</code></span>"
        ),
        body="""
<div class="callout">
  <strong>Status:</strong> Deprecated. DailyRun step [5/14] is skipped.
  Prefer RS / BRT / RL / YH / SB / WPBR / MTS production sleeves.
  Historical Closed/Open may still appear as IND in monthly backtest tables.
</div>
<div class="callout ok">
  TC Strong outlooks are still used as <em>gates</em> by <a href="rs.html">RS</a>
  (<code>rs_require_tc_strong</code>). That is not the IND sleeve.
</div>

<h2>1. What it is</h2>
<p>
  Full DuckDB-universe indicator-only backtest on the TBN host with year-high zones off.
  Buy when indicator-buy mode is <code>only</code> (no zone identity). Long-only in the bat
  (<code>indicator_sides=long</code>, <code>transaction_type=long</code>).
</p>

<h2>2. Entry logic (last bat freeze — not live allocation)</h2>
<ol class="steps">
  <li><code>use_indicators=true</code>, <code>indicator_buy=only</code>, <code>indicator_diff=7</code>.</li>
  <li><code>min_ind_score=-2</code>, <code>max_ind_entry_neutral_n=30</code>.</li>
  <li>ATR% floor at trigger: <code>min_atr_pct_at_trigger=8.1</code> (max unbound).</li>
  <li>ATR stop/target overlays: <code>atr_stop=1.4</code>, <code>atr_target=2.2</code> (plus <code>target_pct=1.24</code>).</li>
  <li><code>yh_zones=false</code>. <code>aggressive_avg_positions=20</code>.</li>
</ol>
<p>Do not treat this list as a production freeze — the sleeve is deprecated. The bat is a historical runner.</p>

<h2>3. Exit logic</h2>
<ul>
  <li>Multiplier target <code>target_pct=1.24</code>; trailing increment 0 (off) in the bat.</li>
  <li>ATR stop 1.4 / ATR target 2.2 as configured.</li>
  <li>Host gap / stop / target schedule otherwise.</li>
</ul>

<h2>4. Levers (historical bat)</h2>
"""
        + levers([
            ("<code>indicator_buy</code>", "How indicators create entries", "<strong>only</strong>", "off = no IND identity (RS uses this)"),
            ("<code>indicator_diff</code>", "TC/indicator diff threshold", "<strong>7</strong>", "Higher → fewer signals"),
            ("<code>min_ind_score</code>", "Score floor", "<strong>−2</strong>", "Higher floor → fewer entries"),
            ("<code>min_atr_pct_at_trigger</code>", "Min ATR% at signal", "<strong>8.1</strong>", "Cuts quiet names"),
            ("<code>atr_stop</code> / <code>atr_target</code>", "ATR-multiple stop/target", "<strong>1.4 / 2.2</strong>", "Wider stop / farther target"),
            ("<code>target_pct</code>", "Price multiplier target", "<strong>1.24</strong>", "Alongside ATR target"),
            ("<code>max_ind_entry_neutral_n</code>", "Neutral-outlook cap", "<strong>30</strong>", "Limits entries while TC is mixed"),
        ])
        + """
<h2>5. Universe / status</h2>
"""
        + kv([
            ("Status", "<strong>Deprecated</strong> — DailyRun skipped; not gold allocation"),
            ("Runner", "<code>run_ind.bat</code> (standalone / research only)"),
            ("Universe", "<code>drive/universes/IND_universe.csv</code> (default * = full scan)"),
            ("Do not", "Wire new DailyRun allocation to IND"),
        ])
        + """
<h2>6. Caveats</h2>
<ul>
  <li>RS is the production consumer of Strong TC outlooks — do not revive IND to “keep TC in the book.”</li>
  <li>Monthly HTML still labels an IND column for legacy Closed/Open files.</li>
</ul>

<h2>Canonical links</h2>
<ul>
  <li><code>run_ind.bat</code> · <code>DailyRun.bat</code> step [5/14] SKIPPED</li>
  <li><a href="rs.html">RS — Relative Strength</a> (TC Strong gates)</li>
  <li><a href="../system_setup_process.html">System setup process</a></li>
</ul>
""",
        footer="Canonical IND write-up · Twin Beacon Networks (TBN) · deprecated sleeve",
    )


PAGES: list[tuple[str, str, str]] = [
    ("rs.html", "RS_System_Guide.html", rs),
    ("sb.html", "SB_System_Guide.html", sb),
    ("rl.html", "RL_System_Guide.html", rl),
    ("yh.html", "YH_System_Guide.html", yh),
    ("brt.html", "BRT_System_Guide.html", brt),
    ("wpbr.html", "WPBR_System_Guide.html", wpbr),
    ("mts.html", "MTS_System_Guide.html", mts),
    ("vz.html", "VZ_System_Guide.html", vz),
    ("mvcp.html", "MVCP_System_Guide.html", mvcp),
    ("ind.html", "IND_System_Guide.html", ind),
]


def write_all() -> list[Path]:
    DRIVE_SYSTEMS.mkdir(parents=True, exist_ok=True)
    DOCS_SYSTEMS.mkdir(parents=True, exist_ok=True)
    PAUL.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for sys_name, guide_name, fn in PAGES:
        html = fn()
        for dest in (
            DRIVE_SYSTEMS / sys_name,
            DOCS_SYSTEMS / sys_name,
            PAUL / guide_name,
        ):
            dest.write_text(html, encoding="utf-8")
            written.append(dest)
    return written


def main() -> None:
    written = write_all()
    print(f"Wrote {len(written)} files:")
    for p in written:
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            rel = p
        print(f"  {rel} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    raise SystemExit(main())
