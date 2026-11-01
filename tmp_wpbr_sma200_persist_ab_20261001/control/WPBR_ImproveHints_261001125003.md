# WPBR Improve Hints — stamp `261001125003`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (798 sym / 2121 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AA, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACGL, ACLS, ACM, ACN, ACU
- **Evidence:** AA TARGET 108d +22.0% (~0.20%/d) 2017-12-29; AA TARGET 103d +22.0% (~0.21%/d) 2021-12-22; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12; ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; AAT TARGET 183d +22.0% (~0.12%/d) 2016-07-21

## 2. `fat_stops` (748 sym / 1808 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, ABBV, ABCB, ABG, ABR, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADBE, ADI, ADNT, ADP

## 3. `early_run_long_tail` (423 sym / 597 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AA, AAON, AAPL, ABBNY, ABCB, ABR, ABT, ACLS, ACU, ADBE, ADM, ADSK, AEE, AEIS, AEM, AER, AGCO, AGI, AGO, AGYS
- **Evidence:** AA +10% by day 22 then held 108d exit +22.0% (TARGET); ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); ABT +10% by day 18 then held 484d exit +22.0% (TARGET); ACLS +10% by day 6 then held 84d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (231 sym / 277 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, ABG, ACAD, ACLS, ACM, ACN, ADMA, AEHR, AEP, AES, ALB, ALNT, ALNY, AMAT, AME, AMKR, ANDE, AOSL, APP, APPS
- **Evidence:** AA TARGET 2022-02-09 -> STOP 2022-07-05 (8d); ABG TARGET 2016-02-23 -> STOP 2016-08-04 (3d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d); ADMA TARGET 2025-03-19 -> STOP 2025-04-04 (7d); ACLS TARGET 2015-05-11 -> STOP 2015-09-18 (2d)

## 5. `false_start_2022_2023` (192 sym / 225 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, ABM, ACLS, ACRS, ACU, ADNT, ADSK, AEE, AEHR, AES, AGCO, AGYS, AJG, AKR, ALB, ANDE, ANF, AOSL, APA, APAM
- **Evidence:** AA 2022 STOP 8d -16.2%; ABM 2022 STOP 14d -11.4%; ACRS 2023 STOP 5d -13.1%; ADNT 2022 STOP 14d -9.7%; ACLS 2022 STOP 2d -11.5%

## 6. `winner_peak_giveback` (91 sym / 110 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AAON, ADMA, ADPT, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMN, AOSL, APPS, ASM, AVAV, BBY, BLDR, CELH, CLF, CLS, CMC
- **Evidence:** ADMA peak~47% -> exit +33.3% (giveback~13pp, 51d, GAP_UP); ADPT peak~38% -> exit +22.0% (giveback~16pp, 65d, TARGET); AAON peak~37% -> exit +23.2% (giveback~14pp, 67d, GAP_UP); ALDX peak~45% -> exit +22.0% (giveback~23pp, 50d, TARGET); AGX peak~39% -> exit +23.9% (giveback~15pp, 169d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (51 sym / 2187 trades) — direction: mixed, confidence: medium, 46.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (2187 trades, 47%, high) vs target_contract_slow_hold → contract (2121 trades, 45%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 2187/4673 TARGET exits (47%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 2121/4673 TARGET exits (45%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +10% in 15d after TARGET; AA +6% in 15d after TARGET; AA +9% in 15d after TARGET; AA +19% in 15d after TARGET; ABNB +8% in 15d after TARGET; ACA +5% in 15d after TARGET | [B contract] AA TARGET 108d +22.0% (~0.20%/d); AA TARGET 103d +22.0% (~0.21%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 164d +22.0% (~0.13%/d); AAT TARGET 183d +22.0% (~0.12%/d); AAT TARGET 165d +22.0% (~0.13%/d)

## 2. `stop_pct_tension_expand_vs_contract` (53 sym / 1368 trades) — direction: mixed, confidence: medium, 23.7% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (1368 trades, 24%, high) vs stop_contract_dead_losers → contract (1245 trades, 22%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1368/5762 STOP exits (24%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 1245/5762 STOPs (22%) never expanded (MFE<2%) and 1808 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAMI, AAON, AAP, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AA STOP 2018-12-21 then back above entry/15d; AA STOP 2026-07-20 then back above entry/15d; ABNB STOP 2026-06-11 then back above entry/15d; ACA STOP 2022-09-23 then back above entry/15d; AAMI STOP 2026-02-05 then back above entry/15d; ABUS STOP 2013-11-08 then back above entry/15d | [B contract] AA MFE~1.1% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP; ACA MFE~0.0% STOP; AAT MFE~0.1% STOP; ABUS MFE~0.0% STOP

## 3. `target_contract_approach_fail` (761 sym / 1373 trades) — direction: contract, confidence: medium, 10.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 1373/12599 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABT, ABUS, ACLS, ACM, ACN, ADI, ADNT, ADP, ADSK, AEG, AEHR
- **Evidence:** AA reached 68% of target then STOP; ABUS reached 59% of target then STOP; ABUS reached 66% of target then STOP; ABUS reached 64% of target then STOP; AAP reached 61% of target then STOP; AAP reached 89% of target then STOP

## 4. `band_tighten_weak_fill` (518 sym / 793 trades) — direction: tighten, confidence: low, 6.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 793/12599 trades (6%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AA, AAL, AAON, AAT, ABG, ABM, ABR, ACAD, ACLS, ACN, ACRS, ACU, ADMA, ADNT, ADP, ADSK, AEE, AEHR, AEM, AES
- **Evidence:** AA MFE~1.1% STOP 8d; AA MFE~1.1% STOP 8d; AA MFE~0.1% STOP 4d; AAT MFE~0.1% STOP 9d; ABM MFE~1.2% STOP 14d; ABG MFE~0.0% STOP 3d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
