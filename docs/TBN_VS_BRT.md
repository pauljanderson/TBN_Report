# TBN vs BRT

| Name | Meaning |
|------|---------|
| **TBN** (Twin Beacon Networks) | Shared multi-system **engine / platform** (`stock_analysis/rocket_tbn.py`) |
| **BRT** (Break and ReTest) | One **strategy system** hosted by TBN (`brt_zones=true` → `BRT_*` outputs) |

## Systems on the TBN engine

BRT, WPBR, YH, MTS, RL, RS, IND, VEC, … — selected by `-v` flags / batch wrappers (`run_brt.bat`, `run_rl.bat`, `run_rs.bat`, …). Output CSV prefixes stay system-named (`BRT_Closed_*`, `RL_Closed_*`, `RS_Closed_*`, …).

## Invoke

```bat
python stock_analysis\rocket_tbn.py data\newdata\data -o drive ...
```

Legacy path still works (shim):

```bat
python stock_analysis\rocket_brt.py ...
```

RS thin launcher (also a shim into TBN):

```bat
python stock_analysis\rocket_rs.py ...
rem preferred production: run_rs.bat → rocket_tbn.py --relative-strength
```

DailyRun still calls `run_brt.bat` for the **BRT system**; that bat now launches `rocket_tbn.py`.
DailyRun step 9 calls `run_rs.bat` for **RS** (Relative Strength).

## Deliberately unchanged

- `brt_zones`, `BRT_Closed_*` / `BRT_Summary_*`, sheet BRT tab language, `BRTConfig` class name (alias: `TBNConfig`)
- `run_brt_backtest`, `BRT_Optimizer`, `rl_emit_brt_mirror.py` → `BRT_Closed_RL_*`
- `brt_cash` and other `brt_*` config fields that mean Break-and-ReTest / legacy sizing
