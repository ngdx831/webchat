import logging
import mimetypes
import os
import secrets
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

import db as dbm
from config import MEDIA_TTL_SECONDS, WEBCHAT_MEDIA_ROOT
from shared.media_paths import media_relative_path

from ..db_helpers import enrich_media_payload, get_conn, session_access_error, session_key_error, web_widget_or_error
from ..rate_limit import allow_rate, client_ip_for_rate_limit
from ..telegram_client import ensure_thread, tg_send_document_file, tg_send_photo_file
from ..validators import json_error, validate_key_api


logger = logging.getLogger(__name__)

bp = Blueprint("upload", __name__)

_ALLOWED_MIME_PREFIXES = ("image/", "video/")
_ALLOWED_MIME_EXACT = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}
_MAX_FILENAME_LEN = 120


def _is_allowed_mime(mime: str) -> bool:
    if not mime:
        return False
    for prefix in _ALLOWED_MIME_PREFIXES:
        if mime.startswith(prefix):
            return True
    return mime in _ALLOWED_MIME_EXACT


def _kind_from_mime(mime: str) -> str:
    if mime.startswith("image/"):
        return "photo"
    if mime.startswith("video/"):
        return "video"
    return "document"


def _ensure_media_dir(ym: str) -> str:
    out_dir = os.path.join(WEBCHAT_MEDIA_ROOT, ym)
    os.makedirs(out_dir, exist_ok=True)
    try:
        os.chmod(out_dir, 0o775)
    except Exception:
        pass
    return out_dir


@bp.post("/api/upload/<key>")
def api_upload(key: str):
    ip = client_ip_for_rate_limit()
    if not allow_rate(ip):
        return json_error(429, "RATE_LIMIT")

    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")

    try:
        session_id = (request.form.get("session_id") or "").strip()[:64]
        visitor_id = (request.form.get("visitor_id") or "").strip()[:64]
        submitted_token = (request.form.get("token") or request.form.get("session_access_token") or "").strip()
        caption = (request.form.get("caption") or "").strip()[:200]
    except RequestEntityTooLarge:
        return json_error(413, "REQUEST_TOO_LARGE")

    if "file" not in request.files:
        return json_error(400, "NO_FILE")

    file = request.files["file"]
    if not file or not file.filename:
        return json_error(400, "NO_FILE")

    original_name = os.path.basename(file.filename)[:_MAX_FILENAME_LEN]
    mime = file.mimetype or (mimetypes.guess_type(original_name)[0] or "application/octet-stream")
    if not _is_allowed_mime(mime):
        return json_error(400, "FILE_TYPE_NOT_ALLOWED")

    if not session_id:
        session_id = uuid.uuid4().hex
    if not visitor_id:
        visitor_id = session_id

    conn = get_conn()
    w, error = web_widget_or_error(conn, kk)
    if error:
        return error

    existing_session = dbm.session_get(conn, session_id)
    err = session_key_error(existing_session, kk)
    if err:
        return err
    if existing_session and (existing_session.get("stream_token") or "").strip():
        err = session_access_error(conn, session_id, submitted_token)
        if err:
            return err

    forum_chat_id = int(w["forum_chat_id"])
    display_name = w.get("display_name") or kk
    enabled = int(w.get("enabled") or 0)
    offline_msg = w.get("offline_msg") or ""

    dbm.session_create_if_missing(conn, session_id, kk, forum_chat_id, channel="web", visitor_id=visitor_id)
    s = dbm.session_get(conn, session_id) or {}
    thread_id = s.get("thread_id")
    if not thread_id:
        thread_id = ensure_thread(
            conn,
            session_id=session_id,
            forum_chat_id=forum_chat_id,
            key=kk,
            display_name=display_name,
            enabled=enabled,
            offline_msg=offline_msg,
            force_new=False,
        )

    # save file locally
    ext = os.path.splitext(original_name)[1] or (mimetypes.guess_extension(mime) or ".bin")
    ext = ext.lower()
    ym = datetime.now().strftime("%Y%m")
    out_dir = _ensure_media_dir(ym)
    unique_id = secrets.token_hex(16)
    fname = f"{unique_id}{ext}"
    abs_path = os.path.join(out_dir, fname)
    try:
        file.save(abs_path)
        try:
            os.chmod(abs_path, 0o664)
        except Exception:
            pass
    except Exception:
        logger.exception("upload save failed: key=%s", kk)
        return json_error(500, "SAVE_FAILED")

    rel_path = media_relative_path(ym, fname)
    kind = _kind_from_mime(mime)

    # record event
    event_id = dbm.event_add(
        conn,
        session_id,
        role="user",
        kind=kind,
        text="",
        file_id=unique_id,
        caption=caption,
        from_name="",
        local_path=rel_path,
        file_name=original_name,
    )
    dbm.media_asset_upsert(conn, session_id, unique_id, kind, rel_path, ttl_seconds=MEDIA_TTL_SECONDS)

    # forward to TG forum thread
    try:
        if kind == "photo":
            tg_send_photo_file(forum_chat_id, int(thread_id), abs_path, caption=caption)
        else:
            tg_send_document_file(forum_chat_id, int(thread_id), abs_path, file_name=original_name, caption=caption)
    except Exception:
        logger.warning("upload tg forward failed: key=%s kind=%s", kk, kind, exc_info=True)

    access_token = dbm.session_get_or_create_access_token(conn, session_id)
    payload = {
        "id": event_id,
        "session_id": session_id,
        "role": "user",
        "kind": kind,
        "file_id": unique_id,
        "file_name": original_name,
        "caption": caption,
        "local_path": rel_path,
    }
    payload = enrich_media_payload(conn, payload, access_token=access_token)

    return jsonify({
        "ok": True,
        "session_id": session_id,
        "event_id": event_id,
        "session_access_token": access_token,
        "stream_token": access_token,
        "event": payload,
    })
