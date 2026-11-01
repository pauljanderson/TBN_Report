# WPBR Improve Hints — stamp `261002090700`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (319 sym / 405 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AAPL, ABCB, ABNB, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AEM, AFRM, AGI, AGYS, AKAM, ALB
- **Evidence:** A TARGET 2011-06-30 -> STOP 2011-08-05 (1d); ABNB TARGET 2021-09-23 -> STOP 2021-12-01 (5d); AAPL TARGET 2024-08-13 -> STOP 2026-07-31 (4d); ACA TARGET 2023-08-31 -> STOP 2024-08-02 (10d); ACLS TARGET 2026-08-06 -> STOP 2026-09-14 (6d)

## 2. `fat_stops` (191 sym / 258 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, AAON, ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AGYS, AHCO, AI, ALEC, ALGN, ALL, ALLE, ALNT, AMP, AMRC

## 3. `slow_target_grind` (172 sym / 205 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, AZO, BALL
- **Evidence:** ABT TARGET 132d +8.0% (~0.06%/d) 2020-01-22; ACN TARGET 141d +8.0% (~0.06%/d) 2013-12-19; ADI TARGET 135d +8.0% (~0.06%/d) 2013-07-17; AEE TARGET 148d +8.0% (~0.05%/d) 2019-09-03; AEE TARGET 224d +8.0% (~0.04%/d) 2025-10-20

## 4. `false_start_2022_2023` (111 sym / 120 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGM, AGO, AI, AMH, AMP, AMTX, AMWL, AN, APLD, APPS, AVGO, BG, BILI, BKR
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADMA 2022 STOP 15d -8.8%; ADPT 2022 STOP 8d -17.1%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (19 sym / 20 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, AVAV, CECO, CEG, DGII, DRS, ESE, FIVN, IESC, LINC, LMAT, LMB, MIDD, MMS, MOD, MWA, RBC, STRL, TGB
- **Evidence:** AGX peak~24% -> exit +8.3% (giveback~16pp, 17d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +8.0% (giveback~12pp, 33d, TARGET); CEG peak~19% -> exit +8.0% (giveback~11pp, 20d, TARGET); CECO peak~22% -> exit +8.0% (giveback~14pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (58 sym / 2061 trades) — direction: expand, confidence: medium, 52.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (2061 trades, 52%, high) vs target_contract_approach_fail → contract (796 trades, 11%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 2061/3944 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 796/7016 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN
- **Evidence:** [A expand] AA +23% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; ABM +9% in 15d after TARGET; ABT +6% in 15d after TARGET | [B contract] A reached 83% of target then STOP; AAMI reached 56% of target then STOP; AAON reached 84% of target then STOP; AAON reached 64% of target then STOP; ABBNY reached 92% of target then STOP; ABR reached 53% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (58 sym / 813 trades) — direction: expand, confidence: medium, 40.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (813 trades, 40%, high) vs stop_ok_never_worked → hold (589 trades, 29%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 813/2018 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 589/2018 STOPs (29%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADMA, ADNT, ADSK
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2023-10-19 then back above entry/15d; AAON STOP 2024-06-10 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; ABNB STOP 2021-12-01 then back above entry/15d; ABR STOP 2010-07-06 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; AAON MFE~1.3% STOP; ABBV MFE~0.0% STOP; ABR MFE~1.9% STOP; ACLS MFE~1.4% STOP

## 3. `band_tighten_weak_fill` (399 sym / 532 trades) — direction: tighten, confidence: low, 7.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 532/7016 trades (8%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGI, AGM, AGO, AGYS, AHT, AI, AIR, AIT
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 1d; AAPL MFE~3.0% STOP 4d; ABR MFE~1.9% STOP 11d; ACLS MFE~0.3% STOP 8d

## 4. `target_contract_slow_hold` (172 sym / 205 trades) — direction: contract, confidence: low, 5.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 205/3944 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, AZO, BALL
- **Evidence:** ABT TARGET 132d +8.0% (~0.06%/d); ACN TARGET 141d +8.0% (~0.06%/d); ADI TARGET 135d +8.0% (~0.06%/d); AEE TARGET 148d +8.0% (~0.05%/d); AEE TARGET 224d +8.0% (~0.04%/d); ACGL TARGET 130d +8.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
