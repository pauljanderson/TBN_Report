# BRT Improve Hints — stamp `260930234329`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (1 sym / 3 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** PSX
- **Evidence:** PSX TARGET 145d +21.0% (~0.14%/d) 2023-08-09; PSX TARGET 141d +21.0% (~0.15%/d) 2024-01-04; PSX TARGET 163d +21.0% (~0.13%/d) 2026-02-06

## Parameter suggestions (band / target / stop)

## 1. `target_contract_slow_hold` (1 sym / 3 trades) — direction: contract, confidence: insufficient, 60.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 3/5 TARGET exits (60%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** PSX
- **Evidence:** PSX TARGET 145d +21.0% (~0.14%/d); PSX TARGET 141d +21.0% (~0.15%/d); PSX TARGET 163d +21.0% (~0.13%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
