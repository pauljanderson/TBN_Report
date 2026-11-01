# WPBR Improve Hints — stamp `261002120010`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (295 sym / 372 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAPL, ABCB, ABNB, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEIS, AEM, AFRM, AGYS, ALB, ALDX, ALEC, ALL, ALLE, ALNY
- **Evidence:** ABNB TARGET 2021-09-24 -> STOP 2021-12-01 (5d); AAPL TARGET 2024-08-16 -> STOP 2026-07-31 (4d); ACAD TARGET 2011-03-28 -> STOP 2011-05-23 (4d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACLS TARGET 2026-08-06 -> STOP 2026-09-14 (6d)

## 2. `slow_target_grind` (237 sym / 312 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABCB, ACGL, ACN, ADI, AEE, AEP, AFG, AFL, AGM, AGNC, AIT, ALL, ALLE, AMT, AMZN, ANDE, AON, ARE, ARW, ATO
- **Evidence:** ABCB TARGET 122d +10.0% (~0.08%/d) 2012-09-21; ACN TARGET 145d +10.0% (~0.07%/d) 2013-12-23; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; ADI TARGET 150d +10.0% (~0.07%/d) 2013-08-01; ACGL TARGET 134d +10.0% (~0.07%/d) 2012-10-05

## 3. `fat_stops` (208 sym / 279 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABG, ABR, ABUS, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AGYS, AHCO, AHT, AI, ALEC, ALGN, ALL, ALLE, ALNT

## 4. `false_start_2022_2023` (117 sym / 129 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGM, AGO, AI, AMH, AMP, AMTX, AMWL, AN, APLD, APPS, AVGO, BG, BILI, BIO
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADMA 2022 STOP 15d -8.8%; ADPT 2022 STOP 8d -17.1%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (28 sym / 29 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ALNT, AVAV, AX, CECO, DGII, DOCU, ESE, ESEA, F, FIVN, FRD, FSLR, IRMD, JMIA, KEX, KINS, LINC, LMAT, LMB
- **Evidence:** AGX peak~24% -> exit +10.0% (giveback~14pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); AX peak~28% -> exit +14.0% (giveback~14pp, 92d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (55 sym / 1832 trades) — direction: expand, confidence: medium, 51.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1832 trades, 52%, high) vs target_contract_approach_fail → contract (863 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1832/3550 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 863/6933 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AA +10% in 15d after TARGET; AA +21% in 15d after TARGET; ABBNY +8% in 15d after TARGET; ABM +7% in 15d after TARGET; AAT +7% in 15d after TARGET; AAL +15% in 15d after TARGET | [B contract] AA reached 86% of target then STOP; A reached 66% of target then STOP; ABBNY reached 73% of target then STOP; AAON reached 92% of target then STOP; AAON reached 52% of target then STOP; ABNB reached 77% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (61 sym / 924 trades) — direction: expand, confidence: medium, 40.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (924 trades, 40%, high) vs stop_ok_never_worked → hold (588 trades, 26%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 924/2309 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 588/2309 STOPs (25%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADMA, ADNT
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAON STOP 2023-10-19 then back above entry/15d; AAON STOP 2024-06-10 then back above entry/15d; ABNB STOP 2021-12-01 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAON MFE~1.3% STOP; ABR MFE~1.9% STOP; AAT MFE~1.7% STOP

## 3. `band_tighten_weak_fill` (398 sym / 530 trades) — direction: tighten, confidence: low, 7.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 530/6933 trades (8%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGI, AGM, AGO, AGYS, AHT, AI, AIR, AIT
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 1d; AAPL MFE~3.0% STOP 4d; ABR MFE~1.9% STOP 11d; ACLS MFE~0.3% STOP 8d

## 4. `target_contract_slow_hold` (237 sym / 312 trades) — direction: contract, confidence: medium, 8.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 312/3550 TARGET exits (9%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABCB, ACGL, ACN, ADI, AEE, AEP, AFG, AFL, AGM, AGNC, AIT, ALL, ALLE, AMT, AMZN, ANDE, AON, ARE, ARW, ATO
- **Evidence:** ABCB TARGET 122d +10.0% (~0.08%/d); ACN TARGET 145d +10.0% (~0.07%/d); ACN TARGET 107d +10.0% (~0.09%/d); ADI TARGET 150d +10.0% (~0.07%/d); ACGL TARGET 134d +10.0% (~0.07%/d); AEE TARGET 169d +10.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
