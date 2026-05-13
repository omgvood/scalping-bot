"""OKX REST client wrapper.

python-okx — синхронная библиотека. Чтобы не блокировать event loop,
сетевые вызовы оборачиваются в asyncio.to_thread.

Документация OKX V5: https://www.okx.com/docs-v5/en/
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from okx.MarketData import MarketAPI

# OKX bar names для нужных нам таймфреймов (mapping из конфига → OKX-обозначение).
# OKX V5 принимает: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, ...
# ВНИМАНИЕ: '1D' у OKX по умолчанию = дневная свеча с открытием в 00:00 UTC+8 (Гонконг).
# Используем '1Dutc' чтобы дневной интервал совпадал с UTC, как у нашего daily_reset.
TIMEFRAME_TO_OKX_BAR: dict[str, str] = {
    "15m": "15m",
    "30m": "30m",
    "60m": "1H",
    "1D": "1Dutc",
}


@dataclass(slots=True, frozen=True)
class Candle:
    """Свеча с OKX, приведённая к нашим типам."""

    open_time: datetime  # начало интервала свечи, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    confirm: bool  # True = свеча закрыта, False = формируется

    @classmethod
    def from_okx(cls, row: list[str]) -> Candle:
        # OKX формат: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        ts_ms = int(row[0])
        return cls(
            open_time=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            confirm=row[8] == "1",
        )


@dataclass(slots=True)
class OkxCredentials:
    api_key: str
    api_secret: str
    passphrase: str
    use_testnet: bool = False

    @property
    def flag(self) -> str:
        """OKX flag: '0' для live, '1' для testnet."""
        return "1" if self.use_testnet else "0"


class OkxClient:
    """Тонкая async-обёртка над python-okx.

    На Этапе 1 используем только публичные endpoints (свечи) — auth не нужен
    для get_candles. Auth-ключи нужны будут на Этапах 2/3 (баланс, ордера).
    """

    def __init__(self, creds: OkxCredentials) -> None:
        self._creds = creds
        self._market = MarketAPI(flag=creds.flag)

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 300,
    ) -> list[Candle]:
        """Возвращает свечи от новейшей к старейшей.

        Бросает RuntimeError, если OKX вернул не code='0' (биржа недоступна,
        неверный symbol/timeframe и т.п.). Сетевые ошибки python-okx
        прокидывает наверх как есть.
        """
        bar = TIMEFRAME_TO_OKX_BAR.get(timeframe)
        if bar is None:
            raise ValueError(f"Unsupported timeframe: {timeframe!r}")

        resp: dict[str, Any] = await asyncio.to_thread(
            self._market.get_candlesticks,
            instId=symbol,
            bar=bar,
            limit=str(limit),
        )
        code = resp.get("code")
        if code != "0":
            raise RuntimeError(f"OKX get_candlesticks failed: code={code} msg={resp.get('msg')!r}")

        data = resp.get("data", [])
        return [Candle.from_okx(row) for row in data]

    async def get_last_closed_candle(self, symbol: str, timeframe: str) -> Candle | None:
        """Последняя закрытая свеча на данном ТФ. None — если все свечи ещё формируются."""
        candles = await self.get_candles(symbol, timeframe, limit=3)
        for c in candles:
            if c.confirm:
                return c
        return None
