"""Точка входа. Запускает основной асинхронный цикл.

Этап 1 (signals_only):
- Раз в poll_interval_sec секунд опрашивает свечи по всем активам
- Считает индикаторы, оценивает сигнал
- Пишет одну запись в decisions per (symbol, новая закрытая свеча 15m)
- Снимок свечей с индикаторами — в candles
- Реальной торговли НЕТ

Запуск:
    uv run python -m scalping_bot.main
Остановка: Ctrl+C — корректно завершает текущий цикл и закрывает БД.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime
from pathlib import Path

from .config import AppConfig, BotMode, StrategyConfig
from .exchange.okx_client import Candle, OkxClient, OkxCredentials
from .logging_setup import configure_logging, get_logger
from .market_data import MarketDataService, SymbolSnapshot
from .signal_engine import SignalEngine, SignalResult
from .storage.db import Database
from .storage.repository import CandleRepository, DecisionRepository, commit


class SignalsOnlyLoop:
    """Главный цикл для Этапа 1: только опрос и логирование сигналов."""

    def __init__(
        self,
        *,
        config: StrategyConfig,
        market: MarketDataService,
        engine: SignalEngine,
        candle_repo: CandleRepository,
        decision_repo: DecisionRepository,
        db: Database,
    ) -> None:
        self._config = config
        self._market = market
        self._engine = engine
        self._candle_repo = candle_repo
        self._decision_repo = decision_repo
        self._db = db
        self._log = get_logger("loop")
        # Помним последнюю закрытую свечу 15m по каждому символу,
        # чтобы не логировать одно и то же решение многократно за период.
        self._last_15m_close: dict[str, datetime] = {}
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._log.info(
            "loop_starting",
            assets=[a.symbol for a in self._config.assets],
            timeframes=self._market.timeframes,
            poll_interval_sec=self._config.market_data.poll_interval_sec,
        )

        while not self._stop.is_set():
            cycle_started = _now_utc()
            for asset in self._config.assets:
                if self._stop.is_set():
                    break
                try:
                    await self._process_symbol(asset.symbol)
                except Exception as e:  # noqa: BLE001
                    self._log.exception(
                        "symbol_processing_error",
                        symbol=asset.symbol,
                        error=str(e),
                    )

            await commit(self._db)
            self._log.debug("cycle_complete", elapsed_sec=(_now_utc() - cycle_started).total_seconds())

            # Прерываемое ожидание следующего цикла
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._config.market_data.poll_interval_sec,
                )
            except TimeoutError:
                pass

        self._log.info("loop_stopped")

    async def _process_symbol(self, symbol: str) -> None:
        snap = await self._market.fetch_snapshot(symbol)
        if snap is None:
            return

        # Логируем decision только когда появилась новая закрытая 15m свеча.
        new_close_15m = snap.by_timeframe["15m"].last_closed.open_time
        if self._last_15m_close.get(symbol) == new_close_15m:
            return
        self._last_15m_close[symbol] = new_close_15m

        await self._snapshot_candles(snap)
        result = self._engine.check_entry(snap)
        await self._log_decision(snap, result)

    async def _snapshot_candles(self, snap: SymbolSnapshot) -> None:
        for tfs in snap.by_timeframe.values():
            c: Candle = tfs.last_closed
            await self._candle_repo.upsert_snapshot(
                symbol=snap.symbol,
                timeframe=tfs.timeframe,
                open_time=c.open_time,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                ema200=tfs.ema200,
                atr14=tfs.atr14,
                captured_at=snap.captured_at,
            )

    async def _log_decision(self, snap: SymbolSnapshot, result: SignalResult) -> None:
        decision = "enter" if result.should_enter else "skip"
        ctx: dict[str, object] = {
            "failed_check": result.failed_check,
            "captured_at": snap.captured_at.isoformat(),
            "timeframes": {
                tf: {
                    "open_time": ts.last_closed.open_time.isoformat(),
                    "o": ts.last_closed.open,
                    "h": ts.last_closed.high,
                    "l": ts.last_closed.low,
                    "c": ts.last_closed.close,
                    "ema200": ts.ema200,
                    "atr14": ts.atr14,
                }
                for tf, ts in snap.by_timeframe.items()
            },
        }
        await self._decision_repo.insert(
            ts=snap.captured_at,
            symbol=snap.symbol,
            decision=decision,
            reason=result.reason,
            context=ctx,
        )
        log_fn = self._log.info if result.should_enter else self._log.info
        log_fn(
            "signal_check",
            symbol=snap.symbol,
            decision=decision,
            reason=result.reason,
            failed_check=result.failed_check,
        )


async def run() -> None:
    config = AppConfig.load()
    configure_logging(level=config.secrets.log_level)
    log = get_logger("bot")

    log.info(
        "bot_starting",
        mode=config.secrets.bot_mode.value,
        assets=[a.symbol for a in config.strategy.assets],
        capital_usdt=config.strategy.capital.total_usdt,
    )

    if config.secrets.bot_mode != BotMode.SIGNALS_ONLY:
        log.warning(
            "mode_not_ready_yet",
            requested=config.secrets.bot_mode.value,
            note="Только режим signals_only реализован на Этапе 1. Меняй BOT_MODE в .env.",
        )
        return

    db = Database(Path(config.strategy.storage.db_path))
    await db.connect()
    log.info("db_connected", path=str(db._path))

    client = OkxClient(
        OkxCredentials(
            api_key=config.secrets.okx_api_key,
            api_secret=config.secrets.okx_api_secret,
            passphrase=config.secrets.okx_api_passphrase,
            use_testnet=config.secrets.okx_use_testnet,
        )
    )
    market = MarketDataService(client, config.strategy)
    engine = SignalEngine(config.strategy)
    loop = SignalsOnlyLoop(
        config=config.strategy,
        market=market,
        engine=engine,
        candle_repo=CandleRepository(db),
        decision_repo=DecisionRepository(db),
        db=db,
    )

    _install_signal_handlers(loop, log)

    try:
        await loop.run()
    finally:
        await db.close()
        log.info("bot_stopped")


def _install_signal_handlers(loop: SignalsOnlyLoop, log) -> None:  # noqa: ANN001
    def _handle(signum: int, _frame) -> None:  # noqa: ANN001
        log.info("shutdown_signal_received", signal=signum)
        loop.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            # SIGTERM на Windows вне основного треда может не сработать — это нормально
            pass


def _now_utc() -> datetime:
    from datetime import UTC, datetime as _dt

    return _dt.now(UTC)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
