# WPBR Improve Hints — stamp `261002120002`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (405 sym / 546 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAON, AAP, AAT, ABR, ABUS, ACAD, ACN, ACRS, ADI, ADPT, ADSK, AEG, AEIS, AEM, AES, AGM, AGX, ALB, ALDX
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); AAON TARGET 2019-07-19 -> STOP 2019-08-09 (3d); AAP TARGET 2015-10-21 -> STOP 2021-10-13 (5d); ABR TARGET 2013-03-15 -> STOP 2013-04-17 (0d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d)

## 2. `false_start_2022_2023` (189 sym / 214 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, ADSK, AEHR, AES, AFRM, AGM, AGO, AI, AIT, AJG, ALB, AMH, AMKR, AMP
- **Evidence:** AA 2022 STOP 10d -9.8%; AAMI 2022 STOP 8d -5.5%; ACLS 2022 STOP 9d -6.9%; ACRS 2023 STOP 6d -9.6%; ADMA 2022 STOP 14d -5.9%

## 3. `slow_target_grind` (135 sym / 152 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACN, AEE, AFG, AFL, AGNC, ALLE, AMT, AON, ARE, ARW, ATO, ATR, AWK, AX, BA, BAX, BKNG, BN, BNY
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d) 2020-01-21; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24; AFL TARGET 315d +10.0% (~0.03%/d) 2017-04-28; AGNC TARGET 176d +10.0% (~0.06%/d) 2016-10-25

## 4. `fat_stops` (112 sym / 129 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABUS, ACRS, ADMA, ADNT, ADPT, AEHR, AGX, AGYS, AHT, AI, ALLE, ALNT, AMWL, ANF, AOSL, APLD, APPS, APYX, BABA

## 5. `winner_peak_giveback` (15 sym / 16 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ALNT, AVAV, CECO, DGII, DOCU, ESEA, F, IRMD, KEX, LINC, LMAT, MWA, SENEA, SPXC, W
- **Evidence:** ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); CECO peak~22% -> exit +10.0% (giveback~12pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (51 sym / 1737 trades) — direction: expand, confidence: medium, 59.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1737 trades, 59%, high) vs stop_ok_never_worked → hold (975 trades, 33%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1737/2945 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 975/2945 STOPs (33%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2017-07-31 then back above entry/15d; AAON STOP 2019-08-09 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; AAON MFE~0.0% STOP; AAON MFE~0.0% STOP; AAON MFE~1.3% STOP; ABBV MFE~0.0% STOP; AAP MFE~0.9% STOP

## 2. `target_pct_tension_expand_vs_contract` (58 sym / 1515 trades) — direction: expand, confidence: medium, 52.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1515 trades, 52%, high) vs target_contract_approach_fail → contract (923 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1515/2886 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 923/6931 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +10% in 15d after TARGET; AA +21% in 15d after TARGET; ABBNY +8% in 15d after TARGET; ABM +7% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +16% in 15d after TARGET | [B contract] AA reached 86% of target then STOP; AA reached 82% of target then STOP; AAON reached 92% of target then STOP; AAON reached 52% of target then STOP; ABBNY reached 73% of target then STOP; AAP reached 50% of target then STOP

## 3. `band_tighten_weak_fill` (634 sym / 1043 trades) — direction: tighten, confidence: high, 15.0% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1043/6931 trades (15%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACLS, ACN, ACRS, ADI, ADM, ADMA, ADNT, ADSK
- **Evidence:** AAMI MFE~1.6% STOP 8d; AAON MFE~0.0% STOP 2d; AAON MFE~0.0% STOP 3d; ABBV MFE~0.0% STOP 0d; AAP MFE~0.9% STOP 5d; A MFE~0.0% STOP 1d

## 4. `target_contract_slow_hold` (135 sym / 152 trades) — direction: contract, confidence: low, 5.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 152/2886 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACN, AEE, AFG, AFL, AGNC, ALLE, AMT, AON, ARE, ARW, ATO, ATR, AWK, AX, BA, BAX, BKNG, BN, BNY
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d); ACN TARGET 107d +10.0% (~0.09%/d); AEE TARGET 169d +10.0% (~0.06%/d); AFL TARGET 315d +10.0% (~0.03%/d); AGNC TARGET 176d +10.0% (~0.06%/d); ALLE TARGET 100d +10.0% (~0.10%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
