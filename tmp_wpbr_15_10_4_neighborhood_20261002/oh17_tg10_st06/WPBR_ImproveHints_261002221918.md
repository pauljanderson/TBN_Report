# WPBR Improve Hints — stamp `261002221918`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (221 sym / 262 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, AAPL, ABCB, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AEM, AFRM, ALDX, ALEC, ALL, ALLE, ALNY, AMKR
- **Evidence:** AAMI TARGET 2015-04-07 -> STOP 2022-01-20 (8d); AAPL TARGET 2021-12-09 -> STOP 2026-07-31 (4d); ABCB TARGET 2013-05-06 -> STOP 2015-08-26 (9d); ACRS TARGET 2017-02-24 -> STOP 2020-11-16 (3d); ACRS TARGET 2025-03-24 -> STOP 2025-06-18 (6d)

## 2. `slow_target_grind` (217 sym / 280 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, ADI, AEE, AEP, AFG, AFL, AGM, AGNC, AIT, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AWK
- **Evidence:** ACGL TARGET 134d +10.0% (~0.07%/d) 2012-10-05; ACN TARGET 145d +10.0% (~0.07%/d) 2013-12-23; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; ADI TARGET 150d +10.0% (~0.07%/d) 2013-08-01; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24

## 3. `fat_stops` (163 sym / 207 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACRS, ADMA, ADNT, ADPT, AEHR, AHCO, AHT, AI, ALEC, ALGN, ALL, ALLE, ALNT, AMP, AMRC, AMTX, AMWL, ANIP, ANNX

## 4. `false_start_2022_2023` (78 sym / 89 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGO, AI, AMTX, APLD, AVGO, BG, BILI, CB, CCL, CGC, CI, COIN, CPT, CUBE
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADPT 2022 STOP 8d -17.1%; ADMA 2022 STOP 15d -8.8%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (21 sym / 22 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ALNT, AVAV, AX, CECO, DGII, ESEA, F, FIVN, FSLR, IRMD, JMIA, KEX, KINS, LMB, MIDD, MOD, MWA, RBC, SENEA
- **Evidence:** AGX peak~24% -> exit +10.0% (giveback~14pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); AX peak~28% -> exit +14.0% (giveback~14pp, 92d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (60 sym / 1465 trades) — direction: expand, confidence: medium, 51.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1465 trades, 51%, high) vs target_contract_approach_fail → contract (703 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1465/2869 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 703/5528 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +21% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +9% in 15d after TARGET; AAL +13% in 15d after TARGET; ABBNY +8% in 15d after TARGET | [B contract] A reached 66% of target then STOP; AAON reached 92% of target then STOP; AAL reached 92% of target then STOP; AAPL reached 81% of target then STOP; ABBNY reached 73% of target then STOP; AAT reached 74% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (60 sym / 720 trades) — direction: expand, confidence: medium, 39.8% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (720 trades, 40%, high) vs stop_ok_never_worked → hold (440 trades, 24%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 720/1809 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 440/1809 STOPs (24%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABR, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADMA, ADNT, ADSK, AEE
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; AAPL STOP 2013-04-18 then back above entry/15d; ACA STOP 2023-10-27 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; ABCB MFE~0.7% STOP; ABR MFE~1.9% STOP

## 3. `band_tighten_weak_fill` (308 sym / 377 trades) — direction: tighten, confidence: low, 6.8% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 377/5528 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGO, AI, AIT, AKTS, ALDX, ALEC, ALL, ALNY
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 1d; AAPL MFE~3.0% STOP 4d; ABCB MFE~2.6% STOP 9d; ABCB MFE~0.7% STOP 3d

## 4. `target_contract_slow_hold` (217 sym / 280 trades) — direction: contract, confidence: medium, 9.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 280/2869 TARGET exits (10%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, ADI, AEE, AEP, AFG, AFL, AGM, AGNC, AIT, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AWK
- **Evidence:** ACGL TARGET 134d +10.0% (~0.07%/d); ACN TARGET 145d +10.0% (~0.07%/d); ACN TARGET 107d +10.0% (~0.09%/d); ADI TARGET 150d +10.0% (~0.07%/d); AEE TARGET 169d +10.0% (~0.06%/d); AEE TARGET 339d +10.0% (~0.03%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
