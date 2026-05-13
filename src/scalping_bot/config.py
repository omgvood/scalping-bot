"""Configuration loading: config.yaml + .env (secrets).

config.yaml — параметры стратегии (TP/SL, объёмы, активы).
.env       — секреты (OKX, Telegram). Никогда не коммитится.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class BotMode(StrEnum):
    SIGNALS_ONLY = "signals_only"
    PAPER = "paper"
    LIVE = "live"


class Secrets(BaseSettings):
    """Из .env. Никогда не печатать в логи."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_api_passphrase: str = ""
    okx_use_testnet: bool = False

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    bot_mode: BotMode = BotMode.SIGNALS_ONLY
    log_level: str = "INFO"


class AssetConfig(BaseModel):
    symbol: str
    min_body_pct: float


class CapitalConfig(BaseModel):
    total_usdt: float
    base_order_usdt: float
    size_multipliers: list[float] = Field(min_length=4, max_length=4)


class GridConfig(BaseModel):
    dca_drop_pct: list[float] = Field(min_length=3, max_length=3)
    max_grids_per_asset: int


class TrendFilterConfig(BaseModel):
    timeframe: str
    ema_period: int


class NoiseFilterConfig(BaseModel):
    mode: str  # fixed_pct | atr
    atr_period: int
    atr_body_threshold: float


class SignalConfig(BaseModel):
    confirmation_timeframes: list[str]
    trend_filter: TrendFilterConfig
    noise_filter: NoiseFilterConfig


class RiskConfig(BaseModel):
    daily_loss_limit_pct: float
    daily_reset_tz: str


class MarketDataConfig(BaseModel):
    poll_interval_sec: int
    candle_cache_size: int


class TimeoutsConfig(BaseModel):
    grid_max_hours: int


class StorageConfig(BaseModel):
    db_path: str


class StrategyConfig(BaseModel):
    """Параметры стратегии из config.yaml."""

    assets: list[AssetConfig]
    capital: CapitalConfig
    grid: GridConfig
    take_profit_pct: list[float] = Field(min_length=4, max_length=4)
    stop_loss_pct: list[float] = Field(min_length=4, max_length=4)
    timeouts: TimeoutsConfig
    signal: SignalConfig
    risk: RiskConfig
    market_data: MarketDataConfig
    storage: StorageConfig

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> Self:
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls.model_validate(raw)


class AppConfig(BaseModel):
    """Полная конфигурация: стратегия + секреты."""

    strategy: StrategyConfig
    secrets: Secrets

    @classmethod
    def load(cls, config_path: Path = DEFAULT_CONFIG_PATH) -> Self:
        return cls(
            strategy=StrategyConfig.load(config_path),
            secrets=Secrets(),
        )
