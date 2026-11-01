# WPBR Improve Hints — stamp `261002204242`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (318 sym / 406 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ACAD, ACLS, ACRS, ADPT, ADSK, AEHR, AEIS, AEP, AFRM, AGM, AGNC, AGX, AKAM, ALDX, ALEC, ALL, ALLE, ALNY, AMAT
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); ACRS TARGET 2025-03-24 -> STOP 2025-06-17 (5d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACLS TARGET 2023-05-26 -> STOP 2024-11-13 (1d); ADPT TARGET 2021-02-09 -> STOP 2021-03-03 (7d)

## 2. `slow_target_grind` (136 sym / 156 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, ADP, AEE, AFG, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB, AWK, AX, BALL, BAX
- **Evidence:** ACGL TARGET 130d +9.0% (~0.07%/d) 2012-10-01; ACN TARGET 142d +9.0% (~0.06%/d) 2013-12-20; ADP TARGET 126d +9.0% (~0.07%/d) 2019-09-06; AEE TARGET 149d +9.0% (~0.06%/d) 2019-09-04; AFG TARGET 343d +9.0% (~0.03%/d) 2013-01-10

## 3. `false_start_2022_2023` (133 sym / 149 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADMA, ADPT, AEHR, AGM, AI, AIT, AJG, ALB, AMP, AMTX, AOS, AOUT, APLD, ASMIY, AVGO, AZO, BBIO
- **Evidence:** AAMI 2022 STOP 8d -6.4%; ACRS 2023 STOP 6d -10.5%; ADPT 2022 STOP 8d -15.4%; ADMA 2022 STOP 15d -6.9%; ADBE 2022 STOP 15d -5.3%

## 4. `fat_stops` (101 sym / 120 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACLS, ACRS, ADMA, ADNT, ADPT, AEHR, AI, ALGN, ALLE, ALNT, AMRC, AMWL, AOSL, APLD, APPS, APYX, BBIO, BLDR, BNTX

## 5. `winner_peak_giveback` (9 sym / 10 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABUS, AGX, AVAV, CECO, DGII, DRS, ESEA, MWA, TGB
- **Evidence:** ABUS peak~20% -> exit +9.0% (giveback~11pp, 21d, TARGET); AGX peak~24% -> exit +9.0% (giveback~15pp, 17d, TARGET); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +9.0% (giveback~11pp, 33d, TARGET); CECO peak~22% -> exit +9.0% (giveback~13pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (61 sym / 1484 trades) — direction: expand, confidence: medium, 51.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1484 trades, 52%, high) vs target_contract_approach_fail → contract (789 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1484/2864 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 789/5898 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACRS, ACU
- **Evidence:** [A expand] AA +22% in 15d after TARGET; ABBNY +7% in 15d after TARGET; AAT +7% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +14% in 15d after TARGET | [B contract] A reached 74% of target then STOP; AAPL reached 90% of target then STOP; ABBNY reached 81% of target then STOP; AAON reached 55% of target then STOP; AAL reached 64% of target then STOP; ACA reached 93% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (54 sym / 1128 trades) — direction: expand, confidence: medium, 52.7% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1128 trades, 53%, high) vs stop_ok_never_worked → hold (664 trades, 31%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1128/2139 STOP exits (53%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 664/2139 STOPs (31%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAPL STOP 2013-04-17 then back above entry/15d; AAT STOP 2012-05-23 then back above entry/15d; AAT STOP 2019-04-22 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.9% STOP; AAT MFE~1.7% STOP; AAT MFE~0.0% STOP

## 3. `band_tighten_weak_fill` (480 sym / 660 trades) — direction: tighten, confidence: medium, 11.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 660/5898 trades (11%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ACLS, ACN, ACRS, ADMA, ADSK, AEHR, AEIS, AGM, AGNC, AGO
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; AAT MFE~1.9% STOP 15d; AAT MFE~0.0% STOP 6d; AAON MFE~0.0% STOP 2d

## 4. `target_contract_slow_hold` (136 sym / 156 trades) — direction: contract, confidence: low, 5.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 156/2864 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, ADP, AEE, AFG, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB, AWK, AX, BALL, BAX
- **Evidence:** ACGL TARGET 130d +9.0% (~0.07%/d); ACN TARGET 142d +9.0% (~0.06%/d); ADP TARGET 126d +9.0% (~0.07%/d); AEE TARGET 149d +9.0% (~0.06%/d); AFG TARGET 343d +9.0% (~0.03%/d); AGNC TARGET 100d +9.0% (~0.09%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
