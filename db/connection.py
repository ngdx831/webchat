import os
import sqlite3
from datetime import datetime, timedelta, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _utc_now_ts() -> int:
    return int(_utc_now().timestamp())


def _iso_after(seconds: int) -> str:
    return (_utc_now() + timedelta(seconds=int(seconds))).isoformat()


def _ts_after(seconds: int) -> int:
    return _utc_now_ts() + int(seconds)


def get_conn(path: str) -> sqlite3.Connection:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # 并发友好的 PRAGMA;失败时静默(老数据库可能不支持)。
    for pragma in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA busy_timeout=5000",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA temp_store=MEMORY",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.DatabaseError:
            continue
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
