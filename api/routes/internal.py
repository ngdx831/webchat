import logging

from flask import Blueprint, jsonify, request

from ..rate_limit import internal_notify_allowed
from ..sse import broadcast_event
from ..validators import json_error


logger = logging.getLogger(__name__)

bp = Blueprint("internal", __name__)


_ALLOWED_EVENT_TYPES = {"msg", "status", "end", "ping"}


@bp.post("/internal/notify")
def internal_notify():
    if not internal_notify_allowed():
        return json_error(401, "UNAUTHORIZED")

    try:
        data = request.get_json(force=True, silent=False) or {}
    except Exception:
        return json_error(400, "BAD_JSON")

    session_id = (data.get("session_id") or "").strip()
    event = data.get("event")

    if not session_id or not isinstance(event, dict):
        return json_error(400, "INVALID_DATA")

    event_type = (event.get("type") or "msg").strip()
    if event_type not in _ALLOWED_EVENT_TYPES:
        return json_error(400, "INVALID_EVENT_TYPE")

    try:
        broadcast_event(session_id, event)
    except Exception:
        logger.exception("broadcast_event failed")
        return json_error(500, "NOTIFY_FAILED")
    return jsonify({"ok": True})
