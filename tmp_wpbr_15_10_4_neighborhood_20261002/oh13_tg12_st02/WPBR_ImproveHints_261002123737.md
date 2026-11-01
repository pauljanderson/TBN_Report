# WPBR Improve Hints — stamp `261002123737`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (455 sym / 604 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAP, AAT, ABT, ABUS, ACAD, ACGL, ACRS, ADI, ADPT, AEIS, AEM, AEO, AES, AFRM, AGI, AGX, ALB
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); A TARGET 2017-01-11 -> STOP 2019-04-23 (1d); AAP TARGET 2015-10-30 -> STOP 2021-10-13 (5d); ABT TARGET 2014-12-03 -> STOP 2015-10-06 (4d); AAL TARGET 2010-06-11 -> STOP 2010-07-02 (0d)

## 2. `false_start_2022_2023` (227 sym / 263 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, AAON, ACLS, ACN, ACRS, ADBE, ADMA, ADPT, ADSK, AEHR, AES, AFRM, AGM, AI, AJG, ALB, AME, AMH, AMKR
- **Evidence:** AA 2022 STOP 10d -8.8%; AAMI 2022 STOP 7d -4.5%; AAON 2023 STOP 1d -2.1%; ACN 2022 STOP 7d -4.9%; ACLS 2022 STOP 9d -5.9%

## 3. `slow_target_grind` (156 sym / 190 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMH, AMT, AMZN, AON, APD, ARE
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d) 2017-01-11; ABT TARGET 110d +12.0% (~0.11%/d) 2020-01-22; ABM TARGET 110d +12.0% (~0.11%/d) 2015-06-03; ACGL TARGET 193d +12.0% (~0.06%/d) 2016-08-02; ACN TARGET 168d +12.0% (~0.07%/d) 2019-12-13

## 4. `fat_stops` (96 sym / 117 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, AAPL, ABUS, ACLS, ACRS, ADMA, ADPT, AEHR, AGX, AGYS, AHT, AI, ALLE, AMWL, ANF, AOSL, APLD, APPS, APYX, AXP

## 5. `winner_peak_giveback` (19 sym / 19 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, AVAV, CECO, CMCL, DGII, DOCU, ESEA, HBAN, IRMD, KEX, LMAT, LUGDF, MWA, ONTO, PRIM, SENEA, W, WLDN
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CECO peak~22% -> exit +12.0% (giveback~10pp, 33d, TARGET); CMCL peak~22% -> exit +12.0% (giveback~10pp, 22d, TARGET)

## 6. `early_run_long_tail` (18 sym / 18 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ALSN, EAT, EVR, FIS, HAS, HLT, IFF, IPAR, JACK, NOC, ODFL, PKG, SAIA, SPG, STN, TFX, WFC
- **Evidence:** ACU +10% by day 8 then held 182d exit +12.0% (TARGET); ALSN +10% by day 17 then held 154d exit +12.0% (TARGET); EAT +10% by day 11 then held 83d exit +12.0% (TARGET); EVR +10% by day 25 then held 93d exit +12.0% (TARGET); FIS +10% by day 23 then held 175d exit +12.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (46 sym / 2284 trades) — direction: expand, confidence: medium, 65.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (2284 trades, 65%, high) vs stop_ok_never_worked → hold (1228 trades, 35%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 2284/3513 STOP exits (65%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 1228/3513 STOPs (35%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS
- **Evidence:** [A expand] AA STOP 2015-03-27 then back above entry/15d; A STOP 2014-02-14 then back above entry/15d; A STOP 2019-04-23 then back above entry/15d; AAMI STOP 2022-01-19 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; ABBNY STOP 2022-04-12 then back above entry/15d | [B hold] AA MFE~0.9% STOP; A MFE~0.0% STOP; A MFE~1.1% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAP MFE~0.9% STOP

## 2. `target_pct_tension_expand_vs_contract` (55 sym / 1197 trades) — direction: expand, confidence: medium, 51.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1197 trades, 51%, high) vs target_contract_approach_fail → contract (920 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1197/2336 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 920/6858 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +19% in 15d after TARGET; AAPL +13% in 15d after TARGET; ABCB +8% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +11% in 15d after TARGET; ABM +5% in 15d after TARGET | [B contract] AA reached 69% of target then STOP; A reached 89% of target then STOP; A reached 55% of target then STOP; ABBNY reached 61% of target then STOP; AAON reached 76% of target then STOP; AAON reached 92% of target then STOP

## 3. `band_tighten_weak_fill` (756 sym / 1372 trades) — direction: tighten, confidence: high, 20.0% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1372/6858 trades (20%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACA, ACGL, ACLS, ACN, ACRS, ADBE, ADI
- **Evidence:** AA MFE~0.9% STOP 8d; A MFE~0.0% STOP 0d; A MFE~1.1% STOP 1d; AAMI MFE~1.6% STOP 7d; ABBV MFE~0.0% STOP 0d; AAP MFE~0.9% STOP 5d

## 4. `target_contract_slow_hold` (156 sym / 190 trades) — direction: contract, confidence: medium, 8.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 190/2336 TARGET exits (8%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMH, AMT, AMZN, AON, APD, ARE
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d); ABT TARGET 110d +12.0% (~0.11%/d); ABM TARGET 110d +12.0% (~0.11%/d); ACGL TARGET 193d +12.0% (~0.06%/d); ACN TARGET 168d +12.0% (~0.07%/d); ACU TARGET 182d +12.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
