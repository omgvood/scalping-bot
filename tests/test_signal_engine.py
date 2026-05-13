"""Тесты SignalEngine: проверяем каждое из 3 условий по отдельности."""

from __future__ import annotations

from datetime import UTC, datetime

from scalping_bot.config import StrategyConfig
from scalping_bot.exchange.okx_client import Candle
from scalping_bot.market_data import SymbolSnapshot, TimeframeSnapshot
from scalping_bot.signal_engine import SignalEngine


def _candle(open_: float, close: float, *, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(
        open_time=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        open=open_,
        high=high if high is not None else max(open_, close) + 1,
        low=low if low is not None else min(open_, close) - 1,
        close=close,
        volume=1.0,
        confirm=True,
    )


def _snapshot(
    *,
    symbol: str = "BTC-USDT",
    daily_close: float = 100.0,
    ema200: float | None = 90.0,
    candles_15_30_60: tuple[Candle, Candle, Candle] | None = None,
) -> SymbolSnapshot:
    """Удобный фикстура-конструктор: создаёт SymbolSnapshot с разумными дефолтами."""
    if candles_15_30_60 is None:
        # По умолчанию — все зелёные, тело 0.5% (хватает для BTC порога 0.1%)
        candles_15_30_60 = (
            _candle(100, 100.5),
            _candle(100, 100.5),
            _candle(100, 100.5),
        )
    snap = SymbolSnapshot(symbol=symbol, captured_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC))
    snap.by_timeframe["15m"] = TimeframeSnapshot("15m", candles_15_30_60[0], atr14=1.0)
    snap.by_timeframe["30m"] = TimeframeSnapshot("30m", candles_15_30_60[1], atr14=1.0)
    snap.by_timeframe["60m"] = TimeframeSnapshot("60m", candles_15_30_60[2], atr14=1.0)
    snap.by_timeframe["1D"] = TimeframeSnapshot("1D", _candle(95, daily_close), ema200=ema200)
    return snap


def _engine() -> SignalEngine:
    return SignalEngine(StrategyConfig.load())


class TestTrendFilter:
    def test_pass_when_daily_above_ema200(self) -> None:
        result = _engine().check_entry(_snapshot(daily_close=120, ema200=100))
        assert result.should_enter is True
        assert result.failed_check is None

    def test_fail_when_daily_below_ema200(self) -> None:
        result = _engine().check_entry(_snapshot(daily_close=90, ema200=100))
        assert result.should_enter is False
        assert result.failed_check == "trend"
        assert "EMA200" in result.reason

    def test_fail_when_daily_equal_ema200(self) -> None:
        # Спека требует строгое >, не >=
        result = _engine().check_entry(_snapshot(daily_close=100, ema200=100))
        assert result.should_enter is False
        assert result.failed_check == "trend"

    def test_fail_when_ema200_unavailable(self) -> None:
        result = _engine().check_entry(_snapshot(ema200=None))
        assert result.should_enter is False
        assert result.failed_check == "trend"


class TestThreeGreenCandles:
    def test_fail_when_15m_is_red(self) -> None:
        candles = (_candle(100, 99.5), _candle(100, 100.5), _candle(100, 100.5))
        result = _engine().check_entry(_snapshot(candles_15_30_60=candles))
        assert result.should_enter is False
        assert result.failed_check == "green"
        assert "15m" in result.reason

    def test_fail_when_30m_is_red(self) -> None:
        candles = (_candle(100, 100.5), _candle(100, 99.5), _candle(100, 100.5))
        result = _engine().check_entry(_snapshot(candles_15_30_60=candles))
        assert result.should_enter is False
        assert result.failed_check == "green"
        assert "30m" in result.reason

    def test_fail_when_60m_is_red(self) -> None:
        candles = (_candle(100, 100.5), _candle(100, 100.5), _candle(100, 99.5))
        result = _engine().check_entry(_snapshot(candles_15_30_60=candles))
        assert result.should_enter is False
        assert result.failed_check == "green"
        assert "60m" in result.reason

    def test_fail_when_candle_is_doji(self) -> None:
        # close == open считается НЕ зелёной (требуется строгое >)
        candles = (_candle(100, 100), _candle(100, 100.5), _candle(100, 100.5))
        result = _engine().check_entry(_snapshot(candles_15_30_60=candles))
        assert result.should_enter is False
        assert result.failed_check == "green"


class TestBodyFilterFixedPct:
    def test_fail_when_body_below_btc_threshold(self) -> None:
        # BTC порог в config.yaml = 0.10%. Тело 0.05% < порога.
        candles = (
            _candle(100.0, 100.05),  # 0.05% от 100.05 = 0.05003... тело 0.05 < 0.10005
            _candle(100, 100.5),
            _candle(100, 100.5),
        )
        result = _engine().check_entry(_snapshot(symbol="BTC-USDT", candles_15_30_60=candles))
        assert result.should_enter is False
        assert result.failed_check == "body"

    def test_pass_when_body_meets_btc_threshold(self) -> None:
        # 0.5% > 0.10% порог
        candles = (
            _candle(100.0, 100.5),
            _candle(100.0, 100.5),
            _candle(100.0, 100.5),
        )
        result = _engine().check_entry(_snapshot(symbol="BTC-USDT", candles_15_30_60=candles))
        assert result.should_enter is True

    def test_sol_has_higher_threshold(self) -> None:
        # SOL порог = 0.25%. Тело 0.15% — пройдёт BTC (0.10%), но не SOL.
        candles = (
            _candle(100.0, 100.15),
            _candle(100.0, 100.15),
            _candle(100.0, 100.15),
        )
        assert _engine().check_entry(_snapshot(symbol="BTC-USDT", candles_15_30_60=candles)).should_enter
        assert not _engine().check_entry(_snapshot(symbol="SOL-USDT", candles_15_30_60=candles)).should_enter


class TestUnknownAsset:
    def test_unknown_asset_rejected(self) -> None:
        result = _engine().check_entry(_snapshot(symbol="DOGE-USDT"))
        assert result.should_enter is False
        assert result.failed_check == "body"
