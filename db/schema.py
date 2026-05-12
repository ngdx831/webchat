import sqlite3
from datetime import timedelta

from .connection import _utc_now, _add_column


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
        "stream_token TEXT DEFAULT ''",
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
