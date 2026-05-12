import os
from typing import Any, Dict, Optional

import db as dbm
from config import DB_PATH

from .cleanup import cleanup_expired_once
from .paths import PUBLIC_ROOT
from .validators import json_error


def get_conn():
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
    cleanup_expired_once(conn)
    return conn


def web_widget_or_error(conn, key: str):
    widget = dbm.widget_get(conn, key)
    if not widget:
        return None, json_error(404, "KEY_NOT_FOUND")

    owner_user_id = widget.get("owner_user_id")
    if owner_user_id is None:
        return None, json_error(403, "WEB_DISABLED")

    owner = dbm.user_get(conn, int(owner_user_id))
    if not owner or int(owner.get("enabled") or 0) != 1:
        return None, json_error(403, "WEB_DISABLED")
    if owner.get("role") == dbm.USER_ROLE_NORMAL:
        return None, json_error(403, "WEB_DISABLED")

    return widget, None


def session_key_error(session: Optional[Dict[str, Any]], key: str):
    if session and (session.get("key") or "") != key:
        return json_error(403, "SESSION_KEY_MISMATCH")
    return None


def _media_missing(local_path: str) -> bool:
    rel = (local_path or "").strip().lstrip("/\\")
    if not rel:
        return False
    return not os.path.exists(os.path.join(PUBLIC_ROOT, rel))


def enrich_media_payload(conn, payload: Dict[str, Any]) -> Dict[str, Any]:
    kind = payload.get("kind") or "text"
    if kind in {"photo", "video", "document", "media"} and payload.get("file_id"):
        asset = dbm.media_asset_get_by_file_id(conn, payload["file_id"])
        expired = bool(asset and asset.get("deleted_at"))
        if not expired and asset and _media_missing(asset.get("local_path") or ""):
            expired = True
        payload["media_expired"] = expired
        payload["media_url"] = f"/api/media/{payload['file_id']}"
    elif kind == "note":
        media = payload.get("media") or []
        for item in media:
            file_id = item.get("file_id") or ""
            if not file_id:
                item["media_expired"] = False
                continue
            asset = dbm.media_asset_get_by_file_id(conn, file_id)
            expired = bool(asset and asset.get("deleted_at"))
            if not expired and asset and _media_missing(asset.get("local_path") or ""):
                expired = True
            item["media_expired"] = expired
            item["media_url"] = f"/api/media/{file_id}"
    return payload
