import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


USER_ROLE_NORMAL = "normal"
USER_ROLE_VIP = "vip"
USER_ROLE_ADMIN = "admin"
USER_ROLES = {USER_ROLE_NORMAL, USER_ROLE_VIP, USER_ROLE_ADMIN}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _iso_after(seconds: int) -> str:
    return (_utc_now() + timedelta(seconds=int(seconds))).isoformat()


def get_conn(path: str) -> sqlite3.Connection:
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
    # Keep this small compatibility shim so existing local databases can still boot.
    if _table_has_column(conn, "widgets", "k"):
        return "k"
    return "key"


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
    except Exception:
        pass


def _validate_user_role(role: str) -> str:
    role = role or USER_ROLE_NORMAL
    if role not in USER_ROLES:
        raise ValueError("INVALID_USER_ROLE")
    return role


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        telegram_user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        display_name TEXT DEFAULT '',
        role TEXT NOT NULL DEFAULT 'normal',
        enabled INTEGER NOT NULL DEFAULT 1,
        vip_until TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS widgets(
        key TEXT PRIMARY KEY,
        owner_user_id INTEGER,
        forum_chat_id INTEGER NOT NULL,
        display_name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        offline_msg TEXT DEFAULT '',
        offline_at TEXT DEFAULT '',
        welcome_text TEXT DEFAULT ''
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sessions(
        session_id TEXT PRIMARY KEY,
        key TEXT NOT NULL,
        forum_chat_id INTEGER NOT NULL,
        thread_id INTEGER,
        channel TEXT NOT NULL DEFAULT 'web',
        source_code TEXT DEFAULT '',
        visitor_id TEXT DEFAULT '',
        customer_chat_id INTEGER,
        bot_binding_id INTEGER,
        customer_status TEXT NOT NULL DEFAULT 'none',
        marked_by TEXT DEFAULT '',
        marked_at TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        last_activity_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'text',
        text TEXT DEFAULT '',
        caption TEXT DEFAULT '',
        file_id TEXT DEFAULT '',
        file_name TEXT DEFAULT '',
        from_name TEXT DEFAULT '',
        local_path TEXT DEFAULT '',
        media_json TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS bot_bindings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        owner_user_id INTEGER,
        bot_token TEXT NOT NULL UNIQUE,
        bot_username TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_actions(
        telegram_user_id INTEGER PRIMARY KEY,
        action TEXT NOT NULL,
        key TEXT DEFAULT '',
        payload TEXT DEFAULT '',
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT '',
        updated_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS quick_replies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        title TEXT NOT NULL,
        answer TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS source_clicks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        source_code TEXT NOT NULL,
        channel TEXT NOT NULL,
        visitor_id TEXT NOT NULL,
        clicked_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS source_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        source_code TEXT NOT NULL,
        channel TEXT NOT NULL,
        visitor_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS customer_marks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        key TEXT NOT NULL,
        source_code TEXT DEFAULT '',
        channel TEXT NOT NULL DEFAULT 'web',
        mark TEXT NOT NULL,
        marked_by TEXT DEFAULT '',
        marked_at TEXT NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS media_assets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        file_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        local_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT DEFAULT '',
        deleted_at TEXT DEFAULT ''
    )
    """)

    for definition in [
        "thread_id INTEGER",
        "last_activity_at TEXT DEFAULT ''",
        "channel TEXT NOT NULL DEFAULT 'web'",
        "source_code TEXT DEFAULT ''",
        "visitor_id TEXT DEFAULT ''",
        "customer_chat_id INTEGER",
        "bot_binding_id INTEGER",
        "customer_status TEXT NOT NULL DEFAULT 'none'",
        "marked_by TEXT DEFAULT ''",
        "marked_at TEXT DEFAULT ''",
    ]:
        _add_column(conn, "sessions", definition)

    for definition in [
        "kind TEXT NOT NULL DEFAULT 'text'",
        "caption TEXT DEFAULT ''",
        "file_id TEXT DEFAULT ''",
        "file_name TEXT DEFAULT ''",
        "from_name TEXT DEFAULT ''",
        "local_path TEXT DEFAULT ''",
        "media_json TEXT DEFAULT ''",
    ]:
        _add_column(conn, "events", definition)

    for definition in [
        "owner_user_id INTEGER",
        "enabled INTEGER NOT NULL DEFAULT 1",
        "offline_msg TEXT DEFAULT ''",
        "offline_at TEXT DEFAULT ''",
        "welcome_text TEXT DEFAULT ''",
    ]:
        _add_column(conn, "widgets", definition)

    _add_column(conn, "bot_bindings", "owner_user_id INTEGER")
    _add_column(conn, "customer_marks", "channel TEXT NOT NULL DEFAULT 'web'")

    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_users_role_enabled ON users(role, enabled)",
        "CREATE INDEX IF NOT EXISTS idx_widgets_owner ON widgets(owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_bot_bindings_owner ON bot_bindings(owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pending_actions_expires ON pending_actions(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_thread ON sessions(forum_chat_id, thread_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(bot_binding_id, customer_chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_clicks_key_source ON source_clicks(key, source_code, channel)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_source_sessions_unique ON source_sessions(key, source_code, channel, visitor_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_marks_unique ON customer_marks(session_id, mark)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_media_file ON media_assets(file_id)",
    ]:
        try:
            conn.execute(sql)
        except Exception:
            pass

    try:
        conn.execute("""
        UPDATE sessions
        SET last_activity_at=created_at
        WHERE last_activity_at IS NULL OR last_activity_at=''
        """)
    except Exception:
        pass

    conn.commit()


def cleanup_old(conn: sqlite3.Connection, event_ttl_seconds: int = 86400, session_ttl_seconds: int = 86400) -> None:
    try:
        ev_before = (_utc_now() - timedelta(seconds=event_ttl_seconds)).isoformat()
        conn.execute("""
            DELETE FROM events
            WHERE created_at < ?
              AND session_id NOT IN (SELECT session_id FROM sessions)
        """, (ev_before,))
        conn.commit()
    except Exception:
        pass


def user_get(conn: sqlite3.Connection, telegram_user_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_user_id=? LIMIT 1",
        (int(telegram_user_id),),
    ).fetchone()
    if not row:
        return None
    out = dict(row)
    out["enabled"] = int(out.get("enabled") or 0)
    return out


def user_upsert_from_telegram(
    conn: sqlite3.Connection,
    telegram_user_id: int,
    username: str,
    display_name: str,
    default_role: str = USER_ROLE_NORMAL,
) -> Dict[str, Any]:
    default_role = _validate_user_role(default_role)
    telegram_user_id = int(telegram_user_id)
    now = _utc_now_iso()
    existing = user_get(conn, telegram_user_id)
    role = default_role
    if existing:
        role = USER_ROLE_ADMIN if default_role == USER_ROLE_ADMIN else existing["role"]

    conn.execute(
        """
        INSERT INTO users(
            telegram_user_id, username, display_name, role, enabled,
            vip_until, created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            username=excluded.username,
            display_name=excluded.display_name,
            role=excluded.role,
            updated_at=excluded.updated_at
        """,
        (
            telegram_user_id,
            username or "",
            display_name or "",
            role,
            1,
            existing["vip_until"] if existing else "",
            existing["created_at"] if existing else now,
            now,
        ),
    )
    conn.commit()
    user = user_get(conn, telegram_user_id)
    if user is None:
        raise RuntimeError("USER_UPSERT_FAILED")
    return user


def user_set_role(conn: sqlite3.Connection, telegram_user_id: int, role: str) -> Optional[Dict[str, Any]]:
    role = _validate_user_role(role)
    conn.execute(
        "UPDATE users SET role=?, updated_at=? WHERE telegram_user_id=?",
        (role, _utc_now_iso(), int(telegram_user_id)),
    )
    conn.commit()
    return user_get(conn, telegram_user_id)


def user_set_enabled(conn: sqlite3.Connection, telegram_user_id: int, enabled: bool) -> Optional[Dict[str, Any]]:
    conn.execute(
        "UPDATE users SET enabled=?, updated_at=? WHERE telegram_user_id=?",
        (1 if enabled else 0, _utc_now_iso(), int(telegram_user_id)),
    )
    conn.commit()
    return user_get(conn, telegram_user_id)


def user_list(
    conn: sqlite3.Connection,
    role: str = "",
    enabled_only: bool = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    where = []
    args: List[Any] = []
    if role:
        where.append("role=?")
        args.append(_validate_user_role(role))
    if enabled_only:
        where.append("enabled=1")
    sql = "SELECT * FROM users"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY telegram_user_id ASC LIMIT ?"
    args.append(int(limit))
    out = [dict(r) for r in conn.execute(sql, args).fetchall()]
    for row in out:
        row["enabled"] = int(row.get("enabled") or 0)
    return out


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


def setting_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key=? LIMIT 1", (key,)).fetchone()
    if not row:
        return default
    return row["value"] or ""


def setting_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value, updated_at)
        VALUES(?,?,?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
        """,
        (key, value or "", _utc_now_iso()),
    )
    conn.commit()


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
        now_ts = int(_utc_now().timestamp())
        conn.execute(
            f"INSERT INTO widgets({keycol}, owner_user_id, display_name, forum_chat_id, created_ts, updated_ts) VALUES(?,?,?,?,?,?) "
            f"ON CONFLICT({keycol}) DO UPDATE SET owner_user_id=excluded.owner_user_id, display_name=excluded.display_name, forum_chat_id=excluded.forum_chat_id, updated_ts=excluded.updated_ts",
            (key, owner_user_id, display_name, int(forum_chat_id), now_ts, now_ts),
        )
    except Exception:
        conn.execute(
            f"INSERT INTO widgets({keycol}, owner_user_id, forum_chat_id, display_name, enabled, offline_msg, offline_at) VALUES(?,?,?,?,?,?,?) "
            f"ON CONFLICT({keycol}) DO UPDATE SET owner_user_id=excluded.owner_user_id, forum_chat_id=excluded.forum_chat_id, display_name=excluded.display_name",
            (key, owner_user_id, int(forum_chat_id), display_name, 1, "", ""),
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
    offat_expr = "offline_at" if _table_has_column(conn, "widgets", "offline_at") else "''"
    welcome_expr = "welcome_text" if _table_has_column(conn, "widgets", "welcome_text") else "''"
    cur = conn.execute(
        f"""
        SELECT {keycol} as key, forum_chat_id, display_name,
               {owner_expr} as owner_user_id,
               {enabled_expr} as enabled,
               {offmsg_expr} as offline_msg,
               {offat_expr} as offline_at,
               {welcome_expr} as welcome_text
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
    return out


def widget_list(conn: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    keycol = _widgets_key_col(conn)
    owner_expr = "owner_user_id" if _table_has_column(conn, "widgets", "owner_user_id") else "NULL"
    enabled_expr = "enabled" if _table_has_column(conn, "widgets", "enabled") else "1"
    offmsg_expr = "offline_msg" if _table_has_column(conn, "widgets", "offline_msg") else "''"
    offat_expr = "offline_at" if _table_has_column(conn, "widgets", "offline_at") else "''"
    welcome_expr = "welcome_text" if _table_has_column(conn, "widgets", "welcome_text") else "''"
    rows = conn.execute(
        f"""
        SELECT {keycol} as key, forum_chat_id, display_name,
               {owner_expr} as owner_user_id,
               {enabled_expr} as enabled,
               {offmsg_expr} as offline_msg,
               {offat_expr} as offline_at,
               {welcome_expr} as welcome_text
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
    return out


def widget_list_by_owner(conn: sqlite3.Connection, owner_user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    keycol = _widgets_key_col(conn)
    rows = conn.execute(
        f"""
        SELECT {keycol} as key, owner_user_id, forum_chat_id, display_name,
               enabled, offline_msg, offline_at, welcome_text
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
    now = _utc_now().isoformat(timespec="seconds")
    if enabled == 0:
        cur = conn.execute(
            f"UPDATE widgets SET enabled=0, offline_msg=?, offline_at=? WHERE {keycol}=?",
            (offline_msg or "", now, key),
        )
    else:
        cur = conn.execute(
            f"UPDATE widgets SET enabled=1, offline_at='' WHERE {keycol}=?",
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
    now = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO sessions(
            session_id, key, forum_chat_id, thread_id, channel, source_code,
            visitor_id, customer_chat_id, bot_binding_id, customer_status,
            marked_by, marked_at, created_at, last_activity_at
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
            "",
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
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (int(bot_binding_id), int(customer_chat_id)),
    ).fetchone()
    return dict(row) if row else None


def session_touch(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("UPDATE sessions SET last_activity_at=? WHERE session_id=?", (_utc_now_iso(), session_id))
    conn.commit()


def session_set_thread(conn: sqlite3.Connection, session_id: str, thread_id: int) -> None:
    conn.execute("UPDATE sessions SET thread_id=? WHERE session_id=?", (int(thread_id), session_id))
    conn.commit()


def session_by_thread(conn: sqlite3.Connection, forum_chat_id: int, thread_id: int) -> Optional[str]:
    row = session_get_by_thread(conn, forum_chat_id, thread_id)
    return row["session_id"] if row else None


def sessions_expired(conn: sqlite3.Connection, max_age_seconds: int, idle_seconds: int) -> List[Dict[str, Any]]:
    now = _utc_now()
    created_before = (now - timedelta(seconds=int(max_age_seconds))).isoformat()
    idle_before = (now - timedelta(seconds=int(idle_seconds))).isoformat()
    rows = conn.execute(
        """
        SELECT * FROM sessions
        WHERE created_at < ?
           OR COALESCE(NULLIF(last_activity_at, ''), created_at) < ?
        ORDER BY created_at ASC
        """,
        (created_before, idle_before),
    ).fetchall()
    return [dict(r) for r in rows]


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
        INSERT INTO events(session_id, role, kind, text, caption, file_id, file_name, from_name, local_path, media_json, created_at)
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
            _utc_now_iso(),
        ),
    )
    if touch_session:
        conn.execute("UPDATE sessions SET last_activity_at=? WHERE session_id=?", (_utc_now_iso(), session_id))
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


def session_delete(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM media_assets WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
    conn.commit()


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


def quick_reply_add(conn: sqlite3.Connection, key: str, title: str, answer: str, sort_order: int = 0, enabled: int = 1) -> int:
    now = _utc_now_iso()
    cur = conn.execute(
        """
        INSERT INTO quick_replies(key, title, answer, sort_order, enabled, created_at, updated_at)
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


def source_click_add(conn: sqlite3.Connection, key: str, source_code: str, channel: str, visitor_id: str) -> Optional[int]:
    source_code = (source_code or "").strip()
    visitor_id = (visitor_id or "").strip()
    if not source_code or not visitor_id:
        return None
    cur = conn.execute(
        "INSERT INTO source_clicks(key, source_code, channel, visitor_id, clicked_at) VALUES(?,?,?,?,?)",
        (key, source_code, channel or "web", visitor_id, _utc_now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def source_click_latest(conn: sqlite3.Connection, key: str, channel: str, visitor_id: str) -> str:
    row = conn.execute(
        """
        SELECT source_code FROM source_clicks
        WHERE key=? AND channel=? AND visitor_id=?
        ORDER BY clicked_at DESC, id DESC
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
        INSERT OR IGNORE INTO source_sessions(key, source_code, channel, visitor_id, session_id, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (key, source_code, channel or "web", visitor_id, session_id, _utc_now_iso()),
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
        SET source_code='', customer_status='none', marked_by='', marked_at=''
        WHERE {session_clause}
        """,
        params,
    )
    conn.commit()
    return deleted


def media_asset_upsert(
    conn: sqlite3.Connection,
    session_id: str,
    file_id: str,
    kind: str,
    local_path: str,
    ttl_seconds: int = 3 * 24 * 60 * 60,
) -> int:
    now = _utc_now_iso()
    expires_at = _iso_after(ttl_seconds)
    conn.execute(
        """
        INSERT INTO media_assets(session_id, file_id, kind, local_path, created_at, expires_at, deleted_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(file_id) DO UPDATE SET
            session_id=excluded.session_id,
            kind=excluded.kind,
            local_path=excluded.local_path,
            expires_at=excluded.expires_at
        """,
        (session_id, file_id, kind or "media", local_path or "", now, expires_at, ""),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM media_assets WHERE file_id=? LIMIT 1", (file_id,)).fetchone()
    return int(row["id"]) if row else 0


def media_asset_get_by_file_id(conn: sqlite3.Connection, file_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM media_assets WHERE file_id=? LIMIT 1", (file_id,)).fetchone()
    return dict(row) if row else None


def media_assets_expired(conn: sqlite3.Connection, media_ttl_seconds: int) -> List[Dict[str, Any]]:
    cutoff = (_utc_now() - timedelta(seconds=int(media_ttl_seconds))).isoformat()
    now = _utc_now_iso()
    rows = conn.execute(
        """
        SELECT * FROM media_assets
        WHERE COALESCE(deleted_at, '')=''
          AND (
            created_at < ?
            OR (COALESCE(expires_at, '')<>'' AND expires_at < ?)
          )
        ORDER BY created_at ASC
        """,
        (cutoff, now),
    ).fetchall()
    return [dict(r) for r in rows]


def media_asset_mark_deleted(conn: sqlite3.Connection, file_id: str) -> None:
    conn.execute("UPDATE media_assets SET deleted_at=? WHERE file_id=?", (_utc_now_iso(), file_id))
    conn.commit()
