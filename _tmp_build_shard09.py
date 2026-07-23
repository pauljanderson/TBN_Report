from pathlib import Path

repo = Path(r"C:\Users\songg\Downloads\stockresearch")
data = repo / "data" / "newdata" / "data"
outdir = repo / "drive" / "davey_experiments" / "spy_tc_strong_system" / "universe_then_curated" / "shards" / "shard_09"
outdir.mkdir(parents=True, exist_ok=True)

csvs = sorted(p.stem.upper() for p in data.glob("*.csv"))
universe = [s for s in csvs if s != "SPY"]
shard_idx = 9
shard = [s for i, s in enumerate(universe) if i % 20 == shard_idx]

sym_path = outdir / "symbols.txt"
sym_path.write_text("\n".join(shard) + "\n", encoding="utf-8")
meta = outdir / "universe_meta.txt"
meta.write_text(
    f"source=data_csvs_ex_SPY\nuniverse_n={len(universe)}\nshard={shard_idx}/20\nshard_n={len(shard)}\nmax_positions=10\n",
    encoding="utf-8",
)
print("universe_n", len(universe))
print("shard_n", len(shard))
print("first10", shard[:10])
print("last10", shard[-10:])
print("wrote", sym_path)

# sanity vs shard_00 / shard_08
s0 = [ln.strip().lstrip("\ufeff") for ln in (outdir.parent / "shard_00" / "symbols.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
exp0 = [s for i, s in enumerate(universe) if i % 20 == 0]
print("shard00_match", s0 == exp0, "n", len(s0), len(exp0))
s8 = [ln.strip().lstrip("\ufeff") for ln in (outdir.parent / "shard_08" / "symbols.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
exp8 = [s for i, s in enumerate(universe) if i % 20 == 8]
print("shard08_match", s8 == exp8, "n", len(s8), len(exp8))
