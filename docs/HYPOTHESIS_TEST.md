# Hypothesis test one-pager

**Product owner (PO)–aligned process:** param changes are **hypothesis tests** / **missed-trade fixes**, not open-ended optimization. See `drive/paul_experiments/system_setup_process.html` (steps 5–8, 12) and `docs/POST_RUN_ANALYSIS.md`.

Copy this into `drive/paul_experiments/<experiment>/HYPOTHESIS.md` (or paste into the experiment README) **before** running A/B.

## Rules (do not skip)

- **No change without evidence** — ImproveHints / post-run, ToS review, or a counted miss / band-touch pattern. If none, stop.
- **One hypothesis, one knob** — freeze everything else; same universe for A/B.
- **≤ 1–2 pre-agreed alternatives** — no combinatorial / “find optimal” grids.
- **ToS before/after is the gate** — reject PnL-up that does not look like the same setup.
- **Judge** trade quality / thesis fit / drawdown / reconcile — **not** max profit.
- **Adopt only** with PO sign-off + reconcile freeze / re-baseline.

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
| Metrics (trades, win%, DD, robust FIT, reconcile) — not max PnL primary | |
| ToS before path | `drive/paul_studies/…` |
| ToS after path | `drive/paul_studies/…` |
| Trade-diff HTML (if used) | `drive/paul_experiments/…` |
| **Decision** | adopt / reject / hold |
| Reviewer | |
| PO sign-off | yes / no / date |
| Reconcile freeze / re-baseline done | yes / no |

## Decision checklist

- [ ] Evidence was real and countable (not “feels better”)
- [ ] Only one knob differed between arms
- [ ] Charts still look like the intended setup
- [ ] Drawdown / reconcile acceptable
- [ ] If adopt: PO signed off and sheet↔engine re-baselined

## Tooling note

Prefer ImproveHints / deep post-run to surface near-miss and band-touch patterns. RL today: `--missed-moves`. Broader zone-system near-miss / band-touch teaching in post-run is a future enhancement—until then, count misses manually on ToS when needed.
