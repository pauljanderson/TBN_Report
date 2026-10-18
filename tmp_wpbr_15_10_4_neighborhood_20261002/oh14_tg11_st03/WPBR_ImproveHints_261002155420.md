# WPBR Improve Hints — stamp `261002155420`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (390 sym / 504 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAP, ABUS, ACAD, ACRS, ADI, ADPT, ADSK, AEIS, AEM, AES, AFRM, AGM, AGX, ALB, ALDX, ALEC, ALL, ALLE, ALNT
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); AAP TARGET 2015-10-29 -> STOP 2021-10-13 (5d); ABUS TARGET 2014-04-22 -> STOP 2014-11-05 (0d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACRS TARGET 2025-03-25 -> STOP 2025-06-16 (4d)

## 2. `false_start_2022_2023` (178 sym / 202 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, ADSK, AEHR, AES, AFRM, AGM, AGO, AI, AIT, AJG, ALB, AMH, AMKR, AMP
- **Evidence:** AAMI 2022 STOP 8d -5.5%; AA 2022 STOP 10d -9.8%; ACRS 2023 STOP 6d -9.6%; ACLS 2022 STOP 9d -6.9%; ADMA 2022 STOP 14d -5.9%

## 3. `slow_target_grind` (158 sym / 184 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACN, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AMH, AMT, AON, ARE, ARW, ASH, ATO, ATR, AVB, AWK, AX, BA
- **Evidence:** ACN TARGET 168d +11.0% (~0.07%/d) 2019-12-13; ADP TARGET 263d +11.0% (~0.04%/d) 2020-01-21; AEE TARGET 170d +11.0% (~0.06%/d) 2019-09-25; AEP TARGET 148d +11.0% (~0.07%/d) 2019-09-03; AFL TARGET 315d +11.0% (~0.03%/d) 2017-04-28

## 4. `fat_stops` (103 sym / 120 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACRS, ADMA, ADNT, ADPT, AEHR, AGX, AHT, AI, ALLE, ANF, AOSL, APLD, APPS, APYX, BABA, BBIO, BBWI, BXMT, CASH, CBRE

## 5. `winner_peak_giveback` (18 sym / 18 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ALNT, AVAV, CECO, DGII, DOCU, ESEA, F, HBAN, IRMD, KEX, LINC, LMAT, MWA, PRIM, SENEA, TIPT, W, WLDN
- **Evidence:** ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CECO peak~22% -> exit +11.0% (giveback~11pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP); DOCU peak~35% -> exit +20.0% (giveback~15pp, 16d, GAP_UP)

## 6. `early_run_long_tail` (5 sym / 5 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** HAS, JACK, SPG, STN, TFX
- **Evidence:** HAS +10% by day 22 then held 231d exit +11.0% (TARGET); JACK +10% by day 14 then held 83d exit +11.7% (GAP_UP); SPG +10% by day 19 then held 82d exit +11.0% (TARGET); STN +10% by day 22 then held 92d exit +11.0% (TARGET); TFX +10% by day 23 then held 184d exit +11.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (51 sym / 1671 trades) — direction: expand, confidence: medium, 58.6% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1671 trades, 59%, high) vs stop_ok_never_worked → hold (902 trades, 32%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1671/2852 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 902/2852 STOPs (32%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2017-07-31 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d; AAON STOP 2024-06-04 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; AAON MFE~0.0% STOP; AAON MFE~1.3% STOP; AAP MFE~0.9% STOP; ABBV MFE~0.0% STOP; A MFE~0.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (57 sym / 1328 trades) — direction: expand, confidence: medium, 51.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1328 trades, 51%, high) vs target_contract_approach_fail → contract (870 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1328/2596 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 870/6481 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +20% in 15d after TARGET; ABNB +19% in 15d after TARGET; AAPL +14% in 15d after TARGET; AAL +14% in 15d after TARGET; AAL +18% in 15d after TARGET; AAL +12% in 15d after TARGET | [B contract] AA reached 75% of target then STOP; AAON reached 83% of target then STOP; A reached 60% of target then STOP; AAPL reached 74% of target then STOP; AAL reached 52% of target then STOP; AAL reached 84% of target then STOP

## 3. `band_tighten_weak_fill` (609 sym / 958 trades) — direction: tighten, confidence: medium, 14.8% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 958/6481 trades (15%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACLS, ACN, ACRS, ADI, ADMA, ADNT, ADSK, AEG
- **Evidence:** AAMI MFE~1.6% STOP 8d; AAON MFE~0.0% STOP 2d; AAP MFE~0.9% STOP 5d; ABBV MFE~0.0% STOP 0d; A MFE~0.0% STOP 1d; AAL MFE~2.1% STOP 12d

## 4. `target_contract_slow_hold` (158 sym / 184 trades) — direction: contract, confidence: low, 7.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 184/2596 TARGET exits (7%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACN, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AMH, AMT, AON, ARE, ARW, ASH, ATO, ATR, AVB, AWK, AX, BA
- **Evidence:** ACN TARGET 168d +11.0% (~0.07%/d); ADP TARGET 263d +11.0% (~0.04%/d); AEE TARGET 170d +11.0% (~0.06%/d); AEP TARGET 148d +11.0% (~0.07%/d); AFL TARGET 315d +11.0% (~0.03%/d); AGNC TARGET 177d +11.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
