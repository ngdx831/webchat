import sqlite3
from typing import Any, Dict, Optional

from .connection import _utc_now_iso, _iso_after


def pending_action_set(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    action: str,
    key: str = "",
    payload: str = "",
    ttl_seconds: int = 300,
) -> Dict[str, Any]:
    telegram_user_id = int(telegram_user_id)
    now = _utc_now_iso()
    expires_at = _iso_after(ttl_seconds)
    conn.execute(
        """
        INSERT INTO pending_actions(telegram_user_id, action, key, payload, expires_at, created_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            action=excluded.action,
            key=excluded.key,
            payload=excluded.payload,
            expires_at=excluded.expires_at,
            created_at=excluded.created_at
        """,
        (telegram_user_id, action or "", key or "", payload or "", expires_at, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM pending_actions WHERE telegram_user_id=? LIMIT 1",
        (telegram_user_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("PENDING_ACTION_SET_FAILED")
    return dict(row)


def pending_action_get(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT * FROM pending_actions
        WHERE telegram_user_id=? AND expires_at>?
        LIMIT 1
        """,
        (int(telegram_user_id), _utc_now_iso()),
    ).fetchone()
    return dict(row) if row else None


def pending_action_clear(conn: sqlite3.Connection, telegram_user_id: int) -> int:
    cur = conn.execute(
        "DELETE FROM pending_actions WHERE telegram_user_id=?",
        (int(telegram_user_id),),
    )
    conn.commit()
    return int(cur.rowcount)


def pending_action_cleanup(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM pending_actions WHERE expires_at<=?", (_utc_now_iso(),))
    conn.commit()
    return int(cur.rowcount)
