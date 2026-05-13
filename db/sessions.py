import hmac
import json
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional

from .connection import _utc_now_ts


def session_get(conn: sqlite3.Connection, session_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM sessions WHERE session_id=? LIMIT 1", (session_id,)).fetchone()
    return dict(row) if row else None


def session_get_by_thread(conn: sqlite3.Connection, forum_chat_id: int, thread_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM sessions WHERE forum_chat_id=? AND thread_id=? LIMIT 1",
        (int(forum_chat_id), int(thread_id)),
    ).fetchone()
    return dict(row) if row else None


def session_create_if_missing(
    conn: sqlite3.Connection,
    session_id: str,
    key: str,
    forum_chat_id: int,
    channel: str = "web",
    source_code: str = "",
    visitor_id: str = "",
    customer_chat_id: Optional[int] = None,
    bot_binding_id: Optional[int] = None,
) -> bool:
    if conn.execute("SELECT 1 FROM sessions WHERE session_id=? LIMIT 1", (session_id,)).fetchone():
        return False
    now = _utc_now_ts()
    conn.execute(
        """
        INSERT INTO sessions(
            session_id, key, forum_chat_id, thread_id, channel, source_code,
            visitor_id, customer_chat_id, bot_binding_id, customer_status,
            marked_by, marked_ts, created_ts, last_activity_ts
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id,
            key,
            int(forum_chat_id),
            None,
            channel or "web",
            source_code or "",
            visitor_id or "",
            int(customer_chat_id) if customer_chat_id is not None else None,
            int(bot_binding_id) if bot_binding_id is not None else None,
            "none",
            "",
            0,
            now,
            now,
        ),
    )
    conn.commit()
    return True


def session_find_customer(conn: sqlite3.Connection, bot_binding_id: int, customer_chat_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT * FROM sessions
        WHERE bot_binding_id=? AND customer_chat_id=?
        ORDER BY created_ts DESC
        LIMIT 1
        """,
        (int(bot_binding_id), int(customer_chat_id)),
    ).fetchone()
    return dict(row) if row else None


def session_touch(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET last_activity_ts=? WHERE session_id=?", (_utc_now_ts(), session_id))
    conn.commit()


def session_set_thread(conn: sqlite3.Connection, session_id: str, thread_id: int) -> None:
    conn.execute("UPDATE sessions SET thread_id=? WHERE session_id=?", (int(thread_id), session_id))
    conn.commit()


def session_by_thread(conn: sqlite3.Connection, forum_chat_id: int, thread_id: int) -> Optional[str]:
    row = session_get_by_thread(conn, forum_chat_id, thread_id)
    return row["session_id"] if row else None


def sessions_expired(conn: sqlite3.Connection, max_age_seconds: int, idle_seconds: int) -> List[Dict[str, Any]]:
    now = int(time.time())
    created_before = now - int(max_age_seconds)
    idle_before = now - int(idle_seconds)
    rows = conn.execute(
        """
        SELECT * FROM sessions
        WHERE created_ts < ?
           OR COALESCE(NULLIF(last_activity_ts, 0), created_ts) < ?
        ORDER BY created_ts ASC
        """,
        (created_before, idle_before),
    ).fetchall()
    return [dict(r) for r in rows]


def session_get_media_paths(conn: sqlite3.Connection, session_id: str) -> List[str]:
    out: List[str] = []
    seen = set()

    def add_path(path: str) -> None:
        path = path or ""
        if path and path not in seen:
            seen.add(path)
            out.append(path)

    rows = conn.execute("SELECT local_path, media_json FROM events WHERE session_id=?", (session_id,)).fetchall()
    for row in rows:
        add_path(row["local_path"])
        raw = row["media_json"] or ""
        if not raw:
            continue
        try:
            media = json.loads(raw)
        except Exception:
            continue
        if isinstance(media, list):
            for item in media:
                if isinstance(item, dict):
                    add_path(item.get("local_path") or "")

    rows = conn.execute("SELECT local_path FROM media_assets WHERE session_id=?", (session_id,)).fetchall()
    for row in rows:
        add_path(row["local_path"])
    return out


def session_get_or_create_access_token(conn: sqlite3.Connection, session_id: str) -> str:
    """返回此 session 的统一访问 token,不存在时创建并写库。

    当前仍复用旧字段名 stream_token,但语义已经扩展为 history/SSE/media
    共同使用的 session access token。
    """
    try:
        row = conn.execute(
            "SELECT stream_token FROM sessions WHERE session_id=? LIMIT 1",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    if not row:
        return ""
    existing = (row["stream_token"] or "").strip() if isinstance(row, sqlite3.Row) else ""
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    try:
        conn.execute(
            "UPDATE sessions SET stream_token=? WHERE session_id=? AND COALESCE(stream_token, '')=''",
            (token, session_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT stream_token FROM sessions WHERE session_id=? LIMIT 1",
            (session_id,),
        ).fetchone()
        return (row["stream_token"] or "").strip() if row else token
    except sqlite3.OperationalError:
        return ""


def session_verify_access_token(conn: sqlite3.Connection, session_id: str, token: str) -> bool:
    if not token:
        return False
    try:
        row = conn.execute(
            "SELECT stream_token FROM sessions WHERE session_id=? LIMIT 1",
            (session_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    if not row:
        return False
    stored = (row["stream_token"] or "").strip() if isinstance(row, sqlite3.Row) else ""
    if not stored:
        return False
    return hmac.compare_digest(stored, str(token))


def session_get_or_create_stream_token(conn: sqlite3.Connection, session_id: str) -> str:
    return session_get_or_create_access_token(conn, session_id)


def session_verify_stream_token(conn: sqlite3.Connection, session_id: str, token: str) -> bool:
    return session_verify_access_token(conn, session_id, token)


def session_delete(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
    conn.commit()
