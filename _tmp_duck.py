import duckdb
from pathlib import Path
db = Path(r"C:\Users\songg\Downloads\stockresearch\drive\brt_profile.duckdb")
con = duckdb.connect(str(db), read_only=True)
tables = con.execute("SHOW TABLES").fetchall()
print("tables", tables)
for (t,) in tables:
    cols = con.execute(f"DESCRIBE {t}").fetchall()
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(t, "n=", n, "cols=", [c[0] for c in cols][:20])
