import sqlite3
from typing import Any, Dict, List, Optional

from .connection import _utc_now_ts


def quick_reply_add(conn: sqlite3.Connection, key: str, title: str, answer: str, sort_order: int = 0, enabled: int = 1) -> int:
    now = _utc_now_ts()
    cur = conn.execute(
        """
        INSERT INTO quick_replies(key, title, answer, sort_order, enabled, created_ts, updated_ts)
        VALUES(?,?,?,?,?,?,?)
        """,
        (key, title.strip(), answer.strip(), int(sort_order), 1 if int(enabled) else 0, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def quick_reply_list(conn: sqlite3.Connection, key: str, enabled_only: bool = True) -> List[Dict[str, Any]]:
    if enabled_only:
        rows = conn.execute(
            "SELECT * FROM quick_replies WHERE key=? AND enabled=1 ORDER BY sort_order ASC, id ASC",
            (key,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM quick_replies WHERE key=? ORDER BY sort_order ASC, id ASC",
            (key,),
        ).fetchall()
    return [dict(r) for r in rows]


def quick_reply_get(conn: sqlite3.Connection, reply_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM quick_replies WHERE id=? LIMIT 1", (int(reply_id),)).fetchone()
    return dict(row) if row else None


def quick_reply_delete(conn: sqlite3.Connection, key: str, reply_id: int) -> int:
    cur = conn.execute("DELETE FROM quick_replies WHERE key=? AND id=?", (key, int(reply_id)))
    conn.commit()
    return cur.rowcount
