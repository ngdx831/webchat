import os
import sqlite3

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import db as dbm
import db.connection as db_connection
from api.app import create_app
import api.db_helpers as db_helpers


class TrackingConnection(sqlite3.Connection):
    closed = False

    def close(self):
        self.closed = True
        return super().close()


def _init_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    dbm.init_db(conn)
    owner = dbm.user_upsert_from_telegram(
        conn,
        3001,
        "tracked-owner",
        "Tracked Owner",
        default_role=dbm.USER_ROLE_VIP,
    )
    dbm.widget_add(conn, "tracked", 12345, "Tracked Widget", owner_user_id=int(owner["telegram_user_id"]))
    conn.close()


def test_api_request_closes_sqlite_connection_after_request(tmp_path, monkeypatch):
    db_path = tmp_path / "webchat.sqlite"
    _init_db(db_path)
    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_path))

    original_connect = db_connection.sqlite3.connect
    opened = []

    def tracking_connect(*args, **kwargs):
        kwargs["factory"] = TrackingConnection
        conn = original_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db_connection.sqlite3, "connect", tracking_connect)

    resp = create_app().test_client().get("/widget/tracked")

    assert resp.status_code == 200
    assert opened
    assert all(conn.closed for conn in opened)
