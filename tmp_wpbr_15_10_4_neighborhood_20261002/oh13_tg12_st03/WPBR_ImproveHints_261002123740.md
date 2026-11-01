# WPBR Improve Hints — stamp `261002123740`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (383 sym / 501 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAON, AAP, AAT, ABUS, ACAD, ACRS, ADI, ADPT, ADSK, AEIS, AEM, AES, AGI, AGX, ALB, ALDX, ALEC, ALL, ALNT
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); AAP TARGET 2015-10-30 -> STOP 2021-10-13 (5d); AAON TARGET 2019-07-24 -> STOP 2019-08-09 (3d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); AAT TARGET 2013-10-17 -> STOP 2016-01-20 (0d)

## 2. `slow_target_grind` (199 sym / 247 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMH, AMT, AMZN, AON, APD, ARE
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d) 2017-01-11; ABM TARGET 110d +12.0% (~0.11%/d) 2015-06-03; ABT TARGET 110d +12.0% (~0.11%/d) 2020-01-22; ACN TARGET 168d +12.0% (~0.07%/d) 2019-12-13; ACGL TARGET 193d +12.0% (~0.06%/d) 2016-08-02

## 3. `false_start_2022_2023` (192 sym / 218 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, ADSK, AEHR, AES, AFRM, AGM, AGO, AI, AIT, AJG, ALB, AMH, AMKR, AMP
- **Evidence:** AA 2022 STOP 10d -9.8%; AAMI 2022 STOP 8d -5.5%; ACLS 2022 STOP 9d -6.9%; ADMA 2022 STOP 14d -5.9%; ACRS 2023 STOP 6d -9.6%

## 4. `fat_stops` (116 sym / 136 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABUS, ACLS, ACRS, ADMA, ADNT, ADPT, AEHR, AGX, AGYS, AHT, AI, ALLE, AMWL, ANF, AOSL, APLD, APPS, APYX, BABA

## 5. `winner_peak_giveback` (26 sym / 26 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, ALNT, AVAV, CECO, CMCL, DGII, DOCU, ESEA, F, HBAN, IRMD, KEX, LINC, LMAT, LUGDF, MWA, ONTO, PATK, PRIM
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CECO peak~22% -> exit +12.0% (giveback~10pp, 33d, TARGET)

## 6. `early_run_long_tail` (21 sym / 21 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACU, ALSN, EAT, EVR, FIS, HAS, HLT, IFF, IPAR, JACK, NOC, ODFL, PKG, SAIA, SPG, STN, SYF, TFX, TOWN, WFC
- **Evidence:** ACU +10% by day 8 then held 182d exit +12.0% (TARGET); ALSN +10% by day 17 then held 154d exit +12.0% (TARGET); EAT +10% by day 11 then held 83d exit +12.0% (TARGET); EVR +10% by day 25 then held 93d exit +12.0% (TARGET); FIS +10% by day 23 then held 175d exit +12.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (51 sym / 1859 trades) — direction: expand, confidence: medium, 58.8% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1859 trades, 59%, high) vs stop_ok_never_worked → hold (966 trades, 30%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1859/3164 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 966/3164 STOPs (31%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] ABBV STOP 2015-02-04 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d; AAP STOP 2010-05-06 then back above entry/15d; AAP STOP 2021-10-13 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d | [B hold] A MFE~0.0% STOP; ABBV MFE~0.0% STOP; AAMI MFE~1.6% STOP; AAP MFE~0.9% STOP; AAON MFE~0.0% STOP; AAON MFE~0.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (55 sym / 1307 trades) — direction: expand, confidence: medium, 50.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1307 trades, 50%, high) vs target_contract_approach_fail → contract (929 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1307/2605 TARGET exits (50%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 929/6853 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +19% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +11% in 15d after TARGET; ABM +5% in 15d after TARGET; ABCB +8% in 15d after TARGET | [B contract] AA reached 72% of target then STOP; AA reached 69% of target then STOP; A reached 89% of target then STOP; A reached 55% of target then STOP; AAON reached 76% of target then STOP; AAON reached 92% of target then STOP

## 3. `band_tighten_weak_fill` (632 sym / 1035 trades) — direction: tighten, confidence: high, 15.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1035/6853 trades (15%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACLS, ACN, ACRS, ADI, ADM, ADMA, ADNT, ADSK
- **Evidence:** A MFE~0.0% STOP 1d; ABBV MFE~0.0% STOP 0d; AAMI MFE~1.6% STOP 8d; AAP MFE~0.9% STOP 5d; AAON MFE~0.0% STOP 2d; AAON MFE~0.0% STOP 3d

## 4. `target_contract_slow_hold` (199 sym / 247 trades) — direction: contract, confidence: medium, 9.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 247/2605 TARGET exits (9%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AJG, ALSN, AMH, AMT, AMZN, AON, APD, ARE
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d); ABM TARGET 110d +12.0% (~0.11%/d); ABT TARGET 110d +12.0% (~0.11%/d); ACN TARGET 168d +12.0% (~0.07%/d); ACGL TARGET 193d +12.0% (~0.06%/d); ACU TARGET 182d +12.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
