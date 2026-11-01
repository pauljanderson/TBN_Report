# WPBR Improve Hints — stamp `261002223838`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (363 sym / 435 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, ABM, ABT, ABUS, ACAD, ACGL, ADI, ADPT, AEIS, AEM, AFL, AFRM, AGX, AGYS, ALB, ALDX, ALEC
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); AAMI TARGET 2015-04-23 -> STOP 2022-01-19 (7d); A TARGET 2017-01-11 -> STOP 2019-04-23 (1d); AAL TARGET 2010-06-11 -> STOP 2010-07-02 (0d); ABT TARGET 2014-12-03 -> STOP 2015-10-06 (4d)

## 2. `false_start_2022_2023` (164 sym / 188 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACN, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, ALB, AME, AMKR, AMRC, AMTX, AOUT, APH
- **Evidence:** AA 2022 STOP 10d -8.8%; AAMI 2022 STOP 7d -4.5%; ACLS 2022 STOP 9d -5.9%; ACRS 2023 STOP 2d -8.6%; ACN 2022 STOP 7d -4.9%

## 3. `slow_target_grind` (141 sym / 167 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMT, AMZN, AON, ARE, ARW, ASH
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d) 2017-01-11; ABT TARGET 110d +12.0% (~0.11%/d) 2020-01-22; ABM TARGET 110d +12.0% (~0.11%/d) 2015-06-03; ACGL TARGET 193d +12.0% (~0.06%/d) 2016-08-02; ACN TARGET 168d +12.0% (~0.07%/d) 2019-12-13

## 4. `fat_stops` (78 sym / 91 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACLS, ACRS, ADMA, ADPT, AEHR, AGX, AHT, AI, ALLE, AOSL, APLD, APPS, APYX, AXP, BABA, BBWI, BILI, BKNG, BXMT, CASH

## 5. `early_run_long_tail` (15 sym / 15 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ALSN, EAT, EVR, FIS, HLT, IFF, IPAR, JACK, ODFL, PKG, SAIA, SPG, STN, TFX
- **Evidence:** ACU +10% by day 8 then held 182d exit +12.0% (TARGET); ALSN +10% by day 17 then held 154d exit +12.0% (TARGET); EAT +10% by day 11 then held 83d exit +12.0% (TARGET); EVR +10% by day 25 then held 93d exit +12.0% (TARGET); FIS +10% by day 23 then held 175d exit +12.0% (TARGET)

## 6. `winner_peak_giveback` (15 sym / 15 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, AVAV, CECO, CMCL, DGII, ESEA, HBAN, IRMD, KEX, LUGDF, MWA, PRIM, SENEA, W
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CECO peak~22% -> exit +12.0% (giveback~10pp, 33d, TARGET); CMCL peak~22% -> exit +12.0% (giveback~10pp, 22d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (50 sym / 1831 trades) — direction: expand, confidence: medium, 65.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1831 trades, 65%, high) vs stop_ok_never_worked → hold (940 trades, 34%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1831/2802 STOP exits (65%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 940/2802 STOPs (34%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** [A expand] AAMI STOP 2022-01-19 then back above entry/15d; A STOP 2014-02-14 then back above entry/15d; A STOP 2019-04-23 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2017-07-27 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; A MFE~0.0% STOP; A MFE~1.1% STOP; AAON MFE~0.0% STOP; AAL MFE~0.9% STOP; ABBV MFE~0.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (59 sym / 958 trades) — direction: mixed, confidence: medium, 50.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (958 trades, 50%, high) vs target_contract_approach_fail → contract (772 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 958/1902 TARGET exits (50%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 772/5518 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +19% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +11% in 15d after TARGET; AAT +5% in 15d after TARGET; AAPL +13% in 15d after TARGET; ABCB +8% in 15d after TARGET | [B contract] AA reached 69% of target then STOP; A reached 55% of target then STOP; AAON reached 76% of target then STOP; AAON reached 92% of target then STOP; AAL reached 77% of target then STOP; ABBNY reached 61% of target then STOP

## 3. `band_tighten_weak_fill` (645 sym / 1032 trades) — direction: tighten, confidence: high, 18.7% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1032/5518 trades (19%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACGL, ACLS, ACN, ACRS, ADBE, ADI, ADMA, ADNT
- **Evidence:** AAMI MFE~1.6% STOP 7d; A MFE~0.0% STOP 0d; A MFE~1.1% STOP 1d; AAON MFE~0.0% STOP 2d; AAL MFE~0.9% STOP 0d; AAL MFE~2.1% STOP 9d

## 4. `target_contract_slow_hold` (141 sym / 167 trades) — direction: contract, confidence: medium, 8.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 167/1902 TARGET exits (9%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMT, AMZN, AON, ARE, ARW, ASH
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d); ABT TARGET 110d +12.0% (~0.11%/d); ABM TARGET 110d +12.0% (~0.11%/d); ACGL TARGET 193d +12.0% (~0.06%/d); ACN TARGET 168d +12.0% (~0.07%/d); ACU TARGET 182d +12.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
