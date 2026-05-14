"""会话过期清理：删 TG 话题 → 删 DB → 删媒体。"""
import contextlib
import uuid
from pathlib import Path

import db as dbm
from shared.session_cleanup import cleanup_expired_sessions


def _db_path():
    root = Path("data") / "test_dbs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"cleanup_{uuid.uuid4().hex}.db"


def _seed_session(conn, *, session_id, thread_id, created_offset=-86400 * 90):
    """创建一个已 90 天的会话，确保会被 cleanup 视为过期。"""
    import time

    dbm.user_upsert_from_telegram(conn, 1, "u", "U", default_role=dbm.USER_ROLE_VIP)
    dbm.widget_add(conn, "k1", -100123, "K1", owner_user_id=1)
    dbm.session_create_if_missing(conn, session_id, "k1", -100123)
    conn.execute(
        "UPDATE sessions SET thread_id=?, created_ts=?, last_activity_ts=? WHERE session_id=?",
        (thread_id, int(time.time()) + created_offset, int(time.time()) + created_offset, session_id),
    )
    conn.commit()


def test_cleanup_deletes_topic_then_session(tmp_path):
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed_session(conn, session_id="s1", thread_id=42)

        calls = []

        def fake_delete_topic(chat_id, thread_id):
            calls.append((chat_id, thread_id))

        results = cleanup_expired_sessions(
            conn,
            str(tmp_path),
            delete_topic=fake_delete_topic,
            max_age_seconds=1,
            idle_seconds=1,
        )
        assert calls == [(-100123, 42)]
        assert len(results) == 1
        assert results[0].topic_deleted is True
        assert results[0].topic_error == ""
        # session 已被删除
        assert dbm.session_get(conn, "s1") is None


def test_cleanup_keeps_session_if_topic_delete_fails(tmp_path):
    """如果 TG 删除话题失败，DB 应当保留，等下一轮重试。"""
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed_session(conn, session_id="s2", thread_id=99)

        def boom(chat_id, thread_id):
            raise RuntimeError("forbidden")

        results = cleanup_expired_sessions(
            conn,
            str(tmp_path),
            delete_topic=boom,
            max_age_seconds=1,
            idle_seconds=1,
        )
        assert len(results) == 1
        assert results[0].topic_deleted is False
        assert "forbidden" in results[0].topic_error
        # session 仍然存在，下一轮可重试
        assert dbm.session_get(conn, "s2") is not None


def test_cleanup_without_thread_id_still_deletes_session(tmp_path):
    """没有 thread_id 的会话（例如客户机器人通道未触达话题）也应被清掉。"""
    db_path = _db_path()
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        _seed_session(conn, session_id="s3", thread_id=None)

        calls = []
        results = cleanup_expired_sessions(
            conn,
            str(tmp_path),
            delete_topic=lambda c, t: calls.append((c, t)),
            max_age_seconds=1,
            idle_seconds=1,
        )
        assert calls == []  # 没有话题，未调用
        assert len(results) == 1
        assert dbm.session_get(conn, "s3") is None
