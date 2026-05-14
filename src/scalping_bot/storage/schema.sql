-- Схема SQLite для скальпинг-бота.
-- Создаётся автоматически при первом запуске.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- grids: одна запись на одну сетку усреднения
-- ============================================================
CREATE TABLE IF NOT EXISTS grids (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    status          TEXT    NOT NULL CHECK (status IN ('open', 'closed_tp', 'closed_sl', 'closed_timeout', 'closed_manual')),
    level           INTEGER NOT NULL DEFAULT 0,        -- 0..3 (entry + до 3 усреднений)
    entry_price     REAL    NOT NULL,                  -- цена первого входа
    avg_price       REAL    NOT NULL,                  -- средневзвешенная цена
    total_qty       REAL    NOT NULL DEFAULT 0,        -- общее количество базовой монеты
    total_spent     REAL    NOT NULL DEFAULT 0,        -- сумма потраченных USDT
    opened_at       TEXT    NOT NULL,                  -- ISO 8601 UTC
    closed_at       TEXT,
    realized_pnl    REAL,                              -- итоговый PnL в USDT (после закрытия)
    close_reason    TEXT,
    mode            TEXT    NOT NULL CHECK (mode IN ('signals_only', 'paper', 'live'))
);
CREATE INDEX IF NOT EXISTS idx_grids_status ON grids(status);
CREATE INDEX IF NOT EXISTS idx_grids_symbol ON grids(symbol);

-- ============================================================
-- orders: все ордера (выставленные/исполненные/отменённые)
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    grid_id         INTEGER NOT NULL REFERENCES grids(id) ON DELETE CASCADE,
    exchange_id     TEXT,                              -- ord_id с OKX (NULL в paper-режиме)
    order_type      TEXT    NOT NULL CHECK (order_type IN ('entry', 'dca', 'tp', 'sl', 'market_close')),
    level           INTEGER NOT NULL,                  -- уровень сетки 0..3 для entry/dca
    side            TEXT    NOT NULL CHECK (side IN ('buy', 'sell')),
    price           REAL,                              -- лимитная цена; NULL для рыночных
    qty             REAL    NOT NULL,                  -- количество в базовой монете
    quote_qty       REAL,                              -- сумма в USDT (для market-by-quote)
    status          TEXT    NOT NULL CHECK (status IN ('pending', 'placed', 'filled', 'cancelled', 'failed')),
    placed_at       TEXT,
    filled_at       TEXT,
    raw_response    TEXT                               -- сырой JSON-ответ биржи для отладки
);
CREATE INDEX IF NOT EXISTS idx_orders_grid ON orders(grid_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- ============================================================
-- trades: фактически исполненные сделки
-- ============================================================
CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    grid_id         INTEGER NOT NULL REFERENCES grids(id) ON DELETE CASCADE,
    exchange_trade_id TEXT,
    price           REAL    NOT NULL,
    qty             REAL    NOT NULL,
    fee             REAL    NOT NULL DEFAULT 0,        -- комиссия
    fee_currency    TEXT,
    executed_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_grid ON trades(grid_id);

-- ============================================================
-- candles: снимки свечей в моменты принятия решений
-- ============================================================
CREATE TABLE IF NOT EXISTS candles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,                  -- 15m | 30m | 60m | 1D
    open_time       TEXT    NOT NULL,                  -- ISO 8601 UTC
    open            REAL    NOT NULL,
    high            REAL    NOT NULL,
    low             REAL    NOT NULL,
    close           REAL    NOT NULL,
    volume          REAL    NOT NULL,
    ema200          REAL,                              -- только для 1D
    atr14           REAL,                              -- для 15m/30m/60m
    captured_at     TEXT    NOT NULL,
    UNIQUE (symbol, timeframe, open_time)
);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf ON candles(symbol, timeframe, open_time DESC);

-- ============================================================
-- decisions: лог всех решений бота с обоснованием
-- ============================================================
CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,                  -- ISO 8601 UTC
    symbol          TEXT,
    decision        TEXT    NOT NULL,                  -- 'enter' | 'skip' | 'dca' | 'tp_hit' | 'sl_hit' | 'timeout' | 'manual_stop'
    reason          TEXT    NOT NULL,                  -- человекочитаемое обоснование
    grid_id         INTEGER REFERENCES grids(id) ON DELETE SET NULL,
    context         TEXT                               -- JSON со снимком сигналов/цен/индикаторов
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts DESC);

-- ============================================================
-- historical_candles: сырые OHLCV свечи с биржи для бэктестов.
-- Заполняется отдельным скриптом (scripts/download_history.py), а не
-- основным циклом бота. Никаких индикаторов здесь не храним —
-- считаются на лету во время replay.
-- ============================================================
CREATE TABLE IF NOT EXISTS historical_candles (
    symbol      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    open_time   TEXT NOT NULL,                       -- ISO 8601 UTC
    open        REAL NOT NULL,
    high        REAL NOT NULL,
    low         REAL NOT NULL,
    close       REAL NOT NULL,
    volume      REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, open_time)
);
CREATE INDEX IF NOT EXISTS idx_hist_symbol_tf
    ON historical_candles(symbol, timeframe, open_time);

-- ============================================================
-- daily_stats: для daily loss limit и отчётов
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_stats (
    date            TEXT PRIMARY KEY,                  -- YYYY-MM-DD (UTC)
    start_balance   REAL    NOT NULL,                  -- баланс на 00:00 UTC
    realized_pnl    REAL    NOT NULL DEFAULT 0,
    new_grids_blocked INTEGER NOT NULL DEFAULT 0       -- 0/1, daily loss limit hit
);
