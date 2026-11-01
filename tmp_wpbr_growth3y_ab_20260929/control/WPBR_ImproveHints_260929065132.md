# WPBR Improve Hints — stamp `260929065132`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (890 sym / 2772 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** AA TARGET 103d +22.0% (~0.21%/d) 2021-12-22; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12; ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; AAP TARGET 140d +22.0% (~0.16%/d) 2013-10-25; AAP TARGET 279d +22.0% (~0.08%/d) 2015-08-13

## 2. `fat_stops` (860 sym / 2669 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACAD, ACLS, ACM, ACRS, ACU, ADBE, ADI

## 3. `early_run_long_tail` (543 sym / 843 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAMI, AAON, AAPL, ABBNY, ABCB, ABR, ABT, ACAD, ACLS, ACU, ADBE, ADMA, ADSK, AEE, AEG, AEIS, AEM, AER, AES, AGCO
- **Evidence:** AAMI +10% by day 15 then held 92d exit +22.0% (TARGET); ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ACAD +10% by day 12 then held 107d exit +22.0% (TARGET); ACLS +10% by day 6 then held 84d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (330 sym / 418 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAL, ABBNY, ABG, ACAD, ACLS, ACM, ADMA, AEHR, AEP, AES, AGCO, AI, AIT, AKAM, ALB, ALDX, ALEC, ALFVY, ALNT
- **Evidence:** AA TARGET 2022-02-09 -> STOP 2022-07-05 (8d); ABBNY TARGET 2019-12-19 -> STOP 2020-03-09 (7d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d); ACAD TARGET 2020-04-14 -> STOP 2020-07-21 (6d); AAL TARGET 2026-06-30 -> STOP 2026-07-17 (7d)

## 5. `false_start_2022_2023` (248 sym / 292 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, ABM, ACLS, ACRS, ACU, ADNT, ADPT, ADSK, AEE, AEHR, AES, AGCO, AGYS, AHT, AJG, ALB, AMRC, ANAB, ANDE, ANF
- **Evidence:** AA 2022 STOP 8d -16.2%; ACRS 2023 STOP 8d -15.2%; ACLS 2022 STOP 2d -11.5%; ADNT 2022 STOP 14d -9.7%; ADPT 2022 STOP 11d -19.8%

## 6. `winner_peak_giveback` (133 sym / 168 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AAON, ACAD, ACRS, ADMA, ADPT, AEIS, AFRM, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMN, AOSL, APPS, ASM, AVAV, AXON, BBY
- **Evidence:** ACAD peak~52% -> exit +38.8% (giveback~13pp, 70d, GAP_UP); ACAD peak~36% -> exit +22.0% (giveback~14pp, 71d, TARGET); ACRS peak~34% -> exit +22.0% (giveback~12pp, 29d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 24d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 113d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (46 sym / 3236 trades) — direction: mixed, confidence: medium, 48.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (3236 trades, 49%, high) vs target_contract_slow_hold → contract (2772 trades, 42%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 3236/6636 TARGET exits (49%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 2772/6636 TARGET exits (42%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +11% in 15d after TARGET; AA +5% in 15d after TARGET; AA +10% in 15d after TARGET; AA +10% in 15d after TARGET; AA +9% in 15d after TARGET; AA +12% in 15d after TARGET | [B contract] AA TARGET 103d +22.0% (~0.21%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 164d +22.0% (~0.13%/d); AAP TARGET 140d +22.0% (~0.16%/d); AAP TARGET 279d +22.0% (~0.08%/d); AAP TARGET 324d +22.0% (~0.07%/d)

## 2. `stop_pct_tension_expand_vs_contract` (49 sym / 1961 trades) — direction: mixed, confidence: medium, 25.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (1961 trades, 25%, high) vs stop_contract_dead_losers → contract (1698 trades, 22%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1961/7858 STOP exits (25%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 1698/7858 STOPs (22%) never expanded (MFE<2%) and 2669 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAMI, AAON, AAP, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN
- **Evidence:** [A expand] AA STOP 2018-12-21 then back above entry/15d; AA STOP 2021-03-23 then back above entry/15d; AA STOP 2026-07-20 then back above entry/15d; ABNB STOP 2026-06-11 then back above entry/15d; ACA STOP 2022-09-23 then back above entry/15d; AAP STOP 2026-03-19 then back above entry/15d | [B contract] AA MFE~1.7% STOP; AA MFE~1.1% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP; ACA MFE~0.0% STOP; AAP MFE~0.4% STOP

## 3. `target_contract_approach_fail` (867 sym / 1887 trades) — direction: contract, confidence: medium, 10.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 1887/17430 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABT, ABUS, ACAD, ACLS, ACM, ACN, ACRS, ADBE, ADI, ADMA
- **Evidence:** AA reached 52% of target then STOP; AA reached 68% of target then STOP; AAP reached 61% of target then STOP; AAP reached 85% of target then STOP; AAP reached 66% of target then STOP; AAP reached 89% of target then STOP

## 4. `band_tighten_weak_fill` (637 sym / 1111 trades) — direction: tighten, confidence: low, 6.4% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1111/17430 trades (6%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AA, AAL, AAON, AAT, ABG, ABM, ABR, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADM, ADMA, ADNT, ADP, ADSK, AEE
- **Evidence:** AA MFE~1.1% STOP 8d; AA MFE~1.1% STOP 8d; AA MFE~0.1% STOP 4d; ABUS MFE~0.7% STOP 15d; AAT MFE~1.7% STOP 6d; AAT MFE~2.2% STOP 14d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
