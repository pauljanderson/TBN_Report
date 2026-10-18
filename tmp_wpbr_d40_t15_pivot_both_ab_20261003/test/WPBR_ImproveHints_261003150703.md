# WPBR Improve Hints — stamp `261003150703`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (291 sym / 397 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AAMI, AAON, AAP, AAT, ACGL, ADBE, ADI, ADM, AEE, AER, AIR, AIT, AJG, AKAM, ALSN, AME, AMG, AMT, ANDE, AON
- **Evidence:** AAMI TARGET 118d +15.0% (~0.13%/d) 2021-04-08; ACGL TARGET 127d +15.0% (~0.12%/d) 2021-10-27; AAT TARGET 108d +15.0% (~0.14%/d) 2016-05-09; AEE TARGET 371d +15.0% (~0.04%/d) 2026-03-02; ADBE TARGET 121d +15.0% (~0.12%/d) 2018-09-14

## 2. `fat_stops` (244 sym / 325 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, ABR, ABUS, ACAD, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AGNC, AHT, AI, AKAM, ALDX, ALGN, ALNT, ALNY

## 3. `post_target_quick_stop` (114 sym / 125 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAT, ABCB, ABR, ACAD, ACLS, ADPT, AI, ALGN, ALNY, ALSN, AMTX, ANIP, AOSL, APLD, APP, ARES, AWI, AXON, BABA, BBW
- **Evidence:** ADPT TARGET 2021-02-12 -> STOP 2021-03-04 (8d); AAT TARGET 2016-05-09 -> STOP 2018-02-09 (8d); ABR TARGET 2021-04-26 -> STOP 2021-11-22 (10d); ACLS TARGET 2023-06-07 -> STOP 2024-11-15 (3d); AI TARGET 2025-10-03 -> STOP 2025-11-17 (7d)

## 4. `early_run_long_tail` (69 sym / 71 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ADBE, ADI, AIT, ALSN, ATR, AYI, BN, BR, BWXT, CASY, CCI, COST, CPT, CRH, CVS, DBSDY, DHI, DVA, DXC, EAT
- **Evidence:** ADBE +10% by day 15 then held 191d exit +15.2% (GAP_UP); ADI +10% by day 14 then held 196d exit +15.0% (TARGET); AIT +10% by day 19 then held 224d exit +15.0% (TARGET); AIT +10% by day 22 then held 114d exit +15.0% (TARGET); ALSN +10% by day 17 then held 274d exit +15.0% (TARGET)

## 5. `false_start_2022_2023` (55 sym / 57 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, ACRS, AEE, AEHR, AFRM, AMP, AMTX, APLD, ATUSF, BILI, BILL, CCL, CGC, CHD, CNC, COIN, DE, DHI, DXCM, GH
- **Evidence:** AA 2022 STOP 13d -14.4%; ACRS 2023 STOP 8d -14.2%; AEE 2022 STOP 3d -7.6%; AFRM 2022 STOP 7d -13.9%; AEHR 2022 STOP 7d -10.8%

## 6. `winner_peak_giveback` (25 sym / 28 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, ALBY, ALNT, AVAV, CCJ, CLS, DPZ, FSLR, FTAI, HROW, JMIA, KFY, LUGDF, MOD, PATK, PRIM, RBC, RGC, SENEA
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ALBY peak~27% -> exit +15.0% (giveback~12pp, 54d, TARGET); ALBY peak~29% -> exit +18.4% (giveback~11pp, 107d, GAP_UP); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (61 sym / 1021 trades) — direction: expand, confidence: medium, 50.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1021 trades, 50%, high) vs target_contract_approach_fail → contract (458 trades, 10%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1021/2034 TARGET exits (50%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 458/4752 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAMI, AAON, AAPL, ABBV, ABCB, ABG, ABR, ABUS, ACA, ACLS, ACRS, ADBE, ADM, ADMA, ADNT, ADPT, ADSK, AEHR
- **Evidence:** [A expand] ADPT +9% in 15d after TARGET; ADPT +20% in 15d after TARGET; ADPT +9% in 15d after TARGET; ADPT +8% in 15d after TARGET; ADNT +10% in 15d after TARGET; ADNT +6% in 15d after TARGET | [B contract] AA reached 55% of target then STOP; ACA reached 80% of target then STOP; ADNT reached 69% of target then STOP; ADNT reached 53% of target then STOP; ACRS reached 57% of target then STOP; ACRS reached 75% of target then STOP

## 2. `stop_pct_tension_expand_vs_contract` (65 sym / 465 trades) — direction: expand, confidence: medium, 33.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (465 trades, 33%, high) vs stop_contract_dead_losers → contract (267 trades, 19%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 465/1404 STOP exits (33%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 267/1404 STOPs (19%) never expanded (MFE<2%) and 325 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAPL, AAT, ABCB, ABG, ABR, ACA, ACAD, ACLS, ACRS, ADBE, ADP, ADSK, AEE, AEG, AEHR, AFL, AFRM, AGM, AGNC
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ADP STOP 2020-03-18 then back above entry/15d; ACRS STOP 2023-10-25 then back above entry/15d; ACRS STOP 2025-06-18 then back above entry/15d; ACRS STOP 2026-02-18 then back above entry/15d | [B contract] ADP MFE~1.4% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AAPL MFE~0.1% STOP; AAT MFE~0.5% STOP; AEE MFE~0.3% STOP

## 3. `target_contract_slow_hold` (291 sym / 397 trades) — direction: contract, confidence: high, 19.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 397/2034 TARGET exits (20%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AAMI, AAON, AAP, AAT, ACGL, ADBE, ADI, ADM, AEE, AER, AIR, AIT, AJG, AKAM, ALSN, AME, AMG, AMT, ANDE, AON
- **Evidence:** AAMI TARGET 118d +15.0% (~0.13%/d); ACGL TARGET 127d +15.0% (~0.12%/d); AAT TARGET 108d +15.0% (~0.14%/d); AEE TARGET 371d +15.0% (~0.04%/d); ADBE TARGET 121d +15.0% (~0.12%/d); ADM TARGET 146d +15.0% (~0.10%/d)

## 4. `band_tighten_weak_fill` (169 sym / 197 trades) — direction: tighten, confidence: low, 4.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 197/4752 trades (4%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAPL, AAT, ABCB, ABR, ACLS, ACRS, ADP, AEE, AEHR, AKTS, ALB, ALNY, ALSN, AMP, AMZN, ANIP, ANNX, AOS, AOSL, APP
- **Evidence:** ADP MFE~1.4% STOP 0d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AAPL MFE~0.1% STOP 11d; AAT MFE~0.5% STOP 8d; AEE MFE~0.3% STOP 3d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
