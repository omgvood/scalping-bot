"""Выставление и отмена ордеров на OKX. Реальный и paper executor. TODO Stage 2/3."""

from __future__ import annotations

from typing import Protocol


class OrderExecutor(Protocol):
    """Контракт исполнителя ордеров. Реализации: PaperExecutor (Stage 2), LiveExecutor (Stage 3)."""

    async def place_limit(self, symbol: str, side: str, price: float, qty: float) -> str: ...
    async def place_market(self, symbol: str, side: str, qty: float) -> str: ...
    async def cancel(self, exchange_id: str) -> None: ...
