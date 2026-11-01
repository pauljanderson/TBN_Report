# WPBR Improve Hints — stamp `261002180125`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (273 sym / 350 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, ABT, ACGL, ACN, ACU, ADBE, ADI, ADP, AEIS, AER, AGM, AIG, AIT, AIZ, AJG, ALGN, ALL, ALLE
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d) 2017-03-13; ABT TARGET 210d +20.0% (~0.10%/d) 2015-05-18; ACU TARGET 217d +20.0% (~0.09%/d) 2014-12-30; AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; AAL TARGET 196d +20.0% (~0.10%/d) 2013-10-01

## 2. `fat_stops` (242 sym / 326 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABR, ABUS, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY, AMD, AMKR

## 3. `early_run_long_tail` (165 sym / 177 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, AEIS, AIT, ALB, ALLE, ALSN, AMAT, AMGN, AON, APG, APH, APP, ARES, ASML, ATO, AVGO, AX, BA, BABA, BAESY
- **Evidence:** ACU +10% by day 8 then held 217d exit +20.0% (TARGET); ALLE +10% by day 24 then held 175d exit +20.0% (TARGET); ALB +10% by day 19 then held 83d exit +20.0% (TARGET); ALSN +10% by day 17 then held 283d exit +20.0% (TARGET); AIT +10% by day 19 then held 418d exit +20.0% (TARGET)

## 4. `post_target_quick_stop` (89 sym / 98 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, ADSK, ALGN, ALNY, APLD, APP, ARES, AU, AWI, AXON, BA, BANF, BBW, BILL, BLBD, CELH, CHCI, CHDN, CMCL, CNX
- **Evidence:** ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d); ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALNY TARGET 2024-10-16 -> STOP 2026-02-12 (9d); ALGN TARGET 2017-09-06 -> STOP 2020-03-18 (0d); APLD TARGET 2023-09-28 -> STOP 2023-10-09 (0d)

## 5. `false_start_2022_2023` (41 sym / 42 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILL, CB, CCL, CGC, COIN, DOCN, DXCM, GH, GME, GNRC, HBAN
- **Evidence:** AA 2022 STOP 13d -14.4%; AAMI 2022 STOP 9d -10.3%; ACRS 2023 STOP 8d -14.2%; AFRM 2022 STOP 7d -13.9%; AEHR 2022 STOP 7d -10.8%

## 6. `winner_peak_giveback` (28 sym / 32 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AER, AFRM, AMTX, APLD, ASM, AVAV, CLF, CLS, DOCU, DRS, FSLR, HCI, JMIA, KTOS, LEU, LUGDF, MOD, PAYC, PRI, REAL
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AMTX peak~37% -> exit +20.0% (giveback~17pp, 42d, TARGET); APLD peak~33% -> exit +21.2% (giveback~12pp, 19d, GAP_UP); ASM peak~38% -> exit +20.0% (giveback~18pp, 19d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (62 sym / 723 trades) — direction: expand, confidence: medium, 51.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (723 trades, 51%, high) vs target_contract_approach_fail → contract (408 trades, 9%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 723/1416 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 408/4502 trades (9%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAMI, AAON, AAPL, ABM, ABNB, ABR, ABT, ABUS, ACA, ACLS, ACM, ACN, ACRS, ACU, ADI, ADM, ADMA, ADNT
- **Evidence:** [A expand] AA +11% in 15d after TARGET; ABNB +10% in 15d after TARGET; ADMA +17% in 15d after TARGET; ADPT +15% in 15d after TARGET; ADNT +5% in 15d after TARGET; ACLS +5% in 15d after TARGET | [B contract] ADMA reached 65% of target then STOP; ADMA reached 56% of target then STOP; ADPT reached 79% of target then STOP; ABR reached 60% of target then STOP; ABR reached 51% of target then STOP; ACA reached 60% of target then STOP

## 2. `stop_pct_tension_expand_vs_contract` (70 sym / 434 trades) — direction: expand, confidence: medium, 35.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (434 trades, 35%, high) vs stop_contract_dead_losers → contract (193 trades, 16%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 434/1232 STOP exits (35%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 193/1232 STOPs (16%) never expanded (MFE<2%) and 326 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ADI, ADSK, AEE, AEHR, AFRM, AGO, AGX, AI, AIG, AIZ
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ABR STOP 2010-08-31 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ACLS STOP 2022-07-01 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; ACRS STOP 2023-10-25 then back above entry/15d | [B contract] ACLS MFE~1.3% STOP; AAMI MFE~1.6% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AEHR MFE~0.9% STOP; AEHR MFE~0.9% STOP

## 3. `target_contract_slow_hold` (273 sym / 350 trades) — direction: contract, confidence: high, 24.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 350/1416 TARGET exits (25%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AAL, AAON, ABT, ACGL, ACN, ACU, ADBE, ADI, ADP, AEIS, AER, AGM, AIG, AIT, AIZ, AJG, ALGN, ALL, ALLE
- **Evidence:** A TARGET 256d +20.0% (~0.08%/d); ABT TARGET 210d +20.0% (~0.10%/d); ACU TARGET 217d +20.0% (~0.09%/d); AAON TARGET 147d +20.0% (~0.14%/d); AAL TARGET 196d +20.0% (~0.10%/d); AGM TARGET 181d +20.0% (~0.11%/d)

## 4. `band_tighten_weak_fill` (125 sym / 139 trades) — direction: tighten, confidence: low, 3.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 139/4502 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANNX, APP, ARES, AVGO, AYI, B, BA, BAC, BAP, BBW, BEP, BLBD
- **Evidence:** ACLS MFE~1.3% STOP 3d; AAMI MFE~1.6% STOP 9d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AEHR MFE~0.9% STOP 4d; AEHR MFE~0.9% STOP 7d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
