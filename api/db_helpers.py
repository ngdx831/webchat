import os
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

import db as dbm
from config import DB_PATH

from .paths import PUBLIC_ROOT
from .validators import json_error


def get_conn():
    conn = dbm.get_conn(DB_PATH)
    dbm.init_db(conn)
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


def session_access_error(conn, session_id: str, token: str):
    if not dbm.session_verify_access_token(conn, session_id, token):
        return json_error(401, "BAD_SESSION_TOKEN")
    return None


def media_proxy_url(file_id: str, session_id: str, access_token: str) -> str:
    file_id = (file_id or "").strip()
    session_id = (session_id or "").strip()
    access_token = (access_token or "").strip()
    if not file_id or not session_id or not access_token:
        return ""
    query = urlencode({"session_id": session_id, "token": access_token})
    return f"/api/media/{quote(file_id, safe='')}?{query}"


def _media_missing(local_path: str) -> bool:
    rel = (local_path or "").strip().lstrip("/\\")
    if not rel:
        return False
    return not os.path.exists(os.path.join(PUBLIC_ROOT, rel))


def enrich_media_payload(conn, payload: Dict[str, Any], access_token: str = "") -> Dict[str, Any]:
    kind = payload.get("kind") or "text"
    session_id = payload.get("session_id") or ""
    if kind in {"photo", "video", "document", "media"} and payload.get("file_id"):
        asset = dbm.media_asset_get_by_file_id(conn, payload["file_id"])
        expired = bool(asset and asset.get("deleted_ts"))
        if not expired and asset and _media_missing(asset.get("local_path") or ""):
            expired = True
        payload["media_expired"] = expired
        url = media_proxy_url(payload["file_id"], session_id, access_token)
        if url:
            payload["media_url"] = url
    elif kind == "note":
        media = payload.get("media") or []
        for item in media:
            file_id = item.get("file_id") or ""
            if not file_id:
                item["media_expired"] = False
                continue
            asset = dbm.media_asset_get_by_file_id(conn, file_id)
            expired = bool(asset and asset.get("deleted_ts"))
            if not expired and asset and _media_missing(asset.get("local_path") or ""):
                expired = True
            item["media_expired"] = expired
            url = media_proxy_url(file_id, session_id, access_token)
            if url:
                item["media_url"] = url
    return payload
