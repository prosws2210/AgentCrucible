import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("INVENTORY_DB", os.path.expanduser("~/.inventory/inventory.db"))


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
