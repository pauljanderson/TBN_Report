# RL Improve Hints — stamp `261002070512`

Rule-based **hypotheses** (missed-trade / pattern evidence), not an optimization mandate. If nothing actionable and charts already look on-thesis, leave params alone. Acting on a hint: one knob, ≤2 alternatives, ToS before/after, quality over max PnL (see docs/HYPOTHESIS_TEST.md). Use with ONE_LINER / FIT_ASSESSMENT / charts.

## Taken-trade patterns

## 1. `winner_peak_giveback` (194 sym / 251 trades)
- **Lever:** rl_trail_profit / rl_trail_stop (or trail2) or rl_partial_exit
- **Suggestion:** Winners that peaked ≥15% MFE then exited ≥10pp below peak — enable trail or partial scale-out (hypothesis; one knob).
- **Symbols:** AA, ABG, ACLS, ACU, ADMA, AEIS, AEM, AGCO, AGI, AGX, AIR, ALNT, ALNY, AMAT, ANAB, ANIP, AOSL, APP, APPS, ARGX
- **Evidence:** AA peak~48% -> exit +24.0% (giveback~24pp, 38d, ENTRY_TARGET); AA peak~31% -> exit +16.0% (giveback~15pp, 37d, TRAIL_STOP); ABG peak~41% -> exit +24.0% (giveback~17pp, 50d, ENTRY_TARGET); ACLS peak~44% -> exit +24.0% (giveback~20pp, 28d, ENTRY_TARGET); ACLS peak~41% -> exit +24.0% (giveback~17pp, 101d, ENTRY_TARGET)

## 2. `fat_stops` (72 sym / 78 trades)
- **Lever:** rl_stop_pct (tighter) or rl_exit_percent/days time-stop
- **Suggestion:** Large STOP losses dominate — tighter stop or time-based cut_the_losers exit.
- **Symbols:** ABUS, ACAD, ACRS, AEHR, ALEC, AMKR, AMTX, ANET, ANIK, AOSL, APPS, ASM, ATLC, ATUSF, AXON, BANF, BELFA, BFC, BILI, CASH

## 3. `slow_target_grind` (48 sym / 50 trades)
- **Lever:** rl_target_pct (contract) — alt: rl_exit_percent/days or rl_partial_exit
- **Suggestion:** Many TARGET hits took ≥100 days — hypothesis: closer target / partial exit / RL_EXIT_DAYS after a profit gate recycles capital sooner (turnover/Ann_ROR; one knob).
- **Symbols:** ACLS, AIR, AVGO, BC, BILI, CE, CLX, CNO, CRZBY, CTVA, CYTK, CZR, DCO, DECK, DKNG, DXPE, FAST, FIVN, FN, FTNT
- **Evidence:** ACLS TARGET 101d +24.0% (~0.24%/d) 2023-06-12; AIR TARGET 148d +24.0% (~0.16%/d) 2026-08-04; AVGO TARGET 148d +24.0% (~0.16%/d) 2014-07-03; BC TARGET 117d +24.0% (~0.21%/d) 2021-05-03; BILI TARGET 116d +24.0% (~0.21%/d) 2020-11-19

## 4. `mtm_giveback_stop` (33 sym / 34 trades)
- **Lever:** rl_trail_profit / rl_trail_stop (or trail2)
- **Suggestion:** Trades that ran ≥15% MTM then exited STOP — trails may salvage giveback.
- **Symbols:** ACAD, AGX, ALNT, AMKR, APP, APPS, ARES, BELFA, BILI, CENX, CRUS, CRWD, DDOG, DELL, ENSG, ESOA, FN, HIMS, KINS, LSCC
- **Evidence:** ACAD peak~16% -> STOP -12.7% (2012-11-14); AGX peak~18% -> STOP -10.9% (2011-08-08); ALNT peak~18% -> STOP -9.8% (2025-11-06); AMKR peak~17% -> STOP -12.7% (2026-03-06); APP peak~17% -> STOP -9.0% (2025-11-18)

## 5. `shallow_entry_sma50_fail` (23 sym / 25 trades)
- **Lever:** rl_dip_pct (tighter), rl_slope_threshold, rl_sma_qual stack
- **Suggestion:** Quick stops with entry hugging SMA50 suggest shallow dips / weak slope — tighten dip band or require stronger SMA50 slope.
- **Symbols:** AMAT, AMRC, AMTX, ANIP, APLD, ASM, CAMT, COIN, CYTK, DOCN, FLEX, GCT, GOLD, HIMS, INOD, LMND, MRNA, RBLX, ROKU, SMCI
- **Evidence:** AMAT 2026-07-23 stop 5d entry~SMA50; AMRC 2020-03-10 stop 2d entry~SMA50; AMRC 2021-12-14 stop 2d entry~SMA50; AMTX 2014-05-05 stop 5d entry~SMA50; ANIP 2014-04-10 stop 2d entry~SMA50

## 6. `post_target_quick_stop` (17 sym / 20 trades)
- **Lever:** rl_post_target_reentry_bars + rl_post_target_reentry_mode (stop_loss / min_stack / under_sma_limit / none)
- **Suggestion:** Many symbols take a TARGET then immediately re-enter and STOP quickly — A/B modes: stop_loss (N×stop_pct), min_stack, under_sma_limit, or none cooldown; avoid calendar symbol_reentry_cooldown_days (kills NTRA ladder).
- **Symbols:** AMAT, ANIP, APPS, ASM, CMCL, CYTK, CZR, HIMS, HOOD, LUGDF, MRNA, NET, ONTO, SNDK, STX, TCI, TSLA
- **Evidence:** AMAT TARGET 2026-06-15 -> STOP 2026-07-27 (5d); ANIP TARGET 2011-07-08 -> STOP 2014-04-11 (2d); APPS TARGET 2018-02-13 -> STOP 2020-10-28 (3d); APPS TARGET 2020-11-05 -> STOP 2021-03-04 (9d); ASM TARGET 2025-10-15 -> STOP 2025-10-27 (5d)

## 7. `false_start_2022_2023` (7 sym / 7 trades)
- **Lever:** rl_slope_threshold, rl_cut_the_losers, optional start_date / regime filter
- **Suggestion:** Cluster of short 2022–2023 STOP false starts — slope/extension gates or SPY INT weak block may help (tradeoff: fewer bull-market entries).
- **Symbols:** AOSL, APLD, KINS, MCRI, MSTR, SMCI, SPRY
- **Evidence:** AOSL 2022 STOP 3d -7.4%; APLD 2023 STOP 4d -11.3%; KINS 2023 STOP 11d -8.7%; MCRI 2022 STOP 10d -9.1%; MSTR 2023 STOP 4d -8.9%

## Parameter suggestions (band / target / stop)

## 1. `stop_pct_tension_expand_vs_contract` (73 sym / 241 trades) — direction: expand, confidence: medium, 68.3% of trades
- **Param:** stop_pct
- **Lever:** rl_stop_pct
- **Suggestion:** Mixed stop_pct evidence (lean expand): stop_expand_post_stop_rebound → expand (241 trades, 68%, high) vs stop_contract_dead_losers → contract (43 trades, 12%, medium). Independent trade subsets — not a single high-confidence knob move. A: Expand stop: 241/353 STOP exits (68%) recovered above entry within 15 bars — classic wick-through / stopped-out-of-winner pattern. B: Tighten stop or cut faster: 43/353 STOPs (12%) never expanded (MFE<2%) and 78 fat losses (pnl%≤-12) — losers that don't rebound.
- **Heuristic:** reconcile opposing lenses: STOP exit then OHLC High >= entry within 15 bars || STOP exit AND MAX_PRICE MFE < 2% (never-worked loser)
- **Symbols:** AAL, ABR, ABUS, ACAD, ACLS, ACRS, ACU, ADPT, AEHR, AEM, AER, AFRM, AGI, AGX, ALEC, ALNT, AMAT, AMD, AMKR, AMRC
- **Evidence:** [A expand] AAL STOP 2014-08-05 then back above entry/15d; AAL STOP 2015-02-09 then back above entry/15d; ABR STOP 2011-03-04 then back above entry/15d; ABUS STOP 2014-04-08 then back above entry/15d; ACAD STOP 2011-05-23 then back above entry/15d; ACAD STOP 2012-11-14 then back above entry/15d | [B contract] ACRS MFE~0.0% STOP; AEHR MFE~0.4% STOP; AEHR MFE~0.0% STOP; AMRC MFE~0.5% STOP; ANF MFE~1.2% STOP; ANIP MFE~0.0% STOP

## 2. `target_pct_tension_expand_vs_contract` (69 sym / 125 trades) — direction: expand, confidence: medium, 64.8% of trades
- **Param:** target_pct
- **Lever:** rl_target_pct / rl_expansion
- **Suggestion:** Mixed target_pct evidence (lean expand): target_expand_post_exit → expand (125 trades, 65%, high) vs target_contract_slow_hold → contract (50 trades, 26%, high). Independent trade subsets — not a single high-confidence knob move. A: Expand target: 125/193 TARGET exits (65%) continued ≥5% higher within 15 bars — possible money left on table. B: Contract target (turnover): 50/193 TARGET exits (26%) held ≥100d — closer target may recycle capital sooner (Ann_ROR / trades-per-year over max single-trade PnL; one-knob hypothesis).
- **Heuristic:** reconcile opposing lenses: TARGET exit then OHLC fwd max-gain >= 5% in 15 bars || TARGET exit AND DAYS_HELD >= 100
- **Symbols:** AA, ACLS, ADMA, AEIS, AGX, AIR, ALNT, ALNY, AMAT, AMKR, ANAB, ANIP, APP, APPS, ASM, ATLC, AVGO, AX, BC, BILI
- **Evidence:** [A expand] AA +14% in 15d after TARGET; ACLS +11% in 15d after TARGET; ADMA +12% in 15d after TARGET; AEIS +7% in 15d after TARGET; AGX +7% in 15d after TARGET; ALNT +17% in 15d after TARGET | [B contract] ACLS TARGET 101d +24.0% (~0.24%/d); AIR TARGET 148d +24.0% (~0.16%/d); AVGO TARGET 148d +24.0% (~0.16%/d); BC TARGET 117d +24.0% (~0.21%/d); BILI TARGET 116d +24.0% (~0.21%/d); CE TARGET 159d +24.0% (~0.15%/d)

## 3. `band_tighten_weak_fill` (41 sym / 46 trades) — direction: tighten, confidence: medium, 8.0% of trades
- **Param:** band_pct
- **Lever:** rl_dip_pct / entry band (tighter dip = stricter)
- **Suggestion:** Tighten band/acceptance: 46/575 trades (8%) entered but expanded <3% MFE then STOP/TIME — shallow fills may be noise.
- **Heuristic:** weak_fill: MAX_PRICE MFE < 3.0% AND exit in STOP|TIME AND days_held<=15 AND pnl%<5
- **Symbols:** ACRS, AEHR, AMRC, ANF, ANIP, AOSL, APPS, ARM, ASM, ATUSF, AXON, CELH, CLF, CMCL, CZR, DDS, ESEA, ESOA, FLEX, GCT
- **Evidence:** ACRS MFE~0.0% STOP 7d; AEHR MFE~0.4% STOP 2d; AEHR MFE~0.0% STOP 4d; AMRC MFE~0.5% STOP 2d; ANF MFE~1.2% STOP 8d; ANIP MFE~0.0% STOP 2d

## Peer-learn (cross-system overlap)

## 1. `peer_learn_no_peers` (0 sym / 0 trades) — direction: adopt, confidence: insufficient
- **Param:** cross_system
- **Lever:** peer Closed overlap
- **Suggestion:** No peer LatestRun/stamped Closed books found under drive/.
- **Heuristic:** discover {SYS}_LatestRun_Closed.csv
- **Symbols:** 
