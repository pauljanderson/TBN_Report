# WPBR Improve Hints — stamp `261002212557`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (386 sym / 476 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, ABM, ABT, ABUS, ACAD, ACGL, ACLS, ADI, ADPT, AEIS, AEM, AFL, AFRM, AGX, AGYS, ALB, ALDX
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); A TARGET 2017-01-11 -> STOP 2019-04-23 (1d); AAMI TARGET 2015-04-23 -> STOP 2022-01-19 (7d); AAL TARGET 2010-06-11 -> STOP 2010-07-02 (0d); ABT TARGET 2014-12-03 -> STOP 2015-10-06 (4d)

## 2. `false_start_2022_2023` (186 sym / 214 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACN, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, ALB, AME, AMKR, AMP, AMRC, AMTX, AOS
- **Evidence:** AA 2022 STOP 10d -8.8%; AAMI 2022 STOP 7d -4.5%; ACRS 2023 STOP 2d -8.6%; ACLS 2022 STOP 9d -5.9%; ACN 2022 STOP 7d -4.9%

## 3. `slow_target_grind` (141 sym / 168 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMT, AMZN, AON, ARE, ARW, ASH
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d) 2017-01-11; ABT TARGET 110d +12.0% (~0.11%/d) 2020-01-22; ACGL TARGET 193d +12.0% (~0.06%/d) 2016-08-02; ABM TARGET 110d +12.0% (~0.11%/d) 2015-06-03; ACN TARGET 168d +12.0% (~0.07%/d) 2019-12-13

## 4. `fat_stops` (80 sym / 96 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACLS, ACRS, ADMA, ADPT, AEHR, AGX, AHT, AI, ALLE, AOSL, APLD, APPS, APYX, AXP, BABA, BBWI, BILI, BKNG, BXMT, CASH

## 5. `winner_peak_giveback` (16 sym / 16 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, AVAV, CECO, CMCL, DGII, ESEA, HBAN, IRMD, KEX, LUGDF, MWA, PRIM, SENEA, W, WLDN
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CECO peak~22% -> exit +12.0% (giveback~10pp, 33d, TARGET); CMCL peak~22% -> exit +12.0% (giveback~10pp, 22d, TARGET)

## 6. `early_run_long_tail` (15 sym / 15 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ALSN, EAT, EVR, FIS, HLT, IFF, IPAR, JACK, ODFL, PKG, SAIA, SPG, STN, TFX
- **Evidence:** ACU +10% by day 8 then held 182d exit +12.0% (TARGET); ALSN +10% by day 17 then held 154d exit +12.0% (TARGET); EAT +10% by day 11 then held 83d exit +12.0% (TARGET); EVR +10% by day 25 then held 93d exit +12.0% (TARGET); FIS +10% by day 23 then held 175d exit +12.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (50 sym / 1941 trades) — direction: expand, confidence: medium, 65.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1941 trades, 65%, high) vs stop_ok_never_worked → hold (1012 trades, 34%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1941/2976 STOP exits (65%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 1012/2976 STOPs (34%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** [A expand] A STOP 2014-02-14 then back above entry/15d; A STOP 2019-04-23 then back above entry/15d; AAMI STOP 2022-01-19 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAPL STOP 2013-04-17 then back above entry/15d; AAT STOP 2012-05-18 then back above entry/15d | [B hold] A MFE~0.0% STOP; A MFE~1.1% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.9% STOP; AAT MFE~1.7% STOP

## 2. `target_pct_tension_expand_vs_contract` (58 sym / 1016 trades) — direction: expand, confidence: medium, 51.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1016 trades, 51%, high) vs target_contract_approach_fail → contract (809 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1016/1992 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 809/5830 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +19% in 15d after TARGET; AAPL +13% in 15d after TARGET; AAT +5% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +11% in 15d after TARGET; ABCB +8% in 15d after TARGET | [B contract] AA reached 69% of target then STOP; A reached 55% of target then STOP; AAPL reached 68% of target then STOP; AAT reached 57% of target then STOP; ABBNY reached 61% of target then STOP; AAON reached 76% of target then STOP

## 3. `band_tighten_weak_fill` (680 sym / 1122 trades) — direction: tighten, confidence: high, 19.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1122/5830 trades (19%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACGL, ACLS, ACN, ACRS, ADBE, ADI, ADM, ADMA
- **Evidence:** A MFE~0.0% STOP 0d; A MFE~1.1% STOP 1d; AAMI MFE~1.6% STOP 7d; ABBV MFE~0.0% STOP 0d; AAT MFE~1.9% STOP 10d; AAT MFE~0.0% STOP 0d

## 4. `target_contract_slow_hold` (141 sym / 168 trades) — direction: contract, confidence: medium, 8.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 168/1992 TARGET exits (8%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMT, AMZN, AON, ARE, ARW, ASH
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d); ABT TARGET 110d +12.0% (~0.11%/d); ACGL TARGET 193d +12.0% (~0.06%/d); ABM TARGET 110d +12.0% (~0.11%/d); ACN TARGET 168d +12.0% (~0.07%/d); ACU TARGET 182d +12.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
