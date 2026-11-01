# WPBR Improve Hints — stamp `261002225932`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (283 sym / 349 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, AAPL, ABCB, ABNB, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AEM, AFRM, AGI, AKAM, ALDX, ALEC
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); AAPL TARGET 2024-08-13 -> STOP 2026-07-31 (4d); ABNB TARGET 2021-09-23 -> STOP 2021-12-01 (5d); ACA TARGET 2023-08-31 -> STOP 2024-08-02 (10d); ABCB TARGET 2013-05-06 -> STOP 2015-08-26 (9d)

## 2. `fat_stops` (167 sym / 222 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAON, ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AHCO, AI, ALEC, ALGN, ALL, ALLE, ALNT, AMP, AMRC, AMTX, AMWL

## 3. `slow_target_grind` (165 sym / 193 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, AZO, BALL
- **Evidence:** ABT TARGET 132d +8.0% (~0.06%/d) 2020-01-22; ACGL TARGET 130d +8.0% (~0.06%/d) 2012-10-01; ACN TARGET 141d +8.0% (~0.06%/d) 2013-12-19; ADI TARGET 135d +8.0% (~0.06%/d) 2013-07-17; ADP TARGET 183d +8.0% (~0.04%/d) 2012-08-16

## 4. `false_start_2022_2023` (95 sym / 104 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGO, AI, AMP, AMTX, AN, APLD, APPS, AVGO, BG, BILI, BKR, CASH, CB, CCL
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADMA 2022 STOP 15d -8.8%; ADPT 2022 STOP 8d -17.1%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (17 sym / 18 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, AVAV, CECO, CEG, DGII, DRS, FIVN, IESC, LINC, LMAT, LMB, MIDD, MMS, MOD, MWA, RBC, TGB
- **Evidence:** AGX peak~24% -> exit +8.3% (giveback~16pp, 17d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +8.0% (giveback~12pp, 33d, TARGET); CEG peak~19% -> exit +8.0% (giveback~11pp, 20d, TARGET); CECO peak~22% -> exit +8.0% (giveback~14pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (62 sym / 1847 trades) — direction: expand, confidence: medium, 51.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1847 trades, 52%, high) vs target_contract_approach_fail → contract (709 trades, 11%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1847/3556 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 709/6272 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +23% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAT +6% in 15d after TARGET; AAL +17% in 15d after TARGET | [B contract] A reached 83% of target then STOP; ABBNY reached 92% of target then STOP; AAON reached 84% of target then STOP; AAON reached 64% of target then STOP; AAT reached 92% of target then STOP; ACA reached 94% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (59 sym / 717 trades) — direction: expand, confidence: medium, 40.2% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (717 trades, 40%, high) vs stop_ok_never_worked → hold (518 trades, 29%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 717/1784 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 518/1784 STOPs (29%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABNB, ABR, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADMA, ADNT, ADSK, AEE
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; ABNB STOP 2021-12-01 then back above entry/15d; AAON STOP 2023-10-19 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ABR STOP 2010-07-06 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; ABR MFE~1.9% STOP; ABCB MFE~0.7% STOP

## 3. `band_tighten_weak_fill` (354 sym / 461 trades) — direction: tighten, confidence: low, 7.4% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 461/6272 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGI, AGO, AHT, AI, AIR, AIT, AKTS, ALDX
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 1d; AAPL MFE~3.0% STOP 4d; ABR MFE~1.9% STOP 11d; ABCB MFE~2.6% STOP 9d

## 4. `target_contract_slow_hold` (165 sym / 193 trades) — direction: contract, confidence: low, 5.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 193/3556 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, AZO, BALL
- **Evidence:** ABT TARGET 132d +8.0% (~0.06%/d); ACGL TARGET 130d +8.0% (~0.06%/d); ACN TARGET 141d +8.0% (~0.06%/d); ADI TARGET 135d +8.0% (~0.06%/d); ADP TARGET 183d +8.0% (~0.04%/d); ADP TARGET 125d +8.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
