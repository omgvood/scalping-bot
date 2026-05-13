# Scalping Bot (OKX spot)

Автоматизированный торговый бот для скальпинга на споте OKX (BTC/ETH/SOL/BNB к USDT)
с многотаймфреймовыми сигналами и DCA-сеткой усреднения.

Стратегия зафиксирована в [scalping-bot-spec.md](scalping-bot-spec.md).
Версионируйте изменения в спеке отдельным коммитом.

## Этапы

- [x] **Этап 0** — каркас проекта, конфиги, схема БД
- [ ] **Этап 1** — market data + сигналы (без торговли), 2-3 дня лога
- [ ] **Этап 2** — paper trading, полный FSM сеток, 1-2 недели
- [ ] **Этап 3** — реальная торговля минимальным капиталом (100 $)
- [ ] **Этап 4** — Telegram + Dashboard
- [ ] **Этап 5** — Docker, VPS, капитал 1000 $

Текущая фаза: **конец Этапа 0**.

## Стек

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — менеджер зависимостей
- python-okx — клиент биржи
- aiosqlite — БД
- pydantic + PyYAML — конфиг
- structlog — логирование

## Первый запуск

```powershell
# Из корня проекта
uv sync                                  # установит зависимости (создаст .venv)
copy .env.example .env                   # затем заполни OKX_API_* в .env
uv run python -m scalping_bot.main       # запуск (Этап 0: bootstrap-проверка)
```

## Структура

```
scalping-bot/
├── config/config.yaml          # параметры стратегии (TP/SL, объёмы, активы)
├── .env                        # секреты (НЕ коммитится)
├── .env.example                # шаблон секретов
├── src/scalping_bot/
│   ├── main.py                 # точка входа
│   ├── config.py               # загрузка config.yaml + .env
│   ├── logging_setup.py        # structlog
│   ├── exchange/okx_client.py  # OKX REST client
│   ├── market_data.py          # свечи, EMA, ATR (Stage 1)
│   ├── signal_engine.py        # сигналы входа (Stage 1)
│   ├── risk_manager.py         # глобальные риск-проверки (Stage 2)
│   ├── grid/manager.py         # FSM сеток (Stage 2)
│   ├── order_executor.py       # paper + live executor (Stage 2/3)
│   └── storage/
│       ├── schema.sql          # схема SQLite
│       └── db.py               # async обёртка
├── tests/                      # pytest
└── data/                       # SQLite файл (создаётся автоматически)
```

## Безопасность

- API ключ OKX — **только Trade**, **без Withdraw**, **с IP whitelist** на свой IP.
- Sub-account, а не основной аккаунт.
- `.env` — никогда не коммитить, не пересылать в чаты.
- Перед боевой торговлей — обязательный прогон paper-режима (≥ 1 неделя).

## Тесты

```powershell
uv run pytest
```
