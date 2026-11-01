# WPBR Improve Hints — stamp `261002090700`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (445 sym / 591 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AAON, AAP, AAT, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ADPT, AEG, AEHR, AEIS, AEM, AES, AGI, AGM, AGX
- **Evidence:** A TARGET 2011-06-30 -> STOP 2011-08-05 (1d); AAON TARGET 2019-06-28 -> STOP 2019-08-09 (3d); AAON TARGET 2020-02-27 -> STOP 2020-03-09 (10d); AAP TARGET 2015-09-30 -> STOP 2021-10-13 (5d); ABR TARGET 2013-03-12 -> STOP 2013-04-17 (0d)

## 2. `false_start_2022_2023` (179 sym / 204 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADMA, ADPT, ADSK, AEHR, AES, AFRM, AGM, AGO, AI, AIT, AJG, ALB, AMH, AMKR, AMP, AMTX, AMWL
- **Evidence:** AAMI 2022 STOP 8d -5.5%; ACRS 2023 STOP 6d -9.6%; ADPT 2022 STOP 8d -14.5%; ADMA 2022 STOP 14d -5.9%; ADSK 2022 STOP 11d -11.2%

## 3. `fat_stops` (100 sym / 117 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ACRS, ADMA, ADNT, ADPT, AEHR, AGX, AGYS, AI, ALLE, ALNT, AMWL, ANF, AOSL, APLD, APPS, APYX, BABA, BBIO, BXMT

## 4. `slow_target_grind` (91 sym / 96 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ADP, AEE, AFG, ALLE, AON, ATO, ATR, AX, BALL, BF.B, BN, BNY, BRK.B, BRO, CACI, CB, CECO, CHD, CINF, CLX
- **Evidence:** ADP TARGET 125d +8.0% (~0.06%/d) 2019-09-05; AEE TARGET 148d +8.0% (~0.05%/d) 2019-09-03; ALLE TARGET 100d +8.0% (~0.08%/d) 2015-07-30; AFG TARGET 342d +8.0% (~0.02%/d) 2013-01-09; AON TARGET 102d +8.0% (~0.08%/d) 2013-09-17

## 5. `winner_peak_giveback` (10 sym / 11 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AVAV, CECO, CEG, DGII, DRS, LINC, LMAT, MMS, MWA, TGB
- **Evidence:** AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +8.0% (giveback~12pp, 33d, TARGET); CEG peak~19% -> exit +8.0% (giveback~11pp, 20d, TARGET); CECO peak~22% -> exit +8.0% (giveback~14pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (51 sym / 1573 trades) — direction: expand, confidence: medium, 59.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1573 trades, 59%, high) vs stop_ok_never_worked → hold (979 trades, 37%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1573/2658 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 979/2658 STOPs (37%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2019-08-09 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d; AAON STOP 2024-06-04 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; AAON MFE~0.0% STOP; AAON MFE~0.0% STOP; AAON MFE~1.3% STOP; ABBV MFE~0.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (57 sym / 1741 trades) — direction: expand, confidence: medium, 53.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1741 trades, 53%, high) vs target_contract_approach_fail → contract (897 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1741/3276 TARGET exits (53%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 897/6988 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] AA +23% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +18% in 15d after TARGET | [B contract] A reached 83% of target then STOP; AAMI reached 56% of target then STOP; AAON reached 60% of target then STOP; AAON reached 84% of target then STOP; AAON reached 64% of target then STOP; ABBNY reached 92% of target then STOP

## 3. `band_tighten_weak_fill` (635 sym / 1050 trades) — direction: tighten, confidence: high, 15.0% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1050/6988 trades (15%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACLS, ACN, ACRS, ADI, ADM, ADMA, ADNT, ADSK
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; AAON MFE~0.0% STOP 2d; AAON MFE~0.0% STOP 3d; ABBV MFE~0.0% STOP 0d; AAP MFE~0.9% STOP 5d

## 4. `target_contract_slow_hold` (91 sym / 96 trades) — direction: contract, confidence: low, 2.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 96/3276 TARGET exits (3%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ADP, AEE, AFG, ALLE, AON, ATO, ATR, AX, BALL, BF.B, BN, BNY, BRK.B, BRO, CACI, CB, CECO, CHD, CINF, CLX
- **Evidence:** ADP TARGET 125d +8.0% (~0.06%/d); AEE TARGET 148d +8.0% (~0.05%/d); ALLE TARGET 100d +8.0% (~0.08%/d); AFG TARGET 342d +8.0% (~0.02%/d); AON TARGET 102d +8.0% (~0.08%/d); ATO TARGET 153d +8.0% (~0.05%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
