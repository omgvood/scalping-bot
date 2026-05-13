"""Утилита: вывести список таблиц в SQLite и количество записей."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "bot.sqlite3"


def main() -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    print(f"DB: {DB_PATH}\nTables:")
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ):
        (count,) = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
        print(f"  - {name:<14} rows={count}")
    conn.close()


if __name__ == "__main__":
    main()
