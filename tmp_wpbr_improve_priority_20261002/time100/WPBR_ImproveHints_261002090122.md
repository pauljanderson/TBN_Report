# WPBR Improve Hints — stamp `261002090122`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `fat_stops` (259 sym / 351 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AA, AAL, ABBNY, ABR, ABUS, ACRS, ADMA, ADPT, AEHR, AEM, AFRM, AHT, AI, AKAM, ALB, ALDX, ALGN, ALNT, ALNY, AMD

## 2. `slow_target_grind` (212 sym / 246 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABG, ACGL, ACN, ADBE, AER, AGYS, AIG, AIZ, ALB, ALG, ALGN, ALNY, AMAT, AME, AMGN, AMP, AMZN, ANDE, AON, APH
- **Evidence:** ACN TARGET 125d +20.0% (~0.16%/d) 2011-07-07; ABG TARGET 104d +20.0% (~0.19%/d) 2013-02-05; ACGL TARGET 121d +20.0% (~0.17%/d) 2019-07-10; ACGL TARGET 137d +20.0% (~0.15%/d) 2024-08-26; ADBE TARGET 113d +20.0% (~0.18%/d) 2013-04-10

## 3. `early_run_long_tail` (172 sym / 189 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** AAPL, ACU, AEIS, ALB, ALLE, ALSN, AMAT, AMGN, AON, APG, APH, ARES, ASML, AVGO, AWI, AX, BA, BABA, BAESY, BALL
- **Evidence:** AAPL +10% by day 9 then held 146d exit +1.8% (TIME); ACU +10% by day 8 then held 142d exit +7.3% (TIME); AEIS +10% by day 18 then held 145d exit +1.6% (TIME); ALB +10% by day 19 then held 83d exit +20.0% (TARGET); ALLE +10% by day 24 then held 142d exit +13.5% (TIME)

## 4. `winner_peak_giveback` (111 sym / 119 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** ABM, ADI, AEIS, AER, AFL, AFRM, AGM, AJG, AMN, AMTX, AOS, APLD, ARGX, ASM, AVA, AVAV, AWI, AWK, BAC, BEN
- **Evidence:** ABM peak~18% -> exit +5.9% (giveback~12pp, 146d, TIME); ADI peak~16% -> exit +5.8% (giveback~11pp, 145d, TIME); AFRM peak~36% -> exit +23.4% (giveback~12pp, 24d, GAP_UP); AGM peak~18% -> exit +7.7% (giveback~10pp, 144d, TIME); AEIS peak~20% -> exit +1.6% (giveback~18pp, 145d, TIME)

## 5. `post_target_quick_stop` (91 sym / 100 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** ACLS, ADSK, ALGN, ALNY, APLD, APP, ARES, AU, AWI, AXON, AYI, BA, BANF, BBW, BILL, BLBD, CELH, CHCI, CHDN, CMCL
- **Evidence:** ACLS TARGET 2023-06-12 -> STOP 2024-11-15 (3d); ADSK TARGET 2014-06-18 -> STOP 2016-12-02 (7d); ALNY TARGET 2024-10-16 -> STOP 2026-02-12 (9d); ALGN TARGET 2017-09-06 -> STOP 2020-03-18 (0d); APLD TARGET 2023-09-28 -> STOP 2023-10-09 (0d)

## 6. `false_start_2022_2023` (41 sym / 42 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, ACRS, AEHR, AFRM, AMTX, APLD, ATUSF, AZO, BILL, CB, CCL, CGC, COIN, DOCN, DXCM, GH, GME, GNRC, HBAN
- **Evidence:** AA 2022 STOP 13d -14.4%; AAMI 2022 STOP 9d -10.3%; ACRS 2023 STOP 8d -14.2%; AEHR 2022 STOP 7d -10.8%; AEHR 2022 STOP 2d -12.8%

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (66 sym / 1010 trades) — direction: contract, confidence: medium, 52.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean contract): target_expand_post_exit → expand (712 trades, 52%, high) vs target_contract_approach_fail → contract (1010 trades, 23%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 712/1360 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 1010/4383 trades (23%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAMI, AAON, AAPL, AAT, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +11% in 15d after TARGET; AAPL +18% in 15d after TARGET; ABNB +10% in 15d after TARGET; AAL +5% in 15d after TARGET; AAL +9% in 15d after TARGET; ABUS +54% in 15d after TARGET | [B contract] AAMI reached 76% of target then TIME; AAON reached 55% of target then STOP; AAPL reached 72% of target then TIME; A reached 57% of target then TIME; ABM reached 67% of target then TIME; ABM reached 90% of target then TIME

## 2. `stop_pct_tension_expand_vs_contract` (70 sym / 463 trades) — direction: expand, confidence: medium, 32.4% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (463 trades, 32%, high) vs stop_contract_dead_losers → contract (214 trades, 15%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 463/1429 STOP exits (32%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 214/1429 STOPs (15%) never expanded (MFE<2%) and 351 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAMI, AAPL, ABG, ABR, ACA, ACAD, ACLS, ACRS, ADI, ADSK, AEE, AEHR, AEP, AFRM, AGO, AGX, AI, AIG, AIZ
- **Evidence:** [A expand] AA STOP 2022-05-09 then back above entry/15d; AAMI STOP 2022-01-21 then back above entry/15d; AAPL STOP 2013-04-19 then back above entry/15d; ACA STOP 2023-11-02 then back above entry/15d; ACA STOP 2024-08-02 then back above entry/15d; ABR STOP 2010-08-31 then back above entry/15d | [B contract] AAMI MFE~1.6% STOP; ACLS MFE~1.3% STOP; ACRS MFE~1.4% STOP; ACRS MFE~0.0% STOP; AEHR MFE~0.9% STOP; AEHR MFE~0.9% STOP

## 3. `target_contract_slow_hold` (212 sym / 246 trades) — direction: contract, confidence: high, 18.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 246/1360 TARGET exits (18%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABG, ACGL, ACN, ADBE, AER, AGYS, AIG, AIZ, ALB, ALG, ALGN, ALNY, AMAT, AME, AMGN, AMP, AMZN, ANDE, AON, APH
- **Evidence:** ACN TARGET 125d +20.0% (~0.16%/d); ABG TARGET 104d +20.0% (~0.19%/d); ACGL TARGET 121d +20.0% (~0.17%/d); ACGL TARGET 137d +20.0% (~0.15%/d); ADBE TARGET 113d +20.0% (~0.18%/d); AGYS TARGET 112d +20.0% (~0.18%/d)

## 4. `band_tighten_weak_fill` (124 sym / 137 trades) — direction: tighten, confidence: low, 3.1% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 137/4383 trades (3%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AAMI, ACLS, ACRS, ADSK, AEHR, AKTS, ALNY, AMP, ANNX, APP, ARES, AVGO, AYI, B, BA, BAP, BBW, BEP, BLBD, BLDR
- **Evidence:** AAMI MFE~1.6% STOP 9d; ACLS MFE~1.3% STOP 3d; ACRS MFE~1.4% STOP 8d; ACRS MFE~0.0% STOP 6d; AEHR MFE~0.9% STOP 4d; AEHR MFE~0.9% STOP 7d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
