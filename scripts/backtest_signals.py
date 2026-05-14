"""Replay SignalEngine на исторических свечах. Часть A: только частота входов.

Идея:
- Считаем 15m главным «таймером» истории. На каждой 15m-свече, для каждого
  актива собираем SymbolSnapshot — последние закрытые свечи 15m/30m/60m/1D
  и предвычисленные индикаторы (EMA200 на 1D, ATR14 на коротких ТФ).
- Прогоняем уже написанный SignalEngine.check_entry() — он работает
  одинаково и в live, и в replay.

PnL НЕ считаем — для этого нужна FSM сетки (Часть B / Этап 2). Сейчас
только: сколько входов было бы и где они кластеризованы.

Запуск:
    uv run python scripts/backtest_signals.py
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scalping_bot.config import StrategyConfig  # noqa: E402
from scalping_bot.exchange.okx_client import Candle  # noqa: E402
from scalping_bot.market_data import SymbolSnapshot, TimeframeSnapshot  # noqa: E402
from scalping_bot.signal_engine import SignalEngine  # noqa: E402

# Сколько свечей предыдущей истории нужно перед первым пригодным сигналом:
# EMA(200) на 1D = 200 дней; берём с запасом 250 для прогрева.
WARMUP_DAYS = 250


def _load_candles(
    conn: sqlite3.Connection,
    symbol: str,
    timeframe: str,
) -> list[Candle]:
    rows = conn.execute(
        """SELECT open_time, open, high, low, close, volume
             FROM historical_candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY open_time ASC""",
        (symbol, timeframe),
    ).fetchall()
    out: list[Candle] = []
    for r in rows:
        out.append(
            Candle(
                open_time=datetime.fromisoformat(r[0]),
                open=r[1],
                high=r[2],
                low=r[3],
                close=r[4],
                volume=r[5],
                confirm=True,  # исторические свечи всегда закрыты
            )
        )
    return out


def _precompute_ema(candles: list[Candle], period: int) -> list[float | None]:
    """Инкрементальный EMA за один проход (O(N)).

    Seed: SMA первых `period` значений → значение на индексе period-1.
    Далее EMA(t) = alpha * close(t) + (1-alpha) * EMA(t-1).
    """
    n = len(candles)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    seed = sum(c.close for c in candles[:period]) / period
    result[period - 1] = seed
    alpha = 2.0 / (period + 1)
    current = seed
    for i in range(period, n):
        current = alpha * candles[i].close + (1 - alpha) * current
        result[i] = current
    return result


def _precompute_atr(candles: list[Candle], period: int) -> list[float | None]:
    """Инкрементальный ATR (Wilder) за один проход (O(N)).

    Seed: SMA первых `period` true-range значений → ATR на индексе period.
    Далее ATR(t) = ((period-1)*ATR(t-1) + TR(t)) / period.
    """
    n = len(candles)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result
    trs: list[float] = []
    for i in range(1, n):
        h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    seed = sum(trs[:period]) / period
    result[period] = seed  # ATR соответствует свече с индексом period (1-based от tr-индекса)
    current = seed
    # trs[i] относится к свече с индексом i+1 (так как мы пропустили первую)
    for i in range(period, len(trs)):
        current = ((period - 1) * current + trs[i]) / period
        result[i + 1] = current
    return result


def _last_closed_at_or_before(
    candles: list[Candle],
    cursor: int,
    cutoff: datetime,
) -> tuple[int, Candle] | None:
    """Идём вперёд от cursor пока candle.open_time + duration <= cutoff.
    Возвращает (новый_cursor, последняя_подходящая_свеча) или None."""
    last_idx: int | None = None
    i = cursor
    while i < len(candles) and candles[i].open_time <= cutoff:
        last_idx = i
        i += 1
    if last_idx is None:
        return None
    return last_idx, candles[last_idx]


def _bar_duration(tf: str) -> timedelta:
    return {
        "15m": timedelta(minutes=15),
        "30m": timedelta(minutes=30),
        "60m": timedelta(hours=1),
        "1D": timedelta(days=1),
    }[tf]


def replay_symbol(
    symbol: str,
    cfg: StrategyConfig,
    conn: sqlite3.Connection,
    engine: SignalEngine,
) -> dict[str, Any]:
    """Прогоняет один актив, возвращает агрегаты."""
    candles_by_tf: dict[str, list[Candle]] = {}
    for tf in ["15m", "30m", "60m", "1D"]:
        candles_by_tf[tf] = _load_candles(conn, symbol, tf)
        if not candles_by_tf[tf]:
            return {"symbol": symbol, "error": f"no data for {tf}"}

    # Предвычисление индикаторов
    ema200_by_day = _precompute_ema(
        candles_by_tf["1D"],
        period=cfg.signal.trend_filter.ema_period,
    )
    atr14_by_tf: dict[str, list[float | None]] = {}
    for tf in ["15m", "30m", "60m"]:
        atr14_by_tf[tf] = _precompute_atr(candles_by_tf[tf], period=14)

    fifteen = candles_by_tf["15m"]
    # Прогрев: пропускаем первые WARMUP_DAYS, чтобы EMA(200) уже была готова
    start_cutoff = fifteen[0].open_time + timedelta(days=WARMUP_DAYS)
    cursors: dict[str, int] = {tf: 0 for tf in ["30m", "60m", "1D"]}

    enters = 0
    skips_by_reason: dict[str, int] = defaultdict(int)
    enters_by_month: dict[str, int] = defaultdict(int)
    sample_entries: list[dict[str, Any]] = []
    # Дедуп: уникальные дни и распределение длины серий подряд идущих сигналов
    enter_days: set[str] = set()
    runs: list[int] = []
    current_run = 0

    for i, c15 in enumerate(fifteen):
        # «Сейчас» = момент закрытия этой 15m свечи
        now = c15.open_time + _bar_duration("15m")
        if now < start_cutoff:
            continue

        snap = SymbolSnapshot(symbol=symbol, captured_at=now)
        snap.by_timeframe["15m"] = TimeframeSnapshot("15m", c15, atr14=atr14_by_tf["15m"][i])

        # Для 30m/60m/1D: последняя закрытая свеча на момент `now`
        valid = True
        for tf in ["30m", "60m", "1D"]:
            found = _last_closed_at_or_before(
                candles_by_tf[tf],
                cursor=cursors[tf],
                cutoff=now - _bar_duration(tf),  # свеча закрыта = её начало + длительность <= now
            )
            if found is None:
                valid = False
                break
            idx, candle = found
            cursors[tf] = idx
            indicator_key = "atr14" if tf != "1D" else "ema200"
            arr = ema200_by_day if tf == "1D" else atr14_by_tf[tf]
            kwargs = {indicator_key: arr[idx]}
            snap.by_timeframe[tf] = TimeframeSnapshot(tf, candle, **kwargs)  # type: ignore[arg-type]

        if not valid:
            continue

        result = engine.check_entry(snap)
        if result.should_enter:
            enters += 1
            current_run += 1
            month_key = now.strftime("%Y-%m")
            enters_by_month[month_key] += 1
            enter_days.add(now.strftime("%Y-%m-%d"))
            if len(sample_entries) < 5:
                sample_entries.append(
                    {
                        "time": now.isoformat(),
                        "price": c15.close,
                        "ema200_1d": snap.by_timeframe["1D"].ema200,
                    }
                )
        else:
            if current_run > 0:
                runs.append(current_run)
                current_run = 0
            skips_by_reason[result.failed_check or "unknown"] += 1
    if current_run > 0:
        runs.append(current_run)

    total_bars = sum(1 for c in fifteen if c.open_time + _bar_duration("15m") >= start_cutoff)
    avg_run = sum(runs) / len(runs) if runs else 0.0
    max_run = max(runs) if runs else 0
    return {
        "symbol": symbol,
        "total_bars": total_bars,
        "enters": enters,
        "enter_runs": len(runs),                # уникальные серии входов
        "enter_days": len(enter_days),          # уникальные дни
        "avg_run_len": avg_run,
        "max_run_len": max_run,
        "skips_by_reason": dict(skips_by_reason),
        "enters_by_month": dict(sorted(enters_by_month.items())),
        "sample_entries": sample_entries,
        "history_from": fifteen[0].open_time.isoformat() if fifteen else None,
        "history_to": fifteen[-1].open_time.isoformat() if fifteen else None,
    }


def _format_pct(num: int, total: int) -> str:
    return f"{(num / total * 100):.2f}%" if total else "0%"


def main() -> None:
    cfg = StrategyConfig.load()
    db_path = PROJECT_ROOT / cfg.storage.db_path
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        print("Сначала запусти scripts/download_history.py")
        return

    conn = sqlite3.connect(db_path)
    engine = SignalEngine(cfg)

    print("=" * 78)
    print("BACKTEST PART A — Signal frequency analysis")
    print("=" * 78)
    for asset in cfg.assets:
        result = replay_symbol(asset.symbol, cfg, conn, engine)
        print(f"\n>>> {asset.symbol}")
        if "error" in result:
            print(f"    ERROR: {result['error']}")
            continue
        print(f"    history:        {result['history_from'][:10]} → {result['history_to'][:10]}")
        print(f"    15m bars after warmup: {result['total_bars']:,}")
        print(f"    raw signal bars:       {result['enters']}")
        print(f"    distinct trigger runs: {result['enter_runs']}  "
              f"(avg run = {result['avg_run_len']:.1f} bars, max = {result['max_run_len']})")
        print(f"    distinct trigger days: {result['enter_days']}")
        skips_total = sum(result["skips_by_reason"].values())
        print(f"    skips:          {skips_total:,}")
        for reason, count in sorted(result["skips_by_reason"].items()):
            print(f"      - {reason:<8} {count:>6,}  ({_format_pct(count, skips_total)})")
        if result["enters_by_month"]:
            print("    entries by month (top 12 most active):")
            top = sorted(result["enters_by_month"].items(), key=lambda x: -x[1])[:12]
            for month, count in sorted(top):
                print(f"      {month}  {count}")
        if result["sample_entries"]:
            print("    first 5 entries:")
            for s in result["sample_entries"]:
                print(
                    f"      {s['time'][:16]}  price={s['price']:.4f}  "
                    f"ema200_1d={s['ema200_1d']:.4f}"
                )

    conn.close()


if __name__ == "__main__":
    main()
