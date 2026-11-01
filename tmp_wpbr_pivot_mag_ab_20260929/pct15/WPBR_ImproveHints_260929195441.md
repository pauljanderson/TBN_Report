# WPBR Improve Hints — stamp `260929195441`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (886 sym / 2355 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** AA TARGET 132d +22.0% (~0.17%/d) 2017-08-08; AA TARGET 103d +22.0% (~0.21%/d) 2021-12-22; ABBV TARGET 136d +22.0% (~0.16%/d) 2014-11-24; ABBV TARGET 206d +22.0% (~0.11%/d) 2024-10-31; ACA TARGET 278d +22.0% (~0.08%/d) 2024-02-12

## 2. `fat_stops` (827 sym / 2814 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACRS

## 3. `early_run_long_tail` (531 sym / 799 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAL, AAMI, AAON, ABCB, ABR, ACAD, ACGL, ACLS, ACU, ADBE, ADMA, ADSK, AEE, AEIS, AEM, AES, AGCO, AGI, AGM, AGO
- **Evidence:** AAMI +10% by day 15 then held 92d exit +22.0% (TARGET); ABR +10% by day 17 then held 227d exit +22.0% (TARGET); ADMA +10% by day 1 then held 113d exit +22.0% (TARGET); ACGL +10% by day 15 then held 268d exit +22.0% (TARGET); ACAD +10% by day 12 then held 107d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (341 sym / 455 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAL, ABG, ABR, ACA, ACAD, ACLS, ADI, ADMA, ADP, AEHR, AEM, AGCO, AI, AKAM, ALB, ALDX, ALEC, ALLE, ALNT
- **Evidence:** AA TARGET 2017-12-28 -> STOP 2018-12-21 (8d); AA TARGET 2022-02-09 -> STOP 2022-07-05 (8d); ACA TARGET 2024-02-12 -> STOP 2024-08-02 (10d); ABR TARGET 2018-06-11 -> STOP 2020-03-17 (4d); ADMA TARGET 2018-02-12 -> STOP 2018-04-02 (6d)

## 5. `false_start_2022_2023` (241 sym / 288 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, ACLS, ACRS, ACU, ADNT, ADPT, ADSK, AEE, AEHR, AES, AFRM, AGCO, AGYS, AHT, AI, ALB, AMRC, ANAB, ANDE, ANF
- **Evidence:** AA 2022 STOP 8d -16.2%; ACRS 2023 STOP 8d -15.2%; ADNT 2022 STOP 14d -9.7%; ADPT 2022 STOP 11d -19.8%; ACLS 2022 STOP 2d -11.5%

## 6. `winner_peak_giveback` (153 sym / 196 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AAON, ABUS, ACAD, ACRS, ADMA, ADPT, AEIS, AFRM, AGM, AGX, AGYS, ALBY, ALDX, ALGN, AMKR, AMN, AMTX, ANAB, AOSL, APLD
- **Evidence:** ABUS peak~32% -> exit +22.0% (giveback~10pp, 23d, TARGET); ACRS peak~34% -> exit +22.0% (giveback~12pp, 29d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 24d, TARGET); ADMA peak~34% -> exit +22.0% (giveback~12pp, 113d, TARGET); ADMA peak~47% -> exit +33.3% (giveback~13pp, 51d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (48 sym / 3304 trades) — direction: expand, confidence: medium, 51.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (3304 trades, 52%, high) vs target_contract_slow_hold → contract (2355 trades, 37%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 3304/6389 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 2355/6389 TARGET exits (37%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS
- **Evidence:** [A expand] ABNB +8% in 15d after TARGET; ABNB +8% in 15d after TARGET; AA +10% in 15d after TARGET; AA +8% in 15d after TARGET; AA +10% in 15d after TARGET; AA +8% in 15d after TARGET | [B contract] AA TARGET 132d +22.0% (~0.17%/d); AA TARGET 103d +22.0% (~0.21%/d); ABBV TARGET 136d +22.0% (~0.16%/d); ABBV TARGET 206d +22.0% (~0.11%/d); ACA TARGET 278d +22.0% (~0.08%/d); ACA TARGET 105d +22.0% (~0.21%/d)

## 2. `stop_pct_tension_expand_vs_contract` (50 sym / 1969 trades) — direction: mixed, confidence: medium, 26.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (1969 trades, 26%, high) vs stop_contract_dead_losers → contract (1579 trades, 21%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1969/7556 STOP exits (26%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 1579/7556 STOPs (21%) never expanded (MFE<2%) and 2814 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, ABBNY, ABBV, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU
- **Evidence:** [A expand] ABNB STOP 2021-12-16 then back above entry/15d; ABNB STOP 2022-01-24 then back above entry/15d; ABNB STOP 2026-06-11 then back above entry/15d; AA STOP 2018-12-21 then back above entry/15d; AA STOP 2021-03-23 then back above entry/15d; AA STOP 2026-07-20 then back above entry/15d | [B contract] AA MFE~1.4% STOP; AA MFE~1.1% STOP; AA MFE~1.1% STOP; AA MFE~0.1% STOP; ABBV MFE~0.3% STOP; ABBNY MFE~0.6% STOP

## 3. `target_contract_approach_fail` (842 sym / 1838 trades) — direction: contract, confidence: medium, 11.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 1838/16636 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAP, AAPL, ABBNY, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACRS, ADI, ADMA, ADNT
- **Evidence:** ABNB reached 53% of target then STOP; AA reached 52% of target then STOP; AA reached 68% of target then STOP; ABBV reached 53% of target then STOP; ACA reached 52% of target then STOP; ACA reached 70% of target then STOP

## 4. `band_tighten_weak_fill` (603 sym / 1095 trades) — direction: tighten, confidence: low, 6.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1095/16636 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAON, AAP, ABG, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI, ADM, ADMA, ADNT, ADP, ADSK, AEE, AEG
- **Evidence:** AA MFE~1.1% STOP 8d; AA MFE~1.1% STOP 8d; AA MFE~0.1% STOP 4d; AAP MFE~1.2% STOP 0d; A MFE~0.0% STOP 4d; A MFE~1.9% STOP 14d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
