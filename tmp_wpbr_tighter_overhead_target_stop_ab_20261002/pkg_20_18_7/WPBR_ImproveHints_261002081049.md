# WPBR Improve Hints — stamp `261002081049`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (431 sym / 688 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, AEE, AEIS, AEP, AFL, AGM, AGNC, AIT
- **Evidence:** AAON TARGET 139d +18.0% (~0.13%/d) 2011-07-13; A TARGET 230d +18.0% (~0.08%/d) 2017-02-15; ABT TARGET 184d +18.0% (~0.10%/d) 2015-04-22; AAT TARGET 122d +18.0% (~0.15%/d) 2012-09-07; ACU TARGET 216d +18.0% (~0.08%/d) 2014-12-29

## 2. `fat_stops` (241 sym / 317 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABR, ABUS, ACAD, ACLS, ACRS, ADMA, ADPT, AEHR, AFRM, AGI, AHCO, AHT, AI, ALB, ALGN, ALNT, ALNY, AMAT

## 3. `post_target_quick_stop` (134 sym / 149 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ADSK, ALGN, ALL, ALLE, ALNY, AMTX, AMZN, APLD, APP, ATLC, AWI, AWK, AXON, AYI, BA, BABA, BANF, BBW, BILI, BILL
- **Evidence:** ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALLE TARGET 2019-11-01 -> STOP 2020-03-09 (7d); ALL TARGET 2017-05-03 -> STOP 2018-02-09 (1d); ALNY TARGET 2024-08-29 -> STOP 2026-02-12 (9d); ALGN TARGET 2017-08-15 -> STOP 2020-03-18 (0d)

## 4. `early_run_long_tail` (113 sym / 121 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AGYS, ALB, ALLE, ALSN, AMGN, AON, APG, APH, ARES, ASML, AX, BA, BAESY, BALL, BIO, BKHYY, BKNG, BLK, BLX
- **Evidence:** ACU +10% by day 8 then held 216d exit +18.0% (TARGET); AGYS +10% by day 15 then held 90d exit +22.9% (GAP_UP); ALB +10% by day 19 then held 83d exit +18.0% (TARGET); ALLE +10% by day 24 then held 150d exit +18.0% (TARGET); ALSN +10% by day 17 then held 281d exit +18.0% (GAP_UP)

## 5. `false_start_2022_2023` (55 sym / 58 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, ADMA, AEHR, AFRM, AGO, AI, AMTX, APLD, ATUSF, AZO, BILI, BILL, CB, CCL, CGC, COIN, DXCM, EGP
- **Evidence:** AA 2022 STOP 13d -13.5%; AAMI 2022 STOP 9d -9.3%; ACRS 2023 STOP 8d -13.3%; ADMA 2022 STOP 15d -9.8%; AEHR 2022 STOP 7d -9.9%

## 6. `winner_peak_giveback` (26 sym / 31 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AFRM, ARGX, ASM, AVAV, CCJ, CLF, CLS, FSLR, HCI, HL, HP, HROW, JMIA, KTOS, LEU, LUGDF, MOD, OMER, PLUS, PRI
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ARGX peak~33% -> exit +18.0% (giveback~15pp, 20d, GAP_UP); ASM peak~38% -> exit +18.6% (giveback~19pp, 19d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CCJ peak~29% -> exit +18.0% (giveback~11pp, 32d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (64 sym / 917 trades) — direction: expand, confidence: medium, 45.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (917 trades, 46%, high) vs target_contract_slow_hold → contract (688 trades, 34%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 917/2013 TARGET exits (46%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 688/2013 TARGET exits (34%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABG, ABNB, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM
- **Evidence:** [A expand] AA +13% in 15d after TARGET; ABNB +12% in 15d after TARGET; AAPL +20% in 15d after TARGET; ABUS +56% in 15d after TARGET; AAL +11% in 15d after TARGET; ACLS +6% in 15d after TARGET | [B contract] AAON TARGET 139d +18.0% (~0.13%/d); A TARGET 230d +18.0% (~0.08%/d); ABT TARGET 184d +18.0% (~0.10%/d); AAT TARGET 122d +18.0% (~0.15%/d); ACU TARGET 216d +18.0% (~0.08%/d); ACM TARGET 262d +18.0% (~0.07%/d)

## 2. `stop_pct_tension_expand_vs_contract` (65 sym / 652 trades) — direction: expand, confidence: medium, 35.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (652 trades, 35%, high) vs stop_contract_dead_losers → contract (276 trades, 15%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 652/1854 STOP exits (35%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 276/1854 STOPs (15%) never expanded (MFE<2%) and 317 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAMI, AAON, AAPL, AAT, ABCB, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ADI, ADMA, ADSK, AEE, AEHR, AEM
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAPL STOP 2013-04-18 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ABR STOP 2010-07-06 then back above entry/15d | [B contract] AAMI MFE~1.6% STOP; A MFE~0.0% STOP; ABR MFE~1.9% STOP; AAT MFE~1.7% STOP; ACRS MFE~0.0% STOP; ACRS MFE~1.4% STOP

## 3. `target_contract_approach_fail` (444 sym / 579 trades) — direction: contract, confidence: medium, 12.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 579/4580 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAL, AAMI, AAON, AAP, AAPL, ABCB, ABM, ABR, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ADI, ADMA, ADPT, AEHR
- **Evidence:** AAMI reached 85% of target then STOP; AAON reached 51% of target then STOP; AAON reached 61% of target then STOP; ABM reached 80% of target then STOP; ABT reached 85% of target then STOP; AAPL reached 80% of target then STOP

## 4. `band_tighten_weak_fill` (176 sym / 197 trades) — direction: tighten, confidence: low, 4.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 197/4580 trades (4%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, ABR, ACRS, ADSK, AEHR, AEM, AGO, AI, AKTS, ALL, ALNY, AMN, AMP, AMTX, AMZN, ANNX, APP, AVGO, AWI
- **Evidence:** AAMI MFE~1.6% STOP 9d; A MFE~0.0% STOP 4d; ABR MFE~1.9% STOP 11d; ACRS MFE~0.0% STOP 6d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
