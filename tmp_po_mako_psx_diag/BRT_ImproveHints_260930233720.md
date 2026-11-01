# BRT Improve Hints — stamp `260930233720`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `fat_stops` (1 sym / 8 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** MAKO

## 2. `false_start_2022_2023` (1 sym / 3 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** MAKO
- **Evidence:** MAKO 2022 STOP 8d -13.5%; MAKO 2022 STOP 15d -10.8%; MAKO 2022 STOP 6d -15.5%

## 3. `post_target_quick_stop` (1 sym / 3 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** MAKO
- **Evidence:** MAKO TARGET 2019-12-27 -> STOP 2020-01-21 (8d); MAKO TARGET 2020-02-05 -> STOP 2020-02-12 (2d); MAKO TARGET 2021-05-21 -> STOP 2021-07-19 (4d)

## 4. `slow_target_grind` (1 sym / 2 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** PSX
- **Evidence:** PSX TARGET 145d +21.0% (~0.14%/d) 2023-08-09; PSX TARGET 141d +21.0% (~0.15%/d) 2024-01-04

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_contract` (2 sym / 12 trades) — direction: expand, confidence: medium, 57.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (12 trades, 57%, medium) vs stop_contract_dead_losers → contract (6 trades, 29%, low). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 12/21 STOP exits (57%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 6/21 STOPs (29%) never expanded (MFE<2%) and 8 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** MAKO, PSX
- **Evidence:** [A expand] MAKO STOP 2018-12-19 then back above entry/15d; MAKO STOP 2020-01-21 then back above entry/15d; MAKO STOP 2020-02-12 then back above entry/15d; MAKO STOP 2020-02-27 then back above entry/15d; MAKO STOP 2020-06-12 then back above entry/15d; MAKO STOP 2020-10-20 then back above entry/15d | [B contract] MAKO MFE~0.0% STOP; MAKO MFE~0.0% STOP; MAKO MFE~0.0% STOP; MAKO MFE~0.0% STOP; MAKO MFE~0.0% STOP; PSX MFE~0.8% STOP

## 2. `target_pct_tension_expand_vs_contract` (2 sym / 6 trades) — direction: expand, confidence: low, 54.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (6 trades, 54%, low) vs target_contract_approach_fail → contract (3 trades, 7%, insufficient). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 6/11 TARGET exits (55%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 3/45 trades (7%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** MAKO, PSX
- **Evidence:** [A expand] MAKO +22% in 15d after TARGET; MAKO +14% in 15d after TARGET; MAKO +6% in 15d after TARGET; MAKO +7% in 15d after TARGET; MAKO +22% in 15d after TARGET; MAKO +7% in 15d after TARGET | [B contract] MAKO reached 70% of target then STOP; MAKO reached 64% of target then STOP; PSX reached 86% of target then STOP

## 3. `band_tighten_weak_fill` (2 sym / 6 trades) — direction: tighten, confidence: low, 13.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 6/45 trades (13%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** MAKO, PSX
- **Evidence:** MAKO MFE~0.0% STOP 8d; MAKO MFE~0.0% STOP 2d; MAKO MFE~0.0% STOP 4d; MAKO MFE~0.0% STOP 6d; MAKO MFE~2.8% STOP 7d; PSX MFE~0.8% STOP 4d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
