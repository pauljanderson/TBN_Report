# WPBR Improve Hints — stamp `261003135702`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `winner_peak_giveback` (789 sym / 1503 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABNB, ABT, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI
- **Evidence:** AA peak~31% -> exit +18.1% (giveback~13pp, 23d, SCALE+TARGET); A peak~30% -> exit +18.0% (giveback~12pp, 309d, SCALE+GAP_UP); ABNB peak~32% -> exit +18.7% (giveback~13pp, 55d, SCALE+TARGET); ADPT peak~31% -> exit +18.0% (giveback~13pp, 36d, SCALE+TARGET); ADPT peak~25% -> exit +12.0% (giveback~13pp, 20d, SCALE+STOP_LOSS)

## 2. `slow_target_grind` (404 sym / 571 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AAP, AAT, ABCB, ABG, ACGL, ACM, ACN, ADBE, ADM, ADP, ADSK, AEE, AEIS, AER, AFG, AFL, AGYS, AIG, AIT, AIZ
- **Evidence:** AAT TARGET 300d +18.0% (~0.06%/d) 2013-03-04; ADM TARGET 103d +18.0% (~0.17%/d) 2022-10-26; ACN TARGET 812d +18.7% (~0.02%/d) 2015-06-22; ADP TARGET 422d +18.0% (~0.04%/d) 2012-10-05; ADP TARGET 238d +18.0% (~0.08%/d) 2021-12-27

## 3. `early_run_long_tail` (295 sym / 359 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ABCB, ACM, ACU, ADI, ADM, AEIS, AGX, AGYS, AI, AIT, ALB, ALGN, ALLE, ALNT, ALSN, AMAT, AME, AMG, AMGN, AMH
- **Evidence:** ADM +10% by day 11 then held 103d exit +18.0% (SCALE+TARGET); ACU +10% by day 8 then held 463d exit +11.8% (SCALE+GAP_DOWN); ACU +10% by day 8 then held 122d exit +13.8% (SCALE+STOP_LOSS); ABCB +10% by day 4 then held 426d exit +18.0% (SCALE+TARGET); ADI +10% by day 10 then held 205d exit +18.1% (SCALE+GAP_UP)

## 4. `fat_stops` (208 sym / 280 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABR, ABUS, ACAD, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY, AMD

## 5. `post_target_quick_stop` (65 sym / 66 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, ACRS, ADSK, ALGN, AMN, APLD, APP, ARES, AWI, AYI, BANF, BILL, CHDN, COHR, CRS, CRWD, DY, ENPH, ENS, EPAM
- **Evidence:** ACRS TARGET 2020-12-16 -> STOP 2020-12-29 (7d); ACLS TARGET 2023-07-17 -> STOP 2024-11-15 (3d); ADSK TARGET 2014-11-21 -> STOP 2016-12-02 (7d); ALGN TARGET 2017-10-16 -> STOP 2020-03-18 (0d); APLD TARGET 2024-01-10 -> STOP 2025-09-02 (6d)

## 6. `false_start_2022_2023` (41 sym / 42 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILI, BILL, CB, CCL, CGC, COIN, DOCN, DXCM, GH, GME, GNRC
- **Evidence:** AA 2022 STOP 13d -14.4%; ACRS 2023 STOP 8d -14.2%; AAMI 2022 STOP 9d -10.3%; AFRM 2022 STOP 7d -13.9%; AEHR 2022 STOP 7d -10.8%

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (73 sym / 1177 trades) — direction: expand, confidence: medium, 60.8% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1177 trades, 61%, high) vs stop_ok_never_worked → hold (174 trades, 9%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1177/1937 STOP exits (61%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 174/1937 STOPs (9%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAMI, AAON, AAPL, ABCB, ABG, ABM, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACN, ACRS, ACU, ADI, ADMA, ADNT
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; ADPT STOP 2021-01-27 then back above entry/15d; ADPT STOP 2021-02-22 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ADNT STOP 2022-06-13 then back above entry/15d | [B hold] ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ADSK MFE~1.1% STOP; AKTS MFE~0.1% STOP

## 2. `target_pct_tension_expand_vs_contract` (56 sym / 1172 trades) — direction: mixed, confidence: medium, 98.9% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (1071 trades, 99%, high) vs target_contract_approach_fail → contract (1172 trades, 28%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1071/1083 TARGET exits (99%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 1172/4210 trades (28%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAON, AAP, AAPL, AAT, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AA +20% in 15d after TARGET; ABNB +11% in 15d after TARGET; ADPT +19% in 15d after TARGET; ADPT +17% in 15d after TARGET; ADPT +19% in 15d after TARGET; ADNT +12% in 15d after TARGET | [B contract] AA reached 55% of target then STOP; ADPT reached 85% of target then STOP; ADPT reached 52% of target then STOP; ACA reached 56% of target then STOP; ACA reached 80% of target then STOP; ADNT reached 69% of target then STOP

## 3. `target_contract_slow_hold` (404 sym / 571 trades) — direction: contract, confidence: high, 52.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 571/1083 TARGET exits (53%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AAP, AAT, ABCB, ABG, ACGL, ACM, ACN, ADBE, ADM, ADP, ADSK, AEE, AEIS, AER, AFG, AFL, AGYS, AIG, AIT, AIZ
- **Evidence:** AAT TARGET 300d +18.0% (~0.06%/d); ADM TARGET 103d +18.0% (~0.17%/d); ACN TARGET 812d +18.7% (~0.02%/d); ADP TARGET 422d +18.0% (~0.04%/d); ADP TARGET 238d +18.0% (~0.08%/d); ABCB TARGET 426d +18.0% (~0.04%/d)

## 4. `band_tighten_weak_fill` (118 sym / 130 trades) — direction: tighten, confidence: low, 3.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 130/4210 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANIP, ANNX, APP, ARES, AVGO, AYI, B, BA, BAP, BBW, BEP, BLBD
- **Evidence:** ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ADSK MFE~1.1% STOP 7d; AKTS MFE~0.1% STOP 2d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
