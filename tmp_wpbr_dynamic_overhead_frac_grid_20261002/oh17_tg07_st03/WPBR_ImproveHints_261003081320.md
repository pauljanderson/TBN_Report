# WPBR Improve Hints — stamp `261003081320`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `small_target_wins` (952 sym / 2912 trades)
- **Lever:** target_pct / expansion / partial_exit
- **Suggestion:** Many small TARGET wins — consider higher target or partial scale-out.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM

## 2. `post_target_quick_stop` (359 sym / 446 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, AAON, ABM, ACAD, ACLS, ACN, ACRS, ADI, ADPT, ADSK, AEHR, AEIS, AEM, AGX, AKAM, ALB, ALDX, ALEC, ALGN, ALL
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); AAON TARGET 2020-02-27 -> STOP 2020-03-09 (10d); ABM TARGET 2016-11-10 -> STOP 2021-07-02 (10d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACRS TARGET 2023-07-13 -> STOP 2023-10-23 (6d)

## 3. `false_start_2022_2023` (127 sym / 143 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADPT, AEHR, AFRM, AGM, AGO, AI, AIT, AJG, ALB, AMKR, AMTX, AOUT, APLD, ASMIY, AVGO, AZO, BBIO
- **Evidence:** AAMI 2022 STOP 8d -5.5%; ACRS 2023 STOP 6d -9.6%; ADPT 2022 STOP 8d -14.5%; ADBE 2022 STOP 15d -4.3%; AEHR 2022 STOP 4d -6.0%

## 4. `fat_stops` (72 sym / 85 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACRS, ACU, ADNT, ADPT, AEHR, AGX, AI, ALLE, ALNT, AOSL, APPS, APYX, BBIO, BXMT, CBRE, CDE, CGC, DLTR, DXCM, EGO

## 5. `slow_target_grind` (62 sym / 64 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AFG, ATR, BALL, BF.B, BKNG, BN, BRK.B, BXP, CB, CCEP, CECO, CHD, CINF, CNP, CPT, CTAS, DUK, EVRG, FDX, GE
- **Evidence:** AFG TARGET 337d +7.0% (~0.02%/d) 2013-01-04; ATR TARGET 105d +7.0% (~0.07%/d) 2011-01-18; BALL TARGET 110d +7.0% (~0.06%/d) 2013-03-27; BF.B TARGET 103d +7.0% (~0.07%/d) 2012-04-02; BKNG TARGET 129d +7.0% (~0.05%/d) 2023-12-11

## 6. `winner_peak_giveback` (9 sym / 9 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AVAV, CECO, CEG, DGII, KINS, MMS, MWA, SSNC, TSSI
- **Evidence:** AVAV peak~20% -> exit +7.6% (giveback~13pp, 33d, GAP_UP); CEG peak~19% -> exit +7.0% (giveback~12pp, 20d, TARGET); CECO peak~22% -> exit +7.0% (giveback~15pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP); KINS peak~17% -> exit +7.0% (giveback~10pp, 16d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (63 sym / 1499 trades) — direction: expand, confidence: medium, 51.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1499 trades, 52%, high) vs target_contract_approach_fail → contract (706 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1499/2912 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 706/5693 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAON, AAP, AAPL, ABCB, ABG, ABM, ABT, ABUS, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADMA
- **Evidence:** [A expand] AA +24% in 15d after TARGET; AAL +18% in 15d after TARGET; AAL +20% in 15d after TARGET; AAL +16% in 15d after TARGET; AAPL +6% in 15d after TARGET; AAPL +6% in 15d after TARGET | [B contract] AAL reached 83% of target then STOP; AAON reached 69% of target then STOP; AAON reached 61% of target then STOP; AAP reached 72% of target then STOP; ABCB reached 87% of target then STOP; ABCB reached 51% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (49 sym / 1145 trades) — direction: expand, confidence: medium, 58.7% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1145 trades, 59%, high) vs stop_ok_never_worked → hold (757 trades, 39%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1145/1949 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 757/1949 STOPs (39%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AAL STOP 2013-02-04 then back above entry/15d; AAL STOP 2013-04-03 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAT STOP 2012-05-18 then back above entry/15d; AAT STOP 2019-04-17 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.9% STOP; AAT MFE~0.0% STOP; AAON MFE~0.0% STOP

## 3. `band_tighten_weak_fill` (534 sym / 797 trades) — direction: tighten, confidence: medium, 14.0% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 797/5693 trades (14%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACLS, ACN, ACRS, ADI, ADMA, ADNT, ADSK, AEHR
- **Evidence:** A MFE~0.0% STOP 1d; AAL MFE~2.1% STOP 12d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; AAT MFE~1.9% STOP 10d; AAT MFE~0.0% STOP 1d

## 4. `target_contract_slow_hold` (62 sym / 64 trades) — direction: contract, confidence: low, 2.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 64/2912 TARGET exits (2%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AFG, ATR, BALL, BF.B, BKNG, BN, BRK.B, BXP, CB, CCEP, CECO, CHD, CINF, CNP, CPT, CTAS, DUK, EVRG, FDX, GE
- **Evidence:** AFG TARGET 337d +7.0% (~0.02%/d); ATR TARGET 105d +7.0% (~0.07%/d); BALL TARGET 110d +7.0% (~0.06%/d); BF.B TARGET 103d +7.0% (~0.07%/d); BKNG TARGET 129d +7.0% (~0.05%/d); BN TARGET 127d +7.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
