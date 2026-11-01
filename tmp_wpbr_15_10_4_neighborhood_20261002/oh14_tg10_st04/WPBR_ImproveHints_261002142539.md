# WPBR Improve Hints — stamp `261002142539`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (338 sym / 439 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACAD, ACLS, ACN, ACRS, ADPT, ADSK, AEIS, AEP, AES, AFRM, AGM, AGNC, AGX, ALDX, ALEC, ALL, ALLE, ALNY, AMD, AMKR
- **Evidence:** ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACRS TARGET 2025-03-24 -> STOP 2025-06-17 (5d); ACLS TARGET 2022-05-27 -> STOP 2022-06-16 (1d); ACN TARGET 2022-06-06 -> STOP 2026-06-22 (0d); ADPT TARGET 2021-02-10 -> STOP 2021-03-03 (7d)

## 2. `slow_target_grind` (165 sym / 200 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, AEE, AFG, AFL, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AWK, AX, BA, BAX
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d) 2020-01-21; ACN TARGET 145d +10.0% (~0.07%/d) 2013-12-23; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; ACGL TARGET 134d +10.0% (~0.07%/d) 2012-10-05; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24

## 3. `false_start_2022_2023` (156 sym / 176 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, AEHR, AES, AGM, AI, AIT, AJG, ALB, AMP, AMTX, AN, AOS, AOUT, APLD, ASMIY
- **Evidence:** AAMI 2022 STOP 8d -6.4%; ACRS 2023 STOP 6d -10.5%; ACLS 2022 STOP 1d -7.2%; ADMA 2022 STOP 15d -6.9%; ADPT 2022 STOP 8d -15.4%

## 4. `fat_stops` (119 sym / 145 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AI, ALGN, ALLE, ALNT, AMRC, AMWL, ANF, AOSL, APLD, APPS, APYX, BBIO

## 5. `winner_peak_giveback` (17 sym / 18 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ALNT, AVAV, CECO, DGII, DOCU, ESE, ESEA, F, IRMD, KEX, KINS, LINC, LMAT, MWA, SENEA, W
- **Evidence:** AGX peak~24% -> exit +10.0% (giveback~14pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); CECO peak~22% -> exit +10.0% (giveback~12pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (60 sym / 1548 trades) — direction: expand, confidence: medium, 52.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1548 trades, 52%, high) vs target_contract_approach_fail → contract (870 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1548/2972 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 870/6511 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +21% in 15d after TARGET; ABBNY +8% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +13% in 15d after TARGET; AAL +5% in 15d after TARGET | [B contract] A reached 66% of target then STOP; ABBNY reached 73% of target then STOP; AAON reached 92% of target then STOP; AAON reached 52% of target then STOP; AAPL reached 81% of target then STOP; AAL reached 58% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (53 sym / 1322 trades) — direction: expand, confidence: medium, 52.8% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1322 trades, 53%, high) vs stop_ok_never_worked → hold (751 trades, 30%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1322/2503 STOP exits (53%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 751/2503 STOPs (30%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI
- **Evidence:** [A expand] ABBV STOP 2015-02-04 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-01 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d | [B hold] A MFE~0.0% STOP; ABBV MFE~0.0% STOP; AAMI MFE~1.6% STOP; AAON MFE~0.0% STOP; AAON MFE~1.3% STOP; ABM MFE~1.0% STOP

## 3. `band_tighten_weak_fill` (521 sym / 743 trades) — direction: tighten, confidence: medium, 11.4% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 743/6511 trades (11%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ACLS, ACN, ACRS, ADMA, ADSK, AEHR, AEIS, AGM, AGNC, AGO
- **Evidence:** A MFE~0.0% STOP 1d; ABBV MFE~0.0% STOP 0d; AAMI MFE~1.6% STOP 8d; AAON MFE~0.0% STOP 2d; AAL MFE~2.1% STOP 13d; ABM MFE~1.0% STOP 14d

## 4. `target_contract_slow_hold` (165 sym / 200 trades) — direction: contract, confidence: low, 6.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 200/2972 TARGET exits (7%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, AEE, AFG, AFL, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AWK, AX, BA, BAX
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d); ACN TARGET 145d +10.0% (~0.07%/d); ACN TARGET 107d +10.0% (~0.09%/d); ACGL TARGET 134d +10.0% (~0.07%/d); AEE TARGET 169d +10.0% (~0.06%/d); AFL TARGET 315d +10.0% (~0.03%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
