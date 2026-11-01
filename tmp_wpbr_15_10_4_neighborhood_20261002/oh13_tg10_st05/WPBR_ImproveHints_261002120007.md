# WPBR Improve Hints — stamp `261002120007`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (339 sym / 432 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAT, ABCB, ABNB, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADPT, ADSK, AEIS, AFRM, AGM, AGNC, AGX, ALB, ALDX, ALEC, ALL
- **Evidence:** ABNB TARGET 2021-09-24 -> STOP 2021-12-01 (5d); ABUS TARGET 2014-04-22 -> STOP 2014-11-06 (1d); ACLS TARGET 2022-05-27 -> STOP 2022-06-16 (1d); ACLS TARGET 2026-08-06 -> STOP 2026-09-14 (6d); AAT TARGET 2013-10-15 -> STOP 2016-01-20 (0d)

## 2. `slow_target_grind` (194 sym / 250 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ACGL, ACN, AEE, AFG, AFL, AGNC, ALL, ALLE, AMT, AMZN, ANDE, AON, ARE, ARW, ATO, ATR, AWK, AX, AZO, BA
- **Evidence:** ACN TARGET 145d +10.0% (~0.07%/d) 2013-12-23; ACN TARGET 107d +10.0% (~0.09%/d) 2015-07-31; ACGL TARGET 134d +10.0% (~0.07%/d) 2012-10-05; AEE TARGET 169d +10.0% (~0.06%/d) 2019-09-24; AGNC TARGET 176d +10.0% (~0.06%/d) 2016-10-25

## 3. `fat_stops` (179 sym / 225 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABG, ABR, ABUS, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AGYS, AHCO, AHT, AI, ALEC, ALGN, ALLE, ALNT, AMN

## 4. `false_start_2022_2023` (137 sym / 151 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, AMP, AMTX, AMWL, AN, AOUT, APLD, AVGO, AZO, BILI
- **Evidence:** AAMI 2022 STOP 8d -7.4%; ACLS 2022 STOP 1d -8.1%; ACRS 2023 STOP 7d -11.4%; ADMA 2022 STOP 15d -7.8%; ADPT 2022 STOP 8d -16.3%

## 5. `winner_peak_giveback` (24 sym / 25 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ALNT, AVAV, AX, CECO, DGII, DOCU, ESE, ESEA, F, FIVN, FSLR, IRMD, JMIA, KEX, KINS, LINC, LMAT, MOD, MWA
- **Evidence:** AGX peak~24% -> exit +10.0% (giveback~14pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AVAV peak~20% -> exit +10.0% (giveback~10pp, 33d, TARGET); AX peak~28% -> exit +14.0% (giveback~14pp, 92d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (59 sym / 1734 trades) — direction: expand, confidence: medium, 51.8% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1734 trades, 52%, high) vs target_contract_approach_fail → contract (919 trades, 13%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1734/3348 TARGET exits (52%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 919/6923 trades (13%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABUS, ACA, ACAD, ACGL, ACLS, ACM, ACN, ACRS
- **Evidence:** [A expand] AA +10% in 15d after TARGET; AA +21% in 15d after TARGET; AAL +15% in 15d after TARGET; AAL +16% in 15d after TARGET; AAL +9% in 15d after TARGET; AAL +13% in 15d after TARGET | [B contract] AAON reached 92% of target then STOP; AAON reached 52% of target then STOP; AA reached 86% of target then STOP; AAL reached 92% of target then STOP; A reached 66% of target then STOP; ABNB reached 77% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (59 sym / 1167 trades) — direction: expand, confidence: medium, 46.0% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1167 trades, 46%, high) vs stop_ok_never_worked → hold (697 trades, 28%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1167/2535 STOP exits (46%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 697/2535 STOPs (27%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI
- **Evidence:** [A expand] AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-08 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d; AAON STOP 2024-06-04 then back above entry/15d; AAMI STOP 2022-01-20 then back above entry/15d | [B hold] AAON MFE~1.3% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; A MFE~0.0% STOP; ABR MFE~1.9% STOP; ABM MFE~1.0% STOP

## 3. `band_tighten_weak_fill` (467 sym / 658 trades) — direction: tighten, confidence: medium, 9.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 658/6923 trades (10%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAT, ABBV, ABCB, ABM, ABR, ACLS, ACN, ACRS, ADM, ADPT, ADSK, AEHR, AEIS, AGI, AGM, AGNC, AGO, AGX
- **Evidence:** AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; A MFE~0.0% STOP 1d; ABR MFE~1.9% STOP 7d; ABM MFE~1.0% STOP 14d; ACLS MFE~1.3% STOP 1d

## 4. `target_contract_slow_hold` (194 sym / 250 trades) — direction: contract, confidence: low, 7.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 250/3348 TARGET exits (7%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ACGL, ACN, AEE, AFG, AFL, AGNC, ALL, ALLE, AMT, AMZN, ANDE, AON, ARE, ARW, ATO, ATR, AWK, AX, AZO, BA
- **Evidence:** ACN TARGET 145d +10.0% (~0.07%/d); ACN TARGET 107d +10.0% (~0.09%/d); ACGL TARGET 134d +10.0% (~0.07%/d); AEE TARGET 169d +10.0% (~0.06%/d); AGNC TARGET 176d +10.0% (~0.06%/d); AFL TARGET 315d +10.0% (~0.03%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
