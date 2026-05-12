import sqlite3

from .connection import _utc_now_iso


def setting_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=? LIMIT 1", (key,)).fetchone()
    if not row:
        return default
    return row["value"] or ""


def setting_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value, updated_at)
        VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (key, value or "", _utc_now_iso()),
    )
    conn.commit()
