# WPBR Improve Hints — stamp `261002081049`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (352 sym / 513 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAON, AAT, ABT, ACGL, ACN, ACU, ADBE, ADI, ADP, AEE, AEP, AFG, AFL, AGM, AGNC, AIT, AJG, AKR, ALB
- **Evidence:** AAON TARGET 113d +15.0% (~0.13%/d) 2011-06-17; A TARGET 224d +15.0% (~0.07%/d) 2017-02-09; ABT TARGET 123d +15.0% (~0.12%/d) 2015-02-20; ABT TARGET 133d +15.0% (~0.11%/d) 2019-07-22; AAT TARGET 105d +15.0% (~0.14%/d) 2012-08-21

## 2. `fat_stops` (176 sym / 231 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACLS, ACRS, ADMA, ADNT, ADPT, AEHR, AFRM, AHCO, AHT, AI, ALB, ALEC, ALGN, ALL, ALNT, ALNY, AMRC, AMTX, AMWL

## 3. `post_target_quick_stop` (172 sym / 205 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ABCB, ACAD, ACN, ACRS, ADPT, ADSK, AEIS, AI, ALEC, ALGN, ALL, ALLE, ALNY, AMKR, AMTX, AMZN, ANIK, ANIP, AOSL
- **Evidence:** AAMI TARGET 2015-05-06 -> STOP 2022-01-20 (8d); ACAD TARGET 2011-04-11 -> STOP 2011-05-23 (4d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACRS TARGET 2017-02-24 -> STOP 2020-11-16 (3d); ADPT TARGET 2021-02-12 -> STOP 2021-03-03 (7d)

## 4. `false_start_2022_2023` (75 sym / 85 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, AEHR, AFRM, AGO, AI, AMTX, APLD, ATUSF, AVGO, BG, BILI, CB, CCL, CGC, CI, COIN, CPT, CUBE
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADMA 2022 STOP 15d -8.8%; AEHR 2022 STOP 7d -8.9%; AEHR 2022 STOP 2d -10.9%

## 5. `early_run_long_tail` (67 sym / 69 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ADI, ALLE, ALSN, AON, APG, BA, BAESY, BALL, BKHYY, BLK, BLX, BWXT, CASY, CBOE, CCEP, CRZBY, CTAS, DHI, DRD
- **Evidence:** ACU +10% by day 8 then held 204d exit +15.0% (TARGET); ADI +10% by day 14 then held 196d exit +15.0% (TARGET); ALLE +10% by day 24 then held 143d exit +15.0% (TARGET); ALSN +10% by day 17 then held 274d exit +15.0% (TARGET); APG +10% by day 12 then held 80d exit +15.0% (TARGET)

## 6. `winner_peak_giveback` (25 sym / 28 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, ALNT, AVAV, AX, CCJ, CLS, ESEA, FIVN, FSLR, HROW, JMIA, LUGDF, MOD, PATK, PLUS, PRIM, RBC, RGC, SENEA
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AX peak~28% -> exit +15.0% (giveback~13pp, 92d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (59 sym / 1059 trades) — direction: expand, confidence: medium, 48.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1059 trades, 48%, high) vs target_contract_approach_fail → contract (669 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1059/2185 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 669/5052 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAL, AAON, AAPL, ABCB, ABG, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM, ADMA, ADNT
- **Evidence:** [A expand] ABUS +60% in 15d after TARGET; AAL +10% in 15d after TARGET; AAL +14% in 15d after TARGET; AAL +8% in 15d after TARGET; ACLS +8% in 15d after TARGET; ACAD +7% in 15d after TARGET | [B contract] AAON reached 79% of target then STOP; AAON reached 61% of target then STOP; AAON reached 73% of target then STOP; AAPL reached 54% of target then STOP; ACA reached 56% of target then STOP; ACA reached 80% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (63 sym / 809 trades) — direction: expand, confidence: medium, 39.9% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (809 trades, 40%, high) vs stop_ok_never_worked → hold (378 trades, 19%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 809/2026 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 378/2026 STOPs (19%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABCB, ABG, ABR, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADMA, ADNT, ADSK
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2014-04-07 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAPL STOP 2013-04-18 then back above entry/15d; ACA STOP 2023-10-27 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; A MFE~0.0% STOP; ABR MFE~1.9% STOP; AAT MFE~1.7% STOP; ACRS MFE~0.0% STOP; ACRS MFE~1.4% STOP

## 3. `target_contract_slow_hold` (352 sym / 513 trades) — direction: contract, confidence: high, 23.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 513/2185 TARGET exits (23%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAON, AAT, ABT, ACGL, ACN, ACU, ADBE, ADI, ADP, AEE, AEP, AFG, AFL, AGM, AGNC, AIT, AJG, AKR, ALB
- **Evidence:** AAON TARGET 113d +15.0% (~0.13%/d); A TARGET 224d +15.0% (~0.07%/d); ABT TARGET 123d +15.0% (~0.12%/d); ABT TARGET 133d +15.0% (~0.11%/d); AAT TARGET 105d +15.0% (~0.14%/d); ACU TARGET 204d +15.0% (~0.07%/d)

## 4. `band_tighten_weak_fill` (259 sym / 312 trades) — direction: tighten, confidence: low, 6.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 312/5052 trades (6%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABCB, ABR, ACRS, ADSK, AEHR, AEIS, AEM, AGO, AI, AKTS, ALEC, ALL, ALNY, AMKR, AMN, AMP, AMTX
- **Evidence:** AAMI MFE~1.6% STOP 8d; A MFE~0.0% STOP 1d; AAPL MFE~3.0% STOP 4d; ABR MFE~1.9% STOP 11d; ACRS MFE~0.0% STOP 3d; ACRS MFE~1.4% STOP 7d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
