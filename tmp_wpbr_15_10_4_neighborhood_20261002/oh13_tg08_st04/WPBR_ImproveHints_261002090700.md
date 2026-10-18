# WPBR Improve Hints — stamp `261002090700`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (390 sym / 525 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AAT, ABCB, ABR, ACA, ACAD, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AEP, AES, AFRM, AGM, AGNC, AGX, AKAM
- **Evidence:** A TARGET 2011-06-30 -> STOP 2011-08-05 (1d); ABCB TARGET 2010-05-28 -> STOP 2012-05-23 (1d); ABR TARGET 2013-03-12 -> STOP 2013-04-18 (1d); ACA TARGET 2023-08-31 -> STOP 2024-08-02 (10d); AAT TARGET 2013-10-01 -> STOP 2016-01-20 (0d)

## 2. `false_start_2022_2023` (158 sym / 178 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADMA, ADPT, AEHR, AES, AGM, AI, AIT, AJG, ALB, AMP, AMTX, AMWL, AN, AOS, AOUT, APLD, ASMIY
- **Evidence:** AAMI 2022 STOP 8d -6.4%; ACRS 2023 STOP 6d -10.5%; ADMA 2022 STOP 15d -6.9%; ADPT 2022 STOP 8d -15.4%; ADBE 2022 STOP 15d -5.3%

## 3. `fat_stops` (124 sym / 151 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AGYS, AI, ALGN, ALLE, ALNT, AMRC, AMWL, ANF, AOSL, APLD, APPS

## 4. `slow_target_grind` (123 sym / 137 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, ADP, AEE, AFG, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, BALL, BF.B, BKHYY, BN, BNY, BRK.B, BRO
- **Evidence:** ACN TARGET 141d +8.0% (~0.06%/d) 2013-12-19; ACGL TARGET 130d +8.0% (~0.06%/d) 2012-10-01; ADP TARGET 125d +8.0% (~0.06%/d) 2019-09-05; AEE TARGET 148d +8.0% (~0.05%/d) 2019-09-03; ALL TARGET 140d +8.0% (~0.06%/d) 2019-11-26

## 5. `winner_peak_giveback` (12 sym / 13 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, AVAV, CECO, CEG, DGII, DRS, ESE, LINC, LMAT, MMS, MWA, TGB
- **Evidence:** AGX peak~24% -> exit +8.3% (giveback~16pp, 17d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +8.0% (giveback~12pp, 33d, TARGET); CEG peak~19% -> exit +8.0% (giveback~11pp, 20d, TARGET); CECO peak~22% -> exit +8.0% (giveback~14pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (59 sym / 1867 trades) — direction: expand, confidence: medium, 52.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1867 trades, 53%, high) vs target_contract_approach_fail → contract (859 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1867/3546 TARGET exits (53%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 859/7000 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AA +23% in 15d after TARGET; ABM +9% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAL +17% in 15d after TARGET | [B contract] A reached 83% of target then STOP; AAON reached 60% of target then STOP; AAON reached 84% of target then STOP; AAON reached 64% of target then STOP; AAMI reached 56% of target then STOP; ABBNY reached 92% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (52 sym / 1260 trades) — direction: expand, confidence: medium, 52.7% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1260 trades, 53%, high) vs stop_ok_never_worked → hold (813 trades, 34%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1260/2389 STOP exits (53%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 813/2389 STOPs (34%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI, ADM
- **Evidence:** [A expand] ABBV STOP 2015-02-04 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d; AAON STOP 2024-06-04 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d | [B hold] A MFE~0.0% STOP; ABBV MFE~0.0% STOP; AAON MFE~0.0% STOP; AAON MFE~1.3% STOP; AAMI MFE~1.6% STOP; ABM MFE~1.0% STOP

## 3. `band_tighten_weak_fill` (542 sym / 815 trades) — direction: tighten, confidence: medium, 11.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 815/7000 trades (12%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ACLS, ACN, ACRS, ADM, ADMA, ADSK, AEHR, AEIS, AGM, AGNC
- **Evidence:** A MFE~0.0% STOP 1d; ABBV MFE~0.0% STOP 0d; AAON MFE~0.0% STOP 2d; AAMI MFE~1.6% STOP 8d; ABM MFE~1.0% STOP 14d; ABCB MFE~0.3% STOP 1d

## 4. `target_contract_slow_hold` (123 sym / 137 trades) — direction: contract, confidence: low, 3.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 137/3546 TARGET exits (4%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, ADP, AEE, AFG, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, BALL, BF.B, BKHYY, BN, BNY, BRK.B, BRO
- **Evidence:** ACN TARGET 141d +8.0% (~0.06%/d); ACGL TARGET 130d +8.0% (~0.06%/d); ADP TARGET 125d +8.0% (~0.06%/d); AEE TARGET 148d +8.0% (~0.05%/d); ALL TARGET 140d +8.0% (~0.06%/d); ALLE TARGET 100d +8.0% (~0.08%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
