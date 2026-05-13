"""Доступ к SQLite: запись свечей, решений, daily_stats.

Тонкая прослойка над aiosqlite, чтобы main-цикл не дёргал SQL напрямую.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .db import Database


class CandleRepository:
    """Снимки свечей с индикаторами на момент принятия решения."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_snapshot(
        self,
        *,
        symbol: str,
        timeframe: str,
        open_time: datetime,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        ema200: float | None,
        atr14: float | None,
        captured_at: datetime,
    ) -> None:
        """UPSERT по (symbol, timeframe, open_time). Если такая свеча уже есть —
        обновляем поля индикаторов и captured_at."""
        await self._db.conn.execute(
            """
            INSERT INTO candles
                (symbol, timeframe, open_time, open, high, low, close, volume,
                 ema200, atr14, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timeframe, open_time) DO UPDATE SET
                ema200 = excluded.ema200,
                atr14  = excluded.atr14,
                captured_at = excluded.captured_at
            """,
            (
                symbol,
                timeframe,
                open_time.isoformat(),
                open,
                high,
                low,
                close,
                volume,
                ema200,
                atr14,
                captured_at.isoformat(),
            ),
        )


class DecisionRepository:
    """Лог решений бота: 'enter' | 'skip' | etc."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        *,
        ts: datetime,
        symbol: str | None,
        decision: str,
        reason: str,
        grid_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        await self._db.conn.execute(
            """
            INSERT INTO decisions (ts, symbol, decision, reason, grid_id, context)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                ts.isoformat(),
                symbol,
                decision,
                reason,
                grid_id,
                json.dumps(context, default=str) if context else None,
            ),
        )


async def commit(db: Database) -> None:
    """Явный commit. Вызываем один раз после батча записей за один цикл."""
    await db.conn.commit()
