import duckdb
c = duckdb.connect("data/ohlcv.duckdb", read_only=True)
print("tables:", c.execute("SHOW TABLES").fetchall())
print("schema:", c.execute("DESCRIBE prices").fetchall())
print("stats:", c.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM prices").fetchone())
c.close()
