# WPBR Improve Hints — stamp `261002055424`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (421 sym / 665 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAON, AAT, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, AEE, AEIS, AEP, AFL, AGM, AGNC, AIT
- **Evidence:** A TARGET 230d +18.0% (~0.08%/d) 2017-02-15; ABT TARGET 184d +18.0% (~0.10%/d) 2015-04-22; AAON TARGET 139d +18.0% (~0.13%/d) 2011-07-13; ADNT TARGET 125d +18.0% (~0.14%/d) 2021-11-23; ACU TARGET 216d +18.0% (~0.08%/d) 2014-12-29

## 2. `fat_stops` (214 sym / 282 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABR, ABUS, ACAD, ACRS, ADMA, ADPT, AEHR, AFRM, AGI, AHT, AI, ALB, ALGN, ALNT, ALNY, AMAT, AMD, AMRC

## 3. `post_target_quick_stop` (116 sym / 127 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ADSK, ALGN, ALL, ALNY, AMTX, APLD, APP, ATLC, AWI, AWK, AXON, AYI, BA, BABA, BANF, BBW, BILL, BLBD, BN, CB
- **Evidence:** ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALL TARGET 2017-05-03 -> STOP 2018-02-09 (1d); ALNY TARGET 2024-08-29 -> STOP 2026-02-12 (9d); AMTX TARGET 2017-08-15 -> STOP 2021-05-12 (0d); ALGN TARGET 2017-08-15 -> STOP 2020-03-18 (0d)

## 4. `early_run_long_tail` (109 sym / 117 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ALB, ALLE, ALSN, AMGN, AON, APG, APH, ARES, ASML, AX, BA, BAESY, BALL, BIO, BKHYY, BLK, BLX, BWXT, CASY
- **Evidence:** ACU +10% by day 8 then held 216d exit +18.0% (TARGET); ALB +10% by day 19 then held 83d exit +18.0% (TARGET); ALLE +10% by day 24 then held 150d exit +18.0% (TARGET); ALSN +10% by day 17 then held 281d exit +18.0% (GAP_UP); APG +10% by day 12 then held 83d exit +18.0% (TARGET)

## 5. `false_start_2022_2023` (48 sym / 50 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AGO, AMTX, APLD, ATUSF, AZO, BILL, CB, CCL, CGC, COIN, DXCM, EGP, GME, GNRC, HBAN
- **Evidence:** AA 2022 STOP 13d -13.5%; AAMI 2022 STOP 9d -9.3%; ACRS 2023 STOP 8d -13.3%; AEHR 2022 STOP 7d -9.9%; AEHR 2022 STOP 2d -11.9%

## 6. `winner_peak_giveback` (25 sym / 30 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AFRM, ASM, AVAV, CCJ, CLF, CLS, FSLR, HCI, HL, HP, HROW, JMIA, KTOS, LEU, LUGDF, MOD, OMER, PLUS, PRI, RGC
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ASM peak~38% -> exit +18.6% (giveback~19pp, 19d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CCJ peak~29% -> exit +18.0% (giveback~11pp, 32d, TARGET); CLS peak~35% -> exit +20.4% (giveback~14pp, 26d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (64 sym / 865 trades) — direction: expand, confidence: medium, 45.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (865 trades, 45%, high) vs target_contract_slow_hold → contract (665 trades, 35%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 865/1904 TARGET exits (45%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 665/1904 TARGET exits (35%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABG, ABNB, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM
- **Evidence:** [A expand] AA +13% in 15d after TARGET; ABNB +12% in 15d after TARGET; ABUS +56% in 15d after TARGET; ACLS +6% in 15d after TARGET; ACRS +8% in 15d after TARGET; ACRS +174% in 15d after TARGET | [B contract] A TARGET 230d +18.0% (~0.08%/d); ABT TARGET 184d +18.0% (~0.10%/d); AAON TARGET 139d +18.0% (~0.13%/d); ADNT TARGET 125d +18.0% (~0.14%/d); ACU TARGET 216d +18.0% (~0.08%/d); AAT TARGET 122d +18.0% (~0.15%/d)

## 2. `stop_pct_tension_expand_vs_contract` (65 sym / 594 trades) — direction: expand, confidence: medium, 34.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (594 trades, 34%, high) vs stop_contract_dead_losers → contract (251 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 594/1734 STOP exits (34%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 251/1734 STOPs (14%) never expanded (MFE<2%) and 282 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAON, AAPL, AAT, ABCB, ABG, ABR, ACA, ACAD, ACLS, ACRS, ADI, ADSK, AEE, AEHR, AEM, AEP, AFRM, AGO
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; ABR STOP 2010-07-06 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; ACAD STOP 2011-05-23 then back above entry/15d | [B contract] AAMI MFE~1.6% STOP; ABR MFE~1.9% STOP; ACRS MFE~0.0% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AAT MFE~1.7% STOP

## 3. `target_contract_approach_fail` (430 sym / 547 trades) — direction: contract, confidence: medium, 12.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 547/4305 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAL, AAMI, AAON, AAP, AAPL, ABCB, ABM, ABR, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ADI, ADMA, ADPT, AEHR
- **Evidence:** ACA reached 67% of target then STOP; AAMI reached 85% of target then STOP; ABT reached 85% of target then STOP; ABR reached 66% of target then STOP; ABR reached 57% of target then STOP; AAON reached 51% of target then STOP

## 4. `band_tighten_weak_fill` (152 sym / 170 trades) — direction: tighten, confidence: low, 3.9% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 170/4305 trades (4%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ABR, ACRS, ADSK, AEHR, AEM, AGO, AKTS, ALL, ALNY, AMP, AMTX, ANNX, APP, AVGO, AWI, AWK, AYI, B, BA
- **Evidence:** AAMI MFE~1.6% STOP 9d; ABR MFE~1.9% STOP 11d; ACRS MFE~0.0% STOP 6d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AEHR MFE~0.9% STOP 4d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
