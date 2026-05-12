import json
import logging
from queue import Empty, Queue

from flask import Blueprint, Response, request, stream_with_context

import db as dbm
from shared.event_payload import event_row_to_payload

from ..db_helpers import enrich_media_payload, get_conn, web_widget_or_error
from ..sse import subscribe, unsubscribe
from ..validators import json_error


logger = logging.getLogger(__name__)

bp = Blueprint("stream", __name__)


@bp.get("/api/stream/<session_id>")
def api_stream(session_id: str):
    session_id = (session_id or "").strip()
    if not session_id or session_id == "undefined":
        return json_error(400, "NO_SESSION")

    try:
        since_id = int(request.args.get("since_id") or "0")
    except Exception:
        since_id = 0

    token = (request.args.get("token") or "").strip()

    conn = get_conn()
    session = dbm.session_get(conn, session_id)
    if session:
        _, error = web_widget_or_error(conn, session.get("key") or "")
        if error:
            return error
        if not dbm.session_verify_stream_token(conn, session_id, token):
            return json_error(401, "BAD_STREAM_TOKEN")
    # session 不存在则允许订阅(首次连接;消息发送后会被自动创建)。

    # 队列上限调小:超过即视为客户端死,broadcast 时会被踢出。
    q: Queue = Queue(maxsize=50)
    subscribe(session_id, q)

    @stream_with_context
    def gen():
        try:
            try:
                conn2 = get_conn()
                missed = dbm.events_since(conn2, session_id, since_id, limit=200)
                for ev in missed:
                    payload = enrich_media_payload(conn2, event_row_to_payload(ev))
                    yield f"event: msg\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            except Exception:
                logger.exception("sse replay error session=%s", session_id)

            while True:
                try:
                    ev = q.get(timeout=30)
                    yield f"event: msg\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except Empty:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            unsubscribe(session_id, q)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )
