# WPBR Improve Hints — stamp `261002135539`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (361 sym / 472 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, ABCB, ACAD, ACLS, ACRS, ADPT, ADSK, AEIS, AEP, AES, AFRM, AGM, AGNC, AGX, AKAM, ALDX, ALEC, ALL, ALLE, ALNY
- **Evidence:** A TARGET 2011-06-30 -> STOP 2011-08-05 (1d); ABCB TARGET 2010-05-28 -> STOP 2012-05-23 (1d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACLS TARGET 2023-05-26 -> STOP 2024-11-13 (1d); ACRS TARGET 2025-03-24 -> STOP 2025-06-17 (5d)

## 2. `false_start_2022_2023` (150 sym / 171 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADMA, ADPT, AEHR, AES, AGM, AI, AIT, AJG, ALB, AMP, AMTX, AN, AOS, AOUT, APLD, ASMIY, AVGO
- **Evidence:** AAMI 2022 STOP 8d -6.4%; ACRS 2023 STOP 6d -10.5%; ADMA 2022 STOP 15d -6.9%; ADPT 2022 STOP 8d -15.4%; AEHR 2022 STOP 4d -7.0%

## 3. `slow_target_grind` (142 sym / 165 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, ADP, AEE, AFG, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB, AWK, AX, BA, BALL
- **Evidence:** ACN TARGET 142d +9.0% (~0.06%/d) 2013-12-20; ADP TARGET 126d +9.0% (~0.07%/d) 2019-09-06; AEE TARGET 149d +9.0% (~0.06%/d) 2019-09-04; ACGL TARGET 130d +9.0% (~0.07%/d) 2012-10-01; AGNC TARGET 100d +9.0% (~0.09%/d) 2016-08-10

## 4. `fat_stops` (112 sym / 138 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AI, ALGN, ALLE, ALNT, AMRC, AMWL, ANF, AOSL, APLD, APPS, APYX, BBIO

## 5. `winner_peak_giveback` (13 sym / 14 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABUS, AGX, AVAV, CECO, DGII, DOCU, DRS, ESE, ESEA, LINC, LMAT, MWA, TGB
- **Evidence:** ABUS peak~20% -> exit +9.0% (giveback~11pp, 21d, TARGET); AGX peak~24% -> exit +9.0% (giveback~15pp, 17d, TARGET); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +9.0% (giveback~11pp, 33d, TARGET); CECO peak~22% -> exit +9.0% (giveback~13pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (60 sym / 1657 trades) — direction: expand, confidence: medium, 52.0% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1657 trades, 52%, high) vs target_contract_approach_fail → contract (856 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1657/3186 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 856/6562 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACRS, ACU
- **Evidence:** [A expand] AA +22% in 15d after TARGET; ABBNY +7% in 15d after TARGET; ABM +8% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +14% in 15d after TARGET | [B contract] AAON reached 55% of target then STOP; AAON reached 57% of target then STOP; ABBNY reached 81% of target then STOP; A reached 74% of target then STOP; AAPL reached 90% of target then STOP; ABM reached 78% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (53 sym / 1250 trades) — direction: expand, confidence: medium, 52.6% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1250 trades, 53%, high) vs stop_ok_never_worked → hold (755 trades, 32%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1250/2375 STOP exits (53%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 755/2375 STOPs (32%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d; AAON STOP 2024-06-04 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; AAON MFE~0.0% STOP; AAON MFE~1.3% STOP; ABBV MFE~0.0% STOP; A MFE~0.0% STOP; ABM MFE~1.0% STOP

## 3. `band_tighten_weak_fill` (525 sym / 750 trades) — direction: tighten, confidence: medium, 11.4% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 750/6562 trades (11%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ACLS, ACN, ACRS, ADMA, ADSK, AEHR, AEIS, AGM, AGNC, AGO
- **Evidence:** AAMI MFE~1.6% STOP 8d; AAON MFE~0.0% STOP 2d; ABBV MFE~0.0% STOP 0d; A MFE~0.0% STOP 1d; ABM MFE~1.0% STOP 14d; AAL MFE~2.1% STOP 13d

## 4. `target_contract_slow_hold` (142 sym / 165 trades) — direction: contract, confidence: low, 5.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 165/3186 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, ADP, AEE, AFG, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB, AWK, AX, BA, BALL
- **Evidence:** ACN TARGET 142d +9.0% (~0.06%/d); ADP TARGET 126d +9.0% (~0.07%/d); AEE TARGET 149d +9.0% (~0.06%/d); ACGL TARGET 130d +9.0% (~0.07%/d); AGNC TARGET 100d +9.0% (~0.09%/d); ALLE TARGET 100d +9.0% (~0.09%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
