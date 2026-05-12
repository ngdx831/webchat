import logging
import secrets
import string
from threading import Lock
from typing import Any, Dict

import requests

import db as dbm
from config import BOT_TOKEN
from shared.errors import TelegramAPIError, scrub_secrets

from .validators import html_escape


logger = logging.getLogger(__name__)


def tg_call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BOT_TOKEN:
        raise TelegramAPIError(0, "BOT_TOKEN_NOT_CONFIGURED", method)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=20)
    except requests.RequestException as e:
        # 注意:不要直接把 e 转字符串放到外层(可能含 URL+token)。
        logger.warning("tg_call network error: method=%s err=%s", method, scrub_secrets(repr(e)))
        raise TelegramAPIError(0, "NETWORK_ERROR", method) from None

    status = r.status_code
    try:
        data = r.json()
    except ValueError:
        logger.warning("tg_call non-json response: method=%s status=%s", method, status)
        raise TelegramAPIError(status, "BAD_RESPONSE", method) from None

    if status >= 400 or not data.get("ok"):
        description = str(data.get("description") or "").strip() or f"HTTP_{status}"
        logger.warning("tg_call api error: method=%s status=%s desc=%s", method, status, scrub_secrets(description))
        raise TelegramAPIError(status, description, method)
    return data


def tg_create_topic(forum_chat_id: int, topic_name: str) -> int:
    data = tg_call("createForumTopic", {"chat_id": forum_chat_id, "name": topic_name})
    return int(data["result"]["message_thread_id"])


def tg_delete_topic(forum_chat_id: int, thread_id: int) -> None:
    payload = {"chat_id": int(forum_chat_id), "message_thread_id": int(thread_id)}
    try:
        tg_call("deleteForumTopic", payload)
    except TelegramAPIError:
        # 删除失败(权限/已删),退化为 close;close 再失败就抛上去。
        tg_call("closeForumTopic", payload)


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
        raise TelegramAPIError(0, "BOT_TOKEN_NOT_CONFIGURED", "getFile")
    data = tg_call("getFile", {"file_id": file_id})
    file_path = data["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


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
    off_line = f"\n离线提示：{html_escape(offline_msg)}" if (int(enabled) == 0 and offline_msg) else ""
    header = (
        f"🔔 <b>新咨询</b>\n"
        f"入口：<b>{html_escape(key)}</b>（{html_escape(display_name)}）\n"
        f"状态：<b>{status_line}</b>{off_line}\n"
        f"会话：<code>{html_escape(session_id)}</code>\n"
        f"——\n"
    )
    tg_send_message(forum_chat_id, int(thread_id), header)


_thread_locks: Dict[str, "Lock"] = {}
_thread_locks_guard = Lock()


def _session_thread_lock(session_id: str) -> "Lock":
    with _thread_locks_guard:
        lock = _thread_locks.get(session_id)
        if lock is None:
            lock = Lock()
            _thread_locks[session_id] = lock
        return lock


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
    串行化:同一 session 同一时刻只有一个调用方在创建话题,避免重复 createForumTopic。
    """
    lock = _session_thread_lock(session_id)
    with lock:
        s = dbm.session_get(conn, session_id) or {}
        thread_id = s.get("thread_id")

        if (not force_new) and thread_id:
            return int(thread_id)

        topic_name = _make_topic_name(display_name, key, enabled)
        thread_id = tg_create_topic(int(forum_chat_id), topic_name)
        try:
            dbm.session_set_thread(conn, session_id, int(thread_id))
        except Exception:
            # 半成功补偿:话题已建但 DB 没记下,主动删除避免泄漏空话题。
            try:
                tg_delete_topic(int(forum_chat_id), int(thread_id))
            except Exception:
                logger.exception("tg_delete_topic compensation failed")
            raise
        try:
            _send_session_header(int(forum_chat_id), int(thread_id), session_id, key, display_name, enabled, offline_msg)
        except TelegramAPIError:
            # header 发送失败不致命,留 log 即可,thread_id 仍然有效。
            logger.warning("session header send failed: session=%s", session_id)
        return int(thread_id)
