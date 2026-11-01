# WPBR Improve Hints — stamp `261003081714`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (426 sym / 641 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADP, AEE, AEIS, AEP, AER, AFG, AFL, AGNC
- **Evidence:** AAL TARGET 196d +20.0% (~0.10%/d) 2013-10-01; A TARGET 256d +20.0% (~0.08%/d) 2017-03-13; ABT TARGET 210d +20.0% (~0.10%/d) 2015-05-18; AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; AAT TARGET 239d +20.0% (~0.08%/d) 2013-01-02

## 2. `fat_stops` (246 sym / 328 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABR, ABUS, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY, AMD, AMKR

## 3. `early_run_long_tail` (135 sym / 144 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AEIS, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AON, APG, APH, APP, ARES, ASML, AVGO, AX, BA, BABA, BAESY, BALL
- **Evidence:** ACU +10% by day 8 then held 217d exit +20.0% (TARGET); AEIS +10% by day 18 then held 316d exit +20.0% (TARGET); ALLE +10% by day 24 then held 175d exit +20.0% (TARGET); ALSN +10% by day 17 then held 283d exit +20.0% (TARGET); AIT +10% by day 19 then held 418d exit +20.0% (TARGET)

## 4. `post_target_quick_stop` (97 sym / 106 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, ADSK, ALGN, ALNY, APLD, APP, ARES, AU, AWI, AXON, AYI, BA, BAC, BANF, BBW, BILL, BLBD, CELH, CHCI, CHDN
- **Evidence:** ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d); ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALGN TARGET 2017-09-06 -> STOP 2020-03-18 (0d); APP TARGET 2021-11-11 -> STOP 2021-12-03 (7d); APP TARGET 2025-12-02 -> STOP 2026-01-30 (9d)

## 5. `false_start_2022_2023` (41 sym / 42 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILL, CB, CCL, CGC, COIN, DOCN, DXCM, GH, GME, GNRC, HBAN
- **Evidence:** AAMI 2022 STOP 9d -10.3%; AA 2022 STOP 13d -14.4%; ACRS 2023 STOP 8d -14.2%; AFRM 2022 STOP 7d -13.9%; AEHR 2022 STOP 7d -10.8%

## 6. `winner_peak_giveback` (28 sym / 32 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AER, AFRM, AMTX, APLD, ASM, AVAV, CLF, CLS, DOCU, DRS, FICO, FSLR, HCI, JMIA, KTOS, LEU, LUGDF, MOD, PRI, REAL
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AMTX peak~37% -> exit +20.0% (giveback~17pp, 42d, TARGET); APLD peak~33% -> exit +21.2% (giveback~12pp, 19d, GAP_UP); ASM peak~38% -> exit +20.0% (giveback~18pp, 19d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (65 sym / 783 trades) — direction: mixed, confidence: medium, 45.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (783 trades, 45%, high) vs target_contract_slow_hold → contract (641 trades, 37%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 783/1725 TARGET exits (45%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 641/1725 TARGET exits (37%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABG, ABNB, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM, ADMA
- **Evidence:** [A expand] AAL +5% in 15d after TARGET; AAL +9% in 15d after TARGET; AAL +11% in 15d after TARGET; ABUS +54% in 15d after TARGET; AA +11% in 15d after TARGET; AAPL +18% in 15d after TARGET | [B contract] AAL TARGET 196d +20.0% (~0.10%/d); A TARGET 256d +20.0% (~0.08%/d); ABT TARGET 210d +20.0% (~0.10%/d); AAON TARGET 147d +20.0% (~0.14%/d); AAT TARGET 239d +20.0% (~0.08%/d); ABG TARGET 104d +20.0% (~0.19%/d)

## 2. `stop_pct_tension_expand_vs_contract` (71 sym / 478 trades) — direction: expand, confidence: medium, 35.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (478 trades, 35%, high) vs stop_contract_dead_losers → contract (180 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 478/1359 STOP exits (35%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 180/1359 STOPs (13%) never expanded (MFE<2%) and 328 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAON, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACRS, ADI, ADSK, AEE, AEHR, AFRM, AGO, AGX, AI, AIG, AIZ
- **Evidence:** [A expand] ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; ABR STOP 2010-08-31 then back above entry/15d; AA STOP 2022-05-09 then back above entry/15d | [B contract] AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; ADSK MFE~1.1% STOP; AKTS MFE~0.1% STOP

## 3. `target_contract_approach_fail` (358 sym / 439 trades) — direction: contract, confidence: medium, 10.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 439/4293 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAMI, AAON, ABM, ABR, ABT, ABUS, ACA, ACM, ACN, ACRS, ADI, ADMA, ADNT, ADPT, AEM, AFL, AFRM, AGO, AGX, AIG
- **Evidence:** ACA reached 60% of target then STOP; ABT reached 76% of target then STOP; AAMI reached 76% of target then STOP; AAON reached 55% of target then STOP; ABUS reached 73% of target then STOP; ABR reached 60% of target then STOP

## 4. `band_tighten_weak_fill` (122 sym / 135 trades) — direction: tighten, confidence: low, 3.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 135/4293 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANNX, APP, ARES, AVGO, AYI, B, BA, BAC, BAP, BBW, BEP, BLBD
- **Evidence:** AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; ADSK MFE~1.1% STOP 7d; AKTS MFE~0.1% STOP 2d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
