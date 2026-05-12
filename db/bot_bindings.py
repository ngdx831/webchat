import sqlite3
from typing import Any, Dict, List, Optional

from .connection import _utc_now_iso


def bot_binding_add(
    conn: sqlite3.Connection,
    key: str,
    bot_token: str,
    bot_username: str = "",
    enabled: int = 1,
    owner_user_id: Optional[int] = None,
) -> int:
    now = _utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO bot_bindings(key, owner_user_id, bot_token, bot_username, enabled, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(bot_token) DO UPDATE SET
            key=excluded.key,
            owner_user_id=excluded.owner_user_id,
            bot_username=excluded.bot_username,
            enabled=excluded.enabled,
            updated_at=excluded.updated_at
        """,
        (key, owner_user_id, bot_token, bot_username or "", 1 if int(enabled) else 0, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM bot_bindings WHERE bot_token=? LIMIT 1", (bot_token,)).fetchone()
    return int(row["id"] if row else cur.lastrowid)


def bot_binding_delete(conn: sqlite3.Connection, key: str, bot_username: str = "") -> int:
    if bot_username:
        cur = conn.execute("DELETE FROM bot_bindings WHERE key=? AND bot_username=?", (key, bot_username))
    else:
        cur = conn.execute("DELETE FROM bot_bindings WHERE key=?", (key,))
    conn.commit()
    return cur.rowcount


def bot_binding_list(conn: sqlite3.Connection, key: str = "", enabled_only: bool = False) -> List[Dict[str, Any]]:
    where = []
    args: List[Any] = []
    if key:
        where.append("key=?")
        args.append(key)
    if enabled_only:
        where.append("enabled=1")
    sql = "SELECT * FROM bot_bindings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY key ASC, bot_username ASC, id ASC"
    out = [dict(r) for r in conn.execute(sql, args).fetchall()]
    for row in out:
        if row.get("owner_user_id") is not None:
            row["owner_user_id"] = int(row["owner_user_id"])
    return out


def bot_binding_list_by_owner(
    conn: sqlite3.Connection,
    owner_user_id: int,
    key: str = "",
    enabled_only: bool = False,
) -> List[Dict[str, Any]]:
    where = ["owner_user_id=?"]
    args: List[Any] = [int(owner_user_id)]
    if key:
        where.append("key=?")
        args.append(key)
    if enabled_only:
        where.append("enabled=1")
    sql = "SELECT * FROM bot_bindings WHERE " + " AND ".join(where)
    sql += " ORDER BY key ASC, bot_username ASC, id ASC"
    out = [dict(r) for r in conn.execute(sql, args).fetchall()]
    for row in out:
        row["owner_user_id"] = int(row["owner_user_id"])
    return out


def bot_binding_get(conn: sqlite3.Connection, binding_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM bot_bindings WHERE id=? LIMIT 1", (int(binding_id),)).fetchone()
    if not row:
        return None
    out = dict(row)
    if out.get("owner_user_id") is not None:
        out["owner_user_id"] = int(out["owner_user_id"])
    return out
