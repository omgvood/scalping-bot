"""OKX REST client wrapper.

Stage 0: pass-through заглушка. Полная реализация — на Этапе 1.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OkxCredentials:
    api_key: str
    api_secret: str
    passphrase: str
    use_testnet: bool = False


class OkxClient:
    """Stub. Будет наполнен на Этапе 1 через python-okx."""

    def __init__(self, creds: OkxCredentials) -> None:
        self._creds = creds

    async def ping(self) -> bool:
        """Проверка доступности публичного API OKX (без auth). TODO Stage 1."""
        raise NotImplementedError("OkxClient.ping — to be implemented in Stage 1")

    async def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[dict]:
        """Свечи через GET /api/v5/market/candles. TODO Stage 1."""
        raise NotImplementedError("OkxClient.get_candles — to be implemented in Stage 1")
