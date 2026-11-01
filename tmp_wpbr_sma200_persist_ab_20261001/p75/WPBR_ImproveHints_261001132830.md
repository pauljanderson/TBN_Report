# WPBR Improve Hints — stamp `261001132830`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `slow_target_grind` (370 sym / 661 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** AAON, AAP, AAPL, ABCB, ABG, ABR, ABT, ACA, ACGL, ACM, ACN, ACU, ADBE, ADP, AEE, AEP, AFL, AGX, AIG, AIT
- **Evidence:** ACA TARGET 164d +22.0% (~0.13%/d) 2026-02-05; AAP TARGET 279d +22.0% (~0.08%/d) 2015-08-13; AAP TARGET 324d +22.0% (~0.07%/d) 2016-12-08; ABR TARGET 112d +22.0% (~0.20%/d) 2021-06-01; ABT TARGET 241d +22.0% (~0.09%/d) 2015-06-18

## 2. `fat_stops` (327 sym / 455 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** A, AAL, AAMI, AAON, AAP, ABG, ABR, ABUS, ACAD, ACLS, ACU, ADBE, AGX, AGYS, AIR, AKAM, ALNT, ALNY, ALSN, AMD

## 3. `early_run_long_tail` (144 sym / 165 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAON, ABR, ACU, ADBE, ADSK, AER, AIT, ALGN, ALLE, ALSN, AMD, AMGN, AMN, ANET, AON, ARES, ARGX, AVGO, AX, AXSM
- **Evidence:** ABR +10% by day 13 then held 112d exit +22.0% (TARGET); ACU +10% by day 8 then held 217d exit +22.0% (TARGET); AER +10% by day 13 then held 98d exit +22.0% (TARGET); AAON +10% by day 14 then held 93d exit +22.0% (TARGET); AIT +10% by day 14 then held 117d exit +22.0% (TARGET)

## 4. `post_target_quick_stop` (75 sym / 81 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACAD, ADMA, ALNT, APP, APPS, ATO, AX, BLK, BRK.B, BURL, CACI, CHTR, CNO, CRM, CRS, DDS, DECK, DOV, DXCM, ENPH
- **Evidence:** ADMA TARGET 2025-03-19 -> STOP 2025-04-04 (7d); ACAD TARGET 2015-04-17 -> STOP 2015-08-06 (3d); ALNT TARGET 2015-10-22 -> STOP 2016-02-08 (3d); APP TARGET 2025-12-02 -> STOP 2026-01-30 (9d); APPS TARGET 2020-04-09 -> STOP 2021-11-03 (8d)

## 5. `false_start_2022_2023` (45 sym / 47 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** ACLS, AEE, AEHR, AJG, ARE, ARES, ARW, BIO, BLK, COST, DKL, DXCM, ENPH, EPAM, EXLS, FN, GMAB, GNRC, HWKN, INFY
- **Evidence:** ACLS 2022 STOP 2d -11.5%; AEHR 2023 STOP 2d -11.1%; AJG 2022 STOP 13d -10.7%; ARW 2023 STOP 9d -9.9%; ARE 2022 STOP 7d -10.5%

## 6. `winner_peak_giveback` (11 sym / 11 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, CLS, EXEL, GGAL, GMAB, KTOS, LEU, ODC, PDEX, PLUS, STX
- **Evidence:** AGX peak~42% -> exit +23.8% (giveback~18pp, 37d, GAP_UP); CLS peak~35% -> exit +22.0% (giveback~13pp, 26d, TARGET); EXEL peak~34% -> exit +22.0% (giveback~12pp, 17d, TARGET); GGAL peak~52% -> exit +38.5% (giveback~14pp, 62d, GAP_UP); GMAB peak~414% -> exit +22.0% (giveback~392pp, 60d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (57 sym / 661 trades) — direction: mixed, confidence: medium, 52.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (538 trades, 43%, high) vs target_contract_slow_hold → contract (661 trades, 52%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 538/1263 TARGET exits (43%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 661/1263 TARGET exits (52%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AAON, AAP, AAPL, ABCB, ABG, ABR, ABT, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACU, ADBE, ADMA, ADP, AEE, AEP, AER
- **Evidence:** [A expand] ACA +8% in 15d after TARGET; ACA +6% in 15d after TARGET; AAP +7% in 15d after TARGET; ABR +6% in 15d after TARGET; ACLS +13% in 15d after TARGET; ABT +10% in 15d after TARGET | [B contract] ACA TARGET 164d +22.0% (~0.13%/d); AAP TARGET 279d +22.0% (~0.08%/d); AAP TARGET 324d +22.0% (~0.07%/d); ABR TARGET 112d +22.0% (~0.20%/d); ABT TARGET 241d +22.0% (~0.09%/d); ABT TARGET 162d +22.0% (~0.14%/d)

## 2. `stop_pct_tension_expand_vs_contract` (58 sym / 373 trades) — direction: mixed, confidence: medium, 23.6% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (373 trades, 24%, high) vs stop_contract_dead_losers → contract (358 trades, 23%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 373/1579 STOP exits (24%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 358/1579 STOPs (23%) never expanded (MFE<2%) and 455 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AAMI, AAON, ABCB, ABG, ABR, ACAD, ACLS, ACN, ADI, ADMA, ADP, ADSK, AEE, AEG, AEHR, AER, AFG, AGM, AGYS, AIT
- **Evidence:** [A expand] AAMI STOP 2026-02-05 then back above entry/15d; ABR STOP 2020-02-28 then back above entry/15d; ACLS STOP 2022-07-01 then back above entry/15d; ABG STOP 2015-08-24 then back above entry/15d; ADMA STOP 2025-04-04 then back above entry/15d; ADI STOP 2022-03-07 then back above entry/15d | [B contract] ABR MFE~0.2% STOP; ACLS MFE~0.0% STOP; ADI MFE~1.8% STOP; ACAD MFE~0.9% STOP; AEHR MFE~0.4% STOP; AFG MFE~0.2% STOP

## 3. `target_contract_approach_fail` (272 sym / 330 trades) — direction: contract, confidence: medium, 9.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 330/3466 trades (10%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAP, AAPL, ABCB, ABG, ABT, ACLS, ACM, ACN, ADI, ADSK, AER, AFL, AGM, AGYS, AIR, AKAM, ALG, AMD, AME, AMG
- **Evidence:** AAP reached 61% of target then STOP; ACLS reached 53% of target then STOP; ACLS reached 75% of target then STOP; ABT reached 69% of target then STOP; ABG reached 51% of target then STOP; ADI reached 94% of target then STOP

## 4. `band_tighten_weak_fill` (196 sym / 234 trades) — direction: tighten, confidence: low, 6.8% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 234/3466 trades (7%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAON, ABR, ACAD, ACLS, ADMA, ADP, ADSK, AEE, AEHR, AFG, AGM, AGYS, AIT, AJG, AKAM, ALGN, ALNT, ALSN, AME, AMZN
- **Evidence:** ABR MFE~0.2% STOP 14d; ACLS MFE~0.0% STOP 2d; ADMA MFE~2.1% STOP 7d; ACAD MFE~0.9% STOP 3d; AEHR MFE~0.4% STOP 2d; AFG MFE~0.2% STOP 5d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
