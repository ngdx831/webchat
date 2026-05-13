import os
import sqlite3
import time
import unittest

os.environ.setdefault("WEBCHAT_TOKEN_KEY", "45_3WKFv7XuSizf8ugfEGwANpINcSQz08wQiLKvyxfE=")

import db as dbm
from config import MEDIA_TTL_SECONDS, SESSION_IDLE_TTL_SECONDS, SESSION_TTL_SECONDS


class DatabaseOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        dbm.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def _columns(self, table):
        return {row["name"]: row for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def test_schema_uses_epoch_columns_for_core_tables(self):
        sessions = self._columns("sessions")
        events = self._columns("events")
        media = self._columns("media_assets")

        self.assertEqual("INTEGER", sessions["created_ts"]["type"])
        self.assertEqual("INTEGER", sessions["last_activity_ts"]["type"])
        self.assertEqual("INTEGER", events["created_ts"]["type"])
        self.assertEqual("INTEGER", media["created_ts"]["type"])
        self.assertEqual("INTEGER", media["expires_ts"]["type"])
        self.assertNotIn("created_at", sessions)
        self.assertNotIn("created_at", events)

    def test_session_delete_cascades_to_child_tables(self):
        dbm.widget_add(self.conn, "k1", 100, "Widget")
        dbm.session_create_if_missing(self.conn, "s1", "k1", 100, source_code="ad", visitor_id="v1")
        dbm.event_add(self.conn, "s1", "customer", text="hello")
        dbm.media_asset_upsert(self.conn, "s1", "file-1", "photo", "media/a.jpg")
        dbm.customer_mark_set(self.conn, "s1", "valid", "admin")
        dbm.source_session_add(self.conn, "k1", "ad", "web", "v1", "s1")

        dbm.session_delete(self.conn, "s1")

        for table in ("events", "media_assets", "customer_marks", "source_sessions"):
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            self.assertEqual(0, row["n"], table)

    def test_cleanup_old_removes_expired_sessions_and_old_clicks(self):
        dbm.widget_add(self.conn, "k1", 100, "Widget")
        dbm.session_create_if_missing(self.conn, "old", "k1", 100)
        dbm.event_add(self.conn, "old", "customer", text="stale")
        old_ts = int(time.time()) - max(SESSION_TTL_SECONDS, SESSION_IDLE_TTL_SECONDS) - 10
        old_click_ts = int(time.time()) - 91 * 24 * 60 * 60
        self.conn.execute(
            "UPDATE sessions SET created_ts=?, last_activity_ts=? WHERE session_id='old'",
            (old_ts, old_ts),
        )
        self.conn.execute(
            "INSERT INTO source_clicks(key, source_code, channel, visitor_id, clicked_ts) VALUES(?,?,?,?,?)",
            ("k1", "ad", "web", "v1", old_click_ts),
        )
        self.conn.commit()

        dbm.cleanup_old(self.conn, session_ttl_seconds=SESSION_TTL_SECONDS)

        self.assertIsNone(dbm.session_get(self.conn, "old"))
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) AS n FROM source_clicks").fetchone()["n"])

    def test_media_expiration_requires_created_and_expiry_to_be_stale(self):
        dbm.widget_add(self.conn, "k1", 100, "Widget")
        dbm.session_create_if_missing(self.conn, "s1", "k1", 100)
        dbm.media_asset_upsert(self.conn, "s1", "file-1", "photo", "media/a.jpg")
        now = int(time.time())
        self.conn.execute(
            "UPDATE media_assets SET created_ts=?, expires_ts=? WHERE file_id='file-1'",
            (now, now - 10),
        )
        self.conn.commit()

        self.assertEqual([], dbm.media_assets_expired(self.conn, MEDIA_TTL_SECONDS))

    def test_source_click_query_uses_full_index(self):
        plan = self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM source_clicks WHERE key=? AND source_code=?",
            ("k1", "ad"),
        ).fetchall()
        details = " ".join(row["detail"] for row in plan)
        self.assertIn("idx_clicks_full", details)


if __name__ == "__main__":
    unittest.main()
