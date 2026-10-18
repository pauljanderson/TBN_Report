# WPBR Improve Hints — stamp `261002221915`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (253 sym / 309 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ABCB, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEHR, AEIS, AFRM, AGM, AGNC, AGX, ALDX, ALEC, ALL, ALLE
- **Evidence:** AAMI TARGET 2015-04-07 -> STOP 2022-01-20 (8d); ABCB TARGET 2013-05-06 -> STOP 2015-08-25 (8d); ABUS TARGET 2014-04-22 -> STOP 2014-11-06 (1d); ACRS TARGET 2017-02-24 -> STOP 2020-11-16 (3d); ACRS TARGET 2025-03-24 -> STOP 2025-06-17 (5d)

## 2. `slow_target_grind` (178 sym / 226 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, AEE, AFG, AFL, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AWK, AZO, BALL, BAX, BFC
- **Evidence:** ACGL TARGET 134d +10.0% (~0.07%/d) 2012-10-05; ACN TARGET 145d +10.0% (~0.07%/d) 2013-12-23; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24; AFL TARGET 315d +10.0% (~0.03%/d) 2017-04-28

## 3. `fat_stops` (138 sym / 164 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACRS, ADMA, ADNT, ADPT, AEHR, AHCO, AHT, AI, ALEC, ALGN, ALLE, ALNT, AMN, AMP, AMRC, AMWL, AOSL, APPS, APYX

## 4. `false_start_2022_2023` (97 sym / 107 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, AMTX, AOUT, APLD, AVGO, AZO, BILI, CB, CCEP, CCL
- **Evidence:** AAMI 2022 STOP 8d -7.4%; ACRS 2023 STOP 7d -11.4%; ACLS 2022 STOP 1d -8.1%; ADPT 2022 STOP 8d -16.3%; ADMA 2022 STOP 15d -7.8%

## 5. `winner_peak_giveback` (18 sym / 19 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ALNT, AVAV, AX, CECO, DGII, ESEA, F, FIVN, FSLR, IRMD, JMIA, KEX, KINS, MOD, MWA, SENEA, W
- **Evidence:** AGX peak~24% -> exit +10.0% (giveback~14pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); AX peak~28% -> exit +14.0% (giveback~14pp, 92d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (64 sym / 1387 trades) — direction: expand, confidence: medium, 51.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1387 trades, 51%, high) vs target_contract_approach_fail → contract (750 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1387/2712 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 750/5526 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU
- **Evidence:** [A expand] AA +21% in 15d after TARGET; AAT +7% in 15d after TARGET; ABBNY +8% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +9% in 15d after TARGET | [B contract] A reached 66% of target then STOP; AAPL reached 81% of target then STOP; AAON reached 92% of target then STOP; AAL reached 92% of target then STOP; ACA reached 75% of target then STOP; ACRS reached 61% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (57 sym / 918 trades) — direction: expand, confidence: medium, 46.3% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (918 trades, 46%, high) vs stop_ok_never_worked → hold (515 trades, 26%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 918/1981 STOP exits (46%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 515/1981 STOPs (26%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI, ADMA
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAPL STOP 2013-04-17 then back above entry/15d; AAT STOP 2019-04-22 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-08 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; AAT MFE~0.0% STOP; ABCB MFE~0.7% STOP

## 3. `band_tighten_weak_fill` (371 sym / 473 trades) — direction: tighten, confidence: medium, 8.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 473/5526 trades (9%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAT, ABBV, ABCB, ABM, ABR, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AGM, AGNC, AGX, AI, AIT, AJG
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; AAT MFE~0.0% STOP 6d; ABCB MFE~2.6% STOP 8d; ABCB MFE~0.7% STOP 3d

## 4. `target_contract_slow_hold` (178 sym / 226 trades) — direction: contract, confidence: medium, 8.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 226/2712 TARGET exits (8%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, AEE, AFG, AFL, AGNC, ALL, ALLE, AMT, ANDE, AON, ARE, ARW, ATO, ATR, AWK, AZO, BALL, BAX, BFC
- **Evidence:** ACGL TARGET 134d +10.0% (~0.07%/d); ACN TARGET 145d +10.0% (~0.07%/d); ACN TARGET 107d +10.0% (~0.09%/d); AEE TARGET 169d +10.0% (~0.06%/d); AFL TARGET 315d +10.0% (~0.03%/d); AFG TARGET 350d +10.0% (~0.03%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
