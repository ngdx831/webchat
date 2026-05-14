import contextlib
import uuid
from pathlib import Path

import db as dbm
from api.app import create_app


def make_db_path():
    root = Path("data") / "test_dbs"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"widget_embed_{uuid.uuid4().hex}.db"


def seed_widget(db_path, key="demo"):
    with contextlib.closing(dbm.get_conn(str(db_path))) as conn:
        dbm.init_db(conn)
        dbm.user_upsert_from_telegram(
            conn,
            1001,
            "owner",
            "Owner",
            default_role=dbm.USER_ROLE_VIP,
        )
        dbm.widget_add(
            conn,
            key,
            -100123456,
            "Demo Support",
            owner_user_id=1001,
        )


def test_widget_address_can_render_chat_page_without_frame_blocks(monkeypatch):
    db_path = make_db_path()
    seed_widget(db_path)
    monkeypatch.setattr("api.db_helpers.DB_PATH", str(db_path))

    app = create_app()
    resp = app.test_client().get("/widget/demo?src=abc", headers={"Accept": "text/html"})

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert "X-Frame-Options" not in resp.headers
    assert "frame-ancestors" not in resp.get_data(as_text=True)


def test_widget_address_still_returns_config_for_frontend_fetch(monkeypatch):
    db_path = make_db_path()
    seed_widget(db_path)
    monkeypatch.setattr("api.db_helpers.DB_PATH", str(db_path))

    app = create_app()
    resp = app.test_client().get(
        "/widget/demo?visitor_id=visitor-1&src=abc",
        headers={"Accept": "application/json"},
    )

    assert resp.status_code == 200
    assert resp.mimetype == "application/json"
    assert resp.get_json()["key"] == "demo"
