import logging
import uuid

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

import db as dbm
from config import MAX_TEXT_LENGTH
from shared.errors import TelegramAPIError
from shared.event_payload import event_row_to_payload

from ..db_helpers import enrich_media_payload, get_conn, session_access_error, session_key_error, web_widget_or_error
from ..rate_limit import allow_rate, client_ip_for_rate_limit
from ..telegram_client import ensure_thread, tg_send_message
from ..validators import (
    html_escape,
    json_error,
    validate_key_api,
    validate_source_code,
)


logger = logging.getLogger(__name__)


bp = Blueprint("messages", __name__)


@bp.post("/api/msg/<key>")
def api_msg(key: str):
    ip = client_ip_for_rate_limit()
    if not allow_rate(ip):
        return json_error(429, "RATE_LIMIT")

    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")

    try:
        data = request.get_json(force=True, silent=False) or {}
    except RequestEntityTooLarge:
        return json_error(413, "REQUEST_TOO_LARGE")
    except Exception:
        return json_error(400, "BAD_JSON")

    text = (data.get("text") or "").strip()[: int(MAX_TEXT_LENGTH)]
    session_id = (data.get("session_id") or "").strip()[:64]
    source_code = validate_source_code(data.get("source_code") or data.get("src") or "")
    visitor_id = (data.get("visitor_id") or "").strip()[:64]

    if not text:
        return json_error(400, "EMPTY_TEXT")

    if not session_id:
        session_id = uuid.uuid4().hex
    if not visitor_id:
        visitor_id = session_id

    conn = get_conn()
    w, error = web_widget_or_error(conn, kk)
    if error:
        return error

    existing_session = dbm.session_get(conn, session_id)
    error = session_key_error(existing_session, kk)
    if error:
        return error
    submitted_token = (
        data.get("token")
        or data.get("session_access_token")
        or data.get("stream_token")
        or ""
    ).strip()
    if existing_session and (existing_session.get("stream_token") or "").strip():
        error = session_access_error(conn, session_id, submitted_token)
        if error:
            return error

    forum_chat_id = int(w["forum_chat_id"])
    display_name = w.get("display_name") or kk
    enabled = int(w.get("enabled") or 0)
    offline_msg = w.get("offline_msg") or ""

    created = dbm.session_create_if_missing(
        conn,
        session_id,
        kk,
        forum_chat_id,
        channel="web",
        source_code=source_code,
        visitor_id=visitor_id,
    )
    if source_code:
        dbm.source_session_add(conn, kk, source_code, "web", visitor_id, session_id)
    if created and source_code:
        dbm.source_click_add(conn, kk, source_code, "web", visitor_id)

    # 记录用户消息事件（始终保存）
    event_id = dbm.event_add(conn, session_id, role="user", kind="text", text=text, file_id="", caption="", from_name="")
    dbm.session_touch(conn, session_id)

    # 首次会话且离线：以客服回复形式写入下班留言
    if created and enabled == 0 and offline_msg:
        dbm.event_add(conn, session_id, role="agent", kind="text", text=offline_msg, from_name=display_name)

    # 创建 TG 话题并转发消息（在线离线均转发）
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
            channel="web",
            source_code=source_code,
            force_new=False,
        )
    body = f"👤 <b>客户</b>：\n{html_escape(text)}"
    try:
        tg_send_message(forum_chat_id, int(thread_id), body)
    except TelegramAPIError:
        try:
            thread_id = ensure_thread(
                conn,
                session_id=session_id,
                forum_chat_id=forum_chat_id,
                key=kk,
                display_name=display_name,
                enabled=enabled,
                offline_msg=offline_msg,
                channel="web",
                source_code=source_code,
                force_new=True,
            )
            tg_send_message(forum_chat_id, int(thread_id), body)
        except TelegramAPIError:
            logger.exception("tg_send_message failed after retry")
            return json_error(502, "TG_SEND_FAILED")

    access_token = dbm.session_get_or_create_access_token(conn, session_id)
    return jsonify({
        "ok": True,
        "session_id": session_id,
        "event_id": event_id,
        "session_access_token": access_token,
        "stream_token": access_token,
    })


@bp.get("/api/history/<key>")
def api_history(key: str):
    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return json_error(400, "NO_SESSION")
    access_token = (request.args.get("token") or request.args.get("session_access_token") or "").strip()

    conn = get_conn()
    w, error = web_widget_or_error(conn, kk)
    if error:
        return error

    s = dbm.session_get(conn, session_id)
    if not s:
        return jsonify({"ok": True, "events": []})
    error = session_key_error(s, kk)
    if error:
        return error
    error = session_access_error(conn, session_id, access_token)
    if error:
        return error

    events = [
        enrich_media_payload(conn, event_row_to_payload(ev), access_token=access_token)
        for ev in dbm.events_list(conn, session_id, limit=dbm.HISTORY_LIMIT)
    ]
    total = dbm.events_count(conn, session_id)
    truncated = total > len(events)
    return jsonify({"ok": True, "events": events, "truncated": truncated})
