# WPBR Improve Hints — stamp `261002172253`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (478 sym / 781 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, AEE, AEIS, AEP, AER, AFG, AFL
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d) 2017-03-13; ABT TARGET 210d +20.0% (~0.10%/d) 2015-05-18; ABT TARGET 317d +20.0% (~0.06%/d) 2020-01-22; AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; ADNT TARGET 166d +20.0% (~0.12%/d) 2022-01-03

## 2. `fat_stops` (283 sym / 380 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABBNY, ABR, ABUS, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AGM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY

## 3. `early_run_long_tail` (151 sym / 161 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AEIS, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AON, APG, APH, APP, ARES, ASML, AVGO, AX, BA, BABA, BAESY, BALL
- **Evidence:** ACU +10% by day 8 then held 217d exit +20.0% (TARGET); ALB +10% by day 19 then held 83d exit +20.0% (TARGET); ALLE +10% by day 24 then held 175d exit +20.0% (TARGET); AIT +10% by day 19 then held 418d exit +20.0% (TARGET); ALSN +10% by day 17 then held 283d exit +20.0% (TARGET)

## 4. `post_target_quick_stop` (100 sym / 109 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, ADSK, ALGN, ALNY, APLD, APP, ARES, AU, AWI, AXON, AYI, BA, BAC, BANF, BBW, BILL, BLBD, CB, CELH, CHCI
- **Evidence:** ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d); ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALNY TARGET 2024-10-16 -> STOP 2026-02-12 (9d); ALGN TARGET 2017-09-06 -> STOP 2020-03-18 (0d); APLD TARGET 2023-09-28 -> STOP 2023-10-09 (0d)

## 5. `false_start_2022_2023` (41 sym / 42 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILL, CB, CCL, CGC, COIN, DOCN, DXCM, GH, GME, GNRC, HBAN
- **Evidence:** AA 2022 STOP 13d -14.4%; AAMI 2022 STOP 9d -10.3%; ACRS 2023 STOP 8d -14.2%; AEHR 2022 STOP 7d -10.8%; AEHR 2022 STOP 2d -12.8%

## 6. `winner_peak_giveback` (31 sym / 36 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AER, AFRM, AMTX, APLD, ASM, AVAV, CLF, CLS, DOCU, DRS, FICO, FSLR, HCI, JMIA, KTOS, LEU, LUGDF, MOD, PAYC, PLUS
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AMTX peak~37% -> exit +20.0% (giveback~17pp, 42d, TARGET); APLD peak~33% -> exit +21.2% (giveback~12pp, 19d, GAP_UP); ASM peak~38% -> exit +20.0% (giveback~18pp, 19d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (62 sym / 843 trades) — direction: mixed, confidence: medium, 44.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (843 trades, 45%, high) vs target_contract_slow_hold → contract (781 trades, 41%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 843/1885 TARGET exits (45%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 781/1885 TARGET exits (41%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABG, ABNB, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM, ADMA
- **Evidence:** [A expand] AA +11% in 15d after TARGET; ABNB +10% in 15d after TARGET; ABUS +54% in 15d after TARGET; ACLS +5% in 15d after TARGET; ADNT +5% in 15d after TARGET; ADMA +17% in 15d after TARGET | [B contract] A TARGET 256d +20.0% (~0.08%/d); ABT TARGET 210d +20.0% (~0.10%/d); ABT TARGET 317d +20.0% (~0.06%/d); AAON TARGET 147d +20.0% (~0.14%/d); ADNT TARGET 166d +20.0% (~0.12%/d); ACU TARGET 217d +20.0% (~0.09%/d)

## 2. `stop_pct_tension_expand_vs_contract` (70 sym / 515 trades) — direction: expand, confidence: medium, 30.5% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (515 trades, 30%, high) vs stop_contract_dead_losers → contract (208 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 515/1686 STOP exits (31%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 208/1686 STOPs (12%) never expanded (MFE<2%) and 380 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAON, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ADI, ADSK, AEE, AEHR, AEP, AFRM, AGM, AGO, AGX
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; ABR STOP 2010-08-31 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d | [B contract] AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AEHR MFE~0.9% STOP; AEHR MFE~0.9% STOP

## 3. `target_contract_approach_fail` (415 sym / 531 trades) — direction: contract, confidence: medium, 12.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 531/4252 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAMI, AAON, AAPL, ABM, ABR, ABT, ABUS, ACA, ACLS, ACM, ACN, ACRS, ADI, ADMA, ADNT, ADPT, AEHR, AEM, AFL, AFRM
- **Evidence:** ACA reached 60% of target then STOP; AAMI reached 76% of target then STOP; ABT reached 76% of target then STOP; ABR reached 60% of target then STOP; ABR reached 51% of target then STOP; AAON reached 55% of target then STOP

## 4. `band_tighten_weak_fill` (122 sym / 135 trades) — direction: tighten, confidence: low, 3.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 135/4252 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANNX, APP, ARES, AVGO, AYI, B, BA, BAC, BAP, BBW, BEP, BLBD
- **Evidence:** AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AEHR MFE~0.9% STOP 4d; AEHR MFE~0.9% STOP 7d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
