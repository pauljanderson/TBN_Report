# WPBR Improve Hints — stamp `261002205518`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (342 sym / 442 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AA, AAMI, ABM, ABUS, ACAD, ACN, ACRS, ADI, ADPT, ADSK, AEHR, AEIS, AEM, AGM, AGX, ALDX, ALEC, ALL, ALLE, AMAT
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); AAMI TARGET 2015-04-07 -> STOP 2022-01-20 (8d); ABM TARGET 2016-11-11 -> STOP 2021-07-02 (10d); ABUS TARGET 2014-04-22 -> STOP 2014-11-05 (0d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d)

## 2. `false_start_2022_2023` (155 sym / 175 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AGO, AI, AIT, AJG, ALB, AMKR, AMP, AMTX, AOS, AOUT
- **Evidence:** AA 2022 STOP 10d -9.8%; AAMI 2022 STOP 8d -5.5%; ACRS 2023 STOP 6d -9.6%; ACLS 2022 STOP 9d -6.9%; ADPT 2022 STOP 8d -14.5%

## 3. `slow_target_grind` (126 sym / 140 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACN, AEE, AFG, AFL, AGNC, ALLE, AMT, AON, ARE, ARW, ATO, ATR, AWK, AX, BAX, BKNG, BN, BNY, BRK.B
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d) 2020-01-21; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24; AFL TARGET 315d +10.0% (~0.03%/d) 2017-04-28; AFG TARGET 350d +10.0% (~0.03%/d) 2013-01-17

## 4. `fat_stops` (90 sym / 102 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACRS, ADMA, ADNT, ADPT, AEHR, AGX, AHT, AI, ALLE, ALNT, AOSL, APLD, APPS, APYX, BABA, BBIO, BBWI, BXMT, CASH, CBRE

## 5. `winner_peak_giveback` (11 sym / 12 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ALNT, AVAV, CECO, DGII, ESEA, F, IRMD, KEX, MWA, SENEA, W
- **Evidence:** ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); CECO peak~22% -> exit +10.0% (giveback~12pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (54 sym / 1444 trades) — direction: expand, confidence: medium, 58.6% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1444 trades, 59%, high) vs stop_ok_never_worked → hold (797 trades, 32%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1444/2463 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 797/2463 STOPs (32%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAPL STOP 2013-04-17 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2017-07-31 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAON MFE~0.0% STOP; AAT MFE~1.9% STOP; AAT MFE~0.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (58 sym / 1288 trades) — direction: expand, confidence: medium, 52.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1288 trades, 52%, high) vs target_contract_approach_fail → contract (786 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1288/2468 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 786/5872 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +21% in 15d after TARGET; ABBNY +8% in 15d after TARGET; AAT +7% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +13% in 15d after TARGET | [B contract] A reached 66% of target then STOP; AA reached 82% of target then STOP; AAPL reached 81% of target then STOP; AAON reached 92% of target then STOP; ABBNY reached 73% of target then STOP; AAT reached 68% of target then STOP

## 3. `band_tighten_weak_fill` (560 sym / 848 trades) — direction: tighten, confidence: medium, 14.4% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 848/5872 trades (14%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACLS, ACN, ACRS, ADI, ADMA, ADNT, ADSK, AEHR
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; AAON MFE~0.0% STOP 2d; AAT MFE~1.9% STOP 10d; AAT MFE~0.0% STOP 1d

## 4. `target_contract_slow_hold` (126 sym / 140 trades) — direction: contract, confidence: low, 5.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 140/2468 TARGET exits (6%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACN, AEE, AFG, AFL, AGNC, ALLE, AMT, AON, ARE, ARW, ATO, ATR, AWK, AX, BAX, BKNG, BN, BNY, BRK.B
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d); ACN TARGET 107d +10.0% (~0.09%/d); AEE TARGET 169d +10.0% (~0.06%/d); AFL TARGET 315d +10.0% (~0.03%/d); AFG TARGET 350d +10.0% (~0.03%/d); AGNC TARGET 176d +10.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
