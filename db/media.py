import sqlite3
import time
from typing import Any, Dict, List, Optional

from .connection import _ts_after, _utc_now_ts


def media_asset_upsert(
    conn: sqlite3.Connection,
    session_id: str,
    file_id: str,
    kind: str,
    local_path: str,
    ttl_seconds: int = 3 * 24 * 60 * 60,
) -> int:
    now = _utc_now_ts()
    expires_ts = _ts_after(ttl_seconds)
    conn.execute(
        """
        INSERT INTO media_assets(session_id, file_id, kind, local_path, created_ts, expires_ts, deleted_ts)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(file_id) DO UPDATE SET
            session_id=excluded.session_id,
            kind=excluded.kind,
            local_path=excluded.local_path,
            expires_ts=excluded.expires_ts,
            deleted_ts=0
        """,
        (session_id, file_id, kind or "media", local_path or "", now, expires_ts, 0),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM media_assets WHERE file_id=? LIMIT 1", (file_id,)).fetchone()
    return int(row["id"]) if row else 0


def media_asset_get_by_file_id(conn: sqlite3.Connection, file_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM media_assets WHERE file_id=? LIMIT 1", (file_id,)).fetchone()
    return dict(row) if row else None


def media_owner_session_id(conn: sqlite3.Connection, file_id: str) -> Optional[str]:
    file_id = (file_id or "").strip()
    if not file_id:
        return None

    asset = media_asset_get_by_file_id(conn, file_id)
    if asset and asset.get("session_id"):
        return str(asset["session_id"])

    row = conn.execute(
        """
        SELECT session_id FROM events
        WHERE file_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (file_id,),
    ).fetchone()
    if row and row["session_id"]:
        return str(row["session_id"])
    return None


def media_assets_expired(conn: sqlite3.Connection, media_ttl_seconds: int) -> List[Dict[str, Any]]:
    cutoff = int(time.time()) - int(media_ttl_seconds)
    now = _utc_now_ts()
    rows = conn.execute(
        """
        SELECT * FROM media_assets
        WHERE COALESCE(deleted_ts, 0)=0
          AND created_ts < ?
          AND COALESCE(expires_ts, 0)<>0
          AND expires_ts < ?
        ORDER BY created_ts ASC
        """,
        (cutoff, now),
    ).fetchall()
    return [dict(r) for r in rows]


def media_asset_mark_deleted(conn: sqlite3.Connection, file_id: str) -> None:
    conn.execute("UPDATE media_assets SET deleted_ts=? WHERE file_id=?", (_utc_now_ts(), file_id))
    conn.commit()
