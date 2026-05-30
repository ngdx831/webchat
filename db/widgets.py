import sqlite3
from typing import Any, Dict, List, Optional

from .connection import _table_has_column, _utc_now_ts, _widgets_key_col


def widget_add(
    conn: sqlite3.Connection,
    key: str,
    forum_chat_id: int,
    display_name: str,
    must_not_exist: bool = True,
    owner_user_id: Optional[int] = None,
) -> None:
    keycol = _widgets_key_col(conn)
    if must_not_exist:
        cur = conn.execute(f"SELECT 1 FROM widgets WHERE {keycol}=? LIMIT 1", (key,))
        if cur.fetchone():
            raise ValueError("KEY_EXISTS")

    try:
        now_ts = _utc_now_ts()
        conn.execute(
            f"INSERT INTO widgets({keycol}, owner_user_id, display_name, forum_chat_id, created_ts, updated_ts) VALUES(?,?,?,?,?,?) "
            f"ON CONFLICT({keycol}) DO UPDATE SET owner_user_id=excluded.owner_user_id, display_name=excluded.display_name, forum_chat_id=excluded.forum_chat_id, updated_ts=excluded.updated_ts",
            (key, owner_user_id, display_name, int(forum_chat_id), now_ts, now_ts),
        )
    except Exception:
        conn.execute(
            f"INSERT INTO widgets({keycol}, owner_user_id, forum_chat_id, display_name, enabled, offline_msg, offline_ts) VALUES(?,?,?,?,?,?,?) "
            f"ON CONFLICT({keycol}) DO UPDATE SET owner_user_id=excluded.owner_user_id, forum_chat_id=excluded.forum_chat_id, display_name=excluded.display_name",
            (key, owner_user_id, int(forum_chat_id), display_name, 1, "", 0),
        )
    conn.commit()


def widget_del(conn: sqlite3.Connection, key: str) -> int:
    keycol = _widgets_key_col(conn)
    cur = conn.execute(f"DELETE FROM widgets WHERE {keycol}=?", (key,))
    conn.commit()
    return cur.rowcount


def widget_get(conn: sqlite3.Connection, key: str) -> Optional[Dict[str, Any]]:
    keycol = _widgets_key_col(conn)
    owner_expr = "owner_user_id" if _table_has_column(conn, "widgets", "owner_user_id") else "NULL"
    enabled_expr = "enabled" if _table_has_column(conn, "widgets", "enabled") else "1"
    offmsg_expr = "offline_msg" if _table_has_column(conn, "widgets", "offline_msg") else "''"
    offat_expr = "offline_ts" if _table_has_column(conn, "widgets", "offline_ts") else "0"
    welcome_expr = "welcome_text" if _table_has_column(conn, "widgets", "welcome_text") else "''"
    sched_expr = "work_schedule" if _table_has_column(conn, "widgets", "work_schedule") else "''"
    sched_active_expr = "work_schedule_active" if _table_has_column(conn, "widgets", "work_schedule_active") else "1"
    cur = conn.execute(
        f"""
        SELECT {keycol} as key, forum_chat_id, display_name,
               {owner_expr} as owner_user_id,
               {enabled_expr} as enabled,
               {offmsg_expr} as offline_msg,
               {offat_expr} as offline_at,
               {welcome_expr} as welcome_text,
               {sched_expr} as work_schedule,
               {sched_active_expr} as work_schedule_active
        FROM widgets
        WHERE {keycol}=?
        LIMIT 1
        """,
        (key,),
    )
    row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    if out.get("owner_user_id") is not None:
        out["owner_user_id"] = int(out["owner_user_id"])
    out["enabled"] = int(out.get("enabled") or 0)
    out["offline_msg"] = out.get("offline_msg") or ""
    out["offline_at"] = out.get("offline_at") or ""
    out["welcome_text"] = out.get("welcome_text") or ""
    out["work_schedule"] = out.get("work_schedule") or ""
    out["work_schedule_active"] = int(out.get("work_schedule_active") if out.get("work_schedule_active") is not None else 1)
    return out


def widget_list(conn: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    keycol = _widgets_key_col(conn)
    owner_expr = "owner_user_id" if _table_has_column(conn, "widgets", "owner_user_id") else "NULL"
    enabled_expr = "enabled" if _table_has_column(conn, "widgets", "enabled") else "1"
    offmsg_expr = "offline_msg" if _table_has_column(conn, "widgets", "offline_msg") else "''"
    offat_expr = "offline_ts" if _table_has_column(conn, "widgets", "offline_ts") else "0"
    welcome_expr = "welcome_text" if _table_has_column(conn, "widgets", "welcome_text") else "''"
    sched_expr = "work_schedule" if _table_has_column(conn, "widgets", "work_schedule") else "''"
    sched_active_expr = "work_schedule_active" if _table_has_column(conn, "widgets", "work_schedule_active") else "1"
    rows = conn.execute(
        f"""
        SELECT {keycol} as key, forum_chat_id, display_name,
               {owner_expr} as owner_user_id,
               {enabled_expr} as enabled,
               {offmsg_expr} as offline_msg,
               {offat_expr} as offline_at,
               {welcome_expr} as welcome_text,
               {sched_expr} as work_schedule,
               {sched_active_expr} as work_schedule_active
        FROM widgets
        ORDER BY {keycol} ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    out = [dict(r) for r in rows]
    for row in out:
        if row.get("owner_user_id") is not None:
            row["owner_user_id"] = int(row["owner_user_id"])
        row["enabled"] = int(row.get("enabled") or 0)
        row["offline_msg"] = row.get("offline_msg") or ""
        row["offline_at"] = row.get("offline_at") or ""
        row["welcome_text"] = row.get("welcome_text") or ""
        row["work_schedule"] = row.get("work_schedule") or ""
        row["work_schedule_active"] = int(row.get("work_schedule_active") if row.get("work_schedule_active") is not None else 1)
    return out


def widget_list_by_owner(conn: sqlite3.Connection, owner_user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    keycol = _widgets_key_col(conn)
    rows = conn.execute(
        f"""
        SELECT {keycol} as key, owner_user_id, forum_chat_id, display_name,
               enabled, offline_msg, offline_ts as offline_at, welcome_text
        FROM widgets
        WHERE owner_user_id=?
        ORDER BY {keycol} ASC
        LIMIT ?
        """,
        (int(owner_user_id), int(limit)),
    ).fetchall()
    out = [dict(r) for r in rows]
    for row in out:
        row["owner_user_id"] = int(row["owner_user_id"])
        row["enabled"] = int(row.get("enabled") or 0)
        row["offline_msg"] = row.get("offline_msg") or ""
        row["offline_at"] = row.get("offline_at") or ""
        row["welcome_text"] = row.get("welcome_text") or ""
    return out


def widget_count_by_owner(conn: sqlite3.Connection, owner_user_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM widgets WHERE owner_user_id=?",
        (int(owner_user_id),),
    ).fetchone()
    return int(row["count"] if row else 0)


def widget_get_owned(conn: sqlite3.Connection, key: str, owner_user_id: int) -> Optional[Dict[str, Any]]:
    widget = widget_get(conn, key)
    if not widget or widget.get("owner_user_id") != int(owner_user_id):
        return None
    return widget


def widget_set_enabled(conn: sqlite3.Connection, key: str, enabled: int, offline_msg: Optional[str] = None) -> bool:
    keycol = _widgets_key_col(conn)
    enabled = 1 if int(enabled) else 0
    now = _utc_now_ts()
    if enabled == 0:
        cur = conn.execute(
            f"UPDATE widgets SET enabled=0, offline_msg=?, offline_ts=? WHERE {keycol}=?",
            (offline_msg or "", now, key),
        )
    else:
        cur = conn.execute(
            f"UPDATE widgets SET enabled=1, offline_ts=0 WHERE {keycol}=?",
            (key,),
        )
    conn.commit()
    return cur.rowcount > 0


def widget_set_offline_msg(conn: sqlite3.Connection, key: str, offline_msg: str) -> bool:
    keycol = _widgets_key_col(conn)
    cur = conn.execute(f"UPDATE widgets SET offline_msg=? WHERE {keycol}=?", (offline_msg or "", key))
    conn.commit()
    return cur.rowcount > 0


def widget_set_forum_chat_id(conn: sqlite3.Connection, key: str, forum_chat_id: int) -> bool:
    keycol = _widgets_key_col(conn)
    cur = conn.execute(
        f"UPDATE widgets SET forum_chat_id=? WHERE {keycol}=?",
        (int(forum_chat_id), key),
    )
    conn.commit()
    return cur.rowcount > 0


def widget_set_welcome_text(conn: sqlite3.Connection, key: str, welcome_text: str) -> bool:
    keycol = _widgets_key_col(conn)
    cur = conn.execute(
        f"UPDATE widgets SET welcome_text=? WHERE {keycol}=?",
        (welcome_text or "", key),
    )
    conn.commit()
    return cur.rowcount > 0


def widget_set_work_schedule(conn: sqlite3.Connection, key: str, schedule: str) -> bool:
    keycol = _widgets_key_col(conn)
    cur = conn.execute(
        f"UPDATE widgets SET work_schedule=? WHERE {keycol}=?",
        (schedule or "", key),
    )
    conn.commit()
    return cur.rowcount > 0


def widget_set_work_schedule_active(conn: sqlite3.Connection, key: str, active: bool) -> bool:
    keycol = _widgets_key_col(conn)
    cur = conn.execute(
        f"UPDATE widgets SET work_schedule_active=? WHERE {keycol}=?",
        (1 if active else 0, key),
    )
    conn.commit()
    return cur.rowcount > 0


def widget_get_work_schedule(conn: sqlite3.Connection, key: str) -> str:
    keycol = _widgets_key_col(conn)
    row = conn.execute(
        f"SELECT work_schedule FROM widgets WHERE {keycol}=? LIMIT 1", (key,)
    ).fetchone()
    if not row:
        return ""
    try:
        return row["work_schedule"] or ""
    except (KeyError, IndexError):
        return ""
