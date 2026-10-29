import os
from dataclasses import dataclass

import aiosqlite


class DatabaseConn:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("BANK_DB", "bank.sqlite3")

    async def fetchone(self, sql: str, *params):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(sql, params) as cur:
                return await cur.fetchone()

    async def fetchall(self, sql: str, *params):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(sql, params) as cur:
                return await cur.fetchall()

    async def execute(self, sql: str, *params) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(sql, params)
            await db.commit()
            return cur.rowcount


@dataclass
class SupportDeps:
    customer_id: int
    db: DatabaseConn
