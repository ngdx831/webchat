import os
import time
import uuid
import json
import re
import secrets
import string
from typing import Any, Dict, Optional
from ipaddress import ip_address
from queue import Queue, Empty
from threading import Lock

import requests
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory

import db as dbm
from event_payload import event_row_to_payload
from session_cleanup import cleanup_expired_media_files, cleanup_expired_sessions
from config import (
    BOT_TOKEN, DB_PATH, API_HOST, API_PORT,
    SESSION_TTL_SECONDS, SESSION_IDLE_TTL_SECONDS, RATE_LIMIT_PER_60S,
    MEDIA_TTL_SECONDS, CUSTOMER_WAITING_HINT,
    WEBCHAT_MEDIA_ROOT,
)

app = Flask(__name__)

KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$")
RESERVED_KEYS = {"api", "assets", "favicon.ico", "health", "internal", "robots.txt", "static", "webchat", "widget"}
SOURCE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

_subscribers: Dict[str, list] = {}
_sub_lock = Lock()
_cleanup_lock = Lock()
_last_cleanup_at = 0.0
CLEANUP_INTERVAL_SECONDS = 60
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")


def _public_root_from_media_root() -> str:
    """从 WEBCHAT_MEDIA_ROOT 推导站点静态根目录（例如 /www/wwwroot/kefu.ws）。"""
    try:
        return os.path.abspath(os.path.join(WEBCHAT_MEDIA_ROOT, os.pardir, os.pardir))
    except Exception:
        return "/www/wwwroot/kefu.ws"


PUBLIC_ROOT = _public_root_from_media_root()


def _html_escape(s: str) -> str:
    s = s or ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def _event_row_to_payload(ev: Dict[str, Any]) -> Dict[str, Any]:
    """把 DB events 行转换成前端统一可渲染的 payload（特别是 note 回放）。"""
    kind = (ev.get("kind") or "text")
    payload: Dict[str, Any] = {
        "id": ev.get("id"),
        "role": ev.get("role"),
        "kind": kind,
        "from_name": ev.get("from_name") or "",

        "text": ev.get("text") or "",
        "caption": ev.get("caption") or "",
        "file_id": ev.get("file_id") or "",
        "file_name": ev.get("file_name") or "",
        "local_path": ev.get("local_path") or "",
    }

    if kind == "note":
        title = "客服笔记"
        body = ""
        raw_text = ev.get("text") or ""
        try:
            obj = json.loads(raw_text) if raw_text else {}
            if isinstance(obj, dict):
                title = (obj.get("title") or title)[:60]
                body = obj.get("body") or ""
            else:
                body = raw_text
        except Exception:
            body = raw_text

        media = []
        raw_mj = ev.get("media_json") or ""
        try:
            arr = json.loads(raw_mj) if raw_mj else []
            if isinstance(arr, list):
                for m in arr:
                    if not isinstance(m, dict):
                        continue
                    media.append({
                        "type": m.get("type") or "photo",
                        "file_id": m.get("file_id") or "",
                        "local_path": m.get("local_path") or "",
                    })
        except Exception:
            pass

        payload.update({
            "title": title,
            "body": body,
            "media": media,
        })

    return payload


def json_error(status: int, code: str, extra: Optional[Dict[str, Any]] = None):
    payload = {"ok": False, "error": code}
    if extra:
        payload.update(extra)
    return jsonify(payload), status


@app.errorhandler(Exception)
def _handle_any_error(e: Exception):
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    return json_error(500, "INTERNAL_ERROR", {"detail": str(e)})


def validate_key_api(k: str) -> Optional[str]:
    k2 = (k or "").strip()
    if not k2:
        return None
    kl = k2.lower()
    if kl in RESERVED_KEYS or kl.startswith("api"):
        return None
    if not KEY_RE.fullmatch(k2):
        return None
    return k2


def validate_source_code(s: str) -> str:
    s2 = (s or "").strip()
    if not s2:
        return ""
    if not SOURCE_RE.fullmatch(s2):
        return ""
    return s2


def _media_missing(local_path: str) -> bool:
    rel = (local_path or "").strip().lstrip("/\\")
    if not rel:
        return False
    return not os.path.exists(os.path.join(PUBLIC_ROOT, rel))


def _enrich_media_payload(conn, payload: Dict[str, Any]) -> Dict[str, Any]:
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


def tg_delete_topic(forum_chat_id: int, thread_id: int) -> None:
    payload = {"chat_id": int(forum_chat_id), "message_thread_id": int(thread_id)}
    try:
        tg_call("deleteForumTopic", payload)
    except Exception:
        tg_call("closeForumTopic", payload)


def cleanup_expired_once(conn) -> None:
    global _last_cleanup_at
    now = time.time()
    if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
        return
    with _cleanup_lock:
        now = time.time()
        if now - _last_cleanup_at < CLEANUP_INTERVAL_SECONDS:
            return
        _last_cleanup_at = now
        results = cleanup_expired_sessions(
            conn,
            public_root=PUBLIC_ROOT,
            delete_topic=tg_delete_topic,
            max_age_seconds=SESSION_TTL_SECONDS,
            idle_seconds=SESSION_IDLE_TTL_SECONDS,
        )
        media_deleted = cleanup_expired_media_files(
            conn,
            public_root=PUBLIC_ROOT,
            media_ttl_seconds=MEDIA_TTL_SECONDS,
        )
        if results:
            deleted = len(results)
            topics = sum(1 for item in results if item.topic_deleted)
            media = sum(item.media_deleted for item in results)
            print(f"Expired sessions cleaned: sessions={deleted}, topics={topics}, media={media}")
        if media_deleted:
            print(f"Expired media cleaned: media={media_deleted}")


def tg_call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not configured")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, json=payload, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"TG_API_ERROR:{data}")
    return data


def tg_create_topic(forum_chat_id: int, topic_name: str) -> int:
    data = tg_call("createForumTopic", {"chat_id": forum_chat_id, "name": topic_name})
    return int(data["result"]["message_thread_id"])


def _rand_topic_tag(n: int = 4) -> str:
    # 方便人工识别：大写字母 + 数字
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(max(2, int(n))))


def _make_topic_name(display_name: str, key: str, enabled: int) -> str:
    """每个会话随机一个名字，避免所有话题都一样。"""
    display_name = (display_name or key or "").strip() or (key or "")
    base = f"{display_name}({key})-{_rand_topic_tag(4)}"
    if int(enabled) == 0:
        base = "【离线】" + base
    return base[:80] if len(base) > 80 else base


def tg_send_message(forum_chat_id: int, thread_id: int, text: str) -> None:
    tg_call("sendMessage", {
        "chat_id": forum_chat_id,
        "message_thread_id": thread_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    })


def tg_get_file_url(file_id: str) -> str:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not configured")
    data = tg_call("getFile", {"file_id": file_id})
    file_path = data["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


def _send_session_header(
    forum_chat_id: int,
    thread_id: int,
    session_id: str,
    key: str,
    display_name: str,
    enabled: int,
    offline_msg: str,
) -> None:
    status_line = "离线留言" if int(enabled) == 0 else "在线咨询"
    off_line = f"\n离线提示：{_html_escape(offline_msg)}" if (int(enabled) == 0 and offline_msg) else ""
    header = (
        f"🔔 <b>新咨询</b>\n"
        f"入口：<b>{_html_escape(key)}</b>（{_html_escape(display_name)}）\n"
        f"状态：<b>{status_line}</b>{off_line}\n"
        f"会话：<code>{_html_escape(session_id)}</code>\n"
        f"——\n"
    )
    tg_send_message(forum_chat_id, int(thread_id), header)


def ensure_thread(
    conn,
    session_id: str,
    forum_chat_id: int,
    key: str,
    display_name: str,
    enabled: int,
    offline_msg: str,
    force_new: bool = False,
) -> int:
    """确保 session 有可用 thread_id。

    force_new=True: 无论原 thread_id 是什么，都新建话题并覆盖（用于话题被手动删除/关闭的情况）。
    """
    s = dbm.session_get(conn, session_id) or {}
    thread_id = s.get("thread_id")

    if (not force_new) and thread_id:
        return int(thread_id)

    topic_name = _make_topic_name(display_name, key, enabled)
    thread_id = tg_create_topic(int(forum_chat_id), topic_name)
    dbm.session_set_thread(conn, session_id, int(thread_id))
    _send_session_header(int(forum_chat_id), int(thread_id), session_id, key, display_name, enabled, offline_msg)
    return int(thread_id)


# ========= Rate limit（非常简单） =========
_rate_bucket: Dict[str, list] = {}


def allow_rate(ip: str) -> bool:
    now = time.time()
    b = _rate_bucket.get(ip, [])
    b = [x for x in b if now - x < 60]
    if len(b) >= RATE_LIMIT_PER_60S:
        _rate_bucket[ip] = b
        return False
    b.append(now)
    _rate_bucket[ip] = b
    return True


def _is_internal_ip(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    try:
        parsed = ip_address(value)
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_private


def _internal_notify_client_ip() -> str:
    remote_addr = (request.remote_addr or "").strip()
    if _is_internal_ip(remote_addr):
        forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        if forwarded_for:
            return forwarded_for
        if real_ip:
            return real_ip
    return remote_addr


def internal_notify_allowed() -> bool:
    return _is_internal_ip(_internal_notify_client_ip())


def broadcast_event(session_id: str, event: Dict[str, Any]) -> None:
    with _sub_lock:
        qs = _subscribers.get(session_id, [])
        for q in qs:
            try:
                q.put_nowait(event)
            except:
                pass


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/widget/<key>")
def api_widget(key: str):
    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")

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


@app.post("/api/msg/<key>")
def api_msg(key: str):
    ip = request.headers.get("X-Real-IP") or request.remote_addr or "0.0.0.0"
    if not allow_rate(ip):
        return json_error(429, "RATE_LIMIT")

    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")

    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        return json_error(400, "BAD_JSON")

    text = (data.get("text") or "").strip()
    session_id = (data.get("session_id") or "").strip()
    source_code = validate_source_code(data.get("source_code") or data.get("src") or "")
    visitor_id = (data.get("visitor_id") or "").strip()

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
    dbm.ensure_system_event(conn, session_id, CUSTOMER_WAITING_HINT, marker="waiting_hint")
    s = dbm.session_get(conn, session_id) or {}
    thread_id = s.get("thread_id")

    # 首条消息：创建话题（话题名带随机尾巴，避免都一样）
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

    # 记录事件（用户）
    dbm.event_add(conn, session_id, role="user", kind="text", text=text, file_id="", caption="", from_name="")

    # 发到 TG（离线时标识一下）
    prefix = "👤 <b>客户（离线留言）</b>：" if enabled == 0 else "👤 <b>客户</b>："
    body = f"{prefix}\n{_html_escape(text)}"

    # ✅ 关键修复：如果管理员手动删除/关闭了话题，但 DB 里还保留旧 thread_id，
    # sendMessage 会报错 -> 这里自动重建话题并重试一次，避免前端收到 INTERNAL_ERROR。
    try:
        tg_send_message(forum_chat_id, int(thread_id), body)
    except Exception:
        try:
            thread_id = ensure_thread(
                conn,
                session_id=session_id,
                forum_chat_id=forum_chat_id,
                key=kk,
                display_name=display_name,
                enabled=enabled,
                offline_msg=offline_msg,
                force_new=True,
            )
            tg_send_message(forum_chat_id, int(thread_id), body)
        except Exception as e2:
            return json_error(502, "TG_SEND_FAILED", {"detail": str(e2)})

    return jsonify({"ok": True, "session_id": session_id})


@app.get("/api/history/<key>")
def api_history(key: str):
    kk = validate_key_api(key)
    if not kk:
        return json_error(400, "BAD_KEY")

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return json_error(400, "NO_SESSION")

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

    events = [_enrich_media_payload(conn, event_row_to_payload(ev)) for ev in dbm.events_list(conn, session_id, limit=200)]
    return jsonify({"ok": True, "events": events})


@app.get("/api/stream/<session_id>")
def api_stream(session_id: str):
    session_id = (session_id or "").strip()
    if not session_id or session_id == "undefined":
        return json_error(400, "NO_SESSION")

    try:
        since_id = int(request.args.get("since_id") or "0")
    except Exception:
        since_id = 0

    conn = get_conn()
    session = dbm.session_get(conn, session_id)
    if session:
        _, error = web_widget_or_error(conn, session.get("key") or "")
        if error:
            return error

    q: Queue = Queue(maxsize=500)

    with _sub_lock:
        _subscribers.setdefault(session_id, []).append(q)

    @stream_with_context
    def gen():
        try:
            conn = get_conn()
            missed = dbm.events_since(conn, session_id, since_id, limit=200)
            for ev in missed:
                payload = _enrich_media_payload(conn, event_row_to_payload(ev))
                yield f"event: msg\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            pass

        try:
            while True:
                try:
                    ev = q.get(timeout=30)
                    yield f"event: msg\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except Empty:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            with _sub_lock:
                if session_id in _subscribers:
                    try:
                        _subscribers[session_id].remove(q)
                    except:
                        pass
                    if not _subscribers[session_id]:
                        _subscribers.pop(session_id, None)

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/media/<file_id>")
def api_media(file_id: str):
    """媒体文件代理接口：优先走本地 local_path，其次才重定向 Telegram。"""
    file_id = (file_id or "").strip()
    if not file_id:
        return json_error(400, "BAD_FILE_ID")

    def expired_placeholder(kind: str = "photo"):
        label = "图片已过期"
        if kind == "video":
            label = "视频已过期"
        elif kind == "document":
            label = "文件已过期"
        safe_label = _html_escape(label)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" fill="#f3f4f6"/>
  <rect x="1" y="1" width="638" height="358" fill="none" stroke="#d1d5db"/>
  <text x="320" y="180" dominant-baseline="middle" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" fill="#6b7280">{safe_label}</text>
</svg>"""
        return Response(svg, mimetype="image/svg+xml", status=410)

    try:
        conn = get_conn()
        asset = dbm.media_asset_get_by_file_id(conn, file_id)
        if asset:
            rel = str(asset.get("local_path") or "").lstrip("/")
            abs_path = os.path.join(PUBLIC_ROOT, rel)
            if asset.get("deleted_at"):
                return expired_placeholder(asset.get("kind") or "photo")
            if rel and os.path.exists(abs_path):
                from flask import redirect
                return redirect("/" + rel)
            dbm.media_asset_mark_deleted(conn, file_id)
            return expired_placeholder(asset.get("kind") or "photo")
    except Exception:
        pass

    # 1) 先查 events.local_path（单媒体消息会写在这里）
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT local_path FROM events WHERE file_id=? AND local_path<>'' ORDER BY id DESC LIMIT 1",
            (file_id,)
        ).fetchone()
        if row and row[0]:
            rel = str(row[0]).lstrip("/")
            abs_path = os.path.join(PUBLIC_ROOT, rel)
            if os.path.exists(abs_path):
                from flask import redirect
                return redirect("/" + rel)
    except Exception:
        pass

    # 2) 再查 events.media_json（note 的媒体在 media_json 里）
    try:
        conn = get_conn()
        pat1 = f'%"file_id":"{file_id}"%'
        pat2 = f'%"file_id": "{file_id}"%'
        rows = conn.execute(
            "SELECT media_json FROM events WHERE media_json LIKE ? OR media_json LIKE ? ORDER BY id DESC LIMIT 10",
            (pat1, pat2)
        ).fetchall()

        for r in rows:
            mj = r[0] or ""
            try:
                arr = json.loads(mj) if mj else []
            except Exception:
                arr = []
            if not isinstance(arr, list):
                continue
            for m in arr:
                if not isinstance(m, dict):
                    continue
                if (m.get("file_id") or "") != file_id:
                    continue
                rel = str(m.get("local_path") or "").lstrip("/")
                if not rel:
                    continue
                abs_path = os.path.join(PUBLIC_ROOT, rel)
                if os.path.exists(abs_path):
                    from flask import redirect
                    return redirect("/" + rel)
    except Exception:
        pass

    # 3) 兜底：重定向 Telegram
    try:
        file_url = tg_get_file_url(file_id)
        from flask import redirect
        return redirect(file_url)
    except Exception as e:
        return json_error(500, "GET_FILE_FAILED", {"detail": str(e)})


@app.get("/<key>")
def chat_page(key: str):
    kk = validate_key_api(key)
    if not kk:
        return json_error(404, "NOT_FOUND")
    conn = get_conn()
    _, error = web_widget_or_error(conn, kk)
    if error:
        return error
    return send_from_directory(PUBLIC_DIR, "chat.html")


@app.post("/internal/notify")
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


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("WARNING: WEBCHAT_BOT_TOKEN not set")
    print(f"Starting API server on {API_HOST}:{API_PORT}")
    app.run(host=API_HOST, port=API_PORT, threaded=True)
