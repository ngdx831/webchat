import sqlite3

from .connection import _utc_now_iso
from .sessions import session_get


def customer_mark_set(conn: sqlite3.Connection, session_id: str, mark: str, marked_by: str = "") -> bool:
    mark = (mark or "").strip().lower()
    if mark not in {"valid", "deal"}:
        raise ValueError("BAD_MARK")
    session = session_get(conn, session_id)
    if not session:
        return False
    now = _utc_now_iso()
    conn.execute("DELETE FROM customer_marks WHERE session_id=? AND mark=?", (session_id, mark))
    conn.execute(
        """
        INSERT INTO customer_marks(session_id, key, source_code, channel, mark, marked_by, marked_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            session_id,
            session["key"],
            session.get("source_code") or "",
            session.get("channel") or "web",
            mark,
            marked_by or "",
            now,
        ),
    )
    if mark == "deal":
        status = "deal"
    else:
        current = session.get("customer_status") or "none"
        status = "deal" if current == "deal" else "valid"
    conn.execute(
        "UPDATE sessions SET customer_status=?, marked_by=?, marked_at=? WHERE session_id=?",
        (status, marked_by or "", now, session_id),
    )
    conn.commit()
    return True
