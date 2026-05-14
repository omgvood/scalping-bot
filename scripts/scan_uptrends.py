"""Найти все USDT-пары на OKX, где текущая дневная цена выше EMA(200).

Цель: за пределами нашего конфиг-списка (BTC/ETH/SOL/BNB) — какие активы
прямо сейчас проходят глобальный тренд-фильтр стратегии.

Фильтры по умолчанию:
- инструмент: spot, котировка USDT
- 24h volume >= 10M USDT (отсечь неликвидные)
- доступно >= 250 дневных свечей (для устойчивого EMA200)
- close > EMA200

Запуск:
    uv run python scripts/scan_uptrends.py                # дефолты
    uv run python scripts/scan_uptrends.py 5000000        # порог объёма 5M USDT
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from okx.MarketData import MarketAPI

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scalping_bot.indicators import ema  # noqa: E402

REQUEST_DELAY_SEC = 0.15
EMA_PERIOD = 200
MIN_CANDLES = 250  # запас на инициализацию + последняя свеча
DAILY_BAR = "1Dutc"

# Стейблкоины и wrapped-токены — у них тренда нет
EXCLUDED_BASE = {
    "USDC", "USDT", "DAI", "FDUSD", "TUSD", "BUSD", "USDP", "PYUSD", "GUSD",
    "EUR", "EURC", "EURT", "GBP",
    "WBTC", "WETH", "WBNB", "WSOL",
    "EURI", "PAX", "USDK", "USDS",
}


def fetch_usdt_tickers(api: MarketAPI, min_vol_usdt: float) -> list[dict]:
    """Один вызов /api/v5/market/tickers — отдаёт все 1200+ спотов разом."""
    resp = api.get_tickers(instType="SPOT")
    if resp.get("code") != "0":
        raise RuntimeError(f"get_tickers failed: {resp.get('msg')}")
    out: list[dict] = []
    for t in resp.get("data", []):
        inst = t.get("instId", "")
        if not inst.endswith("-USDT"):
            continue
        base = inst[:-5]
        if base in EXCLUDED_BASE:
            continue
        try:
            vol_usdt = float(t.get("volCcy24h") or 0)
            last = float(t.get("last") or 0)
        except ValueError:
            continue
        if vol_usdt < min_vol_usdt or last <= 0:
            continue
        out.append({"symbol": inst, "vol_usdt": vol_usdt, "last": last})
    out.sort(key=lambda x: -x["vol_usdt"])
    return out


def fetch_daily_closes(api: MarketAPI, symbol: str, limit: int = MIN_CANDLES) -> list[float] | None:
    """Возвращает closes от старой свечи к новой; None если данных недостаточно."""
    resp = api.get_candlesticks(instId=symbol, bar=DAILY_BAR, limit=str(limit))
    if resp.get("code") != "0":
        return None
    rows = resp.get("data", [])
    if len(rows) < MIN_CANDLES:
        return None
    # OKX даёт от новой к старой → разворачиваем
    closes: list[float] = []
    for r in reversed(rows):
        try:
            closes.append(float(r[4]))
        except (ValueError, IndexError):
            return None
    return closes


def main() -> None:
    min_vol = float(sys.argv[1]) if len(sys.argv) > 1 else 10_000_000.0
    print(f"OKX uptrend scan: spot/USDT, vol24h ≥ {min_vol:,.0f} USDT, close > EMA{EMA_PERIOD} (1D UTC)")
    print()

    api = MarketAPI(flag="0")
    tickers = fetch_usdt_tickers(api, min_vol)
    print(f"Pairs after volume filter: {len(tickers)}")
    print(f"Fetching ~{len(tickers) * REQUEST_DELAY_SEC:.0f}s of daily candles...\n")

    candidates: list[dict] = []
    skipped_no_history = 0
    skipped_below = 0
    skipped_error = 0
    t0 = time.time()

    for i, t in enumerate(tickers, 1):
        symbol = t["symbol"]
        if i % 20 == 0:
            print(f"  ... {i}/{len(tickers)}  ({time.time() - t0:.0f}s)")
        try:
            closes = fetch_daily_closes(api, symbol)
        except Exception:  # noqa: BLE001
            skipped_error += 1
            time.sleep(REQUEST_DELAY_SEC)
            continue
        if closes is None:
            skipped_no_history += 1
            time.sleep(REQUEST_DELAY_SEC)
            continue

        ema_val = ema(closes, period=EMA_PERIOD)
        last_close = closes[-1]
        if ema_val is None or last_close <= ema_val:
            skipped_below += 1
            time.sleep(REQUEST_DELAY_SEC)
            continue

        pct_above = (last_close / ema_val - 1) * 100
        candidates.append(
            {
                "symbol": symbol,
                "last": last_close,
                "ema200": ema_val,
                "pct_above_ema200": pct_above,
                "vol_usdt_24h": t["vol_usdt"],
            }
        )
        time.sleep(REQUEST_DELAY_SEC)

    print(f"\nDone in {time.time() - t0:.0f}s")
    print(f"  ✓ uptrend (close > EMA200): {len(candidates)}")
    print(f"  ✗ below EMA200:             {skipped_below}")
    print(f"  ✗ not enough history:       {skipped_no_history}")
    print(f"  ✗ API errors:               {skipped_error}")

    if not candidates:
        print("\nNo pairs in uptrend right now.")
        return

    # Сортируем по % выше EMA200
    candidates.sort(key=lambda x: -x["pct_above_ema200"])

    print("\n" + "=" * 78)
    print(f"{'#':>3}  {'pair':<14} {'last':>14} {'EMA200':>14} {'% above':>9}  {'vol24h USDT':>15}")
    print("-" * 78)
    for i, c in enumerate(candidates[:50], 1):
        print(
            f"{i:>3}  {c['symbol']:<14} "
            f"{c['last']:>14.6g} {c['ema200']:>14.6g} "
            f"{c['pct_above_ema200']:>+8.2f}%  "
            f"{c['vol_usdt_24h']:>15,.0f}"
        )
    if len(candidates) > 50:
        print(f"\n... and {len(candidates) - 50} more")


if __name__ == "__main__":
    main()
