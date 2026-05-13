import sqlite3
from typing import Any, Dict, List, Optional

from .connection import _utc_now_ts


def source_click_add(conn: sqlite3.Connection, key: str, source_code: str, channel: str, visitor_id: str) -> Optional[int]:
    source_code = (source_code or "").strip()
    visitor_id = (visitor_id or "").strip()
    if not source_code or not visitor_id:
        return None
    cur = conn.execute(
        "INSERT INTO source_clicks(key, source_code, channel, visitor_id, clicked_ts) VALUES(?,?,?,?,?)",
        (key, source_code, channel or "web", visitor_id, _utc_now_ts()),
    )
    conn.commit()
    return int(cur.lastrowid)


def source_click_latest(conn: sqlite3.Connection, key: str, channel: str, visitor_id: str) -> str:
    row = conn.execute(
        """
        SELECT source_code FROM source_clicks
        WHERE key=? AND channel=? AND visitor_id=?
        ORDER BY clicked_ts DESC, id DESC
        LIMIT 1
        """,
        (key, channel or "web", visitor_id),
    ).fetchone()
    return (row["source_code"] if row else "") or ""


def source_session_add(conn: sqlite3.Connection, key: str, source_code: str, channel: str, visitor_id: str, session_id: str) -> Optional[int]:
    source_code = (source_code or "").strip()
    visitor_id = (visitor_id or "").strip()
    if not source_code or not visitor_id:
        return None
    conn.execute(
        """
        INSERT OR IGNORE INTO source_sessions(key, source_code, channel, visitor_id, session_id, created_ts)
        VALUES(?,?,?,?,?,?)
        """,
        (key, source_code, channel or "web", visitor_id, session_id, _utc_now_ts()),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT id FROM source_sessions
        WHERE key=? AND source_code=? AND channel=? AND visitor_id=?
        LIMIT 1
        """,
        (key, source_code, channel or "web", visitor_id),
    ).fetchone()
    return int(row["id"]) if row else None


def stats_for_key(conn: sqlite3.Connection, key: str, source_code: str = "") -> List[Dict[str, Any]]:
    source_code = (source_code or "").strip()
    dims = set()
    args: List[Any] = [key]
    source_filter = ""
    if source_code:
        source_filter = " AND source_code=?"
        args.append(source_code)

    for table in ("source_clicks", "source_sessions", "customer_marks"):
        rows = conn.execute(
            f"SELECT DISTINCT key, source_code, COALESCE(channel, 'web') AS channel FROM {table} WHERE key=?{source_filter} AND source_code<>''",
            args,
        ).fetchall()
        for row in rows:
            dims.add((row["key"], row["source_code"], row["channel"]))

    out: List[Dict[str, Any]] = []
    for item_key, item_source, channel in sorted(dims, key=lambda x: (x[1], x[2])):
        clicks = conn.execute(
            """
            SELECT COUNT(DISTINCT visitor_id) AS n
            FROM source_clicks
            WHERE key=? AND source_code=? AND channel=?
            """,
            (item_key, item_source, channel),
        ).fetchone()["n"]
        sessions = conn.execute(
            """
            SELECT COUNT(DISTINCT visitor_id) AS n
            FROM source_sessions
            WHERE key=? AND source_code=? AND channel=?
            """,
            (item_key, item_source, channel),
        ).fetchone()["n"]
        valid = conn.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS n
            FROM customer_marks
            WHERE key=? AND source_code=? AND channel=? AND mark='valid'
            """,
            (item_key, item_source, channel),
        ).fetchone()["n"]
        deal = conn.execute(
            """
            SELECT COUNT(DISTINCT session_id) AS n
            FROM customer_marks
            WHERE key=? AND source_code=? AND channel=? AND mark='deal'
            """,
            (item_key, item_source, channel),
        ).fetchone()["n"]
        out.append({
            "key": item_key,
            "source_code": item_source,
            "channel": channel,
            "clicks": int(clicks or 0),
            "sessions": int(sessions or 0),
            "valid": int(valid or 0),
            "deal": int(deal or 0),
        })
    return out


def stats_delete(conn: sqlite3.Connection, key: str, source_code: str = "") -> int:
    source_code = (source_code or "").strip()
    deleted = 0
    if source_code:
        params = (key, source_code)
        clauses = "key=? AND source_code=?"
        session_clause = "key=? AND source_code=?"
    else:
        params = (key,)
        clauses = "key=?"
        session_clause = "key=?"

    for table in ("source_clicks", "source_sessions", "customer_marks"):
        cur = conn.execute(f"DELETE FROM {table} WHERE {clauses}", params)
        deleted += max(cur.rowcount, 0)

    conn.execute(
        f"""
        UPDATE sessions
        SET source_code='', customer_status='none', marked_by='', marked_ts=0
        WHERE {session_clause}
        """,
        params,
    )
    conn.commit()
    return deleted
