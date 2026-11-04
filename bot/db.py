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
            -- о чём уже писали: чтобы не было повторов между сборами
            CREATE TABLE IF NOT EXISTS history (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                gist     TEXT NOT NULL,
                title    TEXT,
                url      TEXT,
                ts       INTEGER NOT NULL
            );
            """
        )
        try:  # база от старой версии — докидываем колонку
            _conn.execute("ALTER TABLE posts ADD COLUMN category TEXT")
        except sqlite3.OperationalError:
            pass
    return _conn


def is_seen(key: str) -> bool:
    return conn().execute("SELECT 1 FROM seen WHERE key = ?", (key,)).fetchone() is not None


def mark_seen(keys: list[str]) -> None:
    now = int(time.time())
    conn().executemany("INSERT OR IGNORE INTO seen (key, ts) VALUES (?, ?)", [(k, now) for k in keys])
    conn().commit()


def save_post(category: str, kind: str, source: str, url: str, text: str) -> int:
    cur = conn().execute(
        "INSERT INTO posts (category, kind, source, url, text, ts) VALUES (?, ?, ?, ?, ?, ?)",
        (category, kind, source, url, text, int(time.time())),
    )
    conn().commit()
    return cur.lastrowid


def get_post(post_id: int) -> sqlite3.Row | None:
    return conn().execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()


def add_history(category: str, gist: str, title: str, url: str) -> None:
    conn().execute(
        "INSERT INTO history (category, gist, title, url, ts) VALUES (?, ?, ?, ?, ?)",
        (category, gist, title, url, int(time.time())),
    )
    conn().commit()


def get_history(category: str, limit: int) -> list[sqlite3.Row]:
    return conn().execute(
        "SELECT gist, title FROM history WHERE category = ? ORDER BY id DESC LIMIT ?", (category, limit)
    ).fetchall()


def reset() -> tuple[int, int]:
    seen = conn().execute("DELETE FROM seen").rowcount
    hist = conn().execute("DELETE FROM history").rowcount
    conn().commit()
    return seen, hist
