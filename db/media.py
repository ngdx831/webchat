import sqlite3
from datetime import timedelta
from typing import Any, Dict, List, Optional

from .connection import _utc_now, _utc_now_iso, _iso_after


def media_asset_upsert(
    conn: sqlite3.Connection,
    session_id: str,
    file_id: str,
    kind: str,
    local_path: str,
    ttl_seconds: int = 3 * 24 * 60 * 60,
) -> int:
    now = _utc_now_iso()
    expires_at = _iso_after(ttl_seconds)
    conn.execute(
        """
        INSERT INTO media_assets(session_id, file_id, kind, local_path, created_at, expires_at, deleted_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(file_id) DO UPDATE SET
            session_id=excluded.session_id,
            kind=excluded.kind,
            local_path=excluded.local_path,
            expires_at=excluded.expires_at
        """,
        (session_id, file_id, kind or "media", local_path or "", now, expires_at, ""),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM media_assets WHERE file_id=? LIMIT 1", (file_id,)).fetchone()
    return int(row["id"]) if row else 0


def media_asset_get_by_file_id(conn: sqlite3.Connection, file_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute("SELECT * FROM media_assets WHERE file_id=? LIMIT 1", (file_id,)).fetchone()
    return dict(row) if row else None


def media_assets_expired(conn: sqlite3.Connection, media_ttl_seconds: int) -> List[Dict[str, Any]]:
    cutoff = (_utc_now() - timedelta(seconds=int(media_ttl_seconds))).isoformat()
    now = _utc_now_iso()
    rows = conn.execute(
        """
        SELECT * FROM media_assets
        WHERE COALESCE(deleted_at, '')=''
          AND (
            created_at < ?
            OR (COALESCE(expires_at, '')<>'' AND expires_at < ?)
          )
        ORDER BY created_at ASC
        """,
        (cutoff, now),
    ).fetchall()
    return [dict(r) for r in rows]


def media_asset_mark_deleted(conn: sqlite3.Connection, file_id: str) -> None:
    conn.execute("UPDATE media_assets SET deleted_at=? WHERE file_id=?", (_utc_now_iso(), file_id))
    conn.commit()
