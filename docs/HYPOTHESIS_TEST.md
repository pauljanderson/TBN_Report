# Hypothesis test one-pager

**Product owner (PO)–aligned process:** param changes are **hypothesis tests** / **missed-trade fixes**, not open-ended optimization. See `drive/paul_experiments/system_setup_process.html` (steps 5–8, 12) and `docs/POST_RUN_ANALYSIS.md`.

Copy this into `drive/paul_experiments/<experiment>/HYPOTHESIS.md` (or paste into the experiment README) **before** running A/B.

## Rules (do not skip)

- **No change without evidence** — ImproveHints / post-run, ToS review, or a counted miss / band-touch pattern. If none, stop.
- **One hypothesis, one knob** — freeze everything else; same universe for A/B.
- **≤ 1–2 pre-agreed alternatives** — no combinatorial / “find optimal” grids.
- **Trade-diff HTML before ToS** — after control + candidate Closed stamps exist, produce the three-section HTML (below) **before** human Thinkorswim (ToS) study comparison.
- **ToS before/after is the gate** — reject PnL-up that does not look like the same setup.
- **Judge** trade quality / thesis fit / drawdown / reconcile — **not** max profit.
- **Adopt only** with PO sign-off + reconcile freeze / re-baseline.

## Adopt flow (order)

1. Evidence → one knob → A/B Closed stamps (control vs candidate arm)
2. **Trade-diff HTML** (required) — Closed stamps control vs arm; three sortable sections
3. **ToS** before/after (+ trade-diff studies) guided by those sections
4. Adopt / reject / hold → PO + reconcile freeze if adopt

### Trade-diff HTML (step 7 — before ToS)

**When:** immediately after control and candidate Closed stamps exist for the one-knob A/B; do not open charts for the lever gate until this HTML exists.

**Tool:** `drive/paul_experiments/_gen_too_high_diff.py` (canonical; helpers `sortable_th` / `SORTABLE_TABLE_SCRIPT`). Sibling: `drive/paul_experiments/_gen_markten_band_diff.py`. Edit stamp IDs; write `drive/paul_experiments/rl_stamp_trade_diff_*.html`.

**Inputs:** `{PREFIX}_Closed_<control>.csv` vs `{PREFIX}_Closed_<candidate>.csv` (plus Report/Summary for metrics).

**HTML looks like (3 trade sections):**

1. **Old trades no longer taken** — in control, not in candidate
2. **New trades taken** — in candidate, not in control
3. **Same or similar (“close enough”)** — exact + nearby open / same-or-similar exit

(Optional above them: run metrics side-by-side, per-symbol counts. Monthly-style sortable column headers.)

## Template

| Field | Fill in |
|-------|---------|
| System / prefix | |
| Baseline stamp | |
| Universe (seed or promotion list) | |
| **Evidence** (hint IDs, chart notes, miss counts) | |
| **Hypothesis** (one sentence) | |
| **Single knob** (`-v` / lever) | |
| Frozen settings (everything else) | |
| Alternatives (baseline + ≤2 values) | |
| Candidate stamps (A/B/…) | |
| Metrics (trades, win%, DD, Calmar, Sharpe, robust FIT, reconcile) — not max PnL primary | |
| **Trade-diff HTML** (required before ToS) | `drive/paul_experiments/…` via `_gen_too_high_diff.py` |
| ToS before path | `drive/paul_studies/…` |
| ToS after path | `drive/paul_studies/…` |
| **Decision** | adopt / reject / hold |
| Reviewer | |
| PO sign-off | yes / no / date |
| Reconcile freeze / re-baseline done | yes / no |

## Decision checklist

- [ ] Evidence was real and countable (not “feels better”)
- [ ] Only one knob differed between arms
- [ ] Trade-diff HTML produced from Closed stamps (old / new / close-enough) before ToS
- [ ] Charts still look like the intended setup
- [ ] Drawdown / reconcile acceptable
- [ ] If adopt: PO signed off and sheet↔engine re-baselined

## Tooling note

Prefer ImproveHints / deep post-run to surface near-miss and band-touch patterns. RL today: `--missed-moves`. Broader zone-system near-miss / band-touch teaching in post-run is a future enhancement—until then, count misses manually on ToS when needed.
