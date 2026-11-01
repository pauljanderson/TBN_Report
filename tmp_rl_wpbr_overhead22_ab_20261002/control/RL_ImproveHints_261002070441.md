# RL Improve Hints — stamp `261002070441`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `winner_peak_giveback` (579 sym / 1241 trades)
- **Lever:** rl_trail_profit / rl_trail_stop (or trail2) or rl_partial_exit
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — enable trail or partial scale-out (hypothesis; one knob).
- **Symbols:** A, AA, AAL, AAMI, AAON, ABBV, ABCB, ABG, ABR, ABUS, ACA, ACAD, ACLS, ACRS, ACU, ADMA, ADNT, ADPT, ADSK, AEHR
- **Evidence:** A peak~43% -> exit +24.0% (giveback~19pp, 206d, ENTRY_TARGET); AA peak~47% -> exit +24.0% (giveback~23pp, 54d, ENTRY_TARGET); AA peak~40% -> exit +24.0% (giveback~16pp, 35d, ENTRY_TARGET); AA peak~31% -> exit +16.0% (giveback~15pp, 37d, TRAIL_STOP); AA peak~43% -> exit +24.0% (giveback~19pp, 44d, ENTRY_TARGET)

## 2. `slow_target_grind` (292 sym / 365 trades)
- **Lever:** rl_target_pct (contract) — alt: rl_exit_percent/days or rl_partial_exit
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target / partial exit / RL_EXIT_DAYS after a profit gate recycles capital sooner (turnover/Ann_ROR; one knob).
- **Symbols:** A, AA, AAON, ABCB, ACA, ACLS, ADSK, AEM, AGI, AGM, AGX, AGYS, AIG, AIR, ALNT, ALNY, AMAT, AMRC, ANDE, ANGO
- **Evidence:** A TARGET 206d +24.0% (~0.12%/d) 2021-01-07; AA TARGET 105d +24.0% (~0.23%/d) 2026-06-02; AAON TARGET 164d +24.0% (~0.15%/d) 2013-11-22; ABCB TARGET 108d +24.0% (~0.22%/d) 2021-05-21; ACA TARGET 464d +24.1% (~0.05%/d) 2023-12-14

## 3. `fat_stops` (254 sym / 407 trades)
- **Lever:** rl_stop_pct (tighter) or rl_exit_percent/days time-stop
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based cut_the_losers exit.
- **Symbols:** AAMI, AAPL, ABUS, ACAD, ACLS, ACRS, ADMA, ADNT, ADPT, AEHR, AFRM, AGYS, AHCO, ALB, ALDX, ALEC, ALNY, AMKR, AMN, AMRC

## 4. `mtm_giveback_stop` (188 sym / 217 trades)
- **Lever:** rl_trail_profit / rl_trail_stop (or trail2)
- **Suggestion:** Trades that ran ≥15% MTM then exited STOP — trails may salvage giveback.
- **Symbols:** ABUS, ACAD, ACLS, ADMA, ADPT, AES, AGM, AIR, AKR, ALDX, ALEC, ALG, ALNT, AMD, AMKR, AMN, AMTX, APLD, APO, APP
- **Evidence:** ABUS peak~19% -> STOP -10.3% (2026-01-16); ACAD peak~16% -> STOP -13.5% (2011-03-15); ACAD peak~16% -> STOP -12.7% (2012-11-14); ACLS peak~15% -> STOP -15.4% (2020-09-04); ADMA peak~15% -> STOP -8.5% (2024-12-18)

## 5. `post_target_quick_stop` (130 sym / 152 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (stop_loss / min_stack / under_sma_limit / none)
- **Suggestion:** Many symbols take a TARGET then immediately re-enter and STOP quickly — A/B modes: stop_loss (N×stop_pct), min_stack, under_sma_limit, or none cooldown; avoid calendar symbol_reentry_cooldown_days (kills NTRA ladder).
- **Symbols:** AA, AAL, AAON, ABG, ABUS, ACAD, ACRS, ADPT, AEHR, AEM, AGCO, AGI, AGX, ALNT, AMAT, AMKR, AMRC, ANIP, APPS, APYX
- **Evidence:** AA TARGET 2021-10-15 -> STOP 2021-10-27 (2d); AAL TARGET 2021-03-15 -> STOP 2021-04-20 (7d); AAON TARGET 2013-11-22 -> STOP 2023-01-04 (9d); ABG TARGET 2021-04-14 -> STOP 2021-11-03 (3d); ABUS TARGET 2024-09-06 -> STOP 2024-09-27 (9d)

## 6. `shallow_entry_sma50_fail` (117 sym / 144 trades)
- **Lever:** rl_dip_pct (tighter), rl_slope_threshold, rl_sma_qual stack
- **Suggestion:** Quick stops with entry hugging SMA50 suggest shallow dips / weak slope — tighten dip band or require stronger SMA50 slope.
- **Symbols:** ABG, ABNB, ADMA, ADNT, ADPT, AEHR, AGM, AGX, AMAT, AMWL, ANIP, APLD, ARW, ASM, ASMIY, AVAV, AVGO, BBY, BKTI, BNTX
- **Evidence:** ABG 2021-11-01 stop 3d entry~SMA50; ABNB 2025-03-04 stop 4d entry~SMA50; ADMA 2019-10-02 stop 3d entry~SMA50; ADMA 2023-08-24 stop 7d entry~SMA50; ADNT 2020-03-02 stop 3d entry~SMA50

## 7. `false_start_2022_2023` (103 sym / 118 trades)
- **Lever:** rl_slope_threshold, rl_cut_the_losers, optional start_date / regime filter
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — slope/extension gates or SPY INT weak block may help (tradeoff: fewer bull-market entries).
- **Symbols:** AAON, ACAD, ACLS, ADMA, AEHR, AFRM, AI, ALDX, ANET, ANF, AOSL, APLD, ASM, ATI, ATUSF, AVGO, AX, BANF, BBW, BELFA
- **Evidence:** AAON 2023 STOP 9d -7.3%; ACAD 2023 STOP 9d -8.2%; ACLS 2022 STOP 1d -7.6%; ADMA 2022 STOP 1d -7.3%; ADMA 2023 STOP 7d -8.5%

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_contract` (60 sym / 1521 trades) — direction: expand, confidence: medium, 58.7% of trades
- **Param:** stop_pct
- **Lever:** rl_stop_pct
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (1521 trades, 59%, high) vs stop_contract_dead_losers → contract (516 trades, 20%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 1521/2593 STOP exits (59%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 516/2593 STOPs (20%) never expanded (MFE<2%) and 407 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AA, AAL, AAMI, AAON, AAP, AAPL, AAT, ABBV, ABCB, ABNB, ABR, ABUS, ACAD, ACLS, ACRS, ADBE, ADMA, ADNT, ADPT, ADSK
- **Evidence:** [A expand] AA STOP 2017-04-13 then back above entry/15d; AA STOP 2021-06-17 then back above entry/15d; AA STOP 2021-10-27 then back above entry/15d; AAL STOP 2010-12-27 then back above entry/15d; AAL STOP 2014-04-08 then back above entry/15d; AAL STOP 2014-08-05 then back above entry/15d | [B contract] AA MFE~0.9% STOP; AAL MFE~1.3% STOP; AAL MFE~1.7% STOP; AAL MFE~1.1% STOP; AAP MFE~0.0% STOP; AAPL MFE~1.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (65 sym / 594 trades) — direction: expand, confidence: medium, 62.7% of trades
- **Param:** target_pct
- **Lever:** rl_target_pct / rl_expansion
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (594 trades, 63%, high) vs target_contract_slow_hold → contract (365 trades, 38%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 594/947 TARGET exits (63%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 365/947 TARGET exits (39%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** A, AA, AAL, AAMI, AAON, ABCB, ABUS, ACA, ACAD, ACLS, ACRS, ACU, ADMA, ADSK, AEHR, AEIS, AEM, AEO, AGCO, AGI
- **Evidence:** [A expand] AA +7% in 15d after TARGET; AA +15% in 15d after TARGET; AA +31% in 15d after TARGET; AAL +6% in 15d after TARGET; AAMI +7% in 15d after TARGET; AAON +6% in 15d after TARGET | [B contract] A TARGET 206d +24.0% (~0.12%/d); AA TARGET 105d +24.0% (~0.23%/d); AAON TARGET 164d +24.0% (~0.15%/d); ABCB TARGET 108d +24.0% (~0.22%/d); ACA TARGET 464d +24.1% (~0.05%/d); ACLS TARGET 101d +24.0% (~0.24%/d)

## 3. `band_tighten_weak_fill` (325 sym / 539 trades) — direction: tighten, confidence: medium, 13.9% of trades
- **Param:** band_pct
- **Lever:** rl_dip_pct / entry band (tighter dip = stricter)
- **Suggestion:** Tighten band/acceptance: 539/3889 trades (14%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** AA, AAL, AAON, AAP, ABNB, ABR, ABUS, ACLS, ACRS, ADMA, ADNT, ADPT, AEHR, AEIS, AER, AES, AGCO, AGI, AGM, AGX
- **Evidence:** AA MFE~0.9% STOP 2d; AAL MFE~1.3% STOP 12d; AAL MFE~1.7% STOP 7d; AAON MFE~2.1% STOP 9d; AAP MFE~0.0% STOP 2d; ABNB MFE~2.3% STOP 4d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
