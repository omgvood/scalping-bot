"""Подобрать min_body_pct для новых активов по реальной 15m волатильности.

Для каждой пары считаем распределение размера тела ЗЕЛЁНЫХ 15m свечей
в процентах от open: body_pct = (close - open) / open * 100.

Показываем перцентили 25/50/75/90 — это «типичные» размеры тел.
Текущие min_body_pct из спеки нужно сопоставлять с одним и тем же
перцентилем для всех активов, чтобы фильтр работал единообразно.

Запуск:
    uv run python scripts/calibrate_body_filter.py
"""

from __future__ import annotations

import sqlite3
import statistics
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scalping_bot.config import StrategyConfig  # noqa: E402

# Текущие значения из config.yaml — для сопоставления
CURRENT_THRESHOLDS = {
    "BTC-USDT": 0.10,
    "ETH-USDT": 0.15,
    "SOL-USDT": 0.25,
    "BNB-USDT": 0.15,
}


def green_body_pcts(conn: sqlite3.Connection, symbol: str) -> list[float]:
    rows = conn.execute(
        """SELECT open, close FROM historical_candles
           WHERE symbol = ? AND timeframe = '15m' AND close > open""",
        (symbol,),
    ).fetchall()
    return [(c - o) / o * 100.0 for o, c in rows if o > 0]


def percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(round((len(sorted_vals) - 1) * p / 100))
    return sorted_vals[idx]


def analyze(conn: sqlite3.Connection, symbol: str) -> dict | None:
    bodies = sorted(green_body_pcts(conn, symbol))
    if not bodies:
        return None
    return {
        "symbol": symbol,
        "count": len(bodies),
        "p25": percentile(bodies, 25),
        "p50": percentile(bodies, 50),
        "p75": percentile(bodies, 75),
        "p90": percentile(bodies, 90),
        "mean": statistics.fmean(bodies),
    }


def main() -> None:
    cfg = StrategyConfig.load()
    db_path = PROJECT_ROOT / cfg.storage.db_path
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return
    conn = sqlite3.connect(db_path)

    # Сначала эталонные активы (по которым уже есть min_body_pct в спеке),
    # потом всё остальное, что нашлось в БД
    in_db = {
        row[0]
        for row in conn.execute("SELECT DISTINCT symbol FROM historical_candles")
    }
    known = [s for s in CURRENT_THRESHOLDS if s in in_db]
    others = sorted(in_db - set(known))
    symbols = known + others

    print("Distribution of GREEN 15m candle body sizes (% of open price)")
    print("Higher percentile = bigger body. 'p50' is the median body.\n")
    print(
        f"{'pair':<12} {'count':>8} {'p25':>8} {'p50':>8} {'p75':>8} {'p90':>8} "
        f"{'mean':>8}   {'current cfg':>12}   {'p50/cfg ratio':>16}"
    )
    print("-" * 110)

    results: list[dict] = []
    for symbol in symbols:
        r = analyze(conn, symbol)
        if r is None:
            continue
        cfg_val = CURRENT_THRESHOLDS.get(symbol)
        ratio = (r["p50"] / cfg_val) if cfg_val else None
        print(
            f"{symbol:<12} {r['count']:>8,} "
            f"{r['p25']:>7.3f}% {r['p50']:>7.3f}% {r['p75']:>7.3f}% {r['p90']:>7.3f}% "
            f"{r['mean']:>7.3f}%   "
            + (f"{cfg_val:>11.2f}%" if cfg_val is not None else f"{'—':>12}")
            + "   "
            + (f"{ratio:>15.2f}" if ratio is not None else f"{'—':>16}")
        )
        results.append({**r, "current_cfg": cfg_val})

    # На основе известных активов вычислим средний коэффициент cfg/p50,
    # и применим его к новым.
    known_ratios = [
        r["current_cfg"] / r["p50"] for r in results if r.get("current_cfg") and r["p50"] > 0
    ]
    if known_ratios:
        scale = statistics.fmean(known_ratios)
        print()
        print(f"Average (current_cfg / median_body_pct) across known assets = {scale:.2f}")
        print("Apply that ratio to new assets to keep the filter equally selective:")
        for r in results:
            if r.get("current_cfg") is None:
                suggested = round(r["p50"] * scale, 2)
                print(f"  {r['symbol']:<12}  median body = {r['p50']:.3f}% → suggested min_body_pct = {suggested}%")

    conn.close()


if __name__ == "__main__":
    main()
