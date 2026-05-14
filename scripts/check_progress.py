"""Быстро посмотреть, сколько свечей по TON/TRX уже в БД."""

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "bot.sqlite3"
syms = sys.argv[1:] or ["TON-USDT", "TRX-USDT"]
conn = sqlite3.connect(DB)
print(f"Progress for {syms}:")
for s in syms:
    rows = conn.execute(
        "SELECT timeframe, COUNT(*) FROM historical_candles WHERE symbol=? GROUP BY timeframe ORDER BY timeframe",
        (s,),
    ).fetchall()
    print(f"  {s}: {dict(rows) if rows else 'empty'}")
conn.close()
