# WPBR Improve Hints — stamp `261001204554`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (442 sym / 668 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AAL, AAPL, ABBNY, ABG, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADM, ADP, ADSK, AEE, AEIS, AEM, AEP, AER, AFL
- **Evidence:** ABT TARGET 241d +22.0% (~0.09%/d) 2015-06-18; ABBNY TARGET 234d +22.0% (~0.09%/d) 2024-12-09; ADM TARGET 153d +22.0% (~0.14%/d) 2024-07-09; ACU TARGET 217d +22.0% (~0.10%/d) 2014-12-30; ACM TARGET 281d +22.0% (~0.08%/d) 2024-10-16

## 2. `fat_stops` (286 sym / 363 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABUS, ACLS, ACN, ACRS, ACU, AEHR, AEIS, AGX, AKAM, ALB, ALGN, ALNT, ALNY, AMD, AMKR, AMN, AMT, AMTX

## 3. `early_run_long_tail` (145 sym / 157 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ABCB, ACM, ACU, ADSK, AEM, AGYS, ALLE, AMAT, AMGN, AMP, ANET, AON, APG, APH, ARES, AVGO, AWI, AX, BA, BAESY
- **Evidence:** ACU +10% by day 8 then held 217d exit +22.0% (TARGET); ACM +10% by day 22 then held 257d exit +24.6% (GAP_UP); AEM +10% by day 7 then held 109d exit +22.0% (TARGET); ADSK +10% by day 14 then held 157d exit +22.0% (TARGET); AGYS +10% by day 7 then held 104d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (46 sym / 47 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, AEP, ALNY, APP, ARES, AU, AWI, AXON, BA, BLBD, BRK.B, CELH, DXCM, DY, ENPH, ENS, EPAM, FIX, FSI, GLPI
- **Evidence:** ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d); AEP TARGET 2020-01-24 -> STOP 2020-03-20 (4d); ALNY TARGET 2024-10-16 -> STOP 2026-02-12 (9d); APP TARGET 2025-12-02 -> STOP 2026-01-30 (9d); ARES TARGET 2020-02-06 -> STOP 2020-03-12 (1d)

## 5. `false_start_2022_2023` (22 sym / 23 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AEHR, ALB, DXCM, GME, GNRC, HBAN, HROW, INFY, INOD, MATX, MGA, MPC, NVDA, ORLY, PYPL, ROKU, SHOP, TRMB, TWLO
- **Evidence:** AA 2022 STOP 13d -15.4%; AEHR 2022 STOP 7d -11.8%; AEHR 2022 STOP 2d -13.8%; ALB 2022 STOP 1d -11.1%; DXCM 2022 STOP 15d -14.6%

## 6. `winner_peak_giveback` (17 sym / 19 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ASM, AVAV, CLF, CLS, FICO, HIMS, KTOS, LEU, ODC, PLUS, SRPT, TATT, TKO, UTHR, WAT, WLDN
- **Evidence:** AGX peak~42% -> exit +23.8% (giveback~18pp, 37d, GAP_UP); ASM peak~38% -> exit +22.0% (giveback~16pp, 19d, TARGET); AVAV peak~34% -> exit +22.0% (giveback~12pp, 23d, TARGET); CLF peak~37% -> exit +24.6% (giveback~13pp, 28d, GAP_UP); CLS peak~35% -> exit +22.0% (giveback~13pp, 26d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (61 sym / 668 trades) — direction: contract, confidence: medium, 51.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean contract): target_expand_post_exit → expand (527 trades, 41%, high) vs target_contract_slow_hold → contract (668 trades, 52%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 527/1291 TARGET exits (41%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 668/1291 TARGET exits (52%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AA, AAL, AAPL, ABBNY, ABG, ABT, ABUS, ACGL, ACM, ACN, ACU, ADBE, ADI, ADM, ADMA, ADP, ADSK, AEE, AEIS, AEM
- **Evidence:** [A expand] AA +9% in 15d after TARGET; ABUS +51% in 15d after TARGET; ADMA +15% in 15d after TARGET; ACM +7% in 15d after TARGET; AEM +7% in 15d after TARGET; AAL +15% in 15d after TARGET | [B contract] ABT TARGET 241d +22.0% (~0.09%/d); ABBNY TARGET 234d +22.0% (~0.09%/d); ADM TARGET 153d +22.0% (~0.14%/d); ACU TARGET 217d +22.0% (~0.10%/d); ACM TARGET 281d +22.0% (~0.08%/d); ADP TARGET 191d +22.0% (~0.12%/d)

## 2. `stop_pct_tension_expand_vs_contract` (69 sym / 285 trades) — direction: expand, confidence: medium, 24.6% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (285 trades, 25%, high) vs stop_contract_dead_losers → contract (139 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 285/1158 STOP exits (25%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 139/1158 STOPs (12%) never expanded (MFE<2%) and 363 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAON, ABT, ACA, ACLS, ACN, AEE, AEHR, AEP, AIZ, AJG, AKAM, ALB, ALBY, ALGN, ALNT, ALNY, ALSN, AMH
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ABT STOP 2020-03-20 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; ACLS STOP 2022-07-01 then back above entry/15d | [B contract] ACLS MFE~1.3% STOP; AEHR MFE~0.9% STOP; AEHR MFE~0.9% STOP; AEE MFE~0.9% STOP; ALB MFE~1.6% STOP; AEP MFE~1.6% STOP

## 3. `target_contract_approach_fail` (287 sym / 340 trades) — direction: contract, confidence: medium, 11.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 340/2947 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** ABM, ABT, ABUS, ACA, ACLS, ACM, ACN, ADI, AFL, AGO, ALB, ALNT, ALSN, AMAT, AMD, AMH, AMKR, AMP, AMTX, AMZN
- **Evidence:** ACA reached 55% of target then STOP; ABT reached 69% of target then STOP; ABT reached 92% of target then STOP; ABUS reached 66% of target then STOP; ABM reached 65% of target then STOP; ACLS reached 75% of target then STOP

## 4. `band_tighten_weak_fill` (65 sym / 69 trades) — direction: tighten, confidence: low, 2.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 69/2947 trades (2%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** ACLS, AEHR, AIZ, ALB, ALNY, AMP, APP, ARES, BA, BAP, BBW, BEP, BLBD, BLDR, BRK.B, CGC, COHR, DRD, DXCM, DY
- **Evidence:** ACLS MFE~1.3% STOP 3d; AEHR MFE~0.9% STOP 4d; AEHR MFE~0.9% STOP 7d; ALB MFE~1.6% STOP 1d; ALNY MFE~0.7% STOP 2d; APP MFE~2.7% STOP 9d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
