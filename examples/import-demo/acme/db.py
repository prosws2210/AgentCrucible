"""Database access. DATABASE_URL is a SQLite URL in development (sqlite:///path/to/acme.db)."""

import os
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///acme.db")


@contextmanager
def connect():
    path = os.environ.get("DATABASE_URL", DATABASE_URL).removeprefix("sqlite:///")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
