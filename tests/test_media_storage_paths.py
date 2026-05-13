import asyncio
import os
import sqlite3

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import config
import db as dbm
from api.app import create_app
import api.db_helpers as db_helpers
import api.routes.media as media_route
import bot.media as bot_media


def _init_media_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    dbm.init_db(conn)
    owner = dbm.user_upsert_from_telegram(
        conn,
        2001,
        "media-owner",
        "Media Owner",
        default_role=dbm.USER_ROLE_VIP,
    )
    dbm.widget_add(conn, "mediakey", -100333, "Media Widget", owner_user_id=int(owner["telegram_user_id"]))
    dbm.session_create_if_missing(conn, "media-session", "mediakey", -100333)
    token = dbm.session_get_or_create_access_token(conn, "media-session")
    conn.close()
    return token


def test_default_media_root_is_project_media_directory():
    assert os.path.abspath(config.WEBCHAT_MEDIA_ROOT) == os.path.join(config.BASE_DIR, "media")


def test_saved_media_uses_project_media_relative_path(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    monkeypatch.setattr(bot_media, "WEBCHAT_MEDIA_ROOT", str(media_root))
    monkeypatch.setattr(bot_media, "tg_get_file_path", lambda file_id: "photos/source.jpg")

    def fake_download(_url, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"image-bytes")

    monkeypatch.setattr(bot_media, "download_file_to", fake_download)

    rel_path = asyncio.run(bot_media.save_webchat_media("telegram-file", "unique-file"))

    assert rel_path.startswith("media/")
    assert not rel_path.startswith("webchat/")
    saved = media_root / rel_path.split("/", 1)[1]
    assert saved.read_bytes() == b"image-bytes"


def test_media_route_serves_project_media_file(tmp_path, monkeypatch):
    db_path = tmp_path / "webchat.sqlite"
    token = _init_media_db(db_path)
    media_root = tmp_path / "media"
    file_path = media_root / "202605" / "file.jpg"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"local-media")

    monkeypatch.setattr(db_helpers, "DB_PATH", str(db_path))
    monkeypatch.setattr(media_route, "PUBLIC_ROOT", str(tmp_path))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    dbm.media_asset_upsert(conn, "media-session", "file-id", "photo", "media/202605/file.jpg")
    conn.close()

    resp = create_app().test_client().get(f"/api/media/file-id?session_id=media-session&token={token}")

    assert resp.status_code == 200
    assert resp.data == b"local-media"
