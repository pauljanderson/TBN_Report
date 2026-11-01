# WPBR Improve Hints — stamp `261002191442`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (274 sym / 335 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ABCB, ABNB, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AEM, AFRM, AGI, AKAM, ALDX, ALEC, ALL, ALLE
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); ABNB TARGET 2021-09-23 -> STOP 2021-12-01 (5d); ABCB TARGET 2013-05-06 -> STOP 2015-08-26 (9d); ACRS TARGET 2017-02-23 -> STOP 2020-11-16 (3d); ACRS TARGET 2025-03-24 -> STOP 2025-06-18 (6d)

## 2. `slow_target_grind` (196 sym / 241 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB
- **Evidence:** ABT TARGET 100d +9.0% (~0.09%/d) 2019-06-19; ACGL TARGET 130d +9.0% (~0.07%/d) 2012-10-01; ACN TARGET 142d +9.0% (~0.06%/d) 2013-12-20; ADP TARGET 204d +9.0% (~0.04%/d) 2012-09-06; ADP TARGET 126d +9.0% (~0.07%/d) 2019-09-06

## 3. `fat_stops` (171 sym / 226 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABG, ABR, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AHCO, AHT, AI, ALEC, ALGN, ALL, ALLE, ALNT, AMP, AMRC, AMTX

## 4. `false_start_2022_2023` (97 sym / 108 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADMA, ADPT, AEHR, AFRM, AGO, AI, AMP, AMTX, AN, APLD, APPS, AVGO, BG, BILI, BKR, CASH, CB, CCL
- **Evidence:** AAMI 2022 STOP 8d -8.4%; ACRS 2023 STOP 7d -12.4%; ADPT 2022 STOP 8d -17.1%; ADMA 2022 STOP 15d -8.8%; AEHR 2022 STOP 7d -8.9%

## 5. `winner_peak_giveback` (21 sym / 22 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABUS, AGX, AVAV, CECO, DGII, DOCU, DRS, ESEA, FIVN, FSLR, HURC, IESC, JMIA, LINC, LMAT, LMB, MIDD, MOD, MWA, RBC
- **Evidence:** ABUS peak~20% -> exit +9.0% (giveback~11pp, 21d, TARGET); AGX peak~24% -> exit +9.0% (giveback~15pp, 17d, TARGET); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +9.0% (giveback~11pp, 33d, TARGET); CECO peak~22% -> exit +9.0% (giveback~13pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (61 sym / 1738 trades) — direction: expand, confidence: medium, 51.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1738 trades, 52%, high) vs target_contract_approach_fail → contract (762 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1738/3377 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 762/6201 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AA +22% in 15d after TARGET; AAT +7% in 15d after TARGET; ABBNY +7% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +17% in 15d after TARGET; AAL +10% in 15d after TARGET | [B contract] A reached 74% of target then STOP; AAPL reached 90% of target then STOP; AAT reached 82% of target then STOP; ABNB reached 86% of target then STOP; AAON reached 57% of target then STOP; ABBNY reached 81% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (62 sym / 768 trades) — direction: expand, confidence: medium, 40.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (768 trades, 40%, high) vs stop_ok_never_worked → hold (514 trades, 27%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 768/1913 STOP exits (40%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 514/1913 STOPs (27%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABNB, ABR, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADMA, ADNT, ADSK
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAPL STOP 2013-04-18 then back above entry/15d; ABBV STOP 2015-02-05 then back above entry/15d; ABNB STOP 2021-12-01 then back above entry/15d; AAON STOP 2023-10-19 then back above entry/15d; ACA STOP 2023-10-27 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; ABR MFE~1.9% STOP; ABCB MFE~0.7% STOP

## 3. `band_tighten_weak_fill` (353 sym / 456 trades) — direction: tighten, confidence: low, 7.4% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 456/6201 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAPL, ABBV, ABCB, ABR, ACLS, ACRS, ADSK, AEHR, AEIS, AEM, AGI, AGO, AHT, AI, AIR, AIT, AKTS, ALDX
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; AAPL MFE~3.0% STOP 4d; ABBV MFE~0.0% STOP 1d; ABR MFE~1.9% STOP 11d; ABCB MFE~2.6% STOP 9d

## 4. `target_contract_slow_hold` (196 sym / 241 trades) — direction: contract, confidence: low, 7.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 241/3377 TARGET exits (7%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, ADI, ADP, AEE, AEP, AFG, AGM, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AVB
- **Evidence:** ABT TARGET 100d +9.0% (~0.09%/d); ACGL TARGET 130d +9.0% (~0.07%/d); ACN TARGET 142d +9.0% (~0.06%/d); ADP TARGET 204d +9.0% (~0.04%/d); ADP TARGET 126d +9.0% (~0.07%/d); ADI TARGET 149d +9.0% (~0.06%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
