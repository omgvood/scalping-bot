"""Проверка соединения с OKX.

Делает:
1) Публичный запрос (получает свечи BTC-USDT) — проверяет сеть + REST API биржи.
2) Приватный запрос (баланс sub-account) — проверяет API ключ, секрет, passphrase, IP whitelist.

Запуск:
    uv run python scripts/check_okx.py

Ключи берёт из .env (через scalping_bot.config). В консоль НЕ печатает ничего секретного.
"""

from __future__ import annotations

import sys
from typing import Any

from okx.Account import AccountAPI
from okx.MarketData import MarketAPI

from scalping_bot.config import Secrets

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _mask(value: str) -> str:
    """Показывает только длину, чтобы убедиться, что ключ непустой."""
    if not value:
        return "<empty>"
    return f"<{len(value)} chars>"


def check_secrets(secrets: Secrets) -> bool:
    print("=== .env проверка ===")
    print(f"OKX_API_KEY        : {_mask(secrets.okx_api_key)}")
    print(f"OKX_API_SECRET     : {_mask(secrets.okx_api_secret)}")
    print(f"OKX_API_PASSPHRASE : {_mask(secrets.okx_api_passphrase)}")
    print(f"OKX_USE_TESTNET    : {secrets.okx_use_testnet}")
    missing = [
        name
        for name, val in [
            ("OKX_API_KEY", secrets.okx_api_key),
            ("OKX_API_SECRET", secrets.okx_api_secret),
            ("OKX_API_PASSPHRASE", secrets.okx_api_passphrase),
        ]
        if not val
    ]
    if missing:
        print(f"\n[ERROR] Пустые поля в .env: {', '.join(missing)}")
        return False
    print("OK: все три поля заполнены")
    return True


def check_public(flag: str) -> bool:
    print("\n=== Публичный запрос: GET /api/v5/market/candles BTC-USDT 1H ===")
    api = MarketAPI(flag=flag)
    resp: dict[str, Any] = api.get_candlesticks(instId="BTC-USDT", bar="1H", limit="3")
    code = resp.get("code")
    if code != "0":
        print(f"[ERROR] OKX вернул code={code}, msg={resp.get('msg')!r}")
        return False
    candles = resp.get("data", [])
    print(f"OK: получено {len(candles)} свечей")
    for c in candles[:3]:
        # формат OKX: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
        ts_ms = int(c[0])
        print(
            f"  ts_ms={ts_ms}  O={c[1]}  H={c[2]}  L={c[3]}  C={c[4]}  "
            f"confirm={'closed' if c[8] == '1' else 'forming'}"
        )
    return True


def check_private(secrets: Secrets, flag: str) -> bool:
    print("\n=== Приватный запрос: GET /api/v5/account/balance ===")
    api = AccountAPI(
        api_key=secrets.okx_api_key,
        api_secret_key=secrets.okx_api_secret,
        passphrase=secrets.okx_api_passphrase,
        flag=flag,
        debug=False,
    )
    resp: dict[str, Any] = api.get_account_balance()
    code = resp.get("code")
    if code != "0":
        print(f"[ERROR] OKX вернул code={code}, msg={resp.get('msg')!r}")
        if resp.get("msg", "").lower().find("ip") >= 0 or code == "50110":
            print(
                "        → Скорее всего IP не в whitelist. Проверь свой публичный IP "
                "на https://www.whatismyip.com и сравни с whitelist у API ключа на OKX."
            )
        elif code in ("50111", "50112", "50113", "50114"):
            print("        → Ключ/секрет/passphrase неверны или ключ просрочен/отключён.")
        return False

    data = resp.get("data", [])
    if not data:
        print("OK: ответ пустой (sub-account создан, но без активов — это нормально)")
        return True

    print("OK: баланс sub-account получен")
    details = data[0].get("details", [])
    if not details:
        print("  (на sub-account пока нет монет — это ожидаемо для Этапа 1)")
    else:
        print(f"  Найдено активов: {len(details)}")
        for d in details[:5]:
            ccy = d.get("ccy")
            avail = d.get("availBal", "0")
            eq = d.get("eq", "0")
            print(f"  - {ccy:<8} avail={avail}  equity={eq}")
    return True


def main() -> int:
    secrets = Secrets()
    flag = "1" if secrets.okx_use_testnet else "0"

    if not check_secrets(secrets):
        return 1
    if not check_public(flag):
        return 2
    if not check_private(secrets, flag):
        return 3

    print("\n=== Все проверки прошли ===")
    print("Можно начинать Этап 1: опрос свечей и детектор сигналов.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
