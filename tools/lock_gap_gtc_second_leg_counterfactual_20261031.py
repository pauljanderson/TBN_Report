"""Counterfactual: adopted second-leg GTC / 180s / cheap-exit policy vs immediate flatten.

Re-runnable when Kalshi in-game minute paths land. Today it uses the 23 Oct GTC-vs-flatten
one-leg miss table (ask-touch counterfactual) plus kitchen leftover settlement buckets.

Research only. Not gold. Not DailyRun. Does not place orders.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import live_lock_orders

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs"
OUT_HTML = OUT_DIR / "lock_gap_gtc_second_leg_adopt_20261031.html"
OUT_JSON = OUT_DIR / "lock_gap_gtc_second_leg_counterfactual_20261031.json"

# From one_leg_miss_gtc_vs_flatten_20261023 (known ticks).
GTC_COMEBACK_PCT = 48.1
GTC_N_KNOWN = 27
GTC_N_YES = 13
GTC_COMPLEMENTARY_LOCK_PNL_C = 60.52
GTC_FLATTEN_PNL_C = -40.90
MEDIAN_TOUCH_SEC = 82

# Kitchen leftover settled buckets (orders_performance 31 Oct, A one-leg leftovers).
LEFTOVER = {
    "le_25": {"n": 7, "wins": 0, "pnl": -1.13},
    "gt_25": {"n": 15, "wins": 10, "pnl": 2.40},  # 22 total − 7 cheap
}


def simulate_policy() -> dict:
    """Conservative book vs immediate flatten on the researched one-leg sample.

    Hard number: complementary GTC locks that would have printed within ~180s
    (median touch 82s) vs the flatten P&L on that same page. Hold / cheap-exit
    legs are listed as kitchen evidence, not invented P&L on the GTC-miss rows.
    """
    gtc_fill_n = GTC_N_YES
    gtc_miss_n = GTC_N_KNOWN - GTC_N_YES
    gtc_lock_pnl_c = GTC_COMPLEMENTARY_LOCK_PNL_C
    flatten_pnl_c = GTC_FLATTEN_PNL_C
    # Floor: only credit documented complementary locks; treat non-lock touches + misses as 0
    # vs counting full flatten book. Delta vs flatten on the overlapping researched book.
    conservative_policy_floor_c = gtc_lock_pnl_c  # +0 on unknown miss fates
    policy_minus_flatten_c = conservative_policy_floor_c - flatten_pnl_c

    return {
        "policy": {
            "hard": "IOC",
            "easy": "GTC at L",
            "wait_sec": live_lock_orders.ONE_LEG_GTC_WAIT_SEC,
            "cheap_exit_max": str(live_lock_orders.CHEAP_EXIT_MAX),
            "after_deadline_gt_25": "IOC complete ≤ BE(+1¢) else hold",
            "cancel_on_resolve": True,
        },
        "inputs": {
            "gtc_comeback_pct": GTC_COMEBACK_PCT,
            "gtc_n_known": GTC_N_KNOWN,
            "gtc_n_yes": GTC_N_YES,
            "median_touch_sec": MEDIAN_TOUCH_SEC,
            "complementary_lock_pnl_c": GTC_COMPLEMENTARY_LOCK_PNL_C,
            "immediate_flatten_pnl_c": GTC_FLATTEN_PNL_C,
            "leftover_buckets": LEFTOVER,
            "note": (
                "Ask-touch counterfactual, not queue-guaranteed. "
                "Re-run with Kalshi in-game minutes for exact BE/+1¢ ladders and per-row held prices."
            ),
        },
        "counterfactual": {
            "gtc_fill_n": gtc_fill_n,
            "gtc_miss_n": gtc_miss_n,
            "gtc_lock_pnl_c": round(gtc_lock_pnl_c, 2),
            "immediate_flatten_pnl_c": round(flatten_pnl_c, 2),
            "conservative_policy_floor_c": round(conservative_policy_floor_c, 2),
            "policy_minus_flatten_c": round(policy_minus_flatten_c, 2),
            "kitchen_leftover_le_25_pnl": LEFTOVER["le_25"]["pnl"],
            "kitchen_leftover_gt_25_pnl": LEFTOVER["gt_25"]["pnl"],
            "interpretation": (
                f"Even crediting only the +{gtc_lock_pnl_c}¢ complementary GTC locks "
                f"(and $0 for the other {gtc_miss_n + (GTC_N_YES - 7)} non-lock/miss rows) "
                f"beats the −{abs(flatten_pnl_c)}¢ flatten book on that page by "
                f"+{policy_minus_flatten_c:.1f}¢. Kitchen leftovers say exit ≤25¢ "
                f"({LEFTOVER['le_25']['wins']}/{LEFTOVER['le_25']['n']}) and holding >25¢ "
                f"was +${LEFTOVER['gt_25']['pnl']:.2f} on {LEFTOVER['gt_25']['n']} tickets."
            ),
        },
        "decision_checks": {
            "held_0.20_at_180s": live_lock_orders.one_leg_deadline_action(
                held_pay=Decimal("0.20"), gtc_filled=False, waited_sec=180
            ),
            "held_0.40_at_60s": live_lock_orders.one_leg_deadline_action(
                held_pay=Decimal("0.40"), gtc_filled=False, waited_sec=60
            ),
            "held_0.40_at_180s_no_be": live_lock_orders.one_leg_deadline_action(
                held_pay=Decimal("0.40"),
                gtc_filled=False,
                waited_sec=180,
                be_complete_available=False,
            ),
        },
    }


def render_html(data: dict) -> str:
    c = data["counterfactual"]
    p = data["policy"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Lock gap GTC second-leg adopt — 31 Oct 2026</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 1.25rem; color: #0f172a; line-height: 1.45; max-width: 52rem; }}
.banner {{ background: #fef3c7; border: 1px solid #d97706; padding: 10px 12px; margin: 0 0 14px; }}
.callout {{ background: #f8fafc; border: 1px solid #d8dee9; padding: 0.8rem 1rem; margin: 0 0 1rem; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #d8dee9; padding: 6px 8px; text-align: left; }}
th {{ background: #f8fafc; }}
code {{ font-size: 0.92em; }}
.note {{ color: #334155; font-size: 0.95rem; }}
.tiny {{ color: #64748b; font-size: 0.88rem; }}
</style>
</head>
<body>
<h1>Lock gap — adopted live policy: second-leg GTC (31 Oct 2026)</h1>
<p class="banner"><strong>Adopted live policy</strong> (Paul 2026-10-31). Not gold. Not DailyRun.
Written America/New_York. Orders stay off until trading PC enables via
<code>orders_enabled.on</code> / <code>LOCK_ORDERS_ENABLED=1</code>. See merge_lock_gap_gtc_live.bat.</p>

<div class="callout">
<h2>What Paul approved</h2>
<ol>
<li>Hard / first leg: <strong>IOC</strong>.</li>
<li>If hard fills → easy / second leg: <strong>GTC at original L</strong> (take now + rest).</li>
<li>If still open after <strong>{p['wait_sec']}s</strong>:
  <ul>
    <li>held ≤ <strong>{p['cheap_exit_max']}</strong> → exit (flatten if tighter, else market sell). Do not hold.</li>
    <li>held &gt; 25¢ → one IOC to complete at ≤ break-even (+1¢ slip); else <strong>hold</strong>.</li>
  </ul>
</li>
<li><strong>Cancel-on-resolve</strong> for resting second-leg GTCs.</li>
</ol>
</div>

<div class="callout">
<h2>Wired in this repo</h2>
<p class="note"><code>tools/live_lock_orders.py</code>: GTC TIF builders, <code>_send_pair</code> second-leg GTC,
<code>tick_one_leg_gtc_watches</code>, <code>cancel_second_leg_gtc_on_resolve</code>, pure policy helpers.
<code>tools/live_game_pollers.py</code> ticks watches after lock sends and cancels on closed results.
Tests in <code>tools/test_live_lock_orders.py</code>.</p>
<p class="note">Trading-PC note: production <code>live_lock_orders.py</code> is ahead of this git dump
(thin-first / flatten_filled_leg). Merge this policy onto that file; do not overwrite thin-first.
Run <code>merge_lock_gap_gtc_live.bat</code> after merging the PR.</p>
</div>

<h2>Counterfactual vs immediate flatten</h2>
<p class="note">Same 27 known-tick one-leg misses from the 23 Oct GTC study. Median touch {data['inputs']['median_touch_sec']}s
(inside the 180s window). Complementary lock P&amp;L only counted where the page had a true $1 pair.</p>
<table>
<thead><tr><th>Book</th><th>P&amp;L (¢)</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>Immediate flatten (14 rows on that page)</td><td>{c['immediate_flatten_pnl_c']}</td><td>Live house rule before this adopt</td></tr>
<tr><td>Conservative policy floor</td><td>{c['conservative_policy_floor_c']}</td><td>Only the +{c['gtc_lock_pnl_c']}¢ complementary GTC locks; $0 on other touches/misses</td></tr>
<tr><td>Policy floor − flatten</td><td><strong>{c['policy_minus_flatten_c']}</strong></td><td>Directional; tiny N; ask-touch ≠ queue fill</td></tr>
</tbody>
</table>
<p class="note">{c['interpretation']}</p>

<h2>Re-run when Kalshi in-game minutes arrive</h2>
<pre>python tools/lock_gap_gtc_second_leg_counterfactual_20261031.py
# Then replace the hardcoded GTC_*/LEFTOVER inputs with per-miss best-ask paths
# from local raw/price_memory (or Kalshi hist minutes) and recompute BE/+1¢ ladders exactly.
</pre>
<p class="tiny">Generator: <code>tools/lock_gap_gtc_second_leg_counterfactual_20261031.py</code>.
JSON: <code>docs/lock_gap_gtc_second_leg_counterfactual_20261031.json</code>.</p>
</body>
</html>
"""


def main() -> None:
    data = simulate_policy()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    OUT_HTML.write_text(render_html(data), encoding="utf-8")
    print(json.dumps(data["counterfactual"], indent=2))
    print(f"wrote {OUT_HTML}")
    print(f"wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
