import secrets
import string
from typing import Any, Dict

import requests

import db as dbm
from config import BOT_TOKEN

from .validators import html_escape


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


def tg_delete_topic(forum_chat_id: int, thread_id: int) -> None:
    payload = {"chat_id": int(forum_chat_id), "message_thread_id": int(thread_id)}
    try:
        tg_call("deleteForumTopic", payload)
    except Exception:
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
        raise RuntimeError("BOT_TOKEN not configured")
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
