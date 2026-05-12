from flask import Blueprint, jsonify, request

from ..rate_limit import internal_notify_allowed
from ..sse import broadcast_event
from ..validators import json_error


bp = Blueprint("internal", __name__)


@bp.post("/internal/notify")
def internal_notify():
    if not internal_notify_allowed():
        return json_error(403, "FORBIDDEN")

    try:
        data = request.get_json(force=True, silent=False) or {}
        session_id = (data.get("session_id") or "").strip()
        event = data.get("event")

        if session_id and event:
            broadcast_event(session_id, event)
            return jsonify({"ok": True})

        return json_error(400, "INVALID_DATA")
    except Exception as e:
        return json_error(500, "NOTIFY_FAILED", {"detail": str(e)})
