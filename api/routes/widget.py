import uuid

from flask import Blueprint, jsonify, request, send_from_directory

import db as dbm
from config import CUSTOMER_WAITING_HINT

from ..db_helpers import get_conn, web_widget_or_error
from ..paths import PUBLIC_DIR
from ..validators import json_error, validate_key_api, validate_source_code


bp = Blueprint("widget", __name__)


def _wants_widget_page() -> bool:
    if "visitor_id" in request.args:
        return False
    fetch_dest = (request.headers.get("Sec-Fetch-Dest") or "").lower()
    if fetch_dest in {"document", "iframe"}:
        return True
    accept = (request.headers.get("Accept") or "").lower()
    return "text/html" in accept and "application/json" not in accept


def _send_chat_page(kk: str):
    conn = get_conn()
    _, error = web_widget_or_error(conn, kk)
    if error:
        return error
    return send_from_directory(PUBLIC_DIR, "chat.html")


@bp.get("/widget/<key>")
def api_widget(key: str):
    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")
    if _wants_widget_page():
        return _send_chat_page(kk)

    source_code = validate_source_code(request.args.get("src") or request.args.get("source") or "")
    visitor_id = (request.args.get("visitor_id") or "").strip()
    if not visitor_id or visitor_id == "undefined":
        visitor_id = uuid.uuid4().hex

    conn = get_conn()
    w, error = web_widget_or_error(conn, kk)
    if error:
        return error

    if source_code:
        dbm.source_click_add(conn, kk, source_code, "web", visitor_id)

    return jsonify({
        "ok": True,
        "key": kk,
        "display_name": w.get("display_name") or "",
        "visitor_id": visitor_id,
        "source_code": source_code,
        "enabled": int(w.get("enabled") or 0),
        "offline_msg": w.get("offline_msg") or "",
        "offline_at": w.get("offline_at") or "",
        "waiting_hint": CUSTOMER_WAITING_HINT,
        "quick_replies": [
            {
                "id": item["id"],
                "title": item["title"],
                "answer": item["answer"],
            }
            for item in dbm.quick_reply_list(conn, kk)
        ],
    })


@bp.get("/<key>")
def chat_page(key: str):
    kk = validate_key_api(key)
    if not kk:
        return json_error(404, "NOT_FOUND")
    return _send_chat_page(kk)
