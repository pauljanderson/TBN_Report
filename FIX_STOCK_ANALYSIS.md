# Fix empty `stock_analysis` on new PC

## Problem
GitHub has `stock_analysis` as a nested-repo pointer, not real files. Clones get an empty folder.

## On OLD machine (has the real files)

```bat
cd C:\Users\songg\Downloads\stockresearch
git pull
fix_stock_analysis_gitlink.bat
git commit -m "Track stock_analysis source files instead of nested gitlink"
git push
```

## On NEW machine (after old machine pushed)

```bat
cd C:\Users\songg\Downloads\stockresearch
git pull
setup_new_pc.bat --smoke
run_backfill_data_to_2010.bat
```

## Tell Cursor on the old machine

Open this file and say:

> Follow FIX_STOCK_ANALYSIS.md. Run the old-machine steps. Do not skip the verify step in the bat file.
