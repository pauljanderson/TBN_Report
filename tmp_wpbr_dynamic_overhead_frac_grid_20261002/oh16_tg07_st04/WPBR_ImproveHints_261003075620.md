# WPBR Improve Hints — stamp `261003075620`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `small_target_wins` (985 sym / 3305 trades)
- **Lever:** target_pct / expansion / partial_exit
- **Suggestion:** Many small TARGET wins — consider higher target or partial scale-out.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS

## 2. `post_target_quick_stop` (331 sym / 423 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ACAD, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AEP, AFRM, AGX, AKAM, ALB, ALDX, ALEC, ALGN, ALL, ALLE, ALNY
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACRS TARGET 2023-07-13 -> STOP 2023-10-23 (6d); ACRS TARGET 2025-03-24 -> STOP 2025-06-17 (5d); ACLS TARGET 2018-10-17 -> STOP 2018-10-29 (5d)

## 3. `false_start_2022_2023` (128 sym / 143 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADPT, AEHR, AGM, AI, AIT, AJG, ALB, AMP, AMTX, AOS, AOUT, APLD, ASMIY, AVGO, AZO, BBIO, BG
- **Evidence:** AAMI 2022 STOP 8d -6.4%; ACRS 2023 STOP 6d -10.5%; ADPT 2022 STOP 8d -15.4%; ADBE 2022 STOP 15d -5.3%; AEHR 2022 STOP 4d -7.0%

## 4. `fat_stops` (91 sym / 110 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACLS, ACRS, ACU, ADNT, ADPT, AEHR, AI, ALGN, ALLE, ALNT, AMRC, AMWL, AOSL, APLD, APPS, APYX, BBIO, BLDR, BNTX

## 5. `slow_target_grind` (89 sym / 96 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, AFG, ALL, ANDE, ATO, ATR, AWK, AX, BALL, BF.B, BKNG, BN, BRK.B, BXP, CAG, CB, CBOE, CCEP, CE
- **Evidence:** ACGL TARGET 127d +7.0% (~0.06%/d) 2012-09-28; ACN TARGET 110d +7.0% (~0.06%/d) 2013-11-18; AFG TARGET 337d +7.0% (~0.02%/d) 2013-01-04; ALL TARGET 132d +7.0% (~0.05%/d) 2019-11-18; ANDE TARGET 107d +7.0% (~0.07%/d) 2013-07-18

## 6. `winner_peak_giveback` (10 sym / 10 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, AVAV, CECO, CEG, DGII, KINS, MMS, MWA, SSNC, TSSI
- **Evidence:** AGX peak~24% -> exit +8.3% (giveback~16pp, 17d, GAP_UP); AVAV peak~20% -> exit +7.6% (giveback~13pp, 33d, GAP_UP); CEG peak~19% -> exit +7.0% (giveback~12pp, 20d, TARGET); CECO peak~22% -> exit +7.0% (giveback~15pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (63 sym / 1716 trades) — direction: expand, confidence: medium, 51.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1716 trades, 52%, high) vs target_contract_approach_fail → contract (705 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1716/3305 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 705/6064 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAON, AAPL, ABCB, ABG, ABM, ABT, ABUS, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM, ADMA
- **Evidence:** [A expand] AAL +18% in 15d after TARGET; AAL +20% in 15d after TARGET; AAL +16% in 15d after TARGET; AA +24% in 15d after TARGET; ABCB +7% in 15d after TARGET; AAPL +6% in 15d after TARGET | [B contract] AAON reached 69% of target then STOP; AAON reached 61% of target then STOP; AAL reached 83% of target then STOP; ABCB reached 87% of target then STOP; ABCB reached 51% of target then STOP; ABG reached 81% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (50 sym / 977 trades) — direction: expand, confidence: medium, 52.4% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (977 trades, 52%, high) vs stop_ok_never_worked → hold (681 trades, 36%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 977/1864 STOP exits (52%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 681/1864 STOPs (37%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ACAD, ACLS, ACN, ACRS, ACU, ADI, ADMA, ADNT, ADSK
- **Evidence:** [A expand] AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2023-10-19 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d; AAL STOP 2013-02-05 then back above entry/15d; AAL STOP 2013-04-05 then back above entry/15d | [B hold] AAON MFE~0.0% STOP; A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; ABCB MFE~0.7% STOP; AAT MFE~1.9% STOP

## 3. `band_tighten_weak_fill` (486 sym / 680 trades) — direction: tighten, confidence: medium, 11.2% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 680/6064 trades (11%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ACLS, ACN, ACRS, ADMA, ADSK, AEHR, AEIS, AGM, AGNC, AGO
- **Evidence:** AAON MFE~0.0% STOP 2d; A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; AAL MFE~2.1% STOP 13d; ABBV MFE~0.0% STOP 0d; ABCB MFE~0.7% STOP 3d

## 4. `target_contract_slow_hold` (89 sym / 96 trades) — direction: contract, confidence: low, 2.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 96/3305 TARGET exits (3%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, AFG, ALL, ANDE, ATO, ATR, AWK, AX, BALL, BF.B, BKNG, BN, BRK.B, BXP, CAG, CB, CBOE, CCEP, CE
- **Evidence:** ACGL TARGET 127d +7.0% (~0.06%/d); ACN TARGET 110d +7.0% (~0.06%/d); AFG TARGET 337d +7.0% (~0.02%/d); ALL TARGET 132d +7.0% (~0.05%/d); ANDE TARGET 107d +7.0% (~0.07%/d); ATO TARGET 115d +7.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
