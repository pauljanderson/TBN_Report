# WPBR Improve Hints — stamp `261001163120`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (743 sym / 1821 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABR, ABT, ACA, ACGL, ACLS, ACM, ACN, ACU, ADBE
- **Evidence:** AAMI TARGET 105d +22.0% (~0.21%/d) 2021-08-25; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12; ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; ABBNY TARGET 111d +22.0% (~0.20%/d) 2024-05-08; ABBV TARGET 206d +22.0% (~0.11%/d) 2024-10-31

## 2. `fat_stops` (681 sym / 1523 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, ABBV, ABCB, ABG, ABR, ABT, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADBE, ADNT, ADP

## 3. `early_run_long_tail` (349 sym / 484 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAON, AAPL, ABBNY, ABR, ACGL, ACLS, ACU, ADBE, ADSK, AEIS, AEM, AER, AES, AGCO, AGI, AGO, AGX, AGYS, AIT, AKR
- **Evidence:** ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ACGL +10% by day 15 then held 268d exit +22.0% (TARGET); ACLS +10% by day 6 then held 84d exit +22.0% (TARGET); AEM +10% by day 7 then held 109d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (213 sym / 253 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, ABG, ACAD, ACLS, ACM, ADMA, AEHR, AEP, AES, ALB, ALNT, ALNY, AME, AMKR, AMN, ANDE, APP, APPS, ARES, ARW
- **Evidence:** AA TARGET 2022-02-09 -> STOP 2026-04-17 (9d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d); ACLS TARGET 2015-05-11 -> STOP 2015-09-18 (2d); ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d); ACM TARGET 2020-01-10 -> STOP 2020-03-09 (6d)

## 5. `false_start_2022_2023` (158 sym / 184 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** ABM, ACLS, ACU, ADNT, AEHR, AES, AGCO, AGYS, AJG, AKR, ALB, AMN, ANDE, ANF, AOSL, APAM, ARE, ARES, ARW, AXON
- **Evidence:** ABM 2022 STOP 14d -11.4%; ADNT 2022 STOP 14d -9.7%; ACLS 2022 STOP 2d -11.5%; AEHR 2022 STOP 7d -11.8%; AEHR 2022 STOP 2d -13.8%

## 6. `winner_peak_giveback` (77 sym / 94 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AAON, ADMA, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMN, AOSL, APPS, ASM, AVAV, BLDR, CELH, CLF, CLS, CORT, CVCO, DRS
- **Evidence:** ADMA peak~47% -> exit +33.3% (giveback~13pp, 51d, GAP_UP); AAON peak~37% -> exit +23.2% (giveback~14pp, 67d, GAP_UP); ALDX peak~45% -> exit +22.0% (giveback~23pp, 50d, TARGET); AGYS peak~33% -> exit +22.0% (giveback~11pp, 42d, TARGET); AGX peak~42% -> exit +23.8% (giveback~18pp, 37d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (49 sym / 1821 trades) — direction: mixed, confidence: medium, 46.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (1812 trades, 46%, high) vs target_contract_slow_hold → contract (1821 trades, 47%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1812/3911 TARGET exits (46%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 1821/3911 TARGET exits (47%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** [A expand] AA +19% in 15d after TARGET; ACA +5% in 15d after TARGET; ACA +8% in 15d after TARGET; ACA +6% in 15d after TARGET; ABBNY +7% in 15d after TARGET; ABR +6% in 15d after TARGET | [B contract] AAMI TARGET 105d +22.0% (~0.21%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 164d +22.0% (~0.13%/d); ABBNY TARGET 111d +22.0% (~0.20%/d); ABBV TARGET 206d +22.0% (~0.11%/d); ABR TARGET 112d +22.0% (~0.20%/d)

## 2. `stop_pct_tension_expand_vs_contract` (51 sym / 1176 trades) — direction: mixed, confidence: medium, 25.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (1176 trades, 25%, high) vs stop_contract_dead_losers → contract (998 trades, 21%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1176/4684 STOP exits (25%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 998/4684 STOPs (21%) never expanded (MFE<2%) and 1523 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAMI, AAON, AAPL, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACU, ADI, ADM, ADMA, ADNT
- **Evidence:** [A expand] AA STOP 2026-07-20 then back above entry/15d; AAMI STOP 2026-02-05 then back above entry/15d; ACA STOP 2022-09-23 then back above entry/15d; ABM STOP 2022-05-12 then back above entry/15d; ABBV STOP 2016-10-28 then back above entry/15d; ABBV STOP 2020-10-15 then back above entry/15d | [B contract] ACA MFE~0.0% STOP; ABM MFE~1.2% STOP; ABBV MFE~0.3% STOP; ABR MFE~1.4% STOP; ABR MFE~0.2% STOP; ABUS MFE~0.2% STOP

## 3. `target_contract_approach_fail` (656 sym / 1089 trades) — direction: contract, confidence: medium, 10.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 1089/10340 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABT, ABUS, ACLS, ACM, ACN, ADI, ADNT, ADP, ADSK, AEG, AEHR, AEIS, AER
- **Evidence:** ABM reached 53% of target then STOP; ABBNY reached 55% of target then STOP; ABBV reached 53% of target then STOP; ABBV reached 50% of target then STOP; ABUS reached 59% of target then STOP; ABUS reached 66% of target then STOP

## 4. `band_tighten_weak_fill` (439 sym / 643 trades) — direction: tighten, confidence: low, 6.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 643/10340 trades (6%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAON, ABG, ABM, ABR, ACAD, ACLS, ACU, ADMA, ADNT, ADSK, AEHR, AEM, AES, AGCO, AGM, AGYS, AHCO, AIT, AJG, AKAM
- **Evidence:** ABM MFE~1.2% STOP 14d; ABR MFE~0.2% STOP 14d; ACAD MFE~0.9% STOP 3d; ACAD MFE~1.5% STOP 10d; ACAD MFE~0.5% STOP 2d; ACAD MFE~2.7% STOP 6d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
