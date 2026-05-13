"""Глобальные риск-проверки: Daily>EMA200, daily loss, баланс, лимиты сеток. TODO Stage 2."""

from __future__ import annotations


class RiskManager:
    """Stub. Полная реализация на Этапе 2."""

    def can_open_grid(self, symbol: str) -> bool:
        raise NotImplementedError("RiskManager.can_open_grid — Stage 2")
