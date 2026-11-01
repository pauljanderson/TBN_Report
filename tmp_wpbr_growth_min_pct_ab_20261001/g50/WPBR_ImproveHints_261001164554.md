# WPBR Improve Hints — stamp `261001164554`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (601 sym / 1233 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABR, ABT, ACA, ACGL, ACLS, ACM, ACN, ACU, ADBE, ADI
- **Evidence:** ABBV TARGET 206d +22.0% (~0.11%/d) 2024-10-31; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12; ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; ABBNY TARGET 234d +22.0% (~0.09%/d) 2024-12-09; A TARGET 118d +22.0% (~0.19%/d) 2013-12-17

## 2. `fat_stops` (557 sym / 1158 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, ABG, ABR, ABUS, ACAD, ACLS, ACRS, ACU, ADBE, ADNT, AEHR, AEIS, AEM, AEO, AES

## 3. `early_run_long_tail` (264 sym / 341 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAON, ABR, ACM, ACU, ADBE, ADSK, AEIS, AEM, AER, AGI, AGX, AGYS, ALFVY, ALGN, ALSN, AMAT, AMD, AMGN, AMKR, AMN
- **Evidence:** ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ACU +10% by day 8 then held 217d exit +22.0% (TARGET); ACM +10% by day 22 then held 257d exit +24.6% (GAP_UP); AEM +10% by day 7 then held 109d exit +22.0% (TARGET); AGI +10% by day 24 then held 101d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (165 sym / 194 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, ACA, ACAD, ACLS, ADMA, AEHR, ALB, ALNT, ALNY, AME, AMKR, ANDE, APP, APPS, ARES, ARW, AVAV, AVY, AWI, AX
- **Evidence:** AA TARGET 2022-02-09 -> STOP 2026-04-17 (9d); ACA TARGET 2024-02-12 -> STOP 2024-08-02 (10d); ACLS TARGET 2015-05-11 -> STOP 2015-09-18 (2d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d); ADMA TARGET 2025-03-19 -> STOP 2025-04-04 (7d)

## 5. `false_start_2022_2023` (110 sym / 133 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** ACLS, ADNT, AEHR, AES, AGCO, AGYS, AJG, ALB, ANDE, AOSL, APO, ARES, ARW, AXON, BBWI, BELFB, BILI, BIO, BLK, CCJ
- **Evidence:** ACLS 2022 STOP 2d -11.5%; ADNT 2022 STOP 14d -9.7%; AEHR 2022 STOP 7d -11.8%; AEHR 2022 STOP 2d -13.8%; AEHR 2022 STOP 5d -14.3%

## 6. `winner_peak_giveback` (57 sym / 69 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ADMA, AGX, AGYS, ALBY, ALGN, AMKR, AMN, ANIP, AOSL, APPS, ASM, AVAV, CELH, CLF, CLS, CORT, DRS, ENVA, ESOA, ESP
- **Evidence:** ADMA peak~47% -> exit +33.3% (giveback~13pp, 51d, GAP_UP); AGYS peak~33% -> exit +22.0% (giveback~11pp, 42d, TARGET); AMKR peak~33% -> exit +22.0% (giveback~11pp, 130d, TARGET); AGX peak~42% -> exit +23.8% (giveback~18pp, 37d, GAP_UP); ALBY peak~34% -> exit +22.1% (giveback~12pp, 41d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (53 sym / 1365 trades) — direction: mixed, confidence: medium, 48.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (1365 trades, 48%, high) vs target_contract_slow_hold → contract (1233 trades, 44%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1365/2815 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 1233/2815 TARGET exits (44%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] AA +19% in 15d after TARGET; ACA +5% in 15d after TARGET; ACA +8% in 15d after TARGET; ACA +6% in 15d after TARGET; A +11% in 15d after TARGET; ABR +6% in 15d after TARGET | [B contract] ABBV TARGET 206d +22.0% (~0.11%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 164d +22.0% (~0.13%/d); ABBNY TARGET 234d +22.0% (~0.09%/d); A TARGET 118d +22.0% (~0.19%/d); A TARGET 102d +22.0% (~0.22%/d)

## 2. `stop_pct_tension_expand_vs_contract` (53 sym / 873 trades) — direction: mixed, confidence: medium, 25.8% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (873 trades, 26%, high) vs stop_contract_dead_losers → contract (744 trades, 22%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 873/3390 STOP exits (26%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 744/3390 STOPs (22%) never expanded (MFE<2%) and 1158 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AAL, AAMI, AAON, ABCB, ABG, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACU, ADI, ADM, ADMA, ADNT, ADSK, AEHR, AEIS, AEM
- **Evidence:** [A expand] AAMI STOP 2026-02-05 then back above entry/15d; ACA STOP 2022-09-23 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ABR STOP 2020-02-28 then back above entry/15d; ABUS STOP 2022-12-28 then back above entry/15d; ACLS STOP 2017-07-03 then back above entry/15d | [B contract] ACA MFE~0.0% STOP; ABR MFE~1.4% STOP; ABR MFE~0.2% STOP; ABUS MFE~0.2% STOP; ACLS MFE~1.8% STOP; ACLS MFE~0.0% STOP

## 3. `target_contract_approach_fail` (502 sym / 760 trades) — direction: contract, confidence: medium, 10.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 760/7440 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAP, AAPL, ABBNY, ABCB, ABG, ABM, ABUS, ACLS, ACM, ACN, ADI, ADNT, ADSK, AEG, AEHR, AES, AFL, AGI, AGM, AGO
- **Evidence:** ABBNY reached 55% of target then STOP; ABUS reached 66% of target then STOP; ABUS reached 64% of target then STOP; ABM reached 59% of target then STOP; ACLS reached 64% of target then STOP; ACLS reached 53% of target then STOP

## 4. `band_tighten_weak_fill` (342 sym / 488 trades) — direction: tighten, confidence: low, 6.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 488/7440 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAON, ABR, ACAD, ACLS, ACU, ADMA, ADNT, ADSK, AEHR, AEM, AES, AGM, AGYS, AHCO, AIT, AJG, AKAM, ALB, ALFVY, ALGN
- **Evidence:** ABR MFE~0.2% STOP 14d; ACLS MFE~1.8% STOP 2d; ACLS MFE~2.3% STOP 14d; ACLS MFE~0.0% STOP 2d; ACU MFE~2.1% STOP 11d; ADNT MFE~1.8% STOP 14d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
