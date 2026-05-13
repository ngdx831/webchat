import sqlite3
from typing import Any, Dict, List

from .connection import _utc_now_ts


def ensure_system_event(conn: sqlite3.Connection, session_id: str, text: str, marker: str = "system") -> bool:
    text = text or ""
    marker = marker or "system"
    if not text:
        return False
    row = conn.execute(
        "SELECT 1 FROM events WHERE session_id=? AND role='system' AND from_name=? LIMIT 1",
        (session_id, marker),
    ).fetchone()
    if row:
        return False
    event_add(conn, session_id, role="system", kind="text", text=text, from_name=marker, touch_session=False)
    return True


def event_add(
    conn: sqlite3.Connection,
    session_id: str,
    role: str,
    kind: str = "text",
    text: str = "",
    caption: str = "",
    file_id: str = "",
    file_name: str = "",
    from_name: str = "",
    local_path: str = "",
    media_json: str = "",
    touch_session: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO events(session_id, role, kind, text, caption, file_id, file_name, from_name, local_path, media_json, created_ts)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session_id,
            role,
            kind or "text",
            text or "",
            caption or "",
            file_id or "",
            file_name or "",
            from_name or "",
            local_path or "",
            media_json or "",
            _utc_now_ts(),
        ),
    )
    if touch_session:
        conn.execute("UPDATE sessions SET last_activity_ts=? WHERE session_id=?", (_utc_now_ts(), session_id))
    conn.commit()
    return int(cur.lastrowid)


def events_since(conn: sqlite3.Connection, session_id: str, since_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE session_id=? AND id>? ORDER BY id ASC LIMIT ?",
        (session_id, int(since_id), int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def events_list(conn: sqlite3.Connection, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, int(limit)),
    ).fetchall()
    out = [dict(r) for r in rows]
    out.reverse()
    return out
