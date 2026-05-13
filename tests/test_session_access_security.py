import json
import os
import sqlite3
import unittest
from unittest.mock import patch


os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import db as dbm
from api.app import create_app


class _FakeTelegramResponse:
    headers = {"Content-Type": "image/jpeg"}

    def iter_content(self, chunk_size):
        yield b"telegram-bytes"

    def raise_for_status(self):
        return None


class SessionAccessSecurityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        dbm.init_db(self.conn)
        dbm.widget_add(self.conn, "k1", 100, "Widget")
        dbm.widget_add(self.conn, "k2", 200, "Other")
        dbm.session_create_if_missing(self.conn, "s1", "k1", 100)
        dbm.session_create_if_missing(self.conn, "s2", "k2", 200)

    def tearDown(self):
        self.conn.close()

    def test_session_access_token_is_required_and_exact(self):
        token = dbm.session_get_or_create_access_token(self.conn, "s1")

        self.assertTrue(token)
        self.assertTrue(dbm.session_verify_access_token(self.conn, "s1", token))
        self.assertFalse(dbm.session_verify_access_token(self.conn, "s1", ""))
        self.assertFalse(dbm.session_verify_access_token(self.conn, "s1", "wrong-token"))
        self.assertFalse(dbm.session_verify_access_token(self.conn, "missing", token))

    def test_empty_legacy_session_token_is_not_a_wildcard(self):
        self.conn.execute("UPDATE sessions SET stream_token='' WHERE session_id='s1'")
        self.conn.commit()

        self.assertFalse(dbm.session_verify_access_token(self.conn, "s1", "any-token"))

    def test_media_owner_session_can_be_resolved_from_all_media_sources(self):
        dbm.media_asset_upsert(self.conn, "s1", "asset-file", "photo", "media/a.jpg")
        dbm.event_add(self.conn, "s2", role="agent", kind="photo", file_id="event-file")
        dbm.event_add(
            self.conn,
            "s1",
            role="agent",
            kind="note",
            media_json=json.dumps([{"file_id": "note-file", "local_path": "media/n.jpg"}]),
        )

        self.assertEqual("s1", dbm.media_owner_session_id(self.conn, "asset-file"))
        self.assertEqual("s2", dbm.media_owner_session_id(self.conn, "event-file"))
        self.assertEqual("s1", dbm.media_owner_session_id(self.conn, "note-file"))
        self.assertIsNone(dbm.media_owner_session_id(self.conn, "unknown-file"))

    def test_media_fallback_never_redirects_to_telegram_file_api(self):
        token = dbm.session_get_or_create_access_token(self.conn, "s1")
        dbm.event_add(self.conn, "s1", role="agent", kind="photo", file_id="remote-file")

        client = create_app().test_client()
        with (
            patch("api.routes.media.get_conn", return_value=self.conn),
            patch(
                "api.routes.media.tg_get_file_url",
                return_value="https://api.telegram.org/file/bot123456:SECRET/photos/a.jpg",
            ),
            patch("requests.get", return_value=_FakeTelegramResponse()),
        ):
            resp = client.get(f"/api/media/remote-file?session_id=s1&token={token}")

        self.assertNotIn("api.telegram.org", resp.headers.get("Location", ""))
        self.assertNotEqual(302, resp.status_code)


if __name__ == "__main__":
    unittest.main()
