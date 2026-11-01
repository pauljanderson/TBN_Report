# WPBR Improve Hints — stamp `261001161455`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (796 sym / 2184 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACGL, ACLS, ACM, ACN
- **Evidence:** AA TARGET 103d +22.0% (~0.21%/d) 2021-12-22; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12; ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; AAMI TARGET 124d +22.0% (~0.18%/d) 2021-04-14; AAMI TARGET 105d +22.0% (~0.21%/d) 2021-08-25

## 2. `fat_stops` (739 sym / 1766 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, ABBV, ABCB, ABG, ABR, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADBE, ADI, ADNT, ADP

## 3. `early_run_long_tail` (415 sym / 592 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAON, AAPL, ABBNY, ABCB, ABR, ABT, ACLS, ACU, ADBE, ADSK, AEIS, AEM, AER, AES, AGCO, AGI, AGO, AGX, AGYS, AIR
- **Evidence:** ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); ACLS +10% by day 6 then held 84d exit +22.0% (TARGET); AEM +10% by day 7 then held 109d exit +22.0% (TARGET); ABT +10% by day 18 then held 484d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (234 sym / 285 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, ABG, ACAD, ACLS, ACM, ACN, ADMA, AEHR, AEP, AES, ALB, ALNT, ALNY, AME, AMKR, ANDE, AOSL, APP, APPS, ARES
- **Evidence:** AA TARGET 2022-02-09 -> STOP 2022-07-05 (8d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d); ADMA TARGET 2025-03-19 -> STOP 2025-04-04 (7d); ACLS TARGET 2015-05-11 -> STOP 2015-09-18 (2d); ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d)

## 5. `false_start_2022_2023` (188 sym / 218 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, ABM, ACLS, ACRS, ACU, ADNT, AEE, AEHR, AES, AGCO, AGYS, AJG, AKR, ALB, ALSN, ANDE, ANF, AOSL, APA, APAM
- **Evidence:** AA 2022 STOP 8d -16.2%; ACRS 2023 STOP 5d -13.1%; ABM 2022 STOP 14d -11.4%; ADNT 2022 STOP 14d -9.7%; ACLS 2022 STOP 2d -11.5%

## 6. `winner_peak_giveback` (86 sym / 105 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AAON, ADMA, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMN, AOSL, APPS, ASM, AVAV, BLDR, CELH, CLF, CLS, CORT, CVCO, DRS
- **Evidence:** ADMA peak~47% -> exit +33.3% (giveback~13pp, 51d, GAP_UP); AAON peak~37% -> exit +23.2% (giveback~14pp, 67d, GAP_UP); ALDX peak~45% -> exit +22.0% (giveback~23pp, 50d, TARGET); AGYS peak~33% -> exit +22.0% (giveback~11pp, 42d, TARGET); AGX peak~42% -> exit +23.8% (giveback~18pp, 37d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (49 sym / 2184 trades) — direction: mixed, confidence: medium, 46.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (2144 trades, 46%, high) vs target_contract_slow_hold → contract (2184 trades, 47%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 2144/4664 TARGET exits (46%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 2184/4664 TARGET exits (47%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +10% in 15d after TARGET; AA +9% in 15d after TARGET; AA +19% in 15d after TARGET; ABNB +8% in 15d after TARGET; ACA +5% in 15d after TARGET; ACA +8% in 15d after TARGET | [B contract] AA TARGET 103d +22.0% (~0.21%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 164d +22.0% (~0.13%/d); AAMI TARGET 124d +22.0% (~0.18%/d); AAMI TARGET 105d +22.0% (~0.21%/d); ABR TARGET 398d +22.0% (~0.06%/d)

## 2. `stop_pct_tension_expand_vs_contract` (52 sym / 1332 trades) — direction: mixed, confidence: medium, 24.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (1332 trades, 24%, high) vs stop_contract_dead_losers → contract (1198 trades, 22%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1332/5528 STOP exits (24%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 1198/5528 STOPs (22%) never expanded (MFE<2%) and 1766 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAMI, AAON, AAPL, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADI
- **Evidence:** [A expand] AA STOP 2018-12-21 then back above entry/15d; AA STOP 2026-07-20 then back above entry/15d; ABNB STOP 2026-06-11 then back above entry/15d; ACA STOP 2022-09-23 then back above entry/15d; AAMI STOP 2026-02-05 then back above entry/15d; ABR STOP 2020-02-28 then back above entry/15d | [B contract] AA MFE~1.1% STOP; AA MFE~1.1% STOP; ACA MFE~0.0% STOP; ABR MFE~1.4% STOP; ABR MFE~0.2% STOP; ABUS MFE~0.2% STOP

## 3. `target_contract_approach_fail` (734 sym / 1290 trades) — direction: contract, confidence: medium, 10.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 1290/12278 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABT, ABUS, ACLS, ACM, ACN, ACU, ADI, ADNT, ADP, ADSK, AEG, AEHR
- **Evidence:** ABUS reached 59% of target then STOP; ABUS reached 66% of target then STOP; ABUS reached 64% of target then STOP; ABBNY reached 86% of target then STOP; ABBNY reached 55% of target then STOP; AAP reached 61% of target then STOP

## 4. `band_tighten_weak_fill` (511 sym / 769 trades) — direction: tighten, confidence: low, 6.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 769/12278 trades (6%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AA, AAON, ABG, ABM, ABR, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADMA, ADNT, ADP, ADSK, AEE, AEHR, AEM, AES, AFG
- **Evidence:** AA MFE~1.1% STOP 8d; AA MFE~1.1% STOP 8d; ABR MFE~0.2% STOP 14d; ACRS MFE~1.1% STOP 5d; ABM MFE~1.2% STOP 14d; ACAD MFE~0.9% STOP 3d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
