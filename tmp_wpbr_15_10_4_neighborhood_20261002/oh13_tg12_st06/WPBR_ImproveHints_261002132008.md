# WPBR Improve Hints — stamp `261002132008`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (313 sym / 433 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADI, ADP, AEE, AEP, AFG, AFL, AGM, AGNC, AJG, AKR, ALB, ALL, ALLE
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d) 2017-01-11; ABT TARGET 128d +12.0% (~0.09%/d) 2019-07-17; ABM TARGET 110d +12.0% (~0.11%/d) 2015-06-03; ACU TARGET 182d +12.0% (~0.07%/d) 2014-11-25; ADI TARGET 256d +12.0% (~0.05%/d) 2013-11-15

## 2. `post_target_quick_stop` (281 sym / 350 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ABCB, ACAD, ACN, ACRS, ACU, ADPT, ADSK, AEIS, AEM, AGI, ALB, ALDX, ALEC, ALL, ALLE, ALNT, ALNY, AMAT, AMKR, AMRC
- **Evidence:** ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACRS TARGET 2020-08-20 -> STOP 2020-09-02 (2d); ACU TARGET 2020-12-28 -> STOP 2021-04-20 (7d); ABCB TARGET 2013-05-07 -> STOP 2015-08-26 (9d); ADPT TARGET 2021-02-12 -> STOP 2021-03-03 (7d)

## 3. `fat_stops` (219 sym / 305 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABG, ABR, ABUS, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AGYS, AHCO, AHT, AI, ALEC, ALGN, ALL, ALNT, ALNY

## 4. `false_start_2022_2023` (118 sym / 133 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGM, AGO, AI, AMH, AMP, AMTX, AMWL, AN, APLD, APPS, ATUSF, AVGO, BG, BILI
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADMA 2022 STOP 15d -8.8%; ADPT 2022 STOP 8d -17.1%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (37 sym / 37 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, AGX, ALNT, AVAV, AX, CECO, CMCL, DGII, DOCU, ESEA, F, FIVN, FSLR, HBAN, IRMD, JMIA, KEX, LINC, LMAT
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AGX peak~24% -> exit +12.0% (giveback~12pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP)

## 6. `early_run_long_tail` (29 sym / 29 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACN, ACU, ALLE, ALSN, EAT, ENVA, EVR, FIS, HAS, HLT, IAG, IFF, IPAR, JACK, NEO, NOC, ODFL, PKG, PSIX, ROK
- **Evidence:** ACU +10% by day 8 then held 182d exit +12.0% (TARGET); ACN +10% by day 24 then held 89d exit +12.0% (TARGET); ALLE +10% by day 24 then held 142d exit +12.0% (TARGET); ALSN +10% by day 17 then held 154d exit +12.0% (TARGET); EAT +10% by day 11 then held 83d exit +12.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (53 sym / 1585 trades) — direction: expand, confidence: medium, 49.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1585 trades, 49%, high) vs target_contract_approach_fail → contract (913 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1585/3217 TARGET exits (49%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 913/6838 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACRS, ACU
- **Evidence:** [A expand] AA +19% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +7% in 15d after TARGET; AAL +11% in 15d after TARGET; AAON +6% in 15d after TARGET | [B contract] AA reached 72% of target then STOP; AAL reached 77% of target then STOP; A reached 89% of target then STOP; A reached 55% of target then STOP; ABBNY reached 61% of target then STOP; AAON reached 76% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (61 sym / 1026 trades) — direction: expand, confidence: medium, 40.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1026 trades, 40%, high) vs stop_ok_never_worked → hold (584 trades, 23%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1026/2566 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 584/2566 STOPs (23%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADMA
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; AAON STOP 2014-04-07 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAON STOP 2019-10-03 then back above entry/15d; AAON STOP 2023-10-19 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; A MFE~0.0% STOP; AAON MFE~1.3% STOP; ABR MFE~1.9% STOP; ACLS MFE~1.4% STOP

## 3. `band_tighten_weak_fill` (398 sym / 525 trades) — direction: tighten, confidence: low, 7.7% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 525/6838 trades (8%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGI, AGM, AGO, AHT, AI, AIR, AIT, AKTS
- **Evidence:** AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 1d; A MFE~0.0% STOP 1d; ABR MFE~1.9% STOP 11d; AAPL MFE~3.0% STOP 4d; ACLS MFE~0.3% STOP 8d

## 4. `target_contract_slow_hold` (313 sym / 433 trades) — direction: contract, confidence: medium, 13.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 433/3217 TARGET exits (13%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, ABM, ABT, ACGL, ACN, ACU, ADBE, ADI, ADP, AEE, AEP, AFG, AFL, AGM, AGNC, AJG, AKR, ALB, ALL, ALLE
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d); ABT TARGET 128d +12.0% (~0.09%/d); ABM TARGET 110d +12.0% (~0.11%/d); ACU TARGET 182d +12.0% (~0.07%/d); ADI TARGET 256d +12.0% (~0.05%/d); AEE TARGET 111d +12.0% (~0.11%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
