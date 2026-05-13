"""Тесты EMA и ATR."""

from __future__ import annotations

import math

import pytest

from scalping_bot.indicators import atr, ema, true_range


class TestEMA:
    def test_returns_none_when_not_enough_data(self) -> None:
        assert ema([1.0, 2.0, 3.0], period=5) is None

    def test_sma_when_exactly_period_points(self) -> None:
        # На границе period EMA = SMA(period)
        result = ema([10.0, 20.0, 30.0, 40.0, 50.0], period=5)
        assert result == pytest.approx(30.0)

    def test_known_value_period_3(self) -> None:
        # period=3, alpha = 2/4 = 0.5
        # init SMA([1,2,3]) = 2.0
        # step x=4: 0.5*4 + 0.5*2.0 = 3.0
        # step x=5: 0.5*5 + 0.5*3.0 = 4.0
        assert ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3) == pytest.approx(4.0)

    def test_constant_series_equals_constant(self) -> None:
        assert ema([7.0] * 250, period=200) == pytest.approx(7.0)

    def test_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            ema([1.0, 2.0], period=0)


class TestTrueRange:
    def test_no_gap_uses_high_minus_low(self) -> None:
        # H-L = 5, |H-pC|=2, |L-pC|=3 → max = 5
        assert true_range(high=105, low=100, prev_close=102) == 5

    def test_gap_up(self) -> None:
        # Open above prev_close: H=110, L=108, pC=100 → max(2, 10, 8) = 10
        assert true_range(high=110, low=108, prev_close=100) == 10

    def test_gap_down(self) -> None:
        # H=92, L=90, pC=100 → max(2, 8, 10) = 10
        assert true_range(high=92, low=90, prev_close=100) == 10


class TestATR:
    def test_returns_none_when_not_enough_data(self) -> None:
        # Нужно period+1 точек; даём period штук
        assert atr([1.0, 2.0, 3.0], [0.5, 1.5, 2.5], [0.8, 1.8, 2.8], period=3) is None

    def test_constant_range_series(self) -> None:
        # Каждая свеча даёт TR=2 (high-low=2, без гэпов)
        n = 20
        highs = [102.0] * n
        lows = [100.0] * n
        closes = [101.0] * n
        result = atr(highs, lows, closes, period=14)
        assert result == pytest.approx(2.0)

    def test_mismatched_lengths_raise(self) -> None:
        with pytest.raises(ValueError):
            atr([1.0, 2.0], [1.0], [1.0, 2.0], period=1)

    def test_wilder_smoothing_converges_on_constant_tr(self) -> None:
        # Восходящая лестница: H[i]=i+1, L[i]=i, C[i]=i+0.5.
        # Для каждой свечи TR = max(H-L=1, |H-pC|=1.5, |L-pC|=0.5) = 1.5.
        # Wilder-сглаживание по константному ряду TR должно вернуть 1.5.
        highs = [float(i + 1) for i in range(50)]
        lows = [float(i) for i in range(50)]
        closes = [float(i) + 0.5 for i in range(50)]
        result = atr(highs, lows, closes, period=14)
        assert result is not None
        assert math.isclose(result, 1.5, abs_tol=1e-9)
