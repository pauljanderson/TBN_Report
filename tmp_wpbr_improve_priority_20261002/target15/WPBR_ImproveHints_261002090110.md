# WPBR Improve Hints — stamp `261002090110`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (389 sym / 599 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, AEE, AEP, AFG, AFL, AGM, AGNC, AIT
- **Evidence:** AAON TARGET 113d +15.0% (~0.13%/d) 2011-06-17; A TARGET 224d +15.0% (~0.07%/d) 2017-02-09; AAT TARGET 105d +15.0% (~0.14%/d) 2012-08-21; ABT TARGET 123d +15.0% (~0.12%/d) 2015-02-20; ABT TARGET 133d +15.0% (~0.11%/d) 2019-07-22

## 2. `fat_stops` (252 sym / 337 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABBNY, ABR, ABUS, ACAD, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY

## 3. `post_target_quick_stop` (111 sym / 121 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ACAD, ACLS, ADPT, ADSK, AI, ALGN, ALNY, ALSN, AMTX, ANIP, AOSL, APLD, APP, ARES, AU, AWI, AXON, AYI, BA
- **Evidence:** AAMI TARGET 2015-05-06 -> STOP 2022-01-21 (9d); ACLS TARGET 2023-06-07 -> STOP 2024-11-15 (3d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ADPT TARGET 2021-02-12 -> STOP 2021-03-04 (8d); ADSK TARGET 2014-06-06 -> STOP 2016-12-02 (7d)

## 4. `early_run_long_tail` (72 sym / 74 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AIT, ALLE, ALSN, AON, APG, BA, BAESY, BALL, BKHYY, BLK, BLX, BSX, BWXT, CASY, CBOE, CCEP, CCI, CF, CNC
- **Evidence:** ACU +10% by day 8 then held 204d exit +15.0% (TARGET); ALLE +10% by day 24 then held 143d exit +15.0% (TARGET); AIT +10% by day 19 then held 224d exit +15.0% (TARGET); ALSN +10% by day 17 then held 274d exit +15.0% (TARGET); APG +10% by day 12 then held 80d exit +15.0% (TARGET)

## 5. `false_start_2022_2023` (43 sym / 45 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILI, BILL, CB, CCL, CGC, COIN, DXCM, EGP, GH, GME, GNRC
- **Evidence:** AA 2022 STOP 13d -14.4%; AAMI 2022 STOP 9d -10.3%; ACRS 2023 STOP 8d -14.2%; AEHR 2022 STOP 7d -10.8%; AEHR 2022 STOP 2d -12.8%

## 6. `winner_peak_giveback` (26 sym / 29 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, ALNT, AVAV, AX, CCJ, CLS, FSLR, FTAI, HROW, JMIA, LUGDF, MOD, PATK, PLUS, PRIM, RBC, RGC, SENEA, SSNC
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AX peak~28% -> exit +15.0% (giveback~13pp, 92d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (63 sym / 1028 trades) — direction: expand, confidence: medium, 47.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1028 trades, 48%, high) vs target_contract_slow_hold → contract (599 trades, 28%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1028/2163 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 599/2163 TARGET exits (28%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAL, AAON, AAT, ABCB, ABG, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM, ADMA, ADNT, ADP
- **Evidence:** [A expand] AAL +10% in 15d after TARGET; AAL +14% in 15d after TARGET; AAL +8% in 15d after TARGET; ABUS +60% in 15d after TARGET; ACLS +8% in 15d after TARGET; ACU +10% in 15d after TARGET | [B contract] AAON TARGET 113d +15.0% (~0.13%/d); A TARGET 224d +15.0% (~0.07%/d); AAT TARGET 105d +15.0% (~0.14%/d); ABT TARGET 123d +15.0% (~0.12%/d); ABT TARGET 133d +15.0% (~0.11%/d); ACU TARGET 204d +15.0% (~0.07%/d)

## 2. `stop_pct_tension_expand_vs_contract` (69 sym / 455 trades) — direction: expand, confidence: medium, 30.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (455 trades, 30%, high) vs stop_contract_dead_losers → contract (215 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 455/1500 STOP exits (30%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 215/1500 STOPs (14%) never expanded (MFE<2%) and 337 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAON, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ADI, ADSK, AEE, AEHR, AEP, AFRM, AGO, AGX, AI
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAPL STOP 2013-04-19 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d | [B contract] AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; ADSK MFE~1.1% STOP; AEHR MFE~0.9% STOP

## 3. `target_contract_approach_fail` (441 sym / 561 trades) — direction: contract, confidence: medium, 12.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 561/4390 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAON, AAPL, ABCB, ABR, ABT, ABUS, ACA, ACM, ACN, ACRS, ADI, ADMA, ADNT, AEHR, AEM, AES, AFRM, AGO
- **Evidence:** AA reached 55% of target then STOP; AAON reached 61% of target then STOP; AAON reached 73% of target then STOP; AAPL reached 54% of target then STOP; AAL reached 62% of target then STOP; ACA reached 56% of target then STOP

## 4. `band_tighten_weak_fill` (125 sym / 139 trades) — direction: tighten, confidence: low, 3.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 139/4390 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANIP, ANNX, AOSL, APP, ARES, AVGO, AYI, B, BA, BAP, BBW, BEP
- **Evidence:** AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; ADSK MFE~1.1% STOP 7d; AEHR MFE~0.9% STOP 4d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
