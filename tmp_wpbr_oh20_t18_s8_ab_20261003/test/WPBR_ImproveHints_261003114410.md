# WPBR Improve Hints — stamp `261003114410`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (458 sym / 746 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, AEE, AEIS, AEP, AFL, AGM, AGNC, AGX
- **Evidence:** A TARGET 230d +18.0% (~0.08%/d) 2017-02-15; ADNT TARGET 125d +18.0% (~0.14%/d) 2021-11-23; ABT TARGET 184d +18.0% (~0.10%/d) 2015-04-22; AAT TARGET 122d +18.0% (~0.15%/d) 2012-09-07; AAON TARGET 139d +18.0% (~0.13%/d) 2011-07-13

## 2. `fat_stops` (303 sym / 413 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABBNY, ABR, ABUS, ACLS, ACRS, ADMA, ADPT, AEG, AEHR, AEM, AFRM, AHCO, AHT, AI, AKAM, ALB, ALDX, ALGN

## 3. `post_target_quick_stop` (124 sym / 137 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, ADSK, ALGN, ALLE, ALNY, ALSN, AMTX, AMZN, APLD, APP, ARES, AU, AWI, AXON, AYI, BA, BAC, BANF, BBW, BILI
- **Evidence:** ACLS TARGET 2023-06-07 -> STOP 2024-11-15 (3d); ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALLE TARGET 2019-11-01 -> STOP 2020-03-09 (7d); ALSN TARGET 2024-10-07 -> STOP 2025-04-04 (3d); ALGN TARGET 2017-08-15 -> STOP 2020-03-18 (0d)

## 4. `early_run_long_tail` (121 sym / 130 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AGYS, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AON, APG, APH, APP, ARES, ASML, AX, BA, BAESY, BALL, BIO, BKHYY
- **Evidence:** ACU +10% by day 8 then held 216d exit +18.0% (TARGET); AGYS +10% by day 15 then held 90d exit +22.9% (GAP_UP); ALLE +10% by day 24 then held 150d exit +18.0% (TARGET); AIT +10% by day 19 then held 231d exit +18.0% (TARGET); ALSN +10% by day 17 then held 281d exit +18.0% (GAP_UP)

## 5. `false_start_2022_2023` (47 sym / 48 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AI, AMTX, APLD, ATUSF, AZO, BILI, BILL, CB, CCL, CGC, COIN, DXCM, EGP, GH, GM
- **Evidence:** AA 2022 STOP 13d -14.4%; ACRS 2023 STOP 8d -14.2%; AAMI 2022 STOP 9d -10.3%; AFRM 2022 STOP 7d -13.9%; AI 2023 STOP 0d -17.9%

## 6. `winner_peak_giveback` (27 sym / 32 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AFRM, ARGX, ASM, AVAV, CCJ, CLF, CLS, FSLR, HCI, HL, HP, HROW, JMIA, KTOS, LEU, LUGDF, MOD, OMER, PAYC, PLUS
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ARGX peak~33% -> exit +18.0% (giveback~15pp, 20d, GAP_UP); ASM peak~38% -> exit +18.6% (giveback~19pp, 19d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CCJ peak~29% -> exit +18.0% (giveback~11pp, 32d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (63 sym / 954 trades) — direction: expand, confidence: medium, 45.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (954 trades, 45%, high) vs target_contract_slow_hold → contract (746 trades, 36%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 954/2103 TARGET exits (45%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 746/2103 TARGET exits (35%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABG, ABNB, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM
- **Evidence:** [A expand] AA +13% in 15d after TARGET; ABNB +12% in 15d after TARGET; ADPT +9% in 15d after TARGET; ADPT +17% in 15d after TARGET; ADPT +6% in 15d after TARGET; ADPT +7% in 15d after TARGET | [B contract] A TARGET 230d +18.0% (~0.08%/d); ADNT TARGET 125d +18.0% (~0.14%/d); ABT TARGET 184d +18.0% (~0.10%/d); AAT TARGET 122d +18.0% (~0.15%/d); AAON TARGET 139d +18.0% (~0.13%/d); ACU TARGET 216d +18.0% (~0.08%/d)

## 2. `stop_pct_tension_expand_vs_contract` (69 sym / 541 trades) — direction: expand, confidence: medium, 31.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (541 trades, 31%, high) vs stop_contract_dead_losers → contract (233 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 541/1733 STOP exits (31%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 233/1733 STOPs (13%) never expanded (MFE<2%) and 413 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAMI, AAON, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ADI, ADMA, ADSK, AEE, AEHR, AEP, AFRM, AGO
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ACRS STOP 2023-10-25 then back above entry/15d; ACRS STOP 2025-06-18 then back above entry/15d; ACRS STOP 2026-02-18 then back above entry/15d | [B contract] A MFE~0.0% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ADSK MFE~1.1% STOP

## 3. `target_contract_approach_fail` (434 sym / 553 trades) — direction: contract, confidence: medium, 12.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 553/4572 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAL, AAMI, AAON, AAPL, ABCB, ABM, ABR, ABT, ABUS, ACA, ACLS, ACM, ACN, ACRS, ADI, ADMA, ADNT, ADPT, AEG, AEHR
- **Evidence:** ADPT reached 87% of target then STOP; ACA reached 67% of target then STOP; ADNT reached 57% of target then STOP; ACRS reached 62% of target then STOP; ACRS reached 62% of target then STOP; AAMI reached 85% of target then STOP

## 4. `band_tighten_weak_fill` (144 sym / 159 trades) — direction: tighten, confidence: low, 3.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 159/4572 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, ACLS, ACRS, ADSK, AEHR, AI, AKTS, ALNY, AMP, AMWL, AMZN, ANNX, APP, ARES, AVGO, AYI, B, BA, BAC
- **Evidence:** A MFE~0.0% STOP 4d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ADSK MFE~1.1% STOP 7d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
