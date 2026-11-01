# WPBR Improve Hints — stamp `261003081320`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `small_target_wins` (986 sym / 3307 trades)
- **Lever:** target_pct / expansion / partial_exit
- **Suggestion:** Many small TARGET wins — consider higher target or partial scale-out.
- **Symbols:** A, AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBNY, ABCB, ABG, ABM, ABNB, ABR, ABT, ABUS, ACA, ACAD, ACGL, ACLS

## 2. `post_target_quick_stop` (272 sym / 337 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAMI, ABCB, ACAD, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AFRM, AGX, AKAM, ALDX, ALEC, ALGN, ALL, ALLE, AMD, AMKR
- **Evidence:** AAMI TARGET 2015-03-20 -> STOP 2022-01-20 (8d); ABCB TARGET 2013-05-03 -> STOP 2015-08-25 (8d); ACRS TARGET 2017-02-23 -> STOP 2020-11-16 (3d); ACRS TARGET 2023-07-13 -> STOP 2023-10-24 (7d); ACRS TARGET 2025-03-24 -> STOP 2025-06-17 (5d)

## 3. `fat_stops` (114 sym / 138 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** ABR, ACRS, ACU, ADNT, ADPT, AEHR, AI, ALEC, ALGN, ALLE, ALNT, AMN, AMP, AMRC, AMWL, AOSL, APPS, APYX, BELFB, BLDR

## 4. `slow_target_grind` (105 sym / 117 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, AFG, ALL, ANDE, ATO, ATR, AWK, AZO, BALL, BDX, BF.B, BKNG, BN, BRK.B, BXP, CB, CBOE, CCEP
- **Evidence:** ABT TARGET 132d +7.0% (~0.05%/d) 2020-01-22; ACGL TARGET 127d +7.0% (~0.06%/d) 2012-09-28; ACN TARGET 110d +7.0% (~0.06%/d) 2013-11-18; AFG TARGET 337d +7.0% (~0.02%/d) 2013-01-04; ALL TARGET 132d +7.0% (~0.05%/d) 2019-11-18

## 5. `false_start_2022_2023` (88 sym / 95 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACRS, ADBE, ADPT, AEHR, AFRM, AGM, AI, AJG, AMTX, AOUT, APLD, AVGO, AZO, CB, CCEP, CCL, CGC, CI, COIN
- **Evidence:** AAMI 2022 STOP 8d -7.4%; ACRS 2023 STOP 7d -11.4%; ADPT 2022 STOP 8d -16.3%; ADBE 2022 STOP 15d -6.3%; AEHR 2022 STOP 7d -7.9%

## 6. `winner_peak_giveback` (12 sym / 12 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, AVAV, CECO, CEG, DGII, IESC, KINS, MMS, MOD, MWA, SSNC, TSSI
- **Evidence:** AGX peak~24% -> exit +8.3% (giveback~16pp, 17d, GAP_UP); AVAV peak~20% -> exit +7.6% (giveback~13pp, 33d, GAP_UP); CEG peak~19% -> exit +7.0% (giveback~12pp, 20d, TARGET); CECO peak~22% -> exit +7.0% (giveback~15pp, 33d, TARGET); DGII peak~23% -> exit +11.4% (giveback~12pp, 42d, GAP_UP)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (64 sym / 1690 trades) — direction: expand, confidence: medium, 51.1% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1690 trades, 51%, high) vs target_contract_approach_fail → contract (652 trades, 11%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1690/3307 TARGET exits (51%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 652/5727 trades (11%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** AA, AAL, AAON, AAPL, ABCB, ABG, ABM, ABT, ABUS, ACAD, ACGL, ACLS, ACM, ACN, ACRS, ACU, ADBE, ADI, ADMA, ADNT
- **Evidence:** [A expand] AA +24% in 15d after TARGET; AAL +18% in 15d after TARGET; AAL +20% in 15d after TARGET; AAL +12% in 15d after TARGET; AAL +16% in 15d after TARGET; AAPL +6% in 15d after TARGET | [B contract] AAON reached 69% of target then STOP; AAON reached 61% of target then STOP; AAON reached 61% of target then STOP; ABUS reached 59% of target then STOP; ABG reached 81% of target then STOP; ABG reached 65% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (52 sym / 737 trades) — direction: expand, confidence: medium, 46.1% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (737 trades, 46%, high) vs stop_ok_never_worked → hold (534 trades, 33%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 737/1598 STOP exits (46%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 534/1598 STOPs (33%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAT, ABBV, ABCB, ABG, ABM, ABR, ABUS, ACAD, ACLS, ACN, ACRS, ACU, ADI, ADNT, ADP, ADPT, ADSK
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; ABBV STOP 2015-02-04 then back above entry/15d; AAT STOP 2019-04-22 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-08 then back above entry/15d; AAON STOP 2023-10-20 then back above entry/15d | [B hold] A MFE~0.0% STOP; AAMI MFE~1.6% STOP; ABBV MFE~0.0% STOP; AAT MFE~1.7% STOP; AAT MFE~0.0% STOP; ABR MFE~1.9% STOP

## 3. `band_tighten_weak_fill` (377 sym / 492 trades) — direction: tighten, confidence: medium, 8.6% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 492/5727 trades (9%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAT, ABBV, ABCB, ABM, ABR, ACLS, ACN, ACRS, ADPT, ADSK, AEHR, AEIS, AGM, AGNC, AGX, AI, AIT, AJG
- **Evidence:** A MFE~0.0% STOP 1d; AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; AAT MFE~0.0% STOP 6d; ABR MFE~1.9% STOP 7d; ABCB MFE~2.6% STOP 8d

## 4. `target_contract_slow_hold` (105 sym / 117 trades) — direction: contract, confidence: low, 3.5% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 117/3307 TARGET exits (4%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, AFG, ALL, ANDE, ATO, ATR, AWK, AZO, BALL, BDX, BF.B, BKNG, BN, BRK.B, BXP, CB, CBOE, CCEP
- **Evidence:** ABT TARGET 132d +7.0% (~0.05%/d); ACGL TARGET 127d +7.0% (~0.06%/d); ACN TARGET 110d +7.0% (~0.06%/d); AFG TARGET 337d +7.0% (~0.02%/d); ALL TARGET 132d +7.0% (~0.05%/d); ANDE TARGET 107d +7.0% (~0.07%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
