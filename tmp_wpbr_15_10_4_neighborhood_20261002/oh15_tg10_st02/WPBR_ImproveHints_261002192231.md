# WPBR Improve Hints — stamp `261002192231`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (421 sym / 544 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** A, AA, AAL, AAMI, AAON, ABM, ABR, ABT, ABUS, ACAD, ACGL, ACRS, ADI, ADPT, AEIS, AEM, AFL, AFRM, AGM, AGNC
- **Evidence:** AA TARGET 2022-02-16 -> STOP 2022-05-06 (10d); A TARGET 2016-07-29 -> STOP 2019-04-23 (1d); AAMI TARGET 2015-04-07 -> STOP 2022-01-19 (7d); AAON TARGET 2020-03-04 -> STOP 2023-09-26 (1d); AAL TARGET 2010-06-11 -> STOP 2010-07-02 (0d)

## 2. `false_start_2022_2023` (193 sym / 223 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AA, AAMI, AAON, ACLS, ACN, ACRS, ADBE, ADMA, ADPT, ADSK, AEHR, AFRM, AGM, AI, AJG, ALB, AME, AMKR, AMP, AMRC
- **Evidence:** AA 2022 STOP 10d -8.8%; AAMI 2022 STOP 7d -4.5%; AAON 2023 STOP 1d -2.1%; ACRS 2023 STOP 2d -8.6%; ACLS 2022 STOP 9d -5.9%

## 3. `slow_target_grind` (89 sym / 100 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACN, AEE, AFG, AFL, AGNC, ALLE, AMT, AON, ARE, ATO, BAX, BN, BNY, BRK.B, BRO, BXP, CACI, CB, CCI
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d) 2020-01-21; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24; AFL TARGET 315d +10.0% (~0.03%/d) 2017-04-28; AGNC TARGET 176d +10.0% (~0.06%/d) 2016-10-25

## 4. `fat_stops` (84 sym / 99 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ACLS, ACRS, ADMA, ADPT, AEHR, AGX, AHT, AI, ALLE, ALNT, AOSL, APLD, APPS, APYX, AXP, BABA, BBWI, BILI, BKNG, BXMT

## 5. `winner_peak_giveback` (11 sym / 12 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AVAV, CECO, DGII, DOCU, ESEA, IRMD, KEX, LMAT, MWA, SENEA, W
- **Evidence:** AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); CECO peak~22% -> exit +10.0% (giveback~12pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP); DOCU peak~35% -> exit +20.0% (giveback~15pp, 16d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_hold` (47 sym / 1931 trades) — direction: expand, confidence: medium, 65.5% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1931 trades, 66%, high) vs stop_ok_never_worked → hold (1090 trades, 37%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1931/2947 STOP exits (66%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 1090/2947 STOPs (37%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABBV, ABCB, ABG, ABM, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM
- **Evidence:** [A expand] A STOP 2014-02-14 then back above entry/15d; A STOP 2019-04-23 then back above entry/15d; AAMI STOP 2022-01-19 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAPL STOP 2013-04-17 then back above entry/15d; ABBNY STOP 2022-04-12 then back above entry/15d | [B hold] A MFE~0.0% STOP; A MFE~1.1% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAON MFE~0.0% STOP; AAON MFE~1.8% STOP

## 2. `target_pct_tension_expand_vs_contract` (60 sym / 1233 trades) — direction: expand, confidence: medium, 53.2% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1233 trades, 53%, high) vs target_contract_approach_fail → contract (850 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1233/2319 TARGET exits (53%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 850/6183 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +21% in 15d after TARGET; ABBNY +8% in 15d after TARGET; AAT +7% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +13% in 15d after TARGET; ACA +7% in 15d after TARGET | [B contract] AA reached 82% of target then STOP; A reached 66% of target then STOP; AAPL reached 81% of target then STOP; ABBNY reached 73% of target then STOP; AAON reached 92% of target then STOP; AAT reached 68% of target then STOP

## 3. `band_tighten_weak_fill` (710 sym / 1209 trades) — direction: tighten, confidence: high, 19.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 1209/6183 trades (20%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAL, AAMI, AAON, AAP, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACA, ACGL, ACLS, ACN, ACRS, ADBE, ADI, ADM
- **Evidence:** A MFE~0.0% STOP 0d; A MFE~1.1% STOP 1d; AAMI MFE~1.6% STOP 7d; ABBV MFE~0.0% STOP 0d; AAON MFE~0.0% STOP 2d; AAON MFE~1.8% STOP 1d

## 4. `target_contract_slow_hold` (89 sym / 100 trades) — direction: contract, confidence: low, 4.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 100/2319 TARGET exits (4%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACN, AEE, AFG, AFL, AGNC, ALLE, AMT, AON, ARE, ATO, BAX, BN, BNY, BRK.B, BRO, BXP, CACI, CB, CCI
- **Evidence:** ABT TARGET 109d +10.0% (~0.09%/d); ACN TARGET 107d +10.0% (~0.09%/d); AEE TARGET 169d +10.0% (~0.06%/d); AFL TARGET 315d +10.0% (~0.03%/d); AGNC TARGET 176d +10.0% (~0.06%/d); AFG TARGET 350d +10.0% (~0.03%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
