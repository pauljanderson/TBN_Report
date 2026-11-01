# WPBR Improve Hints — stamp `261003132717`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (734 sym / 1866 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AA, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACGL, ACM, ACN, ACU
- **Evidence:** AA TARGET 106d +15.0% (~0.14%/d) 2017-12-27; A TARGET 225d +15.0% (~0.07%/d) 2017-02-09; A TARGET 122d +15.0% (~0.12%/d) 2024-05-10; A TARGET 229d +15.0% (~0.07%/d) 2025-01-21; ACA TARGET 103d +15.0% (~0.15%/d) 2021-11-22

## 2. `fat_stops` (696 sym / 1703 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAON, AAP, AAT, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADBE, ADM, ADMA

## 3. `post_target_quick_stop` (492 sym / 744 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAL, AAMI, AAP, AAPL, ABBV, ABCB, ABG, ABNB, ACA, ACAD, ACLS, ACM, ADBE, ADI, ADMA, ADPT, ADSK, AEE, AEHR, AEIS
- **Evidence:** ABNB TARGET 2026-08-07 -> STOP 2026-09-10 (8d); ADPT TARGET 2021-02-12 -> STOP 2021-03-04 (8d); ADPT TARGET 2025-01-06 -> STOP 2025-01-13 (5d); ACA TARGET 2024-07-16 -> STOP 2024-08-02 (10d); AAMI TARGET 2021-08-04 -> STOP 2022-01-21 (9d)

## 4. `false_start_2022_2023` (357 sym / 463 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ABM, ACLS, ACRS, ACU, ADNT, ADPT, ADSK, AEE, AEHR, AFRM, AGCO, AGYS, AI, AIZ, AJG, ALB, ALFVY, ALGN
- **Evidence:** AA 2022 STOP 13d -14.4%; ADPT 2022 STOP 8d -18.9%; ADNT 2022 STOP 14d -8.7%; ACRS 2023 STOP 8d -14.2%; AAMI 2022 STOP 9d -10.3%

## 5. `early_run_long_tail` (287 sym / 341 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AA, AAMI, AAP, ABBNY, ACGL, ACM, ACU, ADI, ADM, AEE, AEG, AGCO, AGI, AGX, AIG, AIR, AIT, AIZ, AJG, ALLE
- **Evidence:** AA +10% by day 22 then held 106d exit +15.0% (TARGET); AAMI +10% by day 15 then held 87d exit +15.0% (TARGET); ABBNY +10% by day 13 then held 98d exit +15.6% (GAP_UP); ADM +10% by day 22 then held 355d exit +15.3% (GAP_UP); ACGL +10% by day 5 then held 300d exit +15.0% (TARGET)

## 6. `winner_peak_giveback` (124 sym / 144 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, ADMA, AEO, AFRM, AGYS, ALBY, ALDX, ALNT, ALNY, AMG, AMKR, AMTX, AN, ANAB, ANF, AOSL, ARW, ATI, ATLC, AVAV
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); ADMA peak~34% -> exit +15.0% (giveback~19pp, 24d, TARGET); ADMA peak~38% -> exit +15.0% (giveback~23pp, 27d, TARGET); ADMA peak~47% -> exit +33.3% (giveback~13pp, 51d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (48 sym / 4814 trades) — direction: expand, confidence: medium, 49.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (4814 trades, 50%, high) vs target_contract_approach_fail → contract (2155 trades, 9%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 4814/9711 TARGET exits (50%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 2155/25003 trades (9%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS
- **Evidence:** [A expand] AA +10% in 15d after TARGET; AA +6% in 15d after TARGET; AA +17% in 15d after TARGET; AA +8% in 15d after TARGET; AA +12% in 15d after TARGET; AA +15% in 15d after TARGET | [B contract] AA reached 51% of target then STOP; AA reached 52% of target then STOP; AA reached 77% of target then STOP; AA reached 55% of target then STOP; A reached 72% of target then STOP; ABNB reached 51% of target then STOP

## 2. `stop_pct_tension_expand_vs_contract` (43 sym / 2579 trades) — direction: mixed, confidence: medium, 30.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (2579 trades, 30%, high) vs stop_contract_dead_losers → contract (2519 trades, 30%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 2579/8505 STOP exits (30%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 2519/8505 STOPs (30%) never expanded (MFE<2%) and 1703 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM
- **Evidence:** [A expand] AA STOP 2017-04-13 then back above entry/15d; AA STOP 2018-12-20 then back above entry/15d; AA STOP 2021-03-23 then back above entry/15d; AA STOP 2022-05-09 then back above entry/15d; AA STOP 2026-07-17 then back above entry/15d; A STOP 2023-03-23 then back above entry/15d | [B contract] AA MFE~1.4% STOP; AA MFE~1.7% STOP; AA MFE~0.9% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP; A MFE~0.0% STOP

## 3. `band_tighten_weak_fill` (811 sym / 1881 trades) — direction: tighten, confidence: low, 7.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1881/25003 trades (8%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ACAD, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** AA MFE~1.7% STOP 15d; AA MFE~1.1% STOP 7d; AA MFE~0.1% STOP 4d; A MFE~0.0% STOP 4d; A MFE~1.9% STOP 14d; ABNB MFE~2.2% STOP 8d

## 4. `target_contract_slow_hold` (734 sym / 1866 trades) — direction: contract, confidence: high, 19.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 1866/9711 TARGET exits (19%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACGL, ACM, ACN, ACU
- **Evidence:** AA TARGET 106d +15.0% (~0.14%/d); A TARGET 225d +15.0% (~0.07%/d); A TARGET 122d +15.0% (~0.12%/d); A TARGET 229d +15.0% (~0.07%/d); ACA TARGET 103d +15.0% (~0.15%/d); ACA TARGET 217d +15.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
