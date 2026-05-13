"""SQLite database wrapper (async via aiosqlite)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Тонкая обёртка над aiosqlite с lazy-инициализацией схемы."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._apply_schema()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _apply_schema(self) -> None:
        assert self._conn is not None
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        await self._conn.executescript(schema_sql)
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
