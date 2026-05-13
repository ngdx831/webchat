import os
import sqlite3

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import db as dbm
from api.app import create_app
import api.db_helpers as db_helpers


def _init_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    dbm.init_db(conn)
    owner = dbm.user_upsert_from_telegram(
        conn,
        1001,
        "owner",
        "Owner",
        default_role=dbm.USER_ROLE_VIP,
    )
    dbm.widget_add(
        conn,
        "vip1",
        12345,
        "VIP Support",
        owner_user_id=int(owner["telegram_user_id"]),
    )
    conn.close()


def test_chat_page_serves_required_static_assets(tmp_path, monkeypatch):
    db_path = tmp_path / "webchat.sqlite"
    _init_db(db_path)
    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_path))

    client = create_app().test_client()

    assert client.get("/vip1").status_code == 200

    css = client.get("/chat.css")
    assert css.status_code == 200
    assert "text/css" in css.headers.get("Content-Type", "")
    assert b".msg" in css.data

    js = client.get("/chat.js")
    assert js.status_code == 200
    assert "javascript" in js.headers.get("Content-Type", "")
    assert b"EventSource" in js.data
