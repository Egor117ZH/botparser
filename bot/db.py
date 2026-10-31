import sqlite3
import time

from . import config

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY,
                ts  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                kind    TEXT,
                source  TEXT,
                url     TEXT,
                text    TEXT,
                ts      INTEGER NOT NULL
            );
            """
        )
    return _conn


def is_seen(key: str) -> bool:
    return conn().execute("SELECT 1 FROM seen WHERE key = ?", (key,)).fetchone() is not None


def mark_seen(keys: list[str]) -> None:
    now = int(time.time())
    conn().executemany("INSERT OR IGNORE INTO seen (key, ts) VALUES (?, ?)", [(k, now) for k in keys])
    conn().commit()


def save_post(kind: str, source: str, url: str, text: str) -> int:
    cur = conn().execute(
        "INSERT INTO posts (kind, source, url, text, ts) VALUES (?, ?, ?, ?, ?)",
        (kind, source, url, text, int(time.time())),
    )
    conn().commit()
    return cur.lastrowid


def get_post(post_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()


def reset_seen() -> int:
    cur = conn().execute("DELETE FROM seen")
    conn().commit()
    return cur.rowcount
