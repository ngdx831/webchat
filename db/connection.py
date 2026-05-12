import os
import sqlite3
from datetime import datetime, timedelta, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _iso_after(seconds: int) -> str:
    return (_utc_now() + timedelta(seconds=int(seconds))).isoformat()


def get_conn(path: str) -> sqlite3.Connection:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return col in [r[1] for r in cur.fetchall()]
    except Exception:
        return False


def _widgets_key_col(conn: sqlite3.Connection) -> str:
    if _table_has_column(conn, "widgets", "k"):
        return "k"
    return "key"


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
    except Exception:
        pass
