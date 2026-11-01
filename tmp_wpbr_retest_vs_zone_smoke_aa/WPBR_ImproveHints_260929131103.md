# WPBR Improve Hints — stamp `260929131103`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `fat_stops` (1 sym / 5 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA

## Parameter suggestions (band / target / stop)

## 1. `target_expand_post_exit` (1 sym / 9 trades) — direction: expand, confidence: medium, 75.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Expand target: 9/12 TARGET exits (75%) continued ≥5% higher within 15 bars — possible money left on table.
- **Heuristic:** TARGET exit then OHLC fwd max-gain >= 5% in 15 bars
- **Symbols:** AA
- **Evidence:** AA +11% in 15d after TARGET; AA +5% in 15d after TARGET; AA +10% in 15d after TARGET; AA +10% in 15d after TARGET; AA +9% in 15d after TARGET; AA +12% in 15d after TARGET

## 2. `stop_pct_tension_expand_vs_contract` (1 sym / 4 trades) — direction: contract, confidence: insufficient, 33.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean contract): stop_expand_post_stop_rebound → expand (3 trades, 25%, insufficient) vs stop_contract_dead_losers → contract (4 trades, 33%, insufficient). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 3/12 STOP exits (25%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 4/12 STOPs (33%) never expanded (MFE<2%) and 5 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA
- **Evidence:** [A expand] AA STOP 2018-12-21 then back above entry/15d; AA STOP 2021-03-23 then back above entry/15d; AA STOP 2026-07-20 then back above entry/15d | [B contract] AA MFE~1.7% STOP; AA MFE~1.1% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP

## 3. `band_tighten_weak_fill` (1 sym / 3 trades) — direction: tighten, confidence: insufficient, 11.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 3/27 trades (11%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
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
