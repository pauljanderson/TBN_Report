from pathlib import Path
base = Path(r"C:\Users\songg\Downloads\stockresearch\drive\davey_experiments\spy_tc_strong_system\universe_then_curated\shards")
for name in ["shard_00", "shard_03", "shard_04", "shard_06", "shard_08", "shard_14"]:
    d = base / name
    print("====", name, "====")
    for f in sorted(d.iterdir()):
        if f.name == "desktop.ini":
            continue
        print("FILE", f.name, "size", f.stat().st_size)
        if f.suffix in {".txt", ".json", ".md", ".log"} and f.stat().st_size < 50000:
            text = f.read_text(encoding="utf-8", errors="replace")
            print(text[:3000])
            print("---")
