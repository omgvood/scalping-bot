"""Скачать историю свечей с OKX за N дней назад и сохранить в SQLite.

Запуск:
    uv run python scripts/download_history.py          # по умолчанию 730 дней (2 года)
    uv run python scripts/download_history.py 1095     # 3 года

Что делает:
- Для каждой комбинации (актив, таймфрейм) идёт назад по времени батчами
  по 100 свечей через OKX /api/v5/market/history-candles
- INSERT OR IGNORE — повторный запуск не перезаписывает уже скачанное
- Соблюдает rate limit (~10 RPS): спим 150 мс между запросами

OKX держит историю по основным парам как минимум 3-5 лет, так что
2 года точно покрываются. Если запрос вернёт пустой массив раньше
заданной даты — это значит у биржи нет более старых данных, что
тоже нормально (например, SOL/BNB до 2020 г.).
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from okx.MarketData import MarketAPI

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scalping_bot.config import StrategyConfig  # noqa: E402
from scalping_bot.exchange.okx_client import TIMEFRAME_TO_OKX_BAR  # noqa: E402
from scalping_bot.storage.db import SCHEMA_PATH  # noqa: E402

REQUEST_DELAY_SEC = 0.15  # 150 ms ⇒ ~6.6 RPS, под лимитом OKX (10 RPS)
BATCH_LIMIT = 100  # OKX history-candles max


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _oldest_in_db(conn: sqlite3.Connection, symbol: str, timeframe: str) -> datetime | None:
    row = conn.execute(
        "SELECT MIN(open_time) FROM historical_candles WHERE symbol=? AND timeframe=?",
        (symbol, timeframe),
    ).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[0] else None


def _count_in_db(conn: sqlite3.Connection, symbol: str, timeframe: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM historical_candles WHERE symbol=? AND timeframe=?",
        (symbol, timeframe),
    ).fetchone()
    return int(row[0]) if row else 0


def download_one(
    conn: sqlite3.Connection,
    api: MarketAPI,
    symbol: str,
    timeframe: str,
    earliest: datetime,
) -> int:
    """Идём назад от ближайшего недостающего момента до `earliest`. Возвращает
    число вставленных строк."""
    bar = TIMEFRAME_TO_OKX_BAR[timeframe]
    # Если уже есть данные — продолжаем с самой старой записи, иначе с now
    oldest = _oldest_in_db(conn, symbol, timeframe) or datetime.now(UTC)
    cursor_ms = int(oldest.timestamp() * 1000)

    inserted = 0
    batches = 0
    while True:
        # `after` = вернуть свечи СТАРШЕ этого ts
        resp = api.get_history_candlesticks(
            instId=symbol,
            bar=bar,
            after=str(cursor_ms),
            limit=str(BATCH_LIMIT),
        )
        if resp.get("code") != "0":
            raise RuntimeError(f"OKX error: {resp.get('msg')} (code={resp.get('code')})")

        rows = resp.get("data", [])
        if not rows:
            # Биржа исчерпала историю
            break

        batch_data: list[tuple] = []
        oldest_in_batch_ms = cursor_ms
        for row in rows:
            ts_ms = int(row[0])
            oldest_in_batch_ms = min(oldest_in_batch_ms, ts_ms)
            open_time = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
            batch_data.append(
                (
                    symbol,
                    timeframe,
                    open_time,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    float(row[5]),
                )
            )

        conn.executemany(
            """INSERT OR IGNORE INTO historical_candles
               (symbol, timeframe, open_time, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            batch_data,
        )
        conn.commit()
        inserted += conn.total_changes  # cumulative; не идеально, но достаточно для лога
        batches += 1

        cursor_ms = oldest_in_batch_ms
        if datetime.fromtimestamp(cursor_ms / 1000, tz=UTC) <= earliest:
            break

        # Прогресс каждые 5 батчей
        if batches % 5 == 0:
            current = datetime.fromtimestamp(cursor_ms / 1000, tz=UTC)
            print(f"    ... {symbol:<10} {timeframe:<4} now at {current.date()}  batches={batches}")

        time.sleep(REQUEST_DELAY_SEC)

    return inserted


def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 730
    earliest = datetime.now(UTC) - timedelta(days=days)

    cfg = StrategyConfig.load()
    db_path = PROJECT_ROOT / cfg.storage.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    api = MarketAPI(flag="0")
    conn = sqlite3.connect(db_path)
    _apply_schema(conn)

    print(f"Downloading {days} days of history to {db_path}")
    print(f"Earliest target: {earliest.date()} UTC\n")

    total_start = time.time()
    for asset in cfg.assets:
        symbol = asset.symbol
        for tf in ["15m", "30m", "60m", "1D"]:
            before = _count_in_db(conn, symbol, tf)
            t0 = time.time()
            download_one(conn, api, symbol, tf, earliest)
            after = _count_in_db(conn, symbol, tf)
            dt = time.time() - t0
            print(
                f"  {symbol:<10} {tf:<4} rows {before} -> {after}  "
                f"(+{after - before} in {dt:.1f}s)"
            )

    conn.close()
    print(f"\nTotal time: {time.time() - total_start:.1f}s")


if __name__ == "__main__":
    main()
