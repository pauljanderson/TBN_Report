# WPBR Improve Hints — stamp `261002195651`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `small_target_wins` (1102 sym / 16115 trades)
- **Lever:** target_pct / expansion / partial_exit
- **Suggestion:** Many small TARGET wins — consider higher target or partial scale-out.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL

## 2. `post_target_quick_stop` (1060 sym / 4892 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** AA TARGET 2013-11-15 -> STOP 2013-12-12 (2d); AA TARGET 2014-01-15 -> STOP 2014-02-10 (0d); AA TARGET 2015-06-03 -> STOP 2015-07-08 (0d); AA TARGET 2017-01-04 -> STOP 2017-03-21 (5d); AA TARGET 2017-11-16 -> STOP 2017-11-20 (0d)

## 3. `false_start_2022_2023` (781 sym / 1459 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACN, ACRS, ACU, ADI, ADMA
- **Evidence:** A 2022 STOP 1d -2.3%; A 2023 STOP 0d -2.0%; A 2023 STOP 0d -0.3%; AAMI 2022 STOP 9d -9.3%; ABBNY 2022 STOP 0d -0.3%

## 4. `slow_target_grind` (511 sym / 863 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAT, ABG, ABT, ABUS, ACGL, ACM, ACN, ADBE, ADI, ADNT, ADP, AEE, AEIS, AEP, AER, AFG, AFL
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d) 2017-03-13; AAT TARGET 239d +20.0% (~0.08%/d) 2013-01-02; AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; AAON TARGET 151d +6.3% (~0.04%/d) 2016-10-04; AAL TARGET 196d +20.0% (~0.10%/d) 2013-10-01

## 5. `fat_stops` (392 sym / 588 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, AAMI, ABBV, ABR, ABUS, ACAD, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AES, AFRM, AGI, AGM, AGYS, AHCO

## 6. `early_run_long_tail` (167 sym / 181 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ABUS, ACU, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AMN, AMTX, ANIP, AON, APG, APH, APP, ARES, ASML, ATEYY, AX, AYI
- **Evidence:** ABUS +10% by day 5 then held 169d exit +117.3% (TARGET); ACU +10% by day 8 then held 213d exit +17.0% (GAP_UP); AIT +10% by day 19 then held 418d exit +20.0% (TARGET); ALB +10% by day 19 then held 83d exit +20.0% (TARGET); ALLE +10% by day 24 then held 175d exit +20.0% (TARGET)

## 7. `winner_peak_giveback` (40 sym / 45 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ACRS, AER, AFRM, AMTX, ANIP, ASM, AVAV, AX, BLDR, CELH, CGC, CLS, DOCU, ESE, ESEA, FICO, FIVN, FSLR, GME, HCI
- **Evidence:** ACRS peak~75% -> exit +32.4% (giveback~43pp, 33d, TARGET); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AMTX peak~171% -> exit +137.5% (giveback~34pp, 1049d, TARGET); ANIP peak~78% -> exit +67.0% (giveback~11pp, 292d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (42 sym / 9674 trades) — direction: expand, confidence: medium, 50.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (9674 trades, 51%, high) vs target_contract_approach_fail → contract (3544 trades, 10%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 9674/19134 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 3544/35895 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +7% in 15d after TARGET; AA +8% in 15d after TARGET; AA +17% in 15d after TARGET; AA +5% in 15d after TARGET; AA +9% in 15d after TARGET; AA +9% in 15d after TARGET | [B contract] AA reached 69% of target then STOP; AA reached 90% of target then STOP; AA reached 65% of target then STOP; AA reached 70% of target then STOP; AA reached 72% of target then STOP; A reached 62% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (40 sym / 8406 trades) — direction: mixed, confidence: medium, 67.4% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (7986 trades, 64%, high) vs stop_ok_never_worked → hold (8406 trades, 67%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 7986/12476 STOP exits (64%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 8406/12476 STOPs (67%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA STOP 2011-06-13 then back above entry/15d; AA STOP 2013-12-12 then back above entry/15d; AA STOP 2014-02-10 then back above entry/15d; AA STOP 2015-07-08 then back above entry/15d; AA STOP 2017-11-20 then back above entry/15d; AA STOP 2017-11-29 then back above entry/15d | [B hold] AA MFE~1.2% STOP; AA MFE~1.6% STOP; AA MFE~0.7% STOP; AA MFE~0.5% STOP; AA MFE~0.4% STOP; AA MFE~0.9% STOP

## 3. `band_tighten_weak_fill` (1092 sym / 8927 trades) — direction: tighten, confidence: high, 24.9% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 8927/35895 trades (25%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** AA MFE~1.2% STOP 3d; AA MFE~1.6% STOP 2d; AA MFE~0.7% STOP 0d; AA MFE~0.5% STOP 0d; AA MFE~0.4% STOP 1d; AA MFE~0.9% STOP 5d

## 4. `target_contract_slow_hold` (511 sym / 863 trades) — direction: contract, confidence: low, 4.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 863/19134 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAL, AAON, AAT, ABG, ABT, ABUS, ACGL, ACM, ACN, ADBE, ADI, ADNT, ADP, AEE, AEIS, AEP, AER, AFG, AFL
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d); AAT TARGET 239d +20.0% (~0.08%/d); AAON TARGET 147d +20.0% (~0.14%/d); AAON TARGET 151d +6.3% (~0.04%/d); AAL TARGET 196d +20.0% (~0.10%/d); ABT TARGET 210d +20.0% (~0.10%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
