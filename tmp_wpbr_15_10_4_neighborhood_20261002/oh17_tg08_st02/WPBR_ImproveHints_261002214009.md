# WPBR Improve Hints — stamp `261002214009`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (412 sym / 513 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AAL, AAMI, AAON, ABM, ABR, ABUS, ACA, ACAD, ACGL, ACLS, ACRS, ADPT, AEG, AEIS, AEM, AFL, AFRM, AGM, AGNC
- **Evidence:** A TARGET 2016-07-20 -> STOP 2019-04-23 (1d); AAMI TARGET 2015-03-20 -> STOP 2022-01-19 (7d); AAON TARGET 2020-02-27 -> STOP 2020-03-09 (10d); ACA TARGET 2023-08-31 -> STOP 2024-08-02 (10d); AAL TARGET 2010-06-11 -> STOP 2010-07-02 (0d)

## 2. `false_start_2022_2023` (157 sym / 181 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACN, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, ALB, AME, AMKR, AMRC, AMTX, AOUT, APH, APLD, ARE
- **Evidence:** AAMI 2022 STOP 7d -4.5%; ACRS 2023 STOP 2d -8.6%; ACN 2022 STOP 7d -4.9%; ADPT 2022 STOP 7d -13.6%; ADMA 2022 STOP 12d -4.9%

## 3. `fat_stops` (68 sym / 81 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACRS, ADMA, ADPT, AEHR, AGX, AI, ALLE, ALNT, AOSL, APPS, APYX, AXP, BABA, BILI, BKNG, BXMT, CBRE, CDE, CGC, DLTR

## 4. `slow_target_grind` (60 sym / 62 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ADP, AEE, AFG, ALLE, AON, ATO, ATR, BALL, BF.B, BN, BNY, BRK.B, BRO, CB, CHD, CINF, CLX, CMCSA, CME, CMS
- **Evidence:** ADP TARGET 125d +8.0% (~0.06%/d) 2019-09-05; AEE TARGET 148d +8.0% (~0.05%/d) 2019-09-03; AFG TARGET 342d +8.0% (~0.02%/d) 2013-01-09; ALLE TARGET 100d +8.0% (~0.08%/d) 2015-07-30; AON TARGET 102d +8.0% (~0.08%/d) 2013-09-17

## 5. `winner_peak_giveback` (8 sym / 9 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AVAV, CECO, CEG, DGII, DRS, MMS, MWA, TGB
- **Evidence:** AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +8.0% (giveback~12pp, 33d, TARGET); CEG peak~19% -> exit +8.0% (giveback~11pp, 20d, TARGET); CECO peak~22% -> exit +8.0% (giveback~14pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (48 sym / 1600 trades) — direction: expand, confidence: medium, 66.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1600 trades, 66%, high) vs stop_ok_never_worked → hold (966 trades, 40%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1600/2413 STOP exits (66%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 966/2413 STOPs (40%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] A STOP 2014-02-14 then back above entry/15d; A STOP 2019-04-23 then back above entry/15d; AAMI STOP 2022-01-19 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d | [B hold] A MFE~0.0% STOP; A MFE~1.1% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAON MFE~0.0% STOP; AAP MFE~0.9% STOP

## 2. `target_pct_tension_expand_vs_contract` (60 sym / 1275 trades) — direction: expand, confidence: medium, 52.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1275 trades, 53%, high) vs target_contract_approach_fail → contract (764 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1275/2426 TARGET exits (53%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 764/5657 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +23% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAT +6% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +15% in 15d after TARGET | [B contract] A reached 83% of target then STOP; AAON reached 60% of target then STOP; AAON reached 84% of target then STOP; AAON reached 53% of target then STOP; ABBNY reached 92% of target then STOP; AAP reached 63% of target then STOP

## 3. `band_tighten_weak_fill` (657 sym / 1064 trades) — direction: tighten, confidence: high, 18.8% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1064/5657 trades (19%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACGL, ACLS, ACN, ACRS, ADBE, ADI, ADMA, ADNT
- **Evidence:** A MFE~0.0% STOP 0d; A MFE~1.1% STOP 1d; AAMI MFE~1.6% STOP 7d; ABBV MFE~0.0% STOP 0d; AAON MFE~0.0% STOP 2d; AAP MFE~0.9% STOP 5d

## 4. `target_contract_slow_hold` (60 sym / 62 trades) — direction: contract, confidence: low, 2.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 62/2426 TARGET exits (3%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ADP, AEE, AFG, ALLE, AON, ATO, ATR, BALL, BF.B, BN, BNY, BRK.B, BRO, CB, CHD, CINF, CLX, CMCSA, CME, CMS
- **Evidence:** ADP TARGET 125d +8.0% (~0.06%/d); AEE TARGET 148d +8.0% (~0.05%/d); AFG TARGET 342d +8.0% (~0.02%/d); ALLE TARGET 100d +8.0% (~0.08%/d); AON TARGET 102d +8.0% (~0.08%/d); ATO TARGET 153d +8.0% (~0.05%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
