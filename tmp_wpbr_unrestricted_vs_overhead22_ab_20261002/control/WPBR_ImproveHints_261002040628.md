# WPBR Improve Hints — stamp `261002040628`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (931 sym / 3389 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** AA TARGET 103d +22.0% (~0.21%/d) 2021-12-22; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12; ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; AAMI TARGET 124d +22.0% (~0.18%/d) 2021-04-14; AAMI TARGET 105d +22.0% (~0.21%/d) 2021-08-25

## 2. `fat_stops` (902 sym / 3199 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACRS, ACU

## 3. `early_run_long_tail` (624 sym / 1017 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAL, AAMI, AAON, AAPL, ABBNY, ABCB, ABR, ABT, ACAD, ACLS, ACU, ADBE, ADI, ADMA, ADSK, AEE, AEG, AEIS, AEM, AER
- **Evidence:** AAMI +10% by day 15 then held 92d exit +22.0% (TARGET); ABBNY +10% by day 21 then held 143d exit +22.7% (GAP_UP); ABR +10% by day 17 then held 227d exit +22.0% (TARGET); ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ABT +10% by day 18 then held 484d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (376 sym / 495 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAL, ABBNY, ABG, ACAD, ACLS, ACM, ADMA, AEHR, AEM, AEP, AES, AFG, AGCO, AI, AKAM, ALB, ALDX, ALEC, ALFVY
- **Evidence:** AA TARGET 2022-02-09 -> STOP 2022-07-05 (8d); ABBNY TARGET 2019-12-19 -> STOP 2020-03-09 (7d); ACM TARGET 2020-01-10 -> STOP 2020-03-09 (6d); ACAD TARGET 2011-04-11 -> STOP 2011-05-23 (4d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d)

## 5. `false_start_2022_2023` (260 sym / 314 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, ABM, ACLS, ACRS, ACU, ADNT, ADPT, ADSK, AEE, AEHR, AES, AFRM, AGCO, AGYS, AHT, AI, AJG, ALB, AMRC, ANAB
- **Evidence:** AA 2022 STOP 8d -16.2%; ABM 2022 STOP 14d -11.4%; ACRS 2023 STOP 8d -15.2%; ADNT 2022 STOP 14d -9.7%; ADPT 2022 STOP 11d -19.8%

## 6. `winner_peak_giveback` (161 sym / 208 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AAON, ABUS, ACAD, ACRS, ADMA, ADPT, AEIS, AFRM, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMN, AMTX, ANAB, AOSL, APLD, APPS
- **Evidence:** ABUS peak~32% -> exit +22.0% (giveback~10pp, 23d, TARGET); ACRS peak~34% -> exit +22.0% (giveback~12pp, 29d, TARGET); ACAD peak~52% -> exit +38.8% (giveback~13pp, 70d, GAP_UP); ACAD peak~36% -> exit +22.0% (giveback~14pp, 71d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 24d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (46 sym / 3848 trades) — direction: mixed, confidence: medium, 48.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (3848 trades, 48%, high) vs target_contract_slow_hold → contract (3389 trades, 42%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 3848/7995 TARGET exits (48%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 3389/7995 TARGET exits (42%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL
- **Evidence:** [A expand] AA +11% in 15d after TARGET; AA +5% in 15d after TARGET; AA +10% in 15d after TARGET; AA +10% in 15d after TARGET; AA +9% in 15d after TARGET; AA +12% in 15d after TARGET | [B contract] AA TARGET 103d +22.0% (~0.21%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 164d +22.0% (~0.13%/d); AAMI TARGET 124d +22.0% (~0.18%/d); AAMI TARGET 105d +22.0% (~0.21%/d); AAMI TARGET 166d +22.0% (~0.13%/d)

## 2. `stop_pct_tension_expand_vs_contract` (45 sym / 2317 trades) — direction: mixed, confidence: medium, 24.9% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (2317 trades, 25%, high) vs stop_contract_dead_losers → contract (1984 trades, 21%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 2317/9307 STOP exits (25%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 1984/9307 STOPs (21%) never expanded (MFE<2%) and 3199 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACLS
- **Evidence:** [A expand] AA STOP 2018-12-21 then back above entry/15d; AA STOP 2021-03-23 then back above entry/15d; AA STOP 2026-07-20 then back above entry/15d; ABNB STOP 2021-12-16 then back above entry/15d; ABNB STOP 2022-01-24 then back above entry/15d; ABNB STOP 2026-06-11 then back above entry/15d | [B contract] AA MFE~1.7% STOP; AA MFE~1.1% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP; ACA MFE~0.0% STOP; AAMI MFE~1.5% STOP

## 3. `target_contract_approach_fail` (930 sym / 2283 trades) — direction: contract, confidence: medium, 11.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 2283/20670 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN
- **Evidence:** AA reached 52% of target then STOP; AA reached 68% of target then STOP; ABNB reached 53% of target then STOP; ACA reached 52% of target then STOP; ACA reached 70% of target then STOP; AAMI reached 69% of target then STOP

## 4. `band_tighten_weak_fill` (692 sym / 1295 trades) — direction: tighten, confidence: low, 6.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1295/20670 trades (6%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAON, AAP, AAT, ABG, ABM, ABR, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADM, ADMA, ADNT, ADP
- **Evidence:** AA MFE~1.1% STOP 8d; AA MFE~1.1% STOP 8d; AA MFE~0.1% STOP 4d; ABUS MFE~0.7% STOP 15d; ABR MFE~0.2% STOP 14d; ABM MFE~1.2% STOP 14d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
