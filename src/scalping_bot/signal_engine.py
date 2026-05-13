"""Детектор сигналов входа.

По спеке для входа в сетку нужны одновременно:
  1. Daily close > EMA(200) на торгуемом активе
  2. Последние закрытые свечи на 15м, 30м и 60м — все зелёные (close > open)
  3. Тело каждой из трёх свечей больше порога волатильности
     - fixed_pct: |close - open| / close >= assets[symbol].min_body_pct / 100
     - atr:       (close - open) > 0.3 * ATR(14) на соответствующем ТФ

Этап 1 — фильтр капитала и лимит сеток на актив здесь НЕ проверяется
(это задача RiskManager на Этапе 2). Мы лишь говорим, есть ли потенциальный
сигнал по рыночным данным.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import AssetConfig, StrategyConfig
from .market_data import SymbolSnapshot


@dataclass(slots=True, frozen=True)
class SignalResult:
    """Решение по одному символу."""

    should_enter: bool
    reason: str  # человекочитаемое: «all conditions met» / «60m candle is red» / ...
    failed_check: str | None = None  # короткий машинный код: 'trend' | 'green' | 'body' | None


class SignalEngine:
    """Stateless проверка сигнала по уже собранному SymbolSnapshot."""

    def __init__(self, config: StrategyConfig) -> None:
        self._config = config
        self._assets: dict[str, AssetConfig] = {a.symbol: a for a in config.assets}

    def check_entry(self, snap: SymbolSnapshot) -> SignalResult:
        cfg = self._config
        trend_tf = cfg.signal.trend_filter.timeframe
        confirm_tfs = cfg.signal.confirmation_timeframes

        # --- 1. Глобальный фильтр тренда: Daily close > EMA(200) ---
        trend = snap.by_timeframe.get(trend_tf)
        if trend is None or trend.ema200 is None:
            return SignalResult(
                False,
                f"{trend_tf} EMA({cfg.signal.trend_filter.ema_period}) not yet available",
                failed_check="trend",
            )
        if trend.last_closed.close <= trend.ema200:
            return SignalResult(
                False,
                f"{trend_tf} close {trend.last_closed.close:.4f} <= EMA200 {trend.ema200:.4f}",
                failed_check="trend",
            )

        # --- 2. Все 3 подтверждающие свечи зелёные ---
        for tf in confirm_tfs:
            tfs = snap.by_timeframe.get(tf)
            if tfs is None:
                return SignalResult(False, f"{tf}: no closed candle yet", failed_check="green")
            c = tfs.last_closed
            if not (c.close > c.open):
                return SignalResult(
                    False,
                    f"{tf} candle is red ({c.open:.4f} → {c.close:.4f})",
                    failed_check="green",
                )

        # --- 3. Фильтр шума (тело свечи) ---
        asset = self._assets.get(snap.symbol)
        if asset is None:
            return SignalResult(
                False,
                f"asset {snap.symbol} not in config",
                failed_check="body",
            )

        for tf in confirm_tfs:
            tfs = snap.by_timeframe[tf]
            c = tfs.last_closed
            body = c.close - c.open  # > 0, т.к. зелёная свеча
            if cfg.signal.noise_filter.mode == "atr":
                if tfs.atr14 is None:
                    return SignalResult(
                        False,
                        f"{tf}: ATR(14) not yet available",
                        failed_check="body",
                    )
                threshold = cfg.signal.noise_filter.atr_body_threshold * tfs.atr14
                if body <= threshold:
                    return SignalResult(
                        False,
                        f"{tf} body {body:.4f} <= 0.3*ATR {threshold:.4f}",
                        failed_check="body",
                    )
            else:  # fixed_pct (MVP)
                threshold = asset.min_body_pct / 100.0 * c.close
                if body < threshold:
                    return SignalResult(
                        False,
                        f"{tf} body {body:.4f} < min {threshold:.4f} ({asset.min_body_pct}%)",
                        failed_check="body",
                    )

        return SignalResult(True, "all conditions met", failed_check=None)
