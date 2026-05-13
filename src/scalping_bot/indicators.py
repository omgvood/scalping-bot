"""Технические индикаторы.

Чистые функции без зависимостей от рынка/БД, чтобы было удобно тестировать.
Входные ряды — от старого к новому (chronological order).
"""

from __future__ import annotations

from collections.abc import Sequence


def ema(values: Sequence[float], period: int) -> float | None:
    """Экспоненциальная скользящая средняя. Возвращает значение на последней точке.

    Инициализируется как SMA первых `period` значений, далее
    EMA(t) = α * x(t) + (1-α) * EMA(t-1), где α = 2/(period+1).

    Возвращает None, если данных меньше `period`.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(values)
    if n < period:
        return None

    alpha = 2.0 / (period + 1)
    current = sum(values[:period]) / period  # SMA-initialization
    for x in values[period:]:
        current = alpha * x + (1 - alpha) * current
    return current


def true_range(high: float, low: float, prev_close: float) -> float:
    """True Range для одной свечи: max(H-L, |H-pC|, |L-pC|)."""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    """Average True Range (Wilder).

    Первое значение ATR — простое среднее TR за `period` свечей.
    Далее сглаживание Wilder: ATR(t) = ((period-1)*ATR(t-1) + TR(t)) / period.

    Все три ряда (highs/lows/closes) от старого к новому, одинаковой длины.
    Нужно минимум period+1 точек (для первого TR нужен prev_close).
    """
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows, closes must be of equal length")
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(highs)
    if n < period + 1:
        return None

    trs: list[float] = []
    for i in range(1, n):
        trs.append(true_range(highs[i], lows[i], closes[i - 1]))

    current = sum(trs[:period]) / period
    for tr in trs[period:]:
        current = ((period - 1) * current + tr) / period
    return current
