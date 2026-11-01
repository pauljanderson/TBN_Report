import duckdb

c = duckdb.connect("data/ohlcv.duckdb", read_only=True)
print("span", c.execute("SELECT min(date), max(date), count(*), count(DISTINCT symbol) FROM prices").fetchall())
print("from2010", c.execute("SELECT count(DISTINCT symbol) FROM prices WHERE date >= '2010-01-01'").fetchall())
print("ge750", c.execute("SELECT count(*) FROM (SELECT symbol FROM prices WHERE date >= '2010-01-01' GROUP BY symbol HAVING count(*) >= 750)").fetchall())
print("ge2000", c.execute("SELECT count(*) FROM (SELECT symbol FROM prices WHERE date >= '2010-01-01' GROUP BY symbol HAVING count(*) >= 2000)").fetchall())
print("recent_and_long", c.execute("""
SELECT count(*) FROM (
  SELECT symbol
  FROM prices
  WHERE date >= '2010-01-01' AND close > 0
  GROUP BY symbol
  HAVING count(*) >= 1000
     AND max(date) >= (SELECT max(date) - INTERVAL 15 DAY FROM prices)
)""").fetchall())
print("cols", c.execute("DESCRIBE prices").fetchall())
