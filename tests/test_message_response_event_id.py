import os
import sqlite3

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import db as dbm
from api.app import create_app
import api.db_helpers as db_helpers
import api.rate_limit as rate_limit
import api.routes.messages as messages_route


def _init_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    dbm.init_db(conn)
    owner = dbm.user_upsert_from_telegram(
        conn,
        1002,
        "owner2",
        "Owner 2",
        default_role=dbm.USER_ROLE_VIP,
    )
    dbm.widget_add(
        conn,
        "vip2",
        -100123,
        "VIP 2",
        owner_user_id=int(owner["telegram_user_id"]),
    )
    conn.close()


def test_message_response_contains_saved_user_event_id(tmp_path, monkeypatch):
    db_path = tmp_path / "webchat.sqlite"
    _init_db(db_path)
    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_path))
    monkeypatch.setattr(messages_route, "ensure_thread", lambda *args, **kwargs: 777)
    monkeypatch.setattr(messages_route, "tg_send_message", lambda *args, **kwargs: None)
    rate_limit._rate_bucket.clear()

    client = create_app().test_client()

    resp = client.post(
        "/api/msg/vip2",
        json={
            "session_id": "s-event-id",
            "visitor_id": "visitor-1",
            "text": "hello",
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert isinstance(data["event_id"], int)
    assert data["event_id"] > 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    events = dbm.events_list(conn, "s-event-id")
    assert any(row["id"] == data["event_id"] and row["role"] == "user" for row in events)
    conn.close()
