# WPBR Improve Hints — stamp `261002210753`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (400 sym / 501 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, ABM, ABR, ABT, ABUS, ACAD, ACGL, ACLS, ACRS, ADI, ADPT, AEIS, AEM, AFL, AFRM, AGM, AGNC
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); A TARGET 2016-08-15 -> STOP 2019-04-23 (1d); AAMI TARGET 2015-04-13 -> STOP 2022-01-19 (7d); AAL TARGET 2010-06-11 -> STOP 2010-07-02 (0d); ABT TARGET 2014-12-02 -> STOP 2015-10-06 (4d)

## 2. `false_start_2022_2023` (184 sym / 211 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACN, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, ALB, AME, AMKR, AMP, AMRC, AMTX, AOS
- **Evidence:** AA 2022 STOP 10d -8.8%; AAMI 2022 STOP 7d -4.5%; ACRS 2023 STOP 2d -8.6%; ACLS 2022 STOP 9d -5.9%; ACN 2022 STOP 7d -4.9%

## 3. `slow_target_grind` (110 sym / 126 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACN, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AMT, AON, ARE, ARW, ASH, ATO, ATR, AVB, BAX, BF.B, BN, BNY
- **Evidence:** ACN TARGET 168d +11.0% (~0.07%/d) 2019-12-13; ADP TARGET 263d +11.0% (~0.04%/d) 2020-01-21; AEE TARGET 170d +11.0% (~0.06%/d) 2019-09-25; AEP TARGET 148d +11.0% (~0.07%/d) 2019-09-03; AFL TARGET 315d +11.0% (~0.03%/d) 2017-04-28

## 4. `fat_stops` (79 sym / 91 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACLS, ACRS, ADMA, ADPT, AEHR, AGX, AHT, AI, ALLE, AOSL, APLD, APPS, APYX, AXP, BABA, BBWI, BILI, BKNG, BXMT, CASH

## 5. `winner_peak_giveback` (12 sym / 12 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AVAV, CECO, DGII, ESEA, HBAN, IRMD, KEX, MWA, PRIM, SENEA, W, WLDN
- **Evidence:** AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); CECO peak~22% -> exit +11.0% (giveback~11pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP); ESEA peak~26% -> exit +11.0% (giveback~15pp, 15d, TARGET); HBAN peak~24% -> exit +12.0% (giveback~12pp, 29d, GAP_UP)

## 6. `early_run_long_tail` (4 sym / 4 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** JACK, SPG, STN, TFX
- **Evidence:** JACK +10% by day 14 then held 83d exit +11.7% (GAP_UP); SPG +10% by day 19 then held 82d exit +11.0% (TARGET); STN +10% by day 22 then held 92d exit +11.0% (TARGET); TFX +10% by day 23 then held 184d exit +11.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (49 sym / 1884 trades) — direction: expand, confidence: medium, 65.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1884 trades, 65%, high) vs stop_ok_never_worked → hold (1017 trades, 35%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1884/2884 STOP exits (65%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 1017/2884 STOPs (35%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** [A expand] A STOP 2014-02-14 then back above entry/15d; A STOP 2019-04-23 then back above entry/15d; AAMI STOP 2022-01-19 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAPL STOP 2013-04-17 then back above entry/15d; AAT STOP 2012-05-18 then back above entry/15d | [B hold] A MFE~0.0% STOP; A MFE~1.1% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.9% STOP; AAT MFE~1.7% STOP

## 2. `target_pct_tension_expand_vs_contract` (58 sym / 1096 trades) — direction: expand, confidence: medium, 52.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1096 trades, 52%, high) vs target_contract_approach_fail → contract (815 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1096/2107 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 815/5858 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +20% in 15d after TARGET; AAPL +14% in 15d after TARGET; AAT +6% in 15d after TARGET; ABNB +19% in 15d after TARGET; AAL +14% in 15d after TARGET; AAL +12% in 15d after TARGET | [B contract] AA reached 75% of target then STOP; A reached 60% of target then STOP; AAPL reached 74% of target then STOP; AAT reached 62% of target then STOP; ABBNY reached 67% of target then STOP; AAON reached 83% of target then STOP

## 3. `band_tighten_weak_fill` (683 sym / 1127 trades) — direction: tighten, confidence: high, 19.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1127/5858 trades (19%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACGL, ACLS, ACN, ACRS, ADBE, ADI, ADM, ADMA
- **Evidence:** A MFE~0.0% STOP 0d; A MFE~1.1% STOP 1d; AAMI MFE~1.6% STOP 7d; ABBV MFE~0.0% STOP 0d; AAT MFE~1.9% STOP 10d; AAT MFE~0.0% STOP 0d

## 4. `target_contract_slow_hold` (110 sym / 126 trades) — direction: contract, confidence: low, 6.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 126/2107 TARGET exits (6%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACN, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AMT, AON, ARE, ARW, ASH, ATO, ATR, AVB, BAX, BF.B, BN, BNY
- **Evidence:** ACN TARGET 168d +11.0% (~0.07%/d); ADP TARGET 263d +11.0% (~0.04%/d); AEE TARGET 170d +11.0% (~0.06%/d); AEP TARGET 148d +11.0% (~0.07%/d); AFL TARGET 315d +11.0% (~0.03%/d); AFG TARGET 355d +11.0% (~0.03%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
