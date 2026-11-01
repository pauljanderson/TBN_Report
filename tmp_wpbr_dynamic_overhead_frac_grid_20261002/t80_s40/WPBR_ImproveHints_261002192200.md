# WPBR Improve Hints — stamp `261002192200`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `small_target_wins` (1098 sym / 15160 trades)
- **Lever:** target_pct / expansion / partial_exit
- **Suggestion:** Many small TARGET wins — consider higher target or partial scale-out.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL

## 2. `post_target_quick_stop` (1051 sym / 4643 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** AA TARGET 2014-01-16 -> STOP 2014-02-10 (0d); AA TARGET 2017-01-04 -> STOP 2017-03-21 (5d); AA TARGET 2017-11-16 -> STOP 2017-11-20 (0d); AA TARGET 2017-11-24 -> STOP 2017-11-29 (0d); AA TARGET 2021-09-10 -> STOP 2021-09-21 (0d)

## 3. `false_start_2022_2023` (763 sym / 1421 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBNY, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACN, ACRS, ACU, ADBE, ADI, ADMA
- **Evidence:** A 2022 STOP 1d -2.4%; A 2023 STOP 0d -2.2%; A 2023 STOP 0d -0.3%; AAMI 2022 STOP 9d -10.3%; AAT 2022 STOP 7d -4.5%

## 4. `slow_target_grind` (555 sym / 935 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAPL, AAT, ABG, ABR, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADM, ADNT, ADP, ADPT, AEE, AEIS
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d) 2017-03-13; AAT TARGET 239d +20.0% (~0.08%/d) 2013-01-02; AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; AAON TARGET 151d +7.2% (~0.05%/d) 2016-10-04; AAPL TARGET 232d +21.9% (~0.09%/d) 2013-10-24

## 5. `fat_stops` (440 sym / 684 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAL, AAMI, ABBNY, ABBV, ABG, ABR, ABUS, ACAD, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AEM, AES, AFRM, AGI, AGM

## 6. `early_run_long_tail` (200 sym / 220 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ADPT, AEIS, AGX, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AMN, AMTX, ANIP, AON, APG, APH, APP, ARES, ASM, ASML
- **Evidence:** ADPT +10% by day 4 then held 138d exit +43.7% (TARGET); ACU +10% by day 8 then held 216d exit +18.2% (TARGET); AEIS +10% by day 18 then held 316d exit +19.9% (TARGET); AIT +10% by day 19 then held 418d exit +20.0% (TARGET); AGX +10% by day 12 then held 139d exit +40.7% (TARGET)

## 7. `winner_peak_giveback` (47 sym / 53 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ACRS, AER, AFRM, AMTX, APP, ARGX, ASM, AVAV, BBIO, BLDR, CLF, CLS, CORT, DOCU, EGO, ESEA, FCX, FICO, FIVN, FSLR
- **Evidence:** ACRS peak~75% -> exit +37.0% (giveback~38pp, 33d, TARGET); AFRM peak~36% -> exit +24.8% (giveback~11pp, 24d, TARGET); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AMTX peak~171% -> exit +157.1% (giveback~14pp, 1049d, TARGET); APP peak~54% -> exit +42.4% (giveback~12pp, 185d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (40 sym / 9344 trades) — direction: expand, confidence: medium, 50.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (9344 trades, 51%, high) vs target_contract_approach_fail → contract (3568 trades, 10%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 9344/18427 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 3568/35346 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +7% in 15d after TARGET; AA +8% in 15d after TARGET; AA +12% in 15d after TARGET; AA +16% in 15d after TARGET; AA +8% in 15d after TARGET; AA +8% in 15d after TARGET | [B contract] AA reached 79% of target then STOP; AA reached 93% of target then STOP; AA reached 58% of target then STOP; AA reached 86% of target then STOP; AA reached 86% of target then STOP; A reached 91% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (40 sym / 8211 trades) — direction: mixed, confidence: medium, 65.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (7873 trades, 63%, high) vs stop_ok_never_worked → hold (8211 trades, 65%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 7873/12581 STOP exits (63%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 8211/12581 STOPs (65%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA STOP 2011-06-13 then back above entry/15d; AA STOP 2014-02-10 then back above entry/15d; AA STOP 2015-07-08 then back above entry/15d; AA STOP 2017-11-20 then back above entry/15d; AA STOP 2017-11-29 then back above entry/15d; AA STOP 2017-12-07 then back above entry/15d | [B hold] AA MFE~1.2% STOP; AA MFE~0.7% STOP; AA MFE~1.4% STOP; AA MFE~0.5% STOP; AA MFE~0.4% STOP; AA MFE~0.9% STOP

## 3. `band_tighten_weak_fill` (1090 sym / 8723 trades) — direction: tighten, confidence: high, 24.7% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 8723/35346 trades (25%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** AA MFE~1.2% STOP 3d; AA MFE~0.7% STOP 0d; AA MFE~1.4% STOP 5d; AA MFE~0.5% STOP 0d; AA MFE~0.4% STOP 1d; AA MFE~0.9% STOP 5d

## 4. `target_contract_slow_hold` (555 sym / 935 trades) — direction: contract, confidence: low, 5.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 935/18427 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAL, AAON, AAPL, AAT, ABG, ABR, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADM, ADNT, ADP, ADPT, AEE, AEIS
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d); AAT TARGET 239d +20.0% (~0.08%/d); AAON TARGET 147d +20.0% (~0.14%/d); AAON TARGET 151d +7.2% (~0.05%/d); AAPL TARGET 232d +21.9% (~0.09%/d); AAL TARGET 196d +20.0% (~0.10%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
