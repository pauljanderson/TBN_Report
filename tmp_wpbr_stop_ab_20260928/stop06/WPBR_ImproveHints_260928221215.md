# WPBR Improve Hints — stamp `260928221215`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (864 sym / 2716 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI
- **Evidence:** AAMI TARGET 124d +22.0% (~0.18%/d) 2021-04-14; AAMI TARGET 105d +22.0% (~0.21%/d) 2021-08-25; AAMI TARGET 166d +22.0% (~0.13%/d) 2024-07-23; AAT TARGET 190d +22.0% (~0.12%/d) 2012-08-21; AAT TARGET 114d +22.0% (~0.19%/d) 2019-02-07

## 2. `early_run_long_tail` (582 sym / 934 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAL, AAMI, AAPL, ABBNY, ABCB, ABR, ACGL, ACLS, ACM, ACU, ADBE, ADI, ADMA, ADSK, AEE, AEG, AEIS, AER, AES, AGCO
- **Evidence:** AAMI +10% by day 15 then held 92d exit +22.0% (TARGET); ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); AAL +10% by day 12 then held 85d exit +22.0% (TARGET); ABR +10% by day 13 then held 112d exit +22.0% (TARGET); AAPL +10% by day 10 then held 127d exit +22.0% (TARGET)

## 3. `fat_stops` (543 sym / 1090 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, AAMI, AAON, AAP, ABBV, ABG, ABM, ABR, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADMA, ADNT, ADP, ADPT, ADSK

## 4. `post_target_quick_stop` (551 sym / 885 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAL, AAMI, AAON, AAPL, ABBV, ABCB, ABG, ABNB, ABR, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADI, ADMA, AEG, AEHR, AEM
- **Evidence:** AAMI TARGET 2021-08-25 -> STOP 2022-01-20 (8d); AAON TARGET 2011-04-07 -> STOP 2011-07-28 (8d); AAL TARGET 2010-07-26 -> STOP 2010-11-10 (7d); AAL TARGET 2026-06-30 -> STOP 2026-07-15 (5d); ABNB TARGET 2021-11-05 -> STOP 2021-12-01 (5d)

## 5. `false_start_2022_2023` (470 sym / 633 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, AAT, ABM, ABR, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADI, ADMA, ADNT, ADPT, ADSK, AEE, AEHR, AEIS, AEM, AES
- **Evidence:** AAMI 2022 STOP 8d -8.4%; AAMI 2022 STOP 4d -7.9%; AAT 2022 STOP 15d -7.5%; ABR 2022 STOP 4d -7.3%; ACA 2022 STOP 3d -7.8%

## 6. `winner_peak_giveback` (135 sym / 170 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABUS, ACAD, ADMA, ADPT, AFRM, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMTX, ANAB, AOSL, APLD, APPS, ARGX, ASM, AVAV, AXON
- **Evidence:** ABUS peak~32% -> exit +22.0% (giveback~10pp, 23d, TARGET); ACAD peak~52% -> exit +38.8% (giveback~13pp, 70d, GAP_UP); ACAD peak~36% -> exit +22.0% (giveback~14pp, 71d, TARGET); ADPT peak~38% -> exit +22.0% (giveback~16pp, 65d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 24d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (43 sym / 4334 trades) — direction: expand, confidence: medium, 38.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (4334 trades, 38%, high) vs stop_ok_never_worked → hold (2864 trades, 25%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 4334/11364 STOP exits (38%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 2864/11364 STOPs (25%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AAMI STOP 2019-03-22 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d; AAMI STOP 2022-09-23 then back above entry/15d; AAMI STOP 2026-02-05 then back above entry/15d; AA STOP 2015-08-21 then back above entry/15d; AA STOP 2017-04-18 then back above entry/15d | [B hold] AAMI MFE~1.5% STOP; AAMI MFE~1.6% STOP; AA MFE~1.7% STOP; AA MFE~0.4% STOP; AA MFE~1.1% STOP; AA MFE~0.4% STOP

## 2. `target_pct_tension_expand_vs_contract` (51 sym / 3391 trades) — direction: mixed, confidence: medium, 48.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (3391 trades, 48%, high) vs target_contract_slow_hold → contract (2716 trades, 39%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 3391/7035 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 2716/7035 TARGET exits (39%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +11% in 15d after TARGET; AA +5% in 15d after TARGET; AA +10% in 15d after TARGET; AA +10% in 15d after TARGET; AA +9% in 15d after TARGET; AA +12% in 15d after TARGET | [B contract] AAMI TARGET 124d +22.0% (~0.18%/d); AAMI TARGET 105d +22.0% (~0.21%/d); AAMI TARGET 166d +22.0% (~0.13%/d); AAT TARGET 190d +22.0% (~0.12%/d); AAT TARGET 114d +22.0% (~0.19%/d); AAT TARGET 165d +22.0% (~0.13%/d)

## 3. `band_tighten_weak_fill` (896 sym / 2546 trades) — direction: tighten, confidence: medium, 11.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 2546/22084 trades (12%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN
- **Evidence:** AAMI MFE~2.5% STOP 10d; AAMI MFE~1.6% STOP 8d; AA MFE~1.7% STOP 11d; AA MFE~0.4% STOP 10d; AA MFE~1.1% STOP 6d; AA MFE~0.4% STOP 10d

## 4. `target_contract_approach_fail` (932 sym / 2339 trades) — direction: contract, confidence: medium, 10.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 2339/22084 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, ABBV, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ADBE, ADI
- **Evidence:** AA reached 88% of target then STOP; AA reached 68% of target then STOP; AAP reached 61% of target then STOP; AAP reached 66% of target then STOP; AAP reached 51% of target then STOP; A reached 63% of target then STOP

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
