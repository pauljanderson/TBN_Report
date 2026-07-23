from pathlib import Path
utc = Path(r"C:\Users\songg\Downloads\stockresearch\drive\davey_experiments\spy_tc_strong_system\universe_then_curated")
print("utc exists", utc.exists())
shards = utc / "shards"
print("shards exists", shards.exists())
if utc.exists():
    for p in sorted(utc.iterdir()):
        print(" ", p.name, "dir" if p.is_dir() else "file")
if shards.exists():
    for p in sorted(shards.iterdir()):
        print(" shard:", p.name)
        if p.is_dir():
            for c in sorted(p.iterdir())[:20]:
                print("   ", c.name)
