"""Распечатать последние N решений и свечей-снимков из SQLite.

Запуск:
    uv run python scripts/show_decisions.py          # последние 20 решений
    uv run python scripts/show_decisions.py 50       # последние 50

Полезно после прогона бота: посмотреть, что он наскраулил.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "bot.sqlite3"


def main() -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print(f"=== Decisions (last {limit}, newest first) ===")
    rows = conn.execute(
        "SELECT ts, symbol, decision, reason FROM decisions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        print("  (empty)")
    for r in rows:
        marker = "✓ ENTER" if r["decision"] == "enter" else "  skip "
        print(f"  {r['ts']}  {r['symbol']:<10} {marker}  {r['reason']}")

    print("\n=== Aggregate stats ===")
    stats = conn.execute(
        """
        SELECT symbol,
               SUM(CASE WHEN decision='enter' THEN 1 ELSE 0 END) AS enters,
               SUM(CASE WHEN decision='skip'  THEN 1 ELSE 0 END) AS skips,
               COUNT(*) AS total
          FROM decisions
         GROUP BY symbol
         ORDER BY symbol
        """
    ).fetchall()
    if not stats:
        print("  (no data)")
    for s in stats:
        print(f"  {s['symbol']:<10}  enters={s['enters']:<4} skips={s['skips']:<4} total={s['total']}")

    print("\n=== Last candle per (symbol, timeframe) ===")
    candles = conn.execute(
        """
        SELECT symbol, timeframe, open_time, open, high, low, close, ema200, atr14
          FROM candles c
         WHERE captured_at = (
             SELECT MAX(captured_at) FROM candles WHERE symbol=c.symbol AND timeframe=c.timeframe
         )
         ORDER BY symbol, timeframe
        """
    ).fetchall()
    if not candles:
        print("  (empty)")
    for c in candles:
        green = c["close"] > c["open"]
        body_pct = (c["close"] - c["open"]) / c["open"] * 100
        ema = f"ema200={c['ema200']:.4f}" if c["ema200"] is not None else ""
        atr = f"atr14={c['atr14']:.4f}" if c["atr14"] is not None else ""
        print(
            f"  {c['symbol']:<10} {c['timeframe']:<4} "
            f"{c['open_time']}  o={c['open']} c={c['close']} "
            f"({'green' if green else 'red  '}, body={body_pct:+.3f}%)  {ema}{atr}"
        )

    conn.close()


if __name__ == "__main__":
    main()
