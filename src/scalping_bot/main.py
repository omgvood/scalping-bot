"""Entry point. На Этапе 0 — только bootstrap: загрузка конфига, БД, проверки.

Запуск:
    uv run python -m scalping_bot.main
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import AppConfig, BotMode
from .logging_setup import configure_logging, get_logger
from .storage.db import Database


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

    db = Database(Path(config.strategy.storage.db_path))
    await db.connect()
    log.info("db_connected", path=str(db._path))

    if config.secrets.bot_mode == BotMode.SIGNALS_ONLY:
        log.info("stage_0_bootstrap_ok", note="Этап 1 (опрос свечей, сигналы) — следующий шаг")
    else:
        log.warning("mode_not_ready", mode=config.secrets.bot_mode.value)

    await db.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
