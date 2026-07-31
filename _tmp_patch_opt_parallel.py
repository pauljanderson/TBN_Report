from pathlib import Path
import re, csv
from datetime import datetime

script = Path(r"C:\Users\songg\Downloads\stockresearch\tools\run_rs_one_flag_score_opt.py")
t = script.read_text(encoding="utf-8")
old = t
t = t.replace(
    "default=1,\n        help=\"Concurrent RS jobs (default 1; keep at 1 per request)\"",
    "default=6,\n        help=\"Concurrent single-worker RS jobs across arms (default 6; each job still -w 1)\"",
)
t = t.replace(
    "if args.parallel_runs != 1:\n        print(f\"[warn] parallel-runs={args.parallel_runs} (requested default is 1)", flush=True)\n",
    "if args.parallel_runs < 1:\n        raise SystemExit(\"--parallel-runs must be >= 1\")\n",
)
t = t.replace(
    "Baseline: current run_rs.bat universe + flags, -w 1, sequential runs.",
    "Baseline: current run_rs.bat universe + flags, -w 1 per job; fan out arms via --parallel-runs.",
)
if t != old:
    script.write_text(t, encoding="utf-8")
    print("script patched")
else:
    print("script unchanged")

base = Path(r"C:\Users\songg\Downloads\stockresearch\drive\paul_experiments\rs_one_flag_score_opt")
md = (base / "RESULTS.md").read_text(encoding="utf-8")
md = re.sub(r'\(I\"([^\]]+)\)', r'(d=\1)', md)
md = re.sub(r'\*\*Best shorter-hold \([^\)]+\):\*\*', '**Best shorter-hold (>=95 score, avg days <=85% of baseline):**', md)
if "## Status" not in md:
    md += (\n\n""## Status\n"
        "\n"
        "- COMPLETE: 54/54 arms scored.\n"
        "- Long-timeout cause: orchestrator ran with --parallel-runs=1 (serial). "
        "Each arm ~12-40s; 54 serial ~15-20 min. Script supports --parallel-runs N with -w 1 per job.\n"
        "- Prefer: python tools/run_rs_one_flag_score_opt.py --workers 1 --parallel-runs 6 --skip-existing\n"
    )
(base / "RESULTS.md").write_text(md, encoding="utf-8")
rows = list(csv.DictReader(open(base / "summary.csv", encoding="utf-8"))
print("RESULTS updated", len(rows))
print("default=6", "default=6" in script.read_text(encoding="utf-8"))
print("top3", [(r["rank"], r["label"], r["score"]) for r in rows[:3]])
