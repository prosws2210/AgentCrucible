import os
import sqlite3

DB = os.getenv("NOTES_DB", "notes.db")


def _conn():
    conn = sqlite3.connect(DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, topic TEXT, body TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return conn


def list_topics() -> list[tuple[str, int]]:
    with _conn() as c:
        return c.execute("SELECT topic, COUNT(*) FROM notes GROUP BY topic ORDER BY topic").fetchall()


def read_topic(topic: str) -> list[str]:
    with _conn() as c:
        return [r[0] for r in c.execute("SELECT body FROM notes WHERE topic = ? ORDER BY id", (topic,))]


def append(topic: str, body: str) -> int:
    with _conn() as c:
        return c.execute("INSERT INTO notes (topic, body) VALUES (?, ?)", (topic, body)).lastrowid


def purge(topic: str) -> int:
    with _conn() as c:
        return c.execute("DELETE FROM notes WHERE topic = ?", (topic,)).rowcount
