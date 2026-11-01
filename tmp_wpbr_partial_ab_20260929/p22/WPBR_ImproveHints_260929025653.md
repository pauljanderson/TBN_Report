# WPBR Improve Hints — stamp `260929025653`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `winner_peak_giveback` (1 sym / 10 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AA
- **Evidence:** AA peak~40% -> exit +25.6% (giveback~15pp, 137d, SCALE+TARGET); AA peak~36% -> exit +17.6% (giveback~18pp, 342d, SCALE+STOP_LOSS); AA peak~43% -> exit +25.6% (giveback~17pp, 231d, SCALE+TARGET); AA peak~29% -> exit +17.6% (giveback~11pp, 150d, SCALE+STOP_LOSS); AA peak~33% -> exit +17.6% (giveback~15pp, 63d, SCALE+STOP_LOSS)

## 2. `fat_stops` (1 sym / 6 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA

## 3. `slow_target_grind` (1 sym / 4 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AA
- **Evidence:** AA TARGET 137d +25.6% (~0.19%/d) 2014-03-28; AA TARGET 231d +25.6% (~0.11%/d) 2017-08-23; AA TARGET 151d +25.6% (~0.17%/d) 2022-02-08; AA TARGET 147d +25.6% (~0.17%/d) 2025-12-03

## 4. `early_run_long_tail` (1 sym / 2 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AA
- **Evidence:** AA +10% by day 7 then held 231d exit +25.6% (SCALE+TARGET); AA +10% by day 22 then held 150d exit +17.6% (SCALE+STOP_LOSS)

## 5. `false_start_2022_2023` (1 sym / 2 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA
- **Evidence:** AA 2022 STOP 13d -15.4%; AA 2022 STOP 8d -16.2%

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_contract` (1 sym / 8 trades) — direction: expand, confidence: medium, 50.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (8 trades, 50%, medium) vs stop_contract_dead_losers → contract (4 trades, 25%, insufficient). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 8/16 STOP exits (50%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 4/16 STOPs (25%) never expanded (MFE<2%) and 6 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA
- **Evidence:** [A expand] AA STOP 2015-03-17 then back above entry/15d; AA STOP 2018-02-09 then back above entry/15d; AA STOP 2018-12-21 then back above entry/15d; AA STOP 2021-03-23 then back above entry/15d; AA STOP 2021-06-17 then back above entry/15d; AA STOP 2022-05-09 then back above entry/15d | [B contract] AA MFE~1.4% STOP; AA MFE~1.1% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP

## 2. `target_pct_tension_expand_vs_contract` (1 sym / 6 trades) — direction: mixed, confidence: low, 100.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (6 trades, 100%, low) vs target_contract_approach_fail → contract (6 trades, 26%, low). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 6/6 TARGET exits (100%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 6/23 trades (26%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA
- **Evidence:** [A expand] AA +20% in 15d after TARGET; AA +24% in 15d after TARGET; AA +24% in 15d after TARGET; AA +41% in 15d after TARGET; AA +8% in 15d after TARGET; AA +41% in 15d after TARGET | [B contract] AA reached 89% of target then STOP; AA reached 72% of target then STOP; AA reached 52% of target then STOP; AA reached 82% of target then STOP; AA reached 64% of target then STOP; AA reached 81% of target then STOP

## 3. `target_contract_slow_hold` (1 sym / 4 trades) — direction: contract, confidence: insufficient, 66.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 4/6 TARGET exits (67%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AA
- **Evidence:** AA TARGET 137d +25.6% (~0.19%/d); AA TARGET 231d +25.6% (~0.11%/d); AA TARGET 151d +25.6% (~0.17%/d); AA TARGET 147d +25.6% (~0.17%/d)

## 4. `band_tighten_weak_fill` (1 sym / 3 trades) — direction: tighten, confidence: insufficient, 13.0% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 3/23 trades (13%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AA
- **Evidence:** AA MFE~1.1% STOP 8d; AA MFE~1.1% STOP 8d; AA MFE~0.1% STOP 4d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
