# WPBR Improve Hints — stamp `261003124834`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (321 sym / 455 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AGNC, AIT, AJG, ALB, ALG
- **Evidence:** A TARGET 224d +15.0% (~0.07%/d) 2017-02-09; ABT TARGET 123d +15.0% (~0.12%/d) 2015-02-20; AAT TARGET 105d +15.0% (~0.14%/d) 2012-08-21; AAON TARGET 113d +15.0% (~0.13%/d) 2011-06-17; ACU TARGET 204d +15.0% (~0.07%/d) 2014-12-17

## 2. `fat_stops` (215 sym / 289 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABR, ABUS, ACAD, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY, AMD

## 3. `post_target_quick_stop` (108 sym / 118 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ACAD, ACLS, ADPT, ADSK, AI, ALGN, ALNY, ALSN, AMTX, ANIP, AOSL, APLD, APP, ARES, AU, AWI, AXON, AYI, BA
- **Evidence:** ADPT TARGET 2021-02-12 -> STOP 2021-03-04 (8d); AAMI TARGET 2015-05-06 -> STOP 2022-01-21 (9d); ACLS TARGET 2023-06-07 -> STOP 2024-11-15 (3d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ADSK TARGET 2014-06-06 -> STOP 2016-12-02 (7d)

## 4. `early_run_long_tail` (58 sym / 60 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AIT, ALLE, ALSN, AON, BA, BAESY, BALL, BKHYY, BSX, BWXT, CASY, CBOE, CCEP, CCI, CNC, CTAS, DHI, DXC, EADSY
- **Evidence:** ACU +10% by day 8 then held 204d exit +15.0% (TARGET); ALLE +10% by day 24 then held 143d exit +15.0% (TARGET); AIT +10% by day 19 then held 224d exit +15.0% (TARGET); ALSN +10% by day 17 then held 274d exit +15.0% (TARGET); AON +10% by day 8 then held 110d exit +15.0% (TARGET)

## 5. `false_start_2022_2023` (43 sym / 45 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILI, BILL, CB, CCL, CGC, COIN, DXCM, EGP, GH, GME, GNRC
- **Evidence:** AA 2022 STOP 13d -14.4%; ACRS 2023 STOP 8d -14.2%; AAMI 2022 STOP 9d -10.3%; AFRM 2022 STOP 7d -13.9%; AEHR 2022 STOP 7d -10.8%

## 6. `winner_peak_giveback` (22 sym / 24 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, ALNT, AVAV, CCJ, CLS, FSLR, FTAI, HROW, JMIA, LUGDF, MOD, PATK, PRIM, RBC, RGC, SENEA, TCI, TSSI, UAN
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CCJ peak~29% -> exit +17.4% (giveback~11pp, 32d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (65 sym / 965 trades) — direction: expand, confidence: medium, 48.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (965 trades, 48%, high) vs target_contract_slow_hold → contract (455 trades, 23%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 965/1998 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 455/1998 TARGET exits (23%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAL, AAON, AAT, ABG, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADM, ADMA, ADNT, ADP, ADPT, ADSK
- **Evidence:** [A expand] ADPT +9% in 15d after TARGET; ADPT +20% in 15d after TARGET; ADPT +9% in 15d after TARGET; ADPT +8% in 15d after TARGET; ADNT +10% in 15d after TARGET; ADNT +6% in 15d after TARGET | [B contract] A TARGET 224d +15.0% (~0.07%/d); ABT TARGET 123d +15.0% (~0.12%/d); AAT TARGET 105d +15.0% (~0.14%/d); AAON TARGET 113d +15.0% (~0.13%/d); ACU TARGET 204d +15.0% (~0.07%/d); ACM TARGET 231d +15.0% (~0.06%/d)

## 2. `stop_pct_tension_expand_vs_contract` (70 sym / 426 trades) — direction: expand, confidence: medium, 35.6% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (426 trades, 36%, high) vs stop_contract_dead_losers → contract (186 trades, 16%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 426/1196 STOP exits (36%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 186/1196 STOPs (16%) never expanded (MFE<2%) and 289 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAON, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACRS, ADI, ADSK, AEE, AEHR, AFRM, AGO, AGX, AI, AIZ, AKAM
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ACRS STOP 2023-10-25 then back above entry/15d; ACRS STOP 2025-06-18 then back above entry/15d; ACRS STOP 2026-02-18 then back above entry/15d | [B contract] ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ADSK MFE~1.1% STOP; AEHR MFE~0.9% STOP

## 3. `target_contract_approach_fail` (363 sym / 445 trades) — direction: contract, confidence: medium, 10.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 445/4421 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAON, AAPL, ABR, ABUS, ACA, ACM, ACRS, ADI, ADMA, ADNT, AEHR, AEM, AES, AFRM, AGO, AHT, AI, AIG
- **Evidence:** AA reached 55% of target then STOP; ACA reached 56% of target then STOP; ACA reached 80% of target then STOP; ADNT reached 69% of target then STOP; ADNT reached 53% of target then STOP; ACRS reached 57% of target then STOP

## 4. `band_tighten_weak_fill` (126 sym / 140 trades) — direction: tighten, confidence: low, 3.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 140/4421 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANIP, ANNX, AOSL, APP, ARES, AVGO, AYI, B, BA, BAC, BAP, BBW
- **Evidence:** ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ADSK MFE~1.1% STOP 7d; AEHR MFE~0.9% STOP 4d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
