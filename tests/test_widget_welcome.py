import contextlib
import uuid
from pathlib import Path

import db as dbm
from api.app import create_app


def _db_path():
    root = Path("data") / "test_dbs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"widget_welcome_{uuid.uuid4().hex}.db"


def _seed(db_path, *, welcome_text="您好，请稍候。", offline_msg="下班了请留言。", enabled=1):
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        dbm.user_upsert_from_telegram(conn, 1001, "owner", "Owner", default_role=dbm.USER_ROLE_VIP)
        dbm.widget_add(conn, "demo", -100123456, "Demo", owner_user_id=1001)
        dbm.widget_set_welcome_text(conn, "demo", welcome_text)
        if not enabled:
            dbm.widget_set_enabled(conn, "demo", 0, offline_msg)
        else:
            dbm.widget_set_offline_msg(conn, "demo", offline_msg)


def test_widget_api_returns_welcome_text(monkeypatch):
    db_path = _db_path()
    _seed(db_path)
    monkeypatch.setattr("api.db_helpers.DB_PATH", str(db_path))

    resp = create_app().test_client().get(
        "/widget/demo?visitor_id=v1",
        headers={"Accept": "application/json"},
    )
    body = resp.get_json()
    assert body["ok"] is True
    assert body["welcome_text"] == "您好，请稍候。"
    assert body["offline_msg"] == "下班了请留言。"
    assert body["enabled"] == 1


def test_widget_api_offline_still_returns_welcome_and_offline(monkeypatch):
    db_path = _db_path()
    _seed(db_path, enabled=0)
    monkeypatch.setattr("api.db_helpers.DB_PATH", str(db_path))

    body = create_app().test_client().get(
        "/widget/demo?visitor_id=v1",
        headers={"Accept": "application/json"},
    ).get_json()
    assert body["enabled"] == 0
    assert body["welcome_text"] == "您好，请稍候。"
    assert body["offline_msg"] == "下班了请留言。"
