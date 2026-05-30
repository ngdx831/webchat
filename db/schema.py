import sqlite3
import time

from .connection import _add_column, _utc_now_ts


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users(
        telegram_user_id INTEGER PRIMARY KEY,
        username TEXT DEFAULT '',
        display_name TEXT DEFAULT '',
        role TEXT NOT NULL DEFAULT 'normal',
        enabled INTEGER NOT NULL DEFAULT 1,
        vip_until TEXT DEFAULT '',
        created_ts INTEGER NOT NULL,
        updated_ts INTEGER NOT NULL
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
        offline_ts INTEGER DEFAULT 0,
        welcome_text TEXT DEFAULT '',
        created_ts INTEGER NOT NULL DEFAULT 0,
        updated_ts INTEGER NOT NULL DEFAULT 0
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sessions(
        session_id TEXT PRIMARY KEY,
        key TEXT NOT NULL REFERENCES widgets(key) ON DELETE CASCADE,
        forum_chat_id INTEGER NOT NULL,
        thread_id INTEGER,
        channel TEXT NOT NULL DEFAULT 'web',
        source_code TEXT DEFAULT '',
        visitor_id TEXT DEFAULT '',
        customer_chat_id INTEGER,
        bot_binding_id INTEGER,
        customer_status TEXT NOT NULL DEFAULT 'none',
        marked_by TEXT DEFAULT '',
        marked_ts INTEGER DEFAULT 0,
        stream_token TEXT DEFAULT '',
        created_ts INTEGER NOT NULL,
        last_activity_ts INTEGER NOT NULL
    )
    """)
    _add_column(conn, "sessions", "stream_token TEXT DEFAULT ''")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'text',
        text TEXT DEFAULT '',
        caption TEXT DEFAULT '',
        file_id TEXT DEFAULT '',
        file_name TEXT DEFAULT '',
        from_name TEXT DEFAULT '',
        local_path TEXT DEFAULT '',
        media_json TEXT DEFAULT '',
        created_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS bot_bindings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL REFERENCES widgets(key) ON DELETE CASCADE,
        owner_user_id INTEGER,
        bot_token TEXT NOT NULL UNIQUE,
        bot_token_hash TEXT NOT NULL UNIQUE,
        bot_username TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_ts INTEGER NOT NULL,
        updated_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_actions(
        telegram_user_id INTEGER PRIMARY KEY,
        action TEXT NOT NULL,
        key TEXT DEFAULT '',
        payload TEXT DEFAULT '',
        expires_ts INTEGER NOT NULL,
        created_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT '',
        updated_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS quick_replies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL REFERENCES widgets(key) ON DELETE CASCADE,
        title TEXT NOT NULL,
        answer TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_ts INTEGER NOT NULL,
        updated_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS source_clicks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        source_code TEXT NOT NULL,
        channel TEXT NOT NULL,
        visitor_id TEXT NOT NULL,
        clicked_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS source_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        source_code TEXT NOT NULL,
        channel TEXT NOT NULL,
        visitor_id TEXT NOT NULL,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        created_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS customer_marks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        source_code TEXT DEFAULT '',
        channel TEXT NOT NULL DEFAULT 'web',
        mark TEXT NOT NULL,
        marked_by TEXT DEFAULT '',
        marked_ts INTEGER NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS media_assets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        file_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        local_path TEXT NOT NULL,
        created_ts INTEGER NOT NULL,
        expires_ts INTEGER DEFAULT 0,
        deleted_ts INTEGER DEFAULT 0
    )
    """)

    _add_column(conn, "widgets", "work_schedule TEXT DEFAULT ''")
    _add_column(conn, "widgets", "work_schedule_active INTEGER DEFAULT 1")

    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_users_role_enabled ON users(role, enabled)",
        "CREATE INDEX IF NOT EXISTS idx_widgets_owner ON widgets(owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_bot_bindings_owner ON bot_bindings(owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_pending_actions_expires ON pending_actions(expires_ts)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_thread ON sessions(forum_chat_id, thread_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions(bot_binding_id, customer_chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_activity ON sessions(last_activity_ts)",
        "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_ts)",
        "CREATE INDEX IF NOT EXISTS idx_clicks_full ON source_clicks(key, source_code, channel, visitor_id)",
        "CREATE INDEX IF NOT EXISTS idx_clicks_time ON source_clicks(clicked_ts)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_source_sessions_unique ON source_sessions(key, source_code, channel, visitor_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_marks_unique ON customer_marks(session_id, mark)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_media_file ON media_assets(file_id)",
    ]:
        conn.execute(sql)

    conn.commit()


def cleanup_old(conn: sqlite3.Connection, event_ttl_seconds: int = 86400, session_ttl_seconds: int = 86400) -> None:
    from .sessions import session_delete, sessions_expired

    try:
        idle_seconds = int(session_ttl_seconds)
        for session in sessions_expired(conn, int(session_ttl_seconds), idle_seconds):
            session_delete(conn, session["session_id"])
    except Exception:
        pass

    try:
        click_before = int(time.time()) - 90 * 24 * 60 * 60
        conn.execute("DELETE FROM source_clicks WHERE clicked_ts < ?", (click_before,))
        conn.commit()
    except Exception:
        pass
