# WPBR Improve Hints — stamp `261002220847`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (235 sym / 277 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, AAPL, ABCB, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AEM, AFRM, AKAM, ALDX, ALEC, ALL, ALLE, ALNY
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); AAPL TARGET 2021-12-08 -> STOP 2026-07-31 (4d); ABCB TARGET 2013-05-06 -> STOP 2015-08-26 (9d); ACRS TARGET 2017-02-23 -> STOP 2020-11-16 (3d); ACRS TARGET 2025-03-24 -> STOP 2025-06-18 (6d)

## 2. `slow_target_grind` (189 sym / 232 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB
- **Evidence:** ABT TARGET 100d +9.0% (~0.09%/d) 2019-06-19; ACGL TARGET 130d +9.0% (~0.07%/d) 2012-10-01; ACN TARGET 142d +9.0% (~0.06%/d) 2013-12-20; ADI TARGET 149d +9.0% (~0.06%/d) 2013-07-31; ADP TARGET 204d +9.0% (~0.04%/d) 2012-09-06

## 3. `fat_stops` (155 sym / 197 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACRS, ADMA, ADNT, ADPT, AEHR, AHCO, AHT, AI, ALEC, ALGN, ALL, ALLE, ALNT, AMP, AMRC, AMTX, AMWL, ANIP, ANNX

## 4. `false_start_2022_2023` (78 sym / 88 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGO, AI, AMTX, APLD, AVGO, BG, BILI, CB, CCL, CGC, CI, COIN, CPT, CUBE
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADMA 2022 STOP 15d -8.8%; ADPT 2022 STOP 8d -17.1%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (18 sym / 19 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABUS, AGX, AVAV, CECO, DGII, DRS, ESEA, FIVN, FSLR, HURC, IESC, JMIA, LMB, MIDD, MOD, MWA, RBC, TGB
- **Evidence:** ABUS peak~20% -> exit +9.0% (giveback~11pp, 21d, TARGET); AGX peak~24% -> exit +9.0% (giveback~15pp, 17d, TARGET); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +9.0% (giveback~11pp, 33d, TARGET); CECO peak~22% -> exit +9.0% (giveback~13pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (62 sym / 1550 trades) — direction: expand, confidence: medium, 50.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1550 trades, 51%, high) vs target_contract_approach_fail → contract (702 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1550/3046 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 702/5570 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +22% in 15d after TARGET; AAT +7% in 15d after TARGET; ABBNY +7% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +10% in 15d after TARGET | [B contract] A reached 74% of target then STOP; AAPL reached 90% of target then STOP; AAT reached 82% of target then STOP; ABBNY reached 81% of target then STOP; ACA reached 93% of target then STOP; ACA reached 83% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (60 sym / 681 trades) — direction: expand, confidence: medium, 39.9% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (681 trades, 40%, high) vs stop_ok_never_worked → hold (441 trades, 26%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 681/1705 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 441/1705 STOPs (26%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAPL, AAT, ABBV, ABCB, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADMA, ADNT, ADSK, AEE, AEHR
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; AAPL STOP 2013-04-18 then back above entry/15d; ACA STOP 2023-10-27 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ABCB STOP 2015-08-26 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; ABCB MFE~0.7% STOP; ABR MFE~1.9% STOP

## 3. `band_tighten_weak_fill` (309 sym / 379 trades) — direction: tighten, confidence: low, 6.8% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 379/5570 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGO, AI, AIT, AKTS, ALDX, ALEC, ALL, ALNY
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 1d; AAPL MFE~3.0% STOP 4d; ABCB MFE~2.6% STOP 9d; ABCB MFE~0.7% STOP 3d

## 4. `target_contract_slow_hold` (189 sym / 232 trades) — direction: contract, confidence: low, 7.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 232/3046 TARGET exits (8%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB
- **Evidence:** ABT TARGET 100d +9.0% (~0.09%/d); ACGL TARGET 130d +9.0% (~0.07%/d); ACN TARGET 142d +9.0% (~0.06%/d); ADI TARGET 149d +9.0% (~0.06%/d); ADP TARGET 204d +9.0% (~0.04%/d); ADP TARGET 126d +9.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
