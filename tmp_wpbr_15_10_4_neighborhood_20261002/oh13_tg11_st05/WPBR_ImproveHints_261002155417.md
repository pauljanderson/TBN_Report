# WPBR Improve Hints — stamp `261002155417`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `post_target_quick_stop` (337 sym / 428 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (none/under_sma_limit/min_stack/stop_loss) or longer symbol_reentry_cooldown_days
- **Suggestion:** TARGET then quick STOP re-entry — prefer post-win-only gates over blanket cd alone.
- **Symbols:** AAT, ABCB, ABNB, ABUS, ACAD, ACLS, ACRS, ACU, ADPT, ADSK, AEIS, AFRM, AGM, AGNC, AGX, ALB, ALDX, ALEC, ALL, ALLE
- **Evidence:** ABNB TARGET 2021-11-04 -> STOP 2021-12-01 (5d); ABUS TARGET 2014-04-22 -> STOP 2014-11-06 (1d); AAT TARGET 2013-10-16 -> STOP 2016-01-20 (0d); ACAD TARGET 2012-10-05 -> STOP 2012-10-22 (10d); ACLS TARGET 2022-05-27 -> STOP 2022-06-16 (1d)

## 2. `slow_target_grind` (227 sym / 297 trades)
- **Lever:** target_pct (contract) — alt: shorter time_stop_days or STRENGTH-style early take
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target (or early take) recycles capital sooner; prefer turnover/Ann_ROR over waiting for one fat tag (one knob A/B; not an optimize sweep).
- **Symbols:** ABT, ACGL, ACN, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AKR, ALL, AMH, AMT, ANDE, AON, APD, ARE, ARW, ASH
- **Evidence:** ABT TARGET 106d +11.0% (~0.10%/d) 2019-06-25; ADP TARGET 263d +11.0% (~0.04%/d) 2020-01-21; AEE TARGET 170d +11.0% (~0.06%/d) 2019-09-25; ACGL TARGET 137d +11.0% (~0.08%/d) 2012-10-08; AEP TARGET 148d +11.0% (~0.07%/d) 2019-09-03

## 3. `fat_stops` (180 sym / 227 trades)
- **Lever:** stop_pct (tighter) or time-stop / cut_the_losers
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based exit.
- **Symbols:** AAMI, ABG, ABR, ABUS, ACLS, ACRS, ADMA, ADNT, ADPT, ADSK, AEHR, AGYS, AHCO, AHT, AI, ALEC, ALGN, ALLE, ALNY, AMN

## 4. `false_start_2022_2023` (139 sym / 154 trades)
- **Lever:** slope/regime gates, optional start_date / SPY weak block
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — regime filters may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAMI, ACLS, ACRS, ADBE, ADMA, ADPT, AEHR, AFRM, AGM, AI, AJG, AMP, AMTX, AMWL, AN, AOUT, APLD, ATUSF, AVGO, AZO
- **Evidence:** AAMI 2022 STOP 8d -7.4%; ACLS 2022 STOP 1d -8.1%; ACRS 2023 STOP 7d -11.4%; ADMA 2022 STOP 15d -7.8%; ADPT 2022 STOP 8d -16.3%

## 5. `winner_peak_giveback` (27 sym / 27 trades)
- **Lever:** trail (trailing_stop_increment / sma_stop_days / chandelier) or partial scale-out
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — trail or scale-out may lock more of the run (hypothesis; one trail knob).
- **Symbols:** AGX, ALNT, AVAV, AX, CECO, DGII, DOCU, ESEA, F, FIVN, FSLR, HBAN, IRMD, JMIA, KEX, KINS, LINC, LMAT, MOD, MWA
- **Evidence:** AGX peak~24% -> exit +11.0% (giveback~13pp, 17d, TARGET); ALNT peak~27% -> exit +15.5% (giveback~11pp, 28d, GAP_UP); AVAV peak~34% -> exit +20.9% (giveback~13pp, 23d, GAP_UP); AX peak~28% -> exit +14.0% (giveback~14pp, 92d, GAP_UP); CECO peak~22% -> exit +11.0% (giveback~11pp, 33d, TARGET)

## 6. `early_run_long_tail` (9 sym / 10 trades)
- **Lever:** trail after +10% / lower target_pct / shorter time_stop after milestone
- **Suggestion:** Hit +10% within 25 days then held ≥80 days — capital sat after the early run; test trail-after-+10%, STRENGTH-style early take, or shorter time_stop (turnover over max single-trade profit).
- **Symbols:** ACN, ENVA, HAS, JACK, NOC, SPG, STN, TFX, TTWO
- **Evidence:** ACN +10% by day 24 then held 89d exit +11.3% (GAP_UP); ENVA +10% by day 15 then held 99d exit +11.0% (TARGET); HAS +10% by day 22 then held 231d exit +11.0% (TARGET); JACK +10% by day 14 then held 83d exit +11.7% (GAP_UP); JACK +10% by day 15 then held 183d exit +11.0% (TARGET)

## Parameter suggestions (band / target / stop)

## 1. `target_pct_tension_expand_vs_contract` (55 sym / 1604 trades) — direction: expand, confidence: medium, 50.4% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (1604 trades, 50%, high) vs target_contract_approach_fail → contract (930 trades, 14%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 1604/3184 TARGET exits (50%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target: 930/6880 trades (14%) reached 50%–95% of entry→target distance (via MAX_PRICE) then exited STOP/TIME without tagging — a closer target may lock gains more often.
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || non-TARGET exit AND target_progress in [0.5,0.95)
- **Symbols:** A, AA, AAL, AAON, AAPL, AAT, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACM, ACN, ACRS, ACU, ADBE
- **Evidence:** [A expand] AA +20% in 15d after TARGET; AAL +14% in 15d after TARGET; AAL +18% in 15d after TARGET; AAL +8% in 15d after TARGET; AAL +12% in 15d after TARGET; ABNB +19% in 15d after TARGET | [B contract] AA reached 78% of target then STOP; AAON reached 83% of target then STOP; AAL reached 84% of target then STOP; ABNB reached 70% of target then STOP; A reached 60% of target then STOP; AAPL reached 74% of target then STOP

## 2. `stop_pct_tension_expand_vs_hold` (59 sym / 1220 trades) — direction: expand, confidence: medium, 45.8% of trades
- **Param:** stop_pct
- **Lever:** stop_pct / atr_stop
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1220 trades, 46%, high) vs stop_ok_never_worked → hold (696 trades, 26%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1220/2662 STOP exits (46%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Stop may be adequate: 696/2662 STOPs (26%) never worked (MFE<2%) — expanding the stop likely won't rescue these; focus filters/entry.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** A, AAMI, AAON, AAPL, AAT, ABBV, ABCB, ABG, ABM, ABNB, ABR, ABUS, ACA, ACAD, ACLS, ACN, ACRS, ACU, ADBE, ADI
- **Evidence:** [A expand] AAMI STOP 2022-01-20 then back above entry/15d; AAON STOP 2011-03-11 then back above entry/15d; AAON STOP 2013-11-08 then back above entry/15d; AAON STOP 2017-08-03 then back above entry/15d; AAON STOP 2019-10-02 then back above entry/15d; AAON STOP 2023-10-18 then back above entry/15d | [B hold] AAMI MFE~1.6% STOP; AAON MFE~1.3% STOP; ABBV MFE~0.0% STOP; A MFE~0.0% STOP; ABR MFE~1.9% STOP; ACA MFE~1.9% STOP

## 3. `band_tighten_weak_fill` (469 sym / 657 trades) — direction: tighten, confidence: medium, 9.5% of trades
- **Param:** band_pct
- **Lever:** band_pct / ATR band / zone acceptance
- **Suggestion:** Tighten band/acceptance: 657/6880 trades (10%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** A, AAMI, AAT, ABBV, ABCB, ABM, ABR, ACLS, ACN, ACRS, ADM, ADPT, ADSK, AEHR, AEIS, AGI, AGM, AGNC, AGO, AGX
- **Evidence:** AAMI MFE~1.6% STOP 8d; ABBV MFE~0.0% STOP 0d; A MFE~0.0% STOP 1d; ABR MFE~1.9% STOP 7d; ABM MFE~1.0% STOP 14d; AAT MFE~0.0% STOP 0d

## 4. `target_contract_slow_hold` (227 sym / 297 trades) — direction: contract, confidence: medium, 9.3% of trades
- **Param:** target_pct
- **Lever:** target_pct / atr_target
- **Suggestion:** Contract target (turnover): 297/3184 TARGET exits (9%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** TARGET exit AND DAYS_HELD >= 100
- **Symbols:** ABT, ACGL, ACN, ADP, AEE, AEP, AFG, AFL, AGNC, AJG, AKR, ALL, AMH, AMT, ANDE, AON, APD, ARE, ARW, ASH
- **Evidence:** ABT TARGET 106d +11.0% (~0.10%/d); ADP TARGET 263d +11.0% (~0.04%/d); AEE TARGET 170d +11.0% (~0.06%/d); ACGL TARGET 137d +11.0% (~0.08%/d); AEP TARGET 148d +11.0% (~0.07%/d); ACN TARGET 291d +11.0% (~0.04%/d)

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
