"""Опрос свечей с OKX, расчёт EMA/ATR, кеш свечей в памяти.

Жизненный цикл одного цикла:
1) Для каждого (symbol, timeframe) дёргаем последние N свечей с OKX.
2) Считаем индикаторы (EMA(200) на 1D, ATR(14) на остальных).
3) Возвращаем снимок: для каждого символа последняя закрытая свеча
   на каждом ТФ + индикаторы.

Не используем WebSocket (по спеке — REST polling). Сетевые ошибки
обрабатываются с retry через tenacity. Если после повторов всё равно
не получили данных — пропускаем символ в текущем цикле (бот не падает).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from structlog.stdlib import BoundLogger
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import StrategyConfig
from .exchange.okx_client import Candle, OkxClient
from .indicators import atr, ema
from .logging_setup import get_logger


@dataclass(slots=True)
class TimeframeSnapshot:
    """Состояние одного таймфрейма на момент проверки."""

    timeframe: str
    last_closed: Candle
    atr14: float | None = None  # для 15m/30m/60m
    ema200: float | None = None  # для 1D


@dataclass(slots=True)
class SymbolSnapshot:
    """Полный набор данных по одному активу для оценки сигнала."""

    symbol: str
    captured_at: datetime
    by_timeframe: dict[str, TimeframeSnapshot] = field(default_factory=dict)


class MarketDataService:
    """Опрашивает OKX и собирает SymbolSnapshot по каждому активу."""

    def __init__(
        self,
        client: OkxClient,
        config: StrategyConfig,
        log: BoundLogger | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._log = log or get_logger("market_data")
        # Все ТФ, которые надо опрашивать: подтверждение сигнала + ТФ тренда (1D)
        self._timeframes: list[str] = list(
            dict.fromkeys(
                [
                    *config.signal.confirmation_timeframes,
                    config.signal.trend_filter.timeframe,
                ]
            )
        )

    @property
    def timeframes(self) -> list[str]:
        return list(self._timeframes)

    async def fetch_snapshot(self, symbol: str) -> SymbolSnapshot | None:
        """Возвращает снимок состояния символа или None при ошибке сети.

        На один символ делает len(self._timeframes) сетевых запросов.
        """
        captured_at = _now_utc()
        snap = SymbolSnapshot(symbol=symbol, captured_at=captured_at)

        for tf in self._timeframes:
            candles = await self._fetch_candles_with_retry(symbol, tf)
            if candles is None:
                # Не получилось — пропустим весь символ в этом цикле
                return None
            ts = _build_tf_snapshot(tf, candles, self._config.signal.trend_filter.ema_period)
            if ts is None:
                self._log.debug(
                    "no_closed_candle",
                    symbol=symbol,
                    timeframe=tf,
                    candles_received=len(candles),
                )
                return None
            snap.by_timeframe[tf] = ts

        return snap

    async def _fetch_candles_with_retry(self, symbol: str, timeframe: str) -> list[Candle] | None:
        """Лёгкая ретрай-обёртка над OkxClient.get_candles."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type((RuntimeError, OSError)),
                reraise=True,
            ):
                with attempt:
                    return await self._client.get_candles(
                        symbol,
                        timeframe,
                        limit=self._config.market_data.candle_cache_size,
                    )
        except Exception as e:  # noqa: BLE001
            self._log.warning(
                "fetch_candles_failed",
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )
            return None
        return None  # для mypy: AsyncRetrying gives at least one iteration


def _now_utc() -> datetime:
    """Отделено для удобства мокинга в тестах."""
    from datetime import UTC, datetime as _dt

    return _dt.now(UTC)


def _build_tf_snapshot(
    timeframe: str,
    candles: list[Candle],
    ema_period: int,
) -> TimeframeSnapshot | None:
    """Принимает свечи от OKX (новейшая первая) и возвращает снимок ТФ.

    Возвращает None, если нет ни одной закрытой свечи в выборке.
    """
    if not candles:
        return None
    # OKX отдаёт от новейшей к старейшей; нам нужны хронологически (старая → новая)
    chrono = list(reversed(candles))
    # Закрытые свечи
    closed = [c for c in chrono if c.confirm]
    if not closed:
        return None

    last_closed = closed[-1]
    snap = TimeframeSnapshot(timeframe=timeframe, last_closed=last_closed)

    if timeframe == "1D":
        snap.ema200 = ema([c.close for c in closed], period=ema_period)
    else:
        snap.atr14 = atr(
            [c.high for c in closed],
            [c.low for c in closed],
            [c.close for c in closed],
            period=14,
        )

    return snap


def _format_candle(c: Candle) -> dict[str, Any]:
    """Утилита для логов: компактное представление свечи."""
    return {
        "ts": c.open_time.isoformat(),
        "o": c.open,
        "h": c.high,
        "l": c.low,
        "c": c.close,
        "green": c.close > c.open,
    }
