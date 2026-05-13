"""Smoke-тесты загрузки конфига."""

from __future__ import annotations

from scalping_bot.config import StrategyConfig


def test_strategy_config_loads_from_default_yaml() -> None:
    cfg = StrategyConfig.load()
    assert len(cfg.assets) == 4
    assert {a.symbol for a in cfg.assets} == {"BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"}


def test_strategy_config_take_profit_descending() -> None:
    cfg = StrategyConfig.load()
    tp = cfg.take_profit_pct
    assert tp == sorted(tp, reverse=True), "TP должны убывать с ростом уровня сетки"


def test_strategy_config_stop_loss_first_level_zero() -> None:
    cfg = StrategyConfig.load()
    assert cfg.stop_loss_pct[0] == 0.0, "На уровне 0 (только вход) SL отсутствует"


def test_strategy_config_grid_depth_matches_spec() -> None:
    cfg = StrategyConfig.load()
    base = cfg.capital.base_order_usdt
    depth = sum(base * m for m in cfg.capital.size_multipliers)
    assert depth == 94.0, "Полная глубина сетки по спеке = 94$"
