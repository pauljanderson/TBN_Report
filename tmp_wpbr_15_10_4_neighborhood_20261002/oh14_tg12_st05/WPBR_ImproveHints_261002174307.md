# WPBR Improve Hints — stamp `261002174307`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (312 sym / 381 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ABCB, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEIS, AFRM, AGI, AGX, ALDX, ALEC, ALL, ALLE, ALNT, ALNY, AMAT
- **Evidence:** ABUS TARGET 2014-04-22 -> STOP 2014-11-06 (1d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACLS TARGET 2022-05-27 -> STOP 2022-06-16 (1d); ACRS TARGET 2017-02-24 -> STOP 2020-11-16 (3d); ACU TARGET 2020-12-28 -> STOP 2021-04-20 (7d)

## 2. `slow_target_grind` (263 sym / 343 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, ABG, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AKR, ALL, ALLE, ALSN, AMH
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d) 2017-01-11; ABM TARGET 110d +12.0% (~0.11%/d) 2015-06-03; ABT TARGET 128d +12.0% (~0.09%/d) 2019-07-17; ACU TARGET 182d +12.0% (~0.07%/d) 2014-11-25; ACN TARGET 296d +12.0% (~0.04%/d) 2014-01-22

## 3. `fat_stops` (170 sym / 217 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABG, ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AHCO, AHT, AI, ALEC, ALGN, ALNY, AMN, AMP, AMRC, AMWL

## 4. `false_start_2022_2023` (130 sym / 147 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, AMP, AMTX, AN, AOUT, APLD, ATUSF, AVGO, AZO, BILI
- **Evidence:** AAMI 2022 STOP 8d -7.4%; ACLS 2022 STOP 1d -8.1%; ACRS 2023 STOP 7d -11.4%; ADMA 2022 STOP 15d -7.8%; ADPT 2022 STOP 8d -16.3%

## 5. `winner_peak_giveback` (33 sym / 33 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABNB, AFRM, AGX, ALNT, AVAV, AX, CECO, CMCL, DGII, DOCU, ESEA, F, FIVN, FSLR, HBAN, IRMD, JMIA, KEX, LINC, LMAT
- **Evidence:** ABNB peak~27% -> exit +15.9% (giveback~11pp, 52d, GAP_UP); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AGX peak~24% -> exit +12.0% (giveback~12pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP)

## 6. `early_run_long_tail` (27 sym / 27 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACN, ACU, ALLE, ALSN, EAT, ENVA, EVR, FIS, HAS, HLT, IAG, IFF, IPAR, JACK, ODFL, PKG, PSIX, ROK, SAIA, SPG
- **Evidence:** ACU +10% by day 8 then held 182d exit +12.0% (TARGET); ACN +10% by day 24 then held 89d exit +12.0% (TARGET); ALLE +10% by day 24 then held 142d exit +12.0% (TARGET); ALSN +10% by day 17 then held 154d exit +12.0% (TARGET); EAT +10% by day 11 then held 83d exit +12.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (56 sym / 1410 trades) — direction: expand, confidence: medium, 49.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1410 trades, 50%, high) vs target_contract_approach_fail → contract (894 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1410/2847 TARGET exits (50%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 894/6426 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +19% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +7% in 15d after TARGET; AAL +11% in 15d after TARGET; ABM +5% in 15d after TARGET | [B contract] AAON reached 76% of target then STOP; AAON reached 92% of target then STOP; AAL reached 77% of target then STOP; A reached 89% of target then STOP; A reached 55% of target then STOP; ABNB reached 64% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (60 sym / 1195 trades) — direction: expand, confidence: medium, 45.9% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1195 trades, 46%, high) vs stop_ok_never_worked → hold (642 trades, 25%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1195/2601 STOP exits (46%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 642/2601 STOPs (25%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-08 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d; AAON STOP 2024-06-04 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; AAON MFE~1.3% STOP; ABBV MFE~0.0% STOP; A MFE~0.0% STOP; ABR MFE~1.9% STOP; ABM MFE~1.0% STOP

## 3. `band_tighten_weak_fill` (446 sym / 599 trades) — direction: tighten, confidence: medium, 9.3% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 599/6426 trades (9%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAT, ABBV, ABCB, ABM, ABR, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AGI, AGM, AGO, AGX, AHT, AI
- **Evidence:** AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; A MFE~0.0% STOP 1d; ABR MFE~1.9% STOP 7d; ABM MFE~1.0% STOP 14d; AAT MFE~0.0% STOP 6d

## 4. `target_contract_slow_hold` (263 sym / 343 trades) — direction: contract, confidence: medium, 12.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 343/2847 TARGET exits (12%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, ABG, ABM, ABT, ACGL, ACN, ACU, ADBE, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AKR, ALL, ALLE, ALSN, AMH
- **Evidence:** A TARGET 195d +12.0% (~0.06%/d); ABM TARGET 110d +12.0% (~0.11%/d); ABT TARGET 128d +12.0% (~0.09%/d); ACU TARGET 182d +12.0% (~0.07%/d); ACN TARGET 296d +12.0% (~0.04%/d); ACN TARGET 168d +12.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
