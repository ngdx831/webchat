import contextlib
import uuid
from pathlib import Path

import db as dbm
from api.app import create_app


def _db_path():
    root = Path("data") / "test_dbs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"customer_waiting_{uuid.uuid4().hex}.db"


def _seed(db_path, *, enabled=1):
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        dbm.user_upsert_from_telegram(conn, 1001, "owner", "Owner", default_role=dbm.USER_ROLE_VIP)
        dbm.widget_add(conn, "demo", -100123456, "Demo Support", owner_user_id=1001)
        if not enabled:
            dbm.widget_set_enabled(conn, "demo", 0, "客服已下班，请留言。")


def _post_message(client, session_id):
    return client.post(
        "/api/msg/demo",
        json={
            "session_id": session_id,
            "visitor_id": "visitor-1",
            "text": "你好",
        },
    )


def test_first_online_message_returns_created_and_enabled(monkeypatch):
    db_path = _db_path()
    _seed(db_path, enabled=1)
    monkeypatch.setattr("api.db_helpers.DB_PATH", str(db_path))
    monkeypatch.setattr("api.routes.messages.ensure_thread", lambda *args, **kwargs: 123)
    monkeypatch.setattr("api.routes.messages.tg_send_message", lambda *args, **kwargs: None)

    resp = _post_message(create_app().test_client(), f"s-{uuid.uuid4().hex}")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["created"] is True
    assert body["enabled"] == 1


def test_first_offline_message_returns_created_and_disabled(monkeypatch):
    db_path = _db_path()
    _seed(db_path, enabled=0)
    monkeypatch.setattr("api.db_helpers.DB_PATH", str(db_path))
    monkeypatch.setattr("api.routes.messages.ensure_thread", lambda *args, **kwargs: 123)
    monkeypatch.setattr("api.routes.messages.tg_send_message", lambda *args, **kwargs: None)

    resp = _post_message(create_app().test_client(), f"s-{uuid.uuid4().hex}")
    body = resp.get_json()

    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["created"] is True
    assert body["enabled"] == 0
