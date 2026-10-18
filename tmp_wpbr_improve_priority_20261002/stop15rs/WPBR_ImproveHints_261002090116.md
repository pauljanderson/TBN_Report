# WPBR Improve Hints — stamp `261002090116`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `fat_stops` (717 sym / 1175 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABM, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADMA

## 2. `slow_target_grind` (597 sym / 1077 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** A, AAL, AAON, AAPL, AAT, ABG, ABR, ABT, ACGL, ACM, ACN, ACU, ADBE, ADI, ADNT, ADP, ADSK, AEE, AEIS, AEP
- **Evidence:** AAON TARGET 147d +20.0% (~0.14%/d) 2011-07-21; A TARGET 256d +20.0% (~0.08%/d) 2017-03-13; AAT TARGET 239d +20.0% (~0.08%/d) 2013-01-02; ABR TARGET 166d +20.0% (~0.12%/d) 2011-01-26; ABT TARGET 210d +20.0% (~0.10%/d) 2015-05-18

## 3. `early_run_long_tail` (195 sym / 221 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACA, ACN, ACU, ADSK, AEIS, AGX, AIT, ALB, ALDX, ALLE, ALSN, AMAT, AMGN, AMH, AN, ANET, AON, APG, APH, APP
- **Evidence:** ACA +10% by day 7 then held 139d exit +24.0% (GAP_UP); ACU +10% by day 8 then held 217d exit +20.0% (TARGET); ADSK +10% by day 14 then held 150d exit +20.0% (TARGET); ACN +10% by day 24 then held 577d exit +20.0% (TARGET); AEIS +10% by day 18 then held 316d exit +20.0% (TARGET)

## 4. `post_target_quick_stop` (53 sym / 57 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, AON, APO, ARES, BA, BANF, BAP, BMRN, BN, CHCI, COHR, CVNA, CZR, DDS, DXCM, ENPH, ESEA, ESTC, FRO, GCT
- **Evidence:** ACLS TARGET 2023-06-12 -> STOP 2024-11-19 (7d); APO TARGET 2020-01-21 -> STOP 2020-03-09 (6d); AON TARGET 2019-12-20 -> STOP 2020-03-18 (6d); ARES TARGET 2020-02-04 -> STOP 2020-03-18 (7d); BA TARGET 2017-06-19 -> STOP 2020-03-11 (2d)

## 5. `winner_peak_giveback` (40 sym / 45 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AER, AFRM, AGX, AMTX, APLD, ASM, AVAV, CLF, CLS, DOCU, DRS, FICO, FSLR, HALO, HCI, HIMS, JMIA, KTOS, LEU, LUGDF
- **Evidence:** AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AER peak~32% -> exit +20.0% (giveback~12pp, 99d, TARGET); AGX peak~32% -> exit +20.0% (giveback~12pp, 92d, TARGET); AMTX peak~37% -> exit +20.0% (giveback~17pp, 42d, TARGET); APLD peak~33% -> exit +21.2% (giveback~12pp, 19d, GAP_UP)

## 6. `false_start_2022_2023` (21 sym / 22 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** ACRS, AEHR, AFRM, ATUSF, CCL, CGC, GH, GME, HIMS, INOD, MDB, MGA, NET, NGL, NVDA, ORLY, PYPL, ROKU, SPRY, TSLA
- **Evidence:** ACRS 2023 STOP 9d -20.8%; AEHR 2022 STOP 11d -17.6%; AFRM 2022 STOP 13d -20.4%; ATUSF 2022 STOP 14d -13.1%; CCL 2023 STOP 12d -15.8%

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (61 sym / 1077 trades) — direction: mixed, confidence: medium, 47.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (no clear lean — pick one A/B arm or segment trades): target_expand_post_exit → expand (1033 trades, 45%, high) vs target_contract_slow_hold → contract (1077 trades, 47%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1033/2287 TARGET exits (45%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 1077/2287 TARGET exits (47%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABG, ABNB, ABR, ABT, ABUS, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADM
- **Evidence:** [A expand] AA +11% in 15d after TARGET; ABNB +10% in 15d after TARGET; ABR +11% in 15d after TARGET; AAL +5% in 15d after TARGET; AAL +9% in 15d after TARGET; AAL +7% in 15d after TARGET | [B contract] AAON TARGET 147d +20.0% (~0.14%/d); A TARGET 256d +20.0% (~0.08%/d); AAT TARGET 239d +20.0% (~0.08%/d); ABR TARGET 166d +20.0% (~0.12%/d); ABT TARGET 210d +20.0% (~0.10%/d); ABT TARGET 622d +20.0% (~0.03%/d)

## 2. `target_contract_approach_fail` (390 sym / 480 trades) — direction: contract, confidence: medium, 11.6% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target: 480/4144 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AAMI, AAON, AAP, AAPL, ABM, ABR, ABUS, ACAD, ACM, ACN, ACRS, ADMA, ADNT, ADP, ADPT, AEHR, AFL, AFRM, AGO, AIG
- **Evidence:** AAMI reached 76% of target then STOP; AAON reached 75% of target then STOP; AAON reached 55% of target then STOP; ABR reached 60% of target then STOP; ABR reached 51% of target then STOP; ABM reached 91% of target then STOP

## 3. `stop_pct_tension_expand_vs_contract` (68 sym / 134 trades) — direction: mixed, confidence: medium, 11.4% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (no clear lean — pick one A/B arm or segment trades): stop_expand_post_stop_rebound → expand (134 trades, 11%, medium) vs stop_contract_dead_losers → contract (118 trades, 10%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 134/1180 STOP exits (11%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 118/1180 STOPs (10%) never expanded (MFE<2%) and 1175 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** ABUS, ACA, ACAD, ACLS, ACRS, AEHR, AFRM, AIZ, AJG, ALB, ALBY, ALNT, ALNY, AMTX, AN, AON, AOS, APH, APLD, APO
- **Evidence:** [A expand] ACA STOP 2024-08-05 then back above entry/15d; ABUS STOP 2014-05-16 then back above entry/15d; ACAD STOP 2012-11-14 then back above entry/15d; ACRS STOP 2016-11-03 then back above entry/15d; ACRS STOP 2023-10-26 then back above entry/15d; ACRS STOP 2026-02-26 then back above entry/15d | [B contract] ACLS MFE~1.3% STOP; ACRS MFE~1.4% STOP; AEHR MFE~0.9% STOP; ALBY MFE~0.7% STOP; ALNY MFE~0.7% STOP; AJG MFE~2.0% STOP

## 4. `band_tighten_weak_fill` (63 sym / 67 trades) — direction: tighten, confidence: low, 1.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 67/4144 trades (2%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** ACLS, ACRS, AEHR, AIZ, ALNY, APO, APP, ARES, ATI, AYI, BA, BAP, BEP, BMRN, CCL, CHCI, COHR, CRUS, CVNA, CXDO
- **Evidence:** ACLS MFE~1.3% STOP 7d; ACRS MFE~1.4% STOP 9d; AEHR MFE~0.9% STOP 11d; ALNY MFE~0.7% STOP 6d; AIZ MFE~1.1% STOP 5d; APO MFE~1.4% STOP 6d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
