from pathlib import Path
data = Path("data/newdata/data")
csvs = sorted(p.stem.upper() for p in data.glob("*.csv") if p.stem.upper() != "SPY")
shard_i = 5
syms = [s for i, s in enumerate(csvs) if i % 20 == shard_i]
outdir = Path("drive/davey_experiments/spy_tc_strong_system/universe_then_curated/shards/shard_05")
outdir.mkdir(parents=True, exist_ok=True)
(outdir / "symbols.txt").write_text("\n".join(syms) + "\n", encoding="utf-8")
(outdir / "universe_meta.txt").write_text(
    f"source=csv_glob_exclude_SPY\nuniverse_n={len(csvs)}\nshard={shard_i}/20\nshard_n={len(syms)}\nmax_positions=10\n",
    encoding="utf-8",
)
print("universe_n", len(csvs))
print("shard_n", len(syms))
print("first10", syms[:10])
print("last10", syms[-10:])
print("comma", ",".join(syms))
