# WPBR Improve Hints — stamp `261002203007`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (310 sym / 385 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ABCB, ABNB, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AFRM, AGI, AGM, AGNC, AGX, AKAM
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); ABNB TARGET 2021-09-23 -> STOP 2021-12-01 (5d); ACA TARGET 2023-08-31 -> STOP 2024-08-02 (10d); ABCB TARGET 2013-05-06 -> STOP 2015-08-25 (8d); ABUS TARGET 2014-04-22 -> STOP 2014-11-06 (1d)

## 2. `fat_stops` (132 sym / 159 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACLS, ACRS, ADMA, ADNT, ADPT, AEHR, AHCO, AI, ALEC, ALGN, ALLE, ALNT, AMN, AMP, AMRC, AMWL, AOSL, APLD, APPS

## 3. `slow_target_grind` (132 sym / 152 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, ADP, AEE, AFG, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, AZO, BALL, BF.B, BKHYY, BN, BNY
- **Evidence:** ABT TARGET 132d +8.0% (~0.06%/d) 2020-01-22; ACGL TARGET 130d +8.0% (~0.06%/d) 2012-10-01; ACN TARGET 141d +8.0% (~0.06%/d) 2013-12-19; ADP TARGET 125d +8.0% (~0.06%/d) 2019-09-05; AEE TARGET 148d +8.0% (~0.05%/d) 2019-09-03

## 4. `false_start_2022_2023` (104 sym / 114 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, AMP, AMTX, AOS, AOUT, APLD, AVGO, AZO, BILI, BKR, CASH
- **Evidence:** AAMI 2022 STOP 8d -7.4%; ACRS 2023 STOP 7d -11.4%; ADPT 2022 STOP 8d -16.3%; ADMA 2022 STOP 15d -7.8%; ADBE 2022 STOP 15d -6.3%

## 5. `winner_peak_giveback` (12 sym / 13 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, AVAV, CECO, CEG, DGII, DRS, FIVN, IESC, MMS, MOD, MWA, TGB
- **Evidence:** AGX peak~24% -> exit +8.3% (giveback~16pp, 17d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +8.0% (giveback~12pp, 33d, TARGET); CEG peak~19% -> exit +8.0% (giveback~11pp, 20d, TARGET); CECO peak~22% -> exit +8.0% (giveback~14pp, 33d, TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (62 sym / 1668 trades) — direction: expand, confidence: medium, 51.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1668 trades, 52%, high) vs target_contract_approach_fail → contract (733 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1668/3220 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 733/5955 trades (12%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABCB, ABG, ABM, ABT, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +23% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAPL +5% in 15d after TARGET; AAT +6% in 15d after TARGET; AAL +17% in 15d after TARGET | [B contract] A reached 83% of target then STOP; AAON reached 60% of target then STOP; AAON reached 54% of target then STOP; AAON reached 84% of target then STOP; AAON reached 53% of target then STOP; ACA reached 94% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (58 sym / 870 trades) — direction: expand, confidence: medium, 46.5% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (870 trades, 46%, high) vs stop_ok_never_worked → hold (566 trades, 30%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 870/1871 STOP exits (46%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 566/1871 STOPs (30%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI, ADMA
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAT STOP 2019-04-22 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-08 then back above entry/15d; AAON STOP 2023-10-20 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; AAT MFE~0.0% STOP; ABCB MFE~0.7% STOP

## 3. `band_tighten_weak_fill` (405 sym / 531 trades) — direction: tighten, confidence: medium, 8.9% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 531/5955 trades (9%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAT, ABBV, ABCB, ABM, ABR, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AGI, AGM, AGNC, AGO, AGX, AI
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; AAT MFE~0.0% STOP 6d; ABCB MFE~2.6% STOP 8d; ABCB MFE~0.7% STOP 3d

## 4. `target_contract_slow_hold` (132 sym / 152 trades) — direction: contract, confidence: low, 4.7% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 152/3220 TARGET exits (5%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, ADP, AEE, AFG, ALL, ALLE, ANDE, AON, ATO, ATR, AWK, AX, AZO, BALL, BF.B, BKHYY, BN, BNY
- **Evidence:** ABT TARGET 132d +8.0% (~0.06%/d); ACGL TARGET 130d +8.0% (~0.06%/d); ACN TARGET 141d +8.0% (~0.06%/d); ADP TARGET 125d +8.0% (~0.06%/d); AEE TARGET 148d +8.0% (~0.05%/d); AFG TARGET 342d +8.0% (~0.02%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
