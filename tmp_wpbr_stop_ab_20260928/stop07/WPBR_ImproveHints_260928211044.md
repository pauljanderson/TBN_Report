# WPBR Improve Hints — stamp `260928211044`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (882 sym / 2939 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACGL, ACM, ACN, ACU
- **Evidence:** AAMI TARGET 124d +22.0% (~0.18%/d) 2021-04-14; AAMI TARGET 105d +22.0% (~0.21%/d) 2021-08-25; AAMI TARGET 166d +22.0% (~0.13%/d) 2024-07-23; AA TARGET 103d +22.0% (~0.21%/d) 2021-12-22; AAT TARGET 190d +22.0% (~0.12%/d) 2012-08-21

## 2. `fat_stops` (659 sym / 1538 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, ABBV, ABG, ABM, ABR, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADBE, ADMA, ADP, ADPT

## 3. `early_run_long_tail` (596 sym / 960 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAL, AAMI, AAPL, ABBNY, ABCB, ABR, ACGL, ACLS, ACM, ACU, ADBE, ADI, ADMA, ADSK, AEE, AEG, AEIS, AER, AES, AGCO
- **Evidence:** AAMI +10% by day 15 then held 92d exit +22.0% (TARGET); ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); AAL +10% by day 12 then held 85d exit +22.0% (TARGET); ABR +10% by day 13 then held 112d exit +22.0% (TARGET); AAPL +10% by day 10 then held 127d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (479 sym / 707 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAL, AAMI, AAON, AAPL, ABCB, ABG, ABNB, ABR, ABUS, ACAD, ACLS, ACM, ADBE, ADMA, ADNT, AEHR, AEM, AEO, AEP, AFG
- **Evidence:** AAMI TARGET 2021-08-25 -> STOP 2022-01-21 (9d); AAL TARGET 2010-07-26 -> STOP 2010-11-10 (7d); ABNB TARGET 2021-11-05 -> STOP 2021-12-01 (5d); AAON TARGET 2011-04-07 -> STOP 2011-07-28 (8d); ABR TARGET 2021-06-01 -> STOP 2021-11-18 (6d)

## 5. `false_start_2022_2023` (389 sym / 512 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ABM, ABR, ACA, ACLS, ACRS, ACU, ADI, ADMA, ADNT, ADPT, ADSK, AEE, AEHR, AFRM, AGCO, AGO, AGYS, AI, AJG
- **Evidence:** AAMI 2022 STOP 9d -9.3%; AAMI 2022 STOP 4d -8.9%; ABR 2022 STOP 4d -8.3%; ABM 2022 STOP 14d -9.5%; ACA 2022 STOP 7d -8.8%

## 6. `winner_peak_giveback` (143 sym / 181 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABUS, ACAD, ADMA, ADPT, AFRM, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMTX, ANAB, AOSL, APLD, APPS, ARGX, ASM, AVAV, AXON
- **Evidence:** ABUS peak~32% -> exit +22.0% (giveback~10pp, 23d, TARGET); ACAD peak~52% -> exit +38.8% (giveback~13pp, 70d, GAP_UP); ACAD peak~36% -> exit +22.0% (giveback~14pp, 71d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 24d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 113d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (42 sym / 3530 trades) — direction: expand, confidence: medium, 33.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (3530 trades, 33%, high) vs stop_ok_never_worked → hold (2549 trades, 24%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 3530/10596 STOP exits (33%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 2549/10596 STOPs (24%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS
- **Evidence:** [A expand] AAMI STOP 2019-03-22 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; AAMI STOP 2022-09-23 then back above entry/15d; AAMI STOP 2026-02-05 then back above entry/15d; AA STOP 2015-08-21 then back above entry/15d; AA STOP 2017-06-16 then back above entry/15d | [B hold] AAMI MFE~1.5% STOP; AAMI MFE~1.6% STOP; AA MFE~1.7% STOP; AA MFE~0.4% STOP; AA MFE~0.9% STOP; AA MFE~1.1% STOP

## 2. `target_pct_tension_expand_vs_contract` (49 sym / 3554 trades) — direction: mixed, confidence: medium, 48.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (3554 trades, 48%, high) vs target_contract_slow_hold → contract (2939 trades, 40%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 3554/7372 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 2939/7372 TARGET exits (40%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +11% in 15d after TARGET; AA +5% in 15d after TARGET; AA +10% in 15d after TARGET; AA +10% in 15d after TARGET; AA +9% in 15d after TARGET; AA +12% in 15d after TARGET | [B contract] AAMI TARGET 124d +22.0% (~0.18%/d); AAMI TARGET 105d +22.0% (~0.21%/d); AAMI TARGET 166d +22.0% (~0.13%/d); AA TARGET 103d +22.0% (~0.21%/d); AAT TARGET 190d +22.0% (~0.12%/d); AAT TARGET 114d +22.0% (~0.19%/d)

## 3. `target_contract_approach_fail` (934 sym / 2301 trades) — direction: contract, confidence: medium, 10.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 2301/21525 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS
- **Evidence:** AAMI reached 69% of target then STOP; AA reached 59% of target then STOP; AA reached 68% of target then STOP; AAP reached 61% of target then STOP; AAP reached 66% of target then STOP; AAP reached 51% of target then STOP

## 4. `band_tighten_weak_fill` (842 sym / 2047 trades) — direction: tighten, confidence: medium, 9.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 2047/21525 trades (10%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS
- **Evidence:** AAMI MFE~2.5% STOP 10d; AAMI MFE~1.6% STOP 9d; AA MFE~1.7% STOP 14d; AA MFE~0.4% STOP 10d; AA MFE~0.9% STOP 11d; AA MFE~1.1% STOP 7d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
